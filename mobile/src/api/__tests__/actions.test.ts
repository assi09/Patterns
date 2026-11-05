import {
  estimateNote,
  exerciseName,
  formFromLog,
  logDetails,
  logFromForm,
  logTitle,
  trackerSummary,
  validateLog,
  workoutChoices,
} from '@/lib/actionLog';

import { httpClient } from '../http';
import { DEMO_OWNER, mockClient } from '../mock';
import { saveToken } from '../token';
import type { HealthLog } from '../types';

const FOOD: HealthLog = {
  kind: 'food',
  foodName: 'Example meal',
  mealType: 'LUNCH',
  consumedAt: '2026-10-24T12:00:00+03:00',
  proteinG: 40,
  provenance: 'user_entered',
};

beforeEach(async () => {
  const { token } = await mockClient.logIn(DEMO_OWNER);
  await saveToken(token);
});
afterEach(async () => {
  await saveToken(null);
});

it('keeps absent quantities unknown and preserves an explicit zero', () => {
  const edit = (changes: Record<string, string>) =>
    logFromForm(FOOD, { ...formFromLog(FOOD), ...changes });
  expect(edit({ proteinG: '0', fatG: '' })).toMatchObject({ proteinG: 0 });
  expect(edit({ fatG: '' })).not.toHaveProperty('fatG');
  expect(() => edit({ proteinG: 'lots' })).toThrow('number');
  expect(() => edit({ time: '25:99' })).toThrow();
  expect(() => edit({ date: '24/10/2026' })).toThrow('YYYY-MM-DD');
});

it('revises the reviewed version, blocks stale confirmation and supports confirmed undo', async () => {
  const draft = await mockClient.proposeAction('lifecycle', FOOD);
  const changed = await mockClient.reviseAction(draft.id, 1, { ...FOOD, proteinG: 45 });
  expect(changed.version).toBe(2);
  await expect(mockClient.confirmAction(draft.id, 1)).rejects.toMatchObject({
    code: 'stale_action',
  });
  await expect(mockClient.confirmAction(draft.id, 2)).resolves.toMatchObject({
    status: 'succeeded',
  });
  await expect(mockClient.confirmAction(draft.id, 2)).resolves.toMatchObject({
    status: 'succeeded',
  });
  await expect(mockClient.undoAction(draft.id, 2)).resolves.toMatchObject({ status: 'undone' });
});

it('prevents duplicate drafts and keeps cancellation from becoming a log', async () => {
  const log = { ...FOOD, foodName: 'Another example meal' };
  const draft = await mockClient.proposeAction('duplicate', log);
  await expect(mockClient.proposeAction('duplicate', log)).resolves.toMatchObject({ id: draft.id });
  await expect(mockClient.proposeAction('another-key', log)).rejects.toMatchObject({
    code: 'duplicate_log',
  });
  await mockClient.cancelAction(draft.id, 1);
  await expect(mockClient.confirmAction(draft.id, 1)).rejects.toMatchObject({
    code: 'stale_action',
  });
});

it('does not expose another account’s drafts', async () => {
  const draft = await mockClient.proposeAction('ownership', {
    ...FOOD,
    foodName: 'Private demo meal',
  });
  const person = await mockClient.signUp({
    email: 'action-person@example.com',
    password: 'long enough password',
  });
  const request = (await mockClient.getAccessRequests()).find(
    (r) => r.email === 'action-person@example.com',
  )!;
  await mockClient.decideAccessRequest(request.id, true);
  await saveToken(person.token);
  await expect(mockClient.getAction(draft.id)).rejects.toMatchObject({ status: 404 });
});

it('uses versioned backend operations without silently falling back to demo writes', async () => {
  const original = globalThis.fetch;
  const fetch = jest
    .fn()
    .mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        error: { code: 'write_scope_needed', message: 'Allow logging first.' },
      }),
    });
  globalThis.fetch = fetch;
  try {
    const client = httpClient('http://api.test', mockClient);
    await expect(client.confirmAction('a b', 3)).rejects.toMatchObject({
      code: 'write_scope_needed',
    });
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/actions/a%20b/confirm');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ version: 3 });
    await expect(client.connectGoogle('food_logging')).rejects.toMatchObject({ status: 403 });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ capability: 'food_logging' });
  } finally {
    globalThis.fetch = original;
  }
});

const RUN: HealthLog = {
  kind: 'workout',
  exerciseType: 'RUNNING',
  startTime: '2026-10-24T07:00:00+03:00',
  endTime: '2026-10-24T11:00:00+03:00',
  activeSeconds: 14280,
  distanceKm: 42.2,
  provenance: 'user_entered',
};

it('reads entries in plain words, in their own time zone', () => {
  expect(logTitle(FOOD)).toBe('Lunch · Example meal');
  expect(logDetails(FOOD)).toEqual(['Sat 24 Oct, 12:00', 'P 40 g']);
  expect(logTitle(RUN)).toBe('Run');
  expect(logDetails(RUN)).toEqual(['Sat 24 Oct, 07:00–11:00', '3 h 58 min', '42.2 km']);
});

it('round-trips the edit form and keeps the time zone', () => {
  expect(logFromForm(FOOD, formFromLog(FOOD))).toEqual(FOOD);
  const form = formFromLog(RUN);
  expect(form).toMatchObject({ date: '2026-10-24', time: '07:00', duration: '3:58' });
  const shorter = logFromForm(RUN, { ...form, duration: '45', distanceKm: '8' });
  expect(shorter).toMatchObject({
    startTime: '2026-10-24T07:00:00+03:00',
    endTime: '2026-10-24T07:45:00+03:00',
    activeSeconds: 2700,
    distanceKm: 8,
  });
});

it('refuses the same implausible entries as the backend', () => {
  const now = Date.parse('2026-10-25T12:00:00Z');
  expect(() => validateLog({ ...FOOD, energyKcal: 90000 }, now)).toThrow('5000 kcal');
  expect(() => validateLog({ ...FOOD, consumedAt: '2031-01-01T08:00:00+02:00' }, now)).toThrow(
    'future',
  );
  expect(() => validateLog({ ...RUN, distanceKm: 301 }, now)).toThrow('300 km');
  expect(() => validateLog({ ...RUN, activeSeconds: 600 }, now)).toThrow('too far');
  expect(() =>
    validateLog(
      { ...RUN, startTime: '2026-10-10T08:00:00+03:00', activeSeconds: 864000, distanceKm: 0 },
      now,
    ),
  ).toThrow('24 hours');
  expect(() => validateLog(RUN, now)).not.toThrow();
});

const WALK: HealthLog = {
  kind: 'workout',
  exerciseType: 'WALKING',
  startTime: '2026-10-25T13:00:00+02:00',
  endTime: '2026-10-25T13:20:00+02:00',
  activeSeconds: 1200,
  provenance: 'user_entered',
};

it("summarizes the tracker's reading, the person's distance first, and overlaps in local time", () => {
  expect(trackerSummary(FOOD)).toBeNull();
  expect(trackerSummary(WALK)).toBeNull();
  const reading = {
    status: 'measured' as const,
    steps: 2400,
    distanceKm: 1.234,
    caloriesKcal: 119.6,
    averageHeartRate: 101,
    overlaps: [
      {
        exerciseType: 'WALKING',
        startTime: '2026-10-25T11:05:00Z',
        endTime: '2026-10-25T11:15:00Z',
      },
      {
        exerciseType: 'WEIGHTLIFTING',
        startTime: '2026-10-25T10:50:00Z',
        endTime: '2026-10-25T11:02:00Z',
      },
    ],
  };
  expect(trackerSummary({ ...WALK, measured: reading })).toEqual({
    values: ['2,400 steps', '1.23 km', '120 kcal', 'avg 101 bpm'],
    overlaps: ['Walk 13:05–13:15', 'Weightlifting 12:50–13:02'],
    canRefresh: false,
  });
  // The person's own distance is the one sent, so the tracker's is not shown beside it.
  expect(trackerSummary({ ...WALK, distanceKm: 2, measured: reading })?.values).toEqual([
    '2,400 steps',
    '120 kcal',
    'avg 101 bpm',
  ]);
  const missing = trackerSummary({ ...WALK, measured: { status: 'no_data' } });
  expect(missing).toMatchObject({ values: [], canRefresh: true });
  expect(missing?.note).toMatch('No Fitbit data');
});

it('the demo replaces a reading the app sends with its own, and keeps one draft per request', async () => {
  const forged = { ...WALK, measured: { status: 'measured' as const, caloriesKcal: 9000 } };
  const draft = await mockClient.proposeAction('walk', forged);
  expect(draft.log).toMatchObject({ measured: { status: 'measured', caloriesKcal: 100 } });
  await expect(mockClient.proposeAction('walk', WALK)).resolves.toMatchObject({ id: draft.id });
  const refreshed = await mockClient.reviseAction(draft.id, 1, draft.log);
  expect(refreshed).toMatchObject({ version: 2, log: { measured: { caloriesKcal: 100 } } });
  await mockClient.cancelAction(draft.id, 2);
});

it("names and checks any of Google's workout types, not only the common ones", () => {
  const now = Date.parse('2026-10-25T12:00:00Z');
  const tennis: HealthLog = { ...WALK, exerciseType: 'TENNIS' };
  expect(logTitle(tennis)).toBe('Tennis');
  expect(exerciseName('KICKBOXING')).toBe('Kickboxing');
  expect(exerciseName('PICKELBALL')).toBe('Pickleball');
  expect(() => validateLog(tennis, now)).not.toThrow();
  expect(() => validateLog({ ...WALK, exerciseType: 'tennis<b>' }, now)).toThrow('workout type');
  // 20 minutes: 4 km is too fast to swim, fine to cycle.
  expect(() => validateLog({ ...WALK, exerciseType: 'SWIMMING', distanceKm: 4 }, now)).toThrow(
    'too far',
  );
  expect(() => validateLog({ ...WALK, exerciseType: 'BIKING', distanceKm: 4 }, now)).not.toThrow();
  expect(Object.keys(workoutChoices('TENNIS'))[0]).toBe('TENNIS');
  expect(workoutChoices('WALKING')).not.toHaveProperty('TENNIS');
  const edited = logFromForm(tennis, { ...formFromLog(tennis), duration: '0:15' });
  expect(edited).toMatchObject({ exerciseType: 'TENNIS', activeSeconds: 900 });
});

it('lists Active Zone Minutes and swim lengths when the tracker recorded them', () => {
  const swim: HealthLog = {
    ...WALK,
    exerciseType: 'SWIMMING_POOL',
    measured: { status: 'measured', averageHeartRate: 120, activeZoneMinutes: 14, swimLengths: 24 },
  };
  expect(trackerSummary(swim)?.values).toEqual([
    'avg 120 bpm',
    '14 Active Zone Minutes',
    '24 lengths',
  ]);
});

describe('estimateNote', () => {
  const entered = {
    kind: 'food',
    foodName: 'Toast',
    consumedAt: '2026-11-05T08:00:00+00:00',
    mealType: 'BREAKFAST',
    energyKcal: 90,
    provenance: 'user_entered',
  } as const;

  it('says nothing about values the person gave', () => {
    expect(estimateNote(entered)).toBeNull();
  });

  it('names where looked-up values came from', () => {
    const looked = {
      ...entered,
      provenance: 'estimated',
      estimateSource: 'USDA FoodData Central: Jute',
    } as const;
    expect(estimateNote(looked)).toContain('USDA FoodData Central: Jute');
  });

  it('stops being an estimate once the person edits it', () => {
    const looked = { ...entered, provenance: 'estimated', estimateSource: 'USDA' } as const;
    const edited = logFromForm(looked, formFromLog(looked));
    expect(estimateNote(edited)).toBeNull();
  });
});

