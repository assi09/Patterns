import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Linking, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useConnectRequest, useDecideConnectRequest } from '@/api/hooks';
import { AuthForm } from '@/components/AuthForm';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { connectAbilities } from '@/lib/harness';
import { useSession } from '@/lib/session';
import { radius, spacing, useColors } from '@/theme';

/**
 * Where an assistant's OAuth sign-in lands (docs/mcp.md): /connect?request=<id>. Open in every
 * phase, so a signed-out person signs in here and then sees the question, without losing it.
 */
export default function Connect() {
  const { state, account } = useSession();
  if (state.phase === 'loading') return null;
  if (state.phase === 'signedOut') return <AuthForm mode="logIn" />;
  if (account?.status !== 'approved') {
    return (
      <Frame>
        <Text variant="title">Not yet</Text>
        <Text color="muted">
          Your account is waiting for approval. Once it is approved, start the connection again
          from your assistant.
        </Text>
      </Frame>
    );
  }
  return <Question role={account.role} />;
}

function Question({ role }: { role: 'member' | 'supervisor' | 'hr' }) {
  const colors = useColors();
  const { request } = useLocalSearchParams<{ request?: string }>();
  const id = typeof request === 'string' && request ? request : undefined;
  const asked = useConnectRequest(id);
  const decide = useDecideConnectRequest();
  const [answered, setAnswered] = useState<'allowed' | 'denied' | null>(null);
  const abilities = connectAbilities(role);

  if (!id) {
    return (
      <Frame>
        <Text variant="title">Nothing to connect</Text>
        <Text color="muted">Start the connection from your assistant; it opens this page.</Text>
      </Frame>
    );
  }
  if (asked.isPending) return <Frame />;
  if (asked.error) {
    return (
      <Frame>
        <Text variant="title">This link no longer works</Text>
        <Text color="muted">{asked.error.message}</Text>
      </Frame>
    );
  }
  const { clientName, redirectHost } = asked.data;
  if (answered) {
    return (
      <Frame>
        <Text variant="title">{answered === 'allowed' ? 'Connected' : 'Not connected'}</Text>
        <Text color="muted">
          {answered === 'allowed'
            ? `You can go back to ${clientName}. It appears under Settings, where you can revoke it.`
            : `${clientName} was told no. You can close this page.`}
        </Text>
      </Frame>
    );
  }

  async function answer(allow: boolean) {
    if (!id) return;
    const { redirectTo } = await decide.mutateAsync({ id, allow });
    setAnswered(allow ? 'allowed' : 'denied');
    // Back to the assistant, which finishes the sign-in on its side.
    if (Platform.OS === 'web') window.location.assign(redirectTo);
    else await Linking.openURL(redirectTo);
  }

  return (
    <Frame>
      <Ionicons name="link-outline" size={28} color={colors.accent} />
      <Text variant="title">Connect {clientName} to Patterns?</Text>
      {abilities ? (
        <>
          <Text color="muted">It will see what you see in the app, never more. It can:</Text>
          {abilities.map((line) => (
            <View key={line} style={styles.line}>
              <Ionicons name="checkmark" size={16} color={colors.muted} />
              <Text style={styles.lineText}>{line}</Text>
            </View>
          ))}
          <View style={styles.line}>
            <Ionicons name="close" size={16} color={colors.muted} />
            <Text style={styles.lineText}>
              Never read another person&apos;s data or any check-in alert
            </Text>
          </View>
          <View style={[styles.note, { borderColor: colors.border }]}>
            <Text variant="caption" color="muted">
              Your answer goes back to {redirectHost || 'the assistant'}. Allow it only if you just
              started this from {clientName}.
            </Text>
          </View>
          <View style={styles.buttons}>
            <Button label="Allow" disabled={decide.isPending} onPress={() => void answer(true)} />
            <Button
              label="Deny"
              variant="secondary"
              disabled={decide.isPending}
              onPress={() => void answer(false)}
            />
          </View>
        </>
      ) : (
        <>
          <Text color="muted">
            HR contacts cannot connect an assistant: there is nothing in Patterns it could use.
          </Text>
          <Button
            label="Tell it no"
            variant="secondary"
            disabled={decide.isPending}
            onPress={() => void answer(false)}
          />
        </>
      )}
      {decide.error ? <Text color="danger">{decide.error.message}</Text> : null}
    </Frame>
  );
}

function Frame({ children }: { children?: React.ReactNode }) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentContainerStyle={[styles.frame, { paddingTop: insets.top + spacing.xl }]}
    >
      <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        {children}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  frame: { flexGrow: 1, alignItems: 'center', padding: spacing.md },
  card: {
    width: '100%',
    maxWidth: 480,
    gap: spacing.md,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  line: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start' },
  lineText: { flex: 1 },
  note: { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm },
  buttons: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
});
