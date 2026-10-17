"""Windows tray and per-user instance coordination; no business-file writes."""

import hashlib
import threading
import uuid


class DesktopInstance:
    def __init__(self, identity: str):
        import win32api
        import win32event
        name = 'Local\\KDEBotDownloadV3-' + hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
        self.event = win32event.CreateEvent(None, False, False, name + '-open')
        self.mutex = win32event.CreateMutex(None, False, name)
        self.existing = win32api.GetLastError() == 183

    def notify(self):
        import win32event
        win32event.SetEvent(self.event)

    def requested(self) -> bool:
        import win32event
        return win32event.WaitForSingleObject(self.event, 0) == win32event.WAIT_OBJECT_0

    def close(self):
        import win32api
        for name in ('event', 'mutex'):
            handle = getattr(self, name, None)
            if handle is not None:
                win32api.CloseHandle(handle)
                setattr(self, name, None)


class TrayIcon:
    def __init__(self, icon_path, callback):
        self.icon_path = str(icon_path)
        self.callback = callback
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.close_requested = threading.Event()
        self.error = None
        self.hwnd = None
        self.thread = threading.Thread(target=self.run, name='KDE-tray', daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        import win32api
        import win32con
        import win32gui
        class_name = 'KDETray' + uuid.uuid4().hex
        instance = win32api.GetModuleHandle(None)
        icon = None
        registered = False
        try:
            self.taskbar_message = win32gui.RegisterWindowMessage('TaskbarCreated')
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = instance
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = self.window_message
            win32gui.RegisterClass(window_class)
            registered = True
            self.hwnd = win32gui.CreateWindow(class_name, 'KDE background', 0, 0, 0, 0, 0, 0, 0, instance, None)
            icon = win32gui.LoadImage(instance, self.icon_path, win32con.IMAGE_ICON, 0, 0,
                                     win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
            self.notification = (self.hwnd, 1, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                                 win32con.WM_USER + 20, icon, 'KDE Download · ทำงานเบื้องหลัง')
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.notification)
            self.ready.set()
            if self.close_requested.is_set():
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            win32gui.PumpMessages()
        except Exception as error:
            self.error = str(error)
            self.ready.set()
        finally:
            if self.hwnd:
                try:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 1))
                    if win32gui.IsWindow(self.hwnd):
                        win32gui.DestroyWindow(self.hwnd)
                except Exception:
                    pass
            try:
                if icon:
                    win32gui.DestroyIcon(icon)
                if registered:
                    win32gui.UnregisterClass(class_name, instance)
            finally:
                self.hwnd = None
                self.stopped.set()

    def window_message(self, hwnd, message, wparam, lparam):
        import win32con
        import win32gui
        if message == self.taskbar_message:
            if hasattr(self, 'notification'):
                win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.notification)
            return 0
        if message == win32con.WM_USER + 20:
            if lparam == win32con.WM_LBUTTONUP:
                self.callback('tray_show')
            elif lparam == win32con.WM_RBUTTONUP:
                menu = win32gui.CreatePopupMenu()
                try:
                    win32gui.AppendMenu(menu, win32con.MF_STRING, 100, 'เปิด KDE / เริ่มติดตามเมล')
                    win32gui.AppendMenu(menu, win32con.MF_STRING, 300, 'ออกจากโปรแกรมทั้งหมด')
                    win32gui.SetForegroundWindow(hwnd)
                    x, y = win32gui.GetCursorPos()
                    win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, x, y, 0, hwnd, None)
                    win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
                finally:
                    win32gui.DestroyMenu(menu)
            return 0
        if message == win32con.WM_COMMAND:
            action = {100: 'tray_show', 300: 'tray_exit'}.get(wparam & 0xffff)
            if action:
                self.callback(action)
            return 0
        if message == win32con.WM_CLOSE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def close(self):
        import win32con
        import win32gui
        self.close_requested.set()
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
