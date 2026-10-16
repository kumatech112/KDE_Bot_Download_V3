# KDE Download — 3.5.0

Thai Windows GUI with การทำงาน (Monitor), ประวัติการทำงาน (History) and ตั้งค่า (Settings). Open **portable\KDE Bot Download V3.exe**; keep **_internal** beside it. The pinned browser is included. Python and OCR are not required on the deployment computer.

## Current workflow

- Watch new incoming IDs in the configured **data@tradeconnection.co.th** classic Outlook mailbox, including read mail. No subject/body/image/keyword matching or mail mutation.
- New mail triggers a **270-second (4:30) wait**. Other arrivals join the same pending deadline. Mail during active work queues another round; after a successful account finishes, queued new-mail work waits at least another 270 seconds. No new mail means no idle browser loop.
- Process accounts **sequentially: Pre, logout/close, then Post**. At most one browser account is active. A busy/unavailable login waits 60 seconds and retries until available or Stop. Known rejected credentials pause for correction.
- Set the portal's rows-per-page control to **30**. Process today's files on the current page before advancing. Do not catalogue all pages or navigate backward before downloading.
- Use only the visible KDE date column and today's Bangkok date. Blank/unreadable dates are excluded; no filename-date fallback.
- Check already-downloaded filenames only in **\\10.0.0.97\Z Bot KDE**. Existing nonempty .97 files are skipped. .243-only presence does not count and does not supply stale content to a normal download.
- Save new downloads in .97 first, then optionally copy to .243. Never overwrite existing files. A conflicting .243 copy is reported while the new .97 file remains available.
- A successful empty scan returns to waiting for new mail. Download/navigation failures retain completed files and wait for another mail/manual round; only login availability retries every minute.
- Keep compact shared state/monthly CSV, local DPAPI credentials/cache, exact filename history, graceful Stop and the supplied icon.

The reported RuntimeError was found in the shared log: the old complete-catalogue page limit stopped downloads before they began. The new forward page processor starts saving immediately, derives traversal room from pagination totals with a safe fallback, detects unchanged/repeated pages and preserves already-saved files on later errors. A regression reproduces 77 rows with the old max_pages=1 setting.

## Destinations

| Purpose | Folder |
|---|---|
| Required download / existing-file reference | `\\10.0.0.97\Z Bot KDE` |
| Optional additional copy | `\\10.0.0.243\pgp-data$` |
| Shared history / queue | `\\10.0.0.97\Z Log\Log Bot KDE` |

Select .97 only, or .97 plus .243. The older original-only choice migrates to both so .97 remains authoritative. No business-folder tracker/probe/log/temp file or account folder is created. Only final downloaded files are saved there. Existing zero-byte files or conflicting content remain visible failures, never automatic overwrites.

Local settings, encrypted passwords and validated pending sources remain under `%LOCALAPPDATA%\KDE Bot Download V3`. The Log folder holds one schema-3 state, one CSV per month and the worker lock. One monitor may own that shared Log at a time.

See the [Thai Quick Start](docs/QUICK_START.md), [function map](docs/ARCHITECTURE.md), [changes](docs/CHANGES.md) and [verification](docs/VERIFICATION.md).

## Layout and development

The project contains portable, src, tools, tests, docs and assets. The portable contains only EXE, _internal and Quick start.md. Git excludes passwords, runtime settings/logs, business files, raw mail/images and portable binaries. Other applications are outside this project.

Use Windows, Python 3.13 and requirements.txt. The builder needs the pinned Playwright browser; KDE_BUILD_HOME selects a local build drive. Retained source-only OCR regression fixtures need developer-installed Tesseract; the current runtime and packaged checks do not use it.

    python -m compileall -q src tools tests
    python -m pytest tests -q -p no:cacheprovider
    python src/main.py --self-check path-to-offline-report.json
    python tools/build_portable.py
