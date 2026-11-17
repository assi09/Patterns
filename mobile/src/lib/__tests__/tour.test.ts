import { TOUR_STEPS, tourKey } from '../tour';

const MEDICAL =
  /diagnos|disease|illness|condition|treat|medic(ine|ation)|doctor|supplement|diet\b/i;

describe('first-use guide', () => {
  it('covers getting the data in, the main screens, the team and privacy', () => {
    const titles = TOUR_STEPS.map((s) => s.title).join(' | ');
    for (const part of ['Connect your Fitbit', 'Today', 'Ask', 'Reminders', 'team', 'Your data']) {
      expect(titles).toContain(part);
    }
  });
  it('says nothing medical beyond saying it is not medical advice', () => {
    for (const step of TOUR_STEPS) {
      const text = [step.title, step.body, ...step.points]
        .join(' ')
        .replace('not medical advice', '');
      expect(text).not.toMatch(MEDICAL);
    }
  });
  it('links only to screens that exist, and keeps each step short', () => {
    for (const step of TOUR_STEPS) {
      if (step.action) expect(['/settings', '/teams', '/ask']).toContain(step.action.href);
      expect(step.points.length).toBeLessThanOrEqual(3);
    }
  });
  it('keys the seen flag per account without writing the email', () => {
    expect(tourKey('Person@Example.com ')).toBe(tourKey('person@example.com'));
    expect(tourKey('a@example.com')).not.toBe(tourKey('b@example.com'));
    expect(tourKey('person@example.com')).not.toContain('example');
    expect(tourKey('person@example.com')).toMatch(/^[A-Za-z0-9._-]+$/); // SecureStore's rule
  });
});
