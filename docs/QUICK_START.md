# KDE Download 3.4.0

Open **KDE Bot Download V3.exe**. Keep **_internal** beside it. Python and OCR are not needed on the deployment machine.

## Setup

1. Open classic Outlook on the computer that will run KDE Download. Make the **data@tradeconnection.co.th** mailbox available.
2. In Settings, enter the enabled Pre/Post usernames and passwords. Credentials remain encrypted for this Windows user and computer. Keep both accounts enabled to download from both.
3. Select original, new or both destinations, and a separate writable Log folder. The download roots must already exist. Both roots must be readable because either may contain an existing file.
4. Click **Save & start**. Configured launches start the monitor automatically.

Use the whole configured data mailbox and incoming folders. Sent, Drafts, Outbox, Deleted and Junk folders are excluded; Notes/Calendar items do not trigger work. Read and unread incoming messages count equally. More options has an optional relative folder path, such as `Inbox\data`, for a future narrower scope; leave it blank for the confirmed mailbox-wide scope.

## How a round starts

Any previously unseen incoming message from today opens a **70-second window from discovery**. No subject, sender, body, attachment name, keyword or OCR match is required. The app only reads mail IDs and received times and does not change mail flags or content.

Mail discovered at 10:00:00 makes a round ready at 10:01:10. Mail discovered at 10:00:30 joins that deadline. Polling is every 15 seconds by default, so discovery can follow receipt by up to one polling interval. Queued work or login operations can delay processing after the deadline. A new arrival during active work queues a later round without interrupting the current files or extending an existing pending deadline.

First use discovers today's existing incoming mail and queues one sweep. Processed IDs survive restart, so reopening does not repeatedly trigger the same mail. With no new mail and no queued retry, KDE is not opened.

**Request download round** manually queues a sweep after the same 70-second window. **Round details** shows the account result. **Stop** waits for current save/session cleanup and preserves attempts and deadlines. History keeps chronological actions and exact errors, searchable by filename/reason. Settings retains Show password and remasks on Start/Stop.

## Which files download

Both enabled accounts use separate concurrent browser sessions. Each checks the full paginated catalogue, then downloads **every file dated today in Bangkok time**. No company, Pre/Post filename, business-word or email-text filter applies.

The date column displayed by KDE takes precedence. If it is absent, exactly one dated day in the filename can be used. An unreadable/unknown date is skipped and included in the account's date-skip count. A file whose name contains an older business date can still download if KDE's date column says today. Files dated yesterday are excluded even when their name suggests today.

Immediately before each file, both roots are checked for the **same Windows filename**:

- Original: `\\10.0.0.243\pgp-data$`
- New: `\\10.0.0.97\Z Bot KDE`

If present in either, skip it completely. Do not download again or copy it to the other root. Different extensions, dates and business numbers are separate filenames: `report.zip.gpg` and `report.xlsx.gpg` both qualify if missing. Windows lookup is case-insensitive. Existing zero-byte files, directories or access errors are reported and preserved rather than overwritten. Normal skips do not hash-check existing contents or add the between-download delay.

If absent from both, download to local staging, validate it and publish the final filename to the selected destination(s). Two workers coordinate duplicate filenames; exclusive final-file creation also protects against another user saving at the same time. A file appearing after the initial check is never overwritten.

At midnight, pending previous-day rounds expire. Each file is checked again at the download boundary; a download crossing midnight is discarded locally before publication. A save already publishing is allowed to finish safely. A new day's incoming mail starts a new sweep for that day.

## One retry

Each account gets an initial attempt plus **one retry after 60 seconds** when login is busy, the catalogue is empty, download/save fails or navigation fails. A successful account does not reopen just because the other account failed. The second attempt searches afresh and skips files already saved in either root.

After two failures, the account waits for new mail or Request download round. This is a bounded retry policy, including busy users; it does not continuously log in while idle. The app does not force another person out. A rejected password/locked account pauses until Stop, corrected Settings and a restarted monitor; then request a round or wait for new mail.

## Files and permissions

The app creates no account folders, permission-test files, .part files or logs in business destinations. Existing files are never replaced. Windows/SMB must permit reading either root and creating final files in selected roots. The separate Log folder must permit updates and cleanup.

Log location: **\\10.0.0.97\Z Log\Log Bot KDE**. It contains KDE_State.json, one CSV per month and the worker lock. Local settings/cache stay under **%LOCALAPPDATA%\KDE Bot Download V3**. Only one monitor may use the shared Log folder at a time.

If final saving fails, a validated local source is retained. Normal daily sweeps still obey the either-root skip rule. To explicitly finish an incomplete multi-destination save, Stop and use **Tools > Repair pending saves**. That action can fill the other root from an existing/cached verified source without opening KDE. It never overwrites a conflicting final file. Cached sources on another computer are unavailable unless retained on this computer.

A crash/network failure during final publication can leave an incomplete final filename. It is preserved and needs manual attention; the app cannot bypass permissions or safely overwrite it. Old matching queues/history and local credentials are preserved during upgrade, but the daily mode does not run old keyword/OCR requests. The portable contains only EXE, _internal and this guide; no OCR runtime, passwords, logs or business files ship inside it.
