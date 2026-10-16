"""Durable mail-trigger queue. Polling Outlook never implies a KDE login."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from . import legacy_core as core
from .storage import History, Reporter
from .evidence import reference_lookup


TERMINAL = {"complete", "copy_pending", "exhausted", "deferred"}


def reference_side(text: str) -> str | None:
    import re
    side = core.account_side_from_name(text)
    if side:
        return side
    marker = re.search(r"(?i)\ba10xx(l)?\b", text.replace("_", " "))
    return ("post" if marker.group(1) else "pre") if marker else None


def account_side(account: dict[str, Any], index: int) -> str:
    label = account["label"].casefold()
    if "post" in label:
        return "post"
    if "pre" in label:
        return "pre"
    return core.account_side_from_name(account["username"]) or ("pre" if index == 0 else "post")


def route_lookup(message: dict[str, Any], side: str) -> dict[str, str]:
    lookup = message["lookup"]
    explicit_sides = {reference_side(key) for key in lookup}
    explicit_sides.discard(None)
    subject = message.get("subject", "").casefold()
    if not explicit_sides and not message.get("side"):
        import re
        explicit_sides = set(re.findall(r"\b(pre|post)\b", subject))
    if message.get("side") in {"pre", "post"}:
        if explicit_sides and message["side"] not in explicit_sides:
            return {}
        explicit_sides = {message["side"]}
    if explicit_sides and side not in explicit_sides:
        return {}
    return {key: value for key, value in lookup.items()
            if reference_side(key) in {None, side}}


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
    def __init__(self, history: History, reporter: Reporter, settings: dict[str, Any], today: str | None = None):
        self.history = history
        self.reporter = reporter
        self.settings = settings
        self.jobs = history.data["mail_jobs"]
        self.cooldowns = history.data.setdefault("account_cooldowns", {})
        self.today = today

    def expire_old(self) -> None:
        if not self.today:
            return
        for job in self.jobs.values():
            if job.get("flow_version") == 4:
                continue
            day = job.get("work_date") or job.get("received", "")[:10]
            if day != self.today and job["status"] in {"waiting", "review", "copy_pending"}:
                job["status"] = "expired"
                job["last_reason"] = "Previous or unknown-day work retained for history; no automatic login."

    def snapshot(self) -> list[dict[str, Any]]:
        with self.history.lock:
            return [copy.deepcopy(job) for job in self.jobs.values()
                    if not self.today or (job.get("work_date") or job.get("received", "")[:10]) == self.today
                    or job["status"] in {"waiting", "running", "deferred", "review", "copy_pending"}][-1000:]

    def window_due(self, now: float) -> float:
        windows = [job["due"] for job in self.jobs.values() if job["status"] == "waiting"
                   and job["attempts"] == 0 and not job.get("busy_sources") and job["due"] > now]
        return min([now + self.settings["mail_delay_seconds"], *windows])

    def recover_interrupted(self, now: float) -> None:
        with self.history.lock:
            changed = False
            for username, deadline in self.cooldowns.items():
                self.cooldowns[username] = min(deadline, now + self.settings["login_retry_seconds"])
            for job in self.jobs.values():
                if job.get("flow_version") != 4 and job["status"] == "waiting" and job["attempts"]:
                    job["due"] = min(job["due"], now + self.settings["login_retry_seconds"])
                if job["status"] == "exhausted":
                    job["status"] = "deferred"
                    job["last_reason"] = "Previous attempts retained; wait for a new relevant email."
                    changed = True
                if job["status"] in {"waiting", "running", "deferred", "review", "copy_pending"}:
                    job["flow_version"] = 4
                if job["status"] != "running":
                    continue
                changed = True
                job["status"] = "deferred" if job["attempts"] >= 2 else "waiting"
                job["due"] = max(now, min(job["due"], now + self.settings["login_retry_seconds"]))
                job["last_reason"] = "Interrupted session: budget retained; retry after 60 seconds or the next mail round."
                self.reporter.emit(3, "warning",
                                   job["last_reason"], job["label"], self.display(job), persist=True)
            if changed:
                self.history.save()
            self.expire_old()
            for job in self.jobs.values():
                if job["status"] == "waiting" and job["attempts"] == 0 and not job.get("busy_sources"):
                    fallback = min(job["due"], now + self.settings["mail_delay_seconds"])
                    if job.get("cycle", 1) == 1:
                        fallback = min(fallback, job.get("observed", fallback) + self.settings["mail_delay_seconds"])
                    job["window_due"] = job.get("window_due", fallback)
                    job["due"] = min(job["due"], job["window_due"])
            self.history.save()

    @staticmethod
    def display(job: dict[str, Any]) -> str:
        return job.get("subject") or "Mail " + job["id"][:10] + " | " + ", ".join(list(job["lookup"])[:2])

    def ingest(self, messages: list[dict[str, Any]], now: float) -> int:
        added = 0
        with self.history.lock:
            due = self.window_due(now)
            for message in sorted(messages, key=lambda item: item.get("received", "")):
                mail_id = message_identity(message)
                day = message.get("received", "")[:10] or self.today or ""
                if self.today and day != self.today:
                    continue
                sides = {reference_side(key) for key in message["lookup"]}
                sides.discard(None)
                conflict = bool(message.get("side") and sides and message["side"] not in sides)
                if not sides and not message.get("side"):
                    import re
                    sides = set(re.findall(r"\b(pre|post)\b", message.get("subject", "").lower()))
                if message.get("side"):
                    sides.add(message["side"])
                search_any = not sides
                needs_review = message.get("review", False) or not message["lookup"] or conflict
                if needs_review:
                    if any(job["mail_id"] == mail_id for job in self.jobs.values()):
                        continue
                    assigned = next((account for index, account in enumerate(self.settings["accounts"])
                                     if account["enabled"] and sides == {account_side(account, index)}), None)
                    key = hashlib.sha256(f"{mail_id}|review".encode()).hexdigest()
                    self.history.data["mail_sequence"] = self.history.data.get("mail_sequence", 0) + 1
                    self.jobs[key] = {"id": key, "mail_id": mail_id, "account": assigned["username"] if assigned else "",
                                      "label": assigned["label"] if assigned else "Unassigned", "lookup": message["lookup"],
                                      "subject": message.get("subject", "Email needs review"), "received": message.get("received", ""),
                                      "work_date": day, "observed": now, "due": due, "attempts": 0, "flow_version": 4,
                                      "sequence": self.history.data["mail_sequence"], "status": "review",
                                      "last_reason": "Confirm account and reference. " + "; ".join(message.get("notes", []))}
                    added += 1
                    self.reporter.emit(2, "warning", self.jobs[key]["last_reason"], self.jobs[key]["label"],
                                       self.display(self.jobs[key]), persist=True)
                    continue
                for index, account in enumerate(self.settings["accounts"]):
                    if not account["enabled"]:
                        continue
                    if search_any and account is not next(item for item in self.settings["accounts"] if item["enabled"]):
                        continue
                    lookup = route_lookup(message, account_side(account, index))
                    if not lookup:
                        continue
                    key = hashlib.sha256(f"{mail_id}|{account['username'].casefold()}".encode()).hexdigest()
                    if key in self.jobs or any(job["mail_id"] == mail_id and job["account"] == account["username"]
                                               for job in self.jobs.values()):
                        continue
                    job = {
                        "id": key, "mail_id": mail_id, "account": account["username"],
                        "label": "Pre + Post" if search_any else account["label"], "lookup": lookup,
                        "search_any_side": search_any,
                        "received": message.get("received", ""), "observed": now,
                        "due": due, "window_due": due, "flow_version": 4,
                        "attempts": 0, "status": "waiting", "last_reason": "",
                        "subject": message.get("subject", ""), "work_date": day,
                        "sequence": self.history.data.get("mail_sequence", 0) + 1,
                        "image_count": message.get("image_count", 0),
                    }
                    self.history.data["mail_sequence"] = job["sequence"]
                    self.jobs[key] = job
                    added += 1
                    self.reporter.emit(2, "waiting", "New mail joined the fixed 60-second window; countdown is not restarted.",
                                       job["label"], self.display(job), persist=True)
            if added:
                self.history.data["mail_generation"] = self.history.data.get("mail_generation", 0) + 1
                self.history.data["mail_window_due"] = due
                for job in self.jobs.values():
                    if job["status"] == "deferred" and any(account["enabled"] and account["username"] == job["account"]
                                                           for account in self.settings["accounts"]):
                        job.update(status="waiting", attempts=0, due=due, window_due=due, cycle=job.get("cycle", 1) + 1,
                                   flow_version=4, last_reason="New relevant email started the next retry round.")
                        self.reporter.emit(2, "waiting", job["last_reason"], job["label"], self.display(job), persist=True)
                self.history.save()
        return added

    def claim_ready(self, now: float, busy_accounts: set[str]) -> dict[str, list[dict[str, Any]]]:
        batches: dict[str, list[dict[str, Any]]] = {}
        enabled = {account["username"] for account in self.settings["accounts"] if account["enabled"]}
        with self.history.lock:
            self.expire_old()
            blocked = set(busy_accounts) | {job["account"] for job in self.jobs.values() if job["status"] == "running"}
            heads = {}
            for job in sorted(self.jobs.values(), key=lambda item: (item.get("sequence", 0), item.get("observed", 0), item["id"])):
                if job["status"] in {"waiting", "review", "copy_pending"} and job["account"] in enabled:
                    heads.setdefault(job["account"], job)
            for job in heads.values():
                if (job["status"] != "waiting" or job["due"] > now
                        or job["account"] in blocked or job["account"] not in enabled):
                    continue
                if self.cooldowns.get(job["account"], 0) > now:
                    continue
                if job["attempts"] >= self.settings["max_session_attempts"]:
                    job["status"] = "deferred"
                    continue
                if job["attempts"] == 0:
                    job["round_generation"] = self.history.data.get("mail_generation", 0)
                job["total_attempts"] = job.get("total_attempts", job["attempts"]) + 1
                job["attempts"] += 1
                job["status"] = "running"
                # Durable before login; a crash cannot reset the budget or cooldown.
                job["due"] = now + self.settings["login_retry_seconds"]
                batches.setdefault(job["account"], []).append(copy.deepcopy(job))
            if batches:
                self.history.save()
        return batches

    def resolve(self, job_id: str, username: str, reference: str, now: float) -> None:
        with self.history.lock:
            job = self.jobs[job_id]
            account = next(account for account in self.settings["accounts"]
                           if account["enabled"] and account["username"] == username)
            if job["status"] not in {"review", "exhausted", "deferred"}:
                raise ValueError("Only review or deferred requests can be confirmed manually.")
            if self.today and job.get("work_date") != self.today and job.get("flow_version") != 4:
                raise ValueError("Only today's requests can be queued.")
            lookup = reference_lookup(reference, "User-confirmed reference")
            if not lookup:
                key = core.normalize_filename_for_match(reference.strip())
                if len(core.meaningful_tokens_for_match(key)) < 2:
                    raise ValueError("Enter a filename or a specific business reference.")
                lookup[key] = reference.strip() + " [User-confirmed reference]"
            index = self.settings["accounts"].index(account)
            side = account_side(account, index)
            if any(reference_side(key) not in {None, side} for key in lookup):
                raise ValueError("The reference belongs to the other account side.")
            if job["status"] in {"exhausted", "deferred"}:
                job["attempts"] = 0
                job["cycle"] = job.get("cycle", 1) + 1
            job.update(account=username, label=account["label"], lookup=lookup, status="waiting",
                       due=self.window_due(now), flow_version=4, search_any_side=False,
                       last_reason="Reference confirmed; joined the 60-second window.")
            job["window_due"] = job["due"]
            self.history.save()
            self.reporter.emit(2, "waiting", job["last_reason"], job["label"], self.display(job), persist=True)

    def refresh_saved_jobs(self) -> None:
        with self.history.lock:
            changed = False
            for job in self.jobs.values():
                if job["status"] != "copy_pending":
                    continue
                records = [record for record in self.history.data["files"].values() if job["id"] in record.get("mail_jobs", [])]
                if records and all(not record.get("pending") and record.get("destinations") for record in records):
                    job["status"] = "complete"
                    job["last_reason"] = "Pending saves repaired and verified; no KDE redownload."
                    self.reporter.emit(7, "stage_complete", job["last_reason"], job["label"], self.display(job), persist=True)
                    changed = True
            if changed:
                self.history.save()

    def requeue_failed(self, now: float) -> int:
        count = 0
        enabled = {account["username"] for account in self.settings["accounts"] if account["enabled"]}
        with self.history.lock:
            for job in self.jobs.values():
                if job["status"] not in {"exhausted", "deferred"} or job["account"] not in enabled:
                    continue
                if self.today and (job.get("work_date") or job.get("received", "")[:10]) != self.today and job.get("flow_version") != 4:
                    continue
                job["attempts"] = 0
                job["cycle"] = job.get("cycle", 1) + 1
                job["status"] = "waiting"
                job["due"] = now + self.settings["mail_delay_seconds"]
                job["window_due"] = job["due"]
                count += 1
                self.reporter.emit(2, "waiting", f"Manual retry round {job['cycle']}: 60-second window; at most two attempts.",
                                   job["label"], self.display(job), persist=True)
            if count:
                self.history.save()
        return count

    def finish(self, outcomes: dict[str, dict[str, Any]], now: float, stopped: bool = False) -> None:
        with self.history.lock:
            for key, outcome in outcomes.items():
                job = self.jobs[key]
                kind = outcome["kind"]
                reason = outcome["reason"]
                job["last_reason"] = reason
                if kind == "account_busy":
                    job["attempts"] = max(0, job["attempts"] - 1)
                    job["busy_retries"] = job.get("busy_retries", 0) + 1
                    job.update(status="waiting", due=outcome["retry_at"], busy_sources=outcome["sources"])
                    self.reporter.emit(3, "waiting", f"Account busy; check again after its cooldown. {reason}",
                                       job["label"], self.display(job), persist=True)
                    continue
                job.pop("busy_sources", None)
                if kind in {"credentials", "ambiguous"}:
                    job.update(status="review", last_reason=reason)
                    self.reporter.emit(3 if kind == "credentials" else 4, "warning", reason,
                                       job["label"], self.display(job), persist=True)
                    continue
                if kind == "login_failed":
                    self.cooldowns[job["account"]] = now + self.settings["login_retry_seconds"]
                if kind in {"complete", "copy_pending"}:
                    job["status"] = kind
                    status = "stage_complete" if kind == "complete" else "copy_pending"
                elif stopped:
                    job["status"] = "deferred" if job["attempts"] >= 2 else "waiting"
                    job["due"] = now + self.settings["login_retry_seconds"]
                    status = "warning"
                elif job["attempts"] >= self.settings["max_session_attempts"]:
                    job["status"] = "deferred"
                    status = "warning"
                    reason += " — Two attempts used; waiting for a new relevant email."
                    if self.history.data.get("mail_generation", 0) > job.get("round_generation", 0):
                        deadline = max(now, self.history.data.get("mail_window_due", now))
                        job.update(status="waiting", attempts=0, due=deadline, window_due=deadline,
                                   cycle=job.get("cycle", 1) + 1)
                        status = "waiting"
                        reason += " A new email already arrived during this round; joined its existing deadline."
                else:
                    job["status"] = "waiting"
                    delay = self.settings["login_retry_seconds"] if kind == "login_failed" else 0
                    job["due"] = now + delay
                    status = "waiting"
                    reason += " — Retry after 60 seconds." if delay else " — Logged out; one fresh-session retry queued without another mail delay."
                step = 3 if kind == "login_failed" else 7 if kind == "copy_pending" else 4
                self.reporter.emit(step, status, f"Attempt {job['attempts']}/2: {reason}",
                                   job["label"], self.display(job), persist=True, count=status == "error")
            self.history.save()

    def has_pending(self) -> bool:
        with self.history.lock:
            return any(job["status"] in {"waiting", "running"} for job in self.jobs.values()
                       if any(account["enabled"] and account["username"] == job["account"]
                              for account in self.settings["accounts"]))
