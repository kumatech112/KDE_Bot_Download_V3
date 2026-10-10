"""Promote a tested KDE release and remove only explicitly identified old bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EXE = "KDE Bot Download V3.exe"
ALLOWED_TOP_LEVEL = {EXE, "_internal", "คู่มือเริ่มใช้งาน.md"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_bundle(path: Path, expected_hash: str) -> Path:
    resolved = path.resolve(strict=True)
    if resolved.parent != ROOT.resolve() or resolved.name not in {"portable", ".previous-portable"} and not re.fullmatch(r"portable-\d{8}-\d{6}", resolved.name):
        raise ValueError("Bundle must be a directly contained KDE portable directory")
    if {item.name for item in resolved.iterdir()} != ALLOWED_TOP_LEVEL:
        raise ValueError("Unexpected files in portable; preserve them before replacing the release")
    if digest(resolved / EXE) != expected_hash.casefold():
        raise ValueError("Executable differs from the explicitly identified bundle")
    for item in [resolved, *resolved.rglob("*")]:
        if item.is_symlink() or item.is_junction():
            raise ValueError("Refuse cleanup of bundles containing links or junctions")
        if item != resolved and not item.resolve().is_relative_to(resolved):
            raise ValueError("Unexpected path outside the bundle")
    return resolved


def reject_running_bundle(path: Path) -> None:
    executable = str(path / EXE).replace("'", "''")
    command = "$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq '" + executable + "' }).Count"
    environment = os.environ.copy()
    environment["PSModulePath"] = str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/Modules")
    result = subprocess.run([
        str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
        "-NoProfile", "-Command", command,
    ], capture_output=True, text=True, check=True, env=environment,
       creationflags=subprocess.CREATE_NO_WINDOW)
    if int(result.stdout.strip()):
        raise RuntimeError("Close this KDE release before promotion; no process will be terminated automatically")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-old-sha", required=True)
    parser.add_argument("--discard-build", action="append", default=[], help="directory=known-executable-SHA256")
    arguments = parser.parse_args()
    metadata_path = ROOT / "docs/verification/build.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    candidate = validate_bundle(Path(metadata["exe"]).parent, metadata["sha256"])
    if candidate.name == "portable":
        raise ValueError("The replacement must be staged before promotion")
    for name in ("packaged-check-3.1.json", "gui-3.1.json"):
        report = json.loads((ROOT / "docs/verification" / name).read_text(encoding="utf-8"))
        if report.get("exe_sha256") != metadata["sha256"] or report.get("live_portal_access") is not False:
            raise ValueError("Actual executable verification is missing or belongs to another bundle")
        if name.startswith("packaged") and report.get("status") != "passed":
            raise ValueError("Packaged self-check failed")
        if name.startswith("gui") and (report.get("version") != "3.1.0" or not report.get("gui_started") or report.get("mail_queue_rows") != 1):
            raise ValueError("Packaged GUI verification failed")
    old = validate_bundle(ROOT / "portable", arguments.expected_old_sha)
    reject_running_bundle(old)
    reject_running_bundle(candidate)
    discarded = []
    for specification in arguments.discard_build:
        name, expected_hash = specification.split("=", 1)
        stale = validate_bundle(ROOT / name, expected_hash)
        if stale in {old, candidate} or stale.name == ".previous-portable":
            raise ValueError("Discard list overlaps the current or replacement bundle")
        reject_running_bundle(stale)
        discarded.append((stale, expected_hash))
    previous = ROOT / ".previous-portable"
    if previous.exists():
        raise FileExistsError("A previous promotion needs cleanup; preserve it before another promotion")
    os.rename(old, previous)
    try:
        os.rename(candidate, ROOT / "portable")
    except Exception:
        os.rename(previous, old)
        raise
    metadata["exe"] = str(ROOT / "portable" / EXE)
    metadata["status"] = "verified_and_promoted"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    # User-authorized old KDE bundles only. Every absolute target was validated
    # before renaming or removal; settings, logs and other applications lie outside.
    validate_bundle(previous, arguments.expected_old_sha)
    shutil.rmtree(previous)
    for stale, expected_hash in discarded:
        validate_bundle(stale, expected_hash)
        shutil.rmtree(stale)
    print(json.dumps({"status": "promoted", "exe": metadata["exe"], "sha256": metadata["sha256"],
                      "old_release_removed": True, "discarded_builds": [str(path) for path, _ in discarded]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
