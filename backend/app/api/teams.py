"""Teams: supervisors create them and share a code; people join with consent and may leave.

Only a supervisor's own teams are visible to them, and only as a count of members. A person sees
their own memberships. Reports come later (docs/teams.md, build order).
"""

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.agent.llm import LLM, OpenAILLM
from app.analysis.evidence import Evidence, Window
from app.analysis.team import MIN_MEMBERS, team_info, week_of
from app.api import schemas
from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.auth.accounts import LoginThrottle
from app.config import settings
from app.db.models import Team, TeamEvent, TeamMembership, TeamReport, User
from app.db.models import TeamAction as TeamActionRow
from app.db.models import TeamAlert as TeamAlertRow
from app.db.models import TeamChatMessage as TeamChatMessageRow
from app.db.models import TeamNote as TeamNoteRow
from app.reminders import store
from app.reminders.schedule import zone
from app.teams import actions as team_actions
from app.teams import agent as team_agent
from app.teams import memberships as teams
from app.teams import reports

router = APIRouter(tags=["teams"])
# Wrong codes count like wrong passwords, so codes cannot be guessed one after another.
code_throttle = LoginThrottle(max_failures=10)

Person = Annotated[User, Depends(approved_user)]


def supervisor_user(user: Person) -> User:
    if user.role != "supervisor":
        raise ApiError(403, "not_supervisor", "Only supervisors can do this.")
    return user


Supervisor = Annotated[User, Depends(supervisor_user)]


def _team(db, team: Team) -> schemas.Team:
    return schemas.Team(
        id=str(team.id),
        name=team.name,
        invite_code=team.invite_code,
        members=teams.active_members(db, team),
        minimum_members=teams.MIN_MEMBERS,
        report_email=team.report_email,
        paused=teams.overlap_problem(db, team),
        created_at=team.created_at,
    )


def _membership(membership: TeamMembership, team: Team, supervisor: User) -> schemas.Membership:
    return schemas.Membership(
        team_id=str(team.id),
        team=team.name,
        supervisor=supervisor.email,
        joined_at=membership.joined_at,
        share_levels=membership.share_levels,
        levels_consent=teams.LEVELS_CONSENT_TEXT,
        levels_consent_version=teams.LEVELS_CONSENT_VERSION,
    )


# Supervisors


@router.post("/teams", response_model=schemas.Team, status_code=201)
def create_team(body: schemas.NewTeam, db: Db, clock: Now, user: Supervisor) -> schemas.Team:
    return _team(db, teams.create_team(db, user, body.name, body.report_email, clock))


@router.get("/teams", response_model=list[schemas.Team])
def list_teams(db: Db, user: Supervisor) -> list[schemas.Team]:
    return [_team(db, team) for team in teams.supervised(db, user)]


@router.get("/teams/{team_id}", response_model=schemas.Team)
def get_team(team_id: str, db: Db, user: Supervisor) -> schemas.Team:
    return _team(db, teams.supervised_team(db, user, team_id))


@router.post("/teams/{team_id}/invite-code", response_model=schemas.Team)
def rotate_code(team_id: str, db: Db, clock: Now, user: Supervisor) -> schemas.Team:
    """A new code; the old one stops working, people already in the team stay."""
    team = teams.supervised_team(db, user, team_id)
    return _team(db, teams.rotate_code(db, team, user, clock))


# Weekly reports


def _week(report: TeamReport) -> schemas.Window:
    return schemas.Window(start=report.week_start, end=report.week_start + timedelta(days=6))


def _summary(report: TeamReport) -> schemas.TeamReportSummary:
    return schemas.TeamReportSummary(
        week=_week(report),
        status=report.status,
        headline=report.headline,
        members_included=report.members_included,
        created_at=report.created_at,
    )


def _evidence(stored: dict) -> schemas.Evidence:
    evidence = Evidence.model_validate(stored)
    return schemas.Evidence(
        id=evidence.id,
        tool=evidence.tool,
        metrics=list(evidence.metrics),
        windows=[schemas.Window(start=w.start, end=w.end) for w in evidence.windows],
        n=evidence.n,
        sufficient=evidence.sufficient,
        stats=evidence.stats,
    )


def _report(db, team: Team, report: TeamReport, user: User, clock) -> schemas.TeamReport:
    week = Window(start=report.week_start, end=report.week_start + timedelta(days=6))
    shared = reports.shared_levels(db, team, week)
    if shared:
        db.add(TeamEvent(team_id=team.id, user_id=user.id, event="levels_viewed", created_at=clock))
    return schemas.TeamReport(
        **_summary(report).model_dump(),
        members_total=report.members_total,
        minimum_members=MIN_MEMBERS,
        sections=[schemas.ReportSection(**s) for s in report.body.get("sections", [])],
        weekdays=[schemas.ReportSection(**w) for w in report.body.get("weekdays", [])],
        priorities=[schemas.ReportFinding(**f) for f in report.body.get("priorities", [])],
        alerts=list(report.body.get("alerts", [])),
        challenges=[schemas.ReportSection(**c) for c in report.body.get("challenges", [])],
        narrative=[
            schemas.NarrativeParagraph(
                text=p["text"], kind=p["kind"], metric=p["metric"], evidence_ids=p["evidence_ids"]
            )
            for p in report.body.get("narrative", [])
        ],
        evidence={key: _evidence(value) for key, value in report.evidence.items()},
        generated_by=report.generated_by,
        levels=[
            schemas.SharedLevels(
                member=email,
                levels={
                    m: schemas.TeamWeekLevel(mean=v.mean, level=v.level) for m, v in found.items()
                },
            )
            for email, found in shared
        ],
    )


@router.get("/teams/{team_id}/reports", response_model=list[schemas.TeamReportSummary])
def list_reports(team_id: str, db: Db, user: Supervisor) -> list[schemas.TeamReportSummary]:
    team = teams.supervised_team(db, user, team_id)
    found = db.scalars(
        select(TeamReport)
        .where(TeamReport.team_id == team.id)
        .order_by(TeamReport.week_start.desc())
    )
    return [_summary(report) for report in found]


@router.get("/teams/{team_id}/reports/{week}", response_model=schemas.TeamReport)
def get_report(
    team_id: str, week: date, db: Db, clock: Now, user: Supervisor
) -> schemas.TeamReport:
    team = teams.supervised_team(db, user, team_id)
    report = db.scalar(
        select(TeamReport).where(
            TeamReport.team_id == team.id, TeamReport.week_start == week_of(week).start
        )
    )
    if report is None:
        raise ApiError(404, "not_found", "There is no report for that week.")
    return _report(db, team, report, user, clock)


@router.post("/teams/{team_id}/reports", response_model=schemas.TeamReport)
def make_report(
    team_id: str, body: schemas.GenerateReport, db: Db, clock: Now, user: Supervisor
) -> schemas.TeamReport:
    """The report for a full week, made now if it was not made yet; never for a week in progress."""
    team = teams.supervised_team(db, user, team_id)
    latest = reports.last_full_week(clock.date())
    week = week_of(body.week) if body.week else latest
    if week.start > latest.start:
        raise ApiError(409, "week_not_over", "A week's report is made once the week is over.")
    report = reports.build_report(
        db, team, week, clock, report_writer(), settings.team_report_cap_usd
    )
    return _report(db, team, report, user, clock)


def report_writer() -> LLM | None:
    """The model that writes reports' prose, when switched on; tests replace it."""
    return OpenAILLM.from_settings(settings) if settings.team_report_narrative else None


# The supervisor's team agent: chat, notes, alerts and proposed actions


def team_agent_llm() -> LLM:
    """The model the team agent uses; tests replace it."""
    return OpenAILLM.from_settings(settings)


TeamLLM = Annotated[LLM, Depends(team_agent_llm)]


def _local_today(user: User, clock) -> date:
    return clock.astimezone(zone(store.timezone_of(user))).date()


def _chat_message(row: TeamChatMessageRow) -> schemas.TeamChatMessage:
    return schemas.TeamChatMessage(
        id=str(row.id),
        role=row.role,
        text=row.text,
        evidence=[_evidence(e) for e in row.evidence or []],
        rating=row.rating if row.role == "agent" else None,
        created_at=row.created_at,
    )


def _action(row: TeamActionRow) -> schemas.TeamAction:
    return schemas.TeamAction(
        id=str(row.id),
        kind=row.kind,
        title=row.title,
        body=row.body,
        metric=row.metric,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        status=row.status,
        proposed_at=row.proposed_at,
        decided_at=row.decided_at,
    )


def _note(row: TeamNoteRow) -> schemas.TeamNote:
    return schemas.TeamNote(
        id=str(row.id),
        text=row.text,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        created_at=row.created_at,
    )


@router.get("/teams/{team_id}/chat", response_model=list[schemas.TeamChatMessage])
def team_chat(team_id: str, db: Db, user: Supervisor) -> list[schemas.TeamChatMessage]:
    team = teams.supervised_team(db, user, team_id)
    return [_chat_message(m) for m in team_agent.history_of(db, team, limit=100)]


@router.post("/teams/{team_id}/chat", response_model=schemas.TeamChatReply)
def ask_team_agent(
    team_id: str, body: schemas.TeamChatIn, db: Db, clock: Now, user: Supervisor, llm: TeamLLM
) -> schemas.TeamChatReply:
    team = teams.supervised_team(db, user, team_id)
    day_start = clock - timedelta(hours=24)
    spent = sum(
        db.scalars(
            select(TeamChatMessageRow.cost_usd).where(
                TeamChatMessageRow.team_id == team.id, TeamChatMessageRow.created_at >= day_start
            )
        ).all()
    )
    if spent >= settings.chat_daily_cap_per_user_usd:
        raise ApiError(429, "daily_limit", "The team agent has reached today's limit.")
    reply = team_agent.answer_supervisor(llm, db, team, body.text, _local_today(user, clock), clock)
    return schemas.TeamChatReply(
        messages=[_chat_message(m) for m in team_agent.history_of(db, team, limit=2)],
        proposed=[_action(a) for a in reply.actions],
    )


@router.put("/teams/{team_id}/chat/{message_id}/rating", response_model=schemas.TeamChatMessage)
def rate_team_answer(
    team_id: str, message_id: str, body: schemas.RatingIn, db: Db, clock: Now, user: Supervisor
) -> schemas.TeamChatMessage:
    """The supervisor's thumbs up or down on one of the team agent's answers."""
    team = teams.supervised_team(db, user, team_id)
    try:
        key = uuid.UUID(message_id)
    except ValueError:
        key = None
    message = db.get(TeamChatMessageRow, key) if key else None
    if message is None or message.team_id != team.id or message.role != "agent":
        raise ApiError(404, "not_found", "That answer is no longer in this chat.")
    message.rating, message.rated_at = body.rating, clock if body.rating else None
    db.flush()
    return _chat_message(message)


@router.get("/teams/{team_id}/notes", response_model=list[schemas.TeamNote])
def list_notes(team_id: str, db: Db, user: Supervisor) -> list[schemas.TeamNote]:
    team = teams.supervised_team(db, user, team_id)
    return [_note(n) for n in team_agent.notes_of(db, team)]


@router.post("/teams/{team_id}/notes", response_model=schemas.TeamNote, status_code=201)
def add_note(
    team_id: str, body: schemas.TeamNoteIn, db: Db, clock: Now, user: Supervisor
) -> schemas.TeamNote:
    team = teams.supervised_team(db, user, team_id)
    if problem := team_agent._unsafe(body.text, note=True):
        raise ApiError(422, "unsafe_note", f"Not saved: {problem}")
    note = TeamNoteRow(
        team_id=team.id,
        text=body.text.strip(),
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        created_at=clock,
    )
    db.add(note)
    db.flush()
    return _note(note)


@router.delete("/teams/{team_id}/notes/{note_id}", status_code=204)
def delete_note(team_id: str, note_id: str, db: Db, user: Supervisor) -> Response:
    team = teams.supervised_team(db, user, team_id)
    for note in team_agent.notes_of(db, team):
        if str(note.id) == note_id:
            team_agent.forget_note(db, team, note)
            return Response(status_code=204)
    raise ApiError(404, "not_found", "There is no such note.")


@router.get("/teams/{team_id}/alerts", response_model=list[schemas.TeamAlert])
def list_alerts(team_id: str, db: Db, user: Supervisor) -> list[schemas.TeamAlert]:
    team = teams.supervised_team(db, user, team_id)
    rows = db.scalars(
        select(TeamAlertRow)
        .where(TeamAlertRow.team_id == team.id)
        .order_by(TeamAlertRow.raised_at.desc())
        .limit(30)
    ).all()
    return [
        schemas.TeamAlert(
            id=str(a.id),
            metric=a.metric,
            label=team_info(a.metric).label,
            direction=a.direction,
            kind=a.kind,
            text=a.text,
            raised_at=a.raised_at,
            resolved_at=a.resolved_at,
        )
        for a in rows
    ]


@router.get("/teams/{team_id}/actions", response_model=list[schemas.TeamAction])
def list_actions(team_id: str, db: Db, user: Supervisor) -> list[schemas.TeamAction]:
    team = teams.supervised_team(db, user, team_id)
    rows = db.scalars(
        select(TeamActionRow)
        .where(TeamActionRow.team_id == team.id)
        .order_by(TeamActionRow.proposed_at.desc())
    ).all()
    return [_action(a) for a in rows]


@router.post(
    "/teams/{team_id}/actions/{action_id}/{decision}", response_model=schemas.TeamActionDecision
)
def decide_action(
    team_id: str, action_id: str, decision: str, db: Db, clock: Now, user: Supervisor
) -> schemas.TeamActionDecision:
    if decision not in ("approve", "decline"):
        raise ApiError(404, "not_found", "Approve or decline.")
    team = teams.supervised_team(db, user, team_id)
    action = team_actions.action_of(db, team, action_id)
    told = team_actions.decide(db, team, action, decision == "approve", clock)
    return schemas.TeamActionDecision(members_told=told, action=_action(action))


# Members


def _team_for_code(db, user: User, code: str, clock) -> Team:
    key = f"team-code:{user.id}"
    code_throttle.check(key, clock)
    team = teams.team_for_code(db, code)
    if team is None:
        code_throttle.failed(key, clock)
        raise ApiError(404, "unknown_code", "No team has this code. Check it with your supervisor.")
    code_throttle.succeeded(key)
    return team


@router.post("/teams/preview", response_model=schemas.TeamPreview)
def preview(body: schemas.TeamCode, db: Db, clock: Now, user: Person) -> schemas.TeamPreview:
    """What joining the team means, for the person to read before agreeing."""
    team = _team_for_code(db, user, body.code, clock)
    return schemas.TeamPreview(
        team=team.name,
        supervisor=db.get(User, team.supervisor_id).email,
        consent=teams.consent_text(),
        consent_version=teams.CONSENT_VERSION,
    )


@router.post("/teams/join", response_model=schemas.Membership, status_code=201)
def join(body: schemas.JoinTeam, db: Db, clock: Now, user: Person) -> schemas.Membership:
    team = _team_for_code(db, user, body.code, clock)
    if body.consent_version != teams.CONSENT_VERSION:
        raise ApiError(409, "consent_changed", "What joining means has changed. Read it again.")
    membership = teams.join(db, team, user, clock)
    return _membership(membership, team, db.get(User, team.supervisor_id))


@router.get("/me/teams", response_model=list[schemas.Membership])
def my_teams(db: Db, user: Person) -> list[schemas.Membership]:
    return [_membership(*row) for row in teams.memberships(db, user)]


@router.post("/me/teams/{team_id}/levels", response_model=schemas.Membership)
def share_levels(
    team_id: str, body: schemas.ShareLevels, db: Db, clock: Now, user: Person
) -> schemas.Membership:
    """Turns on or off showing one's own named weekly levels to the supervisor."""
    if body.share and body.consent_version != teams.LEVELS_CONSENT_VERSION:
        raise ApiError(409, "consent_changed", "Read what sharing your levels means first.")
    membership = teams.share_levels(db, user, team_id, body.share, clock)
    team = db.get(Team, membership.team_id)
    return _membership(membership, team, db.get(User, team.supervisor_id))


@router.post("/me/teams/{team_id}/leave", status_code=204)
def leave(team_id: str, db: Db, clock: Now, user: Person) -> Response:
    teams.leave(db, user, team_id, clock)
    return Response(status_code=204)
