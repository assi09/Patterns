/**
 * When a waiting check-in alert goes out, exactly: "at 12:00 (in 43 min)", in the device's own
 * time, with the day added when it is not today. After the time: "any moment now".
 */
export function goesOut(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  const hh = String(when.getHours()).padStart(2, '0');
  const mm = String(when.getMinutes()).padStart(2, '0');
  const sameDay = when.toDateString() === now.toDateString();
  const day = sameDay
    ? ''
    : ` on ${when.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' })}`;
  const minutes = Math.ceil((when.getTime() - now.getTime()) / 60_000);
  if (minutes <= 0) return `any moment now (it was due at ${hh}:${mm}${day})`;
  return `at ${hh}:${mm}${day} (in ${minutes} min)`;
}
