// The first-use guide: what Patterns does and the few steps to get going, shown once per account
// on this device after sign-in, and again from Settings. Plain copy, nothing medical.
import type { Ionicons } from '@expo/vector-icons';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export interface TourStep {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  body: string;
  points: string[];
  // A step that needs the person to do something links to where it is done.
  action?: { label: string; href: '/settings' | '/teams' | '/ask' };
}

export const TOUR_STEPS: TourStep[] = [
  {
    icon: 'pulse',
    title: 'Welcome to Patterns',
    body: 'Patterns reads your own Fitbit data and tells you what changed, and why it might have.',
    points: [
      'Every claim comes with the statistic behind it: tap it to see the numbers.',
      'It compares you with your own usual range, never with other people.',
      'It describes patterns in your data. It is not medical advice.',
    ],
  },
  {
    icon: 'link',
    title: 'Connect your Fitbit',
    body: 'Patterns needs your data first. Connect it once; it then stays up to date by itself.',
    points: [
      'Settings → Google Health → Connect, and sign in with the Google account your Fitbit uses.',
      'Allow every permission Google asks for, so sleep, heart and activity all come in.',
      'Your history appears after the first sync; wear the watch at night for sleep data.',
    ],
    action: { label: 'Connect now', href: '/settings' },
  },
  {
    icon: 'today',
    title: 'Today',
    body: 'Your day at a glance: recovery, strain and sleep, your night stage by stage, steps by the hour, and heart and body against your usual range.',
    points: [
      'Tap the insight line or any figure for what is behind it.',
      'Each morning, answer "How do you feel?" in one tap: it helps explain changes.',
      'The arrows at the top go back to earlier days.',
    ],
  },
  {
    icon: 'chatbubble-ellipses',
    title: 'Ask anything about your data',
    body: 'Write as you would to a friend.',
    points: [
      '"How did I sleep this week?", "Why was my recovery low on Tuesday?", "Am I more active on weekends?"',
      'Log a meal or a workout in words ("chicken and rice, 100 g each"): a card shows what will be saved, and nothing is saved until you tap Log it.',
      'Ask for habit ideas too: it suggests options grounded in your own numbers.',
    ],
    action: { label: 'Try a question', href: '/ask' },
  },
  {
    icon: 'notifications',
    title: 'Reminders and alerts',
    body: 'Ask in the chat for a reminder ("remind me to sleep by 11 on weeknights") and it appears under Reminders.',
    points: [
      'Patterns also tells you when something in your data changes clearly.',
      'You can edit or remove any reminder at any time.',
    ],
  },
  {
    icon: 'people',
    title: 'Join your team',
    body: 'If you were given a team code, join from Settings → Teams.',
    points: [
      'Each evening Today asks one question: "How demanding was your day?" One tap.',
      'Your supervisor only ever sees team totals from five or more people, never your own data or answers.',
      'Sharing your own weekly levels is optional, and you can stop at any time.',
    ],
    action: { label: 'Join a team', href: '/teams' },
  },
  {
    icon: 'shield-checkmark',
    title: 'Your data',
    body: 'Your data and questions are stored to answer you, and only used in totals that describe nobody.',
    points: [
      'Thumbs up or down on an answer tells us what to fix.',
      'You can ask for your account and everything in it to be deleted.',
      'That is it. Start with Today, or connect your Fitbit if you have not yet.',
    ],
  },
];

const PREFIX = 'patterns.tour.';

/** The storage key for one account: a plain hash, so the email is not written as a key name. */
export function tourKey(email: string): string {
  let hash = 0;
  for (const char of email.trim().toLowerCase()) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `${PREFIX}${hash.toString(36)}`;
}

/** Whether this account has seen the guide on this device; a storage failure counts as seen. */
export async function tourSeen(email: string): Promise<boolean> {
  try {
    const key = tourKey(email);
    const value =
      Platform.OS === 'web'
        ? (globalThis.localStorage?.getItem(key) ?? null)
        : await SecureStore.getItemAsync(key);
    return value === '1';
  } catch {
    return true; // blocked storage: never show it on every launch
  }
}

export async function markTourSeen(email: string): Promise<void> {
  try {
    const key = tourKey(email);
    if (Platform.OS === 'web') globalThis.localStorage?.setItem(key, '1');
    else await SecureStore.setItemAsync(key, '1');
  } catch {
    // Blocked storage: the guide may show again next launch, which is harmless.
  }
}
