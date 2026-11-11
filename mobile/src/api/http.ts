// Client for the real backend API. Endpoints the backend does not serve yet fall back to
// `fallback` (the mock), so the app can move to the real API one endpoint at a time.
import { getToken } from './token';
import type {
  AccessRequest,
  Account,
  AlarmSettings,
  ApiClient,
  AppNotification,
  ChatMessage,
  CheckIn,
  Conversation,
  MemoryFact,
  MemoryPage,
  Credentials,
  DataStatus,
  DaySummary,
  DayWorkouts,
  Evidence,
  GoogleStatus,
  HealthAction,
  HourlySteps,
  Inbox,
  Membership,
  MetricSeries,
  NotificationSettings,
  Reminder,
  Report,
  SignedIn,
  SupervisedTeam,
  TeamAction,
  TeamAlert,
  TeamChatMessage,
  TeamChatReply,
  TeamNote,
  TeamPreview,
  TeamReport,
  TeamReportSummary,
} from './types';

const TIMEOUT_MS = 15_000;
// An answer can take up to a minute; the server stops waiting after about 55 s.
const CHAT_TIMEOUT_MS = 70_000;

/** An error the screens can show as is. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function request<T>(
  baseUrl: string,
  path: string,
  init?: RequestInit,
  timeoutMs = TIMEOUT_MS,
): Promise<T> {
  const token = getToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, '')}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
        ...init?.headers,
      },
      signal: controller.signal,
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === 'AbortError';
    throw new ApiError(
      timedOut ? 'The server took too long to answer.' : 'Could not reach the server.',
      timedOut ? 'timeout' : 'network',
    );
  } finally {
    clearTimeout(timer);
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    // The backend answers errors as {"error": {"code", "message"}}.
    const error = body?.error;
    throw new ApiError(
      typeof error?.message === 'string' ? error.message : `Request failed (${response.status}).`,
      typeof error?.code === 'string' ? error.code : 'http_error',
      response.status,
    );
  }
  return body as T;
}

function post<T>(baseUrl: string, path: string, body?: unknown, timeoutMs?: number): Promise<T> {
  return request<T>(
    baseUrl,
    path,
    { method: 'POST', ...(body !== undefined && { body: JSON.stringify(body) }) },
    timeoutMs,
  );
}

export function httpClient(baseUrl: string, fallback: ApiClient): ApiClient {
  return {
    ...fallback,
    getActions: () => request<HealthAction[]>(baseUrl, '/actions'),
    getAction: (id) => request<HealthAction>(baseUrl, `/actions/${encodeURIComponent(id)}`),
    proposeAction: (requestKey, log) =>
      post<HealthAction>(baseUrl, '/actions', { requestKey, log }),
    reviseAction: (id, version, log) =>
      post<HealthAction>(baseUrl, `/actions/${encodeURIComponent(id)}/revise`, { version, log }),
    cancelAction: (id, version) =>
      post<HealthAction>(baseUrl, `/actions/${encodeURIComponent(id)}/cancel`, { version }),
    confirmAction: (id, version) =>
      post<HealthAction>(
        baseUrl,
        `/actions/${encodeURIComponent(id)}/confirm`,
        { version },
        30_000,
      ),
    undoAction: (id, version) =>
      post<HealthAction>(baseUrl, `/actions/${encodeURIComponent(id)}/undo`, { version }, 30_000),
    signUp: (credentials: Credentials) => post<SignedIn>(baseUrl, '/auth/signup', credentials),
    logIn: (credentials: Credentials) => post<SignedIn>(baseUrl, '/auth/login', credentials),
    logOut: () => post<void>(baseUrl, '/auth/logout'),
    getAccount: () => request<Account>(baseUrl, '/auth/me'),
    getAccessRequests: () => request<AccessRequest[]>(baseUrl, '/admin/access-requests'),
    decideAccessRequest: (id, approve, role) =>
      post<Account>(
        baseUrl,
        `/admin/access-requests/${encodeURIComponent(id)}/${approve ? 'approve' : 'reject'}`,
        approve && role ? { role } : undefined,
      ),
    getDataStatus: () => request<DataStatus>(baseUrl, '/data/status'),
    getReminders: () => request<Reminder[]>(baseUrl, '/reminders'),
    createReminder: (reminder) => post<Reminder>(baseUrl, '/reminders', reminder),
    changeReminder: (id, change) =>
      request<Reminder>(baseUrl, `/reminders/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(change),
      }),
    deleteReminder: (id) =>
      request<void>(baseUrl, `/reminders/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    getNotificationSettings: () => request<NotificationSettings>(baseUrl, '/notification-settings'),
    updateNotificationSettings: (settings) =>
      request<NotificationSettings>(baseUrl, '/notification-settings', {
        method: 'PUT',
        body: JSON.stringify(settings),
      }),
    getNotifications: () => request<Inbox>(baseUrl, '/notifications'),
    readNotification: (id) =>
      post<AppNotification>(baseUrl, `/notifications/${encodeURIComponent(id)}/read`),
    readAllNotifications: () => post<void>(baseUrl, '/notifications/read-all'),
    getAlarmSettings: () => request<AlarmSettings>(baseUrl, '/alarm-settings'),
    updateAlarmSettings: (settings) =>
      request<AlarmSettings>(baseUrl, '/alarm-settings', {
        method: 'PUT',
        body: JSON.stringify(settings),
      }),
    sendAlarmFeedback: (alarmId, useful) =>
      post<unknown>(baseUrl, `/alarms/${encodeURIComponent(alarmId)}/feedback`, { useful }).then(
        () => undefined,
      ),
    getMemory: () => request<MemoryPage>(baseUrl, '/memory'),
    decideMemory: (id, keep) =>
      post<MemoryFact>(baseUrl, `/memory/facts/${encodeURIComponent(id)}/decision`, { keep }),
    rewordMemory: (id, text) =>
      request<MemoryFact>(baseUrl, `/memory/facts/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ text }),
      }),
    forgetMemory: (id) =>
      request<void>(baseUrl, `/memory/facts/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    noteOpened: (topic) => post<void>(baseUrl, '/memory/interests', { topic }),
    muteInterest: (topic) =>
      request<void>(baseUrl, `/memory/interests/${encodeURIComponent(topic)}`, {
        method: 'DELETE',
      }),
    forgetEpisode: (id) =>
      request<void>(baseUrl, `/memory/episodes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    setTimezone: (timezone) =>
      request<void>(baseUrl, '/me/timezone', { method: 'PUT', body: JSON.stringify({ timezone }) }),
    previewTeam: (code) => post<TeamPreview>(baseUrl, '/teams/preview', { code }),
    joinTeam: (code, consentVersion) =>
      post<Membership>(baseUrl, '/teams/join', { code, consentVersion }),
    getMyTeams: () => request<Membership[]>(baseUrl, '/me/teams'),
    shareTeamLevels: (teamId, share, consentVersion) =>
      post<Membership>(baseUrl, `/me/teams/${encodeURIComponent(teamId)}/levels`, {
        share,
        consentVersion,
      }),
    leaveTeam: (teamId) => post<void>(baseUrl, `/me/teams/${encodeURIComponent(teamId)}/leave`),
    getTeams: () => request<SupervisedTeam[]>(baseUrl, '/teams'),
    createTeam: (name) => post<SupervisedTeam>(baseUrl, '/teams', { name }),
    rotateTeamCode: (teamId) =>
      post<SupervisedTeam>(baseUrl, `/teams/${encodeURIComponent(teamId)}/invite-code`),
    getTeamReports: (teamId) =>
      request<TeamReportSummary[]>(baseUrl, `/teams/${encodeURIComponent(teamId)}/reports`),
    getTeamReport: (teamId, week) =>
      request<TeamReport>(baseUrl, `/teams/${encodeURIComponent(teamId)}/reports/${week}`),
    getTeamChat: (teamId) =>
      request<TeamChatMessage[]>(baseUrl, `/teams/${encodeURIComponent(teamId)}/chat`),
    askTeamAgent: (teamId, text) =>
      post<TeamChatReply>(baseUrl, `/teams/${encodeURIComponent(teamId)}/chat`, { text }, 60_000),
    rateTeamAnswer: (teamId, messageId, rating) =>
      request<TeamChatMessage>(
        baseUrl,
        `/teams/${encodeURIComponent(teamId)}/chat/${encodeURIComponent(messageId)}/rating`,
        { method: 'PUT', body: JSON.stringify({ rating }) },
      ),
    getTeamNotes: (teamId) =>
      request<TeamNote[]>(baseUrl, `/teams/${encodeURIComponent(teamId)}/notes`),
    addTeamNote: (teamId, text, startsOn, endsOn) =>
      post<TeamNote>(baseUrl, `/teams/${encodeURIComponent(teamId)}/notes`, {
        text,
        startsOn: startsOn ?? null,
        endsOn: endsOn ?? null,
      }),
    deleteTeamNote: (teamId, noteId) =>
      request<void>(
        baseUrl,
        `/teams/${encodeURIComponent(teamId)}/notes/${encodeURIComponent(noteId)}`,
        { method: 'DELETE' },
      ),
    getTeamAlerts: (teamId) =>
      request<TeamAlert[]>(baseUrl, `/teams/${encodeURIComponent(teamId)}/alerts`),
    getTeamActions: (teamId) =>
      request<TeamAction[]>(baseUrl, `/teams/${encodeURIComponent(teamId)}/actions`),
    decideTeamAction: (teamId, actionId, approve) =>
      post<{ membersTold: number; action: TeamAction }>(
        baseUrl,
        `/teams/${encodeURIComponent(teamId)}/actions/${encodeURIComponent(actionId)}/${
          approve ? 'approve' : 'decline'
        }`,
      ),
    makeTeamReport: (teamId, week) =>
      post<TeamReport>(baseUrl, `/teams/${encodeURIComponent(teamId)}/reports`, { week }, 60_000),
    getLatestReport: () => request<Report>(baseUrl, '/reports/latest'),
    getDay: (date) => request<DaySummary>(baseUrl, `/days/${encodeURIComponent(date)}`),
    getWorkouts: (date) => request<DayWorkouts>(baseUrl, `/days/${date}/workouts`),
    getHourlySteps: (date) => request<HourlySteps>(baseUrl, `/days/${date}/hourly`),
    getCheckIn: (date) => request<CheckIn | null>(baseUrl, `/checkins/${date}`),
    saveCheckIn: (checkIn) =>
      request<CheckIn>(baseUrl, `/checkins/${checkIn.day}`, {
        method: 'PUT',
        body: JSON.stringify(checkIn),
      }),
    getMetricSeries: (metric, { end, days }) =>
      request<MetricSeries>(
        baseUrl,
        `/metrics/${encodeURIComponent(metric)}?days=${days}${end ? `&end=${end}` : ''}`,
      ),
    getEvidence: (id) => request<Evidence>(baseUrl, `/evidence/${encodeURIComponent(id)}`),
    getChat: (conversationId) =>
      request<ChatMessage[]>(
        baseUrl,
        conversationId ? `/chat?conversation=${encodeURIComponent(conversationId)}` : '/chat',
      ),
    getConversations: () => request<Conversation[]>(baseUrl, '/conversations'),
    createConversation: () => post<Conversation>(baseUrl, '/conversations'),
    updateConversation: (id, changes) =>
      request<Conversation>(baseUrl, `/conversations/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify(changes),
      }),
    deleteConversation: (id) =>
      request<void>(baseUrl, `/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    getGoogleStatus: () => request<GoogleStatus>(baseUrl, '/google/status'),
    connectGoogle: (capability) =>
      post<{ url: string }>(baseUrl, '/google/connect', capability ? { capability } : undefined),
    syncGoogle: (options) =>
      post<GoogleStatus>(baseUrl, '/google/sync', { force: options?.force ?? false }),
    disconnectGoogle: () => post<GoogleStatus>(baseUrl, '/google/disconnect'),
    rateAnswer: (messageId, rating) =>
      request<ChatMessage>(baseUrl, `/chat/${encodeURIComponent(messageId)}/rating`, {
        method: 'PUT',
        body: JSON.stringify({ rating }),
      }),
    sendMessage: (text, { expert, depth, attachment, conversationId, replaces }) =>
      post<ChatMessage[]>(
        baseUrl,
        '/chat',
        { text, expert, depth, attachment, conversationId, replaces },
        CHAT_TIMEOUT_MS,
      ),
  };
}
