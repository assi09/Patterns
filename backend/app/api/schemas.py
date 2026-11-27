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


class SleepStage(ApiModel):
    start: datetime
    end: datetime
    stage: Literal["awake", "light", "deep", "rem", "asleep", "restless"]


class NightStages(ApiModel):
    """The night ending on a day, stage by stage, as the tracker scored it."""

    available: bool  # false without a Google Health connection, or no main sleep that night
    start: datetime | None = None
    end: datetime | None = None
    staged: bool = False  # false for a "classic" night, which knows only asleep, restless, awake
    stages: list[SleepStage] = []


class CheckIn(ApiModel):
    day: date
    rating: int = Field(ge=1, le=5)
    tags: list[str] = []


class PulseToday(ApiModel):
    """The nightly team question for the signed-in person."""

    asked: bool  # in a team: only then is the question shown
    day: date
    question: str
    scale: list[str]  # the words for 1 to 5
    rating: int | None = None


class PulseAnswer(ApiModel):
    rating: int = Field(ge=1, le=5)


class PulseWeek(ApiModel):
    start: date
    end: date
    respondents: int
    mean: float | None = None  # only from at least `minimum` people


class TeamPulse(ApiModel):
    question: str
    minimum: int
    weeks: list[PulseWeek]  # oldest first


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
    hr_invite: str | None = Field(default=None, max_length=200)  # from an HR invitation link


class Account(ApiModel):
    email: str
    status: Literal["pending", "approved", "rejected"]
    is_admin: bool
    role: Literal["member", "supervisor", "hr"] = "member"
    # Whether this server has the individual side on (app/api/features.py); the app hides it if not.
    personal_features: bool = False


class SignedIn(ApiModel):
    token: str
    account: Account


class Approval(ApiModel):
    role: Literal["member", "supervisor", "hr"] = "member"


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
    hr_email: str | None = None  # the team's HR contact for check-in alerts
    hr_invited: str | None = None  # invited, not signed up yet
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
    checkin_alerts: bool = False  # the third consent (docs/escalation.md)
    checkin_consent: str = ""
    checkin_consent_version: str = ""


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


class BriefingItem(ApiModel):
    evidence_ids: list[str] = Field(default_factory=list)
    text: str
    kind: str
    metric: str | None = None


class TeamBriefing(ApiModel):
    """Weekly highlights and upcoming event warnings, each linked to the report evidence."""

    summary: str
    items: list[BriefingItem]
    proposals: int = 0  # team actions it proposed, waiting for approval
    made_at: datetime


class ChangeFigure(ApiModel):
    value: float
    unit: str | None = None
    text: str


class TeamFindingView(ApiModel):
    """A priority finding as the supervisor reads it, built by app.teams.view from computed fields:
    "Sustained change" or "New change", with the dates of its own fixed baseline."""

    label: str
    kind: str | None = None
    metric: str
    metric_label: str
    direction: str | None = None
    change: ChangeFigure
    target: Window | None = None
    weeks_running: int
    baseline: Window | None = None
    contributors: int | None = None
    moved_that_way: int | None = None
    roster: int
    why: str
    evidence_id: str


class TeamWeeklyView(ApiModel):
    """The weekly comparison's own label, dates and scoped summary."""

    label: str
    week: Window
    baseline: Window
    summary: str


class EvidenceCoverage(ApiModel):
    roster: int
    minimum: int
    contributors: int | None = None


class ScanWeekView(ApiModel):
    week: Window
    contributors: int
    change: ChangeFigure | None = None
    higher: int | None = None
    lower: int | None = None
    changed: bool


class EvidenceResult(ApiModel):
    change: ChangeFigure
    higher: int
    lower: int
    p_value: float | None = None


class TeamFindingEvidence(ApiModel):
    """One record of one team report, bounded: what was measured, its dates, method, the team
    figure and its coverage. Never a person's value or a quartile (app.teams.view)."""

    evidence_id: str
    report_week: Window
    metric: str
    metric_label: str
    unit: str | None = None
    label: str
    measured: str
    method: str
    target: Window | None = None
    scanned: Window | None = None  # a scan's four weeks; `target` is the weeks the change held
    baseline: Window | None = None
    coverage: EvidenceCoverage
    limitations: list[str]
    status: str | None = None
    weeks_running: int | None = None
    weeks: list[ScanWeekView] = Field(default_factory=list)
    result: EvidenceResult | None = None
    withheld: str | None = None


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
    briefing: TeamBriefing | None = None
    findings: list[TeamFindingView] = Field(default_factory=list)  # the priorities, labelled
    weekly: TeamWeeklyView | None = None  # what "metrics changed" is measured against


class GenerateReport(ApiModel):
    week: date | None = None  # any day of the week; the last full week when left out


# The supervisor's team agent


class TeamChatMessage(ApiModel):
    id: str
    role: Literal["supervisor", "agent"]
    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    rating: Literal["up", "down"] | None = None  # the supervisor's thumbs, on answers only
    created_at: datetime


class ChangeResult(ApiModel):
    """What followed an ended change: the team's metric during it against its reference days.

    `outcome` names the difference without a judgement, and `caveats` say what it cannot show
    (`app.teams.outcome`). `verdict` is the earlier judgement, kept for older app versions only;
    nothing new reads it."""

    outcome: Literal["above", "below", "no_clear_difference", "insufficient_data"]
    label: str
    reference: Window
    reference_label: str
    caveats: list[str]
    verdict: Literal["better", "worse", "changed", "no_change", "unclear"]
    text: str
    evidence: Evidence


class TeamAction(ApiModel):
    id: str
    kind: Literal["challenge", "message"]
    title: str
    body: str
    metric: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: Literal["proposed", "approved", "declined"]
    source: Literal["agent", "supervisor"] = "agent"
    play: str | None = None  # the playbook change it came from, or "custom"
    result: ChangeResult | None = None  # once an approved change has ended
    proposed_at: datetime
    decided_at: datetime | None = None


class TeamActionIn(ApiModel):
    """A change the supervisor plans: one from the playbook, or their own ("custom")."""

    play: str = Field(min_length=1, max_length=32)
    title: str | None = Field(default=None, max_length=80)
    body: str | None = Field(default=None, max_length=400)
    metric: str | None = None
    starts_on: date | None = None  # tomorrow when left out
    days: int | None = Field(default=None, ge=7, le=28)


class TeamPlay(ApiModel):
    id: str
    title: str
    body: str
    metrics: list[str]  # what it is meant for, the first measured by default
    days: int


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


# Check-in alerts (docs/escalation.md)


class CheckinEvidence(ApiModel):
    """One signal behind a person's own check-in alert; shown to that person only."""

    id: str
    metric: str
    direction: Literal["up", "down"]
    usual_low: float
    usual_high: float
    margin: float
    days_far: int
    days_worn: int
    recent_mean: float
    usual: Window
    recent: Window


class OwnCheckin(ApiModel):
    id: str
    team_id: str
    team: str
    status: Literal["waiting", "withdrawn", "sent"]
    raised_at: datetime
    send_after: datetime
    sent_at: datetime | None
    withdrawn_at: datetime | None
    recipients: str  # "your supervisor (…) and HR (…)"
    evidence: list[CheckinEvidence]


class CheckinMark(ApiModel):
    role: Literal["hr", "supervisor"]
    outcome: Literal["checked_in", "not_needed"] | None
    marked_at: datetime | None


class ReceivedCheckin(ApiModel):
    """A sent alert as HR or the supervisor sees it: who, which team, when; never why."""

    id: str
    person: str
    team: str
    sent_at: datetime
    mine: CheckinMark
    others: list[CheckinMark]
    note: str | None


class MarkCheckin(ApiModel):
    outcome: Literal["checked_in", "not_needed"]
    note: str | None = Field(default=None, max_length=500)


class ShareCheckin(ApiModel):
    share: bool
    consent_version: str | None = None  # needed to turn it on


class TeamHr(ApiModel):
    email: str | None  # None removes the HR contact
    invited: bool = False  # True: no HR account yet, so an invitation was emailed


# Calendar (app/sync/calendar.py): daily counts only, never events


class CalendarStatus(ApiModel):
    connected: bool  # the calendar scope was granted and the sign-in works
    last_sync: datetime | None
    last_error: str | None
    days: int


class CalendarDay(ApiModel):
    date: date
    meeting_minutes: float
    meetings: float
    after_hours_minutes: float
    back_to_back: float
    focus_minutes: float
    out_of_office: float


class TeamCalendarMetric(ApiModel):
    metric: str
    label: str
    unit: Literal["min", "count"]
    members: int  # members with a connected calendar who counted for it
    sufficient: bool  # False: fewer than the minimum, so no figures
    median_week: float | None = None  # per person, this week
    q1_week: float | None = None
    q3_week: float | None = None
    median_change: float | None = None  # against each person's own usual week
    members_up: int | None = None
    members_down: int | None = None
    median_planned: float | None = None  # next week, as planned so far
    evidence_id: str


class TeamCalendar(ApiModel):
    week: Window
    connected: int  # members with a connected calendar
    minimum_members: int
    metrics: list[TeamCalendarMetric]
    generated_at: datetime


class TeamObservedFigure(ApiModel):
    """What the team's latest night or day looked like; never a change from usual."""

    metric: str
    day: date
    median: float
    members: int  # at least the minimum, with a reading that day
    text: str  # "Median sleep last night: 7 h 10 min, based on 6 members."
    evidence_id: str


class TeamObserved(ApiModel):
    figures: list[TeamObservedFigure]
    minimum_members: int
