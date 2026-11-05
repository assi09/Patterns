import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, View } from 'react-native';

import { useDecideMemory, useMemory } from '@/api/hooks';
import type { MemoryFact } from '@/api/types';
import { Text } from '@/components/Text';
import { Button, Card } from '@/components/ui';
import { select, success } from '@/lib/haptics';
import { factDetail } from '@/lib/memory';
import { spacing, useColors } from '@/theme';

/** One thing the person said that Patterns would like to keep. Nothing is kept without this tap. */
export function MemoryChoice({ fact }: { fact: MemoryFact }) {
  const colors = useColors();
  const decide = useDecideMemory();
  const choose = (keep: boolean) =>
    decide.mutate({ id: fact.id, keep }, { onSuccess: () => (keep ? success() : select()) });
  return (
    <Card style={styles.card}>
      <View style={styles.head}>
        <Ionicons name="bookmark-outline" size={16} color={colors.accent} />
        <Text variant="caption" color="muted">
          Keep this in mind?
        </Text>
      </View>
      <Text>{fact.text}</Text>
      {fact.start && (
        <Text variant="caption" color="muted">
          {factDetail(fact)}
        </Text>
      )}
      <View style={styles.buttons}>
        <Button label="Keep" onPress={() => choose(true)} disabled={decide.isPending} />
        <Button
          label="No thanks"
          variant="secondary"
          onPress={() => choose(false)}
          disabled={decide.isPending}
        />
      </View>
    </Card>
  );
}

/** What is waiting for the person's tap, under the latest answer in the chat. */
export function MemoryPrompts() {
  const memory = useMemory();
  return (
    <>
      {memory.data?.waiting.slice(0, 2).map((fact) => (
        <MemoryChoice key={fact.id} fact={fact} />
      ))}
    </>
  );
}

/** The same choice on an inbox entry, for as long as the fact still waits. */
export function InboxMemoryChoice({ factId }: { factId: string }) {
  const memory = useMemory();
  const fact = memory.data?.waiting.find((f) => f.id === factId);
  return fact ? <MemoryChoice fact={fact} /> : null;
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, marginTop: spacing.sm },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  buttons: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
});
