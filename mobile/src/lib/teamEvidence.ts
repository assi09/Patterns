import type { TeamFindingEvidence, TeamFindingView, Window } from '@/api/types';
import { shortDate } from '@/lib/format';

/** A date range as the screen says it: "Sep 28 to Oct 25", with the year when it is not this one. */
export function datesText(window?: Window | null, today: Date = new Date()): string {
  if (!window) return 'dates not recorded';
  const year = window.end.slice(0, 4);
  const suffix = Number(year) === today.getFullYear() ? '' : `, ${year}`;
  return `${shortDate(window.start)} to ${shortDate(window.end)}${suffix}`;
}

/** Where a team record opens: always through its own report's week. */
export function teamEvidenceHref(teamId: string, week: string, evidenceId: string) {
  return { pathname: '/team-evidence' as const, params: { team: teamId, week, id: evidenceId } };
}

/** "Time asleep lower: -46 min" — the finding's figure, in its unit. */
export function findingSentence(finding: TeamFindingView): string {
  const way = finding.direction ? ` ${finding.direction}` : '';
  return `${finding.metricLabel}${way}: median change ${finding.change.text}`;
}

/** Its own comparison and coverage: against which dates, for how long, from how many people. */
export function findingMeta(finding: TeamFindingView): string {
  const parts = [`against ${datesText(finding.baseline)}`];
  if (finding.weeksRunning > 1) parts.push(`${finding.weeksRunning} weeks running`);
  if (finding.contributors != null) {
    const moved = finding.movedThatWay != null ? `${finding.movedThatWay} of ` : '';
    parts.push(`${moved}${finding.contributors} people with data (team of ${finding.roster})`);
  }
  return parts.join(' · ');
}

/** The record's few figures, each with its label, as the evidence screen lists them. */
export function evidenceFigures(record: TeamFindingEvidence): { label: string; value: string }[] {
  const out: { label: string; value: string }[] = [];
  const latest = record.weeks.length ? record.weeks[record.weeks.length - 1] : undefined;
  const change = record.result?.change ?? latest?.change;
  if (change) out.push({ label: 'Median change', value: change.text });
  const higher = record.result?.higher ?? latest?.higher;
  const lower = record.result?.lower ?? latest?.lower;
  if (higher != null && lower != null) {
    out.push({ label: 'People higher / lower', value: `${higher} / ${lower}` });
  }
  const { contributors, roster, minimum } = record.coverage;
  out.push({
    label: 'People with enough data',
    value: `${contributors ?? 0} of ${roster} (at least ${minimum} needed)`,
  });
  if (record.weeksRunning) {
    out.push({ label: 'Weeks running', value: String(record.weeksRunning) });
  }
  return out;
}

/** What was compared with what, in words. */
export function comparisonText(record: TeamFindingEvidence): string {
  const scanned = record.scanned ? ` (scanned ${datesText(record.scanned)})` : '';
  return `${datesText(record.target)}, compared with ${datesText(record.baseline)}${scanned}`;
}
