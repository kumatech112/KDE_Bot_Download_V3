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
    settings["mail_delay_seconds"] = 270
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
    ({"file_time": "", "filename": "A9999_WHATEVER_16102026.zip"}, None),
    ({"file_time": "Loading", "filename": "TODAY_16102026.zip"}, None),
    ({"file_time": "31/02/2026", "filename": "TODAY_16102026.zip"}, None),
    ({"file_time": "", "filename": "unknown.zip"}, None),
])
def test_today_filter_uses_portal_date_without_company_words(row, expected):
    assert daily.portal_day(row) == expected


def test_arrivals_share_270_seconds_and_seen_ids_survive_restart(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    assert queue.ingest([arrival()], 100) == 1
    assert queue.ingest([arrival("two")], 130) == 1
    assert queue.state["pending_due"] == 370
    assert queue.claim(369) == []
    reopened = daily.DailyQueue(History(history.folder), settings)
    reopened.recover(150)
    assert reopened.ingest([arrival(), arrival("two")], 160) == 0
    assert reopened.state["pending_due"] == 370
    jobs = reopened.claim(370)
    assert [job["account"] for job in jobs] == ["account-0"]
    assert all(job["attempts"] == 1 for job in jobs)


def test_busy_retries_every_minute_without_budget_and_preserves_account_order(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    now = 270
    for attempt in range(1, 5):
        jobs = queue.claim(now)
        assert len(jobs) == 1 and jobs[0]["account"] == "account-0" and jobs[0]["attempts"] == attempt
        queue.finish("account-0", {"kind": "account_busy", "reason": "occupied"}, now)
        assert queue.claim(now + 59) == []
        now += 60
    first = queue.claim(now)[0]
    assert first["attempts"] == 5
    queue.finish("account-0", {"kind": "complete", "reason": "saved"}, now + 1)
    second = queue.claim(now + 1)
    assert len(second) == 1 and second[0]["account"] == "account-1"
    queue.finish("account-1", {"kind": "complete", "reason": "saved"}, now + 2)
    assert queue.claim(10000) == []


def test_new_mail_queues_then_success_restores_270_second_delay(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(270)
    queue.ingest([arrival("during")], 280)
    queue.ingest([arrival("later")], 300)
    assert queue.state["pending_due"] == 550
    assert queue.claim(600) == []
    queue.finish("account-0", {"kind": "complete", "reason": "saved"}, 601)
    assert queue.claim(601)[0]["account"] == "account-1"
    queue.finish("account-1", {"kind": "complete", "reason": "saved"}, 602)
    assert queue.state["pending_due"] == 872 and queue.claim(871) == []
    assert len(queue.claim(872)) == 1
    assert queue.state["pending_due"] is None


def test_midnight_expires_old_sweep_and_does_not_download_old_files(setup, monkeypatch):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(270)
    monkeypatch.setattr(daily, "today", lambda: "2026-10-17")
    queue.roll_day()
    assert queue.claim(10000) == [] and queue.state["seen"] == []
    assert all(job["status"] == "expired" for job in queue.state["jobs"].values())
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    with patch.object(engine, "download_to_cache", side_effect=AssertionError("old date download")):
        assert engine.handle_file(None, 0, {"filename": "old.zip", "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "skipped"


@pytest.mark.parametrize("mode", ["both", "original", "new"])
def test_only_97_existing_filename_skips_without_filling_243(setup, mode):
    settings, history, reporter, events = setup
    settings["storage_mode"] = mode
    filename = "Anything.zip"
    (Path(settings["new_dir"]) / filename.lower()).write_bytes(b"already saved")
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    with patch.object(engine, "download_to_cache", side_effect=AssertionError("duplicate download")):
        assert engine.handle_file(None, 0, {"filename": filename, "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "skipped"
    assert list(Path(settings["original_dir"]).iterdir()) == []


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
    with patch.object(daily.DailyDownloader, "process_account", local_process), \
            patch("kde_bot.portal_pages.set_page_size", return_value=True), \
            patch("kde_bot.portal_pages.newest_first"), \
            patch("kde_bot.portal_pages.page_range", return_value=None), \
            patch("kde_bot.portal_pages.next_button", return_value=None):
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


def test_scanner_reads_only_metadata_in_whole_data_mailbox_despite_legacy_folder(setup):
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
        assert len(daily.scan_arrivals(settings, threading.Event())) == 2
        settings["mail_watch"]["folder_path"] = "missing"
        assert len(daily.scan_arrivals(settings, threading.Event())) == 2


def test_inaccessible_folder_and_bad_item_do_not_discard_healthy_arrival(setup):
    settings, history, reporter, events = setup
    class BrokenItems:
        def Sort(self, *_args):
            raise RuntimeError('Folder unavailable')
        @property
        def Count(self):
            raise RuntimeError('Folder unavailable')
    class BadItem:
        @property
        def Class(self):
            raise RuntimeError('Corrupt message')
    broken = folder('Archive')
    broken.Items = BrokenItems()
    inbox = folder('Inbox', [BadItem(), SimpleNamespace(Class=43, EntryID='new-incoming', ReceivedTime=datetime(2026, 10, 16, 14))])
    root = folder(settings['mail_watch']['mailbox_filter'], children=[broken, inbox])
    namespace = SimpleNamespace(Folders=Collection([root]))
    with patch.object(core, 'win32_client', SimpleNamespace(Dispatch=lambda _name: SimpleNamespace(GetNamespace=lambda _name: namespace))), \
            patch.object(core, 'pythoncom', SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        scan = daily.scan_arrivals(settings, threading.Event())
    assert [mail['entry_id'] for mail in scan] == ['new-incoming']
    assert len(scan.warnings) >= 2
    pending = daily.DailyQueue(history, settings)
    assert pending.ingest(scan, 10) == 1 and pending.state['pending_due'] == 280


def test_smtp_account_identifies_mailbox_when_display_name_differs(setup):
    settings, history, reporter, events = setup
    root = folder('Trade Data Mailbox', children=[folder('Inbox', [SimpleNamespace(Class=43, EntryID='smtp-arrival', ReceivedTime=datetime(2026, 10, 16, 14))])])
    account = SimpleNamespace(SmtpAddress=settings['mail_watch']['mailbox_filter'], DeliveryStore=SimpleNamespace(StoreID=root.StoreID))
    namespace = SimpleNamespace(Folders=Collection([root]), Accounts=Collection([account]))
    with patch.object(core, 'win32_client', SimpleNamespace(Dispatch=lambda _name: SimpleNamespace(GetNamespace=lambda _name: namespace))), \
            patch.object(core, 'pythoncom', SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        assert daily.scan_arrivals(settings, threading.Event())[0]['entry_id'] == 'smtp-arrival'


def test_mail_arriving_after_start_flows_from_metadata_to_both_accounts_and_health(setup, tmp_path):
    settings, history, reporter, events = setup
    clock = [0.0]
    stop = threading.Event()
    calls = []
    inbox = folder('Inbox')
    root = folder(settings['mail_watch']['mailbox_filter'], children=[inbox])
    namespace = SimpleNamespace(Folders=Collection([root]))
    real_wait = stop.wait
    def advance(seconds):
        real_wait(0.001)
        clock[0] += seconds
        if clock[0] >= 15 and not inbox.Items.values:
            inbox.Items.values.append(SimpleNamespace(Class=43, EntryID='brand-new', ReceivedTime=datetime(2026, 10, 16, 14)))
        if len(calls) == 2:
            stop.set()
        if clock[0] > 600:
            raise AssertionError('Arrival did not trigger both accounts')
        return stop.is_set()
    def work(_settings, job, *_args):
        calls.append((job['account'], clock[0]))
        return {'kind': 'complete', 'reason': 'Today checked'}
    with patch.object(core, 'win32_client', SimpleNamespace(Dispatch=lambda _name: SimpleNamespace(GetNamespace=lambda _name: namespace))), \
            patch.object(core, 'pythoncom', SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)), \
            patch('kde_bot.daily_download.time.time', side_effect=lambda: clock[0]), \
            patch.object(stop, 'wait', side_effect=advance), \
            patch('kde_bot.daily_download.run_daily_account', side_effect=work):
        daily.run_daily_monitor(settings, stop, reporter, history, tmp_path, True, queues.Queue())
    assert [account for account, _now in calls] == ['account-0', 'account-1']
    assert all(now >= 285 for _account, now in calls)
    health = [event for event in events if event.get('kind') == 'mail_health']
    assert health[0]['count'] == 0 and any(event['new'] == 1 for event in health)
    assert any(event.get('kind') == 'queue' and any(job['id'] == 'pending-daily-round' for job in event['jobs']) for event in events)


def test_credential_error_waits_for_operator_even_if_more_mail_arrives(setup):
    settings, history, reporter, events = setup
    queue = daily.DailyQueue(history, settings)
    queue.ingest([arrival()], 0)
    queue.claim(270)
    queue.finish("account-0", {"kind": "credentials", "reason": "bad password"}, 271)
    assert queue.claim(271)[0]["account"] == "account-1"
    queue.finish("account-1", {"kind": "complete", "reason": "done"}, 272)
    queue.ingest([arrival("next")], 300)
    assert [job["account"] for job in queue.claim(570)] == ["account-1"]


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


def test_daily_monitor_waits_270_seconds_and_never_overlaps_accounts(setup, tmp_path):
    settings, history, reporter, events = setup
    clock = [0.0]
    stop = threading.Event()
    calls = []
    real_wait = stop.wait
    def advance(seconds):
        real_wait(0.001)  # Let the real worker threads complete; no 70-second wall-clock test.
        clock[0] += seconds
        if clock[0] > 700:
            raise AssertionError("Daily monitor did not finish its fixture")
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
    assert all(now >= 270 for _account, _attempt, now in calls)
    assert [(account, attempt) for account, attempt, _now in calls] == [("account-0", 1), ("account-1", 1), ("account-1", 2)]
    assert [(account, attempt) for account, attempt, _now in calls if account == "account-0"] == [("account-0", 1)]
    assert [(account, attempt) for account, attempt, _now in calls if account == "account-1"] == [("account-1", 1), ("account-1", 2)]
    assert next(now for account, attempt, now in calls if attempt == 2) >= 330


def test_existing_files_skip_without_per_file_delay(setup):
    settings, history, reporter, events = setup
    settings["download_delay_seconds"] = 5
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    engine._table_rows = lambda _page: [(0, {"filename": "already.zip", "file_time": "16/10/2026", "size_text": "1 KB"})]
    engine._has_next_page = lambda _page: False
    with patch.object(engine, "handle_file", return_value="skipped"), \
            patch("kde_bot.portal_pages.set_page_size", return_value=True), \
            patch("kde_bot.portal_pages.newest_first"), \
            patch("kde_bot.portal_pages.page_range", return_value=None), \
            patch("kde_bot.portal_pages.next_button", return_value=None), \
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


def test_243_only_presence_does_not_skip_or_reuse_old_content(setup, tmp_path):
    settings, history, reporter, events = setup
    name = "daily-report.zip"
    original = Path(settings["original_dir"]) / name
    original.write_bytes(b"old content in 243")
    source = tmp_path / "local" / "cache" / "fresh.download"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"today content from KDE")
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    with patch.object(engine, "download_to_cache", return_value=source) as download:
        assert engine.handle_file(None, 0, {"filename": name, "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "copy_pending"
    download.assert_called_once()
    assert (Path(settings["new_dir"]) / name).read_bytes() == b"today content from KDE"
    assert original.read_bytes() == b"old content in 243"
    with patch.object(engine, "download_to_cache", side_effect=AssertionError(".97 already has it")):
        assert engine.handle_file(None, 0, {"filename": name, "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "skipped"


def test_new_only_mode_never_reads_or_writes_243_for_tracking(setup, tmp_path, monkeypatch):
    settings, history, reporter, events = setup
    settings["storage_mode"] = "new"
    forbidden = Path(settings["original_dir"])
    original_stat = Path.stat
    def guard(path, *args, **kwargs):
        if path == forbidden or forbidden in path.parents:
            raise AssertionError(".243 used as tracker")
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", guard)
    source = tmp_path / "local" / "cache" / "new.download"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new data")
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    with patch.object(engine, "download_to_cache", return_value=source):
        assert engine.handle_file(None, 0, {"filename": "new.zip", "file_time": "16/10/2026"}, engine.settings.accounts[0], 1000) == "complete"


def test_more_than_two_login_attempts_survive_state_reload(setup):
    settings, history, reporter, events = setup
    pending = daily.DailyQueue(history, settings)
    pending.ingest([arrival()], 0)
    for attempt in range(4):
        now = 270 + 60 * attempt
        assert pending.claim(now)[0]["attempts"] == attempt + 1
        pending.finish("account-0", {"kind": "login_failed", "reason": "unavailable"}, now)
    reopened = daily.DailyQueue(History(history.folder), settings)
    reopened.recover(480)
    assert reopened.claim(509) == []
    assert reopened.claim(510)[0]["attempts"] == 5


def test_download_rechecks_name_date_and_row_position_before_click(setup, tmp_path):
    settings, history, reporter, events = setup
    settings["storage_mode"] = "new"
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / "engine.json"), reporter,
                                   Delivery(history, reporter), settings, threading.Event(), DAY)
    planned = {"filename": "safe.zip", "file_time": "16/10/2026", "size_text": "1 KB"}
    page = object()
    engine._table_rows = lambda _page: [(0, {**planned, "file_time": "15/10/2026"})]
    with patch.object(engine, "download_to_cache", side_effect=AssertionError("Wrong date clicked")):
        assert engine.handle_file(page, 0, planned, engine.settings.accounts[0], 1000) == "error"
    source = tmp_path / "local" / "cache" / "guarded.download"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"verified correct row")
    engine._table_rows = lambda _page: [(4, planned)]
    with patch.object(engine, "download_to_cache", return_value=source) as download:
        assert engine.handle_file(page, 0, planned, engine.settings.accounts[0], 1000) == "complete"
    download.assert_called_once_with(page, 4, 1000)
