# KDE 3.5.0 data flow and changed functions

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
