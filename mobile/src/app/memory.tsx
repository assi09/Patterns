import { useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import {
  useForgetEpisode,
  useForgetMemory,
  useMemory,
  useMuteInterest,
  useRewordMemory,
} from '@/api/hooks';
import type { MemoryFact } from '@/api/types';
import { Row, Section } from '@/components/list';
import { MemoryChoice } from '@/components/MemoryPrompt';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { capitalized, factDetail, isEmpty } from '@/lib/memory';
import { fonts, radius, spacing, useColors } from '@/theme';

const MAX_CHARS = 120;

/** "What Patterns knows about you": everything held, and the person's say over all of it. */
export default function MemoryScreen() {
  const memory = useMemory();
  const mute = useMuteInterest();
  const forgetEpisode = useForgetEpisode();
  const forget = useForgetMemory();
  const page = memory.data;

  if (memory.isError) {
    return (
      <Screen title="What Patterns knows">
        <Text color="muted">This did not load. Check your connection and try again.</Text>
        <Button label="Try again" variant="secondary" onPress={() => memory.refetch()} />
      </Screen>
    );
  }
  if (!page) {
    return (
      <Screen title="What Patterns knows">
        <Skeleton height={120} />
      </Screen>
    );
  }
  return (
    <Screen title="What Patterns knows">
      <Text color="muted">
        Yours to change. Patterns only uses what you chose to keep, what your chats found, and what
        you often look at.
      </Text>

      {isEmpty(page) && (
        <Text color="muted" style={styles.empty}>
          Nothing yet. Tell Patterns about your routine or a goal, or say “remember that…”, and it
          will ask before keeping it.
        </Text>
      )}

      {page.waiting.length > 0 && (
        <Section title="Waiting for you">
          {page.waiting.map((fact) => (
            <MemoryChoice key={fact.id} fact={fact} />
          ))}
        </Section>
      )}

      {page.kept.length > 0 && (
        <Section title="Kept in mind">
          {page.kept.map((fact) => (
            <KeptFact key={fact.id} fact={fact} />
          ))}
        </Section>
      )}

      {page.interests.length > 0 && (
        <Section
          title="You often look at"
          footer="Learned from what you ask about and open. It fades if you stop."
        >
          {page.interests.map((interest) => (
            <Row
              key={interest.topic}
              title={capitalized(interest.label)}
              accessory={
                <TextAction
                  label="Not me"
                  hint={`Stop counting ${interest.label}`}
                  onPress={() => mute.mutate(interest.topic)}
                />
              }
            />
          ))}
        </Section>
      )}

      {page.episodes.length > 0 && (
        <Section title="From your chats" footer="What your chats found, kept for 90 days.">
          {page.episodes.map((episode) => (
            <Row
              key={episode.id}
              title={episode.text}
              accessory={
                <TextAction
                  label="Remove"
                  hint={`Remove: ${episode.text}`}
                  onPress={() => forgetEpisode.mutate(episode.id)}
                />
              }
            />
          ))}
        </Section>
      )}

      {page.noticed.length > 0 && (
        <Section
          title="Noticed once"
          footer="Not used for anything. It goes after 30 days unless you say it again."
        >
          {page.noticed.map((fact) => (
            <Row
              key={fact.id}
              title={fact.text}
              detail={factDetail(fact)}
              accessory={
                <TextAction
                  label="Remove"
                  hint={`Remove: ${fact.text}`}
                  onPress={() => forget.mutate(fact.id)}
                />
              }
            />
          ))}
        </Section>
      )}
    </Screen>
  );
}

function TextAction({
  label,
  hint,
  onPress,
}: {
  label: string;
  hint: string;
  onPress: () => void;
}) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={hint} onPress={onPress} hitSlop={8}>
      <Text variant="caption" color="accent">
        {label}
      </Text>
    </Pressable>
  );
}

/** A kept fact: tapping it opens its wording, to change or remove. */
function KeptFact({ fact }: { fact: MemoryFact }) {
  const colors = useColors();
  const reword = useRewordMemory();
  const forget = useForgetMemory();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(fact.text);

  if (!editing) {
    return (
      <Row
        title={fact.text}
        detail={factDetail(fact)}
        onPress={() => setEditing(true)}
        accessibilityLabel={`${fact.text}. Tap to change or remove.`}
      />
    );
  }
  const save = () =>
    reword.mutate({ id: fact.id, text: text.trim() }, { onSuccess: () => setEditing(false) });
  return (
    <View style={styles.editing}>
      <TextInput
        value={text}
        onChangeText={setText}
        maxLength={MAX_CHARS}
        autoFocus
        accessibilityLabel="What to keep in mind"
        style={[
          styles.input,
          { color: colors.text, borderColor: colors.border, backgroundColor: colors.surface },
        ]}
      />
      {reword.isError && (
        <Text variant="caption" color="danger">
          {reword.error.message}
        </Text>
      )}
      <View style={styles.buttons}>
        <Button label="Save" onPress={save} disabled={!text.trim() || reword.isPending} />
        <Button
          label="Cancel"
          variant="secondary"
          onPress={() => {
            setText(fact.text);
            reword.reset();
            setEditing(false);
          }}
        />
        <View style={styles.spacer} />
        <TextAction
          label="Remove"
          hint={`Remove: ${fact.text}`}
          onPress={() => forget.mutate(fact.id)}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: { marginTop: spacing.md },
  editing: { gap: spacing.sm, paddingVertical: spacing.sm },
  input: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontFamily: fonts.regular,
    fontSize: 16,
  },
  buttons: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  spacer: { flex: 1 },
});
