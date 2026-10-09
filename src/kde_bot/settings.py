"""Per-user settings; credentials never travel with the shared executable."""

from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
from typing import Any


def settings_home() -> Path:
    override = os.environ.get("KDE_V3_HOME")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KDE Bot Download V3"


def default_settings() -> dict[str, Any]:
    return {
        "version": 3,
        "storage_mode": "both",
        "original_dir": r"\\10.0.0.243\pgp-data$",
        "new_dir": r"\\10.0.0.97\Z Bot KDE",
        "log_dir": r"\\10.0.0.97\Z Log\Log Bot KDE",
        "portal_url": "https://www.krungsrifileserver.com/kde-portal",
        "host_url": "https://www.krungsrifileserver.com",
        "auth_api_url": "https://www.krungsrifileserver.com/redirect/kde-auth-api/authn",
        "chrome_path": "",
        "headless": True,
        "search_days": 1,
        "max_pages": 50,
        "download_delay_seconds": 5,
        "busy_wait_seconds": 900,
        "loop_wait_seconds": 1200,
        "page_timeout_seconds": 60,
        "accounts": [
            {"label": "01 Pre", "username": "", "password": "", "enabled": True, "original_dir": ""},
            {"label": "02 Post", "username": "", "password": "", "enabled": True, "original_dir": ""},
        ],
        "mail_watch": {
            "enabled": True,
            "today_only": False,
            "unread_only": True,
            "include_subject": True,
            "include_body": True,
            "max_messages_per_folder": 500,
            "max_body_chars": 20000,
            "match_mode": "contains",
            "filename_regex": "",
            "mailbox_filter": "data@tradeconnection.co.th",
        },
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def decrypt_credentials(value: Any, notices: list[str], location: str = "") -> Any:
    if isinstance(value, dict) and set(value) == {"$dpapi"}:
        try:
            import win32crypt
            return win32crypt.CryptUnprotectData(
                base64.b64decode(value["$dpapi"]), None, None, None, 0
            )[1].decode("utf-8")
        except Exception:
            notices.append(f"{location}: ต้องกรอกรหัสผ่านใหม่สำหรับ Windows user เครื่องนี้")
            return ""
    if isinstance(value, dict):
        return {
            key: decrypt_credentials(item, notices, f"{location}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            decrypt_credentials(item, notices, f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def encrypt_credentials(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: encrypt_credentials(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [encrypt_credentials(item, key) for item in value]
    if key == "password" and isinstance(value, str) and value:
        import win32crypt
        protected = win32crypt.CryptProtectData(value.encode("utf-8"), "KDE V3", None, None, None, 0)
        return {"$dpapi": base64.b64encode(protected).decode("ascii")}
    return value


def normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    result = default_settings()
    for key in result:
        if key in raw and key not in {"accounts", "mail_watch"}:
            result[key] = raw[key]
    result["mail_watch"].update({
        key: value for key, value in raw.get("mail_watch", {}).items()
        if key in result["mail_watch"]
    })
    result["mail_watch"]["unread_only"] = True
    result["mail_watch"]["include_subject"] = True
    result["version"] = 3
    if "accounts" in raw:
        if not isinstance(raw["accounts"], list) or len(raw["accounts"]) > 2:
            raise ValueError("รองรับบัญชี KDE Pre/Post ไม่เกิน 2 บัญชี")
        accounts = []
        for index, item in enumerate(raw["accounts"]):
            account = copy.deepcopy(result["accounts"][index])
            account.update({key: value for key, value in item.items() if key in account})
            accounts.append(account)
        result["accounts"] = accounts
    return result


def load_settings(path: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    path = path or settings_home() / "settings.json"
    notices: list[str] = []
    if not path.exists():
        return default_settings(), ["เครื่องนี้ยังไม่มีการตั้งค่า กรุณากรอกบัญชีในแท็บตั้งค่า"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return normalize_settings(decrypt_credentials(raw, notices)), notices
    except Exception as error:
        return default_settings(), [f"อ่านการตั้งค่าไม่ได้: {type(error).__name__} กรุณาตรวจไฟล์ตั้งค่า"]


def save_settings(settings: dict[str, Any], path: Path | None = None) -> None:
    path = path or settings_home() / "settings.json"
    normalized = normalize_settings(settings)
    protected = encrypt_credentials(normalized)
    if path.exists():
        import shutil
        shutil.copy2(path, path.with_suffix(".json.bak"))
    atomic_json(path, protected)


def import_settings(path: Path) -> tuple[dict[str, Any], list[str]]:
    notices: list[str] = []
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if "profiles" in raw:
        raw = raw["profiles"]["kde"]
    raw = decrypt_credentials(raw, notices)
    if raw.get("version") == 3 and not any(
        "download_dir" in item for item in raw.get("accounts", [])
    ):
        return normalize_settings(raw), notices
    result = normalize_settings(raw)
    for source, account in zip(raw.get("accounts", []), result["accounts"]):
        original = str(source.get("download_dir", "")).strip()
        if original and original.rstrip("\\/") != result["original_dir"].rstrip("\\/"):
            account["original_dir"] = original
    notices.append("นำเข้าบัญชีและกฎจับคู่แล้ว ใช้ปลายทางและ Log ของ V3 กรุณาตรวจค่าก่อนบันทึก")
    return result, notices


def validate_settings(settings: dict[str, Any], require_credentials: bool = True) -> None:
    if settings["storage_mode"] not in {"both", "original", "new"}:
        raise ValueError("กรุณาเลือกวิธีเก็บไฟล์")
    for key in ("loop_wait_seconds", "page_timeout_seconds", "max_pages", "search_days"):
        if not isinstance(settings[key], int) or settings[key] < 1:
            raise ValueError(f"{key}: ต้องเป็นจำนวนเต็มมากกว่า 0")
    for key in ("download_delay_seconds", "busy_wait_seconds"):
        if not isinstance(settings[key], int) or settings[key] < 0:
            raise ValueError(f"{key}: ต้องเป็นจำนวนเต็มตั้งแต่ 0")
    for key in ("log_dir", "original_dir", "new_dir"):
        if not str(settings[key]).strip() or not Path(settings[key]).is_absolute():
            raise ValueError(f"{key}: กรุณาระบุโฟลเดอร์เต็ม")
    enabled = [account for account in settings["accounts"] if account["enabled"]]
    if require_credentials and not enabled:
        raise ValueError("กรุณาเปิดใช้งานบัญชี KDE อย่างน้อย 1 บัญชี")
    seen = set()
    for account in enabled:
        username = str(account["username"]).strip()
        if require_credentials and (not username or not account["password"]):
            raise ValueError(f"{account['label']}: กรุณากรอกชื่อผู้ใช้และรหัสผ่าน KDE ของเครื่องนี้")
        if username and username.casefold() in seen:
            raise ValueError("บัญชี Pre/Post ต้องไม่ใช้ชื่อผู้ใช้ซ้ำกัน")
        seen.add(username.casefold())
        override = str(account.get("original_dir", "")).strip()
        if override and not Path(override).is_absolute():
            raise ValueError(f"{account['label']}: โฟลเดอร์เดิมต้องเป็นตำแหน่งเต็ม")
    for key in ("portal_url", "host_url", "auth_api_url"):
        if not str(settings[key]).startswith("https://"):
            raise ValueError(f"{key}: ต้องใช้ HTTPS")
    mail = settings["mail_watch"]
    for key in ("max_messages_per_folder", "max_body_chars"):
        if not isinstance(mail[key], int) or mail[key] < 1:
            raise ValueError(f"{key}: ต้องเป็นจำนวนเต็มมากกว่า 0")
    if mail["enabled"] and not str(mail["mailbox_filter"]).strip():
        raise ValueError("กรุณาระบุ Outlook mailbox")
