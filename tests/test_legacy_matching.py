from __future__ import annotations

import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import kde_downloader_core as core
from kde_downloader_core import (
    DEFAULT_MAIL_FILENAME_REGEX,
    Account,
    KdeDownloader,
    MailWatchSettings,
    Settings,
    business_dates_are_compatible,
    business_file_identity,
    canonical_file_identity,
    dated_business_file_identity,
    downloaded_file_identities,
    normalize_filename_for_match,
    normalized_business_dates,
    state_has_downloaded_filename,
)


def make_downloader(state_file: Path) -> KdeDownloader:
    settings = Settings(
        portal_url="https://example.invalid/kde-portal",
        host_url="https://example.invalid",
        auth_api_url="https://example.invalid/auth",
        chrome_path="",
        headless=True,
        download_new_only=True,
        search_days=1,
        max_pages=5,
        download_delay_seconds=0,
        busy_wait_seconds=300,
        loop_wait_seconds=300,
        page_timeout_seconds=45,
        state_file=state_file,
        mail_watch=MailWatchSettings(
            enabled=True,
            today_only=False,
            unread_only=True,
            include_subject=True,
            include_body=True,
            max_messages_per_folder=500,
            max_body_chars=20000,
            match_mode="contains",
            filename_regex=DEFAULT_MAIL_FILENAME_REGEX,
            mailbox_filter="data@tradeconnection.co.th",
        ),
        accounts=[
            Account(
                label="02 Post",
                username="A1015L_sumontrees",
                password="",
                download_dir=state_file.parent,
                enabled=True,
            )
        ],
    )
    return KdeDownloader(settings, log=lambda _message: None)


class MissingLoginPage:
    def __init__(self) -> None:
        self.url = "https://example.invalid/default_error_page"
        self.goto_urls: list[str] = []
        self.context = MagicMock()

    def goto(self, url: str, **_kwargs) -> None:
        self.goto_urls.append(url)

    def locator(self, _selector: str):
        locator = MagicMock()
        locator.wait_for.side_effect = core.PlaywrightTimeoutError("missing login form")
        return locator


class LoginRetryTests(unittest.TestCase):
    def test_missing_login_form_uses_portal_entry_for_all_three_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            downloader.settings.busy_wait_seconds = 0
            downloader._wait_network = MagicMock()
            downloader._prepare_login_retry = MagicMock()
            page = MissingLoginPage()
            account = downloader.settings.accounts[0]

            with patch.object(core, "wait_or_stop", return_value=True):
                with self.assertRaisesRegex(core.KdeDownloadError, "after 3 attempts"):
                    downloader._login_with_retry(page, account, 1000)

            self.assertEqual([downloader.settings.portal_url] * 3, page.goto_urls)
            self.assertEqual(2, downloader._prepare_login_retry.call_count)


class CanonicalIdentityTests(unittest.TestCase):
    def test_packaging_and_document_extensions_share_one_identity(self) -> None:
        filenames = [
            "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.xlsx.gpg",
            "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.zip.gpg",
            "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.7z.gpg",
            "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.docx.pgp",
        ]

        identities = {canonical_file_identity(filename) for filename in filenames}

        self.assertEqual(1, len(identities))

    def test_duplicate_identity_keeps_dates_distinct(self) -> None:
        first = "260529_A1015L_A1015L_Document_Round2_29052026.zip.gpg"
        second = "260530_A1015L_A1015L_Document_Round2_30052026.zip.gpg"

        self.assertNotEqual(canonical_file_identity(first), canonical_file_identity(second))
        self.assertEqual(business_file_identity(first), business_file_identity(second))

    def test_split_archive_parts_remain_distinct(self) -> None:
        first = "260608_A1015L_A1015L_VOL61_20260608.7z.001.gpg"
        second = "260608_A1015L_A1015L_VOL61_20260608.7z.002.gpg"

        self.assertNotEqual(canonical_file_identity(first), canonical_file_identity(second))

    def test_business_identity_retains_non_date_numeric_identifiers(self) -> None:
        first = "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.xlsx.gpg"
        second = "260529_A1015L_A1015L_Results_Review_Billcode_67098_29052026.xlsx.gpg"

        self.assertNotEqual(business_file_identity(first), business_file_identity(second))

    def test_business_dates_accept_portal_prefix_and_business_date_for_same_day(self) -> None:
        mail_name = "A1015L_Document_Round2_30092026.zip"
        kde_name = "260930_A1015L_A1015L_Document_Round2_30092026.zip.gpg"

        self.assertTrue(business_dates_are_compatible(mail_name, kde_name))
        self.assertIn("2026-09-30", normalized_business_dates(kde_name)[0])

    def test_business_dates_reject_different_days(self) -> None:
        mail_name = "A1015L_Document_Round2_30092026.zip"
        kde_name = "260929_A1015L_A1015L_Document_Round2_29092026.zip.gpg"

        self.assertFalse(business_dates_are_compatible(mail_name, kde_name))
        self.assertNotEqual(
            dated_business_file_identity(mail_name),
            dated_business_file_identity(kde_name),
        )

    def test_state_detects_same_file_with_different_extension(self) -> None:
        existing = "260623_A1015L_A1015L_Other_23062026.7z.gpg"
        incoming = "260623_A1015L_A1015L_Other_23062026.zip.gpg"
        account_state = {
            f"{existing}|23/06/2026|1 MB": {
                "filename": existing,
                "saved_path": rf"\\server\share\{existing}",
            }
        }

        self.assertTrue(state_has_downloaded_filename(account_state, incoming))
        self.assertIn(canonical_file_identity(incoming), downloaded_file_identities(account_state))

    def test_default_mail_pattern_supports_live_kde_extensions(self) -> None:
        pattern = re.compile(DEFAULT_MAIL_FILENAME_REGEX, re.IGNORECASE)
        filenames = [
            "A1015L_TSS_StopAC_BAYSAM_300726.doc.gpg",
            "A1015L_Db_bank_VOL15_20260730.xlsb.gpg",
            "A1015L_Archive_20260730.001.gpg",
            "A1015L_Document_Round2_30072026.docx.pgp",
        ]

        for filename in filenames:
            with self.subTest(filename=filename):
                match = pattern.search(filename)
                self.assertIsNotNone(match)
                self.assertEqual(filename, match.group(1))


class MailMatchingTests(unittest.TestCase):
    def test_mail_scan_uses_attachment_even_when_sender_name_changes(self) -> None:
        class ComCollection:
            def __init__(self, items: list[object]) -> None:
                self._items = items

            @property
            def Count(self) -> int:
                return len(self._items)

            def Item(self, index: int) -> object:
                return self._items[index - 1]

        class FakeItems(ComCollection):
            def Restrict(self, _clause: str) -> "FakeItems":
                return self

            def Sort(self, _field: str, _descending: bool) -> None:
                return None

        class FakeAttachment:
            FileName = "A10XXL_TSS_StopAC_BAYSAM_300726.doc.gpg"
            DisplayName = FileName

        class FakeMail:
            ReceivedTime = datetime.now()
            UnRead = True
            Subject = "ส่งงานรอบล่าสุด"
            Body = ""
            Sender = None
            SenderEmailAddress = "changed-sender@example.com"
            SenderName = "Changed Sender"
            Attachments = ComCollection([FakeAttachment()])

        class FakeFolder:
            Name = "data@tradeconnection.co.th"
            Items = FakeItems([FakeMail()])
            Folders = ComCollection([])

        class FakeNamespace:
            Folders = ComCollection([FakeFolder()])

        class FakeOutlook:
            def GetNamespace(self, _name: str) -> FakeNamespace:
                return FakeNamespace()

        class FakeWin32Client:
            @staticmethod
            def Dispatch(_name: str) -> FakeOutlook:
                return FakeOutlook()

        class FakePythonCom:
            @staticmethod
            def CoInitialize() -> None:
                return None

            @staticmethod
            def CoUninitialize() -> None:
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            with (
                patch.object(core, "win32_client", FakeWin32Client()),
                patch.object(core, "pythoncom", FakePythonCom()),
            ):
                lookup = downloader.scan_mail_filenames()

        expected_key = normalize_filename_for_match(FakeAttachment.FileName)
        self.assertIn(expected_key, lookup)
        self.assertIn("Attachment:", lookup[expected_key])
        self.assertIn("sender=changed-sender@example.com", lookup[expected_key])

    def test_attachment_filename_matches_different_kde_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_name = "A10XXL_Results_Review_Billcode_67097_29052026.docx"
            kde_name = "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.zip.gpg"
            allowed = {
                normalize_filename_for_match(mail_name): f"{mail_name} [Attachment: Inbox | sender=other@example.com]"
            }

            detail = downloader._mail_match_detail(normalize_filename_for_match(kde_name), allowed)

            self.assertIsNotNone(detail)
            self.assertGreaterEqual(int(detail["score"]), 94)
            self.assertEqual(4, detail["source_priority"])

    def test_pre_mail_does_not_match_post_kde_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_name = "A1015_Document_Round2_30072026.zip"
            kde_name = "260730_A1015L_A1015L_Document_Round2_30072026.zip.gpg"
            allowed = {
                normalize_filename_for_match(mail_name): f"{mail_name} [Attachment: Inbox]"
            }

            detail = downloader._mail_match_detail(normalize_filename_for_match(kde_name), allowed)

            self.assertIsNone(detail)

    def test_different_business_dates_are_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_name = "A10XXL_Results_Review_Billcode_67097_30052026.docx"
            allowed = {
                normalize_filename_for_match(mail_name): f"{mail_name} [Attachment: Inbox]"
            }
            rows = [
                (
                    0,
                    {
                        "filename": "260529_A1015L_A1015L_Results_Review_Billcode_67097_29052026.xlsx.gpg",
                        "file_time": "29/05/2026",
                        "size_text": "1 MB",
                    },
                ),
                (
                    1,
                    {
                        "filename": "260528_A1015L_A1015L_Results_Review_Billcode_67097_28052026.zip.gpg",
                        "file_time": "28/05/2026",
                        "size_text": "1 MB",
                    },
                ),
            ]

            selected, ambiguous = downloader._select_page_mail_matches(rows, allowed)

            self.assertEqual({}, ambiguous)
            self.assertEqual({}, selected)

    def test_same_date_equivalent_rows_select_only_first_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_name = "A10XXL_Results_Review_Billcode_67097_30052026.docx"
            allowed = {
                normalize_filename_for_match(mail_name): f"{mail_name} [Attachment: Inbox]"
            }
            rows = [
                (
                    0,
                    {
                        "filename": "260530_A1015L_A1015L_Results_Review_Billcode_67097_30052026.xlsx.gpg",
                        "file_time": "30/05/2026",
                        "size_text": "1 MB",
                    },
                ),
                (
                    1,
                    {
                        "filename": "260530_A1015L_A1015L_Results_Review_Billcode_67097_30052026.zip.gpg",
                        "file_time": "30/05/2026",
                        "size_text": "1 MB",
                    },
                ),
            ]

            selected, ambiguous = downloader._select_page_mail_matches(rows, allowed)

            self.assertEqual({}, ambiguous)
            self.assertEqual([0], list(selected))
            self.assertEqual(2, selected[0]["equivalent_count"])

    def test_equal_broad_matches_are_rejected_as_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_key = "review bay broken"
            allowed = {
                normalize_filename_for_match(mail_key): f"{mail_key} [Subject key: Inbox]"
            }
            rows = [
                (
                    0,
                    {
                        "filename": "260730_A1015L_A1015L_Review_BAY_Broken_Alpha_30072026.zip.gpg",
                        "file_time": "30/07/2026",
                        "size_text": "1 MB",
                    },
                ),
                (
                    1,
                    {
                        "filename": "260730_A1015L_A1015L_Review_BAY_Broken_Beta_30072026.zip.gpg",
                        "file_time": "30/07/2026",
                        "size_text": "1 MB",
                    },
                ),
            ]

            selected, ambiguous = downloader._select_page_mail_matches(rows, allowed)

            self.assertEqual({}, selected)
            self.assertEqual(2, ambiguous[normalize_filename_for_match(mail_key)])

    def test_split_archive_mail_selects_every_part_in_same_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_key = "A10XXL_VOL61_20260608"
            allowed = {
                normalize_filename_for_match(mail_key): f"{mail_key} [Subject key: Inbox]"
            }
            rows = [
                (
                    0,
                    {
                        "filename": "260608_A1015L_A1015L_VOL61_20260608.7z.001.gpg",
                        "file_time": "08/06/2026",
                        "size_text": "100 MB",
                    },
                ),
                (
                    1,
                    {
                        "filename": "260608_A1015L_A1015L_VOL61_20260608.7z.002.gpg",
                        "file_time": "08/06/2026",
                        "size_text": "100 MB",
                    },
                ),
                (
                    2,
                    {
                        "filename": "260608_A1015L_A1015L_VOL61_20260608.7z.003.gpg",
                        "file_time": "08/06/2026",
                        "size_text": "50 MB",
                    },
                ),
            ]

            selected, ambiguous = downloader._select_page_mail_matches(rows, allowed)

            self.assertEqual({}, ambiguous)
            self.assertEqual([0, 1, 2], sorted(selected))
            self.assertEqual(3, selected[0]["split_part_count"])
            self.assertEqual(
                selected[0]["multi_part_group"],
                selected[2]["multi_part_group"],
            )

    def test_specific_split_part_does_not_match_other_part(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = make_downloader(Path(temp_dir) / "state.json")
            mail_name = "A10XXL_VOL61_20260608.7z.001.gpg"
            allowed = {
                normalize_filename_for_match(mail_name): f"{mail_name} [Attachment: Inbox]"
            }
            different_part = "260608_A1015L_A1015L_VOL61_20260608.7z.002.gpg"

            detail = downloader._mail_match_detail(
                normalize_filename_for_match(different_part),
                allowed,
            )

            self.assertIsNone(detail)

    def test_destination_folder_detects_extension_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            existing = directory / "260623_A1015L_A1015L_Other_23062026.7z.gpg"
            existing.write_bytes(b"test")
            downloader = make_downloader(directory / "state.json")

            identities = downloader._existing_download_identities(directory)

            incoming = "260623_A1015L_A1015L_Other_23062026.zip.gpg"
            self.assertIn(canonical_file_identity(incoming), identities)


class DownloadIntegrityTests(unittest.TestCase):
    class FakeButtons:
        def __init__(self) -> None:
            self.last = self
            self.click_count = 0

        def count(self) -> int:
            return 1

        def click(self, **_kwargs) -> None:
            self.click_count += 1

    class FakeRow:
        def __init__(self, buttons: "DownloadIntegrityTests.FakeButtons") -> None:
            self.buttons = buttons

        def locator(self, selector: str) -> "DownloadIntegrityTests.FakeButtons":
            if selector != "button":
                raise AssertionError(f"unexpected selector: {selector}")
            return self.buttons

    class FakeRows:
        def __init__(self, row: "DownloadIntegrityTests.FakeRow") -> None:
            self.row = row

        def nth(self, _index: int) -> "DownloadIntegrityTests.FakeRow":
            return self.row

    class FakeDownload:
        def __init__(self, payload: bytes, failure_message: str | None = None) -> None:
            self.payload = payload
            self.failure_message = failure_message

        def failure(self) -> str | None:
            return self.failure_message

        def save_as(self, path: str) -> None:
            Path(path).write_bytes(self.payload)

    class FakeDownloadContext:
        def __init__(self, download: "DownloadIntegrityTests.FakeDownload") -> None:
            self.value = download

        def __enter__(self) -> "DownloadIntegrityTests.FakeDownloadContext":
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakePage:
        def __init__(self, download: "DownloadIntegrityTests.FakeDownload") -> None:
            self.buttons = DownloadIntegrityTests.FakeButtons()
            self.rows = DownloadIntegrityTests.FakeRows(
                DownloadIntegrityTests.FakeRow(self.buttons)
            )
            self.download = download

        def locator(self, selector: str) -> "DownloadIntegrityTests.FakeRows":
            if selector != "tbody tr":
                raise AssertionError(f"unexpected selector: {selector}")
            return self.rows

        def expect_download(self, **_kwargs) -> "DownloadIntegrityTests.FakeDownloadContext":
            return DownloadIntegrityTests.FakeDownloadContext(self.download)

    def test_download_is_written_atomically_after_non_empty_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloader = make_downloader(root / "state.json")
            target = root / "result.zip.gpg"
            page = self.FakePage(self.FakeDownload(b"encrypted-payload"))

            result = downloader._click_download_row(page, 0, target, 60000)

            self.assertEqual(target, result)
            self.assertEqual(b"encrypted-payload", target.read_bytes())
            self.assertFalse(target.with_name(target.name + ".part").exists())
            self.assertEqual(1, page.buttons.click_count)

    def test_empty_download_is_rejected_and_partial_file_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloader = make_downloader(root / "state.json")
            target = root / "empty.zip.gpg"
            page = self.FakePage(self.FakeDownload(b""))

            with self.assertRaisesRegex(core.KdeDownloadError, "downloaded file is empty"):
                downloader._click_download_row(page, 0, target, 60000)

            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()
