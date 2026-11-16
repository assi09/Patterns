import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { type ReactNode, useState } from 'react';
import { Pressable, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native';
import Svg, { Circle, Line, Path } from 'react-native-svg';

import type { DayMetric, DaySummary, Finding, NightStages, Workout } from '@/api/types';
import { HourlyBars, StagesBar, workoutTime } from '@/components/day';
import { exerciseIcon } from '@/components/LogDraftCard';
import { Text } from '@/components/Text';
import {
  ACCUMULATING,
  bigValue,
  compare,
  metricOf,
  rangeText,
  STRAIN_BANDS,
  stages,
  valueText,
} from '@/lib/day';
import { metricLabel } from '@/lib/format';
import { isHovered } from '@/lib/platform';
import {
  clockOf,
  gaugeArc,
  hypnogramPath,
  rangeLayout,
  ringFraction,
  stageMinutes,
  stageRows,
} from '@/lib/widgets';
import { fonts, radius, spacing, type as typeScale, useColors, useMetricColor } from '@/theme';

export const TILE_RADIUS = 22;

/** A widget's surface: a tap target when it opens something. */
export function Tile({
  children,
  onPress,
  label,
  style,
}: {
  children: ReactNode;
  onPress?: () => void;
  label?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const colors = useColors();
  const base = [styles.tile, { backgroundColor: colors.surface }, style];
  if (!onPress) return <View style={base}>{children}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={(state) => [...base, isHovered(state) && { backgroundColor: colors.surfaceRaised }]}
    >
      {children}
    </Pressable>
  );
}

/** "↑ above usual", "↓ below usual", "within usual" or "so far", for a value on its day. */
export function positionText(metric: DayMetric, partial: boolean): string {
  if (partial && ACCUMULATING.has(metric.metric)) return 'so far today';
  const where = compare(metric.value, metric.usual);
  if (!where) return metric.value === null ? 'no data' : 'not enough days yet';
  return where === 'above' ? '↑ above usual' : where === 'below' ? '↓ below usual' : 'within usual';
}

// The three scores of the day, as rings

const RINGS = [
  { metric: 'recovery_score', label: 'Recovery' },
  { metric: 'strain', label: 'Strain' },
  { metric: 'sleep_minutes', label: 'Sleep' },
] as const;

function Ring({
  metric,
  label,
  note,
  size,
  onPress,
}: {
  metric: DayMetric;
  label: string;
  note: string;
  size: number;
  onPress: () => void;
}) {
  const colors = useColors();
  const color = useMetricColor(metric.metric);
  const stroke = Math.round(size * 0.1);
  const r = (size - stroke) / 2;
  const length = 2 * Math.PI * r;
  const filled = ringFraction(metric.metric, metric.value, metric.usual) * length;
  const big = bigValue(metric.metric, metric.value);
  const value = metric.metric === 'sleep_minutes' ? big.value.replace(/m$/, '') : big.value;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${big.value}. ${note}`}
      onPress={onPress}
      style={(state) => [styles.ring, isHovered(state) && { opacity: 0.8 }]}
    >
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size}>
          <Circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            stroke={colors.track}
            strokeWidth={stroke}
            fill="none"
          />
          {filled > 0 && (
            <Circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              stroke={color}
              strokeWidth={stroke}
              fill="none"
              strokeLinecap="round"
              strokeDasharray={`${filled} ${length}`}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          )}
        </Svg>
        <View style={styles.ringCenter} pointerEvents="none">
          <Text
            style={[typeScale.number, { fontSize: size * 0.24, lineHeight: size * 0.28 }]}
            numberOfLines={1}
            adjustsFontSizeToFit
          >
            {value}
          </Text>
        </View>
      </View>
      <Text variant="bodyStrong" style={{ fontSize: 14 }}>
        {label}
      </Text>
      <Text variant="caption" color="muted" numberOfLines={1} style={{ fontSize: 12 }}>
        {note}
      </Text>
    </Pressable>
  );
}

export function ScoreRings({
  day,
  wide,
  open,
}: {
  day: DaySummary;
  wide: boolean;
  open: (metric: string) => void;
}) {
  return (
    <Tile style={styles.rings}>
      {RINGS.map(({ metric, label }) => {
        const found = metricOf(day, metric);
        const note =
          metric === 'strain' && day.strain
            ? STRAIN_BANDS[day.strain.band].toLowerCase()
            : positionText(found, day.partial);
        return (
          <Ring
            key={metric}
            metric={found}
            label={label}
            note={note}
            size={wide ? 128 : 96}
            onPress={() => open(metric)}
          />
        );
      })}
    </Tile>
  );
}

/** The newest finding, one line, and a way into why. */
export function InsightBar({ finding }: { finding: Finding }) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityHint="Opens what changed and why"
      onPress={() => router.push(`/finding/${finding.id}`)}
      style={(state) => [
        styles.insight,
        { backgroundColor: colors.text },
        isHovered(state) && { opacity: 0.92 },
      ]}
    >
      <Ionicons name="pulse" size={20} color={colors.accent} />
      <Text style={[typeScale.body, { flex: 1, color: colors.background }]} numberOfLines={2}>
        {finding.title}: {finding.change}
      </Text>
      <Text style={[typeScale.bodyStrong, { color: colors.background }]}>Why?</Text>
    </Pressable>
  );
}

// Activity

function BigFigure({
  metric,
  size = 30,
  unit = true,
}: {
  metric: DayMetric;
  size?: number;
  unit?: boolean; // left out where the title already says it ("Steps")
}) {
  const big = bigValue(metric.metric, metric.value);
  return (
    <View style={styles.bigRow}>
      <Text style={[typeScale.number, { fontSize: size, lineHeight: size + 4 }]} numberOfLines={1}>
        {big.value}
      </Text>
      {unit && big.unit ? (
        <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
          {big.unit}
        </Text>
      ) : null}
    </View>
  );
}

function TileHead({ title, right }: { title: string; right?: string }) {
  return (
    <View style={styles.head}>
      <Text variant="bodyStrong" color="muted" style={{ fontSize: 14 }}>
        {title}
      </Text>
      {right ? (
        <Text variant="caption" color="muted" numberOfLines={1} style={{ flexShrink: 1 }}>
          {right}
        </Text>
      ) : null}
    </View>
  );
}

export function StepsTile({
  day,
  hourly,
  open,
}: {
  day: DaySummary;
  hourly?: (number | null)[];
  open: (metric: string) => void;
}) {
  const steps = metricOf(day, 'steps');
  const color = useMetricColor('steps');
  return (
    <Tile onPress={() => open('steps')} label={`Steps: ${valueText('steps', steps.value)}`}>
      <TileHead
        title="Steps"
        right={
          steps.usual ? `usual ${rangeText('steps', steps.usual).replace(' steps', '')}` : undefined
        }
      />
      <View style={styles.bigRow}>
        <BigFigure metric={steps} size={32} unit={false} />
        <Text variant="caption" style={{ color, fontFamily: fonts.semibold }}>
          {positionText(steps, day.partial)}
        </Text>
      </View>
      {hourly?.some((s) => s !== null) ? <HourlyBars steps={hourly} /> : null}
    </Tile>
  );
}

/** A small number widget: label, figure, and where it sits against usual. */
export function NumberTile({
  day,
  metric,
  open,
  extra,
}: {
  day: DaySummary;
  metric: string;
  open: (metric: string) => void;
  extra?: ReactNode;
}) {
  const found = metricOf(day, metric);
  return (
    <Tile
      style={styles.small}
      onPress={() => open(metric)}
      label={`${metricLabel(metric)}: ${valueText(metric, found.value)}`}
    >
      <TileHead title={metricLabel(metric)} />
      <BigFigure metric={found} size={26} />
      {extra}
      <Text variant="caption" color="muted" style={{ fontSize: 12 }}>
        {positionText(found, day.partial)}
      </Text>
    </Tile>
  );
}

/** Zone minutes against the top of the usual range, as a filling bar. */
export function ProgressBar({ metric }: { metric: DayMetric }) {
  const colors = useColors();
  const color = useMetricColor(metric.metric);
  const share = metric.usual?.high ? Math.min(1, (metric.value ?? 0) / metric.usual.high) : 0;
  return (
    <View style={[styles.progress, { backgroundColor: colors.track }]}>
      <View style={{ width: `${share * 100}%`, height: '100%', backgroundColor: color }} />
    </View>
  );
}

export function StressTile({ day, open }: { day: DaySummary; open: (metric: string) => void }) {
  const colors = useColors();
  const color = useMetricColor('stress_score');
  const stress = metricOf(day, 'stress_score');
  const share = (stress.value ?? 0) / 100;
  const width = 120;
  const r = 50;
  return (
    <Tile
      style={styles.small}
      onPress={() => open('stress_score')}
      label={`Physical stress signs: ${valueText('stress_score', stress.value)}`}
    >
      <TileHead title="Stress signs" />
      <View style={styles.gauge}>
        <Svg width={width} height={66}>
          <Path
            d={gaugeArc(1, width / 2, 60, r)}
            stroke={colors.track}
            strokeWidth={11}
            strokeLinecap="round"
            fill="none"
          />
          {stress.value !== null && share > 0 && (
            <Path
              d={gaugeArc(share, width / 2, 60, r)}
              stroke={color}
              strokeWidth={11}
              strokeLinecap="round"
              fill="none"
            />
          )}
        </Svg>
        <View style={styles.gaugeValue} pointerEvents="none">
          <Text style={[typeScale.number, { fontSize: 24, lineHeight: 28 }]}>
            {bigValue('stress_score', stress.value).value}
          </Text>
        </View>
      </View>
      <Text variant="caption" color="muted" style={{ fontSize: 12 }}>
        {stress.value === null
          ? 'not enough wear yet'
          : day.partial
            ? 'so far today'
            : stress.value < 40
              ? 'calmer than usual'
              : stress.value > 60
                ? 'more than usual'
                : 'a typical day'}
      </Text>
    </Tile>
  );
}

// Sleep: the night stage by stage

function Hypnogram({ night }: { night: NightStages }) {
  const colors = useColors();
  const color = useMetricColor('sleep_minutes');
  const [width, setWidth] = useState(0);
  const rows = stageRows(night);
  const height = rows.length === 4 ? 84 : 64;
  const labelWidth = 48;
  const chart = Math.max(0, width - labelWidth);
  const first = night.stages[0]?.start;
  const last = night.stages[night.stages.length - 1]?.end;
  const middle =
    first && last ? new Date((Date.parse(first) + Date.parse(last)) / 2).toISOString() : null;
  return (
    <View
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
      accessible
      accessibilityLabel={`Sleep stages from ${first ? clockOf(first) : ''} to ${last ? clockOf(last) : ''}`}
    >
      <View style={{ flexDirection: 'row' }}>
        <View style={{ width: labelWidth, height, justifyContent: 'space-between' }}>
          {rows.map((row) => (
            <Text key={row} variant="caption" color="muted" style={styles.stageLabel}>
              {row === 'rem' ? 'REM' : row[0].toUpperCase() + row.slice(1)}
            </Text>
          ))}
        </View>
        {chart > 0 && (
          <Svg width={chart} height={height}>
            {rows.map((_, i) => {
              const y = 6 + (i / (rows.length - 1)) * (height - 12);
              return (
                <Line
                  key={i}
                  x1={0}
                  x2={chart}
                  y1={y}
                  y2={y}
                  stroke={colors.track}
                  strokeWidth={1}
                />
              );
            })}
            <Path
              d={hypnogramPath(night, chart, height - 12)}
              transform="translate(0 6)"
              stroke={color}
              strokeWidth={3}
              strokeLinejoin="round"
              fill="none"
            />
          </Svg>
        )}
      </View>
      {first && last && middle ? (
        <View style={[styles.axis, { marginLeft: labelWidth }]}>
          {[first, middle, last].map((at, i) => (
            <Text key={i} variant="caption" color="muted" style={{ fontSize: 11 }}>
              {clockOf(at)}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flex: 1, gap: 2 }}>
      <Text variant="caption" color="muted" style={{ fontSize: 12 }}>
        {label}
      </Text>
      <Text variant="bodyStrong" style={{ fontVariant: ['tabular-nums'] }} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

export function SleepTile({
  day,
  night,
  open,
}: {
  day: DaySummary;
  night?: NightStages;
  open: (metric: string) => void;
}) {
  const colors = useColors();
  const color = useMetricColor('sleep_minutes');
  const asleep = metricOf(day, 'sleep_minutes');
  const charted = night?.available && night.stages.length ? night : null;
  const minutes = charted ? stageMinutes(charted) : {};
  const fromDay = (metric: string) => metricOf(day, metric).value;
  const where = compare(asleep.value, asleep.usual);
  const span =
    charted?.start && charted.end
      ? `${clockOf(charted.start)} → ${clockOf(charted.end)}`
      : undefined;
  const bar = !charted ? stages(day) : null;
  return (
    <Tile
      onPress={() => open('sleep_minutes')}
      label={`Sleep: ${valueText('sleep_minutes', asleep.value)}`}
    >
      <TileHead title="Sleep" right={span} />
      <View style={[styles.bigRow, { flexWrap: 'wrap' }]}>
        <BigFigure metric={asleep} size={32} />
        {asleep.usual && where ? (
          <Text variant="caption" style={{ color, fontFamily: fonts.semibold }}>
            {where === 'usual'
              ? 'within usual'
              : `${where === 'above' ? '↑ above' : '↓ below'} usual`}{' '}
            {rangeText('sleep_minutes', asleep.usual)}
          </Text>
        ) : null}
      </View>
      {charted ? <Hypnogram night={charted} /> : bar ? <StagesBar stages={bar} /> : null}
      <View style={[styles.stats, { borderTopColor: colors.track }]}>
        <Stat
          label="Deep"
          value={valueText(
            'deep_sleep_minutes',
            fromDay('deep_sleep_minutes') ?? minutes.deep ?? null,
          )}
        />
        <Stat
          label="REM"
          value={valueText(
            'rem_sleep_minutes',
            fromDay('rem_sleep_minutes') ?? minutes.rem ?? null,
          )}
        />
        <Stat
          label="Efficiency"
          value={valueText('sleep_efficiency', fromDay('sleep_efficiency'))}
        />
        <Stat label="Bedtime" value={valueText('bedtime_hour', fromDay('bedtime_hour'))} />
      </View>
    </Tile>
  );
}

// Heart and body: each value on the person's usual range

function RangeRow({ metric, onPress }: { metric: DayMetric; onPress: () => void }) {
  const colors = useColors();
  const color = useMetricColor(metric.metric);
  const layout = rangeLayout(metric);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${metricLabel(metric.metric)}: ${valueText(metric.metric, metric.value)}, ${positionText(metric, false)}`}
      onPress={onPress}
      style={(state) => [styles.rangeRow, isHovered(state) && { opacity: 0.75 }]}
    >
      <View style={styles.head}>
        <Text color="muted" numberOfLines={1} style={{ flexShrink: 1 }}>
          {metricLabel(metric.metric)}
        </Text>
        <Text variant="bodyStrong" style={{ fontVariant: ['tabular-nums'] }}>
          {valueText(metric.metric, metric.value)}
        </Text>
      </View>
      <View style={[styles.rangeTrack, { backgroundColor: colors.track }]}>
        {layout ? (
          <>
            <View
              style={[
                styles.rangeBand,
                {
                  left: `${layout.band[0] * 100}%`,
                  width: `${(layout.band[1] - layout.band[0]) * 100}%`,
                  backgroundColor: `${color}40`,
                },
              ]}
            />
            {layout.dot !== null ? (
              <View
                style={[
                  styles.rangeDot,
                  {
                    left: `${layout.dot * 100}%`,
                    backgroundColor: color,
                    borderColor: colors.surface,
                  },
                ]}
              />
            ) : null}
          </>
        ) : null}
      </View>
    </Pressable>
  );
}

export function RangesTile({
  title,
  day,
  metrics,
  open,
}: {
  title: string;
  day: DaySummary;
  metrics: string[];
  open: (metric: string) => void;
}) {
  const shown = metrics.map((m) => metricOf(day, m)).filter((m) => m.value !== null || m.usual);
  if (!shown.length) return null;
  return (
    <Tile>
      <Text variant="headline">{title}</Text>
      {shown.map((metric) => (
        <RangeRow key={metric.metric} metric={metric} onPress={() => open(metric.metric)} />
      ))}
      <Text variant="caption" color="muted">
        The shaded part is your usual range: the middle half of the four weeks before.
      </Text>
    </Tile>
  );
}

// Workouts and what changed

export function WorkoutTile({ workout, onPress }: { workout: Workout; onPress: () => void }) {
  const colors = useColors();
  const figures = [
    workoutTime(workout),
    workout.distanceKm ? `${workout.distanceKm} km` : null,
    workout.caloriesKcal != null ? `${Math.round(workout.caloriesKcal)} kcal` : null,
  ].filter(Boolean);
  return (
    <Tile onPress={onPress} label={workout.name} style={styles.workout}>
      <View style={[styles.workoutIcon, { backgroundColor: colors.accentSoft }]}>
        <Ionicons name={exerciseIcon(workout.exerciseType)} size={22} color={colors.accent} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="bodyStrong">{workout.name}</Text>
        <Text variant="caption" color="muted" numberOfLines={1}>
          {figures.join(' · ')}
        </Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={colors.faint} />
    </Tile>
  );
}

export function ChangeChips({ findings }: { findings: Finding[] }) {
  const colors = useColors();
  return (
    <View style={styles.chips}>
      {findings.map((finding) => (
        <ChangeChip key={finding.id} finding={finding} border={colors.border} />
      ))}
    </View>
  );
}

function ChangeChip({ finding, border }: { finding: Finding; border: string }) {
  const colors = useColors();
  const color = useMetricColor(finding.metric);
  const arrow = finding.direction === 'up' ? '↑' : finding.direction === 'down' ? '↓' : '→';
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityHint="Opens the evidence for this change"
      onPress={() => router.push(`/finding/${finding.id}`)}
      style={(state) => [
        styles.chip,
        { backgroundColor: colors.surface, borderColor: border },
        isHovered(state) && { backgroundColor: colors.surfaceRaised },
      ]}
    >
      <Text variant="bodyStrong" style={{ color, fontSize: 14 }}>
        {arrow}
      </Text>
      <Text variant="bodyStrong" style={{ fontSize: 14 }}>
        {metricLabel(finding.metric)} {finding.change}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: { borderRadius: TILE_RADIUS, padding: spacing.lg, gap: spacing.md },
  small: { flex: 1, minWidth: 0, gap: spacing.sm },
  rings: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.sm,
  },
  ring: { alignItems: 'center', gap: spacing.xs, flex: 1, borderRadius: radius.md },
  ringCenter: {
    ...StyleSheet.absoluteFill,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 14,
  },
  insight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderRadius: radius.lg,
    paddingVertical: 14,
    paddingHorizontal: spacing.lg,
  },
  head: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: spacing.sm,
  },
  bigRow: { flexDirection: 'row', alignItems: 'baseline', gap: 6 },
  progress: { height: 8, borderRadius: 4, overflow: 'hidden' },
  gauge: { alignItems: 'center' },
  gaugeValue: { position: 'absolute', bottom: 0, left: 0, right: 0, alignItems: 'center' },
  stageLabel: { fontSize: 11, lineHeight: 13 },
  axis: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 },
  stats: { flexDirection: 'row', gap: spacing.sm, borderTopWidth: 1, paddingTop: spacing.md },
  rangeRow: { gap: spacing.sm },
  rangeTrack: { height: 8, borderRadius: 4, justifyContent: 'center' },
  rangeBand: { position: 'absolute', height: 8, borderRadius: 4 },
  rangeDot: {
    position: 'absolute',
    width: 16,
    height: 16,
    marginLeft: -8,
    borderRadius: 8,
    borderWidth: 2,
  },
  workout: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: 14 },
  workoutIcon: {
    width: 44,
    height: 44,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 16,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: 10,
    paddingHorizontal: spacing.md,
  },
});
