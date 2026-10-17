# Verification — 2026-10-17 — 3.6.1

## Reported error and confirmed cause

The .97 screenshot showed outer COM HRESULT -2147352567 with excepinfo SCODE -2147024894. A read-only Windows Task Scheduler lookup in an initialized Python background thread reproduced the exact tuple: `(-2147352567, 'Exception occurred.', (0, None, None, None, 0, -2147024894), None)`.

The inner code is 0x80070002: the task does not exist yet. Version 3.6.0 recognized only a direct outer ERROR_FILE_NOT_FOUND and therefore aborted normal first-time setup. Version 3.6.1 normalizes direct HRESULTs and unwraps only a COM dispatch exception's structured inner SCODE. GetTask's expected missing-task response now continues to registration. The same code during registration still fails; access denied and unknown errors never become success.

Connection, existing-task lookup, registration and cancellation errors now identify their operation stage and Windows code in Thai. No permissions, user identity, task ownership checks, cleanup paths, 22:00 timing, folder protection or download policy were relaxed.

## Source verification

- Compilation and whitespace checks passed.
- All **246 tests and 4 subtests passed**, including **29 targeted cleanup/setup tests**.
- First registration/update/disable passes for both direct and actual pywintypes wrapped task-not-found errors, using a fake task service with no registration side effects.
- Error tests cover access denied, malformed/absent excepinfo, structured-args fallback, no parsing of error text and refusal to unwrap unrelated outer errors. Missing-file errors at registration remain stage-specific failures.
- Existing tests retain exact approved roots, all-folder preservation, locked-file errors, active-account waiting, shared worker locking, headless cleanup, crash/restart behavior and same-day download/repair prevention.
- All **13 source offline checks passed**, including the new real read-only background-thread Windows lookup. No verification task is registered or launched.

## Actual portable verification

- The actual **3.6.1 EXE passed all 13 offline checks**. Its packaged COM code recognized the real Windows missing-task exception in a background thread. Existing temporary-root cleanup, standalone worker, folder preservation and no-redownload checks passed.
- The actual Thai GUI passed and Settings was visually inspected: version 3.6.1, 22:00, cleanup toggle, all-folder protection, unchanged history/countdown, Stop, Show password and supplied icon.
- Diagnostic commands exited successfully and accepted PowerShell provider-qualified UNC report paths. Reports record the tested EXE hash and powershell_path_input_verified=true.
- The Thai packaged guide matches docs/QUICK_START.md. Portable top level remains EXE, _internal and Quick start.md. Pinned browser included; OCR absent; no credentials, production settings, business files or logs bundled.

Verified EXE SHA-256: `4cb44e5a72503098df6851801957cc6fe9b53b7d0051934bcc84c00a08f5eca3`.

The verified bundle replaced 3.6.0 in the normal portable folder. Final EXE and guide hashes match the tested stage. Old/staged releases were removed, leaving one portable folder. No app process was terminated and user settings/history were preserved.

Supplied icon SHA-256 remains `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.

## Target-machine boundary

Checks ran on **.73** against the project on **.97**. The exact reported Windows lookup error was reproduced and corrected, but successful live task registration on .97 is not claimed. Remote scheduler access was denied earlier; the updated stable EXE must be reopened on .97 or its Tools setup action invoked to retry local registration. Settings displays the confirmed registration result or the failed operation/code.

The task remains 22:00 Bangkok for the signed-in user's interactive token, without a stored password or elevation. It runs with KDE closed when .97 is on and that Windows user signed in; a running monitor cooperates under the existing worker lock. No missed-night catch-up is enabled. Every subfolder and its contents, including 03 Check and Checked, remain protected. Same-day deleted names are not downloaded or repaired back.

**No production files were deleted, no tasks were registered or run, and no permissions were changed during verification.** Actual .97 deletion rights and the first successful live nightly run remain unverified. Shared logs/state and local credentials were preserved.
