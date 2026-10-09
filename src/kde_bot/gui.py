"""Plain Version 1 style Tkinter/ttk GUI; all worker operations stay off the UI thread."""

from __future__ import annotations

import copy
import csv
import json
import os
import queue
import socket
import threading
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from . import VERSION
from .settings import (
    import_settings, load_settings, save_settings, settings_home, validate_settings,
)
from .storage import History, WorkerLock, timestamp
from .workflow import STEPS, run_cycle


STATUS_LABELS = {
    "running": "กำลังทำงาน", "stage_complete": "ผ่าน", "complete": "สำเร็จ",
    "skipped": "มีไฟล์ครบแล้ว", "copy_pending": "รอคัดลอก", "error": "ผิดพลาด",
    "warning": "ต้องตรวจสอบ", "summary": "สรุปรอบ",
}
MODES = {"เก็บทั้งสองที่ (ดาวน์โหลดเดิม แล้วคัดลอกใหม่)": "both",
         "เก็บเฉพาะที่เดิม": "original", "เก็บเฉพาะที่ใหม่": "new"}


class Application(ttk.Frame):
    def __init__(self, root: tk.Tk, smoke: bool = False):
        super().__init__(root, padding=12)
        self.root = root
        self.smoke = smoke
        self.settings, self.notices = load_settings()
        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.rows: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.variables: dict[str, tk.Variable] = {}
        self.tables: dict[str, ttk.Treeview] = {}
        self.busy_buttons: list[ttk.Button] = []
        self.status = tk.StringVar(value="พร้อมทำงาน — กรุณาตรวจการตั้งค่าของเครื่องนี้")
        self.summary = tk.StringVar(value="สำเร็จ 0  |  รอคัดลอก 0  |  ผิดพลาด 0  |  มีครบแล้ว 0")
        self.filter = tk.StringVar()
        self.current_step = tk.StringVar(value="ยังไม่ได้เริ่มงาน")
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.build_controls()
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky="nsew", pady=8)
        self.build_steps()
        self.build_result("complete", "Complete — สำเร็จ")
        self.build_result("error", "Error — ผิดพลาด / รอคัดลอก")
        self.build_result("skipped", "ข้าม — มีไฟล์ครบแล้ว")
        self.settings_page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.settings_page, text="ตั้งค่า")
        self.build_settings()
        ttk.Label(self, textvariable=self.current_step, wraplength=1100).grid(row=4, column=0, sticky="w")
        ttk.Label(self, text=f"เครื่อง: {socket.gethostname()}  |  Windows user: {os.environ.get('USERNAME', '')}").grid(row=5, column=0, sticky="w", pady=(5, 0))
        self.fill_settings()
        self.filter.trace_add("write", lambda *_: self.render_results())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.callback_error
        self.poll_id = self.root.after(100, self.drain_events)
        if self.notices:
            self.status.set("ต้องตั้งค่าเครื่องนี้ก่อนเริ่มงาน")
            self.notice_label.configure(text="\n".join(self.notices))
            self.tabs.select(self.settings_page)

    def build_controls(self) -> None:
        ttk.Label(self, text=f"KDE Bot Download V3 — {VERSION}", font=("Leelawadee UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky="ew", pady=(10, 5))
        actions = [
            ("ตรวจหนึ่งครั้ง", lambda: self.start("once")),
            ("ตรวจอัตโนมัติ", lambda: self.start("auto")),
            ("ตรวจอีเมล", lambda: self.start("scan")),
            ("ตรวจสิทธิ์ / Browser", lambda: self.start("check")),
            ("ลองคัดลอกที่ค้าง", lambda: self.start("retry")),
        ]
        for column, (label, action) in enumerate(actions):
            button = ttk.Button(controls, text=label, command=action)
            button.grid(row=0, column=column, padx=(0, 6))
            self.busy_buttons.append(button)
        self.stop_button = ttk.Button(controls, text="หยุด", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=len(actions))
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, textvariable=self.status).grid(row=0, column=0, sticky="w")
        ttk.Label(bar, textvariable=self.summary).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(bar, text="ค้นหาไฟล์:").grid(row=0, column=1, padx=8)
        ttk.Entry(bar, textvariable=self.filter, width=24).grid(row=0, column=2)

    def build_steps(self) -> None:
        page = ttk.Frame(self.tabs, padding=8)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.tabs.add(page, text="ขั้นตอน")
        self.steps_page = page
        ttk.Label(page, text="ลำดับงานปัจจุบัน — ผลต่อไฟล์อยู่ใน Complete / Error / ข้าม").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.step_table = ttk.Treeview(page, columns=("step", "status", "reason"), show="headings")
        for field, title, width in (("step", "ขั้นตอน", 280), ("status", "สถานะ", 120), ("reason", "รายละเอียด / สาเหตุ", 660)):
            self.step_table.heading(field, text=title)
            self.step_table.column(field, width=width, minwidth=80)
        self.step_table.grid(row=1, column=0, sticky="nsew")
        for number, name in STEPS.items():
            self.step_table.insert("", "end", iid=str(number), values=(f"{number}. {name}", "รอ", ""))

    def build_result(self, kind: str, title: str) -> None:
        page = ttk.Frame(self.tabs, padding=8)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.tabs.add(page, text=title)
        bar = ttk.Frame(page)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(bar, text="โหลดประวัติ CSV", command=self.load_history).pack(side="left")
        ttk.Button(bar, text="เปิดโฟลเดอร์ Log", command=self.open_logs).pack(side="left", padx=8)
        ttk.Button(bar, text="คัดลอกรายละเอียดที่เลือก", command=lambda category=kind: self.copy_selected(category)).pack(side="left")
        columns = ("time", "account", "filename", "step", "status", "reason", "destination", "attempt")
        table = ttk.Treeview(page, columns=columns, show="headings", selectmode="browse")
        titles = ("เวลา", "บัญชี", "ชื่อไฟล์", "ขั้นตอน", "ผล", "รายละเอียด / สาเหตุ", "ปลายทาง", "ครั้ง")
        widths = (135, 130, 260, 170, 110, 350, 280, 50)
        for field, heading, width in zip(columns, titles, widths):
            table.heading(field, text=heading)
            table.column(field, width=width, minwidth=45, stretch=field in {"filename", "reason"})
        table.grid(row=1, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(page, orient="vertical", command=table.yview)
        horizontal = ttk.Scrollbar(page, orient="horizontal", command=table.xview)
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tables[kind] = table
        table.bind("<Double-1>", lambda _event, category=kind: self.show_selected(category))

    def build_settings(self) -> None:
        self.settings_page.columnconfigure(0, weight=1)
        self.settings_page.rowconfigure(2, weight=1)
        bar = ttk.Frame(self.settings_page)
        bar.grid(row=0, column=0, sticky="ew")
        for label, command in (
            ("บันทึกการตั้งค่า", self.save_configuration),
            ("นำเข้าการตั้งค่าเดิม", self.import_configuration),
            ("นำเข้าประวัติดาวน์โหลด", self.import_history),
            ("เปิดโฟลเดอร์ตั้งค่าของเครื่องนี้", lambda: self.open_folder(settings_home())),
        ):
            button = ttk.Button(bar, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            self.busy_buttons.append(button)
        self.notice_label = ttk.Label(self.settings_page, text="", wraplength=1100)
        self.notice_label.grid(row=1, column=0, sticky="w", pady=8)
        settings_tabs = ttk.Notebook(self.settings_page)
        settings_tabs.grid(row=2, column=0, sticky="nsew")
        general = self.scrollable_form(settings_tabs, "บัญชีและที่เก็บไฟล์")
        advanced = self.scrollable_form(settings_tabs, "Outlook / เวลา / Browser")
        general.columnconfigure(1, weight=1)
        advanced.columnconfigure(1, weight=1)
        self.add_field(general, 0, "วิธีเก็บไฟล์", "storage_mode", choices=list(MODES))
        self.add_field(general, 1, "โฟลเดอร์เดิม", "original_dir", browse="folder")
        self.add_field(general, 2, "โฟลเดอร์ใหม่", "new_dir", browse="folder")
        self.add_field(general, 3, "โฟลเดอร์ Log", "log_dir", browse="folder")
        for index in range(2):
            frame = ttk.LabelFrame(general, text="บัญชี Pre" if index == 0 else "บัญชี Post", padding=10)
            frame.grid(row=4 + index, column=0, columnspan=3, sticky="ew", pady=(12, 0))
            frame.columnconfigure(1, weight=1)
            prefix = f"accounts.{index}."
            self.add_field(frame, 0, "ใช้งานบัญชี", prefix + "enabled", boolean=True)
            self.add_field(frame, 1, "ชื่อแสดง", prefix + "label")
            self.add_field(frame, 2, "ชื่อผู้ใช้ KDE", prefix + "username")
            self.add_field(frame, 3, "รหัสผ่าน KDE", prefix + "password", password=True)
            self.add_field(frame, 4, "โฟลเดอร์เดิมเฉพาะบัญชี (ว่าง = ใช้ด้านบน)", prefix + "original_dir", browse="folder")
        ttk.Label(general, text="รหัสผ่านเก็บเฉพาะ Windows user เครื่องนี้ • เปิดเครื่องใหม่แล้วตั้งค่าหรือนำเข้าใหม่ • โปรแกรมไม่เริ่มดาวน์โหลดเอง",
                  wraplength=950).grid(row=6, column=0, columnspan=3, sticky="w", pady=12)
        advanced_fields = [
            ("จับคู่ Outlook ก่อนดาวน์โหลด", "mail_watch.enabled", "bool"),
            ("Outlook mailbox", "mail_watch.mailbox_filter", "text"),
            ("ตรวจเฉพาะอีเมลวันนี้", "mail_watch.today_only", "bool"),
            ("ค้นหาชื่อไฟล์ในเนื้อหาอีเมลด้วย", "mail_watch.include_body", "bool"),
            ("จำนวนอีเมลสูงสุดต่อโฟลเดอร์", "mail_watch.max_messages_per_folder", "number"),
            ("จำนวนตัวอักษร Body สูงสุด", "mail_watch.max_body_chars", "number"),
            ("ใช้ Browser แบบไม่มีหน้าต่าง", "headless", "bool"),
            ("Browser (ว่าง = ตรวจ Chrome/Edge อัตโนมัติ)", "chrome_path", "file"),
            ("รอบตรวจอัตโนมัติ (วินาที)", "loop_wait_seconds", "number"),
            ("พักระหว่างไฟล์ (วินาที)", "download_delay_seconds", "number"),
            ("รอบรอเมื่อบัญชีถูกใช้งาน (วินาที)", "busy_wait_seconds", "number"),
            ("หมดเวลารอหน้าเว็บ (วินาที)", "page_timeout_seconds", "number"),
            ("จำนวนหน้า KDE สูงสุด", "max_pages", "number"),
            ("ช่วงค้นหา KDE (วัน)", "search_days", "number"),
            ("KDE Portal URL", "portal_url", "text"),
            ("KDE Host URL", "host_url", "text"),
            ("KDE Auth API URL", "auth_api_url", "text"),
            ("รูปแบบชื่อไฟล์ Outlook (ว่าง = ค่าเดิม)", "mail_watch.filename_regex", "text"),
        ]
        for row, (label, path, kind) in enumerate(advanced_fields):
            self.add_field(advanced, row, label, path, boolean=kind == "bool",
                           browse="file" if kind == "file" else "")

    def scrollable_form(self, notebook: ttk.Notebook, title: str) -> ttk.Frame:
        page = ttk.Frame(notebook)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        notebook.add(page, text=title)
        canvas = tk.Canvas(page, highlightthickness=0, background=self.root.cget("background"))
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        form = ttk.Frame(canvas, padding=12)
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"))
        return form

    def add_field(self, parent: ttk.Frame, row: int, label: str, path: str,
                  boolean: bool = False, password: bool = False,
                  browse: str = "", choices: list[str] | None = None) -> None:
        variable = tk.BooleanVar() if boolean else tk.StringVar()
        self.variables[path] = variable
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        if boolean:
            ttk.Checkbutton(parent, variable=variable).grid(row=row, column=1, sticky="w", pady=3)
            return
        if choices:
            entry = ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly")
        else:
            entry = ttk.Entry(parent, textvariable=variable, show="*" if password else "", width=65)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        if browse:
            ttk.Button(parent, text="เลือก", command=lambda: self.browse(variable, browse)).grid(row=row, column=2, padx=6)
        if password:
            reveal = tk.BooleanVar()
            ttk.Checkbutton(parent, text="แสดง", variable=reveal,
                            command=lambda: entry.configure(show="" if reveal.get() else "*")).grid(row=row, column=2, padx=6)

    @staticmethod
    def lookup(settings: dict[str, Any], path: str) -> Any:
        value: Any = settings
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value

    def fill_settings(self) -> None:
        from .settings import default_settings
        while len(self.settings["accounts"]) < 2:
            self.settings["accounts"].append(default_settings()["accounts"][len(self.settings["accounts"])])
            self.settings["accounts"][-1]["enabled"] = False
        for path, variable in self.variables.items():
            value = self.lookup(self.settings, path)
            if path == "storage_mode":
                value = next(label for label, mode in MODES.items() if mode == value)
            variable.set(value)

    def collect_settings(self) -> dict[str, Any]:
        result = copy.deepcopy(self.settings)
        for path, variable in self.variables.items():
            value: Any = variable.get()
            old = self.lookup(result, path)
            if path == "storage_mode":
                value = MODES[value]
            elif isinstance(old, int) and not isinstance(old, bool):
                value = int(value)
            elif isinstance(value, str) and not path.endswith(".password"):
                value = value.strip()
            target: Any = result
            parts = path.split(".")
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value
        validate_settings(result, require_credentials=False)
        return result

    def browse(self, variable: tk.Variable, kind: str) -> None:
        selected = filedialog.askdirectory(parent=self.root) if kind == "folder" else filedialog.askopenfilename(parent=self.root)
        if selected:
            variable.set(selected)

    def save_configuration(self) -> None:
        try:
            settings = self.collect_settings()
            save_settings(settings)
            self.settings = settings
            missing = [account["label"] for account in settings["accounts"]
                       if account["enabled"] and (not account["username"] or not account["password"])]
            self.notice_label.configure(text="บันทึกแล้ว — ต้องกรอกบัญชี: " + ", ".join(missing) if missing else "บันทึกแล้วสำหรับ Windows user เครื่องนี้")
            self.status.set("บันทึกการตั้งค่าแล้ว")
        except Exception as error:
            messagebox.showerror("บันทึกไม่ได้", str(error), parent=self.root)

    def import_configuration(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="เลือก config.json หรือ settings.json ของ KDE เดิม",
                                          filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self.settings, notices = import_settings(Path(path))
            self.fill_settings()
            self.notice_label.configure(text="\n".join(notices) or "นำเข้าแล้ว กรุณาตรวจและบันทึก")
        except Exception as error:
            messagebox.showerror("นำเข้าไม่ได้", str(error), parent=self.root)

    def import_history(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="เลือก state.json / kde.json / KDE_State.json",
                                          filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            settings = self.collect_settings()
        except Exception as error:
            messagebox.showerror("การตั้งค่าไม่ถูกต้อง", str(error), parent=self.root)
            return
        self.set_busy(True)

        def work():
            try:
                folder = Path(settings["log_dir"])
                with WorkerLock(folder):
                    count = History(folder).import_legacy(Path(path))
                self.events.put(("notice", f"นำเข้าประวัติใหม่ {count} รายการ โดยเก็บประวัติ V3 เดิมไว้"))
            except Exception as error:
                self.events.put(("failure", str(error)))
            finally:
                self.events.put(("idle", None))

        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def start(self, mode: str) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            settings = self.collect_settings()
            validate_settings(settings, require_credentials=mode not in {"scan", "check", "retry"})
            save_settings(settings)
            self.settings = settings
        except Exception as error:
            self.tabs.select(self.settings_page)
            messagebox.showerror("ยังเริ่มงานไม่ได้", str(error), parent=self.root)
            return
        self.stop_event.clear()
        self.set_busy(True)
        self.tabs.select(self.steps_page)

        def work():
            try:
                while not self.stop_event.is_set():
                    counts = run_cycle(
                        settings, self.stop_event, lambda event: self.events.put(("event", event)),
                        scan_only=mode == "scan", check_only=mode == "check", retry_only=mode == "retry",
                    )
                    self.events.put(("counts", counts))
                    if mode != "auto":
                        break
                    self.events.put(("notice", f"รอรอบถัดไป {settings['loop_wait_seconds']} วินาที"))
                    if self.stop_event.wait(settings["loop_wait_seconds"]):
                        break
            except Exception as error:
                text = str(error)
                for account in settings["accounts"]:
                    if account["password"]:
                        text = text.replace(account["password"], "[REDACTED]")
                self.events.put(("event", {
                    "key": "startup-error", "time": timestamp(), "account": "", "filename": "",
                    "step": 1, "status": "error", "reason": f"{type(error).__name__}: {text}",
                    "destination": "", "attempt": 1,
                }))
                self.events.put(("failure", text))
            finally:
                self.events.put(("idle", None))

        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.status.set("กำลังหยุด — รอการดาวน์โหลด/คัดลอกปัจจุบันและ Logout จบ")

    def set_busy(self, busy: bool) -> None:
        for button in self.busy_buttons:
            button.configure(state="disabled" if busy else "normal")
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
            elif kind == "counts":
                self.summary.set(
                    f"สำเร็จ {value['complete']}  |  รอคัดลอก {value['copy_pending']}  |  "
                    f"ผิดพลาด {value['error']}  |  มีครบแล้ว {value['skipped']}"
                )
            elif kind == "failure":
                self.status.set("พบข้อผิดพลาด: " + value)
            elif kind == "notice":
                self.status.set(value)
            elif kind == "history":
                for event in value:
                    self.rows[event["key"]] = event
                changed = True
            elif kind == "idle":
                self.set_busy(False)
        if changed:
            self.render_results()
        self.poll_id = self.root.after(100, self.drain_events)

    def accept_event(self, event: dict[str, Any]) -> None:
        step = int(event["step"])
        label = STATUS_LABELS.get(event["status"], event["status"])
        self.step_table.item(str(step), values=(f"{step}. {STEPS[step]}", label, event["reason"]))
        self.current_step.set(f"{step}. {STEPS[step]} — {event['reason']}")
        if event["status"] == "summary":
            self.status.set(event["reason"])
        elif event["status"] in {"error", "copy_pending", "warning"}:
            self.status.set(f"ขั้นตอน {step}: {event['reason']}")
        if event["filename"] or event["status"] in {"error", "warning"}:
            key = event["key"]
            previous = self.rows.get(key)
            if event["status"] == "running" and previous and previous["status"] in {"error", "copy_pending"}:
                # Keep a pending delivery visible in Error until it actually succeeds.
                return
            self.rows[key] = event
            self.rows.move_to_end(key)
            while len(self.rows) > 2000:
                self.rows.popitem(last=False)

    def render_results(self) -> None:
        search = self.filter.get().casefold()
        categorized = {"complete": [], "error": [], "skipped": []}
        for key, event in self.rows.items():
            if search and search not in (event["filename"] + " " + event["reason"] + " " + event["account"]).casefold():
                continue
            status = event["status"]
            category = "error" if status in {"error", "copy_pending", "warning"} else status
            if category in categorized:
                categorized[category].append((key, event))
        for category, table in self.tables.items():
            desired = {key for key, _ in categorized[category]}
            for key in table.get_children():
                if key not in desired:
                    table.delete(key)
            for key, event in categorized[category]:
                step = int(event["step"])
                values = (
                    str(event["time"]).replace("T", " ")[:19], event["account"], event["filename"],
                    f"{step}. {STEPS[step]}", STATUS_LABELS.get(event["status"], event["status"]),
                    event["reason"], event["destination"], event.get("attempt", 1),
                )
                if table.exists(key):
                    table.item(key, values=values)
                else:
                    table.insert("", "end", iid=key, values=values)

    def selected_details(self, category: str) -> str:
        selected = self.tables[category].selection()
        if not selected:
            return ""
        event = self.rows[selected[0]]
        return json.dumps(event, ensure_ascii=False, indent=2)

    def copy_selected(self, category: str) -> None:
        details = self.selected_details(category)
        if details:
            self.root.clipboard_clear()
            self.root.clipboard_append(details)

    def show_selected(self, category: str) -> None:
        details = self.selected_details(category)
        if details:
            messagebox.showinfo("รายละเอียดขั้นตอน", details, parent=self.root)

    def load_history(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            folder = Path(self.collect_settings()["log_dir"])
        except Exception as error:
            messagebox.showerror("อ่านประวัติไม่ได้", str(error), parent=self.root)
            return
        self.set_busy(True)

        def work():
            try:
                latest: OrderedDict[str, dict[str, Any]] = OrderedDict()
                from .storage import record_key
                for path in sorted(folder.glob("KDE_Log_*.csv"))[-3:]:
                    with path.open(encoding="utf-8-sig", newline="") as stream:
                        for row in csv.DictReader(stream):
                            if not row.get("filename") and row.get("status") not in {"error", "warning"}:
                                continue
                            row["step"] = int(row["step"])
                            row["key"] = record_key(row["account"], row["filename"]) if row["filename"] else f"stage:{row['account']}:{row['step']}"
                            latest[row["key"]] = row
                            latest.move_to_end(row["key"])
                            while len(latest) > 2000:
                                latest.popitem(last=False)
                self.events.put(("history", list(latest.values())))
            except Exception as error:
                self.events.put(("failure", str(error)))
            finally:
                self.events.put(("idle", None))

        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def open_folder(self, folder: Path) -> None:
        try:
            if folder == settings_home():
                folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except Exception as error:
            messagebox.showerror("เปิดโฟลเดอร์ไม่ได้", str(error), parent=self.root)

    def open_logs(self) -> None:
        self.open_folder(Path(self.variables["log_dir"].get()))

    def callback_error(self, error_type, error, _trace) -> None:
        self.status.set(f"{error_type.__name__}: {error}")

    def close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.stop()
            self.status.set("กำลังหยุดและออกจากระบบก่อนปิดหน้าต่าง")
            self.root.after(250, self.wait_to_close)
            return
        self.root.after_cancel(self.poll_id)
        self.root.destroy()

    def wait_to_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.root.after(250, self.wait_to_close)
            return
        self.close()


def launch(smoke_screenshot: Path | None = None, smoke_report: Path | None = None) -> int:
    root = tk.Tk()
    root.title("KDE Bot Download V3")
    root.geometry("1220x850")
    root.minsize(1000, 700)
    root.option_add("*Font", ("Leelawadee UI", 10))
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=28, font=("Leelawadee UI", 10))
    style.configure("Treeview.Heading", font=("Leelawadee UI", 10, "bold"))
    app = Application(root, smoke=smoke_screenshot is not None)
    if smoke_screenshot:
        def capture():
            from PIL import ImageGrab
            app.tabs.select(app.steps_page)
            for step in STEPS:
                app.accept_event({
                    "key": f"smoke:{step}", "time": timestamp(), "step": step,
                    "status": "stage_complete", "reason": "ตัวอย่างขั้นตอน — ยังไม่ได้เชื่อมต่อ KDE",
                    "filename": "", "account": "Pre", "destination": "", "attempt": 1,
                })
            app.accept_event({
                "key": "smoke-file", "time": timestamp(), "step": 7,
                "status": "copy_pending", "reason": "ตัวอย่าง: ดาวน์โหลดแล้ว แต่ไม่มีสิทธิ์เขียนโฟลเดอร์ใหม่",
                "filename": "A1015_PAYMENT_09102026.zip.gpg", "account": "Pre",
                "destination": r"\\10.0.0.97\Z Bot KDE", "attempt": 1,
            })
            app.render_results()
            root.update_idletasks()
            smoke_screenshot.parent.mkdir(parents=True, exist_ok=True)
            root.update()
            ImageGrab.grab().crop((
                root.winfo_rootx(), root.winfo_rooty(),
                root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height(),
            )).save(smoke_screenshot)
            app.tabs.select(app.settings_page)

            def capture_settings():
                root.update_idletasks()
                root.update()
                ImageGrab.grab().crop((
                    root.winfo_rootx(), root.winfo_rooty(),
                    root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height(),
                )).save(smoke_screenshot.with_name(smoke_screenshot.stem + "-settings.png"))
                report = {
                    "gui_started": True, "steps": len(STEPS), "theme_selector": False,
                    "credential_recovery_notices": app.notices,
                    "error_rows": len(app.tables["error"].get_children()),
                    "machine": socket.gethostname(),
                    "live_portal_access": False,
                }
                if smoke_report:
                    smoke_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                app.close()

            root.after(350, capture_settings)
        root.after(1000, capture)
    root.mainloop()
    return 0
