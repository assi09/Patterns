import type { Evidence, ISODate, Window } from '@/api/types';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-10-19" -> "Oct 19". Parsed by hand so the result does not depend on the device timezone. */
export function shortDate(date: ISODate): string {
  const [, month, day] = date.split('-').map(Number);
  return `${MONTHS[month - 1]} ${day}`;
}

/** "2 hours ago" style, relative to `now`. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

export function windowLabel(window: Window): string {
  return `${shortDate(window.start)} – ${shortDate(window.end)}`;
}

export const METRIC_LABELS: Record<string, string> = {
  steps: 'Steps',
  calories: 'Calories',
  distance_km: 'Distance',
  active_zone_minutes: 'Active Zone Minutes',
  cardio_load: 'Cardio load',
  resting_hr: 'Resting heart rate',
  hrv_ms: 'Heart rate variability',
  respiratory_rate: 'Breathing rate',
  readiness: 'Readiness',
  recovery_score: 'Recovery',
  strain: 'Strain',
  stress_score: 'Stress',
  daytime_heart_rate: 'Heart rate while still',
  hr_zone_light_minutes: 'Light zone',
  hr_zone_moderate_minutes: 'Fat burn zone',
  hr_zone_vigorous_minutes: 'Cardio zone',
  hr_zone_peak_minutes: 'Peak zone',
  sedentary_minutes: 'Sedentary time',
  lightly_active_minutes: 'Light activity',
  moderately_active_minutes: 'Moderate activity',
  very_active_minutes: 'Vigorous activity',
  wear_minutes: 'Wear time',
  sleep_minutes: 'Time asleep',
  time_in_bed: 'Time in bed',
  sleep_efficiency: 'Sleep efficiency',
  bedtime_hour: 'Bedtime',
  sleep_score: 'Sleep score',
  deep_sleep_minutes: 'Deep sleep',
  light_sleep_minutes: 'Light sleep',
  rem_sleep_minutes: 'REM sleep',
  awake_in_bed_minutes: 'Awake in bed',
  skin_temp_variation_c: 'Skin temperature',
};

export function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? metric.replace(/_/g, ' ');
}

/** Formats a value in the metric's natural unit, e.g. bedtime 0.5 -> "00:30". */
export function formatValue(metric: string, value: number): string {
  if (metric === 'bedtime_hour') {
    const minutes = Math.round(((value % 24) + 24) % 24 * 60);
    const hh = String(Math.floor(minutes / 60) % 24).padStart(2, '0');
    const mm = String(minutes % 60).padStart(2, '0');
    return `${hh}:${mm}`;
  }
  const digits = Math.abs(value) >= 100 ? 0 : 1;
  return value.toLocaleString('en-US', { maximumFractionDigits: digits });
}

// Metrics counted in minutes: sleep reads best as hours and minutes, activity as minutes.
const SLEEP_MINUTES = new Set([
  'sleep_minutes',
  'time_in_bed',
  'deep_sleep_minutes',
  'light_sleep_minutes',
  'rem_sleep_minutes',
  'awake_in_bed_minutes',
  'wear_minutes',
  'sedentary_minutes',
]);
const ACTIVE_MINUTES = new Set([
  'active_zone_minutes',
  'lightly_active_minutes',
  'moderately_active_minutes',
  'very_active_minutes',
]);
const UNITS: Record<string, string> = {
  sleep_efficiency: '%',
  resting_hr: ' bpm',
  hrv_ms: ' ms',
  respiratory_rate: ' breaths/min',
  distance_km: ' km',
  skin_temp_variation_c: ' °C',
  calories: ' kcal',
};

/** A value with its unit, for reading on its own: 451 min -> "7 h 31 min", 96.6 -> "96.6%". */
export function formatWithUnit(metric: string, value: number): string {
  if (SLEEP_MINUTES.has(metric) && Math.abs(value) >= 60) {
    const minutes = Math.round(Math.abs(value));
    const text = `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
    return value < 0 ? `-${text}` : text;
  }
  if (SLEEP_MINUTES.has(metric) || ACTIVE_MINUTES.has(metric)) {
    return `${formatValue(metric, value)} min`;
  }
  return `${formatValue(metric, value)}${UNITS[metric] ?? ''}`;
}

// Tools that test something; their p-value decides whether a result is clear.
const TESTS = new Set(['compare_windows', 'trend', 'correlate', 'change_point', 'weekday_split']);

export interface Verdict {
  text: string;
  clear: boolean;
}

/**
 * What a test's result means in plain words. It is judged on the p-value the answer was checked
 * against: corrected for all the tests in that answer when there were several.
 */
export function verdict(evidence: Evidence): Verdict | null {
  if (!TESTS.has(evidence.tool)) return null;
  if (!evidence.sufficient) return { text: 'Too few days to tell', clear: false };
  const s = evidence.stats;
  const num = (key: string) => (typeof s[key] === 'number' ? (s[key] as number) : null);
  const judged = num('p_value_run_adjusted') ?? num('p_value_adjusted') ?? num('p_value');
  if (judged === null) return null;
  const relation = evidence.tool === 'correlate';
  if (judged < 0.05) {
    return { text: relation ? 'A clear relationship' : 'A clear change', clear: true };
  }
  const raw = num('p_value');
  const tests = num('tests_in_run');
  if (raw !== null && raw < 0.05 && tests) {
    return {
      text:
        `Not clear once all ${tests} checks in this answer are counted: ` +
        'a difference this size can happen by chance',
      clear: false,
    };
  }
  return { text: relation ? 'No clear relationship' : 'No clear change', clear: false };
}

const TOOL_LABELS: Record<string, string> = {
  describe: 'Summary',
  coverage: 'Data coverage',
  compare_windows: 'Compared two periods',
  trend: 'Trend over time',
  correlate: 'Relationship between metrics',
  compare_day: 'One day against your usual',
  change_point: 'When a change began',
  weekday_split: 'Weekends and weekdays',
  habit_options: 'Habits checked on your days',
  personal_options: 'What stands out for you',
  sleep_regularity: 'Sleep regularity',
  training_load: 'Training load',
  rank_days: 'Best and worst days',
  usual_ranges: 'Your usual ranges',
  checkins: 'Your check-ins',
  tag_effect: 'Days you tagged',
};

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}

/**
 * Short name for a piece of evidence, e.g. "Time asleep" or "Bedtime & Time asleep". Evidence
 * about many metrics at once, such as a data coverage check, is named by what it did instead.
 */
export function evidenceLabel(evidence: Evidence | undefined): string {
  if (!evidence) return 'Evidence';
  if (evidence.metrics.length > 2 || evidence.tool === 'coverage') return toolLabel(evidence.tool);
  return evidence.metrics.map(metricLabel).join(' & ');
}

/** Tiny p-values show as "< 0.001" rather than 0. */
export function formatP(p: number): string {
  if (p < 0.001) return '< 0.001';
  return p.toFixed(3);
}

/** Strength of a rank-based effect size (Cliff's delta or Spearman rho), by common rules of thumb. */
export function strength(effect: number): 'negligible' | 'small' | 'medium' | 'large' {
  const size = Math.abs(effect);
  if (size < 0.15) return 'negligible';
  if (size < 0.33) return 'small';
  if (size < 0.47) return 'medium';
  return 'large';
}

export interface StatLine {
  label: string;
  value: string;
}

/** The few statistics worth showing for a piece of evidence, in plain words. */
export function keyStats(evidence: Evidence): StatLine[] {
  const s = evidence.stats;
  const num = (key: string) => (typeof s[key] === 'number' ? (s[key] as number) : null);
  const metric = evidence.metrics[0];
  const lines: StatLine[] = [];

  if (evidence.tool === 'compare_windows') {
    const recent = num('mean_recent');
    const baseline = num('mean_baseline');
    const delta = num('cliffs_delta');
    if (recent !== null) {
      lines.push({ label: 'Recent average', value: formatWithUnit(metric, recent) });
    }
    if (baseline !== null) {
      lines.push({ label: 'Earlier average', value: formatWithUnit(metric, baseline) });
    }
    if (delta !== null) lines.push({ label: 'Effect size', value: `${delta.toFixed(2)} (${strength(delta)})` });
  } else if (evidence.tool === 'trend') {
    const slope = num('slope_per_day');
    const change = num('change_over_window');
    if (slope !== null) {
      lines.push({ label: 'Change per day', value: formatWithUnit(metric, slope) });
    }
    if (change !== null) {
      lines.push({ label: 'Change over period', value: formatWithUnit(metric, change) });
    }
  } else if (evidence.tool === 'correlate') {
    const rho = num('rho');
    const lag = num('best_lag');
    if (rho !== null) lines.push({ label: 'Correlation', value: `${rho.toFixed(2)} (${strength(rho)})` });
    if (lag !== null) lines.push({ label: 'Delay', value: lag === 0 ? 'same day' : `${lag} day${lag > 1 ? 's' : ''}` });
  }

  // Show the p-value the result was judged on: corrected for the answer's own tests, or for the
  // report's, when there were several; the raw value alongside, since both matter.
  const raw = num('p_value');
  const run = num('p_value_run_adjusted');
  const tests = num('tests_in_run');
  const adjusted = run ?? num('p_value_adjusted');
  if (adjusted !== null && raw !== null && adjusted !== raw) {
    const across = run !== null && tests ? ` (${tests} checks)` : ' (adjusted)';
    lines.push({ label: `p-value${across}`, value: formatP(adjusted) });
    lines.push({ label: 'p-value on its own', value: formatP(raw) });
  } else if (adjusted !== null || raw !== null) {
    lines.push({ label: 'p-value', value: formatP((adjusted ?? raw) as number) });
  }
  lines.push({ label: 'Days of data', value: String(evidence.n) });
  return lines;
}
