from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from kde_bot import legacy_core as core
from kde_bot.search_round import AccountBusyError, CredentialsError, SearchCoordinator, run_search_round
from kde_bot.storage import Delivery, History, Reporter
from kde_bot.workflow import StructuredDownloader, make_engine_settings
from test_mail_trigger import setup_queue, message


NAME = "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"


def ready_job(queue, name=NAME, entry="one", now=0):
    incoming = message(entry, filenames=[name])
    incoming["received"] = "2026-10-16T10:00:00"
    queue.ingest([incoming], now)
    return queue.claim_ready(now + 60, set())["account-0"][0]


def local_process(catalogues, calls, failure=None):
    def process(engine, account):
        engine.settings.download_delay_seconds = 0
        calls.append((account.username, engine.probe_only))
        if failure:
            failure(engine, account)
        if engine.probe_only:
            return {"downloaded": 0, "skipped": 0}
        engine._table_rows = lambda _page: [(index, {"filename": name}) for index, name in enumerate(catalogues[account.username])]
        engine._has_next_page = lambda _page: False
        def handle(_page, index, row, _account, _timeout):
            calls.append(("save", account.username, row["filename"]))
            for job_id in engine.row_jobs[index]:
                engine.job_statuses.setdefault(job_id, []).append("complete")
                job = next(job for job in engine.jobs if job["id"] == job_id)
                for key, original in job["lookup"].items():
                    if core.has_known_file_extension(key) and engine._match_single_mail_key(core.normalize_filename_for_match(row["filename"]), key, original):
                        engine.required_matches.setdefault(job_id, set()).add(key)
            return "complete"
        engine.handle_file = handle
        return engine._download_visible_pages(None, account, 1000, engine.mail_filename_lookup)
    return process


def test_new_mail_joins_existing_window_and_does_not_add_another_minute(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message("first")], 100)
    queue.ingest([message("second")], 130)
    assert {job["due"] for job in queue.jobs.values()} == {160}
    assert queue.claim_ready(159.99, set()) == {}
    first = queue.claim_ready(160, set())["account-0"][0]
    queue.finish({first["id"]: {"kind": "complete", "reason": "saved"}}, 165)
    assert queue.claim_ready(165, set())["account-0"][0]["attempts"] == 1


def test_missing_waits_for_genuinely_new_mail_then_joins_its_round(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    queue.finish({job["id"]: {"kind": "missing", "reason": "not yet published"}}, 61)
    assert queue.claim_ready(61, set())["account-0"][0]["attempts"] == 2
    queue.finish({job["id"]: {"kind": "missing", "reason": "still missing"}}, 62)
    assert queue.jobs[job["id"]]["status"] == "deferred"
    duplicate = message(filenames=[NAME])
    duplicate["received"] = "2026-10-16T10:00:00"
    assert queue.ingest([duplicate], 100) == 0 and queue.claim_ready(1000, set()) == {}
    queue.ingest([message("new-notification", "post")], 200)
    assert queue.jobs[job["id"]]["due"] == 260 and queue.jobs[job["id"]]["attempts"] == 0
    assert set(queue.claim_ready(260, set())) == {"account-0", "account-1"}


@pytest.mark.parametrize("catalogues,expected_source", [
    ({"account-0": [], "account-1": [NAME]}, "account-1"),
    ({"account-0": [NAME], "account-1": [NAME]}, "account-0"),
])
def test_searches_both_accounts_and_downloads_one_exact_file_once(tmp_path, catalogues, expected_source):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    calls = []
    with patch.object(StructuredDownloader, "process_account", local_process(catalogues, calls)):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert {call[0] for call in calls if len(call) == 2} == {"account-0", "account-1"}
    assert [call for call in calls if call[0] == "save"] == [("save", expected_source, NAME)]
    assert result[job["id"]]["kind"] == "complete"


def test_partial_names_are_checked_for_ambiguity_across_both_sources(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue, "payment online 67097")
    calls = []
    catalogues = {"account-0": [NAME.replace("_16102026", "_Alpha_16102026")],
                  "account-1": [NAME.replace("_16102026", "_Beta_16102026")]}
    with patch.object(StructuredDownloader, "process_account", local_process(catalogues, calls)):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert result[job["id"]]["kind"] == "ambiguous"
    assert not any(call[0] == "save" for call in calls)


def test_unknown_business_side_never_treats_pre_and_post_files_as_equivalent(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    incoming = message(side="", filenames=["payment online 67097"])
    incoming["received"] = "2026-10-16T10:00:00"
    queue.ingest([incoming], 0)
    job = queue.claim_ready(60, set())["account-0"][0]
    assert job["search_any_side"]
    calls = []
    catalogues = {"account-0": [NAME], "account-1": [NAME.replace("A1015_", "A1015L_")]}
    with patch.object(StructuredDownloader, "process_account", local_process(catalogues, calls)):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert result[job["id"]]["kind"] == "ambiguous" and not any(call[0] == "save" for call in calls)


def test_busy_checks_are_unlimited_do_not_consume_budget_or_reopen_free_source(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    calls = []
    def failure(engine, account):
        if account.username == "account-1":
            raise AccountBusyError("Post is in use")
    clock = [60]
    process = local_process({"account-0": [NAME], "account-1": []}, calls, failure)
    with patch("kde_bot.search_round.time.time", side_effect=lambda: clock[0]), \
            patch.object(StructuredDownloader, "process_account", process):
        for cycle in range(4):
            result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
            queue.finish(result, clock[0])
            assert queue.jobs[job["id"]]["attempts"] == 0
            assert queue.jobs[job["id"]]["status"] == "waiting"
            clock[0] += 60
            job = queue.claim_ready(clock[0], set())["account-0"][0]
    assert calls.count(("account-0", False)) == 1
    assert calls.count(("account-1", True)) == 3
    assert not any(call[0] == "save" for call in calls)
    reopened = History(tmp_path / "log_dir")
    assert reopened.data["busy_search_accounts"]["account-1"] == 300


def test_busy_source_becomes_available_then_freshly_searches_both_accounts(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    history.data["busy_search_accounts"] = {"account-1": 60}
    calls = []
    with patch("kde_bot.search_round.time.time", return_value=60), \
            patch.object(StructuredDownloader, "process_account", local_process({"account-0": [], "account-1": [NAME]}, calls)):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert calls[0] == ("account-1", True)
    assert result[job["id"]]["kind"] == "complete" and history.data["busy_search_accounts"] == {}


def test_credentials_error_pauses_instead_of_polling_forever(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    calls = []
    def failure(engine, account):
        if account.username == "account-1":
            raise CredentialsError("Post password rejected")
    with patch.object(StructuredDownloader, "process_account", local_process({"account-0": [NAME], "account-1": []}, calls, failure)):
        first = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
        before = calls.copy()
        second = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert first[job["id"]]["kind"] == second[job["id"]]["kind"] == "credentials"
    assert calls == before and not any(call[0] == "save" for call in calls)


def test_busy_probe_setup_failure_is_a_bounded_failure(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    history.data["busy_search_accounts"] = {"account-1": 60}
    with patch("kde_bot.search_round.time.time", return_value=60), \
            patch("kde_bot.workflow.make_engine_settings", side_effect=OSError("probe setup failed")):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert result[job["id"]]["kind"] == "login_failed"
    assert history.data["busy_search_accounts"] == {}


def test_upgrade_shortens_legacy_five_minute_wait_without_resetting_attempts(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    queue.finish({job["id"]: {"kind": "login_failed", "reason": "legacy failed"}}, 61)
    persisted = queue.jobs[job["id"]]
    persisted.pop("flow_version")
    persisted["due"] = 361
    queue.cooldowns["account-0"] = 361
    queue.recover_interrupted(100)
    assert queue.cooldowns["account-0"] == persisted["due"] == 160
    assert persisted["attempts"] == 1
    assert queue.claim_ready(159, set()) == {}
    assert queue.claim_ready(160, set())["account-0"][0]["attempts"] == 2


def test_source_setup_failure_releases_the_other_waiting_worker(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    original = __import__("kde_bot.workflow", fromlist=["run_account_batch"]).run_account_batch
    calls = []
    def source(*args, source_username, coordinator):
        if source_username == "account-1":
            raise OSError("source setup failed")
        return original(*args, source_username=source_username, coordinator=coordinator)
    with patch("kde_bot.workflow.run_account_batch", side_effect=source), \
            patch.object(StructuredDownloader, "process_account", local_process({"account-0": [NAME]}, calls)):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert result[job["id"]]["kind"] == "download_failed" and not any(call[0] == "save" for call in calls)


def test_session_cleanup_never_forces_out_another_users_account(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    engine = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    account = engine.settings.accounts[0]
    page = Mock()
    with patch.object(engine, "_post_auth", side_effect=AssertionError("account-wide reset")), \
            patch.object(engine, "_browser_auth_post", side_effect=AssertionError("not our session")), \
            patch.object(engine, "_ui_logout", side_effect=AssertionError("not logged in")):
        engine.auto_signout(account)
        engine.signout(account)
        engine._logout_browser_session(page, account, 1000)


def test_busy_login_is_classified_separately_from_invalid_credentials(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    engine = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    def busy(*_args):
        engine.protocol_message("Pre: user ยังใช้งานอยู่")
        raise RuntimeError("login failed")
    with patch.object(core.KdeDownloader, "_login_with_retry", side_effect=busy):
        with pytest.raises(AccountBusyError):
            engine._login_with_retry(Mock(), engine.settings.accounts[0], 1000)
    with patch.object(core.KdeDownloader, "_login_with_retry", side_effect=RuntimeError("invalid password")):
        with pytest.raises(CredentialsError):
            engine._login_with_retry(Mock(), engine.settings.accounts[0], 1000)


def test_stop_releases_a_worker_waiting_for_the_other_catalogue(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    stop = threading.Event()
    coordinator = SearchCoordinator(["account-0", "account-1"], stop)
    engine = Mock()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(coordinator.select, "account-0", engine, [])
        stop.set()
        assert future.result(timeout=2) == ({}, {}, {})
    engine._select_page_mail_matches.assert_not_called()


def test_mail_arriving_during_last_attempt_retries_at_its_existing_window(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    queue.finish({job["id"]: {"kind": "missing", "reason": "first failed"}}, 61)
    queue.claim_ready(61, set())
    queue.ingest([message("next-mail", "post")], 80)
    queue.finish({job["id"]: {"kind": "missing", "reason": "second failed"}}, 100)
    retried = queue.jobs[job["id"]]
    assert retried["status"] == "waiting" and retried["attempts"] == 0 and retried["due"] == 140
    reopened = History(tmp_path / "log_dir")
    resumed = __import__("kde_bot.mail_queue", fromlist=["MailQueue"]).MailQueue(reopened, Reporter(reopened, events.append), settings)
    resumed.recover_interrupted(110)
    assert resumed.jobs[job["id"]]["due"] == 140
    assert resumed.claim_ready(139, set()) == {}
    assert len(resumed.claim_ready(140, set())) == 2


def test_new_email_does_not_reset_a_busy_accounts_existing_cooldown(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    job = ready_job(queue)
    queue.finish({job["id"]: {"kind": "account_busy", "reason": "busy", "sources": ["account-1"], "retry_at": 120}}, 60)
    queue.ingest([message("new", "post")], 90)
    queue.recover_interrupted(100)
    assert queue.jobs[job["id"]]["due"] == 120


def test_unknown_side_can_find_a_unique_post_file_in_either_account(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    incoming = message(side="", filenames=["payment online 67097"])
    incoming["received"] = "2026-10-16T10:00:00"
    queue.ingest([incoming], 0)
    job = queue.claim_ready(60, set())["account-0"][0]
    post_name = NAME.replace("A1015_", "A1015L_")
    calls = []
    with patch.object(StructuredDownloader, "process_account", local_process({"account-0": [post_name], "account-1": []}, calls)):
        result = run_search_round(settings, [job], threading.Event(), reporter, history, tmp_path)
    assert result[job["id"]]["kind"] == "complete"
    assert ("save", "account-0", post_name) in calls
