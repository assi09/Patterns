import { httpClient } from '@/api/http';
import { DEMO_OWNER, mockClient } from '@/api/mock';
import { saveToken } from '@/api/token';
import type { HarnessSubmission } from '@/api/types';

import { activityText, connectAbilities, setupCommands, submissionText } from '../harness';

const sent = (kind: HarnessSubmission['kind'], payload: Record<string, unknown>) =>
  ({ id: 's', kind, status: 'pending', payload, teamId: null, createdAt: '' }) as HarnessSubmission;

describe('what a harness sent, in a line', () => {
  it('summarises calendar days by count and range', () => {
    const days = [{ date: '2026-11-24' }, { date: '2026-11-22' }, { date: '2026-11-23' }];
    expect(submissionText(sent('calendar_days', { days }))).toBe(
      '3 calendar days, 2026-11-22 to 2026-11-24',
    );
    expect(submissionText(sent('calendar_days', { days: [{ date: '2026-11-24' }] }))).toBe(
      '1 calendar day, 2026-11-24',
    );
  });

  it('shows a team event as its title and date, as text', () => {
    expect(
      submissionText(sent('team_event', { title: 'Launch', starts_on: '2026-11-27' })),
    ).toBe('Team event: Launch (2026-11-27)');
  });
});

describe('MCP tokens and approvals', () => {
  const realFetch = globalThis.fetch;
  afterEach(async () => {
    globalThis.fetch = realFetch;
    await saveToken(null);
  });

  it('calls the backend routes', async () => {
    const calls: string[] = [];
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url.replace('http://api.test', '')}`);
      return new Response(JSON.stringify({}), { status: 200 });
    }) as unknown as typeof fetch;
    const client = httpClient('http://api.test', mockClient);
    await client.makeAccessToken('Codex');
    await client.getAccessTokens();
    await client.revokeAccessToken('t1');
    await client.getHarnessSubmissions();
    await client.decideHarnessSubmission('s1', true);
    await client.decideHarnessSubmission('s1', false);
    expect(calls).toEqual([
      'POST /me/tokens',
      'GET /me/tokens',
      'DELETE /me/tokens/t1',
      'GET /me/harness',
      'POST /me/harness/s1/approve',
      'POST /me/harness/s1/decline',
    ]);
  });

  it('shows a token once and lists it without it; decides a send once', async () => {
    await saveToken((await mockClient.logIn(DEMO_OWNER)).token);
    const made = await mockClient.makeAccessToken('Claude Code');
    expect(made.token).toMatch(/^pat_/);
    const [listed] = await mockClient.getAccessTokens();
    expect(listed).not.toHaveProperty('token');
    await mockClient.revokeAccessToken(made.id);
    expect((await mockClient.getAccessTokens())[0].revokedAt).not.toBeNull();
    const [waiting] = await mockClient.getHarnessSubmissions();
    expect((await mockClient.decideHarnessSubmission(waiting.id, false)).status).toBe('declined');
    await expect(mockClient.decideHarnessSubmission(waiting.id, true)).rejects.toMatchObject({
      status: 409,
    });
  });
});

describe('setting up a new device', () => {
  const url = 'https://api.example/mcp/';
  const token = 'pat_abc';

  it('gives Claude Code one command with the token as a header', () => {
    expect(setupCommands(url, token).claudeCode).toBe(
      'claude mcp add --transport http patterns https://api.example/mcp/ --header "Authorization: Bearer pat_abc"',
    );
  });

  it('gives Codex its add command and keeps the token out of its config', () => {
    const codex = setupCommands(url, token);
    expect(codex.codexAdd).toBe(
      'codex mcp add patterns --url https://api.example/mcp/ --bearer-token-env-var PATTERNS_TOKEN',
    );
    expect(codex.codexAdd).not.toContain(token);
    expect(codex.codexToken).toBe('export PATTERNS_TOKEN=pat_abc');
  });

  it('describes activity by tool, refusals included', () => {
    expect(activityText([])).toBeNull();
    expect(
      activityText([
        { tool: 'who_am_i', calls: 2, failed: 0 },
        { tool: 'team_overview', calls: 1, failed: 1 },
      ]),
    ).toBe('who_am_i 2 · team_overview 1 (1 refused)');
  });
});

describe('what an assistant may do once allowed', () => {
  it('matches each role, and HR gets nothing to allow', () => {
    expect(connectAbilities('supervisor')?.join(' ')).toContain('at least 5 people');
    expect(connectAbilities('member')?.join(' ')).toContain('your own');
    expect(connectAbilities('hr')).toBeNull();
  });
});
