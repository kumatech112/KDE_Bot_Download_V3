"""Thai user-facing labels and readable translations of retained engine messages."""

from __future__ import annotations

import re


THAI = {
    "Ready": "พร้อมใช้งาน", "No requests yet": "ยังไม่มีรอบดาวน์โหลด", "0 events": "0 รายการ",
    "Setup required": "กรุณาตั้งค่าก่อนเริ่ม", "Start monitor": "เริ่มทำงาน", "Stop": "หยุด",
    "Stopped": "หยุดทำงานแล้ว", "Round details": "รายละเอียดรอบงาน", "Request download round": "สั่งดาวน์โหลด",
    "Tools": "เครื่องมือ", "Check connection": "ตรวจสอบการเชื่อมต่อ", "Repair pending saves": "บันทึกไฟล์ที่ค้างอีกครั้ง",
    "Import settings": "นำเข้าการตั้งค่า", "Import old history": "นำเข้าประวัติเดิม", "Open logs": "เปิดโฟลเดอร์ประวัติ",
    "Monitor": "การทำงาน", "History": "ประวัติการทำงาน", "Settings": "ตั้งค่า", "Account": "บัญชี",
    "Download round": "รอบดาวน์โหลด", "Status": "สถานะ", "Wait": "เวลารอ", "Attempts": "เข้าสู่ระบบ",
    "Result": "ผลการทำงาน", "Refresh": "โหลดประวัติใหม่", "Follow latest": "เลื่อนไปรายการล่าสุด",
    "Search": "ค้นหา", "Time": "วัน / เวลา", "Action": "การทำงาน", "File / email": "ชื่อไฟล์",
    "Details": "รายละเอียด", "Details:": "รายละเอียด:", "Destination:": "ปลายทาง:",
    "Show password": "แสดงรหัสผ่าน", "Browse": "เลือกโฟลเดอร์", "Outlook mailbox": "กล่องเมล Outlook",
    "Save to": "การจัดเก็บ", "Original destination": "โฟลเดอร์คัดลอก .243", "New destination": "โฟลเดอร์ดาวน์โหลด .97",
    "Log folder": "โฟลเดอร์ประวัติ", "Enabled": "เปิดใช้งาน", "Username": "ชื่อผู้ใช้", "Password": "รหัสผ่าน",
    "Save & start": "บันทึกและเริ่มทำงาน", "More options": "ตัวเลือกเพิ่มเติม", "Apply": "นำไปใช้",
    "Incoming folder (optional)": "โฟลเดอร์เมลย่อย (ถ้ามี)", "Outlook poll (seconds)": "ตรวจเมลทุก (วินาที)",
    "Messages per folder": "จำนวนเมลที่ตรวจต่อโฟลเดอร์", "Portal page limit": "ขอบเขตตรวจสอบหน้าเว็บ",
    "Page timeout (seconds)": "เวลารอหน้าเว็บ (วินาที)", "Delay between files (seconds)": "พักระหว่างดาวน์โหลด (วินาที)",
    "Browser path (optional)": "ตำแหน่งเบราว์เซอร์ (ถ้ามี)", "Invalid option": "ตัวเลือกไม่ถูกต้อง",
    "Cannot save": "บันทึกการตั้งค่าไม่ได้", "Saved for this Windows user.": "บันทึกการตั้งค่าสำหรับผู้ใช้ Windows นี้แล้ว",
    "Stop first": "กรุณาหยุดงานก่อน", "Stop the monitor before changing settings.": "กรุณาหยุดการทำงานก่อนเปลี่ยนการตั้งค่า",
    "Import KDE settings": "นำเข้าการตั้งค่า KDE", "Import failed": "นำเข้าไม่สำเร็จ",
    "Import old KDE history": "นำเข้าประวัติ KDE เดิม", "Stop the monitor before importing history.": "กรุณาหยุดการทำงานก่อนนำเข้าประวัติ",
    "Imported. Check the accounts, then Save & start.": "นำเข้าแล้ว กรุณาตรวจสอบบัญชีแล้วกดบันทึกและเริ่มทำงาน",
    "Download round details": "รายละเอียดรอบดาวน์โหลด", "Stop before repairing pending saves.": "กรุณาหยุดก่อนบันทึกไฟล์ที่ค้างอีกครั้ง",
    "Cannot start": "เริ่มทำงานไม่ได้", "Starting monitor": "กำลังเริ่มทำงาน", "Checking": "กำลังตรวจสอบ",
    "Stopping — finishing the current save and logout": "กำลังหยุด รอให้บันทึกไฟล์และออกจากระบบเสร็จก่อน",
    "Work": "การทำงาน", "System": "ระบบ", "Destination": "ปลายทาง", "Machine": "เครื่อง", "Run": "รอบงาน",
    "Work details": "รายละเอียดการทำงาน", "Cannot open logs": "เปิดโฟลเดอร์ประวัติไม่ได้",
    "Working": "กำลังทำงาน", "OK": "สำเร็จ", "Done": "เสร็จแล้ว", "Already saved": "มีไฟล์แล้ว",
    "Save pending": "รอบันทึกไฟล์", "Failed": "ผิดพลาด", "Needs review": "ต้องตรวจสอบ", "Queued": "รอทำงาน",
    "Info": "ข้อมูล", "Waiting for new email": "รอเมลใหม่", "Previous day": "ข้ามงานวันก่อน", "Account busy": "บัญชีมีผู้ใช้งาน",
    "Accounts are encrypted for this Windows user. Save once, then monitoring starts automatically.": "รหัสผ่านถูกเข้ารหัสสำหรับผู้ใช้ Windows นี้ เมื่อตั้งค่าครบ โปรแกรมจะเริ่มทำงานอัตโนมัติ",
    "Setup required — enter the enabled account credentials": "กรุณากรอกชื่อผู้ใช้และรหัสผ่านของบัญชีที่เปิดใช้งาน",
    "Checking this Windows user's environment": "กำลังตรวจสอบการตั้งค่าและสิทธิ์ของผู้ใช้ Windows นี้",
    "Preparing an isolated account session": "กำลังเปิดเบราว์เซอร์สำหรับบัญชีนี้",
    "Logging in to KDE": "กำลังเข้าสู่ระบบ KDE", "Login succeeded": "เข้าสู่ระบบสำเร็จ",
    "Matching portal files against email evidence": "กำลังเปิดรายการไฟล์ KDE ของวันนี้",
    "Logout and session cleanup completed": "ออกจากระบบและปิดเบราว์เซอร์แล้ว", "No KDE session was opened": "ยังไม่ได้เข้าสู่ระบบ KDE",
    "Checking existing files and history": "กำลังตรวจสอบไฟล์ที่บันทึกไว้",
    "Downloading from KDE to local staging": "กำลังดาวน์โหลดไฟล์จาก KDE",
    "Saving and verifying the final destination file": "กำลังบันทึกและตรวจสอบไฟล์ปลายทาง",
    "Saved and verified at all selected destinations": "บันทึกและตรวจสอบไฟล์ครบตามปลายทางแล้ว",
    "Already saved; SHA-256 verified at all destinations": "มีไฟล์แล้ว ตรวจสอบข้อมูลตรงกัน",
    "Pending-save repair finished": "บันทึกไฟล์ที่ค้างเสร็จแล้ว", "Stopped; account sessions closed": "หยุดทำงานและปิดบัญชีแล้ว",
    "Daily download round finished": "เสร็จรอบดาวน์โหลด รอเมลใหม่", "Stopped; attempts retained.": "หยุดทำงาน เก็บสถานะเดิมไว้",
    "Own-session logout could not be confirmed.": "ยังยืนยันการออกจากบัญชีของโปรแกรมไม่ได้ กรุณาตรวจสอบ",
    "Classic Outlook and pywin32 are required on this computer.": "เครื่องนี้ต้องมี Outlook แบบคลาสสิกและส่วนเชื่อมต่อ Outlook",
    "Configured data mailbox was not found in classic Outlook.": "ไม่พบกล่องเมล data ที่ตั้งค่าไว้ใน Outlook แบบคลาสสิก",
    "Email-triggered monitoring must remain enabled.": "ต้องเปิดการทำงานตามเมลใหม่ไว้",
    "Choose a separate Log folder outside the download destinations.": "กรุณาแยกโฟลเดอร์ประวัติออกจากโฟลเดอร์ดาวน์โหลด",
    "Enable at least one KDE account.": "กรุณาเปิดใช้งานอย่างน้อยหนึ่งบัญชี KDE",
    "Pre and Post must have different usernames.": "บัญชี Pre และ Post ต้องใช้ชื่อผู้ใช้ต่างกัน",
    "Date changed; this file will not be downloaded": "วันที่เปลี่ยนแล้ว จึงไม่ดาวน์โหลดไฟล์ของวันก่อน",
    "Unsafe portal filename; download refused": "ชื่อไฟล์บนเว็บไม่เหมาะสำหรับบันทึก จึงข้ามไฟล์นี้",
    "Previous-day sweep stopped; only today's files may download.": "หยุดรอบของวันก่อน ดาวน์โหลดได้เฉพาะไฟล์ของวันนี้",
    "Account removed or disabled in Settings.": "บัญชีนี้ถูกปิดใช้งานหรือนำออกจากการตั้งค่าแล้ว",
    "An existing empty file or directory needs attention; it was preserved.": "พบไฟล์ว่างหรือโฟลเดอร์ชื่อเดียวกัน กรุณาตรวจสอบ โดยโปรแกรมจะไม่เขียนทับ",
    "Outlook did not provide a stable mail ID.": "Outlook ไม่ได้ส่งรหัสเมลที่ใช้ตรวจรายการซ้ำได้",
}


def thai_text(value):
    text = str(value)
    if text in THAI:
        return THAI[text]
    patterns = (
        (r"^(.*): login attempt (\d+)$", r"\1: เข้าสู่ระบบครั้งที่ \2"),
        (r"^Saved (\d+), already saved (\d+), unrequested (\d+), failed (\d+)$", r"ดาวน์โหลด \1 มีไฟล์แล้ว \2 ข้าม \3 ผิดพลาด \4"),
        (r"^Today's files checked: (\d+); saved (\d+), already present (\d+)\.$", r"ตรวจไฟล์ของวันนี้ \1 รายการ ดาวน์โหลด \2 มีไฟล์แล้ว \3"),
        (r"^(\d+) files could not be saved; see History for filenames and reasons\.$", r"มี \1 ไฟล์บันทึกไม่สำเร็จ ดูชื่อไฟล์และสาเหตุในประวัติการทำงาน"),
    )
    for pattern, replacement in patterns:
        if re.match(pattern, text):
            return re.sub(pattern, replacement, text)
    replacements = {
        "Cannot check or save this file: ": "ตรวจสอบหรือบันทึกไฟล์นี้ไม่ได้: ",
        "Cannot read incoming mail in ": "อ่านเมลขาเข้าไม่ได้ใน ",
        "Cannot enumerate incoming folders in ": "อ่านรายการโฟลเดอร์เมลไม่ได้ใน ",
        "Configured incoming folder was not found: ": "ไม่พบโฟลเดอร์เมลที่กำหนด: ",
        "Cannot check the destination root: ": "เข้าถึงโฟลเดอร์ปลายทางไม่ได้: ",
        "credentials rejected or account locked. Stop, update Settings, then restart.": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง หรือบัญชีถูกล็อก กรุณาหยุดและแก้ไขการตั้งค่า",
        "is already in use; wait without forcing sign-out.": "มีผู้ใช้งานอยู่ รออีก 1 นาทีโดยไม่บังคับออกจากระบบ",
        "enter the KDE username and password for this machine.": "กรุณากรอกชื่อผู้ใช้และรหัสผ่านสำหรับเครื่องนี้",
        "KDE user is already in use.": "บัญชี KDE มีผู้ใช้งานอยู่",
        "Log write check passed": "ตรวจสิทธิ์โฟลเดอร์ประวัติผ่าน",
        "; destinations readable. No test files created; save access is checked during real delivery.": "; อ่านโฟลเดอร์ปลายทางได้ ไม่สร้างไฟล์ทดสอบ และตรวจสิทธิ์บันทึกเมื่อดาวน์โหลดจริง",
        "Access denied while saving the final file": "ไม่มีสิทธิ์บันทึกไฟล์ปลายทาง",
        "Permission denied": "ไม่มีสิทธิ์เข้าถึง", "Access is denied": "ไม่มีสิทธิ์เข้าถึง",
        "Browser ready: ": "เบราว์เซอร์พร้อมใช้งาน: ",
        "Portal page limit reached before a complete match check; no files downloaded. Increase the page limit.": "เวอร์ชันเดิมอ่านรายการถึงขอบเขตจำนวนหน้าก่อนตรวจครบ จึงยังไม่ได้ดาวน์โหลดไฟล์",
        "An existing empty file or directory needs attention; it was preserved: ": "พบไฟล์ว่างหรือโฟลเดอร์ชื่อเดียวกัน โปรแกรมไม่เขียนทับ: ",
        "Logout requires attention: ": "กรุณาตรวจสอบการออกจากระบบ: ",
        "Destination appeared during delivery; no overwrite: ": "มีไฟล์ปลายทางถูกสร้างขึ้นระหว่างบันทึก โปรแกรมไม่เขียนทับ: ",
        "Cannot save downloaded file: ": "บันทึกไฟล์ดาวน์โหลดไม่ได้: ",
    }
    for original, translated in replacements.items():
        text = text.replace(original, translated)
    return text
