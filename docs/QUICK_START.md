# KDE Download 3.2.4

Open **KDE Bot Download V3.exe**. Keep **_internal** beside it. Python and a separate OCR installation are not required.

## First setup

1. On the computer that will run the app, open classic Outlook with the required mailbox available.
2. Open **Settings**. Enter the enabled Pre/Post usernames and passwords. Passwords remain encrypted for this Windows user and machine.
3. Choose the destinations and a separate Log folder. Both accounts save directly in the chosen destination roots.
4. Click **Save & start**. On later launches, a configured app starts monitoring automatically.

The executable's network location does not determine where Outlook or credentials are read: the launching computer runs the app.

## Everyday use

- **Monitor** shows one row per email/image request, its account, queue order, remaining wait, attempts and result.
- **Stop** ends monitoring, waits for the current save and logout, and retains queued requests and attempt counts. **Start monitor** resumes retained work under the same timing and retry rules.
- **History** keeps chronological actions and exact failures. Search or double-click an event for details.
- **Settings** contains the mailbox, destinations and two accounts. Stop before changing settings. Each account has **Show password**, initially unchecked. Revealed passwords hide again on Start or Stop. Less common options are behind **More options**.
- **Tools** contains connection checks, failed-request retries, pending-save repair and imports.

## Mail and queue rules

The app reads today's incoming mailbox messages in Bangkok time, including messages already marked read. It never marks messages read, sends email, or changes mail contents. Sent, Drafts, Outbox, Deleted and Junk folders are excluded by available default-folder identities and common folder names; incoming custom folders remain searchable.

New qualifying mail waits **two minutes from discovery**. Each account processes one request at a time, in arrival/discovery order. Pre and Post use independent sessions and can run together. New requests cannot overtake an earlier request or its retry for the same account.

No queued work means no KDE login. Each request gets **two attempts total**. A busy user or login failure waits five minutes before its second attempt. Missing/download failures retry in a fresh session after logout. After two failures, the request stops; new mail does not reset its budget. Closing/reopening retains attempts and processed IDs. Older-day waiting work expires instead of opening KDE automatically.

## Images and matching

The complete portal catalogue is checked first, then requested files are downloaded while returning through the pages. Files on later pages can arrive first within a request; email requests retain their per-account queue order. If a page never finishes loading or does not change, the app reports an error instead of assuming navigation succeeded.

The current email body can name a complete file or just its business words. A clear file/download instruction takes priority over an unrelated subject. For example, `1015` plus `Pre payment online 67097` can identify the file even without its full name. If no company keyword is present, the same business words are still checked. A company keyword alone never downloads anything.

`A10XX` means your `A1015` Pre account; `A10XXL` means your `A1015L` Post account. Generic `Axxxx` or `L10xx` placeholders do not identify the side: the email must say Pre/Post or the request needs review. A trailing `xxxxxx` date placeholder is ignored; the email day applies unless another explicit business date/month is supplied. Explicit dates such as `09102026` remain meaningful even if the email arrived today.

Supported supplied examples include `TSS_ReviewAc_AYCAP`, `Daily_Recovery_Performance_Oct26`, `SAM_CustomerRequest_JA2`, `Document_Round2`, `TSS_Document_AYCAP`, `SelectACLitigation_LegalType_11_21_31_StopAC`, `TSS_HC_Report_App_ProWO`, and `Db_Bank_KTA_TSS`. Incomplete references must still match all supplied business words and numbers. Equally plausible different files remain unselected. This is local rule-based matching, not unrestricted language understanding.

The bundled local OCR engine reads English/Thai text from image attachments and locally embedded email pictures, including CID attachments and base64 HTML images. Supported image formats: PNG, JPEG, GIF, BMP, TIFF and WebP. Subject, body and attachment filename evidence are also used. A filename in the email can have a different archive/document extension from KDE.

Use **Import image** for a separate screenshot, choose Pre or Post, and click **Read image & queue**. Recognized references join the same durable queue and two-minute delay.

Matching checks account side, business references, numbers and dates. An explicit business date takes precedence; otherwise a broad reference must match the email's day. Minor OCR character differences are tolerated conservatively without substituting a different business number. The full portal catalogue within the configured page limit is checked before a download; ambiguous matches are not chosen merely because they appear first. Rows are rechecked before clicking.

Unclear account routing or weak OCR becomes **Needs review**. Select the request, click **Review request**, confirm the account/reference, then queue it. An exhausted request can also be corrected explicitly; this starts a new, visible two-attempt cycle. Images are data only, never instructions for the app.

OCR is bounded to six local images per message, 15 MB per image and 24 megapixels, with a recognition timeout. External image URLs are not fetched; use Import image for pictures available only through remote links. Only the first frame of a multi-frame image is read. OCR cannot guarantee exact text from every image. Validate representative real emails on the deployment machine before relying on unattended processing.

## Storage and permissions

- Original default: **\\10.0.0.243\pgp-data$**
- New default: **\\10.0.0.97\Z Bot KDE**
- Log default: **\\10.0.0.97\Z Log\Log Bot KDE**

The business destinations must already exist. The app creates **no account folders, permission-test files, .part files or log files there**. Downloads are completed in one local cache folder, validated, then saved under the final business filename using exclusive creation. Existing files are never replaced. Matching existing files are hash-verified and skipped; different/incomplete content requires attention.

Windows/SMB must allow saving and reading the final file. Calling an operation a download does not bypass file permissions. On Windows the new file is locked against other readers until publication finishes and its hash is verified. A crash or failed save can leave an incomplete final file; it will not be overwritten automatically. Check/remove that specific incomplete file with appropriate access before repairing the save.

If saving fails, the validated local source is retained. Stop and use **Tools > Repair pending saves**. Repair does not log in or redownload. A pending save holds later work for that account until it is repaired. Restart the monitor after repair. Another machine cannot use a local cached source that exists only on the original machine.

The separate Log folder holds **KDE_State.json**, **one CSV per month**, and the worker lock. It must permit updates and cleanup. Only one monitor may own the shared Log folder at a time; its two internal account workers are allowed. Local settings/cache live under **%LOCALAPPDATA%\KDE Bot Download V3**, keeping the program folder clean.

The app does not remove old permission-test leftovers or move existing business files. Source, release and logs remain separate. Git contains source and documentation, not passwords, business files, raw mail/images, local settings or the portable bundle.
