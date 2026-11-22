import { useState } from 'react';
import { type StyleProp, StyleSheet, TextInput, View, type ViewStyle } from 'react-native';

import { ApiError } from '@/api/http';
import {
  useAddTeamNote,
  useDecideTeamAction,
  useDeleteTeamNote,
  useTeamActions,
  useTeamAlerts,
  useTeamNotes,
} from '@/api/hooks';
import type { TeamAction } from '@/api/types';
import { Row, Section } from '@/components/list';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { fonts, radius, spacing, useColors } from '@/theme';


// Concerns first, then load and bedtime, then good news.
const KIND_ORDER = { concern: 0, change: 1, improvement: 2 };

/** Changes in the team's aggregate, raised once by the daily check (docs/teams.md). */
export function AlertsSection({
  teamId,
  style,
  endedOnly = false,
}: {
  teamId: string;
  style?: StyleProp<ViewStyle>;
  endedOnly?: boolean; // where the open ones are already in the briefing
}) {
  const alerts = useTeamAlerts(teamId);
  const open = endedOnly ? [] : (alerts.data ?? []).filter((a) => !a.resolvedAt);
  const ended = (alerts.data ?? []).filter((a) => a.resolvedAt).slice(0, 3);
  if (!open.length && !ended.length) return null;
  return (
    <Section
      style={style}
      title={endedOnly ? 'Earlier alerts' : 'Alerts'}
      footer="Team figures from at least five people. A change has to hold for several days before it is raised."
    >
      {[...open]
        .sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind])
        .map((alert) => (
          <Row
            key={alert.id}
            icon={alert.direction === 'up' ? 'trending-up' : 'trending-down'}
            title={alert.label}
            detail={alert.text}
            value={alert.kind === 'improvement' ? 'Good news' : 'Ongoing'}
          />
        ))}
      {ended.map((alert) => (
        <Row
          key={alert.id}
          icon="checkmark-circle-outline"
          title={alert.label}
          detail={alert.text}
          value={alert.kind === 'concern' ? 'Back to usual' : 'Ended'}
        />
      ))}
    </Section>
  );
}

function when(action: TeamAction): string {
  if (action.kind !== 'challenge' || !action.startsOn || !action.endsOn)
    return 'A note to everyone';
  return `A challenge, ${action.startsOn} to ${action.endsOn}`;
}

/** What the agent proposed for the whole team; nothing reaches members before approval. */
export function ProposalsSection({
  teamId,
  style,
}: {
  teamId: string;
  style?: StyleProp<ViewStyle>;
}) {
  const actions = useTeamActions(teamId);
  const decide = useDecideTeamAction(teamId);
  const [told, setTold] = useState<string | null>(null);
  const waiting = (actions.data ?? []).filter((a) => a.status === 'proposed');
  const decided = (actions.data ?? []).filter((a) => a.status !== 'proposed').slice(0, 4);
  if (!waiting.length && !decided.length) return null;
  return (
    <Section
      style={style}
      title="Waiting for you"
      footer="Approving sends it to every member's inbox, signed by no one."
    >
      {waiting.map((action) => (
        <View key={action.id} style={styles.proposal}>
          <Text variant="caption" color="faint">
            {when(action)}
          </Text>
          <Text style={styles.title}>{action.title}</Text>
          <Text color="muted">{action.body}</Text>
          <View style={styles.buttons}>
            <Button
              label="Approve"
              disabled={decide.isPending}
              onPress={() =>
                decide.mutate(
                  { actionId: action.id, approve: true },
                  {
                    onSuccess: (r) =>
                      setTold(
                        `Sent to ${r.membersTold} ${r.membersTold === 1 ? 'person' : 'people'}.`,
                      ),
                  },
                )
              }
            />
            <Button
              label="Decline"
              variant="secondary"
              disabled={decide.isPending}
              onPress={() => decide.mutate({ actionId: action.id, approve: false })}
            />
          </View>
        </View>
      ))}
      {told ? (
        <Text variant="caption" color="muted" style={styles.note}>
          {told}
        </Text>
      ) : null}
      {decided.map((action) => (
        <Row
          key={action.id}
          icon={action.status === 'approved' ? 'checkmark-circle-outline' : 'close-circle-outline'}
          title={action.title}
          detail={when(action)}
          value={action.status === 'approved' ? 'Approved' : 'Declined'}
        />
      ))}
      {decide.error ? <ErrorLine error={decide.error} /> : null}
    </Section>
  );
}

/** What the supervisor told the agent about the team's work, so changes can be lined up with it. */
export function NotesSection({
  teamId,
  style,
}: {
  teamId: string;
  style?: StyleProp<ViewStyle>;
}) {
  const colors = useColors();
  const notes = useTeamNotes(teamId);
  const add = useAddTeamNote(teamId);
  const remove = useDeleteTeamNote(teamId);
  const [text, setText] = useState('');
  const [date, setDate] = useState('');
  const parsed = new Date(date + 'T00:00:00Z');
  const validDate =
    !date || (!Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date);
  const save = () => {
    if (!text.trim() || !validDate || add.isPending) return;
    add.mutate(
      { text: text.trim(), date: date || undefined },
      {
        onSuccess: () => {
          setText('');
          setDate('');
        },
      },
    );
  };
  return (
    <Section
      style={style}
      title="Team notes"
      footer="Add an event date to compare past releases or deadlines with upcoming ones. Keep notes about the whole team."
    >
      {(notes.data ?? []).map((note) => (
        <Row
          key={note.id}
          icon="bookmark-outline"
          title={note.text}
          detail={
            note.startsOn
              ? `${note.startsOn}${note.endsOn && note.endsOn !== note.startsOn ? ` to ${note.endsOn}` : ''}`
              : undefined
          }
          value="Remove"
          onPress={() => remove.mutate(note.id)}
          accessibilityLabel={`Remove note: ${note.text}`}
        />
      ))}
      <View style={styles.field}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="e.g. Product release"
          placeholderTextColor={colors.faint}
          maxLength={300}
          onSubmitEditing={save}
          accessibilityLabel="New team note"
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
      </View>
      <View style={styles.field}>
        <TextInput
          value={date}
          onChangeText={setDate}
          maxLength={10}
          accessibilityLabel="Event date, YYYY-MM-DD"
          placeholder="Event date · YYYY-MM-DD"
          placeholderTextColor={colors.faint}
          onSubmitEditing={save}
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
        <Button label="Add" disabled={!validDate || !text.trim() || add.isPending} onPress={save} />
      </View>
      {!validDate ? <Text color="danger">Enter a valid date as YYYY-MM-DD.</Text> : null}
      {add.error ? <ErrorLine error={add.error} /> : null}
    </Section>
  );
}

function ErrorLine({ error }: { error: Error }) {
  const message = error instanceof ApiError ? error.message : 'Something went wrong. Try again.';
  return (
    <Text variant="caption" color="danger" style={styles.note}>
      {message}
    </Text>
  );
}

const styles = StyleSheet.create({
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.md,
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 16,
    paddingVertical: 11,
    fontFamily: fonts.regular,
    fontSize: 15,
  },
  proposal: { gap: spacing.xs, paddingVertical: spacing.md },
  title: { fontFamily: fonts.semibold },
  buttons: { flexDirection: 'row', gap: spacing.sm, paddingTop: spacing.sm },
  note: { paddingBottom: spacing.sm },
});
