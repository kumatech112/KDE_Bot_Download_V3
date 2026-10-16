# Verification — 2026-10-16 — 3.4.0

## Daily mode source checks

- Source compilation and **205 tests plus 4 subtests passed** with the daily workflow, retaining the existing legacy-helper tests as regression/reference fixtures. Production entrypoint tests explicitly reject any call to the old email matcher or evidence/OCR reader.
- New checks cover the fixed 70-second window, ID deduplication and restart, arrivals during active work, midnight expiration and a midnight-crossing download, one busy retry, independent successful sources, credential pause and corrupted-state preservation.
- Exact filenames are checked in either root in all three save modes. Different extensions download separately and retain distinct complete events. Two workers download a duplicate filename once. Existing files cause neither another download nor a copy to the other root; skips incur no between-download delay.
- Explicit Repair pending saves reuses the exact daily ledger and retained source without opening a browser. Legacy delivery behavior remains covered by the original tests.
- All **11 source offline checks passed**. The metadata check uses fake COM objects that raise if Subject, Body, Attachments or other contents are accessed. It verifies incoming data mailbox scope, read mail, optional nested folder, and outgoing/Notes exclusions.
- The native daily check runs both real browser workers against local HTML for two rounds: five arbitrary/extension-distinct files download once each, shared names download once, existing files remain in just their original root, yesterday/unknown dates are excluded, both selected roots receive final files and the second sweep performs no downloads. Success history is replayed with exact keys.
- Preserved native pagination checks exercise delayed/loading/busy/stalled tables, reverse traversal, shifted row indexes and Stop. Shared-root delivery, read-only business preflight, DPAPI and the worker lock remain exercised.
- The source GUI uses six representative states and reports daily_all, 70-second delay, two total attempts including busy accounts, no OCR/content matching, either-root skip, Show password, Stop, the supplied icon and no theme selector.

## Storage and scope

No production mailbox, live KDE account, credential or business file is used for verification. All file fixtures use isolated temporary roots. No Windows/SMB permissions or unrelated applications change. The log layout remains one schema-3 state file, monthly CSV and lock; daily_watch and exact-name records are additive. Existing historical queues are retained but not executed by production daily mode.

The business destinations receive no probes, temporary sidecars, new folders or logs. New downloads use exclusive final-file creation and hash-verified publication. Already-present nonempty filenames are skipped without checking their contents, per the requested rule. Zero-byte files/conflicts remain visible failures and are never overwritten. Explicit save repair is separate from automatic either-root skipping.

The supplied icon is unchanged: SHA-256 `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.

## Portable release

- The actual packaged 3.4.0 EXE passed all **11 offline checks**, including the metadata-only scanner, durable 70-second trigger, bounded retry, exact-name two-browser download and both-root publication/skip rules.
- The actual packaged GUI passed and Monitor/Settings screenshots were visually checked. The report confirms daily_all, mail_delay_seconds=70, busy_attempts_total=2, skip_either_destination=true, email_content_matching=false and ocr_enabled=false. Show password, Stop, auto-start, history search/details and supplied icons passed.
- Packaged self-check and GUI were both launched with PowerShell provider-qualified UNC output paths. Successful exit codes, real report placement and powershell_path_input_verified=true are recorded; both reports carry the tested EXE hash.
- The staged distribution has only EXE, _internal and Quick start.md at its top level. The pinned browser is present; _internal/ocr is absent and bundled_ocr=false. No local settings, credentials, logs or business files are bundled.

Verified EXE SHA-256: `6a6781905692f0bf1f1d6ff455534aa95fd05a58226b84fe8692ea7855f58e51`.

Verified release folder: `portable`.

The tested 3.4.0 bundle replaced 3.3.0 in the normal portable folder. Final EXE hash, supplied icon, guide/source equality, three-item layout, OCR absence and old/staged-bundle removal were verified after promotion. Only one portable folder remains. User settings, cached sources, shared logs/state and production business files were preserved.

## Deployment boundary

Verification executes on **10.0.0.73** against the project stored on **10.0.0.97**. It does not verify .97's Windows user, Outlook profile, network permissions or live KDE login/list/download/logout behavior. The two-browser fixture uses local HTML and Blob downloads; login/page content/logout are local fixture replacements.

The configured data mailbox and incoming folders are the confirmed scope. Mail is polled every 15 seconds by default; 70 seconds starts at discovery. Pending work, login operations and occupied users can delay processing. A failed/empty/busy account retries once after 60 seconds, then waits for another mail/manual trigger. No idle availability loop or forced sign-out remains.

Portal date text is authoritative; blank dates may use a unique filename date. Unsupported/unreadable dates are excluded and counted. Representative live portal dates/selectors still need deployment validation. A full catalogue exceeding the configured page limit fails visibly; no live completeness or speed benchmark is claimed.
