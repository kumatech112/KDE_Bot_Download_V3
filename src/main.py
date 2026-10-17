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
    """Retired task actions are harmless even if Windows refuses their removal."""
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-screenshot", type=filesystem_path)
    parser.add_argument("--smoke-report", type=filesystem_path)
    parser.add_argument("--self-check", type=filesystem_path)
    parser.add_argument('--scheduled-cleanup', action='store_true')
    parser.add_argument('--background', action='store_true')
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
    from kde_bot.desktop import DesktopInstance
    from kde_bot.settings import settings_home
    from kde_bot.gui import launch
    instance = DesktopInstance(str(settings_home().resolve()))
    try:
        if instance.existing:
            if not arguments.background:
                instance.notify()
            return 0
        return launch(background=arguments.background, instance=instance)
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
