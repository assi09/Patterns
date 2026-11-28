"""Two first requests for one team week at once, on PostgreSQL (docs/team-metrics.md): the second
waits on the first's row, then returns it, so both show the same evidence ids. Runs where
FA_TEST_POSTGRES_URL is set."""

import threading
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_hr_invite_postgres import ADMIN_URL, BLOCKED, engine  # noqa: F401 (the fixture)

from app.analysis.team import week_of
from app.db.models import Team, TeamMetricWeek, User
from app.teams import explorer, memberships, reports

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="FA_TEST_POSTGRES_URL is not set")
NOW = datetime(2026, 11, 26, 9, tzinfo=UTC)
WEEK = week_of(date(2026, 11, 16))


def test_two_first_requests_for_a_week_store_it_once(engine):  # noqa: F811
    with Session(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        reports.build_report(db, team, WEEK, NOW)  # the week's roster is on record
        team_id = team.id
        db.commit()

    first = Session(engine)
    made = explorer.week_figures(first, first.get(Team, team_id), WEEK, NOW).results  # uncommitted
    outcome: dict = {}

    def second():
        with Session(engine) as db:
            row = explorer.week_figures(db, db.get(Team, team_id), WEEK, NOW)
            outcome["results"] = row.results
            db.commit()

    racer = threading.Thread(target=second)
    racer.start()
    racer.join(BLOCKED)
    assert racer.is_alive()  # waiting on the first request's row, not storing its own
    first.commit()
    racer.join(10)
    first.close()

    assert outcome["results"] == made  # the same evidence ids, not a second set
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(TeamMetricWeek)) == 1
