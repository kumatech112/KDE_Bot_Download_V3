# KDE Download — 3.3.0

A dedicated Windows KDE downloader with a small English interface: **Monitor**, **History**, and **Settings**. Native ttk controls, no theme selector.

Open **portable\KDE Bot Download V3.exe**. Keep **_internal** beside it. The browser and English/Thai OCR engine are included; the deployment machine does not need Python or a separate Tesseract installation.

Read [Quick Start](docs/QUICK_START.md) for setup and daily use.

## Behavior

- Reads portal rows in a batch and delivers requested files on the return path after checking the full catalogue. Page loading must finish and settle; unchanged or unreadable navigation fails clearly.
- **Show password** independently reveals either account password while editing; passwords start hidden and hide again when monitoring starts or stops.
- **Stop** ends monitoring safely after the active save/logout; queued work and attempt counts remain available on restart.
- Reads body instructions and incomplete business references, including the supplied TSS/AYCAP, Daily Recovery, SAM CustomerRequest, Document Round, litigation/legal-type, HC Report and Db Bank examples. `A10XX`/`A10XXL` target `A1015`/`A1015L`; a date placeholder uses the email day. `1015`, `Axxxx` or `L10xx` alone cannot select a file or account.
- Starts monitoring automatically after valid local account setup.
- Tracks today's incoming Outlook messages in Bangkok time, including read mail; processed message IDs prevent repeated work.
- Uses subject/body references, attachment filenames and local image OCR. **Import image** supports separate screenshots.
- Uses a fixed **one-minute window** from discovery. Mail arriving in an open window joins its existing deadline; the wait never restarts or accumulates.
- Searches the complete catalogues of **both enabled KDE accounts** before selecting files. The two isolated browsers run concurrently within one search round; another round waits for cleanup.
- Retains FIFO request order per business side. Two attempts total per round: the first attempt plus one fresh-session retry. Missing/download failures retry immediately after logout; ordinary login failures wait 60 seconds.
- After two failures, **Waiting for new email** requests are retried when a genuinely new relevant email starts another round. Duplicate scans never wake them. Pending requests survive midnight and restart with their original business dates.
- A confirmed busy account is checked every 60 seconds until available, without consuming the two attempts or forcing another person out. Only busy sources are probed during that wait; full matching resumes with fresh catalogues from both sources. Rejected credentials require review.
- Checks company, business side, numbers, dates and cross-account/cross-page ambiguity. Meaningful references without a side search both; conflicting candidates or weak OCR require review.
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
