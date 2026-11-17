import { Ionicons } from '@expo/vector-icons';
import { useEffect, useState } from 'react';
import { AppState, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { useSession } from '@/lib/session';
import { radius, spacing, useColors } from '@/theme';

const RECHECK_MS = 20_000;

/** Where a signed-in account waits until the owner approves it (or sees that they did not). */
export default function Waiting() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { account, refresh, logOut } = useSession();
  const [checking, setChecking] = useState(false);
  const rejected = account?.status === 'rejected';

  async function checkAgain() {
    setChecking(true);
    await refresh();
    setChecking(false);
  }

  // Approval sends nothing, so look again on our own: every so often, and on coming back to the
  // app. Once approved, the session's account changes and navigation leaves this screen.
  useEffect(() => {
    if (rejected) return;
    const timer = setInterval(() => void refresh(), RECHECK_MS);
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void refresh();
    });
    return () => {
      clearInterval(timer);
      subscription.remove();
    };
  }, [refresh, rejected]);

  return (
    <View
      style={[
        styles.screen,
        { backgroundColor: colors.background, paddingTop: insets.top + spacing.xxl },
      ]}
    >
      <View style={styles.body}>
        <View style={[styles.icon, { backgroundColor: colors.accentSoft }]}>
          <Ionicons
            name={rejected ? 'close-circle-outline' : 'hourglass-outline'}
            size={26}
            color={colors.accent}
          />
        </View>
        <Text variant="title">
          {rejected ? 'Your request was not approved' : 'You are on the list'}
        </Text>
        <Text color="muted">
          {rejected
            ? 'Patterns is in a small test for now. Ask the team if you think this is a mistake.'
            : 'Patterns is in testing, so each account is approved by hand. Check back soon: once you are in, you can connect your Fitbit.'}
        </Text>
        {account && (
          <Text variant="caption" color="faint">
            Signed in as {account.email}
          </Text>
        )}
        <View style={styles.actions}>
          {!rejected && (
            <Button
              label={checking ? 'Checking…' : 'Check again'}
              onPress={checkAgain}
              disabled={checking}
            />
          )}
          <Button label="Sign out" variant="secondary" onPress={logOut} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, paddingHorizontal: spacing.xl },
  body: { width: '100%', maxWidth: 420, alignSelf: 'center', gap: spacing.md },
  icon: {
    width: 52,
    height: 52,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
  },
  actions: { flexDirection: 'row', gap: spacing.xs, marginTop: spacing.md, flexWrap: 'wrap' },
});
