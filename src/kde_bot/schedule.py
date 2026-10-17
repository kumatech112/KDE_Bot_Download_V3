"""Bangkok working hours and in-process maintenance deadlines."""

from datetime import datetime, timedelta

from .evidence import BANGKOK


def overnight_key(now: float) -> str | None:
    moment = datetime.fromtimestamp(now, BANGKOK)
    if moment.hour >= 22:
        return moment.date().isoformat()
    if moment.hour < 5:
        return (moment.date() - timedelta(days=1)).isoformat()
    return None


class TrackingHours:
    def __init__(self, history):
        self.history = history

    def resume_manually(self, now: float) -> None:
        key = overnight_key(now)
        if key:
            with self.history.lock:
                self.history.data['tracking_schedule'] = {'manual_night': key}
                self.history.save()

    def allowed(self, now: float) -> bool:
        key = overnight_key(now)
        record = self.history.data.get('tracking_schedule', {})
        override = record.get('manual_night') if isinstance(record, dict) else None
        return key is None or override == key


class BackgroundClock:
    """No missed-night deletion: starting after 22:00 schedules tomorrow."""

    def __init__(self, now: float):
        moment = datetime.fromtimestamp(now, BANGKOK)
        self.cleanup_due = self.next_hour(moment, 22)
        self.resume_due = self.next_hour(moment, 5)

    @staticmethod
    def next_hour(moment, hour):
        due = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        return due if due > moment else due + timedelta(days=1)

    def tick(self, now: float) -> list[str]:
        moment = datetime.fromtimestamp(now, BANGKOK)
        actions = []
        if moment >= self.cleanup_due:
            if moment.date() == self.cleanup_due.date() and moment.hour >= 22:
                actions.append('cleanup')
            self.cleanup_due = self.next_hour(moment, 22)
        if moment >= self.resume_due:
            if 5 <= moment.hour < 22:
                actions.append('resume')
            self.resume_due = self.next_hour(moment, 5)
        return actions
