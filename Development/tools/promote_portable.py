"""Promote a tested KDE release to Program and archive the previous bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "Archive/verification"
EXE = "KDE Bot Download V3.exe"
ALLOWED_TOP_LEVEL = {EXE, "_internal", "Quick start.md"}
LEGACY_TOP_LEVEL = {EXE, "_internal", "คู่มือเริ่มใช้งาน.md"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_bundle(path: Path, expected_hash: str) -> Path:
    resolved = path.resolve(strict=True)
    project = ROOT.resolve()
    stable = resolved.parent == project and resolved.name in {'Program', 'portable'}
    staged = resolved.parent == (project / 'Archive/builds') and re.fullmatch(r"portable-\d{8}-\d{6}", resolved.name)
    archived = resolved.parent == (project / 'Archive/releases') and re.fullmatch(r"KDE-\d+\.\d+\.\d+-[0-9a-f]{12}", resolved.name)
    if not (stable or staged or archived):
        raise ValueError("Bundle must be the stable Program or an explicitly contained Archive bundle")
    if {item.name for item in resolved.iterdir()} not in (ALLOWED_TOP_LEVEL, LEGACY_TOP_LEVEL):
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
    import win32con
    import win32file
    handle = win32file.CreateFile(str(path / EXE), win32con.GENERIC_READ, 0, None,
                                 win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
    handle.Close()  # Read-only exclusive open also detects another machine's SMB lock.
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
    parser.add_argument("--old-version", required=True)
    parser.add_argument("--old-folder", choices=('Program', 'portable'), default='Program')
    parser.add_argument("--discard-build", action="append", default=[], help="directory=known-executable-SHA256")
    arguments = parser.parse_args()
    metadata_path = REPORTS / "build.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    candidate = validate_bundle(Path(metadata["exe"]).parent, metadata["sha256"])
    if candidate.parent != (ROOT / "Archive/builds").resolve():
        raise ValueError("The replacement must be staged before promotion")
    for name in ("packaged-check-3.1.json", "gui-3.1.json", f"background-{metadata['version']}.json"):
        report = json.loads((REPORTS / name).read_text(encoding="utf-8"))
        if report.get("exe_sha256") != metadata["sha256"] or report.get("live_portal_access") is not False:
            raise ValueError("Actual executable verification is missing or belongs to another bundle")
        if not name.startswith('background') and (report.get('delivery_order') != ['original_dir', 'new_dir']
                                                     or report.get('copy_source') != 'original_dir'):
            raise ValueError('Verification does not identify the .243-first delivery policy')
        if name.startswith("packaged") and (report.get("status") != "passed" or report.get("download_policy") != "daily_all" or report.get("ocr_enabled") is not False):
            raise ValueError("Packaged self-check failed")
        if name.startswith('background') and (report.get('status') != 'passed' or not all(report.get(key) is True for key in
                ('starts_hidden', 'background_duplicate_stays_hidden', 'manual_reopens_same_window',
                 'x_hides_and_keeps_process', 'tray_exit_stops_process'))):
            raise ValueError('Packaged background lifecycle verification failed')
        if name.startswith("gui") and (report.get("version") != metadata["version"] or not report.get("gui_started") or report.get("mail_queue_rows", 0) < 1
                                       or report.get("activity_rows", 0) < 1 or report.get("fixed_step_checklist") is not False
                                       or not report.get("history_search_passed") or not report.get("readable_event_details")
                                       or report.get("language") != "th" or report.get("tab_count") != 3
                                       or not report.get("auto_start_passed") or report.get("mail_delay_seconds") != 270
                                       or report.get("download_policy") != "daily_all" or report.get("email_content_matching") is not False
                                       or report.get("ocr_enabled") is not False or report.get("tracker_source") != "new_dir"
                                       or report.get("sequential_accounts") is not True or report.get("portal_rows_per_page") != 30
                                       or report.get("page_by_page") is not True or report.get("login_retry_unlimited") is not True
                                       or not report.get("deferred_status_visible") or not report.get("busy_status_visible")
                                       or not report.get("password_toggle_passed") or not report.get("stop_control_passed")
                                       or not report.get("includes_read_mail") or not report.get("today_only")
                                       or not report.get("window_icon_applied") or not report.get("header_icon_applied")
                                       or report.get('task_scheduler_required') is not False
                                       or report.get('close_to_tray') is not True or report.get('manual_open_resumes') is not True
                                       or report.get('settings_section_count') != 4
                                       or report.get('editable_timing_roundtrip') is not True or report.get('save_without_start_passed') is not True
                                       or report.get('tracking_pause') != '22:00' or report.get('tracking_resume') != '05:00'):
            raise ValueError("Packaged GUI verification failed")
    old = validate_bundle(ROOT / arguments.old_folder, arguments.expected_old_sha)
    reject_running_bundle(old)
    reject_running_bundle(candidate)
    discarded = []
    for specification in arguments.discard_build:
        name, expected_hash = specification.split("=", 1)
        stale = validate_bundle(ROOT / name, expected_hash)
        if stale in {old, candidate} or stale.parent != (ROOT / "Archive/builds").resolve():
            raise ValueError("Discard list overlaps the current or replacement bundle")
        reject_running_bundle(stale)
        discarded.append((stale, expected_hash))
    if not re.fullmatch(r"\d+\.\d+\.\d+", arguments.old_version):
        raise ValueError('Use a numeric old release version')
    releases = ROOT / 'Archive/releases'
    releases.mkdir(parents=True, exist_ok=True)
    previous = releases / ('KDE-' + arguments.old_version + '-' + arguments.expected_old_sha[:12].casefold())
    if not previous.resolve().is_relative_to(ROOT.resolve()) or previous.resolve().parent != releases.resolve():
        raise ValueError('Archive destination escaped the KDE project')
    if previous.exists():
        raise FileExistsError('The identified old release is already archived; no overwrite')
    program = ROOT / 'Program'
    if program.exists() and program != old:
        raise FileExistsError('Program already contains another bundle; no overwrite')
    launcher = ROOT / 'KDE Bot Download V3.lnk'
    prior_launcher = launcher.read_bytes() if launcher.exists() else None
    os.rename(old, previous)
    try:
        os.rename(candidate, program)
        from create_shortcut import create_shortcut
        create_shortcut(ROOT)
    except Exception:
        if program.exists():
            os.rename(program, candidate)
        os.rename(previous, old)
        if prior_launcher is None:
            launcher.unlink(missing_ok=True)
        else:
            launcher.write_bytes(prior_launcher)
        raise
    metadata["exe"] = str(program / EXE)
    metadata['previous_release'] = str(previous)
    metadata["status"] = "verified_and_promoted"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    # User-authorized old KDE bundles only. Every absolute target was validated
    # before renaming or removal; settings, logs and other applications lie outside.
    validate_bundle(previous, arguments.expected_old_sha)
    # Preserve the former release, byte for byte, in Archive for rollback.
    for stale, expected_hash in discarded:
        validate_bundle(stale, expected_hash)
        shutil.rmtree(stale)
    print(json.dumps({"status": "promoted", "exe": metadata["exe"], "sha256": metadata["sha256"],
                      "old_release_archived": str(previous), "discarded_builds": [str(path) for path, _ in discarded]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
