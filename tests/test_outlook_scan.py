"""Reproduce the Notes-folder Restrict error without accessing a real mailbox."""

from __future__ import annotations

import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kde_bot import legacy_core as core
from kde_bot.settings import default_settings
from kde_bot.storage import Delivery, History, Reporter
from kde_bot.workflow import StructuredDownloader, make_engine_settings, run_mail_monitor


class Collection:
    def __init__(self, values=(), reject_filter=False):
        self.values = list(values)
        self.reject_filter = reject_filter
        self.restrict_calls = []

    @property
    def Count(self):
        return len(self.values)

    def Item(self, index):
        return self.values[index - 1]

    def Restrict(self, clause):
        self.restrict_calls.append(clause)
        if self.reject_filter:
            raise RuntimeError("Microsoft Outlook: Condition is not valid; filter failed")
        return Collection([item for item in self.values if getattr(item, "UnRead", False)])

    def Sort(self, *_args):
        pass


def mail(entry_id="mail-1", unread=True, item_class=43):
    return SimpleNamespace(EntryID=entry_id, Class=item_class, ReceivedTime=datetime.now(),
                           UnRead=unread, Subject="A1015_TEST_10102026.zip.gpg", Body="",
                           Attachments=Collection([]))


def folder(name, items=(), item_type=0, children=(), reject_filter=False):
    return SimpleNamespace(Name=name, DefaultItemType=item_type, StoreID="offline-store",
                           Items=Collection(items, reject_filter), Folders=Collection(children))


def setup_scanner(tmp_path):
    settings = default_settings()
    history = History(tmp_path)
    events = []
    reporter = Reporter(history, events.append)
    scanner = StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"),
                                   reporter, Delivery(history, reporter), settings, threading.Event())
    return settings, history, events, reporter, scanner


def scan(scanner, roots):
    namespace = SimpleNamespace(Folders=Collection(roots))
    outlook = SimpleNamespace(GetNamespace=lambda _name: namespace)
    with patch.object(core, "win32_client", SimpleNamespace(Dispatch=lambda _name: outlook)), \
            patch.object(core, "pythoncom", SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)):
        return scanner.scan_mail_filenames()


@pytest.mark.parametrize("item_type", [1, 2, 3, 4, 5, 6, 7])
def test_non_mail_folders_are_not_filtered_but_mail_children_are_scanned(tmp_path, item_type):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    real_mail = mail()
    child = folder("KDE Mail", [real_mail])
    non_mail = folder("บันทึกย่อ", [mail("note", item_class=44)], item_type, [child], reject_filter=True)
    root = folder("data@tradeconnection.co.th", children=[non_mail])
    lookup = scan(scanner, [root])
    assert lookup and [message["entry_id"] for message in scanner.mail_messages] == ["mail-1"]
    assert non_mail.Items.restrict_calls == []
    assert child.Items.restrict_calls
    assert scanner.mail_failures == []
    assert real_mail.UnRead is True


def test_rejected_mail_filter_falls_back_without_false_error_or_read_flag_changes(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    values = [mail("unread"), mail("read", unread=False), mail("note", item_class=44)]
    inbox = folder("data@tradeconnection.co.th", values, reject_filter=True)
    for _ in range(3):
        assert scan(scanner, [inbox])
        assert [message["entry_id"] for message in scanner.mail_messages] == ["unread"]
    assert scanner.mail_failures == []
    assert [item.UnRead for item in values] == [True, False, True]
    assert len(events) == 1 and events[0]["status"] == "notice"
    assert "ตรวจสถานะเมลทีละรายการ" in events[0]["reason"]


def test_unknown_folder_type_still_scans_mail_and_skips_non_mail_items(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    inbox = folder("data@tradeconnection.co.th", [mail(), mail("note", item_class=44)], reject_filter=True)
    del inbox.DefaultItemType
    assert scan(scanner, [inbox])
    assert [message["entry_id"] for message in scanner.mail_messages] == ["mail-1"]
    assert scanner.mail_failures == []


def test_real_mail_folder_access_failure_remains_an_error(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)

    class UnavailableItems(Collection):
        def Restrict(self, _clause):
            raise PermissionError("Cannot access mailbox")

        @property
        def Count(self):
            raise PermissionError("Cannot access mailbox")

    inbox = folder("data@tradeconnection.co.th")
    inbox.Items = UnavailableItems()
    assert scan(scanner, [inbox]) == {}
    assert len(scanner.mail_failures) == 1
    assert "อ่านโฟลเดอร์อีเมลไม่ได้" in scanner.mail_failures[0]


def test_fallback_respects_configured_message_limit(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    scanner.settings.mail_watch.max_messages_per_folder = 2
    inbox = folder("data@tradeconnection.co.th", [mail(str(index)) for index in range(5)], reject_filter=True)
    assert scan(scanner, [inbox])
    assert len(scanner.mail_messages) == 2


def test_successful_monitor_scan_clears_old_outlook_error_without_portal_calls(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    reporter.emit(2, "error", "unread restrict failed Notes", persist=True)

    def no_mail(engine):
        engine.mail_messages = []
        return {}

    with patch.object(StructuredDownloader, "scan_mail_filenames", no_mail), \
            patch("kde_bot.workflow.run_account_batch") as portal:
        run_mail_monitor(settings, threading.Event(), reporter, history, tmp_path, watch=False)
        portal.assert_not_called()
    assert history.data["outcomes"]["stage::2"]["signature"][1] == "stage_complete"
    assert any(event["status"] == "stage_complete" for event in events)
