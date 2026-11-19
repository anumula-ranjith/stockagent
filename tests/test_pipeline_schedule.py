from datetime import date, datetime
from zoneinfo import ZoneInfo

from stock_agents.jobs.pipelines import due_slots, latest_session

TZ = ZoneInfo("Asia/Kolkata")


def test_morning_uses_completed_session():
    assert latest_session(datetime(2026, 11, 19, 7, tzinfo=TZ)) == date(2026, 11, 18)


def test_evening_and_weekend_resolve_sessions():
    assert latest_session(datetime(2026, 11, 19, 18, 30, tzinfo=TZ)) == date(2026, 11, 19)
    assert latest_session(datetime(2026, 11, 22, 7, tzinfo=TZ)) == date(2026, 11, 20)


def test_due_slots_paused_and_future_excluded():
    schedules = [dict(id="morning",hour=7,minute=0,enabled=True),
                 dict(id="evening",hour=18,minute=30,enabled=False)]
    slots = due_slots(datetime(2026,11,19,7,1,tzinfo=TZ), schedules)
    assert len(slots) == 1
    assert slots[0][0] == "morning:2026-11-19"
