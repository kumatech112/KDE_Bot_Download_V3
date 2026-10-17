"""Background-hours regressions, with no production files or registry writes."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
import queue
import threading

import pytest

from kde_bot.evidence import BANGKOK
from kde_bot.schedule import BackgroundClock, TrackingHours, overnight_key
from kde_bot.settings import default_settings, normalize_settings, validate_settings
from kde_bot.storage import History, Reporter
from kde_bot.gui import Application
from kde_bot.selfcheck import check_background_schedule, check_desktop_instance, check_native_tray


def moment(value):
    return datetime.fromisoformat(value).replace(tzinfo=BANGKOK).timestamp()


def test_packaged_schedule_contract(tmp_path):
    check_background_schedule(tmp_path)


def test_native_instance_and_tray_lifecycle():
    check_desktop_instance()
    check_native_tray()


@pytest.mark.parametrize('value,expected', [
    ('2026-10-17T21:59:59', None),
    ('2026-10-17T22:00:00', '2026-10-17'),
    ('2026-10-18T00:00:00', '2026-10-17'),
    ('2026-10-18T04:59:59', '2026-10-17'),
    ('2026-10-18T05:00:00', None),
])
def test_bangkok_boundaries(value, expected):
    assert overnight_key(moment(value)) == expected


def test_clock_skips_missed_night_and_does_not_fire_late_resume_at_night():
    clock = BackgroundClock(moment('2026-10-17T21:59:59'))
    assert clock.tick(moment('2026-10-18T23:00:00')) == []
    assert clock.tick(moment('2026-10-19T05:00:00')) == ['resume']
    assert clock.tick(moment('2026-10-19T22:00:00')) == ['cleanup']
    assert clock.tick(moment('2026-10-19T22:00:01')) == []


@pytest.mark.parametrize('record', ['invalid', {'manual_night': '2026-1-1'}, {'manual_night': []}])
def test_invalid_schedule_is_not_silently_reset(tmp_path, record):
    history = History(tmp_path)
    history.data['tracking_schedule'] = record
    history.save()
    original = history.path.read_bytes()
    with pytest.raises(ValueError, match='tracking schedule'):
        History(tmp_path)
    assert history.path.read_bytes() == original


def test_manual_resume_cannot_publish_state_during_another_history_write(tmp_path):
    history = History(tmp_path)
    original_lock = history.lock
    attempted = threading.Event()
    resume_thread_id = []
    errors = []

    class ObservedLock:
        def __enter__(self):
            if resume_thread_id and threading.get_ident() == resume_thread_id[0]:
                attempted.set()
            original_lock.acquire()
            return self

        def __exit__(self, *_args):
            original_lock.release()

    history.lock = ObservedLock()
    def resume():
        resume_thread_id.append(threading.get_ident())
        try:
            TrackingHours(history).resume_manually(moment('2026-10-17T23:00:00'))
        except Exception as error:
            errors.append(error)

    with history.lock:
        thread = threading.Thread(target=resume)
        thread.start()
        reached_lock = attempted.wait(3)
        state_changed_during_write = 'tracking_schedule' in history.data
    thread.join(3)
    assert reached_lock and not state_changed_during_write and not thread.is_alive() and not errors
    assert TrackingHours(History(tmp_path)).allowed(moment('2026-10-18T04:00:00'))


def app_shell():
    app = object.__new__(Application)
    app.root = Mock()
    app.smoke = False
    app.closing = False
    app.worker = None
    app.maintenance_worker = None
    app.stop_event = threading.Event()
    app.maintenance_stop = threading.Event()
    app.requests = queue.Queue()
    app.resume_pending = False
    app.resume_manual = False
    app.hide_passwords = Mock()
    app.status = Mock()
    return app


def test_window_close_hides_without_stopping_tracking_or_maintenance():
    app = app_shell()
    ready = threading.Event()
    ready.set()
    app.tray = SimpleNamespace(ready=ready, error=None, stopped=threading.Event())
    app.close()
    app.root.withdraw.assert_called_once()
    assert not app.stop_event.is_set() and not app.maintenance_stop.is_set()
    app.root.destroy.assert_not_called()


def test_window_stays_accessible_when_tray_failed():
    app = app_shell()
    app.tray = None
    app.close()
    app.root.withdraw.assert_not_called()
    app.root.destroy.assert_not_called()


def test_manual_open_resumes_existing_worker_without_new_download_round():
    app = app_shell()
    app.worker = SimpleNamespace(is_alive=lambda: True)
    app.show_window()
    app.root.deiconify.assert_called_once()
    assert app.requests.get_nowait() == {'kind': 'resume_tracking'}
    assert app.requests.empty()


def test_manual_resume_waits_for_maintenance():
    app = app_shell()
    app.maintenance_worker = SimpleNamespace(is_alive=lambda: True)
    app.auto_start = Mock()
    app.resume_tracking()
    assert app.resume_pending and app.resume_manual
    app.auto_start.assert_not_called()


def test_full_exit_signals_both_workers():
    app = app_shell()
    app.stop = Mock(side_effect=app.stop_event.set)
    app.wait_to_close = Mock()
    app.exit_fully()
    assert app.closing and app.stop_event.is_set() and app.maintenance_stop.is_set()
    app.wait_to_close.assert_called_once()


def test_monitor_finishes_active_account_but_does_not_start_post_until_manual_open(tmp_path):
    from kde_bot import daily_download as daily
    settings = default_settings()
    settings['daily_cleanup_enabled'] = False
    for index, account in enumerate(settings['accounts']):
        account['username'] = f'user-{index}'
    history = History(tmp_path)
    events = []
    reporter = Reporter(history, events.append)
    commands = queue.Queue()
    stop = threading.Event()
    clock = [moment('2026-10-17T21:55:00')]
    boundary = moment('2026-10-17T22:00:00')
    submissions = []
    scans = []
    cleanup_ticks = []

    class Future:
        def __init__(self, ready):
            self.ready = ready

        def done(self):
            return clock[0] >= self.ready

        def result(self):
            return {'kind': 'complete', 'reason': 'Offline account finished'}

    class Pool:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def submit(self, _function, _settings, job, *_args):
            submissions.append((job['account'], clock[0]))
            return Future(max(clock[0], boundary + 10))

    def wait(_seconds):
        clock[0] += 10
        if clock[0] == boundary + 30:
            assert [account for account, _now in submissions] == ['user-0']
            assert not any(boundary <= now <= boundary + 20 for now in scans)
            commands.put({'kind': 'resume_tracking'})
        if len(submissions) == 2:
            stop.set()
        assert clock[0] < boundary + 90
        return stop.is_set()

    def scan(*_args):
        scans.append(clock[0])
        return []

    fake_cleanup = SimpleNamespace(tick=lambda now, active, _stop: cleanup_ticks.append((now, active)) or False)
    with patch.object(daily, 'today', return_value='2026-10-17'), \
            patch.object(daily.time, 'time', side_effect=lambda: clock[0]), \
            patch.object(daily, 'ThreadPoolExecutor', Pool), \
            patch.object(daily, 'scan_arrivals', side_effect=scan), \
            patch('kde_bot.cleanup.DailyCleanup', return_value=fake_cleanup), \
            patch.object(stop, 'wait', side_effect=wait):
        daily.run_daily_monitor(settings, stop, reporter, history, tmp_path, True, commands, request_round=True)
    assert submissions[0][1] < boundary and submissions[1][1] >= boundary + 30
    assert any(now >= boundary and active for now, active in cleanup_ticks)
    assert [event['paused'] for event in events if event.get('kind') == 'schedule_status'] == [False, True, False]
    assert TrackingHours(History(tmp_path)).allowed(boundary + 60)


def test_startup_preference_migrates_without_losing_existing_settings():
    settings = normalize_settings({'start_with_windows': False, 'new_dir': r'\\10.0.0.97\Z Bot KDE'})
    assert settings['start_with_windows'] is False
    assert normalize_settings({})['start_with_windows'] is True
    settings['start_with_windows'] = 'yes'
    with pytest.raises(ValueError, match='startup'):
        validate_settings(settings, require_credentials=False)


@pytest.mark.parametrize('enabled,previous,writes,deletes', [
    (True, None, 1, 0),
    (True, 'matching', 1, 0),
    (False, 'matching', 0, 1),
    (False, None, 0, 0),
])
def test_startup_only_changes_owned_value_with_mock_registry(tmp_path, enabled, previous, writes, deletes):
    import subprocess
    import winreg
    from kde_bot.startup import configure_startup, VALUE_NAME, RUN_KEY
    executable = tmp_path / 'portable' / 'KDE Bot Download V3.exe'
    command = subprocess.list2cmdline([str(executable.resolve()), '--background'])
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=True), \
            patch('kde_bot.startup.sys.frozen', True, create=True), \
            patch('winreg.CreateKeyEx') as create, \
            patch('winreg.QueryValueEx') as read, \
            patch('winreg.SetValueEx') as write, patch('winreg.DeleteValue') as delete:
        if previous is None:
            read.side_effect = FileNotFoundError()
        else:
            read.return_value = (command, winreg.REG_SZ)
        configure_startup(enabled, executable)
        assert create.call_args.args[:2] == (winreg.HKEY_CURRENT_USER, RUN_KEY)
        assert write.call_count == writes and delete.call_count == deletes
        if writes:
            assert write.call_args.args[1:] == (VALUE_NAME, 0, winreg.REG_SZ, command)
        if deletes:
            assert delete.call_args.args[1] == VALUE_NAME


@pytest.mark.parametrize('enabled', [True, False])
def test_startup_refuses_conflicting_command_without_registry_changes(tmp_path, enabled):
    import winreg
    from kde_bot.startup import configure_startup
    executable = tmp_path / 'portable' / 'KDE Bot Download V3.exe'
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=True), \
            patch('kde_bot.startup.sys.frozen', True, create=True), \
            patch('winreg.CreateKeyEx'), \
            patch('winreg.QueryValueEx', return_value=('another-program.exe', winreg.REG_SZ)), \
            patch('winreg.SetValueEx') as write, patch('winreg.DeleteValue') as delete:
        with pytest.raises(RuntimeError):
            configure_startup(enabled, executable)
        write.assert_not_called()
        delete.assert_not_called()


@pytest.mark.parametrize('background,existing,notifications,launches', [
    (False, True, 1, 0),
    (True, True, 0, 0),
    (True, False, 0, 1),
    (False, False, 0, 1),
])
def test_main_manual_duplicate_reopens_but_startup_duplicate_stays_hidden(background, existing, notifications, launches):
    from main import main
    instance = Mock(existing=existing)
    with patch('sys.argv', ['KDE'] + (['--background'] if background else [])), \
            patch('kde_bot.desktop.DesktopInstance', return_value=instance), \
            patch('kde_bot.gui.launch', return_value=0) as launch:
        assert main() == 0
        assert instance.notify.call_count == notifications
        assert launch.call_count == launches
        instance.close.assert_called_once()
        if launches:
            assert launch.call_args.kwargs == {'background': background, 'instance': instance}


def test_0500_existing_monitor_resumes_naturally_without_manual_override():
    app = app_shell()
    app.worker = SimpleNamespace(is_alive=lambda: True)
    app.resume_tracking(manual=False)
    assert app.requests.empty() and not app.resume_pending


def test_maintenance_clock_keeps_running_after_stop():
    app = app_shell()
    app.stop_event.set()
    app.instance = None
    app.background_clock = Mock()
    app.background_clock.tick.return_value = ['cleanup', 'resume']
    app.start_maintenance = Mock()
    app.resume_tracking = Mock()
    app.render_jobs = Mock()
    app.tick()
    app.start_maintenance.assert_called_once()
    app.resume_tracking.assert_called_once_with(manual=False)
    app.root.after.assert_called_once()


def test_background_monitor_resumes_email_scans_at_0500_without_manual_open(tmp_path):
    from kde_bot import daily_download as daily
    settings = default_settings()
    history = History(tmp_path)
    events = []
    reporter = Reporter(history, events.append)
    stop = threading.Event()
    clock = [moment('2026-10-18T04:59:59')]
    scans = []

    def wait(_seconds):
        clock[0] += 1
        assert clock[0] <= moment('2026-10-18T05:00:01')
        return False

    def scan(*_args):
        scans.append(clock[0])
        stop.set()
        return []

    fake_cleanup = SimpleNamespace(tick=lambda *_args: False)
    with patch.object(daily, 'today', return_value='2026-10-18'), \
            patch.object(daily.time, 'time', side_effect=lambda: clock[0]), \
            patch.object(daily, 'scan_arrivals', side_effect=scan), \
            patch('kde_bot.cleanup.DailyCleanup', return_value=fake_cleanup), \
            patch.object(stop, 'wait', side_effect=wait):
        daily.run_daily_monitor(settings, stop, reporter, history, tmp_path, True, queue.Queue())
    assert scans == [moment('2026-10-18T05:00:00')]
    assert [event['paused'] for event in events if event.get('kind') == 'schedule_status'] == [True, False]
    assert 'tracking_schedule' not in history.data


@pytest.mark.parametrize('blocking_operation', ['mail_scan', 'cleanup_tick'])
def test_blocking_work_crossing_2200_cannot_start_another_account(tmp_path, blocking_operation):
    from kde_bot import daily_download as daily
    settings = default_settings()
    history = History(tmp_path)
    reporter = Reporter(history, lambda _event: None)
    stop = threading.Event()
    clock = [moment('2026-10-17T21:59:59')]
    pending = Mock()
    pending.state = {'pending_due': None, 'jobs': {}}
    pending.snapshot.return_value = []
    pending.ingest.return_value = 0

    def block():
        clock[0] = moment('2026-10-17T22:00:01')

    def scan(*_args):
        if blocking_operation == 'mail_scan':
            block()
        return []

    def cleanup_tick(*_args):
        if blocking_operation == 'cleanup_tick':
            block()
        return False

    def wait(_seconds):
        stop.set()
        return True

    with patch.object(daily.time, 'time', side_effect=lambda: clock[0]), \
            patch.object(daily, 'DailyQueue', return_value=pending), \
            patch.object(daily, 'scan_arrivals', side_effect=scan), \
            patch('kde_bot.cleanup.DailyCleanup', return_value=SimpleNamespace(tick=cleanup_tick)), \
            patch.object(stop, 'wait', side_effect=wait):
        daily.run_daily_monitor(settings, stop, reporter, history, tmp_path, True, queue.Queue())
    pending.claim.assert_not_called()
