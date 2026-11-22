import { Ionicons } from '@expo/vector-icons';
import { type ReactNode, useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import { ApiError } from '@/api/http';
import {
  useDecideTeamAction,
  usePlanTeamChange,
  useTeamActions,
  useTeamAlerts,
  useTeamPlaybook,
  useTeamPulse,
} from '@/api/hooks';
import type { ChangeResult, TeamAction, TeamBriefing, TeamReport } from '@/api/types';
import { stateColor } from '@/components/teamDashboard';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { TILE_RADIUS } from '@/components/widgets';
import { metricLabel } from '@/lib/format';
import { changeRows, latestTeamWeek, shortChange } from '@/lib/team';
import { fonts, radius, spacing, type as typeScale, useColors } from '@/theme';

/** One of the dashboard's numbered parts: "01 This week". */
export function Part({
  number,
  title,
  detail,
  action,
  children,
}: {
  number: string;
  title: string;
  detail?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const colors = useColors();
  return (
    <View style={styles.part}>
      <View style={styles.partHead}>
        <Text variant="label" style={{ color: colors.accent }}>
          {number}
        </Text>
        <Text accessibilityRole="header" style={typeScale.title}>
          {title}
        </Text>
        {detail ? <Text color="muted">{detail}</Text> : null}
        {action ? <View style={styles.partAction}>{action}</View> : null}
      </View>
      {children}
    </View>
  );
}

/** Cards side by side when there is room, one under the other on a phone. */
export function Cards({ children, basis = 320 }: { children: ReactNode; basis?: number }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : [children];
  return (
    <View style={styles.cards}>
      {items.map((child, index) => (
        <View key={index} style={{ flexGrow: 1, flexBasis: basis, minWidth: 0 }}>
          {child}
        </View>
      ))}
    </View>
  );
}

/** A plain surface for the dashboard's cards. */
export function Card({ title, children }: { title?: string; children: ReactNode }) {
  const colors = useColors();
  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      {title ? (
        <Text variant="label" color="muted">
          {title}
        </Text>
      ) : null}
      {children}
    </View>
  );
}

/** The week's leading changes as big numbers, and how demanding the team said its days were. */
export function KeyTiles({ teamId, report }: { teamId: string; report?: TeamReport }) {
  const colors = useColors();
  const pulse = useTeamPulse(teamId);
  const found = (report?.status === 'ready' ? report.priorities : []).slice(0, 3);
  const weeks = pulse.data?.weeks ?? [];
  const last = weeks[weeks.length - 1];
  const before = weeks.slice(0, -1).filter((w) => w.mean !== null);
  const usual = before.length
    ? before.reduce((sum, w) => sum + (w.mean ?? 0), 0) / before.length
    : null;
  if (!found.length && !last) return null;
  let solid = false; // only the first concern gets the solid tile
  return (
    <View style={styles.tiles}>
      {found.map((f) => {
        const week = latestTeamWeek(report?.evidence[f.evidenceId]);
        const lead = f.kind === 'concern' && !solid;
        solid ||= lead;
        const tint = f.kind === 'improvement' ? `${colors.secondary}26` : colors.surface;
        const ink = lead ? colors.onAccent : colors.text;
        const figure = week ? shortChange(f.metric, week.median_change) : '—';
        const moved = week
          ? `${week.median_change < 0 ? week.members_down : week.members_up} of ${week.members} ${
              week.median_change < 0 ? 'lower' : 'higher'
            }`
          : '';
        return (
          <View
            key={f.evidenceId}
            accessible
            accessibilityLabel={f.text}
            style={[
              styles.tile,
              { backgroundColor: lead ? colors.accent : tint, borderColor: colors.border },
            ]}
          >
            <Text variant="caption" style={{ color: ink, fontFamily: fonts.semibold }}>
              {f.label}
            </Text>
            <Text
              style={[typeScale.number, { color: ink }, figure.length > 8 && { fontSize: 22 }]}
              numberOfLines={1}
            >
              {figure}
            </Text>
            <Text variant="caption" style={{ color: lead ? colors.onAccent : colors.muted }}>
              {[moved, f.status === 'lasting' ? 'lasting' : 'new'].filter(Boolean).join(' · ')}
            </Text>
          </View>
        );
      })}
      {last ? (
        <View
          style={[styles.tile, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Text variant="caption" style={{ fontFamily: fonts.semibold }}>
            How demanding
          </Text>
          <Text style={typeScale.number}>
            {last.mean !== null ? last.mean.toFixed(1) : '—'}
            <Text color="muted"> / 5</Text>
          </Text>
          <Text variant="caption" color="muted">
            {last.mean !== null
              ? `${last.respondents} answered${usual !== null ? ` · ${usual.toFixed(1)} before` : ''}`
              : `${last.respondents} of ${pulse.data?.minimum} answers needed`}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const AREA_METRICS: [string, string][] = [
  ['Sleep', 'sleep_minutes'],
  ['Activity', 'steps'],
  ['Recovery', 'recovery_score'],
  ['Load', 'strain'],
  ['Stress signs', 'stress_score'],
];

/** For each area's main metric: how many people were lower and higher than their own usual. */
export function WhoMoved({ report }: { report?: TeamReport }) {
  const colors = useColors();
  if (report?.status !== 'ready') return null;
  const rows = changeRows(report);
  const bars = AREA_METRICS.map(([label, metric]) => ({
    label,
    row: rows.find((r) => r.metric === metric),
  })).filter((b) => b.row && b.row.members > 0);
  if (!bars.length) return null;
  return (
    <Card title="Who moved, by area">
      <Text variant="caption" color="muted">
        People lower or higher than their own usual, out of {bars[0].row!.members}
      </Text>
      <View style={styles.legend}>
        <Legend color={colors.accent} label="Lower" />
        <Legend color={colors.secondary} label="Higher" />
      </View>
      <View style={[styles.bars, { borderColor: colors.border }]}>
        {bars.map(({ label, row }) => {
          const r = row!;
          const faded = r.status !== 'changed';
          return (
            <View
              key={label}
              style={styles.barSlot}
              accessible
              accessibilityLabel={`${label}: ${r.down} lower, ${r.up} higher, of ${r.members}`}
            >
              <View style={[styles.stack, { opacity: faded ? 0.35 : 1 }]}>
                <View
                  style={{
                    height: `${(r.up / r.members) * 100}%`,
                    backgroundColor: colors.secondary,
                  }}
                />
                <View
                  style={{
                    height: `${(r.down / r.members) * 100}%`,
                    backgroundColor: colors.accent,
                  }}
                />
              </View>
              <Text variant="caption" color="muted" numberOfLines={1}>
                {label}
              </Text>
            </View>
          );
        })}
      </View>
      <Text variant="caption" color="muted">
        Faded: not broad enough to count as a team change.
      </Text>
    </Card>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text variant="caption" color="muted">
        {label}
      </Text>
    </View>
  );
}

const VERDICT: Record<ChangeResult['verdict'], string> = {
  better: 'Better during it',
  worse: 'Worse during it',
  changed: 'Changed during it',
  no_change: 'No clear change',
  unclear: 'Too few to tell',
};

function day(iso: string | null): string {
  if (!iso) return '';
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

function today(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** Alerts, decisions, coming events and changes, as five lanes (docs/teams.md). */
export function TeamBoard({
  teamId,
  briefing,
  planning,
}: {
  teamId: string;
  briefing?: TeamBriefing | null;
  planning: boolean;
}) {
  const colors = useColors();
  const alerts = useTeamAlerts(teamId);
  const actions = useTeamActions(teamId);
  const decide = useDecideTeamAction(teamId);
  const [told, setTold] = useState<string | null>(null);
  const now = today();
  const all = actions.data ?? [];
  const open = (alerts.data ?? []).filter((a) => !a.resolvedAt);
  const waiting = all.filter((a) => a.status === 'proposed');
  const coming = (briefing?.items ?? []).filter((i) => i.kind === 'ahead');
  const trying = all.filter(
    (a) => a.status === 'approved' && a.kind === 'challenge' && (a.endsOn ?? '') >= now,
  );
  const ended = all.filter((a) => a.status === 'approved' && a.result).slice(0, 3);
  const closed = (alerts.data ?? []).filter((a) => a.resolvedAt).slice(0, 2);
  return (
    <View style={styles.part}>
      {planning ? <PlanChange teamId={teamId} /> : null}
      <View style={styles.lanes}>
        <Lane
          icon="alert-circle-outline"
          tint={colors.accent}
          title="Open alerts"
          count={open.length}
        >
          {open.map((alert) => (
            <Item key={alert.id} title={alert.label} detail={alert.text} />
          ))}
        </Lane>
        <Lane icon="time-outline" tint={colors.text} title="Waiting for you" count={waiting.length}>
          {waiting.map((action) => (
            <Item
              key={action.id}
              kicker={`Suggested by your team agent · ${day(action.startsOn)} to ${day(action.endsOn)}`}
              title={action.title}
              detail={`${action.body} Measured on ${metricLabel(action.metric ?? '').toLowerCase()}.`}
            >
              <View style={styles.buttons}>
                <Button
                  label="Approve"
                  disabled={decide.isPending}
                  onPress={() =>
                    decide.mutate(
                      { actionId: action.id, approve: true },
                      { onSuccess: (r) => setTold(`Sent to ${r.membersTold} people.`) },
                    )
                  }
                />
                <Button
                  label="Decline"
                  variant="secondary"
                  disabled={decide.isPending}
                  onPress={() => decide.mutate({ actionId: action.id, approve: false })}
                />
              </View>
            </Item>
          ))}
          {told ? (
            <Text variant="caption" color="muted">
              {told}
            </Text>
          ) : null}
          {decide.error ? <ErrorLine error={decide.error} /> : null}
        </Lane>
        <Lane icon="calendar-outline" tint={colors.warning} title="Coming up" count={coming.length}>
          {coming.map((item) => (
            <Item key={item.text} title={item.text} plain />
          ))}
        </Lane>
        <Lane icon="arrow-forward" tint={colors.secondary} title="Trying" count={trying.length}>
          {trying.map((action) => (
            <Running key={action.id} action={action} today={now} />
          ))}
        </Lane>
        <Lane
          icon="checkmark-circle-outline"
          tint={stateColor('improvement', colors)}
          title="How it went"
          count={ended.length + closed.length}
        >
          {ended.map((action) => (
            <Item
              key={action.id}
              title={action.title}
              detail={action.result!.text}
              badge={VERDICT[action.result!.verdict]}
            />
          ))}
          {closed.map((alert) => (
            <Item
              key={alert.id}
              title={`${alert.label} alert closed`}
              detail={alert.text}
              badge={alert.kind === 'concern' ? 'Back to usual' : 'Ended'}
            />
          ))}
        </Lane>
      </View>
    </View>
  );
}

function Running({ action, today: now }: { action: TeamAction; today: string }) {
  const colors = useColors();
  const start = Date.parse(`${action.startsOn}T00:00:00Z`);
  const end = Date.parse(`${action.endsOn}T00:00:00Z`);
  const total = Math.round((end - start) / 86_400_000) + 1;
  const done = Math.round((Date.parse(`${now}T00:00:00Z`) - start) / 86_400_000) + 1;
  const started = done >= 1;
  return (
    <Item
      title={action.title}
      detail={`${action.source === 'agent' ? 'Suggested and approved' : 'Started by you'} · measured on ${metricLabel(action.metric ?? '').toLowerCase()}.`}
    >
      <View style={[styles.progress, { backgroundColor: colors.track }]}>
        <View
          style={{
            width: `${started ? Math.min(100, (done / total) * 100) : 0}%`,
            height: '100%',
            backgroundColor: colors.secondary,
          }}
        />
      </View>
      <Text variant="caption" color="muted">
        {started ? `Day ${Math.min(done, total)} of ${total}` : `Starts ${day(action.startsOn)}`}
      </Text>
    </Item>
  );
}

function Lane({
  icon,
  tint,
  title,
  count,
  children,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  tint: string;
  title: string;
  count: number;
  children: ReactNode;
}) {
  const colors = useColors();
  return (
    <View style={[styles.lane, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <View style={styles.laneHead}>
        <View style={[styles.laneIcon, { backgroundColor: `${tint}22` }]}>
          <Ionicons name={icon} size={15} color={tint} />
        </View>
        <Text variant="bodyStrong" style={{ flex: 1 }}>
          {title}
        </Text>
        <Text variant="caption" color="muted">
          {count}
        </Text>
      </View>
      {count === 0 ? (
        <Text variant="caption" color="muted" style={{ paddingHorizontal: 4 }}>
          Nothing here.
        </Text>
      ) : null}
      {children}
    </View>
  );
}

function Item({
  kicker,
  title,
  detail,
  badge,
  plain = false,
  children,
}: {
  kicker?: string;
  title: string;
  detail?: string;
  badge?: string;
  plain?: boolean; // a whole sentence rather than a name
  children?: ReactNode;
}) {
  const colors = useColors();
  return (
    <View style={[styles.item, { backgroundColor: colors.background, borderColor: colors.border }]}>
      {kicker ? (
        <Text variant="caption" color="muted">
          {kicker}
        </Text>
      ) : null}
      <Text variant={plain ? 'body' : 'bodyStrong'}>{title}</Text>
      {detail ? (
        <Text variant="caption" color="muted">
          {detail}
        </Text>
      ) : null}
      {badge ? (
        <View style={[styles.badge, { backgroundColor: colors.track }]}>
          <Text variant="caption" style={{ fontFamily: fonts.semibold }}>
            {badge}
          </Text>
        </View>
      ) : null}
      {children}
    </View>
  );
}

const ALL_METRICS = [
  'sleep_minutes',
  'bedtime_hour',
  'steps',
  'active_zone_minutes',
  'resting_hr',
  'hrv_ms',
  'recovery_score',
  'strain',
  'stress_score',
];

/** Start a change for the whole team: one from the playbook, or the supervisor's own. */
export function PlanChange({ teamId }: { teamId: string }) {
  const colors = useColors();
  const plays = useTeamPlaybook(teamId);
  const plan = usePlanTeamChange(teamId);
  const [chosen, setChosen] = useState<string | null>(null);
  const [metric, setMetric] = useState<string | null>(null);
  const [starts, setStarts] = useState('');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [told, setTold] = useState<string | null>(null);
  const play = plays.data?.find((p) => p.id === chosen);
  const own = chosen === 'custom';
  const metrics = own ? ALL_METRICS : (play?.metrics ?? []);
  const measured = metric && metrics.includes(metric) ? metric : (metrics[0] ?? null);
  const parsed = new Date(`${starts}T00:00:00Z`);
  const validDate =
    !starts || (!Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === starts);
  const ready = Boolean(chosen) && validDate && (!own || (title.trim() && body.trim() && measured));
  const input = [
    styles.input,
    { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
  ];
  const pick = (id: string) => {
    setChosen(id);
    setMetric(null);
    setTold(null);
  };
  const submit = () => {
    if (!ready || !chosen || plan.isPending) return;
    plan.mutate(
      {
        play: chosen,
        metric: measured ?? undefined,
        startsOn: starts || undefined,
        ...(own && { title: title.trim(), body: body.trim() }),
      },
      {
        onSuccess: (r) => {
          setTold(
            `${r.action.title} starts ${day(r.action.startsOn)}. Sent to ${r.membersTold} people.`,
          );
          setChosen(null);
          setStarts('');
          setTitle('');
          setBody('');
        },
      },
    );
  };
  return (
    <Card title="Plan a change for the whole team">
      <Text color="muted">
        It starts as you set it, and every member is told. Once it ends you see how the team went
        during it.
      </Text>
      <View style={styles.choices}>
        {[
          ...(plays.data ?? []).map((p) => ({ id: p.id, title: p.title })),
          { id: 'custom', title: 'Your own' },
        ].map((p) => (
          <Chip key={p.id} label={p.title} on={chosen === p.id} onPress={() => pick(p.id)} />
        ))}
      </View>
      {play ? <Text>{play.body}</Text> : null}
      {own ? (
        <>
          <TextInput
            value={title}
            onChangeText={setTitle}
            maxLength={80}
            placeholder="Name, e.g. Fridays end at 4"
            placeholderTextColor={colors.faint}
            accessibilityLabel="Name of the change"
            style={input}
          />
          <TextInput
            value={body}
            onChangeText={setBody}
            maxLength={400}
            placeholder="What it is, for the whole team"
            placeholderTextColor={colors.faint}
            accessibilityLabel="What the change is"
            style={input}
          />
        </>
      ) : null}
      {chosen ? (
        <>
          <Text variant="caption" color="muted">
            Measured on
          </Text>
          <View style={styles.choices}>
            {metrics.map((m) => (
              <Chip
                key={m}
                label={metricLabel(m)}
                on={measured === m}
                onPress={() => setMetric(m)}
              />
            ))}
          </View>
          <View style={styles.row}>
            <TextInput
              value={starts}
              onChangeText={setStarts}
              maxLength={10}
              placeholder="Starts · YYYY-MM-DD (tomorrow if empty)"
              placeholderTextColor={colors.faint}
              accessibilityLabel="Start date, YYYY-MM-DD"
              style={[input, { flex: 1 }]}
            />
            <Button
              label="Start for the team"
              disabled={!ready || plan.isPending}
              onPress={submit}
            />
          </View>
          {!validDate ? <Text color="danger">Enter a valid date as YYYY-MM-DD.</Text> : null}
        </>
      ) : null}
      {told ? <Text color="muted">{told}</Text> : null}
      {plan.error ? <ErrorLine error={plan.error} /> : null}
    </Card>
  );
}

function Chip({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: on }}
      onPress={onPress}
      style={[
        styles.chip,
        on
          ? { backgroundColor: colors.text, borderColor: colors.text }
          : { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      <Text
        variant="caption"
        style={{ color: on ? colors.background : colors.text, fontFamily: fonts.semibold }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

function ErrorLine({ error }: { error: Error }) {
  const message = error instanceof ApiError ? error.message : 'Something went wrong. Try again.';
  return (
    <Text variant="caption" color="danger">
      {message}
    </Text>
  );
}

const styles = StyleSheet.create({
  part: { gap: spacing.md },
  partHead: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', gap: spacing.md },
  partAction: { marginLeft: 'auto' },
  cards: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  card: { borderRadius: TILE_RADIUS, borderWidth: 1, padding: spacing.lg, gap: spacing.md },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tile: {
    flexGrow: 1,
    flexBasis: 140,
    minHeight: 120,
    borderRadius: 18,
    borderWidth: 1,
    padding: spacing.md,
    justifyContent: 'space-between',
    gap: spacing.xs,
  },
  legend: { flexDirection: 'row', gap: spacing.md },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  bars: {
    flexDirection: 'row',
    gap: spacing.xs,
    height: 170,
    alignItems: 'flex-end',
    borderBottomWidth: 1,
    paddingBottom: 2,
  },
  barSlot: { flex: 1, height: '100%', alignItems: 'center', justifyContent: 'flex-end', gap: 6 },
  stack: {
    width: 32,
    height: '82%',
    borderRadius: 7,
    overflow: 'hidden',
    justifyContent: 'flex-end',
  },
  lanes: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  lane: {
    flexGrow: 1,
    flexBasis: 210,
    minWidth: 0,
    borderRadius: 18,
    borderWidth: 1,
    padding: spacing.sm,
    gap: spacing.sm,
  },
  laneHead: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: 4 },
  laneIcon: {
    width: 26,
    height: 26,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  item: { borderRadius: 14, borderWidth: 1, padding: spacing.md, gap: 6 },
  badge: {
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  buttons: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  progress: { height: 5, borderRadius: 3, overflow: 'hidden' },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    minHeight: 40,
    justifyContent: 'center',
    borderRadius: 999,
    borderWidth: 1,
    paddingHorizontal: 14,
  },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm },
  input: {
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 11,
    fontFamily: fonts.regular,
    fontSize: 15,
    minWidth: 200,
  },
});
