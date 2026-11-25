import { useSession } from '@/lib/session';

/**
 * Whether the individual side (Ask, findings, reminders, smart alarms, memory, logging) is on.
 * The server decides (FA_PERSONAL_FEATURES, docs/pivot.md) and says so on the account; since the
 * move to teams on 2026-11-25 it is off, and its screens stay in the code.
 */
export function usePersonal(): boolean {
  return useSession().account?.personalFeatures ?? false;
}
