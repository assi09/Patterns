import type { Evidence, ReportSection, TeamLevel, TeamReport } from '@/api/types';
import { formatWithUnit, metricLabel } from '@/lib/format';

/** A signed change in the metric's units: "-1 h 4 min", "+12 min" for bedtime, "-1,148 steps". */
export function signedChange(metric: string, value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '±';
  const size = Math.abs(value);
  if (metric === 'bedtime_hour') return `${sign}${Math.round(size * 60)} min`;
  if (metric === 'steps') return `${sign}${Math.round(size).toLocaleString('en-US')} steps`;
  return `${sign}${formatWithUnit(metric, size)}`;
}

/** A short signed change for a small label: "+31 min", "−1.3k steps". */
export function shortChange(metric: string, value: number): string {
  if (metric === 'steps' && Math.abs(value) >= 1000) {
    const sign = value > 0 ? '+' : '−';
    return `${sign}${(Math.abs(value) / 1000).toFixed(1)}k steps`;
  }
  return signedChange(metric, value);
}

/** One metric of a team report, as its figure draws it: how many people went each way. */
export interface ChangeRow {
  metric: string;
  label: string;
  status: 'changed' | 'steady' | 'not_enough_data';
  text: string; // the report's sentence, for screen readers
  members: number;
  up: number;
  down: number;
  median: number | null;
  minimum?: number; // with too little data: how many people were needed
}

const ORDER = { changed: 0, steady: 1, not_enough_data: 2 };

/** The report's metrics with the counts their evidence holds: changes first, then steady ones. */
export function changeRows(report: TeamReport): ChangeRow[] {
  return report.sections
    .map((section) =>
      changeRow(section, report.evidence[section.evidenceId], report.minimumMembers),
    )
    .sort((a, b) => ORDER[a.status] - ORDER[b.status]);
}

function changeRow(section: ReportSection, evidence: Evidence | undefined, minimum: number) {
  const stats = evidence?.stats ?? {};
  const number = (key: string) => (typeof stats[key] === 'number' ? (stats[key] as number) : 0);
  const status = evidence?.sufficient === false ? 'not_enough_data' : (section.status ?? 'steady');
  return {
    metric: section.metric,
    label: section.label ?? metricLabel(section.metric),
    status,
    text: section.text,
    members: number('members'),
    up: number('members_up'),
    down: number('members_down'),
    median: typeof stats.median_change === 'number' ? stats.median_change : null,
    ...(status === 'not_enough_data' && { minimum }),
  } satisfies ChangeRow;
}

export const WEEKDAYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
] as const;

export interface WeekdayBar {
  day: (typeof WEEKDAYS)[number];
  short: string; // "Mon"
  value: number; // the median deviation from each person's own usual
  size: number; // |value| as a share of the largest, 0 to 1
  highest: boolean;
  lowest: boolean;
}

/** The seven weekday bars of a weekday pattern, or null when its evidence has too few people. */
export function weekdayBars(evidence: Evidence | undefined): WeekdayBar[] | null {
  const medians = evidence?.stats.median_deviation_by_weekday as Record<string, number> | undefined;
  if (!evidence?.sufficient || !medians || WEEKDAYS.some((d) => typeof medians[d] !== 'number')) {
    return null;
  }
  const values = WEEKDAYS.map((day) => medians[day]);
  const largest = Math.max(...values.map(Math.abs)) || 1;
  const high = Math.max(...values);
  const low = Math.min(...values);
  return WEEKDAYS.map((day, i) => ({
    day,
    short: day.slice(0, 1).toUpperCase() + day.slice(1, 3),
    value: values[i],
    size: Math.abs(values[i]) / largest,
    highest: values[i] === high && high > 0,
    lowest: values[i] === low && low < 0,
  }));
}

export const LEVEL_METRICS: [string, string][] = [
  ['recovery_score', 'Recovery'],
  ['sleep_minutes', 'Sleep'],
  ['strain', 'Strain'],
  ['stress_score', 'Stress signs'], // a narrow column; physical signs, not how anyone feels
];

/** How a shared level reads in the table: an arrow and a word, never color alone. */
export function levelMark(level: TeamLevel | null | undefined): { icon: string; word: string } {
  if (level === 'above') return { icon: 'arrow-up', word: 'Above' };
  if (level === 'below') return { icon: 'arrow-down', word: 'Below' };
  if (level === 'usual') return { icon: 'remove', word: 'Usual' };
  return { icon: 'ellipsis-horizontal', word: 'Too few days' };
}
