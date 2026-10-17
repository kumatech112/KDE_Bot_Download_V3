"""Thai monitoring UI with tray maintenance and isolated download workers."""

from __future__ import annotations

import copy
import json
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import VERSION
from .language import thai_text
from .activity import ActivityHistory, read_activity, update_latest
from .evidence import today
from .settings import import_settings, load_settings, save_settings, validate_settings
from .storage import History, WorkerLock, timestamp
from .workflow import run_cycle
from .schedule import BackgroundClock

STEPS = {1: "เริ่มต้น", 2: "ตรวจเมล", 3: "เข้าสู่ระบบ", 4: "ตรวจรายการ", 5: "ตรวจไฟล์", 6: "ดาวน์โหลด", 7: "บันทึกไฟล์", 8: "ออกจากระบบ", 9: "ลบไฟล์ 22:00"}


STATUS_LABELS = {"running": 'กำลังทำงาน', "stage_complete": 'สำเร็จ', "complete": 'เสร็จแล้ว',
                 "skipped": 'มีไฟล์แล้ว', "copy_pending": 'รอบันทึกไฟล์', "error": 'ผิดพลาด',
                 "warning": 'ต้องตรวจสอบ', "summary": 'การทำงาน', "waiting": 'รอทำงาน', "notice": 'ข้อมูล'}
JOB_LABELS = {"waiting": 'รอทำงาน', "running": 'กำลังทำงาน', "complete": 'เสร็จแล้ว', "copy_pending": 'รอบันทึกไฟล์',
              "exhausted": 'รอเมลใหม่', "deferred": 'รอเมลใหม่', "review": 'ต้องตรวจสอบ', "expired": 'ข้ามงานวันก่อน'}
MODES = {"เก็บ .97 และคัดลอก .243": "both", "เก็บ .97 อย่างเดียว": "new"}


def application_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets" / "app.ico"
    return Path(__file__).resolve().parents[2] / "assets" / "app.ico"


def apply_window_icon(root: tk.Tk) -> bool:
    path = application_icon_path()
    if not path.is_file():
        return False
    try:
        root.iconbitmap(default=str(path))
        return True
    except tk.TclError:
        return False


class Application(ttk.Frame):
    def __init__(self, root: tk.Tk, smoke: bool = False, background=False, instance=None):
        super().__init__(root, padding=16)
        self.root = root
        self.smoke = smoke
        self.instance = instance
        self.tray = None
        self.closing = False
        self.background_clock = BackgroundClock(time.time())
        self.maintenance_stop = threading.Event()
        self.maintenance_worker = None
        self.resume_pending = False
        self.resume_manual = not background
        self.schedule_paused = False
        self.settings, self.notices = load_settings()
        self.events: queue.Queue = queue.Queue()
        self.requests: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.rows: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.activity = ActivityHistory()
        self.variables: dict[str, tk.Variable] = {}
        self.password_controls: dict[str, tuple[Any, tk.BooleanVar, Any]] = {}
        self.inputs: list[Any] = []
        self.busy_buttons: list[Any] = []
        self.status = tk.StringVar(value='พร้อมใช้งาน')
        self.summary = tk.StringVar(value='ยังไม่มีรอบดาวน์โหลด')
        self.mail_health = {}
        self.mail_status = tk.StringVar(value='การตรวจเมล: ยังไม่ได้เริ่มทำงาน')
        self.cleanup_status = tk.StringVar(value='ปิดหน้าต่าง = ทำงานเบื้องหลัง · ลบ 22:00 (เก็บทุกโฟลเดอร์) · ติดตามต่อ 05:00 หรือเมื่อเปิด KDE')
        self.current_step = tk.StringVar(value="เมลใหม่ → รอ 4 นาที 30 วินาที → ทำทีละบัญชี หน้าละ 30 รายการ → ตรวจไฟล์ซ้ำจาก .97")
        self.filter = tk.StringVar()
        self.follow_history = tk.BooleanVar(value=True)
        self.history_count = tk.StringVar(value='0 รายการ')
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.build_controls()
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky="nsew", pady=(12, 8))
        self.build_monitor()
        self.build_activity()
        self.settings_page = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(self.settings_page, text='ตั้งค่า')
        self.build_settings()
        ttk.Label(self, textvariable=self.current_step, wraplength=1100).grid(row=4, column=0, sticky="w")
        ttk.Label(self, text=f"{socket.gethostname()} / {os.environ.get('USERNAME', '')}").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.fill_settings()
        self.filter.trace_add("write", lambda *_: self.render_activity())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self.callback_error
        self.poll_id = root.after(100, self.drain_events)
        self.clock_id = root.after(1000, self.tick)
        if self.notices:
            self.status.set('กรุณาตั้งค่าก่อนเริ่ม')
            self.tabs.select(self.settings_page)
        if not smoke:
            self.start_tray(background)
            root.after(400, self.auto_start)
            root.after(600, self.load_history)
            root.after(1000, self.configure_background_startup)

    def build_controls(self) -> None:
        from PIL import Image, ImageTk
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.brand_icon = None
        try:
            with Image.open(application_icon_path()) as icon:
                self.brand_icon = ImageTk.PhotoImage(icon.ico.getimage((32, 32)), master=self.root)
        except OSError:
            pass
        ttk.Label(header, text="  KDE Download" if self.brand_icon else "KDE Download", image=self.brand_icon or "",
                  compound="left", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=VERSION).grid(row=0, column=1, sticky="e")
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(12, 8))
        self.start_button = ttk.Button(toolbar, text='เริ่มทำงาน', command=self.resume_tracking)
        self.start_button.pack(side="left")
        self.busy_buttons.append(self.start_button)
        self.stop_button = ttk.Button(toolbar, text='หยุด', command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(toolbar, text='รายละเอียดรอบงาน', command=self.review_request).pack(side="left", padx=(8, 6))
        ttk.Button(toolbar, text='สั่งดาวน์โหลด', command=self.retry_failed).pack(side="left")
        tools = ttk.Menubutton(toolbar, text='เครื่องมือ')
        menu = tk.Menu(tools, tearoff=False)
        menu.add_command(label='ตรวจสอบการเชื่อมต่อ', command=lambda: self.start("check"))
        menu.add_command(label='บันทึกไฟล์ที่ค้างอีกครั้ง', command=self.repair_saves)
        menu.add_separator()
        menu.add_command(label='นำเข้าการตั้งค่า', command=self.import_configuration)
        menu.add_command(label='นำเข้าประวัติเดิม', command=self.import_history)
        menu.add_command(label='เปิดโฟลเดอร์ประวัติ', command=self.open_logs)
        menu.add_command(label='ตั้งค่าการเริ่มพร้อม Windows', command=self.configure_background_startup)
        menu.add_separator()
        menu.add_command(label='ออกจากโปรแกรมทั้งหมด', command=self.exit_fully)
        tools.configure(menu=menu)
        tools.pack(side="right")
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, textvariable=self.status, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(bar, textvariable=self.summary).grid(row=0, column=1, sticky="e")
        ttk.Label(bar, textvariable=self.mail_status).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def make_table(self, page, columns, headings, widths, row=0):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(row, weight=1)
        table = ttk.Treeview(page, columns=columns, show="headings", selectmode="browse")
        for column, heading, width in zip(columns, headings, widths):
            table.heading(column, text=heading)
            table.column(column, width=width, minwidth=45, stretch=column in {"subject", "reference", "filename", "reason"})
        table.grid(row=row, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(page, orient="vertical", command=table.yview)
        horizontal = ttk.Scrollbar(page, orient="horizontal", command=table.xview)
        vertical.grid(row=row, column=1, sticky="ns")
        horizontal.grid(row=row + 1, column=0, sticky="ew")
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return table

    def build_monitor(self) -> None:
        page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(page, text='การทำงาน')
        self.monitor_page = page
        self.job_table = self.make_table(page, ("order", "account", "subject", "status", "ready", "attempts", "reference"),
                                         ("#", 'บัญชี', 'รอบดาวน์โหลด', 'สถานะ', 'เวลารอ', 'เข้าสู่ระบบ', 'ผลการทำงาน'),
                                         (45, 85, 260, 160, 70, 70, 255))
        self.job_table.bind("<Double-1>", lambda _event: self.review_request())
        ttk.Label(page, text="ทำงานเมื่อมีเมลใหม่เท่านั้น หากเข้าสู่ระบบไม่ได้หรือมีผู้ใช้อยู่ รอ 1 นาทีแล้วลองใหม่ กดหยุดได้ทุกเมื่อ", wraplength=1050).grid(row=2, column=0, sticky="w", pady=(8, 0))

    def build_activity(self) -> None:
        page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(page, text='ประวัติการทำงาน')
        self.activity_page = page
        bar = ttk.Frame(page)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(bar, text='โหลดประวัติใหม่', command=self.load_history).pack(side="left")
        ttk.Checkbutton(bar, text='เลื่อนไปรายการล่าสุด', variable=self.follow_history).pack(side="left", padx=12)
        ttk.Label(bar, text='ค้นหา').pack(side="left", padx=(12, 6))
        ttk.Entry(bar, textvariable=self.filter, width=28).pack(side="left")
        ttk.Label(bar, textvariable=self.history_count).pack(side="right")
        self.activity_table = self.make_table(page, ("time", "account", "action", "status", "filename", "reason"),
                                             ('วัน / เวลา', 'บัญชี', 'การทำงาน', 'ผลการทำงาน', 'ชื่อไฟล์', 'รายละเอียด'),
                                             (140, 80, 95, 100, 270, 340), row=1)
        self.activity_table.bind("<Double-1>", lambda _event: self.show_selected())

    def add_field(self, parent, row, label, path, password=False, choices=None, boolean=False, browse=False):
        variable = tk.BooleanVar() if boolean else tk.StringVar()
        self.variables[path] = variable
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=5)
        if boolean:
            widget = ttk.Checkbutton(parent, variable=variable)
        elif choices:
            widget = ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly")
        else:
            widget = ttk.Entry(parent, textvariable=variable, show="*" if password else "")
        widget.grid(row=row, column=1, sticky="ew", pady=5)
        self.inputs.append(widget)
        if password:
            visible = tk.BooleanVar(value=False)
            toggle = ttk.Checkbutton(parent, text='แสดงรหัสผ่าน', variable=visible,
                                     command=lambda: self.toggle_password(path))
            toggle.grid(row=row + 1, column=1, sticky="w", pady=(0, 5))
            self.password_controls[path] = (widget, visible, toggle)
            self.inputs.append(toggle)
        if browse:
            button = ttk.Button(parent, text='เลือกโฟลเดอร์', command=lambda: self.browse(variable))
            button.grid(row=row, column=2, padx=(8, 0))
            self.busy_buttons.append(button)

    def toggle_password(self, path: str) -> None:
        entry, visible, _toggle = self.password_controls[path]
        entry.configure(show="" if visible.get() else "*")

    def hide_passwords(self) -> None:
        for entry, visible, _toggle in self.password_controls.values():
            visible.set(False)
            entry.configure(show="*")

    def build_settings(self) -> None:
        page = self.settings_page
        page.columnconfigure(1, weight=1)
        self.notice_label = ttk.Label(page, text='รหัสผ่านถูกเข้ารหัสสำหรับผู้ใช้ Windows นี้ เมื่อตั้งค่าครบ โปรแกรมจะเริ่มทำงานอัตโนมัติ', wraplength=1050)
        self.notice_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self.add_field(page, 1, 'กล่องเมล Outlook', "mail_watch.mailbox_filter")
        self.add_field(page, 2, 'การจัดเก็บ', "storage_mode", choices=list(MODES))
        self.add_field(page, 3, 'โฟลเดอร์คัดลอก .243', "original_dir", browse=True)
        self.add_field(page, 4, 'โฟลเดอร์ดาวน์โหลด .97', "new_dir", browse=True)
        self.add_field(page, 5, 'โฟลเดอร์ประวัติ', "log_dir", browse=True)
        accounts = ttk.Frame(page)
        accounts.grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)
        for index, title in enumerate(("Pre", "Post")):
            accounts.columnconfigure(index, weight=1)
            frame = ttk.LabelFrame(accounts, text=title, padding=12)
            frame.grid(row=0, column=index, sticky="nsew", padx=(0, 8) if index == 0 else (8, 0))
            frame.columnconfigure(1, weight=1)
            prefix = f"accounts.{index}."
            self.add_field(frame, 0, 'เปิดใช้งาน', prefix + "enabled", boolean=True)
            self.add_field(frame, 1, 'ชื่อผู้ใช้', prefix + "username")
            self.add_field(frame, 2, 'รหัสผ่าน', prefix + "password", password=True)
        self.add_field(page, 7, 'ลบไฟล์ทุกวัน 22:00 (เก็บ Check ไว้)', 'daily_cleanup_enabled', boolean=True)
        buttons = ttk.Frame(page)
        buttons.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 12))
        save = ttk.Button(buttons, text='บันทึกและเริ่มทำงาน', command=self.save_configuration)
        save.pack(side="left")
        self.busy_buttons.append(save)
        advanced = ttk.Button(buttons, text='ตัวเลือกเพิ่มเติม', command=self.advanced_settings)
        advanced.pack(side="left", padx=10)
        self.busy_buttons.append(advanced)
        self.variables['start_with_windows'] = tk.BooleanVar(value=True)
        startup = ttk.Checkbutton(buttons, text='เริ่มพร้อม Windows', variable=self.variables['start_with_windows'])
        startup.pack(side='left', padx=10)
        self.inputs.append(startup)
        ttk.Label(page, textvariable=self.cleanup_status, wraplength=1050).grid(row=9, column=0, columnspan=3, sticky="w")

    def advanced_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title('ตัวเลือกเพิ่มเติม')
        window.transient(self.root)
        window.columnconfigure(1, weight=1)
        fields = [('ตรวจเมลทุก (วินาที)', "mail_poll_seconds"), ('จำนวนเมลที่ตรวจต่อโฟลเดอร์', "mail_watch.max_messages_per_folder"),
                  ('เวลารอหน้าเว็บ (วินาที)', "page_timeout_seconds"),
                  ('พักระหว่างดาวน์โหลด (วินาที)', "download_delay_seconds"), ('ตำแหน่งเบราว์เซอร์ (ถ้ามี)', "chrome_path")]
        local = {}
        for row, (label, path) in enumerate(fields):
            ttk.Label(window, text=label).grid(row=row, column=0, padx=12, pady=8, sticky="w")
            local[path] = tk.StringVar(value=self.lookup(self.settings, path))
            ttk.Entry(window, textvariable=local[path], width=48).grid(row=row, column=1, padx=12, pady=8, sticky="ew")
        def apply():
            try:
                candidate = copy.deepcopy(self.settings)
                for path, variable in local.items():
                    old = self.lookup(candidate, path)
                    self.assign(candidate, path, int(variable.get()) if isinstance(old, int) else variable.get().strip())
                validate_settings(candidate, require_credentials=False)
                self.settings = candidate
                window.destroy()
            except Exception as error:
                messagebox.showerror('ตัวเลือกไม่ถูกต้อง', thai_text(str(error)), parent=window)
        ttk.Button(window, text='นำไปใช้', command=apply).grid(row=len(fields), column=1, sticky="e", padx=12, pady=12)

    @staticmethod
    def lookup(settings, path):
        value = settings
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value

    @staticmethod
    def assign(settings, path, value):
        parts = path.split(".")
        target = settings
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value

    def fill_settings(self) -> None:
        from .settings import default_settings
        self.hide_passwords()
        while len(self.settings["accounts"]) < 2:
            account = default_settings()["accounts"][len(self.settings["accounts"])]
            account["enabled"] = False
            self.settings["accounts"].append(account)
        for path, variable in self.variables.items():
            value = self.lookup(self.settings, path)
            if path == "storage_mode":
                value = next(label for label, mode in MODES.items() if mode == value)
            variable.set(value)

    def collect_settings(self):
        result = copy.deepcopy(self.settings)
        for path, variable in self.variables.items():
            value = variable.get()
            if path == "storage_mode":
                value = MODES[value]
            elif isinstance(value, str) and not path.endswith("password"):
                value = value.strip()
            self.assign(result, path, value)
        validate_settings(result, require_credentials=False)
        return result

    def browse(self, variable):
        path = filedialog.askdirectory(parent=self.root)
        if path:
            variable.set(path)

    def save_configuration(self) -> None:
        try:
            self.settings = self.collect_settings()
            validate_settings(self.settings)
            save_settings(self.settings)
            self.configure_background_startup()
            self.notice_label.configure(text='บันทึกการตั้งค่าสำหรับผู้ใช้ Windows นี้แล้ว')
            self.start("watch")
        except Exception as error:
            messagebox.showerror('บันทึกการตั้งค่าไม่ได้', thai_text(str(error)), parent=self.root)

    def configure_background_startup(self) -> None:
        """Configure user sign-in startup and retire only our legacy task."""
        if self.smoke:
            return
        settings = copy.deepcopy(self.settings)
        def work():
            from .cleanup_task import configure_task
            from .settings import settings_home
            from .startup import configure_startup
            try:
                if not (settings_home() / 'settings.json').is_file():
                    message = 'บันทึกการตั้งค่าก่อน · ปิดหน้าต่างเพื่อทำงานเบื้องหลัง · พัก 22:00 ถึง 05:00'
                else:
                    message = configure_startup(settings['start_with_windows'])
                    try:
                        configure_task(False)
                    except Exception:
                        message += ' · งานตั้งเวลาเดิมไม่ถูกลบ แต่คำสั่งเดิมจะไม่ลบไฟล์อีก'
                    message += ' · ลบ 22:00 / ติดตามเมลต่อ 05:00 · ต้องเปิดเครื่องและคงโปรแกรมไว้ในถาดระบบ'
            except Exception as error:
                message = f'ตั้งค่าเริ่มพร้อม Windows ไม่สำเร็จ: {thai_text(error)} · ตัวจับเวลาในโปรแกรมยังทำงาน'
            self.events.put(('cleanup_task', message))
        threading.Thread(target=work, name='KDE-startup-setup', daemon=True).start()

    def start_tray(self, background=False):
        from .desktop import TrayIcon
        self.tray = TrayIcon(application_icon_path(), lambda action: self.events.put((action, None)))
        self.tray.start()
        if background:
            self.root.withdraw()
        self.root.after(100, lambda: self.check_tray_ready(background))

    def check_tray_ready(self, background):
        if self.closing:
            return
        if not self.tray.ready.is_set():
            self.root.after(100, lambda: self.check_tray_ready(background))
            return
        if self.tray.error or self.tray.stopped.is_set():
            self.root.deiconify()
            self.status.set('สร้างไอคอนถาดระบบไม่ได้ กรุณาเปิดหน้าต่างนี้ไว้: ' + str(self.tray.error or 'Tray stopped'))

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.hide_passwords()
        self.resume_tracking()

    def resume_tracking(self, manual=True):
        if self.closing:
            return
        if self.maintenance_worker and self.maintenance_worker.is_alive():
            self.resume_pending = True
            self.resume_manual = self.resume_manual or manual
            self.status.set('รอลบไฟล์เสร็จ แล้วเริ่มติดตามเมล')
            return
        if self.worker and self.worker.is_alive():
            if self.stop_event.is_set():
                self.resume_pending = True
                self.resume_manual = self.resume_manual or manual
            elif manual:
                self.requests.put({'kind': 'resume_tracking'})
            return
        self.resume_manual = manual
        self.resume_pending = False
        self.auto_start(force=True)

    def start_maintenance(self):
        if self.closing or not self.settings.get('daily_cleanup_enabled', True):
            return
        if self.maintenance_worker and self.maintenance_worker.is_alive():
            return
        self.maintenance_stop.clear()
        def work():
            from .cleanup import run_scheduled_cleanup
            from .cleanup_task import on_cleanup_machine
            from .settings import settings_home
            try:
                if not on_cleanup_machine():
                    raise RuntimeError('ลบไฟล์อัตโนมัติเฉพาะเครื่อง .97')
                if not (settings_home() / 'settings.json').is_file():
                    raise RuntimeError('ยังไม่ได้บันทึกการตั้งค่า จึงไม่ลบไฟล์')
                saved, notices = load_settings()
                if any(notice.startswith('Cannot read settings:') for notice in notices):
                    raise RuntimeError('อ่านการตั้งค่าไม่ได้ จึงไม่ลบไฟล์')
                validate_settings(saved, require_credentials=False)
                code = run_scheduled_cleanup(saved, self.maintenance_stop)
                message = 'ตรวจงานลบ 22:00 แล้ว · ดูผลในประวัติ · พักถึง 05:00' if code == 0 else 'งานลบ 22:00 ไม่ครบ กรุณาดูประวัติ'
                self.events.put(('maintenance_result', message))
            except Exception as error:
                self.events.put(('maintenance_result', f'ลบไฟล์ 22:00 ไม่สำเร็จ: {thai_text(error)}'))
        self.maintenance_worker = threading.Thread(target=work, name='KDE-maintenance', daemon=False)
        self.maintenance_worker.start()

    def auto_start(self, force=False) -> None:
        if self.smoke and not force:
            return
        try:
            validate_settings(self.collect_settings())
        except Exception:
            self.status.set('กรุณากรอกชื่อผู้ใช้และรหัสผ่านของบัญชีที่เปิดใช้งาน')
            self.tabs.select(self.settings_page)
            return
        self.start("watch")

    def import_configuration(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('กรุณาหยุดงานก่อน', 'กรุณาหยุดการทำงานก่อนเปลี่ยนการตั้งค่า', parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title='นำเข้าการตั้งค่า KDE', filetypes=[("JSON", "*.json")])
        if path:
            try:
                self.settings, self.notices = import_settings(Path(path))
                self.fill_settings()
                self.tabs.select(self.settings_page)
                self.notice_label.configure(text='นำเข้าแล้ว กรุณาตรวจสอบบัญชีแล้วกดบันทึกและเริ่มทำงาน')
            except Exception as error:
                messagebox.showerror('นำเข้าไม่สำเร็จ', thai_text(str(error)), parent=self.root)

    def import_history(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('กรุณาหยุดงานก่อน', 'กรุณาหยุดการทำงานก่อนนำเข้าประวัติ', parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title='นำเข้าประวัติ KDE เดิม', filetypes=[("JSON", "*.json")])
        if not path:
            return
        settings = self.collect_settings()
        def work():
            try:
                with WorkerLock(Path(settings["log_dir"])):
                    count = History(Path(settings["log_dir"])).import_legacy(Path(path))
                self.events.put(("notice", f"นำเข้าประวัติแล้ว {count} รายการ"))
            except Exception as error:
                self.events.put(("failure", str(error)))
            finally:
                self.events.put(("idle", None))
        self.set_busy(True)
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()


    def review_request(self) -> None:
        selected = self.job_table.selection()
        if not selected:
            return
        job = self.jobs[selected[0]]
        details = f"{thai_text(job.get('subject', ''))}\n\n{thai_text(job.get('last_reason', ''))}\n\nเข้าสู่ระบบ: {job['attempts']} ครั้ง\nวันที่: {job.get('work_date', today())}"
        messagebox.showinfo('รายละเอียดรอบดาวน์โหลด', details, parent=self.root)
        return

    def retry_failed(self) -> None:
        if self.worker and self.worker.is_alive():
            self.requests.put({"kind": "retry"})
        else:
            self.resume_manual = True
            self.start("requeue")

    def repair_saves(self) -> None:
        if self.worker and self.worker.is_alive():
            self.status.set('กรุณาหยุดก่อนบันทึกไฟล์ที่ค้างอีกครั้ง')
        else:
            self.start("retry")

    def start(self, mode: str) -> None:
        if self.closing:
            return
        if self.maintenance_worker and self.maintenance_worker.is_alive():
            if mode in {'watch', 'requeue'}:
                self.resume_pending = True
                self.resume_manual = True
            self.status.set('รอให้งานลบไฟล์เสร็จก่อนเริ่มงานใหม่')
            return
        if self.worker and self.worker.is_alive():
            return
        try:
            settings = self.collect_settings()
            validate_settings(settings, require_credentials=mode not in {"scan", "check", "retry"})
            save_settings(settings)
            self.settings = settings
        except Exception as error:
            self.tabs.select(self.settings_page)
            messagebox.showerror('เริ่มทำงานไม่ได้', thai_text(str(error)), parent=self.root)
            return
        self.stop_event.clear()
        while not self.requests.empty():
            try:
                self.requests.get_nowait()
            except queue.Empty:
                break
        if mode in {'watch', 'requeue'} and self.resume_manual:
            self.requests.put({'kind': 'resume_tracking'})
        self.resume_manual = False
        self.mail_health = {}
        self.mail_status.set('การตรวจเมล: กำลังเริ่มตรวจทุกโฟลเดอร์ขาเข้าของกล่องที่ตั้งค่าไว้')
        self.set_busy(True)
        self.tabs.select(self.monitor_page)
        self.status.set('กำลังเริ่มทำงาน' if mode in {"watch", "requeue"} else 'กำลังตรวจสอบ')
        def work():
            try:
                counts = run_cycle(settings, self.stop_event, lambda event: self.events.put(("event", event)),
                                   scan_only=mode == "scan", check_only=mode == "check", retry_only=mode == "retry",
                                   watch=mode in {"watch", "requeue"}, requeue_failed=mode == "requeue", requests=self.requests)
                self.events.put(("counts", counts))
            except Exception as error:
                text = str(error)
                for account in settings["accounts"]:
                    if account["password"]:
                        text = text.replace(account["password"], "[REDACTED]")
                self.events.put(("event", {"key": "startup-error", "time": timestamp(), "account": "", "filename": "",
                                           "step": 1, "status": "error", "reason": f"{type(error).__name__}: {text}",
                                           "destination": "", "attempt": 1}))
                self.events.put(("failure", thai_text(text)))
            finally:
                self.events.put(("idle", None))
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.hide_passwords()
        self.stop_button.configure(state="disabled")
        self.status.set('กำลังหยุด รอให้บันทึกไฟล์และออกจากระบบเสร็จก่อน')

    def set_busy(self, busy: bool) -> None:
        self.hide_passwords()
        for button in self.busy_buttons:
            button.configure(state="disabled" if busy else "normal")
        for widget in self.inputs:
            widget.configure(state="disabled" if busy else "readonly" if isinstance(widget, ttk.Combobox) else "normal")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def drain_events(self) -> None:
        changed = False
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                self.accept_event(value)
                changed = True
            elif kind == "failure":
                self.status.set("ผิดพลาด: " + thai_text(value))
            elif kind == "notice":
                self.status.set(thai_text(value))
            elif kind == 'tray_show':
                self.show_window()
            elif kind == 'tray_exit':
                self.exit_fully()
            elif kind == 'maintenance_result':
                self.cleanup_status.set(value)
                self.status.set(value)
                self.load_history()
            elif kind == 'cleanup_task':
                self.cleanup_status.set(value)
                if 'ไม่สำเร็จ' in value:
                    self.status.set(value)
            elif kind == "history":
                activity, latest = value
                self.activity.merge(activity)
                for event in latest:
                    update_latest(self.rows, event)
                changed = True
            elif kind == "idle":
                self.set_busy(False)
                self.schedule_paused = False
                if self.stop_event.is_set():
                    self.status.set('หยุดทำงานแล้ว')
        if changed:
            self.render_results()
        self.poll_id = self.root.after(100, self.drain_events)

    def accept_event(self, event: dict[str, Any]) -> None:
        if event.get('kind') == 'schedule_status':
            self.schedule_paused = event['paused']
            return
        if event.get("kind") == "mail_health":
            self.mail_health = event
            return
        if event.get("kind") == "queue":
            self.jobs = {job["id"]: job for job in event["jobs"]}
            return
        step = int(event["step"])
        label = STATUS_LABELS.get(event["status"], event["status"])
        event = dict(event, reason=thai_text(event.get("reason", "")))
        self.activity.add(event)
        self.current_step.set(f"{event.get('account') or 'ระบบ'} · {STEPS.get(step, 'การทำงาน')} · {label}")
        if event["status"] == "summary":
            self.status.set(event["reason"])
        elif event["status"] in {"error", "copy_pending", "warning"}:
            self.status.set(f"{STEPS.get(step, 'การทำงาน')}: {label} — ดูประวัติการทำงาน")
        update_latest(self.rows, event)

    def render_jobs(self) -> None:
        desired = set(self.jobs)
        for key in self.job_table.get_children():
            if key not in desired:
                self.job_table.delete(key)
        ordered = sorted(self.jobs.values(), key=lambda job: (job.get("sequence", 0), job.get("observed", 0)))
        for position, job in enumerate(ordered, 1):
            remaining = max(0, int(job["due"] - time.time())) if job["status"] == "waiting" else 0
            wait = f"{remaining // 60}:{remaining % 60:02}" if remaining else ""
            label = 'บัญชีมีผู้ใช้งาน' if job["status"] == "waiting" and job.get("busy_sources") else JOB_LABELS.get(job["status"], job["status"])
            values = (position, job["label"], thai_text(job.get("subject") or "รอบดาวน์โหลด"), label,
                      wait, f"{job['attempts']} ครั้ง", thai_text(job.get("last_reason", ""))[:220])
            if self.job_table.exists(job["id"]):
                self.job_table.item(job["id"], values=values)
                self.job_table.move(job["id"], "", position - 1)
            else:
                self.job_table.insert("", "end", iid=job["id"], values=values)
        done = sum(job["status"] == "complete" for job in ordered)
        pending = sum(job["status"] in {"waiting", "running"} for job in ordered)
        review = sum(job["status"] in {"review", "exhausted", "copy_pending"} for job in ordered)
        deferred = sum(job["status"] == "deferred" for job in ordered)
        self.summary.set(f"รอ {pending}   ·   เสร็จ {done}   ·   รอเมลใหม่ {deferred}   ·   ต้องตรวจสอบ {review}")
        if self.mail_health:
            checked = time.strftime('%H:%M:%S', time.localtime(self.mail_health['checked']))
            if self.mail_health.get('error'):
                self.mail_status.set(f"ตรวจเมล {checked} · ต้องตรวจสอบ: {thai_text(self.mail_health['error'])[:190]}")
            else:
                prefix = f"ตรวจเมลล่าสุด {checked} · เมลวันนี้ {self.mail_health.get('count', 0)} ฉบับ · ทุกโฟลเดอร์ขาเข้า"
                waiting = self.jobs.get('pending-daily-round')
                if waiting:
                    remaining = max(0, int(waiting['due'] - time.time()))
                    suffix = (f"รอดาวน์โหลด {remaining // 60}:{remaining % 60:02}" if remaining else "รอบพร้อมแล้ว รอบัญชีก่อนหน้าจบ")
                else:
                    suffix = 'กำลังดาวน์โหลด' if any(job['status'] == 'running' for job in ordered) else 'รอเมลใหม่'
                self.mail_status.set(prefix + ' · ' + suffix)
        if self.schedule_paused:
            self.mail_status.set('พักติดตามเมลถึง 05:00 · เปิด KDE เพื่อเริ่มก่อนเวลาได้ · รอให้งานปัจจุบันจบก่อนลบไฟล์')
        elif self.stop_event.is_set():
            self.mail_status.set('หยุดติดตามเมลแล้ว · ตัวจับเวลาลบ 22:00 และเริ่มใหม่ 05:00 ยังทำงานเมื่อโปรแกรมอยู่เบื้องหลัง')

    def render_activity(self) -> None:
        search = self.filter.get().casefold()
        visible = [(key, event) for key, event in self.activity.entries.items()
                   if not search or search in " ".join(str(event.get(field, "")) for field in
                                                       ("time", "account", "filename", "reason", "destination")).casefold()]
        desired = {key for key, _ in visible}
        for key in self.activity_table.get_children():
            if key not in desired:
                self.activity_table.delete(key)
        for position, (key, event) in enumerate(visible):
            values = (str(event["time"]).replace("T", " ")[:19], event.get("account") or 'ระบบ',
                      STEPS.get(int(event["step"]), 'การทำงาน'), STATUS_LABELS.get(event["status"], event["status"]),
                      event.get("filename", ""), thai_text(event.get("reason", "")))
            if self.activity_table.exists(key):
                self.activity_table.item(key, values=values)
                self.activity_table.move(key, "", position)
            else:
                self.activity_table.insert("", position, iid=key, values=values)
        self.history_count.set(f"{len(visible)} รายการ")
        if visible and self.follow_history.get():
            self.activity_table.see(visible[-1][0])

    def render_results(self) -> None:
        self.render_activity()
        self.render_jobs()

    def selected_details(self, category="activity") -> str:
        selected = self.activity_table.selection()
        if not selected:
            return ""
        event = self.activity.entries[selected[0]]
        fields = (('วัน / เวลา', event["time"]), ('บัญชี', event.get("account") or 'ระบบ'),
                  ('การทำงาน', STEPS.get(int(event["step"]), 'การทำงาน')), ('ผลการทำงาน', STATUS_LABELS.get(event["status"], event["status"])),
                  ('ชื่อไฟล์', event.get("filename", "")), ('รายละเอียด', thai_text(event.get("reason", ""))),
                  ('ปลายทาง', event.get("destination", "")), ('เครื่อง', event.get("machine", "")),
                  ('รอบงาน', event.get("run_id", "")), ("SHA-256", event.get("sha256", "")))
        return "\n".join(f"{label}: {value}" for label, value in fields if value)

    def show_selected(self) -> None:
        details = self.selected_details()
        if details:
            messagebox.showinfo('รายละเอียดการทำงาน', details, parent=self.root)

    def load_history(self) -> None:
        folder = Path(self.settings["log_dir"])
        def work():
            try:
                self.events.put(("history", read_activity(folder, exact_names=True)))
            except Exception as error:
                self.events.put(("notice", f"อ่านประวัติไม่ได้: {thai_text(error)}"))
        threading.Thread(target=work, daemon=True).start()

    def open_logs(self) -> None:
        try:
            os.startfile(str(self.settings["log_dir"]))
        except Exception as error:
            messagebox.showerror('เปิดโฟลเดอร์ประวัติไม่ได้', thai_text(str(error)), parent=self.root)

    def callback_error(self, error_type, error, _trace) -> None:
        self.status.set(f"{error_type.__name__}: {error}")

    def tick(self) -> None:
        if self.closing:
            return
        if not self.smoke:
            if self.instance and self.instance.requested():
                self.show_window()
            for action in self.background_clock.tick(time.time()):
                if action == 'cleanup':
                    self.start_maintenance()
                elif action == 'resume':
                    self.resume_tracking(manual=False)
            if self.resume_pending and not (self.worker and self.worker.is_alive()) and not (self.maintenance_worker and self.maintenance_worker.is_alive()):
                self.resume_tracking(manual=self.resume_manual)
        self.render_jobs()
        self.clock_id = self.root.after(1000, self.tick)

    def close(self) -> None:
        if self.smoke:
            self.exit_fully()
        elif self.tray and self.tray.ready.is_set() and not self.tray.error and not self.tray.stopped.is_set():
            self.hide_passwords()
            self.root.withdraw()
        else:
            self.status.set('ถาดระบบยังไม่พร้อม กรุณาเปิดหน้าต่างไว้ หรือเลือกเครื่องมือ → ออกจากโปรแกรมทั้งหมด')

    def exit_fully(self):
        if self.closing:
            return
        self.closing = True
        self.stop()
        self.maintenance_stop.set()
        self.wait_to_close()

    def wait_to_close(self) -> None:
        if (self.worker and self.worker.is_alive()) or (self.maintenance_worker and self.maintenance_worker.is_alive()):
            self.root.after(250, self.wait_to_close)
        else:
            self.root.after_cancel(self.poll_id)
            self.root.after_cancel(self.clock_id)
            if self.tray:
                self.tray.close()
                if not self.tray.stopped.is_set():
                    self.root.after(100, self.wait_to_close)
                    return
            self.root.destroy()


def launch(smoke_screenshot: Path | None = None, smoke_report: Path | None = None, background=False, instance=None) -> int:
    root = tk.Tk()
    window_icon_applied = apply_window_icon(root)
    root.title("KDE Download")
    root.geometry(f"1180x{min(780, root.winfo_screenheight() - 90)}+20+20")
    root.minsize(1000, 650)
    root.option_add("*Font", ("Tahoma", 11))
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=32, font=("Tahoma", 11))
    style.configure("Treeview.Heading", font=("Tahoma", 11, "bold"))
    app = Application(root, smoke=smoke_screenshot is not None, background=background, instance=instance)
    if smoke_screenshot:
        root.withdraw()
        root.update()
        root.deiconify()
        root.attributes("-topmost", True)
        def capture():
            from PIL import ImageGrab
            from unittest.mock import patch
            moment = time.time()
            for index, status in enumerate(("complete", "waiting", "review", "running", "deferred", "waiting")):
                app.jobs[str(index)] = {"id": str(index), "subject": ["ตรวจไฟล์วันนี้ครบแล้ว", "รอบใหม่จากเมล", "กรุณาตรวจรหัสผ่าน", "กำลังดาวน์โหลดทีละหน้า", "รอเมลใหม่", "บัญชี Post มีผู้ใช้งาน"][index],
                                        "label": "Pre" if index % 2 == 0 else "Post", "status": status,
                                        "attempts": 2 if index == 4 else 1 if index in {0, 3, 5} else 0,
                                        "due": moment + (60 if index == 5 else 270), "sequence": index + 1, "lookup": {}, "last_reason": "ไฟล์ของวันนี้ หน้าละ 30 รายการ ตรวจว่ามีไฟล์แล้วจาก .97"}
                if index == 5:
                    app.jobs[str(index)]["busy_sources"] = ["offline-post"]
            pending = app.jobs.pop('1')
            pending['id'] = 'pending-daily-round'
            app.jobs[pending['id']] = pending
            app.accept_event({'kind': 'mail_health', 'checked': moment, 'count': 12, 'new': 1, 'folders': 3, 'error': ''})
            app.render_jobs()
            mail_health_passed = 'ตรวจเมลล่าสุด' in app.mail_status.get() and 'รอดาวน์โหลด 4:' in app.mail_status.get()
            app.accept_event({'kind': 'mail_health', 'checked': moment, 'error': 'อ่านโฟลเดอร์เมลไม่ได้'})
            app.render_jobs()
            mail_health_passed &= 'ต้องตรวจสอบ' in app.mail_status.get()
            app.accept_event({'kind': 'mail_health', 'checked': moment, 'count': 12, 'new': 1, 'folders': 3, 'error': ''})
            for index in range(12):
                reason = "ไม่มีสิทธิ์บันทึกไฟล์ปลายทาง" if index == 10 else ["พบเมลใหม่ รอ 4 นาที 30 วินาที", "ตรวจวันที่ปัจจุบันจากคอลัมน์บนเว็บ", 'เข้าสู่ระบบสำเร็จ', "ตรวจไฟล์ที่บันทึกไว้ใน .97", "ตรวจสอบไฟล์ดาวน์โหลดแล้ว", "บันทึกไฟล์ปลายทางแล้ว", "ออกจากระบบแล้ว"][index % 7]
                app.accept_event({"key": f"sample-{index}", "time": f"{today()}T10:02:{index:02}+07:00", "step": 7 if index == 10 else 2 + index % 6,
                                  "status": "error" if index == 10 else "stage_complete", "reason": reason, "account": "Pre" if index % 2 == 0 else "Post",
                                  "filename": f"ตัวอย่างไฟล์ {index + 1}", "destination": r"\\10.0.0.97\Z Bot KDE", "attempt": 1})
            app.render_results()
            app.filter.set("ไม่มีสิทธิ์")
            children = app.activity_table.get_children()
            search_passed = len(children) == 1
            if children:
                app.activity_table.selection_set(children[0])
            details_passed = 'รายละเอียด:' in app.selected_details() and 'ปลายทาง:' in app.selected_details()
            app.filter.set("")
            for index in range(2):
                app.variables[f"accounts.{index}.username"].set(f"offline-{index}")
                app.variables[f"accounts.{index}.password"].set("offline-only")
            with patch.object(app, "start") as start:
                app.auto_start(force=True)
                auto_started = start.call_args is not None and start.call_args.args == ("watch",)
            password_toggle_passed = True
            for entry, visible, toggle in app.password_controls.values():
                password_toggle_passed &= entry.cget("show") == "*" and not visible.get()
                toggle.invoke()
                password_toggle_passed &= entry.cget("show") == "" and visible.get()
                toggle.invoke()
                password_toggle_passed &= entry.cget("show") == "*" and not visible.get()
            jobs_before_stop = copy.deepcopy(app.jobs)
            app.set_busy(True)
            app.stop_button.invoke()
            stop_passed = app.stop_event.is_set() and app.jobs == jobs_before_stop and app.stop_button.cget("text") == 'หยุด'
            app.set_busy(False)
            app.stop_event.clear()
            app.fill_settings()
            cleanup_toggle_passed = bool(app.variables['daily_cleanup_enabled'].get())
            app.variables['daily_cleanup_enabled'].set(False)
            cleanup_toggle_passed &= app.collect_settings()['daily_cleanup_enabled'] is False
            app.variables['daily_cleanup_enabled'].set(True)
            from types import SimpleNamespace
            ready = threading.Event()
            ready.set()
            app.tray = SimpleNamespace(ready=ready, error=None, stopped=threading.Event())
            app.smoke = False
            app.close()
            root.update_idletasks()
            close_to_tray_passed = root.state() == 'withdrawn' and not app.stop_event.is_set() and not app.maintenance_stop.is_set()
            with patch.object(app, 'resume_tracking') as resume:
                app.show_window()
                manual_open_passed = resume.call_count == 1
            app.smoke = True
            app.tray = None
            app.status.set("ติดตามเมล data · ไฟล์วันที่ปัจจุบัน · ทำทีละบัญชี")
            smoke_screenshot.parent.mkdir(parents=True, exist_ok=True)
            def screenshot(page, path):
                app.tabs.select(page)
                root.update_idletasks()
                root.update()
                ImageGrab.grab().crop((root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())).save(path)
            screenshot(app.monitor_page, smoke_screenshot)
            screenshot(app.settings_page, smoke_screenshot.with_name(smoke_screenshot.stem + "-settings.png"))
            screenshot(app.activity_page, smoke_screenshot.with_name(smoke_screenshot.stem + "-history.png"))
            report = {"gui_started": True, "version": VERSION, "language": "th", "tab_count": len(app.tabs.tabs()),
                      "window_icon_applied": window_icon_applied, "header_icon_applied": app.brand_icon is not None,
                      "activity_rows": len(app.activity_table.get_children()), "mail_queue_rows": len(app.job_table.get_children()),
                      "error_rows": 1, "fixed_step_checklist": False, "theme_selector": False, "account_folder_overrides": False,
                      "history_search_passed": search_passed, "readable_event_details": details_passed, "auto_start_passed": auto_started,
                      "password_toggle_passed": bool(password_toggle_passed), "stop_control_passed": stop_passed,
                      "mail_delay_seconds": app.settings["mail_delay_seconds"], "login_retry_seconds": app.settings["login_retry_seconds"],
                      "max_session_attempts": None, "today_only": app.settings["mail_watch"]["today_only"],
                      "deferred_status_visible": any('รอเมลใหม่' in app.job_table.item(key, "values") for key in app.job_table.get_children()),
                      "busy_status_visible": any('บัญชีมีผู้ใช้งาน' in app.job_table.item(key, "values") for key in app.job_table.get_children()),
                      "download_policy": "daily_all", "email_content_matching": False, "ocr_enabled": False,
                      "skip_either_destination": False, "busy_attempts_total": None,
                      "tracker_source": "new_dir", "sequential_accounts": True, "portal_rows_per_page": 30,
                      "page_by_page": True, "login_retry_unlimited": True,
                      "mail_health_display_passed": mail_health_passed, "whole_mailbox_trigger": True, "stop_at_older_dates": True,
                      "daily_cleanup_enabled": app.settings['daily_cleanup_enabled'], "daily_cleanup_time": '22:00',
                      "daily_cleanup_toggle_passed": cleanup_toggle_passed,
                      "daily_cleanup_preserves_all_folders": True, "daily_cleanup_requires_monitor": False,
                      "daily_cleanup_task_registered_live": False, "daily_cleanup_skips_deleted_names": True,
                      "task_scheduler_required": False, "close_to_tray": close_to_tray_passed, "tracking_pause": '22:00',
                      "tracking_resume": '05:00', "manual_open_resumes": manual_open_passed, "background_app_required": True,
                      "includes_read_mail": not app.settings["mail_watch"]["unread_only"], "machine": socket.gethostname(), "live_portal_access": False}
            if smoke_report:
                smoke_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            app.close()
        root.after(800, capture)
    root.mainloop()
    return 0
