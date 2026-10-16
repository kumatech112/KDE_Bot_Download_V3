# Verification — 2026-10-16 — 3.2.1

## Icon update

- The supplied download-file.ico was copied byte-for-byte to assets/app.ico. SHA-256: `8ad034733f09aeaca0ca829db1845eb738550f8b6717b574009b9d251060a587`.
- All seven ICO frames (16, 24, 32, 48, 64, 128 and 256 pixels) match the embedded Windows EXE icon resources exactly.
- The bundled _internal/assets/app.ico matches the original supplied ICO.
- Actual source and packaged GUI checks confirm the default window icon and 32-pixel header icon are applied. The packaged header was visually inspected.
- Compile, all 119 regression tests plus 4 subtests, and all eleven packaged offline checks passed for 3.2.1.
- The change is limited to the supplied icon, icon loading, build/release evidence, version and documentation. Mail, OCR, queue, credential and delivery behavior are preserved.

## Source checks completed

- Compile validation passed for src, tools and tests.
- **119 tests and 4 subtests passed** after the implementation changes.
- Actual local Tesseract recognized a generated filename screenshot; confidence was above the configured acceptance threshold and content caching prevented a second OCR call.
- Attachment/CID and base64 inline image paths were exercised with local fixtures. Remote image URLs/scripts were not executed or fetched.
- Today's read and unread messages were included; previous/future days and outgoing/system folders were excluded without changing read flags.
- Two-minute initial timing, processed-ID deduplication, two total attempts, fresh-session retry, five-minute busy/login cooldown and restart budgets passed.
- Per-account FIFO prevented overtaking, allowed the other account to work, held pending saves, and expired old-day work without an invisible queue block.
- Newest-first Outlook results were queued in received order. Duplicate-filename emails retained separate IDs.
- Unknown/conflicting account evidence became review jobs. Explicit confirmation retained deduplication and side guards.
- OCR character tolerance did not accept another business number or the other account side.
- Account/day matching, precise-reference precedence, cross-page ambiguity rejection, truncated page limits and changed rows were verified.
- Existing matching guards for extension variants, split volumes, dates, equal-score ambiguity and equivalent filenames remained covered.
- Actual Windows exclusive final-file creation held readers out until publication, refused competing existing files, and created no destination sidecars.
- Validated local sources survived save failure and repaired final filenames without another portal download; completed cache sources were removed.
- Destination diagnostics remained read-only, including with all synthetic destination writes rejected. Missing/unreadable folders remained failures.
- DPAPI, compact state/CSV, corrupt-state preservation, history search/replay, redaction, account concurrency and session/logout cleanup regressions remained covered.
- Source self-check passed with actual local OCR and actual offline browser pagination. Full-catalogue ambiguity and precise-reference selection were exercised against local HTML.
- Source GUI rendered and was visually checked: three English tabs, concise controls, accessible account settings, no theme selector, countdown, search/details and isolated automatic-start trigger.

## Portable release

- Portable build completed with the headless browser and local English/Thai OCR engine under _internal.
- The actual packaged EXE passed all eleven offline checks, including native browser pagination, OCR recognition, two concurrent browsers, durable queue timing/cooldowns, copy repair and final-name-only publication.
- The actual packaged GUI passed and was visually inspected: three English tabs, four sample queue states, 120-second delay, read-mail policy, automatic-start trigger, history search and readable details.
- Reports are linked to the tested EXE by SHA-256. No real mailbox or KDE portal was contacted.

Verified EXE SHA-256: `e97ca3737e0197ab62ef5dd33f6a5efa4eee35bba1cc61130f50ca4f38a7f7d5`

Verified release folder: `portable`.

The verified 3.2.1 bundle was promoted to `portable`, its EXE hash was rechecked, and the identified old bundle was removed. No staged or previous portable folders remain. Only EXE, _internal and Quick start.md are distributed. Local settings, cached sources, shared history and business files were preserved.

## Deployment boundary

Checks execute on **10.0.0.73**, accessing the project on **10.0.0.97**. They do not prove the Windows user's Outlook profile, share access or live KDE selectors/login/download/logout on .97.

No real mailbox content, credentials, business image or production download was used in verification. No production business files were moved, deleted or overwritten. No Windows/SMB permission changes or unrelated application changes were made.

OCR validation uses generated representative text images, not the user's real email screenshots. Local English/Thai recognition is provided, with documented image limits and review behavior; exact extraction from every real image is not guaranteed. External image URLs are not fetched automatically.

The portal catalogue check verifies the pagination logic against local HTML. Missing/changed actual portal controls fail safely and require deployment validation. The app remains local Outlook polling (15 seconds by default), not an email server webhook or a cloud AI service.

Final-filename-only publication uses a reader lock and durable local source/hash rather than destination rename sidecars. A crash can leave an incomplete final filename that is preserved and reported, never silently overwritten. Shared Log must permit normal updates; actual final-file access is still required.
