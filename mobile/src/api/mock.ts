// In-memory stand-in for the backend, used until the API exists. All values are made up.
import { logSignature, validateLog } from '@/lib/actionLog';
import { expertForMetric } from '@/lib/experts';
import { shortDate } from '@/lib/format';
import { describeSchedule, nextDue, validTime } from '@/lib/reminders';

import { ApiError } from './http';
import { getToken } from './token';
import type {
  MemoryFact,
  AlarmSettings,
  AppNotification,
  AccessRequest,
  Account,
  ApiClient,
  Attachment,
  ChatMessage,
  CheckIn,
  ContextQuestion,
  Conversation,
  DataStatus,
  DayMetric,
  DaySummary,
  Depth,
  Evidence,
  Expert,
  Finding,
  GoogleStatus,
  HealthAction,
  HealthLog,
  ISODate,
  MetricSeries,
  NotificationSettings,
  Point,
  Reminder,
  Usual,
  Report,
  SendOptions,
  SignedIn,
  Strain,
  TeamPreview,
  Membership,
  SupervisedTeam,
  TeamReport,
} from './types';

const DAYS = 28;
const LATENCY_MS = 400;

function isoDate(daysAgo: number): ISODate {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() - daysAgo);
  return date.toISOString().slice(0, 10);
}

// Small deterministic PRNG so the charts look the same on every reload.
function random(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 2 ** 32;
    return state / 2 ** 32;
  };
}

function series(
  seed: number,
  base: number,
  noise: number,
  shift: number,
  shiftDay: number,
): Point[] {
  const next = random(seed);
  return Array.from({ length: DAYS }, (_, i) => {
    const daysAgo = DAYS - 1 - i;
    const value = base + (next() - 0.5) * 2 * noise + (daysAgo < shiftDay ? shift : 0);
    return { date: isoDate(daysAgo), value: Math.round(value * 10) / 10 };
  });
}

// A made-up daily history for Today: [metric, typical value, day-to-day spread, decimals].
const HISTORY_DAYS = 120;
const DAILY: [string, number, number, number][] = [
  ['sleep_minutes', 445, 40, 0],
  ['time_in_bed', 490, 40, 0],
  ['sleep_efficiency', 91, 3, 0],
  ['bedtime_hour', 0.6, 0.6, 2],
  ['deep_sleep_minutes', 78, 15, 0],
  ['light_sleep_minutes', 255, 30, 0],
  ['rem_sleep_minutes', 98, 18, 0],
  ['awake_in_bed_minutes', 45, 12, 0],
  ['steps', 9200, 2800, 0],
  ['calories', 2480, 260, 0],
  ['distance_km', 6.8, 2, 2],
  ['active_zone_minutes', 34, 18, 0],
  ['lightly_active_minutes', 210, 40, 0],
  ['moderately_active_minutes', 22, 10, 0],
  ['very_active_minutes', 18, 12, 0],
  ['resting_hr', 58, 2, 0],
  ['hrv_ms', 46, 7, 1],
  ['respiratory_rate', 14.6, 0.6, 1],
  ['skin_temp_variation_c', 0, 0.3, 1],
  ['wear_minutes', 1320, 60, 0],
  ['hr_zone_light_minutes', 820, 90, 0],
  ['hr_zone_moderate_minutes', 26, 12, 0],
  ['hr_zone_vigorous_minutes', 9, 7, 0],
  ['hr_zone_peak_minutes', 1, 1, 0],
  ['recovery_score', 62, 15, 0],
  ['strain', 9, 5, 1],
  ['stress_score', 50, 20, 0],
];

function dailyValue(metric: number, daysAgo: number): number {
  const [, base, spread, decimals] = DAILY[metric];
  const value = base + (random(metric * 7919 + daysAgo * 104729)() - 0.5) * 2 * spread;
  return Math.round(Math.max(0, value) * 10 ** decimals) / 10 ** decimals;
}

function daysAgoOf(date: ISODate): number {
  return Math.round((Date.parse(isoDate(0)) - Date.parse(date)) / 86_400_000);
}

// The same usual range as the backend: the middle half of the 28 days before, at least 7 days.
function quantile(sorted: number[], q: number): number {
  const position = (sorted.length - 1) * q;
  const below = Math.floor(position);
  const above = Math.min(below + 1, sorted.length - 1);
  return sorted[below] + (sorted[above] - sorted[below]) * (position - below);
}

function mockUsual(metric: number, daysAgo: number): Usual | null {
  const values = Array.from({ length: 28 }, (_, i) => daysAgo + 1 + i)
    .filter((ago) => ago < HISTORY_DAYS)
    .map((ago) => dailyValue(metric, ago))
    .sort((a, b) => a - b);
  if (values.length < 7) return null;
  const round = (v: number) => Math.round(v * 100) / 100;
  return {
    median: round(quantile(values, 0.5)),
    low: round(quantile(values, 0.25)),
    high: round(quantile(values, 0.75)),
    days: values.length,
  };
}

let checkIns: CheckIn[] = [];

function mockDay(date: ISODate): DaySummary {
  const ago = daysAgoOf(date);
  if (ago < 0 || ago >= HISTORY_DAYS) {
    throw new ApiError('There is no data for that day.', 'no_data', 404);
  }
  const metrics = DAILY.map<DayMetric>(([metric], index) => ({
    metric,
    value: dailyValue(index, ago),
    usual: mockUsual(index, ago),
    recent: Array.from({ length: 14 }, (_, i) => ago + 13 - i).map((a) =>
      a < HISTORY_DAYS ? dailyValue(index, a) : null,
    ),
  }));
  const valueOf = (name: string) => metrics.find((m) => m.metric === name)!.value!;
  return {
    date,
    partial: ago === 0,
    lowWear: false,
    first: isoDate(HISTORY_DAYS - 1),
    last: isoDate(0),
    metrics,
    recovery: { score: 64, parts: { hrv_ms: 71, resting_hr: 58, sleep_minutes: 63 } },
    strain: mockStrain(valueOf('strain')),
    stress: {
      score: valueOf('stress_score'),
      parts: { daytime_heart_rate: 62, hrv_ms: 48, resting_hr: 55, sleep_minutes: 51 },
    },
  };
}

/** The strain the backend would report for a score, with its band and the load behind it. */
function mockStrain(score: number): Strain {
  const band = score >= 18 ? 'all_out' : score >= 14 ? 'high' : score >= 10 ? 'moderate' : 'light';
  const load = Math.round(-200 * Math.log(1 - score / 21) * 10) / 10;
  return { score, band, load, method: 'zones' };
}

function mockSeries(metric: string, days: number, end?: ISODate): MetricSeries {
  const index = DAILY.findIndex(([name]) => name === metric);
  if (index === -1) throw new ApiError('There is no such metric.', 'unknown_metric', 404);
  const endAgo = Math.max(0, end ? daysAgoOf(end) : 0);
  return {
    metric,
    points: Array.from({ length: days }, (_, i) => endAgo + days - 1 - i).map((ago) => ({
      date: isoDate(ago),
      value: ago < HISTORY_DAYS ? dailyValue(index, ago) : null,
    })),
    usual: mockUsual(index, endAgo),
  };
}

const recent = { start: isoDate(13), end: isoDate(0) };
const baseline = { start: isoDate(27), end: isoDate(14) };

const evidence: Record<string, Evidence> = {
  ev_eff: {
    id: 'ev_eff',
    tool: 'compare_windows',
    metrics: ['sleep_efficiency'],
    windows: [recent, baseline],
    n: 27,
    sufficient: true,
    stats: {
      mean_recent: 86.1,
      mean_baseline: 91.6,
      difference: -5.5,
      pct_change: -6.0,
      cliffs_delta: -0.71,
      p_value: 0.0008,
    },
  },
  ev_bed: {
    id: 'ev_bed',
    tool: 'compare_windows',
    metrics: ['bedtime_hour'],
    windows: [recent, baseline],
    n: 27,
    sufficient: true,
    stats: {
      mean_recent: 0.4,
      mean_baseline: -0.45,
      difference: 0.85,
      cliffs_delta: 0.64,
      p_value: 0.002,
    },
  },
  ev_corr: {
    id: 'ev_corr',
    tool: 'correlate',
    metrics: ['bedtime_hour', 'sleep_efficiency'],
    windows: [{ start: isoDate(27), end: isoDate(0) }],
    n: 27,
    sufficient: true,
    stats: { lags_tested: 3, best_lag: 0, rho: -0.58, p_value: 0.0015, p_value_adjusted: 0.0045 },
  },
  ev_steps: {
    id: 'ev_steps',
    tool: 'trend',
    metrics: ['steps'],
    windows: [{ start: isoDate(27), end: isoDate(0) }],
    n: 28,
    sufficient: true,
    stats: {
      slope_per_day: 61.2,
      slope_low: 22.5,
      slope_high: 98.0,
      change_over_window: 1652,
      kendall_tau: 0.33,
      p_value: 0.013,
    },
  },
  ev_hrv: {
    id: 'ev_hrv',
    tool: 'compare_windows',
    metrics: ['hrv_ms'],
    windows: [recent, baseline],
    n: 26,
    sufficient: true,
    stats: {
      mean_recent: 48.2,
      mean_baseline: 55.9,
      difference: -7.7,
      pct_change: -13.8,
      cliffs_delta: -0.52,
      p_value: 0.011,
    },
  },
};

const findings: Finding[] = [
  {
    id: 'f_eff',
    title: 'Sleep efficiency dropped',
    summary:
      'Your sleep efficiency averaged 86% over the last two weeks, down from 92% the two weeks before.',
    metric: 'sleep_efficiency',
    unit: '%',
    direction: 'down',
    change: '-6%',
    series: series(1, 91.5, 2.5, -5.5, 14),
    highlight: recent,
    evidenceIds: ['ev_eff'],
  },
  {
    id: 'f_bed',
    title: 'Bedtime moved later',
    summary:
      'You went to bed about 50 minutes later on average, and later nights went with lower sleep efficiency.',
    metric: 'bedtime_hour',
    unit: 'h',
    direction: 'up',
    change: '+50 min',
    series: series(2, -0.45, 0.5, 0.85, 14),
    highlight: recent,
    evidenceIds: ['ev_bed', 'ev_corr'],
  },
  {
    id: 'f_steps',
    title: 'Steps trending up',
    summary:
      'Daily steps rose by about 60 a day over the last four weeks, around 1,650 more per day overall.',
    metric: 'steps',
    unit: 'steps',
    direction: 'up',
    change: '+1,650/day',
    series: series(3, 8200, 1400, 0, 0).map((point, i) => ({
      ...point,
      value: Math.round((point.value ?? 0) + i * 61),
    })),
    evidenceIds: ['ev_steps'],
  },
];

let questions: ContextQuestion[] = [
  {
    id: 'q_shift',
    prompt: `Your bedtime shifted around ${shortDate(isoDate(14))}. Did something change?`,
    date: isoDate(14),
    options: ['Travel', 'Work schedule', 'Exams', 'Training', 'Nothing'],
    answer: null,
  },
];

// Reminders, as the backend keeps them: the agent's suggestion waits for approval.
function mockReminder(
  fields: Pick<Reminder, 'id' | 'title' | 'message' | 'schedule' | 'status' | 'source'> &
    Partial<Reminder>,
): Reminder {
  const active = fields.status === 'active';
  return {
    channels: ['in_app', 'email'],
    reason: null,
    evidenceId: null,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    version: 1,
    createdAt: new Date().toISOString(),
    ...fields,
    scheduleText: describeSchedule(fields.schedule),
    nextDueAt: active ? (nextDue(fields.schedule)?.toISOString() ?? null) : null,
  };
}

let reminders: Reminder[] = [
  mockReminder({
    id: 'r_wind',
    title: 'Wind down',
    message: 'Time to start winding down for bed.',
    schedule: { kind: 'weekly', time: '23:00', weekdays: [0, 1, 2, 3, 4] },
    status: 'proposed',
    source: 'agent',
    reason: 'Later bedtimes went with lower sleep efficiency over the last four weeks.',
    evidenceId: null,
    channels: ['in_app'],
  }),
  mockReminder({
    id: 'r_stretch',
    title: 'Stretch',
    message: 'Ten minutes of stretching before dinner.',
    schedule: { kind: 'weekly', time: '18:30', weekdays: [0, 2, 4] },
    status: 'active',
    source: 'person',
  }),
];

let inbox: AppNotification[] = [
  {
    id: 'n_stretch',
    kind: 'reminder',
    title: 'Stretch',
    body: 'Ten minutes of stretching before dinner.',
    link: '/reminders',
    alarmId: null,
    alarmFeedback: null,
    factId: null,
    createdAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
    readAt: null,
  },
  {
    id: 'n_alarm',
    kind: 'alarm',
    title: 'Time asleep well below your usual',
    body: "Last night's time asleep sat well under your usual range of 6 h 50 min to 7 h 30 min.",
    link: '/reminders',
    alarmId: 'a_sleep',
    alarmFeedback: null,
    factId: null,
    createdAt: new Date(Date.now() - 40 * 60_000).toISOString(),
    readAt: null,
  },
];

// Made-up memory, shaped like the backend's: `waiting` and `kept` follow the person's taps.
let facts: MemoryFact[] = [
  {
    id: 'f_goal',
    kind: 'goal',
    text: 'Wants to be in bed earlier on weeknights',
    status: 'approved',
    start: null,
    end: null,
    createdAt: new Date(Date.now() - 12 * 86_400_000).toISOString(),
  },
  {
    id: 'f_exams',
    kind: 'event',
    text: 'Exams',
    status: 'proposed',
    start: isoDate(-3),
    end: isoDate(-8),
    createdAt: new Date(Date.now() - 3600_000).toISOString(),
  },
  {
    id: 'f_once',
    kind: 'routine',
    text: 'Trains on Tuesdays',
    status: 'candidate',
    start: null,
    end: null,
    createdAt: new Date(Date.now() - 3 * 86_400_000).toISOString(),
  },
];
let interests = [{ topic: 'bedtime_hour', label: 'bedtime' }];
let episodes = [
  { id: 'e_bed', day: isoDate(9), text: 'Later bedtimes went with lower sleep efficiency.' },
];

function factWith(id: string): MemoryFact {
  const found = facts.find((f) => f.id === id);
  if (!found) throw new ApiError('There is no such fact.', 'not_found', 404);
  return found;
}

let alarmSettings: AlarmSettings = { enabled: true, mutedKinds: [], sensitivity: 'normal' };

let chat: ChatMessage[] = [];

let notificationSettings: NotificationSettings = {
  quietHours: { start: '22:00', end: '07:00' },
  maxPerDay: 3,
  email: true,
};

/** Like the agent with `propose_reminder`: "remind me … at 22:30 …" becomes a proposal. */
function proposeReminder(text: string): Reminder | null {
  if (!/\bremind me\b/i.test(text)) return null;
  const clock = /\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b/i.exec(text);
  let hours = clock ? Number(clock[1]) % 24 : 22;
  if (clock?.[3]?.toLowerCase() === 'pm' && hours < 12) hours += 12;
  const time = `${String(hours).padStart(2, '0')}:${clock?.[2] ?? (clock ? '00' : '30')}`;
  const weekdays = /weeknight|weekday/i.test(text)
    ? [0, 1, 2, 3, 4]
    : /weekend/i.test(text)
      ? [5, 6]
      : [0, 1, 2, 3, 4, 5, 6];
  const what = /\bto (.+?)(?:\s+(?:at|every|on|tonight|tomorrow)\b|[.?!]|$)/i.exec(text)?.[1];
  const title = what ? what.charAt(0).toUpperCase() + what.slice(1, 60) : 'Reminder';
  const proposed = mockReminder({
    id: `r_${Date.now().toString(36)}`,
    title,
    message: what ? `Time to ${what}.` : '',
    schedule: { kind: 'weekly', time, weekdays },
    status: 'proposed',
    source: 'agent',
  });
  reminders = [proposed, ...reminders];
  return proposed;
}

function checkReminder(reminder: Pick<Reminder, 'title' | 'schedule' | 'channels'>) {
  if (!reminder.title.trim())
    throw new ApiError('A reminder needs a title.', 'invalid_reminder', 422);
  if (reminder.channels.length === 0) {
    throw new ApiError('Choose email, in the app, or both.', 'invalid_reminder', 422);
  }
  if (!validTime(reminder.schedule.time)) {
    throw new ApiError('That schedule is not valid.', 'invalid_reminder', 422);
  }
  if (reminder.schedule.kind === 'weekly' && reminder.schedule.weekdays.length === 0) {
    throw new ApiError('That schedule is not valid.', 'invalid_reminder', 422);
  }
  if (reminder.schedule.kind === 'once' && nextDue(reminder.schedule) === null) {
    throw new ApiError('That time has already passed.', 'in_the_past', 422);
  }
}

const MEDICAL =
  /\b(diagnos|disease|illness|sick|medic|medication|doctor|symptom|treat|apnea|afib|heart attack)/i;

// Stand-in for the router: keywords per expert. Ties go to the earlier expert in this list.
const TOPICS: [Expert, RegExp][] = [
  ['recovery', /recover|hrv|heart|resting|readiness|breath|respirat|temperature|tired/i],
  ['sleep', /sleep|bed|nap|\brem\b|deep|awake|efficien|night/i],
  ['activity', /step|walk|activ|exercise|workout|train|cardio|\brun|zone/i],
  ['nutrition', /\beat|food|meal|protein|carb|macro|nutri|diet/i],
];

/** Experts a question is about, most likely first. */
export function routeQuestion(text: string): Expert[] {
  return TOPICS.map(([expert, pattern]) => ({
    expert,
    hits: text.match(new RegExp(pattern.source, 'gi'))?.length ?? 0,
  }))
    .filter(({ hits }) => hits > 0)
    .sort((a, b) => b.hits - a.hits)
    .map(({ expert }) => expert);
}

function attachmentExpert(attachment: Attachment | undefined): Expert | undefined {
  if (!attachment) return undefined;
  const metric =
    attachment.kind === 'metric'
      ? attachment.metric
      : findings.find((f) => f.id === attachment.id)?.metric;
  return metric ? expertForMetric(metric) : undefined;
}

type Answer = Pick<ChatMessage, 'text' | 'evidenceIds'>;

function answerAbout(topic: Expert, depth: Depth, consulted: Expert[]): Answer {
  if (topic === 'sleep') {
    return depth === 'deep'
      ? {
          text: 'Sleep efficiency fell from 92% to 86% between the two halves of the last four weeks. Over the same period your bedtime moved about 50 minutes later, and nights with later bedtimes had lower efficiency. That is a correlation in your data, not proof that bedtime is the cause.',
          evidenceIds: ['ev_eff', 'ev_bed', 'ev_corr'],
        }
      : {
          text: 'Sleep efficiency fell from 92% to 86% over the last two weeks, while your bedtime moved about 50 minutes later.',
          evidenceIds: ['ev_eff', 'ev_bed'],
        };
  }
  if (topic === 'recovery') {
    const answer = {
      text: 'Your HRV averaged 48 ms over the last two weeks, down from 56 ms in the two weeks before.',
      evidenceIds: ['ev_hrv'],
    };
    if (consulted.includes('sleep')) {
      answer.text +=
        ' Over the same weeks your bedtime moved about 50 minutes later. Both changed together; the data does not show which caused which.';
      answer.evidenceIds.push('ev_bed');
    }
    return answer;
  }
  if (topic === 'activity') {
    return {
      text: 'Your steps have been rising steadily, by about 60 a day over four weeks, which adds up to around 1,650 more steps per day.',
      evidenceIds: ['ev_steps'],
    };
  }
  return {
    text: "I can't see any nutrition data yet. Once nutrition from Cronometer is imported, I can look at it alongside your sleep and activity.",
    evidenceIds: [],
  };
}

function reply(text: string, options: SendOptions): Omit<ChatMessage, 'id' | 'createdAt'> {
  // The scope check runs whatever expert was chosen, so choosing one cannot skip it.
  if (MEDICAL.test(text)) {
    return {
      role: 'assistant',
      text: "I can describe patterns in your Fitbit data, but I can't diagnose or give medical advice. For health concerns, please talk to a doctor.",
      evidenceIds: [],
      refused: true,
    };
  }
  // An attachment decides the topic; otherwise the question's keywords do.
  const fromAttachment = attachmentExpert(options.attachment);
  const topics = fromAttachment ? [fromAttachment] : routeQuestion(text);
  const chosen = options.expert === 'auto' ? undefined : options.expert;
  const lead = chosen ?? topics[0];

  if (!lead) {
    return {
      role: 'assistant',
      text: 'I can look into trends, changes between periods, and how your metrics relate, for example sleep, activity, heart rate or recovery. What would you like to know?',
      evidenceIds: [],
      answeredBy: 'general',
      routed: true,
    };
  }
  // The lead consults the other experts the question touches; a quick answer consults none.
  const consulted = options.depth === 'deep' ? topics.filter((t) => t !== lead) : [];
  // A chosen expert asked about another expert's metrics answers with what it consulted.
  const topic = chosen && topics.length > 0 && !topics.includes(chosen) ? topics[0] : lead;
  if (topic !== lead && !consulted.includes(topic)) consulted.push(topic);
  const unavailable = lead === 'nutrition';
  return {
    role: 'assistant',
    ...answerAbout(topic, options.depth, consulted),
    answeredBy: unavailable ? 'general' : lead,
    routed: !chosen,
    ...(consulted.length > 0 && { consulted }),
  };
}

function delay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), LATENCY_MS));
}

// Like the backend: each chat is a conversation, named by its first question until renamed.
const NEW_CHAT = 'New chat';
let conversations: Conversation[] = [];
let nextConversation = 0;

function conversationTitle(text: string): string {
  const title = text.split(/\s+/).filter(Boolean).join(' ') || NEW_CHAT;
  return title.length <= 60 ? title : `${title.slice(0, 59).trimEnd()}…`;
}

function newConversation(): Conversation {
  const now = new Date().toISOString();
  const conversation = {
    id: `c${++nextConversation}`,
    title: NEW_CHAT,
    pinned: false,
    messages: 0,
    createdAt: now,
    updatedAt: now,
  };
  conversations = [...conversations, conversation];
  return { ...conversation };
}

function latestConversation(): Conversation | undefined {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0];
}

let nextMessage = 0;

function message(fields: Omit<ChatMessage, 'id' | 'createdAt'>): ChatMessage {
  // Counted, not from the length: ids must stay unique after messages are replaced.
  return { ...fields, id: `m${++nextMessage}`, createdAt: new Date().toISOString() };
}

// Accounts work like the backend's: sign-ups wait for approval, and the made-up demo owner can
// sign in and approve them.
export const DEMO_OWNER = { email: 'demo@patterns.app', password: 'demo-password' };
export const DEMO_SUPERVISOR = { email: 'lead@patterns.app', password: 'demo-password' };

interface MockAccount extends Account {
  id: string;
  password: string;
  requestedAt: string;
  hasData: boolean; // false until they connect Google Health, as for someone without a Fitbit
}

let accounts: MockAccount[] = [
  {
    id: 'u1',
    ...DEMO_OWNER,
    status: 'approved',
    isAdmin: true,
    role: 'member',
    requestedAt: new Date().toISOString(),
    hasData: true,
  },
  {
    id: 'u0',
    ...DEMO_SUPERVISOR,
    status: 'approved',
    isAdmin: false,
    role: 'supervisor',
    requestedAt: new Date().toISOString(),
    hasData: false, // a supervisor without a Fitbit (docs/teams.md)
  },
];
const sessions = new Map<string, string>(); // token -> account id

function publicAccount({ email, status, isAdmin, role }: MockAccount): Account {
  return { email, status, isAdmin, role };
}

function signedIn(account: MockAccount): SignedIn {
  const token = `mock-token-${sessions.size + 1}-${Math.random().toString(36).slice(2)}`;
  sessions.set(token, account.id);
  return { token, account: publicAccount(account) };
}

function currentAccount(): MockAccount {
  const id = sessions.get(getToken() ?? '');
  const account = accounts.find((a) => a.id === id);
  if (!account) throw new ApiError('Sign in to continue.', 'signed_out', 401);
  return account;
}

/** Like the backend: someone signed in without synced data has none to show. */
function ownData(): void {
  const account = accounts.find((a) => a.id === sessions.get(getToken() ?? ''));
  if (account && !account.hasData) {
    throw new ApiError('Your Fitbit data is not connected yet.', 'no_data', 404);
  }
}

function adminAccount(): MockAccount {
  const account = currentAccount();
  if (!account.isAdmin) throw new ApiError("Only the app's owner can do this.", 'forbidden', 403);
  return account;
}

/** Waits like a network call, then runs `action`; a thrown error becomes a rejection. */
async function later<T>(action: () => T): Promise<T> {
  await delay(null);
  return structuredClone(action());
}

let google: GoogleStatus = {
  status: 'none',
  syncing: false,
  lastSync: null,
  lastError: null,
  missingScopes: [],
};

const RESYNC_AFTER_MS = 10 * 60 * 1000;

function startMockSync() {
  google = { ...google, syncing: true };
  setTimeout(() => {
    google = { ...google, syncing: false, lastSync: new Date().toISOString() };
  }, 3000);
}

// A made-up tracker reading, as the server would add it: never what the app sent.
function withMockReading(log: HealthLog): HealthLog {
  if (log.kind !== 'workout') return log;
  const minutes = log.activeSeconds / 60;
  return {
    ...log,
    measured: {
      status: 'measured',
      steps: Math.round(minutes * 100),
      distanceKm: Math.round(minutes * 0.08 * 100) / 100,
      caloriesKcal: Math.round(minutes * 5),
      averageHeartRate: 110,
      overlaps: [],
    },
  };
}

function withoutReading(log: HealthLog): HealthLog {
  if (log.kind !== 'workout') return log;
  const { measured: _, ...given } = log;
  return given;
}

const logDrafts: { owner: string; requestKey: string; first: string; action: HealthAction }[] = [];
let nextDraft = 0;

function actionAccount() {
  const account = currentAccount();
  if (account.status !== 'approved')
    throw new ApiError('Your account is waiting for approval.', 'not_approved', 403);
  return account;
}

function ownedDraft(id: string, version?: number) {
  const owner = actionAccount().id;
  const record = logDrafts.find((d) => d.owner === owner && d.action.id === id);
  if (!record) throw new ApiError('No such logging draft.', 'not_found', 404);
  if (version !== undefined && record.action.version !== version)
    throw new ApiError('This draft changed. Review it again.', 'stale_action', 409);
  return record;
}

function transition(id: string, version: number, from: string[], to: HealthAction['status']) {
  const record = ownedDraft(id, version);
  if (!from.includes(record.action.status))
    throw new ApiError('This action is no longer available.', 'stale_action', 409);
  record.action = { ...record.action, status: to, updatedAt: new Date().toISOString() };
  return { ...record.action, log: { ...record.action.log } };
}

// One made-up team to join with the code DEMO2345, worded like the backend's consent texts.
const MOCK_TEAM = { id: 't1', name: 'Design', code: 'DEMO2345', supervisor: 'lead@patterns.app' };
const MOCK_CONSENT = {
  consent:
    "Your supervisor will see weekly figures about the whole team: how its sleep, activity, recovery, strain and stress changed, each built from at least 5 people. They will not see your name, your own values, your days, your chats or anything else from your account, and they will not see whether you joined. You can leave at any time in Settings; from then on your data is left out of the team's figures.",
  consentVersion: 'teams-v1',
  levelsConsent:
    "Your supervisor will also see your name with your own weekly recovery, sleep, strain and stress, each as below, within or above your own usual range and as the week's average. Nothing else: no days, no other metrics, no chats. You can turn this off at any time; your row then disappears, including from past weeks.",
  levelsConsentVersion: 'team-levels-v1',
};
let myTeams: Membership[] = [];

function mockTeam(code: string) {
  if (code.toUpperCase().replace(/[^A-Z0-9]/g, '') !== MOCK_TEAM.code) {
    throw new ApiError(
      'No team has this code. Check it with your supervisor.',
      'unknown_code',
      404,
    );
  }
  return MOCK_TEAM;
}

function ownMembership(teamId: string): Membership {
  const membership = myTeams.find((m) => m.teamId === teamId);
  if (!membership) throw new ApiError('You are not in this team.', 'not_found', 404);
  return membership;
}

// A supervisor's view: teams created in this session, and a made-up report for the last full
// week, aggregates only, as the backend would make it.
let supervisedTeams: SupervisedTeam[] = [];
const teamReports = new Map<string, TeamReport[]>();

function supervisorAccount(): MockAccount {
  const account = currentAccount();
  if (account.role !== 'supervisor') {
    throw new ApiError('Only supervisors can do this.', 'not_supervisor', 403);
  }
  return account;
}

function ownTeam(teamId: string): SupervisedTeam {
  supervisorAccount();
  const team = supervisedTeams.find((t) => t.id === teamId);
  if (!team) throw new ApiError('No such team.', 'not_found', 404);
  return team;
}

function newCode(): string {
  const alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  return Array.from({ length: 8 }, () => alphabet[Math.floor(Math.random() * 31)]).join('');
}

/** Monday of the week before the current one. */
function lastFullWeek(): ISODate {
  const today = new Date(`${isoDate(0)}T00:00:00Z`);
  const monday = new Date(today);
  monday.setUTCDate(today.getUTCDate() - ((today.getUTCDay() + 6) % 7) - 7);
  return monday.toISOString().slice(0, 10);
}

function mockReport(team: SupervisedTeam, start: ISODate): TeamReport {
  const end = new Date(Date.parse(`${start}T00:00:00Z`) + 6 * 86_400_000)
    .toISOString()
    .slice(0, 10);
  // A section and the aggregate evidence it cites, as the backend stores them.
  const evidence: Record<string, Evidence> = {};
  const change = (
    metric: string,
    label: string,
    median: number,
    shown: string,
    up: number,
    down: number,
    changed = false,
  ) => {
    const id = `e_${metric}`;
    evidence[id] = {
      id,
      tool: 'team_change',
      metrics: [metric],
      windows: [],
      n: 8,
      sufficient: true,
      stats: { members: 8, median_change: median, members_up: up, members_down: down },
    };
    const who = `${up} of 8 higher, ${down} lower`;
    const text = changed
      ? `${label} ${median > 0 ? 'rose' : 'fell'} across the team: median change ${shown} (${who}).`
      : `${label}: no clear change for the team (median ${shown}; ${who}).`;
    return { metric, label, status: changed ? 'changed' : 'steady', text, evidenceId: id } as const;
  };
  evidence.e_weekday_sleep = {
    id: 'e_weekday_sleep',
    tool: 'team_weekday',
    metrics: ['sleep_minutes'],
    windows: [],
    n: 8,
    sufficient: true,
    stats: {
      members: 8,
      median_deviation_by_weekday: {
        monday: -6,
        tuesday: -11,
        wednesday: -19,
        thursday: -8,
        friday: 4,
        saturday: 31,
        sunday: 22,
      },
    },
  };
  evidence.e_weekday_steps = {
    id: 'e_weekday_steps',
    tool: 'team_weekday',
    metrics: ['steps'],
    windows: [],
    n: 8,
    sufficient: true,
    stats: {
      members: 8,
      median_deviation_by_weekday: {
        monday: 420,
        tuesday: 610,
        wednesday: 380,
        thursday: 150,
        friday: -240,
        saturday: -1310,
        sunday: -890,
      },
    },
  };
  return {
    week: { start, end },
    status: 'ready',
    headline:
      "This week the team's time asleep fell and recovery fell against the four weeks before; the rest held steady.",
    membersIncluded: 8,
    membersTotal: 8,
    minimumMembers: 5,
    createdAt: new Date().toISOString(),
    generatedBy: 'model',
    narrative: [
      {
        text: 'Time asleep went down, with a median change of -38 min; 7 of 8 people were lower.',
        kind: 'change',
        metric: 'sleep_minutes',
        evidenceIds: ['e_sleep_minutes'],
      },
      {
        text: 'Recovery went down, with a median change of -9; 6 of 8 people were lower.',
        kind: 'change',
        metric: 'recovery_score',
        evidenceIds: ['e_recovery_score'],
      },
    ],
    sections: [
      change('sleep_minutes', 'Time asleep', -38, '-38 min', 1, 7, true),
      change('bedtime_hour', 'Bedtime', 0.2, '+12 min', 5, 3),
      change('steps', 'Steps', -310, '-310 steps', 3, 5),
      change('active_zone_minutes', 'Active Zone Minutes', 2.5, '+2.5 min', 5, 3),
      change('resting_hr', 'Resting heart rate', 0.4, '+0.4 bpm', 4, 4),
      change('hrv_ms', 'Heart rate variability', -1.8, '-1.8 ms', 3, 5),
      change('recovery_score', 'Recovery', -9, '-9.0', 2, 6, true),
      change('strain', 'Strain', 0.4, '+0.4', 5, 3),
      change('stress_score', 'Stress', 3, '+3.0', 5, 3),
    ],
    weekdays: [
      {
        metric: 'sleep_minutes',
        text: "Time asleep by weekday: highest on Saturdays (+31 min against each person's usual), lowest on Wednesdays (-19 min).",
        evidenceId: 'e_weekday_sleep',
      },
      {
        metric: 'steps',
        text: "Steps by weekday: highest on Tuesdays (+610 steps against each person's usual), lowest on Saturdays (-1,310 steps).",
        evidenceId: 'e_weekday_steps',
      },
    ],
    evidence,
    levels: [
      {
        member: 'maya@example.com',
        levels: {
          recovery_score: { mean: 58, level: 'below' },
          sleep_minutes: { mean: 402, level: 'below' },
          strain: { mean: 8.1, level: 'usual' },
          stress_score: { mean: 61, level: 'above' },
        },
      },
      {
        member: 'omar@example.com',
        levels: {
          recovery_score: { mean: 71, level: 'usual' },
          sleep_minutes: { mean: 447, level: 'usual' },
          strain: { mean: 12.4, level: 'above' },
          stress_score: { mean: 47, level: 'usual' },
        },
      },
      {
        member: 'lina@example.com',
        levels: {
          recovery_score: { mean: 66, level: 'usual' },
          sleep_minutes: { mean: 391, level: 'below' },
          strain: { mean: null, level: null },
          stress_score: { mean: 38, level: 'below' },
        },
      },
    ],
  };
}

export const mockClient: ApiClient = {
  getTeams: () =>
    later(() => {
      supervisorAccount();
      return supervisedTeams;
    }),
  createTeam: (name) =>
    later<SupervisedTeam>(() => {
      supervisorAccount();
      const team: SupervisedTeam = {
        id: `team${supervisedTeams.length + 1}`,
        name: name.trim(),
        inviteCode: newCode(),
        members: 8,
        minimumMembers: 5,
        reportEmail: null,
        createdAt: new Date().toISOString(),
      };
      supervisedTeams = [...supervisedTeams, team];
      return team;
    }),
  rotateTeamCode: (teamId) =>
    later(() => {
      const team = ownTeam(teamId);
      team.inviteCode = newCode();
      return team;
    }),
  getTeamReports: (teamId) =>
    later(() => {
      ownTeam(teamId);
      return (teamReports.get(teamId) ?? []).map(
        ({ week, status, headline, membersIncluded, createdAt }) => ({
          week,
          status,
          headline,
          membersIncluded,
          createdAt,
        }),
      );
    }),
  getTeamReport: (teamId, week) =>
    later(() => {
      ownTeam(teamId);
      const found = (teamReports.get(teamId) ?? []).find(
        (r) => r.week.start <= week && week <= r.week.end,
      );
      if (!found) throw new ApiError('There is no report for that week.', 'not_found', 404);
      return found;
    }),
  makeTeamReport: (teamId) =>
    later(() => {
      const team = ownTeam(teamId);
      const start = lastFullWeek();
      const existing = teamReports.get(teamId) ?? [];
      const found = existing.find((r) => r.week.start === start);
      if (found) return found;
      const report = mockReport(team, start);
      teamReports.set(teamId, [report, ...existing]);
      return report;
    }),
  previewTeam: (code) =>
    later<TeamPreview>(() => {
      const team = mockTeam(code);
      return {
        team: team.name,
        supervisor: team.supervisor,
        consent: MOCK_CONSENT.consent,
        consentVersion: MOCK_CONSENT.consentVersion,
      };
    }),
  joinTeam: (code, consentVersion) =>
    later<Membership>(() => {
      const team = mockTeam(code);
      if (consentVersion !== MOCK_CONSENT.consentVersion) {
        throw new ApiError(
          'What joining means has changed. Read it again.',
          'consent_changed',
          409,
        );
      }
      if (myTeams.some((m) => m.teamId === team.id)) {
        throw new ApiError('You are already in this team.', 'already_member', 409);
      }
      const membership: Membership = {
        teamId: team.id,
        team: team.name,
        supervisor: team.supervisor,
        joinedAt: new Date().toISOString(),
        shareLevels: false,
        levelsConsent: MOCK_CONSENT.levelsConsent,
        levelsConsentVersion: MOCK_CONSENT.levelsConsentVersion,
      };
      myTeams = [...myTeams, membership];
      return membership;
    }),
  getMyTeams: () => later(() => myTeams),
  shareTeamLevels: (teamId, share, consentVersion) =>
    later<Membership>(() => {
      const membership = ownMembership(teamId);
      if (share && consentVersion !== membership.levelsConsentVersion) {
        throw new ApiError('Read what sharing your levels means first.', 'consent_changed', 409);
      }
      membership.shareLevels = share;
      return membership;
    }),
  leaveTeam: (teamId) =>
    later(() => {
      ownMembership(teamId);
      myTeams = myTeams.filter((m) => m.teamId !== teamId);
    }),
  getActions: () =>
    later(() => {
      const owner = actionAccount().id;
      return logDrafts
        .filter((d) => d.owner === owner)
        .map((d) => ({ ...d.action, log: { ...d.action.log } }));
    }),
  getAction: (id) =>
    later(() => {
      const { action } = ownedDraft(id);
      return { ...action, log: { ...action.log } };
    }),
  proposeAction: (requestKey, given) =>
    later(() => {
      const log = withMockReading(given);
      validateLog(log);
      const owner = actionAccount().id;
      const existing = logDrafts.find((d) => d.owner === owner && d.requestKey === requestKey);
      if (existing) {
        if (existing.first !== JSON.stringify(withoutReading(log)))
          throw new ApiError('Request key already used.', 'request_conflict', 409);
        return { ...existing.action, log: { ...existing.action.log } };
      }
      if (
        logDrafts.some(
          (d) =>
            d.owner === owner &&
            !['cancelled', 'undone'].includes(d.action.status) &&
            logSignature(d.action.log) === logSignature(log),
        )
      )
        throw new ApiError(
          'This entry already has a draft or a logged record.',
          'duplicate_log',
          409,
        );
      const now = new Date().toISOString();
      const action: HealthAction = {
        id: `draft_${++nextDraft}`,
        version: 1,
        status: 'draft',
        log: { ...log },
        error: null,
        pendingOperation: null,
        createdAt: now,
        updatedAt: now,
      };
      logDrafts.push({ owner, requestKey, first: JSON.stringify(withoutReading(log)), action });
      return { ...action, log: { ...action.log } };
    }),
  reviseAction: (id, version, given: HealthLog) =>
    later(() => {
      const log = withMockReading(given);
      validateLog(log);
      const record = ownedDraft(id, version);
      if (log.kind !== record.action.log.kind)
        throw new ApiError('Start a new draft to change the log type.', 'invalid_log', 422);
      if (
        logDrafts.some(
          (d) =>
            d.owner === record.owner &&
            d.action.id !== id &&
            !['cancelled', 'undone'].includes(d.action.status) &&
            logSignature(d.action.log) === logSignature(log),
        )
      )
        throw new ApiError(
          'This entry already has a draft or a logged record.',
          'duplicate_log',
          409,
        );
      transition(id, version, ['draft', 'failed'], 'draft');
      record.action = { ...record.action, log: { ...log }, version: version + 1, error: null };
      return { ...record.action, log: { ...record.action.log } };
    }),
  cancelAction: (id, version) =>
    later(() => transition(id, version, ['draft', 'failed'], 'cancelled')),
  confirmAction: (id, version) =>
    later(() => transition(id, version, ['draft', 'succeeded'], 'succeeded')),
  undoAction: (id, version) =>
    later(() => transition(id, version, ['succeeded', 'undone'], 'undone')),
  signUp: ({ email, password }) =>
    later(() => {
      const normalized = email.trim().toLowerCase();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(normalized)) {
        throw new ApiError('Enter a valid email address.', 'invalid_email', 422);
      }
      if (password.length < 10) {
        throw new ApiError('Use a password of at least 10 characters.', 'weak_password', 422);
      }
      if (accounts.some((a) => a.email === normalized)) {
        throw new ApiError('An account with this email already exists.', 'email_taken', 409);
      }
      const account: MockAccount = {
        id: `u${accounts.length + 1}`,
        email: normalized,
        password,
        status: 'pending',
        isAdmin: false,
        role: 'member',
        requestedAt: new Date().toISOString(),
        hasData: false,
      };
      accounts = [...accounts, account];
      return signedIn(account);
    }),

  logIn: ({ email, password }) =>
    later(() => {
      const account = accounts.find((a) => a.email === email.trim().toLowerCase());
      if (!account || account.password !== password) {
        throw new ApiError('Wrong email or password.', 'invalid_credentials', 401);
      }
      return signedIn(account);
    }),

  logOut: () =>
    later(() => {
      sessions.delete(getToken() ?? '');
    }),

  getAccount: () => later(() => publicAccount(currentAccount())),

  // Google Health: connecting succeeds at once (no Google page) and a sync takes 3 seconds.
  getGoogleStatus: () => later(() => google),
  connectGoogle: () =>
    later(() => {
      google = { ...google, status: 'active', missingScopes: [] };
      const account = accounts.find((a) => a.id === sessions.get(getToken() ?? ''));
      if (account) account.hasData = true; // the made-up history stands in for theirs
      startMockSync();
      return { url: '' }; // nothing to open
    }),
  syncGoogle: (options) =>
    later(() => {
      if (google.status !== 'active') {
        throw new ApiError('Connect Google Health first.', 'not_connected', 409);
      }
      // Like the server: the app's own syncs start at most one every 10 minutes.
      const recent =
        google.lastSync !== null && Date.now() - Date.parse(google.lastSync) < RESYNC_AFTER_MS;
      if (options?.force || (!recent && !google.syncing)) startMockSync();
      return google;
    }),
  disconnectGoogle: () =>
    later(() => {
      google = { ...google, status: 'none', syncing: false };
      return google;
    }),

  getAccessRequests: () =>
    later(() => {
      adminAccount();
      return accounts
        .filter((a) => a.status === 'pending')
        .map<AccessRequest>(({ id, email, requestedAt }) => ({ id, email, requestedAt }));
    }),

  decideAccessRequest: (id, approve, role = 'member') =>
    later(() => {
      adminAccount();
      const account = accounts.find((a) => a.id === id);
      if (!account) throw new ApiError('No such account.', 'not_found', 404);
      account.status = approve ? 'approved' : 'rejected';
      if (approve) account.role = role;
      if (!approve) {
        // Like the backend: a rejected person is signed out everywhere.
        for (const [token, owner] of sessions) if (owner === id) sessions.delete(token);
      }
      return publicAccount(account);
    }),

  getLatestReport: () =>
    later<Report>(() => {
      ownData();
      return {
        id: 'report_latest',
        period: { start: isoDate(27), end: isoDate(0) },
        createdAt: new Date().toISOString(),
        headline: 'Your sleep got less efficient as your bedtime moved later.',
        findings,
        questions,
        evidence,
      };
    }),

  getDay: (date) =>
    later(() => {
      ownData();
      return mockDay(date === 'latest' ? isoDate(0) : date);
    }),

  getMetricSeries: (metric, { end, days }) => later(() => mockSeries(metric, days, end)),

  getWorkouts: (date) =>
    later(() => ({
      available: true,
      // A made-up walk every other day.
      workouts:
        daysAgoOf(date) % 2
          ? []
          : [
              {
                id: `w-${date}`,
                exerciseType: 'WALKING',
                name: 'Walk',
                start: `${date}T07:30:00Z`,
                end: `${date}T08:05:00Z`,
                activeSeconds: 2100,
                steps: 3900,
                distanceKm: 2.9,
                caloriesKcal: 180,
                averageHeartRate: 104,
                activeZoneMinutes: 12,
                zoneSeconds: { light: 900, moderate: 600, vigorous: 0, peak: 0 },
                source: 'Demo tracker',
              },
            ],
    })),

  getHourlySteps: (date) =>
    later(() => ({
      available: true,
      steps: Array.from({ length: 24 }, (_, hour) =>
        hour < 7 || (daysAgoOf(date) === 0 && hour > new Date().getHours())
          ? null
          : Math.round(random(hour * 31 + daysAgoOf(date))() * 900),
      ),
    })),

  getCheckIn: (date) => later(() => checkIns.find((c) => c.day === date) ?? null),

  saveCheckIn: (checkIn) =>
    later(() => {
      if (checkIn.day !== isoDate(0)) {
        throw new ApiError("Only today's check-in can be set or changed.", 'invalid_checkin', 422);
      }
      if (!Number.isInteger(checkIn.rating) || checkIn.rating < 1 || checkIn.rating > 5) {
        throw new ApiError('The rating is a whole number from 1 to 5.', 'invalid_checkin', 422);
      }
      checkIns = [...checkIns.filter((c) => c.day !== checkIn.day), checkIn];
      return checkIn;
    }),

  getEvidence: (id) =>
    evidence[id]
      ? delay(evidence[id])
      : Promise.reject(new Error('This evidence no longer exists.')),

  answerQuestion: (questionId, answer) => {
    questions = questions.map((q) => (q.id === questionId ? { ...q, answer } : q));
    const updated = questions.find((q) => q.id === questionId);
    return updated ? delay(updated) : Promise.reject(new Error('Unknown question'));
  },

  getChat: (conversationId) => {
    const id = conversationId ?? latestConversation()?.id;
    if (conversationId && !conversations.some((c) => c.id === conversationId)) {
      return Promise.reject(new ApiError('No such conversation.', 'not_found', 404));
    }
    return delay(chat.filter((m) => m.conversationId === id));
  },

  getConversations: () =>
    delay(
      [...conversations]
        .sort(
          (a, b) => Number(b.pinned) - Number(a.pinned) || b.updatedAt.localeCompare(a.updatedAt),
        )
        .map((c) => ({ ...c, messages: chat.filter((m) => m.conversationId === c.id).length })),
    ),

  createConversation: () => delay(newConversation()),

  updateConversation: (id, { title, pinned }) => {
    const conversation = conversations.find((c) => c.id === id);
    if (!conversation) {
      return Promise.reject(new ApiError('No such conversation.', 'not_found', 404));
    }
    if (title !== undefined) conversation.title = conversationTitle(title);
    if (pinned !== undefined) conversation.pinned = pinned;
    return delay({ ...conversation });
  },

  deleteConversation: (id) => {
    conversations = conversations.filter((c) => c.id !== id);
    chat = chat.filter((m) => m.conversationId !== id);
    return delay(undefined);
  },

  sendMessage: (text, options) => {
    if (options.expert === 'nutrition') {
      return Promise.reject(new Error('The nutrition expert is not available yet.'));
    }
    // Like the backend: an edited or retried question replaces itself and what followed it.
    const replaced = options.replaces ? chat.find((m) => m.id === options.replaces) : undefined;
    if (options.replaces && (!replaced || replaced.role !== 'user')) {
      return Promise.reject(
        new ApiError('That message is no longer in this chat.', 'not_found', 404),
      );
    }
    if (replaced) {
      const start = chat.indexOf(replaced);
      chat = chat.filter((m, i) => i < start || m.conversationId !== replaced.conversationId);
    }
    const conversation = replaced
      ? conversations.find((c) => c.id === replaced.conversationId)
      : options.conversationId
        ? conversations.find((c) => c.id === options.conversationId)
        : (latestConversation() ?? newConversation());
    if (!conversation) {
      return Promise.reject(new ApiError('No such conversation.', 'not_found', 404));
    }
    if (conversation.title === NEW_CHAT) conversation.title = conversationTitle(text);
    conversation.updatedAt = new Date().toISOString();
    const { attachment } = options;
    const conversationId = conversation.id;
    const added = [
      message({
        role: 'user',
        text,
        evidenceIds: [],
        conversationId,
        ...(attachment && { attachment }),
      }),
    ];
    chat = [...chat, ...added];
    const prepared = proposeReminder(text);
    const answer = message({
      ...(prepared
        ? {
            role: 'assistant' as const,
            text: "Here's the reminder. Tap Set on the card to turn it on.",
            evidenceIds: [],
            answeredBy: 'general' as const,
            reminderIds: [prepared.id],
          }
        : reply(text, options)),
      conversationId,
    });
    chat = [...chat, answer];
    const asked = /remember that (.+)/i.exec(text);
    if (asked) {
      const id = `f_${Date.now().toString(36)}`;
      facts = [
        {
          id,
          kind: 'context',
          text: asked[1].slice(0, 120),
          status: 'proposed',
          start: null,
          end: null,
          createdAt: new Date().toISOString(),
        },
        ...facts,
      ];
    }
    return delay([...added, answer]);
  },

  getReminders: () =>
    delay(reminders.filter((r) => r.status !== 'declined' || r.source === 'agent')),

  createReminder: (reminder) =>
    later(() => {
      checkReminder(reminder);
      const created = mockReminder({
        ...reminder,
        id: `r_${Date.now().toString(36)}`,
        status: 'active',
        source: 'person',
      });
      reminders = [created, ...reminders];
      return created;
    }),

  changeReminder: (id, change) =>
    later(() => {
      const current = reminders.find((r) => r.id === id);
      if (!current) throw new ApiError('No such reminder.', 'not_found', 404);
      if (change.version !== current.version) {
        throw new ApiError('This reminder changed; reload and try again.', 'version_conflict', 409);
      }
      const next = {
        ...current,
        ...change,
        status: change.status ?? current.status,
        version: current.version + 1,
      };
      checkReminder(next);
      const updated = mockReminder(next);
      reminders = reminders.map((r) => (r.id === id ? updated : r));
      return updated;
    }),

  deleteReminder: (id) =>
    later(() => {
      reminders = reminders.filter((r) => r.id !== id);
    }),

  getNotificationSettings: () => delay(notificationSettings),

  updateNotificationSettings: (settings) => {
    if (
      !Number.isInteger(settings.maxPerDay) ||
      settings.maxPerDay < 1 ||
      settings.maxPerDay > 10
    ) {
      return Promise.reject(new Error('maxPerDay must be between 1 and 10'));
    }
    notificationSettings = settings;
    return delay(notificationSettings);
  },

  getNotifications: () =>
    delay({ items: inbox, unread: inbox.filter((n) => n.readAt === null).length }),

  readNotification: (id) =>
    later(() => {
      const found = inbox.find((n) => n.id === id);
      if (!found) throw new ApiError('No such notification.', 'not_found', 404);
      found.readAt ??= new Date().toISOString();
      return found;
    }),

  readAllNotifications: () =>
    later(() => {
      const now = new Date().toISOString();
      inbox = inbox.map((n) => ({ ...n, readAt: n.readAt ?? now }));
    }),

  setTimezone: () => delay(undefined),

  getAlarmSettings: () => delay(alarmSettings),

  updateAlarmSettings: (settings) => {
    alarmSettings = settings;
    return delay(alarmSettings);
  },

  sendAlarmFeedback: (alarmId, useful) =>
    later(() => {
      const found = inbox.find((n) => n.alarmId === alarmId);
      if (!found) throw new ApiError('No such alarm.', 'not_found', 404);
      found.alarmFeedback = useful ? 'useful' : 'not_useful';
    }),

  getMemory: () =>
    later(() => {
      const having = (status: MemoryFact['status']) => facts.filter((f) => f.status === status);
      return {
        waiting: having('proposed'),
        kept: having('approved'),
        noticed: having('candidate'),
        interests,
        episodes,
      };
    }),

  decideMemory: (id, keep) =>
    later(() => {
      const fact = factWith(id);
      if (fact.status !== 'proposed') {
        throw new ApiError('This fact was already decided.', 'invalid_request', 422);
      }
      inbox = inbox.map((n) =>
        n.factId === id ? { ...n, readAt: n.readAt ?? new Date().toISOString() } : n,
      );
      facts = keep
        ? facts.map((f) => (f.id === id ? { ...f, status: 'approved' } : f))
        : facts.filter((f) => f.id !== id);
      return { ...fact, status: keep ? ('approved' as const) : fact.status };
    }),

  rewordMemory: (id, text) =>
    later(() => {
      const fact = { ...factWith(id), text };
      if (/insomnia|apnea|medication/i.test(text)) {
        throw new ApiError('Patterns does not keep medical details.', 'invalid_request', 422);
      }
      facts = facts.map((f) => (f.id === id ? fact : f));
      return fact;
    }),

  forgetMemory: (id) =>
    later(() => {
      factWith(id);
      facts = facts.filter((f) => f.id !== id);
    }),

  noteOpened: () => delay(undefined),

  muteInterest: (topic) =>
    later(() => {
      interests = interests.filter((i) => i.topic !== topic);
    }),

  forgetEpisode: (id) =>
    later(() => {
      episodes = episodes.filter((e) => e.id !== id);
    }),

  getDataStatus: () =>
    later<DataStatus>(() => {
      ownData();
      return {
        source: 'takeout',
        lastSync: new Date(Date.now() - 2 * 3600_000).toISOString(),
        range: { start: isoDate(110), end: isoDate(0) },
        coverage: [
          { metric: 'steps', label: 'Steps', fractionPresent: 1 },
          { metric: 'sleep_minutes', label: 'Sleep', fractionPresent: 0.96 },
          { metric: 'hrv_ms', label: 'HRV', fractionPresent: 0.93 },
          { metric: 'readiness', label: 'Readiness', fractionPresent: 0.89 },
          { metric: 'skin_temp_variation_c', label: 'Skin temperature', fractionPresent: 0.86 },
        ],
        lowWearDays: [isoDate(40), isoDate(39)],
      };
    }),
};
