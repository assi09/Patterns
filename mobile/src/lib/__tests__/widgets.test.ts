import type { NightStages } from '@/api/types';
import {
  gaugeArc,
  hypnogramPath,
  rangeLayout,
  ringFraction,
  stageMinutes,
  stageRows,
} from '../widgets';

const usual = { median: 60, low: 55, high: 65, days: 28 };

describe('ringFraction', () => {
  it('fills recovery out of 100, strain out of 21 and sleep against the usual top', () => {
    expect(ringFraction('recovery_score', 74, null)).toBeCloseTo(0.74);
    expect(ringFraction('strain', 21, null)).toBe(1);
    expect(ringFraction('sleep_minutes', 420, { ...usual, high: 480 })).toBeCloseTo(0.875);
    expect(ringFraction('sleep_minutes', 240, null)).toBeCloseTo(0.5); // 8 hours before a range
  });
  it('never goes past full or below empty, and is empty without a value', () => {
    expect(ringFraction('sleep_minutes', 600, { ...usual, high: 480 })).toBe(1);
    expect(ringFraction('strain', -3, null)).toBe(0);
    expect(ringFraction('recovery_score', null, null)).toBe(0);
  });
});

describe('rangeLayout', () => {
  it('puts the band and the day inside the bar, the day where it falls', () => {
    const layout = rangeLayout({
      metric: 'resting_hr',
      value: 57,
      usual,
      recent: [56, 60, 64, null, 58],
    })!;
    const [low, high] = layout.band;
    expect(low).toBeGreaterThan(0);
    expect(high).toBeLessThan(1);
    expect(layout.dot).toBeGreaterThan(low);
    expect(layout.dot).toBeLessThan(high);
  });
  it('places a day outside the usual range outside the band, still on the bar', () => {
    const layout = rangeLayout({ metric: 'resting_hr', value: 80, usual, recent: [] })!;
    expect(layout.dot).toBeGreaterThan(layout.band[1]);
    expect(layout.dot).toBeLessThan(1);
  });
  it('has nothing to draw without a usual range, and no dot without a value', () => {
    expect(rangeLayout({ metric: 'hrv_ms', value: 40, usual: null, recent: [] })).toBeNull();
    expect(rangeLayout({ metric: 'hrv_ms', value: null, usual, recent: [] })!.dot).toBeNull();
  });
  it('still shows a band when every day was the same', () => {
    const flat = { median: 0, low: 0, high: 0, days: 28 };
    const layout = rangeLayout({
      metric: 'skin_temp_variation_c',
      value: 0,
      usual: flat,
      recent: [0],
    })!;
    expect(layout.band[0]).toBeGreaterThan(0);
    expect(layout.band[1]).toBeLessThan(1);
  });
});

const night: NightStages = {
  available: true,
  staged: true,
  stages: [
    { start: '2026-11-15T23:00:00Z', end: '2026-11-16T01:00:00Z', stage: 'light' },
    { start: '2026-11-16T01:00:00Z', end: '2026-11-16T02:00:00Z', stage: 'deep' },
    { start: '2026-11-16T02:00:00Z', end: '2026-11-16T03:00:00Z', stage: 'awake' },
  ],
};

describe('the night chart', () => {
  it('runs from the first stage at the left to the last at the right, a row per stage', () => {
    const path = hypnogramPath(night, 400, 90);
    expect(path.startsWith('M0.0,60.0L200.0,60.0')).toBe(true); // light is the third of four rows
    expect(path).toContain('L300.0,90.0'); // deep, the bottom row
    expect(path.endsWith('L400.0,0.0')).toBe(true); // awake, the top row
    expect(hypnogramPath({ available: false, stages: [] }, 400, 90)).toBe('');
  });
  it('uses three rows for a classic night', () => {
    expect(stageRows({ ...night, staged: false })).toEqual(['awake', 'restless', 'asleep']);
  });
  it('adds up the minutes in each stage', () => {
    expect(stageMinutes(night)).toEqual({ light: 120, deep: 60, awake: 60 });
  });
});

describe('gaugeArc', () => {
  it('starts at the left end and reaches the top at half', () => {
    expect(gaugeArc(0.5, 50, 50, 40)).toBe('M10,50 A40,40 0 0 1 50.00,10.00');
    expect(gaugeArc(2, 50, 50, 40)).toBe('M10,50 A40,40 0 0 1 90.00,50.00');
  });
});
