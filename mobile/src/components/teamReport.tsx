import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, View } from 'react-native';

import type { Evidence, ReportSection, SharedLevels } from '@/api/types';
import { Text } from '@/components/Text';
import { EvidenceLink } from '@/components/teamEvidence';
import { metricLabel } from '@/lib/format';
import {
  type ChangeRow,
  LEVEL_METRICS,
  levelMark,
  shortChange,
  signedChange,
  weekdayBars,
} from '@/lib/team';
import { radius, spacing, type as typeScale, useColors, useMetricColor } from '@/theme';

/** The report's few headline counts, read before the figures. */
export function KeyFigures({ items }: { items: { value: string; label: string }[] }) {
  return (
    <View style={styles.keys}>
      {items.map((item) => (
        <View key={item.label} style={styles.key} accessible>
          <Text style={typeScale.number}>{item.value}</Text>
          <Text variant="caption" color="muted">
            {item.label}
          </Text>
        </View>
      ))}
    </View>
  );
}

/**
 * How many people went down and up on each metric, around a center line: a diverging bar per
 * metric, on one scale (share of the people with data), so metrics in different units compare.
 * Changes are drawn in the metric's color; steady metrics recede in gray.
 */
export function ChangeChart({
  rows,
  evidenceOf,
}: {
  rows: ChangeRow[];
  evidenceOf?: { teamId: string; week: string }; // each row links to its record when given
}) {
  return (
    <View style={styles.chart}>
      <View style={styles.legend}>
        <Text variant="caption" color="faint">
          ← People lower
        </Text>
        <Text variant="caption" color="faint">
          People higher →
        </Text>
      </View>
      {rows.map((row) => (
        <ChangeBar key={row.metric} row={row} evidenceOf={evidenceOf} />
      ))}
    </View>
  );
}

function ChangeBar({
  row,
  evidenceOf,
}: {
  row: ChangeRow;
  evidenceOf?: { teamId: string; week: string };
}) {
  const link =
    evidenceOf && row.evidenceId ? (
      <EvidenceLink
        teamId={evidenceOf.teamId}
        week={evidenceOf.week}
        evidenceId={row.evidenceId}
        label="Evidence"
      />
    ) : null;
  const colors = useColors();
  const metricColor = useMetricColor(row.metric);
  const changed = row.status === 'changed';
  if (row.status === 'not_enough_data') {
    return (
      <View style={styles.changeRow} accessible accessibilityLabel={row.text}>
        <Text color="muted">{row.label}</Text>
        <Text variant="caption" color="faint">
          Not enough data: {row.members} of the {row.minimum} people needed
        </Text>
        {link}
      </View>
    );
  }
  const fill = changed ? metricColor : colors.faint;
  const share = (count: number) => (row.members ? `${(count / row.members) * 100}%` : '0%');
  return (
    <View style={styles.changeRow} accessible accessibilityLabel={row.text}>
      <View style={styles.changeTitle}>
        <Text variant={changed ? 'bodyStrong' : 'body'} color={changed ? 'text' : 'muted'}>
          {row.label}
        </Text>
        {row.median !== null && (
          <Text
            variant={changed ? 'bodyStrong' : 'body'}
            color={changed ? 'text' : 'muted'}
            style={styles.tabular}
          >
            {signedChange(row.metric, row.median)}
            <Text variant="caption" color="faint">
              {' '}
              median
            </Text>
          </Text>
        )}
      </View>
      <View style={styles.bar}>
        {/* Each half holds one direction, anchored at the center line. */}
        <View style={[styles.half, styles.left, { backgroundColor: colors.track }]}>
          <View style={[styles.fillLeft, { width: share(row.down), backgroundColor: fill }]} />
        </View>
        <View style={[styles.center, { backgroundColor: colors.muted }]} />
        <View style={[styles.half, styles.right, { backgroundColor: colors.track }]}>
          <View style={[styles.fillRight, { width: share(row.up), backgroundColor: fill }]} />
        </View>
      </View>
      <View style={styles.counts}>
        <Text variant="caption" color={changed ? 'muted' : 'faint'} style={styles.tabular}>
          {row.down} lower
        </Text>
        <Text variant="caption" color={changed ? 'muted' : 'faint'} style={styles.tabular}>
          {row.up} higher
        </Text>
      </View>
      {link}
    </View>
  );
}

const BAR_AREA = 40; // height of each direction's bars above and below the line

/** A weekday pattern: seven columns above and below each person's own usual, in the metric's color. */
export function WeekdayChart({
  section,
  evidence,
}: {
  section: ReportSection;
  evidence?: Evidence;
}) {
  const colors = useColors();
  const color = useMetricColor(section.metric);
  const bars = weekdayBars(evidence);
  if (!bars) return null;
  return (
    <View style={styles.weekday} accessible accessibilityLabel={section.text}>
      <Text variant="bodyStrong">{metricLabel(section.metric)} by weekday</Text>
      <View style={styles.columns}>
        {bars.map((bar) => {
          const marked = bar.highest || bar.lowest;
          const height = Math.max(2, bar.size * BAR_AREA);
          return (
            <View key={bar.day} style={styles.column}>
              <View style={[styles.upper, { height: BAR_AREA + 18 }]}>
                {bar.highest && (
                  <Text variant="caption" style={[styles.tabular, styles.columnLabel]}>
                    {shortChange(section.metric, bar.value)}
                  </Text>
                )}
                {bar.value > 0 && (
                  <View
                    style={[
                      styles.columnBar,
                      styles.up,
                      { height, backgroundColor: marked ? color : colors.faint },
                    ]}
                  />
                )}
              </View>
              <View style={[styles.zero, { backgroundColor: colors.muted }]} />
              <View style={[styles.lower, { height: BAR_AREA + 18 }]}>
                {bar.value < 0 && (
                  <View
                    style={[
                      styles.columnBar,
                      styles.down,
                      { height, backgroundColor: marked ? color : colors.faint },
                    ]}
                  />
                )}
                {bar.lowest && (
                  <Text variant="caption" style={[styles.tabular, styles.columnLabel]}>
                    {shortChange(section.metric, bar.value)}
                  </Text>
                )}
              </View>
              <Text variant="caption" color={marked ? 'text' : 'faint'}>
                {bar.short}
              </Text>
            </View>
          );
        })}
      </View>
      <Text variant="caption" color="muted">
        {section.text}
      </Text>
    </View>
  );
}

/** The people who chose to share, one row each, their four weekly levels against their own usual. */
export function LevelsTable({ levels }: { levels: SharedLevels[] }) {
  const colors = useColors();
  return (
    <View>
      <View style={[styles.tableRow, styles.tableHead]}>
        <View style={styles.person} />
        {LEVEL_METRICS.map(([metric, name]) => (
          <Text key={metric} variant="caption" color="faint" style={styles.cell} numberOfLines={1}>
            {name}
          </Text>
        ))}
      </View>
      {levels.map((person) => (
        <View
          key={person.member}
          style={[styles.tableRow, { borderTopColor: colors.border }]}
          accessible
          accessibilityLabel={`${person.member}: ${LEVEL_METRICS.map(
            ([metric, name]) => `${name} ${levelMark(person.levels[metric]?.level).word}`,
          ).join(', ')}`}
        >
          <Text style={styles.person} numberOfLines={1}>
            {person.member.split('@')[0]}
          </Text>
          {LEVEL_METRICS.map(([metric]) => {
            const level = person.levels[metric]?.level;
            const mark = levelMark(level);
            const off = level === 'above' || level === 'below';
            if (!level) {
              return (
                <Text key={metric} variant="caption" color="faint" style={styles.cell}>
                  {'  '}–
                </Text>
              );
            }
            return (
              <View key={metric} style={styles.cell}>
                <View style={[styles.mark, off && { backgroundColor: colors.chartHighlight }]}>
                  <Ionicons
                    name={mark.icon as keyof typeof Ionicons.glyphMap}
                    size={12}
                    color={off ? colors.text : colors.faint}
                  />
                  <Text variant="caption" color={off ? 'text' : 'faint'} numberOfLines={1}>
                    {mark.word}
                  </Text>
                </View>
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  keys: { flexDirection: 'row', gap: spacing.xl, paddingVertical: spacing.md, flexWrap: 'wrap' },
  key: { gap: 2, minWidth: 72 },
  chart: { gap: spacing.md, paddingVertical: spacing.md },
  legend: { flexDirection: 'row', justifyContent: 'space-between' },
  changeRow: { gap: 6 },
  changeTitle: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: spacing.md,
  },
  tabular: { fontVariant: ['tabular-nums'] },
  bar: { flexDirection: 'row', alignItems: 'center', height: 10 },
  half: { flex: 1, height: 8, flexDirection: 'row', overflow: 'hidden' },
  left: { justifyContent: 'flex-end', borderTopLeftRadius: 4, borderBottomLeftRadius: 4 },
  right: { justifyContent: 'flex-start', borderTopRightRadius: 4, borderBottomRightRadius: 4 },
  // Rounded at the outer end only; the end at the center line stays square.
  fillLeft: { height: 8, borderTopLeftRadius: 4, borderBottomLeftRadius: 4 },
  fillRight: { height: 8, borderTopRightRadius: 4, borderBottomRightRadius: 4 },
  center: { width: 2, height: 14, marginHorizontal: 2, borderRadius: 1 },
  counts: { flexDirection: 'row', justifyContent: 'space-between' },
  weekday: { gap: spacing.sm, paddingVertical: spacing.md },
  columns: { flexDirection: 'row' },
  column: { flex: 1, alignItems: 'center', gap: 4 },
  upper: { justifyContent: 'flex-end', alignItems: 'center', alignSelf: 'stretch', gap: 2 },
  lower: { justifyContent: 'flex-start', alignItems: 'center', alignSelf: 'stretch', gap: 2 },
  columnBar: { width: '50%', maxWidth: 28 },
  // Wider than its column, so a value such as "−1.3k steps" is never cut off.
  columnLabel: { width: 84, textAlign: 'center' },
  up: { borderTopLeftRadius: 4, borderTopRightRadius: 4 },
  down: { borderBottomLeftRadius: 4, borderBottomRightRadius: 4 },
  zero: { height: 1, alignSelf: 'stretch' },
  tableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  tableHead: { borderTopWidth: 0, paddingTop: spacing.md, paddingBottom: spacing.xs },
  person: { flex: 1.4, minWidth: 0 },
  cell: { flex: 1, minWidth: 0 },
  mark: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    alignSelf: 'flex-start',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
});
