import { BottomTabBarHeightContext } from 'expo-router/js-tabs';
import { useQueryClient } from '@tanstack/react-query';
import { type ComponentRef, type ReactNode, useContext, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { requestSync } from '@/api/hooks';
import { PressableScale } from '@/components/PressableScale';
import { WIDE_CONTENT } from '@/lib/layout';
import { PULL_TRIGGER, useWebPull } from '@/lib/pull';
import { floatingTabBar } from '@/lib/platform';
import { Skeleton } from '@/components/Skeleton';
import { Text } from '@/components/Text';
import { column, radius, spacing, useColors } from '@/theme';

interface ScreenProps {
  children: ReactNode;
  title?: string; // a large page title; tab screens use it instead of a header bar
  subtitle?: string;
  refreshing?: boolean;
  onRefresh?: () => unknown; // enables pull to refresh
  header?: ReactNode; // a custom top, in place of the title; gets the same safe-area spacing
  wide?: boolean; // a wider column, for screens laid out in two columns on large displays
}

export function Screen({
  children,
  title,
  subtitle,
  refreshing = false,
  onRefresh,
  header,
  wide = false,
}: ScreenProps) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const client = useQueryClient();
  // On iOS the tab bar floats over the content, so leave room for it.
  const barHeight = useContext(BottomTabBarHeightContext) ?? 0;
  const tabBarHeight = floatingTabBar ? barHeight : 0;
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const [reloading, setReloading] = useState(false);
  const refresh = () => {
    // Pulling to refresh also fetches new data from Google when it is due.
    void requestSync(client);
    return onRefresh ? onRefresh() : client.invalidateQueries();
  };
  // The web build (and an app added to the home screen) gets the pull from touch events.
  const pulled = useWebPull(scroll, () => {
    setReloading(true);
    void Promise.resolve(refresh()).finally(() => setReloading(false));
  });
  const webSpinner = Platform.OS === 'web' && (pulled > 0 || reloading || refreshing);

  return (
    <ScrollView
      ref={scroll}
      contentContainerStyle={[
        styles.content,
        wide && { maxWidth: WIDE_CONTENT },
        { paddingTop: title || header ? insets.top + spacing.md : spacing.lg },
        { paddingBottom: tabBarHeight + spacing.xl },
      ]}
      scrollIndicatorInsets={{ bottom: tabBarHeight }}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh && (
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              void refresh(); // React Native 0.88 types the callback's result
            }}
            tintColor={colors.muted}
          />
        )
      }
    >
      {webSpinner && (
        <View
          style={[
            styles.pull,
            {
              height: reloading || refreshing ? 44 : pulled,
              opacity: Math.min(1, pulled / PULL_TRIGGER) || 1,
            },
          ]}
          accessibilityLabel="Refreshing"
        >
          <ActivityIndicator color={colors.muted} />
        </View>
      )}
      {header}
      {title && !header && (
        <View style={styles.header}>
          {subtitle && (
            <Text variant="label" color="muted">
              {subtitle}
            </Text>
          )}
          <Text variant="display" accessibilityRole="header">
            {title}
          </Text>
        </View>
      )}
      {children}
    </ScrollView>
  );
}

interface QueryLike {
  isPending: boolean;
  error: Error | null;
  refetch: () => unknown;
}

/** Shows placeholders while loading and a retryable message on error; renders children otherwise. */
export function QueryState({
  query,
  children,
  loading,
}: {
  query: QueryLike;
  children: () => ReactNode;
  loading?: ReactNode; // placeholder shaped like the content
}) {
  const colors = useColors();
  if (query.isPending) {
    return (
      loading ?? (
        <View style={{ gap: spacing.md }}>
          <Skeleton height={120} radius={radius.lg} />
          <Skeleton height={120} radius={radius.lg} />
        </View>
      )
    );
  }
  if (query.error) {
    return (
      <View style={[styles.error, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <Text variant="headline">Could not load this</Text>
        <Text variant="caption" color="muted" style={{ textAlign: 'center' }}>
          {query.error.message}
        </Text>
        <PressableScale
          accessibilityRole="button"
          onPress={() => query.refetch()}
          style={[styles.retry, { backgroundColor: colors.accentSoft }]}
        >
          <Text variant="bodyStrong" color="accent">
            Try again
          </Text>
        </PressableScale>
      </View>
    );
  }
  return <>{children()}</>;
}

const styles = StyleSheet.create({
  content: { ...column, paddingHorizontal: spacing.lg, gap: spacing.md },
  header: { gap: 2, marginBottom: spacing.sm },
  pull: { alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  error: {
    padding: spacing.xl,
    alignItems: 'center',
    gap: spacing.sm,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
  },
  retry: {
    marginTop: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.pill,
  },
});
