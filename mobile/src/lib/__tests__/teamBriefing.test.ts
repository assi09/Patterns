import type { Evidence, TeamAlert, TeamReport } from '@/api/types';

import { briefingContent, buildingHistory, type TeamStatus } from '../team';

const READINGS = ['Median sleep last night: 7 h 10 min, based on 6 members.'];
const unknown: TeamStatus = { level: 'unknown', title: 'Not enough yet', line: 'No report yet.' };
const steady: TeamStatus = { level: 'steady', title: 'Steady', line: 'No change.' };

describe('the briefing card while a team builds history', () => {
  it('keeps the readings next to a briefing', () => {
    const content = briefingContent(steady, true, 0, READINGS);
    expect(content.main).toBe('briefing');
    expect(content.observed).toEqual(READINGS);
  });

  it('keeps the readings next to briefing items', () => {
    const content = briefingContent(unknown, false, 2, READINGS);
    expect(content.main).toBe('items');
    expect(content.observed).toEqual(READINGS);
    expect(content.title).toBe('Not enough yet');
  });

  it('calls them first readings when they are all there is', () => {
    expect(briefingContent(unknown, false, 0, READINGS)).toEqual({
      main: null,
      observed: READINGS,
      title: 'First readings',
    });
  });

  it('falls back to the status line without readings', () => {
    expect(briefingContent(steady, false, 0)).toEqual({
      main: 'line',
      observed: [],
      title: 'Steady',
    });
  });
});

function report(status: 'ready' | 'withheld', sufficient: boolean[]): TeamReport {
  const evidence: Record<string, Evidence> = {};
  const sections = sufficient.map((ok, i) => {
    evidence[`e${i}`] = { sufficient: ok } as Evidence;
    return { metric: `m${i}`, text: '', evidenceId: `e${i}` };
  });
  return { status, sections, evidence } as unknown as TeamReport;
}

describe('whether a team is still building history', () => {
  it('is, without a report, with a withheld one, or with no metric that had enough history', () => {
    expect(buildingHistory(undefined)).toBe(true);
    expect(buildingHistory(report('withheld', []))).toBe(true);
    expect(buildingHistory(report('ready', [false, false]))).toBe(true);
  });

  it('is not, once one metric has enough history to say what changed', () => {
    expect(buildingHistory(report('ready', [false, true]))).toBe(false);
  });

  it('is not once a team alert exists: an alert is itself a change from usual', () => {
    const alert = { id: 'a1', kind: 'concern' } as TeamAlert;
    expect(buildingHistory(undefined, [alert])).toBe(false);
    expect(buildingHistory(report('withheld', []), [alert])).toBe(false);
  });
});
