"""Mail-arrival triggers and today's complete KDE catalogues, without content matching."""

from __future__ import annotations

import copy
import hashlib
import queue
import re
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import legacy_core as core
from .evidence import BANGKOK, today
from .search_round import AccountBusyError, CredentialsError
from .storage import Delivery, check_destination, exact_record_key
from .workflow import StructuredDownloader, make_engine_settings, selected_folders


def portal_day(row: dict) -> str | None:
    """The portal's dated row is authoritative; use a filename date only if absent."""
    text = row.get("file_time", "").strip()
    iso = re.search(r"(?<!\d)(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?!\d)", text)
    local = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if iso or local:
        parts = list(map(int, (iso or local).groups()))
        year, month, day = parts if iso else parts[::-1]
        if year > 2400:
            year -= 543
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None
    if text:
        return None  # Never bypass an unreadable portal date with a filename guess.
    days, _months = core.normalized_business_dates(row.get("filename", ""))
    return next(iter(days)) if len(days) == 1 else None


def scan_arrivals(settings: dict, stop_event: threading.Event) -> list[dict]:
    """Read only incoming mail IDs and received times; never read body or images."""
    if core.win32_client is None or core.pythoncom is None:
        raise RuntimeError("Classic Outlook and pywin32 are required on this computer.")
    filters = [value.strip().casefold() for value in re.split(r"[,;]+", settings["mail_watch"]["mailbox_filter"]) if value.strip()]
    target = settings["mail_watch"].get("folder_path", "").replace("/", "\\").strip("\\ ").casefold()
    excluded = {"sent items", "sent", "drafts", "outbox", "deleted items", "junk email", "junk e-mail",
                "รายการที่ส่ง", "แบบร่าง", "กล่องขาออก", "รายการที่ถูกลบ", "อีเมลขยะ"}
    result = []
    matched_roots = 0
    matched_folders = 0
    day = today()

    def walk(folder, root_name, relative=""):
        nonlocal matched_folders
        if stop_event.is_set():
            return
        name = str(folder.Name)
        if name.casefold() in excluded:
            return
        try:
            store = folder.Store
            if any(str(folder.EntryID) == str(store.GetDefaultFolder(kind).EntryID) for kind in (3, 4, 5, 16, 23)):
                return
        except Exception:
            pass
        inside = not target or relative.casefold() == target or relative.casefold().startswith(target + "\\")
        if target and relative.casefold() == target:
            matched_folders += 1
        try:
            mail_folder = int(folder.DefaultItemType) == 0
        except Exception:
            mail_folder = True
        path = root_name + ("\\" + relative if relative else "")
        if inside and mail_folder:
            try:
                items = folder.Items
                items.Sort("[ReceivedTime]", True)
                for index in range(1, min(int(items.Count), settings["mail_watch"]["max_messages_per_folder"]) + 1):
                    if stop_event.is_set():
                        return
                    item = items.Item(index)
                    if int(item.Class) != 43:
                        continue
                    received = item.ReceivedTime
                    if not isinstance(received, datetime):
                        continue
                    if received.tzinfo:
                        received = received.astimezone(BANGKOK)
                    if received.date().isoformat() != day:
                        continue
                    entry = str(item.EntryID or "")
                    if not entry:
                        raise RuntimeError("Outlook did not provide a stable mail ID.")
                    result.append({"entry_id": entry, "store_id": str(folder.StoreID or ""),
                                   "received": received.isoformat(), "folder": path})
            except Exception as error:
                raise RuntimeError(f"Cannot read incoming mail in {path}: {error}") from error
        try:
            children = folder.Folders
            for index in range(1, int(children.Count) + 1):
                child = children.Item(index)
                child_relative = relative + "\\" + str(child.Name) if relative else str(child.Name)
                if not target or not relative or target.startswith(child_relative.casefold() + "\\") or child_relative.casefold().startswith(target) or child_relative.casefold() == target:
                    walk(child, root_name, child_relative)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"Cannot enumerate incoming folders in {path}: {error}") from error

    core.pythoncom.CoInitialize()
    try:
        namespace = core.win32_client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        roots = namespace.Folders
        for index in range(1, int(roots.Count) + 1):
            root = roots.Item(index)
            root_name = str(root.Name)
            if any(value in root_name.casefold() for value in filters):
                matched_roots += 1
                walk(root, root_name)
        if not matched_roots:
            raise RuntimeError("Configured data mailbox was not found in classic Outlook.")
        if target and not matched_folders:
            raise RuntimeError("Configured incoming folder was not found: " + target)
        return result
    finally:
        core.pythoncom.CoUninitialize()


class DailyDelivery(Delivery):
    """Exact Windows filename identity; extensions and business numbers stay distinct."""
    def __init__(self, history, reporter):
        super().__init__(history, reporter)
        reporter.file_key = exact_record_key

    def record_identifier(self, account, filename):
        return exact_record_key(account, filename)

    def existing(self, folder, filename):
        target = folder / filename
        try:
            metadata = target.stat()
        except FileNotFoundError:
            if not folder.is_dir():
                raise FileNotFoundError("Cannot check the destination root: " + str(folder))
            return None
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
            raise FileExistsError("An existing empty file or directory needs attention; it was preserved: " + str(target))
        return target

    def index(self, folder, refresh=False):
        # The inherited publisher updates this bookkeeping; exact existence checks
        # above deliberately do not use business-name equivalence or directory caches.
        with self.index_lock:
            return self.indexes.setdefault(str(folder).casefold(), {})

    def _deliver(self, account, filename, folders, download, recovery_folders=None):
        status = super()._deliver(account, filename, folders, download, recovery_folders)
        key = self.record_identifier(account, filename)
        with self.history.lock:
            if key in self.history.data["files"]:
                self.history.data["files"][key]["download_policy"] = "daily_all"
                self.history.save()
        return status


class DailyDownloader(StructuredDownloader):
    def __init__(self, settings, reporter, delivery, configuration, stop_event, work_day=None):
        exact_delivery = DailyDelivery(delivery.history, reporter)
        super().__init__(settings, reporter, exact_delivery, configuration, stop_event, read_evidence=False)
        self.work_day = work_day or today()
        self.jobs = [{"id": "daily-sweep", "lookup": {}}]  # Use the verified complete-catalogue traversal.
        self.selection_reason = "Portal file is dated today; checking both destination roots"
        self.delay_on_skipped = False
        self.eligible = 0
        self.rejected_dates = 0

    def _select_page_mail_matches(self, rows, allowed_filenames):
        selected = {}
        self.row_jobs = {}
        self.rejected_dates = 0
        for index, row in rows:
            if portal_day(row) == self.work_day:
                selected[index] = {"daily": True}
            else:
                self.rejected_dates += 1
        self.eligible = len(selected)
        self.reporter.emit(4, "stage_complete", f"Today's files: {self.eligible}; other or unreadable dates: {self.rejected_dates}", self.account)
        return selected, {}

    def handle_file(self, page, row_index, row, account, timeout_ms):
        # Recheck the Bangkok day at the actual download boundary, including midnight.
        if today() != self.work_day or portal_day(row) != today():
            self.reporter.emit(4, "notice", "Date changed; this file will not be downloaded", account.label, row["filename"])
            return "skipped"
        filename = row["filename"]
        if core.safe_filename(filename) != filename or Path(filename).name != filename or filename.startswith("."):
            self.reporter.emit(4, "error", "Unsafe portal filename; download refused", account.label, filename, persist=True, count=True)
            return "error"
        with self.delivery.history.file_lock(filename):
            try:
                # Windows/SMB lookup is case-insensitive. Fresh stat calls observe other users'
                # publications without repeatedly listing every file in both shared roots.
                existing = []
                for folder in dict.fromkeys((Path(self.configuration["original_dir"]), Path(self.configuration["new_dir"]))):
                    target = self.delivery.existing(folder, filename)
                    if target is not None:
                        existing.append(target)
                if existing:
                    self.reporter.emit(5, "skipped", "Filename already exists in either destination; no download or extra copy",
                                       account.label, filename, str(existing[0]), persist=True, count=True)
                    return "skipped"
                configuration = next(item for item in self.configuration["accounts"] if item["username"] == account.username)
                def download_today(_target):
                    source = self.download_to_cache(page, row_index, timeout_ms)
                    if today() != self.work_day:
                        source.unlink(missing_ok=True)
                        raise RuntimeError("Bangkok date changed during download; previous-day cache discarded before publication.")
                    return source
                return self.delivery.deliver(account.username, filename, selected_folders(self.configuration, configuration), download_today)
            except Exception as error:
                self.reporter.emit(5, "error", f"Cannot check or save this file: {type(error).__name__}: {error}",
                                   account.label, filename, persist=True, count=True)
                return "error"


class DailyQueue:
    def __init__(self, history, settings):
        self.history = history
        self.settings = settings
        self.blocked = set()
        self.state = history.data.setdefault("daily_watch", {"day": today(), "seen": [], "pending_due": None, "sequence": 0, "jobs": {}})
        self.roll_day()

    def roll_day(self):
        with self.history.lock:
            if self.state["day"] != today():
                self.state.update(day=today(), seen=[], pending_due=None)
                for job in self.state["jobs"].values():
                    if job["status"] != "complete":
                        job.update(status="expired", last_reason="Previous-day sweep stopped; only today's files may download.")
                self.history.save()

    def recover(self, now):
        with self.history.lock:
            enabled = {account["username"] for account in self.settings["accounts"] if account["enabled"]}
            for job in self.state["jobs"].values():
                if job["account"] not in enabled:
                    job.update(status="expired", last_reason="Account removed or disabled in Settings.")
                    continue
                if job["status"] == "running":
                    job.update(status="waiting" if job["attempts"] < 2 else "deferred",
                               due=max(now, min(job["due"], now + 60)), last_reason="Interrupted sweep; attempts and deadline retained.")
            self.history.save()

    def ingest(self, arrivals, now):
        self.roll_day()
        with self.history.lock:
            seen = set(self.state["seen"])
            added = 0
            for mail in arrivals:
                if mail["received"][:10] != self.state["day"]:
                    continue
                identity = hashlib.sha256((mail["store_id"] + "|" + mail["entry_id"]).encode()).hexdigest()
                if identity not in seen:
                    seen.add(identity)
                    added += 1
            if added:
                self.state["seen"] = sorted(seen)
                deadline = now + 70
                self.state["pending_due"] = min(self.state["pending_due"], deadline) if self.state["pending_due"] is not None else deadline
                self.history.save()
            return added

    def request_round(self, now):
        self.roll_day()
        with self.history.lock:
            self.state["pending_due"] = min(self.state["pending_due"], now + 70) if self.state["pending_due"] is not None else now + 70
            self.history.save()

    def claim(self, now):
        self.roll_day()
        with self.history.lock:
            jobs = self.state["jobs"]
            if any(job["status"] == "running" for job in jobs.values()):
                return []
            if not any(job["status"] == "waiting" for job in jobs.values()) and self.state["pending_due"] is not None and self.state["pending_due"] <= now:
                self.state["sequence"] += 1
                attention = {username: copy.deepcopy(job) for username, job in jobs.items() if username in self.blocked}
                jobs.clear()
                jobs.update(attention)
                for account in self.settings["accounts"]:
                    if account["enabled"] and account["username"] not in self.blocked:
                        username = account["username"]
                        jobs[username] = {"id": username, "account": username, "label": account["label"], "status": "waiting", "attempts": 0,
                                          "due": self.state["pending_due"], "work_date": self.state["day"], "sequence": self.state["sequence"],
                                          "subject": "Download all today's KDE files", "lookup": {}, "last_reason": "Mail arrival triggered a daily sweep."}
                self.state["pending_due"] = None
            ready = []
            for job in jobs.values():
                if job["status"] == "waiting" and job["due"] <= now:
                    job.update(status="running", attempts=job["attempts"] + 1, due=now + 60)
                    ready.append(copy.deepcopy(job))
            if ready:
                self.history.save()
            return ready

    def finish(self, username, outcome, now, stopped=False):
        with self.history.lock:
            job = self.state["jobs"][username]
            job["last_reason"] = outcome["reason"]
            job.pop("busy_sources", None)
            if job["work_date"] != today():
                job["status"] = "expired"
            elif outcome["kind"] == "complete":
                job["status"] = "complete"
            elif outcome["kind"] == "credentials":
                job["status"] = "review"
                self.blocked.add(username)
            elif job["attempts"] >= 2:
                job["status"] = "deferred"
                job["last_reason"] += " Two attempts used; wait for new mail or Request download round."
            else:
                job.update(status="waiting", due=now + 60)
                if outcome["kind"] == "account_busy":
                    job["busy_sources"] = [username]
            self.history.save()

    def snapshot(self):
        with self.history.lock:
            rows = copy.deepcopy(list(self.state["jobs"].values()))
            if self.state["pending_due"] is not None:
                rows.append({"id": "pending-daily-round", "account": "", "label": "Pre + Post", "status": "waiting", "attempts": 0,
                             "due": self.state["pending_due"], "sequence": self.state["sequence"] + 1,
                             "subject": "Next daily download round", "lookup": {}, "last_reason": "70-second mail window; countdown is not restarted."})
            return rows


def run_daily_account(settings, job, stop_event, reporter, history, temporary):
    engine = None
    try:
        index = next(index for index, account in enumerate(settings["accounts"]) if account["username"] == job["account"])
        for folder in dict.fromkeys((Path(settings["original_dir"]), Path(settings["new_dir"]))):
            check_destination(folder)
        state_path = temporary / f"daily-{job['sequence']}-{index}.json"
        engine = DailyDownloader(make_engine_settings(settings, state_path),
                                 reporter, Delivery(history, reporter), settings, stop_event, job["work_date"])
        account = next(item for item in engine.settings.accounts if item.username == job["account"])
        result = engine.process_account(account)
        if engine.logout_failures:
            raise RuntimeError("Own-session logout could not be confirmed.")
        if stop_event.is_set():
            return {"kind": "stopped", "reason": "Stopped; attempts retained."}
        if result.get("errors"):
            return {"kind": "download_failed", "reason": f"{result['errors']} files could not be saved; see History for filenames and reasons."}
        if not engine.eligible:
            return {"kind": "empty", "reason": "No dated-today files were visible in this KDE account."}
        return {"kind": "complete", "reason": f"Today's files checked: {engine.eligible}; saved {result.get('downloaded', 0)}, already present {result.get('skipped', 0)}."}
    except Exception as error:
        kind = "account_busy" if isinstance(error, AccountBusyError) else "credentials" if isinstance(error, CredentialsError) else "download_failed"
        reason = f"{type(error).__name__}: {error}"
        for account in settings["accounts"]:
            if account["password"]:
                reason = reason.replace(account["password"], "[REDACTED]")
        reporter.emit(engine.stage if engine else 3, "warning" if kind == "account_busy" else "error", reason,
                      job["label"], persist=True, count=True)
        return {"kind": kind, "reason": reason}


def run_daily_monitor(settings, stop_event, reporter, history, temporary, watch, requests=None, request_round=False):
    reporter.file_key = exact_record_key
    pending = DailyQueue(history, settings)
    pending.recover(time.time())
    if request_round:
        pending.request_round(time.time())
    active = {}
    next_scan = 0
    last_snapshot = None
    last_summary = None
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="KDE-daily") as pool:
        while not stop_event.is_set():
            now = time.time()
            pending.roll_day()
            for username, future in list(active.items()):
                if future.done():
                    outcome = future.result()
                    pending.finish(username, outcome, time.time())
                    reporter.emit(4, "stage_complete" if outcome["kind"] == "complete" else "warning", outcome["reason"], username, persist=True)
                    del active[username]
            if requests is not None:
                for _index in range(20):
                    try:
                        command = requests.get_nowait()
                    except queue.Empty:
                        break
                    if command["kind"] == "retry":
                        pending.request_round(time.time())
            if now >= next_scan:
                try:
                    added = pending.ingest(scan_arrivals(settings, stop_event), time.time())
                    if added:
                        reporter.emit(2, "waiting", f"{added} new mail arrivals; download all today's KDE files after the fixed 70-second window.", persist=True)
                except Exception as error:
                    reporter.emit(2, "error", str(error), persist=True, count=True)
                    if not watch:
                        break
                next_scan = time.time() + settings["mail_poll_seconds"]
            if not active and not stop_event.is_set():
                for job in pending.claim(time.time()):
                    active[job["account"]] = pool.submit(run_daily_account, settings, job, stop_event, reporter, history, temporary)
            rows = pending.snapshot()
            signature = repr(rows)
            if requests is not None and signature != last_snapshot:
                reporter.callback({"kind": "queue", "jobs": rows})
                last_snapshot = signature
            summary = f"Watching data mail arrivals · Today's files only · Active accounts {len(active)}/2"
            if summary != last_summary:
                reporter.emit(2, "summary", summary)
                last_summary = summary
            if not watch and not active and pending.state["pending_due"] is None and not any(job["status"] == "waiting" for job in pending.state["jobs"].values()):
                break
            stop_event.wait(0.5)
        for username, future in active.items():
            pending.finish(username, future.result(), time.time(), stopped=True)
    if requests is not None:
        reporter.callback({"kind": "queue", "jobs": pending.snapshot()})
    reporter.emit(8, "summary", "Stopped; account sessions closed" if stop_event.is_set() else "Daily download round finished")
