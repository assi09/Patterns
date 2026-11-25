import type { TeamCalendarMetric } from '@/api/types';

/** "16 h 30 min", "45 min", or a count as it is. */
export function loadValue(value: number, unit: 'min' | 'count'): string {
  if (unit === 'count') return String(Math.round(value));
  const minutes = Math.round(Math.abs(value));
  const text =
    minutes >= 60
      ? `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ''}`
      : `${minutes} min`;
  return value < 0 ? `-${text}` : text;
}

/** "+3 h 30 min on their usual week", or "about their usual" for a small change. */
export function loadChange(metric: TeamCalendarMetric): string {
  const change = metric.medianChange ?? 0;
  const small = metric.unit === 'min' ? Math.abs(change) < 30 : Math.abs(change) < 1;
  if (small) return 'about their usual week';
  return `${change > 0 ? '+' : ''}${loadValue(change, metric.unit)} on their usual week`;
}
