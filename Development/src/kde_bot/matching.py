"""Conservative OCR tolerance with account, business-date and numeric guards."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from . import legacy_core as core


def row_matches_job_date(filename: str, row_time: str, job: dict[str, Any]) -> bool:
    requested_days = set()
    requested_months = set()
    for key in job["lookup"]:
        days, months = core.normalized_business_dates(key)
        requested_days.update(days)
        requested_months.update(months)
    file_days, file_months = core.normalized_business_dates(filename)
    if not file_days:
        for date in re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", row_time):
            day, month, year = map(int, date)
            if year > 2400:
                year -= 543
            file_days.add(f"{year:04}-{month:02}-{day:02}")
        file_days.update(re.findall(r"\d{4}-\d{2}-\d{2}", row_time))
    if requested_days:
        return bool(file_days & requested_days)
    if requested_months:
        return bool(file_months & requested_months)
    day = job.get("work_date") or job.get("received", "")[:10]
    if day and file_days:
        return day in file_days
    # No dated broad match: exact/precise references can still name an undated file.
    return any(core.is_precise_mail_lookup_key(key, original) for key, original in job["lookup"].items())


def ocr_match(kde_key: str, mail_key: str, original: str) -> dict[str, Any] | None:
    if "ocr" not in original.lower() and "imported image" not in original.lower():
        return None
    if not core.account_sides_are_compatible(mail_key, kde_key) or not core.business_dates_are_compatible(mail_key, kde_key):
        return None
    if core.split_volume_part(mail_key) and core.split_volume_part(mail_key) != core.split_volume_part(kde_key):
        return None
    reference = core.business_file_identity(mail_key)
    candidate = core.business_file_identity(kde_key)
    if len(reference) < 14 or len(candidate) < 14:
        return None
    if re.findall(r"\d+", reference) != re.findall(r"\d+", candidate):
        return None
    if len(core.meaningful_tokens_for_match(mail_key)) < 2:
        return None
    ratio = SequenceMatcher(None, reference, candidate).ratio()
    if ratio < 0.94:
        return None
    return {"mail_key": mail_key, "original": original, "score": 80, "precise": True,
            "source_priority": 3, "ocr_similarity": round(ratio, 3)}
