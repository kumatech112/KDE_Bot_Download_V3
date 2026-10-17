"""Search both portal accounts before selecting files; never force another session out."""

from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor


class AccountBusyError(RuntimeError):
    pass


class CredentialsError(RuntimeError):
    pass


class SearchCoordinator:
    def __init__(self, sources, stop_event):
        self.sources = sources
        self.stop_event = stop_event
        self.condition = threading.Condition()
        self.catalogues = {}
        self.failures = {}
        self.engines = {}
        self.plans = None
        self.conflicts = {}

    def fail(self, source, outcome):
        with self.condition:
            self.failures[source] = outcome
            self.condition.notify_all()

    def select(self, source, engine, rows):
        with self.condition:
            self.catalogues[source] = rows
            while len(self.catalogues) < len(self.sources) and not self.failures and not self.stop_event.is_set():
                self.condition.wait(0.1)
            if self.failures or self.stop_event.is_set():
                return {}, {}, {}
            if self.plans is None:
                combined = []
                origins = {}
                for username in self.sources:
                    for local_index, row in self.catalogues[username]:
                        global_index = len(combined)
                        combined.append((global_index, row))
                        origins[global_index] = (username, local_index)
                selected, self.conflicts = engine._select_page_mail_matches(combined, {})
                self.plans = {username: ({}, {}) for username in self.sources}
                for global_index, detail in selected.items():
                    username, local_index = origins[global_index]
                    self.plans[username][0][local_index] = detail
                    self.plans[username][1][local_index] = set(engine.row_jobs.get(global_index, set()))
                self.condition.notify_all()
            selected, row_jobs = self.plans[source]
            conflicts = self.conflicts if source == self.sources[0] else {}
            return copy.deepcopy(selected), dict(conflicts), copy.deepcopy(row_jobs)


def run_search_round(settings, jobs, stop_event, reporter, history, temporary):
    from .workflow import StructuredDownloader, make_engine_settings, run_account_batch
    from .storage import Delivery
    sources = [account["username"] for account in settings["accounts"] if account["enabled"]]
    with history.lock:
        busy = history.data.setdefault("busy_search_accounts", {})
        blocked = history.data.setdefault("blocked_search_accounts", {})
        blocked_reason = next((blocked[source] for source in sources if source in blocked), None)
        known_busy = {source: due for source, due in busy.items() if source in sources}
    if blocked_reason:
        return {job["id"]: {"kind": "credentials", "reason": blocked_reason} for job in jobs}
    # While an account is known busy, probe only that account. Do not repeatedly
    # reopen the available account or hold its browser/session while waiting.
    for source, due in known_busy.items():
        if due > time.time() or stop_event.is_set():
            continue
        try:
            engine = StructuredDownloader(make_engine_settings(settings, temporary / f"probe-{jobs[0]['id']}-{sources.index(source)}.json"),
                                          reporter, Delivery(history, reporter), settings, stop_event)
            engine.probe_only = True
            account = next(account for account in engine.settings.accounts if account.username == source)
            engine.process_account(account)
            if engine.logout_failures:
                raise RuntimeError("Own-session logout could not be confirmed.")
        except AccountBusyError as error:
            with history.lock:
                busy[source] = time.time() + settings["login_retry_seconds"]
                history.save()
        except CredentialsError as error:
            with history.lock:
                blocked[source] = str(error)
                history.save()
            return {job["id"]: {"kind": "credentials", "reason": str(error)} for job in jobs}
        except Exception as error:
            with history.lock:
                busy.pop(source, None)
                history.save()
            reason = str(error)
            for account_settings in settings["accounts"]:
                if account_settings["password"]:
                    reason = reason.replace(account_settings["password"], "[REDACTED]")
            return {job["id"]: {"kind": "login_failed", "reason": reason} for job in jobs}
        else:
            with history.lock:
                busy.pop(source, None)
                history.save()
    with history.lock:
        pending_busy = {source: busy[source] for source in sources if source in busy}
    if pending_busy:
        outcome = {"kind": "account_busy", "sources": list(pending_busy), "retry_at": min(pending_busy.values()),
                   "reason": "Waiting for the busy account before completing the two-source search; no forced sign-out."}
        return {job["id"]: dict(outcome) for job in jobs}
    if stop_event.is_set():
        return {job["id"]: {"kind": "missing", "reason": "Stopped before search."} for job in jobs}
    coordinator = SearchCoordinator(sources, stop_event)
    def source_task(source):
        try:
            return run_account_batch(settings, jobs, stop_event, reporter, history, temporary,
                                     source_username=source, coordinator=coordinator)
        except Exception as error:
            reason = str(error)
            for account_settings in settings["accounts"]:
                if account_settings["password"]:
                    reason = reason.replace(account_settings["password"], "[REDACTED]")
            coordinator.fail(source, {"kind": "download_failed", "reason": reason})
            return {}
    with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="KDE-source") as executor:
        futures = [executor.submit(source_task, source) for source in sources]
        source_results = [future.result() for future in futures]
    failures = list(coordinator.failures.items())
    credential_failure = next(((source, value) for source, value in failures if value["kind"] == "credentials"), None)
    if credential_failure:
        source, outcome = credential_failure
        with history.lock:
            blocked[source] = outcome["reason"]
            history.save()
        return {job["id"]: dict(outcome) for job in jobs}
    busy_failures = [source for source, value in failures if value["kind"] == "account_busy"]
    if busy_failures:
        with history.lock:
            for source in busy_failures:
                busy[source] = time.time() + settings["login_retry_seconds"]
            history.save()
        outcome = {"kind": "account_busy", "sources": busy_failures, "retry_at": min(busy[source] for source in busy_failures),
                   "reason": "A KDE account is in use. Available sessions were closed; only busy accounts will be probed."}
        return {job["id"]: dict(outcome) for job in jobs}
    if failures:
        outcome = failures[0][1]
        return {job["id"]: dict(outcome) for job in jobs}
    # Merge evidence from both workers. A file found in only one account must not
    # be reported missing by the worker that deliberately did not download it.
    aggregate = next(iter(coordinator.engines.values()))
    aggregate.job_statuses = {}
    aggregate.required_matches = {}
    for result in source_results:
        for job_id, value in result.get("statuses", {}).items():
            aggregate.job_statuses.setdefault(job_id, []).extend(value)
        for job_id, value in result.get("required", {}).items():
            aggregate.required_matches.setdefault(job_id, set()).update(value)
    outcomes = aggregate.job_outcomes()
    if coordinator.conflicts:
        for job in jobs:
            if set(job["lookup"]) & set(coordinator.conflicts):
                outcomes[job["id"]] = {"kind": "ambiguous", "reason": "Different files match across Pre/Post; confirm the reference."}
    return outcomes
