import { useLocalSearchParams } from 'expo-router';

import { useTeamMetric } from '@/api/hooks';
import { QueryState, Screen } from '@/components/Screen';
import { TeamMetricView } from '@/components/teamMetrics';

/** One team metric's evidence for one week; the same record and id MCP's team_metric gives. */
export default function TeamMetricScreen() {
  const { team, week, metric } = useLocalSearchParams<{
    team: string;
    week: string;
    metric: string;
  }>();
  const record = useTeamMetric(team, week, metric);
  return (
    <Screen>
      <QueryState query={record}>{() => <TeamMetricView record={record.data!} />}</QueryState>
    </Screen>
  );
}
