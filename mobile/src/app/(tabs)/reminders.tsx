import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Switch, View } from 'react-native';

import {
  useAlarmFeedback,
  useAlarmSettings,
  useChangeReminder,
  useNotifications,
  useNotificationSettings,
  useReadNotifications,
  useReminders,
  useUpdateAlarmSettings,
  useUpdateNotificationSettings,
} from '@/api/hooks';
import type {
  AlarmKind,
  AlarmSettings,
  AppNotification,
  NotificationSettings,
  Reminder,
} from '@/api/types';
import { Row, Section } from '@/components/list';
import { InboxMemoryChoice } from '@/components/MemoryPrompt';
import { QueryState, Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Button, Chip } from '@/components/ui';
import { timeAgo } from '@/lib/format';
import { select, success } from '@/lib/haptics';
import { dueText } from '@/lib/reminders';
import { spacing, useColors } from '@/theme';

const QUIET_HOURS: { label: string; value: NotificationSettings['quietHours'] }[] = [
  { label: '22:00 – 07:00', value: { start: '22:00', end: '07:00' } },
  { label: '23:00 – 08:00', value: { start: '23:00', end: '08:00' } },
  { label: 'Off', value: null },
];
const MAX_PER_DAY = [1, 2, 3, 5];
const INBOX_SHOWN = 5;

/**
 * Reminders and the inbox in one place: what came in, what Patterns suggests, and what you set.
 * Reminders arrive in the app (this inbox, and the badge on this tab) and by email.
 */
export default function RemindersScreen() {
  const colors = useColors();
  const reminders = useReminders();
  const inbox = useNotifications();

  return (
    <Screen
      title="Reminders"
      refreshing={reminders.isRefetching}
      onRefresh={() => {
        reminders.refetch();
        inbox.refetch();
      }}
    >
      <Inbox items={inbox.data?.items ?? []} unread={inbox.data?.unread ?? 0} />
      <QueryState query={reminders}>
        {() => {
          const all = reminders.data!;
          const suggested = all.filter((r) => r.status === 'proposed');
          const yours = all.filter((r) => r.status === 'active' || r.status === 'paused');
          return (
            <>
              {suggested.length > 0 && (
                <Section
                  title="Suggested by Patterns"
                  footer="From patterns in your data. Nothing is scheduled until you approve it."
                >
                  {suggested.map((r) => (
                    <Suggestion key={r.id} reminder={r} />
                  ))}
                </Section>
              )}

              <Section
                title="Your reminders"
                action={
                  <Pressable
                    accessibilityRole="button"
                    onPress={() => router.push('/reminder/new')}
                    hitSlop={8}
                    style={styles.add}
                  >
                    <Ionicons name="add" size={16} color={colors.accent} />
                    <Text variant="caption" color="accent">
                      New
                    </Text>
                  </Pressable>
                }
                footer="Tip: ask in Ask, for example “remind me every weeknight at 22:30 to wind down”."
              >
                {yours.length === 0 ? (
                  <Row
                    icon="alarm-outline"
                    title="No reminders yet"
                    detail="Add one here, or ask Patterns to set it up."
                    onPress={() => router.push('/reminder/new')}
                  />
                ) : (
                  yours.map((r) => <ReminderRow key={r.id} reminder={r} />)
                )}
              </Section>
            </>
          );
        }}
      </QueryState>
      <SettingsSection />
      <AlertSettings />
    </Screen>
  );
}

function Inbox({ items, unread }: { items: AppNotification[]; unread: number }) {
  const read = useReadNotifications();
  if (items.length === 0) return null;

  function open(item: AppNotification) {
    if (!item.readAt) read.mutate(item.id);
    if (item.link && item.link !== '/reminders') router.push(item.link as never);
  }

  return (
    <Section
      title={unread > 0 ? `Inbox · ${unread} new` : 'Inbox'}
      action={
        unread > 0 ? (
          <Pressable accessibilityRole="button" onPress={() => read.mutate('all')} hitSlop={8}>
            <Text variant="caption" color="accent">
              Mark all read
            </Text>
          </Pressable>
        ) : undefined
      }
    >
      {items.slice(0, INBOX_SHOWN).map((item) => (
        <View key={item.id}>
          <Row
            icon={
              item.kind === 'alarm'
                ? item.readAt
                  ? 'pulse-outline'
                  : 'pulse'
                : item.readAt
                  ? 'notifications-outline'
                  : 'notifications'
            }
            title={item.title}
            detail={`${item.body} · ${timeAgo(item.createdAt)}`}
            accessory={item.readAt ? undefined : <UnreadDot />}
            onPress={() => open(item)}
            accessibilityLabel={`${item.readAt ? '' : 'Unread: '}${item.title}. ${item.body}`}
          />
          {item.alarmId && <AlarmFeedback alarmId={item.alarmId} given={item.alarmFeedback} />}
          {item.factId && <InboxMemoryChoice factId={item.factId} />}
        </View>
      ))}
    </Section>
  );
}

/** "Was this alert useful?" under an alert, answered once; it tunes alerts and is evaluated. */
function AlarmFeedback({
  alarmId,
  given,
}: {
  alarmId: string;
  given: AppNotification['alarmFeedback'];
}) {
  const feedback = useAlarmFeedback();
  if (given) {
    return (
      <Text variant="caption" color="muted" style={styles.feedback}>
        {given === 'useful' ? 'Marked useful. Thanks.' : 'Marked not useful. Thanks.'}
      </Text>
    );
  }
  const answer = (useful: boolean) => {
    select();
    feedback.mutate({ alarmId, useful });
  };
  return (
    <View style={[styles.feedback, styles.feedbackRow]}>
      <Text variant="caption" color="muted">
        Was this alert useful?
      </Text>
      <Pressable
        accessibilityRole="button"
        disabled={feedback.isPending}
        onPress={() => answer(true)}
        hitSlop={8}
      >
        <Text variant="caption" color="accent">
          Yes
        </Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        disabled={feedback.isPending}
        onPress={() => answer(false)}
        hitSlop={8}
      >
        <Text variant="caption" color="accent">
          No
        </Text>
      </Pressable>
    </View>
  );
}

function UnreadDot() {
  return <View style={[styles.dot, { backgroundColor: useColors().accent }]} />;
}

function Suggestion({ reminder }: { reminder: Reminder }) {
  const change = useChangeReminder();
  const pending = change.isPending && change.variables?.id === reminder.id;
  const decide = (status: 'active' | 'declined') =>
    change.mutate(
      { id: reminder.id, change: { version: reminder.version, status } },
      { onSuccess: () => (status === 'active' ? success() : select()) },
    );

  return (
    <View style={styles.suggestion}>
      <Text variant="bodyStrong">{reminder.title}</Text>
      <Text variant="caption" color="muted">
        {reminder.scheduleText} · “{reminder.message}”
      </Text>
      {reminder.reason && (
        <Text variant="caption" color="muted">
          Why: {reminder.reason}
        </Text>
      )}
      {reminder.evidenceId && (
        <Pressable
          accessibilityRole="link"
          onPress={() => router.push(`/evidence/${reminder.evidenceId}`)}
          hitSlop={6}
        >
          <Text variant="caption" color="accent">
            See the numbers behind it ›
          </Text>
        </Pressable>
      )}
      {change.error && change.variables?.id === reminder.id && (
        <Text variant="caption" color="danger">
          {change.error.message}
        </Text>
      )}
      <View style={styles.actions}>
        <Button
          label="Not now"
          variant="secondary"
          onPress={() => decide('declined')}
          disabled={pending}
        />
        <Button label="Approve" onPress={() => decide('active')} disabled={pending} />
      </View>
    </View>
  );
}

function ReminderRow({ reminder }: { reminder: Reminder }) {
  const colors = useColors();
  const change = useChangeReminder();
  const on = reminder.status === 'active';
  const pending = change.isPending && change.variables?.id === reminder.id;
  const when = on ? dueText(reminder.nextDueAt) : null;
  const via =
    reminder.channels.length === 2
      ? 'app and email'
      : reminder.channels[0] === 'email'
        ? 'email'
        : 'app';

  return (
    <Row
      title={reminder.title}
      detail={
        on
          ? `${reminder.scheduleText}${when ? ` · next ${when}` : ''} · by ${via}`
          : `Paused · ${reminder.scheduleText}`
      }
      onPress={() => router.push(`/reminder/${reminder.id}`)}
      accessory={
        <Switch
          accessibilityLabel={`${reminder.title} ${on ? 'on' : 'paused'}`}
          value={on}
          disabled={pending}
          onValueChange={(value) => {
            select();
            change.mutate({
              id: reminder.id,
              change: { version: reminder.version, status: value ? 'active' : 'paused' },
            });
          }}
          trackColor={{ true: colors.accent, false: colors.track }}
          thumbColor="#FFFFFF"
          // react-native-web colors the "on" knob separately.
          {...({ activeThumbColor: '#FFFFFF' } as object)}
        />
      }
    />
  );
}

function SettingsSection() {
  const colors = useColors();
  const settings = useNotificationSettings();
  const update = useUpdateNotificationSettings();

  return (
    <Section
      title="How you hear from Patterns"
      footer="Quiet hours and the daily limit apply to suggestions and alerts. Reminders you set come at the time you chose."
    >
      <QueryState query={settings}>
        {() => {
          const current = update.isPending ? update.variables! : settings.data!;
          const save = (next: Partial<NotificationSettings>) =>
            update.mutate({ ...current, ...next });
          return (
            <View style={styles.settings}>
              <Row
                icon="mail-outline"
                title="Email me too"
                detail="When a reminder is set to send by email."
                accessory={
                  <Switch
                    accessibilityLabel="Email me too"
                    value={current.email}
                    onValueChange={(email) => save({ email })}
                    trackColor={{ true: colors.accent, false: colors.track }}
                    thumbColor="#FFFFFF"
                    {...({ activeThumbColor: '#FFFFFF' } as object)}
                  />
                }
              />
              <Text variant="caption" color="muted" style={styles.label}>
                Quiet hours
              </Text>
              <View style={styles.chips}>
                {QUIET_HOURS.map(({ label, value }) => (
                  <Chip
                    key={label}
                    label={label}
                    selected={JSON.stringify(value) === JSON.stringify(current.quietHours)}
                    onPress={() => save({ quietHours: value })}
                  />
                ))}
              </View>
              <Text variant="caption" color="muted" style={styles.label}>
                Suggestions and alerts per day, at most
              </Text>
              <View style={styles.chips}>
                {MAX_PER_DAY.map((n) => (
                  <Chip
                    key={n}
                    label={String(n)}
                    selected={current.maxPerDay === n}
                    onPress={() => save({ maxPerDay: n })}
                  />
                ))}
              </View>
              {update.error && (
                <Text variant="caption" color="danger">
                  Could not save. Please try again.
                </Text>
              )}
            </View>
          );
        }}
      </QueryState>
    </Section>
  );
}

const ALERT_KINDS: { kind: AlarmKind; label: string }[] = [
  { kind: 'day', label: 'A day far from usual' },
  { kind: 'streak', label: 'Several days running' },
  { kind: 'finding', label: 'Two-week changes' },
  { kind: 'data', label: 'Data and sync' },
];
const SENSITIVITY: { value: AlarmSettings['sensitivity']; label: string }[] = [
  { value: 'fewer', label: 'Fewer' },
  { value: 'normal', label: 'Normal' },
  { value: 'more', label: 'More' },
];

/** Alerts Patterns sends by itself when something in the data looks off. */
function AlertSettings() {
  const colors = useColors();
  const settings = useAlarmSettings();
  const update = useUpdateAlarmSettings();
  return (
    <Section
      title="Alerts"
      footer="Patterns checks your data through the day and tells you when something stands out, like a night far below your usual. Each alert links to its numbers. Patterns in your data, not medical advice."
    >
      <QueryState query={settings}>
        {() => {
          const current = update.isPending ? update.variables! : settings.data!;
          const save = (next: Partial<AlarmSettings>) => update.mutate({ ...current, ...next });
          return (
            <View style={styles.settings}>
              <Row
                icon="pulse-outline"
                title="Send me alerts"
                accessory={
                  <Switch
                    accessibilityLabel="Send me alerts"
                    value={current.enabled}
                    onValueChange={(enabled) => save({ enabled })}
                    trackColor={{ true: colors.accent, false: colors.track }}
                    thumbColor="#FFFFFF"
                    {...({ activeThumbColor: '#FFFFFF' } as object)}
                  />
                }
              />
              {current.enabled && (
                <>
                  <Text variant="caption" color="muted" style={styles.label}>
                    About
                  </Text>
                  <View style={styles.chips}>
                    {ALERT_KINDS.map(({ kind, label }) => {
                      const on = !current.mutedKinds.includes(kind);
                      return (
                        <Chip
                          key={kind}
                          label={label}
                          selected={on}
                          onPress={() =>
                            save({
                              mutedKinds: on
                                ? [...current.mutedKinds, kind]
                                : current.mutedKinds.filter((k) => k !== kind),
                            })
                          }
                        />
                      );
                    })}
                  </View>
                  <Text variant="caption" color="muted" style={styles.label}>
                    How many
                  </Text>
                  <View style={styles.chips}>
                    {SENSITIVITY.map(({ value, label }) => (
                      <Chip
                        key={value}
                        label={label}
                        selected={current.sensitivity === value}
                        onPress={() => save({ sensitivity: value })}
                      />
                    ))}
                  </View>
                </>
              )}
              {update.error && (
                <Text variant="caption" color="danger">
                  Could not save. Please try again.
                </Text>
              )}
            </View>
          );
        }}
      </QueryState>
    </Section>
  );
}

const styles = StyleSheet.create({
  add: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  suggestion: { gap: 4, paddingVertical: spacing.md },
  actions: { flexDirection: 'row', gap: spacing.sm, justifyContent: 'flex-end', marginTop: 4 },
  settings: { paddingBottom: spacing.md },
  label: { marginTop: spacing.md, marginBottom: spacing.xs },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  feedback: { marginLeft: 36, marginTop: -6, marginBottom: spacing.sm },
  feedbackRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
});
