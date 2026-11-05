import type { MemoryFact, MemoryPage } from '@/api/types';

import { capitalized, factDetail, isEmpty } from '../memory';

const fact = (over: Partial<MemoryFact>): MemoryFact => ({
  id: 'f',
  kind: 'routine',
  text: 'Works nights',
  status: 'approved',
  start: null,
  end: null,
  createdAt: '2026-11-05T09:00:00Z',
  ...over,
});
const empty: MemoryPage = { waiting: [], kept: [], noticed: [], interests: [], episodes: [] };

describe('factDetail', () => {
  it('names the kind in plain words', () => {
    expect(factDetail(fact({ kind: 'context' }))).toBe('About you');
    expect(factDetail(fact({ kind: 'commitment' }))).toBe('Plan');
  });

  it('adds the dates of an event', () => {
    const exams = fact({ kind: 'event', start: '2026-11-09', end: '2026-11-14' });
    expect(factDetail(exams)).toBe('Event · Nov 9 to Nov 14');
  });

  it('shows one date when it starts and ends the same day', () => {
    const day = fact({ kind: 'event', start: '2026-11-09', end: '2026-11-09' });
    expect(factDetail(day)).toBe('Event · Nov 9');
  });
});

it('capitalizes a label that starts lower case', () => {
  expect(capitalized('bedtime')).toBe('Bedtime');
  expect(capitalized('')).toBe('');
});

describe('isEmpty', () => {
  it('is true only with nothing held', () => {
    expect(isEmpty(empty)).toBe(true);
    expect(isEmpty({ ...empty, noticed: [fact({ status: 'candidate' })] })).toBe(false);
    const episode = { id: 'e', day: '2026-11-05', text: 'Nov 5: Sleep dropped.' };
    expect(isEmpty({ ...empty, episodes: [episode] })).toBe(false);
  });
});
