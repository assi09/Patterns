import { Ionicons } from '@expo/vector-icons';
import { Stack } from 'expo-router';
import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  useAskTeamAgent,
  useDecideTeamAction,
  useRateTeamAnswer,
  useTeamChat,
  useTeams,
} from '@/api/hooks';
import type { TeamAction, TeamChatMessage } from '@/api/types';
import { RatingButtons } from '@/components/chat';
import { Text } from '@/components/Text';
import { Button, Chip } from '@/components/ui';
import { useStickToBottom } from '@/lib/stickToBottom';
import { CONTENT_WIDTH, fonts, radius, spacing, useColors } from '@/theme';

const SUGGESTIONS = [
  'How has the team been lately?',
  'Is anything lasting, or just one week?',
  'What could we try as a team?',
  'We have a release deadline on Friday.',
];
const MAX_LENGTH = 600;

/** The supervisor's conversation with the team agent, on a page of its own. */
export default function TeamChatScreen() {
  const teams = useTeams();
  const team = teams.data?.[0];
  return (
    <>
      <Stack.Screen options={{ title: team ? `Ask about ${team.name}` : 'Ask about your team' }} />
      {team ? <Conversation teamId={team.id} /> : null}
    </>
  );
}

function Conversation({ teamId }: { teamId: string }) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const chat = useTeamChat(teamId);
  const ask = useAskTeamAgent(teamId);
  const rate = useRateTeamAnswer(teamId);
  const { ref, onScroll, onContentSizeChange, onLayout, showJump, pin } = useStickToBottom();
  const [text, setText] = useState('');
  const [proposed, setProposed] = useState<TeamAction[]>([]);
  const messages = chat.data ?? [];

  const send = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;
    pin();
    ask.mutate(trimmed, {
      onSuccess: (reply) => {
        setText('');
        setProposed(reply.proposed);
      },
    });
  };

  return (
    <KeyboardAvoidingView
      style={[styles.page, { backgroundColor: colors.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 64 : 0}
    >
      <View style={{ flex: 1 }}>
        <ScrollView
          ref={ref}
          style={{ flex: 1 }}
          contentContainerStyle={styles.messages}
          keyboardShouldPersistTaps="handled"
          onScroll={onScroll}
          onContentSizeChange={onContentSizeChange}
          onLayout={onLayout}
          scrollEventThrottle={32}
        >
          {messages.length === 0 && !ask.isPending ? (
            <View style={styles.empty}>
              <Text variant="headline">What do you want to know about the team?</Text>
              <Text color="muted">
                Answers come from team figures of at least five people, never one person. Tell it
                about deadlines or travel and it will line them up with the team&apos;s data.
              </Text>
              <View style={styles.suggestions}>
                {SUGGESTIONS.map((s) => (
                  <Chip key={s} label={s} onPress={() => send(s)} />
                ))}
              </View>
            </View>
          ) : null}
          {messages.map((message, at) => (
            <Message
              key={message.id ?? `${message.createdAt}-${at}`}
              message={message}
              onRate={(rating) => rate.mutate({ id: message.id, rating })}
            />
          ))}
          {ask.isPending ? (
            <>
              <Mine text={ask.variables ?? ''} />
              <Text color="muted" style={styles.thinking}>
                Looking at the team&apos;s figures…
              </Text>
            </>
          ) : null}
          {proposed.map((action) => (
            <Proposal key={action.id} teamId={teamId} action={action} />
          ))}
          {ask.error ? (
            <Text variant="caption" color="danger" style={styles.error}>
              {ask.error.message || 'Could not send that.'} Try again.
            </Text>
          ) : null}
        </ScrollView>
        {showJump ? (
          <View style={styles.jump} pointerEvents="box-none">
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Jump to the latest message"
              onPress={() => pin()}
              style={[
                styles.jumpButton,
                { backgroundColor: colors.surfaceRaised, borderColor: colors.border },
              ]}
            >
              <Ionicons name="arrow-down" size={18} color={colors.text} />
            </Pressable>
          </View>
        ) : null}
      </View>
      <View style={[styles.composer, { paddingBottom: insets.bottom + spacing.sm }]}>
        <View
          style={[styles.field, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder="Ask about the team, or tell it about a deadline"
            placeholderTextColor={colors.faint}
            maxLength={MAX_LENGTH}
            multiline
            onSubmitEditing={() => send(text)}
            blurOnSubmit
            accessibilityLabel="Ask the team agent"
            style={[styles.input, { color: colors.text }]}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Send"
            disabled={!text.trim() || ask.isPending}
            onPress={() => send(text)}
            style={[
              styles.send,
              { backgroundColor: text.trim() && !ask.isPending ? colors.accent : colors.track },
            ]}
          >
            <Ionicons name="arrow-up" size={18} color={colors.onAccent} />
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

function Mine({ text }: { text: string }) {
  const colors = useColors();
  return (
    <View
      style={[styles.mine, { backgroundColor: colors.surfaceRaised, borderColor: colors.border }]}
    >
      <Text>{text}</Text>
    </View>
  );
}

function Message({
  message,
  onRate,
}: {
  message: TeamChatMessage;
  onRate: (rating: 'up' | 'down' | null) => void;
}) {
  if (message.role === 'supervisor') return <Mine text={message.text} />;
  return (
    <View style={styles.answer}>
      <Text variant="caption" color="faint">
        Team agent
      </Text>
      <Text>{message.text}</Text>
      {message.id ? (
        <View style={styles.rating}>
          <RatingButtons rating={message.rating} onRate={onRate} />
        </View>
      ) : null}
    </View>
  );
}

/** A proposal from this answer, decided right here; it also waits on the Team tab. */
function Proposal({ teamId, action }: { teamId: string; action: TeamAction }) {
  const colors = useColors();
  const decide = useDecideTeamAction(teamId);
  const [done, setDone] = useState<string>();
  return (
    <View style={[styles.proposal, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Text variant="caption" color="faint">
        Proposed for your approval
      </Text>
      <Text style={styles.proposalTitle}>{action.title}</Text>
      <Text color="muted">{action.body}</Text>
      {done ? (
        <Text variant="caption" color="muted">
          {done}
        </Text>
      ) : (
        <View style={styles.buttons}>
          <Button
            label="Approve"
            disabled={decide.isPending}
            onPress={() =>
              decide.mutate(
                { actionId: action.id, approve: true },
                { onSuccess: (r) => setDone(`Sent to ${r.membersTold} people.`) },
              )
            }
          />
          <Button
            label="Decline"
            variant="secondary"
            disabled={decide.isPending}
            onPress={() =>
              decide.mutate(
                { actionId: action.id, approve: false },
                { onSuccess: () => setDone('Declined.') },
              )
            }
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  messages: {
    width: '100%',
    maxWidth: CONTENT_WIDTH,
    alignSelf: 'center',
    padding: spacing.lg,
    gap: spacing.lg,
    flexGrow: 1,
  },
  empty: { gap: spacing.md, marginTop: spacing.xl },
  suggestions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  mine: {
    alignSelf: 'flex-end',
    maxWidth: '85%',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
  },
  answer: { gap: spacing.xs, maxWidth: '92%' },
  rating: { flexDirection: 'row', gap: spacing.xs, marginLeft: -spacing.xs },
  thinking: { fontStyle: 'italic' },
  error: { textAlign: 'center' },
  proposal: {
    gap: spacing.xs,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  proposalTitle: { fontFamily: fonts.semibold },
  buttons: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  jump: { position: 'absolute', bottom: spacing.md, left: 0, right: 0, alignItems: 'center' },
  jumpButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  composer: {
    width: '100%',
    maxWidth: CONTENT_WIDTH,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  field: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    paddingLeft: spacing.md,
    paddingRight: spacing.xs,
    paddingVertical: spacing.xs,
  },
  input: { flex: 1, fontFamily: fonts.regular, fontSize: 15, maxHeight: 140, paddingVertical: 8 },
  send: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
});
