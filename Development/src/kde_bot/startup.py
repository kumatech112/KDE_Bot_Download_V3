"""Opt-in user sign-in startup; only this application's registry value is touched."""

from pathlib import Path
import ntpath
import subprocess
import sys


VALUE_NAME = 'KDE Bot Download V3'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


KNOWN_EXECUTABLES = (
    r"\\10.0.0.97\kumashare\Z AI\Projects\KDE_Bot_Download_V3\portable\KDE Bot Download V3.exe",
    r"\\10.0.0.97\kuma$\Z\Projects\KDE_Bot_Download_V3\portable\KDE Bot Download V3.exe",
    r"\\10.0.0.97\kuma$\Z\Projects\KDE_Bot_Download_V3\Program\KDE Bot Download V3.exe",
)


def owned_startup_commands(executable):
    """Allow only the current executable and exact known KDE project aliases."""
    current = str(executable)
    paths = [current]
    if ntpath.normcase(ntpath.normpath(current)) in {
            ntpath.normcase(ntpath.normpath(path)) for path in KNOWN_EXECUTABLES}:
        paths.extend(KNOWN_EXECUTABLES)
    return {subprocess.list2cmdline([path, '--background']) for path in paths}


def configure_startup(enabled, executable=None):
    import winreg
    from .cleanup_task import on_cleanup_machine
    executable = Path(executable or sys.executable).resolve()
    if not on_cleanup_machine():
        return 'การเริ่มพร้อม Windows ตั้งค่าเมื่อเปิดโปรแกรมบนเครื่อง .97'
    if not getattr(sys, 'frozen', False) or executable.parent.name.casefold() not in {'program', 'portable'} or executable.name != 'KDE Bot Download V3.exe':
        return 'การเริ่มพร้อม Windows ใช้งานจากโปรแกรมในโฟลเดอร์ Program'
    command = subprocess.list2cmdline([str(executable), '--background'])
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
        try:
            previous, value_type = winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            previous, value_type = None, None
        if previous is not None and (value_type != winreg.REG_SZ or previous not in owned_startup_commands(executable)):
            raise RuntimeError('รายการเริ่มพร้อม Windows ชื่อนี้มีคำสั่งอื่นอยู่ จึงไม่เปลี่ยนแปลง')
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        elif previous is not None:
            winreg.DeleteValue(key, VALUE_NAME)
    return 'เริ่ม KDE เบื้องหลังเมื่อเข้าสู่ Windows แล้ว' if enabled else 'ปิดการเริ่ม KDE พร้อม Windows แล้ว'
