import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import type { ComponentProps } from 'react';
import { StyleSheet, View } from 'react-native';

import type { ReportFinding, TeamReport } from '@/api/types';
import { Row, Section } from '@/components/list';
import { Text } from '@/components/Text';
import type { AreaReading, AreaState, TeamStatus } from '@/lib/team';
import { spacing, type as typeScale, useColors } from '@/theme';

type Colors = ReturnType<typeof useColors>;
type IconName = ComponentProps<typeof Ionicons>['name'];

/** Concerns in amber, good news in sky blue, the rest quiet: color only where it says something. */
export function stateColor(state: AreaState | TeamStatus['level'], colors: Colors): string {
  if (state === 'concern' || state === 'attention') return colors.warning;
  if (state === 'improvement' || state === 'good') return colors.secondary;
  if (state === 'change' || state === 'watch') return colors.text;
  return colors.muted;
}

const WORD: Record<AreaState, string> = {
  concern: 'Watch',
  change: 'Changed',
  improvement: 'Better',
  steady: 'Steady',
};

/** The top of the dashboard: one word for where the team stands, and the sentence behind it. */
export function TeamStatusLine({ status }: { status: TeamStatus }) {
  const colors = useColors();
  return (
    <View style={styles.status} accessibilityRole="summary">
      <Text style={[typeScale.title, { color: stateColor(status.level, colors) }]}>
        {status.title}
      </Text>
      <Text color="muted">{status.line}</Text>
    </View>
  );
}

/** Five areas at arm's length: a word each, coloured only when it changed. */
export function AreaStrip({ readings }: { readings: AreaReading[] }) {
  const colors = useColors();
  return (
    <View style={styles.areas}>
      {readings.map((reading) => (
        <View
          key={reading.key}
          style={styles.area}
          accessible
          accessibilityLabel={`${reading.label}: ${WORD[reading.state]}. ${reading.detail}`}
        >
          {/* Value first, as Today's numbers: the words line up whatever the label's length. */}
          <Text style={[typeScale.number, { color: stateColor(reading.state, colors) }]}>
            {WORD[reading.state]}
          </Text>
          <Text variant="caption" color="muted" numberOfLines={2}>
            {reading.label}
          </Text>
          <Text variant="caption" color="faint" numberOfLines={2}>
            {reading.detail}
          </Text>
        </View>
      ))}
    </View>
  );
}

/** The way into the team agent, now a page of its own. */
export function AskTeamRow({ teamId }: { teamId: string }) {
  return (
    <Section footer="Answers come from team figures only and never describe one person.">
      <Row
        icon="chatbubbles-outline"
        title="Ask about your team"
        detail="What changed, what lined up with it, what the team could try"
        onPress={() => router.push({ pathname: '/team-chat', params: { team: teamId } })}
      />
    </Section>
  );
}

const FINDING_ICON: Record<ReportFinding['kind'], IconName> = {
  concern: 'alert-circle-outline',
  change: 'swap-vertical-outline',
  improvement: 'arrow-up-circle-outline',
};

/** What last week's report leads with, then the challenges that ended and how they went. */
export function PrioritiesSection({ report }: { report: TeamReport }) {
  if (!report.priorities.length && !report.challenges.length) return null;
  return (
    <Section
      title="What to focus on"
      footer="Changes that held and were big and broad enough to matter, from at least five people."
    >
      {report.priorities.map((found) => (
        <Row
          key={`${found.metric}-${found.status}`}
          icon={FINDING_ICON[found.kind]}
          title={found.label}
          detail={found.text}
          value={found.status === 'lasting' ? 'Lasting' : 'New'}
        />
      ))}
      {report.challenges.map((challenge) => (
        <Row
          key={challenge.evidenceId}
          icon="flag-outline"
          title="Challenge"
          detail={challenge.text}
        />
      ))}
    </Section>
  );
}

const styles = StyleSheet.create({
  status: { gap: spacing.xs, marginTop: spacing.sm },
  areas: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: spacing.lg,
    rowGap: spacing.md,
    marginTop: spacing.lg,
  },
  // Five to a row on a wide screen, two or three on a phone.
  area: { flexBasis: 104, flexGrow: 1, gap: 2 },
});
