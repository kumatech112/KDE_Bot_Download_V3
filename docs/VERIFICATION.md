# Verification — 2026-10-17 — 3.7.0

## Source and regression checks

- Compilation and whitespace checks passed. All **280 tests and 4 subtests passed**, including 34 new background/desktop/startup checks. A focused background/cleanup/daily-monitor run also passed all 94 tests.
- Simulated Bangkok boundaries cover 21:59:59, 22:00, midnight, 04:59:59 and 05:00. Manual resume persists across midnight/restart and expires the following night. Late startup and missed-night wakeups do not delete a new day's files.
- The real monitor loop finishes an active Pre account across 22:00, pauses mail scans and Post, then resumes on a manual command. A separate monitor check resumes scans exactly at 05:00 without a manual override.
- Regression tests cover a mail scan or cleanup operation crossing 22:00: recheck the current Bangkok gate before claiming another account, preventing a stale pre-22:00 decision from starting new work afterward.
- GUI lifecycle tests cover close-to-tray, tray failure staying visible, early reopen, deferred resume during cleanup, full exit stopping both workers, and maintenance continuing after Stop.
- A synchronized two-thread test proves manual resume cannot change shared state while another history write owns its lock; the persisted override remains valid across restart.
- Windows startup tests use a mocked registry: only the exact own HKCU Run value may be written/removed; conflicting commands are preserved. Manual duplicate launch signals the existing instance; background duplicates stay hidden.
- Existing cleanup, exact-root/folder preservation, lock cooperation, no-redownload journal, credentials, daily mail triggers, portal paging and delivery regressions remain passing. Legacy scheduled CLI is now tested as a harmless no-op, including with missing/corrupt settings.
- All **15 source offline checks passed**, including actual native Windows tray and instance-handle lifecycle checks. Business-file deletions use temporary roots only.

## Actual executable checks

- The final EXE passed all **15 packaged offline checks**. Both packaged diagnostic commands exited with code 0 and accepted provider-qualified PowerShell UNC output paths; reports identify the tested executable hash.
- The Thai packaged GUI passed; Settings was visually inspected. Close-to-tray/reopen, startup preference, 22:00/05:00 text, existing history/countdown, Stop, Show password and supplied icon are present.
- An end-to-end run of the real EXE with an isolated profile passed: starts hidden, duplicate background launch stays hidden, manual duplicate reopens the same native window, X hides while the process remains alive, and tray Exit ends the process successfully. That profile has no valid portal credentials, disabled cleanup, temporary destinations/logs and disabled startup.
- Packaged offline-check results are recorded in docs/verification/packaged-check-3.7.0.json. GUI and background evidence are gui-3.7.0.json and background-3.7.0.json. Reports are local verification artifacts, excluded from Git.
- The Thai packaged guide matches docs/QUICK_START.md. Portable top level remains EXE, _internal and Quick start.md. Browser included; OCR absent; no user credentials/settings/business files bundled.

Tested EXE SHA-256: `f9dff693e37bc3d3e32d9562c0998909dc91dfc5d0a00094cec40f8f7bbdb614`.

Supplied icon SHA-256 remains `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.

## Deployment boundary

Checks ran on **.73**, accessing the project on **.97**. Actual .97 Outlook/KDE sessions, share deletion rights, Windows sign-in startup activation, legacy task removal and the first real 22:00/05:00 transition remain unverified. Open the stable portable on .97 to activate its own-user startup preference; Settings reports the result. No Task Scheduler setup is required. A leftover legacy task's action no longer deletes files.

Timed actions require KDE to remain running in the tray, with the computer awake and Windows signed in. Full Exit/off/sleep/sign-out cannot perform them. At 22:00 the active account finishes before direct-file cleanup; all folders and nested contents survive. At 05:00 tracking resumes; opening KDE manually can resume it earlier. Today's deleted names are not restored that day, and the next day never downloads yesterday's rows.

**No production files were deleted, no startup registry entries or tasks were installed/run, and no permissions were changed during verification.** Local credentials, shared logs/state and other applications were preserved.
