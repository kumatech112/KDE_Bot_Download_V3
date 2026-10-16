# KDE 3.2 data flow and changed functions

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

Flow: per-user settings → read-only business destination checks / mutable shared Log lock → pending-save repair → today's Outlook messages → text + local OCR evidence → account/date routing or review → durable two-minute FIFO → isolated Pre/Post sessions → full-catalogue matching → local validated download → exclusive final-file publication → hash verification → logout → completion or one bounded retry.

## Production function map

| File | Changed or added functions | Responsibility |
|---|---|---|
| settings.py | default_settings, normalize_settings, validate_settings, credential/load/import notices | Enforce 120 seconds, today-only read/unread scanning, two attempts, separate Log; preserve paths and DPAPI credentials |
| evidence.py | today, correct_reference, reference_lookup | Bangkok date, contextual OCR account-code correction, existing reference/Thai aliases |
| evidence.py | EmbeddedImages, LocalOCR.read, MailEvidenceReader.read/screenshot | Local attachment/CID/data-image OCR; bounded content caching; confidence and review evidence; screenshot import |
| matching.py | row_matches_job_date, ocr_match | Explicit business dates or email day; conservative OCR similarity with number/account/split-part guards |
| legacy_core.py | scan_mail_filenames and received_datetime/scan_folder | Include today's read mail; skip outgoing/default folders; invoke the optional V3 evidence hook; preserve generic portal engine behavior |
| legacy_core.py | process_account | Do not create a business destination when the V3 file handler is installed |
| mail_queue.py | reference_side, route_lookup, MailQueue.ingest | Pre/Post routing including wildcard account markers; visible review requests; durable ordering and deduplication |
| mail_queue.py | expire_old, recover_interrupted, claim_ready, snapshot | Retain attempts; expire old waiting work; one head request per account; prevent overtaking; send concise UI snapshots |
| mail_queue.py | resolve, requeue_failed, finish, refresh_saved_jobs | Explicit corrections/new retry cycles; two-attempt limits and cooldowns; verified copy repair releases the queue |
| storage.py | open_new_target, verified_copy | Windows CREATE_NEW and no shared readers while publishing; only final filenames at destinations; never replace existing content |
| storage.py | cached_source, Delivery._deliver, History.__init__ | Trusted local staged source; durable per-destination pending state; cache reuse/removal; review/expired schema validation |
| workflow.py | StructuredDownloader.__init__, _match_single_mail_key, _select_page_mail_matches | Evidence reader, conservative fallback, per-job account/date guards and precise-reference precedence |
| workflow.py | _has_next_page, _previous_page, _download_visible_pages | Catalogue all permitted pages; reject global ambiguity/page-limit truncation; recheck rows before click |
| workflow.py | download_to_cache, handle_file | Keep .part files in local cache; link file history to mail jobs; deliver only final business names |
| workflow.py | run_cycle, run_mail_monitor, run_account_batch, reporting methods | Repair without portal; process image/review commands; independent ordered workers; English events and live queue snapshots |
| gui.py | Application builders, advanced_settings, field/config helpers | Three English tabs; small primary toolbar; secondary tools/options; preserved native ttk, no theme selector |
| gui.py | auto_start, start, stop, close, drain_events | Automatic configured launch, worker boundaries and graceful logout |
| gui.py | import_image, review_request, retry_failed, repair_saves | Local image requests and explicit human corrections through the owning monitor's command queue |
| gui.py | render_jobs, render_activity, selected_details, load_history, tick | One row per request; countdown; retained chronological history; readable evidence/details |
| gui.py | launch | Actual GUI smoke with three rendered pages, search/details and an isolated auto-start check |
| activity.py | read_activity | English folder-access error; historical CSV contents retained |
| selfcheck.py | check_agent_features, existing checks | Actual OCR sample, FIFO/cooldown and final-name-only publication; preserved packaged checks |
| tools/build_portable.py | bundle_ocr, main | Include OCR executable/libraries, English/Thai models and notices under _internal; one English quick-start file |
| tools/promote_portable.py | validate_bundle, main | Accept identified old/new manual names; require English three-tab, auto-start, 120-second and read-mail evidence before promotion |

## Boundaries

The agent behavior is local OCR plus explicit workflow/matching rules. No cloud model, email/image upload, web-image fetch or remote instruction execution is added. Outlook attachments are extracted through [Microsoft's SaveAsFile API](https://learn.microsoft.com/en-us/office/vba/api/outlook.attachment.saveasfile) into temporary local storage. OCR uses [Tesseract's command-line TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

The shared state remains schema 3 and retains older history. Old account-folder overrides remain ignored. The new policy changes the initial delay to two minutes and stops old-day waiting work; it does not reset consumed attempts. Review requests never open a portal session until account/reference confirmation. A review/pending-save head blocks later work for its assigned account; the other account can continue.

Final-name-only publication cannot use an atomic destination rename because destination sidecars/renames are excluded by this design. Instead, Windows readers are locked out during copying/verification. Local source and expected hash are saved before publication. A process/network failure may leave a partial final filename; subsequent delivery preserves it and reports the conflict. This tradeoff is documented in Quick Start.

The full-catalogue pass uses the existing next-page controls plus corresponding previous-page controls. Changed/missing pagination or a truncated page limit fails before an unsafe click. Tests cover a changed row and cross-page ambiguity; the actual KDE portal selectors still require deployment validation.

Only KDE files in this project are changed. KUMA, MI, Routine, Talktime, other credentials and Windows/SMB permissions are untouched.
