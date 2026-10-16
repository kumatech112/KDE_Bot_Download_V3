"""Simple English monitoring UI; all Outlook, OCR and portal work runs in workers."""

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
from .activity import ActivityHistory, read_activity, update_latest
from .evidence import IMAGE_SUFFIXES, today
from .settings import import_settings, load_settings, save_settings, validate_settings
from .storage import History, WorkerLock, timestamp
from .workflow import STEPS, run_cycle


STATUS_LABELS = {"running": "Working", "stage_complete": "OK", "complete": "Done",
                 "skipped": "Already saved", "copy_pending": "Save pending", "error": "Failed",
                 "warning": "Needs review", "summary": "Monitor", "waiting": "Queued", "notice": "Info"}
JOB_LABELS = {"waiting": "Queued", "running": "Working", "complete": "Done", "copy_pending": "Save pending",
              "exhausted": "Failed (2/2)", "review": "Needs review", "expired": "Previous day"}
MODES = {"Both destinations": "both", "Original destination only": "original", "New destination only": "new"}


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
    def __init__(self, root: tk.Tk, smoke: bool = False):
        super().__init__(root, padding=16)
        self.root = root
        self.smoke = smoke
        self.settings, self.notices = load_settings()
        self.events: queue.Queue = queue.Queue()
        self.requests: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.rows: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.activity = ActivityHistory()
        self.variables: dict[str, tk.Variable] = {}
        self.inputs: list[Any] = []
        self.busy_buttons: list[Any] = []
        self.status = tk.StringVar(value="Ready")
        self.summary = tk.StringVar(value="No requests yet")
        self.current_step = tk.StringVar(value="Today's mail · 2-minute delay · Two attempts · Separate Pre/Post queues")
        self.filter = tk.StringVar()
        self.follow_history = tk.BooleanVar(value=True)
        self.history_count = tk.StringVar(value="0 events")
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.build_controls()
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky="nsew", pady=(12, 8))
        self.build_monitor()
        self.build_activity()
        self.settings_page = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(self.settings_page, text="Settings")
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
            self.status.set("Setup required")
            self.tabs.select(self.settings_page)
        if not smoke:
            root.after(400, self.auto_start)
            root.after(600, self.load_history)

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
        self.start_button = ttk.Button(toolbar, text="Start monitor", command=lambda: self.start("watch"))
        self.start_button.pack(side="left")
        self.busy_buttons.append(self.start_button)
        self.stop_button = ttk.Button(toolbar, text="Pause", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        ttk.Button(toolbar, text="Import image", command=self.import_image).pack(side="left", padx=(8, 6))
        ttk.Button(toolbar, text="Review request", command=self.review_request).pack(side="left")
        tools = ttk.Menubutton(toolbar, text="Tools")
        menu = tk.Menu(tools, tearoff=False)
        menu.add_command(label="Check connection", command=lambda: self.start("check"))
        menu.add_command(label="Repair pending saves", command=self.repair_saves)
        menu.add_command(label="Retry failed requests", command=self.retry_failed)
        menu.add_separator()
        menu.add_command(label="Import settings", command=self.import_configuration)
        menu.add_command(label="Import old history", command=self.import_history)
        menu.add_command(label="Open logs", command=self.open_logs)
        tools.configure(menu=menu)
        tools.pack(side="right")
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, textvariable=self.status, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(bar, textvariable=self.summary).grid(row=0, column=1, sticky="e")

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
        self.tabs.add(page, text="Monitor")
        self.monitor_page = page
        self.job_table = self.make_table(page, ("order", "account", "subject", "status", "ready", "attempts", "reference"),
                                         ("#", "Account", "Email / image", "Status", "Wait", "Attempts", "Reference"),
                                         (45, 85, 280, 115, 70, 70, 280))
        self.job_table.bind("<Double-1>", lambda _event: self.review_request())
        ttk.Label(page, text="Today's requests, in queue order. Double-click a request for details.").grid(row=2, column=0, sticky="w", pady=(8, 0))

    def build_activity(self) -> None:
        page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(page, text="History")
        self.activity_page = page
        bar = ttk.Frame(page)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(bar, text="Refresh", command=self.load_history).pack(side="left")
        ttk.Checkbutton(bar, text="Follow latest", variable=self.follow_history).pack(side="left", padx=12)
        ttk.Label(bar, text="Search").pack(side="left", padx=(12, 6))
        ttk.Entry(bar, textvariable=self.filter, width=28).pack(side="left")
        ttk.Label(bar, textvariable=self.history_count).pack(side="right")
        self.activity_table = self.make_table(page, ("time", "account", "action", "status", "filename", "reason"),
                                             ("Time", "Account", "Action", "Result", "File / email", "Details"),
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
        if browse:
            button = ttk.Button(parent, text="Browse", command=lambda: self.browse(variable))
            button.grid(row=row, column=2, padx=(8, 0))
            self.busy_buttons.append(button)

    def build_settings(self) -> None:
        page = self.settings_page
        page.columnconfigure(1, weight=1)
        self.notice_label = ttk.Label(page, text="Accounts are encrypted for this Windows user. Save once, then monitoring starts automatically.", wraplength=1050)
        self.notice_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        self.add_field(page, 1, "Outlook mailbox", "mail_watch.mailbox_filter")
        self.add_field(page, 2, "Save to", "storage_mode", choices=list(MODES))
        self.add_field(page, 3, "Original destination", "original_dir", browse=True)
        self.add_field(page, 4, "New destination", "new_dir", browse=True)
        self.add_field(page, 5, "Log folder", "log_dir", browse=True)
        accounts = ttk.Frame(page)
        accounts.grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)
        for index, title in enumerate(("Pre", "Post")):
            accounts.columnconfigure(index, weight=1)
            frame = ttk.LabelFrame(accounts, text=title, padding=12)
            frame.grid(row=0, column=index, sticky="nsew", padx=(0, 8) if index == 0 else (8, 0))
            frame.columnconfigure(1, weight=1)
            prefix = f"accounts.{index}."
            self.add_field(frame, 0, "Enabled", prefix + "enabled", boolean=True)
            self.add_field(frame, 1, "Username", prefix + "username")
            self.add_field(frame, 2, "Password", prefix + "password", password=True)
        buttons = ttk.Frame(page)
        buttons.grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 12))
        save = ttk.Button(buttons, text="Save & start", command=self.save_configuration)
        save.pack(side="left")
        self.busy_buttons.append(save)
        advanced = ttk.Button(buttons, text="More options", command=self.advanced_settings)
        advanced.pack(side="left", padx=10)
        self.busy_buttons.append(advanced)
        ttk.Label(page, text="Both accounts save directly in the selected folders. No test files or account subfolders.\nToday only · Read and unread mail · 2-minute delay · Two attempts per request", wraplength=1050).grid(row=8, column=0, columnspan=3, sticky="w")

    def advanced_settings(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("More options")
        window.transient(self.root)
        window.columnconfigure(1, weight=1)
        fields = [("Outlook poll (seconds)", "mail_poll_seconds"), ("Messages per folder", "mail_watch.max_messages_per_folder"),
                  ("Portal page limit", "max_pages"), ("Page timeout (seconds)", "page_timeout_seconds"),
                  ("Delay between files (seconds)", "download_delay_seconds"), ("Browser path (optional)", "chrome_path")]
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
                messagebox.showerror("Invalid option", str(error), parent=window)
        ttk.Button(window, text="Apply", command=apply).grid(row=len(fields), column=1, sticky="e", padx=12, pady=12)

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
            self.notice_label.configure(text="Saved for this Windows user.")
            self.start("watch")
        except Exception as error:
            messagebox.showerror("Cannot save", str(error), parent=self.root)

    def auto_start(self, force=False) -> None:
        if self.smoke and not force:
            return
        try:
            validate_settings(self.collect_settings())
        except Exception:
            self.status.set("Setup required — enter the enabled account credentials")
            self.tabs.select(self.settings_page)
            return
        self.start("watch")

    def import_configuration(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Pause first", "Pause the monitor before changing settings.", parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title="Import KDE settings", filetypes=[("JSON", "*.json")])
        if path:
            try:
                self.settings, self.notices = import_settings(Path(path))
                self.fill_settings()
                self.tabs.select(self.settings_page)
                self.notice_label.configure(text="Imported. Check the accounts, then Save & start.")
            except Exception as error:
                messagebox.showerror("Import failed", str(error), parent=self.root)

    def import_history(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Pause first", "Pause the monitor before importing history.", parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, title="Import old KDE history", filetypes=[("JSON", "*.json")])
        if not path:
            return
        settings = self.collect_settings()
        def work():
            try:
                with WorkerLock(Path(settings["log_dir"])):
                    count = History(Path(settings["log_dir"])).import_legacy(Path(path))
                self.events.put(("notice", f"Imported {count} history records."))
            except Exception as error:
                self.events.put(("failure", str(error)))
            finally:
                self.events.put(("idle", None))
        self.set_busy(True)
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def import_image(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Import a screenshot or image",
                                          filetypes=[("Images", " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES)))])
        if not path:
            return
        window = tk.Toplevel(self.root)
        window.title("Image request")
        window.transient(self.root)
        ttk.Label(window, text=Path(path).name, wraplength=500).pack(padx=20, pady=14)
        ttk.Label(window, text="Which account should receive this request?").pack(padx=20)
        side = tk.StringVar(value="Pre")
        ttk.Combobox(window, textvariable=side, values=["Pre", "Post"], state="readonly").pack(padx=20, pady=10)
        def submit():
            if not self.worker or not self.worker.is_alive():
                self.start("watch")
            if self.worker and self.worker.is_alive():
                self.requests.put({"kind": "image", "path": path, "side": side.get().lower()})
                window.destroy()
        ttk.Button(window, text="Read image & queue", command=submit).pack(padx=20, pady=14)

    def review_request(self) -> None:
        selected = self.job_table.selection()
        if not selected:
            return
        job = self.jobs[selected[0]]
        if job["status"] not in {"review", "exhausted"}:
            details = f"{job.get('subject', '')}\n\n{job.get('last_reason', '')}\n\n" + "\n".join(job["lookup"])
            messagebox.showinfo("Request details", details, parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("Review request")
        window.transient(self.root)
        ttk.Label(window, text=job.get("subject", ""), wraplength=600).pack(padx=20, pady=12)
        ttk.Label(window, text=job.get("last_reason", ""), wraplength=600).pack(padx=20)
        accounts = {account["label"]: account["username"] for account in self.settings["accounts"] if account["enabled"]}
        account = tk.StringVar(value=job["label"] if job["label"] in accounts else next(iter(accounts), ""))
        ttk.Combobox(window, textvariable=account, values=list(accounts), state="readonly").pack(padx=20, pady=10)
        ttk.Label(window, text="Confirm the filename or business reference").pack(padx=20)
        reference = tk.Text(window, width=75, height=6, wrap="word")
        reference.pack(padx=20, pady=10)
        reference.insert("1.0", "\n".join(job["lookup"]))
        def submit():
            value = reference.get("1.0", "end").strip()
            if not value or account.get() not in accounts:
                return
            if not self.worker or not self.worker.is_alive():
                self.start("watch")
            if self.worker and self.worker.is_alive():
                self.requests.put({"kind": "review", "id": job["id"], "account": accounts[account.get()], "reference": value})
                window.destroy()
        ttk.Button(window, text="Confirm & queue", command=submit).pack(padx=20, pady=14)

    def retry_failed(self) -> None:
        if self.worker and self.worker.is_alive():
            self.requests.put({"kind": "retry"})
        else:
            self.start("requeue")

    def repair_saves(self) -> None:
        if self.worker and self.worker.is_alive():
            self.status.set("Pause before repairing pending saves.")
        else:
            self.start("retry")

    def start(self, mode: str) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            settings = self.collect_settings()
            validate_settings(settings, require_credentials=mode not in {"scan", "check", "retry"})
            save_settings(settings)
            self.settings = settings
        except Exception as error:
            self.tabs.select(self.settings_page)
            messagebox.showerror("Cannot start", str(error), parent=self.root)
            return
        self.stop_event.clear()
        self.set_busy(True)
        self.tabs.select(self.monitor_page)
        self.status.set("Starting monitor" if mode in {"watch", "requeue"} else "Checking")
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
                self.events.put(("failure", text))
            finally:
                self.events.put(("idle", None))
        self.worker = threading.Thread(target=work, daemon=False)
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.status.set("Pausing — finishing the current save and logout")

    def set_busy(self, busy: bool) -> None:
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
                self.status.set("Error: " + value)
            elif kind == "notice":
                self.status.set(value)
            elif kind == "history":
                activity, latest = value
                self.activity.merge(activity)
                for event in latest:
                    update_latest(self.rows, event)
                changed = True
            elif kind == "idle":
                self.set_busy(False)
                if self.stop_event.is_set():
                    self.status.set("Paused")
        if changed:
            self.render_results()
        self.poll_id = self.root.after(100, self.drain_events)

    def accept_event(self, event: dict[str, Any]) -> None:
        if event.get("kind") == "queue":
            self.jobs = {job["id"]: job for job in event["jobs"]}
            return
        step = int(event["step"])
        label = STATUS_LABELS.get(event["status"], event["status"])
        self.activity.add(event)
        self.current_step.set(f"{event.get('account') or 'System'} · {STEPS.get(step, 'Work')} · {label}")
        if event["status"] == "summary":
            self.status.set(event["reason"])
        elif event["status"] in {"error", "copy_pending", "warning"}:
            self.status.set(f"{STEPS.get(step, 'Work')}: {label} — see History")
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
            values = (position, job["label"], job.get("subject") or "Email request", JOB_LABELS.get(job["status"], job["status"]),
                      wait, f"{job['attempts']}/2", ", ".join(job["lookup"])[:220])
            if self.job_table.exists(job["id"]):
                self.job_table.item(job["id"], values=values)
                self.job_table.move(job["id"], "", position - 1)
            else:
                self.job_table.insert("", "end", iid=job["id"], values=values)
        done = sum(job["status"] == "complete" for job in ordered)
        pending = sum(job["status"] in {"waiting", "running"} for job in ordered)
        review = sum(job["status"] in {"review", "exhausted", "copy_pending"} for job in ordered)
        self.summary.set(f"Queued {pending}   ·   Done {done}   ·   Needs attention {review}")

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
            values = (str(event["time"]).replace("T", " ")[:19], event.get("account") or "System",
                      STEPS.get(int(event["step"]), "Work"), STATUS_LABELS.get(event["status"], event["status"]),
                      event.get("filename", ""), event.get("reason", ""))
            if self.activity_table.exists(key):
                self.activity_table.item(key, values=values)
                self.activity_table.move(key, "", position)
            else:
                self.activity_table.insert("", position, iid=key, values=values)
        self.history_count.set(f"{len(visible)} events")
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
        fields = (("Time", event["time"]), ("Account", event.get("account") or "System"),
                  ("Action", STEPS.get(int(event["step"]), "Work")), ("Result", STATUS_LABELS.get(event["status"], event["status"])),
                  ("File / email", event.get("filename", "")), ("Details", event.get("reason", "")),
                  ("Destination", event.get("destination", "")), ("Machine", event.get("machine", "")),
                  ("Run", event.get("run_id", "")), ("SHA-256", event.get("sha256", "")))
        return "\n".join(f"{label}: {value}" for label, value in fields if value)

    def show_selected(self) -> None:
        details = self.selected_details()
        if details:
            messagebox.showinfo("Work details", details, parent=self.root)

    def load_history(self) -> None:
        folder = Path(self.settings["log_dir"])
        def work():
            try:
                self.events.put(("history", read_activity(folder)))
            except Exception as error:
                self.events.put(("notice", f"History unavailable: {error}"))
        threading.Thread(target=work, daemon=True).start()

    def open_logs(self) -> None:
        try:
            os.startfile(str(self.settings["log_dir"]))
        except Exception as error:
            messagebox.showerror("Cannot open logs", str(error), parent=self.root)

    def callback_error(self, error_type, error, _trace) -> None:
        self.status.set(f"{error_type.__name__}: {error}")

    def tick(self) -> None:
        self.render_jobs()
        self.clock_id = self.root.after(1000, self.tick)

    def close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop()
            self.root.after(250, self.wait_to_close)
            return
        self.root.after_cancel(self.poll_id)
        self.root.after_cancel(self.clock_id)
        self.root.destroy()

    def wait_to_close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.root.after(250, self.wait_to_close)
        else:
            self.close()


def launch(smoke_screenshot: Path | None = None, smoke_report: Path | None = None) -> int:
    root = tk.Tk()
    window_icon_applied = apply_window_icon(root)
    root.title("KDE Download")
    root.geometry(f"1180x{min(780, root.winfo_screenheight() - 90)}+20+20")
    root.minsize(1000, 650)
    root.option_add("*Font", ("Segoe UI", 10))
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=30)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
    app = Application(root, smoke=smoke_screenshot is not None)
    if smoke_screenshot:
        root.withdraw()
        root.update()
        root.deiconify()
        root.attributes("-topmost", True)
        def capture():
            from PIL import ImageGrab
            from unittest.mock import patch
            moment = time.time()
            for index, status in enumerate(("complete", "waiting", "review", "running")):
                app.jobs[str(index)] = {"id": str(index), "subject": ["Pre payment notification", "Post review files", "Image reference needs confirmation", "Post results notice"][index],
                                        "label": "Pre" if index % 2 == 0 else "Post", "status": status, "attempts": 1 if index in {0, 3} else 0,
                                        "due": moment + 120, "sequence": index + 1, "lookup": {"payment online 67097": "Image OCR"}}
            for index in range(12):
                reason = "Access denied while saving the final file" if index == 10 else ["Email queued for two minutes", "Image OCR reference found", "Login succeeded", "File matched", "Download validated locally", "Final file saved", "Logout complete"][index % 7]
                app.accept_event({"key": f"sample-{index}", "time": f"{today()}T10:02:{index:02}+07:00", "step": 7 if index == 10 else 2 + index % 6,
                                  "status": "error" if index == 10 else "stage_complete", "reason": reason, "account": "Pre" if index % 2 == 0 else "Post",
                                  "filename": f"Sample request {index + 1}", "destination": r"\\10.0.0.97\Z Bot KDE", "attempt": 1})
            app.render_results()
            app.filter.set("Access denied")
            children = app.activity_table.get_children()
            search_passed = len(children) == 1
            if children:
                app.activity_table.selection_set(children[0])
            details_passed = "Details:" in app.selected_details() and "Destination:" in app.selected_details()
            app.filter.set("")
            for index in range(2):
                app.variables[f"accounts.{index}.username"].set(f"offline-{index}")
                app.variables[f"accounts.{index}.password"].set("offline-only")
            with patch.object(app, "start") as start:
                app.auto_start(force=True)
                auto_started = start.call_args is not None and start.call_args.args == ("watch",)
            app.fill_settings()
            app.status.set("Monitoring today's mail · Active accounts 1/2")
            smoke_screenshot.parent.mkdir(parents=True, exist_ok=True)
            def screenshot(page, path):
                app.tabs.select(page)
                root.update_idletasks()
                root.update()
                ImageGrab.grab().crop((root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())).save(path)
            screenshot(app.monitor_page, smoke_screenshot)
            screenshot(app.settings_page, smoke_screenshot.with_name(smoke_screenshot.stem + "-settings.png"))
            screenshot(app.activity_page, smoke_screenshot.with_name(smoke_screenshot.stem + "-history.png"))
            report = {"gui_started": True, "version": VERSION, "language": "en", "tab_count": len(app.tabs.tabs()),
                      "window_icon_applied": window_icon_applied, "header_icon_applied": app.brand_icon is not None,
                      "activity_rows": len(app.activity_table.get_children()), "mail_queue_rows": len(app.job_table.get_children()),
                      "error_rows": 1, "fixed_step_checklist": False, "theme_selector": False, "account_folder_overrides": False,
                      "history_search_passed": search_passed, "readable_event_details": details_passed, "auto_start_passed": auto_started,
                      "mail_delay_seconds": app.settings["mail_delay_seconds"], "login_retry_seconds": app.settings["login_retry_seconds"],
                      "max_session_attempts": 2, "today_only": app.settings["mail_watch"]["today_only"],
                      "includes_read_mail": not app.settings["mail_watch"]["unread_only"], "machine": socket.gethostname(), "live_portal_access": False}
            if smoke_report:
                smoke_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            app.close()
        root.after(800, capture)
    root.mainloop()
    return 0
