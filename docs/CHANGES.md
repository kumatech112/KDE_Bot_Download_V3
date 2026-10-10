# KDE Bot Download V3 — 3.1.4

- Remove synthetic permission-test files from business download destinations.
- Check destination existence and directory readability without creating, modifying or deleting files.
- Keep the mutable Log-folder write/delete probe and report that actual destination save rights are checked during real delivery.
- Preserve no-overwrite safeguards, atomic business-file staging, flat storage and all mail/session rules.
- Verify both diagnostics and copy-only startup in all storage modes with destination writes denied; preserve actual save errors and unreadable/missing-folder failures.

Short commit message: fix: avoid permission probes in KDE download folders

## 3.1.3

- Store both Pre/Post account downloads directly in the selected shared destination roots.
- Remove account-specific folder controls and discard old account folder overrides on settings load/save/import.
- Route pending-copy recovery through the same shared roots without recreating deleted account folders.
- Retain global destination preferences, local encrypted credentials, history, mail timing and two-account concurrency.
- Verify migration, all three storage modes, concurrent flat delivery and root-based pending-copy repair.
- Document that Windows/SMB root write permissions still apply; no existing business files are moved or deleted.

Short commit message: fix: store KDE files directly in shared destination roots

## 3.1.2

- Fix the Notes-folder `Condition is not valid` error by checking Outlook DefaultItemType before filtering items.
- Skip non-mail folders while retaining traversal into their mail subfolders; ignore non-MailItem objects.
- Treat successful bounded UnRead fallback as a Thai informational history event, once per folder per scanner.
- Keep actual mailbox access failures as errors and retain unread flags without modifying Outlook items.
- Clear prior scan errors after a successful monitor scan, retaining their chronological history.
- Add regression and packaged fake-COM checks for Notes, rejected filters, limits and mixed item classes.

Short commit message: fix: skip non-mail Outlook folders during KDE scan

## 3.1.1

- Replace the fixed eight-step page with chronological Thai work history.
- Retain errors, fresh-login retries and later success as separate events; keep Complete/Error as latest outcomes.
- Add history reload, text search, follow-latest control and readable event details.
- Record meaningful business transitions in the existing monthly CSV without idle poll spam or new folders.
- Reload the latest three months, show up to 2,000 recent events and deduplicate replay against live history.
- Retain older logs, credentials, destinations, mail triggers, concurrency and retry timing.
- Derive build version from source and require packaged history GUI evidence before promotion.
- Confirm directory-cache misses from disk before another download, including delayed NTFS/SMB timestamps.

Commit message: feat: replace KDE checklist with work history

## 3.1.0

- Replace serial scheduled account loops with a durable mail queue.
- Remove the old loop entrypoints and timer controls; Outlook polling performs no portal operations.
- Wait 180 seconds after first observing each qualifying unread message.
- Run up to two independent browser processes, one per account, with isolated cookies and Playwright runtimes.
- Route definite Pre/Post mail to its account; ambiguous-side mail checks both enabled accounts.
- Retry missing/failed downloads in a fresh session, with two attempts total.
- After login failure, enforce a durable 300-second account cooldown, including new mail.
- Retain processed IDs/attempts across restarts; recover interrupted work without resetting budgets.
- Add explicit manual failed-mail retry; no automatic retry after exhaustion.
- Repair pending copies without a portal session; preserve verified delivery to the selected destinations.
- Add a mail queue, per-account progress, live counts and missing-file reasons to the Thai plain ttk GUI.
- Synchronize JSON/CSV and equivalent filenames while allowing different files to download concurrently.
- Preserve machine-specific DPAPI credentials and existing V3 download history.
- Replace the previous portable release after the replacement passes actual EXE checks.

Changed files/functions are mapped in ARCHITECTURE.md. Deployment limits are recorded in VERIFICATION.md.
