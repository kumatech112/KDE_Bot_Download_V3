from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from kde_bot.settings import (
    atomic_json, default_settings, import_settings, load_settings, save_settings,
)
from kde_bot.workflow import run_cycle, selected_folders
from kde_bot import legacy_core as core


def test_foreign_dpapi_opens_settings_with_values_preserved(tmp_path):
    settings = default_settings()
    settings["accounts"][0]["username"] = "test-account"
    settings["accounts"][0]["password"] = {"$dpapi": "invalid"}
    path = tmp_path / "settings.json"
    atomic_json(path, settings)
    loaded, notices = load_settings(path)
    assert loaded["accounts"][0]["username"] == "test-account"
    assert loaded["accounts"][0]["password"] == ""
    assert loaded["original_dir"] == settings["original_dir"]
    assert notices


def test_saved_credentials_are_encrypted(tmp_path):
    settings = default_settings()
    settings["accounts"][0]["password"] = "test-private-password"
    path = tmp_path / "settings.json"
    save_settings(settings, path)
    assert "test-private-password" not in path.read_text(encoding="utf-8")
    loaded, notices = load_settings(path)
    assert loaded["accounts"][0]["password"] == "test-private-password" and not notices


def test_import_combined_config_keeps_only_kde(tmp_path):
    raw = default_settings()
    raw["accounts"][0]["download_dir"] = str(tmp_path / "custom")
    raw["accounts"][0]["password"] = {"$dpapi": "invalid"}
    path = tmp_path / "old.json"
    atomic_json(path, {"profiles": {"kde": raw, "routine": {"password": "unrelated"}}})
    settings, notices = import_settings(path)
    assert "profiles" not in settings
    assert "original_dir" not in settings["accounts"][0]
    assert "download_dir" not in settings["accounts"][0]
    assert settings["original_dir"] == raw["original_dir"]
    assert settings["accounts"][0]["password"] == ""
    assert notices and "unrelated" not in json.dumps(settings)


def test_missing_credentials_never_start_browser(tmp_path):
    settings = default_settings()
    settings["log_dir"] = str(tmp_path)
    with patch("kde_bot.workflow.StructuredDownloader") as engine:
        with pytest.raises(ValueError, match="username and password"):
            run_cycle(settings, threading.Event(), lambda _: None)
        engine.assert_not_called()


@pytest.mark.parametrize("mode", ["both", "original", "new"])
def test_destination_modes_ignore_legacy_account_subfolders(tmp_path, mode):
    settings = default_settings()
    settings["original_dir"] = str(tmp_path / "original")
    settings["new_dir"] = str(tmp_path / "new")
    settings["storage_mode"] = mode
    expected = {"both": [tmp_path / "original", tmp_path / "new"],
                "original": [tmp_path / "original"], "new": [tmp_path / "new"]}[mode]
    for account in settings["accounts"]:
        account["original_dir"] = str(tmp_path / "original" / account["label"])
        assert selected_folders(settings, account) == expected


@pytest.mark.parametrize("reader", [load_settings, import_settings])
def test_saved_v3_migration_discards_account_folders_preserves_user_settings(tmp_path, reader):
    raw = default_settings()
    raw["original_dir"] = str(tmp_path / "chosen-original")
    raw["new_dir"] = str(tmp_path / "chosen-new")
    raw["log_dir"] = str(tmp_path / "chosen-logs")
    raw["accounts"][0].update(username="pre-user", password="local-password",
                              original_dir=str(tmp_path / "01 Pre"))
    raw["accounts"][1].update(username="post-user", enabled=False,
                              original_dir=str(tmp_path / "02 Post"))
    path = tmp_path / "settings.json"
    atomic_json(path, raw)
    settings, notices = reader(path)
    assert not notices
    assert all("original_dir" not in account for account in settings["accounts"])
    assert settings["accounts"][0]["username"] == "pre-user"
    assert settings["accounts"][0]["password"] == "local-password"
    assert settings["accounts"][1]["enabled"] is False
    assert all(settings[key] == raw[key] for key in ("original_dir", "new_dir", "log_dir"))
    save_settings(settings, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert all("original_dir" not in account for account in saved["accounts"])
    assert "local-password" not in path.read_text(encoding="utf-8")


def test_delivery_hook_continues_after_one_failed_file(tmp_path):
    from kde_bot.workflow import make_engine_settings
    settings = default_settings()
    settings["original_dir"] = str(tmp_path)
    settings["new_dir"] = str(tmp_path)
    settings["download_delay_seconds"] = 0
    settings["max_pages"] = 1
    settings["accounts"][0]["username"] = "pre"
    engine = core.KdeDownloader(make_engine_settings(settings, tmp_path / "engine.json"))
    account = engine.settings.accounts[0]
    engine.state["downloaded"][account.username] = {}
    rows = [(0, {"filename": "A1015_TEST_09102026.zip.gpg"}),
            (1, {"filename": "A1015_OTHER_09102026.zip.gpg"})]
    engine._table_rows = lambda _page: rows
    statuses = iter(["copy_pending", "complete"])
    engine.file_handler = lambda *_: next(statuses)
    result = engine._download_visible_pages(None, account, 1000, None)
    assert result["errors"] == 1 and result["downloaded"] == 1


def test_pending_copy_recovery_uses_roots_without_recreating_deleted_account_folder(tmp_path):
    from kde_bot.storage import History, record_key
    settings = default_settings()
    for key in ("original_dir", "new_dir", "log_dir"):
        folder = tmp_path / key
        folder.mkdir()
        settings[key] = str(folder)
    account = settings["accounts"][0]
    account.update(username="pre-user", original_dir=str(tmp_path / "original_dir" / "01 Pre"))
    settings["accounts"][1]["enabled"] = False
    filename = "A1015_TEST_10102026.zip.gpg"
    source = tmp_path / "original_dir" / filename
    source.write_bytes(b"previous download at root")
    history = History(tmp_path / "log_dir")
    history.set_file(record_key(account["username"], filename), {
        "account": account["username"], "filename": filename,
        "pending": [settings["new_dir"]],
    })
    with patch.object(core.KdeDownloader, "_click_download_row", side_effect=AssertionError("portal download called")):
        run_cycle(settings, threading.Event(), lambda _: None, retry_only=True)
    assert (tmp_path / "new_dir" / filename).read_bytes() == source.read_bytes()
    assert not (tmp_path / "original_dir" / "01 Pre").exists()
    record = History(tmp_path / "log_dir").data["files"][record_key(account["username"], filename)]
    assert record["pending"] == []
    assert set(record["destinations"]) == {settings["original_dir"], settings["new_dir"]}


@pytest.mark.parametrize("mode", ["both", "original", "new"])
@pytest.mark.parametrize("check_only", [True, False])
def test_destination_preflight_never_opens_test_files_for_writing(tmp_path, monkeypatch, mode, check_only):
    from kde_bot.workflow import StructuredDownloader
    settings = default_settings()
    settings["storage_mode"] = mode
    destinations = set()
    for key in ("original_dir", "new_dir", "log_dir"):
        folder = tmp_path / key
        folder.mkdir()
        settings[key] = str(folder)
        if key != "log_dir":
            destinations.add(folder)
            (folder / "business-file.gpg").write_bytes(b"preserve existing download")
    original_open = Path.open
    attempted_destination_writes = []

    def guarded_open(path, mode="r", *args, **kwargs):
        if path.parent in destinations and any(flag in mode for flag in ("w", "a", "x", "+")):
            attempted_destination_writes.append(path)
            raise AssertionError(f"Destination preflight attempted to create a file: {path}")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(StructuredDownloader, "_browser_launch_kwargs", lambda _self: {"executable_path": sys.executable})
    events = []
    run_cycle(settings, threading.Event(), events.append, check_only=check_only, retry_only=not check_only)
    assert attempted_destination_writes == []
    for folder in destinations:
        assert {path.name for path in folder.iterdir()} == {"business-file.gpg"}
        assert (folder / "business-file.gpg").read_bytes() == b"preserve existing download"
    assert any("save access is checked during real delivery" in event["reason"] for event in events)
