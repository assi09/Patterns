import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { useSession } from '@/lib/session';
import { markTourSeen, TOUR_STEPS } from '@/lib/tour';
import { column, fonts, radius, spacing, useColors } from '@/theme';

/** The first-use guide, one step a page; leaving it at any point marks it seen. */
export default function Tour() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { account } = useSession();
  const [index, setIndex] = useState(0);
  const step = TOUR_STEPS[index];
  const last = index === TOUR_STEPS.length - 1;

  const leave = (href?: string) => {
    if (account) void markTourSeen(account.email);
    if (router.canGoBack()) router.back();
    else router.replace('/');
    if (href) setTimeout(() => router.push(href as never), 0);
  };

  return (
    <View
      style={[
        styles.page,
        {
          backgroundColor: colors.background,
          paddingTop: insets.top + spacing.md,
          paddingBottom: insets.bottom + spacing.lg,
        },
      ]}
    >
      <View style={[column, styles.top]}>
        <Text variant="caption" color="muted">
          {index + 1} of {TOUR_STEPS.length}
        </Text>
        {!last && (
          <Pressable accessibilityRole="button" onPress={() => leave()} hitSlop={12}>
            <Text variant="caption" color="muted" style={{ fontFamily: fonts.semibold }}>
              Skip
            </Text>
          </Pressable>
        )}
      </View>

      <ScrollView contentContainerStyle={[column, styles.body]}>
        <View style={[styles.icon, { backgroundColor: colors.accentSoft }]}>
          <Ionicons name={step.icon} size={30} color={colors.accent} />
        </View>
        <Text variant="title">{step.title}</Text>
        <Text style={{ color: colors.text, fontSize: 17, lineHeight: 24 }}>{step.body}</Text>
        <View style={[styles.points, { backgroundColor: colors.surface }]}>
          {step.points.map((point) => (
            <View key={point} style={styles.point}>
              <Ionicons name="checkmark-circle" size={18} color={colors.accent} />
              <Text style={{ flex: 1, lineHeight: 21 }}>{point}</Text>
            </View>
          ))}
        </View>
        {step.action && (
          <Button
            label={step.action.label}
            icon="arrow-forward"
            iconAfter
            variant="secondary"
            onPress={() => leave(step.action!.href)}
          />
        )}
      </ScrollView>

      <View style={[column, styles.bottom]}>
        <View style={styles.dots} accessibilityLabel={`Step ${index + 1} of ${TOUR_STEPS.length}`}>
          {TOUR_STEPS.map((s, i) => (
            <View
              key={s.title}
              style={[
                styles.dot,
                { backgroundColor: i === index ? colors.accent : colors.track },
                i === index && { width: 18 },
              ]}
            />
          ))}
        </View>
        <View style={styles.buttons}>
          {index > 0 && (
            <Button label="Back" variant="secondary" onPress={() => setIndex(index - 1)} />
          )}
          <Button
            label={last ? 'Start using Patterns' : 'Next'}
            icon={last ? undefined : 'arrow-forward'}
            iconAfter
            onPress={() => (last ? leave() : setIndex(index + 1))}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, paddingHorizontal: spacing.lg },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  body: { gap: spacing.lg, paddingVertical: spacing.xl },
  icon: {
    width: 60,
    height: 60,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  points: { borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md },
  point: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  bottom: { gap: spacing.lg },
  dots: { flexDirection: 'row', gap: 6, justifyContent: 'center' },
  dot: { width: 6, height: 6, borderRadius: 3 },
  buttons: { flexDirection: 'row', gap: spacing.sm, justifyContent: 'flex-end' },
});
