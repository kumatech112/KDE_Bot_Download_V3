from __future__ import annotations

import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from kde_bot import legacy_core as core
from kde_bot.evidence import MailEvidenceReader, correct_reference
from kde_bot.instructions import instruction_lookup
from kde_bot.mail_queue import MailQueue
from kde_bot.storage import Delivery
from kde_bot.workflow import StructuredDownloader, make_engine_settings
from test_mail_trigger import setup_queue
from test_outlook_scan import Collection, folder, mail, scan, setup_scanner


USER_REFERENCES = [
    ("A1015_TSS_ReviewAc_AYCAP_16102026", "A1015_TSS_ReviewAc_AYCAP_16102026.xlsx.gpg", "pre"),
    ("File Name: A10XX_Daily_Recovery_Performance_Oct26.zip.gpg", "A1015_Daily_Recovery_Performance_Oct26.zip.gpg", "pre"),
    ("A10xxL_SAM_CustomerRequest_JA2_xxxxxx", "A1015L_SAM_CustomerRequest_JA2_16102026.zip.gpg", "post"),
    ("A10xxL_Document_Round2_15102026", "A1015L_Document_Round2_15102026.zip.gpg", "post"),
    ("A1015L_TSS_Document_AYCAP_09102026", "A1015L_TSS_Document_AYCAP_09102026.xlsx.gpg", "post"),
    ("A10xxL_SelectACLitigation_LegalType_11_21_31_StopAC", "A1015L_SelectACLitigation_LegalType_11_21_31_StopAC_16102026.zip.gpg", "post"),
    ("A10xxL_TSS_HC_Report_App_ProWO_15102026.xlsx.gpg", "A1015L_TSS_HC_Report_App_ProWO_15102026.xlsx.gpg", "post"),
    ("A10XXL_Db_Bank_KTA_TSS_16102026.xlsx.pgp", "A1015L_Db_Bank_KTA_TSS_16102026.xlsx.pgp", "post"),
]


def engine_for(settings, history, reporter, tmp_path):
    return StructuredDownloader(make_engine_settings(settings, tmp_path / "engine.json"), reporter,
                                Delivery(history, reporter), settings, threading.Event())


@pytest.mark.parametrize("body,filename,side", USER_REFERENCES)
def test_user_body_examples_route_and_select_intended_file(tmp_path, body, filename, side):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    item = SimpleNamespace(EntryID="body-example", Body=body, HTMLBody="", Attachments=Collection([]))
    evidence = MailEvidenceReader().read(item, "Files available", datetime.now())
    incoming = {"entry_id": "body-example", "subject": "Files available", "received": "2026-10-16T10:00:00",
                **evidence, "lookup": evidence.get("preferred_lookup", evidence["lookup"])}
    queue.ingest([incoming], 0)
    batches = queue.claim_ready(120, set())
    account = "account-0" if side == "pre" else "account-1"
    assert set(batches) == {account}
    engine = engine_for(settings, history, reporter, tmp_path)
    engine.jobs = batches[account]
    rows = [(0, {"filename": filename, "file_time": "16/10/2026"}),
            (1, {"filename": filename.replace("A1015", "A9999"), "file_time": "16/10/2026"})]
    selected, ambiguous = engine._select_page_mail_matches(rows, engine.jobs[0]["lookup"])
    assert set(selected) == {0} and not ambiguous


@pytest.mark.parametrize("marker", ["1015", "Axxxx", "L10xx", ""])
def test_plain_body_instructions_work_with_company_only_generic_or_no_code(tmp_path, marker):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    item = SimpleNamespace(EntryID="body", Body=f"กรุณาใช้ไฟล์ Pre payment online 67097 {marker}",
                           HTMLBody="", Attachments=Collection([]))
    evidence = MailEvidenceReader().read(item, "New work", datetime.now())
    incoming = {"entry_id": "body", "subject": "New work", "received": "2026-10-16T10:00:00",
                **evidence, "lookup": evidence["preferred_lookup"]}
    queue.ingest([incoming], 0)
    engine = engine_for(settings, history, reporter, tmp_path)
    engine.jobs = queue.claim_ready(120, set())["account-0"]
    rows = [(index, {"filename": name}) for index, name in enumerate([
        "A1015_PAYMENT_ONLINE_67098_16102026.zip.gpg",
        "A1015_PAYMENT_ONLINE_67097_15102026.zip.gpg",
        "A1015L_PAYMENT_ONLINE_67097_16102026.zip.gpg",
        "A1015_PAYMENT_ONLINE_67097_16102026.zip.gpg",
    ])]
    selected, ambiguous = engine._select_page_mail_matches(rows, incoming["lookup"])
    assert set(selected) == {3} and not ambiguous


def test_real_scanner_body_instruction_overrides_unrelated_subject(tmp_path):
    settings, history, events, reporter, scanner = setup_scanner(tmp_path)
    incoming = mail("body-first")
    incoming.Subject = "A1015_OTHER_REPORT_16102026.zip.gpg"
    incoming.Body = "Please download Pre payment online 67097 for company 1015."
    assert scan(scanner, [folder("data@tradeconnection.co.th", [incoming])])
    result = scanner.mail_messages[0]
    assert result["side"] == "pre"
    assert all("[Email instruction]" in value for value in result["lookup"].values())
    assert not any("other_report" in key for key in result["lookup"])


def test_company_keyword_alone_or_unknown_side_never_selects_arbitrary_files(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    assert instruction_lookup("Keyword 1015") == {}
    evidence = MailEvidenceReader().read(SimpleNamespace(Body="Keyword 1015", Attachments=Collection([])), "Notice", None)
    assert evidence["relevant"] and not evidence["lookup"]
    queue.ingest([{"entry_id": "only-company", "subject": "Notice", "lookup": evidence["lookup"]},
                  {"entry_id": "unknown-side", "subject": "Notice", "lookup": instruction_lookup("Axxxx payment online 67097")}], 0)
    assert len(queue.jobs) == 2
    assert all(job["status"] == "review" for job in queue.jobs.values())
    assert queue.claim_ready(9999, set()) == {}


def test_body_partial_matches_reject_business_number_changes_and_ambiguity(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    lookup = instruction_lookup("Please download Pre Axxxx SelectACLitigation LegalType 11 21 31 StopAC")
    queue.ingest([{"entry_id": "types", "subject": "Pre", "received": "2026-10-16T10:00:00", "lookup": lookup}], 0)
    engine = engine_for(settings, history, reporter, tmp_path)
    engine.jobs = queue.claim_ready(120, set())["account-0"]
    rows = [(0, {"filename": "A1015_SelectACLitigation_LegalType_11_21_32_StopAC_16102026.zip.gpg"})]
    assert engine._select_page_mail_matches(rows, lookup) == ({}, {})
    names = ["A1015_SelectACLitigation_LegalType_11_21_31_StopAC_Alpha_16102026.zip.gpg",
             "A1015_SelectACLitigation_LegalType_11_21_31_StopAC_Beta_16102026.zip.gpg"]
    selected, ambiguous = engine._select_page_mail_matches([(index, {"filename": name}) for index, name in enumerate(names)], lookup)
    assert selected == {} and ambiguous


def test_current_body_ignores_quoted_instruction_and_excludes_foreign_company(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    lookup = instruction_lookup("Please use Pre payment online 67097\nFrom: Previous sender\nPlease download Post recovery report")
    assert len(lookup) == 1 and all("recovery" not in key for key in lookup)
    engine = engine_for(settings, history, reporter, tmp_path)
    foreign = instruction_lookup("Please download A9999 payment online 67097")
    assert all(engine._match_single_mail_key("a1015_payment_online_67097_16102026.zip.gpg", key, value) is None
               for key, value in foreign.items())
    assert correct_reference("A1O15_PAYMENT_16102026.zip.gpg").startswith("A1015_")


def test_complete_body_names_preserve_numeric_guards_and_extension_variants(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    engine = engine_for(settings, history, reporter, tmp_path)
    lookup = instruction_lookup("File Name: A10xxL_SelectACLitigation_LegalType_11_21_31_StopAC_16102026.xlsx.gpg")
    key, value = next(iter(lookup.items()))
    right = "a1015l_selectaclitigation_legaltype_11_21_31_stopac_16102026.zip.gpg"
    assert engine._match_single_mail_key(right, key, value)
    assert engine._match_single_mail_key(right.replace("_31_", "_32_"), key, value) is None
    assert engine._match_single_mail_key(right.replace("_16102026", "_15102026"), key, value) is None
    month_lookup = instruction_lookup("File Name: A10XX_Daily_Recovery_Performance_Oct26.zip.gpg")
    key, value = next(iter(month_lookup.items()))
    assert engine._match_single_mail_key("a1015_daily_recovery_performance_oct2026.zip.gpg", key, value)


def test_current_body_side_overrides_generic_subject_but_not_conflicting_file_code(tmp_path):
    settings, history, events, reporter, queue = setup_queue(tmp_path)
    reader = MailEvidenceReader()
    evidence = reader.read(SimpleNamespace(Body="Please download Post Axxxx payment online 67097", Attachments=Collection([])), "Pre notification", None)
    assert evidence["side"] == "post" and not evidence["review"]
    queue.ingest([{"entry_id": "body-side", "subject": "Pre notification", **evidence,
                   "lookup": evidence["preferred_lookup"]}], 0)
    # The preferred body side must not also produce a Pre request.
    assert set(queue.claim_ready(120, set())) == {"account-1"}
    conflict = reader.read(SimpleNamespace(Body="Please download Pre A10xxL payment online 67097", Attachments=Collection([])), "Notice", None)
    isolated = MailQueue(history, reporter, settings)
    isolated.ingest([{"entry_id": "conflicting-side", "subject": "Notice", **conflict,
                      "lookup": conflict["preferred_lookup"]}], 200)
    assert any(job["status"] == "review" for job in isolated.jobs.values())
