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


def check_portal_paging(root: Path) -> None:
    """Exercise delayed tables, reverse delivery and failed navigation offline."""
    from .legacy_core import sync_playwright_without_console
    from .workflow import StructuredDownloader, make_engine_settings
    from . import legacy_core as core
    settings = default_settings()
    settings["accounts"][0]["username"] = "offline-paging-pre"
    settings["download_delay_seconds"] = 0
    settings["max_pages"] = 3
    logs = root / "paging-logs"
    logs.mkdir()
    history = History(logs)
    reporter = Reporter(history, lambda _event: None)
    engine = StructuredDownloader(make_engine_settings(settings, root / "paging.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    names = ["A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg", "A1015_TSS_REVIEW_16102026.zip.gpg",
             "A1015_TSS_DOCUMENT_16102026.zip.gpg"]
    lookup = {core.normalize_filename_for_match(name): name for name in names}
    engine.jobs = [{"id": "offline-paging-job", "account": "offline-paging-pre", "lookup": lookup,
                    "received": "2026-10-16T10:00:00", "work_date": "2026-10-16"}]
    pages = [["A1015_FIRST_16102026.zip.gpg"], names[:2], names[2:]]
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            # Every request is fulfilled locally; no production service is contacted.
            page.route("**/*", lambda route: route.fulfill(status=200, body="ok", headers={"access-control-allow-origin": "*"}))
            page.set_content("""<table><tbody></tbody></table>
                <button id='previous' aria-label='Go to previous page' onclick='turn(-1)'>Previous</button>
                <button id='next' aria-label='Go to next page' onclick='turn(1)'>Next</button>
                <script>window.pages=""" + json.dumps(pages) + """;window.pageIndex=0;window.moves=[];window.stall=false;window.polls=0;
                function render(){document.querySelector('tbody').innerHTML=window.pages[window.pageIndex].map((name,index)=>
                '<tr><td>'+(index+1)+'</td><td>'+name+'</td><td>16/10/2026</td><td>1 MB</td></tr>').join('');
                document.querySelector('table').setAttribute('aria-busy','false');
                document.querySelector('#previous').disabled=window.pageIndex===0;
                document.querySelector('#next').disabled=window.pageIndex===2;}
                function turn(delta){if(window.stall)return;window.moves.push(delta>0?'next':'previous');window.pageIndex+=delta;
                document.querySelector('tbody').innerHTML='<tr><td>Loading</td></tr>';setTimeout(render,750);}
                setInterval(()=>{window.polls++;fetch('https://kde-offline.invalid/poll').catch(()=>{});},100);render();</script>""")
            reads = []
            original_rows = engine._table_rows
            def read_rows(current_page):
                reads.append(current_page.evaluate("window.pageIndex"))
                return original_rows(current_page)
            engine._table_rows = read_rows
            clicked = []
            def handle(current_page, row_index, row, _account, _timeout):
                actual = current_page.locator("tbody tr").nth(row_index)
                assert actual.locator("td").nth(1).inner_text() == row["filename"]
                clicked.append(row["filename"])
                actual.evaluate("row => row.remove()")
                return "complete"
            with patch.object(engine, "handle_file", side_effect=handle), \
                    patch.object(engine, "_wait_network", side_effect=AssertionError("Paging must not wait for network idle")):
                result = engine._download_visible_pages(page, engine.settings.accounts[0], 5000, lookup)
            assert result["downloaded"] == 3 and clicked == [names[2], names[0], names[1]]
            assert reads == [0, 1, 2, 2, 1, 1]
            assert page.evaluate("window.moves") == ["next", "next", "previous"]
            assert page.evaluate("window.polls") > 0
            page.evaluate("render();document.querySelector('table').setAttribute('aria-busy','true')")
            assert engine._table_signature(page) == ""
            page.evaluate("document.querySelector('table').setAttribute('aria-busy','false');window.stall=true")
            try:
                engine._next_page(page, 500)
            except RuntimeError as error:
                assert "incomplete catalogue" in str(error)
            else:
                raise AssertionError("Unchanged table was accepted as a new page")
            timer = threading.Timer(0.2, engine.stop_event.set)
            timer.start()
            try:
                assert engine._next_page(page, 5000) is False
            finally:
                timer.join()
        finally:
            browser.close()


def check_joint_search_round(root: Path) -> None:
    """Run both native browser workers and real delivery using local HTML only."""
    from . import legacy_core as core
    from .mail_queue import MailQueue
    from .search_round import run_search_round
    from .workflow import StructuredDownloader

    settings = default_settings()
    settings["accounts"][0].update(username="offline-round-pre", password="offline-only")
    settings["accounts"][1].update(username="offline-round-post", password="offline-only")
    settings["download_delay_seconds"] = 0
    for key in ("original_dir", "new_dir", "log_dir"):
        folder = root / ("round-" + key)
        folder.mkdir()
        settings[key] = str(folder)
    history = History(Path(settings["log_dir"]))
    reporter = Reporter(history, lambda _event: None)
    queue = MailQueue(history, reporter, settings, "2026-10-16")
    filename = "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"
    queue.ingest([{"entry_id": "offline-joint-round", "subject": "Pre", "side": "pre",
                   "received": "2026-10-16T10:00:00", "work_date": "2026-10-16",
                   "lookup": {core.normalize_filename_for_match(filename): filename}}], 1000)
    job = queue.claim_ready(1060, set())["offline-round-pre"][0]
    visited = []
    closed = []
    payload = "offline joint round payload"

    def local_login(engine, _page, account, _timeout):
        engine.session_attempted = True
        engine.session_owned = True
        visited.append(account.username)

    def local_catalogue(engine, page, _timeout):
        engine.stage = 4
        names = [] if engine.source_username.endswith("-pre") else [filename]
        page.set_content("""<table><tbody></tbody></table><script>
            const names=""" + json.dumps(names) + ";const payload=" + json.dumps(payload) + """;
            document.querySelector('tbody').innerHTML=names.map((name,index)=>
            '<tr><td>'+(index+1)+'</td><td>'+name+'</td><td>16/10/2026</td><td>1 MB</td><td><button>Download</button></td></tr>').join('');
            document.querySelectorAll('button').forEach((button,index)=>button.onclick=()=>{
                const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([payload],{type:'application/octet-stream'}));
                link.download=names[index];link.click();});</script>""")

    def local_logout(engine, _page, account, _timeout):
        closed.append(account.username)
        engine.session_owned = False

    with patch.object(StructuredDownloader, "_login_with_retry", local_login), \
            patch.object(StructuredDownloader, "_open_download_page", local_catalogue), \
            patch.object(StructuredDownloader, "_logout_browser_session", local_logout), \
            patch.object(StructuredDownloader, "_post_auth", side_effect=AssertionError("Account-wide reset is forbidden")):
        outcomes = run_search_round(settings, [job], threading.Event(), reporter, history, root)
    assert outcomes[job["id"]]["kind"] == "complete", outcomes
    assert set(visited) == set(closed) == {"offline-round-pre", "offline-round-post"}
    assert len(visited) == len(closed) == 2
    for key in ("original_dir", "new_dir"):
        folder = Path(settings[key])
        assert {path.name for path in folder.iterdir()} == {filename}
        assert (folder / filename).read_text() == payload
    records = list(history.data["files"].values())
    assert len(records) == 1 and records[0]["mail_jobs"] == [job["id"]]


def check_round_timing(root: Path) -> None:
    """Verify durable round deadlines and a busy wait without portal access."""
    from .mail_queue import MailQueue
    settings = default_settings()
    settings["mail_delay_seconds"] = 60  # Historical matcher fixture; not the production daily queue.
    settings["accounts"][0]["username"] = "offline-timing-pre"
    settings["accounts"][1]["username"] = "offline-timing-post"
    logs = root / "round-timing"
    logs.mkdir()
    history = History(logs)
    reporter = Reporter(history, lambda _event: None)
    queue = MailQueue(history, reporter, settings)
    first = {"entry_id": "timing-first", "subject": "Pre", "lookup": {"payment online 67097": "payment online 67097"}}
    queue.ingest([first], 100)
    queue.ingest([{**first, "entry_id": "timing-second"}], 130)
    assert {job["due"] for job in queue.jobs.values()} == {160}
    job = queue.claim_ready(160, set())["offline-timing-pre"][0]
    queue.finish({job["id"]: {"kind": "missing", "reason": "offline missing"}}, 161)
    assert queue.claim_ready(161, set())["offline-timing-pre"][0]["attempts"] == 2
    queue.ingest([{**first, "entry_id": "timing-new-round", "subject": "Post"}], 180)
    queue.finish({job["id"]: {"kind": "missing", "reason": "offline still missing"}}, 200)
    assert queue.jobs[job["id"]]["due"] == 240 and queue.jobs[job["id"]]["attempts"] == 0
    resumed_history = History(logs)
    resumed = MailQueue(resumed_history, Reporter(resumed_history, lambda _event: None), settings)
    resumed.recover_interrupted(210)
    assert resumed.jobs[job["id"]]["due"] == 240
    assert resumed.claim_ready(239, set()) == {}
    batches = resumed.claim_ready(240, set())
    for batch in batches.values():
        for active in batch:
            resumed.finish({active["id"]: {"kind": "account_busy", "reason": "offline busy",
                                           "sources": ["offline-timing-post"], "retry_at": 300}}, 241)
            assert resumed.jobs[active["id"]]["attempts"] == 0
            assert resumed.jobs[active["id"]]["due"] == 300
    resumed.recover_interrupted(250)
    assert resumed.jobs[job["id"]]["due"] == 300


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
    assert queue.claim_ready(1059, set()) == {}
    first = queue.claim_ready(1060, set())["offline-pre"]
    assert len(first) == 1 and queue.claim_ready(1061, set()) == {}
    queue.finish({first[0]["id"]: {"kind": "login_failed", "reason": "offline login failure"}}, 1062)
    assert queue.claim_ready(1121, set()) == {}
    assert queue.claim_ready(1122, set())["offline-pre"][0]["id"] == first[0]["id"]
    queue.finish({first[0]["id"]: {"kind": "complete", "reason": "offline success"}}, 1123)
    assert queue.claim_ready(1123, set())["offline-pre"][0]["id"] != first[0]["id"]
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
    assert any("ตรวจสิทธิ์บันทึกเมื่อดาวน์โหลดจริง" in event["reason"] for event in events)


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


def check_arrival_metadata(root: Path) -> None:
    from . import legacy_core as core
    from .daily_download import scan_arrivals
    from .evidence import BANGKOK

    class Collection:
        def __init__(self, values=()):
            self.values = list(values)
        @property
        def Count(self):
            return len(self.values)
        def Item(self, index):
            return self.values[index - 1]
        def Sort(self, *_args):
            pass

    class Metadata:
        Class = 43
        EntryID = "offline-no-content-mail"
        ReceivedTime = datetime.now(BANGKOK)
        def __getattr__(self, name):
            raise AssertionError("Mail content was accessed: " + name)

    def folder(name, values=(), children=(), kind=0):
        return SimpleNamespace(Name=name, StoreID="offline-data-store", DefaultItemType=kind,
                               Items=Collection(values), Folders=Collection(children))

    settings = default_settings()
    child = folder("data", [Metadata()])
    inbox = folder("Inbox", [Metadata()], [child])
    root_folder = folder(settings["mail_watch"]["mailbox_filter"], children=[inbox, folder("Sent Items", [Metadata()]), folder("Notes", [Metadata()], kind=5)])
    namespace = SimpleNamespace(Folders=Collection([root_folder, folder("unrelated mailbox", [Metadata()])]))
    with patch.object(core, "win32_client", SimpleNamespace(Dispatch=lambda _name: SimpleNamespace(GetNamespace=lambda _name: namespace))), \
            patch.object(core, "pythoncom", SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        assert len(scan_arrivals(settings, threading.Event())) == 2
        settings["mail_watch"]["folder_path"] = "Inbox\\data"
        found = scan_arrivals(settings, threading.Event())
        assert len(found) == 2 and found[0]["entry_id"] == Metadata.EntryID
        root_folder.Name = "Data mailbox display label"
        namespace.Accounts = Collection([SimpleNamespace(SmtpAddress=settings['mail_watch']['mailbox_filter'], DeliveryStore=SimpleNamespace(StoreID=root_folder.StoreID))])
        namespace.Folders.values[1].StoreID = "unrelated-store"
        assert len(scan_arrivals(settings, threading.Event())) == 2


def check_scheduler_missing_task() -> None:
    """Reproduce a real missing-task COM exception in the GUI's thread model."""
    import uuid
    from .cleanup_task import scheduler_error_code

    def lookup():
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            service = win32com.client.Dispatch('Schedule.Service')
            service.Connect()
            try:
                service.GetFolder('\\').GetTask('KDE ReadOnly Missing ' + uuid.uuid4().hex)
            except Exception as error:
                assert scheduler_error_code(error) == 0x80070002, repr(error)
                return
            raise AssertionError('Random verification task unexpectedly exists')
        finally:
            pythoncom.CoUninitialize()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='KDE-task-lookup-check') as pool:
        pool.submit(lookup).result(timeout=30)


def check_daily_cleanup(root: Path) -> None:
    from datetime import timedelta
    from . import cleanup
    from .cleanup_task import task_definition
    from .evidence import BANGKOK
    import win32com.client
    import win32security

    settings = default_settings()
    for key in ('original_dir', 'new_dir', 'log_dir'):
        folder = root / ('cleanup-' + key)
        folder.mkdir()
        settings[key] = str(folder)
    for key in ('original_dir', 'new_dir'):
        folder = Path(settings[key])
        (folder / 'purged.zip').write_bytes(b'offline final file')
        for name in ('03 Check', 'Checked', 'another folder'):
            protected = folder / name
            protected.mkdir()
            (protected / 'keep.zip').write_bytes(b'protected content')
    clock = [datetime.now(BANGKOK).replace(hour=21, minute=59, second=59, microsecond=0)]
    history = History(Path(settings['log_dir']))
    reporter = Reporter(history, lambda _event: None)
    with patch.object(cleanup, 'APPROVED_ROOTS', (settings['original_dir'], settings['new_dir'])), \
            patch.object(cleanup, 'current_time', side_effect=lambda: clock[0]):
        scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
        scheduler.tick(clock[0].timestamp(), False, threading.Event())
        assert (Path(settings['new_dir']) / 'purged.zip').is_file()
        clock[0] = clock[0].replace(hour=22, minute=0, second=0)
        assert scheduler.tick(clock[0].timestamp(), True, threading.Event())
        scheduler.tick(clock[0].timestamp(), False, threading.Event())
        for key in ('original_dir', 'new_dir'):
            folder = Path(settings[key])
            assert not (folder / 'purged.zip').exists()
            assert len(list(folder.glob('*/keep.zip'))) == 3
        restored = History(history.folder)
        assert cleanup.was_cleaned(restored, 'PURGED.ZIP')
        assert cleanup.run_scheduled_cleanup(settings) == 0
        assert not cleanup.request_path(settings).exists()
        # A subsequent night's standalone pass owns the real worker lock, with no GUI.
        headless = Path(settings['new_dir']) / 'headless-only.zip'
        headless.write_bytes(b'headless offline download')
        clock[0] += timedelta(days=1)
        assert cleanup.run_scheduled_cleanup(settings) == 0
        assert not headless.exists() and not cleanup.request_path(settings).exists()
        assert History(history.folder).data['daily_cleanup']['deleted_names'] == ['headless-only.zip']
        assert all(len(list(Path(settings[key]).glob('*/keep.zip'))) == 3 for key in ('original_dir', 'new_dir'))
    # Construct a real Task Scheduler definition in memory; never register or run it.
    service = win32com.client.Dispatch('Schedule.Service')
    service.Connect()
    sid = win32security.ConvertSidToStringSid(win32security.ConvertStringSidToSid('S-1-5-21-1-2-3-1001'))
    definition = task_definition(service, root / 'offline-never-executed.exe', sid, clock[0])
    assert 'T22:00:00+07:00' in definition.Triggers.Item(1).StartBoundary
    assert definition.Principal.LogonType == 3 and definition.Principal.RunLevel == 0
    assert definition.Actions.Item(1).Arguments == '--scheduled-cleanup'
    assert definition.Settings.StartWhenAvailable is False


def check_daily_queue(root: Path) -> None:
    from .daily_download import DailyQueue
    from .evidence import today
    settings = default_settings()
    for index, account in enumerate(settings["accounts"]):
        account["username"] = f"offline-daily-{index}"
    logs = root / "daily-queue"
    logs.mkdir()
    history = History(logs)
    pending = DailyQueue(history, settings)
    mail = {"entry_id": "first", "store_id": "offline", "received": today() + "T08:00:00"}
    assert pending.ingest([mail], 100) == 1
    assert pending.ingest([{**mail, "entry_id": "second"}], 130) == 1
    assert pending.state["pending_due"] == 370 and pending.claim(369) == []
    restarted = DailyQueue(History(logs), settings)
    restarted.recover(150)
    assert restarted.ingest([mail], 160) == 0
    restarted.ingest([{**mail, "entry_id": "during-download"}], 380)
    assert restarted.state["pending_due"] == 370  # Still the original unclaimed trigger window.
    now = 370
    for attempt in range(1, 5):
        jobs = restarted.claim(now)
        assert len(jobs) == 1 and jobs[0]["account"] == "offline-daily-0" and jobs[0]["attempts"] == attempt
        restarted.finish("offline-daily-0", {"kind": "account_busy", "reason": "offline busy"}, now)
        assert restarted.claim(now + 59) == []
        now += 60
    assert restarted.claim(now)[0]["attempts"] == 5
    restarted.ingest([{**mail, "entry_id": "queued-after-login"}], now + 1)
    restarted.finish("offline-daily-0", {"kind": "complete", "reason": "offline saved"}, now + 2)
    second = restarted.claim(now + 2)
    assert len(second) == 1 and second[0]["account"] == "offline-daily-1"
    restarted.finish("offline-daily-1", {"kind": "complete", "reason": "offline saved"}, now + 3)
    assert restarted.state["pending_due"] == now + 273
    assert restarted.claim(now + 272) == []
    assert len(restarted.claim(now + 273)) == 1
    restarted.finish("offline-daily-0", {"kind": "download_failed", "reason": "offline failed file"}, now + 274)
    assert restarted.claim(now + 274)[0]["account"] == "offline-daily-1"
    restarted.finish("offline-daily-1", {"kind": "complete", "reason": "offline saved"}, now + 275)
    assert restarted.claim(10000) == []


def daily_fixture_html(rows, custom_select=False, remove_rows=False):
    """Local paginator fixture matching native and Material-style controls."""
    control = ("<div role='combobox' tabindex='0' onclick=\"document.querySelector('[role=listbox]').hidden=false\">15</div>"
               "<div role='listbox' hidden><div role='option' onclick='resize(30)'>30</div></div>" if custom_select else
               "<select onchange='resize(Number(this.value))'><option>15</option><option>30</option></select>")
    return ("<table><thead><tr><th></th><th>File</th><th aria-sort='none' onclick='sortDates()'>วัน เวลา</th></tr></thead><tbody></tbody></table><div data-kde-pagination>จำนวนแถวต่อ 1 หน้า " + control +
            "<span id='range'></span><button id='first' aria-label='Go to first page' onclick='turn(0)'>First</button>"
            "<button id='next' aria-label='Go to next page' onclick='turn(window.pageIndex+1)'>Next</button></div><script>"
            "window.rows=" + json.dumps(rows) + ";window.removeRows=" + json.dumps(remove_rows) + ";" + r"""
            window.pageIndex=0;window.pageSize=15;window.events=[];
            function dateKey(value){const match=value.match(/(\d{2})\/(\d{2})\/(\d{4})/);return match?match[3]+match[2]+match[1]:'00000000';}
            function sortDates(){window.rows.sort((left,right)=>dateKey(right[1]).localeCompare(dateKey(left[1])));
              window.pageIndex=0;document.querySelector('th[aria-sort]').setAttribute('aria-sort','descending');render();}
            function resize(size){window.pageSize=size;window.pageIndex=0;window.events.push('size:'+size);
              const custom=document.querySelector('[role=combobox]');if(custom){custom.textContent=size;document.querySelector('[role=listbox]').hidden=true;}render();}
            function turn(index){window.events.push('next:'+index);window.pageIndex=index;
              document.querySelector('tbody').innerHTML='<tr><td>Loading</td></tr>';setTimeout(render,100);}
            function render(){const start=window.pageIndex*window.pageSize;const visible=window.rows.slice(start,start+window.pageSize);
              document.querySelector('tbody').innerHTML=visible.map((row,index)=>'<tr><td>'+(start+index+1)+'</td><td>'+row[0]+'</td><td>'+row[1]+'</td><td>1 KB</td><td><button>Download</button></td></tr>').join('');
              document.querySelector('#range').textContent=(visible.length?start+1:0)+'-'+(start+visible.length)+' จาก '+window.rows.length;
              document.querySelector('#first').disabled=window.pageIndex===0;document.querySelector('#next').disabled=start+visible.length>=window.rows.length;
              document.querySelectorAll('tbody button').forEach((button,index)=>button.onclick=()=>{
                const name=visible[index][0];window.events.push('download:'+name);
                const link=document.createElement('a');link.href=URL.createObjectURL(new Blob(['payload '+name],{type:'application/octet-stream'}));link.download=name;link.click();
                if(window.removeRows){window.rows.splice(start+index,1);render();}});}render();</script>""")


def check_daily_native_round(root: Path) -> None:
    from datetime import timedelta
    from .daily_download import DailyDownloader, run_daily_account
    from .evidence import BANGKOK, today
    from .workflow import StructuredDownloader
    settings = default_settings()
    settings["download_delay_seconds"] = 0
    settings["max_pages"] = 1  # The retained legacy guard must not block the next daily page.
    for index, account in enumerate(settings["accounts"]):
        account.update(username=f"offline-native-{index}", password="offline-only")
    for key in ("original_dir", "new_dir", "log_dir"):
        folder = root / ("native-" + key)
        folder.mkdir()
        settings[key] = str(folder)
    (Path(settings["original_dir"]) / "already-original.zip").write_bytes(b"payload already-original.zip")
    (Path(settings["new_dir"]) / "already-new.zip").write_bytes(b"new existing")
    history = History(Path(settings["log_dir"]))
    reporter = Reporter(history, lambda _event: None)
    visited = []
    downloaded = []
    current = datetime.now(BANGKOK)
    date_text = current.strftime("%d/%m/%Y")
    old_date = (current - timedelta(days=1)).strftime("%d/%m/%Y")
    catalogues = {
        "offline-native-0": [("pre-only.csv", date_text), ("report.xlsx.gpg", date_text), ("report.zip.gpg", date_text),
                             ("shared.zip", date_text), ("already-original.zip", date_text), ("yesterday.zip", old_date)],
        "offline-native-1": [("post-only.bin", date_text), ("shared.zip", date_text), ("already-new.zip", date_text), ("unknown-date.zip", "Unknown")],
    }
    catalogues["offline-native-0"].extend((f"daily-{index:02}.csv", date_text) for index in range(26))
    page_evidence = []
    def local_login(engine, _page, account, _timeout):
        engine.session_attempted = True
        engine.session_owned = True
        visited.append(account.username)
    def local_page(engine, page, _timeout):
        engine.stage = 4
        username = next(account.username for account in engine.settings.accounts if account.label == engine.account)
        rows = catalogues[username]
        page.set_content(daily_fixture_html(rows, custom_select=username.endswith("-0")))
    def local_logout(engine, page, account, _timeout):
        page_evidence.append((account.username, page.evaluate("({size:window.pageSize,events:window.events})")))
        engine.session_owned = False
    original_download = DailyDownloader.download_to_cache
    def native_download(engine, page, index, timeout):
        downloaded.append(page.locator("tbody tr").nth(index).locator("td").nth(1).inner_text())
        return original_download(engine, page, index, timeout)
    with patch.object(StructuredDownloader, "_login_with_retry", local_login), \
            patch.object(StructuredDownloader, "_open_download_page", local_page), \
            patch.object(StructuredDownloader, "_logout_browser_session", local_logout), \
            patch.object(StructuredDownloader, "_post_auth", side_effect=AssertionError("Account-wide reset")), \
            patch.object(DailyDownloader, "download_to_cache", native_download), \
            patch("kde_bot.workflow.MailEvidenceReader", side_effect=AssertionError("Content matching or OCR was used")):
        for sequence in (1, 2):
            jobs = [{"account": account["username"], "label": account["label"], "work_date": today(), "sequence": sequence} for account in settings["accounts"]]
            outcomes = [run_daily_account(settings, job, threading.Event(), reporter, history, root) for job in jobs]
            assert all(outcome["kind"] == "complete" for outcome in outcomes), outcomes
            assert set(downloaded) == {"post-only.bin", "pre-only.csv", "report.xlsx.gpg", "report.zip.gpg", "shared.zip", "already-original.zip"} | {f"daily-{index:02}.csv" for index in range(26)}
            assert len(downloaded) == 32
    assert len(visited) == 4
    expected = {"post-only.bin", "pre-only.csv", "report.xlsx.gpg", "report.zip.gpg", "shared.zip"} | {f"daily-{index:02}.csv" for index in range(26)}
    assert len(history.data["files"]) == 32  # .243-only presence still requires a fresh KDE download.
    from .activity import read_activity
    activity, _latest = read_activity(Path(settings["log_dir"]), exact_names=True)
    completed = {event["filename"] for event in activity if event["status"] == "complete"}
    assert completed == expected | {"already-original.zip"}
    for key, existing in (("original_dir", {"already-original.zip"}), ("new_dir", {"already-original.zip", "already-new.zip"})):
        folder = Path(settings[key])
        assert {path.name for path in folder.iterdir()} == expected | existing
        for name in expected:
            assert (folder / name).read_text() == "payload " + name
    assert all(evidence["size"] == 30 for _account, evidence in page_evidence)
    events = page_evidence[0][1]["events"]
    assert events.index(next(event for event in events if event.startswith("download:"))) < events.index("next:1")


def run_self_check(output: Path) -> int:
    result = {"checks": [], "live_portal_access": False, "business_files_modified": False,
              "download_policy": "daily_all", "ocr_enabled": False, "mail_delay_seconds": 270,
              "tracker_source": "new_dir", "sequential_accounts": True, "page_by_page": True, "portal_rows_per_page": 30,
              "daily_cleanup_time": '22:00', "daily_cleanup_preserves_all_folders": True,
              "daily_cleanup_skips_deleted_names": True, "daily_cleanup_task_registered_live": False}
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
                        assert page.locator("h1").inner_text() == "KDE offline browser check"
                        assert context.cookies()[0]["value"] == str(index)
                        context.close()
                        return index
                    finally:
                        browser.close()

            assert [browser_worker(index) for index in range(2)] == [0, 1]
            assert asyncio.create_subprocess_exec is original_subprocess_factory
            result["checks"].append("Sequential packaged browser processes with isolated account cookies; offline")
            check_arrival_metadata(root)
            result["checks"].append("Whole data mailbox incoming IDs only; read mail included; no subject/body/images read; legacy folder ignored; SMTP/store resolution; outgoing/Notes excluded; fake COM only")
            check_daily_queue(root)
            result["checks"].append("270-second arrival window, persisted mail IDs, sequential accounts, busy retry beyond two attempts at 60 seconds, restored 270-second cooldown after success, no idle portal loop")
            check_daily_cleanup(root)
            result['checks'].append('22:00 cleanup in temporary roots only; all Check/other folders preserved; active-download wait; persistent no-redownload names; headless idempotence; real Windows task definition in memory only, no task registration')
            check_scheduler_missing_task()
            result['checks'].append('Actual Windows background-thread missing-task lookup: nested COM SCODE 0x80070002 recognized for first setup; read-only, no task registered')
            check_flat_storage(root)
            result["checks"].append("Two concurrent accounts store verified files directly in shared destination roots; legacy account subfolders ignored in all three modes")
            check_destination_preflight(root)
            result["checks"].append("Destination preflight creates no probe files and succeeds with business-folder writes denied; existing files preserved; Log probe retained")
            check_portal_paging(root)
            result["checks"].append("Actual offline browser: delayed tables with background polling, shorter reverse delivery, fresh row indexes, stalled navigation refusal and Stop cancellation")
            check_daily_native_round(root)
            result["checks"].append("Real sequential daily sweep: native and Material-style 30-row selectors, downloads before next-page navigation despite old max_pages=1, today's portal dates, .97 duplicate tracking, exact extensions/history, no OCR/reset; second sweep makes no downloads")
        result["status"] = "passed"
        exit_code = 0
    except Exception as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code
