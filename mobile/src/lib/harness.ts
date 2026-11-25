import type { HarnessSubmission } from '@/api/types';

/** What a harness sent, in a line: "2 calendar days, Nov 23 – Nov 24", "Team event: Launch". */
export function submissionText(item: HarnessSubmission): string {
  if (item.kind === 'team_event') {
    const title = String(item.payload.title ?? '');
    return `Team event: ${title} (${String(item.payload.starts_on ?? '')})`;
  }
  const days = (item.payload.days as { date: string }[] | undefined) ?? [];
  const dates = days.map((d) => d.date).sort();
  const range = dates.length > 1 ? `${dates[0]} to ${dates[dates.length - 1]}` : (dates[0] ?? '');
  return `${days.length} calendar ${days.length === 1 ? 'day' : 'days'}, ${range}`;
}
