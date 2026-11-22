import { useState } from 'react';
import { type StyleProp, StyleSheet, TextInput, View, type ViewStyle } from 'react-native';

import { ApiError } from '@/api/http';
import { useAddTeamNote, useDeleteTeamNote, useTeamNotes } from '@/api/hooks';
import { Row, Section } from '@/components/list';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { fonts, radius, spacing, useColors } from '@/theme';


/** What the supervisor told the agent about the team's work, so changes can be lined up with it. */
export function NotesSection({
  teamId,
  style,
}: {
  teamId: string;
  style?: StyleProp<ViewStyle>;
}) {
  const colors = useColors();
  const notes = useTeamNotes(teamId);
  const add = useAddTeamNote(teamId);
  const remove = useDeleteTeamNote(teamId);
  const [text, setText] = useState('');
  const [date, setDate] = useState('');
  const parsed = new Date(date + 'T00:00:00Z');
  const validDate =
    !date || (!Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date);
  const save = () => {
    if (!text.trim() || !validDate || add.isPending) return;
    add.mutate(
      { text: text.trim(), date: date || undefined },
      {
        onSuccess: () => {
          setText('');
          setDate('');
        },
      },
    );
  };
  return (
    <Section
      style={style}
      title="Team notes"
      footer="Add an event date to compare past releases or deadlines with upcoming ones. Keep notes about the whole team."
    >
      {(notes.data ?? []).map((note) => (
        <Row
          key={note.id}
          icon="bookmark-outline"
          title={note.text}
          detail={
            note.startsOn
              ? `${note.startsOn}${note.endsOn && note.endsOn !== note.startsOn ? ` to ${note.endsOn}` : ''}`
              : undefined
          }
          value="Remove"
          onPress={() => remove.mutate(note.id)}
          accessibilityLabel={`Remove note: ${note.text}`}
        />
      ))}
      <View style={styles.field}>
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="e.g. Product release"
          placeholderTextColor={colors.faint}
          maxLength={300}
          onSubmitEditing={save}
          accessibilityLabel="New team note"
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
      </View>
      <View style={styles.field}>
        <TextInput
          value={date}
          onChangeText={setDate}
          maxLength={10}
          accessibilityLabel="Event date, YYYY-MM-DD"
          placeholder="Event date · YYYY-MM-DD"
          placeholderTextColor={colors.faint}
          onSubmitEditing={save}
          style={[
            styles.input,
            { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
          ]}
        />
        <Button label="Add" disabled={!validDate || !text.trim() || add.isPending} onPress={save} />
      </View>
      {!validDate ? <Text color="danger">Enter a valid date as YYYY-MM-DD.</Text> : null}
      {add.error ? <ErrorLine error={add.error} /> : null}
    </Section>
  );
}

function ErrorLine({ error }: { error: Error }) {
  const message = error instanceof ApiError ? error.message : 'Something went wrong. Try again.';
  return (
    <Text variant="caption" color="danger" style={styles.note}>
      {message}
    </Text>
  );
}

const styles = StyleSheet.create({
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
  note: { paddingBottom: spacing.sm },
});
