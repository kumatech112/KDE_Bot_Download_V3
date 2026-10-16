# Verification — 2026-10-16 — 3.3.0

## Current workflow verification

- Source compilation and **177 tests plus 4 subtests passed**. The full regression suite covers cross-account selection, equivalent duplicate files, cross-source ambiguity, unknown business sides, company/date/number guards, FIFO, deferred rounds and two total attempts per round.
- Timing checks cover one shared 60-second window, later mail joining without resetting it, new mail arriving during the final attempt, restart with an existing future deadline, midnight retention and migration from legacy five-minute waits without resetting consumed attempts.
- Busy checks are separate from the attempt budget. Tests repeat busy outcomes beyond two checks, verify only busy sources are probed, resume fresh full catalogues when available and pause rejected credentials. Stop and setup failures release waiting source workers. Account-wide sign-out/reset methods are disabled in V3.
- All **15 source offline checks passed**, exercising the real OCR engine, two native browser processes, complete paginated catalogues, delayed/loading/busy/stalled tables, shorter reverse delivery, fresh row indexes, cancellation, durable queue state and final-file publication.
- The new complete joint-round check opens both real browser workers against local HTML. A Pre request is found only in Post, downloaded once through the native download event, published into both temporary flat destinations and linked to its mail job in history. Only login, page content and session cleanup are replaced by local fixtures.
- The source GUI check reports 3.3.0, six representative queue states, visible deferred/busy labels, 60-second policy, two attempts, read-mail scanning, automatic-start trigger, Show password, Stop and the supplied window/header icon.

## Preserved boundaries

- Delivery remains flat and no-overwrite. No destination probes, account folders, log files or temporary sidecars are created in business destinations. Checks use isolated temporary folders and generated data.
- Existing Windows CREATE_NEW publication, reader exclusion during copying, hash verification, duplicate verification, cached-source repair, DPAPI, exclusive Log lock, compact state/monthly CSV, redaction, history search and body/OCR matching remain covered.
- The supplied multi-size icon remains unchanged: SHA-256 `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.
- PowerShell provider-qualified diagnostic path conversion remains covered by the regression suite; actual packaged arguments are checked before promotion.
- Shared state remains schema 3 with validated additive fields. Old exhausted requests migrate to deferred. Pending work retains its original date and survives midnight. Invalid/ambiguous requests require explicit review; a review or pending-save head holds its business-side queue.
- No unrelated application, Windows/SMB permission, credential format or business destination is changed. An existing incomplete final file is preserved and requires attention rather than automatic overwrite.

## Portable release

- The actual packaged 3.3.0 EXE passed all **15 offline checks**, including two-source native downloads, dual-destination final publication, OCR, paging, durable timing and busy-budget behavior.
- The actual packaged GUI passed and its Monitor/Settings screenshots were visually checked: six representative states, fully visible deferred/busy labels, 60-second mail/login policy, two attempts, password controls, Stop, icon and clean three-tab layout.
- Both packaged diagnostic commands were launched using PowerShell FileSystem-provider-qualified UNC output paths. Both exited successfully and wrote the expected real reports. Self-check and GUI reports are linked to the tested EXE by SHA-256 and record powershell_path_input_verified=true.
- The staged bundle contains only the EXE, _internal and Quick start.md at its top level, with bundled browser and English/Thai OCR.

Verified EXE SHA-256: `9d6d0dba4794958fcb5224cf78e6a570eeb6ff1c6e99021dd0bb2446d267eae2`.

Verified release folder: `portable`.

The verified 3.3.0 bundle replaced 3.2.4 at `portable`. Final EXE hash, bundled icon, three-item layout and removal of the old/staged bundle were checked after promotion. Only one portable folder remains. Local settings, cached downloads, shared logs/state and business files were preserved.

## Deployment boundary

Checks execute on **10.0.0.73**, accessing the project on **10.0.0.97**. They do not prove the Windows user's Outlook profile, share access or live KDE login/catalogue/download/logout on .97.

No real mailbox, production credential, business screenshot or live KDE service is used during verification. OCR uses generated representative images; exact extraction from every real image is not guaranteed. External image URLs are not fetched automatically.

The app polls local classic Outlook every 15 seconds by default. The one-minute deadline starts at discovery, not the mail server's receipt timestamp; queued work or an occupied account can delay actual processing. Busy probes run every 60 seconds plus operation time, not continuously. Full two-source matching waits for both enabled sources and never forces another user out. A successful availability probe is cleaned up before a fresh joint search, so live server logout behavior still needs deployment validation.

Known username/password rejection or account-lock messages pause for review. Unknown login errors use the bounded retry policy. Representative live portal messages and selectors should be checked on .97; no live performance benchmark is claimed.
