# Verification — 2026-10-09

## Completed checks

- Python syntax/compilation validation.
- 36 regression tests and 4 subtests passed.
- Preserved date-aware matching and split-volume regression suite passed.
- Partial copy followed by retry: download callback ran once, both destinations matched.
- Conflicting and empty existing files were preserved and reported at the correct step.
- Download timeout reported at step 6 without modifying unrelated files.
- Unchanged skipped outcomes did not create repeated CSV rows.
- Corrupt shared history failed without resetting the original file.
- Legacy history import retained existing V3 records.
- Unreadable DPAPI credentials retained account/path settings and left the password blank for re-entry.
- Saved password was absent from plaintext settings; local DPAPI roundtrip passed.
- Competing worker could not acquire an active lock.
- Delivery callback continued to the next file after a per-file failure.
- Actual portable EXE launched from the requested UNC project folder, exit code 0.
- Packaged GUI screenshot smoke passed with 8 steps, accessible Settings and no theme selector.
- Packaged offline browser, credentials, delivery, retry and lock self-check passed, exit code 0.
- Source publication scan found no current standalone passwords or runtime files in publishable source.

## Packaged executable

portable/KDE Bot Download V3.exe

SHA-256: 3e64842c8a4a02e4d09d7f70e904b46c2821cd1efa764ae63a65d4dfaefbb208

Only EXE, _internal and the Thai manual are placed in the portable folder.
Raw check reports and rendered screenshots are kept together under docs/verification and excluded from Git.

## Not verified

The checks ran on machine 10.0.0.73 while opening the executable stored on 10.0.0.97.
Actual execution under the Windows user on 10.0.0.97, its share write permissions,
Outlook mailbox/profile, and live KDE login/download/logout remain unverified.
No live portal download, production file overwrite, legacy application modification,
or credential deployment to another machine was performed.
