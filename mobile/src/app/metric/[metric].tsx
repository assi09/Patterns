import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { api } from '@/api';
import { useDay, useMetricSeries } from '@/api/hooks';
import type { DaySummary, ISODate, Point } from '@/api/types';
import { LineChart } from '@/components/LineChart';
import { Row, Section, Stat } from '@/components/list';
import { Screen } from '@/components/Screen';
import { SegmentedControl } from '@/components/SegmentedControl';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import {
  ACCUMULATING,
  bigValue,
  dayTitle,
  metricOf,
  STRAIN_BANDS,
  usualLine,
  valueText,
} from '@/lib/day';
import { metricLabel } from '@/lib/format';
import { useWide } from '@/lib/layout';
import { radius, spacing, useColors, useMetricColor } from '@/theme';
import { isHovered } from '@/lib/platform';

const SPANS = { '7 days': 7, '30 days': 30, '90 days': 90 } as const;
type Span = keyof typeof SPANS;

/** One metric: the day's value, the last weeks as a chart with the usual band, and the days. */
export default function MetricScreen() {
  const { metric, date } = useLocalSearchParams<{ metric: string; date?: string }>();
  const [span, setSpan] = useState<Span>('30 days');
  const [selected, setSelected] = useState<ISODate | undefined>(date || undefined);
  const day = useDay(selected ?? 'latest');
  const series = useMetricSeries(metric, SPANS[span], day.data?.date);
  const color = useMetricColor(metric);
  const colors = useColors();
  const wide = useWide();
  useEffect(() => {
    api.noteOpened(metric).catch(() => undefined); // a signal, so nothing to tell the person
  }, [metric]);
  const label = metricLabel(metric);

  const value = day.data ? metricOf(day.data, metric) : undefined;
  const big = value ? bigValue(metric, value.value) : undefined;
  const points = series.data?.points ?? [];
  const known = points.filter((p): p is Point & { value: number } => p.value !== null);
  const average = known.length ? known.reduce((sum, p) => sum + p.value, 0) / known.length : null;

  return (
    <Screen wide>
      <Stack.Screen options={{ title: label }} />
      {!day.data || !value || !big ? (
        <View style={{ gap: spacing.md }}>
          <Skeleton height={14} width={120} radius={radius.sm} />
          <Skeleton height={48} width={180} radius={radius.sm} />
          <Skeleton height={200} radius={radius.md} />
        </View>
      ) : (
        <View style={wide ? styles.columns : undefined}>
          <View style={[wide && styles.main, { gap: spacing.lg }]}>
            <View style={{ gap: spacing.xs }}>
              <Text variant="label" color="muted">
                {dayTitle(day.data.date, day.data.last)}
                {day.data.partial && ACCUMULATING.has(metric) ? ' · so far' : ''}
              </Text>
              <Stat value={big.value} unit={big.unit} label={usualLine(value, day.data.partial)} />
            </View>

            <View style={{ gap: spacing.md }}>
              <SegmentedControl
                options={Object.keys(SPANS) as Span[]}
                value={span}
                onChange={setSpan}
                accessibilityLabel="Period"
              />
              <View style={{ opacity: series.isPlaceholderData ? 0.5 : 1 }}>
                {series.data ? (
                  <LineChart
                    points={points}
                    metric={metric}
                    height={wide ? 240 : 180}
                    showAxis
                    fill={false}
                    usual={series.data.usual}
                    marker={day.data.date}
                  />
                ) : (
                  <Skeleton height={wide ? 240 : 180} radius={radius.md} />
                )}
              </View>
              <View style={styles.legend}>
                <View style={[styles.band, { backgroundColor: color, opacity: 0.18 }]} />
                <Text variant="caption" color="muted">
                  Your usual range: the middle half of the four weeks before
                </Text>
              </View>
            </View>

            <View style={[styles.summary, { borderColor: colors.border }]}>
              <Summary
                label={`${span} average`}
                value={average === null ? '–' : valueText(metric, average)}
              />
              <Summary
                label="Lowest"
                value={
                  known.length ? valueText(metric, Math.min(...known.map((p) => p.value))) : '–'
                }
              />
              <Summary
                label="Highest"
                value={
                  known.length ? valueText(metric, Math.max(...known.map((p) => p.value))) : '–'
                }
              />
            </View>

            {metric === 'recovery_score' && (
              <RecoveryParts parts={day.data.recovery?.parts ?? {}} />
            )}
            {metric === 'strain' && <StrainParts day={day.data} />}
            {metric === 'stress_score' && <StressParts parts={day.data.stress?.parts ?? {}} />}

            <View style={styles.ask}>
              <Button
                label={`Ask about ${label.toLowerCase()}`}
                icon="sparkles-outline"
                // dismissTo returns to the Ask tab; push would stack a second set of tabs.
                onPress={() => router.dismissTo({ pathname: '/ask', params: { metric } })}
              />
            </View>
          </View>

          <View style={wide ? styles.side : undefined}>
            <Section title="Day by day">
              {[...points]
                .reverse()
                .slice(0, 14)
                .map((point) => (
                  <DayRow
                    key={point.date}
                    metric={metric}
                    point={point}
                    last={day.data!.last}
                    selected={point.date === day.data!.date}
                    onPress={() => setSelected(point.date)}
                  />
                ))}
            </Section>
          </View>
        </View>
      )}
    </Screen>
  );
}

const RECOVERY_WORDS: Record<string, (share: number) => string> = {
  hrv_ms: (share) => `Higher than on ${share}% of your 28 days before`,
  resting_hr: (share) => `Lower than on ${share}% of your 28 days before`,
  sleep_minutes: (share) => `Longer than on ${share}% of your 28 nights before`,
};

/** What the recovery score is made of, and how, so it can be checked by eye. */
function RecoveryParts({ parts }: { parts: Record<string, number> }) {
  return (
    <Section
      title="What makes it"
      footer="Our own estimate, not Fitbit's: where last night's heart rate variability, resting heart rate and time asleep sit among your previous 28 days, averaged with equal weights. A higher resting heart rate counts down. It needs at least two of the three. Not a health assessment."
    >
      {Object.entries(parts).map(([metric, share]) => (
        <Row
          key={metric}
          title={metricLabel(metric)}
          detail={RECOVERY_WORDS[metric]?.(Math.round(share))}
          value={String(Math.round(share))}
        />
      ))}
    </Section>
  );
}

const ZONES = [
  ['hr_zone_moderate_minutes', 2],
  ['hr_zone_vigorous_minutes', 3],
  ['hr_zone_peak_minutes', 4],
  ['hr_zone_light_minutes', 0.04],
] as const;

/** The day's minutes in each heart-rate zone and what they add to strain. */
function StrainParts({ day }: { day: DaySummary }) {
  const strain = day.strain;
  if (!strain) return null;
  const estimated = strain.method === 'active_zone_minutes';
  return (
    <Section
      title="What makes it"
      footer={`Our own estimate, not WHOOP's or Fitbit's: minutes in Fitbit's heart-rate zones, which Fitbit sets from your own resting heart rate and age, weighted by zone and put on a 0 to 21 scale where each extra minute adds a little less. The light zone is most of a waking day, so it counts very little.${estimated ? ' This day has no zone minutes, so its load is estimated from Active Zone Minutes.' : ''} Not a health assessment.`}
    >
      <Row
        title="Band"
        detail="Light under 10, moderate 10 to 14, high 14 to 18, all out above"
        value={STRAIN_BANDS[strain.band]}
      />
      {estimated ? (
        <Row
          title="Active Zone Minutes"
          value={valueText('active_zone_minutes', metricOf(day, 'active_zone_minutes').value)}
        />
      ) : (
        ZONES.map(([zone, weight]) => (
          <Row
            key={zone}
            title={metricLabel(zone)}
            detail={`Each minute counts ${weight}`}
            value={valueText(zone, metricOf(day, zone).value)}
          />
        ))
      )}
    </Section>
  );
}

const STRESS_WORDS: Record<string, (share: number) => string> = {
  daytime_heart_rate: (share) =>
    `Higher than on ${share}% of your 28 days before, allowing for the day's exercise`,
  hrv_ms: (share) => `Lower than on ${share}% of your 28 days before`,
  resting_hr: (share) => `Higher than on ${share}% of your 28 days before`,
  sleep_minutes: (share) => `Shorter than on ${share}% of your 28 nights before`,
};

/** What the stress score is made of: each input's share of the 28 days it showed more signs than. */
function StressParts({ parts }: { parts: Record<string, number> }) {
  return (
    <Section
      title="What makes it"
      footer="Our own estimate of physical signs of stress, not a measure of how you feel: mostly your heart rate while sitting still and awake, compared with what the day's exercise would explain, then last night's heart rate variability, resting heart rate and sleep, each against your previous 28 days. 50 is a typical day for you. Caffeine, heat or illness raise it too. Not a health assessment."
    >
      {Object.entries(parts).map(([input, share]) => (
        <Row
          key={input}
          title={metricLabel(input)}
          detail={STRESS_WORDS[input]?.(Math.round(share))}
          value={String(Math.round(share))}
        />
      ))}
    </Section>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flex: 1, gap: 2 }}>
      <Text variant="caption" color="muted">
        {label}
      </Text>
      <Text variant="bodyStrong" style={{ fontVariant: ['tabular-nums'] }}>
        {value}
      </Text>
    </View>
  );
}

function DayRow({
  metric,
  point,
  last,
  selected,
  onPress,
}: {
  metric: string;
  point: Point;
  last: ISODate;
  selected: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      disabled={point.value === null}
      style={(state) => [
        styles.dayRow,
        (isHovered(state) || selected) && { backgroundColor: colors.track },
      ]}
    >
      <Text style={{ flex: 1 }} color={selected ? 'text' : undefined}>
        {dayTitle(point.date, last)}
      </Text>
      <Text style={styles.dayValue} color={point.value === null ? 'faint' : 'text'}>
        {point.value === null ? 'No data' : valueText(metric, point.value)}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  columns: { flexDirection: 'row', gap: spacing.xxl, alignItems: 'flex-start' },
  main: { flex: 3, minWidth: 0 },
  side: { flex: 2, minWidth: 0 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  band: { width: 16, height: 10, borderRadius: 3 },
  summary: {
    flexDirection: 'row',
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  ask: { flexDirection: 'row', marginBottom: spacing.md },
  dayRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    marginHorizontal: -spacing.sm,
    borderRadius: radius.sm,
  },
  dayValue: { fontVariant: ['tabular-nums'], minWidth: 90, textAlign: 'right' },
});
