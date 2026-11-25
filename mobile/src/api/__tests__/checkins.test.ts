import { ApiError, httpClient } from '../http';
import { DEMO_OWNER, DEMO_SUPERVISOR, mockClient } from '../mock';
import { saveToken } from '../token';

// Check-in alerts (docs/escalation.md): the mock behaves like the backend's contract, and the
// HTTP client calls the routes the backend serves.

const BASE = 'http://api.test';
const realFetch = globalThis.fetch;

afterEach(async () => {
  globalThis.fetch = realFetch;
  await saveToken(null);
});

async function signInAs(credentials: { email: string; password: string }) {
  const { token } = await mockClient.logIn(credentials);
  await saveToken(token);
}

describe('check-in alerts on the mock', () => {
  it('needs the current consent, is told first, and can be stopped once', async () => {
    await signInAs(DEMO_OWNER);
    const preview = await mockClient.previewTeam('DEMO2345');
    const joined = await mockClient.joinTeam('DEMO2345', preview.consentVersion);
    expect(joined.checkinAlerts).toBe(false);

    await expect(mockClient.shareTeamCheckin(joined.teamId, true, 'old')).rejects.toMatchObject({
      code: 'consent_changed',
    });
    const on = await mockClient.shareTeamCheckin(joined.teamId, true, joined.checkinConsentVersion);
    expect(on.checkinAlerts).toBe(true);

    const [alert] = await mockClient.getMyCheckins();
    expect(alert.status).toBe('waiting');
    expect(alert.evidence.length).toBeGreaterThanOrEqual(2);

    const stopped = await mockClient.withdrawCheckin(alert.id);
    expect(stopped.status).toBe('withdrawn');
    expect((await mockClient.getMyTeams())[0].checkinAlerts).toBe(false);
    await expect(mockClient.withdrawCheckin(alert.id)).rejects.toBeInstanceOf(ApiError);
    await mockClient.leaveTeam(joined.teamId);
  });

  it('shows received alerts to supervisors only, and keeps their mark', async () => {
    await signInAs(DEMO_OWNER);
    expect(await mockClient.getReceivedCheckins()).toEqual([]);
    await expect(mockClient.markCheckin('received-1', 'checked_in')).rejects.toMatchObject({
      status: 404,
    });

    await signInAs(DEMO_SUPERVISOR);
    const [received] = await mockClient.getReceivedCheckins();
    expect(received).not.toHaveProperty('evidence');
    const marked = await mockClient.markCheckin(received.id, 'not_needed', '  Spoke today ');
    expect(marked.mine.outcome).toBe('not_needed');
    expect(marked.note).toBe('Spoke today');
  });
});

describe('check-in alerts over HTTP', () => {
  it('calls the backend routes', async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    globalThis.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return new Response(JSON.stringify({}), { status: 200 });
    }) as unknown as typeof fetch;
    const client = httpClient(BASE, mockClient);
    await client.shareTeamCheckin('t 1', true, 'checkin-v1');
    await client.getMyCheckins();
    await client.withdrawCheckin('a1');
    await client.getReceivedCheckins();
    await client.markCheckin('a1', 'checked_in', 'ok');
    await client.setTeamHr('t1', null);
    expect(calls.map((c) => `${c.method} ${c.url.replace(BASE, '')}`)).toEqual([
      'POST /me/teams/t%201/checkin',
      'GET /me/checkins',
      'POST /me/checkins/a1/withdraw',
      'GET /checkins',
      'POST /checkins/a1/mark',
      'PUT /teams/t1/hr',
    ]);
    expect(calls[0].body).toEqual({ share: true, consentVersion: 'checkin-v1' });
    expect(calls[4].body).toEqual({ outcome: 'checked_in', note: 'ok' });
    expect(calls[5].body).toEqual({ email: null });
  });
});
