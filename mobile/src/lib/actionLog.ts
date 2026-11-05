import type { HealthAction, HealthLog } from '@/api/types';

type FoodLog = Extract<HealthLog, { kind: 'food' }>;
type WorkoutLog = Extract<HealthLog, { kind: 'workout' }>;

export const MEALS: Record<FoodLog['mealType'], string> = {
  BREAKFAST: 'Breakfast',
  LUNCH: 'Lunch',
  DINNER: 'Dinner',
  SNACK: 'Snack',
};

// The same names and speed limits as backend/app/actions/exercises.py. The agent can log any of
// Google's workout types; the edit form offers the common ones and the entry's own.
const NAMES: Record<string, string> = {
  RUNNING: 'Run',
  WALKING: 'Walk',
  BIKING: 'Bike',
  HIKING: 'Hike',
  AEROBIC_WORKOUT: 'Aerobic workout',
  PICKELBALL: 'Pickleball',
  HIIT: 'HIIT',
  TRX: 'TRX',
  FOOTBALL_AMERICAN: 'American football',
  FOOTBALL_AUSTRALIAN: 'Australian football',
  FRISBEE_PLAYING_GENERAL: 'Frisbee',
  VOLLEYBALL_BEACH: 'Beach volleyball',
  SWIMMING_POOL: 'Pool swim',
  SWIMMING_OPEN_WATER: 'Open water swim',
  YOGA_BIKRAM: 'Bikram yoga',
  YOGA_HATHA: 'Hatha yoga',
  YOGA_POWER: 'Power yoga',
  YOGA_VINYASA: 'Vinyasa yoga',
  WALK_WITH_WEIGHTS: 'Walk with weights',
  MEDITATE: 'Meditation',
  OTHER: 'Other workout',
};

/** "WEIGHTLIFTING" -> "Weightlifting", "RUNNING" -> "Run". */
export function exerciseName(type: string): string {
  if (type in NAMES) return NAMES[type];
  const words = type.toLowerCase().replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const COMMON_WORKOUTS = ['WALKING', 'RUNNING', 'BIKING', 'WEIGHTLIFTING', 'YOGA', 'WORKOUT'];

/** The types the edit form offers: the common ones, and the entry's own if it is another. */
export function workoutChoices(current: string): Record<string, string> {
  const types = COMMON_WORKOUTS.includes(current) ? COMMON_WORKOUTS : [current, ...COMMON_WORKOUTS];
  return Object.fromEntries(types.map((type) => [type, exerciseName(type)]));
}

const RUN = ['RUNNING', 'TRAIL_RUN', 'TREADMILL', 'INCLINE_RUN', 'ORIENTEERING', 'TRACK_AND_FIELD'];
// prettier-ignore
const ON_FOOT = [
  ...RUN,
  'WALKING', 'HIKING', 'TREADMILL_WALK', 'INCLINE_WALK', 'POWER_WALKING', 'NORDIC_WALKING',
  'STROLLER_WALK', 'WALK_WITH_WEIGHTS', 'RUCKING', 'BACKPACKING', 'SNOWSHOEING',
];
// prettier-ignore
const WHEELS = [
  'BIKING', 'MOUNTAIN_BIKE', 'OUTDOOR_BIKE', 'STATIONARY_BIKE', 'SPINNING', 'ELECTRIC_BIKE',
  'HAND_CYCLING', 'ASSAULT_BIKE', 'UNICYCLING', 'WHEELCHAIR',
];
const SWIM = ['SWIMMING', 'SWIMMING_POOL', 'SWIMMING_OPEN_WATER'];
const PADDLE = ['ROWING', 'ROWING_MACHINE', 'KAYAKING', 'CANOEING', 'PADDLEBOARDING'];
const SKATE = ['ROLLERBLADING', 'ROLLER_SKATING', 'ICE_SKATING', 'SKATING', 'SPEED_SKATING'];

/** Fastest plausible average over the active time, in km/h; none for most sports. */
function maxSpeedKmh(type: string): number | undefined {
  if (RUN.includes(type)) return 25;
  if (ON_FOOT.includes(type)) return 10;
  if (WHEELS.includes(type)) return 80;
  if (SWIM.includes(type)) return 10;
  if (PADDLE.includes(type)) return 25;
  if (SKATE.includes(type)) return 60;
  return undefined;
}

/** A broad group for the entry's icon. */
export function workoutGroup(type: string): 'foot' | 'run' | 'wheels' | 'swim' | 'other' {
  if (RUN.includes(type)) return 'run';
  if (ON_FOOT.includes(type)) return 'foot';
  if (WHEELS.includes(type)) return 'wheels';
  if (SWIM.includes(type)) return 'swim';
  return 'other';
}

export const STATUS: Record<HealthAction['status'], string> = {
  draft: 'Draft',
  executing: 'Checking',
  succeeded: 'Logged',
  failed: 'Not logged',
  unknown: 'Checking',
  cancelled: 'Cancelled',
  undoing: 'Removing',
  undone: 'Removed',
};

// The same limits as the backend (backend/app/actions/schemas.py), so mistakes show while typing.
const MAX_KCAL = 5000;
const MAX_MACRO_G = 500;
const MAX_WORKOUT_S = 24 * 3600;
const MAX_DISTANCE_KM = 300;
const FUTURE_GRACE_MS = 15 * 60_000;

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

interface Wall {
  date: string; // 2026-10-24
  time: string; // 13:00
  offset: string; // +03:00
}

/** The date and time as the person entered them, in the entry's own time zone. */
function wall(iso: string): Wall {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.exec(
    iso,
  );
  if (!match) throw new Error('Use a date and time with a timezone.');
  return { date: match[1], time: match[2], offset: match[3] === 'Z' ? '+00:00' : match[3] };
}

function dayLabel(date: string): string {
  const [year, month, day] = date.split('-').map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return `${DAYS[weekday]} ${day} ${MONTHS[month - 1]}`;
}

export function duration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
}

function grams(value: number): string {
  return `${Math.round(value * 10) / 10} g`;
}

/** "Lunch · Chicken salad", or "Run". */
export function logTitle(log: HealthLog): string {
  return log.kind === 'food'
    ? `${MEALS[log.mealType]} · ${log.foodName}`
    : exerciseName(log.exerciseType);
}

/** The parts of the summary line, e.g. ["Sat 24 Oct, 13:00", "550 kcal", "P 40 g · C 30 g"]. */
/** Says the values are looked up, not the person's, so they check them before confirming. */
export function estimateNote(log: HealthLog): string | null {
  if (log.kind !== 'food' || log.provenance !== 'estimated') return null;
  return `Estimated from ${log.estimateSource ?? 'a food lookup'}. Check it before you confirm.`;
}

export function logDetails(log: HealthLog): string[] {
  if (log.kind === 'food') {
    const at = wall(log.consumedAt);
    const macros = [
      log.proteinG != null && `P ${grams(log.proteinG)}`,
      log.carbohydrateG != null && `C ${grams(log.carbohydrateG)}`,
      log.fatG != null && `F ${grams(log.fatG)}`,
    ].filter(Boolean);
    return [
      `${dayLabel(at.date)}, ${at.time}`,
      ...(log.energyKcal != null ? [`${Math.round(log.energyKcal)} kcal`] : []),
      ...(macros.length ? [macros.join(' · ')] : []),
    ];
  }
  const start = wall(log.startTime);
  const end = wall(log.endTime);
  return [
    `${dayLabel(start.date)}, ${start.time}–${end.time}`,
    duration(log.activeSeconds),
    ...(log.distanceKm != null ? [`${Math.round(log.distanceKm * 100) / 100} km`] : []),
  ];
}

export interface TrackerSummary {
  values: string[]; // e.g. ["2,400 steps", "120 kcal", "avg 101 bpm"]
  note?: string; // why there are no values
  overlaps: string[]; // e.g. ["Walk 13:28–13:44"]
  canRefresh: boolean;
}

/** What the tracker recorded during a workout, for the card; null for food. */
export function trackerSummary(log: HealthLog): TrackerSummary | null {
  if (log.kind !== 'workout' || !log.measured) return null;
  const reading = log.measured;
  const offset = wall(log.startTime).offset;
  const overlaps = (reading.overlaps ?? []).map((o) => {
    const start = wall(withOffset(new Date(o.startTime), offset)).time;
    const end = wall(withOffset(new Date(o.endTime), offset)).time;
    return `${exerciseName(o.exerciseType)} ${start}–${end}`;
  });
  if (reading.status !== 'measured') {
    const note =
      reading.status === 'no_data'
        ? 'No Fitbit data for this time yet. If you wore it, sync your tracker and refresh.'
        : 'Could not read your Fitbit data for this time.';
    return { values: [], note, overlaps, canRefresh: true };
  }
  const values = [
    reading.steps ? `${reading.steps.toLocaleString('en-US')} steps` : null,
    // The person's own distance is already in the summary line and is the one sent.
    log.distanceKm == null && reading.distanceKm
      ? `${Math.round(reading.distanceKm * 100) / 100} km`
      : null,
    reading.caloriesKcal != null ? `${Math.round(reading.caloriesKcal)} kcal` : null,
    reading.averageHeartRate ? `avg ${reading.averageHeartRate} bpm` : null,
    reading.activeZoneMinutes ? `${reading.activeZoneMinutes} Active Zone Minutes` : null,
    reading.swimLengths ? `${reading.swimLengths} lengths` : null,
  ].filter((value): value is string => value !== null);
  return { values, overlaps, canRefresh: false };
}

/** The edit form's fields: plain text, local date and time, duration as h:mm. */
export type LogForm = Record<string, string>;

export function formFromLog(log: HealthLog): LogForm {
  if (log.kind === 'food') {
    const at = wall(log.consumedAt);
    return {
      foodName: log.foodName,
      mealType: log.mealType,
      date: at.date,
      time: at.time,
      energyKcal: log.energyKcal?.toString() ?? '',
      proteinG: log.proteinG?.toString() ?? '',
      carbohydrateG: log.carbohydrateG?.toString() ?? '',
      fatG: log.fatG?.toString() ?? '',
    };
  }
  const start = wall(log.startTime);
  const minutes = Math.round(log.activeSeconds / 60);
  return {
    exerciseType: log.exerciseType,
    date: start.date,
    time: start.time,
    duration: `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}`,
    distanceKm: log.distanceKm?.toString() ?? '',
  };
}

function amount(text: string, what: string): number | undefined {
  if (!text.trim()) return undefined; // left empty: unknown, never zero
  const value = Number(text.replace(',', '.'));
  if (!Number.isFinite(value) || value < 0) throw new Error(`Enter ${what} as a number.`);
  return value;
}

/** "1:30" (h:mm) or "90" (minutes) to seconds. */
function parseDuration(text: string): number {
  const clock = /^(\d{1,2}):([0-5]\d)$/.exec(text.trim());
  const minutes = clock ? Number(clock[1]) * 60 + Number(clock[2]) : Number(text.trim());
  if (!Number.isFinite(minutes) || minutes <= 0) {
    throw new Error('Enter the duration as h:mm, such as 1:30, or in minutes.');
  }
  return Math.round(minutes * 60);
}

function instant(date: string, time: string, offset: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date.trim())) throw new Error('Enter the date as YYYY-MM-DD.');
  if (!/^\d{1,2}:\d{2}$/.test(time.trim())) throw new Error('Enter the time as HH:MM.');
  const [hours, minutes] = time.trim().split(':');
  const iso = `${date.trim()}T${hours.padStart(2, '0')}:${minutes}:00${offset}`;
  if (!Number.isFinite(Date.parse(iso))) throw new Error('That date or time does not exist.');
  return iso;
}

/** The edited entry, keeping the original's time zone; throws a message to show if invalid. */
export function logFromForm(original: HealthLog, form: LogForm): HealthLog {
  if (original.kind === 'food') {
    const offset = wall(original.consumedAt).offset;
    const log: FoodLog = {
      kind: 'food',
      foodName: (form.foodName ?? '').trim(),
      mealType: form.mealType as FoodLog['mealType'],
      consumedAt: instant(form.date ?? '', form.time ?? '', offset),
      energyKcal: amount(form.energyKcal ?? '', 'calories'),
      proteinG: amount(form.proteinG ?? '', 'protein'),
      carbohydrateG: amount(form.carbohydrateG ?? '', 'carbohydrates'),
      fatG: amount(form.fatG ?? '', 'fat'),
      provenance: 'user_entered',
    };
    for (const key of ['energyKcal', 'proteinG', 'carbohydrateG', 'fatG'] as const) {
      if (log[key] === undefined) delete log[key];
    }
    validateLog(log);
    return log;
  }
  const offset = wall(original.startTime).offset;
  const startTime = instant(form.date ?? '', form.time ?? '', offset);
  const activeSeconds = parseDuration(form.duration ?? '');
  const end = new Date(Date.parse(startTime) + activeSeconds * 1000);
  const log: WorkoutLog = {
    kind: 'workout',
    exerciseType: form.exerciseType ?? original.exerciseType,
    startTime,
    endTime: withOffset(end, offset),
    activeSeconds,
    distanceKm: amount(form.distanceKm ?? '', 'the distance'),
    provenance: 'user_entered',
  };
  if (log.distanceKm === undefined) delete log.distanceKm;
  validateLog(log);
  return log;
}

/** An instant written in a given offset, e.g. 2026-10-24T11:00:00+03:00. */
function withOffset(moment: Date, offset: string): string {
  const sign = offset.startsWith('-') ? -1 : 1;
  const [hours, minutes] = offset.slice(1).split(':').map(Number);
  const local = new Date(moment.getTime() + sign * (hours * 60 + minutes) * 60_000);
  return `${local.toISOString().slice(0, 19)}${offset}`;
}

export function validateLog(log: HealthLog, now: number = Date.now()): void {
  function time(value: string): number {
    if (!/(Z|[+-]\d\d:\d\d)$/.test(value) || !Number.isFinite(Date.parse(value))) {
      throw new Error('Use a date and time with a timezone, such as 2026-10-24T12:00:00+03:00.');
    }
    const at = Date.parse(value);
    if (at > now + FUTURE_GRACE_MS) throw new Error('A log cannot be in the future.');
    return at;
  }
  if (log.kind === 'food') {
    if (!log.foodName.trim() || log.foodName.length > 160) throw new Error('Enter a food name.');
    time(log.consumedAt);
    if (!(log.mealType in MEALS)) throw new Error('Choose a meal.');
    const macros = [log.proteinG, log.carbohydrateG, log.fatG].filter((v) => v != null);
    if (log.energyKcal == null && !macros.length) {
      throw new Error('Enter the calories or at least one macronutrient.');
    }
    if (log.energyKcal != null && log.energyKcal > MAX_KCAL) {
      throw new Error(`One entry can have at most ${MAX_KCAL} kcal.`);
    }
    if (macros.some((grams) => grams > MAX_MACRO_G)) {
      throw new Error(`One entry can have at most ${MAX_MACRO_G} g of each macronutrient.`);
    }
    return;
  }
  // The server checks the type against Google's list.
  if (!/^[A-Z_]{1,64}$/.test(log.exerciseType)) throw new Error('Choose a workout type.');
  const elapsed = (time(log.endTime) - time(log.startTime)) / 1000;
  if (
    !Number.isInteger(log.activeSeconds) ||
    log.activeSeconds <= 0 ||
    log.activeSeconds > elapsed
  ) {
    throw new Error('The active time must fit within the workout.');
  }
  if (elapsed > MAX_WORKOUT_S) throw new Error('One workout can last at most 24 hours.');
  if (log.distanceKm != null) {
    if (!Number.isFinite(log.distanceKm) || log.distanceKm < 0) {
      throw new Error('Enter a valid distance in km.');
    }
    if (log.distanceKm > MAX_DISTANCE_KM) {
      throw new Error(`One workout can cover at most ${MAX_DISTANCE_KM} km.`);
    }
    const limit = maxSpeedKmh(log.exerciseType);
    if (limit && log.distanceKm / (log.activeSeconds / 3600) > limit) {
      throw new Error('That distance is too far for the time.');
    }
  }
}

/** Same explicit entry at the same instant is a duplicate, even with another timezone offset. */
export function logSignature(log: HealthLog): string {
  const source = log as unknown as Record<string, unknown>;
  const keys =
    log.kind === 'food'
      ? ['kind', 'foodName', 'consumedAt']
      : ['kind', 'exerciseType', 'startTime', 'endTime'];
  const canonical = Object.fromEntries(keys.map((key) => [key, source[key]]));
  for (const key of ['consumedAt', 'startTime', 'endTime']) {
    if (typeof canonical[key] === 'string') {
      canonical[key] = new Date(canonical[key] as string).toISOString();
    }
  }
  if (typeof canonical.foodName === 'string') {
    canonical.foodName = canonical.foodName.trim().toLowerCase().replace(/\s+/g, ' ');
  }
  return JSON.stringify(canonical, Object.keys(canonical).sort());
}
