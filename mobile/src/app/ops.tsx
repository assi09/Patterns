import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { useFeedback, useOpsMetrics } from '@/api/hooks';
import type { OpsMetrics } from '@/api/types';
import { QueryState, Screen } from '@/components/Screen';
import { SegmentedControl } from '@/components/SegmentedControl';
import { Text } from '@/components/Text';
import { Tile } from '@/components/widgets';
import { shortDate } from '@/lib/format';
import {
  capLevel,
  capShare,
  dollars,
  latencyLevel,
  type Level,
  percent,
  rateLevel,
  seconds,
  words,
} from '@/lib/ops';
import { fonts, spacing, useColors } from '@/theme';

const PERIODS = { Today: 1, '7 days': 7, '14 days': 14, '30 days': 30 } as const;
type Period = keyof typeof PERIODS;

/** The operations page: how the agent is used, how well, how fast and at what cost (AgentOps). */
export default function Ops() {
  const [period, setPeriod] = useState<Period>('7 days');
  const metrics = useOpsMetrics(PERIODS[period]);
  return (
    <Screen
      title="Operations"
      subtitle="The pilot, in totals"
      refreshing={metrics.isRefetching}
      onRefresh={metrics.refetch}
      wide
    >
      <SegmentedControl
        options={Object.keys(PERIODS) as Period[]}
        value={period}
        onChange={setPeriod}
        accessibilityLabel="Period"
      />
      <QueryState query={metrics}>{() => <Page m={metrics.data!} />}</QueryState>
      <TesterFeedback />
    </Screen>
  );
}

function Page({ m }: { m: OpsMetrics }) {
  const c = m.chat;
  return (
    <>
      <View style={styles.grid}>
        <Figure
          title="Questions"
          value={String(c.questions)}
          note={`${m.people.askedThisPeriod} of ${m.people.approved} people asked`}
        />
        <Figure
          title="Answered"
          value={percent(c.successRate)}
          note={`of questions it could answer; ${percent(c.refusalRate)} refused by design`}
          level={rateLevel(c.successRate)}
        />
        <Figure
          title="Typical answer time"
          value={seconds(c.latencyS.median)}
          note={`slowest 10% over ${seconds(c.latencyS.p90)}`}
          level={latencyLevel(c.latencyS.median)}
        />
        <Figure
          title="Thumbs up"
          value={percent(c.thumbs.upRate)}
          note={`${c.thumbs.up} up, ${c.thumbs.down} down`}
          level={rateLevel(c.thumbs.upRate, 0.8, 0.6)}
        />
      </View>

      <Section title="Each day">
        <Bars days={m.days} value={(d) => d.answers} label={(v) => String(v)} title="Answers" />
        <Bars days={m.days} value={(d) => d.costUsd} label={dollars} title="Spent" />
      </Section>

      <Section title="Cost and caps">
        <Cap title="Today, everyone" used={m.spend.todayUsd} cap={m.spend.todayCapUsd} />
        <Cap
          title="Today, the heaviest user"
          used={m.spend.highestPersonTodayUsd}
          cap={m.spend.personCapUsd}
          note={
            m.spend.peopleAtTheirCapToday
              ? `${m.spend.peopleAtTheirCapToday} at their daily limit`
              : undefined
          }
        />
        <Cap title="All time" used={m.spend.allTimeUsd} cap={m.spend.allTimeCapUsd} />
        <Row label="Per answer" value={`${dollars(c.costUsd.perAnswer.median)} typical`} />
        <Row label="Per person a day" value={dollars(c.costUsd.perPersonPerDay)} />
      </Section>

      <Section title="Quality">
        <Row
          label="Claims checked against the answer key"
          value={`${percent(m.accuracy.agreement)} agree (${m.accuracy.checked})`}
          level={rateLevel(m.accuracy.agreement)}
        />
        <Row
          label="Changes the key found that answers named"
          value={`${percent(m.recall.recall)} (${m.recall.changesFoundByKey})`}
        />
        <Row label="Claims the verifier stopped" value={String(c.rejectedClaims)} />
        <Row label="Answers with a tool error" value={String(c.withToolErrors)} />
        {Object.entries(c.outcomes).map(([key, count]) => (
          <Row key={key} label={`Outcome: ${words(key)}`} value={String(count)} />
        ))}
      </Section>

      <Section title="Speed">
        <Row label="Answer time, typical" value={seconds(c.latencyS.median)} />
        <Row label="Answer time, slowest 10%" value={seconds(c.latencyS.p90)} />
        <Row label="Answer time, slowest" value={seconds(c.latencyS.max)} />
        <Row label="Of which the model, typical" value={seconds(c.modelS.median)} />
        <Row label="Tool calls an answer, typical" value={String(c.toolCalls.median ?? '–')} />
      </Section>

      <Section title="What people ask">
        {Object.entries(c.questionTypes).map(([key, count]) => (
          <Row key={key} label={words(key)} value={String(count)} />
        ))}
      </Section>

      <Section title="Data and habits">
        <Row
          label="Google syncs that succeeded"
          value={`${percent(m.syncs.successRate)} of ${m.syncs.runs}`}
          level={rateLevel(m.syncs.successRate, 0.95, 0.85)}
        />
        <Row label="Sync time, typical" value={seconds(m.syncs.seconds.median)} />
        <Row label="Connected to Google" value={`${m.syncs.connected} of ${m.people.approved}`} />
        <Row
          label="Need to reconnect"
          value={String(m.syncs.reconnectNeeded)}
          level={m.syncs.reconnectNeeded ? 'watch' : 'good'}
        />
        <Row label="Morning check-ins answered" value={percent(m.engagement.checkInRate)} />
        <Row
          label="Evening team question answered"
          value={`${percent(m.engagement.eveningRate)} of ${m.engagement.teamMembers} members`}
        />
        <Row
          label="Waiting for approval"
          value={String(m.people.waitingForApproval)}
          level={m.people.waitingForApproval ? 'watch' : 'good'}
        />
      </Section>

      <Text variant="caption" color="faint">
        {shortDate(m.period.since)} to {shortDate(m.period.until)}, the pilot&apos;s people only
        (admins left out). Totals and rates; no one is named. Updated every minute.
      </Text>
    </>
  );
}

/** What testers sent from the app, newest first: who, when, and the answer a report is about. */
function TesterFeedback() {
  const colors = useColors();
  const feedback = useFeedback();
  const rows = feedback.data ?? [];
  return (
    <Section title={`Feedback from testers${rows.length ? ` (${rows.length})` : ''}`}>
      {rows.length === 0 ? (
        <Text color="muted">
          Nothing yet. Testers can report an answer (the flag under it) or send feedback on a chat
          (the button at the top of Ask).
        </Text>
      ) : (
        rows.map((row) => (
          <View key={row.id} style={[styles.note, { borderColor: colors.border }]}>
            <Text variant="caption" color="muted">
              {row.kind === 'report' ? 'Report on an answer' : 'Feedback'} · {row.email} ·{' '}
              {new Date(row.createdAt).toLocaleString()}
            </Text>
            <Text>{row.text}</Text>
            {row.quoted ? (
              <Text variant="caption" color="faint" numberOfLines={3}>
                About: {row.quoted}
              </Text>
            ) : null}
          </View>
        ))
      )}
    </Section>
  );
}

function useLevelColor(level?: Level): string | undefined {
  const colors = useColors();
  if (!level) return undefined;
  return level === 'good' ? colors.secondary : level === 'watch' ? colors.warning : colors.danger;
}

function Figure({
  title,
  value,
  note,
  level,
}: {
  title: string;
  value: string;
  note: string;
  level?: Level;
}) {
  const color = useLevelColor(level);
  return (
    <Tile style={styles.figure}>
      <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
        {title}
      </Text>
      <Text style={[styles.big, color ? { color } : null]}>{value}</Text>
      <Text variant="caption" color="muted">
        {note}
      </Text>
    </Tile>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Tile>
      <Text variant="headline">{title}</Text>
      <View style={{ gap: spacing.sm }}>{children}</View>
    </Tile>
  );
}

function Row({ label, value, level }: { label: string; value: string; level?: Level }) {
  const color = useLevelColor(level);
  return (
    <View style={styles.row}>
      <Text style={{ flex: 1 }} color="muted">
        {label}
      </Text>
      <Text style={[{ fontFamily: fonts.semibold }, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

function Cap({
  title,
  used,
  cap,
  note,
}: {
  title: string;
  used: number;
  cap: number;
  note?: string;
}) {
  const colors = useColors();
  const color = useLevelColor(capLevel(used, cap));
  return (
    <View style={{ gap: 4 }}>
      <View style={styles.row}>
        <Text style={{ flex: 1 }} color="muted">
          {title}
        </Text>
        <Text style={{ fontFamily: fonts.semibold }}>
          {dollars(used)} of {dollars(cap)}
        </Text>
      </View>
      <View style={[styles.track, { backgroundColor: colors.track }]}>
        <View
          style={{ width: `${capShare(used, cap) * 100}%`, height: '100%', backgroundColor: color }}
        />
      </View>
      {note ? (
        <Text variant="caption" color="muted">
          {note}
        </Text>
      ) : null}
    </View>
  );
}

function Bars({
  days,
  value,
  label,
  title,
}: {
  days: OpsMetrics['days'];
  value: (day: OpsMetrics['days'][number]) => number;
  label: (v: number) => string;
  title: string;
}) {
  const colors = useColors();
  const values = days.map(value);
  const top = Math.max(...values, 0);
  const total = values.reduce((a, b) => a + b, 0);
  return (
    <View style={{ gap: 6 }}>
      <View style={styles.row}>
        <Text color="muted" style={{ flex: 1 }}>
          {title}
        </Text>
        <Text style={{ fontFamily: fonts.semibold }}>{label(total)} in all</Text>
      </View>
      <View style={styles.bars} accessibilityLabel={`${title} by day`}>
        {days.map((day, i) => (
          <View key={day.day} style={styles.barSlot}>
            <View
              style={{
                height: top ? `${Math.max(4, (values[i] / top) * 100)}%` : 4,
                backgroundColor: values[i] ? colors.accent : colors.track,
                borderRadius: 3,
              }}
            />
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  figure: { flexGrow: 1, flexBasis: 150, gap: 2 },
  big: { fontFamily: fonts.bold, fontSize: 28 },
  row: { flexDirection: 'row', alignItems: 'baseline', gap: spacing.md },
  track: { height: 8, borderRadius: 4, overflow: 'hidden' },
  bars: { flexDirection: 'row', alignItems: 'flex-end', height: 56, gap: 3 },
  barSlot: { flex: 1, height: '100%', justifyContent: 'flex-end' },
  note: { gap: 2, paddingBottom: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth },
});
