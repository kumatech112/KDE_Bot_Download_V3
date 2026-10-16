"""Bounded chronological work history, independent of the latest file outcomes."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from .storage import CSV_FIELDS, record_key


def event_identity(event: dict[str, Any]) -> str:
    values = [str(event.get(field, "")) for field in CSV_FIELDS]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def update_latest(rows: OrderedDict[str, dict[str, Any]], event: dict[str, Any], limit: int = 2000) -> None:
    """Resolved stage errors leave the current Error view, but remain in the timeline."""
    key = event["key"]
    if not event.get("filename") and event["status"] == "stage_complete":
        rows.pop(key, None)
        return
    if not event.get("filename") and event["status"] not in {"error", "warning"}:
        return
    previous = rows.get(key)
    if event["status"] == "running" and previous and previous["status"] in {"error", "copy_pending"}:
        return
    rows[key] = event
    rows.move_to_end(key)
    while len(rows) > limit:
        rows.popitem(last=False)


class ActivityHistory:
    def __init__(self, limit: int = 2000):
        self.limit = limit
        self.entries: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def add(self, event: dict[str, Any]) -> None:
        if event.get("activity_recorded") is False:
            return
        self.entries.setdefault(event_identity(event), dict(event))
        while len(self.entries) > self.limit:
            self.entries.popitem(last=False)

    def merge(self, events: Iterable[dict[str, Any]]) -> None:
        combined = list(self.entries.values()) + list(events)
        combined.sort(key=lambda event: str(event["time"]))
        self.entries.clear()
        for event in combined:
            self.add(event)


def read_activity(folder: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the latest three monthly CSVs without inventing missing historical actions."""
    activity = ActivityHistory()
    latest: OrderedDict[str, dict[str, Any]] = OrderedDict()
    if not folder.is_dir():
        raise FileNotFoundError(f"Log folder is missing or inaccessible: {folder}")
    for path in sorted(folder.glob("KDE_Log_*.csv"))[-3:]:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if not row.get("time") or not row.get("status"):
                    continue
                for field, value in row.items():
                    if isinstance(value, str) and value.startswith(("'=", "'+", "'-", "'@")):
                        row[field] = value[1:]
                row["step"] = int(row["step"])
                row["key"] = record_key(row["account"], row["filename"]) if row["filename"] else f"stage:{row['account']}:{row['step']}"
                activity.add(row)
                update_latest(latest, row)
    activity.merge([])
    return list(activity.entries.values()), list(latest.values())
