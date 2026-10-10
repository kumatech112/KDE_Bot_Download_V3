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
| src/kde_bot/storage.py | History.save, History.import_legacy | Compact shared history; merge without replacing existing V3 records |
| src/kde_bot/storage.py | History.__init__, set_file, file_lock | Validate durable mail jobs; synchronize state; serialize equivalent filenames across accounts |
| src/kde_bot/storage.py | Reporter.emit, Reporter.redact | Structured outcomes; redact passwords; suppress unchanged CSV outcomes |
| src/kde_bot/storage.py | Delivery.index, Delivery.existing, Delivery.deliver, verified_copy | Per-destination completion, partial delivery retry, hash verification and no overwrite on conflicts |
| src/kde_bot/workflow.py | selected_folders, detect_chrome, make_engine_settings, run_cycle | Destination selection, environment checks, KDE-only orchestration |
| src/kde_bot/workflow.py | StructuredDownloader overrides | Structured stage events and delivery integration around the preserved portal engine |
| src/kde_bot/workflow.py | StructuredDownloader._select_page_mail_matches, handle_file, job_outcomes | Associate selected files with messages; check required filenames; distinguish missing/download/copy failures |
| src/kde_bot/workflow.py | run_mail_monitor, run_account_batch | Local mail polling without idle portal calls; independent runtimes; wait for Logout before retry |
| src/kde_bot/mail_queue.py | account_side, route_lookup, message_identity | Stable per-message/account identity and account routing |
| src/kde_bot/mail_queue.py | MailQueue.ingest, claim_ready, finish | Durable delay, two-attempt budget, account cooldown and terminal states |
| src/kde_bot/mail_queue.py | recover_interrupted, requeue_failed, has_pending | Restart recovery without resetting attempts; explicitly initiated manual retry |
| src/kde_bot/legacy_core.py | scan_mail_filenames, _login_with_retry | Read-only message metadata hook, including duplicate filenames; one login attempt per V3 session |
| src/kde_bot/legacy_core.py | sync_playwright_without_console | Reference-count hidden driver launch across concurrent runtimes and restore after the last worker exits |
| src/kde_bot/legacy_core.py | KdeDownloader._download_visible_pages | Add optional file callback after the existing matching filters; original behavior retained when absent |
| src/kde_bot/gui.py | Application.build_controls, build_steps, build_result, build_settings | Plain Thai ttk GUI without theme selection |
| src/kde_bot/gui.py | collect_settings, save_configuration, import_configuration, import_history | Explicit machine setup and migration controls |
| src/kde_bot/gui.py | start, stop, drain_events, accept_event, render_results, load_history | Background work; stable per-file rows; meaningful outcomes |
| src/kde_bot/gui.py | close, wait_to_close, launch | Graceful worker shutdown and screenshot smoke |
| src/kde_bot/selfcheck.py | run_self_check | Real packaged credential/storage/browser checks using temporary data |
| tools/build_portable.py | main | Local PyInstaller build, pinned headless browser, signed Node wrapper and portable publish |
| tools/promote_portable.py | validate_bundle, reject_running_bundle, main | Check verification hashes and running processes; promote within this project; remove only explicitly identified old KDE bundles |

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
Monthly CSV is an outcome log, not an append-only transcript of every browser/debug line. Unchanged duplicate outcomes are suppressed; attempt counts remain in JSON.
GUI rows are keyed by account and canonical business-file identity, and updated on retries.

## Verification boundaries

Automated tests and offline EXE checks do not establish live KDE login/download/logout success.
Permissions and Outlook profile must be checked on the actual deployment machine and Windows user.
All machines sharing the workflow must use the same shared log directory to share its exclusive lock.
