import type { MemoryFact, MemoryPage } from '@/api/types';

import { shortDate } from './format';

const KIND_LABELS: Record<MemoryFact['kind'], string> = {
  routine: 'Routine',
  goal: 'Goal',
  preference: 'Preference',
  context: 'About you',
  event: 'Event',
  commitment: 'Plan',
};

/** The quiet line under a memory: what kind it is, and its dates when it has some. */
export function factDetail(fact: MemoryFact): string {
  const kind = KIND_LABELS[fact.kind];
  if (!fact.start) return kind;
  const dates =
    !fact.end || fact.end === fact.start
      ? shortDate(fact.start)
      : `${shortDate(fact.start)} to ${shortDate(fact.end)}`;
  return `${kind} · ${dates}`;
}

export function capitalized(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** Nothing held at all: the page shows what it is for instead of empty sections. */
export function isEmpty(page: MemoryPage): boolean {
  return (
    page.waiting.length + page.kept.length + page.noticed.length + page.interests.length === 0 &&
    page.episodes.length === 0
  );
}
