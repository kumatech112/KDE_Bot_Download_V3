# KDE 3.4.0 data flow and function map

## Current data flow

Per-user settings / DPAPI → writable Log lock and read-only checks of both download roots → daily state recovery → local classic Outlook metadata scan of the configured data mailbox → deduplicate stable received-message IDs → fixed 70-second pending window → one daily round with up to two isolated source workers → full paginated KDE catalogue → today's portal-date rows only → exact filename check in both roots → skip if present in either, otherwise local download → validated exclusive final-file publication to selected root(s) → own-session logout → account success or one 60-second retry → wait for new mail/manual request after two failures.

Normal production run_cycle calls run_daily_monitor. It does not call the old run_mail_monitor, MailQueue, SearchCoordinator, body matching or OCR. Historical matching code and its fixtures remain in source for regression/reference; old mail_jobs and prior CSV history remain preserved in state. No old keyword request is revived or executed by the daily path. The OCR runtime is no longer bundled. Only the shared browser/pagination/delivery infrastructure is reused.

## Trigger and account queue

DailyQueue stores day, seen IDs, an absolute pending_due, sequence and the latest per-account round outcomes under daily_watch in the existing schema-3 KDE_State.json. No new runtime file/folder is introduced. New unseen incoming IDs open now+70 or join an earlier pending deadline. Subjects, bodies, sender names, attachment names and images are never read by the new scanner. Incoming read/unread messages count; outgoing/system folders and non-mail items do not. The user confirmed the whole configured data mailbox; optional relative folder_path defaults blank.

The monitor polls Outlook every 15 seconds by default and continues ingesting arrivals while workers run. Mail during active work queues the next round. Existing pending/retry deadlines are not extended by new mail. Only one round owns source sessions; it waits for both workers to finish before admitting another round. Source workers have isolated browsers and cookies. A successful source is not reopened for another source's retry.

Two attempts total means the initial source sweep plus one fresh-session retry after 60 seconds. Busy, empty, navigation, download and save failures use that same bounded budget. Busy attempts are no longer refunded and there are no availability probes or unlimited retries. Known credential rejection pauses that account during the monitor run, even if more mail arrives. Stop/restart retains consumed attempts. Correct Settings and restart before an explicit/new-mail round to revisit credentials. On a new Bangkok day, old pending work expires and the seen-ID set resets.

## Date and filename identity

The visible KDE date column is authoritative. Valid YYYY-MM-DD / YYYY/MM/DD / DD-MM-YYYY / DD/MM/YYYY and Buddhist years are handled. A blank column can use exactly one dated filename day. A nonblank unreadable date is never bypassed with a filename guess. Other dates and undated rows are counted as date skips. There is no company/business-side/word/extension filter on today's rows.

DailyDelivery uses exact Windows filenames for existing files, delivery records and outcome keys. Names with different extensions or business numbers do not collapse to the old business equivalence identity. The Windows/SMB stat is fresh before every file; skipped files do not incur the configured between-download delay. Local shared filename locks serialize competing workers; exclusive final-file creation prevents overwrite by external publishers. Duplicate detection is filename presence, not a hash comparison of an already-present file.

Missing files still use the established validated local staging, CREATE_NEW, reader exclusion and hash-verified publication. A midnight check runs immediately before download and after local completion; previous-day cache is discarded before publication. Publication already in progress finishes safely. Normal rounds skip when either root already holds a file. Explicit Repair pending saves may finish the other selected root using cached/verified content without a portal session; it uses the daily exact record key for daily records.

## Changed functions

| File | Functions/classes | Change |
|---|---|---|
| daily_download.py | portal_day | Strict current portal-date parsing, conservative blank-date fallback |
| daily_download.py | scan_arrivals, walk | Metadata-only incoming data mailbox scan, optional relative folder, stable IDs, read/unread, system/non-mail exclusions, clear folder errors |
| daily_download.py | DailyDelivery.__init__, record_identifier, existing, index, _deliver | Exact filename keys; fresh stat; no business-name equivalence; separate extension histories; daily record marker for explicit repair |
| daily_download.py | DailyDownloader.__init__, _select_page_mail_matches, handle_file, download_today | Reuse verified catalogue traversal; select all today's rows; no evidence reader; skip either-root presence; final-day checks; no idle skip delay |
| daily_download.py | DailyQueue.__init__, roll_day, recover | Compact additive state; pending recovery; disabled-account handling; midnight expiry |
| daily_download.py | DailyQueue.ingest, request_round, claim, finish, snapshot | Fixed 70-second window, durable deduplication, queued next round, initial plus one retry, credential pause and readable account results |
| daily_download.py | run_daily_account, run_daily_monitor | Two isolated source workers, bounded outcomes, secret redaction, continued mailbox polling, Stop cleanup and final queue snapshot |
| workflow.py | StructuredDownloader.__init__ | Optional evidence reader; disabled by the daily subclass |
| workflow.py | StructuredDownloader._download_visible_pages | Policy-specific selection text; daily skipped files do not sleep; existing safe pagination/click checks retained |
| workflow.py | make_engine_settings | Filter mail adapter fields; optional folder scope stays outside the legacy engine dataclass |
| workflow.py | run_cycle | Read-only checks of both roots; route production to daily monitor; explicit repair only; metadata-only diagnostic scan; choose daily repair ledger |
| storage.py | exact_record_key, Delivery.record_identifier, Delivery._deliver | Add exact-key policy hook while retaining the legacy delivery default |
| storage.py | History.__init__, import_legacy | Validate additive daily state; preserve daily repair policy during imports |
| storage.py | Reporter.__init__, _emit | Policy-selectable filename outcome key; separate same-stem completion events |
| activity.py | read_activity | Optional exact-name replay for the daily GUI; historical timeline preserved |
| settings.py | default_settings, normalize_settings, validate_settings | Force 70-second arrival delay, 60-second retry and two attempts; optional folder scope; preserve credentials and paths |
| gui.py | build_controls, build_monitor, build_settings, advanced_settings | Replace image/review controls with Round details / Request download round; concise daily policy and optional folder scope |
| gui.py | review_request, render_jobs, load_history, launch | Details-only dialog, result text, exact-name replay, six representative smoke states and new policy evidence |
| selfcheck.py | check_arrival_metadata, check_daily_queue, check_daily_native_round, run_self_check | Fake COM metadata proof, durable timing/bounded retries, two real offline browser rounds, exact extensions and separate history; no OCR runtime requirement |
| tools/build_portable.py | main | Remove OCR bundle/dependency; keep browser, supplied icon and three-item distribution |
| tools/promote_portable.py | main | Require hash-linked packaged daily policy, 70 seconds, either-root skips, OCR/content matching disabled and bounded busy attempts |

Tests cover the new production entrypoint, date precedence, midnight during download, either-root skips in all save modes, exact extensions, two-worker deduplication, 70-second coalescing/restart, real monitor scheduling, one failed-source retry, queued arrivals, credential pause, corrupted-state preservation, no per-skip delay and explicit cached repair. Retained tests continue covering existing delivery, credentials, pagination and historical helper behavior.

## Scope and limits

Only this KDE project changes. No unrelated application, Windows/SMB permissions, credential format, business files or production mail is changed during verification. Business destinations receive only final files from real downloads/explicit repairs; diagnostics create no files there. Logs remain one shared state, one CSV per month and a lock; local cache/settings stay under the launching user's profile.

The app polls local classic Outlook; it is not a server webhook. Live .97 Outlook/profile/share access and actual KDE selectors/login/download/logout require deployment validation. Portal page limits and unreadable dates fail or skip with visible reasons, rather than claiming the entire live server has been downloaded. Existing nonempty filenames are skipped regardless of their content; zero-byte/conflicting entries remain visible errors and are never overwritten.
