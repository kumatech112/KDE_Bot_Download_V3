# Verification — 2026-10-16 — 3.5.0

## Reported production failure

The user confirmed Portal Page limit. A read-only inspection of the existing shared monthly CSV found repeated `RuntimeError: Portal page limit reached before a complete match check; no files downloaded. Increase the page limit.` entries on 2026-10-16. No mailbox content, credentials or business files were read to diagnose this. The old catalogue gate is replaced in the daily production subclass; increasing the old limit alone is not the fix.

## Source verification

- Source compile and **211 tests plus 4 subtests passed**. Historical helper tests remain in addition to new policy regressions.
- A real browser reproduces **77 rows**, changes 15 to 30 through native and custom Material-style controls, downloads all 65 dated-today rows before page advances and succeeds despite old max_pages=1. Only two next-page moves are required.
- Further real-browser tests remove/refill rows while downloading without missing files and stall the next-page click after the first 30 successful files. The failure preserves the first page instead of preventing every download.
- Queue tests prove a fixed 270-second new-mail trigger, persisted IDs/deadlines, one account at a time, retries beyond two login attempts every 60 seconds, preserved counts after reopening, no overtaking by the second account, restored 270-second queued cooldown after success and no idle portal loop.
- Tracking tests check .97-only skips in all retained modes. .243-only old content is not reused as today's source; fresh KDE data is saved in .97 first while a conflicting old .243 file is preserved. .97-only mode rejects any attempt to stat/read/write .243.
- Existing exact-name/extension history, CREATE_NEW no-overwrite publication, cached repair, midnight guards, corrupt-state preservation, read-only preflight, DPAPI, worker lock and no-sleep ordinary skips remain covered.
- All **11 source offline checks passed**, including sequential real browser sessions, fake-COM metadata-only mail scanning, flow timing, required .97 storage, and native daily file download/publication. The daily fixture spans two pages with a legacy limit of 1, tests native/custom 30-row controls and verifies downloads occur before the next-page action. Its second round makes no native downloads.
- Source GUI verification passed with Thai tabs/controls/statuses/details, Thai font, 4:30 countdown, one-minute busy countdown, unrestricted login counts, .97-only tracker, sequential/page-by-page/30-row policy, Show password, Stop, icon and no theme selector.

## Scope and data boundaries

No real Outlook mailbox or KDE account is used during verification. Shared production CSV is inspected read-only for the reported error. Native browser checks use local HTML/Blob downloads and temporary destination roots; login/page content/logout are fixture replacements. No production business files, credentials, permissions or unrelated applications are changed.

Business roots receive no probes, tracker files, temporary sidecars, logs or account folders. Only final downloaded/explicitly repaired files can be published. .97 is mandatory; .243 is an optional second copy. Existing .97 names skip the optional copy. Normal missing-.97 downloads ignore .243 as a content source; existing .243 bytes remain protected by hash comparison/no overwrite. Log/state remain compact and local credentials retain DPAPI protection.

The supplied icon is unchanged: SHA-256 `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.

## Portable release

- The actual packaged 3.5.0 EXE passed all **11 offline checks**. Its native/custom 30-row, sequential, current-date, .97 tracking and first-page-before-navigation behavior passed using the packaged browser/download/publication code.
- The actual packaged Thai GUI passed and Monitor/Settings screenshots were visually checked: 270-second trigger, 60-second busy countdown, 30 rows, sequential/page-by-page policy, required .97 reference, unrestricted login retry, Show password, Stop, icon, history search/details and no theme selector.
- Both actual EXE diagnostic commands accepted PowerShell provider-qualified UNC paths and wrote reports to the correct real paths. Successful exit codes and powershell_path_input_verified=true are recorded. Reports carry the tested executable hash.
- The staged portable contains only EXE, _internal and Quick start.md. The guide is Thai, the pinned browser is included and the OCR runtime is absent. No credentials, runtime settings/logs or business files are bundled.

Verified EXE SHA-256: `7dd4ce620ac4aed9b1c67cfa40973e176659c8fa7e02130c960a9b033dd6b612`.

Verified release folder: `portable`.

The tested 3.5.0 bundle replaced 3.4.0 in the normal portable folder. After promotion, the EXE hash, source/packaged Thai-guide equality, supplied icon, three-item layout, OCR absence and old/staged-bundle removal were verified. Only one portable folder remains. User settings, local cache, shared history/state and production business files were preserved.

## Deployment boundary

Checks run on **10.0.0.73** against the project on **10.0.0.97**. They do not confirm .97's Windows user, Outlook profile, SMB rights or actual KDE controls/login/list/download/logout. The observed label/date formats are supported and exercised locally; changed live controls fail visibly rather than silently reverting to 15 rows or downloading an unverified date.

The app polls incoming data-mailbox IDs every 15 seconds by default. 270 seconds begins at discovery. Busy/unavailable login retries wait 60 seconds plus operation time, until available or Stop. Known invalid/locked credentials pause for correction. With no new mail, successful work does not create another timer round. A queued new-mail round waits at least 270 seconds after successful work finishes. No server webhook, forced human logout or live throughput/completeness benchmark is claimed.
