"""Build locally, then publish a clean, isolated portable directory to this project."""

from __future__ import annotations

import hashlib
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
NAME = "KDE Bot Download V3"




def source_version() -> str:
    module = ast.parse((ROOT / "src/kde_bot/__init__.py").read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError("Missing application VERSION")


def main() -> int:
    builder_root = Path(os.environ.get("KDE_BUILD_HOME", tempfile.gettempdir()))
    builder_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(builder_root).free < 1024 * 1024 * 1024:
        raise OSError("Need at least 1 GiB free in the local builder; set KDE_BUILD_HOME to a local drive with space")
    local = Path(tempfile.mkdtemp(prefix="kde-v3-build-", dir=builder_root))
    source = local / "source"
    shutil.copytree(ROOT / "src", source, ignore=shutil.ignore_patterns("__pycache__"))
    icon = local / "app.ico"
    shutil.copy2(ROOT / "assets/app.ico", icon)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed",
        "--noupx", "--name", NAME, "--icon", str(icon),
        "--add-data", str(icon) + ";assets",
        "--paths", str(source), "--distpath", str(local / "dist"),
        "--workpath", str(local / "build"), "--specpath", str(local),
        "--collect-all", "playwright", "--collect-all", "greenlet",
        "--hidden-import", "win32timezone", "--hidden-import", "win32crypt",
        "--hidden-import", "win32com.client", "--hidden-import", "pythoncom",
        "--hidden-import", "PIL.ImageGrab",
    ]
    for module in ("PyQt5", "PyQt6", "PySide2", "PySide6", "shiboken6",
                   "numpy", "pandas", "matplotlib", "IPython", "pytest"):
        command.extend(["--exclude-module", module])
    command.append(str(source / "main.py"))
    build_log = local / "build.log"
    with build_log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=local, stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"PyInstaller failed: {build_log}")
    distribution = local / "dist" / NAME
    browser_source = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright/chromium_headless_shell-1169/chrome-win"
    if not (browser_source / "headless_shell.exe").is_file():
        raise FileNotFoundError("Install the pinned browser: python -m playwright install chromium-headless-shell")
    browser_destination = distribution / "_internal/chromium_headless_shell"
    shutil.copytree(browser_source, browser_destination, ignore=shutil.ignore_patterns("debug.log"))
    powershell_environment = os.environ.copy()
    powershell_environment["PSModulePath"] = str(
        Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/Modules"
    )
    subprocess.run([
        str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(ROOT / "tools/patch_windows_gui_subsystem.ps1"),
        "-ExecutablePath", str(browser_destination / "headless_shell.exe"),
    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW, env=powershell_environment)
    driver = distribution / "_internal/playwright/driver"
    os.rename(driver / "node.exe", driver / "node-console.exe")
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([
        str(compiler), "/nologo", "/target:winexe", "/optimize+", "/platform:anycpu",
        f"/out:{driver / 'node.exe'}", str(ROOT / "tools/playwright_node_gui_launcher.cs"),
    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    shutil.copy2(ROOT / "docs/QUICK_START.md", distribution / "Quick start.md")
    destination = ROOT / "portable"
    if destination.exists():
        if any(destination.iterdir()):
            destination = ROOT / ("portable-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        else:
            destination.rmdir()
    shutil.copytree(distribution, destination)
    executable = destination / f"{NAME}.exe"
    evidence = {
        "status": "built", "version": source_version(), "exe": str(executable),
        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "local_build": str(local), "build_log": str(build_log),
        "bundled_browser": True, "bundled_ocr": False, "contains_credentials": False,
        "icon_sha256": hashlib.sha256(icon.read_bytes()).hexdigest(),
    }
    verification = ROOT / "docs/verification"
    verification.mkdir(parents=True, exist_ok=True)
    (verification / "build.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
