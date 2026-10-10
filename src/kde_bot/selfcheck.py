"""Offline checks executed by the real packaged EXE, with isolated temporary data."""

from __future__ import annotations

import json
import asyncio
import os
import tempfile
import threading
from datetime import datetime
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from .settings import atomic_json, default_settings, load_settings, save_settings
from .storage import Delivery, History, Reporter, WorkerLock


def check_flat_storage(root: Path) -> None:
    """Exercise both account deliveries without creating account subdirectories."""
    from .workflow import selected_folders

    settings = default_settings()
    for key in ("original_dir", "new_dir", "log_dir"):
        folder = root / ("flat-" + key)
        folder.mkdir()
        settings[key] = str(folder)
    for account in settings["accounts"]:
        account["original_dir"] = str(Path(settings["original_dir"]) / account["label"])
    history = History(Path(settings["log_dir"]))
    reporter = Reporter(history, lambda _event: None)
    barrier = threading.Barrier(2)
    downloads = []

    def deliver(index: int) -> str:
        def download(path: Path) -> Path:
            barrier.wait(timeout=30)
            path.write_bytes(f"offline account {index}".encode("utf-8"))
            downloads.append(path)
            return path

        account = settings["accounts"][index]
        return Delivery(history, reporter).deliver(
            f"flat-user-{index}", f"flat-file-{index}.gpg",
            selected_folders(settings, account), download,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(deliver, range(2))) == ["complete", "complete"]
    assert len(downloads) == 2
    for key in ("original_dir", "new_dir"):
        folder = Path(settings[key])
        assert {path.name for path in folder.iterdir()} == {"flat-file-0.gpg", "flat-file-1.gpg"}
        assert all(path.is_file() for path in folder.iterdir())
        for index in range(2):
            assert (folder / f"flat-file-{index}.gpg").read_bytes() == f"offline account {index}".encode("utf-8")
    for mode, keys in (("original", ["original_dir"]), ("new", ["new_dir"]),
                       ("both", ["original_dir", "new_dir"])):
        settings["storage_mode"] = mode
        for account in settings["accounts"]:
            assert selected_folders(settings, account) == [Path(settings[key]) for key in keys]


def check_outlook_folder_filter(root: Path) -> None:
    """Use fake COM folders to verify the deployed scanner without reading real mail."""
    from . import legacy_core as core
    from .workflow import StructuredDownloader, make_engine_settings

    class Items:
        def __init__(self, values=(), reject_filter=False):
            self.values = list(values)
            self.reject_filter = reject_filter
            self.restrict_calls = 0

        @property
        def Count(self):
            return len(self.values)

        def Item(self, index):
            return self.values[index - 1]

        def Restrict(self, _clause):
            self.restrict_calls += 1
            if self.reject_filter:
                raise RuntimeError("Microsoft Outlook: Condition is not valid; filter failed")
            return Items([item for item in self.values if getattr(item, "UnRead", False)])

        def Sort(self, *_args):
            pass

    def message(entry_id, unread, item_class=43):
        return SimpleNamespace(EntryID=entry_id, UnRead=unread, Class=item_class,
                               ReceivedTime=datetime.now(), Subject="A1015_TEST_10102026.zip.gpg",
                               Body="", Attachments=Items())

    unread = message("offline-unread", True)
    read = message("offline-read", False)
    inbox = SimpleNamespace(Name="Inbox", DefaultItemType=0, StoreID="offline-store",
                            Items=Items([unread, read, message("offline-note", True, 44)], True), Folders=Items())
    notes = SimpleNamespace(Name="บันทึกย่อ", DefaultItemType=5,
                            Items=Items([message("ignored-note", True, 44)], True), Folders=Items([inbox]))
    mailbox = SimpleNamespace(Name="data@tradeconnection.co.th", DefaultItemType=0,
                              Items=Items(), Folders=Items([notes]))
    outlook = SimpleNamespace(GetNamespace=lambda _name: SimpleNamespace(Folders=Items([mailbox])))
    settings = default_settings()
    logs = root / "outlook-filter-check"
    logs.mkdir()
    history = History(logs)
    events = []
    reporter = Reporter(history, events.append)
    scanner = StructuredDownloader(make_engine_settings(settings, root / "scan-state.json"),
                                   reporter, Delivery(history, reporter), settings, threading.Event())
    with patch.object(core, "win32_client", SimpleNamespace(Dispatch=lambda _name: outlook)), \
            patch.object(core, "pythoncom", SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        for _ in range(2):
            assert scanner.scan_mail_filenames()
            assert [mail["entry_id"] for mail in scanner.mail_messages] == ["offline-unread"]
    assert notes.Items.restrict_calls == 0
    assert scanner.mail_failures == []
    assert len(events) == 1 and events[0]["status"] == "notice"
    assert unread.UnRead is True and read.UnRead is False


def run_self_check(output: Path) -> int:
    result = {"checks": [], "live_portal_access": False, "business_files_modified": False}
    try:
        with tempfile.TemporaryDirectory(prefix="kde-v3-exe-check-") as temporary:
            root = Path(temporary)
            os.environ["KDE_V3_HOME"] = str(root / "local")
            settings = default_settings()
            settings["accounts"][0]["password"] = "offline-test-credential"
            settings["accounts"][1]["enabled"] = False
            save_settings(settings)
            saved_text = (root / "local/settings.json").read_text(encoding="utf-8")
            assert "offline-test-credential" not in saved_text
            loaded, _ = load_settings()
            assert loaded["accounts"][0]["password"] == "offline-test-credential"
            result["checks"].append("DPAPI local roundtrip; password absent from JSON")
            damaged = default_settings()
            damaged["accounts"][0]["password"] = {"$dpapi": "invalid-base64"}
            damaged["accounts"][0]["username"] = "offline-user"
            atomic_json(root / "foreign.json", damaged)
            recovered, notices = load_settings(root / "foreign.json")
            assert recovered["accounts"][0]["password"] == ""
            assert recovered["accounts"][0]["username"] == "offline-user" and notices
            result["checks"].append("Foreign credentials recover without preventing Settings")
            first = root / "original"
            second = root / "new"
            logs = root / "logs"
            for folder in (first, second, logs):
                folder.mkdir()
            with WorkerLock(logs):
                history = History(logs)
                reporter = Reporter(history, lambda _event: None)
                delivery = Delivery(history, reporter)
                downloads = []

                def download(path: Path) -> Path:
                    downloads.append(str(path))
                    path.write_bytes(b"offline package delivery check")
                    return path

                with patch("kde_bot.storage.verified_copy", side_effect=PermissionError("simulated access denied")):
                    assert delivery.deliver("offline-user", "A1015_TEST_09102026.zip.gpg",
                                            [first, second], download) == "copy_pending"
                assert delivery.deliver("offline-user", "A1015_TEST_09102026.zip.gpg",
                                        [first, second], download) == "complete"
                assert len(downloads) == 1
                assert delivery.deliver("offline-user", "A1015_TEST_09102026.zip.gpg",
                                        [first, second], download) == "skipped"
                assert len(downloads) == 1
                result["checks"].append("Partial copy retry and duplicate verification without redownload")
                try:
                    with WorkerLock(logs):
                        raise AssertionError("Second worker obtained an active lock")
                except RuntimeError:
                    result["checks"].append("Exclusive worker lock")
            from .workflow import StructuredDownloader, make_engine_settings
            engine = StructuredDownloader(
                make_engine_settings(settings, root / "temporary-engine.json"),
                reporter, delivery, settings, threading.Event(),
            )
            from .legacy_core import sync_playwright_without_console
            barrier = threading.Barrier(2)
            original_subprocess_factory = asyncio.create_subprocess_exec

            def browser_worker(index):
                with sync_playwright_without_console(lambda _message: None) as playwright:
                    browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
                    try:
                        context = browser.new_context()
                        context.add_cookies([{"name": "account", "value": str(index),
                                             "domain": "example.test", "path": "/"}])
                        page = context.new_page()
                        page.set_content("<html><body><h1>KDE offline browser check</h1></body></html>")
                        barrier.wait(timeout=30)
                        assert page.locator("h1").inner_text() == "KDE offline browser check"
                        assert context.cookies()[0]["value"] == str(index)
                        context.close()
                        return index
                    finally:
                        browser.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert list(pool.map(browser_worker, range(2))) == [0, 1]
            assert asyncio.create_subprocess_exec is original_subprocess_factory
            result["checks"].append("Two concurrent packaged browser processes with isolated account cookies; offline")
            from .mail_queue import MailQueue
            with WorkerLock(logs):
                history = History(logs)
                reporter = Reporter(history, lambda _event: None)
                settings["accounts"][0]["username"] = "offline-user"
                mail_queue = MailQueue(history, reporter, settings)
                message = {"entry_id": "offline-message", "store_id": "offline-store", "subject": "Pre",
                           "lookup": {"payment online 67097": "payment online 67097"}}
                assert mail_queue.claim_ready(0, set()) == {}
                mail_queue.ingest([message], 1000)
                assert mail_queue.claim_ready(1179, set()) == {}
                batch = mail_queue.claim_ready(1180, set())["offline-user"]
                job_id = batch[0]["id"]
                mail_queue.finish({job_id: {"kind": "login_failed", "reason": "offline failure"}}, 1181)
                assert mail_queue.claim_ready(1480, set()) == {}
                assert mail_queue.claim_ready(1481, set())["offline-user"][0]["attempts"] == 2
                mail_queue.finish({job_id: {"kind": "missing", "reason": "offline missing file"}}, 1482)
                assert mail_queue.claim_ready(9999, set()) == {}
            result["checks"].append("Packaged durable mail queue: no idle session; 180-second delay; 300-second cooldown; two attempts total")
            check_outlook_folder_filter(root)
            result["checks"].append("Packaged Outlook scanner: skip Notes, scan mail children, recover rejected UnRead filter, ignore read/non-mail items; fake COM only")
            check_flat_storage(root)
            result["checks"].append("Two concurrent accounts store verified files directly in shared destination roots; legacy account subfolders ignored in all three modes")
        result["status"] = "passed"
        exit_code = 0
    except Exception as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code
