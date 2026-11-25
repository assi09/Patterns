import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Platform, Pressable, StyleSheet, View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import { runOnJS } from 'react-native-reanimated';

import {
  useDay,
  useHourlySteps,
  useNoData,
  useReport,
  useSleepStages,
  useWorkouts,
} from '@/api/hooks';
import type { DaySummary, Finding, ISODate } from '@/api/types';
import { CheckInSection } from '@/components/checkin';
import { DayHeader } from '@/components/day';
import { QuestionCard } from '@/components/insights';
import { Section } from '@/components/list';
import { PulseCard } from '@/components/pulse';
import {
  ChangeChips,
  InsightBar,
  NumberTile,
  ProgressBar,
  RangesTile,
  ScoreRings,
  SleepTile,
  StepsTile,
  StressTile,
  TILE_RADIUS,
  WorkoutTile,
} from '@/components/widgets';
import { NoData } from '@/components/NoData';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { SyncLine } from '@/components/SyncLine';
import { Text } from '@/components/Text';
import { metricOf, shiftDate } from '@/lib/day';
import { usePersonal } from '@/lib/features';
import { useWide } from '@/lib/layout';
import { radius, spacing, useColors } from '@/theme';

const HEART = ['resting_hr', 'hrv_ms', 'respiratory_rate', 'skin_temp_variation_c'];

export default function TodayScreen() {
  const [date, setDate] = useState<ISODate | 'latest'>('latest');
  const day = useDay(date);
  const report = useReport(usePersonal()); // findings belong to the individual side
  const noData = useNoData();
  const wide = useWide();
  const data = day.data;

  function change(to: ISODate | 'latest', step = 0) {
    if (to === 'latest' || !data) return setDate('latest');
    const next = shiftDate(to, step);
    if (next < data.first) return;
    setDate(next >= data.last ? 'latest' : next);
  }

  // On the web, the arrow keys move between days.
  useEffect(() => {
    if (Platform.OS !== 'web' || !data) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;
      if (event.key === 'ArrowLeft') change(data.date, -1);
      if (event.key === 'ArrowRight') change(data.date, 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  // On phones a sideways swipe moves between days; vertical scrolling is left alone.
  const swipe = Gesture.Pan()
    .enabled(Platform.OS !== 'web' && !!data)
    .activeOffsetX([-30, 30])
    .failOffsetY([-12, 12])
    .onEnd((event) => {
      if (Math.abs(event.translationX) > 60 && data) {
        runOnJS(change)(data.date, event.translationX < 0 ? 1 : -1);
      }
    });

  const open = (metric: string) =>
    router.push({ pathname: '/metric/[metric]', params: { metric, date: data?.date ?? '' } });

  if (noData && !data) {
    return (
      <Screen title="Today" wide>
        <NoData shows="Today shows your sleep, recovery, strain and stress" />
      </Screen>
    );
  }

  return (
    <GestureDetector gesture={swipe}>
      <View style={{ flex: 1 }}>
        <Screen
          wide
          refreshing={day.isRefetching && !day.isPlaceholderData}
          onRefresh={() => {
            day.refetch();
            report.refetch();
          }}
          header={
            data ? (
              <DayHeader
                date={data.date}
                today={data.last}
                first={data.first}
                last={data.last}
                partial={data.partial}
                onChange={change}
              />
            ) : (
              <View style={styles.headerSkeleton}>
                <Skeleton height={14} width={160} radius={radius.sm} />
                <Skeleton height={36} width={140} radius={radius.sm} />
              </View>
            )
          }
        >
          {day.error && !data ? (
            <Section>
              <Pressable onPress={() => day.refetch()} style={styles.error}>
                <Text>Could not load this day.</Text>
                <Text variant="caption" color="muted">
                  {day.error.message} Tap to try again.
                </Text>
              </Pressable>
            </Section>
          ) : !data ? (
            <DaySkeleton wide={wide} />
          ) : (
            <View style={{ opacity: day.isPlaceholderData ? 0.5 : 1, gap: spacing.md }}>
              <SyncLine />
              <DayBody
                day={data}
                wide={wide}
                open={open}
                findings={report.data?.findings ?? []}
                questions={report.data?.questions}
              />
              <Text variant="caption" color="faint" style={styles.footer}>
                Your own Fitbit data compared with your own usual range, the middle half of the four
                weeks before. Patterns, not medical advice.
              </Text>
            </View>
          )}
        </Screen>
      </View>
    </GestureDetector>
  );
}

function DayBody({
  day,
  wide,
  open,
  findings,
  questions,
}: {
  day: DaySummary;
  wide: boolean;
  open: (metric: string) => void;
  findings: Finding[];
  questions?: Parameters<typeof QuestionCard>[0]['question'][];
}) {
  const colors = useColors();
  const workouts = useWorkouts(day.date);
  const hourly = useHourlySteps(day.date);
  const night = useSleepStages(day.date);

  const rings = <ScoreRings day={day} wide={wide} open={open} />;
  const insight = findings[0] ? <InsightBar finding={findings[0]} /> : null;
  const steps = <StepsTile day={day} hourly={hourly.data?.steps} open={open} />;
  const sleep = <SleepTile day={day} night={night.data} open={open} />;
  const heart = <RangesTile title="Heart and body" day={day} metrics={HEART} open={open} />;
  const tiles = (
    <>
      <View style={styles.pair}>
        <StressTile day={day} open={open} />
        <NumberTile
          day={day}
          metric="active_zone_minutes"
          open={open}
          extra={<ProgressBar metric={metricOf(day, 'active_zone_minutes')} />}
        />
      </View>
      <View style={styles.pair}>
        <NumberTile day={day} metric="distance_km" open={open} />
        <NumberTile day={day} metric="calories" open={open} />
      </View>
      {day.lowWear ? (
        <Text variant="caption" color="faint">
          Your tracker was worn under 10 hours this day, so these totals are low and left out of
          your usual range.
        </Text>
      ) : null}
    </>
  );
  // Without a Google Health connection there is nothing to read workouts from: say nothing.
  const sessions = workouts.data?.available
    ? workouts.data.workouts.map((workout) => (
        <WorkoutTile
          key={workout.id}
          workout={workout}
          onPress={() =>
            router.push({ pathname: '/workout/[id]', params: { id: workout.id, date: day.date } })
          }
        />
      ))
    : null;
  const pulse = <PulseCard today={day.partial} />;
  const checkIn = (
    <CheckInSection
      day={day.date}
      today={day.partial}
      style={[styles.checkIn, { backgroundColor: colors.surface }]}
    />
  );
  const changes = (
    <View style={{ gap: spacing.md }}>
      {(questions ?? [])
        .filter((q) => !q.answer)
        .map((question) => (
          <QuestionCard key={question.id} question={question} />
        ))}
      <Text variant="label" color="muted" accessibilityRole="header">
        What changed lately
      </Text>
      {findings.length ? (
        <ChangeChips findings={findings} />
      ) : (
        <Text color="muted">
          Nothing differed clearly from the weeks before. Ask about any metric in the Ask tab.
        </Text>
      )}
    </View>
  );

  if (!wide) {
    return (
      <>
        {rings}
        {insight}
        {pulse}
        {steps}
        {sleep}
        {heart}
        {tiles}
        {sessions}
        {checkIn}
        {changes}
      </>
    );
  }
  return (
    <>
      {rings}
      {insight}
      <View style={styles.columns}>
        <View style={styles.column}>
          {pulse}
          {sleep}
          {heart}
          {checkIn}
        </View>
        <View style={styles.column}>
          {steps}
          {tiles}
          {sessions}
          {changes}
        </View>
      </View>
    </>
  );
}

function DaySkeleton({ wide }: { wide: boolean }) {
  return (
    <View style={{ gap: spacing.lg }}>
      {(wide ? [4] : [2, 2]).map((count, row) => (
        <View key={row} style={styles.keysSkeleton}>
          {Array.from({ length: count }, (_, i) => (
            <View key={i} style={{ flex: 1, gap: spacing.sm }}>
              <Skeleton height={12} width={70} radius={radius.sm} />
              <Skeleton height={wide ? 44 : 30} radius={radius.sm} />
              <Skeleton height={12} width={90} radius={radius.sm} />
            </View>
          ))}
        </View>
      ))}
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} height={18} radius={radius.sm} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  headerSkeleton: { gap: spacing.sm, marginBottom: spacing.md },
  keys: {
    gap: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  keyRow: { flexDirection: 'row', gap: spacing.lg },
  keysSkeleton: { flexDirection: 'row', gap: spacing.lg },
  columns: { flexDirection: 'row', gap: spacing.lg, alignItems: 'flex-start' },
  column: { flex: 1, minWidth: 0, gap: spacing.md },
  pair: { flexDirection: 'row', gap: spacing.md },
  checkIn: { borderRadius: TILE_RADIUS, padding: spacing.lg },
  none: { paddingVertical: spacing.md },
  finding: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    marginHorizontal: -spacing.sm,
    borderRadius: radius.sm,
  },
  findingDot: { width: 8, height: 8, borderRadius: 4 },
  error: { paddingVertical: spacing.md, gap: 2 },
  footer: { textAlign: 'center', marginTop: spacing.lg },
});
