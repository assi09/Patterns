"""Response models. Field names are camelCase on the wire to match mobile/src/api/types.ts."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Window(ApiModel):
    start: date
    end: date


class MetricCoverage(ApiModel):
    metric: str
    label: str
    fraction_present: float


class DataStatus(ApiModel):
    source: Literal["takeout", "google_health", "none"]
    last_sync: datetime | None
    range: Window | None
    coverage: list[MetricCoverage]
    low_wear_days: list[date]


class ErrorBody(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ErrorBody


class Evidence(ApiModel):
    id: str
    tool: str
    metrics: list[str]
    windows: list[Window]
    n: int
    sufficient: bool
    stats: dict[str, Any]  # keys stay snake_case: they are statistic names, not fields


class Point(ApiModel):
    date: date
    value: float | None


class Finding(ApiModel):
    id: str
    title: str
    summary: str
    metric: str
    unit: str
    direction: Literal["up", "down", "none"]
    change: str
    series: list[Point]
    highlight: Window | None
    evidence_ids: list[str]


class Usual(ApiModel):
    median: float
    low: float  # the middle half of the 28 days before: 25th to 75th percentile
    high: float
    days: int


class DayMetric(ApiModel):
    metric: str
    value: float | None
    usual: Usual | None
    recent: list[float | None]  # the 14 days ending with this one, oldest first


class Recovery(ApiModel):
    score: float
    parts: dict[str, float]  # each input's share (0 to 100) of the 28 days before it beat


class Strain(ApiModel):
    score: float  # 0 to 21
    band: Literal["light", "moderate", "high", "all_out"]
    load: float  # weighted minutes in the heart-rate zones
    method: Literal["zones", "active_zone_minutes"]  # the second is an estimate without zones


class Stress(ApiModel):
    score: float  # 0 to 100; 50 is a typical day for this person, higher means more signs
    parts: dict[str, float]  # each input's share (0 to 100) of the 28 days before it beat


class Day(ApiModel):
    date: date
    partial: bool  # today, still filling in
    low_wear: bool  # under 10 hours of wear: activity totals are not representative
    first: date  # the range of days there is data for, for moving between days
    last: date
    metrics: list[DayMetric]
    recovery: Recovery | None = None  # with at least two of HRV, resting heart rate, sleep
    strain: Strain | None = None
    stress: Stress | None = None  # with 4 hours of still, awake wear that day


class Workout(ApiModel):
    id: str
    exercise_type: str
    name: str
    start: datetime
    end: datetime
    active_seconds: int | None
    steps: int | None = None
    distance_km: float | None = None
    calories_kcal: float | None = None
    average_heart_rate: int | None = None
    active_zone_minutes: int | None = None
    zone_seconds: dict[str, float] | None = None  # light, moderate, vigorous, peak
    source: str | None = None  # the device or app that recorded it


class DayWorkouts(ApiModel):
    available: bool  # false without a Google Health connection to read them from
    workouts: list[Workout]


class HourlySteps(ApiModel):
    available: bool
    steps: list[int | None]  # 24 local hours; None for an hour with no data


class CheckIn(ApiModel):
    day: date
    rating: int = Field(ge=1, le=5)
    tags: list[str] = []


class MetricSeries(ApiModel):
    metric: str
    points: list[Point]
    usual: Usual | None  # the usual range before the last day


class ContextQuestion(ApiModel):
    id: str
    prompt: str
    date: date
    options: list[str]
    answer: str | None


class Report(ApiModel):
    id: str
    period: Window
    created_at: datetime
    headline: str
    findings: list[Finding]
    questions: list[ContextQuestion]
    evidence: dict[str, Evidence]


class Credentials(ApiModel):
    # Loose limits here; the account rules give the person a specific message.
    email: str = Field(max_length=1000)
    password: str = Field(max_length=1000)


class Account(ApiModel):
    email: str
    status: Literal["pending", "approved", "rejected"]
    is_admin: bool
    role: Literal["member", "supervisor"] = "member"


class SignedIn(ApiModel):
    token: str
    account: Account


class Approval(ApiModel):
    role: Literal["member", "supervisor"] = "member"


class AccessRequest(ApiModel):
    id: str
    email: str
    requested_at: datetime


class SourceLink(ApiModel):
    title: str
    source: str
    url: str


class ChatMessage(ApiModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    sources: list[SourceLink] | None = None  # where the person can check it
    evidence_ids: list[str]
    action_ids: list[str] | None = None  # owned drafts, never statistical evidence
    reminder_ids: list[str] | None = None  # reminders prepared here, waiting for one tap
    attachment: dict[str, Any] | None = None  # what a question asked about
    answered_by: str | None = None  # an expert or "general"; absent on refusals
    routed: bool | None = None  # true if the router chose the expert
    consulted: list[str] | None = None
    refused: bool | None = None
    conversation_id: str | None = None
    rating: Literal["up", "down"] | None = None  # the person's thumbs, on answers only
    created_at: datetime


class RatingIn(ApiModel):
    """Thumbs up or down on an answer; null takes it back."""

    rating: Literal["up", "down"] | None


class Conversation(ApiModel):
    id: str
    title: str
    pinned: bool
    messages: int
    created_at: datetime
    updated_at: datetime


class ConversationUpdate(ApiModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    pinned: bool | None = None


class GoogleStatus(ApiModel):
    status: Literal["none", "active", "reconnect_needed"]
    syncing: bool
    last_sync: datetime | None
    last_error: str | None  # the latest sync's failure, safe to show
    missing_scopes: list[str]  # permissions the person unticked on Google's page


class ConnectStart(ApiModel):
    url: str  # Google's sign-in page, to open in the browser


# Teams (docs/teams.md)


class NewTeam(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    report_email: str | None = Field(default=None, max_length=320)


class Team(ApiModel):
    id: str
    name: str
    invite_code: str
    members: int  # active members: a count, never who
    minimum_members: int  # no team figure is built from fewer
    report_email: str | None
    paused: str | None = None  # why its figures are paused, when they are
    created_at: datetime


class TeamCode(ApiModel):
    code: str = Field(min_length=1, max_length=32)


class TeamPreview(ApiModel):
    """What joining means, shown before the person agrees."""

    team: str
    supervisor: str  # the supervisor's email: who will see the team's figures
    consent: str
    consent_version: str


class JoinTeam(TeamCode):
    consent_version: str  # the version of the text the person agreed to; must be current


class Membership(ApiModel):
    team_id: str
    team: str
    supervisor: str
    joined_at: datetime
    share_levels: bool
    levels_consent: str  # the text for the second, separate consent
    levels_consent_version: str


class ShareLevels(ApiModel):
    share: bool
    consent_version: str | None = None  # needed to turn sharing on


class ReportSection(ApiModel):
    metric: str
    label: str | None = None
    status: Literal["changed", "steady", "not_enough_data"] | None = None
    text: str
    evidence_id: str


class ReportFinding(ApiModel):
    """What the week's report leads with: a worthwhile team change, in reading order."""

    metric: str
    label: str
    kind: Literal["concern", "improvement", "change"]
    status: Literal["lasting", "new"]
    text: str
    evidence_id: str


class TeamWeekLevel(ApiModel):
    mean: float | None
    level: Literal["below", "usual", "above"] | None


class SharedLevels(ApiModel):
    """One member who chose to share, with their week against their own usual."""

    member: str  # their email
    levels: dict[str, TeamWeekLevel]  # recovery_score, sleep_minutes, strain, stress_score


class NarrativeParagraph(ApiModel):
    text: str
    kind: Literal["change", "no_change", "pattern"]
    metric: str
    evidence_ids: list[str]


class TeamReportSummary(ApiModel):
    week: Window
    status: Literal["ready", "withheld"]
    headline: str
    members_included: int
    created_at: datetime


class TeamReport(TeamReportSummary):
    members_total: int
    minimum_members: int
    sections: list[ReportSection]
    weekdays: list[ReportSection]
    priorities: list[ReportFinding] = Field(default_factory=list)  # concerns first
    alerts: list[str] = Field(default_factory=list)  # raised during the week
    challenges: list[ReportSection] = Field(default_factory=list)  # approved ones that ended
    narrative: list[NarrativeParagraph]  # the model's prose, checked; empty when templated
    evidence: dict[str, Evidence]
    generated_by: Literal["template", "model"]
    levels: list[SharedLevels]


class GenerateReport(ApiModel):
    week: date | None = None  # any day of the week; the last full week when left out


# The supervisor's team agent


class TeamChatIn(ApiModel):
    text: str = Field(min_length=1, max_length=600)


class TeamChatMessage(ApiModel):
    id: str
    role: Literal["supervisor", "agent"]
    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    rating: Literal["up", "down"] | None = None  # the supervisor's thumbs, on answers only
    created_at: datetime


class TeamAction(ApiModel):
    id: str
    kind: Literal["challenge", "message"]
    title: str
    body: str
    metric: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: Literal["proposed", "approved", "declined"]
    proposed_at: datetime
    decided_at: datetime | None = None


class TeamChatReply(ApiModel):
    messages: list[TeamChatMessage]
    proposed: list[TeamAction] = Field(default_factory=list)


class TeamNoteIn(ApiModel):
    text: str = Field(min_length=1, max_length=300)
    starts_on: date | None = None
    ends_on: date | None = None


class TeamNote(ApiModel):
    id: str
    text: str
    starts_on: date | None = None
    ends_on: date | None = None
    created_at: datetime


class TeamAlert(ApiModel):
    id: str
    metric: str
    label: str
    direction: Literal["up", "down"]
    kind: Literal["concern", "improvement", "change"] = "change"
    text: str
    raised_at: datetime
    resolved_at: datetime | None = None


class TeamActionDecision(ApiModel):
    members_told: int
    action: TeamAction
