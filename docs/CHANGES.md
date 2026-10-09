# KDE Bot Download V3 — 3.0.0

## Changes

- New KDE-only portable application in a separate V3 project.
- Plain Thai Version 1 style ttk GUI, no theme switcher.
- Three storage modes: both, original only, new only.
- Original destination \\10.0.0.243\pgp-data$; new \\10.0.0.97\Z Bot KDE.
- Copy after a single download, SHA-256 verification, no conflicting-file overwrite.
- Per-file pending-copy recovery without downloading the source again.
- Step 1–8 results, separate Complete/Error/Skipped tables, stable rows across retries.
- Monthly CSV plus shared history; remove per-run audit folders and duplicate archive copies.
- Machine/user-specific encrypted credentials; unreadable passwords leave Settings accessible.
- Explicit import of legacy KDE settings/history and environment/Outlook checks.
- Source, portable, tools, tests, and documentation separated.

## Compatibility

Existing applications, their configuration and business files are not modified.
Existing matching rules and login/logout engine are reused from the standalone Version 1 application.
The only modification to the preserved engine is an optional file-delivery callback after matching.

## Short commit message

feat: rebuild KDE downloader with verified delivery and step reporting
