# KDE 3.7.0 data flow and changed functions

## 3.7.0 background workflow (supersedes scheduled-task flows below)

Normal/manual launch → per-user/session native mutex → show existing Tk instance via event or create one → Thai GUI + native tray + BackgroundClock. Sign-in startup uses the same EXE with --background, never signaling an existing instance. Mail metadata → persisted queue → 270-second delay → serial Pre/Post current-day page downloads remains unchanged. At 22:00 TrackingHours blocks new scans/claims but lets the active future finish; DailyCleanup and the GUI maintenance thread cooperate through the existing Log request/WorkerLock. At 05:00 the gate opens; if the tracker was stopped, the GUI starts it again. A manual reopening overrides only that overnight interval. Midnight queue expiration and cleanup tombstones still prevent old-day restoration.

| File | Functions/classes | Change |
|---|---|---|
| schedule.py | overnight_key | Bangkok 22:00-inclusive / 05:00-exclusive night identity, shared across midnight |
| schedule.py | TrackingHours.__init__, resume_manually, allowed | Persist manual resume under the shared History lock; additive state; automatically expire it next night |
| schedule.py | BackgroundClock.__init__, next_hour, tick | Independent 22:00 cleanup / 05:00 restart clock; single firing; skip missed-night deletion |
| desktop.py | DesktopInstance.__init__, notify, requested, close | Native per-profile/user-session mutex and one-shot reopen event; no extra files or duplicate GUI |
| desktop.py | TrayIcon.__init__, start, run, window_message, close | Native tray lifecycle, Thai menu/show/full-exit events, Explorer restart recovery, early-shutdown handling; callbacks queue to Tk |
| startup.py | configure_startup | Only own HKCU Run value; .97/stable-portable guard; background startup; no privilege/password; refuse conflicting value |
| main.py | scheduled_cleanup_entry | Legacy scheduled action is a no-op, even if old-task removal is denied |
| main.py | main | --background and native instance ownership; manual duplicate signals existing window; self-check/smoke remain isolated |
| daily_download.py | run_daily_monitor | Finish active work before night pause; gate scans and new claims only; recheck time after blocking scan/cleanup; manual resume command; schedule-status events |
| gui.py | Application.__init__, build_controls, build_settings, save_configuration | Tray/runtime state; Thai full-exit control and independent startup preference |
| gui.py | configure_background_startup | Set user startup; best-effort removal of exact own legacy task, never register another task |
| gui.py | start_tray, check_tray_ready, show_window, resume_tracking | Background startup, tray failure visibility, early manual resume without forcing a download round; defer resume while stopping/cleaning |
| gui.py | start_maintenance | Independent non-daemon maintenance worker; .97/saved-valid-settings guards; existing lock-cooperative cleanup, even when tracker stopped |
| gui.py | start, retry_failed, drain_events, accept_event, render_jobs, tick | Preserve worker mode; handle maintenance/tray/pause events; independent clock and instance polling; no new worker during cleanup |
| gui.py | close, exit_fully, wait_to_close, launch/capture | X hides without Stop; explicit full exit stops both workers and removes tray before Tk destruction; smoke verifies hide/reopen without real startup |
| settings.py | default_settings, validate_settings | Additive start_with_windows boolean; preserve existing accounts and preferences |
| storage.py | History.__init__ | Validate optional manual-night date without resetting corrupt state or changing schema 3 |
| selfcheck.py | check_background_schedule, check_desktop_instance, check_native_tray, check_daily_cleanup, run_self_check | Offline boundary/native lifecycle checks; no active Scheduler dependency or registration; deletion only in temporary roots |
| tools/promote_portable.py | main | Require actual executable GUI proof of tray/manual-open/22:00/05:00 policies and matching-hash end-to-end background report before promotion |
| tools/verify_background.py | windows_for, wait_until, verify, main | Isolated real-EXE startup/duplicate/manual-reopen/X/tray-exit checks; native windows restricted to the spawned test PID; reject the production stable bundle when testing on .97; no production profile or valid credentials |

Full Exit/off/sleep/sign-out cannot run in-process deadlines. X and Stop retain the maintenance clock; a failed tray stays visible. Startup registration and legacy task removal occur only on normal .97 stable-portable launch, never in verification. Other applications, credentials, business destinations and monthly logging remain unchanged. Historical implementation notes follow for provenance and do not describe current task scheduling.

## 3.6.1 first-run setup fix

| File | Functions | Change |
|---|---|---|
| cleanup_task.py | scheduler_error_code | Normalize direct COM HRESULTs and unwrap only DISP_E_EXCEPTION's nested excepinfo SCODE; supports pywin32 attributes and structured args without parsing error text |
| cleanup_task.py | setup_error | Readable Thai operation stage and hexadecimal Windows error code |
| cleanup_task.py | configure_task | Treat only GetTask's 0x80070002 as first setup; continue creation; preserve other failures and all owner/action checks |
| selfcheck.py | check_scheduler_missing_task, run_self_check | Real read-only Windows lookup in an initialized background COM thread; new packaged regression; no task registered |

The reported tuple was reproduced exactly: outer HRESULT -2147352567 (DISP_E_EXCEPTION), excepinfo[5] -2147024894 (0x80070002). Version 3.6.0 checked only the outer hresult, so it rejected the normal first-run absence of a task. The fix applies only to the existing-task lookup. A missing-file error during RegisterTaskDefinition still fails and identifies registration as the failed stage. Access denied and other genuine errors never become an installed status.

## 3.6.0 cleanup flow and function map

Stable EXE startup on .97 → own-user Task Scheduler definition → daily 22:00+07:00 → headless entry without GUI/Outlook/portal credentials → validate saved settings → transient Log request → wait for shared WorkerLock or cooperate with running monitor → validate the two exact approved roots → regular direct children only → save deletion intent → unlink → save deletion name → monthly CSV result. In-app DailyCleanup.tick also fires at 22:00 while monitoring and waits until the active account finishes. No production cleanup is invoked during installation or verification.

| File | Functions/classes | Change |
|---|---|---|
| cleanup.py | current_time, was_cleaned | Bangkok clock and exact filename/day deletion-history check |
| cleanup.py | request_path, write_request, path_identity, validated_root, file_signature | Separate atomic Log request with unique temporary names and short Windows sharing retries; normalized/resolved approved roots; reparse-point refusal and fresh child metadata |
| cleanup.py | cleanup_root | No recursion; preserve all directories/links; journal before/after unlink; per-file failure handling; Stop/midnight cancellation |
| cleanup.py | DailyCleanup.__init__, requested_today, tick, run | 22:00 due time, cooperative request, active-download wait, once-per-day/crash behavior, compact shared results |
| cleanup.py | run_scheduled_cleanup | No-GUI worker; early-run refusal; shared lock ownership; running-GUI cooperation; task exit status |
| cleanup_task.py | on_cleanup_machine, task_definition, configure_task | .97 guard; daily offset-aware 22:00 definition; interactive current-user SID; no password/elevation/catch-up; verify registration; only own matching task may be updated/removed |
| main.py | scheduled_cleanup_entry, main | Dedicated scheduled action; reject missing/corrupt settings; report task outcome locally; no GUI error dialog |
| daily_download.py | DailyDownloader.handle_file, run_daily_monitor | Skip intentionally removed names; run cleanup between active account sessions |
| workflow.py | run_cycle | Explicit cached-save repair also respects same-day deletion history |
| storage.py | History.__init__ | Validate additive cleanup results/filename journal without changing schema 3 |
| settings.py | default_settings, validate_settings | Enabled-by-default boolean cleanup preference; existing settings normalize additively |
| gui.py | Application.__init__, build_controls, build_settings, save_configuration, configure_cleanup_task, drain_events, run.capture | Thai preference/status/stage; automatic local setup only outside smoke mode; expose 22:00/closed-app/no-redownload policy in GUI verification |
| selfcheck.py | check_daily_cleanup, run_self_check | Temporary-root deletions and folder preservation, persistent no-redownload checks, in-memory real Windows task definition; no task is registered or run |

Only the two approved download roots can be deleted from. User folders such as `03 Check` and `Checked` are not special-cased by spelling: all directories are preserved, so nested contents are never enumerated or removed. The cleanup runs against both roots even in .97-only download mode. File publication remains unchanged.

Deletion intentions are saved before unlink. Successful names and uncertain crash-time names block same-day download/repair restoration; failed unlinks clear the pending name and leave the file. Cleanup history is additive and scoped to its Bangkok date; a different extension or next day's file is not conflated. A second run/restart cannot delete later arrivals that day.

The external worker does not break the monitor's long-lived worker lock. It writes one atomic request under Log; a running monitor executes the pass after its active account closes, while a closed monitor lets the worker own the lock. The request is removed after completion. Errors/partial passes return a nonzero task result. Missed nights are not executed against a new day's files.

Task registration occurs locally on .97 for the current user's interactive token, not SYSTEM/S4U, so the task uses that signed-in user's SMB access without storing a password. Root task names include that user's SID; mismatched principals/actions are refused. The task launches the stable portable EXE with --scheduled-cleanup, has one daily trigger and ignores overlapping invocations. The builder's remote scheduler access was denied; local activation remains a deployment boundary.

## 3.5.1 changes by function

| File | Functions/classes | Change |
|---|---|---|
| daily_download.py | ArrivalScan, scan_arrivals | Whole configured incoming mailbox; legacy folder filter bypassed only for daily policy; SMTP/store resolution; per-item/folder fault isolation; coverage warnings; stop sorted mail enumeration at yesterday |
| daily_download.py | run_daily_monitor | Send scan-health events, log first scan/recovery and changed partial coverage, record trigger deadline; retain 270-second scheduling and serial account queue |
| portal_pages.py | newest_first, check_date_order, download_pages | Select descending date sort, verify visible dates and page boundaries, stop when older dates begin, preserve current-page downloads |
| gui.py | Application.__init__, build_controls, build_settings, start, accept_event, render_jobs, run.capture | Main scan-health/countdown line; remove obsolete subfolder control; handle diagnostic events; exercise countdown/error display in packaged smoke |
| selfcheck.py | check_arrival_metadata, daily_fixture_html | Whole-mailbox legacy-filter and SMTP coverage; sortable native/custom portal fixture |

The production CSV confirmed 21 downloads followed by 160 pages scanned on .97. It did not record a new-email event for the reported test; the exact live test-message cause cannot be established from those records. The identified legacy-folder and all-or-nothing scan paths are corrected, and live scan coverage is now visible. No subject/body/file-name matcher is added.

Date-boundary stopping relies on newest-first server pagination. When available the date-header control is selected and aria-sort=descending is confirmed. Without a sort control the portal must already present newest-first order; visible date increases (including across page boundaries) are rejected. This avoids silently traversing history as a fallback. Today-only rows still use the portal date, and unknown dates are never downloaded.

## Current flow

Per-user settings/DPAPI → shared Log lock → selected destination read-only checks → saved arrival/round recovery → today's incoming data-mailbox IDs → deduplication → pending 270-second trigger → Pre account → set 30 rows → verify current-page table → download today's rows and skip existing .97 names → advance and verify next page → logout/close → Post account with the same page flow → logout/close → idle until another new-mail/manual trigger.

The user supplied the 30-row control and DD/MM/YYYY timestamp screenshots. Shared production CSV errors confirmed the old complete-catalogue page guard prevented all downloads. DailyDownloader now overrides the inherited catalogue traversal with portal_pages.download_pages; the older matcher/paging code remains only for retained helper regressions. No full catalogue or reverse walk gates daily downloads.

## Trigger and sequential ownership

One executor worker owns browser work. DailyQueue.claim returns one account at a time and preserves account order, including its 60-second login cooldown. The current source closes before the next starts. Outlook metadata polling continues in the monitor thread while the source worker runs.

Each new incoming ID opens a 270-second window or joins the existing pending deadline. New mail during active work queues another round. A successful account raises an already-pending new-mail deadline to at least finish+270; it creates no new round by itself. Failed/busy logins remain waiting for finish+60 without a fixed attempt cap. Credentials rejected/locked pause for operator correction. Empty successful scans complete, and file/navigation failures defer until new mail rather than repeatedly reopening a successful login.

Daily job attempts are nonnegative integers without the former two-attempt limit; legacy mail_jobs keep their old validation. Interrupted jobs preserve attempts/deadlines. Upgrade from flow 4 lengthens old pending trigger windows once and marks flow_version=5, so restarts do not repeatedly extend them. Midnight expires old work and resets the day's seen IDs. Existing queues/logs/credentials remain intact.

## Page safety

The page-size adapter scopes native select or Material/MUI combobox controls inside the paginator or the observed Thai rows-per-page label. It selects and verifies 30, returns to the first page when required, and waits for complete stable rows. Native and custom option fixtures are exercised.

Each page downloads before a next-page click. Rows are re-read after every file so removals, refills and reordered indexes do not skip visible current-day files. A processed-name set avoids repeated file actions within the sweep. Navigation must produce changed, stable rows. Repeated page fingerprints stop the sweep. Pagination totals inform the traversal budget; a stale max_pages=1 cannot prevent the normal 77-row/three-page case. A safe fallback still guards unbounded or broken navigation. Partial successful downloads remain in .97 when later navigation fails.

The date column is authoritative; valid Gregorian/Buddhist YYYY-MM-DD, YYYY/MM/DD, DD-MM-YYYY and DD/MM/YYYY dates are compared with Bangkok today. Blank/unreadable dates never fall back to filenames. Each file is rechecked at the download boundary and a local download crossing midnight is discarded before publication.

## .97 file authority

Daily handle_file checks only new_dir for an existing exact Windows filename. .97 is always first in daily_folders; original_dir is optional. Legacy original-only settings migrate to both. Presence only in .243 never skips a file and never supplies the source for a normal daily download. Cached validated download sources can still recover an interrupted save. The base delivery's existing-source selection has an overridable default so historical/explicit repair behavior is preserved.

DailyDelivery obtains fresh KDE bytes when .97 is missing, publishes .97 first with CREATE_NEW/hash verification, then verifies/copies .243 without overwrite. Existing .97 files skip the optional copy too. A .243 conflict leaves today's .97 bytes intact and reports copy_pending. Explicit Repair pending saves may reuse validated local/existing content without a browser. No tracker/probe/log/temp/account directory is created in either business destination.

## Changed functions

| File | Functions/classes | Change |
|---|---|---|
| portal_pages.py | pagination_scope, page_range, next_button | Locate observed paginator controls, Thai/English range totals and enabled next-page button |
| portal_pages.py | wait_ready, set_page_size | Stable complete rows, first-page recovery, native/custom 30-row selection verification |
| portal_pages.py | download_pages | Forward per-page downloads before navigation; fresh indexes; refill handling; current-day filter; repeated-page guard; partial-result preservation |
| daily_download.py | portal_day, daily_folders | Remove filename-date inference; require .97 and optional .243 second |
| daily_download.py | DailyDelivery.__init__, existing_source | Separate normal fresh-download source choice from explicit cached/existing save repair |
| daily_download.py | DailyDownloader.__init__, _download_visible_pages, handle_file | Thai reporting; call page processor; .97-only duplicate detection; .97-first final publication |
| daily_download.py | DailyQueue.__init__, recover, ingest, request_round, claim, finish, snapshot | Flow-5 migration, 270-second triggers, one account claim, unlimited 60-second login retry, successful cooldown reset, visible Thai states |
| daily_download.py | run_daily_account, run_daily_monitor | Classify login failures separately from later file/navigation errors; one browser worker; no idle round after success |
| storage.py | Delivery.existing_source, _deliver | Default-preserving source-selection hook |
| storage.py | History.__init__ | Allow persisted daily login counts above two; legacy validation unchanged |
| storage.py | Reporter.__init__, _emit | Optional Thai translation before existing redaction/history logic |
| language.py | THAI, thai_text | Thai controls, retained-engine messages, counts and readable failure prefixes; preserve technical evidence |
| workflow.py | run_cycle | Thai reporter; required .97/optional .243 preflight and daily explicit repair folders |
| settings.py | default_settings, normalize_settings, validate_settings | 270-second trigger/60-second login policy; migrate original-only storage |
| gui.py | Application builders, round/history/config methods, launch | Thai controls/history/details; readable Thai font; remove misleading legacy page-limit option; unrestricted login count; smoke policy evidence |
| selfcheck.py | check_daily_queue, daily_fixture_html, check_daily_native_round, run_self_check | Sequential native browsers; both control types; old-limit reproduction; downloads before navigation; .97-only tracking and fresh .243-only download |
| tools/promote_portable.py | main | Require hash-linked Thai GUI, 270 seconds, 30 rows, sequential/page-by-page policy and .97 tracker |

Only this KDE project changes. Other applications, credential encryption format, Windows/SMB permissions, mail flags and production business files are untouched by verification. Legacy helpers remain source-only references; the new runtime does not invoke keyword/OCR matching or account-wide sign-out.
