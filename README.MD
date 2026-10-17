# KDE Download — 3.6.0

Thai Windows GUI with การทำงาน (Monitor), ประวัติการทำงาน (History) and ตั้งค่า (Settings). Open **portable\KDE Bot Download V3.exe**; keep **_internal** beside it. The pinned browser is included. Python and OCR are not required on the deployment computer.

## Current workflow

- Watch new incoming IDs in the configured **data@tradeconnection.co.th** classic Outlook mailbox, including read mail. No subject/body/image/keyword matching or mail mutation.
- Daily mode watches all incoming folders even if a legacy subfolder filter remains saved. Identify an account by SMTP/store when its display label differs. A bad folder/message reports partial coverage and does not discard arrivals from healthy folders. The main window shows last scan time, today's mail count, scan failures and the pending download countdown.
- New mail triggers a **270-second (4:30) wait**. Other arrivals join the same pending deadline. Mail during active work queues another round; after a successful account finishes, queued new-mail work waits at least another 270 seconds. No new mail means no idle browser loop.
- Process accounts **sequentially: Pre, logout/close, then Post**. At most one browser account is active. A busy/unavailable login waits 60 seconds and retries until available or Stop. Known rejected credentials pause for correction.
- Set the portal's rows-per-page control to **30**. Process today's files on the current page before advancing. Do not catalogue all pages or navigate backward before downloading.
- Use only the visible KDE date column and today's Bangkok date. Blank/unreadable dates are excluded; no filename-date fallback.
- Select descending date sort when available and stop at the first older-date boundary. A portal without a date-sort control must already show newest dates first; visibly increasing/mixed dates fail clearly rather than triggering a historical-page walk. No date can be inferred from a filename.
- Check already-downloaded filenames only in **\\10.0.0.97\Z Bot KDE**. Existing nonempty .97 files are skipped. .243-only presence does not count and does not supply stale content to a normal download.
- Save new downloads in .97 first, then optionally copy to .243. Never overwrite existing files. A conflicting .243 copy is reported while the new .97 file remains available.
- A successful empty scan returns to waiting for new mail. Download/navigation failures retain completed files and wait for another mail/manual round; only login availability retries every minute.
- Keep compact shared state/monthly CSV, local DPAPI credentials/cache, exact filename history, graceful Stop and the supplied icon.

## Daily cleanup at 22:00 Bangkok

- Delete only regular files directly in **both** `\\10.0.0.243\pgp-data$` and `\\10.0.0.97\Z Bot KDE`, regardless of the download storage mode. Never recurse, follow links or remove a folder. All folders and their contents survive, including the observed `03 Check` and `Checked`.
- Persist deleted/pending-deletion filenames in the shared state. Today's intentionally deleted files are not downloaded or repaired back that day, including after restart; different filenames/extensions and the next day's files still follow the normal download policy.
- Cleanup waits for the current account download/logout to finish. It runs once per Bangkok day, logs deletions/failures in the existing monthly CSV and leaves locked/denied files in place. Stop can interrupt the in-app pass; restarting never repeats a partially completed deletion pass against later arrivals.
- Opening the stable portable EXE on **.97** installs or updates a Windows task for the signed-in user. The task runs at **22:00 even with KDE closed**, using that user's existing share access and without storing a password. If KDE is running, a small request in the Log folder coordinates the same cleanup under the existing shared worker lock.
- .97 must be on and that Windows user signed in; the screen may be locked. There is no missed-night catch-up after shutdown/sign-out. Local task registration status appears in Settings. Uncheck the 22:00 option and save to disable both the timer and that user's task.

Remote Task Scheduler access from the builder was denied. The release is prepared to register locally when opened on .97; live registration and real business-file deletion are not claimed by offline verification.

The reported RuntimeError was found in the shared log: the old complete-catalogue page limit stopped downloads before they began. The new forward page processor starts saving immediately, derives traversal room from pagination totals with a safe fallback, detects unchanged/repeated pages and preserves already-saved files on later errors. A regression reproduces 77 rows with the old max_pages=1 setting.

## Destinations

| Purpose | Folder |
|---|---|
| Required download / existing-file reference | `\\10.0.0.97\Z Bot KDE` |
| Optional additional copy | `\\10.0.0.243\pgp-data$` |
| Shared history / queue | `\\10.0.0.97\Z Log\Log Bot KDE` |

Select .97 only, or .97 plus .243. The older original-only choice migrates to both so .97 remains authoritative. No business-folder tracker/probe/log/temp file or account folder is created. Only final downloaded files are saved there. Existing zero-byte files or conflicting content remain visible failures, never automatic overwrites.

Local settings, encrypted passwords, validated pending sources and one overwritten scheduled-task result remain under `%LOCALAPPDATA%\KDE Bot Download V3`. The Log folder holds one schema-3 state, one CSV per month, the worker lock and a transient cleanup request only while coordination is pending. One worker may own that shared Log at a time.

See the [Thai Quick Start](docs/QUICK_START.md), [function map](docs/ARCHITECTURE.md), [changes](docs/CHANGES.md) and [verification](docs/VERIFICATION.md).

## Layout and development

The project contains portable, src, tools, tests, docs and assets. The portable contains only EXE, _internal and Quick start.md. Git excludes passwords, runtime settings/logs, business files, raw mail/images and portable binaries. Other applications are outside this project.

Use Windows, Python 3.13 and requirements.txt. The builder needs the pinned Playwright browser; KDE_BUILD_HOME selects a local build drive. Retained source-only OCR regression fixtures need developer-installed Tesseract; the current runtime and packaged checks do not use it.

    python -m compileall -q src tools tests
    python -m pytest tests -q -p no:cacheprovider
    python src/main.py --self-check path-to-offline-report.json
    python tools/build_portable.py
