import { useLocalSearchParams } from 'expo-router';

import { useTeamEvidence } from '@/api/hooks';
import { QueryState, Screen } from '@/components/Screen';
import { TeamEvidenceView } from '@/components/teamEvidence';

/** The record behind one finding of one team report, opened through that report only. */
export default function TeamEvidenceScreen() {
  const { team, week, id } = useLocalSearchParams<{ team: string; week: string; id: string }>();
  const record = useTeamEvidence(team, week, id);
  return (
    <Screen>
      <QueryState query={record}>{() => <TeamEvidenceView record={record.data!} />}</QueryState>
    </Screen>
  );
}
