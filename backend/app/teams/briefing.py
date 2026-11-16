"""The team agent's Monday run: it investigates the week by itself and briefs the supervisor.

Until now the agent only answered when asked, and the weekly report was written by code. Each
Monday the agent now does what a supervisor would ask for: what changed across the team and what
lined up with it from their notes, how any challenge that ended went, and, when a lasting concern
calls for it, a team-level action proposed for approval. Its summary and claims go through the
same checks as in chat (team figures from at least five people, nothing about one person, nothing
medical, every claim on evidence). The briefing is kept with the week's report, shown at the top of
the Team tab and in the Monday email, and posted to the team chat as the agent's message, so the
supervisor can reply to it. When the agent fails, the code-written report stands alone.
"""

import time
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.agent.llm import LLM, Budget
from app.agent.trace import team_trace
from app.db.chat import add_trace
from app.db.models import Team, TeamChatMessage, TeamReport
from app.teams.agent import TeamReply, TeamTools, run_agent
from app.teams.memberships import overlap_problem

MAX_TOOL_CALLS = 14

TASK = """It is Monday {today}, and you are briefing the supervisor of the team {team!r} on the \
week that just ended ({week}). Nobody asked a question: work out what they most need to know.

1. Call team_overview, then team_week for that week, team_alerts and team_notes.
2. Call team_actions; for each approved challenge that has ended, call action_result.
3. If a lasting concern calls for it and nothing like it is already proposed, propose one \
team-level action with propose_team_action. Otherwise propose nothing.
4. Call answer_team. The summary is the briefing: two to five short sentences, the most \
important first: what changed and for how many, what lined up with it from the notes, how an \
ended challenge went, and any proposal waiting for them. If nothing moved, say the team held \
steady. No greeting, no sign-off. Every figure in it is one of your claims.

Only what the tools mark as changed (lasting or new, big and broad enough) is a change; a smaller \
movement is "held steady" (a no_change claim) or left out. Round figures as people say them \
("35 min", "1,400 steps"). That nothing ended, or that you propose nothing, needs no claim: say it \
in a few words without one, or leave it out."""


def brief(
    llm: LLM, db: Session, team: Team, report: TeamReport, today: date, now: datetime, cap: float
) -> TeamReply | None:
    """Runs the Monday investigation for a ready report and keeps what it found on the report;
    None when there is nothing to brief on or the agent could not hand in a checked briefing."""
    if report.status != "ready" or overlap_problem(db, team):
        return None
    if (report.body or {}).get("briefing"):
        return None  # once a week: a second run would post a second message
    box = TeamTools(db, team, today, now)
    week = f"{report.week_start:%a %b %-d} to {report.week_start + timedelta(days=6):%a %b %-d}"
    task = TASK.format(today=f"{today:%d %b %Y}", team=team.name, week=week)
    # More turns than a chat answer: five steps of investigation, then room for two repairs.
    budget = Budget(max_calls=12, max_tool_calls=MAX_TOOL_CALLS, max_cost_usd=cap)
    started = time.monotonic()
    reply = run_agent(llm, box, task, heard="", budget=budget, rounds=10, repairs=2)
    reply.cost_usd = budget.cost_usd
    elapsed = time.monotonic() - started
    report.cost_usd = round((report.cost_usd or 0) + reply.cost_usd, 6)
    # Unasked and emailed, so stricter than chat: every claim must check out, or no briefing.
    if reply.stop != "answered" or not reply.claims:
        rejected = [p for step in reply.trace for p in step.get("rejected", [])]
        report.body = {**report.body, "briefing_failed": {"stop": reply.stop, "why": rejected[:5]}}
        db.flush()
        return None
    cited = {i for claim in reply.claims for i in claim.evidence_ids}
    kept = {e.id: e for e in reply.evidence} | {
        e.id: e for e in box.evidence.values() if e.id in cited
    }
    report.body = {
        **report.body,
        "briefing": {
            "summary": reply.text,
            "items": [
                {"text": c.text, "kind": c.kind, "metric": c.metric, "evidence_ids": c.evidence_ids}
                for c in reply.claims
            ],
            "proposals": len(reply.actions),
            "made_at": now.isoformat(),
        },
    }
    report.evidence = {**report.evidence, **{i: e.model_dump(mode="json") for i, e in kept.items()}}
    message = TeamChatMessage(
        team_id=team.id,
        role="agent",
        text=reply.text[:2000],
        evidence=[e.model_dump(mode="json") for e in kept.values()],
        cost_usd=round(reply.cost_usd, 6),
        created_at=now,
    )
    db.add(message)
    db.flush()
    add_trace(
        db, team_trace(reply.stop, reply.trace, reply.cost_usd, elapsed), team_message_id=message.id
    )
    return reply
