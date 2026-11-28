import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { useTeamMetrics } from '@/api/hooks';
import { QueryState, Screen } from '@/components/Screen';
import { TeamMetricsView } from '@/components/teamMetrics';

/** Every team metric of one finished week, beyond the briefing's few (app.teams.explorer). */
export default function TeamMetricsScreen() {
  const { team, week } = useLocalSearchParams<{ team: string; week?: string }>();
  const [category, setCategory] = useState<string | undefined>();
  const metrics = useTeamMetrics(team, week || undefined);
  return (
    <Screen refreshing={metrics.isRefetching} onRefresh={metrics.refetch}>
      <QueryState query={metrics}>
        {() => (
          <TeamMetricsView
            data={metrics.data!}
            category={category}
            onCategory={setCategory}
            onWeek={(start) => router.setParams({ week: start })}
          />
        )}
      </QueryState>
    </Screen>
  );
}
