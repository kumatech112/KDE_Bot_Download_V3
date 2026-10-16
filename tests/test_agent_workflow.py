from __future__ import annotations

import base64
import io
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from kde_bot import legacy_core as core
from kde_bot.evidence import BANGKOK, LocalOCR, MailEvidenceReader, reference_lookup, today
from kde_bot.mail_queue import MailQueue
from kde_bot.settings import default_settings, settings_home, validate_settings
from kde_bot.storage import Delivery, History, Reporter, file_hash, open_new_target, record_key, verified_copy
from kde_bot.workflow import StructuredDownloader, make_engine_settings
from test_mail_trigger import setup_queue, message
from test_outlook_scan import Collection, folder, mail, scan, setup_scanner


def reference_image(path: Path) -> Path:
    image = Image.new("RGB", (1600, 240), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
    draw.text((30, 30), "PRE PAYMENT ONLINE 67097", font=font, fill="black")
    draw.text((30, 100), "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg", font=font, fill="black")
    image.save(path)
    return path


def test_actual_local_ocr_reads_filename_and_reuses_content_cache(tmp_path):
    path = reference_image(tmp_path / "reference.png")
    reader = LocalOCR()
    result = reader.read(path)
    assert result["confidence"] >= 70
    assert "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg" in result["text"]
    with patch("kde_bot.evidence.subprocess.run", side_effect=AssertionError("repeated OCR")):
        assert reader.read(path) == result


def test_attached_and_inline_data_images_are_read_locally_without_using_image_filenames(tmp_path):
    image = reference_image(tmp_path / "reference.png").read_bytes()
    class Attachment:
        FileName = "image001.png"
        Size = len(image)
        def SaveAsFile(self, path):
            Path(path).write_bytes(image)
    item = SimpleNamespace(EntryID="image-mail", LastModificationTime="one",
                           HTMLBody='<img src="cid:embedded"><img src="data:image/png;base64,' + base64.b64encode(image).decode() + '">',
                           Attachments=Collection([Attachment()]))
    reader = MailEvidenceReader()
    evidence = reader.read(item, "Pre files ready", datetime.now())
    assert evidence["image_count"] == 2
    assert "a1015_payment_online_67097_16102026.zip.gpg" in evidence["lookup"]
    assert "image001.png" not in evidence["lookup"]
    assert evidence.get("side") == "pre" and not evidence["review"]


def test_low_confidence_image_is_a_review_request_without_guessing():
    reader = MailEvidenceReader()
    with patch.object(reader.ocr, "read", return_value={"text": "A1015_PAYMENT_16102026.zip.gpg", "confidence": 51, "sha256": "sample"}):
        result = reader.screenshot(Path("sample.png"), "pre")
    assert result["review"] and result["side"] == "pre"


def test_remote_images_and_html_scripts_do_not_trigger_network_ocr_or_references():
    item = SimpleNamespace(EntryID="remote-image", HTMLBody='<img src="https://tracking.example/image.png"><script>A1015_PAYMENT_16102026.zip.gpg</script>',
                           Attachments=Collection([]))
    reader = MailEvidenceReader()
    with patch.object(reader.ocr, "read", side_effect=AssertionError("remote image opened")):
        result = reader.read(item, "Pre notice", datetime.now())
    assert result["image_count"] == 0 and result["lookup"] == {}


def test_today_scan_includes_read_mail_and_excludes_previous_and_future_days(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    scanner.settings.mail_watch.unread_only = False
    values = [mail("read", unread=False), mail("unread"), mail("old"), mail("future")]
    values[2].ReceivedTime = datetime.now(BANGKOK) - timedelta(days=1)
    values[3].ReceivedTime = datetime.now(BANGKOK) + timedelta(days=1)
    assert scan(scanner, [folder("data@tradeconnection.co.th", values)])
    assert [item["entry_id"] for item in scanner.mail_messages] == ["read", "unread"]
    assert not values[0].UnRead and values[1].UnRead


def test_fifo_blocks_overtaking_and_allows_other_account_to_work(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message("first"), message("second"), message("post", "post")], 100)
    first = next(job for job in queue.jobs.values() if job["account"] == "account-0")
    first["due"] = 500
    ready = queue.claim_ready(220, set())
    assert set(ready) == {"account-1"}
    assert queue.claim_ready(499, set()) == {}
    assert queue.claim_ready(500, set())["account-0"][0]["id"] == first["id"]
    assert queue.claim_ready(501, set()) == {}


def test_unknown_side_requires_review_and_confirmation_keeps_deduplication(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    incoming = message("unknown", side="", filenames=["payment online 67097"])
    queue.ingest([incoming], 100)
    job = next(iter(queue.jobs.values()))
    assert job["status"] == "review" and queue.claim_ready(999, set()) == {}
    queue.resolve(job["id"], "account-1", "A1015L_PAYMENT_ONLINE_67097_16102026.zip.gpg", 1000)
    assert queue.ingest([incoming], 1001) == 0
    assert queue.claim_ready(1119, set()) == {}
    assert queue.claim_ready(1120, set())["account-1"][0]["id"] == job["id"]


def test_review_cannot_assign_post_reference_to_pre(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message(side="", filenames=["payment online 67097"])], 0)
    job = next(iter(queue.jobs.values()))
    with pytest.raises(ValueError, match="other account"):
        queue.resolve(job["id"], "account-0", "A10XXL_PAYMENT_16102026.zip.gpg", 100)
    assert job["status"] == "review"


def test_previous_day_waiting_jobs_expire_without_new_login(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    old = message()
    old["received"] = (datetime.now(BANGKOK) - timedelta(days=1)).isoformat()
    queue.ingest([old], 0)
    scoped = MailQueue(history, reporter, settings, today())
    scoped.recover_interrupted(1000)
    assert scoped.claim_ready(9999, set()) == {}
    assert next(iter(scoped.jobs.values()))["status"] == "expired"
    assert next(iter(History(tmp_path / "log_dir").data["mail_jobs"].values()))["status"] == "expired"


def test_wildcard_post_reference_routes_only_to_post(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message(side="", filenames=["A10XXL_RESULTS_16102026.zip.gpg"])], 0)
    assert set(queue.claim_ready(120, set())) == {"account-1"}


def test_conflicting_image_side_is_visible_for_review(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    incoming = message(filenames=["A1015L_PAYMENT_16102026.zip.gpg"])
    incoming["side"] = "pre"
    queue.ingest([incoming], 0)
    assert len(queue.jobs) == 1
    assert next(iter(queue.jobs.values()))["status"] == "review"
    assert queue.claim_ready(120, set()) == {}


def test_ocr_typo_tolerance_preserves_business_numbers_and_account_side(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    engine = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    reference = "A1015_PAYNENT_ONLINE_67097_16102026.zip.gpg"
    key = core.normalize_filename_for_match(reference)
    good = core.normalize_filename_for_match("A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg")
    assert engine._match_single_mail_key(good, key, reference + " [Image OCR]")
    assert engine._match_single_mail_key(good.replace("67097", "67098"), key, reference + " [Image OCR]") is None
    assert engine._match_single_mail_key(good.replace("a1015_", "a1015l_"), key, reference + " [Image OCR]") is None


def test_broad_reference_uses_email_day_and_does_not_choose_wrong_date_or_side(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    incoming = message(filenames=["payment online 67097"])
    incoming["received"] = "2026-10-16T10:00:00"
    queue.ingest([incoming], 0)
    jobs = queue.claim_ready(120, set())["account-0"]
    engine = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    engine.jobs = jobs
    rows = [(0, {"filename": "A1015_PAYMENT_ONLINE_67097_15102026.zip.gpg"}),
            (1, {"filename": "A1015L_PAYMENT_ONLINE_67097_16102026.zip.gpg"}),
            (2, {"filename": "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"})]
    selected, ambiguous = engine._select_page_mail_matches(rows, jobs[0]["lookup"])
    assert set(selected) == {2} and not ambiguous


def test_final_publication_creates_no_sidecar_and_locks_readers_until_verified(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    destination.mkdir()
    source.write_bytes(b"verified payload")
    target = destination / "business.zip.gpg"
    with patch("kde_bot.storage.os.rename", side_effect=AssertionError("destination rename attempted")):
        verified_copy(source, target, file_hash(source))
    assert list(destination.iterdir()) == [target]
    with open_new_target(destination / "locked.gpg") as stream:
        stream.write(b"not published yet")
        stream.flush()
        with pytest.raises(PermissionError):
            (destination / "locked.gpg").read_bytes()


def test_destination_created_by_competing_writer_is_not_overwritten(tmp_path):
    target = tmp_path / "business.gpg"
    target.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        open_new_target(target)
    assert target.read_bytes() == b"preserve"


def test_failed_save_retains_local_source_for_repair_without_portal(tmp_path, monkeypatch):
    monkeypatch.setenv("KDE_V3_HOME", str(tmp_path / "local"))
    cache = settings_home() / "cache"
    cache.mkdir(parents=True)
    source = cache / "offline.download"
    source.write_bytes(b"cached complete payload")
    destinations = [tmp_path / "first", tmp_path / "second"]
    for folder_path in destinations:
        folder_path.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    history = History(logs)
    delivery = Delivery(history, Reporter(history, lambda _event: None))
    with patch("kde_bot.storage.verified_copy", side_effect=PermissionError("save denied")):
        assert delivery.deliver("Pre", "business.gpg", destinations, lambda _: source) == "copy_pending"
    assert source.is_file()
    assert delivery.deliver("Pre", "business.gpg", destinations,
                            lambda _: pytest.fail("Portal redownload attempted")) == "complete"
    assert not source.exists()
    assert all((folder_path / "business.gpg").read_bytes() == b"cached complete payload" for folder_path in destinations)


def test_log_folder_must_be_separate_from_business_destinations(tmp_path):
    settings = default_settings()
    settings["original_dir"] = str(tmp_path)
    settings["log_dir"] = str(tmp_path / "logs")
    with pytest.raises(ValueError, match="separate Log"):
        validate_settings(settings, require_credentials=False)


def test_sent_drafts_and_deleted_mail_do_not_trigger_download_requests(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    scanner.settings.mail_watch.unread_only = False
    children = [folder(name, [mail(name)]) for name in ("Inbox", "Sent Items", "Drafts", "Deleted Items", "Outbox")]
    scan(scanner, [folder("data@tradeconnection.co.th", children=children)])
    assert [item["entry_id"] for item in scanner.mail_messages] == ["Inbox"]


def catalog_engine(tmp_path, references, pages):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    settings["download_delay_seconds"] = 0
    incoming = message(filenames=references)
    incoming["received"] = "2026-10-16T10:00:00"
    queue.ingest([incoming], 0)
    engine = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                  Delivery(history, reporter), settings, threading.Event())
    engine.jobs = queue.claim_ready(120, set())["account-0"]
    cursor = [0]
    engine._table_rows = lambda _page: [(index, {"filename": name}) for index, name in enumerate(pages[cursor[0]])]
    engine._has_next_page = lambda _page: cursor[0] + 1 < len(pages)
    def next_page(*_args):
        cursor[0] += 1
        return True
    def previous_page(*_args):
        cursor[0] -= 1
        return True
    engine._next_page = next_page
    engine._previous_page = previous_page
    return engine, cursor, events


def test_broad_matches_on_different_pages_are_rejected_before_any_download(tmp_path):
    pages = [["A1015_PAYMENT_ONLINE_67097_Alpha_16102026.zip.gpg"],
             ["A1015_PAYMENT_ONLINE_67097_Beta_16102026.zip.gpg"]]
    engine, cursor, events = catalog_engine(tmp_path, ["payment online 67097"], pages)
    with patch.object(engine, "handle_file", side_effect=AssertionError("ambiguous download")):
        result = engine._download_visible_pages(None, engine.settings.accounts[0], 1000, engine.jobs[0]["lookup"])
    assert result["downloaded"] == 0
    assert any(event["status"] == "warning" for event in events)


def test_precise_reference_does_not_download_extra_broad_subject_matches(tmp_path):
    filename = "A1015_PAYMENT_ONLINE_67097_Alpha_16102026.zip.gpg"
    pages = [[filename], ["A1015_PAYMENT_ONLINE_67097_Beta_16102026.zip.gpg"]]
    engine, cursor, events = catalog_engine(tmp_path, [filename, "payment online 67097"], pages)
    calls = []
    def handle(_page, row_index, row, _account, _timeout):
        calls.append((cursor[0], row["filename"]))
        return "complete"
    engine.handle_file = handle
    result = engine._download_visible_pages(None, engine.settings.accounts[0], 1000, engine.jobs[0]["lookup"])
    assert calls == [(0, filename)] and result["downloaded"] == 1


def test_page_limit_never_causes_partial_catalogue_to_be_treated_as_unique(tmp_path):
    pages = [["A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"], ["other.gpg"]]
    engine, cursor, events = catalog_engine(tmp_path, [pages[0][0]], pages)
    engine.settings.max_pages = 1
    with patch.object(engine, "handle_file", side_effect=AssertionError("download before full matching")):
        with pytest.raises(RuntimeError, match="page limit reached"):
            engine._download_visible_pages(None, engine.settings.accounts[0], 1000, engine.jobs[0]["lookup"])


def test_changed_portal_row_cannot_make_click_target_a_different_file(tmp_path):
    filename = "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"
    engine, cursor, events = catalog_engine(tmp_path, [filename], [[filename]])
    with patch.object(engine, "_table_rows", side_effect=[[(0, {"filename": filename})], [(0, {"filename": "unrequested.gpg"})]]), \
            patch.object(engine, "handle_file", side_effect=AssertionError("wrong file clicked")):
        with pytest.raises(RuntimeError, match="Portal list changed"):
            engine._download_visible_pages(None, engine.settings.accounts[0], 1000, engine.jobs[0]["lookup"])


def test_pending_save_holds_following_work_until_repair_is_verified(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message("first"), message("second")], 0)
    first = queue.claim_ready(120, set())["account-0"][0]
    queue.finish({first["id"]: {"kind": "copy_pending", "reason": "save denied"}}, 121)
    assert queue.claim_ready(1000, set()) == {}
    history.set_file("offline-file", {"mail_jobs": [first["id"]], "pending": [], "destinations": {"root": "business.gpg"}})
    queue.refresh_saved_jobs()
    assert queue.jobs[first["id"]]["status"] == "complete"
    assert queue.claim_ready(1001, set())["account-0"][0]["id"] != first["id"]


def test_a_newest_first_outlook_scan_is_queued_in_received_order(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    newer = message("newer")
    older = message("older")
    newer["received"] = today() + "T10:01:00"
    older["received"] = today() + "T10:00:00"
    queue.ingest([newer, older], 0)
    first = queue.claim_ready(120, set())["account-0"][0]
    assert first["received"] == older["received"]


def test_old_day_pending_save_does_not_invisibly_block_new_day_work(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    queue.ingest([message("old")], 0)
    job = queue.claim_ready(120, set())["account-0"][0]
    queue.finish({job["id"]: {"kind": "copy_pending", "reason": "save denied"}}, 121)
    queue.jobs[job["id"]]["work_date"] = "2000-01-01"
    scoped = MailQueue(history, reporter, settings, today())
    scoped.ingest([message("today")], 200)
    assert scoped.claim_ready(320, set())["account-0"][0]["id"] != job["id"]
    assert scoped.jobs[job["id"]]["status"] == "expired"


def test_download_pass_walks_back_only_to_the_page_with_a_selected_file(tmp_path):
    filename = "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg"
    pages = [["first-page.gpg"], [filename], ["last-page.gpg"]]
    engine, cursor, events = catalog_engine(tmp_path, [filename], pages)
    reads, moves, calls = [], [], []
    original_rows = engine._table_rows
    engine._table_rows = lambda page: (reads.append(cursor[0]), original_rows(page))[1]
    original_next, original_previous = engine._next_page, engine._previous_page
    engine._next_page = lambda *a: (moves.append("next"), original_next(*a))[1]
    engine._previous_page = lambda *a: (moves.append("previous"), original_previous(*a))[1]

    def handle(_page, row_index, row, _account, _timeout):
        calls.append((cursor[0], row["filename"]))
        return "complete"
    engine.handle_file = handle
    result = engine._download_visible_pages(None, engine.settings.accounts[0], 1000, engine.jobs[0]["lookup"])
    assert calls == [(1, filename)] and result["downloaded"] == 1
    # Two forward moves to catalogue, one backward move to page 2 of 3; never back to page 1.
    assert moves == ["next", "next", "previous"]
    # Catalogue reads every page once; the delivery pass reads only the page holding the file.
    assert reads == [0, 1, 2, 1]


class TablePage:
    """Minimal Playwright-like page: tbody text sequence and an evaluate_all payload."""

    def __init__(self, texts=("",), cells=None):
        self.texts, self.cells, self.seen = list(texts), cells or [], 0
        self.elapsed = 0
        self.evaluations = 0
        self.clicks = 0

    def locator(self, _selector):
        return self

    @property
    def first(self):
        return self

    def inner_text(self, timeout=0):
        text = self.texts[min(self.seen, len(self.texts) - 1)]
        self.seen += 1
        return text

    def evaluate_all(self, _script):
        self.evaluations += 1
        return self.cells

    def evaluate(self, _script, arg=None, timeout=0):
        return self.inner_text(timeout=timeout)

    def wait_for_timeout(self, milliseconds):
        self.elapsed += milliseconds / 1000

    def count(self):
        return 1

    def is_enabled(self):
        return True

    def click(self, **_kwargs):
        self.clicks += 1


def test_page_change_wait_returns_when_new_table_text_is_stable(tmp_path):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage(texts=["old", "old", "new", "new", "new"])
    with patch("kde_bot.workflow.time.monotonic", side_effect=lambda: page.elapsed):
        assert engine._wait_table_change(page, "old")
    assert page.elapsed >= 0.65 and page.seen >= 6


def test_table_rows_are_read_in_one_call_and_keep_original_indexes(tmp_path):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage(cells=[["1", "a.gpg", "16-10-2026 10:00", "1 KB"],
                            ["2", "", "t", "s"],
                            ["too", "short"],
                            ["4", "b.gpg", "16-10-2026 11:00", "2 KB", "extra"]])
    assert StructuredDownloader._table_rows(engine, page) == [
        (0, {"no": "1", "filename": "a.gpg", "file_time": "16-10-2026 10:00", "size_text": "1 KB"}),
        (3, {"no": "4", "filename": "b.gpg", "file_time": "16-10-2026 11:00", "size_text": "2 KB"}),
    ]
    assert page.evaluations == 1


@pytest.mark.parametrize("reset", ["old", ""])
def test_transient_table_change_must_settle_after_old_or_empty_rows(tmp_path, reset):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage(texts=["old", "partial", "partial", reset, "full", "full"])
    with patch("kde_bot.workflow.time.monotonic", side_effect=lambda: page.elapsed):
        assert engine._wait_table_change(page, "old")
    assert page.elapsed >= 0.85


def test_stalled_page_click_fails_instead_of_claiming_the_next_page_loaded(tmp_path):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage(texts=["old"])
    with patch("kde_bot.workflow.time.monotonic", side_effect=lambda: page.elapsed):
        with pytest.raises(RuntimeError, match="incomplete catalogue"):
            StructuredDownloader._next_page(engine, page, 500)
    assert page.clicks == 1 and page.elapsed <= 0.6


def test_unreadable_current_table_does_not_start_navigation(tmp_path):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage(texts=[""])
    with pytest.raises(RuntimeError, match="unverified navigation"):
        StructuredDownloader._next_page(engine, page, 500)
    assert page.clicks == 0


def test_stop_cancels_page_wait_and_prevents_another_click(tmp_path):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage(texts=["old"])
    def stop_after_wait(milliseconds):
        page.elapsed += milliseconds / 1000
        engine.stop_event.set()
    page.wait_for_timeout = stop_after_wait
    with patch("kde_bot.workflow.time.monotonic", side_effect=lambda: page.elapsed):
        assert engine._wait_table_change(page, "old") is False
    assert StructuredDownloader._next_page(engine, page, 500) is False
    assert page.clicks == 0


def test_bulk_table_read_failure_preserves_legacy_fallback(tmp_path):
    engine, _cursor, _events = catalog_engine(tmp_path, ["x"], [["x"]])
    page = TablePage()
    expected = [(0, {"filename": "expected.gpg"})]
    with patch.object(page, "evaluate_all", side_effect=RuntimeError("Unsupported table call")), \
            patch.object(core.KdeDownloader, "_table_rows", return_value=expected) as fallback:
        assert StructuredDownloader._table_rows(engine, page) == expected
    fallback.assert_called_once_with(page)


def test_second_download_uses_fresh_row_index_after_first_file_disappears(tmp_path):
    names = ["A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg", "A1015_TSS_REVIEW_16102026.zip.gpg"]
    pages = [names.copy()]
    engine, cursor, _events = catalog_engine(tmp_path, names, pages)
    calls = []
    def handle(_page, row_index, row, _account, _timeout):
        assert pages[cursor[0]][row_index] == row["filename"]
        calls.append(row["filename"])
        pages[cursor[0]].pop(row_index)
        return "complete"
    engine.handle_file = handle
    result = engine._download_visible_pages(None, engine.settings.accounts[0], 1000, engine.jobs[0]["lookup"])
    assert calls == names and result["downloaded"] == 2
