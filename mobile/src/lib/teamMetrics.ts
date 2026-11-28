import type { TeamMetricEvidence, TeamMetricRow, TeamMetrics } from '@/api/types';
import { shortDate } from '@/lib/format';
import { datesText } from '@/lib/teamEvidence';

/** The explorer for one team, at a week when one is given (any day of it). */
export function teamMetricsHref(teamId: string, week?: string) {
  return {
    pathname: '/team-metrics' as const,
    params: week ? { team: teamId, week } : { team: teamId },
  };
}

/** One metric's evidence, always through its own week. */
export function teamMetricHref(teamId: string, week: string, metric: string) {
  return { pathname: '/team-metric' as const, params: { team: teamId, week, metric } };
}

const people = (n: number) => `${n} ${n === 1 ? 'person' : 'people'}`;

/** The figure at the right of a row: the change, or why there is none. */
export function rowValue(row: TeamMetricRow): string {
  if (row.state === 'figure' && row.change) return row.change.text;
  return row.state === 'below_minimum' ? 'Withheld' : 'No data';
}

/** The quiet line under a row's name: who it is from, or how short of the minimum. */
export function rowDetail(row: TeamMetricRow, minimum: number): string {
  if (row.state === 'figure') return `Median change · ${people(row.contributors)}`;
  if (row.state === 'below_minimum') return `${row.contributors} of the ${minimum} people needed`;
  return 'No synced data for this week';
}

/** What every figure on the page is, and against which days. */
export function comparisonLine(data: Pick<TeamMetrics, 'week' | 'baseline'>): string {
  return `Week of ${datesText(data.week)}, against each person's own ${datesText(data.baseline)}`;
}

/** A week chip's label: its Monday, short. */
export function weekLabel(start: string): string {
  return `Week of ${shortDate(start)}`;
}

/** Which categories to show: all of them, or the one chosen. */
export function visibleCategories(
  data: TeamMetrics,
  category: string | undefined,
): TeamMetrics['categories'] {
  return category ? data.categories.filter((c) => c.name === category) : data.categories;
}

/** The figures of one metric's record, in the order the screen shows them. */
export function metricFigures(record: TeamMetricEvidence): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = [];
  if (record.change) out.push({ label: 'Median change', value: record.change.text });
  if (record.coverage) {
    out.push({
      label: 'People counted',
      value: `${record.coverage.contributors} of ${record.coverage.roster}`,
    });
  }
  if (record.change && record.higher != null && record.lower != null) {
    out.push({
      label: 'Higher · lower · same',
      value: `${record.higher} · ${record.lower} · ${record.unchanged ?? 0}`,
    });
  }
  return out;
}
