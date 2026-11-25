import { Ionicons } from '@expo/vector-icons';
import * as Clipboard from 'expo-clipboard';
import { type ReactNode, useState } from 'react';
import {
  Pressable,
  ScrollView,
  type StyleProp,
  StyleSheet,
  TextInput,
  View,
  type ViewStyle,
} from 'react-native';

import { ApiError } from '@/api/http';
import {
  useCreateTeam,
  useMakeTeamReport,
  useRotateTeamCode,
  useSetTeamHr,
  useTeamAlerts,
  useTeamObserved,
  useTeamPulse,
  useTeamReport,
  useTeamReports,
  useTeams,
} from '@/api/hooks';
import type {
  ISODate,
  SharedLevels,
  SupervisedTeam,
  TeamReport,
  TeamReportSummary,
} from '@/api/types';
import { Row, Section } from '@/components/list';
import { NotesSection } from '@/components/teamAgent';
import { Cards, KeyTiles, Part, TeamBoard, WhoMoved } from '@/components/teamBoard';
import { TeamPulseTile } from '@/components/pulse';
import { AreaChips, BriefingCard } from '@/components/teamBrief';
import { TILE_RADIUS } from '@/components/widgets';
import { ChangeChart, KeyFigures, LevelsTable, WeekdayChart } from '@/components/teamReport';
import { QueryState, Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { windowLabel } from '@/lib/format';
import { areaReadings, briefingItems, changeRows, teamStatus } from '@/lib/team';
import { fonts, radius, spacing, useColors, useMetricColor } from '@/theme';

// The team last looked at, for this session: switching tabs and back keeps it.
let lastTeam: string | undefined;

/** A supervisor's teams (a department and its squads, say): one dashboard each (docs/teams.md). */
export default function TeamScreen() {
  const teams = useTeams();
  const [chosen, setChosen] = useState<string | undefined>(lastTeam);
  const [adding, setAdding] = useState(false);
  const all = teams.data ?? [];
  const team = all.find((t) => t.id === chosen) ?? all[0];
  const choose = (id: string) => {
    lastTeam = id;
    setChosen(id);
    setAdding(false);
  };
  return (
    <Screen
      title={adding ? 'New team' : (team?.name ?? 'Team')}
      wide
      refreshing={teams.isRefetching}
      onRefresh={teams.refetch}
    >
      <QueryState query={teams}>
        {() => (
          <>
            {all.length > 0 ? (
              <TeamSwitcher
                teams={all}
                current={adding ? undefined : team?.id}
                onChoose={choose}
                onAdd={() => setAdding(true)}
              />
            ) : null}
            {team && !adding ? (
              <TeamView key={team.id} team={team} />
            ) : (
              <CreateTeam
                first={all.length === 0}
                onCreated={choose}
                onCancel={all.length ? () => setAdding(false) : undefined}
              />
            )}
          </>
        )}
      </QueryState>
    </Screen>
  );
}

/** The supervisor's teams as a row of names, the open one underlined; text, not boxes. */
function TeamSwitcher({
  teams,
  current,
  onChoose,
  onAdd,
}: {
  teams: SupervisedTeam[];
  current?: string;
  onChoose: (id: string) => void;
  onAdd: () => void;
}) {
  const colors = useColors();
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.switcher}
      accessibilityRole="tablist"
    >
      {teams.map((t) => {
        const open = t.id === current;
        return (
          <Pressable
            key={t.id}
            accessibilityRole="tab"
            accessibilityState={{ selected: open }}
            aria-selected={open}
            onPress={() => onChoose(t.id)}
            style={[styles.switch, open && { borderBottomColor: colors.text }]}
          >
            <Text color={open ? 'text' : 'muted'} style={open ? styles.switchOpen : undefined}>
              {t.name}
            </Text>
            {t.paused ? (
              <Ionicons name="pause-circle-outline" size={14} color={colors.warning} />
            ) : null}
          </Pressable>
        );
      })}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="New team"
        onPress={onAdd}
        style={[styles.switch, current === undefined && { borderBottomColor: colors.text }]}
      >
        <Ionicons name="add" size={16} color={colors.muted} />
        <Text color="muted">New team</Text>
      </Pressable>
    </ScrollView>
  );
}

function CreateTeam({
  first,
  onCreated,
  onCancel,
}: {
  first: boolean;
  onCreated: (id: string) => void;
  onCancel?: () => void;
}) {
  const colors = useColors();
  const create = useCreateTeam();
  const [name, setName] = useState('');
  const submit = () => name.trim() && create.mutate(name, { onSuccess: (t) => onCreated(t.id) });
  return (
    <Section
      title={first ? 'Create your team' : 'Another team'}
      footer="You get a code to share. People join with it in their Settings after reading what you will see: weekly team figures from at least 5 people, and named levels only from those who choose to share them."
    >
      <View style={styles.field}>
        <TextInput
          value={name}
          onChangeText={setName}
          placeholder="Team name, e.g. Design"
          placeholderTextColor={colors.faint}
          maxLength={80}
          onSubmitEditing={submit}
          accessibilityLabel="Team name"
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
        <Button label="Create" disabled={!name.trim() || create.isPending} onPress={submit} />
      </View>
      {onCancel ? <Button label="Cancel" variant="secondary" onPress={onCancel} /> : null}
      {!first ? (
        <Text variant="caption" color="muted">
          Teams that share people must differ by at least 5 people, or not at all, or their figures
          pause: comparing two nearly identical teams could single someone out.
        </Text>
      ) : null}
      {create.error ? <ErrorLine error={create.error} /> : null}
    </Section>
  );
}

function TeamView({ team }: { team: SupervisedTeam }) {
  const colors = useColors();
  const card = [styles.card, { backgroundColor: colors.surface, borderColor: colors.border }];
  const reports = useTeamReports(team.id);
  const [chosen, setChosen] = useState<ISODate | undefined>();
  const [planning, setPlanning] = useState(false);
  const week = chosen ?? reports.data?.[0]?.week.start;
  const report = useTeamReport(team.id, week);
  // Where the team stands now: the latest report and the open alerts, whatever week is shown.
  const latest = useTeamReport(team.id, reports.data?.[0]?.week.start);
  const alerts = useTeamAlerts(team.id);
  const pulse = useTeamPulse(team.id);
  const observed = useTeamObserved(team.id);

  const status = teamStatus(alerts.data, latest.data);
  const ready = latest.data?.status === 'ready';
  const kicker = [
    `${team.members} ${team.members === 1 ? 'person' : 'people'}`,
    latest.data ? `week of ${windowLabel(latest.data.week)}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <View style={styles.page}>
      <View style={styles.stack}>
        <Text variant="label" color="muted">
          {kicker}
        </Text>
        {/* Five "Steady"s would claim a reading the team does not have yet. */}
        {team.paused || status.level === 'unknown' ? null : (
          <AreaChips readings={areaReadings(alerts.data, latest.data)} />
        )}
      </View>
      {team.paused ? (
        <Section title="Figures paused" style={card}>
          <Text color="muted">{team.paused}</Text>
        </Section>
      ) : (
        <>
          <Part number="01" title="This week">
            <Cards>
              <BriefingCard
                status={status}
                items={briefingItems(alerts.data, latest.data)}
                briefing={latest.data?.briefing}
                observed={observed.data?.figures.map((f) => f.text)}
              />
              {ready || pulse.data?.weeks.length ? (
                <KeyTiles teamId={team.id} report={latest.data} />
              ) : null}
              {ready ? <WhoMoved report={latest.data} /> : null}
            </Cards>
          </Part>
          <Part
            number="02"
            title="Team board"
            detail="Alerts, decisions, coming events and changes you are trying"
            action={
              <Button
                label={planning ? 'Close' : 'Plan a change'}
                icon={planning ? 'close' : 'add'}
                variant={planning ? 'secondary' : 'primary'}
                onPress={() => setPlanning(!planning)}
              />
            }
          >
            <TeamBoard teamId={team.id} briefing={latest.data?.briefing} planning={planning} />
          </Part>
          <Part
            number="03"
            title="Weekly report"
            detail={report.data ? `Week of ${windowLabel(report.data.week)}` : undefined}
          >
            <ReportSection team={team} reports={reports.data} report={report.data} card={card} />
            <Cards>
              {report.data ? <LevelsSection levels={report.data.levels} card={card} /> : null}
              {pulse.data?.weeks.length ? <TeamPulseTile teamId={team.id} style={card} /> : null}
              {(reports.data?.length ?? 0) > 1 ? (
                <PastWeeks
                  reports={reports.data ?? []}
                  selected={week}
                  onSelect={(start) => setChosen(start)}
                  card={card}
                />
              ) : null}
            </Cards>
          </Part>
        </>
      )}
      <Part number={team.paused ? '01' : '04'} title="Notes and invite">
        <Cards>
          <NotesSection teamId={team.id} style={card} />
          <InviteSection team={team} card={card} />
        </Cards>
      </Part>
    </View>
  );
}

type Card = StyleProp<ViewStyle>;

function ReportSection({
  team,
  reports,
  report,
  card,
}: {
  team: SupervisedTeam;
  reports?: TeamReportSummary[];
  report?: TeamReport;
  card: Card;
}) {
  const make = useMakeTeamReport();
  if (!reports) return <Skeleton height={120} radius={radius.md} />;
  if (reports.length === 0) {
    return (
      <Section
        style={card}
        title="Weekly report"
        footer={`Reports are made each Monday for the week before. ${
          team.members >= team.minimumMembers
            ? `${team.members} people have joined.`
            : `${team.members} of the ${team.minimumMembers} people needed have joined.`
        }`}
      >
        <View style={styles.empty}>
          <Text color="muted">No report yet.</Text>
          <Button
            label="Make last week's report"
            disabled={make.isPending}
            onPress={() => make.mutate(team.id)}
          />
        </View>
        {make.error ? <ErrorLine error={make.error} /> : null}
      </Section>
    );
  }
  if (!report) return <Skeleton height={160} radius={radius.md} />;

  const rows = changeRows(report);
  const changed = rows.filter((row) => row.status === 'changed').length;
  const summary = (
    <Section title="Summary" style={card}>
      <Text variant="headline" style={styles.headline}>
        {report.headline}
      </Text>
      {report.narrative.map((paragraph) => (
        <Line key={paragraph.text} metric={paragraph.metric}>
          {paragraph.text}
        </Line>
      ))}
      {report.status === 'ready' ? (
        <KeyFigures
          items={[
            { value: `${report.membersIncluded}`, label: 'people with data' },
            { value: `${changed} of ${rows.length}`, label: 'metrics changed' },
            { value: `${report.levels.length}`, label: 'sharing levels' },
          ]}
        />
      ) : null}
    </Section>
  );
  if (report.status !== 'ready') return summary;
  return (
    <Cards basis={360}>
      <View style={styles.stack}>
        {summary}
        {report.weekdays.length > 0 ? (
          <Section
            style={card}
            title="By weekday"
            footer="The median, across people, of each weekday against each person's own usual over five weeks. A description, not a test."
          >
            {report.weekdays.map((section) => (
              <WeekdayChart
                key={section.evidenceId}
                section={section}
                evidence={report.evidence[section.evidenceId]}
              />
            ))}
          </Section>
        ) : null}
      </View>
      <Section
        style={card}
        title="How the team changed"
        footer="Each person's week against their own four weeks before; only the counts and the median reach you, never anyone's own data. A metric counts as changed only when the whole team moved clearly. Patterns, not advice."
      >
        <ChangeChart rows={rows} />
      </Section>
    </Cards>
  );
}

/** One sentence of the report with its metric's color, as findings are shown on Today. */
function Line({
  metric,
  muted = false,
  children,
}: {
  metric: string;
  muted?: boolean;
  children: ReactNode;
}) {
  const colors = useColors();
  const color = useMetricColor(metric);
  return (
    <View style={[styles.line, { borderColor: colors.border }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text color={muted ? 'muted' : 'text'} style={{ flex: 1 }}>
        {children}
      </Text>
    </View>
  );
}

function LevelsSection({ levels, card }: { levels: SharedLevels[]; card: Card }) {
  return (
    <Section
      style={card}
      title="Shared weekly levels"
      footer="Only people who chose to share, each week against their own usual weeks, never against each other. They can stop at any time."
    >
      {levels.length === 0 ? (
        <View style={styles.empty}>
          <Text color="muted">No one shares their levels yet.</Text>
        </View>
      ) : (
        <LevelsTable levels={levels} />
      )}
    </Section>
  );
}

function InviteSection({ team, card }: { team: SupervisedTeam; card: Card }) {
  const rotate = useRotateTeamCode();
  const [copied, setCopied] = useState(false);
  return (
    <Section title="Invite" style={card}>
      <Row
        icon="key-outline"
        title={team.inviteCode}
        detail={copied ? 'Copied' : 'Tap to copy and share with your team'}
        onPress={async () => {
          await Clipboard.setStringAsync(team.inviteCode);
          setCopied(true);
        }}
        accessibilityLabel={`Invite code ${team.inviteCode.split('').join(' ')}. Copy`}
      />
      <Row
        icon="people-outline"
        title={`${team.members} ${team.members === 1 ? 'person' : 'people'} joined`}
        detail={`Reports need at least ${team.minimumMembers}`}
      />
      <Row
        icon="refresh-outline"
        title="New code"
        detail="The old code stops working; people already in stay"
        onPress={() => rotate.mutate(team.id)}
      />
      {rotate.error ? <ErrorLine error={rotate.error} /> : null}
      <HrContact team={team} />
    </Section>
  );
}

/** Who receives the team's check-in alerts with the supervisor (docs/escalation.md). */
function HrContact({ team }: { team: SupervisedTeam }) {
  const colors = useColors();
  const save = useSetTeamHr();
  const [editing, setEditing] = useState(false);
  const [email, setEmail] = useState('');
  if (!editing) {
    return (
      <Row
        icon="shield-checkmark-outline"
        title={team.hrEmail ? `HR: ${team.hrEmail}` : 'No HR contact'}
        detail="Check-in alerts go to you and HR, only for people who turned them on"
        onPress={() => {
          setEmail(team.hrEmail ?? '');
          setEditing(true);
        }}
      />
    );
  }
  const submit = () =>
    save.mutate(
      { teamId: team.id, email: email.trim() || null },
      { onSuccess: () => setEditing(false) },
    );
  return (
    <View>
      <View style={styles.field}>
        <TextInput
          value={email}
          onChangeText={setEmail}
          placeholder="hr@company.com"
          placeholderTextColor={colors.faint}
          autoCapitalize="none"
          keyboardType="email-address"
          onSubmitEditing={submit}
          accessibilityLabel="HR contact email"
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
        <Button
          label={email.trim() ? 'Save' : 'Remove'}
          disabled={save.isPending}
          onPress={submit}
        />
      </View>
      <Button label="Cancel" variant="secondary" onPress={() => setEditing(false)} />
      {save.error ? <ErrorLine error={save.error} /> : null}
    </View>
  );
}

function PastWeeks({
  reports,
  selected,
  onSelect,
  card,
}: {
  reports: TeamReportSummary[];
  selected?: ISODate;
  onSelect: (start: ISODate) => void;
  card: Card;
}) {
  if (reports.length < 2) return null;
  return (
    <Section title="Past weeks" style={card}>
      {reports.map((report) => (
        <Row
          key={report.week.start}
          icon={report.week.start === selected ? 'radio-button-on' : 'radio-button-off'}
          title={windowLabel(report.week)}
          detail={report.headline}
          onPress={() => onSelect(report.week.start)}
        />
      ))}
    </Section>
  );
}

function ErrorLine({ error }: { error: Error }) {
  const message = error instanceof ApiError ? error.message : 'Something went wrong. Try again.';
  return (
    <Text variant="caption" color="danger" style={styles.error}>
      {message}
    </Text>
  );
}

const styles = StyleSheet.create({
  switcher: { gap: spacing.lg, paddingBottom: spacing.xs },
  switch: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingVertical: spacing.xs,
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  switchOpen: { fontFamily: fonts.semibold },
  page: { gap: spacing.xxl },
  stack: { gap: spacing.md },
  card: { borderRadius: TILE_RADIUS, borderWidth: 1, padding: spacing.lg, marginTop: 0 },
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.md,
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 16,
    paddingVertical: 11,
    fontFamily: fonts.regular,
    fontSize: 15,
  },
  empty: { gap: spacing.md, paddingVertical: spacing.md, alignItems: 'flex-start' },
  headline: { paddingVertical: spacing.md },
  line: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 7 },
  error: { paddingBottom: spacing.sm },
});
