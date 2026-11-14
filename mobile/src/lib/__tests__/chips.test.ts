import type { Evidence } from '@/api/types';

import { chipIds } from '../format';

const item = (id: string, tool: string, metrics: string[], stats = {}): Evidence =>
  ({ id, tool, metrics, windows: [], n: 10, sufficient: true, stats }) as unknown as Evidence;

describe('the chips under an answer', () => {
  const byId = {
    a: item('a', 'compare_day', ['bedtime_hour']),
    b: item('b', 'habit_options', ['bedtime_hour']),
    c: item('c', 'compare_day', ['sleep_minutes']),
    k: item('k', 'knowledge', [], { title: 'Screens before bed' }),
    v: item('v', 'coverage', ['sleep_minutes', 'steps', 'resting_hr']),
    m: item('m', 'memory', []),
  };

  it('shows each name once, in order', () => {
    expect(chipIds(['a', 'b', 'c'], byId, 'You slept 6 h.', false)).toEqual(['a', 'c']);
  });

  it('leaves out passages already linked, and coverage when the answer names no gap', () => {
    expect(chipIds(['k', 'v', 'c'], byId, 'You slept 6 h.', true)).toEqual(['c']);
    expect(chipIds(['k'], byId, 'Try this.', false)).toEqual(['k']);
    expect(chipIds(['v'], byId, 'Three nights are missing.', false)).toEqual(['v']);
  });

  it('drops evidence with no name, and keeps evidence still loading', () => {
    expect(chipIds(['m', 'x'], byId, '', false)).toEqual(['x']);
  });
});
