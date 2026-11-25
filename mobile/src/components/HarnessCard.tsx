import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { mcpUrl } from '@/api';
import {
  useAccessTokens,
  useDecideHarnessSubmission,
  useHarnessSubmissions,
  useMakeAccessToken,
  useRevokeAccessToken,
} from '@/api/hooks';
import { Row } from '@/components/list';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { timeAgo } from '@/lib/format';
import { activityText, setupCommands, submissionText } from '@/lib/harness';
import { radius, spacing, useColors } from '@/theme';

/**
 * Connecting Claude Code, Codex or another MCP harness (docs/mcp.md): the server's address, a
 * personal token shown once, and what a harness sent, held until approved here.
 */
export function HarnessCard() {
  const colors = useColors();
  const tokens = useAccessTokens();
  const make = useMakeAccessToken();
  const revoke = useRevokeAccessToken();
  const waiting = useHarnessSubmissions();
  const decide = useDecideHarnessSubmission();
  const [name, setName] = useState('');
  const [shown, setShown] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const live = (tokens.data ?? []).filter((t) => !t.revokedAt);
  const error = make.error ?? revoke.error ?? decide.error;

  return (
    <View style={styles.block}>
      <Text color="muted">
        Use Patterns from Codex, Claude Code or another MCP assistant. It sees what you see here,
        never more, and anything it sends waits for your approval below. Make one token per device
        or assistant, so each can be revoked on its own.
      </Text>
      <Row
        icon="link-outline"
        title={mcpUrl}
        detail={copied ? 'Copied' : 'The server address; tap to copy'}
        onPress={async () => {
          await Clipboard.setStringAsync(mcpUrl);
          setCopied(true);
        }}
      />
      {shown ? (
        <View style={[styles.token, { borderColor: colors.border }]}>
          <Text variant="bodyStrong">Connect on this device</Text>
          <Text variant="caption" color="muted">
            Your token is in these commands and is shown only now. Run the one for your assistant in
            a terminal.
          </Text>
          <Command label="Codex: add Patterns once" text={setupCommands(mcpUrl, shown).codexAdd} />
          <Command
            label="Codex: the token, in your shell profile (e.g. ~/.zshrc)"
            text={setupCommands(mcpUrl, shown).codexToken}
          />
          <Command label="Claude Code" text={setupCommands(mcpUrl, shown).claudeCode} />
          <Button label="Done" variant="secondary" onPress={() => setShown(null)} />
        </View>
      ) : (
        <View style={styles.field}>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="Name, e.g. Codex on my laptop"
            placeholderTextColor={colors.faint}
            maxLength={60}
            accessibilityLabel="Token name"
            style={[
              styles.input,
              { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
            ]}
          />
          <Button
            label="Make a token"
            disabled={!name.trim() || make.isPending}
            onPress={() =>
              make.mutate(name.trim(), {
                onSuccess: (made) => {
                  setShown(made.token);
                  setName('');
                },
              })
            }
          />
        </View>
      )}
      {live.map((t) => (
        <Row
          key={t.id}
          icon="key-outline"
          title={t.name}
          detail={
            t.lastUsedAt
              ? [`Last used ${timeAgo(t.lastUsedAt)}`, activityText(t.activity)]
                  .filter(Boolean)
                  .join(' · ')
              : 'Not used yet'
          }
          accessory={
            <Button label="Revoke" variant="secondary" onPress={() => revoke.mutate(t.id)} />
          }
        />
      ))}
      {(waiting.data ?? []).map((item) => (
        <View key={item.id} style={[styles.token, { borderColor: colors.border }]}>
          <Text variant="bodyStrong">From your harness: {submissionText(item)}</Text>
          <Text variant="caption" color="muted">
            Sent {timeAgo(item.createdAt)}. Nothing changes until you approve it.
          </Text>
          <View style={styles.buttons}>
            <Button
              label="Approve"
              disabled={decide.isPending}
              onPress={() => decide.mutate({ id: item.id, approve: true })}
            />
            <Button
              label="Decline"
              variant="secondary"
              disabled={decide.isPending}
              onPress={() => decide.mutate({ id: item.id, approve: false })}
            />
          </View>
        </View>
      ))}
      {error ? <Text color="danger">{error.message}</Text> : null}
    </View>
  );
}

/** One command, selectable, with its own copy button. */
function Command({ label, text }: { label: string; text: string }) {
  const colors = useColors();
  const [copied, setCopied] = useState(false);
  return (
    <View style={{ gap: spacing.xs }}>
      <Text variant="caption" color="muted">
        {label}
      </Text>
      <Text selectable style={[styles.mono, styles.command, { backgroundColor: colors.surface }]}>
        {text}
      </Text>
      <Button
        label={copied ? 'Copied' : 'Copy'}
        variant="secondary"
        onPress={async () => {
          await Clipboard.setStringAsync(text);
          setCopied(true);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  command: { padding: spacing.sm, borderRadius: radius.sm },
  block: { gap: spacing.sm, paddingVertical: spacing.md },
  field: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  input: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  token: { gap: spacing.sm, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  mono: { fontFamily: 'Courier', fontSize: 13 },
  buttons: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
});
