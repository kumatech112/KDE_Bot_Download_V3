"""Run only KDE, preserving portal matching and mandatory logout semantics."""

from __future__ import annotations

import copy
import dataclasses
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from . import legacy_core as core
from .settings import validate_settings
from .storage import Delivery, History, Reporter, WorkerLock, check_writable


STEPS = {
    1: "ตรวจการตั้งค่าและสิทธิ์",
    2: "ตรวจอีเมล Outlook",
    3: "เข้าสู่ระบบ KDE",
    4: "ค้นหาและจับคู่ไฟล์",
    5: "ตรวจประวัติและไฟล์ปลายทาง",
    6: "ดาวน์โหลดไฟล์",
    7: "คัดลอกและตรวจสอบปลายทาง",
    8: "ออกจากระบบและสรุปผล",
}


def selected_folders(settings: dict[str, Any], account: dict[str, Any]) -> list[Path]:
    original = Path(account.get("original_dir") or settings["original_dir"])
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
        self.session_attempted = False
        self.file_handler = self.handle_file

    def protocol_message(self, message: str) -> None:
        # Preserve technical evidence on actual failures, suppress filename chatter.
        lower = message.casefold()
        if "mail watch:" in lower and any(text in lower for text in (
            "failed", "ไม่สำเร็จ", "ไม่พบ mailbox", "จึงสแกน outlook ไม่ได้",
            "เปิด outlook ไม่ได้", "เริ่ม outlook com ไม่ได้", "outlook com error",
        )):
            self.mail_failures.append(message)
        if any(text in lower for text in ("signout", "logout", "log out")):
            if any(text in lower for text in ("error", "ไม่สำเร็จ", "ยังอยู่ที่")):
                self.logout_failures.append(message)
        if "login attempt" in lower or "user ยังใช้งานอยู่" in lower:
            self.reporter.emit(3, "running", message, self.account)
        if "mail key ที่กำกวม" in message:
            self.reporter.emit(4, "warning", message, self.account, persist=True)

    def _login_with_retry(self, page: Any, account: core.Account, timeout_ms: int) -> None:
        self.stage = 3
        self.session_attempted = True
        self.reporter.emit(3, "running", "กำลังเข้าสู่ระบบ KDE", account.label)
        super()._login_with_retry(page, account, timeout_ms)
        self.reporter.emit(3, "stage_complete", "เข้าสู่ระบบสำเร็จ", account.label)

    def _open_download_page(self, page: Any, timeout_ms: int) -> None:
        self.stage = 4
        self.reporter.emit(4, "running", "เปิดรายการไฟล์และจับคู่กับอีเมล", self.account)
        super()._open_download_page(page, timeout_ms)

    def _post_auth(self, path: str, payload=None, referer=None):
        response = super()._post_auth(path, payload, referer)
        response.raise_for_status()
        return response

    def _table_rows(self, page):
        self.stage = 4
        return super()._table_rows(page)

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
        recovery = [Path(configuration.get("original_dir") or self.configuration["original_dir"]),
                    Path(self.configuration["new_dir"])]
        return self.delivery.deliver(
            account.username, core.safe_filename(row["filename"]), folders,
            lambda target: self._click_download_row(page, row_index, target, timeout_ms),
            recovery,
        )

    def process_account(self, account: core.Account) -> dict[str, int]:
        self.account = account.label
        self.stage = 3
        self.logout_failures = []
        self.session_attempted = False
        self.reporter.emit(3, "running", "เตรียม Browser สำหรับบัญชี", self.account)
        try:
            result = super().process_account(account)
            self.reporter.emit(4, "stage_complete",
                               f"ตรวจครบ: ดาวน์โหลด/คัดลอก {result.get('downloaded', 0)}, "
                               f"มีครบแล้ว {result.get('skipped', 0)}, "
                               f"ไม่ตรงอีเมล {result.get('not_requested', 0)}, "
                               f"ผิดพลาด {result.get('errors', 0)}", self.account)
            return result
        finally:
            if self.logout_failures:
                self.reporter.emit(8, "error", "ตรวจการออกจากระบบ: " + " | ".join(self.logout_failures),
                                   self.account, persist=True, count=True)
            elif self.session_attempted:
                # APIs attempted by the preserved engine; do not claim server verification.
                self.reporter.emit(8, "stage_complete", "จบขั้นตอนปิด Session; ไม่พบข้อผิดพลาดที่ระบบรายงาน",
                                   self.account)
            else:
                self.reporter.emit(8, "stage_complete", "ไม่ได้เริ่ม Session KDE จึงไม่มี Session ให้ปิด",
                                   self.account)


def make_engine_settings(settings: dict[str, Any], state_file: Path) -> core.Settings:
    raw = copy.deepcopy(settings)
    raw["state_file"] = state_file
    raw["download_new_only"] = True
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
              check_only: bool = False, retry_only: bool = False) -> dict[str, int]:
    # Fail before any portal/browser operation when the user has not configured the machine.
    validate_settings(settings, require_credentials=not (scan_only or check_only or retry_only))
    log_folder = Path(settings["log_dir"])
    check_writable(log_folder)
    with WorkerLock(log_folder):
        history = History(log_folder)
        reporter = Reporter(history, callback)
        reporter.secrets = [account["password"] for account in settings["accounts"] if account["password"]]
        reporter.emit(1, "running", "ตรวจสิทธิ์ด้วย Windows user ที่ใช้งานเครื่องนี้")
        folders = list(dict.fromkeys(
            path for account in settings["accounts"] if account["enabled"]
            for path in selected_folders(settings, account)
        ))
        if not scan_only:
            for folder in folders:
                check_writable(folder)
        reporter.emit(1, "stage_complete", "ตรวจสิทธิ์ Log และปลายทางที่เลือกผ่าน")
        delivery = Delivery(history, reporter)
        with tempfile.TemporaryDirectory(prefix="kde-v3-") as temporary:
            engine_settings = make_engine_settings(settings, Path(temporary) / "engine-state.json")
            engine = StructuredDownloader(engine_settings, reporter, delivery, settings, stop_event)
            if check_only:
                browser_options = engine._browser_launch_kwargs()
                browser = browser_options.get("executable_path", "")
                if not browser or not Path(browser).is_file():
                    raise FileNotFoundError("ไม่พบ Browser กรุณาติดตั้ง Chrome หรือกำหนดตำแหน่ง Browser")
                reporter.emit(1, "stage_complete", f"Browser พร้อม: {browser}")
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
                    raise FileNotFoundError("ไม่พบต้นฉบับสำหรับคัดลอก ต้องตรวจอีเมล/ดาวน์โหลดใหม่")

                delivery.deliver(
                    account["username"], record["filename"], selected_folders(settings, account),
                    cannot_redownload,
                    [Path(account.get("original_dir") or settings["original_dir"]), Path(settings["new_dir"])],
                )
            if retry_only or stop_event.is_set():
                reporter.emit(8, "summary", "จบการลองคัดลอกไฟล์ที่ค้าง")
                return reporter.counts
            if settings["mail_watch"]["enabled"] or scan_only:
                reporter.emit(2, "running", "กำลังตรวจ Outlook mailbox บนเครื่องนี้")
                try:
                    engine.mail_filename_lookup = engine.scan_mail_filenames()
                except Exception as error:
                    reporter.emit(2, "error", f"{type(error).__name__}: {error}", persist=True, count=True)
                    return reporter.counts
                if engine.mail_failures:
                    reporter.emit(2, "error", " | ".join(engine.mail_failures), persist=True, count=True)
                    return reporter.counts
                reporter.emit(2, "stage_complete",
                              f"พบชื่อ/ข้อความสำหรับจับคู่ {len(engine.mail_filename_lookup)} รายการ")
                if scan_only or not engine.mail_filename_lookup:
                    reporter.emit(8, "summary", "จบรอบตรวจอีเมล ไม่มีงานดาวน์โหลด" if not engine.mail_filename_lookup else "จบการตรวจอีเมล")
                    return reporter.counts
            else:
                reporter.emit(2, "stage_complete", "ปิดการจับคู่ Outlook ตามการตั้งค่า")
            for account in engine_settings.accounts:
                if stop_event.is_set():
                    break
                if not account.enabled:
                    continue
                try:
                    engine.process_account(account)
                except Exception as error:
                    reporter.emit(engine.stage, "error", f"{type(error).__name__}: {error}",
                                  account.label, persist=True, count=True)
            reporter.emit(8, "summary", "หยุดตามคำสั่ง" if stop_event.is_set() else "จบรอบการทำงาน KDE")
        history.save()
        return reporter.counts
