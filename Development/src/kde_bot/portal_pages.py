"""Verified 30-row controls and forward-only, page-at-a-time KDE downloads."""

from __future__ import annotations

import math
import re
import time


PAGINATORS = "mat-paginator, .mat-paginator, .mat-mdc-paginator, .MuiTablePagination-root, [data-kde-pagination]"
NEXT_BUTTONS = ("button[aria-label='Go to next page']", "button[title='Go to next page']",
                "button[aria-label='Next page']", "button[aria-label='หน้าถัดไป']",
                "button.mat-paginator-navigation-next", "button.mat-mdc-paginator-navigation-next")


def pagination_scope(page):
    scopes = page.locator(PAGINATORS)
    if scopes.count():
        return scopes.first
    labels = page.get_by_text(re.compile(r"^(?:จำนวนแถวต่อ\s*(?:1\s*)?หน้า|Rows per page:?)$", re.I))
    return labels.first.locator("xpath=..") if labels.count() else None


def page_range(page):
    scope = pagination_scope(page)
    if scope is None:
        return None
    found = re.search(r"([\d,]+)\s*[-–]\s*([\d,]+)\s*(?:จาก|of)\s*([\d,]+)", scope.inner_text(), re.I)
    return tuple(int(value.replace(",", "")) for value in found.groups()) if found else None


def next_button(page):
    for selector in NEXT_BUTTONS:
        buttons = page.locator(selector)
        if buttons.count():
            button = buttons.first
            if button.is_enabled() and button.get_attribute("aria-disabled") != "true":
                return button
    return None


def wait_ready(engine, page, timeout_ms, changed_from=None):
    deadline = time.monotonic() + min(engine.settings.page_timeout_seconds, timeout_ms / 1000)
    previous = None
    since = None
    while time.monotonic() < deadline and not engine.stop_event.is_set():
        signature = engine._table_signature(page, allow_empty=True)
        if signature and (changed_from is None or signature != changed_from):
            if signature != previous:
                previous, since = signature, time.monotonic()
            elif time.monotonic() - since >= 0.45:
                return True
        else:
            previous, since = None, None
        page.wait_for_timeout(100)
    if engine.stop_event.is_set():
        return False
    raise RuntimeError("ตารางไฟล์ยังไม่พร้อมหรือไม่เปลี่ยนหน้า จึงหยุดก่อนกดดาวน์โหลดผิดรายการ")


def set_page_size(engine, page, timeout_ms):
    scope = pagination_scope(page)
    controls = scope.locator("select, [role='combobox'], [role='button'][aria-haspopup='listbox']") if scope is not None else None
    if controls is None or not controls.count():
        if next_button(page) is not None:
            raise RuntimeError("ไม่พบช่องจำนวนแถวต่อหน้า กรุณาตรวจสอบหน้ารายการ KDE")
        # A genuine single-page list may omit its paginator entirely.
        if len(engine._table_rows(page)) > 30:
            raise RuntimeError("หน้า KDE แสดงเกิน 30 แถวแต่ไม่พบช่องปรับจำนวนแถว")
        return wait_ready(engine, page, timeout_ms)
    control = controls.first
    initial_range = page_range(page)
    if initial_range and initial_range[0] > 1:
        first = page.locator("button[aria-label='Go to first page'], button[aria-label='First page'], button[aria-label='หน้าแรก'], button.mat-paginator-navigation-first, button.mat-mdc-paginator-navigation-first")
        if not first.count() or not first.first.is_enabled():
            raise RuntimeError("KDE ไม่ได้เริ่มที่หน้าแรกและไม่พบปุ่มกลับหน้าแรก")
        before_first = engine._table_signature(page, allow_empty=True)
        first.first.click(timeout=timeout_ms)
        if not wait_ready(engine, page, timeout_ms, before_first):
            return False
    native = control.evaluate("element => element.tagName === 'SELECT'")
    current = control.evaluate("element => element.tagName === 'SELECT' ? (element.selectedOptions[0]?.textContent || '') : (element.innerText || '')").strip()
    before = engine._table_signature(page, allow_empty=True)
    old_range = page_range(page)
    if current != "30":
        if native:
            control.select_option(label="30", timeout=timeout_ms)
        else:
            control.click(timeout=timeout_ms)
            page.get_by_role("option", name="30", exact=True).click(timeout=timeout_ms)
    selected = control.evaluate("element => element.tagName === 'SELECT' ? (element.selectedOptions[0]?.textContent || '') : (element.innerText || '')").strip()
    if selected != "30":
        raise RuntimeError("ตั้งจำนวนแถวต่อหน้าเป็น 30 ไม่สำเร็จ")
    changed = before if current != "30" and old_range and old_range[2] > 15 else None
    if not wait_ready(engine, page, timeout_ms, changed):
        return False
    current_range = page_range(page)
    if current_range and current_range[1] - current_range[0] + 1 > 30:
        raise RuntimeError("หน้า KDE ไม่ยอมใช้จำนวน 30 แถวตามที่ตั้งไว้")
    if current_range and current_range[2] > 30 and current_range[1] - current_range[0] + 1 != 30:
        raise RuntimeError("ตาราง KDE ยังแสดงจำนวนแถวไม่ครบหลังเปลี่ยนเป็น 30")
    engine.reporter.emit(4, "stage_complete", "ตั้งจำนวนแถวต่อหน้าเป็น 30 แล้ว", engine.account)
    return True


def newest_first(engine, page, timeout_ms):
    """Select descending portal date order when the table exposes a sort control."""
    headers = page.locator("th, [role='columnheader']").filter(has_text=re.compile(r"^(?:วัน\s*เวลา|วันที่(?:\s*/\s*เวลา)?|Date(?:\s*(?:/|and)?\s*Time)?)$", re.I))
    if not headers.count():
        return
    header = headers.first
    sortable = header.get_attribute("aria-sort") is not None or header.locator("button, .mat-sort-header-container, [role='button']").count()
    if not sortable:
        return
    for _attempt in range(3):
        if header.get_attribute("aria-sort") == "descending":
            return
        header.click(timeout=timeout_ms)
        if not wait_ready(engine, page, timeout_ms):
            return
    if header.get_attribute("aria-sort") != "descending":
        raise RuntimeError("ตั้งคอลัมน์วันเวลาเป็นใหม่ไปเก่าไม่สำเร็จ จึงไม่ไล่ตรวจหน้าข้อมูลเก่า")


def check_date_order(rows, previous_day=None):
    """Reject visible ascending/mixed dates before using the older-date boundary."""
    from .daily_download import portal_day

    dates = [day for _index, row in rows if (day := portal_day(row)) is not None]
    sequence = ([previous_day] if previous_day else []) + dates
    if any(left < right for left, right in zip(sequence, sequence[1:])):
        raise RuntimeError("วันเวลาใน KDE ไม่เรียงจากใหม่ไปเก่า กรุณาเรียงคอลัมน์วันเวลาใหม่ก่อนเริ่ม ไม่ไล่ตรวจทุกหน้าหรือข้ามไฟล์โดยเดา")
    if rows and not dates:
        raise RuntimeError("อ่านวันที่ในหน้ารายการ KDE ไม่ได้ จึงหยุดโดยไม่ไล่ตรวจหน้าข้อมูลเก่า")
    return dates


def download_pages(engine, page, account, timeout_ms):
    from .daily_download import portal_day, today

    result = {"downloaded": 0, "skipped": 0, "not_requested": 0, "errors": 0}
    if not set_page_size(engine, page, timeout_ms):
        return result
    newest_first(engine, page, timeout_ms)
    processed = set()
    visited = set()
    previous_day = None
    initial_range = page_range(page)
    # A retained small matching-catalogue limit must not block today's downloads.
    budget = max(50, engine.settings.max_pages, math.ceil(initial_range[2] / 30) + 2 if initial_range else 0)
    for page_number in range(1, budget + 1):
        if engine.stop_event.is_set() or today() != engine.work_day:
            return result
        rows = engine._table_rows(page)
        check_date_order(rows, previous_day)
        current = rows
        fingerprint = tuple((row["filename"], row.get("file_time", ""), row.get("size_text", "")) for _index, row in rows)
        if fingerprint in visited and fingerprint:
            raise RuntimeError("KDE แสดงข้อมูลหน้าเดิมซ้ำ จึงหยุดเพื่อไม่วนดาวน์โหลด")
        visited.add(fingerprint)
        engine.reporter.emit(4, "running", f"กำลังดาวน์โหลดไฟล์ของวันนี้จากหน้า {page_number} ทีละรายการ", account.label)
        while not engine.stop_event.is_set() and today() == engine.work_day:
            current = engine._table_rows(page)
            check_date_order(current, previous_day)
            candidate = next(((index, row) for index, row in current
                              if portal_day(row) == engine.work_day and row["filename"].casefold() not in processed), None)
            if candidate is None:
                break
            row_index, row = candidate
            processed.add(row["filename"].casefold())
            engine.eligible += 1
            status = engine.handle_file(page, row_index, row, account, timeout_ms)
            result["downloaded" if status == "complete" else "skipped" if status == "skipped" else "errors"] += 1
            if status != "skipped" and engine.stop_event.wait(engine.settings.download_delay_seconds):
                return result
        engine.rejected_dates += sum(portal_day(row) != engine.work_day for _index, row in current)
        engine.reporter.emit(4, "stage_complete", f"เสร็จหน้า {page_number}: ดาวน์โหลด {result['downloaded']} มีไฟล์แล้ว {result['skipped']} ต่างวันหรือวันที่ไม่ชัดเจน {engine.rejected_dates} ผิดพลาด {result['errors']}", account.label)
        dates = check_date_order(current, previous_day)
        if any(day < engine.work_day for day in dates):
            engine.reporter.emit(4, "stage_complete", "ตรวจไฟล์วันนี้ครบถึงขอบเขตวันที่เก่าแล้ว หยุดโดยไม่เปิดหน้าประวัติย้อนหลัง", account.label)
            return result
        if dates:
            previous_day = dates[-1]
        remaining = page_range(page)
        if remaining and remaining[1] >= remaining[2]:
            return result
        button = next_button(page)
        if button is None:
            if remaining and remaining[1] < remaining[2]:
                raise RuntimeError("รายการยังไม่ถึงหน้าสุดท้าย แต่ไม่พบปุ่มหน้าถัดไปที่ใช้งานได้ ไฟล์ที่โหลดแล้วถูกเก็บไว้")
            return result
        before = engine._table_signature(page, allow_empty=True)
        button.click(timeout=timeout_ms)
        if not wait_ready(engine, page, timeout_ms, before):
            return result
    raise RuntimeError("จำนวนหน้าของ KDE เกินขอบเขตที่ตรวจสอบได้ ไฟล์ที่ดาวน์โหลดสำเร็จแล้วถูกเก็บไว้ใน .97")
