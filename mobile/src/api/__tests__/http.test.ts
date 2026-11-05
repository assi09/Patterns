import { ApiError, httpClient, request } from '../http';
import { mockClient } from '../mock';

const BASE = 'http://api.test';

function respond(status: number, body: unknown) {
  return jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  jest.useRealTimers();
});

describe('request', () => {
  it('returns the parsed body and calls the right URL', async () => {
    const fetchMock = respond(200, { status: 'ok' });
    globalThis.fetch = fetchMock;
    await expect(request(`${BASE}/`, '/health')).resolves.toEqual({ status: 'ok' });
    expect(fetchMock.mock.calls[0][0]).toBe('http://api.test/health');
  });

  it("surfaces the server's error message and code", async () => {
    globalThis.fetch = respond(503, {
      error: { code: 'data_unavailable', message: 'Your Fitbit data could not be loaded.' },
    });
    const error = (await request(BASE, '/data/status').catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe('Your Fitbit data could not be loaded.');
    expect(error.code).toBe('data_unavailable');
    expect(error.status).toBe(503);
  });

  it('copes with error responses that are not JSON', async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: () => Promise.reject(new SyntaxError('Unexpected token <')),
    });
    await expect(request(BASE, '/data/status')).rejects.toThrow('Request failed (502).');
  });

  it('reports an unreachable server plainly', async () => {
    globalThis.fetch = jest.fn().mockRejectedValue(new TypeError('Network request failed'));
    await expect(request(BASE, '/health')).rejects.toMatchObject({
      code: 'network',
      message: 'Could not reach the server.',
    });
  });

  it('gives up after the timeout', async () => {
    jest.useFakeTimers();
    globalThis.fetch = jest.fn(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () =>
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' })),
          );
        }),
    ) as jest.Mock;
    const pending = request(BASE, '/health');
    jest.advanceTimersByTime(15_000);
    await expect(pending).rejects.toMatchObject({ code: 'timeout' });
  });
});

describe('httpClient', () => {
  it('uses the backend for served endpoints and the fallback for the rest', async () => {
    const status = {
      source: 'takeout',
      lastSync: null,
      range: null,
      coverage: [],
      lowWearDays: [],
    };
    const fetchMock = respond(200, status);
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);

    await expect(client.getDataStatus()).resolves.toEqual(status);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Context questions have no endpoint yet, so the mock answers them.
    await client.answerQuestion('q_shift', 'Exams');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await client.getReminders(); // served by the backend since reminders became real
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('evidence', () => {
  it('fetches evidence from the backend', async () => {
    const evidence = {
      id: 'abc',
      tool: 'trend',
      metrics: [],
      windows: [],
      n: 1,
      sufficient: true,
      stats: {},
    };
    const fetchMock = respond(200, evidence);
    globalThis.fetch = fetchMock;
    await expect(httpClient(BASE, mockClient).getEvidence('a b')).resolves.toEqual(evidence);
    expect(fetchMock.mock.calls[0][0]).toBe('http://api.test/evidence/a%20b');
  });

  it('reports unknown evidence instead of falling back to made-up evidence', async () => {
    globalThis.fetch = respond(404, { error: { code: 'not_found', message: 'nope' } });
    await expect(httpClient(BASE, mockClient).getEvidence('ev_steps')).rejects.toMatchObject({
      status: 404,
    });
  });

  it('does not hide other failures behind the mock', async () => {
    globalThis.fetch = respond(503, { error: { code: 'data_unavailable', message: 'down' } });
    await expect(httpClient(BASE, mockClient).getEvidence('ev_steps')).rejects.toThrow('down');
  });
});

describe('chat', () => {
  it('reads the conversation and posts questions with their options', async () => {
    const fetchMock = respond(200, []);
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);
    await client.getChat();
    await client.sendMessage('How did I sleep?', {
      expert: 'sleep',
      depth: 'deep',
      attachment: { kind: 'metric', metric: 'sleep_minutes' },
    });
    expect(fetchMock.mock.calls[0][0]).toBe('http://api.test/chat');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST' });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      text: 'How did I sleep?',
      expert: 'sleep',
      depth: 'deep',
      attachment: { kind: 'metric', metric: 'sleep_minutes' },
    });
  });

  it('waits longer for an answer than for other requests', async () => {
    jest.useFakeTimers();
    globalThis.fetch = jest.fn(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) =>
          init.signal?.addEventListener('abort', () =>
            reject(Object.assign(new Error('aborted'), { name: 'AbortError' })),
          ),
        ),
    ) as unknown as typeof fetch;
    const sending = httpClient(BASE, mockClient).sendMessage('Hi', {
      expert: 'auto',
      depth: 'quick',
    });
    let settled = false;
    sending.catch(() => (settled = true));
    await jest.advanceTimersByTimeAsync(30_000);
    expect(settled).toBe(false); // a normal request would have timed out at 15 s
    await jest.advanceTimersByTimeAsync(45_000);
    await expect(sending).rejects.toMatchObject({ code: 'timeout' });
  });
});

describe('days', () => {
  it('asks for a day and a metric series by path', async () => {
    const fetchMock = respond(200, {});
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);
    await client.getDay('latest');
    await client.getMetricSeries('resting_hr', { days: 30, end: '2026-10-24' });
    await client.getMetricSeries('steps', { days: 7 });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      'http://api.test/days/latest',
      'http://api.test/metrics/resting_hr?days=30&end=2026-10-24',
      'http://api.test/metrics/steps?days=7',
    ]);
  });
});

describe('conversations', () => {
  it('reads, sends to and manages conversations by path', async () => {
    const fetchMock = respond(200, []);
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);
    await client.getChat();
    await client.getChat('c 1');
    await client.getConversations();
    await client.createConversation();
    await client.updateConversation('c1', { title: 'Sleep' });
    await client.deleteConversation('c1');
    await client.sendMessage('Hi', {
      expert: 'auto',
      depth: 'quick',
      conversationId: 'c1',
      replaces: 'm4',
    });
    const calls = fetchMock.mock.calls.map(([url, init]) => [url, init?.method ?? 'GET']);
    expect(calls).toEqual([
      ['http://api.test/chat', 'GET'],
      ['http://api.test/chat?conversation=c%201', 'GET'],
      ['http://api.test/conversations', 'GET'],
      ['http://api.test/conversations', 'POST'],
      ['http://api.test/conversations/c1', 'PATCH'],
      ['http://api.test/conversations/c1', 'DELETE'],
      ['http://api.test/chat', 'POST'],
    ]);
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({ title: 'Sleep' });
    expect(JSON.parse(fetchMock.mock.calls[6][1].body)).toMatchObject({
      conversationId: 'c1',
      replaces: 'm4',
    });
  });
});

describe('the rest of Today', () => {
  it('reads workouts, hourly steps and the check-in, and saves it with PUT', async () => {
    const fetchMock = respond(200, {});
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);
    await client.getWorkouts('2026-10-25');
    await client.getHourlySteps('2026-10-25');
    await client.getCheckIn('2026-10-25');
    await client.saveCheckIn({ day: '2026-10-25', rating: 4, tags: [] });
    expect(fetchMock.mock.calls.map(([url, init]) => [url, init?.method ?? 'GET'])).toEqual([
      ['http://api.test/days/2026-10-25/workouts', 'GET'],
      ['http://api.test/days/2026-10-25/hourly', 'GET'],
      ['http://api.test/checkins/2026-10-25', 'GET'],
      ['http://api.test/checkins/2026-10-25', 'PUT'],
    ]);
  });
});

describe('memory', () => {
  it('sends each change to its route', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => Promise.resolve(undefined),
    });
    globalThis.fetch = fetchMock;
    const client = httpClient(BASE, mockClient);
    await client.forgetMemory('a/b');
    await client.muteInterest('steps');
    await client.forgetEpisode('e1');
    await client.noteOpened('steps');
    await client.decideMemory('f1', true);
    const calls = fetchMock.mock.calls.map(([url, init]) => [init?.method ?? 'GET', url]);
    expect(calls).toEqual([
      ['DELETE', `${BASE}/memory/facts/a%2Fb`],
      ['DELETE', `${BASE}/memory/interests/steps`],
      ['DELETE', `${BASE}/memory/episodes/e1`],
      ['POST', `${BASE}/memory/interests`],
      ['POST', `${BASE}/memory/facts/f1/decision`],
    ]);
  });
});

