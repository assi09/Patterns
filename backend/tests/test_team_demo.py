"""The made-up demo team (app/teams/demo.py): calendar days as a sync stores them, busier in the
week the report covers, and never on weekends."""

from datetime import date, timedelta

from app.teams.demo import MEETING_RISE, _calendar_days

TODAY = date(2026, 11, 26)
BUSY = date(2026, 11, 16)


def test_calendar_days_are_counts_up_to_yesterday_and_empty_at_weekends():
    days = _calendar_days(TODAY - timedelta(days=120), TODAY, BUSY, seed=0)
    assert days.index[-1].date() == TODAY - timedelta(days=1)
    assert set(days.columns) == {
        "meeting_minutes",
        "meetings",
        "after_hours_minutes",
        "back_to_back",
        "focus_minutes",
        "out_of_office",
    }
    weekend = days[days.index.weekday >= 5]
    assert (weekend["meetings"] == 0).all() and (weekend["meeting_minutes"] == 0).all()
    assert (days >= 0).all().all()


def test_the_report_week_is_busier_for_most_members():
    busier = 0
    for seed in range(20):
        days = _calendar_days(TODAY - timedelta(days=120), TODAY, BUSY, seed)
        week = days.loc[str(BUSY) : str(BUSY + timedelta(days=6)), "meetings"].sum()
        usual = days.loc[: str(BUSY - timedelta(days=1)), "meetings"].sum() / (
            (BUSY - (TODAY - timedelta(days=120))).days / 7
        )
        busier += week > usual
    assert MEETING_RISE > 1 and busier >= 17
