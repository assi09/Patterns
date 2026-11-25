import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { useMarkCheckin, useReceivedCheckins } from '@/api/hooks';
import type { CheckinMark, ReceivedCheckin } from '@/api/types';
import { Row, Section } from '@/components/list';
import { QueryState, Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { timeAgo } from '@/lib/format';
import { radius, spacing, useColors } from '@/theme';

const OUTCOME = { checked_in: 'Checked in', not_needed: 'Not needed' } as const;

/**
 * HR and supervisors: people who agreed to check-in alerts and whose own data met the agreed
 * rule. Who, which team and when, never why (docs/escalation.md).
 */
export default function CheckinsScreen() {
  const checkins = useReceivedCheckins();
  return (
    <Screen title="Check-ins" refreshing={checkins.isRefetching} onRefresh={checkins.refetch}>
      <QueryState query={checkins}>
        {() => {
          const all = checkins.data!;
          const open = all.filter((c) => !c.mine.outcome);
          const done = all.filter((c) => c.mine.outcome);
          return (
            <>
              <Section
                title={open.length ? `To check in · ${open.length}` : 'To check in'}
                footer="Each person turned check-in alerts on themselves and was told first. You see their name only: no values, metrics or reasons."
              >
                {open.length === 0 ? (
                  <Row icon="checkmark-circle-outline" title="Nothing waiting" />
                ) : (
                  open.map((c) => <Open key={c.id} checkin={c} />)
                )}
              </Section>
              {done.length > 0 ? (
                <Section title="Done">
                  {done.map((c) => (
                    <Row
                      key={c.id}
                      icon="checkmark-done-outline"
                      title={c.person}
                      detail={`${OUTCOME[c.mine.outcome!]} · ${c.team} · sent ${timeAgo(c.sentAt)}${c.note ? ` · ${c.note}` : ''}`}
                    />
                  ))}
                </Section>
              ) : null}
            </>
          );
        }}
      </QueryState>
    </Screen>
  );
}

function others(marks: CheckinMark[]): string {
  return marks
    .map(
      (m) =>
        `${m.role === 'hr' ? 'HR' : 'Supervisor'}: ${m.outcome ? OUTCOME[m.outcome] : 'not yet'}`,
    )
    .join(' · ');
}

function Open({ checkin }: { checkin: ReceivedCheckin }) {
  const colors = useColors();
  const mark = useMarkCheckin();
  const [note, setNote] = useState('');
  const save = (outcome: 'checked_in' | 'not_needed') =>
    mark.mutate({ id: checkin.id, outcome, note: note.trim() || undefined });
  return (
    <View style={styles.card}>
      <Text variant="headline">Please check in with {checkin.person}</Text>
      <Text color="muted">
        {checkin.team} · sent {timeAgo(checkin.sentAt)}
        {checkin.others.length ? ` · ${others(checkin.others)}` : ''}
      </Text>
      <TextInput
        value={note}
        onChangeText={setNote}
        placeholder="A note for yourself (optional)"
        placeholderTextColor={colors.faint}
        maxLength={500}
        accessibilityLabel={`Note about ${checkin.person}`}
        style={[
          styles.input,
          { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
        ]}
      />
      <View style={styles.buttons}>
        <Button label="Checked in" disabled={mark.isPending} onPress={() => save('checked_in')} />
        <Button
          label="Not needed"
          variant="secondary"
          disabled={mark.isPending}
          onPress={() => save('not_needed')}
        />
      </View>
      {mark.error ? <Text color="danger">{mark.error.message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm, paddingVertical: spacing.md },
  buttons: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  input: {
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
});
