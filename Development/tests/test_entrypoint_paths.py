"""PowerShell provider prefixes must never reach pathlib directory creation."""

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from main import filesystem_path, main


@pytest.mark.parametrize("prefix", [
    "Microsoft.PowerShell.Core\\FileSystem::", "FileSystem::", "filesystem::",
    "Microsoft.PowerShell.Core/FileSystem::",
])
def test_provider_unc_preserves_double_backslash(prefix):
    target = r"\\10.0.0.97\kumashare\Z AI\Projects\KDE_Bot_Download_V3\docs\verification\check.json"
    assert filesystem_path(prefix + target) == Path(target)
    assert str(filesystem_path(prefix + target)).startswith("\\\\")


@pytest.mark.parametrize("target", [r"D:\verification\check.json", r"\\server\share\check.json", "check.json"])
def test_plain_paths_remain_unchanged(target):
    assert filesystem_path(target) == Path(target)
    assert filesystem_path("FileSystem::" + target) == Path(target)


@pytest.mark.parametrize("target", ["FileSystem::", "", "Registry::HKLM\\Software", "OtherProvider::value"])
def test_empty_and_non_filesystem_paths_are_rejected(target):
    with pytest.raises(argparse.ArgumentTypeError):
        filesystem_path(target)


def test_entrypoint_passes_converted_report_to_selfcheck_without_running_app():
    target = r"\\10.0.0.97\kumashare\Z AI\Projects\KDE_Bot_Download_V3\docs\verification\check.json"
    with patch("sys.argv", ["KDE", "--self-check", "Microsoft.PowerShell.Core\\FileSystem::" + target]), \
            patch("kde_bot.selfcheck.run_self_check", return_value=0) as check:
        assert main() == 0
    check.assert_called_once_with(Path(target))
