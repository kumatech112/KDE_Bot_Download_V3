"""Work history must retain real transitions and remain stable on CSV reload."""

from __future__ import annotations

from collections import OrderedDict

from kde_bot.activity import ActivityHistory, read_activity, update_latest
from kde_bot.storage import History, Reporter


def make_reporter(tmp_path):
    history = History(tmp_path)
    events = []
    return history, events, Reporter(history, events.append)


def test_error_retry_success_remain_in_history_and_replay_without_duplicates(tmp_path):
    history, events, reporter = make_reporter(tmp_path)
    reporter.emit(3, "running", "เข้าสู่ระบบ", "Pre")
    reporter.emit(3, "error", "เข้าสู่ระบบไม่ได้", "Pre", persist=True)
    reporter.emit(3, "running", "เข้าสู่ระบบ", "Pre")
    reporter.emit(3, "stage_complete", "เข้าสู่ระบบสำเร็จ", "Pre")
    reporter.emit(6, "running", "ดาวน์โหลด", "Pre", "=test.zip.gpg")
    reporter.emit(7, "complete", "ครบสองปลายทาง", "Pre", "=test.zip.gpg", persist=True)
    loaded, latest = read_activity(tmp_path)
    assert [event["status"] for event in loaded] == ["running", "error", "running", "stage_complete", "running", "complete"]
    assert [event["status"] for event in latest] == ["complete"]
    assert loaded[-1]["filename"] == "=test.zip.gpg"
    timeline = ActivityHistory()
    for event in events:
        timeline.add(event)
    timeline.merge(loaded)
    timeline.merge(loaded)
    assert len(timeline.entries) == 6
    assert history.data["outcomes"]["stage:Pre:3"]["signature"][1] == "stage_complete"


def test_idle_summary_and_unchanged_error_do_not_flood_monthly_csv(tmp_path):
    history, events, reporter = make_reporter(tmp_path)
    for _ in range(20):
        reporter.emit(2, "summary", "ไม่มีเมลใหม่")
        reporter.emit(3, "error", "บัญชีเข้าไม่ได้", "Pre", persist=True)
    loaded, latest = read_activity(tmp_path)
    assert len(loaded) == 2
    assert len(latest) == 1
    assert len(list(tmp_path.glob("KDE_Log_*.csv"))) == 1


def test_repeat_failure_after_fresh_login_is_a_new_activity(tmp_path):
    history, events, reporter = make_reporter(tmp_path)
    for _ in range(2):
        reporter.emit(3, "running", "เข้าสู่ระบบ", "Pre")
        reporter.emit(3, "error", "บัญชีเข้าไม่ได้", "Pre", persist=True)
    loaded, latest = read_activity(tmp_path)
    assert [event["status"] for event in loaded] == ["running", "error", "running", "error"]


def test_history_bounds_recent_entries_and_sorts_merged_accounts():
    timeline = ActivityHistory(limit=2)
    older = {"time": "2026-10-10T10:00:00+07:00", "step": 3, "status": "error", "account": "Pre"}
    middle = dict(older, time="2026-10-10T10:00:01+07:00", account="Post")
    newer = dict(older, time="2026-10-10T10:00:02+07:00", status="stage_complete")
    timeline.add(newer)
    timeline.merge([middle, older, newer])
    assert [event["time"] for event in timeline.entries.values()] == [middle["time"], newer["time"]]


def test_progress_history_preserves_redaction_and_does_not_replace_outcomes(tmp_path):
    history, events, reporter = make_reporter(tmp_path)
    reporter.secrets = ["PRIVATE-PASSWORD"]
    failed = reporter.emit(3, "error", "บัญชีเข้าไม่ได้", "Pre", persist=True)
    reporter.emit(3, "running", "ลองใหม่ PRIVATE-PASSWORD", "Pre")
    loaded, latest = read_activity(tmp_path)
    assert "PRIVATE-PASSWORD" not in next(tmp_path.glob("KDE_Log_*.csv")).read_text(encoding="utf-8-sig")
    assert loaded[-1]["reason"] == "ลองใหม่ [REDACTED]"
    assert latest[0]["status"] == "error"
    assert history.data["outcomes"][failed["key"]]["signature"][1] == "error"


def test_pending_file_remains_in_latest_errors_during_retry():
    rows = OrderedDict()
    event = {"key": "file", "filename": "test.gpg", "status": "copy_pending"}
    update_latest(rows, event)
    update_latest(rows, dict(event, status="running"))
    assert rows["file"]["status"] == "copy_pending"
    update_latest(rows, dict(event, status="complete"))
    assert rows["file"]["status"] == "complete"
