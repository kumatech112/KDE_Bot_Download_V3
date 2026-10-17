# KDE Bot Download V3 — 3.8.1

- Follow the user-created shares: .97 copies in `\\10.0.0.97\Z KDE Bot`; existing history/queue in `\\10.0.0.97\Z Log Bot\KDE Log Bot`.
- Standard delivery saves/verifies .243 first, then copies from that verified file to .97. Reuse exact .243 files when .97 is missing; retain .97 duplicate checks, no overwrite and recoverable failures.
- Migrate only exact retired settings aliases and known own startup commands. Preserve custom settings, credentials and existing state. Update the strict cleanup allowlist to the new .97 share; preserve every folder including Check/Checked.
- Update Thai storage labels, offline delivery-order checks, release gate and documentation. Keep the existing project folders, email trigger/timing and sequential today-only portal traversal.

# KDE Bot Download V3 — 3.8.0

- Group settings into Accounts, Storage, Timing and Application; remove the separate Advanced window and general explanatory banners.
- Add Save without starting, plus Save & Start. Retain encrypted credentials and existing storage preferences.
- Make mail delay, login retry, polling, spacing, pause/cleanup/resume times configurable; apply selected values throughout queue recovery, busy retry, cooldown and maintenance. Defaults stay unchanged.
- Add automatic-tracking and timed-pause switches; expose browser visibility/path, web timeout and mailbox scan limit. Explicit Chrome/Edge selection takes precedence over the bundle.
- Preserve today-only sequential 30-row downloads, .97 duplicate detection, all-folder cleanup protection, shared locks and same-day deletion history.

# KDE Bot Download V3 — 3.7.0

- Replace scheduled cleanup with a tray-based maintenance clock. X hides KDE; explicit full exit stops it.
- At 22:00 pause mail scans/new account work, finish the current account and clean only direct files in both approved roots. Preserve all folders and contents, deletion journals and shared locks.
- Resume tracking automatically at 05:00 or early on manual reopening; retain today's-only downloads and 270-second mail-trigger delay.
- Add per-user Windows sign-in startup on .97 and single-instance reopen signaling. Retire own legacy task best-effort; legacy task CLI no longer deletes anything.
- Preserve Thai GUI, simple folder layout, credentials/settings, account sequencing and duplicate detection. Timed actions require KDE running in the tray on an awake signed-in computer.

# KDE Bot Download V3 — 3.6.1

- Fix first-run task lookup: recognize ERROR_FILE_NOT_FOUND inside a DISP_E_EXCEPTION/excepinfo SCODE as well as a direct HRESULT. Continue creating the task only for the expected missing-task response from GetTask.
- Keep genuine lookup, registration, connection and cancellation failures visible with the operation stage and normalized Windows code.
- Reproduce the exact reported error using a read-only real Windows background-thread lookup; add wrapped/direct first-registration and error-propagation regressions. Preserve the 22:00 cleanup policy, folder protection, download guards, user identity and permissions.

# KDE Bot Download V3 — 3.6.0

- Add once-daily 22:00 Bangkok cleanup of regular direct files in both approved download roots; preserve every folder, its contents and links. Resolve/validate roots and children; no recursion or forced permission changes.
- Register the current user's Windows task locally on .97 when the stable portable opens. Run headlessly with KDE closed while that user remains signed in. No stored password, elevation, missed-run catch-up or immediate task launch during setup.
- Coordinate headless/in-app cleanup through the existing worker lock and one transient request in Log; wait for active downloads. Keep compact per-day results and per-file outcomes in existing state/monthly CSV.
- Journal deletion intentions before unlink and retain removed names. Prevent same-day download/repair restoration after deletion or restart; preserve exact extensions and next-day behavior.
- Add a Thai enable/disable control, local task-setup status and History stage. Task setup remains visibly unverified until registration succeeds on .97.

# KDE Bot Download V3 — 3.5.1

- Stop forward pagination at the first older-date boundary after downloading today's rows; select descending date sort when available and reject visibly inconsistent order. Preserve 30 rows/page, Pre then Post, .97 filename skips and 270/60-second timing.
- Watch the whole configured data mailbox regardless of retained legacy folder filters. Resolve SMTP accounts to stores when mailbox display labels differ. Isolate unreadable messages/folders, retain healthy arrivals, and report partial scan coverage.
- Show last mailbox check, today's mail count, scan warnings/errors and the queued 4:30 countdown on the main window. Record initial scan coverage and trigger deadlines without logging every poll.
- Add metadata-to-queue-to-both-accounts integration coverage and browser regressions for 4,800 rows stopping on page one, sorting today's rows ahead of history and refusing visibly mixed unsortable dates.

# KDE Bot Download V3 — 3.5.0

- Fix the reported complete-catalogue page-limit failure by replacing the daily reverse/catalogue pass with forward, page-at-a-time downloads. Preserve completed files on later navigation errors.
- Set and verify 30 rows using native or Material-style controls. Support the observed Thai pagination label/range; return to the first page, refresh rows after each file and stop on unchanged/repeated pages.
- Use only today's visible KDE date column; blank/unreadable dates no longer infer a date from the filename.
- Change new-mail delay to 270 seconds. Process accounts sequentially in one browser worker. Retry busy/unavailable logins every 60 seconds until available or Stop; preserve counts above two across restart.
- Return to new-mail waiting after success/empty scans. Successful work restores a queued next round's 270-second cooldown. File/navigation failures wait for the next new-mail/manual round.
- Make .97 required and the sole already-downloaded reference. Save .97 first; optionally copy .243. A .243-only file does not skip or supply stale bytes to a normal download. Preserve all existing files on content conflict.
- Translate controls, statuses, history/details and common engine errors to Thai with a readable Thai font. Retain Show password, Stop, supplied icon, three tabs and compact shared history.
- Add a 77-row/30-per-page browser regression with old max_pages=1, native/custom control cases, removed/refilled rows and first-page preservation on navigation stall. Test sequential ordering, unlimited login cooldown, successful reset, .97-only tracking and .243 non-overwrite.

Short commit message: fix: restore sequential Thai KDE page downloads

## 3.4.0

- Replace production keyword/OCR selection with a metadata-only arrival trigger for the configured data mailbox and incoming folders.
- Wait a fixed 70 seconds; coalesce arrivals without extending the pending deadline. Continue detecting arrivals while a round runs, queueing another round.
- Download all today's KDE files from both enabled accounts, using the portal date column, without company/business-side/word filtering. Skip unknown dates and expire previous-day pending work.
- Check exact Windows filenames in both shared roots immediately before each download. If present in either, skip without downloading or filling the other destination.
- Keep different extensions as separate files, delivery records and success-history events. Coordinate duplicate filenames across workers; retain no-overwrite verified final-file publication.
- Bound failed, empty and busy accounts to the first attempt plus one retry after 60 seconds. Do not reopen a successful source for the other's retry. No unlimited busy probes or forced account resets.
- Preserve mail IDs, attempts and absolute deadlines across restarts. Pause rejected credentials during a monitor run. Normal rounds do not automatically repair missing copies when either root already has the file; explicit Repair pending saves remains available without browser access.
- Replace Import image / reference review with Round details and Request download round. Retain Show password, Stop, supplied icon, three tabs and compact monthly history.
- Remove the OCR runtime/build dependency from the portable. Retain historical helper code/fixtures as regression references; production no longer executes old matching queues.
- Add daily policy, real monitor scheduling, midnight, either-root skip, distinct-extension history, exact cached repair, credential and corruption checks. Verify the real packaged browser/download/delivery path against isolated local HTML.

Short commit message: feat: download all current-day KDE files on mail arrival

## 3.3.0

- Replace the two-minute delay with a fixed 60-second window shared by arriving mail; preserve deadlines across restarts and prevent accumulated delays.
- Search both enabled account catalogues before selecting a requested file, retaining company, file-side, date, number and global ambiguity guards. Save identical equivalent files only once.
- Keep two attempts total per request per round. Retry missing/download failures in fresh sessions, then defer until genuinely new relevant mail starts another round, including mail arriving during the final attempt.
- Separate unlimited busy-account availability checks from the attempt budget. Probe only busy accounts every 60 seconds; close available sessions while waiting, then refresh both catalogues when available.
- Remove account-wide sign-out/reset calls from V3. Clean up only successfully acquired browser sessions. Pause rejected credentials or ambiguous references for review.
- Preserve pending work across midnight with original business dates. Retain processed-message IDs, review, copy repair, flat final filenames, no-overwrite delivery and existing credentials/storage boundaries.
- Show Waiting for new email and Account busy in Monitor. Retain the English interface, icon, Show password, Stop and clean portable layout.
- Add cross-source, timing, restart, busy, credential, concurrency and cancellation regressions; exercise real offline browser downloads and final-file delivery through the packaged joint runner.

Short commit message: feat: add joint KDE search and mail-triggered retry rounds

## 3.2.4

- Integrate the reviewed supplied paging patch: read table rows in one browser call and deliver while returning from the last portal page to the earliest selected page.
- Require stable changed file rows instead of networkidle and a fixed 1.5-second pause; ignore loading/busy states and fail explicitly when navigation does not complete.
- Preserve Stop cancellation and allow safe return from a page emptied by completed downloads.
- Refresh the filename, date and size at the current row index before each download, including when previous downloads remove or reorder rows.
- Keep the full catalogue check, account/date/number guards, global ambiguity refusal, email FIFO, two attempts, 120-second delay and no-overwrite publication.
- Add unit and actual offline-browser checks for loading placeholders, stalled navigation, reverse traversal, emptied pages and moved rows. Retain the existing clean portable layout and GUI.

Short commit message: perf: speed up verified KDE paging

## 3.2.3

- Fix diagnostic launch paths containing PowerShell's Microsoft.PowerShell.Core\\FileSystem:: prefix before pathlib parses them, preserving UNC double backslashes.
- Apply the conversion to self-check reports, GUI screenshots and GUI reports. Reject empty or unsupported provider paths before any application or filesystem work begins.
- Add path-conversion and entrypoint-routing regressions; verify the actual packaged executable using provider-prefixed UNC output paths.
- Keep GUI controls, body matching, account queues, credential storage and business-file delivery unchanged.

Short commit message: fix: normalize PowerShell diagnostic paths

## 3.2.2

- Add independent Show password controls, initially masked and remasked on Start/Stop.
- Rename the existing graceful stop control to Stop and make stopping/stopped status explicit; preserve durable queues, retry budgets and logout/save cleanup.
- Parse current plain-text/HTML email body instructions separately from generic subjects. Prefer explicit body file instructions and company-marked body references.
- Match incomplete business names using all stated business words and exact numbers; support the eight supplied examples, own-company template normalization and unknown date placeholders.
- Keep date/account checks, full-catalogue ambiguity rejection, exactly two attempts, 120-second delay, and flat no-overwrite business storage.
- Add actual packaged body checks and GUI toggle/Stop verification; retain supplied icon and existing release layout.

Short commit message: feat: add password visibility, stop and email body matching

## 3.2.1

- Apply the user-provided robot/download icon to the Windows executable, app windows and header.
- Keep one multi-size ICO asset; bundle it under _internal/assets for source and portable use.
- Verify runtime window/header icons and record the source icon hash in build evidence.
- Keep download, mail, OCR, queue, credentials and storage behavior unchanged.

Short commit message: feat: apply supplied KDE download icon

## 3.2.0

- Replace the busy Thai interface with three English tabs: Monitor, History and Settings.
- Start the configured monitor on launch; simplify primary actions and move uncommon settings/tools out of the main workflow.
- Monitor today's incoming read/unread mail, preserve processed IDs, and exclude outgoing/default system folders.
- Reduce the initial delay to 120 seconds; enforce one FIFO head per account, including retries, reviews and pending saves.
- Add bundled English/Thai local image OCR for attachments, CID/data images and explicit screenshot import.
- Add visible account/reference review and conservative OCR tolerance with numeric, side and date guards.
- Check complete portal catalogues before selection, prefer precise evidence and reject cross-page ambiguity or changed rows.
- Stage downloads locally, retain failed-save sources, and publish only final filenames with exclusive creation and reader locking.
- Preserve DPAPI settings, shared state/monthly CSV, two total attempts, busy-user cooldown, independent sessions and logout cleanup.
- Include an English quick-start guide and OCR runtime under the existing clean portable layout.

Short commit message: feat: add English KDE mail agent with OCR and ordered queues

## 3.1.4

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
