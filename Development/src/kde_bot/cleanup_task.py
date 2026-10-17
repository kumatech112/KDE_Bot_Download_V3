"""Register the current .97 Windows user's KDE cleanup task without passwords."""

from __future__ import annotations

import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .evidence import BANGKOK


def scheduler_error_code(error):
    """Read a COM HRESULT, including a dispatch exception's nested SCODE."""
    code = getattr(error, 'hresult', None)
    arguments = getattr(error, 'args', ())
    if not isinstance(code, int) and arguments and isinstance(arguments[0], int):
        code = arguments[0]
    if isinstance(code, int) and code & 0xFFFFFFFF == 0x80020009:
        details = getattr(error, 'excepinfo', None)
        if details is None and len(arguments) > 2:
            details = arguments[2]
        if isinstance(details, (tuple, list)) and len(details) > 5 and isinstance(details[5], int) and details[5]:
            code = details[5]
    return code & 0xFFFFFFFF if isinstance(code, int) else None


def setup_error(stage, error):
    code = scheduler_error_code(error)
    reasons = {0x80070002: 'ไม่พบงานหรือไฟล์ที่อ้างอิง', 0x80070005: 'Windows ไม่อนุญาตให้ดำเนินการ',
               0x80041315: 'บริการ Task Scheduler ยังไม่ทำงาน'}
    reason = reasons.get(code, str(error))
    suffix = f' (0x{code:08X})' if code is not None else ''
    return RuntimeError(f'{stage}: {reason}{suffix}')


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
    if not getattr(sys, 'frozen', False) or executable.name != 'KDE Bot Download V3.exe' or executable.parent.name.casefold() not in {'program', 'portable'}:
        raise RuntimeError('กรุณาเปิดโปรแกรม EXE จากโฟลเดอร์ Program เพื่อลงทะเบียนงานลบไฟล์')
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
        try:
            service.Connect()
            root = service.GetFolder('\\')
        except Exception as error:
            raise setup_error('เชื่อมต่อ Task Scheduler ไม่สำเร็จ', error) from error
        try:
            existing = root.GetTask(name)
        except Exception as error:
            if scheduler_error_code(error) != 0x80070002:  # Expected on first setup, only at GetTask.
                raise setup_error('ตรวจสอบงานลบไฟล์เดิมไม่สำเร็จ', error) from error
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
                try:
                    root.DeleteTask(name, 0)
                except Exception as error:
                    raise setup_error('ยกเลิกงานลบไฟล์ไม่สำเร็จ', error) from error
            return {'installed': False, 'message': 'ปิดการลบไฟล์อัตโนมัติแล้ว'}
        definition = task_definition(service, executable, user_sid, datetime.now(BANGKOK))
        try:
            registered = root.RegisterTaskDefinition(name, definition, 6, user_sid, None, 3)
        except Exception as error:
            raise setup_error('ลงทะเบียนงานลบไฟล์ไม่สำเร็จ', error) from error
        actual = registered.Definition
        if (actual.Actions.Count != 1 or Path(actual.Actions.Item(1).Path).resolve() != executable
                or actual.Actions.Item(1).Arguments != '--scheduled-cleanup'
                or actual.Triggers.Count != 1 or 'T22:00:00+07:00' not in actual.Triggers.Item(1).StartBoundary
                or actual.Principal.LogonType != 3 or not registered.Enabled):
            raise RuntimeError('ตรวจสอบงานลบไฟล์หลังลงทะเบียนไม่ผ่าน กรุณาตรวจ Task Scheduler')
        return {'installed': True, 'task_name': name, 'message': 'ตั้งงานลบทุกวัน 22:00 แล้ว ทำงานแม้ปิด KDE เมื่อ Windows ยังลงชื่อเข้าใช้อยู่'}
    finally:
        pythoncom.CoUninitialize()
