import type { TeamMetricEvidence, TeamMetricRow, TeamMetrics } from '@/api/types';
import {
  metricFigures,
  rowDetail,
  rowValue,
  teamMetricHref,
  teamMetricsHref,
  visibleCategories,
  weekLabel,
} from '@/lib/teamMetrics';

const row = (over: Partial<TeamMetricRow>): TeamMetricRow => ({
  metric: 'rem_sleep_minutes',
  label: 'REM sleep',
  unit: 'min',
  state: 'figure',
  evidenceId: 'abc',
  contributors: 5,
  change: { value: 20, unit: 'min', text: '+20 min' },
  withheld: null,
  ...over,
});

describe('team metric rows', () => {
  it('shows a figure with its contributors', () => {
    expect(rowValue(row({}))).toBe('+20 min');
    expect(rowDetail(row({}), 5)).toBe('Median change · 5 people');
  });

  it('says withheld below the minimum and no data with nobody, never a zero', () => {
    const short = row({ state: 'below_minimum', contributors: 4, change: null });
    expect(rowValue(short)).toBe('Withheld');
    expect(rowDetail(short, 5)).toBe('4 of the 5 people needed');
    const none = row({ state: 'no_data', contributors: 0, change: null });
    expect(rowValue(none)).toBe('No data');
  });

  it('keeps a genuine zero change as a figure', () => {
    expect(rowValue(row({ change: { value: 0, unit: 'min', text: '+0 min' } }))).toBe('+0 min');
  });
});

describe('team metric links and choices', () => {
  it('opens the explorer at a week, and a metric through its week', () => {
    expect(teamMetricsHref('t')).toEqual({ pathname: '/team-metrics', params: { team: 't' } });
    expect(teamMetricsHref('t', '2026-10-12').params).toEqual({ team: 't', week: '2026-10-12' });
    expect(teamMetricHref('t', '2026-10-12', 'steps').params).toEqual({
      team: 't',
      week: '2026-10-12',
      metric: 'steps',
    });
    expect(weekLabel('2026-10-12')).toBe('Week of Oct 12');
  });

  it('filters to one category or shows all', () => {
    const data = {
      categories: [
        { name: 'Sleep', subgroups: [] },
        { name: 'Heart', subgroups: [] },
      ],
    } as unknown as TeamMetrics;
    expect(visibleCategories(data, undefined)).toHaveLength(2);
    expect(visibleCategories(data, 'Heart').map((c) => c.name)).toEqual(['Heart']);
  });

  it('lists the figures of a record, and none for a withheld one', () => {
    const record = {
      change: { value: 20, unit: 'min', text: '+20 min' },
      coverage: { contributors: 5, minimum: 5, roster: 7, withAnyData: 7 },
      higher: 5,
      lower: 0,
      unchanged: 0,
    } as TeamMetricEvidence;
    expect(metricFigures(record)).toEqual([
      { label: 'Median change', value: '+20 min' },
      { label: 'People counted', value: '5 of 7' },
      { label: 'Higher · lower · same', value: '5 · 0 · 0' },
    ]);
    const withheld = { ...record, change: null, higher: null, lower: null } as TeamMetricEvidence;
    expect(metricFigures(withheld)).toEqual([{ label: 'People counted', value: '5 of 7' }]);
  });
});
