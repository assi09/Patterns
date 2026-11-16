import { useState } from 'react';
import { Pressable, type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native';

import { useCheckIn, useSaveCheckIn } from '@/api/hooks';
import { CHECKIN_TAGS, type CheckIn, type ISODate } from '@/api/types';
import { Section } from '@/components/list';
import { Text } from '@/components/Text';
import { Chip } from '@/components/ui';
import { isHovered } from '@/lib/platform';
import { fonts, radius, spacing, useColors, useMetricColor } from '@/theme';

export const FEELINGS = ['Drained', 'Low', 'Okay', 'Good', 'Great'];
export const TAG_LABELS: Record<CheckIn['tags'][number], string> = {
  hard_training: 'Hard training',
  alcohol: 'Alcohol',
  late_meal: 'Late meal',
  stress: 'Stress',
  travel: 'Travel',
  feeling_sick: 'Feeling sick',
};

/**
 * "How do you feel this morning?": a rating from 1 to 5 and optional tags. It is the ground truth
 * the recovery score is compared with, and something the agent can look at.
 */
export function CheckInSection({
  day,
  today,
  style,
}: {
  day: ISODate;
  today: boolean;
  style?: StyleProp<ViewStyle>; // Today shows it as a tile
}) {
  const colors = useColors();
  const checkIn = useCheckIn(day);
  const save = useSaveCheckIn();
  const [editing, setEditing] = useState(false);
  const [rating, setRating] = useState<number>();
  const [tags, setTags] = useState<CheckIn['tags']>([]);
  const saved = checkIn.data;

  // Past days without a check-in show nothing: only today's can be set.
  if (checkIn.isPending || (!saved && !today)) return null;

  if (saved && !editing) {
    return (
      <Section title="Check-in" style={style}>
        <Pressable
          accessibilityRole={today ? 'button' : undefined}
          accessibilityHint={today ? 'Change your check-in' : undefined}
          disabled={!today}
          onPress={() => {
            setRating(saved.rating);
            setTags(saved.tags);
            setEditing(true);
          }}
          style={(state) => [
            styles.saved,
            today && isHovered(state) && { backgroundColor: colors.track },
          ]}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text>You felt {FEELINGS[saved.rating - 1].toLowerCase()}</Text>
            <Text variant="caption" color="muted">
              {saved.tags.length ? saved.tags.map((t) => TAG_LABELS[t]).join(' · ') : 'No tags'}
            </Text>
          </View>
          {today && (
            <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
              Change
            </Text>
          )}
        </Pressable>
      </Section>
    );
  }

  const chosen = rating ?? saved?.rating;
  return (
    <Section
      style={style}
      title="Check-in"
      footer="How you feel is compared with your recovery score over time. Optional, and only for you."
    >
      <View style={styles.body}>
        <Text>How do you feel this morning?</Text>
        <View style={styles.scale} accessibilityRole="radiogroup">
          {FEELINGS.map((label, index) => (
            <Feeling
              key={label}
              label={label}
              selected={chosen === index + 1}
              onPress={() => setRating(index + 1)}
            />
          ))}
        </View>
        {chosen !== undefined && (
          <>
            <View style={styles.tags}>
              {CHECKIN_TAGS.map((tag) => (
                <Chip
                  key={tag}
                  label={TAG_LABELS[tag]}
                  selected={tags.includes(tag)}
                  onPress={() =>
                    setTags(tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag])
                  }
                />
              ))}
            </View>
            <View style={styles.actions}>
              {editing && (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => setEditing(false)}
                  style={styles.action}
                >
                  <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
                    Cancel
                  </Text>
                </Pressable>
              )}
              <Pressable
                accessibilityRole="button"
                disabled={save.isPending}
                onPress={() =>
                  save.mutate({ day, rating: chosen, tags }, { onSuccess: () => setEditing(false) })
                }
                style={[styles.action, { backgroundColor: colors.text }]}
              >
                <Text
                  variant="caption"
                  style={{ color: colors.background, fontFamily: fonts.semibold }}
                >
                  {save.isPending ? 'Saving…' : 'Save'}
                </Text>
              </Pressable>
            </View>
            {save.error && (
              <Text variant="caption" color="danger">
                {save.error.message}
              </Text>
            )}
          </>
        )}
      </View>
    </Section>
  );
}

function Feeling({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  const colors = useColors();
  const color = useMetricColor('recovery_score');
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={(state) => [
        styles.feeling,
        { borderColor: selected ? color : colors.border },
        selected && { backgroundColor: `${color}22` },
        !selected && isHovered(state) && { backgroundColor: colors.track },
      ]}
    >
      <Text
        variant="caption"
        style={{ color: selected ? color : colors.text, fontFamily: fonts.semibold }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  saved: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    marginHorizontal: -spacing.sm,
    borderRadius: radius.sm,
  },
  body: { gap: spacing.md, paddingVertical: spacing.md },
  scale: { flexDirection: 'row', gap: spacing.xs },
  feeling: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  action: { paddingHorizontal: spacing.lg, paddingVertical: 8, borderRadius: radius.pill },
});
