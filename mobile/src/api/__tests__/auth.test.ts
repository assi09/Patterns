import { ApiError, httpClient } from '../http';
import { DEMO_OWNER, DEMO_SUPERVISOR, mockClient } from '../mock';
import { getToken, saveToken } from '../token';

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

describe('mock accounts', () => {
  it('starts a sign-up as pending and keeps it signed in', async () => {
    const { token, account } = await mockClient.signUp({
      email: '  New@Example.com ',
      password: 'long enough password',
    });
    expect(account).toEqual({
      email: 'new@example.com',
      status: 'pending',
      isAdmin: false,
      role: 'member',
      personalFeatures: false, // the individual side is off unless asked for (docs/pivot.md)
    });
    await saveToken(token);
    await expect(mockClient.getAccount()).resolves.toEqual(account);
  });

  it.each([
    ['not-an-email', 'long enough password', 'invalid_email'],
    ['short@example.com', 'short', 'weak_password'],
    [DEMO_OWNER.email, 'long enough password', 'email_taken'],
  ])('refuses sign-up %s with %s', async (email, password, code) => {
    await expect(mockClient.signUp({ email, password })).rejects.toMatchObject({ code });
  });

  it('gives one error for a wrong password or an unknown email', async () => {
    const wrong = mockClient.logIn({ email: DEMO_OWNER.email, password: 'nope nope nope' });
    const unknown = mockClient.logIn({ email: 'nobody@example.com', password: 'whatever!!' });
    await expect(wrong).rejects.toMatchObject({ code: 'invalid_credentials', status: 401 });
    await expect(unknown).rejects.toMatchObject({ code: 'invalid_credentials', status: 401 });
  });

  it('lets the owner approve sign-ups and refuses everyone else', async () => {
    const person = await mockClient.signUp({
      email: 'waiting@example.com',
      password: 'long enough password',
    });
    await saveToken(person.token);
    await expect(mockClient.getAccessRequests()).rejects.toMatchObject({ code: 'forbidden' });

    await signInAs(DEMO_OWNER);
    const waiting = await mockClient.getAccessRequests();
    const request = waiting.find((r) => r.email === 'waiting@example.com')!;
    await expect(mockClient.decideAccessRequest(request.id, true)).resolves.toMatchObject({
      status: 'approved',
    });
    await saveToken(person.token);
    await expect(mockClient.getAccount()).resolves.toMatchObject({
      status: 'approved',
      role: 'member',
    });
  });

  it('approves someone as a supervisor', async () => {
    const person = await mockClient.signUp({
      email: 'new-lead@example.com',
      password: 'long enough password',
    });
    await signInAs(DEMO_OWNER);
    const request = (await mockClient.getAccessRequests()).find(
      (r) => r.email === 'new-lead@example.com',
    )!;
    await mockClient.decideAccessRequest(request.id, true, 'supervisor');
    await saveToken(person.token);
    await expect(mockClient.getAccount()).resolves.toMatchObject({ role: 'supervisor' });
  });

  it('signs out a rejected person', async () => {
    const person = await mockClient.signUp({
      email: 'rejected@example.com',
      password: 'long enough password',
    });
    await signInAs(DEMO_OWNER);
    const request = (await mockClient.getAccessRequests()).find(
      (r) => r.email === 'rejected@example.com',
    )!;
    await mockClient.decideAccessRequest(request.id, false);
    await saveToken(person.token);
    await expect(mockClient.getAccount()).rejects.toMatchObject({ status: 401 });
  });

  it('ends the session on log-out', async () => {
    await signInAs(DEMO_OWNER);
    await mockClient.logOut();
    await expect(mockClient.getAccount()).rejects.toBeInstanceOf(ApiError);
  });
});

describe('http sessions', () => {
  function capture() {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ email: 'a@b.co', status: 'approved', isAdmin: false }),
    });
    globalThis.fetch = fetchMock;
    return fetchMock;
  }

  it('sends the stored token as a bearer header', async () => {
    const fetchMock = capture();
    await saveToken('secret-token');
    expect(getToken()).toBe('secret-token');
    await httpClient(BASE, mockClient).getAccount();
    expect(fetchMock.mock.calls[0][0]).toBe('http://api.test/auth/me');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer secret-token');
  });

  it('sends no Authorization header when signed out', async () => {
    const fetchMock = capture();
    await httpClient(BASE, mockClient).getAccount();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it('posts credentials as JSON and calls the approve and reject paths', async () => {
    const fetchMock = capture();
    const client = httpClient(BASE, mockClient);
    await client.logIn({ email: 'a@b.co', password: 'pw' });
    await client.decideAccessRequest('id/1', false);
    await client.decideAccessRequest('id/2', true, 'supervisor');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ email: 'a@b.co', password: 'pw' }),
    });
    expect(fetchMock.mock.calls[1][0]).toBe('http://api.test/admin/access-requests/id%2F1/reject');
    expect(fetchMock.mock.calls[2]).toEqual([
      'http://api.test/admin/access-requests/id%2F2/approve',
      expect.objectContaining({ body: JSON.stringify({ role: 'supervisor' }) }),
    ]);
  });
});

describe('Google Health', () => {
  it('has no data for someone without a Fitbit until they connect', async () => {
    await signInAs(DEMO_SUPERVISOR); // the mock's supervisor has no Fitbit
    for (const call of [mockClient.getDataStatus, () => mockClient.getDay('latest')]) {
      await expect(call()).rejects.toMatchObject({ code: 'no_data', status: 404 });
    }
    await mockClient.connectGoogle();
    await expect(mockClient.getDataStatus()).resolves.toMatchObject({ source: 'takeout' });

    await signInAs(DEMO_OWNER);
    await expect(mockClient.getDay('latest')).resolves.toHaveProperty('metrics');
    await mockClient.disconnectGoogle();
  });

  it('connects in the mock, syncs for a while, then records the sync', async () => {
    jest.useFakeTimers();
    try {
      const status = mockClient.getGoogleStatus();
      await jest.advanceTimersByTimeAsync(500);
      expect((await status).status).toBe('none');

      const connecting = mockClient.connectGoogle();
      await jest.advanceTimersByTimeAsync(500);
      await expect(connecting).resolves.toEqual({ url: '' });
      const syncing = mockClient.getGoogleStatus();
      await jest.advanceTimersByTimeAsync(500);
      expect(await syncing).toMatchObject({ status: 'active', syncing: true });

      await jest.advanceTimersByTimeAsync(3000);
      const done = mockClient.getGoogleStatus();
      await jest.advanceTimersByTimeAsync(500);
      expect((await done).syncing).toBe(false);
      expect((await done).lastSync).not.toBeNull();

      const disconnecting = mockClient.disconnectGoogle();
      await jest.advanceTimersByTimeAsync(500);
      expect((await disconnecting).status).toBe('none');
      const refused = mockClient.syncGoogle();
      const assertion = expect(refused).rejects.toMatchObject({ code: 'not_connected' });
      await jest.advanceTimersByTimeAsync(500);
      await assertion;
    } finally {
      jest.useRealTimers();
    }
  });

  it('calls the Google endpoints', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    });
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);
    await client.getGoogleStatus();
    await client.connectGoogle();
    await client.syncGoogle();
    await client.disconnectGoogle();
    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method ?? 'GET'])).toEqual([
      ['http://api.test/google/status', 'GET'],
      ['http://api.test/google/connect', 'POST'],
      ['http://api.test/google/sync', 'POST'],
      ['http://api.test/google/disconnect', 'POST'],
    ]);
  });
});

describe('teams as a supervisor', () => {
  it('only lets supervisors create teams, and serves a report for the last full week', async () => {
    const owner = await mockClient.logIn(DEMO_OWNER);
    await saveToken(owner.token);
    await expect(mockClient.getTeams()).rejects.toMatchObject({ code: 'not_supervisor' });

    const lead = await mockClient.logIn(DEMO_SUPERVISOR);
    expect(lead.account.role).toBe('supervisor');
    await saveToken(lead.token);
    const team = await mockClient.createTeam('  Design ');
    expect(team.name).toBe('Design');
    expect(team.inviteCode).toMatch(/^[A-Z2-9]{8}$/);
    const rotated = await mockClient.rotateTeamCode(team.id);
    expect(rotated.inviteCode).not.toBe(team.inviteCode);

    expect(await mockClient.getTeamReports(team.id)).toEqual([]);
    const report = await mockClient.makeTeamReport(team.id);
    expect(new Date(`${report.week.start}T00:00:00Z`).getUTCDay()).toBe(1); // a Monday
    expect(report.week.end < new Date().toISOString().slice(0, 10)).toBe(true); // a full week
    expect(report.levels.every((row) => Object.keys(row.levels).length === 4)).toBe(true);
    const again = await mockClient.makeTeamReport(team.id);
    expect(again.createdAt).toBe(report.createdAt); // made once per week
    const listed = await mockClient.getTeamReports(team.id);
    expect(listed.map((r) => r.week.start)).toEqual([report.week.start]);
    const read = await mockClient.getTeamReport(team.id, report.week.end); // any day of it
    expect(read.headline).toBe(report.headline);
  });
});
