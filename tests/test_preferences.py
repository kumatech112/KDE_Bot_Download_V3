"""User-selected timing must survive persistence and control actual runtime paths."""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
import threading

import pytest

from kde_bot import cleanup, daily_download
from kde_bot.evidence import BANGKOK
from kde_bot.gui import Application
from kde_bot.schedule import BackgroundClock, TrackingHours, overnight_key
from kde_bot.settings import default_settings, load_settings, normalize_settings, save_settings, validate_settings
from kde_bot.storage import History, Reporter


def moment(value):
    return datetime.fromisoformat(value).replace(tzinfo=BANGKOK).timestamp()


def custom_settings():
    settings = default_settings()
    settings.update(mail_delay_seconds=90, login_retry_seconds=20, mail_poll_seconds=10,
                    cleanup_time='21:15', resume_time='06:20', auto_start_tracking=False)
    return settings


def test_custom_values_survive_normalization_and_encrypted_settings_roundtrip(tmp_path):
    settings = custom_settings()
    settings['accounts'][0].update(username='offline', password='offline-only')
    validate_settings(settings, require_credentials=False)
    path = tmp_path / 'settings.json'
    save_settings(settings, path)
    loaded, notices = load_settings(path)
    assert not notices and loaded == normalize_settings(settings)
    assert loaded['mail_delay_seconds'] == 90 and loaded['login_retry_seconds'] == 20
    assert loaded['cleanup_time'] == '21:15' and loaded['resume_time'] == '06:20'
    assert 'offline-only' not in path.read_text(encoding='utf-8')


@pytest.mark.parametrize('key,value', [('cleanup_time', '24:00'), ('resume_time', '5:00'),
                                      ('cleanup_time', '22:60'), ('mail_delay_seconds', -1),
                                      ('login_retry_seconds', 0), ('mail_poll_seconds', 4),
                                      ('mail_delay_seconds', True), ('page_timeout_seconds', 0)])
def test_invalid_preferences_are_rejected(key, value):
    settings = default_settings()
    settings[key] = value
    with pytest.raises(ValueError):
        validate_settings(settings, require_credentials=False)


def test_equal_pause_and_resume_times_are_rejected():
    settings = default_settings()
    settings['cleanup_time'] = settings['resume_time']
    with pytest.raises(ValueError):
        validate_settings(settings, require_credentials=False)


def test_corrupt_saved_time_does_not_prevent_settings_window_loading(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{"cleanup_time":"not-time"}', encoding='utf-8')
    settings, notices = load_settings(path)
    assert notices and settings['cleanup_time'] == '22:00'
    assert path.read_text(encoding='utf-8') == '{"cleanup_time":"not-time"}'


def test_custom_mail_delay_login_retry_and_post_success_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_download, 'today', lambda: '2026-10-17')
    settings = custom_settings()
    for index, account in enumerate(settings['accounts']):
        account['username'] = f'user-{index}'
    history = History(tmp_path)
    pending = daily_download.DailyQueue(history, settings)
    mail = {'entry_id': 'first', 'store_id': 'offline', 'received': '2026-10-17T08:00:00'}
    assert pending.ingest([mail], 100) == 1
    assert pending.state['pending_due'] == 190 and pending.claim(189) == []
    assert pending.claim(190)[0]['account'] == 'user-0'
    pending.finish('user-0', {'kind': 'account_busy', 'reason': 'busy'}, 191)
    assert pending.claim(210) == [] and pending.claim(211)[0]['attempts'] == 2
    assert pending.ingest([{**mail, 'entry_id': 'second'}], 220) == 1
    pending.finish('user-0', {'kind': 'complete', 'reason': 'done'}, 250)
    assert pending.state['pending_due'] == 340
    assert pending.claim(250)[0]['account'] == 'user-1'
    pending.finish('user-1', {'kind': 'complete', 'reason': 'done'}, 251)
    assert pending.state['pending_due'] == 341
    reopened = daily_download.DailyQueue(History(tmp_path), settings)
    reopened.recover(260)
    assert reopened.state['pending_due'] == 341


def test_custom_clock_and_pause_boundaries_include_minutes(tmp_path):
    settings = custom_settings()
    history = History(tmp_path)
    hours = TrackingHours(history, settings)
    clock = BackgroundClock(moment('2026-10-17T21:14:59'), settings)
    assert hours.allowed(moment('2026-10-17T21:14:59'))
    assert clock.tick(moment('2026-10-17T21:15:00')) == ['cleanup']
    assert not hours.allowed(moment('2026-10-17T21:15:00'))
    assert not hours.allowed(moment('2026-10-18T06:19:59'))
    assert clock.tick(moment('2026-10-18T06:20:00')) == ['resume']
    assert hours.allowed(moment('2026-10-18T06:20:00'))
    hours.resume_manually(moment('2026-10-18T02:00:00'))
    assert TrackingHours(History(tmp_path), settings).allowed(moment('2026-10-18T04:00:00'))
    changed = dict(settings, cleanup_time='21:30')
    assert not TrackingHours(History(tmp_path), changed).allowed(moment('2026-10-18T04:00:00'))


def test_daytime_pause_window_and_disabled_pause(tmp_path):
    assert overnight_key(moment('2026-10-17T10:15:00'), '10:15', '12:30') == '2026-10-17'
    assert overnight_key(moment('2026-10-17T12:30:00'), '10:15', '12:30') is None
    settings = dict(custom_settings(), night_pause_enabled=False)
    assert TrackingHours(History(tmp_path), settings).allowed(moment('2026-10-17T23:00:00'))
    clock = BackgroundClock(moment('2026-10-17T21:14:59'), settings)
    assert clock.tick(moment('2026-10-17T21:15:00')) == ['cleanup']
    assert clock.tick(moment('2026-10-18T06:20:00')) == []


@pytest.mark.parametrize('background', [False, True])
def test_custom_cleanup_time_uses_only_temp_roots_and_preserves_check(tmp_path, monkeypatch, background):
    settings = custom_settings()
    for key in ('original_dir', 'new_dir', 'log_dir'):
        folder = tmp_path / key
        folder.mkdir()
        settings[key] = str(folder)
    monkeypatch.setattr(cleanup, 'APPROVED_ROOTS', (settings['original_dir'], settings['new_dir']))
    clock = [datetime(2026, 10, 17, 21, 14, 59, tzinfo=BANGKOK)]
    monkeypatch.setattr(cleanup, 'current_time', lambda: clock[0])
    for key in ('original_dir', 'new_dir'):
        root = Path(settings[key])
        (root / 'download.zip').write_bytes(b'download')
        (root / 'Check').mkdir()
        (root / 'Check' / 'keep.zip').write_bytes(b'keep')
    history = History(Path(settings['log_dir']))
    reporter = Reporter(history, lambda _event: None)
    timer = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    stop = threading.Event()
    timer.tick(clock[0].timestamp(), False, stop)
    assert (Path(settings['new_dir']) / 'download.zip').is_file()
    clock[0] = clock[0].replace(minute=15, second=0)
    if background:
        assert cleanup.run_scheduled_cleanup(settings, stop) == 0
    else:
        assert timer.tick(clock[0].timestamp(), True, stop)
        assert (Path(settings['new_dir']) / 'download.zip').is_file()
        timer.tick(clock[0].timestamp(), False, stop)
    for key in ('original_dir', 'new_dir'):
        assert not (Path(settings[key]) / 'download.zip').exists()
        assert (Path(settings[key]) / 'Check' / 'keep.zip').read_bytes() == b'keep'
    assert History(Path(settings['log_dir'])).data['daily_cleanup']['status'] == 'complete'


def test_disabled_auto_start_requires_explicit_start():
    app = object.__new__(Application)
    app.smoke = False
    app.settings = custom_settings()
    app.status = Mock()
    app.start = Mock()
    app.collect_settings = Mock(return_value=default_settings())
    with patch('kde_bot.gui.validate_settings'):
        app.auto_start()
        app.start.assert_not_called()
        app.auto_start(force=True)
        app.start.assert_called_once_with('watch')


def test_explicit_browser_overrides_bundled_headless_browser(tmp_path):
    from kde_bot.workflow import StructuredDownloader
    executable = tmp_path / 'custom-browser.exe'
    executable.write_bytes(b'offline fixture, never executed')
    engine = object.__new__(StructuredDownloader)
    engine.configuration = {'chrome_path': str(executable)}
    engine.settings = Mock(headless=True)
    with patch('kde_bot.legacy_core.KdeDownloader._browser_launch_kwargs', return_value={'args': [], 'executable_path': 'bundled.exe'}):
        assert engine._browser_launch_kwargs()['executable_path'] == str(executable)
