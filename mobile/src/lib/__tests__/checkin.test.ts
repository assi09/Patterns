import { goesOut } from '../checkin';

describe('when a check-in alert goes out', () => {
  const now = new Date(2026, 10, 25, 11, 17, 0);

  it('gives the exact time and the minutes left', () => {
    expect(goesOut(new Date(2026, 10, 25, 12, 0, 0).toISOString(), now)).toBe(
      'at 12:00 (in 43 min)',
    );
  });

  it('names the day when it is not today', () => {
    const late = new Date(2026, 10, 25, 23, 45, 0);
    const text = goesOut(new Date(2026, 10, 26, 0, 45, 0).toISOString(), late);
    expect(text).toBe('at 00:45 on Thursday 26 Nov (in 60 min)');
  });

  it('says it is due once the time has passed', () => {
    expect(goesOut(new Date(2026, 10, 25, 11, 0, 0).toISOString(), now)).toBe(
      'any moment now (it was due at 11:00)',
    );
  });
});
