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

/** The variable Codex reads the token from (`--bearer-token-env-var`). */
export const CODEX_TOKEN_VAR = 'PATTERNS_TOKEN';

export interface SetupCommands {
  claudeCode: string; // one line for a terminal
  codexAdd: string; // registers the server once
  codexToken: string; // puts the token where Codex reads it
}

/**
 * Ready-to-paste setup for a new device, with the address and token filled in. Claude Code takes
 * the token as a header; Codex reads it from an environment variable, so the token never sits in
 * Codex's config file.
 */
export function setupCommands(url: string, token: string): SetupCommands {
  return {
    claudeCode: `claude mcp add --transport http patterns ${url} --header "Authorization: Bearer ${token}"`,
    codexAdd: `codex mcp add patterns --url ${url} --bearer-token-env-var ${CODEX_TOKEN_VAR}`,
    codexToken: `export ${CODEX_TOKEN_VAR}=${token}`,
  };
}

/** "who_am_i 2 · team_overview 1 (1 refused)", or null when the token did nothing. */
export function activityText(
  activity: { tool: string; calls: number; failed: number }[] | undefined,
): string | null {
  if (!activity?.length) return null;
  return activity
    .map((a) => `${a.tool} ${a.calls}${a.failed ? ` (${a.failed} refused)` : ''}`)
    .join(' · ');
}
