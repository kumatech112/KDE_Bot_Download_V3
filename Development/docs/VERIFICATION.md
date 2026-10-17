# Verification — 2026-10-17 — 3.8.2

## Organized layout

The KDE project now mirrors the inspected MPFM layout: Program contains the current portable; Development contains all complete source, tests, tools, assets, dependency/configuration files and detailed docs; Archive contains previous releases, build staging and verification evidence. A root shortcut targets Program with Program as its working directory. Git remains at the existing root and excludes Program, Archive, the shortcut and runtime/private data.

Original development folders and verification files were moved without deletion. The old 3.8.1 bundle was fingerprinted across all 1,665 files before archival; preservation evidence is in Archive. Source renames and modifications are reviewable in Git. The new builder and promoter stage only inside Archive and install the stable Program after validating hash-linked checks. The promoter checks local processes and read-only exclusive SMB access, preserves the identified old bundle, and rolls back the bundle paths/launcher on installation failure.

## Validation

- The prior verified 3.8.1 revision passed 306 tests and 4 subtests. After reorganization, **315 tests and 4 subtests passed** from Development.
- New layout regressions test designated Program/Archive bundle locations, wrong executable hashes and rejected outside/unknown folders. Startup tests cover exact own legacy-command migration to Program; unrelated registry commands remain protected.
- The final resolved archive-target guard was checked again with all 7 layout tests passing. Syntax compilation passed for source, tools and tests.
- Actual rebuilt Thai EXE GUI check passed. Four Settings sections, icons, passwords/Stop, history and .243 → .97 settings remain present; the storage screenshot was visually inspected.
- The actual staged EXE background lifecycle passed with an isolated profile: hidden launch, background duplicate stays hidden, manual reopen shows the same window, X hides without exit, tray Exit ends normally. No live credentials, production writes, startup registration or task registration were used.
- All **16 actual packaged offline checks passed**. The verified EXE is installed in Program and the shortcut target/working directory were read back successfully. All **1,665 archived old bundle files match their original SHA-256**. Download and Log/state before/after fingerprints match. Evidence is recorded in Archive/verification and Archive/organization-preservation files.

Built/tested EXE SHA-256: `cb458fb723227352dab2e022830a0832b89e8c3002fb57dd93c871dbcc122c72`.

## Runtime boundaries

The current-day mail trigger, selected timing, sequential Pre/Post browsing, 30-row pages, .243-first download/.97 copy, exact duplicate checks and folder-preserving cleanup are unchanged. Downloads remain in `\\10.0.0.243\pgp-data$` / `\\10.0.0.97\Z KDE Bot`; state/CSV remain in `\\10.0.0.97\Z Log Bot\KDE Log Bot`; passwords remain local to the running Windows user. No MPFM files or permissions were changed.

Checks ran on .73 against the .97 project share. Open the new root shortcut once on .97 to load existing settings and migrate its own recognized Windows startup command from portable to Program. Actual .97 Outlook/KDE/share permissions and sign-in startup activation remain target-machine checks. Task Scheduler remains unnecessary. Existing timing choices and the 22:00/05:00 defaults, tray requirement, no missed-night cleanup and same-day deletion journal remain unchanged.
