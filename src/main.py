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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-screenshot", type=filesystem_path)
    parser.add_argument("--smoke-report", type=filesystem_path)
    parser.add_argument("--self-check", type=filesystem_path)
    arguments = parser.parse_args()
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
