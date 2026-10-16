"""Compact shared history, exclusive worker lock, verified file delivery and CSV."""

from __future__ import annotations

import csv
import copy
import hashlib
import json
import math
import os
import socket
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .legacy_core import canonical_file_identity
from .settings import atomic_json, settings_home


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record_key(account: str, filename: str) -> str:
    identity = canonical_file_identity(filename) or filename.casefold()
    return hashlib.sha256(f"{account.casefold()}|{identity}".encode("utf-8")).hexdigest()


def exact_record_key(account: str, filename: str) -> str:
    return hashlib.sha256(f"daily|{account.casefold()}|{filename.casefold()}".encode("utf-8")).hexdigest()


class WorkerLock:
    """Windows/SMB byte-range lock: automatically released when the process exits."""

    def __init__(self, folder: Path):
        self.path = folder / ".kde.lock"
        self.stream = None

    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            self.stream.close()
            self.stream = None
            raise RuntimeError("Another KDE monitor is active, or the Log folder cannot be locked.") from error
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            import msvcrt
            self.stream.seek(0)
            try:
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self.stream.close()
                self.stream = None


def check_destination(folder: Path) -> None:
    """Check a business destination without creating, changing or deleting files."""
    if not folder.is_dir():
        raise FileNotFoundError(f"Destination folder is missing or inaccessible: {folder}")
    try:
        with os.scandir(folder) as entries:
            next(entries, None)
    except PermissionError as error:
        raise PermissionError(f"Cannot read the destination directory: {folder}") from error


def check_writable(folder: Path) -> None:
    """Probe the mutable Log folder only; never use on business destinations."""
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder is missing or inaccessible: {folder}")
    probe = folder / f".kde-check-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as stream:
            stream.write(b"KDE permission check")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        probe.unlink(missing_ok=True)


def verified_copy(source: Path, target: Path, expected_hash: str) -> None:
    """Publish only the final filename; exclusive creation never overwrites a file."""
    if target.exists():
        if target.is_file() and target.stat().st_size > 0 and file_hash(target) == expected_hash:
            return
        raise FileExistsError(f"Existing destination has different content; file preserved: {target}")
    created = False
    try:
        with source.open("rb") as incoming, open_new_target(target) as outgoing:
            created = True
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
            outgoing.seek(0)
            digest = hashlib.sha256()
            for block in iter(lambda: outgoing.read(1024 * 1024), b""):
                digest.update(block)
            if digest.hexdigest() != expected_hash:
                raise OSError("Destination SHA-256 verification failed.")
    except Exception:
        if created:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                # Retain the validated local source and failed destination in shared state.
                # Never hide the actual write failure behind a cleanup access denial.
                pass
        raise


def open_new_target(target: Path):
    """Keep Windows readers locked out until the final file is fully verified."""
    if os.name != "nt":
        return target.open("x+b")
    import msvcrt
    import win32con
    import win32file
    try:
        handle = win32file.CreateFile(str(target), win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                     0, None, win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None)
    except Exception as error:
        code = getattr(error, "winerror", error.args[0] if error.args else None)
        if code in {80, 183}:
            raise FileExistsError(f"Destination appeared during delivery; no overwrite: {target}") from error
        if code == 5:
            raise PermissionError(f"Cannot save downloaded file: {target}") from error
        raise
    descriptor = msvcrt.open_osfhandle(handle.Detach(), os.O_RDWR | os.O_BINARY)
    return os.fdopen(descriptor, "r+b")


def cached_source(record: dict[str, Any]) -> Path | None:
    hint = record.get("source_hint", "")
    if not hint:
        return None
    path = Path(hint)
    cache = settings_home() / "cache"
    if path.parent.resolve() != cache.resolve() or path.suffix != ".download":
        return None
    if path.is_file() and path.stat().st_size > 0 and file_hash(path) == record.get("sha256"):
        return path
    return None


class History:
    def __init__(self, folder: Path):
        self.folder = folder
        self.lock = threading.RLock()
        self.file_locks: dict[str, threading.RLock] = {}
        self.path = folder / "KDE_State.json"
        self.data: dict[str, Any] = {"version": 3, "files": {}, "outcomes": {}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if loaded.get("version") != 3 or not isinstance(loaded.get("files"), dict):
                raise ValueError("Invalid KDE history. Check KDE_State.json before starting.")
            self.data = loaded
            self.data.setdefault("outcomes", {})
        self.data.setdefault("mail_jobs", {})
        if not isinstance(self.data["outcomes"], dict) or not isinstance(self.data["mail_jobs"], dict):
            raise ValueError("Invalid outcome or queue history. Check KDE_State.json.")
        for key, job in self.data["mail_jobs"].items():
            if (not isinstance(job, dict) or job.get("id") != key
                    or job.get("status") not in {"waiting", "running", "complete", "copy_pending", "exhausted", "deferred", "review", "expired"}
                    or not isinstance(job.get("lookup"), dict)
                    or not all(isinstance(value, str) for pair in job.get("lookup", {}).items() for value in pair)
                    or not isinstance(job.get("attempts"), int) or not 0 <= job["attempts"] <= 2
                    or not isinstance(job.get("due"), (int, float)) or not math.isfinite(job["due"])
                    or not all(isinstance(job.get(field), str) for field in ("account", "label", "mail_id"))):
                raise ValueError("Invalid email queue: original state preserved; KDE was not opened.")
        cooldowns = self.data.get("account_cooldowns", {})
        if not isinstance(cooldowns, dict) or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in cooldowns.values()):
            raise ValueError("Invalid login cooldown data. Check KDE_State.json.")
        busy_sources = self.data.get("busy_search_accounts", {})
        if not isinstance(busy_sources, dict) or not all(isinstance(key, str) and isinstance(value, (int, float))
                                                        and math.isfinite(value) for key, value in busy_sources.items()):
            raise ValueError("Invalid busy-account retry state. Check KDE_State.json.")
        blocked_sources = self.data.get("blocked_search_accounts", {})
        if not isinstance(blocked_sources, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                           for key, value in blocked_sources.items()):
            raise ValueError("Invalid credential attention state. Check KDE_State.json.")
        generation = self.data.get("mail_generation", 0)
        deadline = self.data.get("mail_window_due", 0)
        if not isinstance(generation, int) or generation < 0 or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
            raise ValueError("Invalid mail-window state. Check KDE_State.json.")
        for job in self.data["mail_jobs"].values():
            deadline = job.get("window_due", job["due"])
            generation = job.get("round_generation", 0)
            if not isinstance(deadline, (int, float)) or not math.isfinite(deadline) or not isinstance(generation, int) or generation < 0:
                raise ValueError("Invalid email window: original state preserved.")
        daily = self.data.get("daily_watch")
        if daily is not None:
            if (not isinstance(daily, dict) or not isinstance(daily.get("day"), str)
                    or not isinstance(daily.get("seen"), list) or not all(isinstance(value, str) for value in daily["seen"])
                    or not isinstance(daily.get("sequence"), int) or daily["sequence"] < 0
                    or not isinstance(daily.get("jobs"), dict)):
                raise ValueError("Invalid daily download state; original data preserved.")
            deadline = daily.get("pending_due")
            if deadline is not None and (not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
                raise ValueError("Invalid daily download deadline; original data preserved.")
            for username, job in daily["jobs"].items():
                if (not isinstance(job, dict) or job.get("account") != username
                        or job.get("status") not in {"waiting", "running", "complete", "deferred", "review", "expired"}
                        or not isinstance(job.get("attempts"), int) or job["attempts"] < 0
                        or not isinstance(job.get("due"), (int, float)) or not math.isfinite(job["due"])
                        or not all(isinstance(job.get(field), str) for field in ("id", "account", "label", "work_date"))):
                    raise ValueError("Invalid daily account queue; original data preserved.")

    def save(self) -> None:
        with self.lock:
            atomic_json(self.path, self.data)

    def set_file(self, key: str, record: dict[str, Any]) -> None:
        with self.lock:
            self.data["files"][key] = copy.deepcopy(record)
            self.save()

    def file_lock(self, filename: str) -> threading.RLock:
        identity = canonical_file_identity(filename) or filename.casefold()
        with self.lock:
            return self.file_locks.setdefault(identity, threading.RLock())

    def import_legacy(self, path: Path) -> int:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if loaded.get("version") == 3 and isinstance(loaded.get("files"), dict):
            records = list(loaded["files"].items())
        elif isinstance(loaded.get("downloaded"), dict):
            records = []
            for account, entries in loaded["downloaded"].items():
                for entry in entries.values():
                    filename = entry.get("filename", "")
                    if filename:
                        records.append((record_key(account, filename), {
                            "account": account,
                            "filename": filename,
                            "imported": True,
                            "source_hint": str(entry.get("saved_path", "")),
                            "downloaded_at": str(entry.get("downloaded_at", "")),
                            "destinations": {},
                        }))
        else:
            raise ValueError("This is not a KDE download-history file.")
        count = 0
        for key, value in records:
            if key not in self.data["files"]:
                # Whitelist fields: no arbitrary private configuration in shared history.
                self.data["files"][key] = {
                    field: value[field] for field in (
                        "account", "filename", "imported", "source_hint", "downloaded_at",
                        "sha256", "size", "destinations", "pending", "download_policy",
                    ) if field in value
                }
                count += 1
        self.save()
        return count


CSV_FIELDS = [
    "time", "machine", "run_id", "account", "filename", "step", "status",
    "reason", "destination", "attempt", "sha256",
]


class Reporter:
    def __init__(self, history: History, callback: Callable[[dict[str, Any]], None]):
        self.history = history
        self.callback = callback
        self.run_id = uuid.uuid4().hex[:12]
        self.counts = {"complete": 0, "skipped": 0, "copy_pending": 0, "error": 0}
        self.secrets: list[str] = []
        self.file_key = record_key
        self.language = "en"
        self.activity_last: dict[tuple[str, str, int], list[Any]] = {}

    def redact(self, text: Any) -> str:
        result = str(text)
        for secret in sorted(self.secrets, key=len, reverse=True):
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result

    def emit(self, *args, **kwargs) -> dict[str, Any]:
        with self.history.lock:
            return self._emit(*args, **kwargs)

    def _emit(self, step: int, status: str, reason: str, account: str = "",
             filename: str = "", destination: str = "", persist: bool = False,
             sha256: str = "", count: bool = False) -> dict[str, Any]:
        if self.language == "th":
            from .language import thai_text
            reason = thai_text(reason)
        key = self.file_key(account, filename) if filename else f"stage:{account}:{step}"
        previous = self.history.data["outcomes"].get(key, {})
        previous_status = previous.get("signature", [None, None])[1]
        if not filename and status == "stage_complete" and previous_status in {"error", "warning", "copy_pending"}:
            persist = True
        signature = [step, status, self.redact(reason), destination]
        attempt = int(previous.get("attempt", 0)) + (1 if persist else 0)
        event = {
            "key": key, "time": datetime.now().astimezone().isoformat(timespec="microseconds"), "machine": socket.gethostname(),
            "run_id": self.run_id, "account": account, "filename": filename,
            "step": step, "status": status, "reason": signature[2],
            "destination": destination, "attempt": attempt, "sha256": sha256,
        }
        if count and status in self.counts:
            self.counts[status] += 1
        event["counts"] = dict(self.counts)
        outcome_changed = persist and signature != previous.get("signature")
        activity_key = (account, filename, step)
        # Save business transitions, not every mailbox poll or file-existence check.
        progress = ((not filename and status in {"running", "stage_complete", "summary", "notice"})
                    or (filename and step == 6 and status == "running")
                    or (persist and status in {"error", "warning", "copy_pending"}))
        progress_changed = progress and signature != self.activity_last.get(activity_key)
        event["activity_recorded"] = bool(outcome_changed or progress_changed)
        if event["activity_recorded"]:
            self.append_activity(event)
        self.activity_last[activity_key] = signature
        if persist:
            self.history.data["outcomes"][key] = {"signature": signature, "attempt": attempt}
            if outcome_changed:
                self.history.save()
        self.callback(event)
        return event

    def append_activity(self, event: dict[str, Any]) -> None:
        """Append to the existing monthly CSV while the shared history lock is held."""
        path = self.history.folder / f"KDE_Log_{datetime.now():%Y-%m}.csv"
        has_header = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8-sig" if not has_header else "utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            if not has_header:
                writer.writeheader()
            row = {field: self.redact(event[field]) for field in CSV_FIELDS}
            # Prevent formulas when externally supplied filenames are opened in Excel.
            row = {field: "'" + value if value.startswith(("=", "+", "-", "@")) else value
                   for field, value in row.items()}
            writer.writerow(row)
            stream.flush()


class Delivery:
    def __init__(self, history: History, reporter: Reporter):
        self.history = history
        self.reporter = reporter
        self.indexes: dict[str, dict[str, list[Path]]] = {}
        self.index_stamps: dict[str, int] = {}
        self.index_lock = threading.RLock()

    def record_identifier(self, account: str, filename: str) -> str:
        return record_key(account, filename)

    def existing_source(self, available: list[Path]) -> Path | None:
        return available[0] if available else None

    def index(self, folder: Path, refresh: bool = False) -> dict[str, list[Path]]:
        with self.index_lock:
            return self._index(folder, refresh)

    def _index(self, folder: Path, refresh: bool = False) -> dict[str, list[Path]]:
        key = str(folder).casefold()
        stamp = folder.stat().st_mtime_ns
        if refresh or key not in self.indexes or self.index_stamps.get(key) != stamp:
            index: dict[str, list[Path]] = {}
            for path in folder.iterdir():
                if path.is_file() and not path.name.startswith(".") and not path.name.endswith(".part"):
                    identity = canonical_file_identity(path.name)
                    index.setdefault(identity, []).append(path)
            self.indexes[key] = index
            self.index_stamps[key] = stamp
        return self.indexes[key]

    def existing(self, folder: Path, filename: str) -> Path | None:
        exact = folder / filename
        if exact.exists():
            if not exact.is_file() or exact.stat().st_size == 0:
                raise FileExistsError(f"Existing file is incomplete and was preserved: {exact}")
            return exact
        candidates = self.index(folder).get(canonical_file_identity(filename), [])
        valid = [path for path in candidates if path.exists() and path.stat().st_size > 0]
        if not valid:
            # NTFS/SMB directory timestamps can lag a competing publication.
            # Confirm a cache miss from the directory before downloading again.
            candidates = self.index(folder, refresh=True).get(canonical_file_identity(filename), [])
            valid = [path for path in candidates if path.exists() and path.stat().st_size > 0]
        if len(valid) > 1:
            raise FileExistsError(f"Several equivalent filenames require review: {filename}")
        return valid[0] if valid else None

    def deliver(self, account: str, filename: str, folders: list[Path],
                download: Callable[[Path], Path], recovery_folders: list[Path] | None = None) -> str:
        # Different files download concurrently; equivalent names serialize publication.
        with self.history.file_lock(filename):
            return self._deliver(account, filename, folders, download, recovery_folders)

    def _deliver(self, account: str, filename: str, folders: list[Path],
                 download: Callable[[Path], Path], recovery_folders: list[Path] | None = None) -> str:
        key = self.record_identifier(account, filename)
        with self.history.lock:
            record = copy.deepcopy(self.history.data["files"].get(key, {}))
        stage = 5
        source: Path | None = None
        downloaded = False
        try:
            self.reporter.emit(5, "running", "Checking existing files and history", account, filename)
            locations = [(folder, self.existing(folder, filename)) for folder in folders]
            available = [path for _, path in locations if path is not None]
            local_source = cached_source(record)
            if local_source:
                source = local_source
            elif available:
                source = self.existing_source(available)
            else:
                for folder in recovery_folders or []:
                    if folder.is_dir():
                        source = self.existing(folder, filename)
                        if source is not None:
                            break
            if source is None:
                stage = 6
                self.reporter.emit(6, "running", "Downloading from KDE to local staging", account, filename, str(folders[0]))
                source = download(folders[0] / filename)
                downloaded = True
                if not source.is_file() or source.stat().st_size == 0:
                    raise OSError("Downloaded file is empty or missing.")
            digest = file_hash(source)
            if record.get("sha256") and record["sha256"] != digest:
                raise FileExistsError("Content differs from recorded SHA-256; existing files preserved.")
            record.update(account=account, filename=filename, sha256=digest,
                          size=source.stat().st_size, destinations={}, pending=list(map(str, folders)))
            if source.parent.resolve() == (settings_home() / "cache").resolve():
                record["source_hint"] = str(source)
            if downloaded:
                record["downloaded_at"] = timestamp()
            self.history.set_file(key, record)
            copied = False
            for folder, existing in locations:
                stage = 7
                target = existing or folder / filename
                if target == source:
                    record["destinations"][str(folder)] = str(source)
                else:
                    self.reporter.emit(7, "running", "Saving and verifying the final destination file", account, filename, str(target))
                    was_missing = existing is None
                    verified_copy(source, target, digest)
                    record["destinations"][str(folder)] = str(target)
                    copied = copied or was_missing
                self.history.set_file(key, record)
                identity = canonical_file_identity(filename)
                with self.index_lock:
                    index = self.index(folder)
                    if target not in index.setdefault(identity, []):
                        index[identity].append(target)
                record["pending"] = [folder_path for folder_path in record["pending"] if folder_path != str(folder)]
                self.history.set_file(key, record)
            status = "complete" if downloaded or copied else "skipped"
            reason = "Saved and verified at all selected destinations" if status == "complete" else "Already saved; SHA-256 verified at all destinations"
            self.reporter.emit(7 if len(folders) > 1 or copied else 6, status, reason,
                               account, filename, " | ".join(map(str, folders)), True, digest, True)
            if cached_source(record) == source:
                try:
                    source.unlink(missing_ok=True)
                    record.pop("source_hint", None)
                    self.history.set_file(key, record)
                except OSError:
                    pass
            return status
        except Exception as error:
            status = "copy_pending" if source is not None and stage == 7 else "error"
            if source is not None and record.get("sha256"):
                record["pending"] = [
                    str(folder) for folder in folders if str(folder) not in record.get("destinations", {})
                ]
                record["source_hint"] = str(source)
                self.history.set_file(key, record)
            self.reporter.emit(stage, status, f"{type(error).__name__}: {error}",
                               account, filename, " | ".join(map(str, folders)), True, count=True)
            return status
