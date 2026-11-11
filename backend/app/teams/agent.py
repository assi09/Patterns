"""The supervisor's team agent: answers questions about the team, remembers what the supervisor
tells it, and proposes team-wide actions that wait for approval (docs/teams.md).

It sees team aggregates only. Every tool reads the whole team (everyone with data), never a chosen
subset, and nothing is built from fewer than MIN_MEMBERS people, so no question can isolate anyone.
The model computes nothing: tools return evidence, and each claim in an answer is checked against
it, as in the personal agent. A question about a particular person gets a fixed reply without any
model call, and a claim or proposal that singles anyone out, or sounds medical, is refused.
"""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import LLM, Budget, BudgetExceeded, LLMError
from app.agent.sanitize import reads_like_instruction
from app.agent.trace import team_trace
from app.agent.verifier import DOWN_WORDS, MEDICAL, UP_WORDS, text_problems
from app.analysis.evidence import Evidence, Window
from app.analysis.screen import FDR
from app.analysis.team import (
    MIN_MEMBERS,
    TEAM_METRICS,
    member_change,
    prepare,
    team_change,
    team_info,
    team_participation,
    team_scan,
    team_statistics,
)
from app.db.chat import add_trace
from app.db.models import Team, TeamAction, TeamAlert, TeamChatMessage, TeamNote
from app.teams.narrative import INDIVIDUAL
from app.teams.reports import _member_frames, last_full_week

ANSWER = "answer_team"
MAX_CALLS = 6
HISTORY = 6  # earlier messages of the conversation the agent reads in full
EARLIER_SAID = 20  # before those, what the supervisor said, shortened: a team chat is one thread
EARLIER_CHARS = 200
# A message that asks nothing tells the agent something: it is noted, not investigated.
ASKS = re.compile(
    r"\?|^\s*(?:what|how|why|when|where|which|who|whom|did|does|do|is|are|was|were|can|could|"
    r"should|would|will|has|have|any|tell me|show me|give me|compare|explain|summari[sz]e|list|"
    r"check|look)\b",
    re.IGNORECASE,
)
CHALLENGE_DAYS = (7, 28)

ABOUT_A_PERSON = re.compile(
    r"\b(who\b|whom\b|which (?:person|member|employee|colleague|one of)|names?\b|"
    r"individual(?:ly|s)?\b|each (?:person|member|employee)|per (?:person|member)|"
    r"single (?:person|member)|is (?:anyone|someone) (?:struggling|sick|ill|burn))",
    re.IGNORECASE,
)
# "Some of the team" picks out a group smaller than the team; "off sick" is someone's health.
SUBSET = re.compile(
    r"\b(?:some|several|a few|certain|part|half|most|many|none) of (?:the )?(?:team|you|us|them)\b|"
    r"\bsome (?:people|folks|of you)\b",
    re.IGNORECASE,
)
# "For everyone" describes each person, and the evidence is the team's median and counts. A note
# about the team's own work may say it ("everyone was crunching"): it is the supervisor's account.
EVERYONE = re.compile(
    r"\b(?:everyone|everybody|every (?:member|person|one of)|all (?:members|of them|of you))\b",
    re.IGNORECASE,
)
PART_OF_TEAM = re.compile(f"{SUBSET.pattern}|{EVERYONE.pattern}", re.IGNORECASE)
HEALTH_STATE = re.compile(
    r"\b(?:sick|ill|unwell|injur\w*|pregnan\w*|burn(?:ed|t)?[- ]?out|depress\w*|anxi\w*|"
    r"surgery|hospital\w*|diagnos\w*|medical leave|sick leave)\b",
    re.IGNORECASE,
)
ABOUT_A_PERSON_REPLY = (
    "I only ever see the team as a whole, from at least five people, so I can't say anything about "
    "one person. If you're worried about someone, the best step is a conversation with them. I can "
    "tell you how the team as a whole has been doing."
)
MEDICAL_REPLY = (
    "That's outside what I can help with: I describe patterns in the team's data, not health or "
    "medical questions."
)
FALLBACK = "I couldn't put a checked answer together this time. Could you ask it another way?"
# The supervisor asking about themselves: this agent knows the team only, and their own chats with
# Patterns stay theirs, never mixed into the team's memory.
ABOUT_ME = re.compile(
    r"\b(?:about me|know about me|me personally|my own (?:data|sleep|health|memory)|"
    r"what do you remember about me)\b",
    re.IGNORECASE,
)
ABOUT_ME_REPLY = (
    "Here I only know the team: the notes you've given me and this conversation. What you tell "
    "Patterns in your own chats stays there and never reaches the team's memory."
)
NOTED = "Got it, thanks for telling me."

SYSTEM = """You help a supervisor understand their team's Fitbit data and decide what the team \
could change. You see only team figures: each member compared with their own usual, pooled, from \
at least five people. You never see, guess at or mention any individual, and you never rank people.

What you may say: how the team's sleep, activity, recovery, load and physical stress signs moved, \
when, whether a change is lasting (two or more weeks) or new, what lined up with it from the \
supervisor's notes ("lined up with", never "caused"), and team-level options: workload, deadlines, \
meetings, schedules, a team challenge. "Physical stress signs" is a score from heart rate and \
sleep, never how anyone feels: do not call it stress or wellbeing.

How to work: call team_overview first. Use team_week for one week, team_alerts for recent alerts, \
team_notes for what the supervisor told you. When they tell you about an event worth remembering \
(a deadline, a release, travel), save it with save_team_note. Propose an action with \
propose_team_action only when they ask what to do or a lasting change calls for it; it waits for \
their approval. Then call answer_team: a short friendly summary of two to four sentences that \
leads with the answer, and claims, each citing evidence ids. Never medical, never about one \
person.
Asked what they said earlier in this chat, answer from the chat (it may need no claims); if it is \
not there, say so. Answer the question asked."""


class TeamClaim(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    kind: Literal["change", "no_change", "pattern", "value", "note", "action"]
    metric: str | None = None
    direction: Literal["up", "down"] | None = None
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("direction", mode="before")
    @classmethod
    def _no_direction(cls, value):
        return value if value in ("up", "down") else None


class TeamAnswer(BaseModel):
    summary: str = Field(min_length=1, max_length=900)
    claims: list[TeamClaim] = Field(default_factory=list, max_length=6)


@dataclass
class TeamReply:
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    actions: list[TeamAction] = field(default_factory=list)
    notes: list[TeamNote] = field(default_factory=list)
    cost_usd: float = 0.0
    stop: str = "answered"
    trace: list[dict] = field(default_factory=list)


def _tool(name: str, description: str, properties: dict | None = None, required=()) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(required),
            },
        },
    }


def tools() -> list[dict]:
    metric = {"type": "string", "enum": list(TEAM_METRICS)}
    day = {"type": "string", "description": "YYYY-MM-DD"}
    claim = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["change", "no_change", "pattern", "value", "note", "action"],
            },
            "metric": metric,
            "direction": {"type": "string", "enum": ["up", "down"]},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text", "kind", "evidence_ids"],
    }
    return [
        _tool(
            "team_overview",
            "Every area (sleep, activity, recovery, load, physical stress signs) over the last "
            "four full weeks against the 28 days before them: lasting, new or steady, with "
            "team figures.",
        ),
        _tool(
            "team_week",
            "One full week's team changes against the 28 days before, and weekday patterns.",
            {"week_start": day},
        ),
        _tool("team_alerts", "Alerts raised for this team in the last 60 days, open or ended."),
        _tool("team_notes", "What the supervisor told you about the team's work, with dates."),
        _tool(
            "save_team_note",
            "Remember an event the supervisor mentions (a deadline, release, offsite, travel), "
            "with its dates if given. About the team's work only, never about one person.",
            {"text": {"type": "string", "maxLength": 300}, "starts_on": day, "ends_on": day},
            ("text",),
        ),
        _tool(
            "propose_team_action",
            "Propose something for the whole team; it waits for the supervisor's approval. "
            "challenge: a team habit for some days (for example lights out by 23:00 for two "
            "weeks), "
            "with the metric it should move. message: a short anonymous note sent to every member.",
            {
                "kind": {"type": "string", "enum": ["challenge", "message"]},
                "title": {"type": "string", "maxLength": 80},
                "body": {"type": "string", "maxLength": 400},
                "metric": metric,
                "days": {"type": "integer", "minimum": 7, "maximum": 28},
            },
            ("kind", "title", "body"),
        ),
        _tool(
            "action_result",
            "Whether an approved challenge moved its metric for the team, once it has ended.",
            {"action_id": {"type": "string"}},
            ("action_id",),
        ),
        _tool(
            ANSWER,
            "Hand in the answer: the summary the supervisor reads and the claims behind it.",
            {"summary": {"type": "string"}, "claims": {"type": "array", "items": claim}},
            ("summary", "claims"),
        ),
    ]


class TeamTools:
    """The tools, over one team at one moment; every result is kept as evidence."""

    def __init__(self, db: Session, team: Team, today: date, now: datetime):
        self.db, self.team, self.today, self.now = db, team, today, now
        self.week = last_full_week(today)
        self.frames = _member_frames(db, team, self.week)
        self._prepared: list | None = None
        self.evidence: dict[str, Evidence] = {}
        self.actions: list[TeamAction] = []
        self.notes: list[TeamNote] = []

    def _keep(self, records: list[Evidence]) -> list[dict]:
        shown = []
        for record in records:
            self.evidence[record.id] = record
            label = team_info(record.metrics[0]).label if record.metrics else None
            shown.append(
                {"evidence_id": record.id, "tool": record.tool, "metric": label, **record.stats}
            )
        return shown

    def run(self, name: str, arguments: dict) -> dict:
        if name == "team_overview":
            scan = team_scan(self.frames, self.week)
            if not scan.metrics:
                return {
                    "error": f"Fewer than {MIN_MEMBERS} members have data, so nothing is shown."
                }
            participation = team_participation(self.frames, self.week)
            return {
                "weeks": [w.start.isoformat() for w in scan.weeks],
                "areas_moving": scan.areas,
                "metrics": self._keep(scan.metrics),
                "participation": self._keep([participation]) if participation else [],
            }
        if name == "team_week":
            week = self.week
            if start := arguments.get("week_start"):
                first = date.fromisoformat(str(start))
                week = Window(start=first, end=first + timedelta(days=6))
                if week.end >= self.today:
                    return {"error": "That week is not over yet."}
            stats = team_statistics(self.frames, week)
            if not stats.changes:
                return {"error": f"Fewer than {MIN_MEMBERS} members have data that week."}
            return {"changes": self._keep(stats.changes), "weekdays": self._keep(stats.weekdays)}
        if name == "team_alerts":
            since = self.now - timedelta(days=60)
            rows = self.db.scalars(
                select(TeamAlert).where(
                    TeamAlert.team_id == self.team.id, TeamAlert.raised_at >= since
                )
            ).all()
            records = [
                Evidence.model_validate(row.evidence).model_copy(
                    update={"stats": {**row.evidence["stats"], "open": row.resolved_at is None}}
                )
                for row in rows
            ]
            return {"alerts": self._keep(records)}
        if name == "team_notes":
            return {"notes": self._keep([_note_evidence(n) for n in notes_of(self.db, self.team)])}
        if name == "save_team_note":
            text = str(arguments.get("text", "")).strip()[:300]
            if problem := _unsafe(text, note=True):
                return {"error": f"Not saved: {problem}"}
            note = TeamNote(
                team_id=self.team.id,
                text=text,
                starts_on=_day(arguments.get("starts_on")),
                ends_on=_day(arguments.get("ends_on")),
                created_at=self.now,
            )
            self.db.add(note)
            self.db.flush()
            self.notes.append(note)
            return {"saved": self._keep([_note_evidence(note)])}
        if name == "propose_team_action":
            return self._propose(arguments)
        if name == "action_result":
            return self._result(str(arguments.get("action_id", "")))
        return {"error": f"Unknown tool {name!r}."}

    def _propose(self, arguments: dict) -> dict:
        kind = arguments.get("kind")
        title = str(arguments.get("title", "")).strip()[:80]
        body = str(arguments.get("body", "")).strip()[:400]
        metric = arguments.get("metric")
        if kind not in ("challenge", "message") or not title or not body:
            return {"error": "A proposal needs a kind (challenge or message), a title and a body."}
        if problem := _unsafe(f"{title} {body}"):
            return {"error": f"Not proposed: {problem}"}
        if metric is not None and metric not in TEAM_METRICS:
            return {"error": f"Unknown metric {metric!r}."}
        days = int(arguments.get("days") or 14)
        days = min(max(days, CHALLENGE_DAYS[0]), CHALLENGE_DAYS[1])
        start = self.today + timedelta(days=1)
        action = TeamAction(
            team_id=self.team.id,
            kind=kind,
            title=title,
            body=body,
            metric=metric if kind == "challenge" else None,
            starts_on=start if kind == "challenge" else None,
            ends_on=start + timedelta(days=days - 1) if kind == "challenge" else None,
            status="proposed",
            proposed_at=self.now,
        )
        self.db.add(action)
        self.db.flush()
        self.actions.append(action)
        record = Evidence(
            tool="team_action",
            metrics=(metric,) if metric else (),
            windows=(),
            n=0,
            sufficient=True,
            stats={"action_id": str(action.id), "kind": kind, "status": "proposed", "title": title},
        )
        return {"proposed": self._keep([record]), "note": "It waits for the supervisor's approval."}

    def _result(self, action_id: str) -> dict:
        action = next(
            (
                a
                for a in self.db.scalars(
                    select(TeamAction).where(TeamAction.team_id == self.team.id)
                )
                if str(a.id) == action_id
            ),
            None,
        )
        if action is None or action.kind != "challenge" or action.status != "approved":
            return {"error": "No approved challenge with that id."}
        if action.ends_on >= self.today or not action.metric:
            return {"error": "The challenge has not ended yet."}
        return {"result": self._keep([challenge_result(self.frames, action)])}


def challenge_result(frames: list, action: TeamAction) -> Evidence:
    """The challenge's days against the 28 before them, for the team, as for a weekly change."""
    window = Window(start=action.starts_on, end=action.ends_on)
    prepared = [prepare(frame) for frame in frames]
    changes = [member_change(frame, action.metric, window) for frame in prepared]
    return team_change([c for c in changes if c is not None], action.metric, window)


def forget_note(db: Session, team: Team, note: TeamNote) -> None:
    """Deletes a note, and the exchange it was made from: the supervisor took it back, and the
    agent reads earlier messages, so the words would otherwise keep it alive."""
    if note.source_message_id is not None:
        asked = db.get(TeamChatMessage, note.source_message_id)
        if asked is not None and asked.team_id == team.id:
            reply = db.scalar(
                select(TeamChatMessage)
                .where(
                    TeamChatMessage.team_id == team.id,
                    TeamChatMessage.role == "agent",
                    TeamChatMessage.created_at >= asked.created_at,
                )
                .order_by(TeamChatMessage.created_at)
                .limit(1)
            )
            for message in (asked, reply):
                if message is not None:
                    db.delete(message)
    db.delete(note)
    db.flush()


def notes_of(db: Session, team: Team) -> list[TeamNote]:
    return list(
        db.scalars(
            select(TeamNote).where(TeamNote.team_id == team.id).order_by(TeamNote.created_at)
        )
    )


def _note_evidence(note: TeamNote) -> Evidence:
    windows = ()
    if note.starts_on:
        windows = (Window(start=note.starts_on, end=note.ends_on or note.starts_on),)
    return Evidence(
        tool="team_note",
        metrics=(),
        windows=windows,
        n=0,
        sufficient=True,
        stats={"note": note.text},
    )


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _unsafe(text: str, note: bool = False) -> str | None:
    """Why a claim, proposal or note may not be shown, or None. A note may speak of everyone."""
    group = SUBSET if note else PART_OF_TEAM
    if reads_like_instruction(text):
        return "it reads like an instruction; notes are about the team's work."
    if INDIVIDUAL.search(text) or ABOUT_A_PERSON.search(text) or group.search(text):
        return "it would single out a person; keep it about the whole team."
    if HEALTH_STATE.search(text):
        return "it records someone's health; keep it to the team's work and plans."
    if MEDICAL.search(text):
        return "it sounds medical; keep it to everyday work and habits."
    return None


# Checking an answer


def _team_change_moved(record: Evidence) -> bool | None:
    if record.tool == "team_scan":
        return record.stats.get("status") in ("lasting", "new")
    if record.tool == "team_change" and record.sufficient:
        p = record.stats.get("p_value_adjusted", record.stats.get("p_value"))
        return p is not None and p < FDR
    if record.tool == "team_alert":
        return True
    return None


def _direction(record: Evidence) -> str | None:
    if "direction" in record.stats:
        return record.stats["direction"]
    if "median_change" in record.stats:
        return "up" if record.stats["median_change"] > 0 else "down"
    return None


def check_claim(claim: TeamClaim, evidence: dict[str, Evidence]) -> list[str]:
    missing = [i for i in claim.evidence_ids if i not in evidence]
    if missing:
        return [f"cites evidence that does not exist: {', '.join(missing)}"]
    cited = [evidence[i] for i in claim.evidence_ids]
    reasons = []
    about = [e for e in cited if claim.metric in e.metrics] if claim.metric else cited
    if claim.kind in ("change", "no_change", "pattern", "value") and not about:
        reasons.append("none of the cited evidence is about that metric")
    moved = [m for e in about if (m := _team_change_moved(e)) is not None]
    if claim.kind == "change":
        support = [e for e in about if _team_change_moved(e)]
        if not support:
            reasons.append("no cited team evidence shows that change")
        elif claim.direction is None:
            reasons.append("a change must state its direction")
        elif {_direction(e) for e in support} != {claim.direction}:
            reasons.append(f"the team's change does not point {claim.direction}")
        else:
            up, down = bool(UP_WORDS.search(claim.text)), bool(DOWN_WORDS.search(claim.text))
            if (claim.direction == "up" and down and not up) or (
                claim.direction == "down" and up and not down
            ):
                reasons.append("the wording contradicts the stated direction")
    if claim.kind == "no_change" and (not moved or any(moved)):
        reasons.append("no_change must cite team evidence that shows no change")
    if claim.kind == "pattern" and not any(e.tool == "team_weekday" for e in about):
        reasons.append("a weekday pattern must cite a team_weekday evidence id from team_week")
    if claim.kind == "note" and not any(e.tool == "team_note" for e in cited):
        reasons.append("a note claim must cite the note")
    if claim.kind == "action" and not any(e.tool == "team_action" for e in cited):
        reasons.append("an action claim must cite the proposal")
    if problem := _unsafe(claim.text):
        reasons.append(problem)
    return reasons + text_problems(claim.text, cited, general=True)


def check_answer(answer: TeamAnswer, evidence: dict[str, Evidence], said: str = "") -> list[str]:
    """`said` is the conversation: the summary may repeat the supervisor's own "10am" or date."""
    problems = []
    for at, claim in enumerate(answer.claims):
        problems += [f"claim {at + 1}: {r}" for r in check_claim(claim, evidence)]
    if problem := _unsafe(answer.summary):
        problems.append(f"summary: {problem}")
    problems += [
        f"summary: {r}"
        for r in text_problems(answer.summary, list(evidence.values()), said, general=True)
    ]
    return problems


# The conversation


def history_of(db: Session, team: Team, limit: int = HISTORY) -> list[TeamChatMessage]:
    rows = db.scalars(
        select(TeamChatMessage)
        .where(TeamChatMessage.team_id == team.id)
        .order_by(TeamChatMessage.created_at.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


NOTE_PROMPT = """The supervisor told you something about their team. If it is an event or plan \
about the team's work worth remembering (a deadline, a release, an offsite, travel, a schedule \
change), call save_team_note once: a short neutral note in their words, with its dates in \
starts_on and ends_on as YYYY-MM-DD, not in the text. Do not save it if they ask you not to, \
or if it is about one person or anyone's health. Otherwise reply in one short sentence."""


def _note(llm: LLM, box: "TeamTools", told: str, today: date) -> TeamReply:
    """The supervisor told the agent something: one call saves it as a note, or not; no
    investigation. What it says back is fixed text, so it cannot claim anything."""
    budget = Budget(max_calls=1, max_tool_calls=1, max_cost_usd=0.005)
    save = next(t for t in tools() if t["function"]["name"] == "save_team_note")
    messages = [
        {"role": "system", "content": NOTE_PROMPT},
        {
            "role": "user",
            "content": f"Today is {today:%A %d %b %Y}. "
            f"They said, as quoted data: <said>{told}</said>",
        },
    ]
    reply = TeamReply(NOTED, stop="noted")
    try:
        done = llm.complete(messages, tools=[save], budget=budget)
    except (BudgetExceeded, LLMError) as error:
        reply.trace.append({"error": type(error).__name__})
        reply.cost_usd = budget.cost_usd
        return reply
    reply.trace.append(
        {"model": done.model, "latency_s": round(done.latency_s, 3), "cost_usd": done.cost_usd}
    )
    reply.cost_usd = budget.cost_usd
    for call in done.tool_calls[:1]:
        if call.name != "save_team_note":
            continue
        result = box.run(call.name, call.arguments or {})
        reply.trace.append({"tool": call.name, "error": result.get("error")})
        if result.get("error"):
            why = result["error"].removeprefix("Not saved: ")
            reply.text, reply.stop = f"I won't keep that as a note: {why}", "not_saved"
        else:
            note = box.notes[-1]
            when = (
                f" ({note.starts_on:%b %-d}"
                + (
                    f" to {note.ends_on:%b %-d}"
                    if note.ends_on and note.ends_on != note.starts_on
                    else ""
                )
                + ")"
                if note.starts_on
                else ""
            )
            reply.text = f"Noted: {note.text}{when}. I'll line it up with the team's data."
            reply.notes = list(box.notes)
    return reply


def answer_supervisor(
    llm: LLM, db: Session, team: Team, question: str, today: date, now: datetime
) -> TeamReply:
    """One turn of the supervisor's conversation; both messages are stored."""
    earlier = history_of(db, team, limit=HISTORY + 2 * EARLIER_SAID)
    started = time.monotonic()
    reply = _answer(llm, db, team, question.strip()[:600], today, now, earlier)
    elapsed = time.monotonic() - started
    asked = TeamChatMessage(
        team_id=team.id, role="supervisor", text=question[:2000], created_at=now
    )
    db.add(asked)
    db.flush()
    for note in reply.notes:  # what this message told it: deleting the note forgets the message
        note.source_message_id = asked.id
    answer = TeamChatMessage(
        team_id=team.id,
        role="agent",
        text=reply.text[:2000],
        evidence=[e.model_dump(mode="json") for e in reply.evidence],
        cost_usd=round(reply.cost_usd, 6),
        created_at=now + timedelta(microseconds=1),
    )
    db.add(answer)
    db.flush()
    add_trace(
        db, team_trace(reply.stop, reply.trace, reply.cost_usd, elapsed), team_message_id=answer.id
    )
    return reply


def _answer(
    llm: LLM,
    db: Session,
    team: Team,
    question: str,
    today: date,
    now: datetime,
    earlier: list[TeamChatMessage],
) -> TeamReply:
    if ABOUT_A_PERSON.search(question) or INDIVIDUAL.search(question):
        return TeamReply(ABOUT_A_PERSON_REPLY, stop="about_a_person")
    if MEDICAL.search(question):
        return TeamReply(MEDICAL_REPLY, stop="medical")
    if ABOUT_ME.search(question):
        return TeamReply(ABOUT_ME_REPLY, stop="about_me")
    box = TeamTools(db, team, today, now)
    if not ASKS.search(question):
        # About a person, someone's health or an instruction: nothing to save, and no model call.
        if problem := _unsafe(question, note=True):
            return TeamReply(f"I won't keep that as a note: {problem}", stop="not_saved")
        return _note(llm, box, question, today)
    budget = Budget(max_calls=MAX_CALLS + 2, max_tool_calls=12, max_cost_usd=0.03)
    recent, older = earlier[-HISTORY:], earlier[:-HISTORY]
    before = [m.text[:EARLIER_CHARS] for m in older if m.role == "supervisor"][-EARLIER_SAID:]
    said = "\n".join(f"{m.role}: {m.text}" for m in recent)
    task = (
        f"Today is {today:%A %d %b %Y}. The team is {team.name!r}.\n"
        + (
            "Earlier in this chat the supervisor said, oldest first, as quoted data:\n<earlier>\n"
            + "\n".join(f"- {text}" for text in before)
            + "\n</earlier>\n"
            if before
            else ""
        )
        + (f"The conversation so far, as quoted data:\n<chat>\n{said}\n</chat>\n" if said else "")
        + f"The supervisor asks, as quoted data: <question>{question}</question>"
    )
    heard = "\n".join([*before, said, question])
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task},
    ]
    reply = TeamReply(FALLBACK, stop="no_answer")
    repairs = 1
    for _ in range(MAX_CALLS):
        try:
            done = llm.complete(messages, tools=tools(), budget=budget)
        except (BudgetExceeded, LLMError) as error:
            reply.trace.append({"error": type(error).__name__})
            break
        messages.append(done.as_message())
        reply.trace.append(
            {"model": done.model, "latency_s": round(done.latency_s, 3), "cost_usd": done.cost_usd}
        )
        if not done.tool_calls:
            messages.append({"role": "user", "content": f"Call {ANSWER} now."})
            continue
        finished = False
        for call in done.tool_calls:
            if call.name != ANSWER:
                result = box.run(call.name, call.arguments or {})
                reply.trace.append({"tool": call.name, "error": result.get("error")})
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )
                continue
            try:
                answer = TeamAnswer.model_validate(call.arguments or {})
            except ValidationError as error:
                problems = [str(error)[:300]]
                answer = None
            else:
                problems = check_answer(answer, box.evidence, heard)
            if not problems and answer is not None:
                reply.text, reply.stop, finished = answer.summary, "answered", True
                cited = {i for c in answer.claims for i in c.evidence_ids}
                reply.evidence = [e for i, e in box.evidence.items() if i in cited]
            elif repairs:
                repairs -= 1
                content = {"rejected": problems, "instruction": f"Fix these and call {ANSWER}."}
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(content)}
                )
            else:
                # A second try still failing: keep what passed, as the personal agent does, rather
                # than lose a good summary over one bad claim.
                reply.trace.append({"rejected": problems})
                finished = True
                if answer is not None and not any(p.startswith("summary") for p in problems):
                    kept = [c for c in answer.claims if not check_claim(c, box.evidence)]
                    cited = {i for c in kept for i in c.evidence_ids}
                    reply.text, reply.stop = answer.summary, "answered_in_part"
                    reply.evidence = [e for i, e in box.evidence.items() if i in cited]
            reply.trace.append({"answer": "accepted" if not problems else "rejected"})
        if finished:
            break
    reply.cost_usd = budget.cost_usd
    reply.actions, reply.notes = box.actions, box.notes
    if reply.stop != "answered" and box.actions:  # a proposal was made: say so plainly
        reply.text = "I've proposed this for your approval: " + "; ".join(
            a.title for a in box.actions
        )
    return reply
