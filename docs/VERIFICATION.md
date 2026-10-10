# Verification — 2026-10-10 — 3.1.4

## Completed checks

- 94 regression tests and 4 subtests passed after the implementation changes.
- Diagnostic and copy-only preflight passed with all business-destination file writes rejected, across all three storage modes; no test files were created and existing files retained their contents.
- Missing/unreadable destinations still failed explicitly without creating directories or files.
- Actual download PermissionError remained a step-six error without modifying existing business files.
- Old V3 account-folder overrides are dropped on load/import/save while global roots, credentials and enabled-account choices survive.
- Legacy combined configuration imports only KDE and does not restore the former account download folders.
- Both accounts select identical roots in all three storage modes, even when raw legacy overrides are supplied.
- Two concurrent accounts publish verified files directly at both roots without account subdirectories.
- Pending-copy repair uses the shared roots without a portal download or recreation of deleted account folders.
- Reproduced the screenshot's invalid UnRead filter on a Notes folder using fake Outlook COM.
- All seven known non-mail folder types skipped item filtering while their mail children remained readable.
- Rejected mail-folder filters fell back to per-item read checks without adding false scan errors or changing unread flags.
- Mixed non-mail items and read messages stayed out of the queue; the configured item cap remained enforced.
- A genuine mailbox access failure still produced a scan error.
- Successful no-mail monitoring cleared an earlier Outlook error without any portal call.
- Error → fresh login retry → success remained separate chronological events after CSV reload.
- Repeated history reloads deduplicated saved/live events, including Excel-safe filenames.
- Bounded history retained recent events from both accounts in chronological order.
- Repeated unchanged idle summaries/errors did not flood monthly CSV.
- Progress logging retained credential redaction and did not replace authoritative outcomes.
- Successful login recovery cleared latest errors while retaining the historical failure.
- Directory-cache miss recovery detected another worker's equivalent filename even with deliberately delayed directory timestamps.
- No-mail monitoring opened no KDE session, despite repeated local mailbox checks.
- Each newly observed message waited 180 seconds; rediscovery did not extend its deadline.
- Pre/Post workers overlapped, with a maximum of one active batch per account.
- Missing/download failures used exactly two total attempts; login failures waited 300 seconds.
- Login cooldown also blocked newly arriving mail for the same account.
- Completion, interrupted attempts and cooldowns survived shared-state reload.
- Exhausted mail stayed stopped until an explicit manual retry; accumulated attempts were retained.
- Duplicate filenames from different Outlook messages retained distinct message IDs. Mail unread flags were unchanged.
- Mail specifying several filenames was not marked complete when one required file was missing.
- Login/search/download exceptions completed UI logout, signOut, autoSignOut and browser/context close before another session.
- Concurrent distinct-file delivery retained both history records and verified both destinations.
- Equivalent filenames serialized publication and avoided a second download.
- Directory indexes refreshed after another worker published an equivalent filename.
- Overlapping Playwright runtimes restored the subprocess factory after the last worker closed.
- Preserved date/account matching, ambiguity protection, split-volume, DPAPI, conflict and copy-recovery regressions passed.
- Corrupt shared mail state failed without resetting its original file.
- Actual packaged EXE passed its offline self-check, including two concurrent real browser processes with isolated cookies.
- Actual packaged preflight passed with destination file writes rejected; no probe files were created, existing file contents were unchanged, and Log remained writable.
- Actual packaged flat-storage check delivered both account files at both roots, verified their bytes, and confirmed no account subdirectories in all three modes.
- Actual packaged scanner passed the Notes-folder and rejected-filter reproduction using fake COM, including child traversal and unchanged unread flags.
- Actual packaged Thai GUI passed and was visually checked: chronological work history, mail queue, accessible Settings and no theme selector.
- Settings displays the combined-storage explanation and contains no account-specific folder inputs.
- Packaged GUI history search and readable Thai event details passed; the fixed step checklist is absent.
- Packaged reports include the executable hash, linking checks to this specific bundle.
- Recovered login failures clear from live results and saved outcome history; counters represent current rows rather than cumulative failed attempts.

## Executable

portable/KDE Bot Download V3.exe

SHA-256: d3316e1d506953a1199b846765024384ed4c82bc06a5724d031a1c13d7580637

Only EXE, _internal and the Thai manual are distributed. Raw reports/screenshots stay under docs/verification and are excluded from Git.

The previous project portable is removed after verification. Local Windows settings, shared business files/history and other projects are retained.
Build tools now require at least 1 GiB free and support KDE_BUILD_HOME for a local builder with adequate space. This release was built on D:.

## Deployment boundary

Tests ran on 10.0.0.73, opening the executable stored on 10.0.0.97.
Execution under the Windows user on 10.0.0.97, that user's share permissions/Outlook profile, and live KDE login/download/logout remain unverified.
The user's screenshot identifies the failing Notes-folder condition on .97. Regression and packaged Outlook-filter checks use fake COM folders, not that machine's live mailbox.
The user's later screenshot and report identify Permission denied involving a .kde-check probe at the .243 destination root. The generic error does not establish whether creation, writing or cleanup was denied on .97. Version 3.1.4 removes that probe from business destinations. Actual file delivery still requires the necessary Windows/SMB access and is not verified on .97. Deleted 01 Pre/02 Post directories are not recreated, existing business files are not relocated, and old probe leftovers are not removed automatically.
No live production download, credential deployment, business-file overwrite or modification of another application was performed.

The monitor polls Outlook locally every 15 seconds; it is not a server webhook. Portal sessions only start for eligible queued mail. First observation includes previously unprocessed unread messages.
All machines must use the same shared Log directory. One monitor owns its lock and runs up to two account workers within that owner.
