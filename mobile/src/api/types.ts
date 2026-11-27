// The contract between the app and the backend API.
// `Evidence` and `Window` mirror the backend models in backend/app/analysis/evidence.py.

export type ISODate = string; // "2026-10-19"
export type ISODateTime = string; // "2026-10-19T08:30:00Z"

export interface Window {
  start: ISODate;
  end: ISODate; // inclusive
}

export interface Evidence {
  id: string;
  tool: string; // "compare_windows", "trend", "correlate", ...
  metrics: string[];
  windows: Window[];
  n: number;
  sufficient: boolean; // false: too few days for the statistics to be trusted
  stats: Record<string, number | string | null | Record<string, unknown> | unknown[]>;
}

export interface Point {
  date: ISODate;
  value: number | null; // null on days without data
}

export type Direction = 'up' | 'down' | 'none';

export interface Finding {
  id: string;
  title: string; // "Sleep efficiency dropped"
  summary: string; // one or two sentences; every number in it comes from `evidenceIds`
  metric: string; // daily table column, e.g. "sleep_efficiency"
  unit: string; // "%", "min", "bpm"
  direction: Direction;
  change: string; // short label shown on the card, e.g. "-6%"
  series: Point[]; // the metric over the report's range, for the chart
  highlight?: Window; // the part of the series the finding is about
  evidenceIds: string[];
}

export interface ContextQuestion {
  id: string;
  prompt: string; // "Something changed around Sep 28. What was it?"
  date: ISODate;
  options: string[]; // ["Travel", "Work schedule", "Training", "Illness", "Nothing"]
  answer: string | null;
}

export interface Report {
  id: string;
  period: Window;
  createdAt: ISODateTime;
  headline: string;
  findings: Finding[];
  questions: ContextQuestion[];
  evidence: Record<string, Evidence>; // by id
}

export type ChatRole = 'user' | 'assistant';

/** The specialists that answer questions; each owns a set of metrics (docs/product.md). */
export type Expert = 'sleep' | 'recovery' | 'activity' | 'nutrition';

/** Who a question goes to: `auto` lets the router pick the expert. */
export type ExpertChoice = 'auto' | Expert;

/** How much work the expert may do: `deep` allows more tool calls and consulting other experts. */
export type Depth = 'quick' | 'deep';

/** Context the user attached to a question. */
/** The middle half of the 28 days before a day: what is usual for this person. */
export interface Usual {
  median: number;
  low: number; // 25th percentile
  high: number; // 75th percentile
  days: number;
}

export interface DayMetric {
  metric: string;
  value: number | null;
  usual: Usual | null; // null with fewer than 7 days to compare with
  recent: (number | null)[]; // the 14 days ending with this one, oldest first
}

/** One day's numbers, for Today. */
export interface DaySummary {
  date: ISODate;
  partial: boolean; // today, still filling in
  lowWear: boolean; // under 10 hours of wear: activity totals are not representative
  first: ISODate; // the days there is data for
  last: ISODate;
  metrics: DayMetric[];
  recovery?: Recovery | null; // our own estimate, with at least two of its three inputs
  strain?: Strain | null; // load from time in heart-rate zones (docs/scores.md)
  stress?: Stress | null; // with 4 hours of still, awake wear that day
}

/** Where last night's HRV, resting heart rate and sleep sit among the 28 days before (0–100). */
export interface Recovery {
  score: number;
  parts: Record<string, number>; // each input's share of the 28 days before that it beat
}

/** The day's load from minutes in Fitbit's heart-rate zones, on a 0–21 scale. */
export interface Strain {
  score: number;
  band: 'light' | 'moderate' | 'high' | 'all_out';
  load: number; // weighted zone minutes
  method: 'zones' | 'active_zone_minutes'; // the second is an estimate without zone minutes
}

/** Physical signs of stress against the 28 days before (0–100; 50 is a typical day). */
export interface Stress {
  score: number;
  parts: Record<string, number>; // each input's share of the 28 days before that it beat
}

/** A workout the tracker or an app recorded, with its summary. */
export interface Workout {
  id: string;
  exerciseType: string;
  name: string;
  start: ISODateTime;
  end: ISODateTime;
  activeSeconds: number | null;
  steps?: number | null;
  distanceKm?: number | null;
  caloriesKcal?: number | null;
  averageHeartRate?: number | null;
  activeZoneMinutes?: number | null;
  zoneSeconds?: Partial<Record<'light' | 'moderate' | 'vigorous' | 'peak', number>> | null;
  source?: string | null;
}

export interface DayWorkouts {
  available: boolean; // false without a Google Health connection
  workouts: Workout[];
}

export interface HourlySteps {
  available: boolean;
  steps: (number | null)[]; // 24 local hours
}

export type SleepStageKind = 'awake' | 'light' | 'deep' | 'rem' | 'asleep' | 'restless';

/** The night ending on a day, stage by stage (`asleep` and `restless` only on "classic" nights). */
export interface NightStages {
  available: boolean; // false without a Google Health connection or a main sleep that night
  start?: ISODateTime | null;
  end?: ISODateTime | null;
  staged?: boolean;
  stages: { start: ISODateTime; end: ISODateTime; stage: SleepStageKind }[];
}

/** A tester's note to the team: a report about one answer, or feedback on a chat. */
export interface FeedbackIn {
  kind: 'report' | 'feedback';
  text: string;
  conversationId?: string;
  messageId?: string; // a report is about one answer
}

export interface FeedbackRow {
  id: string;
  kind: 'report' | 'feedback';
  text: string;
  createdAt: string;
  quoted?: string | null; // the answer it is about, as it read
  email: string; // admins only: who wrote it
}

/** A spread of values: count, mean, median, 90th percentile and maximum (null when empty). */
export interface Spread {
  n: number;
  mean: number | null;
  median: number | null;
  p90: number | null;
  max: number | null;
}

/** The operations page (admins only): totals over the pilot's people, never one person. */
export interface OpsMetrics {
  period: { since: ISODate; until: ISODate; days: number };
  madeAt: string;
  people: {
    approved: number;
    withData: number;
    askedThisPeriod: number;
    waitingForApproval: number;
  };
  chat: {
    questions: number;
    answers: number;
    outcomes: Record<string, number>;
    successRate: number | null;
    refusalRate: number | null;
    latencyS: Spread;
    modelS: Spread;
    toolCalls: Spread;
    withToolErrors: number;
    rejectedClaims: number;
    questionTypes: Record<string, number>;
    costUsd: { total: number; perAnswer: Spread; perPersonPerDay: number | null };
    thumbs: { rated: number; up: number; down: number; upRate: number | null };
  };
  days: {
    day: ISODate;
    questions: number;
    answers: number;
    successRate: number | null;
    medianLatencyS: number | null;
    thumbsUp: number;
    thumbsDown: number;
    costUsd: number;
  }[];
  spend: {
    todayUsd: number;
    todayCapUsd: number;
    highestPersonTodayUsd: number;
    personCapUsd: number;
    peopleAtTheirCapToday: number;
    allTimeUsd: number;
    allTimeCapUsd: number;
  };
  accuracy: { claims: number; checked: number; agree: number; agreement: number | null };
  recall: { questionsChecked: number; changesFoundByKey: number; recall: number | null };
  syncs: {
    runs: number;
    successRate: number | null;
    seconds: Spread;
    connected: number;
    reconnectNeeded: number;
  };
  engagement: {
    checkIns: number;
    checkInRate: number | null;
    teamMembers: number;
    eveningAnswers: number;
    eveningRate: number | null;
  };
}

/** The nightly team question for the signed-in person (only shown to people in a team). */
export interface PulseToday {
  asked: boolean;
  day: ISODate;
  question: string;
  scale: string[]; // the words for 1 to 5
  rating: number | null;
}

/** A team's weekly pulse: a figure only from at least `minimum` people who answered that week. */
/** What the team's latest night or day looked like, from at least `minimumMembers` people with a
 * reading; shown from the first sync, never a change from usual. */
export interface TeamObservedFigure {
  metric: string;
  day: ISODate;
  median: number;
  members: number;
  text: string; // "Median sleep last night: 7 h 10 min, based on 6 members."
  evidenceId: string;
}

export interface TeamObserved {
  figures: TeamObservedFigure[];
  minimumMembers: number;
}

export interface TeamPulse {
  question: string;
  minimum: number;
  weeks: { start: ISODate; end: ISODate; respondents: number; mean: number | null }[];
}

export const CHECKIN_TAGS = [
  'hard_training',
  'alcohol',
  'late_meal',
  'stress',
  'travel',
  'feeling_sick',
] as const;

/** The morning "how do you feel?" rating, 1 to 5, with optional tags. */
export interface CheckIn {
  day: ISODate;
  rating: number;
  tags: (typeof CHECKIN_TAGS)[number][];
}

export interface MetricSeries {
  metric: string;
  points: Point[];
  usual: Usual | null; // before the last day
}

export type Attachment = { kind: 'finding'; id: string } | { kind: 'metric'; metric: string };

export interface SendOptions {
  expert: ExpertChoice;
  depth: Depth;
  attachment?: Attachment;
  conversationId?: string; // without one: the latest conversation
  replaces?: string; // editing or retrying: this question and what followed it are replaced
}

/** Where the person can check an answer's guidance; set by the server, never by the model. */
export interface SourceLink {
  title: string;
  source: string;
  url: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  sources?: SourceLink[];
  actionIds?: string[]; // owned logging drafts to review; never statistical evidence
  reminderIds?: string[]; // reminders the agent prepared here, each waiting for one tap
  evidenceIds: string[]; // what the assistant's statements are based on
  attachment?: Attachment; // what a user message asked about, if anything
  answeredBy?: Expert | 'general'; // assistant only; absent on refusals
  routed?: boolean; // assistant only: true if the router chose the expert, false if the user did
  consulted?: Expert[]; // other experts the answering expert asked
  refused?: boolean; // the request was out of scope, e.g. medical advice
  conversationId?: string;
  rating?: Rating; // assistant only: the person's thumbs, absent until given
  createdAt: ISODateTime;
}

/** Thumbs up or down on an answer; counted, never shown to anyone else. */
export type Rating = 'up' | 'down';

/** One of the person's chats. Memory is the person's, so every conversation shares it. */
export interface Conversation {
  id: string;
  title: string; // the first question until renamed
  pinned: boolean; // listed first
  messages: number;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
}

/** proposed: the agent prepared it and it waits for approval; done: a one-off already sent. */
export type ReminderStatus = 'proposed' | 'active' | 'paused' | 'declined' | 'done';
export type ReminderChannel = 'email' | 'in_app';

/** Local wall-clock times in the person's time zone; weekdays 0 (Monday) to 6 (Sunday). */
export type ReminderSchedule =
  | { kind: 'once'; date: ISODate; time: string } // "07:00"
  | { kind: 'weekly'; time: string; weekdays: number[] }; // all seven: every day

export interface Reminder {
  id: string;
  title: string; // "Wind down"
  message: string; // what the notification and email say
  schedule: ReminderSchedule;
  scheduleText: string; // "Weeknights at 22:30"
  timezone: string;
  channels: ReminderChannel[];
  status: ReminderStatus;
  source: 'person' | 'agent';
  reason: string | null; // why the agent suggested it
  evidenceId: string | null; // the computation behind that reason
  nextDueAt: ISODateTime | null; // null unless active
  version: number; // sent back with every change
  createdAt: ISODateTime;
}

export interface NewReminder {
  title: string;
  message: string;
  schedule: ReminderSchedule;
  channels: ReminderChannel[];
}

/** Approve (active), pause, resume (active), decline, or edit; always at the version shown. */
export interface ReminderChange {
  version: number;
  status?: 'active' | 'paused' | 'declined';
  title?: string;
  message?: string;
  schedule?: ReminderSchedule;
  channels?: ReminderChannel[];
}

export interface NotificationSettings {
  // For suggestions and smart alarms; your own reminders still come at the time you chose.
  quietHours: { start: string; end: string } | null; // "22:00".."07:00", local time; null = off
  maxPerDay: number; // 1-10
  email: boolean; // also send by email, where a reminder asks for it
}

/** One entry in the app's inbox: a reminder that came due (later, smart alarms too). */
export interface AppNotification {
  id: string;
  kind: string; // "reminder"
  title: string;
  body: string;
  link: string | null; // a path in the app, such as "/reminders"
  alarmId: string | null; // a smart alarm, which can be marked useful or not
  alarmFeedback: 'useful' | 'not_useful' | null;
  factId: string | null; // a memory the person may keep
  createdAt: ISODateTime;
  readAt: ISODateTime | null;
}

/** Something the person said about themselves. Used only once they chose to keep it. */
export interface MemoryFact {
  id: string;
  kind: 'routine' | 'goal' | 'preference' | 'context' | 'event' | 'commitment';
  text: string;
  status: 'candidate' | 'proposed' | 'approved';
  // 'forget': a card asking to forget the kept fact `forgets`; keeping the card deletes that fact.
  action: 'keep' | 'forget';
  forgets: string | null;
  start: ISODate | null; // an event's dates
  end: ISODate | null;
  createdAt: ISODateTime;
}

/** What Patterns holds about the person. */
export interface MemoryPage {
  waiting: MemoryFact[]; // to keep or decline
  kept: MemoryFact[];
  noticed: MemoryFact[]; // heard once and used for nothing; shown so nothing is hidden
  interests: { topic: string; label: string }[]; // strongest first
  episodes: { id: string; day: ISODate; text: string }[]; // newest first
}

/** Which smart alarms (alerts sent automatically from the data) the person wants. */
export type AlarmKind = 'day' | 'streak' | 'finding' | 'data';

export interface AlarmSettings {
  enabled: boolean;
  mutedKinds: AlarmKind[];
  sensitivity: 'fewer' | 'normal' | 'more';
}

export interface Inbox {
  items: AppNotification[]; // newest first, at most 50
  unread: number; // over all of them
}

export interface MetricCoverage {
  metric: string;
  label: string;
  fractionPresent: number; // 0..1 over the report period
}

export interface DataStatus {
  source: 'takeout' | 'google_health' | 'none';
  lastSync: ISODateTime | null;
  range: Window | null;
  coverage: MetricCoverage[];
  lowWearDays: ISODate[];
}

export type AccountStatus = 'pending' | 'approved' | 'rejected';

export interface Account {
  email: string;
  status: AccountStatus; // a sign-up waits for the owner's approval
  isAdmin: boolean; // may approve sign-ups
  role: 'member' | 'supervisor' | 'hr'; // supervisors create teams; HR gets check-in alerts
  personalFeatures: boolean; // the individual side is on for this server (docs/pivot.md)
}

export interface Credentials {
  email: string;
  password: string;
  hrInvite?: string; // from an HR invitation link: approved as that team's HR at once
}

export interface SignedIn {
  token: string; // sent as `Authorization: Bearer <token>`
  account: Account;
}

export interface AccessRequest {
  id: string;
  email: string;
  requestedAt: ISODateTime;
}

export interface GoogleStatus {
  status: 'none' | 'active' | 'reconnect_needed'; // reconnect: Google's sign-in expired
  syncing: boolean;
  lastSync: ISODateTime | null; // the last successful sync
  lastError: string | null; // why the latest sync failed, safe to show
  missingScopes: string[]; // permissions the person unticked on Google's page
}

/** What joining a team means, shown before the person agrees (docs/teams.md). */
export interface TeamPreview {
  team: string;
  supervisor: string; // their email: who will see the team's figures
  consent: string;
  consentVersion: string;
}

/** A team the person is in. Sharing their own weekly levels is a second, separate consent. */
export interface Membership {
  teamId: string;
  team: string;
  supervisor: string;
  joinedAt: ISODateTime;
  shareLevels: boolean;
  levelsConsent: string;
  levelsConsentVersion: string;
  checkinAlerts: boolean; // the third consent: check-in alerts (docs/escalation.md)
  checkinConsent: string;
  checkinConsentVersion: string;
}

/** One signal behind the person's own check-in alert; only that person sees it. */
export interface CheckinEvidence {
  id: string;
  metric: string;
  direction: 'up' | 'down';
  usualLow: number;
  usualHigh: number;
  margin: number;
  daysFar: number;
  daysWorn: number;
  recentMean: number;
  usual: Window;
  recent: Window;
}

/** The person's own check-in alert: told first, with 24 hours to stop it. */
export interface OwnCheckin {
  id: string;
  teamId: string;
  team: string;
  status: 'waiting' | 'withdrawn' | 'sent';
  raisedAt: ISODateTime;
  sendAfter: ISODateTime;
  sentAt: ISODateTime | null;
  withdrawnAt: ISODateTime | null;
  recipients: string;
  evidence: CheckinEvidence[];
}

export type CheckinOutcome = 'checked_in' | 'not_needed';

export interface CheckinMark {
  role: 'hr' | 'supervisor';
  outcome: CheckinOutcome | null;
  markedAt: ISODateTime | null;
}

/** The calendar: read-only, kept as daily counts, never events (backend/app/sync/calendar.py). */
export interface CalendarStatus {
  connected: boolean;
  lastSync: ISODateTime | null;
  lastError: string | null;
  days: number;
}

export interface CalendarDay {
  date: ISODate;
  meetingMinutes: number;
  meetings: number;
  afterHoursMinutes: number;
  backToBack: number;
  focusMinutes: number;
  outOfOffice: number;
}

/** One team calendar figure, built from at least `minimumMembers` people or not at all. */
export interface TeamCalendarMetric {
  metric: string;
  label: string;
  unit: 'min' | 'count';
  members: number;
  sufficient: boolean;
  medianWeek?: number | null; // per person, this week
  q1Week?: number | null;
  q3Week?: number | null;
  medianChange?: number | null; // against each person's own usual week
  membersUp?: number | null;
  membersDown?: number | null;
  medianPlanned?: number | null; // next week, as planned so far
  evidenceId: string;
}

export interface TeamCalendar {
  week: Window;
  connected: number; // members with a connected calendar
  minimumMembers: number;
  metrics: TeamCalendarMetric[];
  generatedAt: ISODateTime;
}

/** A personal access token for the MCP server (docs/mcp.md); the token itself is shown once. */
export interface AccessTokenInfo {
  id: string;
  name: string;
  createdAt: ISODateTime;
  lastUsedAt: ISODateTime | null;
  revokedAt: ISODateTime | null;
  activity?: { tool: string; calls: number; failed: number }[]; // the last 24 hours, never data
  signedIn?: boolean; // the assistant signed in (OAuth) instead of being given a pasted token
}

/** An assistant asking to sign in (OAuth), as the /connect page shows it (docs/mcp.md). */
export interface ConnectRequest {
  clientName: string; // the assistant's own claim
  redirectHost: string; // where the answer is sent: what the person should check
  expiresAt: ISODateTime;
}

export interface MadeAccessToken extends AccessTokenInfo {
  token: string; // shown once, never again
}

/** What a harness sent through MCP, held until the person approves it. */
export interface HarnessSubmission {
  id: string;
  kind: 'calendar_days' | 'team_event';
  status: 'pending' | 'approved' | 'declined';
  payload: Record<string, unknown>;
  teamId: string | null;
  createdAt: ISODateTime;
}

/** A sent alert as HR or the supervisor sees it: who, which team, when; never why. */
export interface ReceivedCheckin {
  id: string;
  person: string;
  team: string;
  sentAt: ISODateTime;
  mine: CheckinMark;
  others: CheckinMark[];
  note: string | null;
}

/** A supervisor's team: a count of members, never who they are. */
export interface SupervisedTeam {
  id: string;
  name: string;
  inviteCode: string;
  members: number;
  minimumMembers: number; // no team figure is built from fewer
  reportEmail: string | null;
  hrEmail?: string | null; // the team's HR contact for check-in alerts
  hrInvited?: string | null; // invited by email, not signed up yet
  paused?: string | null; // why its figures are paused: it differs from another team by too few
  createdAt: ISODateTime;
}

export interface TeamReportSummary {
  week: Window; // Monday to Sunday
  status: 'ready' | 'withheld'; // withheld: fewer people with data than the minimum
  headline: string;
  membersIncluded: number;
  createdAt: ISODateTime;
}

export interface ReportSection {
  metric: string;
  label?: string | null;
  status?: 'changed' | 'steady' | 'not_enough_data' | null;
  text: string;
  evidenceId: string;
}

export interface NarrativeParagraph {
  text: string;
  kind: 'change' | 'no_change' | 'pattern';
  metric: string;
  evidenceIds: string[];
}

export type TeamLevel = 'below' | 'usual' | 'above';

/** One member who chose to share: their week against their own usual, never against others. */
export interface SharedLevels {
  member: string;
  levels: Record<string, { mean: number | null; level: TeamLevel | null }>;
}

/** The supervisor's conversation with the team agent: team figures only, never a person. */
export interface TeamChatMessage {
  id: string;
  role: 'supervisor' | 'agent';
  text: string;
  evidence: Evidence[];
  rating?: Rating | null; // agent only: the supervisor's thumbs
  createdAt: ISODateTime;
}

/** What followed an ended change: the team's metric during it against its reference days, named
 * without a judgement. `caveats` say what it cannot show. */
export interface ChangeResult {
  outcome: 'above' | 'below' | 'no_clear_difference' | 'insufficient_data';
  label: string;
  reference: Window;
  referenceLabel: string;
  caveats: string[];
  /** The earlier judgement, kept for older app versions; not shown. */
  verdict: 'better' | 'worse' | 'changed' | 'no_change' | 'unclear';
  text: string;
  evidence: Evidence;
}

/** A team-wide change: suggested by the agent (waits for approval) or started by the supervisor
 * (approved as made). Nothing reaches members until it is approved. */
export interface TeamAction {
  id: string;
  kind: 'challenge' | 'message';
  title: string;
  body: string;
  metric: string | null;
  startsOn: ISODate | null;
  endsOn: ISODate | null;
  status: 'proposed' | 'approved' | 'declined';
  /** 'assistant': recorded through MCP from the supervisor's agreement in a chat. */
  source?: 'agent' | 'supervisor' | 'assistant';
  play?: string | null; // the playbook change it came from, or "custom"
  result?: ChangeResult | null; // once an approved change has ended
  proposedAt: ISODateTime;
  decidedAt: ISODateTime | null;
  /** What the supervisor reported once it started; null is unknown, never inferred. */
  implementation?: 'tried' | 'not_tried' | null;
  implementationAt?: ISODateTime | null;
  /** Tracked and how; null with no metric: not tracked, nothing measured. */
  comparison?: 'before_the_change' | 'observation_only' | null;
  observeStartsOn?: ISODate | null;
  observeEndsOn?: ISODate | null;
  eventId?: string | null;
}

/** A change from the playbook a supervisor can start. */
export interface TeamPlay {
  id: string;
  title: string;
  body: string;
  metrics: string[]; // what it is meant for, the first measured by default
  days: number;
}

/** A change the supervisor plans: a playbook one, or their own with play "custom". */
export interface PlanChange {
  play: string;
  title?: string;
  body?: string;
  metric?: string;
  startsOn?: ISODate; // tomorrow when left out
  days?: number; // 7 to 28
}

/** Something the supervisor told the agent about the team's work, such as a deadline. */
export type EventCategory =
  'deadline' | 'launch' | 'travel' | 'holiday' | 'reorganisation' | 'onboarding' | 'other';

export interface TeamNote {
  id: string;
  text: string;
  startsOn: ISODate | null;
  endsOn: ISODate | null;
  category?: EventCategory | null;
  createdAt: ISODateTime;
}

/** A change in a team aggregate, raised once; ended when it no longer holds. */
export interface TeamAlert {
  id: string;
  metric: string;
  label: string;
  direction: 'up' | 'down';
  kind: 'concern' | 'improvement' | 'change'; // good news waits for the weekly report
  text: string;
  raisedAt: ISODateTime;
  resolvedAt: ISODateTime | null;
}

/** What the week's report leads with: a worthwhile team change, concerns first. */
export interface ReportFinding {
  metric: string;
  label: string;
  kind: 'concern' | 'improvement' | 'change';
  status: 'lasting' | 'new';
  text: string;
  evidenceId: string;
}

export interface ChangeFigure {
  value: number;
  unit?: string | null;
  text: string; // as the supervisor reads it, e.g. "-46 min"
}

/**
 * A priority finding with its own comparison: "Sustained change" (the same way for weeks running)
 * or "New change", always against the fixed baseline its scan used. Built by the backend from
 * computed fields only (app.teams.view); the same as MCP's team_overview gives.
 */
export interface TeamFindingView {
  label: string;
  kind?: 'concern' | 'improvement' | 'change' | null;
  metric: string;
  metricLabel: string;
  direction?: string | null; // lower, higher, earlier, later
  change: ChangeFigure;
  target?: Window | null; // the weeks it held, ending with the report's week
  weeksRunning: number;
  baseline?: Window | null; // the fixed baseline it was measured against
  contributors?: number | null; // people with enough data in the latest week
  movedThatWay?: number | null;
  roster: number;
  why: string; // the rule that fired
  evidenceId: string;
}

/** What the weekly lines and "metrics changed" are measured against. */
export interface TeamWeeklyView {
  label: string; // "This week vs. the previous four weeks"
  week: Window;
  baseline: Window;
  summary: string;
}

/** One record of one team report, bounded: never a person's value or a quartile. */
export interface TeamFindingEvidence {
  evidenceId: string;
  reportWeek: Window;
  metric: string;
  metricLabel: string;
  unit?: string | null;
  label: string;
  measured: string;
  method: string;
  target?: Window | null; // for a scan, the weeks the change held
  scanned?: Window | null; // a scan's four weeks
  baseline?: Window | null;
  coverage: { roster: number; minimum: number; contributors?: number | null };
  limitations: string[];
  status?: string | null;
  weeksRunning?: number | null;
  weeks: {
    week: Window;
    contributors: number;
    change?: ChangeFigure | null;
    higher?: number | null;
    lower?: number | null;
    changed: boolean;
  }[];
  result?: { change: ChangeFigure; higher: number; lower: number; pValue?: number | null } | null;
  withheld?: string | null; // fewer than the minimum: why there is no figure
  // A team change's result only: its baseline's meaning and the outcome its card shows.
  baselineLabel?: string | null;
  outcome?: ChangeResult['outcome'] | null;
  outcomeLabel?: string | null;
}

/** What the team agent found on its own Monday run, every claim checked against team evidence. */
export interface TeamBriefing {
  summary: string;
  items: { text: string; kind: string; metric?: string | null; evidenceIds: string[] }[];
  proposals: number; // team actions it proposed, waiting for approval
  madeAt: ISODateTime;
}

export interface TeamReport extends TeamReportSummary {
  membersTotal: number;
  minimumMembers: number;
  priorities: ReportFinding[]; // in reading order: concerns, load and bedtime, then good news
  alerts: string[]; // raised during the week
  challenges: ReportSection[]; // approved challenges that ended, and whether they moved
  sections: ReportSection[];
  weekdays: ReportSection[];
  narrative: NarrativeParagraph[]; // the model's checked prose; empty when templated
  evidence: Record<string, Evidence>;
  generatedBy: 'template' | 'model';
  briefing?: TeamBriefing | null; // the team agent's Monday run, when it checked out
  levels: SharedLevels[];
  findings?: TeamFindingView[]; // the priorities, labelled with their own baseline
  weekly?: TeamWeeklyView | null; // what the weekly lines are measured against; none if withheld
}

export interface ApiClient {
  getActions(): Promise<HealthAction[]>;
  getAction(id: string): Promise<HealthAction>;
  proposeAction(requestKey: string, log: HealthLog): Promise<HealthAction>;
  reviseAction(id: string, version: number, log: HealthLog): Promise<HealthAction>;
  cancelAction(id: string, version: number): Promise<HealthAction>;
  confirmAction(id: string, version: number): Promise<HealthAction>;
  undoAction(id: string, version: number): Promise<HealthAction>;
  signUp(credentials: Credentials): Promise<SignedIn>;
  logIn(credentials: Credentials): Promise<SignedIn>;
  logOut(): Promise<void>;
  getAccount(): Promise<Account>;
  getAccessRequests(): Promise<AccessRequest[]>; // admins only
  decideAccessRequest(id: string, approve: boolean, role?: Account['role']): Promise<Account>; // admins only; role on approval, member by default
  getGoogleStatus(): Promise<GoogleStatus>;
  connectGoogle(
    capability?: 'food_logging' | 'workout_logging' | 'calendar',
  ): Promise<{ url: string }>; // Google's sign-in page; it returns to /settings
  // The app calls it by itself (open, focus, pull to refresh); the server starts a sync only when
  // the last one began over 10 minutes ago, unless `force` (Settings' "Sync now").
  syncGoogle(options?: { force?: boolean }): Promise<GoogleStatus>;
  disconnectGoogle(): Promise<GoogleStatus>; // the synced days are kept
  getLatestReport(): Promise<Report>;
  getDay(date: ISODate | 'latest'): Promise<DaySummary>;
  getWorkouts(date: ISODate): Promise<DayWorkouts>;
  getHourlySteps(date: ISODate): Promise<HourlySteps>;
  getSleepStages(date: ISODate): Promise<NightStages>;
  getCheckIn(date: ISODate): Promise<CheckIn | null>;
  saveCheckIn(checkIn: CheckIn): Promise<CheckIn>; // today only
  getPulse(): Promise<PulseToday>;
  savePulse(rating: number): Promise<PulseToday>; // today only
  getTeamPulse(teamId: string): Promise<TeamPulse>; // the last five full weeks, oldest first
  getTeamObserved(teamId: string): Promise<TeamObserved>; // supervisors: from the first sync
  getOpsMetrics(days: number): Promise<OpsMetrics>; // admins only
  sendFeedback(feedback: FeedbackIn): Promise<void>;
  getFeedback(): Promise<FeedbackRow[]>; // admins only, newest first
  getMetricSeries(metric: string, options: { end?: ISODate; days: number }): Promise<MetricSeries>;
  getEvidence(id: string): Promise<Evidence>; // any evidence a finding or chat answer cites
  answerQuestion(questionId: string, answer: string): Promise<ContextQuestion>;
  getChat(conversationId?: string): Promise<ChatMessage[]>; // without one: the latest used
  getConversations(): Promise<Conversation[]>; // most recently used first
  createConversation(): Promise<Conversation>;
  updateConversation(
    id: string,
    changes: { title?: string; pinned?: boolean },
  ): Promise<Conversation>;
  deleteConversation(id: string): Promise<void>;
  sendMessage(text: string, options: SendOptions): Promise<ChatMessage[]>; // returns the new messages
  rateAnswer(messageId: string, rating: Rating | null): Promise<ChatMessage>; // null takes it back
  getReminders(): Promise<Reminder[]>; // all but deleted ones, newest first
  createReminder(reminder: NewReminder): Promise<Reminder>; // active at once
  changeReminder(id: string, change: ReminderChange): Promise<Reminder>;
  deleteReminder(id: string): Promise<void>;
  getNotificationSettings(): Promise<NotificationSettings>;
  updateNotificationSettings(settings: NotificationSettings): Promise<NotificationSettings>;
  getNotifications(): Promise<Inbox>;
  readNotification(id: string): Promise<AppNotification>;
  readAllNotifications(): Promise<void>;
  setTimezone(timezone: string): Promise<void>; // the device's IANA zone; reminders follow it
  getAlarmSettings(): Promise<AlarmSettings>;
  updateAlarmSettings(settings: AlarmSettings): Promise<AlarmSettings>;
  sendAlarmFeedback(alarmId: string, useful: boolean): Promise<void>;
  getMemory(): Promise<MemoryPage>;
  decideMemory(id: string, keep: boolean): Promise<MemoryFact>;
  rewordMemory(id: string, text: string): Promise<MemoryFact>;
  forgetMemory(id: string): Promise<void>;
  noteOpened(topic: string): Promise<void>; // the person opened a metric's page
  muteInterest(topic: string): Promise<void>;
  forgetEpisode(id: string): Promise<void>;
  getDataStatus(): Promise<DataStatus>;
  previewTeam(code: string): Promise<TeamPreview>;
  joinTeam(code: string, consentVersion: string): Promise<Membership>;
  getMyTeams(): Promise<Membership[]>;
  shareTeamLevels(teamId: string, share: boolean, consentVersion?: string): Promise<Membership>;
  shareTeamCheckin(teamId: string, share: boolean, consentVersion?: string): Promise<Membership>;
  getMyCheckins(): Promise<OwnCheckin[]>;
  getCalendarStatus(): Promise<CalendarStatus>;
  getAccessTokens(): Promise<AccessTokenInfo[]>;
  makeAccessToken(name: string): Promise<MadeAccessToken>;
  revokeAccessToken(id: string): Promise<void>;
  getHarnessSubmissions(): Promise<HarnessSubmission[]>; // waiting for this person's approval
  decideHarnessSubmission(id: string, approve: boolean): Promise<HarnessSubmission>;
  getConnectRequest(id: string): Promise<ConnectRequest>;
  /** Allow or deny an assistant's sign-in; returns where to send the browser back to. */
  decideConnectRequest(id: string, allow: boolean): Promise<{ redirectTo: string }>;
  disconnectCalendar(): Promise<CalendarStatus>; // the calendar's sign-in only; days are kept
  getMyCalendar(): Promise<CalendarDay[]>;
  getTeamCalendar(teamId: string, week?: ISODate): Promise<TeamCalendar>; // supervisors
  sendCheckinNow(id: string): Promise<OwnCheckin>; // before the hour is up
  stopCheckin(id: string): Promise<OwnCheckin>; // this alert only; the switch stays on
  getReceivedCheckins(): Promise<ReceivedCheckin[]>; // HR and supervisors
  openCheckin(id: string): Promise<ReceivedCheckin>;
  markCheckin(id: string, outcome: CheckinOutcome, note?: string): Promise<ReceivedCheckin>;
  setTeamHr(
    teamId: string,
    email: string | null,
  ): Promise<{ email: string | null; invited: boolean }>; // supervisors: links an HR account, or emails an invitation
  leaveTeam(teamId: string): Promise<void>;
  getTeams(): Promise<SupervisedTeam[]>; // supervisors only
  createTeam(name: string): Promise<SupervisedTeam>;
  rotateTeamCode(teamId: string): Promise<SupervisedTeam>;
  getTeamReports(teamId: string): Promise<TeamReportSummary[]>; // newest first
  getTeamReport(teamId: string, week: ISODate): Promise<TeamReport>;
  getTeamEvidence(teamId: string, week: ISODate, evidenceId: string): Promise<TeamFindingEvidence>;
  makeTeamReport(teamId: string, week?: ISODate): Promise<TeamReport>; // the last full week
  getTeamChat(teamId: string): Promise<TeamChatMessage[]>; // oldest first
  rateTeamAnswer(
    teamId: string,
    messageId: string,
    rating: Rating | null,
  ): Promise<TeamChatMessage>;
  getTeamNotes(teamId: string): Promise<TeamNote[]>;
  addTeamNote(
    teamId: string,
    text: string,
    startsOn?: ISODate | null,
    endsOn?: ISODate | null,
  ): Promise<TeamNote>;
  deleteTeamNote(teamId: string, noteId: string): Promise<void>;
  getTeamAlerts(teamId: string): Promise<TeamAlert[]>; // newest first
  getTeamActions(teamId: string): Promise<TeamAction[]>; // newest first
  decideTeamAction(
    teamId: string,
    actionId: string,
    approve: boolean,
  ): Promise<{ membersTold: number; action: TeamAction }>;
  /** Did the team try it? null takes an answer back (unknown again). */
  setTeamImplementation(
    teamId: string,
    actionId: string,
    tried: boolean | null,
  ): Promise<TeamAction>;
  getTeamPlaybook(teamId: string): Promise<TeamPlay[]>;
  planTeamChange(
    teamId: string,
    change: PlanChange,
  ): Promise<{ membersTold: number; action: TeamAction }>;
}

export type HealthLog =
  | {
      kind: 'food';
      foodName: string;
      consumedAt: ISODateTime;
      mealType: 'BREAKFAST' | 'LUNCH' | 'DINNER' | 'SNACK';
      energyKcal?: number | null;
      proteinG?: number | null;
      carbohydrateG?: number | null;
      fatG?: number | null;
      provenance: 'user_entered' | 'estimated'; // estimated: from a food lookup, not the person
      estimateSource?: string | null;
    }
  | {
      kind: 'workout';
      exerciseType: string; // any of Google's ExerciseType values, such as TENNIS
      startTime: ISODateTime;
      endTime: ISODateTime;
      activeSeconds: number;
      distanceKm?: number | null;
      provenance: 'user_entered';
      measured?: TrackerReading | null; // added by the server; anything the app sends is replaced
    };

/** What the tracker recorded during a workout, read from Google by the server. */
export interface TrackerReading {
  status: 'measured' | 'no_data' | 'unavailable'; // no_data: not worn, or not synced yet
  steps?: number | null;
  distanceKm?: number | null;
  caloriesKcal?: number | null;
  averageHeartRate?: number | null;
  zoneSeconds?: { light: number; moderate: number; vigorous: number; peak: number } | null;
  activeZoneMinutes?: number | null;
  swimLengths?: number | null;
  overlaps?: {
    exerciseType: string;
    startTime: ISODateTime;
    endTime: ISODateTime;
  }[];
}

export type HealthActionStatus =
  'draft' | 'executing' | 'succeeded' | 'failed' | 'unknown' | 'cancelled' | 'undoing' | 'undone';

export interface HealthAction {
  id: string;
  version: number;
  status: HealthActionStatus;
  log: HealthLog;
  error: string | null;
  pendingOperation: 'create' | 'delete' | null;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
}
