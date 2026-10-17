from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from kde_bot import daily_download as daily
from kde_bot.legacy_core import sync_playwright_without_console
from kde_bot.selfcheck import daily_fixture_html
from kde_bot.settings import default_settings
from kde_bot.storage import Delivery, History, Reporter
from kde_bot.workflow import make_engine_settings


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(daily, "today", lambda: "2026-10-16")
    settings = default_settings()
    settings["accounts"][0]["username"] = "offline-pre"
    settings["download_delay_seconds"] = 0
    settings["max_pages"] = 1
    history = History(tmp_path)
    reporter = Reporter(history, lambda _event: None)
    return daily.DailyDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                 Delivery(history, reporter), settings, threading.Event(), "2026-10-16")


@pytest.mark.parametrize("custom", [False, True])
def test_77_rows_use_30_per_page_and_download_before_next_despite_old_limit(engine, custom):
    rows = [(f"arbitrary-{index:02}.zip", "16/10/2026 16:15:26" if index < 65 else "15/10/2026 16:15:26") for index in range(77)]
    saved = []
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows, custom_select=custom))
            def save(current, index, row, _account, _timeout):
                assert current.locator("tbody tr").nth(index).locator("td").nth(1).inner_text() == row["filename"]
                saved.append(row["filename"])
                current.evaluate("name => window.events.push('download:'+name)", row["filename"])
                return "complete"
            with patch.object(engine, "handle_file", side_effect=save):
                result = engine._download_visible_pages(page, engine.settings.accounts[0], 3000)
            assert result["downloaded"] == 65 and len(saved) == len(set(saved)) == 65
            assert page.evaluate("window.pageSize") == 30
            events = page.evaluate("window.events")
            assert events.index("download:arbitrary-00.zip") < events.index("next:1")
            assert events.index("download:arbitrary-30.zip") < events.index("next:2")
            assert len([event for event in events if event.startswith("next:")]) == 2
        finally:
            browser.close()


def test_rows_removed_and_refilled_during_download_do_not_skip_files(engine):
    rows = [(f"file-{index:02}.gpg", "16/10/2026") for index in range(35)]
    saved = []
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows, remove_rows=True))
            def remove(current, index, row, _account, _timeout):
                saved.append(row["filename"])
                current.evaluate("index => {window.rows.splice(window.pageIndex*window.pageSize+index,1);render();}", index)
                return "complete"
            with patch.object(engine, "handle_file", side_effect=remove):
                result = engine._download_visible_pages(page, engine.settings.accounts[0], 3000)
            assert result["downloaded"] == 35 and len(set(saved)) == 35
            assert page.evaluate("window.rows.length") == 0
        finally:
            browser.close()


def test_stalled_next_page_reports_error_after_preserving_first_page_downloads(engine):
    rows = [(f"file-{index:02}.gpg", "16/10/2026") for index in range(40)]
    saved = []
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows))
            page.evaluate("document.querySelector('#next').onclick=()=>{}")
            with patch.object(engine, "handle_file", side_effect=lambda _page, _index, row, *_args: saved.append(row["filename"]) or "complete"):
                with pytest.raises(RuntimeError, match="ไม่เปลี่ยนหน้า"):
                    engine._download_visible_pages(page, engine.settings.accounts[0], 800)
            assert len(saved) == 30
        finally:
            browser.close()


def test_missing_next_button_cannot_report_a_partial_list_as_complete(engine):
    rows = [(f"file-{index:02}.gpg", "16/10/2026") for index in range(40)]
    saved = []
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows))
            with patch("kde_bot.portal_pages.next_button", return_value=None), \
                    patch.object(engine, "handle_file", side_effect=lambda _page, _index, row, *_args: saved.append(row["filename"]) or "complete"):
                with pytest.raises(RuntimeError, match="ยังไม่ถึงหน้าสุดท้าย"):
                    engine._download_visible_pages(page, engine.settings.accounts[0], 3000)
            assert len(saved) == 30
        finally:
            browser.close()


def test_first_older_boundary_stops_without_visiting_159_history_pages(engine):
    rows = [(f"today-{index}.zip", "16/10/2026 12:00") for index in range(21)]
    rows.extend((f"old-{index}.zip", "15/10/2026 12:00") for index in range(4779))
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows))
            with patch.object(engine, "handle_file", return_value="complete"):
                result = engine._download_visible_pages(page, engine.settings.accounts[0], 3000)
            assert result['downloaded'] == 21
            assert not [event for event in page.evaluate('window.events') if event.startswith('next:')]
            assert page.locator('th[aria-sort]').get_attribute('aria-sort') == 'descending'
        finally:
            browser.close()


def test_date_sort_moves_later_today_rows_ahead_of_history_before_download(engine):
    rows = [(f"old-{index}.zip", "15/10/2026") for index in range(90)]
    rows.extend((f"today-{index}.zip", "16/10/2026") for index in range(4))
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows))
            saved = []
            with patch.object(engine, "handle_file", side_effect=lambda _page, _index, row, *_args: saved.append(row['filename']) or 'complete'):
                engine._download_visible_pages(page, engine.settings.accounts[0], 3000)
            assert saved == [f'today-{index}.zip' for index in range(4)]
            assert not [event for event in page.evaluate('window.events') if event.startswith('next:')]
        finally:
            browser.close()


def test_unsortable_visibly_mixed_dates_fail_without_guessing_or_history_walk(engine):
    rows = [('old.zip', '15/10/2026'), ('today.zip', '16/10/2026')]
    with sync_playwright_without_console(lambda _message: None) as playwright:
        browser = playwright.chromium.launch(**engine._browser_launch_kwargs())
        try:
            page = browser.new_page()
            page.set_content(daily_fixture_html(rows))
            page.locator('thead').evaluate('element => element.remove()')
            with patch.object(engine, 'handle_file', side_effect=AssertionError('Unverified order')):
                with pytest.raises(RuntimeError, match='ไม่เรียง'):
                    engine._download_visible_pages(page, engine.settings.accounts[0], 3000)
            assert not [event for event in page.evaluate('window.events') if event.startswith('next:')]
        finally:
            browser.close()
