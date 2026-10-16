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
        "mail_poll_seconds": 15,
        "mail_delay_seconds": 70,
        "login_retry_seconds": 60,
        "max_session_attempts": 2,
        "page_timeout_seconds": 60,
        "accounts": [
            {"label": "01 Pre", "username": "", "password": "", "enabled": True},
            {"label": "02 Post", "username": "", "password": "", "enabled": True},
        ],
        "mail_watch": {
            "enabled": True,
            "today_only": True,
            "unread_only": False,
            "include_subject": True,
            "include_body": True,
            "max_messages_per_folder": 500,
            "max_body_chars": 20000,
            "match_mode": "contains",
            "filename_regex": "",
            "mailbox_filter": "data@tradeconnection.co.th",
            "folder_path": "",
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
            notices.append(f"{location}: Re-enter the password for this Windows user.")
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
    result["mail_watch"]["unread_only"] = False
    result["mail_watch"]["today_only"] = True
    result["mail_watch"]["include_subject"] = True
    # Mail is mandatory in this release; old timers never start portal sessions.
    result["mail_watch"]["enabled"] = True
    result["mail_delay_seconds"] = 70
    result["login_retry_seconds"] = 60
    result["max_session_attempts"] = 2
    result["version"] = 3
    if "accounts" in raw:
        if not isinstance(raw["accounts"], list) or len(raw["accounts"]) > 2:
            raise ValueError("Configure at most two KDE accounts: Pre and Post.")
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
        return default_settings(), ["Enter your account credentials in Settings."]
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return normalize_settings(decrypt_credentials(raw, notices)), notices
    except Exception as error:
        return default_settings(), [f"Cannot read settings: {type(error).__name__}. Check the local settings file."]


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
    notices.append("KDE settings imported. Both accounts use the shared destination roots. Check before saving.")
    return result, notices


def validate_settings(settings: dict[str, Any], require_credentials: bool = True) -> None:
    if settings["storage_mode"] not in {"both", "original", "new"}:
        raise ValueError("Choose a storage mode.")
    for key in ("page_timeout_seconds", "max_pages", "search_days"):
        if not isinstance(settings[key], int) or settings[key] < 1:
            raise ValueError(f"{key}: enter a positive whole number.")
    for key in ("download_delay_seconds",):
        if not isinstance(settings[key], int) or settings[key] < 0:
            raise ValueError(f"{key}: enter a whole number of zero or greater.")
    for key in ("log_dir", "original_dir", "new_dir"):
        if not str(settings[key]).strip() or not Path(settings[key]).is_absolute():
            raise ValueError(f"{key}: enter an absolute folder path.")
    for key in ("original_dir", "new_dir"):
        if Path(settings["log_dir"]).is_relative_to(Path(settings[key])):
            raise ValueError("Choose a separate Log folder outside the download destinations.")
    enabled = [account for account in settings["accounts"] if account["enabled"]]
    if require_credentials and not enabled:
        raise ValueError("Enable at least one KDE account.")
    seen = set()
    for account in enabled:
        username = str(account["username"]).strip()
        if require_credentials and (not username or not account["password"]):
            raise ValueError(f"{account['label']}: enter the KDE username and password for this machine.")
        if username and username.casefold() in seen:
            raise ValueError("Pre and Post must have different usernames.")
        seen.add(username.casefold())
    for key in ("portal_url", "host_url", "auth_api_url"):
        if not str(settings[key]).startswith("https://"):
            raise ValueError(f"{key}: HTTPS is required.")
    mail = settings["mail_watch"]
    if not mail["enabled"]:
        raise ValueError("Email-triggered monitoring must remain enabled.")
    if settings["mail_delay_seconds"] != 70 or settings["login_retry_seconds"] != 60 or settings["max_session_attempts"] != 2:
        raise ValueError("Policy: a fixed 70-second arrival window and two attempts per account, with one 60-second retry.")
    if not isinstance(mail.get("folder_path", ""), str):
        raise ValueError("Outlook folder path must be text relative to the data mailbox.")
    if not mail["today_only"] or mail["unread_only"]:
        raise ValueError("Monitor today's mail, including read messages; processed message IDs prevent duplicates.")
    if not isinstance(settings["mail_poll_seconds"], int) or settings["mail_poll_seconds"] < 5:
        raise ValueError("Outlook polling must be at least five seconds.")
    for key in ("max_messages_per_folder", "max_body_chars"):
        if not isinstance(mail[key], int) or mail[key] < 1:
            raise ValueError(f"{key}: enter a positive whole number.")
    if mail["enabled"] and not str(mail["mailbox_filter"]).strip():
        raise ValueError("Enter the Outlook mailbox to monitor.")
