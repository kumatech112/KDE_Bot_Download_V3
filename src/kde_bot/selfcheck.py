"""Offline checks executed by the real packaged EXE, with isolated temporary data."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from .settings import atomic_json, default_settings, load_settings, save_settings
from .storage import Delivery, History, Reporter, WorkerLock


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
            import threading
            engine = StructuredDownloader(
                make_engine_settings(settings, root / "temporary-engine.json"),
                reporter, delivery, settings, threading.Event(),
            )
            from .legacy_core import sync_playwright_without_console
            with sync_playwright_without_console(lambda _message: None) as playwright:
                browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
                try:
                    page = browser.new_page()
                    page.set_content("<html><body><h1>KDE offline browser check</h1></body></html>")
                    assert page.locator("h1").inner_text() == "KDE offline browser check"
                finally:
                    browser.close()
            result["checks"].append("Bundled Playwright driver and browser operate offline")
        result["status"] = "passed"
        exit_code = 0
    except Exception as error:
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        exit_code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code
