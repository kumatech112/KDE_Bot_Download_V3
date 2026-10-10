# KDE V3 data flow and function map

The application runs on the computer launching its EXE. The shared source directory is not an execution host.

Flow: per-user settings → validation → shared worker lock → pending-copy repair → Outlook messages → durable queue (180-second delay) → up to two independent account workers → date-aware matching → verified delivery → outcome CSV/shared history → logout → completion or bounded fresh-session retry.

## Files and functions

| File | Functions/classes | Responsibility |
|---|---|---|
| src/main.py | main | Source/EXE launch; isolated smoke and packaged self-check |
| src/kde_bot/settings.py | settings_home, default_settings, normalize_settings, load_settings, save_settings | Machine/user settings and schema |
| src/kde_bot/settings.py | decrypt_credentials, encrypt_credentials, import_settings, validate_settings | Recover foreign credentials without blocking GUI; import only KDE; validate before execution |
| src/kde_bot/settings.py | atomic_json | Atomic local/shared JSON replacement |
| src/kde_bot/storage.py | WorkerLock, check_writable | Exclusive OS/SMB worker lock and temporary permission probe |
| src/kde_bot/storage.py | check_destination | Read-only business-destination existence/listing check; no permission-test files |
| src/kde_bot/storage.py | History.save, History.import_legacy | Compact shared history; merge without replacing existing V3 records |
| src/kde_bot/storage.py | History.__init__, set_file, file_lock | Validate durable mail jobs; synchronize state; serialize equivalent filenames across accounts |
| src/kde_bot/storage.py | Reporter.emit, Reporter._emit, Reporter.append_activity, Reporter.redact | Monthly business transitions and outcomes; redact passwords; suppress unchanged idle/errors/outcomes |
| src/kde_bot/activity.py | event_identity, ActivityHistory.add, ActivityHistory.merge | Chronological event identity; bounded recent history; deduplicate live and replayed events |
| src/kde_bot/activity.py | read_activity, update_latest | Read existing monthly CSVs; keep outcome views independent of chronological history; clear resolved stage errors |
| src/kde_bot/storage.py | Delivery.index, Delivery.existing, Delivery.deliver, verified_copy | Per-destination completion, partial delivery retry, hash verification and no overwrite on conflicts |
| src/kde_bot/workflow.py | selected_folders, detect_chrome, make_engine_settings, run_cycle | Destination selection, environment checks, KDE-only orchestration |
| src/kde_bot/workflow.py | StructuredDownloader overrides | Structured stage events and delivery integration around the preserved portal engine |
| src/kde_bot/workflow.py | StructuredDownloader._select_page_mail_matches, handle_file, job_outcomes | Associate selected files with messages; check required filenames; distinguish missing/download/copy failures |
| src/kde_bot/workflow.py | run_mail_monitor, run_account_batch | Local mail polling without idle portal calls; independent runtimes; wait for Logout before retry |
| src/kde_bot/mail_queue.py | account_side, route_lookup, message_identity | Stable per-message/account identity and account routing |
| src/kde_bot/mail_queue.py | MailQueue.ingest, claim_ready, finish | Durable delay, two-attempt budget, account cooldown and terminal states |
| src/kde_bot/mail_queue.py | recover_interrupted, requeue_failed, has_pending | Restart recovery without resetting attempts; explicitly initiated manual retry |
| src/kde_bot/legacy_core.py | scan_mail_filenames, _login_with_retry | Read-only message metadata hook, including duplicate filenames; one login attempt per V3 session |
| src/kde_bot/legacy_core.py | scan_mail_filenames.folder_contains_mail, is_mail_item, restrict_unread_items, scan_folder | Filter mail folders/items only; retain child traversal; bounded per-item UnRead fallback |
| src/kde_bot/legacy_core.py | sync_playwright_without_console | Reference-count hidden driver launch across concurrent runtimes and restore after the last worker exits |
| src/kde_bot/legacy_core.py | KdeDownloader._download_visible_pages | Add optional file callback after the existing matching filters; original behavior retained when absent |
| src/kde_bot/gui.py | Application.build_controls, build_activity, build_result, build_settings | Plain Thai ttk GUI; work history replaces the fixed step checklist |
| src/kde_bot/gui.py | Application.__init__ | Initialize chronological history and follow/search state; reload saved history for configured launches |
| src/kde_bot/gui.py | collect_settings, save_configuration, import_configuration, import_history | Explicit machine setup and migration controls |
| src/kde_bot/gui.py | start, stop, drain_events, accept_event, render_activity, render_results, load_history | Background work; chronological activity, search/follow controls and stable latest outcomes |
| src/kde_bot/gui.py | selected_details, copy_selected, show_selected | Readable Thai event details, including destination, machine, run and hash |
| src/kde_bot/gui.py | close, wait_to_close, launch | Graceful worker shutdown and screenshot smoke |
| src/kde_bot/selfcheck.py | run_self_check | Real packaged credential/storage/browser checks using temporary data |
| src/kde_bot/selfcheck.py | check_outlook_folder_filter | Packaged fake-COM reproduction: Notes, mail child, mixed classes, fallback and unchanged read flags |
| tools/build_portable.py | main, source_version | Local PyInstaller build, source-version metadata, pinned headless browser, signed Node wrapper and portable publish |
| tools/promote_portable.py | validate_bundle, reject_running_bundle, main | Check verification hashes and running processes; promote within this project; remove only explicitly identified old KDE bundles |

The 3.1.1 patch changes Application.__init__, build_controls, build_activity (replaces build_steps), start, drain_events, accept_event, render_activity, render_results, selected_details, show_selected, load_history and launch in gui.py; Reporter.__init__, _emit and append_activity plus Delivery.index, _index and existing in storage.py; all new activity.py helpers; build_portable.source_version/main; and promote_portable.main. Settings and portal/session/mail scheduling code are unchanged.

The 3.1.2 patch changes legacy_core.KdeDownloader.scan_mail_filenames and its folder/item/filter helpers; workflow.StructuredDownloader.__init__/protocol_message and run_mail_monitor's recovery reporting; storage.Reporter._emit's informational event persistence; gui.STATUS_LABELS/launch smoke data; selfcheck.check_outlook_folder_filter/run_self_check; and the source VERSION. Credentials, portal operations, queue delay, cooldown and retry budgets are preserved.

The 3.1.3 patch changes settings.default_settings, import_settings and validate_settings; normalize_settings now drops obsolete account-folder keys through its existing whitelist. workflow.selected_folders, StructuredDownloader.handle_file and run_cycle use only the shared global roots for delivery and copy recovery. gui.Application.build_settings removes per-account destination inputs and explains combined storage; launch reports their absence. selfcheck.check_flat_storage/run_self_check verify concurrent publication directly at both roots. The source VERSION is updated. Tests cover old settings, all three storage modes, flat concurrent delivery and pending-copy recovery. Global paths, credentials, history, permission checks and portal/mail behavior are preserved. Existing business files are not moved or removed.

The 3.1.4 patch adds storage.check_destination and scopes check_writable's documented purpose to Log. workflow.run_cycle uses the read-only check for business roots and reports its limited scope in Thai. selfcheck.check_destination_preflight/run_self_check exercise the real startup with destination writes denied. The source VERSION is updated. Destination preflight does not create files, delete leftovers or assert write access; actual delivery reports save/copy failures at their corresponding stages. Business-file staging, no-overwrite guards, credentials, history and session/mail behavior are unchanged.

Outlook type constants follow [Microsoft's folder types](https://learn.microsoft.com/en-us/office/vba/api/outlook.olitemtype) and [object classes](https://learn.microsoft.com/en-us/office/vba/api/outlook.olobjectclass). Mail folders use DefaultItemType 0; MailItem Class is 43. Unknown providers retain the existing read-only per-item checks. A rejected UnRead restriction falls back within the configured item limit and reports one informational notice per folder per scanner; a subsequent folder access failure remains fatal to that scan.

## Preserved behavior

Preserve authenticated portal entry/navigation, browser/API logout cleanup, unread Outlook matching, subject/attachment/body candidates, account-side/date compatibility, ambiguity protection, split-volume identity, and atomic download staging. V3 uses one login attempt per session and at most two sessions per mail task. The former run_once/run_loop/config entrypoints are removed.

The new runner does not import KUMA/Routine/MI/Access workflows.
Each worker owns its browser, cookie context, request client and temporary engine state. One monitor holds the SMB worker lock, permitting two account workers inside that owner. Different business files download concurrently; equivalent filenames use a shared per-file lock. JSON/CSV mutations use a reentrant history lock.
The hidden Node launch wrapper is reference-counted across overlapping workers and restored only after the last runtime closes. Directory indexes refresh when another worker publishes a new file.

The scanner retains each message separately even when filenames repeat. EntryID/StoreID are hashed for persistent identity; absent EntryID uses a folder/time/subject/key fingerprint. Delay starts at first observation, including existing unprocessed unread mail. Rediscovery never resets deadlines. Shared state holds matching keys, not credentials or whole mail bodies.

Transitions: waiting → running → complete/copy_pending; failures return to waiting or exhaust at two attempts. Login failure adds a 300-second account cooldown, also blocking new mail. Download/missing retries start after previous Logout/close finishes. Stop/restart retains attempts. Manual retry starts an explicit new cycle and retains total_attempts.

## Completion and audit

Completion requires SHA-256 equality for every selected destination. Existing files are never replaced when content differs.
An interrupted copy leaves the source available for retry. Pending copies are retried even if the matching email has since been read.
An unreadable history fails closed. No silent history reset is permitted.
Monthly CSV retains business transitions: mail arrival/delay, login/search/session results, downloads, delivery outcomes and retries. Repeated unchanged idle summaries/errors and duplicate skipped outcomes are suppressed. File-existence checks and raw browser/debug chatter are not appended. No additional history files or per-run folders are introduced.
Reporter timestamps have microsecond precision to distinguish successive actions. Progress records do not replace authoritative JSON outcomes or change the mail retry budget. JSON mutations and CSV writes remain under the shared history lock.
The GUI timeline uses an event identity, retaining errors followed by retry and success. It reloads the latest three monthly CSVs and displays up to 2,000 recent events; full history stays in CSV. Replaying the same history does not add duplicate rows. Configured launches load history in a background thread.
Complete/Error rows remain keyed by account and canonical business-file identity and show latest outcomes. Successful recovery clears current stage errors while retaining their historical events. Older CSVs display only the events actually recorded at the time.

## Verification boundaries

Automated tests and offline EXE checks do not establish live KDE login/download/logout success.
Permissions and Outlook profile must be checked on the actual deployment machine and Windows user.
All machines sharing the workflow must use the same shared log directory to share its exclusive lock.
