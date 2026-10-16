from __future__ import annotations

import json
import threading
import queue as queues
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kde_bot import daily_download as daily
from kde_bot import legacy_core as core
from kde_bot.storage import Delivery, History, Reporter
from kde_bot.workflow import make_engine_settings, run_cycle
from test_mail_trigger import configured
from test_outlook_scan import Collection, folder


DAY = "2026-10-16"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "today", lambda: DAY)
    monkeypatch.setenv("KDE_V3_HOME", str(tmp_path / "local"))
    settings = configured(tmp_path)
    settings["mail_delay_seconds"] = 70
    settings["download_delay_seconds"] = 0
    history = History(tmp_path / "log_dir")
    events = []
    reporter = Reporter(history, events.append)
    return settings, history, reporter, events


def arrival(entry="one", day=DAY):
    return {"entry_id": entry, "store_id": "data-store", "received": day + "T08:00:00", "folder": "data\\Inbox"}


@pytest.mark.parametrize("row,expected", [
    ({"file_time": "16/10/2026 12:34", "filename": "ANYTHING.zip"}, DAY),
    ({"file_time": "2026-10-16 12:34", "filename": "OTHER_09102026.zip"}, DAY),
    ({"file_time": "2026-10-16T12:34:00", "filename": "any.zip"}, DAY),
    ({"file_time": "16-10-2569", "filename": "other.zip"}, DAY),
    ({"file_time": "15/10/2026", "filename": "TODAY_16102026.zip"}, "2026-10-15"),
    ({"file_time": "", "filename": "A9999_WHATEVER_16102026.zip"}, DAY),
    ({"file_time": "Loading", "filename": "TODAY_16102026.zip"}, None),
    ({"file_time": "31/02/2026", "filename": "TODAY_16102026.zip"}, None),
    ({"file_time": "", "filename": "unknown.zip"}, None),
])
def test_today_filter_uses_portal_date_without_company_words(row, expected):
    assert daily.portal_day(row) == expected


def test_arrivals_share_70_seconds_and_seen_ids_survive_restart(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    assert queue.ingest([arrival()], 100) == 1
    assert queue.ingest([arrival("two")], 130) == 1
    assert queue.state["pending_due"] == 170
    assert queue.claim(169) == []
    reopened = daily.DailyQueue(History(history.folder), settings)
    reopened.recover(150)
    assert reopened.ingest([arrival(), arrival("two")], 160) == 0
    assert reopened.state["pending_due"] == 170
    jobs = reopened.claim(170)
    assert {job["account"] for job in jobs} == {"account-0", "account-1"}
    assert all(job["attempts"] == 1 for job in jobs)


def test_busy_retry_is_once_and_does_not_reopen_successful_account(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(70)
    queue.finish("account-0", {"kind": "complete", "reason": "saved"}, 71)
    queue.finish("account-1", {"kind": "account_busy", "reason": "occupied"}, 71)
    assert queue.claim(130) == []
    jobs = queue.claim(131)
    assert len(jobs) == 1 and jobs[0]["account"] == "account-1" and jobs[0]["attempts"] == 2
    queue.finish("account-1", {"kind": "account_busy", "reason": "still occupied"}, 132)
    assert queue.claim(10000) == []
    assert queue.state["jobs"]["account-1"]["status"] == "deferred"
    queue.ingest([arrival("new")], 200)
    assert len(queue.claim(270)) == 2


def test_mail_during_active_retry_queues_next_round_at_existing_deadline(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(70)
    queue.ingest([arrival("during")], 80)
    queue.ingest([arrival("later")], 100)
    assert queue.state["pending_due"] == 150
    assert queue.claim(200) == []
    for username in ("account-0", "account-1"):
        queue.finish(username, {"kind": "complete", "reason": "saved"}, 201)
    assert len(queue.claim(201)) == 2
    assert queue.state["pending_due"] is None


def test_midnight_expires_old_sweep_and_does_not_download_old_files(setup, monkeypatch):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(70)
    monkeypatch.setattr(daily, "today", lambda: "2026-10-17")
    queue.roll_day()
    assert queue.claim(10000) == [] and queue.state["seen"] == []
    assert all(job["status"] == "expired" for job in queue.state["jobs"].values())
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    with patch.object(engine, "download_to_cache", side_effect=AssertionError("old date download")):
        assert engine.handle_file(None, 0, {"filename": "old.zip", "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "skipped"


@pytest.mark.parametrize("existing_root", ["original_dir", "new_dir"])
@pytest.mark.parametrize("mode", ["both", "original", "new"])
def test_either_existing_filename_skips_without_filling_other_root(setup, existing_root, mode):
    settings, history, reporter, events = setup
    settings["storage_mode"] = mode
    filename = "Anything.zip"
    (Path(settings[existing_root]) / filename.lower()).write_bytes(b"already saved")
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    with patch.object(engine, "download_to_cache", side_effect=AssertionError("duplicate download")):
        assert engine.handle_file(None, 0, {"filename": filename, "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "skipped"
    other = "original_dir" if existing_root == "new_dir" else "new_dir"
    assert list(Path(settings[other]).iterdir()) == []


def test_two_accounts_download_same_name_once_and_download_unrelated_names(setup, monkeypatch, tmp_path):
    settings, history, reporter, events = setup
    names = {"account-0": ["shared.zip", "unrelated-company-9999.csv", "report.xlsx.gpg", "report.zip.gpg"], "account-1": ["shared.zip", "post.bin"]}
    downloads = []
    def local_process(engine, account):
        rows = [(index, {"filename": name, "file_time": "16/10/2026", "size_text": "1 KB"}) for index, name in enumerate(names[account.username])]
        engine._table_rows = lambda _page: rows
        engine._has_next_page = lambda _page: False
        def download(_page, index, _timeout):
            filename = rows[index][1]["filename"]
            downloads.append(filename)
            source = tmp_path / "local" / "cache" / (account.username + str(index) + ".download")
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(filename.encode())
            return source
        engine.download_to_cache = download
        return engine._download_visible_pages(None, account, 1000)
    jobs = [{"account": account["username"], "label": account["label"], "work_date": DAY, "sequence": 1} for account in settings["accounts"]]
    with patch.object(daily.DailyDownloader, "process_account", local_process):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda job: daily.run_daily_account(settings, job, threading.Event(), reporter, history, tmp_path), jobs))
    assert all(result["kind"] == "complete" for result in results)
    assert sorted(downloads) == ["post.bin", "report.xlsx.gpg", "report.zip.gpg", "shared.zip", "unrelated-company-9999.csv"]
    assert len(history.data["files"]) == 5
    from kde_bot.activity import read_activity
    activity, _latest = read_activity(history.folder, exact_names=True)
    assert {event["filename"] for event in activity if event["status"] == "complete"} == set(downloads)
    for key in ("original_dir", "new_dir"):
        assert {path.name for path in Path(settings[key]).iterdir()} == set(downloads)


def test_scanner_reads_only_metadata_in_data_mailbox_and_optional_folder(setup):
    settings, history, reporter, events = setup
    class MetadataOnly:
        Class = 43
        EntryID = "plain-arrival"
        ReceivedTime = datetime(2026, 10, 16, 10)
        def __getattr__(self, name):
            raise AssertionError("Email contents must not be read: " + name)
    inbox = folder("Inbox", [MetadataOnly()])
    inbox.Folders = Collection([folder("data", [MetadataOnly()])])
    root = folder(settings["mail_watch"]["mailbox_filter"], children=[inbox, folder("Sent Items", [MetadataOnly()]), folder("Notes", [MetadataOnly()], 5)])
    namespace = SimpleNamespace(Folders=Collection([root, folder("other-mailbox", [MetadataOnly()])]))
    with patch.object(core, "win32_client", SimpleNamespace(Dispatch=lambda _name: SimpleNamespace(GetNamespace=lambda _name: namespace))), \
            patch.object(core, "pythoncom", SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        found = daily.scan_arrivals(settings, threading.Event())
        assert len(found) == 2 and all(item["entry_id"] == "plain-arrival" for item in found)
        settings["mail_watch"]["folder_path"] = "Inbox\\data"
        assert len(daily.scan_arrivals(settings, threading.Event())) == 1
        settings["mail_watch"]["folder_path"] = "missing"
        with pytest.raises(RuntimeError, match="folder was not found"):
            daily.scan_arrivals(settings, threading.Event())


def test_credential_error_waits_for_operator_even_if_more_mail_arrives(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(70)
    queue.finish("account-0", {"kind": "credentials", "reason": "bad password"}, 71)
    queue.finish("account-1", {"kind": "complete", "reason": "done"}, 71)
    queue.ingest([arrival("next")], 100)
    assert [job["account"] for job in queue.claim(170)] == ["account-1"]


def test_corrupt_daily_state_is_preserved_and_rejected(setup):
    settings, history, reporter, events = setup
    daily.DailyQueue(history, settings)
    history.data["daily_watch"]["pending_due"] = "broken"
    history.save()
    before = history.path.read_bytes()
    with pytest.raises(ValueError, match="deadline"):
        History(history.folder)
    assert history.path.read_bytes() == before


def test_production_entrypoint_uses_daily_monitor_and_never_legacy_matching(setup):
    settings, history, reporter, events = setup
    with patch("kde_bot.daily_download.run_daily_monitor") as monitor, \
            patch("kde_bot.workflow.run_mail_monitor", side_effect=AssertionError("legacy tracker")), \
            patch("kde_bot.workflow.MailEvidenceReader", side_effect=AssertionError("OCR/content matcher")):
        run_cycle(settings, threading.Event(), events.append, watch=True)
    monitor.assert_called_once()


def test_daily_monitor_waits_70_seconds_and_retries_only_failed_source_once(setup, tmp_path):
    settings, history, reporter, events = setup
    clock = [0.0]
    stop = threading.Event()
    calls = []
    real_wait = stop.wait
    def advance(seconds):
        real_wait(0.001)  # Let the real worker threads complete; no 70-second wall-clock test.
        clock[0] += seconds
        if clock[0] > 300:
            raise AssertionError("Daily monitor did not finish its bounded retries")
        return False
    def work(_settings, job, *_args):
        calls.append((job["account"], job["attempts"], clock[0]))
        if job["account"] == "account-1" and job["attempts"] == 1:
            return {"kind": "account_busy", "reason": "occupied"}
        return {"kind": "complete", "reason": "checked all today files"}
    with patch("kde_bot.daily_download.time.time", side_effect=lambda: clock[0]), \
            patch.object(stop, "wait", side_effect=advance), \
            patch("kde_bot.daily_download.scan_arrivals", return_value=[arrival()]), \
            patch("kde_bot.daily_download.run_daily_account", side_effect=work):
        daily.run_daily_monitor(settings, stop, reporter, history, tmp_path, False, queues.Queue())
    assert len(calls) == 3
    assert all(now >= 70 for _account, _attempt, now in calls)
    assert [(account, attempt) for account, attempt, _now in calls if account == "account-0"] == [("account-0", 1)]
    assert [(account, attempt) for account, attempt, _now in calls if account == "account-1"] == [("account-1", 1), ("account-1", 2)]
    assert next(now for account, attempt, now in calls if attempt == 2) >= 130


def test_existing_files_skip_without_per_file_delay(setup):
    settings, history, reporter, events = setup
    settings["download_delay_seconds"] = 5
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    engine._table_rows = lambda _page: [(0, {"filename": "already.zip", "file_time": "16/10/2026", "size_text": "1 KB"})]
    engine._has_next_page = lambda _page: False
    with patch.object(engine, "handle_file", return_value="skipped"), \
            patch.object(engine.stop_event, "wait", side_effect=AssertionError("Skipped files must not add a delay")):
        assert engine._download_visible_pages(None, engine.settings.accounts[0], 1000)["skipped"] == 1


def test_midnight_during_browser_download_does_not_publish_old_file(setup, monkeypatch, tmp_path):
    settings, history, reporter, events = setup
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    cache = tmp_path / "local" / "cache" / "midnight.download"
    def late_download(*_args):
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"last day payload")
        monkeypatch.setattr(daily, "today", lambda: "2026-10-17")
        return cache
    with patch.object(engine, "download_to_cache", side_effect=late_download):
        assert engine.handle_file(None, 0, {"filename": "late.zip", "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "error"
    assert not cache.exists()
    assert list(Path(settings["original_dir"]).iterdir()) == list(Path(settings["new_dir"]).iterdir()) == []


def test_explicit_repair_reuses_exact_daily_cached_file_without_browser(setup, tmp_path):
    settings, history, reporter, events = setup
    source = tmp_path / "local" / "cache" / "retained.download"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"retained exact-name payload")
    delivery = daily.DailyDelivery(history, reporter)
    account = settings["accounts"][0]["username"]
    name = "report.zip.gpg"
    targets = [Path(settings["original_dir"]), Path(settings["new_dir"])]
    with patch("kde_bot.storage.verified_copy", side_effect=PermissionError("temporary denial")):
        assert delivery.deliver(account, name, targets, lambda _target: source) == "copy_pending"
    saved = next(iter(history.data["files"].values()))
    assert saved["download_policy"] == "daily_all" and source.exists()
    with patch.object(daily.DailyDownloader, "process_account", side_effect=AssertionError("Repair opened KDE")):
        run_cycle(settings, threading.Event(), events.append, retry_only=True)
    assert all((target / name).read_bytes() == b"retained exact-name payload" for target in targets)
    assert not source.exists()
