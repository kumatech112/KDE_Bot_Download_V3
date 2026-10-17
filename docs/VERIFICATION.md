# Verification — 2026-10-17 — 3.8.1

## Scope and data flow

Follow the user-created `\\10.0.0.97\Z KDE Bot` copy share and `\\10.0.0.97\Z Log Bot\KDE Log Bot` history share. Save/verify the final download in .243, then read the verified .243 file to copy it to .97. Exact .97 filenames still suppress duplicates. Exact .243-only files can now supply the copy without a portal redownload; recorded SHA-256 conflicts remain errors. The explicit .97-only option is preserved.

The exact new Log folder already contained the state, monthly CSV and worker lock. No folder, business download, log or credential file was relocated or reset. Retired settings aliases migrate on load; custom paths/accounts/timing remain intact. Only known exact own project startup commands can migrate. The strict cleanup allowlist now names the new .97 share and still preserves every folder, contents and links.

## Source validation

- Before editing: **298 tests and 4 subtests passed**.
- After editing: **306 tests and 4 subtests passed**. Existing unrelated KDE matching, Outlook, queue, paging, cleanup, DPAPI and desktop regressions remain passing.
- New regressions prove .243-first publication, actual .243 as the .97 copy source, no .97 publication after .243 denial, recoverable .97 copy denial, no second portal download on repair, cache cleanup after success, exact alias migration/idempotence/custom-path preservation, and scoped own-startup command migration.
- All **16 source offline checks passed**. The real offline browser fixture uses both 30-row selector styles and sequential Pre/Post sessions, asserts the source of every .97 copy, copies an existing .243 file without a browser download, and makes no downloads on the second sweep.
- Production portal/mail content is never used by these checks. Deletion tests use temporary roots and mocked approval lists only.

## Actual executable validation

- The built Thai GUI passed: four Settings sections, .243-first storage labels, exact new paths, 270/60-second defaults, 30 portal rows, current-day/sequential policy, Stop/password controls and icon. The storage screenshot was visually inspected.
- The actual EXE background lifecycle passed in an isolated profile: hidden launch, background duplicate remains hidden, manual reopen shows the same window, X hides without exiting, and tray Exit ends normally. No valid portal credentials, production destinations, cleanup, startup registration or task registration were used.
- All **16 actual packaged offline checks passed**, including the real .243-first browser fixture. Hash-linked policy reports and final promotion are recorded under `docs/verification`.
- Before/after SHA-256 inventories match for every existing .97 business download and shared Log/state file. The existing Checked folder remains untouched.

Tested EXE SHA-256: `8fb39eb23bd89c5832e6d393f6f3a05607faf0a3233428b83ef92e557b17253c`.

Local reports: `source-check-3.8.1.json`, `packaged-check-3.8.1.json`, `gui-3.8.1.json`, `background-3.8.1.json`, `build.json`, `paths-3.8.1-before.json` and `paths-3.8.1-after.json`. They are excluded from Git.

## Deployment boundary

Checks run on **.73** against the project share on **.97**. Live .97 Outlook/KDE login, actual business-file write/delete rights, own-user sign-in startup activation and the first real timed cleanup/resume remain target-machine checks. No production file was created, deleted or overwritten, and no permissions were changed during verification.

Open the stable `portable\KDE Bot Download V3.exe` on .97 after replacement. Existing settings load with known path aliases updated; verify **ดาวน์โหลด .243 → คัดลอก .97** in Settings. Existing custom folders are deliberately retained rather than guessed. Windows startup activation occurs on .97 from the stable bundle; Task Scheduler is not required.

Keep KDE running in the tray, Windows signed in and the machine awake for timed actions. Full Exit, sleep or power-off cannot perform cleanup. Defaults remain 22:00 cleanup/pause and 05:00 resume, with no missed-night catch-up and no same-day restoration of intentionally deleted files. Existing user timing choices are preserved.
