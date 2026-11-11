"""The pilot report on a made-up database: the right totals, and nothing that names anyone."""

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import pilot_report
from app.analysis.day import RECOVERY, with_scores
from app.analysis.evidence import Window
from app.analysis.tools import compare_windows, correlate, describe, weekday_split
from app.config import settings
from app.db.daily import save_daily
from app.db.models import (
    Alarm,
    AnswerTrace,
    ChatMessage,
    CheckIn,
    EvidenceRecord,
    MemoryFact,
    Reminder,
    TeamAction,
    TeamAlert,
    TeamChatMessage,
    User,
)
from app.db.session import session_scope
from app.pilot_report import judge, report
from app.synthetic import Step, generate
from app.teams import memberships

START = date(2026, 9, 1)
DAYS = 75
SINCE = START + timedelta(days=60)
UNTIL = START + timedelta(days=DAYS - 1)
SECRET = "Did my late nights wreck my sleep"  # a question's words: never in the report


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def at(day: date, hour: int = 9) -> datetime:
    return datetime.combine(day, time(hour), UTC)


def person(db, email: str, seed: int, effects=()) -> tuple[User, pd.DataFrame]:
    user = User(email=email, status="approved")
    db.add(user)
    db.flush()
    frame = generate(START, DAYS, effects, seed=seed).frame
    save_daily(db, user.id, "google_health", frame)
    return user, frame


def answer(db, user, day, claims, evidence=(), trace=None, rating=None, cost=0.01):
    db.add(ChatMessage(user_id=user.id, role="user", text=SECRET, created_at=at(day, 8)))
    message = ChatMessage(
        user_id=user.id,
        role="assistant",
        text="Your time asleep fell by about 90 minutes.",
        claims=claims,
        evidence_ids=[e.id for e in evidence],
        cost_usd=cost,
        rating=rating,
        created_at=at(day),
    )
    db.add(message)
    db.flush()
    for e in evidence:
        db.add(
            EvidenceRecord(user_id=user.id, id=e.id, tool=e.tool, payload=e.model_dump(mode="json"))
        )
    if trace:
        defaults = {"stop_reason": "submitted", "latency_ms": 4000, "stages_ms": {"model": 3000}}
        db.add(AnswerTrace(message_id=message.id, **(defaults | trace)))
    return message


def claim(kind: str, evidence, direction=None, metric="sleep_minutes") -> dict:
    return {
        "text": "Time asleep fell.",
        "kind": kind,
        "evidence_ids": [evidence.id],
        "metric": metric,
        "direction": direction,
    }


@pytest.fixture
def pilot(engine, monkeypatch):
    """Two pilot people, the owner (an admin, left out), and a team of five."""
    monkeypatch.setattr(settings, "admin_emails", ["owner@example.com"])
    drop = (Step("sleep_minutes", START + timedelta(days=61), -90.0),)
    with session_scope(engine) as db:
        owner, _ = person(db, "owner@example.com", 0)
        first, frame = person(db, "first@example.com", 1, drop)
        second, _ = person(db, "second@example.com", 2)
        recent = Window(start=SINCE + timedelta(days=1), end=UNTIL)
        baseline = Window(start=START + timedelta(days=20), end=SINCE)
        fell = compare_windows(frame, "sleep_minutes", recent, baseline)
        assert fell.stats["p_value"] < 0.001  # the planted drop is unmistakable
        day = SINCE + timedelta(days=2)
        answer(
            db,
            first,
            day,
            [
                claim("change", fell, "down"),  # right
                claim("change", fell, "up"),  # wrong way round
                claim("value", fell),  # not something the key judges
            ],
            [fell],
            trace={"outcome": "answered", "question_type": "change", "model_calls": 3},
            rating="up",
            cost=0.02,
        )
        answer(
            db,
            first,
            day + timedelta(days=1),
            [],
            trace={"outcome": "refused", "stop_reason": "refused", "latency_ms": 50},
            cost=0.0,
        )
        answer(
            db,
            second,
            day,
            [],
            trace={"outcome": "failed_checks", "summary_fell_back": True, "latency_ms": 9000},
            rating="down",
        )
        answer(db, second, day + timedelta(days=3), [])  # from before traces were stored
        answer(db, owner, day, [], trace={"outcome": "answered"})  # the owner's own use
        answer(db, first, START + timedelta(days=5), [], trace={"outcome": "failed"})  # earlier

        # Check-ins that follow the recovery score for the first person; three for the second.
        scores = with_scores(frame)[RECOVERY].loc[pd.Timestamp(SINCE) :].dropna()
        ranks = scores.rank(pct=True)
        for stamp, rank in ranks.items():
            rating = 1 + min(4, int(rank * 5))
            db.add(CheckIn(user_id=first.id, day=stamp.date(), rating=rating, tags=[]))
        for offset in range(3):
            db.add(CheckIn(user_id=second.id, day=SINCE + timedelta(days=offset), rating=3))

        common = {"kind": "day", "key": "k", "day": day, "severity": 1.0, "title": "t", "body": "b"}
        db.add(Alarm(user_id=first.id, status="sent", feedback="useful", **common))
        db.add(Alarm(user_id=first.id, status="sent", feedback="not_useful", **common))
        db.add(Alarm(user_id=second.id, status="sent", **common))
        db.add(Alarm(user_id=second.id, status="suppressed", **common))
        for when in (at(day), at(day)):
            for status in ("active", "declined"):
                db.add(
                    Reminder(
                        user_id=first.id,
                        title="Wind down",
                        message="m",
                        schedule={},
                        timezone="UTC",
                        channels=["in_app"],
                        status=status,
                        source="agent",
                        created_at=when,
                    )
                )
        for status in ("approved", "declined", "proposed", "candidate"):
            db.add(
                MemoryFact(
                    user_id=first.id, kind="context", text="x", status=status, created_at=at(day)
                )
            )

        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, at(START))
        for user in (first, second):
            memberships.join(db, team, user, at(START))
        for i in range(3):
            other, _ = person(db, f"member{i}@example.com", 10 + i)
            memberships.join(db, team, other, at(START))
        db.add(
            TeamAlert(
                team_id=team.id,
                metric="sleep_minutes",
                direction="down",
                text="t",
                evidence={},
                raised_at=at(day),
            )
        )
        for status in ("approved", "declined"):
            db.add(
                TeamAction(
                    team_id=team.id,
                    kind="challenge",
                    title="t",
                    body="b",
                    status=status,
                    proposed_at=at(day),
                )
            )
        said = TeamChatMessage(
            team_id=team.id,
            role="agent",
            text="The team slept less.",
            cost_usd=0.003,
            rating="up",
            created_at=at(day),
        )
        db.add(said)
        db.flush()
        db.add(
            AnswerTrace(
                team_message_id=said.id,
                outcome="answered",
                stop_reason="answered",
                latency_ms=2000,
                stages_ms={},
            )
        )
    return engine


def made(engine) -> dict:
    with session_scope(engine) as db:
        return report(db, SINCE, UNTIL)


def test_usage_success_latency_cost_and_thumbs(pilot):
    result = made(pilot)
    assert result["people"] == 6  # two pilot people, three more members and the supervisor
    chat = result["chat"]
    assert chat["questions"] == 4 and chat["people_who_asked"] == 2
    assert chat["answers"] == 3 and chat["untraced_answers"] == 1
    assert chat["outcomes"] == {"answered": 1, "failed_checks": 1, "refused": 1}
    assert chat["success_rate"] == 0.5  # one of the two it was allowed to answer
    assert chat["refusal_rate"] == pytest.approx(0.333)
    assert chat["latency_s"]["median"] == 4.0 and chat["latency_s"]["max"] == 9.0
    assert chat["summary_fell_back"] == 1
    assert chat["question_types"] == {"change": 1, "unknown": 2}
    assert chat["cost_usd"]["total"] == pytest.approx(0.04)
    assert chat["thumbs"] == {"rated": 2, "rated_share": 0.5, "up": 1, "down": 1, "up_rate": 0.5}
    assert chat["thumbs_by_outcome"]["answered"]["up"] == 1
    counts = sorted(row["questions"] for row in chat["per_person"])
    assert counts == [0, 0, 0, 0, 2, 2]


def test_claims_are_checked_against_the_independent_key(pilot):
    accuracy = made(pilot)["accuracy"]
    assert accuracy["claims"] == 3 and accuracy["checked"] == 2
    assert accuracy["agree"] == 1 and accuracy["disagree"] == 1 and accuracy["unchecked"] == 1
    assert accuracy["by_tool"] == {"compare_windows": {"agree": 1, "disagree": 1}}


def test_the_recovery_score_is_compared_with_check_ins_across_people(pilot):
    recovery = made(pilot)["recovery_vs_check_ins"]
    assert recovery["people_with_check_ins"] == 2
    assert recovery["people_compared"] == 1 and recovery["too_few_days"] == 1
    assert recovery["positive_significant"] == 1 and recovery["median_rho"] > 0.8


def test_alerts_reminders_and_memory_cards(pilot):
    proposals = made(pilot)["proposals"]
    assert proposals["alerts"] == {
        "raised": 4,
        "sent": 3,
        "useful": 1,
        "not_useful": 1,
        "useful_rate": 0.5,
    }
    assert proposals["agent_reminders"] == {"proposed": 4, "kept": 2, "declined": 2}
    assert proposals["memory_cards"] == {"shown": 3, "kept": 1, "declined": 1, "waiting": 1}


def test_team_results(pilot):
    (team,) = made(pilot)["teams"]["teams"]
    assert team["team"] == "team 1" and team["members"] == 5
    assert team["alerts_raised"] == 1
    assert team["proposals"] == {"approved": 1, "declined": 1}
    assert team["agent"]["answers"] == 1 and team["agent"]["success_rate"] == 1.0
    assert team["thumbs"]["up"] == 1


def test_the_owner_counts_only_when_asked(pilot):
    with session_scope(pilot) as db:
        with_owner = report(db, SINCE, UNTIL, include_admins=True)
    assert with_owner["people"] == 7 and with_owner["chat"]["answers"] == 4


def test_the_printed_report_names_no_one_and_quotes_nothing(pilot, monkeypatch):
    monkeypatch.setattr(pilot_report, "session_scope", lambda: session_scope(pilot))
    out = io.StringIO()
    with redirect_stdout(out):
        pilot_report.main(["--since", SINCE.isoformat(), "--until", UNTIL.isoformat()])
    printed = out.getvalue()
    result = json.loads(printed)
    assert result["chat"]["questions"] == 4
    for private in ("@example.com", SECRET, "Time asleep fell", "90 minutes", "Design", "Wind"):
        assert private not in printed
    with session_scope(pilot) as db:
        ids = [str(u.id) for u in db.query(User)]
    assert not any(i in printed for i in ids)
    labels = {row["person"] for row in result["chat"]["per_person"]}
    assert labels == {f"person {n}" for n in range(1, 7)}


def test_an_empty_pilot_reports_zeros_not_errors(engine, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", [])
    result = made(engine)
    assert result["people"] == 0 and result["chat"]["questions"] == 0
    assert result["chat"]["success_rate"] is None and result["accuracy"]["agreement"] is None
    assert result["recovery_vs_check_ins"]["median_rho"] is None


def test_a_backwards_period_is_refused(capsys):
    with pytest.raises(SystemExit):
        pilot_report.main(["--since", "2026-11-20", "--until", "2026-11-12"])
    assert "before" in capsys.readouterr().err


# The key's judgement of one claim, on numbers made by hand


def frame_with(recent: list[float], baseline: list[float]) -> pd.DataFrame:
    days = pd.date_range("2026-10-01", periods=len(baseline) + len(recent), freq="D")
    return pd.DataFrame({"m": baseline + recent, "n": list(range(len(days)))}, index=days)


def payload(tool: str, metrics, windows, **stats) -> dict:
    return {"tool": tool, "metrics": list(metrics), "windows": windows, "stats": stats}


def window(frame: pd.DataFrame, first: int, last: int) -> dict:
    return {
        "start": frame.index[first].date().isoformat(),
        "end": frame.index[last].date().isoformat(),
    }


def test_judge_reads_changes_no_changes_and_unknown_evidence():
    frame = frame_with([400.0 + i % 3 for i in range(14)], [480.0 + i % 3 for i in range(14)])
    fell = payload("compare_windows", ["m"], [window(frame, 14, 27), window(frame, 0, 13)])
    evidence = {"e": fell}
    said = {"kind": "change", "direction": "down", "evidence_ids": ["e"]}
    assert judge(said, evidence, frame) == ("agree", "compare_windows")
    assert judge(said | {"direction": "up"}, evidence, frame)[0] == "disagree"
    assert judge({"kind": "no_change", "evidence_ids": ["e"]}, evidence, frame)[0] == "disagree"
    assert judge(said | {"evidence_ids": ["missing"]}, evidence, frame)[0] == "unchecked"
    other = {"e": payload("trend", ["m"], [window(frame, 0, 27)])}
    assert judge(said, other, frame)[0] == "unchecked"
    assert judge({"kind": "day", "evidence_ids": ["e"]}, evidence, frame)[0] == "unchecked"


def test_judge_reads_a_flat_series_as_no_change():
    frame = frame_with([450.0 + i % 4 for i in range(14)], [450.0 + i % 4 for i in range(14)])
    flat = {"e": payload("compare_windows", ["m"], [window(frame, 14, 27), window(frame, 0, 13)])}
    assert judge({"kind": "no_change", "evidence_ids": ["e"]}, flat, frame)[0] == "agree"


def test_judge_reads_links_and_weekend_gaps_with_the_real_tools():
    frame = frame_with([float(i % 7) for i in range(30)], [float(i % 7) for i in range(30)])
    frame["n"] = frame["m"] * 2 + 1
    whole = Window(start=frame.index[0].date(), end=frame.index[-1].date())
    linked = correlate(frame, "m", "n", whole)
    evidence = {"c": linked.model_dump(mode="json")}
    said = {"kind": "association", "direction": "up", "evidence_ids": ["c"]}
    assert judge(said, evidence, frame) == ("agree", "correlate")
    assert judge(said | {"direction": "down"}, evidence, frame)[0] == "disagree"
    weekend = frame.index.dayofweek >= 5
    frame.loc[weekend, "m"] += 50
    split = {"w": weekday_split(frame, "m", whole).model_dump(mode="json")}
    gap = {"kind": "change", "direction": "up", "evidence_ids": ["w"]}
    assert judge(gap, split, frame) == ("agree", "weekday_split")


# Recall: what a "has anything changed" answer missed


def test_benjamini_hochberg_keeps_only_what_survives_testing_many():
    from app.oracle import discoveries

    # Thresholds 0.0125, 0.025, 0.0375, 0.05: b passes its own, c does not.
    assert discoveries({"a": 0.001, "b": 0.02, "c": 0.04, "d": 0.5}) == {"a", "b"}
    assert discoveries({"a": 0.001, "b": 0.01, "c": 0.02}) == {"a", "b", "c"}
    assert discoveries({"a": 0.2}) == set() and discoveries({}) == set()


def route(expert: str | None) -> list[dict]:
    return [{"type": "route", "expert": expert}]


def test_recall_counts_named_missed_and_unsupported_changes(engine, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", [])
    drop = (Step("sleep_minutes", START + timedelta(days=40), -120.0),)
    asked = SINCE + timedelta(days=2)
    with session_scope(engine) as db:
        user, frame = person(db, "first@example.com", 3, drop)
        last = pd.Timestamp(asked - timedelta(days=1))
        changed = pilot_report.changes_in(frame, pilot_report.EXPERTS["sleep"].owns, last)
        assert changed["sleep_minutes"] == "down"  # the drop, and whatever moved with it
        k = len(changed)
        some = describe(frame, "sleep_minutes", Window(start=START, end=asked))  # any evidence
        good = claim("change", some, "down")
        cases = [
            ([good], "answered"),  # named
            ([], "answered"),  # missed
            ([good | {"direction": "up"}], "answered_in_part"),  # the wrong way round
            ([good | {"metric": "steps"}, good], "answered"),  # one the key does not see change
            ([], "refused"),  # not counted: it did not answer
        ]
        for claims, outcome in cases:
            answer(
                db,
                user,
                asked,
                claims,
                trace={"outcome": outcome, "question_type": "change", "steps": route("sleep")},
            )
        answer(db, user, asked, [], trace={"outcome": "answered", "question_type": "lookup"})
    recall = made(engine)["recall"]
    assert recall["questions_checked"] == 4 and recall["changes_found_by_key"] == 4 * k
    assert recall["named"] == 2 and recall["wrong_direction"] == 1
    assert recall["missed"] == 4 * k - 3
    assert recall["recall"] == round(2 / (4 * k), 3)
    assert recall["said_changed_key_did_not"] == 1


def test_the_key_rarely_finds_a_change_where_none_was_planted():
    """Over many people with nothing planted, a quiet answer is almost never marked as a miss."""
    sleep = pilot_report.EXPERTS["sleep"].owns
    found = sum(
        bool(
            pilot_report.changes_in(
                generate(START, 60, seed=seed).frame, sleep, START + timedelta(days=59)
            )
        )
        for seed in range(200)
    )
    assert found / 200 <= 0.10
