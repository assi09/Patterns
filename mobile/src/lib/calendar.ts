import type { ISODate, TeamCalendar, TeamCalendarMetric, Window } from '@/api/types';

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

function shift(day: ISODate, days: number): ISODate {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** The week after the one shown: what "planned" refers to, named by its dates. */
export function plannedWeek(week: Window): Window {
  return { start: shift(week.end, 1), end: shift(week.end, 7) };
}

/**
 * Why the team calendar has no figures: too few members connected, or enough connected but too
 * few with the full week and 14 earlier days synced that each comparison needs. Null when there
 * are figures.
 */
export function calendarEmpty(data: TeamCalendar): string | null {
  if (data.metrics.some((m) => m.sufficient)) return null;
  const minimum = data.minimumMembers;
  if (data.connected < minimum) {
    return `Fewer than ${minimum} members have connected a calendar (${data.connected} so far), so there are no figures yet. Members connect theirs in Settings.`;
  }
  const ready = Math.max(0, ...data.metrics.map((m) => m.members));
  return `${data.connected} members have connected a calendar, but only ${ready} have the full week and 14 earlier days synced that a comparison needs, fewer than ${minimum}. Figures start once ${minimum} do.`;
}
