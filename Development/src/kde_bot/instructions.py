"""Bounded email instructions, separate from portal and credential handling."""

from __future__ import annotations

import re

from . import legacy_core as core


MARKER = re.compile(r"(?i)(?<![a-z0-9])(?:a[0-9x]{4}l?|l10xx|1015)(?![a-z0-9])")
BUSINESS_WORDS = {core.TOKEN_ALIASES.get(word, word) for word in core.BODY_HINT_TOKENS} | {
    "billcode", "stopac", "vol", "results",
}
INSTRUCTION = re.compile(
    r"(?i)\b(?:download|retrieve|use|load|get|file\s*name)\b|(?:ดาวน์โหลด|ดาวโหลด|ให้โหลด|โหลดไฟล์|ใช้ไฟล์|ให้ใช้|ชื่อไฟล์)"
)
NOISE = core.STOP_MATCH_TOKENS | {
    "download", "downloads", "retrieve", "use", "using", "load", "get", "named", "name",
    "called", "following", "available", "ready", "kde", "portal", "pre", "post", "company",
    "code", "keyword", "account", "instead", "now", "only", "here", "thank", "thanks",
    "regards", "today", "zip", "gpg", "pgp", "xlsx", "xls", "csv", "txt", "rar", "7z", "xxxxxx", "xxxxxxxx",
    "be", "informed", "need", "needs", "needed", "must", "should", "these", "those", "below", "listed",
}


def current_body(text: str) -> str:
    """Ignore quoted older messages when choosing the current sender's instruction."""
    lines = []
    for line in str(text)[:20000].splitlines():
        if re.match(r"(?i)^\s*(?:from:|จาก:|on .+wrote:|-{3,}\s*(?:original|forwarded)|_{5,})", line):
            break
        lines.append(line)
    return "\n".join(lines)


def normalize_template_markers(text: str) -> str:
    """Generic company templates do not, by themselves, identify Pre or Post."""
    text = core.normalize_thai_digits(text)
    text = re.sub(r"(?i)(?<![a-z0-9])(?:ax{4}l?|l10xx)(?![a-z0-9])", "1015", text)
    return core.normalize_account_wildcards_for_match(text)


def instruction_lookup(text: str) -> dict[str, str]:
    """Extract named business words and numbers, never a company code alone."""
    result = {}
    for line in re.split(r"[\n;]+|\s+/\s+", current_body(text)):
        if len(line) > 500 or core.is_ignored_body_text(line):
            continue
        if re.search(r"(?i)\b(?:do not|don't|cancel)\b|ไม่ต้อง|ห้าม|ยกเลิก", line):
            continue
        normalized = normalize_template_markers(line)
        tokens = core.meaningful_tokens_for_match(normalized)
        if not tokens & BUSINESS_WORDS:
            continue
        # A complete filename is retained verbatim with its date and split suffix.
        filenames = re.findall(core.DEFAULT_MAIL_FILENAME_REGEX, normalized, re.IGNORECASE)
        if filenames:
            references = [value if isinstance(value, str) else value[0] for value in filenames]
        else:
            pieces = re.findall(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", normalized)
            references = [" ".join(piece for piece in pieces if piece.lower() not in NOISE)]
        for reference in references:
            business = core.meaningful_tokens_for_match(MARKER.sub(" ", reference)) - NOISE
            if not business & BUSINESS_WORDS:
                continue
            key = core.normalize_filename_for_match(reference)
            if key:
                source = "Email instruction" if INSTRUCTION.search(line) else "Email body words"
                result[key] = f"{reference} [{source}]"
    return result


def instruction_match(kde_key: str, mail_key: str, original: str) -> dict | None:
    """Match partial body references using all words and exact business numbers."""
    if not any(source in original for source in ("[Email instruction]", "[Email body words]")):
        return None
    if not core.account_sides_are_compatible(mail_key, kde_key) or not core.business_dates_are_compatible(mail_key, kde_key):
        return None
    if not own_company_compatible(kde_key, mail_key):
        return None
    reference = MARKER.sub(" ", normalize_template_markers(mail_key))
    candidate = MARKER.sub(" ", kde_key)
    requested = core.meaningful_tokens_for_match(reference) - NOISE
    available = core.meaningful_tokens_for_match(candidate) - NOISE
    if not requested & BUSINESS_WORDS or not requested <= available:
        return None
    # PAYMENT alone must not silently select PAYMENT ONLINE.
    if "payment" in requested and "online" not in requested and "online" in available:
        return None
    numeric_reference = re.sub(
        r"(?i)(?<![a-z0-9])(?:\d{6}|\d{8}|\d{1,2}[_/-]\d{1,2}[_/-]\d{4}|"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[_ -]?(?:\d{4}|\d{2}))(?![a-z0-9])",
        lambda match: " " if any(core.normalized_business_dates(match.group())) else match.group(), reference,
    )
    required_numbers = set(re.findall(r"\d+", numeric_reference))
    available_numbers = set(re.findall(r"\d+", candidate))
    if not required_numbers <= available_numbers:
        return None
    if core.split_volume_part(mail_key) and core.split_volume_part(mail_key) != core.split_volume_part(kde_key):
        return None
    return {"mail_key": mail_key, "original": original, "score": 75, "precise": False,
            "source_priority": 5, "body_instruction": True}


def own_company_compatible(*references: str) -> bool:
    for reference in references:
        companies = {marker.lower() for marker in MARKER.findall(normalize_template_markers(reference))
                     if marker.lower().startswith("a")}
        if companies and not companies <= {"a1015", "a1015l"}:
            return False
    return True
