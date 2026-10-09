from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from kde_bot.storage import Delivery, History, Reporter, WorkerLock, record_key


@pytest.fixture
def delivery_context(tmp_path):
    folders = [tmp_path / name for name in ("original", "new", "logs")]
    for folder in folders:
        folder.mkdir()
    history = History(folders[2])
    events = []
    reporter = Reporter(history, events.append)
    return Delivery(history, reporter), history, events, folders


def test_retry_copy_does_not_download_twice(delivery_context):
    delivery, history, events, (first, second, _) = delivery_context
    downloads = []

    def download(path):
        downloads.append(path)
        path.write_bytes(b"downloaded business file")
        return path

    filename = "A1015_PAYMENT_09102026.zip.gpg"
    with patch("kde_bot.storage.verified_copy", side_effect=PermissionError("access denied")):
        assert delivery.deliver("account", filename, [first, second], download) == "copy_pending"
    assert events[-1]["step"] == 7 and "PermissionError" in events[-1]["reason"]
    assert history.data["files"][record_key("account", filename)]["pending"] == [str(second)]
    assert delivery.deliver("account", filename, [first, second], download) == "complete"
    assert len(downloads) == 1
    assert delivery.deliver("account", filename, [first, second], download) == "skipped"
    assert len(downloads) == 1
    assert (first / filename).read_bytes() == (second / filename).read_bytes()


def test_conflicting_file_is_preserved(delivery_context):
    delivery, _, events, (first, second, _) = delivery_context
    filename = "A1015_PAYMENT_09102026.zip.gpg"
    (first / filename).write_bytes(b"correct source")
    (second / filename).write_bytes(b"conflicting source")
    assert delivery.deliver("account", filename, [first, second], lambda _: pytest.fail("download called")) == "copy_pending"
    assert (second / filename).read_bytes() == b"conflicting source"
    assert "FileExistsError" in events[-1]["reason"]


def test_single_new_destination_can_copy_original(delivery_context):
    delivery, _, _, (first, second, _) = delivery_context
    filename = "A1015_PAYMENT_09102026.zip.gpg"
    (first / filename).write_bytes(b"already downloaded")
    assert delivery.deliver("account", filename, [second], lambda _: pytest.fail("download called"), [first]) == "complete"
    assert (second / filename).read_bytes() == b"already downloaded"


def test_download_timeout_reports_step_six_and_preserves_other_files(delivery_context):
    delivery, _, events, (first, second, _) = delivery_context
    untouched = first / "unrelated.txt"
    untouched.write_bytes(b"preserve")

    def failed_download(_path):
        raise TimeoutError("KDE browser download timed out")

    assert delivery.deliver("account", "A1015_TEST_09102026.zip.gpg",
                            [first, second], failed_download) == "error"
    assert events[-1]["step"] == 6
    assert "TimeoutError" in events[-1]["reason"]
    assert untouched.read_bytes() == b"preserve"


def test_empty_existing_file_is_not_overwritten(delivery_context):
    delivery, _, events, (first, second, _) = delivery_context
    filename = "A1015_PAYMENT_09102026.zip.gpg"
    (first / filename).touch()
    assert delivery.deliver("account", filename, [first, second],
                            lambda _: pytest.fail("download called")) == "error"
    assert events[-1]["step"] == 5
    assert (first / filename).stat().st_size == 0


def test_dates_and_split_volumes_stay_separate():
    assert record_key("pre", "A1015_PAYMENT_09102026.zip.gpg") != record_key("pre", "A1015_PAYMENT_08102026.zip.gpg")
    assert record_key("pre", "A1015_PAYMENT_09102026.001") != record_key("pre", "A1015_PAYMENT_09102026.002")
    assert record_key("pre", "A1015_PAYMENT_09102026.zip.gpg") != record_key("post", "A1015_PAYMENT_09102026.zip.gpg")


def test_unchanged_duplicate_outcome_does_not_repeat_csv(delivery_context):
    delivery, _, _, (first, second, logs) = delivery_context
    filename = "A1015_PAYMENT_09102026.zip.gpg"
    for folder in (first, second):
        (folder / filename).write_bytes(b"same content")
    for _ in range(3):
        assert delivery.deliver("account", filename, [first, second], lambda _: pytest.fail("download called")) == "skipped"
    files = list(logs.glob("*.csv"))
    assert len(files) == 1
    with files[0].open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 1


def test_corrupt_history_is_not_reset(tmp_path):
    path = tmp_path / "KDE_State.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        History(tmp_path)
    assert path.read_text(encoding="utf-8") == "{broken"


def test_worker_lock_rejects_competing_process(tmp_path):
    with WorkerLock(tmp_path):
        with pytest.raises(RuntimeError):
            with WorkerLock(tmp_path):
                pytest.fail("competing worker acquired lock")


def test_history_import_preserves_existing_records(delivery_context, tmp_path):
    _, history, _, _ = delivery_context
    key = record_key("account", "A1015_PAYMENT_09102026.zip.gpg")
    history.data["files"][key] = {"filename": "preserved", "sha256": "existing"}
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"downloaded": {"account": {
        "first": {"filename": "A1015_PAYMENT_09102026.zip.gpg"},
        "second": {"filename": "A1015_PAYMENT_09102026.001"},
    }}}), encoding="utf-8")
    assert history.import_legacy(legacy) == 1
    assert history.data["files"][key]["sha256"] == "existing"
