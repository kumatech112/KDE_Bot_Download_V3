# KDE Download — 3.4.0

A dedicated Windows KDE downloader with Monitor, History and Settings tabs. Open **portable\KDE Bot Download V3.exe** and keep **_internal** beside it. The browser is bundled; Python and OCR are not required on the deployment computer.

## Daily download behavior

- Watch today's incoming arrivals in the configured **data@tradeconnection.co.th** classic Outlook mailbox, including read messages. Only stable IDs and received times are read; subjects, bodies, attachments and images do not select files.
- New arrivals open a fixed **70-second window**. Other arrivals join the open deadline without resetting it. New mail during a running round queues the next round.
- Each round opens isolated sessions for both enabled KDE accounts. Download **all files dated today in Bangkok time**, regardless of company code, business words or file side.
- Use the portal date column. If it is blank, an unambiguous filename date may supply the date. Unknown/unreadable dates are skipped and counted; earlier dates are excluded.
- Before every download, check the exact Windows filename in **both destination roots**. A file present in either root is skipped; the app does not fill the other root automatically. Different extensions remain different files.
- Download missing files locally and publish only final filenames into the selected destination(s). Never overwrite existing files or create business-folder probes, subfolders, logs or temporary sidecars.
- A failed, empty or busy account gets **one retry after 60 seconds**, for two attempts total. The successful account is not reopened for the other's retry. After two failures, wait for another new mail arrival or Request download round.
- No queued work means no KDE login. Invalid credentials require attention; the affected account stays paused during that monitor run. No account-wide reset or forced logout of another person.
- Stop preserves consumed attempts and deadlines. At midnight, previous-day pending work expires. Historical matching requests remain in shared history but are not executed by this mode.

See [Quick Start](docs/QUICK_START.md), [Function map](docs/ARCHITECTURE.md), [Changes](docs/CHANGES.md) and [Verification](docs/VERIFICATION.md).

## Default destinations

| Purpose | Folder |
|---|---|
| Original files | `\\10.0.0.243\pgp-data$` |
| New files | `\\10.0.0.97\Z Bot KDE` |
| Shared history / queue | `\\10.0.0.97\Z Log\Log Bot KDE` |

Choose original, new or both for new downloads. Both roots are always checked for existing filenames. They must already exist and be readable; the selected save locations must permit final-file creation. Windows/SMB permissions belong to the launching user and are not bypassed.

Local settings, DPAPI credentials and validated pending sources remain under `%LOCALAPPDATA%\KDE Bot Download V3`. The separate writable Log folder holds one shared state file, one CSV per month and a worker lock. Only one monitor may own that Log folder.

## Clean layout

| Folder | Contents |
|---|---|
| portable | EXE, _internal, Quick start.md |
| src | KDE application source |
| tools | Build and verified promotion |
| tests | Regression and daily-sweep checks |
| docs | Setup, function map, changes and verification |
| assets | Supplied icon |

Git excludes passwords, runtime settings/logs, business files, raw mail/images and portable binaries. Unrelated applications are outside this project.

## Development

Use Windows, Python 3.13 and requirements.txt. The builder needs the pinned Playwright headless browser. `KDE_BUILD_HOME` selects a local build drive. No Tesseract runtime is bundled or used by the daily downloader.

Retained source-only OCR regression fixtures need a developer-installed Tesseract. They are separate from the current daily runtime and its packaged offline checks.

    python -m compileall -q src tools tests
    python -m pytest tests -q -p no:cacheprovider
    python src/main.py --self-check path-to-offline-report.json
    python tools/build_portable.py
