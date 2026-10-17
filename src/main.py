"""Source and portable entry point."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path


def filesystem_path(value: str) -> Path:
    """Convert PowerShell FileSystem provider paths before pathlib parses them."""
    prefix = re.compile(r"(?i)^(?:Microsoft\.PowerShell\.Core[\\/])?FileSystem::")
    normalized = prefix.sub("", value, count=1)
    if "::" in normalized:
        raise argparse.ArgumentTypeError("Use a Windows file path, not a PowerShell provider path.")
    if not normalized.strip():
        raise argparse.ArgumentTypeError("Enter a non-empty Windows file path.")
    return Path(normalized)


def scheduled_cleanup_entry() -> int:
    """Return task status without opening a GUI or a Python error dialog."""
    from datetime import datetime
    from kde_bot.cleanup_task import on_cleanup_machine
    from kde_bot.cleanup import run_scheduled_cleanup
    from kde_bot.evidence import BANGKOK
    from kde_bot.settings import atomic_json, load_settings, settings_home, validate_settings

    try:
        if not on_cleanup_machine():
            raise RuntimeError('งานลบไฟล์อนุญาตให้ทำงานเฉพาะเครื่อง .97')
        if not (settings_home() / 'settings.json').is_file():
            raise RuntimeError('ไม่พบการตั้งค่าผู้ใช้ จึงไม่ลบไฟล์')
        settings, notices = load_settings()
        if any(notice.startswith('Cannot read settings:') for notice in notices):
            raise RuntimeError('อ่านการตั้งค่าไม่ได้ จึงไม่ลบไฟล์')
        validate_settings(settings, require_credentials=False)
        code = run_scheduled_cleanup(settings)
        reason = 'จบการทำงานตามนโยบาย 22:00' if code == 0 else 'ลบไฟล์ไม่ครบ กรุณาดูประวัติการทำงาน'
    except Exception as error:
        code = 1
        reason = f'{type(error).__name__}: {error}'
    try:
        atomic_json(settings_home() / 'cleanup_task_result.json',
                    {'time': datetime.now(BANGKOK).isoformat(), 'exit_code': code, 'reason': reason})
    except OSError:
        pass  # Preserve the nonzero task exit status even when its local report is unavailable.
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-screenshot", type=filesystem_path)
    parser.add_argument("--smoke-report", type=filesystem_path)
    parser.add_argument("--self-check", type=filesystem_path)
    parser.add_argument('--scheduled-cleanup', action='store_true')
    arguments = parser.parse_args()
    if arguments.scheduled_cleanup:
        return scheduled_cleanup_entry()
    if arguments.self_check:
        from kde_bot.selfcheck import run_self_check
        return run_self_check(arguments.self_check)
    if arguments.smoke_screenshot:
        # A smoke run never reads or writes the user's real configuration.
        with tempfile.TemporaryDirectory(prefix="kde-v3-gui-check-") as temporary:
            os.environ["KDE_V3_HOME"] = temporary
            from kde_bot.gui import launch
            return launch(arguments.smoke_screenshot, arguments.smoke_report)
    from kde_bot.gui import launch
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
