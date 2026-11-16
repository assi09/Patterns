import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { stateColor } from '@/components/teamDashboard';
import { Text } from '@/components/Text';
import { Tile } from '@/components/widgets';
import { isHovered } from '@/lib/platform';
import type { TeamBriefing } from '@/api/types';
import type { AreaReading, AreaState, BriefingItem, TeamStatus } from '@/lib/team';
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
  teamId,
  briefing,
}: {
  status: TeamStatus;
  items: BriefingItem[];
  teamId: string;
  briefing?: TeamBriefing | null; // the agent's own Monday run, when it checked out
}) {
  const colors = useColors();
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
        {status.title}
      </Text>
      {briefing ? (
        <Text style={{ fontSize: 16, lineHeight: 24 }}>{briefing.summary}</Text>
      ) : items.length ? (
        items.map((item, index) => (
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
      ) : (
        <Text color="muted">{status.line}</Text>
      )}
      {briefing || items.length ? (
        <AskChips
          teamId={teamId}
          questions={['What lined up with this?', 'What could the team try?']}
        />
      ) : null}
    </Tile>
  );
}

function openChat(teamId: string, question?: string) {
  router.push({
    pathname: '/team-chat',
    params: question ? { team: teamId, q: question } : { team: teamId },
  });
}

function AskChips({ teamId, questions }: { teamId: string; questions: string[] }) {
  const colors = useColors();
  return (
    <View style={styles.askChips}>
      {questions.map((question) => (
        <Pressable
          key={question}
          accessibilityRole="button"
          accessibilityHint="Opens the team agent with this question"
          onPress={() => openChat(teamId, question)}
          style={(state) => [
            styles.askChip,
            { borderColor: colors.border },
            isHovered(state) && { backgroundColor: colors.track },
          ]}
        >
          <Text variant="caption" style={{ fontFamily: fonts.semibold }}>
            {question}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

/** The way into the team agent, shaped like the box it opens. */
export function AskBar({ teamId }: { teamId: string }) {
  const colors = useColors();
  return (
    <View style={{ gap: spacing.xs }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Ask your team agent"
        onPress={() => openChat(teamId)}
        style={(state) => [
          styles.ask,
          { backgroundColor: colors.surface, borderColor: colors.border },
          isHovered(state) && { backgroundColor: colors.surfaceRaised },
        ]}
      >
        <Text color="faint" style={{ flex: 1 }}>
          Ask your team agent…
        </Text>
        <View style={[styles.send, { backgroundColor: colors.accent }]}>
          <Ionicons name="arrow-up" size={18} color={colors.onAccent} />
        </View>
      </Pressable>
      <Text variant="caption" color="faint">
        Answers come from team figures only and never describe one person.
      </Text>
    </View>
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
  askChips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  askChip: {
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingVertical: 7,
    paddingHorizontal: spacing.md,
  },
  ask: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: 1,
    borderRadius: 26,
    height: 52,
    paddingLeft: spacing.lg,
    paddingRight: 6,
  },
  send: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
});
