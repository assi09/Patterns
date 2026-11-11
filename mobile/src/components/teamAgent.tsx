import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { ApiError } from '@/api/http';
import {
  useAddTeamNote,
  useAskTeamAgent,
  useDecideTeamAction,
  useDeleteTeamNote,
  useRateTeamAnswer,
  useTeamActions,
  useTeamAlerts,
  useTeamChat,
  useTeamNotes,
} from '@/api/hooks';
import type { TeamAction } from '@/api/types';
import { RatingButtons } from '@/components/chat';
import { Row, Section } from '@/components/list';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { fonts, radius, spacing, useColors } from '@/theme';

const SUGGESTIONS = [
  'How has the team been lately?',
  'Is anything lasting, or just one week?',
  'What could we try as a team?',
];

/** Changes in the team's aggregate, raised once by the daily check (docs/teams.md). */
export function AlertsSection({ teamId }: { teamId: string }) {
  const alerts = useTeamAlerts(teamId);
  const open = (alerts.data ?? []).filter((a) => !a.resolvedAt);
  const ended = (alerts.data ?? []).filter((a) => a.resolvedAt).slice(0, 3);
  if (!open.length && !ended.length) return null;
  return (
    <Section
      title="Alerts"
      footer="Team figures from at least five people. A change has to hold for several days before it is raised."
    >
      {open.map((alert) => (
        <Row
          key={alert.id}
          icon={alert.direction === 'up' ? 'trending-up' : 'trending-down'}
          title={alert.label}
          detail={alert.text}
          value="Ongoing"
        />
      ))}
      {ended.map((alert) => (
        <Row
          key={alert.id}
          icon="checkmark-circle-outline"
          title={alert.label}
          detail={alert.text}
          value="Ended"
        />
      ))}
    </Section>
  );
}

/** The supervisor's conversation with the team agent. */
export function TeamChatSection({ teamId }: { teamId: string }) {
  const colors = useColors();
  const chat = useTeamChat(teamId);
  const ask = useAskTeamAgent(teamId);
  const rate = useRateTeamAnswer(teamId);
  const [text, setText] = useState('');
  const send = (question: string) => {
    if (!question.trim() || ask.isPending) return;
    ask.mutate(question.trim(), { onSuccess: () => setText('') });
  };
  const messages = chat.data ?? [];
  return (
    <Section
      title="Ask about your team"
      footer="Answers come from team figures only and never describe one person. Proposals wait for your approval."
    >
      {messages.length === 0 && !ask.isPending ? (
        <View style={styles.suggestions}>
          {SUGGESTIONS.map((s) => (
            <Button key={s} label={s} variant="secondary" onPress={() => send(s)} />
          ))}
        </View>
      ) : null}
      {messages.slice(-8).map((message, at) => (
        <View
          key={message.id ?? `${message.createdAt}-${at}`}
          style={[styles.message, { borderColor: colors.border }]}
        >
          <Text variant="caption" color="faint">
            {message.role === 'supervisor' ? 'You' : 'Team agent'}
          </Text>
          <Text color={message.role === 'supervisor' ? 'muted' : 'text'}>{message.text}</Text>
          {message.role === 'agent' && message.id ? (
            <View style={styles.rating}>
              <RatingButtons
                rating={message.rating}
                onRate={(rating) => rate.mutate({ id: message.id, rating })}
              />
            </View>
          ) : null}
        </View>
      ))}
      {ask.isPending ? (
        <View style={[styles.message, { borderColor: colors.border }]}>
          <Text variant="caption" color="faint">
            Team agent
          </Text>
          <Text color="muted">Looking at the team&apos;s figures…</Text>
        </View>
      ) : null}
      <View style={styles.field}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="Ask about the team, or tell it about a deadline"
          placeholderTextColor={colors.faint}
          maxLength={600}
          onSubmitEditing={() => send(text)}
          accessibilityLabel="Ask the team agent"
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
        <Button label="Send" disabled={!text.trim() || ask.isPending} onPress={() => send(text)} />
      </View>
      {ask.error ? <ErrorLine error={ask.error} /> : null}
    </Section>
  );
}

function when(action: TeamAction): string {
  if (action.kind !== 'challenge' || !action.startsOn || !action.endsOn)
    return 'A note to everyone';
  return `A challenge, ${action.startsOn} to ${action.endsOn}`;
}

/** What the agent proposed for the whole team; nothing reaches members before approval. */
export function ProposalsSection({ teamId }: { teamId: string }) {
  const actions = useTeamActions(teamId);
  const decide = useDecideTeamAction(teamId);
  const [told, setTold] = useState<string | null>(null);
  const waiting = (actions.data ?? []).filter((a) => a.status === 'proposed');
  const decided = (actions.data ?? []).filter((a) => a.status !== 'proposed').slice(0, 4);
  if (!waiting.length && !decided.length) return null;
  return (
    <Section
      title="Proposals"
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
export function NotesSection({ teamId }: { teamId: string }) {
  const colors = useColors();
  const notes = useTeamNotes(teamId);
  const add = useAddTeamNote(teamId);
  const remove = useDeleteTeamNote(teamId);
  const [text, setText] = useState('');
  const save = () => text.trim() && add.mutate(text.trim(), { onSuccess: () => setText('') });
  return (
    <Section
      title="Team notes"
      footer="Deadlines, releases or travel help the agent line changes up with what the team was doing. Nothing about one person."
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
          placeholder="e.g. Release deadline Nov 3"
          placeholderTextColor={colors.faint}
          maxLength={300}
          onSubmitEditing={save}
          accessibilityLabel="New team note"
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
        <Button label="Add" disabled={!text.trim() || add.isPending} onPress={save} />
      </View>
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
  suggestions: { gap: spacing.sm, paddingVertical: spacing.md, alignItems: 'flex-start' },
  rating: { flexDirection: 'row', gap: spacing.xs, marginLeft: -spacing.xs },
  message: {
    gap: 2,
    paddingVertical: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
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
