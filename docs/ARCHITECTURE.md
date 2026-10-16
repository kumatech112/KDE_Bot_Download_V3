# KDE 3.3 data flow and changed functions

## 3.3.0 current workflow

Per-user settings → read-only business destination checks / writable shared Log lock → repair pending saves → today's incoming Outlook messages → body/subject/local OCR evidence → company, file-side and business-date references → durable fixed one-minute window → oldest eligible request per business side → one joint search round → concurrent isolated Pre/Post browser sessions → complete catalogues from both sources → global selection or review → local validated download → exclusive final filename publication and hash verification → own-session logout → complete, pending save, immediate fresh-session retry, or deferred until new relevant mail.

Each source worker owns its Playwright runtime and browser. A condition coordinates only Python catalogue data; browser objects never cross worker threads. No download begins until every enabled source has supplied its complete catalogue. A file can be found in the other source account while retaining the email's requested business side. Equivalent duplicates select one source in configured order. Different plausible files, including opposite business sides without enough evidence, require review. The original numeric/company/date guards remain active.

The monitor continues to scan Outlook while a round is active. New mail increments a durable generation counter and records an absolute window deadline. New arrivals share the earliest open unattempted window rather than resetting it. Deferred jobs wake on a new generation; a final failed attempt also notices mail that arrived while it was running. A round snapshots the generation when its first attempt starts, preventing repeated self-triggered rounds. Restart preserves deadlines, attempts and deduplication IDs. New scan input is today-only; pending work survives midnight with its original business date.

Two attempts per round means the first search/download attempt plus one fresh-session retry. Missing/download failures retry after cleanup with no additional mail delay. Ordinary login failures wait 60 seconds. Two failures defer the request and release its business-side FIFO head. Review and pending-save heads still block later work for that side. At most one head per business side enters a round, and only one round runs at a time, preventing overlapping sessions for a source account.

Confirmed account-busy failures refund the attempt and persist a separate 60-second availability deadline. While busy, only the occupied source is probed; available sessions close. A successful probe is cleaned up, followed by fresh full catalogues from both sources. There is no fixed maximum number of busy checks while work remains. This deliberately waits for both sources rather than downloading from an incomplete candidate set. Credential rejection/lock pauses in review; unknown login/network failures remain bounded. V3 never calls account-wide reset or username-based sign-out. Only an acquired browser session is eligible for cookie-bound logout. Stop cancels waits and lets file publication and cleanup finish.

| File | Changed functions or classes | Responsibility |
|---|---|---|
| src/kde_bot/settings.py | default_settings, normalize_settings, validate_settings | Enforce 60-second mail/busy/login policy and two attempts; retain user paths, read-mail scan and DPAPI |
| src/kde_bot/mail_queue.py | window_due, ingest | Coalesce arrivals into one absolute window; record mail generations; awaken deferred requests on genuinely new mail; allow meaningful unknown-side searches |
| src/kde_bot/mail_queue.py | recover_interrupted, expire_old, snapshot | Migrate old exhausted requests to deferred; preserve budget/deadlines; keep pending cross-day work visible |
| src/kde_bot/mail_queue.py | claim_ready, finish | Durable FIFO claims; round generation; two-attempt budget; busy refund/cooldown; review and deferred outcomes; mail-during-final-retry handling |
| src/kde_bot/mail_queue.py | resolve, requeue_failed | Explicit reference corrections and manual retry rounds using the new window |
| src/kde_bot/search_round.py | AccountBusyError, CredentialsError | Distinguish retryable occupancy from credentials requiring attention |
| src/kde_bot/search_round.py | SearchCoordinator.__init__, fail, select | Wait for complete source catalogues; release peers on failure/Stop; select against their union and map plans to owning source rows |
| src/kde_bot/search_round.py | run_search_round, source_task | Persist busy/blocked sources; probe only occupied accounts; run both workers; merge per-request download evidence and ambiguity |
| src/kde_bot/workflow.py | StructuredDownloader.__init__, protocol_message, _login_with_retry | Track acquired sessions; single login attempt; classify occupancy and recognized credential rejection |
| src/kde_bot/workflow.py | _select_page_mail_matches, _download_visible_pages | Preserve business-side/date/company guards across sources; use the coordinator's global plan before existing reverse delivery |
| src/kde_bot/workflow.py | _open_download_page, auto_signout, signout, _logout_browser_session, process_account | Login-only busy probes; disable account-wide resets; clean up only owned sessions and expose cleanup failures |
| src/kde_bot/workflow.py | run_account_batch, run_mail_monitor | Separate source state files and engines; release waiting peer on setup/error; one joint round while mail ingestion continues |
| src/kde_bot/storage.py | History.__init__ | Validate deferred jobs, source busy/credential state, mail generations and deadlines; retain schema 3 and existing files |
| src/kde_bot/gui.py | build_controls, build_monitor, advanced_settings, review_request, render_jobs, launch | Explain current policy; show fully readable Account busy / Waiting for new email, deferred count, explicit retry tools and six smoke states |
| src/kde_bot/selfcheck.py | check_agent_features, check_joint_search_round, check_round_timing, run_self_check | Update deadlines; real two-browser cross-account download/dual delivery; packaged timing/restart/busy-budget proof |
| tools/promote_portable.py | main | Require the new 60-second policy and visible deferred/busy states in hash-linked packaged GUI evidence |

Storage delivery code, Outlook scanning implementation, icon and password controls are retained. Tests are changed only to match the authorized policy and add meaningful regressions. The following 3.2 sections describe earlier changes; their old timing and expiry policies are superseded by 3.3 above.

## 3.2.4 reviewed performance patch

The supplied speed_fixes.patch, workflow.py, test_agent_workflow.py and CHANGES.md were compared with 3.2.3. The patch matched both supplied Python files. Bulk table reads and reverse delivery were retained; three readiness/click hazards were corrected before release:

- The supplied wait returned without an error on timeout, allowing the caller to treat an unchanged page as successfully loaded. Timeout now raises a clear error; Stop returns cancellation.
- Two equal text readings could accept a loading placeholder. Readiness now requires complete file columns, no declared aria-busy ancestor, and 450 ms of stable changed row data. Empty/loading/old states reset the stability period. Configured/caller timeouts are respected. Only backward navigation can use a genuinely empty table as its starting state after files have disappeared; the destination still requires ready file rows.
- Cached row positions could become stale after a download removed/reordered a row. The requested filename, timestamp and size are rechecked in a fresh bulk snapshot before every file action.

| File | Functions | Change |
|---|---|---|
| workflow.py | _table_signature, _wait_table_change, _click_page_button | One-call readiness signatures; changed/stable file rows; explicit timeout/read failures; Stop cancellation |
| workflow.py | _next_page, _previous_page, _has_next_page | Shared button selectors and verified navigation without networkidle or a fixed 1.5-second pause |
| workflow.py | _table_rows | One evaluate_all call per row snapshot, original row indexes retained, legacy reader fallback on unsupported calls |
| workflow.py | _download_visible_pages | Complete catalogue first; deliver backward only as far as the earliest selected page; refresh selected rows before each action |
| selfcheck.py | check_portal_paging, run_self_check | Real offline browser with background polling, 750 ms loading placeholders, emptied pages, moved row indexes, stalled navigation and Stop |

The reverse delivery pass changes file order within one request; durable email FIFO per account, 120-second delay, exactly two attempts, account/date/number matching, global ambiguity checks, and no-overwrite final publication remain in place. Login navigation is unchanged. The clean portable layout, English GUI, icon, Show password and Stop controls are retained. No supplied scratch copies are placed in the project root.

## 3.2.3 changed functions

| File | Functions | Change |
|---|---|---|
| src/main.py | filesystem_path | Strip a leading FileSystem provider qualifier before Path can collapse the UNC backslashes; reject empty or non-filesystem provider inputs |
| src/main.py | main | Use the converter for the three diagnostic output arguments; retain isolated diagnostic execution and unchanged normal launch |

The reported WinError 161 came from a verification command passing PowerShell's provider-qualified location as a Windows path. This is separate from business destination permissions. The fix stays at the launch-argument boundary; no destination, credential, matching or queue implementation is modified. Source VERSION and release documentation are updated.

3.2.2 adds body-instruction matching and password visibility, and labels graceful stop explicitly. Unrelated applications, delivery paths, no-overwrite publication, stored credentials, two-minute queue timing and two-attempt retry budgets are unchanged. The supplied multi-size icon remains embedded and bundled.

## 3.2.2 changed functions

| File | Functions | Change |
|---|---|---|
| instructions.py | current_body, normalize_template_markers, instruction_lookup | Bound current sender text, normalize own-company templates, extract partial business references and retain explicit dates/numbers |
| instructions.py | instruction_match, own_company_compatible | Require all business words/numbers, account/date compatibility and own company; retain equal-quality ambiguity protection |
| evidence.py | correct_reference, MailEvidenceReader.read | Correct account OCR before underscores, read plain Body and HTML, expose preferred body instructions and review-only company hints |
| legacy_core.py | scan_mail_filenames / scan_folder | Use V3 preferred body references for each message while retaining the generic scanner's compatibility |
| mail_queue.py | route_lookup, MailQueue.ingest | Prefer the body/image's explicit side over generic subject labels, while rejecting conflicts with coded file references |
| workflow.py | StructuredDownloader._match_single_mail_key, run_mail_monitor | Apply guarded partial-body matching; report stopped sessions clearly |
| gui.py | Application.__init__, build_controls, add_field, toggle_password, hide_passwords, fill_settings | Independent transient visibility controls, default masking and explicit Stop button |
| gui.py | stop, set_busy, drain_events, import_configuration, import_history, repair_saves, launch | Remask passwords, preserve safe stopping, consistent English labels, exercise both controls in isolated GUI smoke |
| selfcheck.py | check_body_instructions, run_self_check | Verify matching in the actual portable executable with isolated fixture data |
| tools/promote_portable.py | main | Require the packaged password and Stop checks before release promotion |

Full names continue through the existing precise matching path. Partial body references use all business words and exact numeric identifiers, plus the existing per-job date/account filtering and global catalogue selection. The eight user-supplied references are regression fixtures. A company code alone produces no selector; neutral generic company patterns require separate side evidence. Current explicit body file instructions override unrelated subject references; quoted message history is not used as the current instruction. Rules remain bounded and conservative rather than claiming arbitrary natural-language understanding.

Current data flow and retry policy are defined in the 3.3.0 section above. The retained function map below includes prior features.

## Production function map

| File | Changed or added functions | Responsibility |
|---|---|---|
| settings.py | default_settings, normalize_settings, validate_settings, credential/load/import notices | Enforce 60 seconds, today-only read/unread scanning, two attempts per round, separate Log; preserve paths and DPAPI credentials |
| evidence.py | today, correct_reference, reference_lookup | Bangkok date, contextual OCR account-code correction, existing reference/Thai aliases |
| evidence.py | EmbeddedImages, LocalOCR.read, MailEvidenceReader.read/screenshot | Local attachment/CID/data-image OCR; bounded content caching; confidence and review evidence; screenshot import |
| matching.py | row_matches_job_date, ocr_match | Explicit business dates or email day; conservative OCR similarity with number/account/split-part guards |
| legacy_core.py | scan_mail_filenames and received_datetime/scan_folder | Include today's read mail; skip outgoing/default folders; invoke the optional V3 evidence hook; preserve generic portal engine behavior |
| legacy_core.py | process_account | Do not create a business destination when the V3 file handler is installed |
| mail_queue.py | reference_side, route_lookup, MailQueue.ingest | Pre/Post routing including wildcard account markers; visible review requests; durable ordering and deduplication |
| mail_queue.py | expire_old, recover_interrupted, claim_ready, snapshot | Retain attempts and cross-day pending work; one eligible head per business side; prevent overtaking; send concise UI snapshots |
| mail_queue.py | resolve, requeue_failed, finish, refresh_saved_jobs | Explicit corrections/new retry cycles; two-attempt limits and cooldowns; verified copy repair releases the queue |
| storage.py | open_new_target, verified_copy | Windows CREATE_NEW and no shared readers while publishing; only final filenames at destinations; never replace existing content |
| storage.py | cached_source, Delivery._deliver, History.__init__ | Trusted local staged source; durable per-destination pending state; cache reuse/removal; review/expired schema validation |
| workflow.py | StructuredDownloader.__init__, _match_single_mail_key, _select_page_mail_matches | Evidence reader, conservative fallback, per-job account/date guards and precise-reference precedence |
| workflow.py | _has_next_page, _previous_page, _download_visible_pages | Catalogue all permitted pages; reject global ambiguity/page-limit truncation; recheck rows before click |
| workflow.py | download_to_cache, handle_file | Keep .part files in local cache; link file history to mail jobs; deliver only final business names |
| workflow.py | run_cycle, run_mail_monitor, run_account_batch, reporting methods | Repair without portal; process image/review commands; joint rounds with isolated source workers; English events and live queue snapshots |
| gui.py | Application builders, advanced_settings, field/config helpers | Three English tabs; small primary toolbar; secondary tools/options; preserved native ttk, no theme selector |
| gui.py | auto_start, start, stop, close, drain_events | Automatic configured launch, worker boundaries and graceful logout |
| gui.py | import_image, review_request, retry_failed, repair_saves | Local image requests and explicit human corrections through the owning monitor's command queue |
| gui.py | render_jobs, render_activity, selected_details, load_history, tick | One row per request; countdown; retained chronological history; readable evidence/details |
| gui.py | launch | Actual GUI smoke with three rendered pages, search/details and an isolated auto-start check |
| activity.py | read_activity | English folder-access error; historical CSV contents retained |
| selfcheck.py | check_agent_features, existing checks | Actual OCR sample, FIFO/cooldown and final-name-only publication; preserved packaged checks |
| tools/build_portable.py | bundle_ocr, main | Include OCR executable/libraries, English/Thai models and notices under _internal; one English quick-start file |
| tools/promote_portable.py | validate_bundle, main | Accept identified old/new manual names; require English three-tab, auto-start, 60-second, deferred/busy and read-mail evidence before promotion |

## Boundaries

The agent behavior is local OCR plus explicit workflow/matching rules. No cloud model, email/image upload, web-image fetch or remote instruction execution is added. Outlook attachments are extracted through [Microsoft's SaveAsFile API](https://learn.microsoft.com/en-us/office/vba/api/outlook.attachment.saveasfile) into temporary local storage. OCR uses [Tesseract's command-line TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

The shared state remains schema 3 and retains older history. Old account-folder overrides remain ignored. Review requests never open a portal session until account/reference confirmation. A review/pending-save head blocks later work for its assigned business side; the other side can supply its head to a joint round. Both enabled portal sources must be available for that round's matching.

Final-name-only publication cannot use an atomic destination rename because destination sidecars/renames are excluded by this design. Instead, Windows readers are locked out during copying/verification. Local source and expected hash are saved before publication. A process/network failure may leave a partial final filename; subsequent delivery preserves it and reports the conflict. This tradeoff is documented in Quick Start.

The full-catalogue pass uses the existing next-page controls plus corresponding previous-page controls. Changed/missing pagination or a truncated page limit fails before an unsafe click. Tests cover a changed row and cross-page ambiguity; the actual KDE portal selectors still require deployment validation.

Only KDE files in this project are changed. KUMA, MI, Routine, Talktime, other credentials and Windows/SMB permissions are untouched.
