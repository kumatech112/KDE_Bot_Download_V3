# KDE Bot Download V3 — 3.1.1

- Replace the fixed eight-step page with chronological Thai work history.
- Retain errors, fresh-login retries and later success as separate events; keep Complete/Error as latest outcomes.
- Add history reload, text search, follow-latest control and readable event details.
- Record meaningful business transitions in the existing monthly CSV without idle poll spam or new folders.
- Reload the latest three months, show up to 2,000 recent events and deduplicate replay against live history.
- Retain older logs, credentials, destinations, mail triggers, concurrency and retry timing.
- Derive build version from source and require packaged history GUI evidence before promotion.
- Confirm directory-cache misses from disk before another download, including delayed NTFS/SMB timestamps.

Short commit message: feat: replace KDE checklist with work history

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
