import * as Clipboard from 'expo-clipboard';
import { type ReactNode, useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { ApiError } from '@/api/http';
import {
  useCreateTeam,
  useMakeTeamReport,
  useRotateTeamCode,
  useTeamAlerts,
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
import { AlertsSection, NotesSection, ProposalsSection } from '@/components/teamAgent';
import {
  AreaStrip,
  AskTeamRow,
  PrioritiesSection,
  TeamStatusLine,
} from '@/components/teamDashboard';
import { ChangeChart, KeyFigures, LevelsTable, WeekdayChart } from '@/components/teamReport';
import { QueryState, Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { windowLabel } from '@/lib/format';
import { areaReadings, changeRows, teamStatus } from '@/lib/team';
import { useWide } from '@/lib/layout';
import { fonts, radius, spacing, useColors, useMetricColor } from '@/theme';

/** A supervisor's team: this week's report, shared levels, the invite code (docs/teams.md). */
export default function TeamScreen() {
  const teams = useTeams();
  const team = teams.data?.[0]; // one team per supervisor in this first version
  return (
    <Screen
      title={team?.name ?? 'Team'}
      wide
      refreshing={teams.isRefetching}
      onRefresh={teams.refetch}
    >
      <QueryState query={teams}>
        {() => (team ? <TeamView team={team} /> : <CreateTeam />)}
      </QueryState>
    </Screen>
  );
}

function CreateTeam() {
  const colors = useColors();
  const create = useCreateTeam();
  const [name, setName] = useState('');
  const submit = () => name.trim() && create.mutate(name);
  return (
    <Section
      title="Create your team"
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
      {create.error ? <ErrorLine error={create.error} /> : null}
    </Section>
  );
}

function TeamView({ team }: { team: SupervisedTeam }) {
  const wide = useWide();
  const reports = useTeamReports(team.id);
  const [chosen, setChosen] = useState<ISODate | undefined>();
  const week = chosen ?? reports.data?.[0]?.week.start;
  const report = useTeamReport(team.id, week);
  // Where the team stands now: the latest report and the open alerts, whatever week is shown.
  const latest = useTeamReport(team.id, reports.data?.[0]?.week.start);
  const alerts = useTeamAlerts(team.id);

  const main = (
    <>
      <TeamStatusLine status={teamStatus(alerts.data, latest.data)} />
      <AreaStrip readings={areaReadings(alerts.data, latest.data)} />
      <AskTeamRow />
      <ProposalsSection teamId={team.id} />
      <AlertsSection teamId={team.id} />
      {latest.data && latest.data.week.start === week ? (
        <PrioritiesSection report={latest.data} />
      ) : null}
      <ReportSection team={team} reports={reports.data} report={report.data} />
    </>
  );
  const side = (
    <>
      <NotesSection teamId={team.id} />
      {report.data ? <LevelsSection levels={report.data.levels} /> : null}
      <InviteSection team={team} />
      <PastWeeks
        reports={reports.data ?? []}
        selected={week}
        onSelect={(start) => setChosen(start)}
      />
    </>
  );
  if (!wide) {
    return (
      <>
        {main}
        {side}
      </>
    );
  }
  return (
    <View style={styles.columns}>
      <View style={styles.main}>{main}</View>
      <View style={styles.side}>{side}</View>
    </View>
  );
}

function ReportSection({
  team,
  reports,
  report,
}: {
  team: SupervisedTeam;
  reports?: TeamReportSummary[];
  report?: TeamReport;
}) {
  const make = useMakeTeamReport();
  if (!reports) return <Skeleton height={120} radius={radius.md} />;
  if (reports.length === 0) {
    return (
      <Section
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
  return (
    <>
      <Section title={`Week of ${windowLabel(report.week)}`}>
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
      {report.status === 'ready' ? (
        <>
          <Section
            title="How the team changed"
            footer="Each person's week against their own four weeks before; only the counts and the median reach you, never anyone's own data. A metric counts as changed only when the whole team moved clearly. Patterns, not advice."
          >
            <ChangeChart rows={rows} />
          </Section>
          {report.weekdays.length > 0 ? (
            <Section
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
        </>
      ) : null}
    </>
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

function LevelsSection({ levels }: { levels: SharedLevels[] }) {
  return (
    <Section
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

function InviteSection({ team }: { team: SupervisedTeam }) {
  const rotate = useRotateTeamCode();
  const [copied, setCopied] = useState(false);
  return (
    <Section title="Invite">
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
    </Section>
  );
}

function PastWeeks({
  reports,
  selected,
  onSelect,
}: {
  reports: TeamReportSummary[];
  selected?: ISODate;
  onSelect: (start: ISODate) => void;
}) {
  if (reports.length < 2) return null;
  return (
    <Section title="Past weeks">
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
  columns: { flexDirection: 'row', gap: spacing.xxl, alignItems: 'flex-start' },
  main: { flex: 3, minWidth: 0 },
  side: { flex: 2, minWidth: 0 },
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
