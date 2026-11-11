import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

import { ApiError } from './http';
import { api } from './index';
import type {
  Account,
  AlarmSettings,
  ChatMessage,
  CheckIn,
  GoogleStatus,
  ISODate,
  NewReminder,
  NotificationSettings,
  Rating,
  ReminderChange,
  SendOptions,
  TeamChatMessage,
} from './types';

const LISTENER_MS = 4000;

export const keys = {
  report: ['report', 'latest'] as const,
  chat: ['chat'] as const,
  conversations: ['conversations'] as const,
  reminders: ['reminders'] as const,
  dataStatus: ['data-status'] as const,
  notificationSettings: ['settings', 'notifications'] as const,
  notifications: ['notifications'] as const,
  memory: ['memory'] as const,
  alarmSettings: ['settings', 'alarms'] as const,
  accessRequests: ['admin', 'access-requests'] as const,
  google: ['google', 'status'] as const,
  myTeams: ['me', 'teams'] as const,
  teams: ['teams'] as const,
};

/** A day's numbers; 'latest' is the newest day with data. Kept while moving between days. */
export function useDay(date: ISODate | 'latest') {
  return useQuery({
    queryKey: ['day', date],
    queryFn: () => api.getDay(date),
    placeholderData: (previous) => previous,
  });
}

export function useWorkouts(date?: ISODate) {
  return useQuery({
    queryKey: ['workouts', date],
    queryFn: () => api.getWorkouts(date!),
    enabled: !!date,
  });
}

export function useHourlySteps(date?: ISODate) {
  return useQuery({
    queryKey: ['hourly', date],
    queryFn: () => api.getHourlySteps(date!),
    enabled: !!date,
  });
}

export function useCheckIn(date?: ISODate) {
  return useQuery({
    queryKey: ['checkin', date],
    queryFn: () => api.getCheckIn(date!),
    enabled: !!date,
  });
}

export function useSaveCheckIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (checkIn: CheckIn) => api.saveCheckIn(checkIn),
    onSuccess: (saved) => client.setQueryData(['checkin', saved.day], saved),
  });
}

export function useMetricSeries(metric: string, days: number, end?: ISODate) {
  return useQuery({
    queryKey: ['metric', metric, days, end ?? 'latest'],
    queryFn: () => api.getMetricSeries(metric, { end, days }),
    placeholderData: (previous) => previous,
  });
}

export function useReport() {
  return useQuery({ queryKey: keys.report, queryFn: api.getLatestReport });
}

export function useEvidence(id: string, enabled = true) {
  return useQuery({ queryKey: ['evidence', id], queryFn: () => api.getEvidence(id), enabled });
}

export function useAnswerQuestion() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) => api.answerQuestion(id, answer),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.report }),
  });
}

/** Which chat is open: a conversation, the latest one, or a new one not created yet. */
export type ChatTarget = string | 'latest' | 'new';

const chatKey = (target: ChatTarget) => [...keys.chat, target];

/** A chat with a new exchange added; an edited or retried question replaces itself and after. */
export function withAnswer(
  old: ChatMessage[] = [],
  added: ChatMessage[],
  replaces?: string,
): ChatMessage[] {
  const cut = replaces ? old.findIndex((m) => m.id === replaces) : -1;
  return [...(cut >= 0 ? old.slice(0, cut) : old), ...added];
}

/**
 * Puts a sent question and its answer into the cached chat. Sent to "the latest chat", the screen
 * then follows the chat's id: that starts from what was shown, or it would hold only this exchange
 * (as after a page reload, when nothing is cached under the id yet).
 */
export function storeAnswer(
  client: QueryClient,
  added: ChatMessage[],
  target: ChatTarget,
  replaces?: string,
): void {
  const id = added[0]?.conversationId;
  const append = (old?: ChatMessage[]) => withAnswer(old, added, replaces);
  const shown =
    target === 'latest' ? client.getQueryData<ChatMessage[]>(chatKey('latest')) : undefined;
  if (id) client.setQueryData<ChatMessage[]>(chatKey(id), (old) => append(old ?? shown));
  if (target === 'latest') client.setQueryData<ChatMessage[]>(chatKey('latest'), append);
}

export function useChat(target: ChatTarget = 'latest') {
  return useQuery({
    queryKey: chatKey(target),
    queryFn: () => (target === 'new' ? [] : api.getChat(target === 'latest' ? undefined : target)),
    // A question without an answer yet is still being answered on the server: check back.
    refetchInterval: (query) => (query.state.data?.at(-1)?.role === 'user' ? 4000 : false),
  });
}

export function useConversations() {
  return useQuery({ queryKey: keys.conversations, queryFn: api.getConversations });
}

export function useUpdateConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: { title?: string; pinned?: boolean } }) =>
      api.updateConversation(id, changes),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.conversations }),
  });
}

export function useDeleteConversation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.conversations });
      client.invalidateQueries({ queryKey: keys.chat });
    },
  });
}

/** Sends to the open chat; a new chat is created on its first message, so none are left empty. */
export function useSendMessage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      text,
      options,
      target,
    }: {
      text: string;
      options: SendOptions;
      target: ChatTarget;
    }) => {
      const conversationId =
        target === 'new'
          ? (await api.createConversation()).id
          : target === 'latest'
            ? undefined
            : target;
      return api.sendMessage(text, { ...options, conversationId });
    },
    // Append directly so the conversation never flickers while it refetches.
    onSuccess: (added, { target, options }) => {
      storeAnswer(client, added, target, options.replaces);
      client.invalidateQueries({ queryKey: keys.conversations });
      // The listener runs after the answer: look again once it has had time.
      setTimeout(() => client.invalidateQueries({ queryKey: keys.memory }), LISTENER_MS);
    },
    // A slow answer was still stored with its question: reload to show them as they arrive.
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'still_answering') {
        client.invalidateQueries({ queryKey: keys.chat });
        client.invalidateQueries({ queryKey: keys.conversations });
      }
    },
  });
}

/** A chat with one message's rating set (or cleared), every other message as it was. */
export function withRating<T extends { id: string; rating?: Rating | null }>(
  messages: T[] | undefined,
  id: string,
  rating: Rating | null,
): T[] | undefined {
  return messages?.map((m) => (m.id === id ? { ...m, rating: rating ?? undefined } : m));
}

/** Thumbs on an answer: shown at once in every cached copy of the chat, undone if it fails. */
export function useRateAnswer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, rating }: { id: string; rating: Rating | null }) =>
      api.rateAnswer(id, rating),
    onMutate: ({ id, rating }) => {
      const before = client.getQueriesData<ChatMessage[]>({ queryKey: keys.chat });
      client.setQueriesData<ChatMessage[]>({ queryKey: keys.chat }, (old) =>
        withRating(old, id, rating),
      );
      return { before };
    },
    onError: (_error, _rated, context) => {
      for (const [key, data] of context?.before ?? []) client.setQueryData(key, data);
    },
  });
}

export function useReminders() {
  return useQuery({ queryKey: keys.reminders, queryFn: api.getReminders });
}

export function useCreateReminder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (reminder: NewReminder) => api.createReminder(reminder),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.reminders }),
  });
}

export function useChangeReminder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, change }: { id: string; change: ReminderChange }) =>
      api.changeReminder(id, change),
    // A stale version means someone else changed it: show what is there now.
    onSettled: () => client.invalidateQueries({ queryKey: keys.reminders }),
  });
}

export function useDeleteReminder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteReminder(id),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.reminders }),
  });
}

/** The inbox, checked every minute while the app is open, so a due reminder shows up. */
export function useNotifications() {
  return useQuery({
    queryKey: keys.notifications,
    queryFn: api.getNotifications,
    refetchInterval: 60_000,
  });
}

export function useReadNotifications() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string | 'all') =>
      id === 'all' ? api.readAllNotifications() : api.readNotification(id).then(() => undefined),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.notifications }),
  });
}

export function useAlarmSettings() {
  return useQuery({ queryKey: keys.alarmSettings, queryFn: api.getAlarmSettings });
}

export function useUpdateAlarmSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (settings: AlarmSettings) => api.updateAlarmSettings(settings),
    onSuccess: (saved) => client.setQueryData(keys.alarmSettings, saved),
  });
}

/** "Was this alert useful?": kept on the alarm, and counted in the evaluation. */
export function useMemory() {
  return useQuery({ queryKey: keys.memory, queryFn: api.getMemory });
}

function useMemoryChange<Input>(change: (input: Input) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: change,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.memory });
      client.invalidateQueries({ queryKey: keys.notifications });
    },
  });
}

export function useDecideMemory() {
  return useMemoryChange(({ id, keep }: { id: string; keep: boolean }) =>
    api.decideMemory(id, keep),
  );
}

export function useRewordMemory() {
  return useMemoryChange(({ id, text }: { id: string; text: string }) =>
    api.rewordMemory(id, text),
  );
}

export function useForgetMemory() {
  return useMemoryChange((id: string) => api.forgetMemory(id));
}

export function useMuteInterest() {
  return useMemoryChange((topic: string) => api.muteInterest(topic));
}

export function useForgetEpisode() {
  return useMemoryChange((id: string) => api.forgetEpisode(id));
}

export function useAlarmFeedback() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ alarmId, useful }: { alarmId: string; useful: boolean }) =>
      api.sendAlarmFeedback(alarmId, useful),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.notifications }),
  });
}

/** Tells the server this device's time zone once per sign-in, so reminders come at local time. */
export function useSyncTimezone() {
  useEffect(() => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (zone) void api.setTimezone(zone).catch(() => undefined);
  }, []);
}

export function useNotificationSettings() {
  return useQuery({ queryKey: keys.notificationSettings, queryFn: api.getNotificationSettings });
}

export function useUpdateNotificationSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (settings: NotificationSettings) => api.updateNotificationSettings(settings),
    onSuccess: (saved) => client.setQueryData(keys.notificationSettings, saved),
  });
}

export function useDataStatus() {
  return useQuery({ queryKey: keys.dataStatus, queryFn: api.getDataStatus });
}

/**
 * True when the person has no Fitbit data to show yet: no Fitbit, not connected, or the first sync
 * still running. Undefined while loading, or after another error, which screens show themselves.
 */
export function useNoData(): boolean | undefined {
  const status = useDataStatus();
  if (status.error instanceof ApiError && status.error.code === 'no_data') return true;
  return status.data ? status.data.source === 'none' : undefined;
}

export function useAccessRequests() {
  return useQuery({ queryKey: keys.accessRequests, queryFn: api.getAccessRequests });
}

export function useDecideAccessRequest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, role }: { id: string; approve: boolean; role?: Account['role'] }) =>
      api.decideAccessRequest(id, approve, role),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.accessRequests }),
  });
}

export function useGoogleStatus() {
  return useQuery({
    queryKey: keys.google,
    queryFn: api.getGoogleStatus,
    refetchInterval: (query) => (query.state.data?.syncing ? 3000 : false), // until it is done
  });
}

/** Sync now or disconnect; both answer with the new status. "Sync now" always starts one. */
export function useGoogleAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: 'sync' | 'disconnect') =>
      action === 'sync' ? api.syncGoogle({ force: true }) : api.disconnectGoogle(),
    onSuccess: (status) => client.setQueryData(keys.google, status),
  });
}

/**
 * Asks the server to sync, when Google is connected; it starts one only if the last began over
 * 10 minutes ago. Called on open, on coming back to the app and on every pull to refresh, so
 * nobody has to think about syncing. Failures stay quiet: the status shows them in Settings.
 */
export async function requestSync(client: QueryClient): Promise<void> {
  try {
    const current =
      client.getQueryData<GoogleStatus>(keys.google) ??
      (await client.fetchQuery({ queryKey: keys.google, queryFn: api.getGoogleStatus }));
    if (current?.status !== 'active' || current.syncing) return;
    client.setQueryData(keys.google, await api.syncGoogle());
  } catch {
    // Not connected yet, offline or signed out: nothing to sync now.
  }
}

/** What a finished sync can change: refetched so new numbers appear without another pull. */
export function refreshSyncedData(client: QueryClient): Promise<unknown> {
  return Promise.all(
    [['day'], ['workouts'], ['hourly'], ['metric'], ['evidence'], keys.report, keys.dataStatus].map(
      (queryKey) => client.invalidateQueries({ queryKey }),
    ),
  );
}

/** Mounted once for a signed-in person: syncs on open and on return, refreshes when done. */
export function useAutoSync() {
  const client = useQueryClient();
  const syncing = useGoogleStatus().data?.syncing ?? false;
  const wasSyncing = useRef(syncing);

  useEffect(() => {
    void requestSync(client);
    // AppState covers phones and, through react-native-web, the browser tab's visibility.
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void requestSync(client);
    });
    return () => subscription.remove();
  }, [client]);

  useEffect(() => {
    if (wasSyncing.current && !syncing) void refreshSyncedData(client);
    wasSyncing.current = syncing;
  }, [client, syncing]);
}

// Teams, as a member (docs/teams.md)

export function useMyTeams() {
  return useQuery({ queryKey: keys.myTeams, queryFn: api.getMyTeams });
}

export function usePreviewTeam() {
  return useMutation({ mutationFn: (code: string) => api.previewTeam(code) });
}

export function useJoinTeam() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ code, consentVersion }: { code: string; consentVersion: string }) =>
      api.joinTeam(code, consentVersion),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.myTeams }),
  });
}

export function useShareTeamLevels() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      teamId,
      share,
      consentVersion,
    }: {
      teamId: string;
      share: boolean;
      consentVersion?: string;
    }) => api.shareTeamLevels(teamId, share, consentVersion),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.myTeams }),
  });
}

export function useLeaveTeam() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (teamId: string) => api.leaveTeam(teamId),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.myTeams }),
  });
}

// Teams, as a supervisor

export function useTeams(enabled = true) {
  return useQuery({ queryKey: keys.teams, queryFn: api.getTeams, enabled });
}

export function useCreateTeam() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.createTeam(name),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.teams }),
  });
}

export function useRotateTeamCode() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (teamId: string) => api.rotateTeamCode(teamId),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.teams }),
  });
}

export function useTeamReports(teamId?: string) {
  return useQuery({
    queryKey: [...keys.teams, teamId, 'reports'],
    queryFn: () => api.getTeamReports(teamId!),
    enabled: !!teamId,
  });
}

export function useTeamReport(teamId?: string, week?: ISODate) {
  return useQuery({
    queryKey: [...keys.teams, teamId, 'report', week],
    queryFn: () => api.getTeamReport(teamId!, week!),
    enabled: !!teamId && !!week,
  });
}

export function useMakeTeamReport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (teamId: string) => api.makeTeamReport(teamId),
    onSuccess: (_, teamId) => client.invalidateQueries({ queryKey: [...keys.teams, teamId] }),
  });
}

// The supervisor's team agent

export function useTeamChat(teamId: string) {
  return useQuery({
    queryKey: [...keys.teams, teamId, 'chat'],
    queryFn: () => api.getTeamChat(teamId),
  });
}

export function useAskTeamAgent(teamId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.askTeamAgent(teamId, text),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: [...keys.teams, teamId, 'chat'] });
      client.invalidateQueries({ queryKey: [...keys.teams, teamId, 'actions'] });
      client.invalidateQueries({ queryKey: [...keys.teams, teamId, 'notes'] });
    },
  });
}

export function useRateTeamAnswer(teamId: string) {
  const client = useQueryClient();
  const key = [...keys.teams, teamId, 'chat'];
  return useMutation({
    mutationFn: ({ id, rating }: { id: string; rating: Rating | null }) =>
      api.rateTeamAnswer(teamId, id, rating),
    onMutate: ({ id, rating }) => {
      const before = client.getQueryData<TeamChatMessage[]>(key);
      client.setQueryData<TeamChatMessage[]>(key, (old) => withRating(old, id, rating));
      return { before };
    },
    onError: (_error, _rated, context) => client.setQueryData(key, context?.before),
  });
}

export function useTeamNotes(teamId: string) {
  return useQuery({
    queryKey: [...keys.teams, teamId, 'notes'],
    queryFn: () => api.getTeamNotes(teamId),
  });
}

export function useAddTeamNote(teamId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.addTeamNote(teamId, text),
    onSuccess: () => client.invalidateQueries({ queryKey: [...keys.teams, teamId, 'notes'] }),
  });
}

export function useDeleteTeamNote(teamId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (noteId: string) => api.deleteTeamNote(teamId, noteId),
    onSuccess: () => client.invalidateQueries({ queryKey: [...keys.teams, teamId, 'notes'] }),
  });
}

export function useTeamAlerts(teamId: string) {
  return useQuery({
    queryKey: [...keys.teams, teamId, 'alerts'],
    queryFn: () => api.getTeamAlerts(teamId),
  });
}

export function useTeamActions(teamId: string) {
  return useQuery({
    queryKey: [...keys.teams, teamId, 'actions'],
    queryFn: () => api.getTeamActions(teamId),
  });
}

export function useDecideTeamAction(teamId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ actionId, approve }: { actionId: string; approve: boolean }) =>
      api.decideTeamAction(teamId, actionId, approve),
    onSuccess: () => client.invalidateQueries({ queryKey: [...keys.teams, teamId, 'actions'] }),
  });
}
