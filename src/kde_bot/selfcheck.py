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


def check_body_instructions(root: Path) -> None:
    from .evidence import MailEvidenceReader
    from .workflow import StructuredDownloader, make_engine_settings
    from .instructions import instruction_lookup
    from .mail_queue import MailQueue
    settings = default_settings()
    settings["accounts"][0]["username"] = "offline-body-pre"
    settings["accounts"][1]["username"] = "offline-body-post"
    logs = root / "body-logs"
    logs.mkdir()
    history = History(logs)
    reporter = Reporter(history, lambda _event: None)
    engine = StructuredDownloader(make_engine_settings(settings, root / "body.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    cases = [
        (0, "Please download Pre payment online 67097 for company 1015", "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"),
        (1, "A10xxL_SAM_CustomerRequest_JA2_xxxxxx", "A1015L_SAM_CustomerRequest_JA2_16102026.zip.gpg"),
        (1, "A10xxL_SelectACLitigation_LegalType_11_21_31_StopAC", "A1015L_SelectACLitigation_LegalType_11_21_31_StopAC_16102026.zip.gpg"),
        (1, "File Name: A10xxL_SelectACLitigation_LegalType_11_21_31_StopAC_16102026.xlsx.gpg", "A1015L_SelectACLitigation_LegalType_11_21_31_StopAC_16102026.zip.gpg"),
        (0, "File Name: A10XX_Daily_Recovery_Performance_Oct26.zip.gpg", "A1015_Daily_Recovery_Performance_Oct26.zip.gpg"),
    ]
    for index, (account, body, filename) in enumerate(cases):
        evidence = MailEvidenceReader().read(SimpleNamespace(Body=body, Attachments=SimpleNamespace(Count=0)), "Notice", None)
        lookup = evidence["preferred_lookup"]
        engine.jobs = [{"id": str(index), "account": settings["accounts"][account]["username"],
                        "lookup": lookup, "work_date": "2026-10-16"}]
        selected, ambiguous = engine._select_page_mail_matches([
            (0, {"filename": filename, "file_time": "16/10/2026"}),
            (1, {"filename": filename.replace("A1015", "A9999"), "file_time": "16/10/2026"}),
        ], lookup)
        assert set(selected) == {0} and not ambiguous
        if "LegalType" in filename:
            selected, ambiguous = engine._select_page_mail_matches([
                (0, {"filename": filename.replace("_31_", "_32_"), "file_time": "16/10/2026"}),
            ], lookup)
            assert not selected and not ambiguous
    assert instruction_lookup("Keyword 1015") == {}
    evidence = MailEvidenceReader().read(SimpleNamespace(Body="Please download Post Axxxx payment online 67097",
                                                        Attachments=SimpleNamespace(Count=0)), "Pre notification", None)
    queue = MailQueue(history, reporter, settings)
    queue.ingest([{"entry_id": "body-side", "subject": "Pre notification", **evidence,
                   "lookup": evidence["preferred_lookup"]}], 0)
    assert set(queue.claim_ready(120, set())) == {"offline-body-post"}


def check_portal_catalogue(root: Path) -> None:
    """Exercise the real browser pagination selectors against local HTML only."""
    from .legacy_core import sync_playwright_without_console
    from .workflow import StructuredDownloader, make_engine_settings
    from .evidence import today
    from . import legacy_core as core
    settings = default_settings()
    settings["accounts"][0]["username"] = "offline-pre"
    settings["download_delay_seconds"] = 0
    settings["max_pages"] = 2
    logs = root / "catalogue-logs"
    logs.mkdir()
    history = History(logs)
    engine = StructuredDownloader(make_engine_settings(settings, root / "catalogue.json"),
                                  Reporter(history, lambda _event: None),
                                  Delivery(history, Reporter(history, lambda _event: None)), settings, threading.Event())
    names = ["A1015_PAYMENT_ONLINE_67097_Alpha_16102026.zip.gpg", "A1015_PAYMENT_ONLINE_67097_Beta_16102026.zip.gpg"]
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content("""<table><tbody></tbody></table>
                <button id='previous' aria-label='Go to previous page' onclick='window.pageIndex--;render()'>Previous</button>
                <button id='next' aria-label='Go to next page' onclick='window.pageIndex++;render()'>Next</button>
                <script>window.names=""" + json.dumps(names) + """;window.pageIndex=0;
                function render(){document.querySelector('tbody').innerHTML='<tr><td>1</td><td>'+window.names[window.pageIndex]+'</td><td>16/10/2026</td><td>1 MB</td></tr>';
                document.querySelector('#previous').disabled=window.pageIndex===0;
                document.querySelector('#next').disabled=window.pageIndex===1;}render();</script>""")
            broad = {"payment online 67097": "payment online 67097 [Subject key]"}
            job = {"id": "offline-catalogue-job", "account": "offline-pre", "lookup": broad,
                   "received": "2026-10-16T10:00:00", "work_date": "2026-10-16"}
            engine.jobs = [job]
            clicked = []
            with patch.object(engine, "handle_file", side_effect=lambda _page, _index, row, _account, _timeout: clicked.append(row["filename"]) or "complete"):
                result = engine._download_visible_pages(page, engine.settings.accounts[0], 5000, broad)
                assert result["downloaded"] == 0 and clicked == []
                page.evaluate("window.pageIndex=0;render()")
                job["lookup"] = {core.normalize_filename_for_match(names[0]): names[0] + " [Image OCR]", **broad}
                result = engine._download_visible_pages(page, engine.settings.accounts[0], 5000, job["lookup"])
                assert result["downloaded"] == 1 and clicked == [names[0]]
        finally:
            browser.close()


def check_agent_features(root: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from .evidence import LocalOCR, MailEvidenceReader, reference_lookup, today
    from .mail_queue import MailQueue
    from .settings import settings_home
    from .storage import file_hash
    image_path = root / "ocr-reference.png"
    image = Image.new("RGB", (1600, 240), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/arial.ttf"), 36)
    draw.text((30, 30), "PRE PAYMENT ONLINE 67097", font=font, fill="black")
    draw.text((30, 100), "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg", font=font, fill="black")
    image.save(image_path)
    recognized = LocalOCR().read(image_path)
    assert recognized["confidence"] >= 70
    assert "a1015_payment_online_67097_16102026.zip.gpg" in reference_lookup(recognized["text"], "Image OCR")
    screenshot = MailEvidenceReader().screenshot(image_path, "pre")
    assert screenshot["lookup"] and not screenshot["review"]
    settings = default_settings()
    settings["accounts"][0].update(username="offline-pre", password="offline-only")
    settings["accounts"][1].update(username="offline-post", password="offline-only")
    logs = root / "agent-logs"
    logs.mkdir()
    history = History(logs)
    reporter = Reporter(history, lambda _event: None)
    queue = MailQueue(history, reporter, settings, today())
    queue.ingest([screenshot, {**screenshot, "entry_id": "second-request"}], 1000)
    assert queue.claim_ready(1119, set()) == {}
    first = queue.claim_ready(1120, set())["offline-pre"]
    assert len(first) == 1 and queue.claim_ready(1121, set()) == {}
    queue.finish({first[0]["id"]: {"kind": "login_failed", "reason": "offline busy user"}}, 1122)
    assert queue.claim_ready(1421, set()) == {}
    assert queue.claim_ready(1422, set())["offline-pre"][0]["id"] == first[0]["id"]
    queue.finish({first[0]["id"]: {"kind": "complete", "reason": "offline success"}}, 1423)
    assert queue.claim_ready(1423, set())["offline-pre"][0]["id"] != first[0]["id"]
    cache = settings_home() / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    source = cache / "packaged-source.download"
    source.write_bytes(b"packaged final-filename-only delivery")
    target = root / "final-only"
    target.mkdir()
    delivery = Delivery(history, reporter)
    assert delivery.deliver("offline-pre", "business.gpg", [target], lambda _path: source) == "complete"
    assert {path.name for path in target.iterdir()} == {"business.gpg"}
    assert (target / "business.gpg").read_bytes() == b"packaged final-filename-only delivery"
    assert not source.exists()


def check_destination_preflight(root: Path) -> None:
    """Run the real preflight while denying all writes in business destinations."""
    from .workflow import run_cycle

    settings = default_settings()
    destinations = set()
    for key in ("original_dir", "new_dir", "log_dir"):
        folder = root / ("preflight-" + key)
        folder.mkdir()
        settings[key] = str(folder)
        if key != "log_dir":
            destinations.add(folder)
            (folder / "business-file.gpg").write_bytes(b"offline existing file")
    original_open = Path.open
    attempted_writes = []

    def guarded_open(path: Path, mode="r", *args, **kwargs):
        if path.parent in destinations and any(flag in mode for flag in ("w", "a", "x", "+")):
            attempted_writes.append(path)
            raise AssertionError(f"Permission probe attempted to write in destination: {path}")
        return original_open(path, mode, *args, **kwargs)

    events = []
    with patch.object(Path, "open", guarded_open):
        run_cycle(settings, threading.Event(), events.append, retry_only=True)
    assert attempted_writes == []
    for folder in destinations:
        assert {path.name for path in folder.iterdir()} == {"business-file.gpg"}
        assert (folder / "business-file.gpg").read_bytes() == b"offline existing file"
    assert any("save access is checked during real delivery" in event["reason"] for event in events)


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
    settings["mail_watch"]["unread_only"] = True
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
                assert mail_queue.claim_ready(1119, set()) == {}
                batch = mail_queue.claim_ready(1120, set())["offline-user"]
                job_id = batch[0]["id"]
                mail_queue.finish({job_id: {"kind": "login_failed", "reason": "offline failure"}}, 1181)
                assert mail_queue.claim_ready(1480, set()) == {}
                assert mail_queue.claim_ready(1481, set())["offline-user"][0]["attempts"] == 2
                mail_queue.finish({job_id: {"kind": "missing", "reason": "offline missing file"}}, 1482)
                assert mail_queue.claim_ready(9999, set()) == {}
            result["checks"].append("Packaged durable mail queue: no idle session; 120-second delay; 300-second cooldown; two attempts total")
            check_outlook_folder_filter(root)
            result["checks"].append("Packaged Outlook scanner: skip Notes, scan mail children, recover rejected UnRead filter, ignore read/non-mail items; fake COM only")
            check_flat_storage(root)
            result["checks"].append("Two concurrent accounts store verified files directly in shared destination roots; legacy account subfolders ignored in all three modes")
            check_destination_preflight(root)
            result["checks"].append("Destination preflight creates no probe files and succeeds with business-folder writes denied; existing files preserved; Log probe retained")
            check_agent_features(root)
            result["checks"].append("Actual bundled English/Thai OCR reads a sample screenshot; strict FIFO, two-minute delay, busy-user retry and final-filename-only publication passed offline")
            check_portal_catalogue(root)
            result["checks"].append("Actual offline browser: previous/next pagination, cross-page ambiguity rejection and precise-reference precedence before any click")
            check_body_instructions(root)
            result["checks"].append("Body instructions: 1015 fallback, generic account templates, unknown-date placeholders, legal-type numbers and monthly filenames; foreign company and company-only references rejected")
        result["status"] = "passed"
        exit_code = 0
    except Exception as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code
