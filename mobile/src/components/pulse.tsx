import { Pressable, StyleSheet, View } from 'react-native';

import { usePulse, useSavePulse, useTeamPulse } from '@/api/hooks';
import { Text } from '@/components/Text';
import { Tile } from '@/components/widgets';
import { isHovered } from '@/lib/platform';
import { fonts, radius, spacing, type as typeScale, useColors } from '@/theme';

export const EVENING_HOUR = 18; // the nightly question shows from here until midnight

/** The nightly team question on Today: only for people in a team, only in the evening of today. */
export function PulseCard({ today, now = new Date() }: { today: boolean; now?: Date }) {
  const colors = useColors();
  const pulse = usePulse();
  const save = useSavePulse();
  const data = pulse.data;
  if (!today || !data?.asked || now.getHours() < EVENING_HOUR) return null;
  return (
    <Tile>
      <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
        For your team · tonight
      </Text>
      <Text variant="headline">{data.question}</Text>
      <View style={styles.choices}>
        {data.scale.map((word, index) => {
          const value = index + 1;
          const chosen = data.rating === value;
          return (
            <Pressable
              key={word}
              accessibilityRole="button"
              accessibilityState={{ selected: chosen }}
              accessibilityLabel={`${value}: ${word}`}
              disabled={save.isPending}
              onPress={() => save.mutate(value)}
              style={(state) => [
                styles.choice,
                { borderColor: chosen ? colors.text : colors.border },
                chosen && { backgroundColor: colors.text },
                !chosen && isHovered(state) && { backgroundColor: colors.track },
              ]}
            >
              <Text style={[styles.number, { color: chosen ? colors.background : colors.text }]}>
                {value}
              </Text>
              <Text
                variant="caption"
                numberOfLines={2}
                style={{
                  color: chosen ? colors.background : colors.muted,
                  fontSize: 11,
                  lineHeight: 13,
                  textAlign: 'center',
                }}
              >
                {word}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <Text variant="caption" color="muted">
        {data.rating
          ? 'Thanks. Your answer only counts in team figures from 5 or more people; you can change it tonight.'
          : 'Your answer only counts in weekly team figures from 5 or more people, never on its own.'}
      </Text>
    </Tile>
  );
}

/** What the team said about its days, week by week; a figure only from 5 or more people. */
export function TeamPulseTile({ teamId, style }: { teamId: string; style?: object }) {
  const colors = useColors();
  const found = useTeamPulse(teamId);
  const weeks = found.data?.weeks ?? [];
  if (!weeks.length) return null;
  const last = weeks[weeks.length - 1];
  const before = weeks.slice(0, -1).filter((w) => w.mean !== null);
  const usual = before.length
    ? before.reduce((sum, w) => sum + (w.mean ?? 0), 0) / before.length
    : null;
  return (
    <Tile style={style}>
      <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
        How the week felt · {found.data?.question}
      </Text>
      {last.mean !== null ? (
        <View style={styles.big}>
          <Text style={[typeScale.number, { fontSize: 30 }]}>{last.mean.toFixed(1)}</Text>
          <Text variant="caption" color="muted">
            of 5 · {last.respondents} answered
            {usual !== null ? ` · ${usual.toFixed(1)} in the weeks before` : ''}
          </Text>
        </View>
      ) : (
        <Text color="muted">
          Not enough answers last week: {last.respondents} of the {found.data?.minimum} needed.
        </Text>
      )}
      <View style={styles.bars} accessibilityLabel="The last five weeks">
        {weeks.map((week) => (
          <View key={week.start} style={styles.barSlot}>
            <View
              style={[
                styles.bar,
                week.mean === null
                  ? { height: 4, backgroundColor: colors.track }
                  : {
                      height: `${(week.mean / 5) * 100}%`,
                      backgroundColor: week === last ? colors.accent : colors.faint,
                    },
              ]}
            />
          </View>
        ))}
      </View>
      <Text variant="caption" color="faint">
        1 light to 5 very heavy, each person&apos;s week counted once. Never one person&apos;s
        answer, never a single day.
      </Text>
    </Tile>
  );
}

const styles = StyleSheet.create({
  choices: { flexDirection: 'row', gap: 6 },
  choice: {
    flex: 1,
    minHeight: 56,
    borderWidth: 1,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    paddingHorizontal: 2,
  },
  number: { fontFamily: fonts.bold, fontSize: 17 },
  big: { flexDirection: 'row', alignItems: 'baseline', gap: spacing.sm, flexWrap: 'wrap' },
  bars: { flexDirection: 'row', alignItems: 'flex-end', height: 48, gap: 8 },
  barSlot: { flex: 1, height: '100%', justifyContent: 'flex-end' },
  bar: { borderRadius: 4, width: '100%' },
});
