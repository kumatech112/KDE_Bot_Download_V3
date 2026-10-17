"""Exercise the real EXE's background/reopen/exit path with isolated settings."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import win32con
import win32gui
import win32process

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kde_bot.settings import default_settings
from kde_bot.cleanup_task import on_cleanup_machine


def windows_for(process_id):
    found = {}
    def visit(hwnd, _context):
        if win32process.GetWindowThreadProcessId(hwnd)[1] == process_id:
            title = win32gui.GetWindowText(hwnd)
            if title in {'KDE Download', 'KDE background'}:
                found[title] = hwnd
        return True
    win32gui.EnumWindows(visit, None)
    return found


def wait_until(predicate, process, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f'Test instance exited early: {process.returncode}')
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise TimeoutError('Isolated background check timed out')


def verify(executable, output):
    if executable.name != 'KDE Bot Download V3.exe':
        raise ValueError('Select the KDE executable under test')
    if on_cleanup_machine() and executable.parent.name.casefold() in {'program', 'portable'}:
        raise ValueError('On .97, use a staged bundle so checks cannot alter production startup/task settings')
    result = {'exe_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'live_portal_access': False, 'business_files_modified': False,
              'startup_registered_live': False, 'task_registered_live': False}
    with tempfile.TemporaryDirectory(prefix='kde-background-check-') as temporary:
        home = Path(temporary)
        settings = default_settings()
        for key in ('log_dir', 'original_dir', 'new_dir'):
            folder = home / key
            folder.mkdir()
            settings[key] = str(folder)
        settings['daily_cleanup_enabled'] = False
        settings['start_with_windows'] = False
        (home / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
        environment = os.environ.copy()
        environment['KDE_V3_HOME'] = str(home)
        process = subprocess.Popen([str(executable), '--background'], env=environment,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            windows = wait_until(lambda: windows_for(process.pid) if len(windows_for(process.pid)) == 2 else None, process)
            assert not win32gui.IsWindowVisible(windows['KDE Download'])
            result['starts_hidden'] = True
            duplicate = subprocess.run([str(executable), '--background'], env=environment, timeout=20,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            assert duplicate.returncode == 0 and not win32gui.IsWindowVisible(windows['KDE Download'])
            result['background_duplicate_stays_hidden'] = True
            manual = subprocess.run([str(executable)], env=environment, timeout=20,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            assert manual.returncode == 0
            wait_until(lambda: win32gui.IsWindowVisible(windows['KDE Download']), process)
            assert windows_for(process.pid)['KDE Download'] == windows['KDE Download']
            result['manual_reopens_same_window'] = True
            win32gui.PostMessage(windows['KDE Download'], win32con.WM_CLOSE, 0, 0)
            wait_until(lambda: not win32gui.IsWindowVisible(windows['KDE Download']), process)
            assert process.poll() is None
            result['x_hides_and_keeps_process'] = True
            win32gui.PostMessage(windows['KDE background'], win32con.WM_COMMAND, 300, 0)
            assert process.wait(timeout=20) == 0
            result['tray_exit_stops_process'] = True
            result['status'] = 'passed'
        finally:
            if process.poll() is None:
                windows = windows_for(process.pid)
                if 'KDE background' in windows:
                    win32gui.PostMessage(windows['KDE background'], win32con.WM_COMMAND, 300, 0)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    # Only our isolated, newly spawned test process may be stopped.
                    process.terminate()
                    process.wait(timeout=10)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.exe.resolve(strict=True), arguments.output)))


if __name__ == '__main__':
    main()
