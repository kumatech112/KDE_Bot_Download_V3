"""Register the current .97 Windows user's KDE cleanup task without passwords."""

from __future__ import annotations

import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .evidence import BANGKOK


def on_cleanup_machine():
    if socket.gethostname().casefold() == 'desktop0097-5k043lb':
        return True
    try:
        return any(item[4][0] == '10.0.0.97' for item in socket.getaddrinfo(socket.gethostname(), None))
    except OSError:
        return False


def task_definition(service, executable, user_sid, moment):
    definition = service.NewTask(0)
    definition.RegistrationInfo.Description = 'KDE: delete direct files in .243/.97 at 22:00 Bangkok; preserve all folders; coordinate shared download lock.'
    definition.Principal.UserId = user_sid
    definition.Principal.LogonType = 3  # Interactive token: no password stored.
    definition.Principal.RunLevel = 0
    definition.Settings.Enabled = True
    definition.Settings.StartWhenAvailable = False
    definition.Settings.DisallowStartIfOnBatteries = False
    definition.Settings.StopIfGoingOnBatteries = False
    definition.Settings.MultipleInstances = 2
    definition.Settings.ExecutionTimeLimit = 'PT2H'
    trigger = definition.Triggers.Create(2)
    first = moment.astimezone(BANGKOK).replace(hour=22, minute=0, second=0, microsecond=0)
    if first <= moment:
        first += timedelta(days=1)
    trigger.StartBoundary = first.isoformat()
    trigger.DaysInterval = 1
    trigger.Enabled = True
    action = definition.Actions.Create(0)
    action.Path = str(executable)
    action.Arguments = '--scheduled-cleanup'
    action.WorkingDirectory = os.environ['LOCALAPPDATA']
    return definition


def configure_task(enabled, executable=None):
    """Install/update only this user's named task, on .97, for the stable portable."""
    if not on_cleanup_machine():
        return {'installed': False, 'message': 'ลงทะเบียนงานลบเวลา 22:00 โดยเปิดโปรแกรมที่เครื่อง .97 หนึ่งครั้ง'}
    executable = Path(executable or sys.executable).resolve(strict=True)
    if not getattr(sys, 'frozen', False) or executable.name != 'KDE Bot Download V3.exe' or executable.parent.name.casefold() != 'portable':
        raise RuntimeError('กรุณาเปิดโปรแกรม EXE จากโฟลเดอร์ portable เพื่อลงทะเบียนงานลบไฟล์')
    import pythoncom
    import win32api
    import win32con
    import win32security
    import win32com.client

    pythoncom.CoInitialize()
    try:
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            user_sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
        finally:
            token.Close()
        name = 'KDE Bot Download Cleanup ' + user_sid
        service = win32com.client.Dispatch('Schedule.Service')
        service.Connect()
        root = service.GetFolder('\\')
        try:
            existing = root.GetTask(name)
        except Exception as error:
            if getattr(error, 'hresult', None) != -2147024894:  # ERROR_FILE_NOT_FOUND only.
                raise
            existing = None
        if existing is not None:
            principal = existing.Definition.Principal.UserId
            if principal.casefold() != user_sid.casefold():
                sid = win32security.LookupAccountName(None, principal)[0]
                if win32security.ConvertSidToStringSid(sid) != user_sid:
                    raise RuntimeError('ชื่องานลบไฟล์ตรงกับงานของผู้ใช้อื่น จึงไม่เปลี่ยนแปลง')
            if (existing.Definition.Actions.Count != 1
                    or Path(existing.Definition.Actions.Item(1).Path).resolve() != executable
                    or existing.Definition.Actions.Item(1).Arguments != '--scheduled-cleanup'):
                raise RuntimeError('งานเดิมอ้างถึงโปรแกรมอื่น จึงไม่เขียนทับ')
        if not enabled:
            if existing is not None:
                root.DeleteTask(name, 0)
            return {'installed': False, 'message': 'ปิดการลบไฟล์อัตโนมัติแล้ว'}
        definition = task_definition(service, executable, user_sid, datetime.now(BANGKOK))
        registered = root.RegisterTaskDefinition(name, definition, 6, user_sid, None, 3)
        actual = registered.Definition
        if (actual.Actions.Count != 1 or Path(actual.Actions.Item(1).Path).resolve() != executable
                or actual.Actions.Item(1).Arguments != '--scheduled-cleanup'
                or actual.Triggers.Count != 1 or 'T22:00:00+07:00' not in actual.Triggers.Item(1).StartBoundary
                or actual.Principal.LogonType != 3 or not registered.Enabled):
            raise RuntimeError('ตรวจสอบงานลบไฟล์หลังลงทะเบียนไม่ผ่าน กรุณาตรวจ Task Scheduler')
        return {'installed': True, 'task_name': name, 'message': 'ตั้งงานลบทุกวัน 22:00 แล้ว ทำงานแม้ปิด KDE เมื่อ Windows ยังลงชื่อเข้าใช้อยู่'}
    finally:
        pythoncom.CoUninitialize()
