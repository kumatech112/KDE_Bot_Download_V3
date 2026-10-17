"""Bangkok working hours and in-process maintenance deadlines."""

from datetime import datetime, timedelta
import re

from .evidence import BANGKOK


def clock_parts(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ValueError('กรุณาระบุเวลาแบบ HH:MM เช่น 22:00')
    return tuple(int(part) for part in value.split(':'))


def scheduled_time(moment, value):
    hour, minute = clock_parts(value)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


def overnight_key(now: float, cleanup_time='22:00', resume_time='05:00') -> str | None:
    moment = datetime.fromtimestamp(now, BANGKOK)
    start = scheduled_time(moment, cleanup_time)
    end = scheduled_time(moment, resume_time)
    if start == end:
        raise ValueError('เวลาพักและเวลาเริ่มติดตามต้องไม่ตรงกัน')
    if start < end:
        return moment.date().isoformat() if start <= moment < end else None
    if moment >= start:
        return moment.date().isoformat()
    if moment < end:
        return (moment.date() - timedelta(days=1)).isoformat()
    return None


class TrackingHours:
    def __init__(self, history, settings=None):
        self.history = history
        self.settings = settings or {}
        self.cleanup_time = self.settings.get('cleanup_time', '22:00')
        self.resume_time = self.settings.get('resume_time', '05:00')
        self.window = self.cleanup_time + '/' + self.resume_time

    def key(self, now):
        return overnight_key(now, self.cleanup_time, self.resume_time) if self.settings.get('night_pause_enabled', True) else None

    def resume_manually(self, now: float) -> None:
        key = self.key(now)
        if key:
            with self.history.lock:
                self.history.data['tracking_schedule'] = {'manual_night': key, 'window': self.window}
                self.history.save()

    def allowed(self, now: float) -> bool:
        key = self.key(now)
        record = self.history.data.get('tracking_schedule', {})
        override = record.get('manual_night') if isinstance(record, dict) else None
        window = record.get('window', '22:00/05:00') if isinstance(record, dict) else None
        return key is None or (override == key and window == self.window)


class BackgroundClock:
    """No missed-night deletion: starting after 22:00 schedules tomorrow."""

    def __init__(self, now: float, settings=None):
        settings = settings or {}
        self.cleanup_time = settings.get('cleanup_time', '22:00')
        self.resume_time = settings.get('resume_time', '05:00')
        self.pause_enabled = settings.get('night_pause_enabled', True)
        moment = datetime.fromtimestamp(now, BANGKOK)
        self.cleanup_due = self.next_time(moment, self.cleanup_time)
        self.resume_due = self.next_time(moment, self.resume_time)

    @staticmethod
    def next_time(moment, value):
        due = scheduled_time(moment, value)
        return due if due > moment else due + timedelta(days=1)

    @staticmethod
    def next_hour(moment, hour):
        due = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        return due if due > moment else due + timedelta(days=1)

    def tick(self, now: float) -> list[str]:
        moment = datetime.fromtimestamp(now, BANGKOK)
        actions = []
        if moment >= self.cleanup_due:
            if moment.date() == self.cleanup_due.date():
                actions.append('cleanup')
            self.cleanup_due = self.next_time(moment, self.cleanup_time)
        if moment >= self.resume_due:
            if self.pause_enabled and overnight_key(now, self.cleanup_time, self.resume_time) is None:
                actions.append('resume')
            self.resume_due = self.next_time(moment, self.resume_time)
        return actions
