import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Switch, TextInput, View } from 'react-native';

import { ApiError } from '@/api/http';
import {
  useJoinTeam,
  useLeaveTeam,
  useMyCheckins,
  useMyTeams,
  usePreviewTeam,
  useShareTeamCheckin,
  useShareTeamLevels,
} from '@/api/hooks';
import type { Membership, TeamPreview } from '@/api/types';
import { Row, Section } from '@/components/list';
import { QueryState, Screen } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { shortDate } from '@/lib/format';
import { fonts, radius, spacing, useColors } from '@/theme';

/** The person's teams: joining with a code and consent, sharing levels, leaving (docs/teams.md). */
export default function Teams() {
  const teams = useMyTeams();
  return (
    <Screen refreshing={teams.isRefetching} onRefresh={teams.refetch}>
      <QueryState query={teams}>
        {() => (
          <>
            {teams.data!.map((membership) => (
              <TeamSection key={membership.teamId} membership={membership} />
            ))}
            <JoinSection first={teams.data!.length === 0} />
          </>
        )}
      </QueryState>
    </Screen>
  );
}

function TeamSection({ membership }: { membership: Membership }) {
  const colors = useColors();
  const share = useShareTeamLevels();
  const checkin = useShareTeamCheckin();
  const leave = useLeaveTeam();
  const waiting = useMyCheckins().data?.find(
    (c) => c.teamId === membership.teamId && c.status === 'waiting',
  );
  const [askingShare, setAskingShare] = useState(false);
  const [askingCheckin, setAskingCheckin] = useState(false);
  const [askingLeave, setAskingLeave] = useState(false);
  const error = share.error ?? checkin.error ?? leave.error;

  return (
    <Section
      title={membership.team}
      footer="Your supervisor sees the team's weekly figures, built from at least 5 people, never your own data. You can leave at any time."
    >
      <Row
        icon="person-outline"
        title={membership.supervisor}
        detail={`Supervisor · joined ${shortDate(membership.joinedAt.slice(0, 10))}`}
      />
      <Row
        icon="pulse-outline"
        title="Show my weekly levels"
        detail={
          membership.shareLevels
            ? 'Your supervisor sees your name with your weekly recovery, sleep, strain and stress'
            : 'Off: only the team figures include you'
        }
        accessory={
          <Switch
            accessibilityLabel="Show my weekly levels to my supervisor"
            value={membership.shareLevels} // stays off until the consent below is confirmed
            disabled={share.isPending}
            onValueChange={(on) => {
              if (on) return setAskingShare(true); // turning on needs the consent below first
              setAskingShare(false);
              share.mutate({ teamId: membership.teamId, share: false });
            }}
            trackColor={{ true: colors.accent, false: colors.track }}
            thumbColor="#FFFFFF"
            // react-native-web colors the "on" knob separately.
            {...({ activeThumbColor: '#FFFFFF' } as object)}
          />
        }
      />
      {askingShare && !membership.shareLevels ? (
        <Consent
          text={membership.levelsConsent}
          confirm="Share my levels"
          busy={share.isPending}
          onConfirm={() =>
            share.mutate(
              {
                teamId: membership.teamId,
                share: true,
                consentVersion: membership.levelsConsentVersion,
              },
              { onSuccess: () => setAskingShare(false) },
            )
          }
          onCancel={() => setAskingShare(false)}
        />
      ) : null}
      <Row
        icon="hand-left-outline"
        title="Check-in alerts"
        detail={
          membership.checkinAlerts
            ? "If your data shows a sustained, extreme change, you are told first; then your supervisor and the team's HR contact are asked to check in. No values are shared"
            : 'Off: nobody is ever asked to check in with you'
        }
        accessory={
          <Switch
            accessibilityLabel="Check-in alerts to my supervisor and the team's HR contact"
            value={membership.checkinAlerts} // stays off until the consent below is confirmed
            disabled={checkin.isPending}
            onValueChange={(on) => {
              if (on) return setAskingCheckin(true);
              setAskingCheckin(false);
              checkin.mutate({ teamId: membership.teamId, share: false });
            }}
            trackColor={{ true: colors.accent, false: colors.track }}
            thumbColor="#FFFFFF"
            {...({ activeThumbColor: '#FFFFFF' } as object)}
          />
        }
      />
      {askingCheckin && !membership.checkinAlerts ? (
        <Consent
          text={membership.checkinConsent}
          confirm="Turn on check-in alerts"
          busy={checkin.isPending}
          onConfirm={() =>
            checkin.mutate(
              {
                teamId: membership.teamId,
                share: true,
                consentVersion: membership.checkinConsentVersion,
              },
              { onSuccess: () => setAskingCheckin(false) },
            )
          }
          onCancel={() => setAskingCheckin(false)}
        />
      ) : null}
      {waiting ? (
        <Row
          icon="alert-circle-outline"
          title="A check-in alert is waiting"
          detail="Nothing is sent yet. Open it to see why, or stop it"
          onPress={() => router.push({ pathname: '/checkin/[id]', params: { id: waiting.id } })}
        />
      ) : null}
      {askingLeave ? (
        <Consent
          text={`Leave ${membership.team}? From the next report your data is left out of its figures, and your levels are no longer shown.`}
          confirm="Leave team"
          busy={leave.isPending}
          onConfirm={() => leave.mutate(membership.teamId)}
          onCancel={() => setAskingLeave(false)}
        />
      ) : (
        <Row
          icon="exit-outline"
          title="Leave team"
          tone="danger"
          onPress={() => setAskingLeave(true)}
        />
      )}
      {error ? <ErrorLine error={error} /> : null}
    </Section>
  );
}

function JoinSection({ first }: { first: boolean }) {
  const colors = useColors();
  const preview = usePreviewTeam();
  const join = useJoinTeam();
  const [code, setCode] = useState('');
  const [found, setFound] = useState<TeamPreview | null>(null);

  function reset() {
    setFound(null);
    setCode('');
    preview.reset();
    join.reset();
  }

  return (
    <Section
      title="Join a team"
      footer={
        first
          ? 'A supervisor can see how a team’s sleep, activity and scores change each week, as a group. Ask them for the team’s code.'
          : undefined
      }
    >
      {found ? (
        <Consent
          title={`${found.team} · ${found.supervisor}`}
          text={found.consent}
          confirm="Join team"
          busy={join.isPending}
          onConfirm={() =>
            join.mutate({ code, consentVersion: found.consentVersion }, { onSuccess: reset })
          }
          onCancel={reset}
        />
      ) : (
        <View style={styles.join}>
          <TextInput
            value={code}
            onChangeText={setCode}
            placeholder="Team code"
            placeholderTextColor={colors.faint}
            autoCapitalize="characters"
            autoCorrect={false}
            maxLength={32}
            editable={!preview.isPending}
            onSubmitEditing={() => code.trim() && preview.mutate(code, { onSuccess: setFound })}
            returnKeyType="go"
            accessibilityLabel="Team code"
            style={[
              styles.input,
              { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
            ]}
          />
          <Button
            label="Continue"
            disabled={!code.trim() || preview.isPending}
            onPress={() => preview.mutate(code, { onSuccess: setFound })}
          />
        </View>
      )}
      {preview.error || join.error ? <ErrorLine error={(preview.error ?? join.error)!} /> : null}
    </Section>
  );
}

/** What the person agrees to, in full, with the action and a way back; no pop-up dialogs. */
function Consent({
  title,
  text,
  confirm,
  busy,
  onConfirm,
  onCancel,
}: {
  title?: string;
  text: string;
  confirm: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <View style={styles.consent}>
      {title ? <Text variant="bodyStrong">{title}</Text> : null}
      <Text color="muted">{text}</Text>
      <View style={styles.actions}>
        <Button label={confirm} disabled={busy} onPress={onConfirm} />
        <Button label="Cancel" variant="secondary" disabled={busy} onPress={onCancel} />
      </View>
    </View>
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
  join: {
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
    letterSpacing: 1,
  },
  consent: { gap: spacing.sm, paddingVertical: spacing.md },
  actions: { flexDirection: 'row', gap: spacing.xs, flexWrap: 'wrap' },
  error: { paddingBottom: spacing.sm },
});
