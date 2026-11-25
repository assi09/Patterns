import { httpClient } from '@/api/http';
import { mockClient } from '@/api/mock';
import type { TeamCalendarMetric } from '@/api/types';
import { loadChange, loadValue } from '@/lib/calendar';

const metric = (change: number, unit: 'min' | 'count' = 'min'): TeamCalendarMetric => ({
  metric: 'meeting_minutes',
  label: 'Time in meetings',
  unit,
  members: 6,
  sufficient: true,
  medianChange: change,
  evidenceId: 'e1',
});

describe('meeting load wording', () => {
  it('reads minutes as hours and minutes, and counts as they are', () => {
    expect(loadValue(990, 'min')).toBe('16 h 30 min');
    expect(loadValue(120, 'min')).toBe('2 h');
    expect(loadValue(45, 'min')).toBe('45 min');
    expect(loadValue(-75, 'min')).toBe('-1 h 15 min');
    expect(loadValue(9.4, 'count')).toBe('9');
  });

  it('calls a small change usual and signs a real one', () => {
    expect(loadChange(metric(20))).toBe('about their usual week');
    expect(loadChange(metric(210))).toBe('+3 h 30 min on their usual week');
    expect(loadChange(metric(-90))).toBe('-1 h 30 min on their usual week');
    expect(loadChange(metric(0.5, 'count'))).toBe('about their usual week');
    expect(loadChange(metric(4, 'count'))).toBe('+4 on their usual week');
  });
});

describe('calendar over HTTP', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it('calls the backend routes', async () => {
    const calls: string[] = [];
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push(
        `${init?.method ?? 'GET'} ${url.replace('http://api.test', '')} ${init?.body ?? ''}`,
      );
      return new Response(JSON.stringify({}), { status: 200 });
    }) as unknown as typeof fetch;
    const client = httpClient('http://api.test', mockClient);
    await client.connectGoogle('calendar');
    await client.getCalendarStatus();
    await client.getTeamCalendar('t1', '2026-11-16');
    expect(calls).toEqual([
      'POST /google/connect {"capability":"calendar"}',
      'GET /calendar/status ',
      'GET /teams/t1/calendar?week=2026-11-16 ',
    ]);
  });
});
