from __future__ import annotations

import json
import threading
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
    assert settings["accounts"][0]["original_dir"] == str(tmp_path / "custom")
    assert settings["accounts"][0]["password"] == ""
    assert notices and "unrelated" not in json.dumps(settings)


def test_missing_credentials_never_start_browser(tmp_path):
    settings = default_settings()
    settings["log_dir"] = str(tmp_path)
    with patch("kde_bot.workflow.StructuredDownloader") as engine:
        with pytest.raises(ValueError, match="รหัสผ่าน"):
            run_cycle(settings, threading.Event(), lambda _: None)
        engine.assert_not_called()


def test_destination_modes(tmp_path):
    settings = default_settings()
    settings["original_dir"] = str(tmp_path / "original")
    settings["new_dir"] = str(tmp_path / "new")
    account = settings["accounts"][0]
    assert len(selected_folders(settings, account)) == 2
    settings["storage_mode"] = "new"
    assert selected_folders(settings, account) == [tmp_path / "new"]


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
