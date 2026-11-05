import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { useDataStatus, useNoData } from '@/api/hooks';
import type { DataStatus, MetricCoverage } from '@/api/types';
import { GoogleHealthCard } from '@/components/GoogleHealthCard';
import { Row, Section } from '@/components/list';
import { Screen } from '@/components/Screen';
import { SegmentedControl } from '@/components/SegmentedControl';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { shortDate, timeAgo, windowLabel } from '@/lib/format';
import { useSession } from '@/lib/session';
import { radius, spacing, useColors, useMetricColor, useThemePreference } from '@/theme';

const SOURCE_LABELS: Record<DataStatus['source'], string> = {
  takeout: 'Google Takeout export',
  google_health: 'Google Health',
  none: 'No data yet',
};

export default function SettingsScreen() {
  const { account, logOut } = useSession();

  // Google sends the browser back here with ?google=connected (or why it did not connect). Keep
  // the answer to show once, and clear it so a reload does not show it again.
  const { google } = useLocalSearchParams<{ google?: string }>();
  const [returned, setReturned] = useState(google);
  if (google && google !== returned) setReturned(google);
  useEffect(() => {
    if (google) router.setParams({ google: undefined });
  }, [google]);

  return (
    <Screen title="Settings">
      <Section title="Account">
        <Row icon="person-circle-outline" title={account?.email ?? 'Signed in'} />
        {account?.isAdmin ? (
          <Row
            icon="people-outline"
            title="Access requests"
            detail="Approve or decline people who signed up"
            onPress={() => router.push('/approvals')}
          />
        ) : null}
      </Section>

      <Section title="Memory">
        <Row
          icon="bookmark-outline"
          title="What Patterns knows"
          detail="See, change or remove what it keeps in mind"
          onPress={() => router.push('/memory')}
        />
      </Section>

      <Section title="Appearance">
        <View style={styles.control}>
          <AppearanceSwitch />
        </View>
      </Section>

      <Section title="Google Health">
        <GoogleHealthCard returned={returned} />
      </Section>

      <YourData />

      <Section title="Teams">
        <Row
          icon="people-circle-outline"
          title="Your teams"
          detail="Join a team with a code, share or stop sharing, leave"
          onPress={() => router.push('/teams')}
        />
      </Section>

      <Section title="Logging">
        <Row
          icon="list-outline"
          title="Logged food and workouts"
          detail="Drafts, entries sent to Google, and undo"
          onPress={() => router.push('/entries')}
        />
      </Section>

      <Section
        title="About"
        footer="Patterns describes patterns in your own data. It does not give medical advice. Profile and account details from your export are never read."
      >
        <Row icon="log-out-outline" title="Sign out" tone="danger" onPress={logOut} />
      </Section>
    </Screen>
  );
}

/** Where the data comes from, how complete each metric is, and the days left out. */
function YourData() {
  const status = useDataStatus();
  const noData = useNoData();
  if (noData) {
    return (
      <Section title="Your data">
        <Row
          icon="time-outline"
          title="No data yet"
          detail="Connect Google Health above; your history appears here once it is synced"
        />
      </Section>
    );
  }
  if (status.isPending) {
    return (
      <Section title="Your data">
        <View style={styles.loading}>
          <Skeleton height={16} radius={radius.sm} />
          <Skeleton height={16} radius={radius.sm} />
          <Skeleton height={16} radius={radius.sm} />
        </View>
      </Section>
    );
  }
  if (status.error || !status.data) {
    return (
      <Section title="Your data">
        <Row
          icon="alert-circle-outline"
          title="Could not load your data"
          detail="Tap to try again"
          onPress={() => status.refetch()}
        />
      </Section>
    );
  }
  const data = status.data;
  const low = data.lowWearDays;
  return (
    <Section
      title="Your data"
      footer="Share of days with data. Findings only use metrics with enough days."
    >
      <Row
        icon="calendar-outline"
        title={data.range ? windowLabel(data.range) : 'No days yet'}
        detail={`From ${SOURCE_LABELS[data.source]}, ${
          data.lastSync ? `updated ${timeAgo(data.lastSync)}` : 'never updated'
        }`}
      />
      {data.coverage.map((coverage) => (
        <CoverageRow key={coverage.metric} coverage={coverage} />
      ))}
      <Row
        icon="time-outline"
        title={low.length ? `${low.length} low-wear days` : 'No low-wear days'}
        detail={
          low.length
            ? `Under 10 hours of wear, left out of activity trends: ${low.map(shortDate).join(', ')}`
            : 'Your device was worn enough every day.'
        }
      />
    </Section>
  );
}

function CoverageRow({ coverage }: { coverage: MetricCoverage }) {
  const colors = useColors();
  const color = useMetricColor(coverage.metric);
  const percent = Math.round(coverage.fractionPresent * 100);
  return (
    <View
      style={styles.coverage}
      accessible
      accessibilityLabel={`${coverage.label}: ${percent}% of days`}
    >
      <Text style={styles.coverageLabel}>{coverage.label}</Text>
      <View style={[styles.track, { backgroundColor: colors.track }]}>
        <View style={[styles.fill, { width: `${percent}%`, backgroundColor: color }]} />
      </View>
      <Text variant="caption" color="muted" style={styles.percent}>
        {percent}%
      </Text>
    </View>
  );
}

const APPEARANCE = { System: 'system', Light: 'light', Dark: 'dark' } as const;
type AppearanceLabel = keyof typeof APPEARANCE;

function AppearanceSwitch() {
  const { preference, setPreference } = useThemePreference();
  const labels = Object.keys(APPEARANCE) as AppearanceLabel[];
  const current = labels.find((label) => APPEARANCE[label] === preference) ?? 'System';
  return (
    <SegmentedControl
      options={labels}
      value={current}
      onChange={(label) => setPreference(APPEARANCE[label])}
      accessibilityLabel="Appearance"
    />
  );
}

const styles = StyleSheet.create({
  control: { paddingVertical: spacing.md },
  loading: { gap: spacing.md, paddingVertical: spacing.md },
  coverage: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, minHeight: 44 },
  coverageLabel: { width: 140 },
  track: { flex: 1, height: 4, borderRadius: radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: radius.pill },
  percent: { width: 40, textAlign: 'right', fontVariant: ['tabular-nums'] },
});
