import type { Evidence, Point } from '@/api/types';

import { chartGeometry } from '../chart';
import { EXPERTS, expertForMetric, expertInfo } from '../experts';
import { heroFrame } from '../hero';
import {
  evidenceLabel,
  formatP,
  formatValue,
  formatWithUnit,
  keyStats,
  shortDate,
  strength,
  timeAgo,
  verdict,
} from '../format';

const points = (values: (number | null)[]): Point[] =>
  values.map((value, i) => ({ date: `2026-10-${String(i + 1).padStart(2, '0')}`, value }));

describe('chartGeometry', () => {
  it('draws one path for a complete series, spanning the box', () => {
    const { paths, min, max } = chartGeometry(points([1, 3, 2]), 100, 50, undefined, 0);
    expect(paths).toEqual(['M0,50 L50,0 L100,25']);
    expect([min, max]).toEqual([1, 3]);
  });

  it('breaks the line at missing days instead of interpolating', () => {
    const { paths, areas } = chartGeometry(points([1, 2, null, 3, 4]), 100, 50);
    expect(paths).toHaveLength(2);
    expect(areas).toHaveLength(2);
  });

  it('closes each filled area down to the bottom edge under its own run', () => {
    const { areas } = chartGeometry(points([1, 3, null, 2]), 90, 50, undefined, 0);
    expect(areas[0]).toBe('M0,50 L30,0 L30,50 L0,50 Z');
    expect(areas[1]).toBe('M90,25 L90,50 L90,50 Z');
  });

  it('draws a flat series through the middle', () => {
    const { paths } = chartGeometry(points([5, 5]), 100, 50, undefined, 0);
    expect(paths).toEqual(['M0,25 L100,25']);
  });

  it('returns nothing to draw without data', () => {
    expect(chartGeometry(points([null, null]), 100, 50).paths).toEqual([]);
    expect(chartGeometry([], 100, 50).paths).toEqual([]);
  });

  it('shades the highlighted window up to the right edge', () => {
    const { highlight } = chartGeometry(points([1, 2, 3, 4, 5]), 100, 50, {
      start: '2026-10-04',
      end: '2026-10-05',
    }, 0);
    expect(highlight).toEqual({ x: 62.5, width: 37.5 });
  });

  it('ignores a highlight outside the series', () => {
    const { highlight } = chartGeometry(points([1, 2]), 100, 50, { start: '2027-01-01', end: '2027-01-02' });
    expect(highlight).toBeNull();
  });
});

describe('formatting', () => {
  it('formats dates without depending on the timezone', () => {
    expect(shortDate('2026-10-01')).toBe('Oct 1');
  });

  it('shows bedtime as a clock time on either side of midnight', () => {
    expect(formatValue('bedtime_hour', -0.5)).toBe('23:30');
    expect(formatValue('bedtime_hour', 1.25)).toBe('01:15');
  });

  it('rounds large values and keeps one decimal for small ones', () => {
    expect(formatValue('steps', 8234.6)).toBe('8,235');
    expect(formatValue('sleep_efficiency', 86.14)).toBe('86.1');
  });

  it('describes how long ago something happened', () => {
    const now = new Date('2026-10-19T12:00:00Z');
    expect(timeAgo('2026-10-19T11:59:40Z', now)).toBe('just now');
    expect(timeAgo('2026-10-19T11:15:00Z', now)).toBe('45 min ago');
    expect(timeAgo('2026-10-19T11:00:00Z', now)).toBe('1 hour ago');
    expect(timeAgo('2026-10-16T12:00:00Z', now)).toBe('3 days ago');
  });

  it('never shows a p-value of zero', () => {
    expect(formatP(0.0000001)).toBe('< 0.001');
    expect(formatP(0.0123)).toBe('0.012');
  });

  it('labels effect sizes regardless of sign', () => {
    expect(strength(-0.71)).toBe('large');
    expect(strength(0.2)).toBe('small');
    expect(strength(0.05)).toBe('negligible');
  });
});

describe('keyStats', () => {
  const base = { id: 'e', metrics: ['sleep_efficiency'], windows: [], n: 27, sufficient: true };

  it('summarizes a window comparison in plain words', () => {
    const evidence: Evidence = {
      ...base,
      tool: 'compare_windows',
      stats: { mean_recent: 86.1, mean_baseline: 91.6, cliffs_delta: -0.71, p_value: 0.0008 },
    };
    expect(keyStats(evidence)).toEqual([
      { label: 'Recent average', value: '86.1%' },
      { label: 'Earlier average', value: '91.6%' },
      { label: 'Effect size', value: '-0.71 (large)' },
      { label: 'p-value', value: '< 0.001' },
      { label: 'Days of data', value: '27' },
    ]);
  });

  it('prefers the adjusted p-value when several lags were tried', () => {
    const evidence: Evidence = {
      ...base,
      tool: 'correlate',
      stats: { rho: -0.58, best_lag: 1, p_value: 0.0015, p_value_adjusted: 0.0045 },
    };
    expect(keyStats(evidence)).toContainEqual({ label: 'p-value (adjusted)', value: '0.004' });
    expect(keyStats(evidence)).toContainEqual({ label: 'Delay', value: '1 day' });
  });

  it('shows the p-value an answer was judged on, after its own checks, and the raw one', () => {
    // From a real answer: time asleep, significant alone but not after 6 checks.
    const evidence: Evidence = {
      ...base,
      metrics: ['sleep_minutes'],
      tool: 'compare_windows',
      stats: {
        mean_recent: 451,
        mean_baseline: 460,
        cliffs_delta: -0.36,
        p_value: 0.0159,
        p_value_run_adjusted: 0.0956,
        tests_in_run: 6,
      },
    };
    expect(keyStats(evidence)).toEqual([
      { label: 'Recent average', value: '7 h 31 min' },
      { label: 'Earlier average', value: '7 h 40 min' },
      { label: 'Effect size', value: '-0.36 (medium)' },
      { label: 'p-value (6 checks)', value: '0.096' },
      { label: 'p-value on its own', value: '0.016' },
      { label: 'Days of data', value: '27' },
    ]);
    expect(verdict(evidence)).toEqual({
      text:
        'Not clear once all 6 checks in this answer are counted: ' +
        'a difference this size can happen by chance',
      clear: false,
    });
    const clear = { ...evidence, stats: { ...evidence.stats, p_value_run_adjusted: 0.04 } };
    expect(verdict(clear)).toEqual({ text: 'A clear change', clear: true });
  });

  it('says plainly when there is no clear result or too few days', () => {
    const steady: Evidence = { ...base, tool: 'compare_windows', stats: { p_value: 0.57 } };
    expect(verdict(steady)?.text).toBe('No clear change');
    expect(verdict({ ...steady, sufficient: false })?.text).toBe('Too few days to tell');
    const link: Evidence = { ...base, tool: 'correlate', stats: { p_value: 0.01 } };
    expect(verdict(link)?.text).toBe('A clear relationship');
    expect(verdict({ ...base, tool: 'describe', stats: {} })).toBeNull();
  });

  it('names evidence by its metrics, or by what it did when it covers many', () => {
    const one: Evidence = { ...base, metrics: ['sleep_minutes'], tool: 'compare_windows', stats: {} };
    expect(evidenceLabel(one)).toBe('Time asleep');
    const pair = { ...one, tool: 'correlate', metrics: ['bedtime_hour', 'sleep_minutes'] };
    expect(evidenceLabel(pair)).toBe('Bedtime & Time asleep');
    const many = { ...pair, tool: 'personal_options', metrics: ['a', 'b', 'c'] } as typeof pair;
    expect(evidenceLabel(many)).toBe('What stands out for you');
    const coverage = { ...one, tool: 'coverage', metrics: ['steps', 'sleep_minutes', 'hrv_ms'] };
    expect(evidenceLabel(coverage)).toBe('Data coverage');
    expect(evidenceLabel(undefined)).toBe('Evidence');
  });

  it('formats values with their units', () => {
    expect(formatWithUnit('sleep_minutes', 451)).toBe('7 h 31 min');
    expect(formatWithUnit('sleep_minutes', 45)).toBe('45 min');
    expect(formatWithUnit('very_active_minutes', 72)).toBe('72 min');
    expect(formatWithUnit('resting_hr', 58.3)).toBe('58.3 bpm');
    expect(formatWithUnit('bedtime_hour', 1.2)).toBe('01:12');
    expect(formatWithUnit('steps', 8234.6)).toBe('8,235');
  });

  it('skips statistics that are missing', () => {
    const evidence: Evidence = { ...base, tool: 'trend', stats: { slope_per_day: null, p_value: null } };
    expect(keyStats(evidence)).toEqual([{ label: 'Days of data', value: '27' }]);
  });
});

describe('experts', () => {
  it('maps every metric family to the expert that owns it', () => {
    expect(expertForMetric('deep_sleep_minutes')).toBe('sleep');
    expect(expertForMetric('steps')).toBe('activity');
    expect(expertForMetric('hrv_ms')).toBe('recovery');
    expect(expertForMetric('readiness')).toBe('recovery');
    expect(expertForMetric('skin_temp_variation_c')).toBe('recovery');
    expect(expertForMetric('unknown_metric')).toBeUndefined();
  });

  it('lists auto first and offers suggestions for every available expert', () => {
    expect(EXPERTS[0].id).toBe('auto');
    for (const expert of EXPERTS.filter((e) => e.available)) {
      expect(expert.suggestions.length).toBeGreaterThan(0);
    }
    expect(expertInfo('general').id).toBe('auto');
  });
});

describe('heroFrame', () => {
  it('starts as a portrait card and ends filling the screen with square corners', () => {
    const start = heroFrame(0, 390, 844);
    expect(start.height).toBeGreaterThan(start.width);
    expect(start.radius).toBe(24);
    expect(heroFrame(1, 390, 844)).toMatchObject({ width: 390, height: 844, radius: 0 });
  });

  it('fits the starting card on a small phone and caps it on a desktop', () => {
    expect(heroFrame(0, 320, 568).width).toBeLessThan(320);
    expect(heroFrame(0, 1440, 900)).toMatchObject({ width: 300, height: 400 });
  });

  it('clamps progress outside 0..1, such as an iOS overscroll bounce', () => {
    expect(heroFrame(-0.5, 390, 844)).toEqual(heroFrame(0, 390, 844));
    expect(heroFrame(2, 390, 844)).toEqual(heroFrame(1, 390, 844));
  });

  it('grows steadily with progress', () => {
    const widths = [0, 0.25, 0.5, 0.75, 1].map((p) => heroFrame(p, 390, 844).width);
    widths.slice(1).forEach((width, i) => expect(width).toBeGreaterThan(widths[i]));
  });
});
