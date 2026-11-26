# ruff: noqa: F811 (the fixtures imported from test_team_briefing)
"""The coach (docs/pivot.md, docs/teams.md): the team's calendar beside its wellbeing in the
Monday briefing, the playbook change its calendar points to, and whether a change was followed.
Made-up teams only."""

import re
import uuid
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from test_team_briefing import LATE, NOW, TODAY, WEEK, engine, make_team, run  # noqa: F401

from app.db.daily import save_daily
from app.db.models import Team, TeamAction, TeamReport, User
from app.db.session import session_scope
from app.sync import calendar
from app.teams import coach, playbook

CAUSAL = re.compile(r"\b(because|due to|caused|cause[sd]?|led to|leads? to|result(ed)? of)\b", re.I)


def calendar_days(seed: int, busy: dict | None = None, span=None) -> pd.DataFrame:
    """Made-up daily counts for 90 days to the report week's end; `busy` adds to weekdays in
    `span` (default: the report week)."""
    rng = np.random.default_rng(seed)
    days = pd.date_range(TODAY - timedelta(days=90), TODAY - timedelta(days=1), freq="D")
    start, end = span or (WEEK.start, WEEK.end)
    rows = []
    for day in days:
        work = day.weekday() < 5
        row = {
            "meeting_minutes": float(rng.normal(120, 15)) if work else 0.0,
            "meetings": float(rng.integers(3, 6)) if work else 0.0,
            "after_hours_minutes": float(rng.normal(10, 3)) if work else 0.0,
            "back_to_back": float(rng.integers(0, 2)) if work else 0.0,
            "focus_minutes": float(rng.normal(180, 20)) if work else 0.0,
            "out_of_office": 0.0,
        }
        if busy and work and start <= day.date() <= end:
            for metric, extra in busy.items():
                row[metric] = max(0.0, row[metric] + extra)
        rows.append(row)
    return pd.DataFrame(rows, index=days).clip(lower=0)


def give_calendars(engine, count: int, busy: dict | None, busier: int | None = None, span=None):
    """Calendars for the first `count` members; the first `busier` of them (default all) busy."""
    with session_scope(engine) as db:
        people = db.scalars(
            select(User).where(User.email.like("member%")).order_by(User.email)
        ).all()
        for i, person in enumerate(people[:count]):
            extra = busy if busier is None or i < busier else None
            save_daily(db, person.id, calendar.SOURCE, calendar_days(i, extra, span))


BUSY = {"meeting_minutes": 90.0, "after_hours_minutes": 30.0, "back_to_back": 2.0}


def items_of(engine, team_id):
    with session_scope(engine) as db:
        report = db.scalar(select(TeamReport).where(TeamReport.team_id == uuid.UUID(team_id)))
        return report.body["briefing"]["items"], report.evidence


# What the briefing says


def test_a_busy_week_beside_a_wellbeing_change_is_said_as_the_same_week(engine):
    team_id = make_team(engine)  # time asleep fell three weeks ago and stayed low
    give_calendars(engine, 7, BUSY)
    run(engine, team_id, [])
    items, evidence = items_of(engine, team_id)
    [line] = [i for i in items if i["kind"] == "calendar"]
    assert line["text"].startswith("In the same week, the team's calendars were busier than usual.")
    assert not CAUSAL.search(line["text"])
    for key in line["evidence_ids"]:  # every figure in it is its evidence's, as written
        stats = evidence[key]["stats"]
        metric = evidence[key]["metrics"][0]
        assert coach.amount(metric, stats["median_change"]) in line["text"]
        way = coach.WATCHED[metric]
        moved = stats["members_up" if way == "up" else "members_down"]
        assert f"({moved} of {stats['members']}" in line["text"]


def test_a_busy_week_with_no_change_found_says_by_how_much_and_claims_nothing_more(engine):
    team_id = make_team(engine, effects=())
    give_calendars(engine, 7, BUSY)
    run(engine, team_id, [])
    items, evidence = items_of(engine, team_id)
    [line] = [i for i in items if i["kind"] == "calendar"]
    assert line["text"].startswith("Calendars were busier last week. For the typical person")
    assert "time in meetings up " in line["text"]
    assert "We detected no clear change in the available team readings." in line["text"]
    # The made-up members have no stress readings, and the sentence says so.
    assert line["text"].endswith("Too few readings to tell for physical stress signs.")
    # An absence of evidence, never a claim about the team's capacity (review, 2026-11-26).
    assert not re.search(r"capacity|handled|coped|managed|fine", line["text"], re.I)
    assert not CAUSAL.search(line["text"])
    assert not [i for i in items if i["kind"] == "proposal"]  # nothing to fix, nothing suggested


@pytest.mark.parametrize("count, busier", [(4, None), (7, 2)])
def test_too_few_calendars_or_too_few_busier_people_say_nothing(engine, count, busier):
    team_id = make_team(engine, effects=())
    give_calendars(engine, count, BUSY, busier)
    run(engine, team_id, [])
    items, _ = items_of(engine, team_id)
    assert not [i for i in items if i["kind"] == "calendar"]


def test_less_focus_time_alone_is_said(engine):
    team_id = make_team(engine, effects=())
    give_calendars(engine, 7, {"focus_minutes": -90.0})
    run(engine, team_id, [])
    items, _ = items_of(engine, team_id)
    [line] = [i for i in items if i["kind"] == "calendar"]
    assert "focus time down " in line["text"] and "time in meetings" not in line["text"]


def test_a_quiet_calendar_adds_nothing(engine):
    team_id = make_team(engine)
    give_calendars(engine, 7, None)
    run(engine, team_id, [])
    items, _ = items_of(engine, team_id)
    assert not [i for i in items if i["kind"] == "calendar"]


# Which change it suggests


STRESS = {
    "metric": "stress_score",
    "kind": "concern",
    "status": "lasting",
    "evidence_id": "e_stress",
}


@pytest.mark.parametrize(
    "moved, expected",
    [
        ({("back_to_back", "up")}, "meeting_breaks"),
        ({("meeting_minutes", "up")}, "meeting_free_day"),
        ({("focus_minutes", "down")}, "meeting_free_day"),
        (set(), "meeting_free_day"),  # no calendar signal: the first change meant for stress
    ],
)
def test_the_calendar_signal_picks_the_change_that_targets_it(engine, moved, expected):
    team_id = make_team(engine, size=5)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        action, _ = playbook.suggest(db, team, [STRESS], [], {}, TODAY, NOW, moved)
        assert action.play == expected


def test_a_busy_evening_week_with_lasting_shorter_sleep_suggests_the_evening_boundary(engine):
    team_id = make_team(engine)
    give_calendars(engine, 7, BUSY)
    run(engine, team_id, [])
    items, _ = items_of(engine, team_id)
    [proposal] = [i for i in items if i["kind"] == "proposal"]
    assert "evening boundary" in proposal["text"]
    assert "meetings after hours rose this week" in proposal["text"]


def test_every_change_has_a_trigger_of_its_own_and_its_evidence():
    seen = set()
    for play in playbook.PLAYS:
        assert play.source, play.id
        for trigger in play.triggers:
            assert trigger not in seen, trigger  # no two changes compete for one signal
            seen.add(trigger)
        if play.adherence:
            assert play.adherence[0] in {*coach.WATCHED, coach.MEETING_FREE_DAYS}


# Whether a change was followed


def ended_change(engine, team_id, play_id: str, span) -> str:
    with session_scope(engine) as db:
        action = TeamAction(
            team_id=uuid.UUID(team_id),
            kind="challenge",
            title=playbook.PLAY[play_id].title,
            body=playbook.PLAY[play_id].body,
            metric=playbook.PLAY[play_id].fits[0],
            starts_on=span[0],
            ends_on=span[1],
            status="approved",
            source="supervisor",
            play=play_id,
            proposed_at=NOW - timedelta(days=30),
            decided_at=NOW - timedelta(days=30),
        )
        db.add(action)
        db.flush()
        return str(action.id)


@pytest.mark.parametrize("drop, followed", [(-9.0, True), (0.0, False)])
def test_the_calendar_shows_whether_a_change_was_followed(engine, drop, followed):
    team_id = make_team(engine, effects=())
    span = (TODAY - timedelta(days=21), TODAY - timedelta(days=8))
    give_calendars(engine, 7, {"after_hours_minutes": drop} if drop else None, span=span)
    action_id = ended_change(engine, team_id, "evening_boundary", span)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        found = playbook.results_of(db, team, TODAY)[action_id]
        assert found["followed"]["followed"] is followed
        assert found["followed"]["text"] in found["text"]
        if not followed:
            assert "may not have been followed" in found["text"]
            # A change that was not done is not counted against it when choosing the next one.
            assert playbook.verdicts({action_id: found})[action_id] is None


def test_amounts_read_as_hours_and_minutes_or_whole_counts():
    assert coach.amount("meeting_minutes", 430) == "7 h 10 min"
    assert coach.amount("meeting_minutes", -45) == "45 min"
    assert coach.amount("meeting_minutes", 120) == "2 h"
    assert coach.amount("back_to_back", 6.4) == "6"


def test_over_many_made_up_teams_quiet_weeks_stay_quiet_and_busy_ones_are_said():
    """Not one lucky seed: 200 teams of 7 with quiet calendars, then the same teams busier."""
    from app.analysis.team_calendar import team_load

    quiet = busy = 0
    for team in range(200):
        calm = [calendar_days(1000 * team + i) for i in range(7)]
        heavy = [calendar_days(1000 * team + i, BUSY) for i in range(7)]
        quiet += coach.line(team_load(calm, WEEK), []) is not None
        busy += coach.line(team_load(heavy, WEEK), []) is not None
    assert quiet <= 4, quiet  # at most 2% of quiet weeks mentioned
    assert busy >= 196, busy  # at least 98% of clearly busy weeks mentioned


# What it says when readings are thin


def _busy_load():
    from app.analysis.team_calendar import team_load

    return team_load([calendar_days(i, BUSY) for i in range(7)], WEEK)


def test_with_no_readings_to_tell_it_says_so():
    sections = [
        {"metric": m, "label": label, "status": "not_enough_data"}
        for m, label in [("sleep_minutes", "Time asleep"), ("steps", "Steps")]
    ]
    text = coach.line(_busy_load(), sections)["text"]
    assert text.endswith("There were too few team readings to tell whether anything else changed.")
    assert "no clear change" not in text


def test_with_some_readings_too_thin_it_names_them():
    sections = [
        {"metric": "sleep_minutes", "label": "Time asleep", "status": "steady"},
        {"metric": "hrv_ms", "label": "HRV", "status": "not_enough_data"},
        {"metric": "stress_score", "label": "Physical stress signs", "status": "not_enough_data"},
    ]
    text = coach.line(_busy_load(), sections)["text"]
    assert "We detected no clear change in the available team readings." in text
    assert text.endswith("Too few readings to tell for HRV and physical stress signs.")


# Was a meeting-free day kept? Read from the days, not from total meeting time


def _shifted(seed: int, span, how: str) -> pd.DataFrame:
    frame = calendar_days(seed)
    inside = (frame.index.date >= span[0]) & (frame.index.date <= span[1])
    if how == "moved":  # Monday's meetings moved to Tuesday: same total, Mondays free
        for day in frame.index[inside & (frame.index.weekday == 0)]:
            tuesday = day + pd.Timedelta(days=1)
            if tuesday in frame.index:
                frame.loc[tuesday, "meeting_minutes"] += frame.loc[day, "meeting_minutes"]
            frame.loc[day, ["meeting_minutes", "meetings"]] = 0.0
    elif how == "shorter":  # every meeting shorter, no day free
        frame.loc[inside & (frame.index.weekday < 5), "meeting_minutes"] *= 0.4
    elif how == "already":  # Wednesdays free before the change and during it alike
        frame.loc[frame.index.weekday == 2, ["meeting_minutes", "meetings"]] = 0.0
    return frame


def _meeting_free_trial(engine, how: str) -> tuple[dict, str | None]:
    """A made-up team's ended meeting-free-day change: its result and its verdict for ranking."""
    team_id = make_team(engine, effects=())
    span = (TODAY - timedelta(days=21), TODAY - timedelta(days=8))
    with session_scope(engine) as db:
        people = db.scalars(
            select(User).where(User.email.like("member%")).order_by(User.email)
        ).all()
        for i, person in enumerate(people):
            save_daily(db, person.id, calendar.SOURCE, _shifted(i, span, how))
    action_id = ended_change(engine, team_id, "meeting_free_day", span)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        results = playbook.results_of(db, team, TODAY)
        return results[action_id], playbook.verdicts(results)[action_id]


@pytest.mark.parametrize("how, kept", [("moved", True), ("shorter", False)])
def test_a_meeting_free_day_counts_free_days_not_total_time(engine, how, kept):
    result, _ = _meeting_free_trial(engine, how)
    found = result["followed"]
    assert found["followed"] is kept, found["text"]
    assert found["text"].startswith("Meeting-free workdays during it:")


def test_a_meeting_free_day_the_team_already_kept_counts_as_followed(engine):
    # Review, 2026-11-26: one free Wednesday a week before and during is the goal met, not a
    # change ignored; scoring it unfollowed would drop its result from ranking as never tried.
    result, verdict = _meeting_free_trial(engine, "already")
    found = result["followed"]
    assert found["followed"] is True and found["increased"] is False, found["text"]
    assert found["text"].endswith("already had one, so the calendar did not change.")
    assert "may not have been followed" not in found["text"]
    assert verdict == result["verdict"]  # its wellbeing result counts when ranking plays


def test_a_day_out_of_office_is_not_a_meeting_free_day():
    frame = calendar_days(0)
    week = WEEK
    days = frame.loc[pd.Timestamp(week.start) : pd.Timestamp(week.end)].index
    monday = [d for d in days if d.weekday() == 0][0]
    frame.loc[monday, ["meeting_minutes", "meetings"]] = 0.0
    frame.loc[monday, "out_of_office"] = 1.0
    free, read = coach._meeting_free_days(frame, week)
    assert free == 0.0 and read == 4
