"""Create the project's normal-permission launcher for the stable Program bundle."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Development/src'))
from kde_bot.startup import KNOWN_EXECUTABLES


def create_shortcut(project_root=ROOT):
    import win32com.client
    root = Path(project_root).resolve(strict=True)
    executable = root / 'Program/KDE Bot Download V3.exe'
    if not executable.is_file():
        raise FileNotFoundError('Stable KDE Program executable is missing')
    shortcut = root / 'KDE Bot Download V3.lnk'
    shell = win32com.client.Dispatch('WScript.Shell')
    link = shell.CreateShortcut(str(shortcut))
    if shortcut.exists() and Path(link.TargetPath) not in {executable, *(Path(path) for path in KNOWN_EXECUTABLES)}:
        raise RuntimeError('Existing shortcut refers to another program; it was preserved')
    link.TargetPath = str(executable)
    link.WorkingDirectory = str(executable.parent)
    link.IconLocation = str(executable) + ',0'
    link.Description = 'เปิด KDE Bot Download'
    link.Save()
    verified = shell.CreateShortcut(str(shortcut))
    if Path(verified.TargetPath) != executable or Path(verified.WorkingDirectory) != executable.parent:
        raise RuntimeError('KDE shortcut verification failed')
    return shortcut


if __name__ == '__main__':
    print(create_shortcut())
