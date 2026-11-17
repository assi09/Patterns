import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import type { ComponentProps } from 'react';
import { Platform, StyleSheet, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { PressableScale } from '@/components/PressableScale';
import { ScrollExpandHero } from '@/components/ScrollExpandHero';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { column, radius, spacing, useColors } from '@/theme';

type IconName = ComponentProps<typeof Ionicons>['name'];

const FEATURES: { icon: IconName; title: string; body: string }[] = [
  {
    icon: 'chatbubble-ellipses-outline',
    title: 'Ask in plain words',
    body: '"Why was my sleep shorter last week?" Patterns decides what to check in your data and runs the numbers.',
  },
  {
    icon: 'stats-chart-outline',
    title: 'Every claim shows its numbers',
    body: 'Each finding links to the statistic behind it, so you can see exactly where it came from.',
  },
  {
    icon: 'pulse-outline',
    title: 'See what changed',
    body: 'Trends, shifts and weekday patterns across your sleep, heart rate and activity.',
  },
];

// Phones are portrait, so the landscape background lost most of the track there; they get an
// upright photo of lanes instead, in the app and in a phone's browser or home-screen web app.
// Wider screens keep the wide one. (Pixabay licence, free to use.)
const PORTRAIT = require('../../assets/landing/background-portrait.jpg');
const LANDSCAPE = require('../../assets/landing/background.jpg');

export default function Welcome() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const background = Platform.OS !== 'web' || height > width ? PORTRAIT : LANDSCAPE;
  const signUp = () => router.push('/sign-up');
  const signIn = () => router.push('/sign-in');

  const header = (
    <View style={[styles.header, { top: insets.top + spacing.sm }]}>
      <View style={styles.brand}>
        <Ionicons name="pulse" size={20} color="#FFFFFF" />
        <Text variant="headline" color="#FFFFFF">
          Patterns
        </Text>
      </View>
      <View style={styles.headerActions}>
        <PressableScale accessibilityRole="button" onPress={signIn} style={styles.headerGhost}>
          <Text variant="caption" color="#FFFFFF">
            Sign in
          </Text>
        </PressableScale>
        <PressableScale accessibilityRole="button" onPress={signUp} style={styles.headerSolid}>
          <Text variant="caption" color="#000000">
            Get started
          </Text>
        </PressableScale>
      </View>
    </View>
  );

  return (
    <>
      <StatusBar style="light" />
      <ScrollExpandHero
        image={require('../../assets/landing/hero.jpg')}
        imageSize={{ width: 1328, height: 1400 }}
        background={background}
        eyebrow="Your Fitbit, explained"
        title={['Know your', 'patterns']}
        hint="Scroll to explore"
        header={header}
      >
        <View style={[styles.body, column, { paddingBottom: insets.bottom + spacing.xxl * 1.5 }]}>
          <Text variant="label" color="accent">
            What Patterns does
          </Text>
          <Text variant="display">Your health data, in plain words</Text>
          <Text variant="body" color="muted" style={styles.lead}>
            Patterns reads your own Fitbit history and tells you what changed, when, and how your
            sleep, activity and recovery move together.
          </Text>

          <View style={styles.features}>
            {FEATURES.map((feature) => (
              <View key={feature.title} style={styles.feature}>
                <View style={[styles.icon, { backgroundColor: colors.accentSoft }]}>
                  <Ionicons name={feature.icon} size={20} color={colors.accent} />
                </View>
                <View style={styles.featureText}>
                  <Text variant="headline">{feature.title}</Text>
                  <Text variant="body" color="muted">
                    {feature.body}
                  </Text>
                </View>
              </View>
            ))}
          </View>

          <View style={styles.actions}>
            <Button label="Get started" icon="arrow-forward" iconAfter onPress={signUp} />
            <Button
              label="Sign in"
              variant="secondary"
              icon="chevron-forward"
              iconAfter
              onPress={signIn}
            />
          </View>

          <Text variant="caption" color="faint" style={styles.note}>
            Patterns describes patterns in your own data. It is not a medical device and does not
            give medical advice.
          </Text>
          <Text variant="caption" color="faint" style={styles.note}>
            Photos from Pixabay
          </Text>
        </View>
      </ScrollExpandHero>
    </>
  );
}

const styles = StyleSheet.create({
  header: {
    position: 'absolute',
    left: spacing.lg,
    right: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  brand: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  headerActions: { flexDirection: 'row', gap: spacing.sm },
  // Over the photo the header keeps its own colors whatever the theme.
  headerGhost: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  headerSolid: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: radius.pill,
    backgroundColor: '#FFFFFF',
  },
  body: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xxl * 1.5,
    gap: spacing.md,
  },
  lead: { fontSize: 17, lineHeight: 25 },
  features: { gap: spacing.xl, marginTop: spacing.xl },
  feature: { flexDirection: 'row', gap: spacing.lg, alignItems: 'flex-start' },
  icon: {
    width: 40,
    height: 40,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  featureText: { flex: 1, gap: spacing.xs },
  // Pills sized to their labels, side by side, as on most sign-up pages.
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: spacing.xl,
  },
  note: { textAlign: 'center', marginTop: spacing.sm },
});
