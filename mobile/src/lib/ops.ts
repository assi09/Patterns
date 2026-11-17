// Formatting and thresholds for the operations page (admins only). Pure, so they are tested.

export type Level = 'good' | 'watch' | 'bad';

export function percent(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? '–' : `${Math.round(rate * 100)}%`;
}

export function dollars(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  return value < 1 ? `$${value.toFixed(3)}` : `$${value.toFixed(2)}`;
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–';
  return value < 10 ? `${value.toFixed(1)} s` : `${Math.round(value)} s`;
}

/** How full a cap is, from 0 to 1. */
export function capShare(used: number, cap: number): number {
  return cap > 0 ? Math.min(1, used / cap) : 0;
}

/** A cap is fine below 70%, worth watching to 90%, then needs acting on. */
export function capLevel(used: number, cap: number): Level {
  const share = capShare(used, cap);
  return share < 0.7 ? 'good' : share < 0.9 ? 'watch' : 'bad';
}

/** A rate where higher is better (success, thumbs up, sync success). */
export function rateLevel(rate: number | null | undefined, good = 0.9, watch = 0.75): Level {
  if (rate === null || rate === undefined) return 'watch';
  return rate >= good ? 'good' : rate >= watch ? 'watch' : 'bad';
}

/** A chat answer within 15 s is fine; a minute or more means something is stuck. */
export function latencyLevel(value: number | null | undefined): Level {
  if (value === null || value === undefined) return 'watch';
  return value <= 15 ? 'good' : value < 60 ? 'watch' : 'bad';
}

/** Outcome keys as people read them: "answered_in_part" → "answered in part". */
export function words(key: string): string {
  return key.replace(/_/g, ' ');
}
