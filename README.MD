# KDE Download — 3.2.1

A dedicated Windows KDE downloader with a small English interface: **Monitor**, **History**, and **Settings**. Native ttk controls, no theme selector.

Open **portable\KDE Bot Download V3.exe**. Keep **_internal** beside it. The browser and English/Thai OCR engine are included; the deployment machine does not need Python or a separate Tesseract installation.

Read [Quick Start](docs/QUICK_START.md) for setup and daily use.

## Behavior

- Starts monitoring automatically after valid local account setup.
- Tracks today's incoming Outlook messages in Bangkok time, including read mail; processed message IDs prevent repeated work.
- Uses subject/body references, attachment filenames and local image OCR. **Import image** supports separate screenshots.
- Waits **two minutes** after discovery, then queues the matching Pre/Post account.
- Each account handles one request at a time, in order. The two accounts can work concurrently. New requests cannot overtake an earlier request or its retry.
- No idle KDE login loop. Two attempts total per request, fresh logout/session between attempts; busy/login failures wait five minutes.
- Checks account, business numbers, dates and full-catalogue ambiguity before downloading. Unclear OCR/routing is visible for review.
- Downloads and validates locally, then publishes only the final business filename. No destination test files, logs, account folders or .part sidecars. Existing content is preserved.
- Retains failed-save sources locally for repair without another portal download. Shared state and monthly CSV preserve attempts, outcomes and history.

## Default destinations

| Purpose | Folder |
|---|---|
| Original files | `\\10.0.0.243\pgp-data$` |
| New files | `\\10.0.0.97\Z Bot KDE` |
| Shared history / queue | `\\10.0.0.97\Z Log\Log Bot KDE` |

Choose original, new or both. Both accounts use the selected roots directly. Passwords/settings and pending local downloads live under `%LOCALAPPDATA%\KDE Bot Download V3`. The Log folder must be separate and writable. Actual final-file access depends on the launching Windows user; no app can bypass SMB permissions.

## Project layout

| Folder | Contents |
|---|---|
| portable | EXE, _internal, Quick start.md |
| src | KDE application only |
| tools | Build and verified release promotion |
| tests | Matching, mail queue, OCR, delivery and history checks |
| docs | Quick Start, function map, changes and verification |
| assets | App icon |

Git excludes passwords, settings, business files, images/mail contents, runtime logs and portable binaries.

## Development

Use Windows and Python 3.13 with `requirements.txt`. The local builder needs Playwright's pinned headless browser and Tesseract with English/Thai models. `KDE_BUILD_HOME` selects a local build drive; `KDE_OCR_HOME` selects the installed OCR build dependency.

    python -m compileall -q src tools tests
    python -m pytest tests -q -p no:cacheprovider
    python src/main.py --self-check path-to-offline-report.json
    python tools/build_portable.py

See [Architecture and changed functions](docs/ARCHITECTURE.md), [Changes](docs/CHANGES.md), and [Verification boundaries](docs/VERIFICATION.md).
