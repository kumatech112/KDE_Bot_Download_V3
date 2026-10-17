"""Daily, nonrecursive cleanup of the two explicitly approved download roots."""

from __future__ import annotations

import ntpath
import json
import os
import stat
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .evidence import BANGKOK
from .schedule import scheduled_time


APPROVED_ROOTS = (r"\\10.0.0.243\pgp-data$", r"\\10.0.0.97\Z Bot KDE")
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def current_time():
    return datetime.now(BANGKOK)


def was_cleaned(history, filename, day=None):
    day = day or current_time().date().isoformat()
    record = history.data.get('daily_cleanup', {})
    return record.get('day') == day and filename.casefold() in set(record.get('deleted_names', []) + record.get('pending_names', []))


def request_path(settings):
    folder = Path(settings['log_dir']).resolve(strict=True)
    for approved in APPROVED_ROOTS:
        if path_identity(folder) == path_identity(approved) or path_identity(folder).startswith(path_identity(approved) + '\\'):
            raise ValueError('ต้องเก็บคำขอลบไฟล์ในโฟลเดอร์ประวัติแยกจากปลายทางดาวน์โหลด')
    return folder / 'KDE_Cleanup_Request.json'


def write_request(settings, day, requested):
    path = request_path(settings)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump({'day': day, 'requested': requested}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        temporary.unlink(missing_ok=True)


def path_identity(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def validated_root(path, approved):
    """Resolve and check the named target before any enumeration or deletion."""
    root = Path(path)
    if path_identity(root) != path_identity(approved):
        raise ValueError(f"ไม่อนุญาตให้ลบไฟล์นอกโฟลเดอร์ที่กำหนด: {root}")
    resolved = root.resolve(strict=True)
    info = root.lstat()
    if (path_identity(resolved) != path_identity(approved)
            or not stat.S_ISDIR(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & REPARSE_POINT):
        raise ValueError(f"โฟลเดอร์ปลายทางเปลี่ยนตำแหน่งหรือเป็นลิงก์ จึงไม่ลบ: {root}")
    return resolved


def file_signature(info):
    return (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)


def cleanup_root(root, reporter, stop_event, day, before_delete, after_delete, failed_delete):
    """Only unlink regular direct children. Never recurse or remove directories."""
    result = {"deleted": 0, "preserved": 0, "errors": 0, "stopped": False}
    label = '.243' if path_identity(root) == path_identity(APPROVED_ROOTS[0]) else '.97'
    for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if stop_event.is_set() or current_time().date().isoformat() != day:
            result['stopped'] = True
            break
        try:
            before = child.lstat()
            if (not stat.S_ISREG(before.st_mode)
                    or getattr(before, 'st_file_attributes', 0) & REPARSE_POINT):
                result['preserved'] += 1
                continue
            resolved = child.resolve(strict=True)
            if resolved.parent != root or child.parent != root:
                raise ValueError('ตำแหน่งไฟล์อยู่นอกโฟลเดอร์ที่อนุญาต')
            after = child.lstat()
            if file_signature(before) != file_signature(after):
                raise RuntimeError('ไฟล์เปลี่ยนแปลงระหว่างตรวจสอบ จึงเก็บไว้')
            if getattr(after, 'st_file_attributes', 0) & REPARSE_POINT:
                raise ValueError('ไฟล์เปลี่ยนเป็นลิงก์ จึงเก็บไว้')
            before_delete(child.name)
            child.unlink()
            after_delete(child.name)
            result['deleted'] += 1
            reporter.emit(9, 'stage_complete', 'ลบไฟล์แล้ว', filename=child.name,
                          account=label, destination=str(root), persist=True)
        except Exception as error:
            failed_delete(child.name)
            result['errors'] += 1
            reporter.emit(9, 'error', f'ลบไฟล์ไม่ได้ เก็บไฟล์ไว้: {type(error).__name__}: {error}',
                          account=label, filename=child.name, destination=str(root), persist=True)
    return result


class DailyCleanup:
    """One attempt per Bangkok day, serialized with KDE downloads under WorkerLock."""

    def __init__(self, settings, history, reporter, now):
        self.settings = settings
        self.history = history
        self.reporter = reporter
        self.wait_reported = False
        self.next_request_check = 0
        moment = datetime.fromtimestamp(now, BANGKOK)
        deadline = scheduled_time(moment, settings.get('cleanup_time', '22:00'))
        # Starting after today's scheduled time never performs a surprise catch-up.
        if moment > deadline:
            deadline += timedelta(days=1)
        self.due = deadline.timestamp()
        previous = history.data.get('daily_cleanup', {})
        if previous.get('status') == 'running':
            reporter.emit(9, 'warning', 'งานลบครั้งก่อนถูกขัดจังหวะ รอรอบถัดไป', persist=True)

    def requested_today(self):
        try:
            path = request_path(self.settings)
            if not path.is_file():
                return False
            request = json.loads(path.read_text(encoding='utf-8-sig'))
            return request.get('day') == current_time().date().isoformat()
        except (OSError, ValueError, TypeError, AttributeError) as error:
            self.reporter.emit(9, 'warning', f'อ่านคำขอลบไฟล์ไม่ได้ จึงไม่ลบจากคำขอนี้: {type(error).__name__}: {error}', persist=True)
            return False

    def tick(self, now, active, stop_event):
        if not self.settings.get('daily_cleanup_enabled', True) or stop_event.is_set():
            return False
        moment = datetime.fromtimestamp(now, BANGKOK)
        deadline = scheduled_time(moment, self.settings.get('cleanup_time', '22:00'))
        if self.history.data.get('daily_cleanup', {}).get('day') == moment.date().isoformat():
            return False
        if now < self.due:
            if moment < deadline or now < self.next_request_check:
                return False
            self.next_request_check = now + 5
            if not self.requested_today():
                return False
            self.due = deadline.timestamp()
        scheduled = datetime.fromtimestamp(self.due, BANGKOK)
        if moment.date() != scheduled.date():
            # Machine asleep/offline across midnight: do not clean the new day's files.
            self.due = deadline.timestamp()
            if self.due < now:
                self.due += 86400
            return False
        if active:
            if not self.wait_reported:
                self.reporter.emit(9, 'waiting', 'รอให้งานปัจจุบันเสร็จก่อนลบไฟล์', persist=True)
                self.wait_reported = True
            return True  # Do not start the next account before cleanup.
        day = scheduled.date().isoformat()
        self.due = (scheduled + timedelta(days=1)).timestamp()
        self.wait_reported = False
        if self.history.data.get('daily_cleanup', {}).get('day') == day:
            return False
        self.run(day, stop_event)
        return False

    def run(self, day, stop_event):
        moment = current_time()
        if moment.date().isoformat() != day or moment < scheduled_time(moment, self.settings.get('cleanup_time', '22:00')):
            return
        if self.history.data.get('daily_cleanup', {}).get('day') == day:
            return
        record = {'day': day, 'status': 'running', 'started': current_time().isoformat(),
                  'roots': {}, 'deleted_names': [], 'pending_names': []}
        with self.history.lock:
            self.history.data['daily_cleanup'] = record
            self.history.save()  # A restart must not repeat deletion against new arrivals.
        self.reporter.emit(9, 'running', 'เริ่มลบไฟล์ตามเวลา')

        def before_delete(filename):
            with self.history.lock:
                record['pending_names'] = [filename.casefold()]
                self.history.save()

        def after_delete(filename):
            with self.history.lock:
                record['deleted_names'] = sorted(set(record['deleted_names']) | {filename.casefold()})
                record['pending_names'] = []
                self.history.save()

        def failed_delete(filename):
            with self.history.lock:
                record['pending_names'] = [name for name in record['pending_names'] if name != filename.casefold()]
                self.history.save()

        for key, approved in zip(('original_dir', 'new_dir'), APPROVED_ROOTS):
            if stop_event.is_set():
                record['status'] = 'stopped'
                break
            try:
                root = validated_root(self.settings[key], approved)
                record['roots'][approved] = cleanup_root(root, self.reporter, stop_event, day, before_delete, after_delete, failed_delete)
            except Exception as error:
                record['roots'][approved] = {'deleted': 0, 'preserved': 0, 'errors': 1, 'stopped': False}
                self.reporter.emit(9, 'error', f'ลบไฟล์ในโฟลเดอร์นี้ไม่ได้: {type(error).__name__}: {error}', destination=approved, persist=True)
        if record['status'] != 'stopped':
            record['status'] = ('stopped' if stop_event.is_set() or any(item['stopped'] for item in record['roots'].values()) else 'errors' if any(item['errors'] for item in record['roots'].values()) else 'complete')
        record['finished'] = current_time().isoformat()
        with self.history.lock:
            self.history.save()
        deleted = sum(item['deleted'] for item in record['roots'].values())
        errors = sum(item['errors'] for item in record['roots'].values())
        self.reporter.emit(9, 'stage_complete' if record['status'] == 'complete' else 'warning',
                           f"ลบ {deleted} ไฟล์ · ผิดพลาด {errors}" + (' · หยุดก่อนครบ' if record['status'] == 'stopped' else ''), persist=True)
        path = request_path(self.settings)
        if path.is_file() and self.requested_today():
            path.unlink()


def run_scheduled_cleanup(settings, stop_event=None):
    """Headless task: request cooperative cleanup or acquire the shared worker lock."""
    from .storage import History, Reporter, WorkerLock

    stop_event = stop_event or threading.Event()
    if not settings.get('daily_cleanup_enabled', True):
        return 0
    moment = current_time()
    if moment < scheduled_time(moment, settings.get('cleanup_time', '22:00')):
        return 0  # Never allow a manual/early task run to delete files.
    day = moment.date().isoformat()
    path = request_path(settings)
    previous = History(Path(settings['log_dir'])).data.get('daily_cleanup', {})
    if previous.get('day') == day and previous.get('status') != 'running':
        return 0 if previous.get('status') == 'complete' else 1
    write_request(settings, day, moment.isoformat())
    while not stop_event.is_set() and current_time().date().isoformat() == day:
        history = History(Path(settings['log_dir']))
        previous = history.data.get('daily_cleanup', {})
        if previous.get('day') == day and previous.get('status') != 'running':
            if path.is_file():
                path.unlink()
            return 0 if previous.get('status') == 'complete' else 1
        worker_lock = WorkerLock(Path(settings['log_dir']))
        try:
            worker_lock.__enter__()
        except RuntimeError:
            stop_event.wait(5)
            continue
        try:
            history = History(Path(settings['log_dir']))
            reporter = Reporter(history, lambda _event: None)
            reporter.language = 'th'
            DailyCleanup(settings, history, reporter, current_time().timestamp()).run(day, stop_event)
            status = history.data.get('daily_cleanup', {}).get('status')
            return 0 if status == 'complete' else 1
        finally:
            worker_lock.__exit__(None, None, None)
    return 1
