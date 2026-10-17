from pathlib import Path
import subprocess
import threading
from unittest.mock import patch

import pytest

from kde_bot import cleanup, daily_download as daily, storage
from kde_bot.settings import default_settings, normalize_settings
from kde_bot.startup import KNOWN_EXECUTABLES, configure_startup, owned_startup_commands
from kde_bot.workflow import make_engine_settings
from test_daily_download import setup, DAY


@pytest.mark.parametrize('log', [r"\\10.0.0.97\Z Log\Log Bot KDE",
                                 r"\\10.0.0.97\Z Log Bot\Log Bot KDE",
                                 r"\\10.0.0.97\Z Bot KDE"])
def test_known_path_migration_preserves_accounts_and_preferences(log):
    raw = default_settings()
    raw.update(new_dir='//10.0.0.97/Z Bot KDE/', log_dir=log, mail_delay_seconds=330)
    raw['accounts'][0].update(username='preserved', password='local-only')
    result = normalize_settings(raw)
    assert result['new_dir'] == r"\\10.0.0.97\Z KDE Bot"
    assert result['log_dir'] == r"\\10.0.0.97\Z Log Bot\KDE Log Bot"
    assert result['accounts'] == raw['accounts'] and result['mail_delay_seconds'] == 330
    assert normalize_settings(result) == result
    assert result['new_dir'] in cleanup.APPROVED_ROOTS
    raw.update(new_dir=r"\\custom\files", log_dir=r"\\custom\logs")
    result = normalize_settings(raw)
    assert result['new_dir'] == raw['new_dir'] and result['log_dir'] == raw['log_dir']


@pytest.mark.parametrize('failure', [None, 'original_dir', 'new_dir'])
def test_daily_publication_uses_verified_243_before_97_and_recovers(setup, tmp_path, failure):
    settings, history, reporter, events = setup
    engine = daily.DailyDownloader(make_engine_settings(settings, history.folder / 'engine.json'), reporter,
                                   storage.Delivery(history, reporter), settings, threading.Event(), DAY)
    filename = 'today.zip.gpg'
    source = tmp_path / 'local/cache/source.download'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'portal payload')
    copies = []
    real_copy = storage.verified_copy
    def copy(incoming, target, digest):
        copies.append((incoming, target))
        if failure and target.parent == Path(settings[failure]):
            raise PermissionError('simulated destination denial')
        if target.parent == Path(settings['new_dir']):
            assert incoming == Path(settings['original_dir']) / filename
            assert incoming.read_bytes() == source.read_bytes()
        real_copy(incoming, target, digest)
    row = {'filename': filename, 'file_time': '16/10/2026'}
    with patch.object(engine, 'download_to_cache', return_value=source) as download, \
            patch('kde_bot.storage.verified_copy', side_effect=copy):
        status = engine.handle_file(None, 0, row, engine.settings.accounts[0], 1000)
    download.assert_called_once()
    assert copies[0] == (source, Path(settings['original_dir']) / filename)
    assert status == ('complete' if failure is None else 'copy_pending')
    if failure == 'original_dir':
        assert len(copies) == 1 and list(Path(settings['new_dir']).iterdir()) == []
    if failure:
        assert source.exists()
        record = next(iter(history.data['files'].values()))
        assert str(Path(settings[failure])) in record['pending']
        with patch.object(engine, 'download_to_cache', side_effect=AssertionError('second portal download')):
            assert engine.handle_file(None, 0, row, engine.settings.accounts[0], 1000) == 'complete'
    for key in ('original_dir', 'new_dir'):
        assert (Path(settings[key]) / filename).read_bytes() == b'portal payload'
        assert [entry.name for entry in Path(settings[key]).iterdir()] == [filename]
    assert not source.exists()


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('current_index', [1, 2])
def test_startup_migrates_only_known_own_legacy_command(enabled, current_index):
    import winreg
    executable = Path(KNOWN_EXECUTABLES[current_index])
    old_command = subprocess.list2cmdline([KNOWN_EXECUTABLES[0], '--background'])
    with patch('kde_bot.cleanup_task.on_cleanup_machine', return_value=True), \
            patch('kde_bot.startup.sys.frozen', True, create=True), \
            patch('winreg.CreateKeyEx'), \
            patch('winreg.QueryValueEx', return_value=(old_command, winreg.REG_SZ)), \
            patch('winreg.SetValueEx') as write, patch('winreg.DeleteValue') as delete:
        configure_startup(enabled, executable)
        assert write.call_count == int(enabled) and delete.call_count == int(not enabled)
        if enabled:
            assert write.call_args.args[-1] == subprocess.list2cmdline([str(executable.resolve()), '--background'])
    assert old_command not in owned_startup_commands(Path(r'C:\Other\portable\KDE Bot Download V3.exe'))
    assert old_command + ' --extra' not in owned_startup_commands(executable)
