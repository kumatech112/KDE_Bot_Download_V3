"""Local-only image OCR and bounded email evidence extraction."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from . import legacy_core as core


BANGKOK = timezone(timedelta(hours=7))
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def today() -> str:
    return datetime.now(BANGKOK).date().isoformat()


def ocr_home() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "_internal" / "ocr"
    return Path(os.environ.get("KDE_OCR_HOME", r"C:\Program Files\Tesseract-OCR"))


def correct_reference(text: str) -> str:
    """Correct common OCR account-code errors only inside an account marker."""
    text = core.normalize_thai_digits(text)
    text = re.sub(r"(?i)\bA[1Il][0O][1Il][5S](L?)\b", r"A1015\1", text)
    text = re.sub(r"(?i)\bA[1Il][0O]XX(L?)\b", r"A10XX\1", text)
    return text


def reference_lookup(text: str, source: str) -> dict[str, str]:
    text = correct_reference(text)
    values = core.extract_kde_reference_candidates(text)
    values.extend(core.thai_business_aliases(text))
    for match in re.finditer(core.DEFAULT_MAIL_FILENAME_REGEX, text, re.IGNORECASE):
        values.append(match.group(1) if match.groups() else match.group())
    for line in text.splitlines():
        line = line.strip(" \t|:;•")
        tokens = core.meaningful_tokens_for_match(line)
        if len(line) <= 160 and len(tokens) >= 2 and tokens & {
            "payment", "online", "review", "withdraw", "recovery", "performance", "billcode", "stopac", "vol",
        }:
            values.append(line)
    result = {}
    for value in values:
        value = " ".join(value.split()).strip(" \t|:;'\"")
        key = core.normalize_filename_for_match(value)
        if key and len(key) >= 5:
            result[key] = f"{value} [{source}]"
    return result


class EmbeddedImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []
        self.text: list[str] = []
        self.skip_text = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.skip_text += 1
        if tag.lower() == "img":
            attributes = dict(attrs)
            source = attributes.get("src", "")
            if source.startswith("data:image/") and len(self.images) < 6:
                self.images.append(source)
            alt = attributes.get("alt", "")
            if alt:
                self.text.append(alt[:500])

    def handle_data(self, data):
        if not self.skip_text:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"}:
            self.skip_text = max(0, self.skip_text - 1)


class LocalOCR:
    def __init__(self):
        self.cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def read(self, path: Path) -> dict[str, Any]:
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds the 15 MB limit.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in self.cache:
            self.cache.move_to_end(digest)
            return dict(self.cache[digest])
        executable = ocr_home() / "tesseract.exe"
        if not executable.is_file():
            raise FileNotFoundError("Bundled OCR engine is missing. Reinstall the complete portable folder.")
        with tempfile.TemporaryDirectory(prefix="kde-ocr-") as temporary:
            prepared = Path(temporary) / "image.png"
            with Image.open(path) as image:
                if image.width * image.height > 24_000_000:
                    raise ValueError("Image exceeds the 24 megapixel limit.")
                image = ImageOps.exif_transpose(image).convert("RGB")
                if image.width < 1800:
                    scale = min(2, 1800 / max(image.width, 1))
                    image = image.resize((int(image.width * scale), int(image.height * scale)))
                image.save(prepared)
            environment = os.environ.copy()
            environment["TESSDATA_PREFIX"] = str(ocr_home() / "tessdata")
            result = subprocess.run(
                [str(executable), str(prepared), "stdout", "--tessdata-dir", str(ocr_home() / "tessdata"),
                 "-l", "eng+tha", "--psm", "11", "tsv"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
                env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode:
                raise RuntimeError("Image text recognition failed: " + result.stderr.strip()[:300])
        lines: OrderedDict[tuple[str, ...], list[str]] = OrderedDict()
        confidences = []
        for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
            word = row.get("text", "").strip()
            confidence = float(row.get("conf", "-1"))
            if not word or confidence < 35:
                continue
            key = tuple(row.get(name, "") for name in ("page_num", "block_num", "par_num", "line_num"))
            lines.setdefault(key, []).append(word)
            confidences.append(confidence)
        value = {"text": "\n".join(" ".join(words) for words in lines.values()),
                 "confidence": round(sum(confidences) / len(confidences), 1) if confidences else 0,
                 "sha256": digest}
        self.cache[digest] = value
        while len(self.cache) > 256:
            self.cache.popitem(last=False)
        return dict(value)


class MailEvidenceReader:
    def __init__(self):
        self.ocr = LocalOCR()
        self.cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def read(self, item: Any, subject: str, received: datetime | None) -> dict[str, Any]:
        identity = str(getattr(item, "EntryID", ""))
        changed = str(getattr(item, "LastModificationTime", ""))
        cache_key = f"{today()}|{identity}|{changed}"
        if identity and cache_key in self.cache:
            return self.cache[cache_key]
        result: dict[str, Any] = {"lookup": {}, "notes": [], "image_count": 0, "review": False}
        parser = EmbeddedImages()
        try:
            parser.feed(str(getattr(item, "HTMLBody", "") or "")[:4_000_000])
        except Exception:
            pass
        html_text = "\n".join(parser.text)[:20000]
        result["lookup"].update(reference_lookup(html_text, "Email text"))
        image_texts = []
        with tempfile.TemporaryDirectory(prefix="kde-mail-images-") as temporary:
            images: list[Path] = []
            attachments = getattr(item, "Attachments", None)
            count = min(int(getattr(attachments, "Count", 0)), 30)
            for index in range(1, count + 1):
                attachment = attachments.Item(index)
                name = str(getattr(attachment, "FileName", "") or getattr(attachment, "DisplayName", "") or "")
                suffix = Path(name).suffix.lower()
                if suffix not in IMAGE_SUFFIXES:
                    try:
                        mime = str(attachment.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x370E001F"))
                        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
                                  "image/tiff": ".tiff", "image/bmp": ".bmp", "image/webp": ".webp"}.get(mime.lower(), suffix)
                    except Exception:
                        pass
                if suffix not in IMAGE_SUFFIXES:
                    continue
                if len(images) >= 6:
                    result["notes"].append("Image limit reached; import remaining pictures for review.")
                    result["review"] = True
                    continue
                if int(getattr(attachment, "Size", 0)) > MAX_IMAGE_BYTES:
                    result["notes"].append("An email image exceeded the size limit.")
                    result["review"] = True
                    continue
                path = Path(temporary) / f"attachment-{index}{suffix}"
                try:
                    attachment.SaveAsFile(str(path))
                    images.append(path)
                except Exception as error:
                    result["notes"].append(f"Cannot read email image: {type(error).__name__}")
            for index, data_url in enumerate(parser.images):
                if len(images) >= 6 or len(data_url) > MAX_IMAGE_BYTES * 2:
                    result["notes"].append("Embedded image limit reached; import the image separately.")
                    result["review"] = True
                    break
                try:
                    header, payload = data_url.split(",", 1)
                    if ";base64" not in header:
                        continue
                    image_bytes = base64.b64decode(payload, validate=True)
                    if len(image_bytes) > MAX_IMAGE_BYTES:
                        continue
                    path = Path(temporary) / f"embedded-{index}.png"
                    path.write_bytes(image_bytes)
                    images.append(path)
                except (ValueError, TypeError):
                    result["notes"].append("An embedded image could not be decoded.")
            for path in images:
                result["image_count"] += 1
                try:
                    evidence = self.ocr.read(path)
                    image_texts.append(evidence["text"])
                    keys = reference_lookup(evidence["text"], "Image OCR")
                    if keys and evidence["confidence"] >= 70:
                        result["lookup"].update(keys)
                    elif keys:
                        result["notes"].append("Image text has low confidence; review its reference.")
                        result["review"] = True
                except Exception as error:
                    result["notes"].append(f"Image OCR unavailable: {type(error).__name__}: {error}")
        combined = subject + "\n" + html_text + "\n" + "\n".join(image_texts)
        sides = set(re.findall(r"(?i)\b(pre|post)\b", combined))
        sides = {side.lower() for side in sides}
        if len(sides) == 1:
            result["side"] = sides.pop()
        result["relevant"] = bool(result["lookup"]) or bool(re.search(r"(?i)\bkde\b|krungsri|\bpre\b|\bpost\b", subject))
        if result["relevant"] and not result["lookup"] and (images or result["notes"]):
            result["review"] = True
        if identity:
            self.cache[cache_key] = result
            while len(self.cache) > 512:
                self.cache.popitem(last=False)
        return result

    def screenshot(self, path: Path, side: str) -> dict[str, Any]:
        evidence = self.ocr.read(path)
        lookup = reference_lookup(evidence["text"], "Imported image")
        return {"entry_id": f"image:{today()}:{side}:{evidence['sha256']}", "store_id": "local-image",
                "received": datetime.now(BANGKOK).isoformat(), "subject": f"{side.title()} image: {path.name}",
                "lookup": lookup, "side": side, "relevant": True,
                "review": evidence["confidence"] < 70 or not lookup,
                "notes": [f"Image OCR confidence: {evidence['confidence']}%"], "image_count": 1}
