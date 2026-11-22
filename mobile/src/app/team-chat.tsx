import { Redirect } from 'expo-router';

/** Older bookmarks lead to the weekly report. */
export default function FormerTeamChat() {
  return <Redirect href="/team" />;
}
