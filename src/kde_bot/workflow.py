"""Run only KDE, preserving portal matching and mandatory logout semantics."""

from __future__ import annotations

import copy
import dataclasses
import os
import queue
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from . import legacy_core as core
from .settings import validate_settings, settings_home
from .storage import Delivery, History, Reporter, WorkerLock, check_destination, check_writable
from .mail_queue import MailQueue, account_side
from .evidence import MailEvidenceReader, today
from .instructions import instruction_match
from .matching import ocr_match, row_matches_job_date


STEPS = {
    1: "Startup", 2: "Email", 3: "Login", 4: "Match",
    5: "Check files", 6: "Download", 7: "Save", 8: "Logout",
}

PAGE_NEXT = ("button[aria-label='Go to next page']", "button[title='Go to next page']",
             "button[aria-label*='next']")
PAGE_PREVIOUS = ("button[aria-label='Go to previous page']", "button[title='Go to previous page']",
                 "button[aria-label*='previous']")


def selected_folders(settings: dict[str, Any], account: dict[str, Any]) -> list[Path]:
    """Both accounts publish directly into the shared configured roots."""
    original = Path(settings["original_dir"])
    new = Path(settings["new_dir"])
    mode = settings["storage_mode"]
    folders = {"both": [original, new], "original": [original], "new": [new]}[mode]
    return list(dict.fromkeys(folders))


def detect_chrome() -> str:
    for root in (
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            path = Path(root) / relative
            if path.is_file():
                return str(path)
    return ""


class StructuredDownloader(core.KdeDownloader):
    def __init__(self, settings: core.Settings, reporter: Reporter, delivery: Delivery,
                 configuration: dict[str, Any], stop_event: threading.Event):
        super().__init__(settings, self.protocol_message, stop_event)
        self.reporter = reporter
        self.delivery = delivery
        self.configuration = configuration
        self.account = ""
        self.stage = 3
        self.logout_failures: list[str] = []
        self.mail_failures: list[str] = []
        self.reported_mail_fallbacks: set[str] = set()
        self.session_attempted = False
        self.file_handler = self.handle_file
        self.login_attempts = 1
        self.mail_messages: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self.row_jobs: dict[int, set[str]] = {}
        self.job_statuses: dict[str, list[str]] = {}
        self.required_matches: dict[str, set[str]] = {}
        self.evidence_reader = MailEvidenceReader()
        self.mail_evidence_reader = self.evidence_reader.read

    def _match_single_mail_key(self, kde_key, mail_key, original):
        if any(source in original for source in ("[Email instruction]", "[Email body words]")):
            body_match = instruction_match(kde_key, mail_key, original)
            if not body_match:
                return None
            if not core.has_known_file_extension(mail_key):
                return body_match
        return super()._match_single_mail_key(kde_key, mail_key, original) or ocr_match(kde_key, mail_key, original)

    def _select_page_mail_matches(self, rows, allowed_filenames):
        if not self.jobs:
            return super()._select_page_mail_matches(rows, allowed_filenames)
        selected = {}
        ambiguous = {}
        self.row_jobs = {}
        for job in self.jobs:
            account = next((account for account in self.configuration["accounts"] if account["username"] == job["account"]), None)
            side = account_side(account, self.configuration["accounts"].index(account)) if account else None
            candidates = [(index, row) for index, row in rows
                          if core.account_side_from_name(row.get("filename", "")) in {None, side}
                          and row_matches_job_date(row.get("filename", ""), row.get("file_time", ""), job)]
            precise = {key: original for key, original in job["lookup"].items()
                       if core.has_known_file_extension(key) or core.is_kde_reference_candidate(key)}
            matches, conflicts = super()._select_page_mail_matches(candidates, precise or job["lookup"])
            ambiguous.update(conflicts)
            for row_index, detail in matches.items():
                selected[row_index] = detail
                self.row_jobs.setdefault(row_index, set()).add(job["id"])
        return selected, ambiguous

    def _table_signature(self, page, allow_empty=False) -> str:
        try:
            return page.locator("tbody").first.evaluate("""(body, allowEmpty) => {
                if (body.closest('[aria-busy="true"]')) return '';
                const rows = Array.from(body.querySelectorAll('tr')).map(row =>
                    Array.from(row.querySelectorAll('td')).map(cell => (cell.innerText || '').trim()));
                if (!rows.length) return allowEmpty ? '[]' : '';
                if (rows.some(values => values.length < 4 || !values[1])) return '';
                return JSON.stringify(rows.map(values => values.slice(0, 4)));
            }""", arg=allow_empty, timeout=2000)
        except Exception:
            return ""

    def _wait_table_change(self, page, before: str, timeout_ms=None) -> bool:
        limit = self.settings.page_timeout_seconds
        if timeout_ms is not None:
            limit = min(limit, max(0, timeout_ms) / 1000)
        deadline = time.monotonic() + limit
        last = None
        stable_since = None
        while time.monotonic() < deadline and not self.stop_event.is_set():
            current = self._table_signature(page)
            now = time.monotonic()
            if current and current != before:
                if current != last:
                    last = current
                    stable_since = now
                elif now - stable_since >= 0.45:
                    return True
            else:
                last = None
                stable_since = None
            page.wait_for_timeout(100)
        if self.stop_event.is_set():
            return False
        raise RuntimeError("Portal table did not change and settle after navigation; refusing an incomplete catalogue.")

    def _click_page_button(self, page, selectors, timeout_ms) -> bool:
        if self.stop_event.is_set():
            return False
        for selector in selectors:
            button = page.locator(selector)
            if button.count() and button.first.is_enabled():
                before = self._table_signature(page, allow_empty=selectors == PAGE_PREVIOUS)
                if not before:
                    raise RuntimeError("Cannot read the current portal table; refusing unverified navigation.")
                button.first.click(timeout=timeout_ms)
                return self._wait_table_change(page, before, timeout_ms)
        return False

    def _next_page(self, page, timeout_ms):
        return self._click_page_button(page, PAGE_NEXT, timeout_ms)

    def _previous_page(self, page, timeout_ms):
        return self._click_page_button(page, PAGE_PREVIOUS, timeout_ms)

    def _has_next_page(self, page):
        for selector in PAGE_NEXT:
            button = page.locator(selector)
            if button.count() and button.first.is_enabled():
                return True
        return False

    def _table_rows(self, page):
        """Read every row in one browser call instead of one call per cell."""
        self.stage = 4
        try:
            data = page.locator("tbody tr").evaluate_all(
                "rows => rows.map(row => Array.from(row.querySelectorAll('td'))"
                ".map(cell => (cell.innerText || '').trim()))")
        except Exception:
            return super()._table_rows(page)
        rows = []
        for index, values in enumerate(data):
            if len(values) >= 4 and values[1]:
                rows.append((index, {"no": values[0], "filename": values[1],
                                     "file_time": values[2], "size_text": values[3]}))
        return rows

    def _download_visible_pages(self, page, account, timeout_ms, allowed_filenames=None):
        if not self.jobs:
            return super()._download_visible_pages(page, account, timeout_ms, allowed_filenames)
        result = {"downloaded": 0, "skipped": 0, "not_requested": 0, "errors": 0}
        catalogue = []
        positions = {}
        pages = 0
        # Pass 1: catalogue every page once, so a reference can never silently pick one of several files.
        for page_number in range(self.settings.max_pages):
            if self.stop_event.is_set():
                return result
            pages += 1
            for row_index, row in self._table_rows(page):
                identifier = len(catalogue)
                catalogue.append((identifier, row))
                positions[identifier] = (page_number, row_index)
            if not self._has_next_page(page):
                break
            if page_number + 1 == self.settings.max_pages:
                raise RuntimeError("Portal page limit reached before a complete match check; no files downloaded. Increase the page limit.")
            if not self._next_page(page, timeout_ms):
                if self.stop_event.is_set():
                    return result
                raise RuntimeError("Portal pagination changed during matching; no files downloaded.")
        selected, ambiguous = self._select_page_mail_matches(catalogue, allowed_filenames or {})
        matched_jobs = {identifier: set(self.row_jobs.get(identifier, set())) for identifier in selected}
        for key, count in ambiguous.items():
            self.reporter.emit(4, "warning", f"Reference matches {count} different files across the portal; review required: {key}",
                               account.label, persist=True)
        if not selected:
            return result
        # Deliver on the way back; skip full row reads on pages with no requested files.
        wanted = {positions[identifier][0] for identifier in selected}
        lowest = min(wanted)
        rows_by_id = dict(catalogue)
        for page_number in range(pages - 1, lowest - 1, -1):
            if self.stop_event.is_set():
                break
            if page_number in wanted:
                for identifier, detail in selected.items():
                    if positions[identifier][0] != page_number:
                        continue
                    if self.stop_event.is_set():
                        return result
                    # A completed download can remove or reorder other rows.
                    current_rows = self._table_rows(page)
                    expected = rows_by_id[identifier]
                    matches = [(index, row) for index, row in current_rows
                               if row.get("filename") == expected.get("filename")
                               and row.get("file_time", "") == expected.get("file_time", "")
                               and row.get("size_text", "") == expected.get("size_text", "")]
                    if len(matches) != 1:
                        raise RuntimeError("Portal list changed after matching; refusing to click a different file.")
                    row_index, row = matches[0]
                    self.row_jobs = {row_index: matched_jobs[identifier]}
                    self.reporter.emit(4, "stage_complete", "Matched email evidence, account and business date", account.label, row["filename"])
                    status = self.handle_file(page, row_index, row, account, timeout_ms)
                    result["downloaded" if status == "complete" else "skipped" if status == "skipped" else "errors"] += 1
                    if self.stop_event.wait(self.settings.download_delay_seconds):
                        return result
            if page_number > lowest and not self._previous_page(page, timeout_ms):
                if self.stop_event.is_set():
                    return result
                raise RuntimeError("Portal pagination changed before delivery finished.")
        return result

    def download_to_cache(self, page, row_index, timeout_ms):
        cache = settings_home() / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (uuid.uuid4().hex + ".download")
        return self._click_download_row(page, row_index, target, timeout_ms)

    def job_outcomes(self) -> dict[str, dict[str, str]]:
        outcomes = {}
        for job in self.jobs:
            statuses = self.job_statuses.get(job["id"], [])
            required = {key for key in job["lookup"] if core.has_known_file_extension(key)}
            missing = required - self.required_matches.get(job["id"], set())
            if missing:
                kind, reason = "missing", "Requested files were not found: " + ", ".join(sorted(missing))
            elif not statuses:
                kind, reason = "missing", "No unique KDE file matched the email reference, account and date."
            elif "error" in statuses:
                kind, reason = "download_failed", "Download or verification failed; see the file's History entry."
            elif "copy_pending" in statuses:
                kind, reason = "copy_pending", "Validated source retained. Use Tools > Repair pending saves; no redownload required."
            else:
                kind, reason = "complete", "Requested files verified at all selected destinations."
            outcomes[job["id"]] = {"kind": kind, "reason": reason}
        return outcomes

    def protocol_message(self, message: str) -> None:
        # Preserve technical evidence on actual failures, suppress filename chatter.
        lower = message.casefold()
        if lower.startswith("mail watch: unread filter fallback|"):
            _prefix, folder, diagnostic = message.split("|", 2)
            if folder.casefold() not in self.reported_mail_fallbacks:
                self.reported_mail_fallbacks.add(folder.casefold())
                self.reporter.emit(2, "notice",
                                   f"Outlook filter unavailable in {folder}; using bounded per-item checks. {diagnostic}")
            return
        if lower.startswith("mail watch: skip folder "):
            self.mail_failures.append("Cannot read email folder: " + message)
        elif "mail watch:" in lower and any(text in lower for text in (
            "failed", "ไม่สำเร็จ", "ไม่พบ mailbox", "จึงสแกน outlook ไม่ได้",
            "เปิด outlook ไม่ได้", "เริ่ม outlook com ไม่ได้", "outlook com error",
        )):
            self.mail_failures.append(message)
        if any(text in lower for text in ("signout", "logout", "log out")):
            if any(text in lower for text in ("error", "ไม่สำเร็จ", "ยังอยู่ที่")):
                self.logout_failures.append(message)
        if "login attempt" in lower or "user ยังใช้งานอยู่" in lower:
            self.reporter.emit(3, "running", "KDE user is already in use." if "user ยังใช้งานอยู่" in lower else message, self.account)
        if "mail key ที่กำกวม" in message:
            self.reporter.emit(4, "warning", "Several KDE files match this reference; no ambiguous file was downloaded.", self.account, persist=True)

    def _login_with_retry(self, page: Any, account: core.Account, timeout_ms: int) -> None:
        self.stage = 3
        self.session_attempted = True
        self.reporter.emit(3, "running", "Logging in to KDE", account.label)
        super()._login_with_retry(page, account, timeout_ms)
        self.reporter.emit(3, "stage_complete", "Login succeeded", account.label)

    def _open_download_page(self, page: Any, timeout_ms: int) -> None:
        self.stage = 4
        self.reporter.emit(4, "running", "Matching portal files against email evidence", self.account)
        super()._open_download_page(page, timeout_ms)

    def _post_auth(self, path: str, payload=None, referer=None):
        response = super()._post_auth(path, payload, referer)
        response.raise_for_status()
        return response

    def _bundled_headless_shell_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent / "_internal/chromium_headless_shell/headless_shell.exe"
        return Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright/chromium_headless_shell-1169/chrome-win/headless_shell.exe"

    def _browser_launch_kwargs(self) -> dict[str, Any]:
        result = super()._browser_launch_kwargs()
        if not self.settings.headless:
            result["args"] = [
                argument for argument in result["args"]
                if not argument.startswith(("--window-position", "--window-size"))
            ]
        return result

    def handle_file(self, page: Any, row_index: int, row: dict[str, Any],
                    account: core.Account, timeout_ms: int) -> str:
        self.stage = 5
        configuration = next(item for item in self.configuration["accounts"] if item["username"] == account.username)
        folders = selected_folders(self.configuration, configuration)
        recovery = [Path(self.configuration["original_dir"]),
                    Path(self.configuration["new_dir"])]
        status = self.delivery.deliver(
            account.username, core.safe_filename(row["filename"]), folders,
            lambda _target: self.download_to_cache(page, row_index, timeout_ms),
            recovery,
        )
        key = self.delivery.history.file_lock(row["filename"])
        with key, self.delivery.history.lock:
            from .storage import record_key
            identifier = record_key(account.username, row["filename"])
            record = self.delivery.history.data["files"].get(identifier)
            if record is not None:
                record["mail_jobs"] = sorted(set(record.get("mail_jobs", [])) | self.row_jobs.get(row_index, set()))
                self.delivery.history.set_file(identifier, record)
        for job_id in self.row_jobs.get(row_index, set()):
            self.job_statuses.setdefault(job_id, []).append(status)
            job = next(job for job in self.jobs if job["id"] == job_id)
            normalized = core.normalize_filename_for_match(row["filename"])
            for key, original in job["lookup"].items():
                if core.has_known_file_extension(key) and self._match_single_mail_key(normalized, key, original):
                    self.required_matches.setdefault(job_id, set()).add(key)
        return status

    def process_account(self, account: core.Account) -> dict[str, int]:
        self.account = account.label
        self.stage = 3
        self.logout_failures = []
        self.session_attempted = False
        self.reporter.emit(3, "running", "Preparing an isolated account session", self.account)
        try:
            result = super().process_account(account)
            self.reporter.emit(4, "stage_complete",
                               f"Saved {result.get('downloaded', 0)}, already saved {result.get('skipped', 0)}, "
                               f"unrequested {result.get('not_requested', 0)}, failed {result.get('errors', 0)}", self.account)
            return result
        finally:
            if self.logout_failures:
                self.reporter.emit(8, "error", "Logout requires attention: " + " | ".join(self.logout_failures),
                                   self.account, persist=True, count=True)
            elif self.session_attempted:
                # APIs attempted by the preserved engine; do not claim server verification.
                self.reporter.emit(8, "stage_complete", "Logout and session cleanup completed",
                                   self.account)
            else:
                self.reporter.emit(8, "stage_complete", "No KDE session was opened",
                                   self.account)


def make_engine_settings(settings: dict[str, Any], state_file: Path) -> core.Settings:
    raw = copy.deepcopy(settings)
    raw["state_file"] = state_file
    raw["download_new_only"] = True
    # Compatibility fields of the portal library; no scheduled runner remains.
    raw["loop_wait_seconds"] = 0
    raw["busy_wait_seconds"] = 0
    raw["chrome_path"] = settings["chrome_path"] or detect_chrome()
    mail = raw["mail_watch"]
    mail["filename_regex"] = mail["filename_regex"] or core.DEFAULT_MAIL_FILENAME_REGEX
    raw["mail_watch"] = core.MailWatchSettings(**mail)
    raw["accounts"] = [
        core.Account(account["label"], account["username"], account["password"],
                     selected_folders(settings, account)[0], account["enabled"])
        for account in settings["accounts"]
    ]
    return core.Settings(**{field.name: raw[field.name] for field in dataclasses.fields(core.Settings)})


def run_cycle(settings: dict[str, Any], stop_event: threading.Event,
              callback: Callable[[dict[str, Any]], None], scan_only: bool = False,
              check_only: bool = False, retry_only: bool = False,
              watch: bool = False, requeue_failed: bool = False,
              requests: queue.Queue | None = None) -> dict[str, int]:
    # Fail before any portal/browser operation when the user has not configured the machine.
    validate_settings(settings, require_credentials=not (scan_only or check_only or retry_only))
    log_folder = Path(settings["log_dir"])
    check_writable(log_folder)
    with WorkerLock(log_folder):
        history = History(log_folder)
        reporter = Reporter(history, callback)
        reporter.secrets = [account["password"] for account in settings["accounts"] if account["password"]]
        reporter.emit(1, "running", "Checking this Windows user's environment")
        folders = list(dict.fromkeys(
            path for account in settings["accounts"] if account["enabled"]
            for path in selected_folders(settings, account)
        ))
        if not scan_only:
            for folder in folders:
                check_destination(folder)
        reason = "Log write check passed"
        if not scan_only:
            reason += "; destinations readable. No test files created; save access is checked during real delivery."
        reporter.emit(1, "stage_complete", reason)
        delivery = Delivery(history, reporter)
        with tempfile.TemporaryDirectory(prefix="kde-v3-") as temporary:
            engine_settings = make_engine_settings(settings, Path(temporary) / "engine-state.json")
            engine = StructuredDownloader(engine_settings, reporter, delivery, settings, stop_event)
            if check_only:
                browser_options = engine._browser_launch_kwargs()
                browser = browser_options.get("executable_path", "")
                if not browser or not Path(browser).is_file():
                    raise FileNotFoundError("Browser not found. Restore the full portable bundle or configure Chrome/Edge.")
                reporter.emit(1, "stage_complete", f"Browser ready: {browser}")
                return reporter.counts
            # Pending deliveries are repaired without requiring the original mail to remain unread.
            for record in list(history.data["files"].values()):
                if scan_only:
                    break
                if stop_event.is_set():
                    break
                if not record.get("pending"):
                    continue
                account = next((item for item in settings["accounts"]
                                if item["enabled"] and item["username"] == record.get("account")), None)
                if account is None:
                    continue

                def cannot_redownload(_target: Path) -> Path:
                    raise FileNotFoundError("Validated source is unavailable; a new mail/download request is required.")

                delivery.deliver(
                    account["username"], record["filename"], selected_folders(settings, account),
                    cannot_redownload,
                    [Path(settings["original_dir"]), Path(settings["new_dir"])],
                )
            queue_state = MailQueue(history, reporter, settings, today())
            queue_state.refresh_saved_jobs()
            if requests is not None:
                reporter.callback({"kind": "queue", "jobs": queue_state.snapshot()})
            if retry_only or stop_event.is_set():
                reporter.emit(8, "summary", "Pending-save repair finished")
                return reporter.counts
            if scan_only:
                reporter.emit(2, "running", "Reading the local Outlook mailbox")
                try:
                    engine.mail_filename_lookup = engine.scan_mail_filenames()
                except Exception as error:
                    reporter.emit(2, "error", f"{type(error).__name__}: {error}", persist=True, count=True)
                    return reporter.counts
                if engine.mail_failures:
                    reporter.emit(2, "error", " | ".join(engine.mail_failures), persist=True, count=True)
                    return reporter.counts
                reporter.emit(2, "stage_complete",
                              f"Found {len(engine.mail_filename_lookup)} matching references")
                reporter.emit(8, "summary", "Email scan finished; KDE was not opened")
                return reporter.counts
            if requeue_failed:
                MailQueue(history, reporter, settings, today()).requeue_failed(time.time())
            run_mail_monitor(settings, stop_event, reporter, history, Path(temporary), watch, requests)
        history.save()
        return reporter.counts


def run_account_batch(settings: dict[str, Any], jobs: list[dict[str, Any]],
                      stop_event: threading.Event, reporter: Reporter,
                      history: History, temporary: Path) -> dict[str, dict[str, str]]:
    # Every worker owns its Playwright runtime, browser and isolated cookies.
    engine_settings = make_engine_settings(settings, temporary / f"engine-{jobs[0]['id']}.json")
    engine = StructuredDownloader(engine_settings, reporter, Delivery(history, reporter), settings, stop_event)
    engine.jobs = jobs
    engine.mail_filename_lookup = {key: original for job in jobs for key, original in job["lookup"].items()}
    account = next(account for account in engine_settings.accounts if account.username == jobs[0]["account"])
    reporter.emit(3, "running", f"Opening an isolated session; attempt {max(job['attempts'] for job in jobs)}/2", account.label)
    try:
        engine.process_account(account)
        if engine.logout_failures:
            raise RuntimeError("Logout failed: " + " | ".join(engine.logout_failures))
        return engine.job_outcomes()
    except Exception as error:
        kind = "login_failed" if engine.stage == 3 or engine.logout_failures else "download_failed"
        reason = f"{STEPS[engine.stage]}: {type(error).__name__}: {error}"
        reporter.emit(engine.stage, "error", reason, account.label, persist=True, count=True)
        return {job["id"]: {"kind": kind, "reason": reason} for job in jobs}


def run_mail_monitor(settings: dict[str, Any], stop_event: threading.Event,
                     reporter: Reporter, history: History, temporary: Path,
                     watch: bool, requests: queue.Queue | None = None) -> None:
    mail_queue = MailQueue(history, reporter, settings, today())
    mail_queue.recover_interrupted(time.time())
    scanner = StructuredDownloader(make_engine_settings(settings, temporary / "mail-scan.json"),
                                   reporter, Delivery(history, reporter), settings, stop_event)
    active: dict[str, Any] = {}
    next_scan = 0.0
    scanned_once = False
    last_summary = ""
    last_snapshot = ""
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="KDE-account") as executor:
        while not stop_event.is_set():
            now = time.time()
            mail_queue.today = today()
            for account, future in list(active.items()):
                if future.done():
                    mail_queue.finish(future.result(), time.time(), stop_event.is_set())
                    del active[account]
            if requests is not None:
                for _ in range(20):
                    try:
                        request = requests.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        if request["kind"] == "image":
                            message = scanner.evidence_reader.screenshot(Path(request["path"]), request["side"])
                            mail_queue.ingest([message], time.time())
                        elif request["kind"] == "review":
                            mail_queue.resolve(request["id"], request["account"], request["reference"], time.time())
                        elif request["kind"] == "retry":
                            mail_queue.requeue_failed(time.time())
                    except Exception as error:
                        reporter.emit(2, "error", f"Request failed: {type(error).__name__}: {error}", persist=True)
            if now >= next_scan and (watch or not scanned_once):
                scanner.mail_messages = []
                scanner.mail_failures = []
                try:
                    scanner.scan_mail_filenames()
                    if scanner.mail_failures:
                        raise RuntimeError(" | ".join(scanner.mail_failures))
                    mail_queue.ingest(scanner.mail_messages, time.time())
                    with history.lock:
                        previous_scan = history.data["outcomes"].get("stage::2", {})
                        if previous_scan.get("signature", [None, None])[1] in {"error", "warning"}:
                            reporter.emit(2, "stage_complete",
                                          f"Outlook recovered; found {len(scanner.mail_messages)} relevant messages")
                except Exception as error:
                    reporter.emit(2, "error", f"Outlook: {type(error).__name__}: {error}", persist=True)
                    if not watch:
                        break
                scanned_once = True
                next_scan = time.time() + settings["mail_poll_seconds"]
            for account, jobs in mail_queue.claim_ready(time.time(), set(active)).items():
                if stop_event.is_set():
                    mail_queue.finish({job["id"]: {"kind": "missing", "reason": "Stopped before opening a session"} for job in jobs}, time.time(), True)
                    continue
                active[account] = executor.submit(run_account_batch, settings, jobs, stop_event,
                                                  reporter, history, temporary)
            snapshot = mail_queue.snapshot()
            signature = repr(snapshot)
            if signature != last_snapshot and requests is not None:
                reporter.callback({"kind": "queue", "jobs": snapshot})
                last_snapshot = signature
            with history.lock:
                enabled = {account["username"] for account in settings["accounts"] if account["enabled"]}
                waiting = sum(job["status"] == "waiting" and job["account"] in enabled for job in mail_queue.jobs.values())
            summary = f"Monitoring today's mail · Queued {waiting} · Active accounts {len(active)}/2"
            if summary != last_summary:
                reporter.emit(2, "summary", summary)
                last_summary = summary
            if not watch and scanned_once and not active and not mail_queue.has_pending():
                break
            stop_event.wait(0.5)
        # Logout finishes in each worker before the monitor releases the shared lock.
        for future in active.values():
            mail_queue.finish(future.result(), time.time(), stop_event.is_set())
    reporter.emit(8, "summary", "Stopped; account sessions closed" if stop_event.is_set() else "Email queue finished")
