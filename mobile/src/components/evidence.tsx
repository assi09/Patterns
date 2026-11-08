import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { useMetricSeries } from '@/api/hooks';
import type { Evidence } from '@/api/types';
import { LineChart } from '@/components/LineChart';
import { Section } from '@/components/list';
import { PressableScale } from '@/components/PressableScale';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import {
  type ChartPlan,
  answer,
  certainty,
  chartPlan,
  figures,
  method,
  periods,
  question,
} from '@/lib/evidence';
import { metricLabel, toolLabel } from '@/lib/format';
import { fonts, radius, spacing, useColors, useMetricColor } from '@/theme';

/** One computation as a page: its question and answer, a chart, the figures and how it was done. */
export function EvidenceView({ evidence }: { evidence: Evidence }) {
  return evidence.tool === 'knowledge' ? (
    <PassageView evidence={evidence} />
  ) : (
    <ComputedView evidence={evidence} />
  );
}

/** A passage from public guidance: what it says and where it comes from, nothing computed. */
function PassageView({ evidence }: { evidence: Evidence }) {
  return (
    <View style={styles.page}>
      <View style={{ gap: spacing.xs }}>
        <Text variant="label" color="muted">
          {toolLabel('knowledge')}
        </Text>
        <Text variant="title" accessibilityRole="header">
          {String(evidence.stats.title ?? '')}
        </Text>
      </View>
      <Text selectable>{String(evidence.stats.text ?? '')}</Text>
      <Text variant="caption" color="muted">
        From {String(evidence.stats.source ?? '')}. General guidance, not about your own data.
      </Text>
    </View>
  );
}

function ComputedView({ evidence }: { evidence: Evidence }) {
  const colors = useColors();
  const color = useMetricColor(evidence.metrics[0] ?? '');
  const [showRaw, setShowRaw] = useState(false);
  const result = answer(evidence);
  const plan = chartPlan(evidence);
  const sure = certainty(evidence);
  const numbers = figures(evidence);
  const single = evidence.metrics.length <= 2 && evidence.tool !== 'coverage';

  return (
    <View style={styles.page}>
      <View style={{ gap: spacing.xs }}>
        <View style={styles.kicker}>
          {single && evidence.metrics.map((metric) => <MetricDot key={metric} metric={metric} />)}
          <Text variant="label" color="muted" numberOfLines={1} style={{ flexShrink: 1 }}>
            {toolLabel(evidence.tool)}
          </Text>
        </View>
        <Text variant="headline" color="muted">
          {question(evidence)}
        </Text>
        <Text
          variant="title"
          style={{ color: result.tone === 'clear' ? color : colors.text }}
          accessibilityRole="header"
        >
          {result.text}
        </Text>
        <Text variant="caption" color="muted">
          {periods(evidence)}
        </Text>
      </View>

      {plan &&
        plan.metrics.map((metric) => (
          <EvidenceChart key={metric} metric={metric} plan={plan} named={plan.metrics.length > 1} />
        ))}
      {plan && (plan.highlight || plan.usual) && (
        <View style={styles.legend}>
          <View
            style={[styles.swatch, { backgroundColor: color, opacity: plan.usual ? 0.1 : 0.08 }]}
          />
          <Text variant="caption" color="muted">
            {plan.usual
              ? 'Your usual range; the dot is the day'
              : evidence.tool === 'change_point'
                ? 'From the day the new level began'
                : 'The recent period'}
          </Text>
        </View>
      )}

      {numbers.length > 0 && (
        <View style={[styles.figures, { borderColor: colors.border }]}>
          {numbers.map((figure) => (
            <View key={figure.label} style={styles.figure}>
              <Text variant="caption" color="muted">
                {figure.label}
              </Text>
              <Text style={styles.figureValue}>{figure.value}</Text>
            </View>
          ))}
        </View>
      )}

      {evidence.tool === 'coverage' && <CoverageBars evidence={evidence} />}

      <Section title="How this was worked out">
        <View style={styles.explain}>
          <Text>{method(evidence)}</Text>
          {sure && <Text color="muted">{sure}</Text>}
          <Text variant="caption" color="muted">
            {evidence.sufficient
              ? `Based on ${evidence.n} days of your data.`
              : `Only ${evidence.n} days of data, too few to rely on.`}
          </Text>
        </View>
      </Section>

      {single && (
        <View style={styles.actions}>
          <Button
            label="Ask about this"
            icon="sparkles-outline"
            // dismissTo goes back to the existing Ask tab; push would stack a second set of tabs.
            onPress={() =>
              router.dismissTo({ pathname: '/ask', params: { metric: evidence.metrics[0] } })
            }
          />
        </View>
      )}

      <Pressable
        accessibilityRole="button"
        onPress={() => setShowRaw((value) => !value)}
        style={styles.rawToggle}
        hitSlop={8}
      >
        <Text variant="caption" color="muted">
          {showRaw ? 'Hide' : 'Show'} every statistic
        </Text>
        <Ionicons name={showRaw ? 'chevron-up' : 'chevron-down'} size={14} color={colors.muted} />
      </Pressable>
      {showRaw && (
        <View style={[styles.raw, { borderColor: colors.border }]}>
          {Object.entries({
            id: evidence.id,
            tool: evidence.tool,
            days: evidence.n,
            ...evidence.stats,
          })
            .filter(([, value]) => typeof value !== 'object' || value === null)
            .map(([key, value]) => (
              <View key={key} style={styles.rawRow}>
                <Text variant="caption" color="muted" style={styles.mono}>
                  {key}
                </Text>
                <Text variant="caption" selectable style={styles.mono}>
                  {String(value)}
                </Text>
              </View>
            ))}
        </View>
      )}
      <Text variant="caption" color="faint" style={{ textAlign: 'center' }}>
        Computed from your own Fitbit data. Patterns, not medical advice.
      </Text>
    </View>
  );
}

function MetricDot({ metric }: { metric: string }) {
  const color = useMetricColor(metric);
  return <View style={[styles.dot, { backgroundColor: color }]} />;
}

function EvidenceChart({
  metric,
  plan,
  named,
}: {
  metric: string;
  plan: ChartPlan;
  named: boolean;
}) {
  const series = useMetricSeries(metric, plan.days, plan.end);
  return (
    <View style={{ gap: spacing.xs }}>
      {named && (
        <Text variant="caption" color="muted">
          {metricLabel(metric)}
        </Text>
      )}
      {series.data ? (
        <LineChart
          points={series.data.points}
          metric={metric}
          height={named ? 110 : 170}
          showAxis
          fill={false}
          highlight={plan.highlight}
          marker={plan.marker}
          usual={plan.usual}
        />
      ) : (
        <Skeleton height={named ? 110 : 170} radius={radius.md} />
      )}
    </View>
  );
}

function CoverageBars({ evidence }: { evidence: Evidence }) {
  const shares = (evidence.stats.fraction_present ?? {}) as Record<string, number>;
  // The least complete first: that is what the reader is looking for.
  const shown = Object.entries(shares)
    .filter(([metric]) => metric !== 'wear_minutes')
    .sort(([, a], [, b]) => a - b);
  return (
    <Section title="Days with data">
      {shown.map(([metric, share]) => (
        <CoverageRow key={metric} metric={metric} share={share} />
      ))}
    </Section>
  );
}

function CoverageRow({ metric, share }: { metric: string; share: number }) {
  const colors = useColors();
  const color = useMetricColor(metric);
  const percent = Math.round(share * 100);
  return (
    <View
      style={styles.coverage}
      accessible
      accessibilityLabel={`${metricLabel(metric)}: ${percent}%`}
    >
      <Text style={{ width: 150 }} numberOfLines={1}>
        {metricLabel(metric)}
      </Text>
      <View style={[styles.track, { backgroundColor: colors.track }]}>
        <View style={[styles.fill, { width: `${percent}%`, backgroundColor: color }]} />
      </View>
      <Text variant="caption" color="muted" style={styles.percent}>
        {percent}%
      </Text>
    </View>
  );
}

/** A compact link to one piece of evidence, shown under chat answers. */
export function EvidenceChip({
  id,
  label,
  metric,
}: {
  id: string;
  label: string;
  metric?: string;
}) {
  const color = useMetricColor(metric ?? '');
  return (
    <PressableScale
      accessibilityRole="link"
      accessibilityHint="Shows the computation behind this answer"
      onPress={() => router.push(`/evidence/${id}`)}
      style={[styles.chip, { backgroundColor: `${color}1F`, borderColor: `${color}55` }]}
    >
      <Ionicons name="stats-chart" size={11} color={color} />
      <Text variant="caption" color={color} style={styles.chipText} numberOfLines={1}>
        {label}
      </Text>
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  page: { gap: spacing.lg },
  kicker: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginTop: -spacing.sm },
  swatch: { width: 16, height: 10, borderRadius: 3 },
  figures: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    rowGap: spacing.md,
    paddingVertical: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  figure: { minWidth: 140, flexGrow: 1, flexBasis: 0, gap: 2 },
  figureValue: {
    fontFamily: fonts.semibold,
    fontSize: 20,
    lineHeight: 26,
    fontVariant: ['tabular-nums'],
  },
  explain: { gap: spacing.sm, paddingVertical: spacing.md },
  actions: { flexDirection: 'row' },
  coverage: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, minHeight: 40 },
  track: { flex: 1, height: 4, borderRadius: radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: radius.pill },
  percent: { width: 40, textAlign: 'right', fontVariant: ['tabular-nums'] },
  rawToggle: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  raw: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: spacing.sm, gap: 4 },
  rawRow: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.md },
  mono: { fontFamily: 'Courier' },
  chipText: { fontSize: 12, flexShrink: 1 }, // a long label ends with … instead of overflowing
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    maxWidth: '100%',
  },
});
