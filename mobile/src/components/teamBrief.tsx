import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, View } from 'react-native';

import { stateColor } from '@/components/teamDashboard';
import { Text } from '@/components/Text';
import { Tile } from '@/components/widgets';
import type { TeamBriefing } from '@/api/types';
import {
  type AreaReading,
  type AreaState,
  type BriefingItem,
  briefingContent,
  type TeamStatus,
} from '@/lib/team';
import { fonts, radius, spacing, type as typeScale, useColors } from '@/theme';

const WORD: Record<AreaState, string> = {
  concern: 'Watch',
  change: 'Changed',
  improvement: 'Better',
  steady: 'Steady',
};

/** The five areas as chips: tinted where something moved, plain where the team held steady. */
export function AreaChips({ readings }: { readings: AreaReading[] }) {
  const colors = useColors();
  return (
    <View style={styles.chips}>
      {readings.map((reading) => {
        const color = stateColor(reading.state, colors);
        const moved = reading.state !== 'steady';
        return (
          <View
            key={reading.key}
            accessible
            accessibilityLabel={`${reading.label}: ${WORD[reading.state]}. ${reading.detail}`}
            style={[styles.chip, { backgroundColor: moved ? `${color}22` : colors.surface }]}
          >
            <Text variant="caption" color="muted" numberOfLines={1} style={{ fontSize: 12 }}>
              {reading.label}
            </Text>
            <Text
              variant="bodyStrong"
              numberOfLines={1}
              style={{ fontSize: 14, color: moved ? color : colors.muted }}
            >
              {WORD[reading.state]}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

/** What the team agent leads with this week: where the team stands, then each thing that moved. */
export function BriefingCard({
  status,
  items,
  briefing,
  observed = [],
}: {
  status: TeamStatus;
  items: BriefingItem[];
  briefing?: TeamBriefing | null; // the agent's own Monday run, when it checked out
  // The team's latest night and day, from 5 people or more; shown from the first sync, when
  // there is no change to tell yet. Changes from usual still need each member's history.
  observed?: string[];
}) {
  const colors = useColors();
  const content = briefingContent(status, !!briefing, items.length, observed);
  return (
    <Tile>
      <View style={styles.from}>
        <View style={[styles.badge, { backgroundColor: colors.accentSoft }]}>
          <Ionicons name="pulse" size={15} color={colors.accent} />
        </View>
        <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
          {briefing
            ? `Your team agent · ${new Date(briefing.madeAt).toLocaleDateString('en-US', {
                weekday: 'long',
                month: 'short',
                day: 'numeric',
              })}`
            : 'This week’s briefing · your team agent'}
        </Text>
      </View>
      <Text
        accessibilityRole="header"
        style={[typeScale.title, { color: stateColor(status.level, colors) }]}
      >
        {content.title}
      </Text>
      {content.main === 'briefing' && briefing ? (
        <Text style={{ fontSize: 16, lineHeight: 24 }}>{briefing.summary}</Text>
      ) : null}
      {content.main === 'items'
        ? items.map((item, index) => (
            <View key={item.key} style={styles.item}>
              <Text
                variant="bodyStrong"
                style={[styles.number, { color: stateColor(item.kind, colors) }]}
              >
                {index + 1}
              </Text>
              <View style={{ flex: 1, gap: 2 }}>
                <Text>{item.text}</Text>
                <Text variant="caption" color="faint">
                  {item.label} · {item.when}
                </Text>
              </View>
            </View>
          ))
        : null}
      {content.main === 'line' ? <Text color="muted">{status.line}</Text> : null}
      {content.observed.length ? (
        <View style={{ gap: spacing.xs }}>
          {content.observed.map((line) => (
            <Text key={line}>{line}</Text>
          ))}
          <Text variant="caption" color="faint">
            Readings only: what changed from usual needs each member&apos;s 14 earlier days.
          </Text>
        </View>
      ) : null}
    </Tile>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    flexGrow: 1,
    flexBasis: 96,
    alignItems: 'center',
    gap: 2,
    borderRadius: radius.md,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.sm,
  },
  from: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  badge: {
    width: 26,
    height: 26,
    borderRadius: 13,
    alignItems: 'center',
    justifyContent: 'center',
  },
  item: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
  number: { width: 16, fontSize: 16 },
});
