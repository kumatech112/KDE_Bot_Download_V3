from __future__ import annotations

import json
import asyncio
import csv
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from kde_bot import legacy_core as core
from kde_bot.mail_queue import MailQueue, message_identity
from kde_bot.settings import default_settings, normalize_settings
from kde_bot.storage import Delivery, History, Reporter
from kde_bot.workflow import StructuredDownloader, make_engine_settings, run_mail_monitor, run_account_batch


def configured(tmp_path):
    settings = default_settings()
    for key in ("log_dir", "original_dir", "new_dir"):
        folder = tmp_path / key
        folder.mkdir(exist_ok=True)
        settings[key] = str(folder)
    for index, account in enumerate(settings["accounts"]):
        account.update(username=f"account-{index}", password="offline-test")
    return settings


def message(entry="one", side="pre", filenames=None):
    filenames = filenames or [f"A1015{'L' if side == 'post' else ''}_TEST_10102026.zip.gpg"]
    return {"entry_id": entry, "store_id": "test-store", "received": "2026-10-10T08:00:00",
            "subject": side, "lookup": {core.normalize_filename_for_match(name): name for name in filenames}}


def setup_queue(tmp_path):
    settings = configured(tmp_path)
    history = History(tmp_path / "log_dir")
    events = []
    reporter = Reporter(history, events.append)
    return settings, history, events, reporter, MailQueue(history, reporter, settings)


def test_new_mail_waits_180_seconds_and_rediscovery_does_not_restart_delay(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    assert queue.ingest([message()], 1000) == 1
    assert queue.ingest([message()], 1100) == 0
    assert queue.claim_ready(1179.99, set()) == {}
    assert queue.claim_ready(1180, set())["account-0"][0]["attempts"] == 1
    assert queue.claim_ready(1181, {"account-0"}) == {}


def test_completion_survives_restart_and_does_not_login_for_same_unread_mail(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 1000)
    job = queue.claim_ready(1180, set())["account-0"][0]
    queue.finish({job["id"]: {"kind": "complete", "reason": "complete"}}, 1182)
    reopened = History(tmp_path / "log_dir")
    restarted = MailQueue(reopened, Reporter(reopened, events.append), settings)
    assert restarted.ingest([message()], 5000) == 0
    assert restarted.claim_ready(10000, set()) == {}


@pytest.mark.parametrize("kind,delay", [("missing", 0), ("download_failed", 0), ("login_failed", 300)])
def test_failure_gets_exactly_two_total_sessions(tmp_path, kind, delay):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 0)
    job = queue.claim_ready(180, set())["account-0"][0]
    queue.finish({job["id"]: {"kind": kind, "reason": "simulated failure"}}, 190)
    if delay:
        assert queue.claim_ready(190 + delay - 0.01, set()) == {}
    retry = queue.claim_ready(190 + delay, set())["account-0"][0]
    assert retry["attempts"] == 2
    queue.finish({retry["id"]: {"kind": kind, "reason": "still failed"}}, 500)
    assert queue.claim_ready(10000, set()) == {}
    assert queue.jobs[job["id"]]["status"] == "exhausted"


def test_login_cooldown_blocks_new_mail_for_same_account(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 0)
    job = queue.claim_ready(180, set())["account-0"][0]
    queue.finish({job["id"]: {"kind": "login_failed", "reason": "blocked"}}, 190)
    queue.ingest([message("new")], 191)
    assert queue.claim_ready(489, set()) == {}
    assert len(queue.claim_ready(490, set())["account-0"]) == 2


def test_copy_failure_never_requests_another_portal_session(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 0)
    job = queue.claim_ready(180, set())["account-0"][0]
    queue.finish({job["id"]: {"kind": "copy_pending", "reason": "access denied"}}, 181)
    assert queue.claim_ready(10000, set()) == {}
    assert not queue.has_pending()


def test_interrupted_session_keeps_budget_and_cooldown(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 0)
    queue.claim_ready(180, set())
    queue.recover_interrupted(200)
    assert queue.claim_ready(499, set()) == {}
    job = queue.claim_ready(500, set())["account-0"][0]
    assert job["attempts"] == 2
    queue.recover_interrupted(501)
    assert queue.claim_ready(10000, set()) == {}


def test_side_routing_and_duplicate_filename_messages_keep_separate_ids(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message("one"), message("two"), message("post", "post")], 0)
    batches = queue.claim_ready(180, set())
    assert len(batches["account-0"]) == 2 and len(batches["account-1"]) == 1
    assert batches["account-0"][0]["id"] != batches["account-0"][1]["id"]


def test_generic_mail_routes_to_both_enabled_accounts(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message(side="", filenames=["payment online 67097"])], 0)
    assert set(queue.claim_ready(180, set())) == {"account-0", "account-1"}


def test_settings_migration_disables_old_portal_timer_policy():
    old = default_settings()
    old.update(busy_wait_seconds=900, loop_wait_seconds=20)
    old["mail_watch"]["enabled"] = False
    migrated = normalize_settings(old)
    assert migrated["mail_watch"]["enabled"]
    assert "busy_wait_seconds" not in migrated and "loop_wait_seconds" not in migrated
    assert migrated["mail_delay_seconds"] == 180 and migrated["max_session_attempts"] == 2


class AcceleratedStop:
    def __init__(self, clock, stop_at=None):
        self.clock = clock
        self.stop_at = stop_at

    def is_set(self):
        return self.stop_at is not None and self.clock[0] >= self.stop_at

    def wait(self, seconds):
        self.clock[0] += seconds
        time.sleep(0.0002)
        if self.clock[0] > 2000:
            raise AssertionError("monitor did not finish")
        return self.is_set()


def test_idle_mail_monitor_never_opens_portal(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    clock = [0.0]

    def scan(scanner):
        scanner.mail_messages = []
        return {}

    with patch("kde_bot.workflow.time.time", side_effect=lambda: clock[0]), \
            patch.object(StructuredDownloader, "scan_mail_filenames", scan), \
            patch("kde_bot.workflow.run_account_batch") as browser:
        run_mail_monitor(settings, AcceleratedStop(clock, 65), reporter, history, tmp_path, True)
        browser.assert_not_called()


def test_monitor_runs_pre_post_concurrently_only_after_mail_delay(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    clock = [0.0]
    barrier = threading.Barrier(2)
    starts = []

    def scan(scanner):
        scanner.mail_messages = [message(), message("post", "post")]
        return {}

    def batch(_settings, jobs, *_args):
        starts.append((jobs[0]["account"], clock[0]))
        barrier.wait(timeout=3)
        return {job["id"]: {"kind": "complete", "reason": "offline"} for job in jobs}

    with patch("kde_bot.workflow.time.time", side_effect=lambda: clock[0]), \
            patch.object(StructuredDownloader, "scan_mail_filenames", scan), \
            patch("kde_bot.workflow.run_account_batch", side_effect=batch):
        run_mail_monitor(settings, AcceleratedStop(clock), reporter, history, tmp_path, False)
    assert len(starts) == 2 and all(start >= 180 for _, start in starts)
    assert all(job["status"] == "complete" for job in queue.jobs.values())


def test_each_failed_login_uses_new_engine_with_single_login_attempt(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 0)
    job = queue.claim_ready(180, set())["account-0"]
    engines = []

    def process(engine, account):
        engines.append(engine)
        assert engine.login_attempts == 1
        raise RuntimeError("simulated login failure")

    with patch.object(StructuredDownloader, "process_account", process):
        first = run_account_batch(settings, job, threading.Event(), reporter, history, tmp_path)
        queue.finish(first, 190)
        retry = queue.claim_ready(490, set())["account-0"]
        second = run_account_batch(settings, retry, threading.Event(), reporter, history, tmp_path)
    assert engines[0] is not engines[1]
    assert next(iter(second.values()))["kind"] == "login_failed"


def test_partially_missing_mail_files_are_not_marked_complete(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    names = ["A1015_TEST_10102026.zip.gpg", "A1015_OTHER_10102026.zip.gpg"]
    queue.ingest([message(filenames=names)], 0)
    jobs = queue.claim_ready(180, set())["account-0"]
    engine = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"),
                                  reporter, Delivery(history, reporter), settings, threading.Event())
    engine.jobs = jobs
    engine.job_statuses[jobs[0]["id"]] = ["complete"]
    engine.required_matches[jobs[0]["id"]] = {core.normalize_filename_for_match(names[0])}
    outcome = engine.job_outcomes()[jobs[0]["id"]]
    assert outcome["kind"] == "missing" and "other" in outcome["reason"]


def test_concurrent_delivery_saves_both_records_without_corrupting_history(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    barrier = threading.Barrier(2)

    def deliver(index):
        def download(path):
            barrier.wait(timeout=3)
            path.write_bytes(f"file-{index}".encode())
            return path
        return Delivery(history, reporter).deliver(f"account-{index}", f"file-{index}.gpg",
            [tmp_path / "original_dir", tmp_path / "new_dir"], download)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(deliver, range(2)))
    assert outcomes == ["complete", "complete"]
    saved = json.loads(history.path.read_text(encoding="utf-8"))
    assert len(saved["files"]) == 2
    assert all(len(record["destinations"]) == 2 for record in saved["files"].values())


def test_equivalent_filenames_from_two_accounts_download_only_once(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    calls = []

    def download(path):
        calls.append(path)
        time.sleep(0.03)
        path.write_bytes(b"same file")
        return path

    def deliver(index):
        return Delivery(history, reporter).deliver(f"account-{index}", "same-file.gpg",
            [tmp_path / "original_dir", tmp_path / "new_dir"], download)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(deliver, range(2)))
    assert sorted(outcomes) == ["complete", "skipped"] and len(calls) == 1


def test_outlook_scan_exposes_duplicate_messages_without_marking_them_read(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)

    class Collection:
        def __init__(self, values):
            self.values = values
            self.Count = len(values)

        def Item(self, index):
            return self.values[index - 1]

        def Restrict(self, _clause):
            return self

        def Sort(self, *_args):
            pass

    mails = [SimpleNamespace(EntryID=str(index), ReceivedTime=datetime.now(), UnRead=True,
                             Subject="A1015_TEST_10102026.zip.gpg", Body="",
                             Attachments=Collection([])) for index in range(2)]
    folder = SimpleNamespace(Name="data@tradeconnection.co.th", StoreID="store",
                             Items=Collection(mails), Folders=Collection([]))
    namespace = SimpleNamespace(Folders=Collection([folder]))
    outlook = SimpleNamespace(GetNamespace=lambda _: namespace)
    scanner = StructuredDownloader(make_engine_settings(settings, tmp_path / "scan.json"),
                                   reporter, Delivery(history, reporter), settings, threading.Event())
    with patch.object(core, "win32_client", SimpleNamespace(Dispatch=lambda _: outlook)), \
            patch.object(core, "pythoncom", SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        lookup = scanner.scan_mail_filenames()
    assert lookup and len(scanner.mail_messages) == 2
    assert scanner.mail_messages[0]["lookup"] == scanner.mail_messages[1]["lookup"]
    assert message_identity(scanner.mail_messages[0]) != message_identity(scanner.mail_messages[1])
    assert all(mail.UnRead for mail in mails)


@pytest.mark.parametrize("failure_stage", ["login", "search", "download"])
def test_logout_and_browser_cleanup_precede_fresh_session_on_failure(tmp_path, failure_stage):
    settings = configured(tmp_path)
    engine = core.KdeDownloader(make_engine_settings(settings, tmp_path / "engine.json"))
    trace = []
    page = SimpleNamespace(url="https://offline.test/login")
    context = SimpleNamespace(new_page=lambda: page, close=lambda: trace.append("context.close"))
    browser = SimpleNamespace(new_context=lambda **_: context, close=lambda: trace.append("browser.close"))
    runtime = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_: browser))

    class Runtime:
        def __enter__(self):
            return runtime

        def __exit__(self, *_args):
            pass

    def fail(*_args):
        raise RuntimeError("simulated failure")

    engine._login_with_retry = fail if failure_stage == "login" else lambda *_: None
    engine._open_download_page = fail if failure_stage == "search" else lambda *_: None
    engine._download_visible_pages = fail
    engine._install_browser_popup_guards = lambda *_: None
    engine._logout_browser_session = lambda *_: trace.append("UI logout")
    engine.signout = lambda *_, **__: trace.append("signOut")
    engine.auto_signout = lambda *_: trace.append("autoSignOut")
    with patch.object(core, "sync_playwright_without_console", return_value=Runtime()):
        with pytest.raises(RuntimeError, match="simulated failure"):
            engine.process_account(engine.settings.accounts[0])
    assert trace == ["UI logout", "signOut", "autoSignOut", "context.close", "browser.close"]


def test_corrupt_mail_queue_fails_without_reset_or_login(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    path = folder / "KDE_State.json"
    text = json.dumps({"version": 3, "files": {}, "outcomes": {}, "mail_jobs": {"broken": {"attempts": -1}}})
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="คิวอีเมล"):
        History(folder)
    assert path.read_text(encoding="utf-8") == text


def test_only_explicit_manual_retry_reopens_exhausted_mail_budget(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message()], 0)
    job = queue.claim_ready(180, set())["account-0"][0]
    queue.finish({job["id"]: {"kind": "missing", "reason": "missing"}}, 181)
    queue.claim_ready(181, set())
    queue.finish({job["id"]: {"kind": "missing", "reason": "missing"}}, 182)
    assert queue.ingest([message()], 1000) == 0
    assert queue.claim_ready(1000, set()) == {}
    assert queue.requeue_failed(1000) == 1
    assert queue.claim_ready(1179, set()) == {}
    retry = queue.claim_ready(1180, set())["account-0"][0]
    assert retry["attempts"] == 1 and retry["total_attempts"] == 3 and retry["cycle"] == 2


def test_overlapping_browser_workers_restore_subprocess_factory_in_either_exit_order():
    original = asyncio.create_subprocess_exec
    second_entered = threading.Event()
    first_finished = threading.Event()
    installed = []

    class Runtime:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            pass

    def first():
        with core.sync_playwright_without_console(lambda _: None):
            installed.append(asyncio.create_subprocess_exec)
            assert second_entered.wait(3)
        first_finished.set()

    def second():
        with core.sync_playwright_without_console(lambda _: None):
            second_entered.set()
            assert first_finished.wait(3)
            assert asyncio.create_subprocess_exec is installed[0]

    with patch.object(core, "sync_playwright", return_value=Runtime()):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(first), pool.submit(second)]
            for future in futures:
                future.result(timeout=5)
    assert asyncio.create_subprocess_exec is original


def test_delivery_index_detects_other_worker_publishing_equivalent_name(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    delivery = Delivery(history, reporter)
    original = tmp_path / "original_dir"
    assert delivery.existing(original, "A1015_TEST_10102026.zip.gpg") is None
    other = original / "A1015_TEST_10102026.7z.gpg"
    other.write_bytes(b"published by other account")
    assert delivery.existing(original, "A1015_TEST_10102026.zip.gpg") == other


def test_recovered_login_error_is_cleared_live_and_in_saved_outcomes(tmp_path):
    from collections import OrderedDict
    from kde_bot.gui import Application
    settings, history, events, reporter, queue = setup_queue(tmp_path)

    class Variable:
        def set(self, _value):
            pass

    app = object.__new__(Application)
    app.settings = settings
    app.rows = OrderedDict()
    app.step_table = SimpleNamespace(item=lambda *_args, **_kwargs: None)
    app.current_step = Variable()
    app.status = Variable()
    app.account_status = [Variable(), Variable()]
    reporter.callback = app.accept_event
    failed = reporter.emit(3, "error", "login temporarily failed", "01 Pre", persist=True)
    assert failed["key"] in app.rows
    reporter.emit(3, "stage_complete", "login succeeded", "01 Pre")
    assert failed["key"] not in app.rows
    assert history.data["outcomes"][failed["key"]]["signature"][1] == "stage_complete"
    with next(history.folder.glob("KDE_Log_*.csv")).open(encoding="utf-8-sig", newline="") as stream:
        assert [row["status"] for row in csv.DictReader(stream)] == ["error", "stage_complete"]
