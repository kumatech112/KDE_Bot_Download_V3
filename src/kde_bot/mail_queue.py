"""Durable mail-trigger queue. Polling Outlook never implies a KDE login."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from . import legacy_core as core
from .storage import History, Reporter


TERMINAL = {"complete", "copy_pending", "exhausted"}


def account_side(account: dict[str, Any], index: int) -> str:
    label = account["label"].casefold()
    if "post" in label:
        return "post"
    if "pre" in label:
        return "pre"
    return core.account_side_from_name(account["username"]) or ("pre" if index == 0 else "post")


def route_lookup(message: dict[str, Any], side: str) -> dict[str, str]:
    lookup = message["lookup"]
    explicit_sides = {core.account_side_from_name(key) for key in lookup}
    explicit_sides.discard(None)
    subject = message.get("subject", "").casefold()
    if not explicit_sides:
        import re
        explicit_sides = set(re.findall(r"\b(pre|post)\b", subject))
    if explicit_sides and side not in explicit_sides:
        return {}
    return {key: value for key, value in lookup.items()
            if core.account_side_from_name(key) in {None, side}}


def message_identity(message: dict[str, Any]) -> str:
    entry = message.get("entry_id", "")
    if entry:
        identity = [message.get("store_id", ""), entry]
    else:
        # Stable fallback for stores lacking EntryID; no full body is persisted.
        identity = [message.get("folder", ""), message.get("received", ""),
                    message.get("subject", ""), sorted(message["lookup"])]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()


class MailQueue:
    def __init__(self, history: History, reporter: Reporter, settings: dict[str, Any]):
        self.history = history
        self.reporter = reporter
        self.settings = settings
        self.jobs = history.data["mail_jobs"]
        self.cooldowns = history.data.setdefault("account_cooldowns", {})

    def recover_interrupted(self, now: float) -> None:
        with self.history.lock:
            changed = False
            for job in self.jobs.values():
                if job["status"] != "running":
                    continue
                changed = True
                job["status"] = "exhausted" if job["attempts"] >= 2 else "waiting"
                job["due"] = max(job["due"], now + self.settings["login_retry_seconds"])
                job["last_reason"] = "งานถูกขัดจังหวะ: เก็บจำนวนครั้งเดิมไว้ และรอ 5 นาทีก่อนเปิด Session ใหม่"
                self.reporter.emit(3, "error" if job["status"] == "exhausted" else "warning",
                                   job["last_reason"], job["label"], self.display(job), persist=True)
            if changed:
                self.history.save()

    @staticmethod
    def display(job: dict[str, Any]) -> str:
        return "เมล " + job["id"][:10] + " | " + ", ".join(list(job["lookup"])[:2])

    def ingest(self, messages: list[dict[str, Any]], now: float) -> int:
        added = 0
        with self.history.lock:
            for message in messages:
                mail_id = message_identity(message)
                for index, account in enumerate(self.settings["accounts"]):
                    if not account["enabled"]:
                        continue
                    lookup = route_lookup(message, account_side(account, index))
                    if not lookup:
                        continue
                    key = hashlib.sha256(f"{mail_id}|{account['username'].casefold()}".encode()).hexdigest()
                    if key in self.jobs:
                        continue
                    job = {
                        "id": key, "mail_id": mail_id, "account": account["username"],
                        "label": account["label"], "lookup": lookup,
                        "received": message.get("received", ""), "observed": now,
                        "due": now + self.settings["mail_delay_seconds"],
                        "attempts": 0, "status": "waiting", "last_reason": "",
                    }
                    self.jobs[key] = job
                    added += 1
                    self.reporter.emit(2, "waiting", "พบอีเมลใหม่: รอ 3 นาทีก่อนค้นหาไฟล์ KDE",
                                       job["label"], self.display(job), persist=True)
            if added:
                self.history.save()
        return added

    def claim_ready(self, now: float, busy_accounts: set[str]) -> dict[str, list[dict[str, Any]]]:
        batches: dict[str, list[dict[str, Any]]] = {}
        enabled = {account["username"] for account in self.settings["accounts"] if account["enabled"]}
        with self.history.lock:
            for job in self.jobs.values():
                if (job["status"] != "waiting" or job["due"] > now
                        or job["account"] in busy_accounts or job["account"] not in enabled):
                    continue
                if self.cooldowns.get(job["account"], 0) > now:
                    continue
                if job["attempts"] >= self.settings["max_session_attempts"]:
                    job["status"] = "exhausted"
                    continue
                job["total_attempts"] = job.get("total_attempts", job["attempts"]) + 1
                job["attempts"] += 1
                job["status"] = "running"
                # Durable before login; a crash cannot reset the budget or cooldown.
                job["due"] = now + self.settings["login_retry_seconds"]
                batches.setdefault(job["account"], []).append(copy.deepcopy(job))
            if batches:
                self.history.save()
        return batches

    def requeue_failed(self, now: float) -> int:
        count = 0
        enabled = {account["username"] for account in self.settings["accounts"] if account["enabled"]}
        with self.history.lock:
            for job in self.jobs.values():
                if job["status"] != "exhausted" or job["account"] not in enabled:
                    continue
                job["attempts"] = 0
                job["cycle"] = job.get("cycle", 1) + 1
                job["status"] = "waiting"
                job["due"] = now + self.settings["mail_delay_seconds"]
                count += 1
                self.reporter.emit(2, "waiting", f"ผู้ใช้สั่งเริ่มรอบใหม่ {job['cycle']}: หน่วง 3 นาที และให้ไม่เกิน 2 ครั้งในรอบนี้",
                                   job["label"], self.display(job), persist=True)
            if count:
                self.history.save()
        return count

    def finish(self, outcomes: dict[str, dict[str, str]], now: float, stopped: bool = False) -> None:
        with self.history.lock:
            for key, outcome in outcomes.items():
                job = self.jobs[key]
                kind = outcome["kind"]
                reason = outcome["reason"]
                job["last_reason"] = reason
                if kind == "login_failed":
                    self.cooldowns[job["account"]] = now + self.settings["login_retry_seconds"]
                if kind in {"complete", "copy_pending"}:
                    job["status"] = kind
                    status = "stage_complete" if kind == "complete" else "copy_pending"
                elif stopped:
                    job["status"] = "exhausted" if job["attempts"] >= 2 else "waiting"
                    job["due"] = now + self.settings["login_retry_seconds"]
                    status = "warning"
                elif job["attempts"] >= self.settings["max_session_attempts"]:
                    job["status"] = "exhausted"
                    status = "error"
                    reason += " — ครบ 2 ครั้งแล้ว หยุดอัตโนมัติ"
                else:
                    job["status"] = "waiting"
                    delay = self.settings["login_retry_seconds"] if kind == "login_failed" else 0
                    job["due"] = now + delay
                    status = "waiting"
                    reason += " — รอ 5 นาทีก่อน Login ใหม่" if delay else " — Logout แล้วเปิด Session ใหม่อีก 1 ครั้ง"
                step = 3 if kind == "login_failed" else 7 if kind == "copy_pending" else 4
                self.reporter.emit(step, status, f"ครั้ง {job['attempts']}/2: {reason}",
                                   job["label"], self.display(job), persist=True, count=status == "error")
            self.history.save()

    def has_pending(self) -> bool:
        with self.history.lock:
            return any(job["status"] in {"waiting", "running"} for job in self.jobs.values()
                       if any(account["enabled"] and account["username"] == job["account"]
                              for account in self.settings["accounts"]))
