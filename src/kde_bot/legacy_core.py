from __future__ import annotations

import asyncio
import json
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    import pythoncom
except Exception:
    pythoncom = None

try:
    import win32com.client as win32_client
except Exception:
    win32_client = None


LogFn = Callable[[str], None]


KNOWN_FILE_EXTENSION_PATTERN = re.compile(
    r"(?i)\.(?:"
    r"gpg|pgp|zip|7z|rar|tar|tgz|gz|bz2|"
    r"xlsx|xls|xlsm|xlsb|csv|txt|pdf|"
    r"doc|docx|docm|xml|json|dat|enc|asc|sig"
    r")$"
)

DEFAULT_MAIL_FILENAME_REGEX = (
    r"([A-Za-z0-9][A-Za-z0-9_.() -]{2,220}"
    r"\.(?:zip|7z|rar|tar|tgz|gz|bz2|xlsx|xls|xlsm|xlsb|csv|txt|pdf|"
    r"doc|docx|docm|xml|json|dat|enc|asc|sig|\d{3}|gpg|pgp)"
    r"(?:\.(?:gpg|pgp))?)"
)


class KdeDownloadError(Exception):
    pass


@dataclass
class Account:
    label: str
    username: str
    password: str
    download_dir: Path
    enabled: bool = True


@dataclass
class MailWatchSettings:
    enabled: bool
    today_only: bool
    unread_only: bool
    include_subject: bool
    include_body: bool
    max_messages_per_folder: int
    max_body_chars: int
    match_mode: str
    filename_regex: str
    mailbox_filter: str


@dataclass
class Settings:
    portal_url: str
    host_url: str
    auth_api_url: str
    chrome_path: str
    headless: bool
    download_new_only: bool
    search_days: int
    max_pages: int
    download_delay_seconds: int
    busy_wait_seconds: int
    loop_wait_seconds: int
    page_timeout_seconds: int
    state_file: Path
    mail_watch: MailWatchSettings
    accounts: list[Account]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def default_log(message: str) -> None:
    print(f"[{now_text()}] {message}", flush=True)


@contextmanager
def sync_playwright_without_console(log: LogFn):
    original_create_subprocess_exec = asyncio.create_subprocess_exec

    async def create_subprocess_without_console(program: Any, *args: Any, **kwargs: Any) -> Any:
        executable_name = Path(str(program)).name.lower()
        if os.name == "nt" and executable_name == "node.exe":
            create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | create_no_window
        return await original_create_subprocess_exec(program, *args, **kwargs)

    asyncio.create_subprocess_exec = create_subprocess_without_console
    try:
        log("Playwright: เริ่ม Node driver แบบไม่แสดงหน้าต่าง Console")
        with sync_playwright() as playwright:
            yield playwright
    finally:
        asyncio.create_subprocess_exec = original_create_subprocess_exec


def load_settings(path: str | Path = "config.json") -> Settings:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    def as_bool(key: str, default: bool) -> bool:
        return bool(raw.get(key, default))

    accounts = []
    for item in raw.get("accounts", []):
        accounts.append(
            Account(
                label=str(item.get("label", item.get("username", ""))),
                username=str(item.get("username", "")),
                password=str(item.get("password", "")),
                download_dir=Path(str(item.get("download_dir", ""))).resolve(),
                enabled=bool(item.get("enabled", True)),
            )
        )

    state_file = Path(str(raw.get("state_file", "state.json")))
    local_state_file = config_path.parent / "state.json"
    if not state_file.is_absolute():
        state_file = config_path.parent / state_file
    elif local_state_file.exists():
        try:
            state_file.relative_to(config_path.parent)
        except ValueError:
            # Portable builds must keep their own history.  If an older config
            # points to a removed workspace, prefer the state beside the exe.
            state_file = local_state_file
    mail_raw = raw.get("mail_watch", {})

    return Settings(
        portal_url=str(raw.get("portal_url", "")),
        host_url=str(raw.get("host_url", "")).rstrip("/"),
        auth_api_url=str(raw.get("auth_api_url", "")).rstrip("/"),
        chrome_path=str(raw.get("chrome_path", "")),
        headless=as_bool("headless", True),
        download_new_only=as_bool("download_new_only", True),
        search_days=int(raw.get("search_days", 1)),
        max_pages=max(1, int(raw.get("max_pages", 1))),
        download_delay_seconds=max(0, int(raw.get("download_delay_seconds", 5))),
        busy_wait_seconds=max(1, int(raw.get("busy_wait_seconds", 300))),
        loop_wait_seconds=max(1, int(raw.get("loop_wait_seconds", 300))),
        page_timeout_seconds=max(10, int(raw.get("page_timeout_seconds", 45))),
        state_file=state_file,
        mail_watch=MailWatchSettings(
            enabled=bool(mail_raw.get("enabled", False)),
            today_only=bool(mail_raw.get("today_only", False)),
            unread_only=True,
            include_subject=True,
            include_body=bool(mail_raw.get("include_body", False)),
            max_messages_per_folder=max(1, int(mail_raw.get("max_messages_per_folder", 500))),
            max_body_chars=max(0, int(mail_raw.get("max_body_chars", 20000))),
            match_mode=str(mail_raw.get("match_mode", "contains")).lower(),
            filename_regex=str(
                mail_raw.get(
                    "filename_regex",
                    DEFAULT_MAIL_FILENAME_REGEX,
                )
            ),
            mailbox_filter=str(mail_raw.get("mailbox_filter", "data@tradeconnection.co.th")).strip(),
        ),
        accounts=accounts,
    )


def save_settings(settings: Settings, path: str | Path = "config.json") -> None:
    config_path = Path(path).resolve()
    state_file_value = str(settings.state_file)
    try:
        if settings.state_file.resolve().parent == config_path.parent:
            state_file_value = settings.state_file.name
    except Exception:
        pass
    data = {
        "portal_url": settings.portal_url,
        "host_url": settings.host_url,
        "auth_api_url": settings.auth_api_url,
        "chrome_path": settings.chrome_path,
        "headless": settings.headless,
        "download_new_only": settings.download_new_only,
        "search_days": settings.search_days,
        "max_pages": settings.max_pages,
        "download_delay_seconds": settings.download_delay_seconds,
        "busy_wait_seconds": settings.busy_wait_seconds,
        "loop_wait_seconds": settings.loop_wait_seconds,
        "page_timeout_seconds": settings.page_timeout_seconds,
        "state_file": state_file_value,
        "mail_watch": {
            "enabled": settings.mail_watch.enabled,
            "today_only": settings.mail_watch.today_only,
            "unread_only": settings.mail_watch.unread_only,
            "include_subject": settings.mail_watch.include_subject,
            "include_body": settings.mail_watch.include_body,
            "max_messages_per_folder": settings.mail_watch.max_messages_per_folder,
            "max_body_chars": settings.mail_watch.max_body_chars,
            "match_mode": settings.mail_watch.match_mode,
            "filename_regex": settings.mail_watch.filename_regex,
            "mailbox_filter": settings.mail_watch.mailbox_filter,
        },
        "accounts": [
            {
                "enabled": account.enabled,
                "label": account.label,
                "username": account.username,
                "password": account.password,
                "download_dir": str(account.download_dir),
            }
            for account in settings.accounts
        ],
    }
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"downloaded": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"downloaded": {}}
        data.setdefault("downloaded", {})
        return data
    except Exception:
        return {"downloaded": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def safe_filename(name: str) -> str:
    base = os.path.basename(name.strip())
    return re.sub(r'[<>:"/\\|?*]', "_", base)


def state_has_downloaded_filename(account_state: dict[str, Any], filename: str) -> bool:
    wanted = normalize_filename_for_match(filename)
    wanted_identity = canonical_file_identity(filename)
    for key, record in account_state.items():
        key_filename = str(key).split("|", 1)[0]
        if normalize_filename_for_match(key_filename) == wanted:
            return True
        if wanted_identity and canonical_file_identity(key_filename) == wanted_identity:
            return True
        if isinstance(record, dict):
            record_filename = str(record.get("filename", ""))
            if record_filename and normalize_filename_for_match(record_filename) == wanted:
                return True
            record_identity = str(record.get("canonical_identity", ""))
            if wanted_identity and record_identity == wanted_identity:
                return True
            if record_filename and wanted_identity and canonical_file_identity(record_filename) == wanted_identity:
                return True
    return False


def downloaded_file_identities(account_state: dict[str, Any]) -> set[str]:
    identities: set[str] = set()
    for key, record in account_state.items():
        candidate_names = [str(key).split("|", 1)[0]]
        if isinstance(record, dict):
            stored_identity = str(record.get("canonical_identity", "")).strip()
            if stored_identity:
                identities.add(stored_identity)
            candidate_names.append(str(record.get("filename", "")))
            candidate_names.append(str(record.get("saved_path", "")))
        for candidate_name in candidate_names:
            identity = canonical_file_identity(candidate_name)
            if identity:
                identities.add(identity)
    return identities


def normalize_account_wildcards_for_match(name: str) -> str:
    text = str(name)
    replacements = (
        (r"(?i)(?<![a-z0-9])a10xxl(?![a-z0-9])", "a1015l"),
        (r"(?i)(?<![a-z0-9])a10xx(?![a-z0-9])", "a1015"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def short_record_id(name: str) -> str:
    clean = safe_filename(name)
    digest = hashlib.sha1(normalize_filename_for_match(clean).encode("utf-8")).hexdigest()[:12]
    stem = clean[:120].rstrip(" .")
    return f"{stem}.{digest}"


def normalize_filename_for_match(name: str) -> str:
    return normalize_account_wildcards_for_match(safe_filename(name)).strip().lower()


def compact_text_for_match(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_account_wildcards_for_match(name).lower())


def strip_known_file_extensions(name: str) -> str:
    result = normalize_account_wildcards_for_match(name).lower().strip()
    while True:
        stripped = KNOWN_FILE_EXTENSION_PATTERN.sub("", result)
        if stripped == result:
            break
        result = stripped
    return result


def has_known_file_extension(name: str) -> bool:
    result = normalize_account_wildcards_for_match(name).lower().strip()
    return bool(KNOWN_FILE_EXTENSION_PATTERN.search(result))


def split_volume_part(name: str) -> str | None:
    result = normalize_account_wildcards_for_match(safe_filename(str(name))).lower().strip()
    while result.endswith((".gpg", ".pgp")):
        result = result[:-4]
    match = re.search(r"\.(\d{3})$", result)
    return match.group(1) if match else None


def split_archive_group_identity(name: str) -> str:
    result = normalize_account_wildcards_for_match(safe_filename(str(name))).lower().strip()
    while result.endswith((".gpg", ".pgp")):
        result = result[:-4]
    if not re.search(r"\.\d{3}$", result):
        return ""
    archive_name = re.sub(r"\.\d{3}$", "", result)
    return canonical_file_identity(archive_name)


def canonical_file_identity(name: str) -> str:
    clean_name = safe_filename(str(name))
    without_extensions = strip_known_file_extensions(clean_name)
    return compact_text_for_match(without_extensions)


def normalize_thai_digits(text: str) -> str:
    return str(text).translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))


def thai_business_aliases(text: str) -> list[str]:
    normalized = normalize_thai_digits(" ".join(str(text).split()))
    compact = re.sub(r"\s+", "", normalized.lower())
    aliases: list[str] = []

    is_customer_document = "เอกสาร" in compact and "ลูกค้า" in compact
    if not is_customer_document:
        return aliases

    round_numbers = re.findall(r"(?i)(?:รอบ(?:ที่)?|round)\s*([0-9]{1,2})", normalized)
    dates = re.findall(r"(?<![0-9])([0-9]{6,8})(?![0-9])", normalized)
    if not round_numbers:
        return aliases

    for number in round_numbers:
        base = f"A10XXL Document Round{int(number)}"
        aliases.append(base)
        for date_text in dates:
            aliases.append(f"{base} {date_text}")

    seen: set[str] = set()
    unique_aliases: list[str] = []
    for alias in aliases:
        key = alias.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_aliases.append(alias)
    return unique_aliases


def is_account_code_token(token: str) -> bool:
    return bool(re.fullmatch(r"a[0-9x]+[a-z]?", token.lower()))


def is_date_like_token(token: str) -> bool:
    token = token.lower()
    month_prefixes = (
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    )
    if re.fullmatch(r"\d{2,8}", token):
        return True
    if re.fullmatch(r"(?:19|20)\d{2}", token):
        return True
    if any(token.startswith(month) for month in month_prefixes):
        rest = token[3:]
        return rest == "" or bool(re.fullmatch(r"\d{2,4}", rest))
    return False


def remove_date_like_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if not is_date_like_token(token)]


def normalized_business_dates(name: str) -> tuple[set[str], set[str]]:
    """Return valid day and month keys without assuming one six-digit layout."""
    day_keys: set[str] = set()
    month_keys: set[str] = set()
    tokens = [token for token in re.split(r"[^a-z0-9]+", str(name).lower()) if token]
    month_numbers = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    def add_day(year: int, month: int, day: int) -> None:
        try:
            value = datetime(year, month, day)
        except ValueError:
            return
        day_keys.add(value.strftime("%Y-%m-%d"))
        month_keys.add(value.strftime("%Y-%m"))

    for token in tokens:
        if re.fullmatch(r"\d{8}", token):
            if token.startswith(("19", "20")):
                add_day(int(token[:4]), int(token[4:6]), int(token[6:8]))
            add_day(int(token[4:8]), int(token[2:4]), int(token[:2]))
            continue
        if re.fullmatch(r"\d{6}", token):
            add_day(2000 + int(token[:2]), int(token[2:4]), int(token[4:6]))
            add_day(2000 + int(token[4:6]), int(token[2:4]), int(token[:2]))
            continue
        month_match = re.fullmatch(r"([a-z]{3})(\d{2}|\d{4})", token)
        if month_match and month_match.group(1) in month_numbers:
            year_text = month_match.group(2)
            year = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)
            month_keys.add(f"{year:04d}-{month_numbers[month_match.group(1)]:02d}")
    return day_keys, month_keys


def business_dates_are_compatible(mail_name: str, kde_name: str) -> bool:
    mail_days, mail_months = normalized_business_dates(mail_name)
    kde_days, kde_months = normalized_business_dates(kde_name)
    if mail_days and kde_days:
        return bool(mail_days & kde_days)
    if mail_months and kde_months:
        return bool(mail_months & kde_months)
    return True


def dated_business_file_identity(name: str) -> str:
    day_keys, month_keys = normalized_business_dates(name)
    date_identity = day_keys or month_keys
    return business_file_identity(name) + "|" + ",".join(sorted(date_identity))


TOKEN_ALIASES = {
    "addr": "address",
    "broke": "broken",
    "reassign": "reassign",
    "reassignment": "reassign",
    "withdrawal": "withdraw",
}

STOP_MATCH_TOKENS = {
    "about",
    "after",
    "again",
    "and",
    "are",
    "auto",
    "automatic",
    "attachment",
    "attachments",
    "before",
    "best",
    "body",
    "can",
    "cc",
    "could",
    "data",
    "dear",
    "confidential",
    "contents",
    "copy",
    "copies",
    "computer",
    "destroy",
    "email",
    "erase",
    "file",
    "files",
    "forcepoint",
    "for",
    "from",
    "guaranteed",
    "has",
    "have",
    "information",
    "into",
    "intended",
    "kindly",
    "leakage",
    "logo",
    "mail",
    "message",
    "office",
    "person",
    "persons",
    "png",
    "proprietary",
    "protecting",
    "please",
    "pls",
    "recipient",
    "related",
    "reply",
    "request",
    "responsible",
    "scanned",
    "sensitive",
    "sent",
    "shall",
    "subject",
    "system",
    "that",
    "the",
    "this",
    "to",
    "upload",
    "was",
    "with",
    "would",
    "you",
    "your",
}

SHORT_MATCH_TOKENS = {"am", "hc", "leg", "oa", "q1", "q2", "q3", "q4", "sam"}

BODY_HINT_TOKENS = {
    "address",
    "addr",
    "approval",
    "bay",
    "broke",
    "broken",
    "change",
    "customer",
    "daily",
    "document",
    "enforcement",
    "excel",
    "format",
    "haircut",
    "haircutbay",
    "hc",
    "kamc",
    "leg",
    "oa",
    "online",
    "payment",
    "performance",
    "reassign",
    "recovery",
    "review",
    "round",
    "round1",
    "round2",
    "round3",
    "round4",
    "sam",
    "tss",
    "withdraw",
    "weekly",
}

IGNORED_BODY_PHRASES = (
    "any person receiving this e-mail",
    "any person receiving this email",
    "as the integrity of this message",
    "bank of ayudhya",
    "breach of confidentiality",
    "forcepoint dlp",
    "if you are not the intended recipient",
    "krungsri-logo",
    "protecting your information",
    "sensitive information leakage",
    "shall treat the information as confidential",
    "this email and attachments have been scanned",
    "this e-mail and any attachment",
)


def is_ignored_body_text(text: str) -> bool:
    compact = " ".join(text.lower().split())
    return any(phrase in compact for phrase in IGNORED_BODY_PHRASES)


def meaningful_tokens_for_match(name: str) -> set[str]:
    result: set[str] = set()
    raw_tokens = [token for token in re.split(r"[^a-z0-9]+", strip_known_file_extensions(name).lower()) if token]
    for raw_token in raw_tokens:
        if is_date_like_token(raw_token) or is_account_code_token(raw_token):
            continue
        token = TOKEN_ALIASES.get(raw_token, raw_token)
        if token in STOP_MATCH_TOKENS:
            continue
        if len(token) < 3 and token not in SHORT_MATCH_TOKENS:
            continue
        if token.isdigit():
            continue
        result.add(token)
        if "bay" in token and token != "bay":
            result.add("bay")
        if "online" in token and token != "online":
            result.add("online")
    if "product" in result and "review" in result:
        result.discard("product")
    if "follow" in result and "broken" in result:
        result.discard("follow")
    return result


def business_file_identity(name: str) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", strip_known_file_extensions(name).lower()) if token]
    business_tokens: list[str] = []
    part_number = split_volume_part(name)
    for raw_token in tokens:
        is_business_date = bool(
            re.fullmatch(r"\d{6}|\d{8}", raw_token)
            or re.fullmatch(r"(?:19|20)\d{2}", raw_token)
            or (
                len(raw_token) >= 3
                and raw_token[:3] in {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
                and (raw_token[3:] == "" or bool(re.fullmatch(r"\d{2,4}", raw_token[3:])))
            )
        )
        if is_business_date or is_account_code_token(raw_token):
            continue
        if part_number and raw_token == part_number:
            continue
        token = TOKEN_ALIASES.get(raw_token, raw_token)
        if part_number and token in {"7z", "zip", "rar", "tar"}:
            continue
        if token in STOP_MATCH_TOKENS:
            continue
        business_tokens.append(token)
    return "".join(business_tokens)


def is_kde_reference_candidate(name: str) -> bool:
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalize_account_wildcards_for_match(name).lower()) if token]
    if not any(is_account_code_token(token) for token in tokens):
        return False
    remaining = [token for token in tokens if not is_account_code_token(token)]
    if not remaining:
        return False
    has_date = any(is_date_like_token(token) for token in remaining)
    content_tokens = [token for token in remaining if not is_date_like_token(token)]
    if not content_tokens:
        return False
    normalized_content = {TOKEN_ALIASES.get(token, token) for token in content_tokens}
    if normalized_content <= STOP_MATCH_TOKENS:
        return False
    if has_date and len(content_tokens) >= 1:
        return True
    meaningful = meaningful_tokens_for_match(name)
    return len(meaningful) >= 2 or bool(meaningful & {"weekly", "review", "payment", "withdraw", "recovery", "performance"})


def extract_kde_reference_candidates(text: str) -> list[str]:
    pattern = re.compile(
        r"(?<![A-Za-z0-9])"
        r"((?:\d{6,8}[_ -]+)?"
        r"(?:A10XXL|A10XX|A1015L|A1015)"
        r"(?:[_ -]+(?:A10XXL|A10XX|A1015L|A1015))?"
        r"(?:[_ -]+[A-Za-z0-9][A-Za-z0-9.-]{1,40}){1,12}"
        r")"
        r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    candidates: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        candidate = match.group(1).strip(" \t\r\n'\"<>[]{}(),;:")
        if not candidate or not is_kde_reference_candidate(candidate):
            continue
        key = normalize_filename_for_match(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def account_side_from_name(name: str) -> str | None:
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalize_account_wildcards_for_match(name).lower()) if token]
    account_tokens = [token for token in tokens if is_account_code_token(token)]
    if not account_tokens:
        return None
    if any("x" in token for token in account_tokens):
        return None
    if any(token.endswith("l") for token in account_tokens):
        return "post"
    return "pre"


def account_sides_are_compatible(mail_name: str, kde_name: str) -> bool:
    mail_side = account_side_from_name(mail_name)
    kde_side = account_side_from_name(kde_name)
    if not mail_side or not kde_side:
        return True
    return mail_side == kde_side


def match_text_variants(name: str) -> set[str]:
    base = strip_known_file_extensions(normalize_filename_for_match(name))
    tokens = [token for token in re.split(r"[^a-z0-9]+", base.lower()) if token]
    sequences: list[list[str]] = []
    if tokens:
        sequences.append(tokens)
        date_free = remove_date_like_tokens(tokens)
        if date_free:
            sequences.append(date_free)

    stripped = list(tokens)
    while stripped and (re.fullmatch(r"\d{6,8}", stripped[0]) or is_account_code_token(stripped[0])):
        stripped.pop(0)
    if stripped:
        sequences.append(stripped)
        stripped_date_free = remove_date_like_tokens(stripped)
        if stripped_date_free:
            sequences.append(stripped_date_free)

    without_accounts = [token for token in stripped if not is_account_code_token(token)]
    if without_accounts:
        sequences.append(without_accounts)
        without_accounts_date_free = remove_date_like_tokens(without_accounts)
        if without_accounts_date_free:
            sequences.append(without_accounts_date_free)

    variants = {compact_text_for_match(" ".join(sequence)) for sequence in sequences}
    return {variant for variant in variants if len(variant) >= 6}


def business_tokens_for_match(name: str) -> set[str]:
    return meaningful_tokens_for_match(name)


def business_token_sets_match(mail_name: str, kde_name: str) -> bool:
    mail_tokens = business_tokens_for_match(mail_name)
    kde_tokens = business_tokens_for_match(kde_name)
    if len(mail_tokens) < 2 or len(kde_tokens) < 2:
        return False
    shared = mail_tokens & kde_tokens
    kde_coverage = len(shared) / max(1, len(kde_tokens))
    mail_coverage = len(shared) / max(1, len(mail_tokens))
    if len(shared) >= 3:
        return True
    if len(shared) >= 2 and (kde_coverage >= 0.75 or (kde_coverage >= 0.6 and mail_coverage >= 0.35)):
        return True
    if {"review", "broken"} <= shared and ("bay" in mail_tokens or "bay" in kde_tokens):
        return True
    if {"review", "bay"} <= shared and ("broken" in mail_tokens or "broken" in kde_tokens):
        return True
    return False


BROAD_TEXT_MATCH_TOKENS = {
    "app",
    "bay",
    "daily",
    "excel",
    "follow",
    "format",
    "hc",
    "kamc",
    "leg",
    "online",
    "payment",
    "product",
    "report",
    "review",
    "sam",
    "tss",
}


def is_precise_mail_lookup_key(mail_key: str, original: str = "") -> bool:
    if has_known_file_extension(mail_key):
        return True
    if "kde ref:" in original.lower():
        return True
    if is_kde_reference_candidate(mail_key):
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalize_account_wildcards_for_match(mail_key).lower()) if token]
    meaningful = meaningful_tokens_for_match(mail_key)
    if any(is_account_code_token(token) for token in tokens) and len(meaningful) >= 2:
        return True
    compact = compact_text_for_match(mail_key)
    if re.search(r"online\d+", compact) and ("payment" in compact or "tss" in compact):
        return True
    if re.search(r"round\d+", compact) and len(meaningful) >= 2:
        return True
    return False


def mail_source_priority(original: str) -> int:
    source = str(original).lower()
    if "attachment:" in source:
        return 4
    if "kde ref:" in source:
        return 3
    if "subject:" in source or "subject key:" in source:
        return 2
    if "text key:" in source or "thai key:" in source:
        return 1
    return 0


def strict_business_text_match(mail_name: str, kde_name: str) -> bool:
    mail_tokens = business_tokens_for_match(mail_name)
    kde_tokens = business_tokens_for_match(kde_name)
    if len(mail_tokens) < 3 or len(kde_tokens) < 3:
        return False
    shared = mail_tokens & kde_tokens
    if len(shared) < 3:
        return False
    mail_coverage = len(shared) / max(1, len(mail_tokens))
    if mail_coverage < 0.75:
        return False
    if not (shared - BROAD_TEXT_MATCH_TOKENS):
        return False
    return True


def is_business_text_match(variant: str) -> bool:
    if len(variant) < 12:
        return False
    markers = (
        "payment",
        "withdraw",
        "reassign",
        "recovery",
        "performance",
        "review",
        "product",
        "broken",
        "broke",
        "follow",
        "bay",
        "kamc",
        "postwo",
        "prewo",
        "online",
    )
    return any(marker in variant for marker in markers)


def wait_or_stop(seconds: int, stop_event: threading.Event | None, log: LogFn, reason: str) -> bool:
    remaining = max(0, seconds)
    while remaining > 0:
        if stop_event and stop_event.is_set():
            return False
        step = min(30, remaining)
        log(f"{reason}: รออีก {remaining} วินาที")
        time.sleep(step)
        remaining -= step
    return not (stop_event and stop_event.is_set())


class KdeDownloader:
    def __init__(
        self,
        settings: Settings,
        log: LogFn | None = None,
        stop_event: threading.Event | None = None,
    ):
        self.settings = settings
        self.log = log or default_log
        self.stop_event = stop_event
        self.state = load_state(settings.state_file)
        self.mail_filename_lookup: dict[str, str] | None = None

    def _post_auth(self, path: str, payload: dict[str, Any] | None = None, referer: str | None = None) -> requests.Response:
        headers = {
            "Origin": self.settings.host_url,
            "Referer": referer or self.settings.portal_url,
            "Host-Reference": self.settings.host_url,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        url = urljoin(self.settings.auth_api_url + "/", path.lstrip("/"))
        return requests.post(url, json=payload or {}, headers=headers, timeout=30)

    def auto_signout(self, account: Account) -> None:
        for payload in ({"username": account.username}, {"userName": account.username}):
            try:
                response = self._post_auth("/autoSignOut", payload)
                self.log(f"{account.label}: autoSignOut {response.status_code}")
            except Exception as exc:
                self.log(f"{account.label}: autoSignOut error: {exc}")

    def signout(self, account: Account, referer: str | None = None) -> None:
        try:
            response = self._post_auth("/signOut", {}, referer=referer)
            self.log(f"{account.label}: signOut {response.status_code} {response.text[:80]}")
        except Exception as exc:
            self.log(f"{account.label}: signOut error: {exc}")

    def _browser_launch_kwargs(self) -> dict[str, Any]:
        launch_kwargs: dict[str, Any] = {
            "headless": self.settings.headless,
            "args": [
                "--disable-background-networking",
                "--disable-breakpad",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--disable-direct-composition",
                "--disable-notifications",
                "--disable-search-engine-choice-screen",
                "--disable-session-crashed-bubble",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-default-browser-check",
                "--no-first-run",
                "--no-service-autorun",
                "--noerrdialogs",
                "--password-store=basic",
                "--use-mock-keychain",
                "--window-position=-32000,-32000",
                "--window-size=1,1",
            ],
        }

        bundled_headless_shell = self._bundled_headless_shell_path()
        if self.settings.headless and bundled_headless_shell.exists():
            launch_kwargs["executable_path"] = str(bundled_headless_shell)
        elif self.settings.chrome_path and Path(self.settings.chrome_path).exists():
            launch_kwargs["executable_path"] = self.settings.chrome_path
        return launch_kwargs

    def _bundled_headless_shell_path(self) -> Path:
        if getattr(sys, "frozen", False):
            application_directory = Path(sys.executable).resolve().parent
        else:
            application_directory = Path(__file__).resolve().parent
        return application_directory / "_internal" / "chromium_headless_shell" / "headless_shell.exe"

    def _log_browser_runtime(self, launch_kwargs: dict[str, Any]) -> None:
        executable_path = str(launch_kwargs.get("executable_path", ""))
        if Path(executable_path).name.lower() == "headless_shell.exe":
            self.log("Playwright: ใช้ Chromium Headless Shell แบบไม่มีหน้าต่างและปิด GPU surface")
            return
        if executable_path:
            self.log(f"Playwright: ใช้ Browser สำรอง {executable_path}")
            return
        self.log("Playwright: ใช้ Browser ค่าเริ่มต้นของ Playwright")

    def _install_browser_popup_guards(self, context: Any, primary_page: Any) -> None:
        def dismiss_dialog(dialog: Any) -> None:
            try:
                message = str(getattr(dialog, "message", ""))[:120]
                self.log(f"Playwright: ปิด dialog ที่ไม่คาดคิด: {message}")
                dialog.dismiss()
            except Exception as exc:
                self.log(f"Playwright: ปิด dialog ไม่สำเร็จ: {exc}")

        def close_popup(popup: Any) -> None:
            try:
                popup_url = str(getattr(popup, "url", ""))[:160]
                self.log(f"Playwright: ปิดหน้าต่าง popup ที่ไม่คาดคิด: {popup_url or 'about:blank'}")
                popup.close()
            except Exception as exc:
                self.log(f"Playwright: ปิด popup ไม่สำเร็จ: {exc}")

        primary_page.on("dialog", dismiss_dialog)
        context.on("page", close_popup)

    def run_once(self) -> dict[str, int]:
        summary = {"accounts": 0, "downloaded": 0, "skipped": 0, "not_requested": 0, "errors": 0}
        self.mail_filename_lookup = None
        if self.settings.mail_watch.enabled:
            self.mail_filename_lookup = self.scan_mail_filenames()
            self.log(f"Mail Watch: พบชื่อไฟล์จากเมลวันนี้ {len(self.mail_filename_lookup)} รายการ")
        for account in self.settings.accounts:
            if self.stop_event and self.stop_event.is_set():
                break
            if not account.enabled:
                continue
            summary["accounts"] += 1
            try:
                result = self.process_account(account)
                summary["downloaded"] += result.get("downloaded", 0)
                summary["skipped"] += result.get("skipped", 0)
                summary["not_requested"] += result.get("not_requested", 0)
            except Exception as exc:
                summary["errors"] += 1
                self.log(f"{account.label}: ERROR {type(exc).__name__}: {exc}")
        save_state(self.settings.state_file, self.state)
        return summary

    def run_loop(self) -> None:
        cycle = 1
        while not (self.stop_event and self.stop_event.is_set()):
            self.log(f"เริ่มรอบที่ {cycle}")
            summary = self.run_once()
            self.log(
                "จบรอบที่ "
                f"{cycle}: accounts={summary['accounts']} downloaded={summary['downloaded']} "
                f"skipped={summary['skipped']} not_requested={summary['not_requested']} errors={summary['errors']}"
            )
            cycle += 1
            if not wait_or_stop(self.settings.loop_wait_seconds, self.stop_event, self.log, "รอก่อนวนรอบใหม่"):
                break
        self.log("หยุด loop แล้ว")

    def process_account(self, account: Account) -> dict[str, int]:
        account.download_dir.mkdir(parents=True, exist_ok=True)
        self.state.setdefault("downloaded", {}).setdefault(account.username, {})
        result = {"downloaded": 0, "skipped": 0}

        self.log(f"{account.label}: เริ่มทำงาน user={account.username}")
        timeout_ms = self.settings.page_timeout_seconds * 1000

        with sync_playwright_without_console(self.log) as p:
            launch_kwargs = self._browser_launch_kwargs()
            self._log_browser_runtime(launch_kwargs)
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                viewport={"width": 1365, "height": 768},
                accept_downloads=True,
            )
            page = context.new_page()
            self._install_browser_popup_guards(context, page)
            try:
                self._login_with_retry(page, account, timeout_ms)
                self._open_download_page(page, timeout_ms)
                result = self._download_visible_pages(page, account, timeout_ms, self.mail_filename_lookup)
            finally:
                try:
                    self._logout_browser_session(page, account, timeout_ms)
                finally:
                    self.signout(account, referer=page.url if page else None)
                    self.auto_signout(account)
                    context.close()
                    browser.close()
                    save_state(self.settings.state_file, self.state)
        self.log(f"{account.label}: เสร็จแล้ว downloaded={result['downloaded']} skipped={result['skipped']}")
        return result

    def scan_mail_filenames(self) -> dict[str, str]:
        if win32_client is None or pythoncom is None:
            self.log("Mail Watch: ไม่พบ pywin32/win32com จึงสแกน Outlook ไม่ได้")
            return {}

        settings = self.settings.mail_watch
        if settings.unread_only:
            self.log("Mail Watch: ใช้เฉพาะเมลที่ยังไม่ได้เปิดอ่าน (Unread only)")
        self.log(
            "Mail Watch: ใช้ Subject ชื่อไฟล์แนบ และ Body จาก Outlook เป็นตัวเทียบ KDE "
            f"(Body {'enabled' if settings.include_body else 'disabled'}, "
            f"mailbox_filter={settings.mailbox_filter or 'all'})"
        )
        self.log("Mail Watch: ไม่กรองชื่อหรืออีเมลผู้ส่ง ผู้ส่งที่เปลี่ยนไปจึงไม่ทำให้เมลถูกข้าม")
        mailbox_filters = [
            item.strip().lower()
            for item in re.split(r"[,;]+", settings.mailbox_filter or "")
            if item.strip()
        ]
        filename_patterns: list[re.Pattern[str]] = []
        configured_pattern = settings.filename_regex.strip()
        if configured_pattern:
            try:
                filename_patterns.append(re.compile(configured_pattern, re.IGNORECASE))
            except re.error as exc:
                self.log(f"Mail Watch: filename_regex ไม่ถูกต้อง จึงใช้รูปแบบมาตรฐานแทน: {exc}")
        if configured_pattern != DEFAULT_MAIL_FILENAME_REGEX or not filename_patterns:
            filename_patterns.append(re.compile(DEFAULT_MAIL_FILENAME_REGEX, re.IGNORECASE))

        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        lookup: dict[str, str] = {}
        stats = {
            "roots": 0,
            "folders": 0,
            "folders_scanned": 0,
            "folders_failed": 0,
            "messages": 0,
            "unread": 0,
            "mails_with_keys": 0,
            "auto_replies": 0,
            "restrict_failed": 0,
            "attachments": 0,
            "attachments_with_keys": 0,
        }
        unread_subject_examples: list[str] = []
        com_initialized = False

        try:
            pythoncom.CoInitialize()
            com_initialized = True
        except Exception as exc:
            self.log(f"Mail Watch: เริ่ม Outlook COM ไม่ได้: {exc}")
            return {}

        try:
            outlook = win32_client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
        except Exception as exc:
            self.log(f"Mail Watch: เปิด Outlook ไม่ได้: {exc}")
            if com_initialized:
                pythoncom.CoUninitialize()
            return {}

        def received_datetime(item: Any) -> datetime | None:
            try:
                value = item.ReceivedTime
            except Exception:
                return None
            if isinstance(value, datetime):
                return value.replace(tzinfo=None)
            try:
                return datetime.fromtimestamp(float(value))
            except Exception:
                return None

        def is_unread(item: Any) -> bool:
            try:
                return bool(item.UnRead)
            except Exception:
                return False

        def sender_identity(item: Any) -> str:
            try:
                sender = item.Sender
                if sender is not None:
                    exchange_user = sender.GetExchangeUser()
                    if exchange_user is not None:
                        primary_address = str(exchange_user.PrimarySmtpAddress or "").strip()
                        if primary_address:
                            return primary_address
            except Exception:
                pass
            for attribute in ("SenderEmailAddress", "SenderName"):
                try:
                    value = str(getattr(item, attribute, "") or "").strip()
                    if value:
                        return value
                except Exception:
                    continue
            return ""

        def add_candidate(name: str, source_label: str) -> None:
            name = " ".join(str(name).split()).strip(" \t\r\n'\"<>[]{}(),;:")
            if not name:
                return
            display_name = re.sub(r'[<>:"/\\|?*]', "_", name)
            key = normalize_filename_for_match(display_name)
            if not key:
                return
            display = f"{display_name} [{source_label}]"
            if key not in lookup:
                lookup[key] = display

        def add_from_text(
            text: str,
            source_label: str,
            allow_text_keys: bool = False,
        ) -> None:
            if not text:
                return
            is_subject_source = source_label.lower().startswith("subject:")
            scan_text = re.sub(r"([A-Za-z]+)'(\d{2,4})", r"\1\2", text)
            for candidate in extract_kde_reference_candidates(scan_text):
                add_candidate(candidate, f"KDE ref: {source_label}")
            for filename_pattern in filename_patterns:
                for match in filename_pattern.finditer(scan_text):
                    name = match.group(1) if match.groups() else match.group(0)
                    add_candidate(name, source_label)
            for alias in thai_business_aliases(scan_text):
                add_candidate(alias, f"Thai key: {source_label}")
            if not allow_text_keys:
                return
            def is_text_candidate(candidate: str) -> bool:
                compact = compact_text_for_match(candidate)
                if len(compact) < 8 or len(compact) > 180:
                    return False
                if not re.search(r"[a-z]", compact):
                    return False
                if re.fullmatch(r"[a-f0-9]{8}[a-f0-9]{4}[a-f0-9]{4}[a-f0-9]{4}[a-f0-9]{12}", compact):
                    return False
                if compact.startswith(("postwowith", "prewowith")):
                    return False
                if not is_subject_source and is_ignored_body_text(candidate):
                    return False
                generic_tokens = meaningful_tokens_for_match(candidate)
                if len(generic_tokens) >= 2:
                    if is_subject_source:
                        return True
                    if generic_tokens & {TOKEN_ALIASES.get(token, token) for token in BODY_HINT_TOKENS}:
                        return True
                if any(marker in compact for marker in ("a15", "a1015", "a10xx")) and any(
                    marker in compact
                    for marker in (
                        "payment",
                        "withdraw",
                        "recovery",
                        "report",
                        "performance",
                        "postwo",
                        "prewo",
                        "prowo",
                        "online",
                        "format",
                        "excel",
                        "sam",
                        "hc",
                    )
                ):
                    return True
                if "payment" in compact and any(marker in compact for marker in ("tss", "online", "prewo", "postwo")):
                    return True
                if "recovery" in compact and any(marker in compact for marker in ("daily", "performance")):
                    return True
                if "report" in compact and any(marker in compact for marker in ("hc", "app", "prowo")):
                    return True
                if "withdraw" in compact and any(marker in compact for marker in ("add", "reassign", "postwo")):
                    return True
                if "sam" in compact:
                    return True
                if "hc" in compact and any(marker in compact for marker in ("report", "approved", "app", "excel")):
                    return True
                if "format" in compact and "excel" in compact:
                    return True
                if "review" in compact and any(
                    marker in compact for marker in ("product", "bay", "kamc", "broken", "broke", "follow")
                ):
                    return True
                if any(marker in compact for marker in ("broken", "broke", "follow")) and any(
                    marker in compact for marker in ("review", "product", "bay", "kamc")
                ):
                    return True
                return False

            for line in scan_text.splitlines():
                for part in re.split(r"[,;|:&\t]+", line):
                    part = " ".join(part.split()).strip(" \t\r\n'\"<>[]{}(),;:")
                    if not part or len(part) > 220:
                        continue
                    for match in re.finditer(
                        r"(?<![A-Za-z0-9])([A-Za-z0-9][A-Za-z0-9_.-]*(?:[ _-]+[A-Za-z0-9][A-Za-z0-9_.-]*)+)(?![A-Za-z0-9])",
                        part,
                    ):
                        candidate = match.group(1)
                        if not is_text_candidate(candidate):
                            continue
                        add_candidate(candidate, f"Text key: {source_label}")

        def add_subject_aliases(subject: str, source_label: str) -> None:
            if not subject:
                return
            normalized = re.sub(r"(?i)\b(?:automatic reply|re|fw):\s*", " ", subject)
            normalized = re.sub(r"([A-Za-z]+)'(\d{2,4})", r"\1\2", normalized)
            normalized = re.sub(r"(?i)\bpre\s+wo\b", "prewo", normalized)
            normalized = re.sub(r"(?i)\bpost\s+wo\b", "postwo", normalized)
            normalized = " ".join(normalized.replace("&", " ").split())
            tokens = [token for token in re.split(r"[^a-z0-9]+", normalized.lower()) if token]
            token_set = set(tokens)
            compact = compact_text_for_match(normalized)
            aliases: list[str] = []

            def add_alias(value: str) -> None:
                value = " ".join(value.split()).strip()
                if value and value.lower() not in {item.lower() for item in aliases}:
                    aliases.append(value)

            strong_markers = (
                "a1015",
                "a1015l",
                "a10xx",
                "payment",
                "withdraw",
                "reassign",
                "recovery",
                "performance",
                "online",
                "format",
                "excel",
                "review",
                "product",
                "broken",
                "broke",
                "follow",
                "bay",
                "kamc",
                "sam",
                "hc",
            )
            if any(marker in compact for marker in strong_markers) and len(normalized) <= 220:
                add_alias(normalized)
            if "payment" in token_set:
                round_numbers = re.findall(r"(?i)\bround\s*([0-9]+)\b", normalized)
                if "online" in token_set:
                    for number in round_numbers:
                        add_alias(f"payment online{number}")
                else:
                    add_alias("payment")
            if "recovery" in token_set and "performance" in token_set:
                add_alias("daily recovery performance")
            if "performance" in token_set and "q2" in token_set:
                add_alias("quarterly oa performance q2")
                add_alias("oa performance q2")
            if "withdraw" in token_set or "reassign" in token_set:
                add_alias("withdraw add reassign")
            if "hc" in token_set:
                add_alias("hc report app prowo")
                add_alias("hc report")
            if "sam" in token_set:
                add_alias("sam")
            if "format" in token_set and "excel" in token_set:
                add_alias("format excel file")
            for alias in thai_business_aliases(normalized):
                add_alias(alias)
            if "review" in token_set and "product" in token_set:
                add_alias("review product")
                if "bay" in token_set and "kamc" in token_set:
                    add_alias("review product bay kamc")
                    add_alias("review bay")
                if "broken" in token_set or "broke" in token_set:
                    add_alias("review product broken")
                    add_alias("review product broke")
                    add_alias("review broken")
                    if "bay" in token_set or "kamc" in token_set:
                        add_alias("review bay broken")
                        add_alias("review bay broke")
            if ("broken" in token_set or "broke" in token_set) and "follow" in token_set:
                add_alias("broken follow")
                add_alias("broke follow")

            for alias in aliases:
                add_candidate(alias, f"Subject key: {source_label}")

        def folder_matches_filter(folder_path: str) -> bool:
            return not mailbox_filters or any(item in folder_path.lower() for item in mailbox_filters)

        def restrict_unread_items(items: Any, folder_path: str) -> Any:
            if not settings.unread_only:
                return items
            last_error = None
            for clause in ("[Unread] = True", "[UnRead] = True"):
                try:
                    return items.Restrict(clause)
                except Exception as exc:
                    last_error = exc
            stats["restrict_failed"] += 1
            if stats["restrict_failed"] <= 10:
                self.log(f"Mail Watch: unread restrict failed {folder_path}: {last_error}")
            return items

        def scan_folder(folder: Any, folder_path: str, matched_filter: bool = False) -> None:
            if self.stop_event and self.stop_event.is_set():
                return
            stats["folders"] += 1
            scan_items = matched_filter or folder_matches_filter(folder_path)
            items = None
            count = 0
            if scan_items:
                stats["folders_scanned"] += 1
                try:
                    items = restrict_unread_items(folder.Items, folder_path)
                    try:
                        items.Sort("[ReceivedTime]", True)
                    except Exception:
                        pass
                    count = min(int(items.Count), settings.max_messages_per_folder)
                except Exception as exc:
                    stats["folders_failed"] += 1
                    if stats["folders_failed"] <= 10:
                        self.log(f"Mail Watch: skip folder {folder_path}: {exc}")

            for index in range(1, count + 1):
                if self.stop_event and self.stop_event.is_set():
                    return
                try:
                    item = items.Item(index)
                except Exception:
                    continue
                received = received_datetime(item)
                if settings.today_only and received and received < start:
                    continue
                if settings.today_only and not received:
                    continue
                stats["messages"] += 1
                if settings.unread_only and not is_unread(item):
                    continue
                stats["unread"] += 1
                subject = ""
                try:
                    subject = str(item.Subject or "")
                except Exception:
                    subject = ""
                if re.search(r"(?i)\bautomatic\s+reply\b", subject):
                    stats["auto_replies"] += 1
                    if stats["auto_replies"] <= 10:
                        self.log(f"Mail Watch: skip automatic reply {folder_path} | {subject[:80]}")
                    continue
                sender = sender_identity(item)
                source_label = f"{folder_path} | {subject[:80]}"
                if sender:
                    source_label = f"{source_label} | sender={sender[:80]}"
                if len(unread_subject_examples) < 10:
                    unread_subject_examples.append(source_label)
                before_keys = len(lookup)
                try:
                    if settings.include_subject:
                        add_from_text(subject, f"Subject: {source_label}", allow_text_keys=True)
                        add_subject_aliases(subject, source_label)
                except Exception:
                    pass
                try:
                    attachments = item.Attachments
                    for attachment_index in range(1, int(attachments.Count) + 1):
                        attachment = attachments.Item(attachment_index)
                        attachment_name = ""
                        for attribute in ("FileName", "DisplayName"):
                            try:
                                attachment_name = str(getattr(attachment, attribute, "") or "").strip()
                            except Exception:
                                attachment_name = ""
                            if attachment_name:
                                break
                        if not attachment_name:
                            continue
                        stats["attachments"] += 1
                        before_attachment_keys = len(lookup)
                        add_from_text(
                            attachment_name,
                            f"Attachment: {source_label}",
                            allow_text_keys=True,
                        )
                        if len(lookup) > before_attachment_keys:
                            stats["attachments_with_keys"] += 1
                except Exception:
                    pass
                if settings.include_body:
                    try:
                        body_text = str(item.Body or "")[: settings.max_body_chars]
                        add_from_text(
                            body_text,
                            source_label,
                            allow_text_keys=True,
                        )
                        for line in body_text.splitlines():
                            line = " ".join(line.split())
                            if not line or is_ignored_body_text(line):
                                continue
                            line_tokens = meaningful_tokens_for_match(line)
                            if line_tokens & {TOKEN_ALIASES.get(token, token) for token in BODY_HINT_TOKENS}:
                                add_subject_aliases(line, source_label)
                    except Exception:
                        pass
                if len(lookup) > before_keys:
                    stats["mails_with_keys"] += 1
                    if stats["mails_with_keys"] <= 30:
                        self.log(f"Mail Watch: key mail {source_label}")

            try:
                child_folders = folder.Folders
                for child_index in range(1, int(child_folders.Count) + 1):
                    child = child_folders.Item(child_index)
                    child_name = str(getattr(child, "Name", child_index))
                    scan_folder(child, f"{folder_path}\\{child_name}", scan_items)
            except Exception:
                pass

        try:
            roots = namespace.Folders
            for root_index in range(1, int(roots.Count) + 1):
                root = roots.Item(root_index)
                root_name = str(getattr(root, "Name", root_index))
                stats["roots"] += 1
                self.log(f"Mail Watch: scan mailbox tree {root_name}")
                scan_folder(root, root_name, folder_matches_filter(root_name))
        except Exception as exc:
            self.log(f"Mail Watch: สแกน folder ไม่สำเร็จ: {exc}")

        if mailbox_filters and stats["folders_scanned"] == 0:
            self.log(f"Mail Watch: ไม่พบ mailbox ตาม filter: {settings.mailbox_filter}")
        self.log(
            f"Mail Watch: scanned mailboxes={stats['roots']} folders_seen={stats['folders']} "
            f"folders_scanned={stats['folders_scanned']} folder_errors={stats['folders_failed']} "
            f"messages_scanned={stats['messages']} messages_unread={stats['unread']} "
            f"auto_replies={stats['auto_replies']} attachments={stats['attachments']} "
            f"attachments_with_keys={stats['attachments_with_keys']} "
            f"mails_with_keys={stats['mails_with_keys']} filenames={len(lookup)}"
        )
        for filename in list(lookup.values())[:20]:
            self.log(f"Mail Watch: filename {filename}")
        if settings.unread_only and stats["unread"] and not lookup:
            self.log("Mail Watch: มี unread mail แต่ Subject ไม่ตรงกับ rule สำหรับเทียบ KDE")
            for subject in unread_subject_examples:
                self.log(f"Mail Watch: unread subject skipped {subject}")
        if com_initialized:
            pythoncom.CoUninitialize()
        return lookup

    def _prepare_login_retry(self, page: Any, account: Account) -> None:
        try:
            page.context.clear_cookies()
            self.log(f"{account.label}: ล้าง session ของ Browser ก่อนลอง Login ใหม่")
        except Exception as exc:
            self.log(f"{account.label}: ล้าง session ของ Browser ไม่สำเร็จ: {exc}")

    def _login_failure_summary(self, page: Any) -> str:
        body = " ".join(self._body_text(page).split())
        if len(body) > 240:
            body = body[:237] + "..."
        return f"url={page.url}" + (f" page={body}" if body else "")

    def _login_with_retry(self, page: Any, account: Account, timeout_ms: int) -> None:
        last_failure = "ไม่ทราบสาเหตุ"
        for attempt in range(1, 4):
            if self.stop_event and self.stop_event.is_set():
                raise KdeDownloadError("stopped")
            self.log(f"{account.label}: login attempt {attempt}")
            try:
                page.goto(self.settings.portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
                self._wait_network(page)
                page.locator("#username").wait_for(timeout=min(5000, timeout_ms))
                page.locator("#password").wait_for(timeout=min(5000, timeout_ms))
                page.fill("#username", account.username, timeout=timeout_ms)
                page.fill("#password", account.password, timeout=timeout_ms)
                page.get_by_text("Login Now", exact=True).click(timeout=timeout_ms)
                page.wait_for_timeout(2500)
            except PlaywrightTimeoutError:
                last_failure = f"ไม่พบหรือใช้งานหน้า Login ไม่ได้ url={page.url}"
                self.log(f"{account.label}: {last_failure}")
            else:
                body = self._body_text(page)
                if "ใช้งานอยู่" in body or "User%3A" in body:
                    self.log(f"{account.label}: user ยังใช้งานอยู่ รอ {self.settings.busy_wait_seconds} วินาที")
                    self._click_text_if_present(page, "OK")
                    if not wait_or_stop(self.settings.busy_wait_seconds, self.stop_event, self.log, f"{account.label}: รอ user ว่าง"):
                        raise KdeDownloadError("stopped while waiting for busy user")
                    self.auto_signout(account)
                    self._prepare_login_retry(page, account)
                    continue

                try:
                    page.wait_for_url("**/kde-file-gateway-and-monitoring**", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    pass
                self._wait_network(page)
                if "/kde-file-gateway-and-monitoring" in page.url and "Log out" in self._body_text(page):
                    self.log(f"{account.label}: login สำเร็จ")
                    return

                last_failure = self._login_failure_summary(page)
                self.log(f"{account.label}: login ยังไม่สำเร็จ {last_failure}")
            if attempt < 3:
                self._prepare_login_retry(page, account)
                if not wait_or_stop(self.settings.busy_wait_seconds, self.stop_event, self.log, f"{account.label}: รอก่อน login ใหม่"):
                    raise KdeDownloadError("stopped while retrying login")

        raise KdeDownloadError(f"login failed after 3 attempts: {last_failure}")

    def _open_download_page(self, page: Any, timeout_ms: int) -> None:
        page.get_by_text("Internet File Gateway", exact=True).click(timeout=timeout_ms)
        page.wait_for_timeout(700)
        page.get_by_text("Customer", exact=True).click(timeout=timeout_ms)
        page.wait_for_timeout(700)
        page.get_by_text("Download (Cust)", exact=True).click(timeout=timeout_ms)
        self._wait_network(page)
        page.wait_for_timeout(2500)
        if "Customer Download List" not in self._body_text(page):
            raise KdeDownloadError(f"download page did not load: {page.url}")

    def _download_visible_pages(
        self,
        page: Any,
        account: Account,
        timeout_ms: int,
        allowed_filenames: dict[str, str] | None = None,
    ) -> dict[str, int]:
        result = {"downloaded": 0, "skipped": 0, "not_requested": 0}
        matched_requested = 0
        account_state = self.state["downloaded"][account.username]
        downloaded_identities = downloaded_file_identities(account_state)
        existing_identities = self._existing_download_identities(account.download_dir)
        consumed_mail_groups: dict[str, str] = {}
        for page_no in range(1, self.settings.max_pages + 1):
            if self.stop_event and self.stop_event.is_set():
                break
            self.log(f"{account.label}: อ่านหน้า download page {page_no}")
            rows = self._table_rows(page)
            if not rows:
                self.log(f"{account.label}: ไม่พบไฟล์ในหน้านี้")
                break

            page_matches: dict[int, dict[str, Any]] = {}
            ambiguous_mail_keys: dict[str, int] = {}
            if allowed_filenames is not None:
                page_matches, ambiguous_mail_keys = self._select_page_mail_matches(rows, allowed_filenames)
                for key in sorted(ambiguous_mail_keys):
                    self.log(
                        f"{account.label}: ข้าม mail key ที่กำกวม เพราะตรงกับ KDE "
                        f"{ambiguous_mail_keys[key]} รายการ: {key}"
                    )

            for row_index, row in rows:
                filename = row.get("filename", "")
                if not filename:
                    continue
                matched_mail: str | None = None
                if allowed_filenames is not None:
                    detail = page_matches.get(row_index)
                    if not detail:
                        result["not_requested"] += 1
                        continue
                    mail_key = str(detail["mail_key"])
                    multi_part_group = str(detail.get("multi_part_group", ""))
                    consumed_group = consumed_mail_groups.get(mail_key)
                    if consumed_group is not None and (
                        not multi_part_group or consumed_group != multi_part_group
                    ):
                        result["not_requested"] += 1
                        continue
                    matched_mail = detail["original"]
                    if consumed_group is None:
                        consumed_mail_groups[mail_key] = multi_part_group or f"single:{canonical_file_identity(filename)}"
                    self.log(
                        f"{account.label}: mail match {filename} <= {matched_mail} "
                        f"(score={detail['score']}, {'precise' if detail['precise'] else 'text'})"
                    )
                    split_part_count = int(detail.get("split_part_count", 0))
                    if split_part_count > 1:
                        self.log(
                            f"{account.label}: mail key นี้ตรงกับชุดไฟล์แบ่งส่วน "
                            f"{split_part_count} รายการ จึงดาวน์โหลดทุก part ที่ยังไม่เคยดาวน์โหลด"
                        )
                    equivalent_count = int(detail.get("equivalent_count", 1))
                    if equivalent_count > 1:
                        self.log(
                            f"{account.label}: เลือก KDE รายการแรกเพียงรายการเดียวจากชื่อธุรกิจเดียวกัน "
                            f"{equivalent_count} รายการ"
                        )
                if allowed_filenames is not None:
                    matched_requested += 1
                target = account.download_dir / safe_filename(filename)
                downloaded_key = self._download_key(row)
                file_identity = canonical_file_identity(filename)
                file_handler = getattr(self, "file_handler", None)
                if file_handler is not None:
                    status = file_handler(page, row_index, row, account, timeout_ms)
                    if status == "complete":
                        result["downloaded"] += 1
                    elif status == "skipped":
                        result["skipped"] += 1
                    else:
                        result["errors"] = result.get("errors", 0) + 1
                    if self.settings.download_delay_seconds > 0:
                        if not wait_or_stop(
                            self.settings.download_delay_seconds, self.stop_event,
                            self.log, f"{account.label}: พักก่อนโหลดไฟล์ถัดไป"
                        ):
                            break
                    continue
                already_recorded = downloaded_key in account_state or (
                    bool(file_identity) and file_identity in downloaded_identities
                )
                already_in_folder = target.exists() or (
                    bool(file_identity) and file_identity in existing_identities
                )
                if self.settings.download_new_only and (already_recorded or already_in_folder):
                    result["skipped"] += 1
                    reason = "ประวัติการดาวน์โหลด" if already_recorded else "พบชื่อไฟล์เดียวกันในโฟลเดอร์ปลายทาง"
                    self.log(f"{account.label}: ข้าม {filename} ({reason})")
                    continue

                saved = self._click_download_row(page, row_index, target, timeout_ms)
                account_state[downloaded_key] = {
                    "filename": filename,
                    "canonical_identity": file_identity,
                    "saved_path": str(saved),
                    "file_time": row.get("file_time", ""),
                    "size_text": row.get("size_text", ""),
                    "downloaded_at": now_text(),
                }
                if file_identity:
                    downloaded_identities.add(file_identity)
                    existing_identities.add(file_identity)
                save_state(self.settings.state_file, self.state)
                result["downloaded"] += 1
                self.log(f"{account.label}: downloaded {filename} -> {saved}")
                if self.settings.download_delay_seconds > 0:
                    if not wait_or_stop(
                        self.settings.download_delay_seconds,
                        self.stop_event,
                        self.log,
                        f"{account.label}: พักก่อนโหลดไฟล์ถัดไป",
                    ):
                        break

            if self.stop_event and self.stop_event.is_set():
                break
            if page_no >= self.settings.max_pages:
                break
            if not self._next_page(page, timeout_ms):
                break
        if allowed_filenames is not None:
            self.log(f"{account.label}: mail matched rows on KDE page={matched_requested}")
        return result

    def _existing_download_identities(self, download_dir: Path) -> set[str]:
        identities: set[str] = set()
        try:
            for item in download_dir.iterdir():
                if not item.is_file():
                    continue
                identity = canonical_file_identity(item.name)
                if identity:
                    identities.add(identity)
        except Exception as exc:
            self.log(f"ตรวจสอบไฟล์เดิมในโฟลเดอร์ {download_dir} ไม่สำเร็จ: {exc}")
        return identities

    def _select_page_mail_matches(
        self,
        rows: list[tuple[int, dict[str, str]]],
        allowed_filenames: dict[str, str],
    ) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
        candidates_by_mail_key: dict[str, list[tuple[int, str, dict[str, Any]]]] = {}
        for row_index, row in rows:
            filename = row.get("filename", "")
            if not filename:
                continue
            detail = self._mail_match_detail(normalize_filename_for_match(filename), allowed_filenames)
            if not detail:
                continue
            mail_key = str(detail["mail_key"])
            candidates_by_mail_key.setdefault(mail_key, []).append((row_index, filename, detail))

        selected: dict[int, dict[str, Any]] = {}
        ambiguous: dict[str, int] = {}
        for mail_key, candidates in candidates_by_mail_key.items():
            ordered = sorted(
                candidates,
                key=lambda candidate: (
                    int(candidate[2]["score"]),
                    int(candidate[2]["precise"]),
                    int(candidate[2].get("source_priority", 0)),
                    -candidate[0],
                ),
                reverse=True,
            )
            split_groups = {split_archive_group_identity(candidate[1]) for candidate in ordered}
            if "" not in split_groups and len(split_groups) == 1:
                split_group = next(iter(split_groups))
                for row_index, _filename, detail in ordered:
                    detail["multi_part_group"] = split_group
                    detail["split_part_count"] = len(ordered)
                    selected[row_index] = detail
                continue
            chosen: tuple[int, str, dict[str, Any]] | None = None
            if len(ordered) == 1:
                chosen = ordered[0]
            else:
                business_identities = {dated_business_file_identity(candidate[1]) for candidate in ordered}
                if "" not in business_identities and len(business_identities) == 1:
                    chosen = ordered[0]
                    chosen[2]["equivalent_count"] = len(ordered)
                else:
                    top_quality = (
                        int(ordered[0][2]["score"]),
                        int(ordered[0][2]["precise"]),
                        int(ordered[0][2].get("source_priority", 0)),
                    )
                    second_quality = (
                        int(ordered[1][2]["score"]),
                        int(ordered[1][2]["precise"]),
                        int(ordered[1][2].get("source_priority", 0)),
                    )
                    if top_quality > second_quality:
                        chosen = ordered[0]

            if chosen is None:
                ambiguous[mail_key] = len(ordered)
                continue
            selected[chosen[0]] = chosen[2]
        return selected, ambiguous

    def _matches_mail_filename(self, kde_key: str, allowed_filenames: dict[str, str]) -> str | None:
        detail = self._mail_match_detail(kde_key, allowed_filenames)
        return str(detail["original"]) if detail else None

    def _mail_match_detail(self, kde_key: str, allowed_filenames: dict[str, str]) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        for mail_key, original in allowed_filenames.items():
            detail = self._match_single_mail_key(kde_key, mail_key, original)
            if not detail:
                continue
            if not best:
                best = detail
                continue
            best_rank = (
                int(best["score"]),
                int(best["precise"]),
                int(best.get("source_priority", 0)),
                len(str(best["mail_key"])),
            )
            detail_rank = (
                int(detail["score"]),
                int(detail["precise"]),
                int(detail.get("source_priority", 0)),
                len(str(detail["mail_key"])),
            )
            if detail_rank > best_rank:
                best = detail
        return best

    def _match_single_mail_key(self, kde_key: str, mail_key: str, original: str) -> dict[str, Any] | None:
        match_mode = self.settings.mail_watch.match_mode
        kde_compact = compact_text_for_match(kde_key)
        kde_variants = match_text_variants(kde_key)
        precise_key = is_precise_mail_lookup_key(mail_key, original)

        def mail_key_allowed(mail_compact: str) -> bool:
            if mail_compact == "payment" and "online" in kde_compact:
                return False
            online_match = re.fullmatch(r"paymentonline(\d+)", mail_compact)
            if online_match:
                number = re.escape(online_match.group(1))
                return bool(re.search(rf"online[^0-9]*{number}(?![0-9])", kde_key.lower()))
            return True

        def detail(score: int) -> dict[str, Any]:
            return {
                "mail_key": mail_key,
                "original": original,
                "score": score,
                "precise": precise_key,
                "source_priority": mail_source_priority(original),
            }

        if kde_key == mail_key:
            return detail(100)
        if not account_sides_are_compatible(mail_key, kde_key):
            return None
        if not business_dates_are_compatible(mail_key, kde_key):
            return None
        mail_compact = compact_text_for_match(mail_key)
        if not mail_key_allowed(mail_compact):
            return None
        mail_split_part = split_volume_part(mail_key)
        kde_split_part = split_volume_part(kde_key)
        if mail_split_part and mail_split_part != kde_split_part:
            return None
        if kde_split_part and not mail_split_part:
            mail_business_identity = business_file_identity(mail_key)
            kde_business_identity = business_file_identity(kde_key)
            if (
                len(mail_business_identity) >= 5
                and mail_business_identity == kde_business_identity
            ):
                return detail(90)
        mail_identity = canonical_file_identity(mail_key)
        kde_identity = canonical_file_identity(kde_key)
        if mail_identity and mail_identity == kde_identity:
            return detail(97)

        if match_mode in {"contains", "substring"}:
            if precise_key:
                if mail_key and mail_key in kde_key:
                    return detail(98)
                if mail_compact and mail_compact in kde_compact:
                    return detail(96)
                mail_variants = match_text_variants(mail_key)
                if kde_variants & mail_variants:
                    return detail(94)
                for mail_variant in mail_variants:
                    if not is_business_text_match(mail_variant):
                        continue
                    for kde_variant in kde_variants:
                        if mail_variant in kde_variant or kde_variant in mail_variant:
                            return detail(88)
                if business_token_sets_match(mail_key, kde_key):
                    return detail(82)
            elif strict_business_text_match(mail_key, kde_key):
                return detail(70)
        if match_mode == "suffix":
            if precise_key:
                if mail_key and kde_key.endswith(mail_key):
                    return detail(98)
                if mail_compact and kde_compact.endswith(mail_compact):
                    return detail(96)
                mail_variants = match_text_variants(mail_key)
                if kde_variants & mail_variants:
                    return detail(94)
            elif strict_business_text_match(mail_key, kde_key):
                return detail(70)
        return None

    def _table_rows(self, page: Any) -> list[tuple[int, dict[str, str]]]:
        rows: list[tuple[int, dict[str, str]]] = []
        table_rows = page.locator("tbody tr")
        for idx in range(table_rows.count()):
            cells = table_rows.nth(idx).locator("td")
            values = []
            for col in range(cells.count()):
                try:
                    values.append(cells.nth(col).inner_text(timeout=1000).strip())
                except Exception:
                    values.append("")
            if len(values) >= 4 and values[1]:
                rows.append(
                    (
                        idx,
                        {
                            "no": values[0],
                            "filename": values[1],
                            "file_time": values[2],
                            "size_text": values[3],
                        },
                    )
                )
        return rows

    def _download_key(self, row: dict[str, str]) -> str:
        return "|".join([row.get("filename", ""), row.get("file_time", ""), row.get("size_text", "")])

    def _click_download_row(self, page: Any, row_index: int, target: Path, timeout_ms: int) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise KdeDownloadError(f"target already exists: {target}")
        temporary_target = target.with_name(target.name + ".part")
        if temporary_target.exists():
            temporary_target.unlink()
        table_row = page.locator("tbody tr").nth(row_index)
        buttons = table_row.locator("button")
        if buttons.count() == 0:
            raise KdeDownloadError(f"download button not found for {target.name}")
        try:
            with page.expect_download(timeout=timeout_ms) as download_info:
                buttons.last.click(timeout=timeout_ms)
            download = download_info.value
            failure = download.failure()
            if failure:
                raise KdeDownloadError(f"browser download failed for {target.name}: {failure}")
            download.save_as(str(temporary_target))
            if not temporary_target.is_file() or temporary_target.stat().st_size <= 0:
                raise KdeDownloadError(f"downloaded file is empty for {target.name}")
            os.replace(temporary_target, target)
            return target
        except Exception as error:
            if temporary_target.exists():
                temporary_target.unlink()
            if isinstance(error, KdeDownloadError):
                raise
            raise KdeDownloadError(
                f"download failed for {target.name} within {timeout_ms // 1000} seconds: {error}"
            ) from error

    def _next_page(self, page: Any, timeout_ms: int) -> bool:
        candidates = [
            "button[aria-label='Go to next page']",
            "button[title='Go to next page']",
            "button[aria-label*='next']",
        ]
        for selector in candidates:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_enabled():
                locator.first.click(timeout=timeout_ms)
                self._wait_network(page)
                page.wait_for_timeout(1500)
                return True
        return False

    def _ui_logout(self, page: Any, timeout_ms: int) -> None:
        if not page:
            return
        try:
            if self._click_text_if_present(page, "Log out", timeout_ms):
                self._wait_for_logout_navigation(page, timeout_ms)
                self.log(f"UI logout clicked, url={page.url}")
                return
            if self._click_text_if_present(page, "Logout", timeout_ms):
                self._wait_for_logout_navigation(page, timeout_ms)
                self.log(f"UI logout clicked, url={page.url}")
        except Exception as exc:
            self.log(f"UI logout error: {exc}")

    def _logout_browser_session(self, page: Any, account: Account, timeout_ms: int) -> None:
        if not page:
            return
        self._ui_logout(page, timeout_ms)
        if "/kde-portal/login" in page.url or "/login" in page.url:
            self.log(f"{account.label}: browser อยู่หน้า login หลัง Log out")
        else:
            self.log(f"{account.label}: หลังคลิก Log out ยังอยู่ที่ {page.url}")

        self._browser_auth_post(page, "/signOut", {}, account.label)
        for payload in ({"username": account.username}, {"userName": account.username}):
            self._browser_auth_post(page, "/autoSignOut", payload, account.label)

    def _browser_auth_post(self, page: Any, path: str, payload: dict[str, Any], label: str) -> None:
        url = urljoin(self.settings.auth_api_url + "/", path.lstrip("/"))
        last_error = None
        for attempt in range(2):
            try:
                result = page.evaluate(
                    """async ({url, payload, host}) => {
                        const response = await fetch(url, {
                            method: "POST",
                            credentials: "include",
                            headers: {
                                "Content-Type": "application/json",
                                "Accept": "application/json, text/plain, */*",
                                "Host-Reference": host
                            },
                            body: JSON.stringify(payload || {})
                        });
                        const text = await response.text();
                        return {status: response.status, text: text.slice(0, 160)};
                    }""",
                    {"url": url, "payload": payload, "host": self.settings.host_url},
                )
                self.log(f"{label}: browser {path} {result.get('status')} {result.get('text', '')[:80]}")
                return
            except Exception as exc:
                last_error = exc
                if "Execution context was destroyed" in str(exc) and attempt == 0:
                    page.wait_for_timeout(2000)
                    self._wait_network(page)
                    continue
                break
        self.log(f"{label}: browser {path} error: {last_error}")

    def _wait_for_logout_navigation(self, page: Any, timeout_ms: int) -> bool:
        try:
            page.wait_for_url("**/kde-portal/login**", timeout=min(timeout_ms, 20000))
            self._wait_network(page)
            return True
        except PlaywrightTimeoutError:
            self._wait_network(page)
            page.wait_for_timeout(1500)
            return "/login" in page.url

    def _wait_network(self, page: Any) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=self.settings.page_timeout_seconds * 1000)
        except PlaywrightTimeoutError:
            pass

    def _body_text(self, page: Any) -> str:
        try:
            return page.locator("body").inner_text(timeout=8000)
        except Exception:
            return ""

    def _click_text_if_present(self, page: Any, text: str, timeout_ms: int = 3000) -> bool:
        locator = page.get_by_text(text, exact=True)
        if locator.count() == 0:
            return False
        for idx in range(locator.count()):
            item = locator.nth(idx)
            try:
                if item.is_visible():
                    item.click(timeout=timeout_ms)
                    return True
            except Exception:
                continue
        return False


def run_once_from_config(config_path: str | Path = "config.json", log: LogFn | None = None) -> dict[str, int]:
    settings = load_settings(config_path)
    runner = KdeDownloader(settings, log=log)
    return runner.run_once()


if __name__ == "__main__":
    run_once_from_config()
