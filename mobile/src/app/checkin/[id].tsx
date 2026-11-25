import { Stack, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { useMyCheckins, useWithdrawCheckin } from '@/api/hooks';
import type { CheckinEvidence, OwnCheckin } from '@/api/types';
import { Row, Section } from '@/components/list';
import { QueryState, Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { formatWithUnit, metricLabel, timeAgo, windowLabel } from '@/lib/format';
import { spacing } from '@/theme';

/**
 * The person's own check-in alert (docs/escalation.md): why it was raised, who will be asked to
 * check in and when, and a way to stop it while it waits. Only this person sees the evidence.
 */
export default function CheckinScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const checkins = useMyCheckins();
  return (
    <Screen refreshing={checkins.isRefetching} onRefresh={checkins.refetch}>
      <Stack.Screen options={{ title: 'Check-in alert' }} />
      <QueryState query={checkins}>
        {() => {
          const alert = checkins.data!.find((c) => c.id === id);
          return alert ? <Alert alert={alert} /> : <Text color="muted">This alert is gone.</Text>;
        }}
      </QueryState>
    </Screen>
  );
}

/** "Tomorrow at 13:34", in the device's own time. */
function sendTime(iso: string): string {
  const when = new Date(iso);
  const time = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const day =
    when.toDateString() === new Date().toDateString()
      ? 'Today'
      : when.toDateString() === tomorrow.toDateString()
        ? 'Tomorrow'
        : when.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' });
  return `${day} at ${time}`;
}

function Alert({ alert }: { alert: OwnCheckin }) {
  const withdraw = useWithdrawCheckin();
  const status =
    alert.status === 'waiting'
      ? `Nothing is sent yet. ${sendTime(alert.sendAfter)}, ${alert.recipients} will be asked to check in with you.`
      : alert.status === 'sent'
        ? `Sent ${timeAgo(alert.sentAt!)} to ${alert.recipients}. They saw your name only, no values or reasons.`
        : `Stopped ${timeAgo(alert.withdrawnAt!)}. Nothing was sent, and check-in alerts are off for ${alert.team}.`;
  return (
    <>
      <Section title={alert.team}>
        <View style={styles.block}>
          <Text variant="headline">
            {alert.status === 'waiting'
              ? 'A check-in alert is waiting'
              : alert.status === 'sent'
                ? 'Check-in alert sent'
                : 'Check-in alert stopped'}
          </Text>
          <Text color="muted">{status}</Text>
        </View>
        {alert.status === 'waiting' ? (
          <View style={styles.block}>
            <Button
              label="Stop it and turn check-in alerts off"
              variant="secondary"
              disabled={withdraw.isPending}
              onPress={() => withdraw.mutate(alert.id)}
            />
            {withdraw.error ? <Text color="danger">{withdraw.error.message}</Text> : null}
          </View>
        ) : null}
      </Section>
      <Section
        title="What raised it"
        footer="Your own data, each signal against your own usual range: the middle half of the four weeks before. Only you see this. Patterns in your data, not medical advice."
      >
        {alert.evidence.map((e) => (
          <Signal key={e.id} evidence={e} />
        ))}
      </Section>
    </>
  );
}

function Signal({ evidence: e }: { evidence: CheckinEvidence }) {
  const usual = `${formatWithUnit(e.metric, e.usualLow)} to ${formatWithUnit(e.metric, e.usualHigh)}`;
  const side = e.direction === 'down' ? 'below' : 'above';
  return (
    <Row
      icon={e.direction === 'down' ? 'trending-down-outline' : 'trending-up-outline'}
      title={metricLabel(e.metric)}
      detail={`Far ${side} your usual (${usual}) on ${e.daysFar} of ${e.daysWorn} days, ${windowLabel(e.recent)}; averaged ${formatWithUnit(e.metric, e.recentMean)}`}
    />
  );
}

const styles = StyleSheet.create({
  block: { gap: spacing.sm, paddingVertical: spacing.md },
});
