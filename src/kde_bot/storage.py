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
from .settings import atomic_json


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
            raise RuntimeError("มีเครื่องอื่นกำลังทำงาน KDE หรือไม่สามารถล็อกโฟลเดอร์ Log ได้") from error
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


def check_writable(folder: Path) -> None:
    if not folder.is_dir():
        raise FileNotFoundError(f"ไม่พบโฟลเดอร์หรือไม่มีสิทธิ์เข้าถึง: {folder}")
    probe = folder / f".kde-check-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as stream:
            stream.write(b"KDE permission check")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        probe.unlink(missing_ok=True)


def verified_copy(source: Path, target: Path, expected_hash: str) -> None:
    """Never replace an existing business file, including mismatched files."""
    if target.exists():
        if target.is_file() and target.stat().st_size > 0 and file_hash(target) == expected_hash:
            return
        raise FileExistsError(f"ไฟล์ปลายทางมีอยู่แต่เนื้อหาไม่ตรงกัน ต้องตรวจสอบ: {target}")
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    published = False
    try:
        with source.open("rb") as incoming, temporary.open("xb") as outgoing:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if file_hash(temporary) != expected_hash:
            raise OSError("ตรวจ SHA-256 ของสำเนาไม่ผ่าน")
        # Windows rename fails if a competing process created the destination.
        os.rename(temporary, target)
        published = True
    finally:
        if not published:
            temporary.unlink(missing_ok=True)


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
                raise ValueError("ประวัติ KDE ไม่ถูกต้อง กรุณาตรวจ KDE_State.json ก่อนเริ่ม")
            self.data = loaded
            self.data.setdefault("outcomes", {})
        self.data.setdefault("mail_jobs", {})
        if not isinstance(self.data["outcomes"], dict) or not isinstance(self.data["mail_jobs"], dict):
            raise ValueError("ประวัติผลลัพธ์/คิวอีเมลไม่ถูกต้อง กรุณาตรวจ KDE_State.json")
        for key, job in self.data["mail_jobs"].items():
            if (not isinstance(job, dict) or job.get("id") != key
                    or job.get("status") not in {"waiting", "running", "complete", "copy_pending", "exhausted"}
                    or not isinstance(job.get("lookup"), dict)
                    or not all(isinstance(value, str) for pair in job.get("lookup", {}).items() for value in pair)
                    or not isinstance(job.get("attempts"), int) or not 0 <= job["attempts"] <= 2
                    or not isinstance(job.get("due"), (int, float)) or not math.isfinite(job["due"])
                    or not all(isinstance(job.get(field), str) for field in ("account", "label", "mail_id"))):
                raise ValueError("คิวอีเมลเสียหาย: เก็บไฟล์เดิมไว้และหยุดก่อนเปิด KDE")
        cooldowns = self.data.get("account_cooldowns", {})
        if not isinstance(cooldowns, dict) or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in cooldowns.values()):
            raise ValueError("ข้อมูลเวลารอ Login เสียหาย กรุณาตรวจ KDE_State.json")

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
            raise ValueError("ไฟล์นี้ไม่ใช่ประวัติดาวน์โหลด KDE")
        count = 0
        for key, value in records:
            if key not in self.data["files"]:
                # Whitelist fields: no arbitrary private configuration in shared history.
                self.data["files"][key] = {
                    field: value[field] for field in (
                        "account", "filename", "imported", "source_hint", "downloaded_at",
                        "sha256", "size", "destinations", "pending",
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
        key = record_key(account, filename) if filename else f"stage:{account}:{step}"
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
        progress = ((not filename and status in {"running", "stage_complete", "summary"})
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
                raise FileExistsError(f"ไฟล์เดิมไม่สมบูรณ์ กรุณาตรวจสอบ: {exact}")
            return exact
        candidates = self.index(folder).get(canonical_file_identity(filename), [])
        valid = [path for path in candidates if path.exists() and path.stat().st_size > 0]
        if not valid:
            # NTFS/SMB directory timestamps can lag a competing publication.
            # Confirm a cache miss from the directory before downloading again.
            candidates = self.index(folder, refresh=True).get(canonical_file_identity(filename), [])
            valid = [path for path in candidates if path.exists() and path.stat().st_size > 0]
        if len(valid) > 1:
            raise FileExistsError(f"พบไฟล์ชื่อเทียบเท่าหลายไฟล์ ต้องตรวจสอบ: {filename}")
        return valid[0] if valid else None

    def deliver(self, account: str, filename: str, folders: list[Path],
                download: Callable[[Path], Path], recovery_folders: list[Path] | None = None) -> str:
        # Different files download concurrently; equivalent names serialize publication.
        with self.history.file_lock(filename):
            return self._deliver(account, filename, folders, download, recovery_folders)

    def _deliver(self, account: str, filename: str, folders: list[Path],
                 download: Callable[[Path], Path], recovery_folders: list[Path] | None = None) -> str:
        key = record_key(account, filename)
        with self.history.lock:
            record = copy.deepcopy(self.history.data["files"].get(key, {}))
        stage = 5
        source: Path | None = None
        downloaded = False
        try:
            self.reporter.emit(5, "running", "ตรวจประวัติและไฟล์ในปลายทาง", account, filename)
            locations = [(folder, self.existing(folder, filename)) for folder in folders]
            available = [path for _, path in locations if path is not None]
            if available:
                source = available[0]
            else:
                for folder in recovery_folders or []:
                    if folder.is_dir():
                        source = self.existing(folder, filename)
                        if source is not None:
                            break
            if source is None:
                stage = 6
                self.reporter.emit(6, "running", "กำลังดาวน์โหลดจาก KDE", account, filename, str(folders[0]))
                source = download(folders[0] / filename)
                downloaded = True
                if not source.is_file() or source.stat().st_size == 0:
                    raise OSError("ไฟล์ดาวน์โหลดว่างหรือไม่พบไฟล์")
            digest = file_hash(source)
            if record.get("sha256") and record["sha256"] != digest:
                raise FileExistsError("เนื้อหาไฟล์ไม่ตรงกับประวัติเดิม ต้องตรวจสอบก่อนคัดลอก")
            record.update(account=account, filename=source.name, sha256=digest,
                          size=source.stat().st_size, destinations={}, pending=[])
            if downloaded:
                record["downloaded_at"] = timestamp()
            self.history.set_file(key, record)
            copied = False
            for folder, existing in locations:
                stage = 7
                target = existing or folder / source.name
                if target == source:
                    record["destinations"][str(folder)] = str(source)
                else:
                    self.reporter.emit(7, "running", "ตรวจสอบหรือคัดลอกไฟล์ปลายทาง", account, filename, str(target))
                    was_missing = existing is None
                    verified_copy(source, target, digest)
                    record["destinations"][str(folder)] = str(target)
                    copied = copied or was_missing
                self.history.set_file(key, record)
                identity = canonical_file_identity(source.name)
                with self.index_lock:
                    index = self.index(folder)
                    if target not in index.setdefault(identity, []):
                        index[identity].append(target)
            status = "complete" if downloaded or copied else "skipped"
            reason = "ดาวน์โหลดและตรวจไฟล์ครบทุกปลายทางที่เลือก" if status == "complete" else "ตรวจ SHA-256 แล้ว พบไฟล์ครบทุกปลายทางที่เลือก"
            self.reporter.emit(7 if len(folders) > 1 or copied else 6, status, reason,
                               account, filename, " | ".join(map(str, folders)), True, digest, True)
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
