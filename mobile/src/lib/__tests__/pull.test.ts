import { PULL_TRIGGER, pullDistance } from '../pull';

describe('web pull to refresh', () => {
  it('ignores upward moves and damps the pull', () => {
    expect(pullDistance(-40)).toBe(0);
    expect(pullDistance(0)).toBe(0);
    expect(pullDistance(100)).toBe(50);
  });
  it('needs a deliberate pull to refresh, and stops growing', () => {
    expect(pullDistance(100)).toBeLessThan(PULL_TRIGGER); // a short swipe is a scroll, not a refresh
    expect(pullDistance(PULL_TRIGGER * 2)).toBeGreaterThanOrEqual(PULL_TRIGGER);
    expect(pullDistance(10_000)).toBe(pullDistance(1_000));
  });
});
