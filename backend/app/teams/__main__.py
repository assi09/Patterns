"""Command line for team reports: `python -m app.teams weekly`.

Run from the repository root with the virtual environment active; the deployed platform's
scheduler runs `weekly` on Mondays. A team's week is made once, so running it again is safe.
Prints counts only, never anyone's data. `demo-members` fills a team with made-up members on a
local database, to try reports before real people join (`demo.py`). `demo-team` makes a new,
labelled team of made-up members for a presentation, and with `--remove` deletes it again; on a
deployed database it needs `--on-production`, and it never touches a team with real members.
"""

import argparse
import sys
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.agent.llm import OpenAILLM
from app.analysis.team import week_of
from app.config import settings
from app.db.models import Team
from app.db.session import session_scope
from app.teams import memberships, reports
from app.teams.briefing import brief
from app.teams.demo import (
    DemoTeamError,
    add_demo_members,
    create_demo_team,
    remove_demo_team,
)
from app.teams.email import MailError, deliver, mailer_from_settings

LOCAL_HOSTS = {None, "localhost", "127.0.0.1", "::1", "db"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.teams")
    commands = parser.add_subparsers(dest="command", required=True)
    weekly = commands.add_parser("weekly", help="make every team's report for the last full week")
    weekly.add_argument("--week", type=date.fromisoformat, help="any day of the week to report")
    weekly.add_argument("--team", type=uuid.UUID, help="only this team")
    weekly.add_argument(
        "--narrate", action="store_true", help="have a model write the prose (paid; checked)"
    )
    weekly.add_argument("--no-email", action="store_true", help="make reports without emailing")
    weekly.add_argument(
        "--agent",
        action="store_true",
        help="select weekly highlights and match upcoming events to past changes (paid)",
    )
    team_demo = commands.add_parser(
        "demo-team", help="a new, labelled team of made-up members for a presentation"
    )
    team_demo.add_argument("--supervisor", required=True, help="the presenter's account email")
    team_demo.add_argument("--name", required=True, help="must contain 'synthetic'")
    team_demo.add_argument("--count", type=int, default=8)
    team_demo.add_argument("--prefix", default="demo-member", help="made-up emails' start")
    team_demo.add_argument(
        "--lasting", action="store_true", help="time asleep lower for three weeks, not one"
    )
    team_demo.add_argument("--remove", action="store_true", help="delete the team and members")
    team_demo.add_argument("--on-production", action="store_true", help="confirm a deployed db")
    demo = commands.add_parser(
        "demo-members", help="fill a team with made-up members (local database only)"
    )
    demo.add_argument("code", help="the team's invite code")
    demo.add_argument("--count", type=int, default=6)
    demo.add_argument("--sharing", type=int, default=3, help="how many share their levels")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    if args.command == "demo-team":
        return _demo_team(args, now)
    if args.command == "demo-members":
        return _demo_members(args.code, args.count, args.sharing, now)
    week = week_of(args.week) if args.week else reports.last_full_week(now.date())
    if week.start > reports.last_full_week(now.date()).start:
        print("That week is not over yet.", file=sys.stderr)
        return 1
    writer = OpenAILLM.from_settings(settings) if args.narrate else None
    agent = OpenAILLM.from_settings(settings) if args.agent else None
    try:
        mailer = None if args.no_email else mailer_from_settings(settings)
    except MailError as error:
        print(error, file=sys.stderr)
        return 1
    made = withheld = written = emailed = failed = briefed = 0
    cost = 0.0
    with session_scope() as session:
        query = select(Team).order_by(Team.created_at)
        if args.team:
            query = query.where(Team.id == args.team)
        for team in session.scalars(query):
            report = reports.build_report(
                session, team, week, now, writer, settings.team_report_cap_usd
            )
            made += report.status == "ready"
            withheld += report.status == "withheld"
            written += report.generated_by == "model"
            if agent is not None and report.status == "ready":
                try:
                    briefed += (
                        brief(
                            agent,
                            session,
                            team,
                            report,
                            week.end + timedelta(days=1),  # the Monday after the report's week
                            now,
                            settings.team_briefing_cap_usd,
                        )
                        is not None
                    )
                except Exception as error:  # noqa: BLE001 the report and its email still go out
                    print(f"{team.name}: no briefing ({type(error).__name__})", file=sys.stderr)
            cost += report.cost_usd
            if mailer is not None:
                try:
                    emailed += deliver(session, team, report, mailer, settings.app_url, now)
                except MailError as error:
                    failed += 1  # the report is kept; the next run tries the email again
                    print(f"{team.name}: {error}", file=sys.stderr)
    print(f"Week of {week.start}: {made} reports ready, {withheld} withheld (too few people).")
    if writer:
        print(f"{written} written by the model, the rest templated; ${cost:.4f}.")
    if agent:
        print(f"{briefed} briefed by the team agent; ${cost:.4f} in all.")
    if mailer is not None:
        where = "sent" if settings.email_backend == "resend" else "written to data/outbox/"
        print(f"{emailed} emails {where}" + (f", {failed} failed." if failed else "."))
    return 1 if failed else 0


def _demo_team(args, now: datetime) -> int:
    from app.db.models import User

    local = make_url(settings.database_url).host in LOCAL_HOSTS
    if not local and not args.on_production:
        print("This database is deployed: add --on-production to confirm.", file=sys.stderr)
        return 1
    with session_scope() as session:
        boss = session.scalar(select(User).where(User.email == args.supervisor))
        if boss is None or boss.role != "supervisor" or boss.status != "approved":
            print("The supervisor must be an approved supervisor account.", file=sys.stderr)
            return 1
        try:
            if args.remove:
                team = session.scalar(
                    select(Team).where(Team.supervisor_id == boss.id, Team.name == args.name)
                )
                if team is None:
                    print("No such team.", file=sys.stderr)
                    return 1
                removed = remove_demo_team(session, team)
                print(f"{args.name}: removed, with {removed} made-up accounts and their data.")
                return 0
            team, added = create_demo_team(
                session, boss, args.name, args.count, args.prefix, args.lasting, now.date(), now
            )
        except DemoTeamError as error:
            print(error, file=sys.stderr)
            return 1
        print(
            f"{team.name}: made with {added.created} made-up members ({added.sharing} sharing "
            f"their levels), team id {team.id}."
        )
    return 0


def _demo_members(code: str, count: int, sharing: int, now: datetime) -> int:
    if make_url(settings.database_url).host not in LOCAL_HOSTS:
        print("Made-up members go only into a local database.", file=sys.stderr)
        return 1
    if not 1 <= count <= 50 or not 0 <= sharing <= count:
        print("Use 1 to 50 members, and at most that many sharing.", file=sys.stderr)
        return 1
    with session_scope() as session:
        team = memberships.team_for_code(session, code)
        if team is None:
            print("No team has this code.", file=sys.stderr)
            return 1
        added = add_demo_members(session, team, count, sharing, now.date(), now)
        name = team.name
    print(
        f"{name}: {added.created} made-up members created, {added.joined} joined, "
        f"{added.sharing} sharing their levels."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
