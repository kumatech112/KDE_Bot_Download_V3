from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kde_bot import cleanup
from kde_bot import daily_download as daily
from kde_bot.cleanup_task import task_definition, configure_task, scheduler_error_code
from kde_bot.evidence import BANGKOK
from kde_bot.settings import default_settings
from kde_bot.storage import Delivery, History, Reporter, WorkerLock
from kde_bot.workflow import make_engine_settings


@pytest.fixture
def context(tmp_path, monkeypatch):
    settings = default_settings()
    for key in ('original_dir', 'new_dir', 'log_dir'):
        folder = tmp_path / key
        folder.mkdir()
        settings[key] = str(folder)
    monkeypatch.setattr(cleanup, 'APPROVED_ROOTS', (settings['original_dir'], settings['new_dir']))
    clock = [datetime(2026, 10, 17, 21, 59, 59, tzinfo=BANGKOK)]
    monkeypatch.setattr(cleanup, 'current_time', lambda: clock[0])
    monkeypatch.setattr(daily, 'today', lambda: clock[0].date().isoformat())
    monkeypatch.setenv('KDE_V3_HOME', str(tmp_path / 'local'))
    history = History(Path(settings['log_dir']))
    events = []
    reporter = Reporter(history, events.append)
    stop = threading.Event()
    return settings, history, reporter, events, clock, stop


def at_ten(clock):
    clock[0] = clock[0].replace(hour=22, minute=0, second=0)
    return clock[0].timestamp()


def test_both_roots_cleanup_at_2200_keeps_every_subfolder_and_no_redownload(context):
    settings, history, reporter, events, clock, stop = context
    for key in ('original_dir', 'new_dir'):
        root = Path(settings[key])
        (root / 'download.zip').write_bytes(b'final download')
        for name in ('03 Check', 'Checked', 'Check', 'Unrelated folder'):
            folder = root / name
            folder.mkdir()
            (folder / 'protected.zip').write_bytes(b'keep')
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    scheduler.tick(clock[0].timestamp(), False, stop)
    assert (Path(settings['new_dir']) / 'download.zip').is_file()
    scheduler.tick(at_ten(clock), False, stop)
    for key in ('original_dir', 'new_dir'):
        root = Path(settings[key])
        assert not (root / 'download.zip').exists()
        assert len(list(root.glob('*/protected.zip'))) == 4
    assert history.data['daily_cleanup']['status'] == 'complete'
    assert history.data['daily_cleanup']['deleted_names'] == ['download.zip']
    assert history.data['daily_cleanup']['pending_names'] == []
    assert len([event for event in events if event.get('filename') == 'download.zip' and event['status'] == 'stage_complete']) == 2
    # Reloaded shared state, not the destination's now-empty contents, prevents re-download.
    restored = History(history.folder)
    settings['accounts'][0]['username'] = 'offline-pre'
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / 'engine.json'), reporter,
                                   Delivery(restored, reporter), settings, stop, '2026-10-17')
    with patch.object(engine, 'download_to_cache', side_effect=AssertionError('Purged file downloaded again')):
        assert engine.handle_file(None, 0, {'filename': 'DOWNLOAD.ZIP', 'file_time': '17/10/2026'}, engine.settings.accounts[0], 1000) == 'skipped'


def test_once_per_day_restart_does_not_delete_later_arrivals(context):
    settings, history, reporter, events, clock, stop = context
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    scheduler.tick(at_ten(clock), False, stop)
    late = Path(settings['new_dir']) / 'arrived-later.zip'
    late.write_bytes(b'late')
    scheduler.tick(clock[0].timestamp() + 1, False, stop)
    restored = cleanup.DailyCleanup(settings, History(history.folder), reporter, clock[0].timestamp())
    restored.tick(clock[0].timestamp() + 2, False, stop)
    assert late.read_bytes() == b'late'


def test_wait_for_active_download_and_both_roots_even_in_new_only_mode(context):
    settings, history, reporter, events, clock, stop = context
    settings['storage_mode'] = 'new'
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    target = Path(settings['original_dir']) / 'original.zip'
    target.write_bytes(b'data')
    assert scheduler.tick(at_ten(clock), True, stop)
    assert target.is_file() and 'daily_cleanup' not in history.data
    assert scheduler.tick(clock[0].timestamp() + 1, True, stop)
    assert len([event for event in events if event['status'] == 'waiting']) == 1
    scheduler.tick(clock[0].timestamp() + 2, False, stop)
    assert not target.exists()


def test_wrong_root_refused_without_deleting_and_other_root_still_works(context, tmp_path):
    settings, history, reporter, events, clock, stop = context
    unrelated = tmp_path / 'outside'
    unrelated.mkdir()
    preserved = unrelated / 'important.zip'
    preserved.write_bytes(b'keep')
    settings['original_dir'] = str(unrelated)
    allowed = Path(settings['new_dir']) / 'allowed.zip'
    allowed.write_bytes(b'delete')
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    scheduler.tick(at_ten(clock), False, stop)
    assert preserved.read_bytes() == b'keep' and not allowed.exists()
    assert history.data['daily_cleanup']['status'] == 'errors'


def test_locked_file_reports_failure_without_tombstone_and_keeps_going(context):
    settings, history, reporter, events, clock, stop = context
    root = Path(settings['new_dir'])
    locked = root / 'a-locked.zip'
    locked.write_bytes(b'locked')
    other = root / 'b-other.zip'
    other.write_bytes(b'data')
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    with locked.open('rb'):
        scheduler.tick(at_ten(clock), False, stop)
    assert locked.read_bytes() == b'locked' and not other.exists()
    assert history.data['daily_cleanup']['status'] == 'errors'
    assert history.data['daily_cleanup']['deleted_names'] == ['b-other.zip']
    assert history.data['daily_cleanup']['pending_names'] == []
    assert any(event['status'] == 'error' and event['filename'] == locked.name for event in events)


def test_stop_and_disabled_cleanup_do_not_delete(context):
    settings, history, reporter, events, clock, stop = context
    target = Path(settings['new_dir']) / 'keep.zip'
    target.write_bytes(b'keep')
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    settings['daily_cleanup_enabled'] = False
    scheduler.tick(at_ten(clock), False, stop)
    settings['daily_cleanup_enabled'] = True
    stop.set()
    scheduler.tick(clock[0].timestamp(), False, stop)
    assert target.exists() and 'daily_cleanup' not in history.data


def test_midnight_does_not_delete_new_day_files(context):
    settings, history, reporter, events, clock, stop = context
    target = Path(settings['new_dir']) / 'new-day.zip'
    target.write_bytes(b'keep')
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    clock[0] = (clock[0] + timedelta(days=1)).replace(hour=0, minute=1)
    scheduler.tick(clock[0].timestamp(), False, stop)
    assert target.is_file() and 'daily_cleanup' not in history.data
    assert datetime.fromtimestamp(scheduler.due, BANGKOK).hour == 22


def test_scheduled_headless_worker_deletes_without_gui_and_cleans_request(context):
    settings, history, reporter, events, clock, stop = context
    target = Path(settings['new_dir']) / 'headless.zip'
    target.write_bytes(b'data')
    assert cleanup.run_scheduled_cleanup(settings) == 0  # Early invocation does nothing.
    assert target.exists()
    at_ten(clock)
    assert cleanup.run_scheduled_cleanup(settings) == 0
    assert not target.exists() and not cleanup.request_path(settings).exists()
    assert History(history.folder).data['daily_cleanup']['status'] == 'complete'


def test_task_cooperates_with_running_gui_through_shared_lock(context):
    settings, history, reporter, events, clock, stop = context
    target = Path(settings['new_dir']) / 'cooperative.zip'
    target.write_bytes(b'data')
    scheduler = cleanup.DailyCleanup(settings, history, reporter, clock[0].timestamp())
    at_ten(clock)
    def advance(_seconds):
        assert cleanup.request_path(settings).is_file()
        assert target.exists()
        scheduler.tick(clock[0].timestamp(), False, stop)
        return False
    with WorkerLock(history.folder), patch.object(stop, 'wait', side_effect=advance):
        assert cleanup.run_scheduled_cleanup(settings, stop) == 0
    assert not target.exists() and not cleanup.request_path(settings).exists()


def test_interrupted_cleanup_is_not_repeated_and_pending_name_blocks_redownload(context):
    settings, history, reporter, events, clock, stop = context
    at_ten(clock)
    history.data['daily_cleanup'] = {'day': '2026-10-17', 'status': 'running', 'roots': {},
                                     'pending_names': ['uncertain.zip'], 'deleted_names': []}
    history.save()
    assert cleanup.run_scheduled_cleanup(settings) == 1
    restored = History(history.folder)
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / 'engine.json'), reporter,
                                   Delivery(restored, reporter), settings, stop, '2026-10-17')
    with patch.object(engine, 'download_to_cache', side_effect=AssertionError('Uncertain deletion redownloaded')):
        assert engine.handle_file(None, 0, {'filename': 'uncertain.zip', 'file_time': '17/10/2026'}, engine.settings.accounts[0], 1000) == 'skipped'


def test_corrupt_cleanup_state_preserved(context):
    settings, history, reporter, events, clock, stop = context
    history.data['daily_cleanup'] = {'day': '2026-10-17', 'status': 'complete', 'roots': {}, 'deleted_names': ['../outside.zip']}
    history.save()
    original = history.path.read_bytes()
    with pytest.raises(ValueError, match='cleanup filename'):
        History(history.folder)
    assert history.path.read_bytes() == original


def test_task_definition_has_2200_bangkok_daily_interactive_user_no_password(tmp_path):
    trigger = SimpleNamespace()
    action = SimpleNamespace()
    definition = SimpleNamespace(RegistrationInfo=SimpleNamespace(), Principal=SimpleNamespace(), Settings=SimpleNamespace(),
                                 Triggers=SimpleNamespace(Create=lambda kind: trigger if kind == 2 else None),
                                 Actions=SimpleNamespace(Create=lambda kind: action if kind == 0 else None))
    result = task_definition(SimpleNamespace(NewTask=lambda _flags: definition), tmp_path / 'KDE Bot Download V3.exe',
                             'S-1-offline', datetime(2026, 10, 17, 16, tzinfo=BANGKOK))
    assert trigger.StartBoundary == '2026-10-17T22:00:00+07:00' and trigger.DaysInterval == 1
    assert result.Principal.LogonType == 3 and result.Principal.RunLevel == 0
    assert action.Arguments == '--scheduled-cleanup'
    assert result.Settings.StartWhenAvailable is False and result.Settings.MultipleInstances == 2


@pytest.mark.parametrize('wrapped', [False, True])
def test_task_registration_and_disable_are_own_user_only_and_never_run_now(tmp_path, wrapped):
    import win32com.client
    import pywintypes
    portable = tmp_path / 'portable'
    portable.mkdir()
    executable = portable / 'KDE Bot Download V3.exe'
    executable.write_bytes(b'offline placeholder, never executed')
    trigger = SimpleNamespace()
    action = SimpleNamespace()
    definition = SimpleNamespace(RegistrationInfo=SimpleNamespace(), Principal=SimpleNamespace(), Settings=SimpleNamespace(),
        Triggers=SimpleNamespace(Create=lambda _kind: trigger, Count=1, Item=lambda _index: trigger),
        Actions=SimpleNamespace(Create=lambda _kind: action, Count=1, Item=lambda _index: action))
    registered = [None]
    calls = []
    def get_task(_name):
        if registered[0] is None:
            if wrapped:
                raise pywintypes.com_error(-2147352567, 'Exception occurred.', (0, None, None, None, 0, -2147024894), None)
            raise pywintypes.com_error(-2147024894, 'Task not found', None, None)
        return registered[0]
    def register(*args):
        calls.append(('register', args))
        registered[0] = SimpleNamespace(Definition=args[1], Enabled=True)
        return registered[0]
    root = SimpleNamespace(GetTask=get_task, RegisterTaskDefinition=register,
                           DeleteTask=lambda *args: calls.append(('delete', args)))
    service = SimpleNamespace(Connect=lambda: None, GetFolder=lambda _path: root, NewTask=lambda _flags: definition)
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=True), \
            patch('kde_bot.cleanup_task.sys.frozen', True, create=True), \
            patch.object(win32com.client, 'Dispatch', return_value=service):
        assert configure_task(True, executable)['installed'] is True
        arguments = calls[0][1]
        assert arguments[2] == 6 and arguments[4] is None and arguments[5] == 3
        assert definition.Principal.UserId == arguments[3]
        assert configure_task(False, executable)['installed'] is False
        assert calls[-1][0] == 'delete'
        registered[0].Definition.Actions.Item(1).Path = str(tmp_path / 'other.exe')
        with pytest.raises(RuntimeError, match='โปรแกรมอื่น'):
            configure_task(True, executable)


def test_task_setup_cannot_register_on_another_machine():
    import win32com.client
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=False), \
            patch.object(win32com.client, 'Dispatch', side_effect=AssertionError('Registration outside .97')):
        assert configure_task(True)['installed'] is False


def test_filename_tombstone_expires_next_day_and_keeps_extension_identity(context):
    settings, history, reporter, events, clock, stop = context
    history.data['daily_cleanup'] = {'day': '2026-10-17', 'status': 'complete', 'roots': {}, 'deleted_names': ['report.zip.gpg'], 'pending_names': []}
    assert cleanup.was_cleaned(history, 'REPORT.ZIP.GPG')
    assert not cleanup.was_cleaned(history, 'report.xlsx.gpg')
    assert not cleanup.was_cleaned(history, 'report.zip.gpg', '2026-10-18')


def test_pending_save_repair_cannot_restore_cleaned_file(context, tmp_path):
    from kde_bot.workflow import run_cycle
    from kde_bot.storage import file_hash
    settings, history, reporter, events, clock, stop = context
    at_ten(clock)
    settings['accounts'][0].update(username='offline-pre', password='offline-only')
    settings['accounts'][1]['enabled'] = False
    source = tmp_path / 'local' / 'cache' / 'purged.download'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'old download')
    history.data['files']['saved'] = {'account': 'offline-pre', 'filename': 'purged.zip', 'pending': [settings['new_dir']],
                                     'source_hint': str(source), 'sha256': file_hash(source), 'download_policy': 'daily_all'}
    history.data['daily_cleanup'] = {'day': '2026-10-17', 'status': 'complete', 'roots': {}, 'deleted_names': ['purged.zip'], 'pending_names': []}
    history.save()
    run_cycle(settings, stop, events.append, retry_only=True)
    assert not (Path(settings['new_dir']) / 'purged.zip').exists()
    assert source.exists()


def test_concurrent_request_writers_leave_valid_atomic_request(context):
    from concurrent.futures import ThreadPoolExecutor
    settings, history, reporter, events, clock, stop = context
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda index: cleanup.write_request(settings, '2026-10-17', str(index)), range(8)))
    assert json.loads(cleanup.request_path(settings).read_text())['day'] == '2026-10-17'
    assert not list(history.folder.glob('*.tmp'))


@pytest.mark.parametrize('corrupt', [False, True])
def test_scheduled_entry_rejects_missing_or_corrupt_user_settings_without_deleting(context, tmp_path, corrupt):
    from main import scheduled_cleanup_entry
    settings, history, reporter, events, clock, stop = context
    local = tmp_path / 'local'
    local.mkdir(exist_ok=True)
    if corrupt:
        (local / 'settings.json').write_text('{broken', encoding='utf-8')
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=True), \
            patch('kde_bot.cleanup.run_scheduled_cleanup', side_effect=AssertionError('Invalid settings allowed deletion')):
        assert scheduled_cleanup_entry() == 1
    assert json.loads((local / 'cleanup_task_result.json').read_text(encoding='utf-8'))['exit_code'] == 1


@pytest.mark.parametrize('outer,details,expected', [
    (-2147024894, None, 0x80070002),
    (-2147352567, (0, None, None, None, 0, -2147024894), 0x80070002),
    (-2147352567, (0, None, None, None, 0, -2147024891), 0x80070005),
    (-2147352567, None, 0x80020009),
    (-2147352567, (0, None), 0x80020009),
    (-2147024891, (0, None, None, None, 0, -2147024894), 0x80070005),
])
def test_scheduler_hresult_only_unwraps_actual_dispatch_exception(outer, details, expected):
    import pywintypes
    assert scheduler_error_code(pywintypes.com_error(outer, 'Exception occurred.', details, None)) == expected


def test_scheduler_hresult_args_fallback_does_not_parse_error_text():
    assert scheduler_error_code(Exception(-2147352567, 'Exception occurred.', (0, None, None, None, 0, -2147024894), None)) == 0x80070002
    assert scheduler_error_code(Exception('file not found -2147024894')) is None


@pytest.mark.parametrize('stage', ['lookup', 'register'])
def test_unexpected_scheduler_errors_fail_with_stage_without_claiming_installed(tmp_path, stage):
    import pywintypes
    import win32com.client
    executable = tmp_path / 'portable' / 'KDE Bot Download V3.exe'
    executable.parent.mkdir()
    executable.write_bytes(b'never executed')
    def lookup(_name):
        code = -2147024891 if stage == 'lookup' else -2147024894
        raise pywintypes.com_error(-2147352567, 'Exception occurred.', (0, None, None, None, 0, code), None)
    def register(*_args):
        raise pywintypes.com_error(-2147352567, 'Exception occurred.', (0, None, None, None, 0, -2147024894), None)
    root = SimpleNamespace(GetTask=lookup, RegisterTaskDefinition=register)
    service = SimpleNamespace(Connect=lambda: None, GetFolder=lambda _path: root)
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=True), \
            patch('kde_bot.cleanup_task.sys.frozen', True, create=True), \
            patch.object(win32com.client, 'Dispatch', return_value=service), \
            patch('kde_bot.cleanup_task.task_definition', return_value=object()):
        expected = 'ตรวจสอบงานลบไฟล์เดิม' if stage == 'lookup' else 'ลงทะเบียนงานลบไฟล์'
        with pytest.raises(RuntimeError, match=expected):
            configure_task(True, executable)
