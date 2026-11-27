# ruff: noqa: F811 (the fixtures imported from test_coach)
"""A team's past cases for an assistant (app.teams.history, docs/change-memory.md): events with or
without a change, every decision state, explicit links apart from date overlaps, the evidence that
exists for the dates, and the day-specific gap said rather than filled."""

import base64
import json
import uuid
from datetime import timedelta

import pytest
from test_coach import NOW, TODAY, WEEK, engine, make_team  # noqa: F401
from test_mcp import build as build_mcp
from test_mcp import call as call_mcp
from test_supervisor_view import boss, reported, team_of

from app.db.models import TeamAction, TeamNote, User
from app.db.session import session_scope
from app.harness import tools
from app.harness.tools import HarnessError, TeamChangeIn
from app.teams import actions as team_actions
from app.teams import history

FRIDAY = WEEK.start + timedelta(days=4)
SECRET = "Dana's migraine week"  # free text that must never leave through MCP


def event(db, team, start, end=None, category="deadline", text=SECRET, made=NOW):
    note = TeamNote(
        team_id=team.id,
        text=text,
        starts_on=start,
        ends_on=end,
        category=category,
        created_at=made - timedelta(days=30),
    )
    db.add(note)
    db.flush()
    return note


def change(
    db,
    team,
    start,
    days=7,
    status="approved",
    note=None,
    tried=None,
    play="step_goal",
    metric=None,
):
    action = TeamAction(
        team_id=team.id,
        kind="challenge",
        title=SECRET if play == "custom" else "Step goal",
        body=SECRET,
        metric=metric,
        comparison="before_the_change" if metric else None,
        starts_on=start,
        ends_on=start + timedelta(days=days - 1),
        status=status,
        source="assistant",
        play=play,
        proposed_at=NOW - timedelta(days=40),
        decided_at=NOW - timedelta(days=39) if status != "proposed" else None,
        event_id=note.id if note else None,
    )
    db.add(action)
    db.flush()
    if tried:
        team_actions.mark_implementation(db, action, tried == "tried", NOW - timedelta(days=20))
    return action


def by_id(listing: dict) -> dict:
    return {c["case_id"]: c for c in listing["cases"]}


def test_a_deadline_with_only_a_weekly_report_says_there_is_no_day_figure(engine):
    team_id = reported(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        note = event(db, team, FRIDAY)
        found = history.one_case(db, team, f"event:{note.id}", TODAY, day=FRIDAY)
    assert found["dates"] == {"start": str(FRIDAY), "end": str(FRIDAY)}
    assert found["day"]["day_specific"] == history.NO_DAY
    [week] = found["day"]["weekly_context"]
    assert week["week"] == {"start": str(WEEK.start), "end": str(WEEK.end)}
    assert "not for a day" in week["relation"]
    [lines] = found["evidence"]
    assert lines["week"] == week["week"] and lines["minimum"] == 5
    assert "Sleep is dated by the local day it ended" in found["day"]["date_convention"]


def test_three_deadlines_keep_their_distinct_states(engine):
    team_id = reported(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        alone = event(db, team, TODAY - timedelta(days=50))
        refused = event(db, team, TODAY - timedelta(days=35))
        tried = event(db, team, TODAY - timedelta(days=10))
        change(db, team, TODAY - timedelta(days=38), status="declined", note=refused)
        done = change(db, team, TODAY - timedelta(days=14), note=tried, tried="tried")
        listing = tools.team_history(db, boss(db), team_id, TODAY, category="deadline")
    cases = by_id(listing)
    events = [c for c in listing["cases"] if c["kind"] == "event"]
    assert len(events) == 3 and all(e["category"] == "deadline" for e in events)
    assert cases[f"event:{alone.id}"]["linked_changes"] == []  # nothing was done: still found
    changes = [c for c in listing["cases"] if c["kind"] == "change"]
    assert sorted(c["decision"]["state"] for c in changes) == ["approved", "declined"]
    assert cases[f"change:{done.id}"]["implementation"] == "reported tried by the supervisor"
    declined = next(c for c in changes if c["decision"]["state"] == "declined")
    assert declined["implementation"] is None and declined["outcome"] is None


def test_overlapping_events_are_nearby_and_an_explicit_link_stays_a_link(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        deadline = event(db, team, FRIDAY)
        offsite = event(db, team, FRIDAY - timedelta(days=1), FRIDAY + timedelta(days=1), "travel")
        action = change(db, team, FRIDAY - timedelta(days=3), days=5, note=deadline)
        cases = {
            c: history.one_case(db, team, c, TODAY)
            for c in (f"event:{deadline.id}", f"event:{offsite.id}", f"change:{action.id}")
        }
    d, o, a = cases.values()
    assert d["linked_changes"] == [a["case_id"]] and a["linked"]["event"] == d["case_id"]
    assert a["case_id"] not in d["nearby"]["cases"]  # linked, so not repeated as nearby
    assert o["case_id"] in d["nearby"]["cases"] and d["case_id"] in o["nearby"]["cases"]
    assert a["case_id"] in o["nearby"]["cases"] and o["linked_changes"] == []
    assert "not an explanation" in o["nearby"]["meaning"]
    for found in cases.values():
        assert "cause" not in str(found).replace("not an explanation", "")


def test_a_first_night_tracked_apart_from_a_three_day_offsite(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        first = TODAY + timedelta(days=7)
        offsite = event(db, team, first, first + timedelta(days=2), "travel")
        tracking = {"metric": "sleep_minutes", "observe_from": first, "observe_to": first}
        made = tools.record_team_change(
            db,
            boss(db),
            team_id,
            TeamChangeIn(
                request_id="offsite-night-1",
                play="evening_boundary",
                starts_on=first - timedelta(days=1),
                ends_on=first,
                event_id=str(offsite.id),
                tracking=tracking,
            ),
            None,
            NOW,
            TODAY,
        )
        later = TODAY + timedelta(days=20)
        found = history.one_case(db, team, f"change:{made['change_id']}", later)
        place = history.one_case(db, team, f"event:{offsite.id}", later)
    observed = found["observation"]
    assert observed["observe"] == {"start": str(first), "end": str(first)}
    assert place["dates"]["end"] == str(first + timedelta(days=2))  # the event keeps its 3 days
    assert observed["state"] == "unavailable" and observed["reason"] == history.NO_DAY
    assert "night ending" in observed["date_convention"]
    assert found["decision"]["state"] == "pending" and found["implementation"] is None


def test_as_of_leaves_out_what_happened_later(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        made = tools.record_team_change(
            db,
            boss(db),
            team_id,
            TeamChangeIn(
                request_id="later-0001",
                play="step_goal",
                starts_on=TODAY,
                ends_on=TODAY + timedelta(days=6),
            ),
            None,
            NOW,
            TODAY,
        )
        action = db.get(TeamAction, uuid.UUID(made["change_id"]))
        team_actions.decide(db, team, action, True, NOW + timedelta(days=2))
        team_actions.mark_implementation(db, action, True, NOW + timedelta(days=5))
        later = TODAY + timedelta(days=9)
        then = tools.team_history(db, boss(db), team_id, later, as_of=str(TODAY))
        now = tools.team_history(db, boss(db), team_id, later)
    [past] = then["cases"]
    [today] = now["cases"]
    assert past["decision"] == {"state": "pending", "on": None} and past["implementation"] is None
    assert then["as_of_meaning"].startswith("what was recorded by that date")
    assert today["decision"]["state"] == "approved"
    assert today["implementation"] == "reported tried by the supervisor"


def test_no_free_text_leaves_through_history(engine):
    team_id = reported(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        note = event(db, team, FRIDAY)
        own = change(db, team, WEEK.start, play="custom", note=note)
        listing = tools.team_history(db, boss(db), team_id, TODAY)
        one = tools.team_case(db, boss(db), team_id, TODAY, f"change:{own.id}", str(FRIDAY))
    assert SECRET not in str(listing) and SECRET not in str(one)
    assert one["title"] == "Custom team change" and one["play"] is None
    assert one["playbook_entry"] == "none: the supervisor's own words"
    assert "not shared through MCP" in one["custom_note"]


def test_filters_return_only_matches_and_never_another_teams(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        event(db, team, FRIDAY, category="launch")
        change(db, team, WEEK.start, play="meeting_breaks")
        retired = change(db, team, WEEK.start, play="walking_meetings")
        assert tools.team_history(db, boss(db), team_id, TODAY, category="holiday")["cases"] == []
        breaks = tools.team_history(db, boss(db), team_id, TODAY, play="meeting_breaks")
        assert [c["play"] for c in breaks["cases"]] == ["meeting_breaks"]
        own = tools.team_history(db, boss(db), team_id, TODAY, play="custom")
        assert [c["case_id"] for c in own["cases"]] == [f"change:{retired.id}"]
        assert own["cases"][0]["title"] == "Custom team change"
        old = tools.team_history(db, boss(db), team_id, TODAY, end=str(TODAY - timedelta(days=60)))
        assert old["cases"] == []
        for bad in ({"category": "party"}, {"play": "nap_pods"}, {"metric": "mood"}):
            with pytest.raises(HarnessError):
                tools.team_history(db, boss(db), team_id, TODAY, **bad)


def test_another_supervisor_and_a_guessed_case_get_nothing(engine):
    team_id = make_team(engine)
    server = build_mcp(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        note = event(db, team, FRIDAY)
        other = User(email="other@example.com", status="approved", role="supervisor")
        db.add(other)
        db.flush()
        other_id, boss_id, case_id = other.id, boss(db).id, f"event:{note.id}"
    error, text = call_mcp(server, other_id, "team_history", team_id=team_id)
    assert error and "No such team" in text
    error, text = call_mcp(server, other_id, "team_case", team_id=team_id, case_id=case_id)
    assert error and "No such team" in text
    error, text = call_mcp(server, boss_id, "team_case", team_id=team_id, case_id="event:abc")
    assert error and "No such case" in text
    error, found = call_mcp(server, boss_id, "team_case", team_id=team_id, case_id=case_id)
    assert not error and found["case_id"] == case_id


def test_a_withheld_week_gives_no_figure_for_its_withheld_metrics(engine):
    team_id = reported(engine, size=5)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        note = event(db, team, FRIDAY)
        found = history.one_case(db, team, f"event:{note.id}", TODAY)
    [week] = found["evidence"]
    for line in week["withheld_metrics"]:
        assert line["contributors"] < 5 and "change" not in line


def test_a_tracked_legacy_change_shows_its_stored_outcome_and_filters_by_metric(engine):
    from app.teams import reports

    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        action = TeamAction(
            team_id=team.id,
            kind="challenge",
            title="No meetings after 5 pm",
            body="x",
            metric="sleep_minutes",
            starts_on=WEEK.start - timedelta(days=14),
            ends_on=WEEK.end,
            status="approved",
            source="supervisor",
            play="no_late_meetings",
            proposed_at=NOW - timedelta(days=20),
            decided_at=NOW - timedelta(days=20),
        )
        db.add(action)
        db.flush()
        reports.build_report(db, team, WEEK, NOW)
        listing = tools.team_history(db, boss(db), team_id, TODAY, metric="sleep_minutes")
        found = history.one_case(db, team, f"change:{action.id}", TODAY)
    [listed] = listing["cases"]
    assert listed["tracked"] and listed["outcome"] == found["outcome"]["label"]
    assert found["outcome"]["reference"]["label"] == "the 28 days before the change started"
    assert found["implementation"] == "not reported: whether the team tried it is unknown"
    assert found["outcome"]["evidence_id"] and found["outcome"]["report_id"]


def test_a_late_first_report_appears_only_from_the_day_it_was_made(engine):
    """A week's first report made ten days late. Asked as of the cutoff, through team_case,
    team_history and team_overview: the decision state known then, no report, no figures, no
    outcome, and nothing decided or marked later. Today: the report, dated by when it was made,
    with its outcome."""
    from app.teams import reports

    team_id = make_team(engine)
    late = NOW + timedelta(days=10)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        action = change(db, team, WEEK.start - timedelta(days=14), days=21, metric="sleep_minutes")
        pending = change(db, team, WEEK.start, days=7, status="proposed", play="meeting_breaks")
        team_actions.decide(db, team, pending, True, late - timedelta(days=2))  # after the cutoff
        team_actions.mark_implementation(db, action, True, late - timedelta(days=1))
        reports.build_report(db, team, WEEK, late)
        case_id = f"change:{action.id}"
        then = history.one_case(db, team, case_id, late.date(), as_of=TODAY)
        now = history.one_case(db, team, case_id, late.date())
        listed_then = tools.team_history(db, boss(db), team_id, late.date(), as_of=str(TODAY))
        asked = {"week": str(WEEK.start)}
        week_then = tools.team_overview(
            db, boss(db), team_id, late.date(), **asked, as_of=str(TODAY)
        )
        latest_then = tools.team_overview(db, boss(db), team_id, late.date(), as_of=str(TODAY))
        week_now = tools.team_overview(db, boss(db), team_id, late.date(), **asked)
        latest_now = tools.team_overview(db, boss(db), team_id, late.date())
        report_id = str(reports.build_report(db, team, WEEK, late).id)
    not_yet = f"No outcome was recorded by {TODAY}"
    # Then, through every tool.
    assert then["outcome"] is None and then["evidence"] == []
    assert then["outcome_note"].startswith(not_yet)
    assert then["implementation"] == "not reported: whether the team tried it is unknown"
    assert by_id(listed_then)[case_id]["outcome_note"].startswith(not_yet)
    for answer in (week_then, latest_then):
        assert answer["as_of"] == str(TODAY)
        assert answer["report"]["state"] == "no_report_by_then"
        assert answer["report"]["note"] == "No report was available by that date."
        assert answer["priorities"] == [] and "this_week_vs_previous_four" not in answer
        assert report_id not in str(answer) and str(late.date()) not in str(answer)
        assert "readings" not in answer and "open_alerts" not in answer
        ended, waiting = sorted(answer["follow_up"], key=lambda f: f["state"])
        assert ended["state"] == "ended" and ended["result"]["outcome"] is None
        assert ended["result"]["note"].startswith(not_yet)
        assert ended["tried"] == "not reported: whether the team tried it is unknown"
        assert waiting["state"] == "proposed"  # approved only after the cutoff
    # Today.
    assert now["outcome"]["report_id"] == report_id and "outcome_note" not in now
    for answer in (week_now, latest_now):
        assert answer["report"]["report_id"] == report_id
        assert answer["report"]["made_on"] == str(late.date())
        assert answer["report"]["week"] == {"start": str(WEEK.start), "end": str(WEEK.end)}
        assert answer["as_of"] == str(late.date())  # never dated before the report existed
        [current] = [f for f in answer["follow_up"] if f.get("result")]
        assert current["result"]["report_id"] == report_id
        assert current["tried"] == "reported tried by the supervisor"


def test_a_report_is_never_replaced_so_an_earlier_date_reads_the_version_it_had(engine):
    """Making a week's report again returns the one already made, with its own date and figures:
    an answer dated between the two reads that version, and one before it reads none."""
    from app.teams import reports

    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        first = reports.build_report(db, team, WEEK, NOW)
        made = (str(first.id), first.created_at, dict(first.evidence))
        give_more = change(db, team, WEEK.start, metric="steps")  # something new to report on
        assert give_more
        again = reports.build_report(db, team, WEEK, NOW + timedelta(days=6))
        assert (str(again.id), again.created_at, dict(again.evidence)) == made
        between = tools.team_overview(
            db, boss(db), team_id, TODAY + timedelta(days=6), as_of=str(TODAY + timedelta(days=3))
        )
        before = tools.team_overview(
            db, boss(db), team_id, TODAY + timedelta(days=6), as_of=str(TODAY - timedelta(days=1))
        )
    assert between["report"]["report_id"] == made[0]
    assert between["report"]["made_on"] == str(NOW.date())
    assert before["report"]["note"] == "No report was available by that date."


def test_every_filter_given_must_hold(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        first, second = event(db, team, FRIDAY), event(db, team, FRIDAY - timedelta(days=7))
        launch = event(db, team, FRIDAY - timedelta(days=14), category="launch")
        start = WEEK.start - timedelta(days=21)
        wanted = change(db, team, start, note=first, metric="sleep_minutes")
        change(db, team, start, note=second, metric="steps")  # deadline, step goal, wrong metric
        change(db, team, start, note=launch, metric="sleep_minutes")  # wrong category
        change(db, team, start, note=second, play="meeting_breaks", metric="sleep_minutes")
        change(db, team, start, metric="sleep_minutes")  # linked to no event
        found = tools.team_history(
            db,
            boss(db),
            team_id,
            TODAY,
            category="deadline",
            play="step_goal",
            metric="sleep_minutes",
        )
        by_metric = tools.team_history(
            db, boss(db), team_id, TODAY, category="deadline", metric="steps"
        )
    assert [c["case_id"] for c in found["cases"]] == [f"change:{wanted.id}"]
    assert [c["tracked"] for c in by_metric["cases"]] == [True]
    assert all(c["kind"] == "change" for c in by_metric["cases"])


def test_a_past_answer_ignores_calendar_data_synced_after_its_cutoff(engine):
    """Calendars arriving after the cutoff: the answer for then says no check was recorded by
    then and gives no followed flag; today's answer reads them."""
    from test_coach import ended_change, give_calendars

    from app.teams import reports

    team_id = make_team(engine, effects=())
    span = (TODAY - timedelta(days=21), TODAY - timedelta(days=8))
    ended_change(engine, team_id, "evening_boundary", span)
    with session_scope(engine) as db:
        reports.build_report(db, team_of(db, team_id), WEEK, NOW)  # on time

    def asked():
        later = TODAY + timedelta(days=10)
        with session_scope(engine) as db:
            then = tools.team_overview(db, boss(db), team_id, later, week=str(WEEK.start))
            [now] = view_follow_up(db, team_of(db, team_id), later)
            return then, now

    from app.teams.view import follow_up as view_follow_up

    before_sync, _ = asked()
    give_calendars(engine, 7, {"after_hours_minutes": -9.0}, span=span)  # synced later
    then, now = asked()
    assert then["as_of"] == str(TODAY)
    for answer in (before_sync, then):
        [followed] = answer["follow_up"]
        assert followed["calendar_check"] == f"No calendar check was recorded by {TODAY}."
        assert "followed_on_the_calendar" not in followed
    assert then["follow_up"] == before_sync["follow_up"]  # the sync changed nothing about then
    assert now["followed_on_the_calendar"] is True and "fell during it" in now["calendar_check"]


def test_a_long_history_pages_through_mcp_without_losing_or_repeating_a_case(engine):
    """21 matching cases on one date, plus ones the filters leave out: page one has 20, page two
    the one left, every case id once, and the last page has no cursor."""
    team_id = make_team(engine)
    server = build_mcp(engine)
    day = TODAY - timedelta(days=3)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        made = {f"event:{event(db, team, day).id}" for _ in range(21)}
        for _ in range(3):
            event(db, team, day, category="launch")  # left out by the filter
        boss_id = boss(db).id
    asked = {"team_id": team_id, "category": "deadline", "as_of": str(TODAY - timedelta(days=1))}
    error, first = call_mcp(server, boss_id, "team_history", **asked)
    assert not error and len(first["cases"]) == 20 and first["more"] == 1
    assert first["next_cursor"]
    error, second = call_mcp(
        server, boss_id, "team_history", team_id=team_id, cursor=first["next_cursor"]
    )
    assert not error and len(second["cases"]) == 1 and second["more"] == 0
    assert second["next_cursor"] is None
    assert second["filters"] == first["filters"] and second["as_of"] == first["as_of"]
    seen = [c["case_id"] for page in (first, second) for c in page["cases"]]
    assert len(seen) == 21 and set(seen) == made
    error, again = call_mcp(server, boss_id, "team_history", **asked)
    assert [c["case_id"] for c in again["cases"]] == seen[:20]  # one order on one date


def test_a_cursor_keeps_todays_date_and_is_refused_elsewhere(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        for _ in range(21):
            event(db, team, TODAY - timedelta(days=2))
        first = tools.team_history(db, boss(db), team_id, TODAY)
        later = TODAY + timedelta(days=5)
        event(db, team, TODAY + timedelta(days=1), made=NOW + timedelta(days=33))  # after day 1
        second = tools.team_history(db, boss(db), team_id, later, cursor=first["next_cursor"])
        assert second["as_of"] == str(TODAY) and len(second["cases"]) == 1
        assert "began" in second["as_of_meaning"]
        with pytest.raises(HarnessError, match="pass it alone"):
            tools.team_history(
                db, boss(db), team_id, later, category="travel", cursor=first["next_cursor"]
            )
        for bad in ("abc", first["next_cursor"][:-4], "x" * 3000):
            with pytest.raises(HarnessError, match="not a cursor"):
                tools.team_history(db, boss(db), team_id, later, cursor=bad)
        saved = json.loads(base64.urlsafe_b64decode(first["next_cursor"] + "=="))
        moved = base64.urlsafe_b64encode(
            json.dumps(saved | {"team": str(uuid.uuid4())}).encode()
        ).decode()
        with pytest.raises(HarnessError, match="another lookup"):
            tools.team_history(db, boss(db), team_id, later, cursor=moved)


def test_a_retired_entry_reads_custom_with_a_retired_status_and_no_old_id(engine):
    """In the live run the assistant named a retired change from its old id. The id is left out;
    the title and an explicit status say what it is, and its case_id opens it."""
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        old = change(db, team, WEEK.start, play="no_late_meetings", metric="sleep_minutes")
        current = change(db, team, WEEK.start, play="meeting_breaks")
        listing = tools.team_history(db, boss(db), team_id, TODAY)
        case = tools.team_case(db, boss(db), team_id, TODAY, f"change:{old.id}")
        own = tools.team_history(db, boss(db), team_id, TODAY, play="custom")
    listed = by_id(listing)
    for shown in (listed[f"change:{old.id}"], case):
        assert shown["title"] == "Custom team change"
        assert shown["playbook_entry"] == "retired" and shown["play"] is None
    assert "no_late_meetings" not in json.dumps(listing) + json.dumps(case)
    assert "retired" in case["custom_note"]
    assert listed[f"change:{current.id}"]["play"] == "meeting_breaks"
    assert listed[f"change:{current.id}"]["playbook_entry"] == "current"
    assert [c["case_id"] for c in own["cases"]] == [f"change:{old.id}"]
