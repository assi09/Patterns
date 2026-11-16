import type { DayMetric, NightStages, SleepStageKind, Usual } from '@/api/types';

/** How full a score ring is, 0 to 1: recovery of 100, strain of 21, sleep against the top of the
 * person's usual range (or 8 hours before there is one). */
export function ringFraction(metric: string, value: number | null, usual: Usual | null): number {
  if (value === null || !Number.isFinite(value)) return 0;
  const full =
    metric === 'recovery_score' || metric === 'stress_score'
      ? 100
      : metric === 'strain'
        ? 21
        : metric === 'sleep_minutes'
          ? (usual?.high ?? 480)
          : (usual?.high ?? value);
  return full > 0 ? Math.max(0, Math.min(1, value / full)) : 0;
}

export interface RangeLayout {
  band: [number, number]; // the usual range, as shares of the bar's width
  dot: number | null; // the day's value, as a share of the width
}

/** Where a value and its usual range sit on a bar that spans the last two weeks and both. */
export function rangeLayout(metric: DayMetric): RangeLayout | null {
  const { value, usual, recent } = metric;
  if (!usual) return null;
  const seen = [usual.low, usual.high, ...recent.filter((v): v is number => v !== null)];
  if (value !== null) seen.push(value);
  let low = Math.min(...seen);
  let high = Math.max(...seen);
  // Pad so the band never fills the bar, and a flat history still shows a band.
  const pad = Math.max((high - low) * 0.15, Math.abs(usual.high) * 0.05, 0.5);
  low -= pad;
  high += pad;
  const share = (v: number) => (v - low) / (high - low);
  return {
    band: [share(usual.low), share(usual.high)],
    dot: value === null ? null : share(value),
  };
}

// Stage rows of the night chart, top to bottom.
export const STAGE_ROWS: SleepStageKind[] = ['awake', 'rem', 'light', 'deep'];
const CLASSIC_ROWS: SleepStageKind[] = ['awake', 'restless', 'asleep'];

export function stageRows(night: NightStages): SleepStageKind[] {
  return night.staged === false ? CLASSIC_ROWS : STAGE_ROWS;
}

/** The night as a step line: x from bedtime to waking, y one row per stage. */
export function hypnogramPath(night: NightStages, width: number, height: number): string {
  const stages = night.stages;
  if (!stages.length) return '';
  const rows = stageRows(night);
  const start = Date.parse(stages[0].start);
  const end = Date.parse(stages[stages.length - 1].end);
  const span = Math.max(1, end - start);
  const x = (t: number) => ((t - start) / span) * width;
  const y = (kind: SleepStageKind) => {
    const row = Math.max(0, rows.indexOf(kind));
    return rows.length > 1 ? (row / (rows.length - 1)) * height : height / 2;
  };
  let path = '';
  for (const stage of stages) {
    const x0 = x(Date.parse(stage.start)).toFixed(1);
    const x1 = x(Date.parse(stage.end)).toFixed(1);
    const level = y(stage.stage).toFixed(1);
    path += `${path ? 'L' : 'M'}${x0},${level}L${x1},${level}`;
  }
  return path;
}

/** Minutes in each stage of the night. */
export function stageMinutes(night: NightStages): Partial<Record<SleepStageKind, number>> {
  const out: Partial<Record<SleepStageKind, number>> = {};
  for (const stage of night.stages) {
    const minutes = (Date.parse(stage.end) - Date.parse(stage.start)) / 60_000;
    out[stage.stage] = (out[stage.stage] ?? 0) + minutes;
  }
  return out;
}

/** An arc of a half-circle gauge from its left end, for a share 0 to 1. */
export function gaugeArc(share: number, cx: number, cy: number, r: number): string {
  const angle = Math.PI * (1 - Math.max(0, Math.min(1, share)));
  const x = cx + r * Math.cos(angle);
  const y = cy - r * Math.sin(angle);
  return `M${cx - r},${cy} A${r},${r} 0 0 1 ${x.toFixed(2)},${y.toFixed(2)}`;
}

/** "00:32", in the device's time zone. */
export function clockOf(iso: string): string {
  const moment = new Date(iso);
  return `${String(moment.getHours()).padStart(2, '0')}:${String(moment.getMinutes()).padStart(2, '0')}`;
}
