"""Source and portable entry point."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-screenshot", type=Path)
    parser.add_argument("--smoke-report", type=Path)
    parser.add_argument("--self-check", type=Path)
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
