import { DEMO_SUPERVISOR, mockClient, routeQuestion } from '../mock';
import { saveToken } from '../token';
import type { SendOptions } from '../types';

const AUTO: SendOptions = { expert: 'auto', depth: 'quick' };
const DEEP: SendOptions = { expert: 'auto', depth: 'deep' };

describe('mock API', () => {
  it('backs every finding with evidence included in the report', async () => {
    const report = await mockClient.getLatestReport();
    for (const finding of report.findings) {
      expect(finding.evidenceIds.length).toBeGreaterThan(0);
      for (const id of finding.evidenceIds) {
        expect(report.evidence[id]).toBeDefined();
      }
    }
  });

  it('rates an answer, takes the rating back, and refuses to rate a question', async () => {
    const [question, answer] = await mockClient.sendMessage('How did I sleep?', AUTO);
    expect(answer.rating).toBeUndefined();
    expect((await mockClient.rateAnswer(answer.id, 'up')).rating).toBe('up');
    const chat = await mockClient.getChat(answer.conversationId);
    const stored = chat.find((m) => m.id === answer.id);
    expect(stored?.rating).toBe('up');
    expect((await mockClient.rateAnswer(answer.id, 'down')).rating).toBe('down');
    expect((await mockClient.rateAnswer(answer.id, null)).rating).toBeUndefined();
    await expect(mockClient.rateAnswer(question.id, 'up')).rejects.toThrow(/no longer/);
    await expect(mockClient.rateAnswer('missing', 'up')).rejects.toThrow(/no longer/);
  });

  it('only cites evidence that exists in chat answers', async () => {
    const report = await mockClient.getLatestReport();
    const [, answer] = await mockClient.sendMessage('Why is my sleep worse?', DEEP);
    expect(answer.role).toBe('assistant');
    expect(answer.evidenceIds.length).toBeGreaterThan(0);
    for (const id of answer.evidenceIds) {
      expect(report.evidence[id]).toBeDefined();
    }
  });

  it('serves every cited evidence by id', async () => {
    const report = await mockClient.getLatestReport();
    for (const id of Object.keys(report.evidence)) {
      expect(await mockClient.getEvidence(id)).toEqual(report.evidence[id]);
    }
    await expect(mockClient.getEvidence('missing')).rejects.toThrow();
  });

  it('refuses medical questions without citing evidence', async () => {
    const [, answer] = await mockClient.sendMessage('Do I have sleep apnea?', AUTO);
    expect(answer.refused).toBe(true);
    expect(answer.evidenceIds).toEqual([]);
  });

  it('records which finding a question was about', async () => {
    const attachment = { kind: 'finding', id: 'f_eff' } as const;
    const [question, answer] = await mockClient.sendMessage('Tell me more', {
      ...AUTO,
      attachment,
    });
    expect(question.attachment).toEqual(attachment);
    expect(answer.evidenceIds).toContain('ev_eff');
  });

  it('answers about the attached finding rather than keywords in the question', async () => {
    const [, steps] = await mockClient.sendMessage('Why did this happen?', {
      ...AUTO,
      attachment: { kind: 'finding', id: 'f_steps' },
    });
    expect(steps.evidenceIds).toEqual(['ev_steps']);
  });

  it('keeps chat history across calls', async () => {
    const before = (await mockClient.getChat()).length;
    await mockClient.sendMessage('How are my steps?', AUTO);
    expect(await mockClient.getChat()).toHaveLength(before + 2);
  });

  it('routes a question to the expert that owns its topic', async () => {
    const [, answer] = await mockClient.sendMessage('How is my HRV?', AUTO);
    expect(answer.answeredBy).toBe('recovery');
    expect(answer.routed).toBe(true);
  });

  it('lets a cross-domain question be led by one expert that consults the other', async () => {
    expect(routeQuestion('Did my late nights affect my recovery?')).toEqual(['recovery', 'sleep']);
    const [, deep] = await mockClient.sendMessage('Did my late nights affect my recovery?', DEEP);
    expect(deep.answeredBy).toBe('recovery');
    expect(deep.consulted).toEqual(['sleep']);
    const [, quick] = await mockClient.sendMessage('Did my late nights affect my recovery?', AUTO);
    expect(quick.consulted).toBeUndefined();
  });

  it('sends the question to the chosen expert without routing', async () => {
    const [, answer] = await mockClient.sendMessage('How is my sleep?', {
      expert: 'sleep',
      depth: 'quick',
    });
    expect(answer.answeredBy).toBe('sleep');
    expect(answer.routed).toBe(false);
  });

  it('has a chosen expert consult the owner when asked about other metrics', async () => {
    const [, answer] = await mockClient.sendMessage('How are my steps?', {
      expert: 'sleep',
      depth: 'quick',
    });
    expect(answer.answeredBy).toBe('sleep');
    expect(answer.consulted).toEqual(['activity']);
    expect(answer.evidenceIds).toEqual(['ev_steps']);
  });

  it('still refuses medical questions when an expert is chosen', async () => {
    const [, answer] = await mockClient.sendMessage('Do I have sleep apnea?', {
      expert: 'sleep',
      depth: 'deep',
    });
    expect(answer.refused).toBe(true);
    expect(answer.answeredBy).toBeUndefined();
  });

  it('cites less evidence in a quick answer than a deep one', async () => {
    const [, quick] = await mockClient.sendMessage('Why is my sleep worse?', AUTO);
    const [, deep] = await mockClient.sendMessage('Why is my sleep worse?', DEEP);
    expect(quick.evidenceIds.length).toBeLessThan(deep.evidenceIds.length);
  });

  it('routes by an attached metric', async () => {
    const [, answer] = await mockClient.sendMessage('What happened here?', {
      ...AUTO,
      attachment: { kind: 'metric', metric: 'resting_hr' },
    });
    expect(answer.answeredBy).toBe('recovery');
  });

  it('rejects the nutrition expert while it is unavailable', async () => {
    await expect(
      mockClient.sendMessage('How much protein do I eat?', { expert: 'nutrition', depth: 'quick' }),
    ).rejects.toThrow('not available');
  });

  it('answers questions without a topic generally', async () => {
    const [, answer] = await mockClient.sendMessage('Hello', AUTO);
    expect(answer.answeredBy).toBe('general');
    expect(answer.evidenceIds).toEqual([]);
  });

  it('approves a suggested reminder at the version shown, and refuses a stale one', async () => {
    const [suggested] = (await mockClient.getReminders()).filter((r) => r.status === 'proposed');
    const approved = await mockClient.changeReminder(suggested.id, {
      version: suggested.version,
      status: 'active',
    });
    expect(approved.status).toBe('active');
    expect(approved.nextDueAt).not.toBeNull();
    await expect(
      mockClient.changeReminder(suggested.id, { version: suggested.version, status: 'paused' }),
    ).rejects.toThrow('changed');
  });

  it('creates reminders like the backend, refusing bad ones', async () => {
    const created = await mockClient.createReminder({
      title: 'Stretch',
      message: '',
      schedule: { kind: 'weekly', time: '07:30', weekdays: [5, 6] },
      channels: ['in_app'],
    });
    expect(created.status).toBe('active');
    expect(created.scheduleText).toBe('Weekends at 07:30');
    await expect(
      mockClient.createReminder({
        ...created,
        schedule: { kind: 'once', date: '2020-01-01', time: '07:00' },
      }),
    ).rejects.toThrow('already passed');
    await expect(mockClient.createReminder({ ...created, channels: [] })).rejects.toThrow('Choose');
  });

  it('keeps an inbox with an unread count', async () => {
    const before = await mockClient.getNotifications();
    expect(before.unread).toBeGreaterThan(0);
    await mockClient.readAllNotifications();
    expect((await mockClient.getNotifications()).unread).toBe(0);
  });

  it('saves notification settings and rejects invalid limits', async () => {
    const settings = { quietHours: null, maxPerDay: 3, email: false };
    const saved = await mockClient.updateNotificationSettings(settings);
    expect(saved).toEqual(settings);
    expect(await mockClient.getNotificationSettings()).toEqual(saved);
    await expect(
      mockClient.updateNotificationSettings({ ...settings, maxPerDay: 0 }),
    ).rejects.toThrow('between 1 and 10');
  });

  it('remembers answers to context questions', async () => {
    await mockClient.answerQuestion('q_shift', 'Exams');
    const report = await mockClient.getLatestReport();
    expect(report.questions.find((q) => q.id === 'q_shift')?.answer).toBe('Exams');
  });

  it('returns copies so callers cannot change stored data', async () => {
    const first = await mockClient.getReminders();
    first[0].title = 'Changed by the caller';
    const second = await mockClient.getReminders();
    expect(second[0].title).not.toBe('Changed by the caller');
  });
});

describe('days', () => {
  it('serves the latest day with a usual range and two weeks for each metric', async () => {
    const day = await mockClient.getDay('latest');
    expect(day.date).toBe(day.last);
    expect(day.partial).toBe(true);
    const steps = day.metrics.find((m) => m.metric === 'steps')!;
    expect(steps.usual!.low).toBeLessThanOrEqual(steps.usual!.high);
    expect(steps.recent).toHaveLength(14);
    const earlier = await mockClient.getDay(day.first);
    expect(earlier.partial).toBe(false);
    expect(earlier.metrics[0].usual).toBeNull(); // nothing before the first day
    await expect(mockClient.getDay('2000-01-01')).rejects.toMatchObject({ status: 404 });
  });

  it('serves strain and stress with the day, and their days as metrics', async () => {
    const day = await mockClient.getDay('latest');
    expect(day.strain!.score).toBeLessThanOrEqual(21);
    expect(['light', 'moderate', 'high', 'all_out']).toContain(day.strain!.band);
    expect(day.stress!.score).toBeGreaterThanOrEqual(0);
    const stress = await mockClient.getMetricSeries('stress_score', { days: 7 });
    expect(stress.points).toHaveLength(7);
  });

  it('serves a metric for the days asked for, ending on the day asked for', async () => {
    const { last } = await mockClient.getDay('latest');
    const series = await mockClient.getMetricSeries('resting_hr', { days: 7 });
    expect(series.points).toHaveLength(7);
    expect(series.points.at(-1)!.date).toBe(last);
    await expect(mockClient.getMetricSeries('made_up', { days: 7 })).rejects.toMatchObject({
      status: 404,
    });
  });
});

describe('conversations', () => {
  const OPTIONS = { expert: 'auto' as const, depth: 'quick' as const };

  it('keeps each chat apart, names it by its first question, and deletes it with its messages', async () => {
    const first = await mockClient.createConversation();
    expect(first.title).toBe('New chat');
    await mockClient.sendMessage('How   did I\nsleep?', { ...OPTIONS, conversationId: first.id });
    const second = await mockClient.createConversation();
    await mockClient.sendMessage('Steps this week?', { ...OPTIONS, conversationId: second.id });

    const list = await mockClient.getConversations();
    expect(list[0]).toMatchObject({ id: second.id, title: 'Steps this week?', messages: 2 });
    expect(list.find((c) => c.id === first.id)?.title).toBe('How did I sleep?');
    const sleep = await mockClient.getChat(first.id);
    expect(sleep.map((m) => m.text)[0]).toBe('How   did I\nsleep?');
    expect(sleep.every((m) => m.conversationId === first.id)).toBe(true);
    expect((await mockClient.getChat())[0].text).toBe('Steps this week?'); // the latest

    await mockClient.updateConversation(first.id, { title: 'Sleep' });
    await mockClient.deleteConversation(second.id);
    const left = await mockClient.getConversations();
    expect(left.map((c) => c.title)).toContain('Sleep');
    expect(left.some((c) => c.id === second.id)).toBe(false);
    await expect(mockClient.getChat(second.id)).rejects.toMatchObject({ status: 404 });
  });
});

describe('editing and organising chats', () => {
  const OPTIONS = { expert: 'auto' as const, depth: 'quick' as const };

  it('lists pinned chats first', async () => {
    const older = await mockClient.createConversation();
    await mockClient.sendMessage('Older', { ...OPTIONS, conversationId: older.id });
    const newer = await mockClient.createConversation();
    await mockClient.sendMessage('Newer', { ...OPTIONS, conversationId: newer.id });
    await mockClient.updateConversation(older.id, { pinned: true });
    const list = await mockClient.getConversations();
    expect(list[0]).toMatchObject({ id: older.id, pinned: true });
  });

  it('replaces an edited question and what followed it, in its own chat', async () => {
    const chat = await mockClient.createConversation();
    const [first] = await mockClient.sendMessage('How did I sleep?', {
      ...OPTIONS,
      conversationId: chat.id,
    });
    await mockClient.sendMessage('And on weekends?', { ...OPTIONS, conversationId: chat.id });
    const edited = await mockClient.sendMessage('How did I sleep in October?', {
      ...OPTIONS,
      replaces: first.id,
    });
    expect(edited[0].conversationId).toBe(chat.id);
    const texts = (await mockClient.getChat(chat.id)).map((m) => m.text);
    expect(texts[0]).toBe('How did I sleep in October?');
    expect(texts).toHaveLength(2);
    const answer = (await mockClient.getChat(chat.id))[1];
    await expect(
      mockClient.sendMessage('Again', { ...OPTIONS, replaces: answer.id }),
    ).rejects.toMatchObject({ status: 404 }); // an answer is not a question
  });
});

describe('the rest of Today', () => {
  it("saves only today's check-in, with a rating from 1 to 5", async () => {
    const { last } = await mockClient.getDay('latest');
    expect(await mockClient.getCheckIn(last)).toBeNull();
    await mockClient.saveCheckIn({ day: last, rating: 4, tags: ['stress'] });
    expect(await mockClient.getCheckIn(last)).toEqual({ day: last, rating: 4, tags: ['stress'] });
    await expect(mockClient.saveCheckIn({ day: last, rating: 6, tags: [] })).rejects.toMatchObject({
      status: 422,
    });
    await expect(
      mockClient.saveCheckIn({ day: '2000-01-01', rating: 3, tags: [] }),
    ).rejects.toMatchObject({ code: 'invalid_checkin' });
  });

  it('serves a day with its recovery, workouts and 24 hours of steps', async () => {
    const day = await mockClient.getDay('latest');
    expect(day.recovery?.score).toBeGreaterThan(0);
    expect((await mockClient.getHourlySteps(day.last)).steps).toHaveLength(24);
    const { workouts } = await mockClient.getWorkouts(day.last);
    expect(workouts[0]).toMatchObject({ exerciseType: 'WALKING', activeSeconds: 2100 });
  });
});

describe('teams', () => {
  it('previews, joins with the consent read, shares levels after a second consent, and leaves', async () => {
    await expect(mockClient.previewTeam('NOPE')).rejects.toMatchObject({ code: 'unknown_code' });
    const preview = await mockClient.previewTeam('demo-2345'); // typed loosely
    expect(preview.team).toBe('Design');
    expect(preview.consent).toContain('at least 5 people');
    await expect(mockClient.joinTeam('DEMO2345', 'old')).rejects.toMatchObject({
      code: 'consent_changed',
    });
    const joined = await mockClient.joinTeam('DEMO2345', preview.consentVersion);
    expect(joined.shareLevels).toBe(false);
    await expect(mockClient.joinTeam('DEMO2345', preview.consentVersion)).rejects.toMatchObject({
      code: 'already_member',
    });
    await expect(mockClient.shareTeamLevels(joined.teamId, true)).rejects.toMatchObject({
      code: 'consent_changed',
    });
    const shared = await mockClient.shareTeamLevels(
      joined.teamId,
      true,
      joined.levelsConsentVersion,
    );
    expect(shared.shareLevels).toBe(true);
    expect((await mockClient.getMyTeams())[0].shareLevels).toBe(true);
    await mockClient.leaveTeam(joined.teamId);
    expect(await mockClient.getMyTeams()).toEqual([]);
  });
});

describe('reminders through the chat', () => {
  it('prepares a reminder to tap on, off until it is set', async () => {
    const [, answer] = await mockClient.sendMessage(
      'Remind me every weeknight at 22:30 to wind down',
      AUTO,
    );
    const [id] = answer.reminderIds ?? [];
    const reminder = (await mockClient.getReminders()).find((r) => r.id === id);
    expect(reminder?.status).toBe('proposed');
    expect(reminder?.scheduleText).toBe('Weeknights at 22:30');
    expect(reminder?.title).toBe('Wind down');
    const set = await mockClient.changeReminder(id, {
      version: reminder!.version,
      status: 'active',
    });
    expect(set.nextDueAt).not.toBeNull();
  });
});

describe('alerts', () => {
  it('asks whether an alert was useful and keeps the answer', async () => {
    const alert = (await mockClient.getNotifications()).items.find((n) => n.alarmId);
    expect(alert?.alarmFeedback).toBeNull();
    await mockClient.sendAlarmFeedback(alert!.alarmId!, false);
    const after = (await mockClient.getNotifications()).items.find((n) => n.id === alert!.id);
    expect(after?.alarmFeedback).toBe('not_useful');
  });

  it('keeps alert settings', async () => {
    const changed = {
      enabled: true,
      mutedKinds: ['finding' as const],
      sensitivity: 'fewer' as const,
    };
    expect(await mockClient.updateAlarmSettings(changed)).toEqual(changed);
    expect(await mockClient.getAlarmSettings()).toEqual(changed);
  });
});

describe('memory', () => {
  it('moves a fact from waiting to kept when the person keeps it', async () => {
    const before = await mockClient.getMemory();
    const [fact] = before.waiting;
    await mockClient.decideMemory(fact.id, true);
    const after = await mockClient.getMemory();
    expect(after.waiting.map((f) => f.id)).not.toContain(fact.id);
    expect(after.kept.map((f) => f.id)).toContain(fact.id);
    await expect(mockClient.decideMemory(fact.id, true)).rejects.toMatchObject({ status: 422 });
  });

  it('refuses a medical rewording, and forgets on request', async () => {
    const [fact] = (await mockClient.getMemory()).kept;
    await expect(mockClient.rewordMemory(fact.id, 'Has insomnia')).rejects.toMatchObject({
      status: 422,
    });
    expect((await mockClient.rewordMemory(fact.id, 'Goes to bed early')).text).toBe(
      'Goes to bed early',
    );
    await mockClient.forgetMemory(fact.id);
    await expect(mockClient.forgetMemory(fact.id)).rejects.toMatchObject({ status: 404 });
  });

  it('asks about what the person asked to have remembered', async () => {
    await mockClient.sendMessage('Please remember that I train on Sundays', {
      expert: 'auto',
      depth: 'quick',
    });
    const { waiting } = await mockClient.getMemory();
    expect(waiting.map((f) => f.text)).toContain('I train on Sundays');
  });
});


describe('the team agent in the mock', () => {
  async function teamId(): Promise<string> {
    const signed = await mockClient.logIn(DEMO_SUPERVISOR);
    await saveToken(signed.token);
    const teams = await mockClient.getTeams();
    return (teams[0] ?? (await mockClient.createTeam('Design'))).id;
  }

  it('never answers about one person', async () => {
    const id = await teamId();
    const reply = await mockClient.askTeamAgent(id, 'Who is sleeping the worst?');
    expect(reply.messages.map((m) => m.role)).toEqual(['supervisor', 'agent']);
    expect(reply.messages[1].text).toMatch(/as a whole/);
    expect(reply.proposed).toEqual([]);
  });

  it('proposes an action that waits for approval and is decided once', async () => {
    const id = await teamId();
    const { proposed } = await mockClient.askTeamAgent(id, 'What could we try?');
    expect(proposed[0].status).toBe('proposed');
    const done = await mockClient.decideTeamAction(id, proposed[0].id, true);
    expect(done.action.status).toBe('approved');
    await expect(mockClient.decideTeamAction(id, proposed[0].id, false)).rejects.toThrow(
      /already decided/,
    );
  });

  it('lets the supervisor rate an answer, never their own question', async () => {
    const id = await teamId();
    const { messages } = await mockClient.askTeamAgent(id, 'How is the team?');
    const [asked, said] = messages;
    expect(said.rating).toBeNull();
    expect((await mockClient.rateTeamAnswer(id, said.id, 'down')).rating).toBe('down');
    const stored = (await mockClient.getTeamChat(id)).find((m) => m.id === said.id);
    expect(stored?.rating).toBe('down');
    expect((await mockClient.rateTeamAnswer(id, said.id, null)).rating).toBeNull();
    await expect(mockClient.rateTeamAnswer(id, asked.id, 'up')).rejects.toThrow(/no longer/);
  });

  it('keeps notes about the team and refuses ones about a person', async () => {
    const id = await teamId();
    const note = await mockClient.addTeamNote(id, 'Release deadline', '2026-11-03');
    expect((await mockClient.getTeamNotes(id)).map((n) => n.id)).toContain(note.id);
    await expect(mockClient.addTeamNote(id, 'She is off sick')).rejects.toThrow(/Not saved/);
    await mockClient.deleteTeamNote(id, note.id);
    expect((await mockClient.getTeamNotes(id)).map((n) => n.id)).not.toContain(note.id);
  });
});
