# Verification — 2026-10-16 — 3.5.1

## Diagnosis and changes

Read-only inspection of the existing shared CSV confirmed that Pre saved 21 files, then traversed 160 pages through historical records before Stop. The same records did not show a new-email event for the reported test message. They cannot establish that message's exact live failure cause, and access to .97's local Outlook settings was unavailable.

Daily mail monitoring no longer applies the retained legacy folder_path filter. It watches all incoming folders in the configured mailbox, resolves an SMTP account's delivery store when its display label differs, and isolates bad messages/folders so healthy arrivals still trigger work. Partial coverage is explicitly reported. The GUI displays the last scan time, today's mail count, scan errors/warnings and queued 4:30 countdown. No subject/body/attachment/name/OCR matcher is invoked.

Portal pagination selects newest-first date sorting when available, processes today's files and stops at the first older-date boundary. Without a sort control, the portal must already list newest dates first. Visible date increases, including across page boundaries, cause an explicit failure instead of a historical walk or guessed completion. Thirty rows per page, sequential Pre/Post ownership, .97-only duplicate tracking, 270-second triggers and 60-second busy-login retries remain intact.

## Source verification

- Compilation and git diff whitespace checks passed.
- All **217 tests and 4 subtests passed**. The targeted daily/portal suite passed **40 tests**.
- A new arrival after monitor startup was passed through the actual fake-COM metadata scanner and persistent queue to both sequential account dispatches after 270 seconds. No email subject/body or filename was provided.
- Regressions cover ignored legacy subfolder restrictions, differing SMTP/display names, bad messages and unreadable folders retaining healthy arrivals.
- Native browser fixtures cover 4,800 rows with 21 today: all 21 download on the first page with zero next-page clicks. An initially old-first catalogue is sorted before downloading its later today's files. An unsortable visibly mixed-date table fails without guessing.
- Existing date/midnight checks, exact filename delivery/history, .97 authority, .243 non-overwrite, native/custom 30-row controls, changing rows, stalled pages, queue recovery, unlimited busy retries and unrelated legacy-helper regressions passed.
- All **11 source offline checks passed**. The Thai GUI's main mail-health/countdown line, scan-error display, Show password, Stop, history/details, icon and policy metadata passed.

## Actual portable verification

- The actual **3.5.1 EXE passed all 11 offline checks**, using packaged browser/download/publication code with local fixtures and isolated temporary roots.
- The actual Thai GUI passed, including mail_health_display_passed, whole_mailbox_trigger and stop_at_older_dates. Monitor and Settings were visually inspected.
- Both diagnostic commands exited successfully and accepted PowerShell provider-qualified UNC output paths. Their reports record powershell_path_input_verified=true and the tested EXE hash.
- The portable guide matches docs/QUICK_START.md by SHA-256. The top-level layout is only EXE, _internal and Quick start.md; pinned browser included, OCR runtime absent, no credentials/settings/business files bundled.

Verified EXE SHA-256: `864563964f6408c26947a166bf9428e8dd3a9e18dc8391416c44d4eeacd1c231`.

The verified bundle replaced 3.5.0 in the normal `portable` folder. Final EXE and guide hashes match the staged verification. Old/staged bundles were removed, leaving one portable folder with the three expected top-level items. No app process was terminated for promotion.

Supplied icon SHA-256 remains `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.

## Deployment boundary

Checks run on **10.0.0.73** against the project share on **10.0.0.97**. They do not verify a real new-email event, Outlook profile/synchronization, credentials, permissions, or actual KDE controls/download/logout on .97. No live mailbox, KDE login or business-file mutation was used during testing. Production CSV/state were read only.

The app polls classic Outlook every 15 seconds by default. The 270-second delay begins when a new incoming ID is discovered, not when the mail server receives it. New arrivals coalesce; arrivals during active work queue another round, retaining the existing successful-work cooldown. No incoming mail means no idle portal-login loop. Folder failures are shown as partial coverage rather than silently presented as a complete scan.

Business roots receive no tracker/probe/log/temp files or account folders. Only final downloaded files are published; existing .97 names skip and .243 conflicts never overwrite. DPAPI credentials, local cache, shared state/logs and unrelated applications remain unchanged by release promotion.
