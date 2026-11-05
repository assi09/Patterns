import { Ionicons } from '@expo/vector-icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ComponentProps, type ReactNode } from 'react';
import {
  Linking,
  Pressable,
  StyleSheet,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';

import { api, usingMock } from '@/api';
import type { HealthAction, HealthLog } from '@/api/types';
import { Text } from '@/components/Text';
import { Button, Card, Chip } from '@/components/ui';
import {
  formFromLog,
  estimateNote,
  logDetails,
  logFromForm,
  logTitle,
  MEALS,
  STATUS,
  trackerSummary,
  workoutChoices,
  workoutGroup,
  type LogForm,
} from '@/lib/actionLog';
import { fonts, METRIC_COLORS, radius, spacing, useColors, useScheme, type Colors } from '@/theme';

type IconName = ComponentProps<typeof Ionicons>['name'];

const ICONS: Record<string, IconName> = {
  run: 'walk-outline',
  foot: 'footsteps-outline',
  wheels: 'bicycle-outline',
  swim: 'water-outline',
  TENNIS: 'tennisball-outline',
  PADEL: 'tennisball-outline',
  SOCCER: 'football-outline',
  FOOTBALL_AMERICAN: 'american-football-outline',
  BASKETBALL: 'basketball-outline',
  YOGA: 'body-outline',
  PILATES: 'body-outline',
  WEIGHTLIFTING: 'barbell-outline',
  STRENGTH_TRAINING: 'barbell-outline',
};

export function logIcon(log: HealthLog): IconName {
  return log.kind === 'food' ? 'restaurant-outline' : exerciseIcon(log.exerciseType);
}

/** An icon for a workout type, e.g. a tennis ball for TENNIS. */
export function exerciseIcon(type: string): IconName {
  return ICONS[type] ?? ICONS[workoutGroup(type)] ?? 'fitness-outline';
}

/** The status as a small colored label. */
export function StatusPill({ status }: { status: HealthAction['status'] }) {
  const colors = useColors();
  const scheme = useScheme();
  const tone = {
    draft: [colors.accentSoft, colors.accent],
    succeeded: [colors.surfaceRaised, METRIC_COLORS.recovery[scheme]],
    failed: [colors.surfaceRaised, colors.danger],
  }[status as string] ?? [colors.surfaceRaised, colors.muted];
  return (
    <View style={[styles.pill, { backgroundColor: tone[0] }]}>
      <Text variant="caption" style={{ color: tone[1], fontFamily: fonts.semibold }}>
        {STATUS[status]}
      </Text>
    </View>
  );
}

/**
 * One logging entry. Only its buttons can send it to Google; nothing the model says can.
 * `collapsible` shows only the summary until it is tapped, then the actions in the same card.
 */
export function LogDraftCard({
  id,
  initial,
  collapsible = false,
}: {
  id: string;
  initial?: HealthAction; // from a list already loaded, so the card does not fetch it again
  collapsible?: boolean;
}) {
  const colors = useColors();
  const client = useQueryClient();
  const key = ['health-action', id];
  const query = useQuery({
    queryKey: key,
    queryFn: () => api.getAction(id),
    initialData: initial,
    // A list refresh brings newer data than an entry loaded earlier.
    initialDataUpdatedAt: initial ? Date.parse(initial.updatedAt) : undefined,
  });
  const [expanded, setExpanded] = useState(!collapsible);
  const [form, setForm] = useState<{ version: number; fields: LogForm } | null>(null);
  const [formError, setFormError] = useState<string>();
  const [confirmingUndo, setConfirmingUndo] = useState(false);

  const action = useMutation({
    mutationFn: (run: () => Promise<HealthAction>) => run(),
    retry: false, // a write is never repeated automatically
    onSuccess: (saved) => {
      client.setQueryData(key, saved);
      client.invalidateQueries({ queryKey: ['health-actions'] });
      setForm(null);
      setConfirmingUndo(false);
      setFormError(undefined);
    },
    onError: () => client.invalidateQueries({ queryKey: key }),
  });
  const allow = useMutation({
    mutationFn: async (kind: HealthLog['kind']) => {
      const { url } = await api.connectGoogle(kind === 'food' ? 'food_logging' : 'workout_logging');
      if (url) await Linking.openURL(url);
    },
  });

  const row = query.data;
  if (!row) {
    return (
      <Card>
        <Text variant="caption" color="muted">
          {query.isError ? 'Could not load this entry.' : 'Loading the entry…'}
        </Text>
        {query.isError && <TextButton label="Try again" onPress={() => query.refetch()} />}
      </Card>
    );
  }

  const busy = action.isPending;
  const tracker = trackerSummary(row.log);
  const editable = row.status === 'draft' || row.status === 'failed';
  const code = (action.error as { code?: string } | null)?.code;
  const run = (call: () => Promise<HealthAction>) => action.mutate(call);

  function save() {
    if (!form || !row) return;
    try {
      const log = logFromForm(row.log, form.fields);
      run(() => api.reviseAction(id, form.version, log));
    } catch (error) {
      setFormError((error as Error).message);
    }
  }

  return (
    // In a list it is a row between hairlines; in a chat answer, a card to act on.
    <Container style={collapsible ? styles.listRow : [styles.card, styles.inChat]}>
      <Pressable
        accessibilityRole={collapsible ? 'button' : undefined}
        accessibilityState={collapsible ? { expanded } : undefined}
        disabled={!collapsible}
        onPress={() => setExpanded(!expanded)}
        style={styles.header}
      >
        <View style={[styles.icon, { backgroundColor: colors.accentSoft }]}>
          <Ionicons name={logIcon(row.log)} size={18} color={colors.accent} />
        </View>
        <View style={styles.headerText}>
          <Text variant="headline" numberOfLines={2}>
            {logTitle(row.log)}
          </Text>
          <Text variant="caption" color="muted">
            {logDetails(row.log).join(' · ')}
          </Text>
          {estimateNote(row.log) && (
            <Text variant="caption" color="warning">
              {estimateNote(row.log)}
            </Text>
          )}
        </View>
        <StatusPill status={row.status} />
        {collapsible && (
          <Ionicons
            name={expanded ? 'chevron-up' : 'chevron-down'}
            size={16}
            color={colors.faint}
            style={styles.chevron}
          />
        )}
      </Pressable>

      {expanded && form && (
        <EditForm
          log={row.log}
          fields={form.fields}
          onChange={(fields) => setForm({ ...form, fields })}
          disabled={busy}
          colors={colors}
        />
      )}

      {expanded && (
        <>
          {tracker && !form && (
            <View style={styles.tracker}>
              {tracker.values.length > 0 && (
                <Text variant="caption" color="muted">
                  <Text variant="caption" style={{ fontFamily: fonts.semibold }}>
                    From your Fitbit:{' '}
                  </Text>
                  {tracker.values.join(' · ')}
                </Text>
              )}
              {tracker.note && (
                <Text variant="caption" color="muted">
                  {tracker.note}
                </Text>
              )}
              {tracker.overlaps.length > 0 && editable && (
                <Text variant="caption" color="warning">
                  Your Fitbit already recorded {tracker.overlaps.join(', ')} at this time. Logging
                  this too would add a second workout.
                </Text>
              )}
              {tracker.canRefresh && editable && (
                <TextButton
                  label="Refresh from Fitbit"
                  disabled={busy}
                  onPress={() => run(() => api.reviseAction(id, row.version, row.log))}
                />
              )}
            </View>
          )}
          {row.status === 'failed' && row.error && (
            <Text variant="caption" color="danger">
              {row.error}
            </Text>
          )}
          {['executing', 'undoing', 'unknown'].includes(row.status) && (
            <Text variant="caption" color="muted">
              Google has not confirmed this yet. Check again in a moment; do not log it a second
              time.
            </Text>
          )}
          {(formError || action.error) && (
            <Text variant="caption" color="danger">
              {formError ?? action.error?.message}
            </Text>
          )}
          {code === 'write_scope_needed' && (
            <Button
              label="Allow logging in Google"
              icon="logo-google"
              disabled={allow.isPending}
              onPress={() => allow.mutate(row.log.kind)}
            />
          )}

          <View style={styles.actions}>
            {form ? (
              <>
                <Button label={busy ? 'Saving…' : 'Save'} disabled={busy} onPress={save} />
                <Button
                  label="Discard"
                  variant="secondary"
                  disabled={busy}
                  onPress={() => setForm(null)}
                />
              </>
            ) : row.status === 'draft' || row.status === 'failed' ? (
              <>
                {row.status === 'draft' && (
                  <Button
                    label={busy ? 'Logging…' : 'Log it'}
                    icon="checkmark"
                    disabled={busy}
                    onPress={() => run(() => api.confirmAction(id, row.version))}
                  />
                )}
                <Button
                  label="Edit"
                  variant="secondary"
                  disabled={busy}
                  onPress={() => {
                    action.reset();
                    setFormError(undefined);
                    setForm({ version: row.version, fields: formFromLog(row.log) });
                  }}
                />
                <TextButton
                  label="Cancel"
                  disabled={busy}
                  onPress={() => run(() => api.cancelAction(id, row.version))}
                />
              </>
            ) : row.status === 'succeeded' ? (
              confirmingUndo ? (
                <>
                  <Text variant="caption" style={styles.question}>
                    Remove it from Google Health?
                  </Text>
                  <Button
                    label="Remove"
                    disabled={busy}
                    onPress={() => run(() => api.undoAction(id, row.version))}
                  />
                  <Button
                    label="Keep"
                    variant="secondary"
                    disabled={busy}
                    onPress={() => setConfirmingUndo(false)}
                  />
                </>
              ) : (
                <TextButton label="Undo" onPress={() => setConfirmingUndo(true)} />
              )
            ) : ['executing', 'undoing', 'unknown'].includes(row.status) ? (
              <Button label="Check again" variant="secondary" onPress={() => query.refetch()} />
            ) : null}
          </View>

          {row.status === 'draft' && !form && (
            <Text variant="caption" color="faint">
              {usingMock
                ? 'Demo: logging is only simulated.'
                : tracker?.values.length
                  ? "Log it adds this entry to Google Health, with your values and your Fitbit's."
                  : 'Log it adds this entry to Google Health, with the values you gave.'}
            </Text>
          )}
        </>
      )}
    </Container>
  );
}

function Container({ style, children }: { style: StyleProp<ViewStyle>; children: ReactNode }) {
  if (Array.isArray(style)) return <Card style={style}>{children}</Card>;
  return <View style={style}>{children}</View>;
}

function TextButton({
  label,
  onPress,
  disabled,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled}
      hitSlop={8}
      style={styles.textButton}
    >
      <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
        {label}
      </Text>
    </Pressable>
  );
}

/** Plain fields: chips for the type, a date and a time, numbers, and a duration as h:mm. */
function EditForm({
  log,
  fields,
  onChange,
  disabled,
  colors,
}: {
  log: HealthLog;
  fields: LogForm;
  onChange: (fields: LogForm) => void;
  disabled: boolean;
  colors: Colors;
}) {
  const set = (name: string) => (text: string) => onChange({ ...fields, [name]: text });
  const input = (name: string, label: string, props: TextInputProps = {}) => (
    <View style={styles.field} key={name}>
      <Text variant="caption" color="muted">
        {label}
      </Text>
      <TextInput
        accessibilityLabel={label}
        value={fields[name]}
        onChangeText={set(name)}
        editable={!disabled}
        autoCapitalize="none"
        placeholderTextColor={colors.faint}
        style={[
          styles.input,
          { color: colors.text, backgroundColor: colors.surface, borderColor: colors.border },
        ]}
        {...props}
      />
    </View>
  );
  const number = { keyboardType: 'decimal-pad' as const, placeholder: 'Not known' };
  const choices = log.kind === 'food' ? MEALS : workoutChoices(log.exerciseType);
  const choiceKey = log.kind === 'food' ? 'mealType' : 'exerciseType';

  return (
    <View style={styles.form}>
      {log.kind === 'food' && input('foodName', 'Food')}
      <View style={styles.chips}>
        {Object.entries(choices).map(([value, label]) => (
          <Chip
            key={value}
            label={label}
            selected={fields[choiceKey] === value}
            disabled={disabled}
            onPress={() => onChange({ ...fields, [choiceKey]: value })}
          />
        ))}
      </View>
      <View style={styles.row}>
        {input('date', 'Date', { placeholder: 'YYYY-MM-DD' })}
        {input('time', log.kind === 'food' ? 'Time' : 'Start', { placeholder: 'HH:MM' })}
      </View>
      {log.kind === 'food' ? (
        <>
          <View style={styles.row}>
            {input('energyKcal', 'Calories (kcal)', number)}
            {input('proteinG', 'Protein (g)', number)}
          </View>
          <View style={styles.row}>
            {input('carbohydrateG', 'Carbs (g)', number)}
            {input('fatG', 'Fat (g)', number)}
          </View>
        </>
      ) : (
        <View style={styles.row}>
          {input('duration', 'Duration (h:mm)', { placeholder: '1:30' })}
          {input('distanceKm', 'Distance (km)', number)}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  listRow: { gap: spacing.md, paddingVertical: spacing.md },
  inChat: { marginTop: spacing.sm }, // below the answer's text
  header: { flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
  chevron: { marginTop: 4 },
  headerText: { flex: 1, gap: 2 },
  icon: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: radius.pill },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.xs },
  question: { width: '100%' },
  tracker: { gap: spacing.xs, alignItems: 'flex-start' },
  textButton: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  form: { gap: spacing.md },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  row: { flexDirection: 'row', gap: spacing.sm },
  field: { flex: 1, gap: 4 },
  input: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    fontFamily: fonts.regular,
    fontSize: 15,
  },
});
