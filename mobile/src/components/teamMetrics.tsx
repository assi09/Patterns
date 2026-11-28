import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import type { TeamMetricEvidence, TeamMetrics } from '@/api/types';
import { Row, Section } from '@/components/list';
import { Text } from '@/components/Text';
import { shortDate } from '@/lib/format';
import { isHovered } from '@/lib/platform';
import { datesText } from '@/lib/teamEvidence';
import {
  comparisonLine,
  metricFigures,
  rowDetail,
  rowValue,
  teamMetricHref,
  visibleCategories,
  weekLabel,
} from '@/lib/teamMetrics';
import { fonts, radius, spacing, useColors } from '@/theme';

/** A row of text choices, the chosen one underlined, as the Team screen's team switcher. */
function Choices({
  label,
  options,
  selected,
  onChoose,
}: {
  label: string;
  options: { key: string; text: string }[];
  selected?: string;
  onChoose: (key: string) => void;
}) {
  const colors = useColors();
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.choices}
      accessibilityRole="tablist"
      accessibilityLabel={label}
    >
      {options.map((option) => {
        const open = option.key === selected;
        return (
          <Pressable
            key={option.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: open }}
            aria-selected={open}
            onPress={() => onChoose(option.key)}
            style={(state) => [
              styles.choice,
              open && { borderBottomColor: colors.text },
              isHovered(state) && { opacity: 0.7 },
            ]}
          >
            <Text color={open ? 'text' : 'muted'} style={open ? styles.open : undefined}>
              {option.text}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

/**
 * Every team metric of one week, by category: a supervisor browses what the briefing did not
 * pick, and opens any of them for its evidence.
 */
export function TeamMetricsView({
  data,
  category,
  onWeek,
  onCategory,
}: {
  data: TeamMetrics;
  category?: string;
  onWeek: (start: string) => void;
  onCategory: (name?: string) => void;
}) {
  const colors = useColors();
  const weeks = data.weeks.map((start) => ({ key: start, text: weekLabel(start) }));
  const categories = [
    { key: '', text: 'All' },
    ...data.categories.map((c) => ({ key: c.name, text: c.name })),
  ];
  return (
    <View style={styles.page}>
      <View style={{ gap: spacing.xs }}>
        <Text variant="title" accessibilityRole="header">
          All team metrics
        </Text>
        <Text color="muted">{comparisonLine(data)}</Text>
      </View>
      <Choices label="Week" options={weeks} selected={data.week.start} onChoose={onWeek} />

      {data.state !== 'ready' ? (
        <View style={[styles.notice, { borderColor: colors.border }]}>
          <Text>{data.message}</Text>
        </View>
      ) : (
        <>
          <Text variant="caption" color="muted">
            Each figure is the median of eligible members&apos; changes from their own previous 28
            days, from at least {data.minimumMembers} people, and a metric shows only when enough
            people have it. {data.membersWithData} of {data.roster} people had synced data. Made{' '}
            {data.madeOn ? shortDate(data.madeOn) : 'earlier'}; it does not change afterwards. A
            description, not a test; these are not the briefing&apos;s highlights.
          </Text>
          <Choices
            label="Category"
            options={categories}
            selected={category ?? ''}
            onChoose={(key) => onCategory(key || undefined)}
          />
          {visibleCategories(data, category).map((group) => (
            <View key={group.name} style={styles.category}>
              {group.subgroups.map((sub) => (
                <Section key={sub.name} title={`${group.name} · ${sub.name}`}>
                  {sub.metrics.map((row) => (
                    <Row
                      key={row.metric}
                      title={row.label}
                      detail={rowDetail(row, data.minimumMembers)}
                      value={rowValue(row)}
                      onPress={() =>
                        router.push(teamMetricHref(data.teamId, data.week.start, row.metric))
                      }
                      accessibilityLabel={`${row.label}: ${rowValue(row)}. ${rowDetail(row, data.minimumMembers)}. Open its evidence`}
                    />
                  ))}
                </Section>
              ))}
            </View>
          ))}
        </>
      )}
    </View>
  );
}

/** One metric's evidence: its figure, dates, coverage, how it is worked out, and limits. */
export function TeamMetricView({ record }: { record: TeamMetricEvidence }) {
  const colors = useColors();
  const ready = record.state === 'figure';
  const figures = metricFigures(record);
  return (
    <View style={styles.page}>
      <View style={{ gap: spacing.xs }}>
        <Text variant="label" color="muted">
          {[record.category, record.subgroup].filter(Boolean).join(' · ') || 'Team metric'}
        </Text>
        <Text variant="title" accessibilityRole="header">
          {record.label}
        </Text>
        <Text color="muted">
          {record.baseline
            ? comparisonLine({ week: record.week, baseline: record.baseline })
            : `Week of ${datesText(record.week)}`}
        </Text>
      </View>

      {record.withheld || record.message ? (
        <View style={[styles.notice, { borderColor: colors.border }]}>
          <Text>{record.withheld ?? record.message}</Text>
        </View>
      ) : null}
      {figures.length ? (
        <View style={[styles.figures, { borderColor: colors.border }]}>
          {figures.map((figure) => (
            <View key={figure.label} style={styles.figure}>
              <Text variant="caption" color="muted">
                {figure.label}
              </Text>
              <Text style={styles.value}>{figure.value}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {ready && record.figureLabel ? (
        <Text variant="caption" color="muted">
          {record.figureLabel}, in {record.unit}.
        </Text>
      ) : null}

      {record.measured ? (
        <Section title="How this was worked out">
          <View style={styles.explain}>
            <Text>{record.measured}</Text>
            {record.derivation ? <Text>{record.derivation}</Text> : null}
            <Text color="muted">{record.method}</Text>
            {record.zeroAndMissing ? <Text color="muted">{record.zeroAndMissing}</Text> : null}
          </View>
        </Section>
      ) : null}

      {record.limitations.length ? (
        <Section title="Limits">
          <View style={styles.explain}>
            {record.limitations.map((line) => (
              <Text key={line} color="muted">
                {line}
              </Text>
            ))}
          </View>
        </Section>
      ) : null}

      {record.evidenceId ? (
        <Text variant="caption" color="faint" selectable>
          Evidence {record.evidenceId} · {record.source} · made{' '}
          {record.madeOn ? shortDate(record.madeOn) : 'earlier'}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: spacing.lg },
  choices: { gap: spacing.lg, paddingBottom: spacing.xs },
  choice: {
    paddingVertical: spacing.xs,
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  open: { fontFamily: fonts.semibold },
  category: { gap: spacing.lg },
  notice: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  figures: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    rowGap: spacing.md,
    paddingVertical: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  figure: { minWidth: 140, flexGrow: 1, flexBasis: 0, gap: 2 },
  value: {
    fontFamily: fonts.semibold,
    fontSize: 20,
    lineHeight: 26,
    fontVariant: ['tabular-nums'],
  },
  explain: { gap: spacing.sm, paddingVertical: spacing.md },
});
