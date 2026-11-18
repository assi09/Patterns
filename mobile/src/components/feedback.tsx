import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { useSendFeedback } from '@/api/hooks';
import type { FeedbackIn } from '@/api/types';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { fonts, radius, spacing, useColors } from '@/theme';

export const FEEDBACK_MAX = 2000;

const COPY = {
  report: {
    title: 'Report this answer',
    hint: 'What was wrong or confusing? A wrong number, a missing point, something that read oddly.',
    placeholder: 'e.g. My steps were higher than this on Monday',
  },
  feedback: {
    title: 'Feedback on this chat',
    hint: 'Anything about this chat or the app: what helped, what did not, what you wish it did.',
    placeholder: 'Write as much or as little as you like',
  },
} as const;

/** A short form that sends a tester's note to the team: about one answer, or a whole chat. Keyed
 * by its target where it is used, so each opening starts empty. */
export function FeedbackSheet({
  target,
  onClose,
}: {
  target: Omit<FeedbackIn, 'text'> | null; // null: closed
  onClose: () => void;
}) {
  const colors = useColors();
  const send = useSendFeedback();
  const [text, setText] = useState('');
  const [sent, setSent] = useState(false);

  if (!target) return null;
  const copy = COPY[target.kind];
  const ready = text.trim().length > 0 && text.length <= FEEDBACK_MAX && !send.isPending;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.backdrop}
      >
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="Close" />
        <View
          style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          {sent ? (
            <>
              <Text variant="headline">Thanks, it&apos;s with the team</Text>
              <Text color="muted">We read every note and may reply by email.</Text>
              <View style={styles.buttons}>
                <Button label="Done" onPress={onClose} />
              </View>
            </>
          ) : (
            <>
              <Text variant="headline">{copy.title}</Text>
              <Text color="muted">{copy.hint}</Text>
              <TextInput
                value={text}
                onChangeText={setText}
                placeholder={copy.placeholder}
                placeholderTextColor={colors.faint}
                multiline
                autoFocus
                maxLength={FEEDBACK_MAX}
                accessibilityLabel={copy.title}
                style={[
                  styles.input,
                  {
                    color: colors.text,
                    borderColor: colors.border,
                    backgroundColor: colors.background,
                  },
                ]}
              />
              {send.error ? (
                <Text color="danger" variant="caption">
                  {send.error.message}
                </Text>
              ) : (
                <Text color="faint" variant="caption">
                  {text.length > FEEDBACK_MAX - 200
                    ? `${FEEDBACK_MAX - text.length} characters left`
                    : 'Sent to the Patterns team with your email, so we can follow up.'}
                </Text>
              )}
              <View style={styles.buttons}>
                <Button label="Cancel" variant="secondary" onPress={onClose} />
                <Button
                  label={send.isPending ? 'Sending…' : 'Send'}
                  disabled={!ready}
                  onPress={() =>
                    send.mutate(
                      { ...target, text: text.trim() },
                      { onSuccess: () => setSent(true) },
                    )
                  }
                />
              </View>
            </>
          )}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
    backgroundColor: 'rgba(0,0,0,0.4)',
  },
  card: {
    width: '100%',
    maxWidth: 480,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: spacing.lg,
    gap: spacing.md,
  },
  input: {
    minHeight: 120,
    maxHeight: 260,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    fontFamily: fonts.regular,
    fontSize: 16,
    textAlignVertical: 'top',
  },
  buttons: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
});
