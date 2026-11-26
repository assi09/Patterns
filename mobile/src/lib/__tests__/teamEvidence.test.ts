import type { TeamFindingEvidence, TeamFindingView } from '@/api/types';
import {
  comparisonText,
  datesText,
  evidenceFigures,
  findingMeta,
  findingSentence,
  teamEvidenceHref,
} from '@/lib/teamEvidence';

const TODAY = new Date('2026-11-27T12:00:00');

const finding: TeamFindingView = {
  label: 'Sustained change',
  kind: 'concern',
  metric: 'sleep_minutes',
  metricLabel: 'Time asleep',
  direction: 'lower',
  change: { value: -45.9, unit: 'min', text: '-46 min' },
  target: { start: '2026-11-02', end: '2026-11-22' },
  weeksRunning: 3,
  baseline: { start: '2026-09-28', end: '2026-10-25' },
  contributors: 8,
  movedThatWay: 8,
  roster: 8,
  why: 'Changed the same way in 3 weeks running against the fixed baseline.',
  evidenceId: 'abc123',
};

describe('team findings and their evidence', () => {
  it('says a finding with its own baseline, duration and coverage', () => {
    expect(findingSentence(finding)).toBe('Time asleep lower: median change -46 min');
    expect(findingMeta(finding)).toBe(
      'against Sep 28 to Oct 25 · 3 weeks running · 8 of 8 people with data (team of 8)',
    );
  });

  it('adds the year only when a range is not this year', () => {
    expect(datesText({ start: '2026-09-28', end: '2026-10-25' }, TODAY)).toBe('Sep 28 to Oct 25');
    expect(datesText({ start: '2021-06-21', end: '2021-07-18' }, TODAY)).toBe(
      'Jun 21 to Jul 18, 2021',
    );
    expect(datesText(null, TODAY)).toBe('dates not recorded');
  });

  it('opens a record through its own report week', () => {
    expect(teamEvidenceHref('t1', '2026-11-16', 'abc123')).toEqual({
      pathname: '/team-evidence',
      params: { team: 't1', week: '2026-11-16', id: 'abc123' },
    });
  });

  it('lists a weekly record’s figures, and none for a withheld one', () => {
    const record: TeamFindingEvidence = {
      evidenceId: 'w1',
      reportWeek: { start: '2021-07-19', end: '2021-07-25' },
      metric: 'steps',
      metricLabel: 'Steps',
      unit: 'steps',
      label: 'This week vs. the previous four weeks',
      measured: 'm',
      method: 'x',
      target: { start: '2021-07-19', end: '2021-07-25' },
      baseline: { start: '2021-06-21', end: '2021-07-18' },
      coverage: { roster: 11, minimum: 5, contributors: 5 },
      limitations: [],
      weeks: [],
      result: { change: { value: -696, text: '-696 steps' }, higher: 0, lower: 5 },
    };
    expect(evidenceFigures(record)).toEqual([
      { label: 'Median change', value: '-696 steps' },
      { label: 'People higher / lower', value: '0 / 5' },
      { label: 'People with enough data', value: '5 of 11 (at least 5 needed)' },
    ]);
    expect(comparisonText(record)).toMatch(/^Jul 19 to Jul 25, 2021, compared with Jun 21 to/);
  });
});
