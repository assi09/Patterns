import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import type { TeamFindingEvidence, TeamFindingView } from '@/api/types';
import { stateColor } from '@/components/teamDashboard';
import { Section } from '@/components/list';
import { Text } from '@/components/Text';
import { Tile } from '@/components/widgets';
import { isHovered } from '@/lib/platform';
import {
  comparisonText,
  datesText,
  evidenceFigures,
  findingMeta,
  findingSentence,
  teamEvidenceHref,
} from '@/lib/teamEvidence';
import { fonts, radius, spacing, useColors } from '@/theme';

/** A quiet "View evidence" link that opens the record through its own report. */
export function EvidenceLink({
  teamId,
  week,
  evidenceId,
  label = 'View evidence',
}: {
  teamId: string;
  week: string;
  evidenceId: string;
  label?: string;
}) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={label}
      onPress={() => router.push(teamEvidenceHref(teamId, week, evidenceId))}
      style={(state) => [styles.link, isHovered(state) && { opacity: 0.7 }]}
    >
      <Text variant="caption" style={{ color: colors.accent, fontFamily: fonts.semibold }}>
        {label}
      </Text>
      <Ionicons name="chevron-forward" size={13} color={colors.accent} />
    </Pressable>
  );
}

/**
 * The week's priority findings, each labelled with its own comparison ("Sustained change" against
 * the scan's fixed baseline, or "New change") and a link to its evidence.
 */
export function FindingsCard({
  teamId,
  week,
  findings,
}: {
  teamId: string;
  week: string;
  findings: TeamFindingView[];
}) {
  const colors = useColors();
  if (!findings.length) return null;
  return (
    <Tile>
      <Text variant="label" color="muted" accessibilityRole="header">
        Findings and their evidence
      </Text>
      {findings.map((finding) => {
        const color = stateColor(finding.kind ?? 'change', colors);
        return (
          <View key={finding.evidenceId} style={styles.finding}>
            <View style={[styles.chip, { backgroundColor: `${color}22` }]}>
              <Text variant="caption" style={{ color, fontFamily: fonts.semibold }}>
                {finding.label}
              </Text>
            </View>
            <Text variant="bodyStrong">{findingSentence(finding)}</Text>
            <Text variant="caption" color="muted">
              {findingMeta(finding)}
            </Text>
            <EvidenceLink teamId={teamId} week={week} evidenceId={finding.evidenceId} />
          </View>
        );
      })}
      <Text variant="caption" color="faint">
        A sustained change is measured against one fixed baseline before the weeks it held; the
        weekly report below compares only this week with the four weeks just before, so its figures
        can differ.
      </Text>
    </Tile>
  );
}

/** One team record, bounded: what was measured, which dates, the team figure, its coverage. */
export function TeamEvidenceView({ record }: { record: TeamFindingEvidence }) {
  const colors = useColors();
  const figures = record.withheld ? [] : evidenceFigures(record);
  return (
    <View style={styles.page}>
      <View style={{ gap: spacing.xs }}>
        <Text variant="label" color="muted">
          {record.label} · report for {datesText(record.reportWeek)}
        </Text>
        <Text variant="title" accessibilityRole="header">
          {record.metricLabel}
        </Text>
        <Text color="muted">{comparisonText(record)}</Text>
        {record.outcomeLabel ? (
          <Text>
            {record.metricLabel}: {record.outcomeLabel}
          </Text>
        ) : null}
      </View>

      {record.withheld ? (
        <View style={[styles.notice, { borderColor: colors.border }]}>
          <Text>{record.withheld}</Text>
        </View>
      ) : (
        <View style={[styles.figures, { borderColor: colors.border }]}>
          {figures.map((figure) => (
            <View key={figure.label} style={styles.figure}>
              <Text variant="caption" color="muted">
                {figure.label}
              </Text>
              <Text style={styles.figureValue}>{figure.value}</Text>
            </View>
          ))}
        </View>
      )}

      {record.weeks.length ? (
        <Section title="Each scanned week, against the same baseline">
          {record.weeks.map((week) => (
            <View key={week.week.start} style={styles.week}>
              <Text style={{ flex: 1 }} color={week.changed ? 'text' : 'muted'}>
                {datesText(week.week)}
              </Text>
              <Text color={week.changed ? 'text' : 'muted'} style={styles.tabular}>
                {week.change ? week.change.text : 'not enough data'}
              </Text>
              <Text variant="caption" color="muted" style={styles.count}>
                {week.contributors} people{week.changed ? ' · changed' : ''}
              </Text>
            </View>
          ))}
        </Section>
      ) : null}

      <Section title="How this was worked out">
        <View style={styles.explain}>
          <Text>{record.measured}</Text>
          <Text color="muted">{record.method}</Text>
        </View>
      </Section>

      <Section title="Limits">
        <View style={styles.explain}>
          {record.limitations.map((line) => (
            <Text key={line} color="muted">
              {line}
            </Text>
          ))}
        </View>
      </Section>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { gap: spacing.lg },
  link: { flexDirection: 'row', alignItems: 'center', gap: 2, alignSelf: 'flex-start' },
  finding: { gap: spacing.xs, paddingTop: spacing.sm },
  chip: {
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
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
  figureValue: {
    fontFamily: fonts.semibold,
    fontSize: 20,
    lineHeight: 26,
    fontVariant: ['tabular-nums'],
  },
  week: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
  tabular: { fontVariant: ['tabular-nums'] },
  count: { minWidth: 110, textAlign: 'right' },
  explain: { gap: spacing.sm, paddingVertical: spacing.md },
});
