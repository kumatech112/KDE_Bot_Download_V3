# Verification — 2026-10-17 — 3.6.0

## Requested behavior

Delete regular files directly in both \\10.0.0.243\pgp-data$ and \\10.0.0.97\Z Bot KDE every day at 22:00 Bangkok. Preserve every directory, link and nested file, including the observed 03 Check and Checked folders. Do not download or repair deleted filenames back that day. Support operation with KDE closed using a Windows task for the signed-in user on .97.

## Source verification

- Compilation and git diff whitespace checks passed.
- All **236 tests and 4 subtests passed**, including **19 targeted cleanup tests**.
- Real temporary-file deletion verified both roots, every subfolder/nested file preserved, no early deletion, once-per-day behavior, active-download waiting, wrong-root refusal and a locked-file failure without deleting unrelated data.
- Reloaded shared state prevented purged filenames and uncertain crash-time names from being downloaded again. Exact extensions remain distinct; the next day's files are not blocked. Explicit cached-save repair also respects deletion history.
- Stop/disabled cleanup, midnight rollover, interrupted passes, malformed state, absent/corrupt user settings and overlapping request writers were exercised. Each deletion intention is journaled before unlink. A failed unlink leaves the file and clears its pending name.
- The real shared WorkerLock coordinated a headless cleanup request with a running monitor fixture. A standalone worker with no GUI also deleted only temporary-root files and removed its transient request.
- Task registration/update/disable was tested against a fake service, including current-user ownership, matching executable/action, no password and no immediate task execution. Another-machine setup and another-program task were refused.
- A real local Windows Task Scheduler definition was constructed **in memory only** and verified: daily 22:00+07:00, interactive token, least privilege, no missed-run catch-up, no concurrent instance and --scheduled-cleanup action. No task was registered or run during verification.
- All **12 source offline checks passed**. The Thai GUI cleanup checkbox, settings collection, 22:00 policy, existing countdown/history controls, Show password, Stop and icon passed.

## Actual portable verification

- The actual **3.6.0 EXE passed all 12 offline checks**, including temporary-root deletion, directory preservation, persistent same-day skip, active-account wait, a subsequent standalone headless cleanup under the real worker lock and the in-memory Windows task definition.
- The actual Thai GUI passed with daily_cleanup_time=22:00, daily_cleanup_toggle_passed=true, daily_cleanup_preserves_all_folders=true, daily_cleanup_requires_monitor=false and daily_cleanup_skips_deleted_names=true. Monitor and Settings were visually checked.
- Diagnostic commands accepted PowerShell provider-qualified UNC output paths and exited successfully. Reports include powershell_path_input_verified=true and the actual tested EXE hash.
- Guide/source hashes match. Portable layout remains only EXE, _internal and Quick start.md. Pinned browser included; OCR absent; no settings, credentials, production files or logs bundled.

Verified EXE SHA-256: `7714ac08faff8f422be035b4aaa0e342a1dbd0b79e131a2f133964e138e717f4`.

The verified 3.6.0 bundle replaced 3.5.1 in the normal portable folder. Final EXE and guide hashes match the tested staged bundle. Old/staged releases were removed; one portable folder remains with the three expected top-level items. No application process was terminated for promotion.

Supplied icon SHA-256 remains `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.

## Activation and live boundary

Checks ran on **.73** against the project share on **.97**. The attempt to access .97 Task Scheduler remotely returned **Access is denied**. The actual task is therefore **not registered or live-verified by this session**; reports deliberately set daily_cleanup_task_registered_live=false.

Open the updated stable portable once on .97. Outside smoke mode it installs/updates only that signed-in user's SID-named cleanup task and verifies the registered definition. Settings shows success or the registration error; Tools also offers the local setup action. Existing portal credentials are not needed by the headless cleanup action, and no Windows password is stored.

The .97 computer must be on and that Windows user signed in, although the screen may be locked. No shutdown/sign-out catch-up is enabled. If KDE owns the shared worker lock at 22:00, the task requests cooperative cleanup and waits for the active account to finish. Otherwise it runs with KDE closed. Disabling the checkbox and saving disables in-app cleanup and removes only the matching own-user task.

**No production files were deleted during development, packaging or task setup.** Production directory names were inspected read-only. Actual .97 share deletion rights and the first live 22:00 run remain unverified. Locked/denied files are not forced; per-root/per-file errors appear in the existing monthly CSV and task failures return nonzero status.

Business roots receive no probes, trackers, logs, temporary sidecars or account folders. Cleanup never recurses or follows links. Log retains existing state/CSV/lock plus a transient coordination request; one overwritten task-result JSON stays in the local settings folder. Existing credentials, business files, logs and unrelated applications were preserved during release work.
