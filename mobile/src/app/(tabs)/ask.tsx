import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { BottomTabBarHeightContext } from 'expo-router/js-tabs';
import { useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  type ScrollViewInstance,
} from 'react-native';
import Animated, { FadeIn, FadeOut, LinearTransition } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  type ChatTarget,
  useChat,
  useConversations,
  useDay,
  useNoData,
  useRateAnswer,
  useReport,
  useSendMessage,
} from '@/api/hooks';
import type { Attachment, Depth, ExpertChoice, Finding } from '@/api/types';
import { type Anchor, AttachSheet } from '@/components/attach';
import { MessageBubble, Thinking } from '@/components/chat';
import { MemoryPrompts } from '@/components/MemoryPrompt';
import { Composer } from '@/components/composer';
import { ConversationList, IconButton } from '@/components/conversations';
import { NoData } from '@/components/NoData';
import { QueryState } from '@/components/Screen';
import { Text } from '@/components/Text';
import { Chip } from '@/components/ui';
import { expertInfo, useExpertColor } from '@/lib/experts';
import { metricLabel } from '@/lib/format';
import { DURATION, EASE_OUT } from '@/lib/motion';
import { useWide } from '@/lib/layout';
import { floatingTabBar } from '@/lib/platform';
import { column, radius, spacing, useColors } from '@/theme';

const MAX_LENGTH = 500;
// On wide screens the conversation is a quarter wider than other pages' column, beside the list.
const WIDE_CHAT = 900;
const SIDEBAR = 272;
const RAIL = 56; // the hidden sidebar's width: room for its two buttons
const SIDEBAR_KEY = 'patterns.chatsOpen';

// Remembered in the browser only, like the theme; phones show the chats as a page instead.
function storedSidebar(): boolean {
  try {
    return globalThis.localStorage?.getItem(SIDEBAR_KEY) !== 'closed';
  } catch {
    return true;
  }
}

function storeSidebar(open: boolean) {
  try {
    globalThis.localStorage?.setItem(SIDEBAR_KEY, open ? 'open' : 'closed');
  } catch {
    // Blocked storage: the choice lasts until reload.
  }
}

// The composer moves from the middle of the empty page down to the bottom of the conversation.
const MOVE = LinearTransition.duration(DURATION.normal).easing(EASE_OUT);

// Questions offered while a finding is attached.
const FINDING_SUGGESTIONS = ['Why did this happen?', 'What else changed around then?'];

function attachmentLabel(attachment: Attachment | undefined, findings: Finding[]): string | undefined {
  if (!attachment) return undefined;
  if (attachment.kind === 'metric') return metricLabel(attachment.metric);
  return findings.find((f) => f.id === attachment.id)?.title ?? 'A finding';
}

export default function AskScreen() {
  const colors = useColors();
  const { findingId, metric, c, q } = useLocalSearchParams<{
    findingId?: string;
    metric?: string;
    c?: string; // a conversation to open, e.g. from the chats page
    q?: string; // a question to start from, e.g. from a workout page
  }>();
  const wide = useWide();
  const [sidebarOpen, setSidebarOpen] = useState(storedSidebar);
  const toggleSidebar = (open: boolean) => {
    setSidebarOpen(open);
    storeSidebar(open);
  };
  const [target, setTarget] = useState<ChatTarget>('latest');
  const [seenChat, setSeenChat] = useState<string>();
  if (c !== seenChat) {
    setSeenChat(c);
    if (c) setTarget(c);
  }
  useEffect(() => {
    if (c) router.setParams({ c: undefined });
  }, [c]);
  const chat = useChat(target);
  const conversations = useConversations();
  // The open conversation: the one asked for, or the latest when none was.
  const openId =
    target === 'latest' ? conversations.data?.[0]?.id : target === 'new' ? undefined : target;
  const openTitle =
    target === 'new' ? 'New chat' : conversations.data?.find((x) => x.id === openId)?.title;
  const report = useReport();
  const send = useSendMessage();
  const rate = useRateAnswer();
  const [draft, setDraft] = useState('');
  // A suggested question fills the composer; the person reads it and sends it.
  const [seenQuestion, setSeenQuestion] = useState<string>();
  if (q !== seenQuestion) {
    setSeenQuestion(q);
    if (q) setDraft(q);
  }
  useEffect(() => {
    if (q) router.setParams({ q: undefined });
  }, [q]);
  const [expert, setExpert] = useState<ExpertChoice>('auto');
  const [depth, setDepth] = useState<Depth>('quick');
  const [attachment, setAttachment] = useState<Attachment>();
  const [attaching, setAttaching] = useState(false);
  const [anchor, setAnchor] = useState<Anchor>();
  // Only metrics the person has data for can be attached.
  const latest = useDay('latest');
  const available = latest.data?.metrics
    .filter((m) => m.value !== null || m.usual !== null)
    .map((m) => m.metric);
  const scroll = useRef<ScrollViewInstance>(null);
  const insets = useSafeAreaInsets();
  const barHeight = useContext(BottomTabBarHeightContext) ?? 0;
  const tabBarHeight = floatingTabBar ? barHeight : 0;
  const keyboardOpen = useKeyboardOpen();

  // "Ask about this" on a finding opens this tab with the finding attached. The parameter is then
  // cleared, so asking about the same finding again attaches it again.
  // A metric page's "Ask about" works the same way with the metric.
  const [seenFindingId, setSeenFindingId] = useState<string>();
  if (findingId !== seenFindingId) {
    setSeenFindingId(findingId);
    if (findingId) setAttachment({ kind: 'finding', id: findingId });
  }
  const [seenMetric, setSeenMetric] = useState<string>();
  if (metric !== seenMetric) {
    setSeenMetric(metric);
    if (metric) setAttachment({ kind: 'metric', metric });
  }
  useEffect(() => {
    if (findingId) router.setParams({ findingId: undefined });
  }, [findingId]);
  useEffect(() => {
    if (metric) router.setParams({ metric: undefined });
  }, [metric]);

  // Once a slow answer shows up in the chat, its "taking longer" message has done its job.
  const lastRole = chat.data?.at(-1)?.role;
  const { reset: resetSend } = send;
  const slow = (send.error as { code?: string } | null)?.code === 'still_answering';
  useEffect(() => {
    if (slow && lastRole === 'assistant') resetSend();
  }, [slow, lastRole, resetSend]);

  const findings = useMemo(() => report.data?.findings ?? [], [report.data]);
  const findingTitles = useMemo(
    () => Object.fromEntries(findings.map((f) => [f.id, f.title])),
    [findings],
  );
  // While an edited or retried question is on its way, what it replaces is already gone.
  const replacing = send.isPending ? send.variables?.options.replaces : undefined;
  const all = chat.data ?? [];
  const cut = replacing ? all.findIndex((m) => m.id === replacing) : -1;
  const messages = cut >= 0 ? all.slice(0, cut) : all;
  const pendingText = send.isPending ? send.variables?.text : undefined;
  const pendingExpert = send.variables?.options.expert ?? expert;
  const started = messages.length > 0 || pendingText !== undefined;
  // Without data there is nothing to ask about yet: the page says how to connect instead.
  const noData = useNoData() === true && !started;
  const sendError = send.error && (
    <Text variant="caption" color="danger" style={{ textAlign: 'center' }}>
      {send.error.message || 'Could not send your message.'}
      {/* A slow answer is still coming; other errors can be retried. */}
      {slow ? '' : ' Try again.'}
    </Text>
  );

  useEffect(() => {
    scroll.current?.scrollToEnd({ animated: true });
  }, [messages.length, send.isPending]);

  function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || send.isPending) return;
    send.mutate(
      { text: trimmed, options: { expert, depth, ...(attachment && { attachment }) }, target },
      {
        // Keep the text if sending fails, so it can be retried.
        onSuccess: (added) => {
          setDraft('');
          setAttachment(undefined);
          // A new chat now exists: keep showing it by its id.
          const id = added[0]?.conversationId;
          if (id && target !== id) setTarget(id);
        },
      },
    );
  }

  /** Sends `text` in place of the question `replaces`: an edit, or a retry of the same text. */
  function resend(text: string, replaces: string) {
    if (send.isPending) return;
    send.mutate(
      { text, options: { expert, depth, replaces }, target },
      {
        onSuccess: (added) => {
          const id = added[0]?.conversationId;
          if (id && target !== id) setTarget(id);
        },
      },
    );
  }

  function openChat(next: ChatTarget) {
    send.reset();
    setDraft('');
    setAttachment(undefined);
    setTarget(next);
  }

  const width = wide ? { maxWidth: WIDE_CHAT } : null;

  const suggestions =
    attachment?.kind === 'finding'
      ? FINDING_SUGGESTIONS
      : expertInfo(expert).suggestions;

  const conversation = (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.header, width, { paddingTop: insets.top + spacing.md }]}>
        <Text
          variant={started ? 'headline' : 'display'}
          accessibilityRole="header"
          numberOfLines={1}
          style={{ flex: 1 }}
        >
          {started && openTitle ? openTitle : 'Ask'}
        </Text>
        {/* On phones the list of chats is a page of its own; wide screens show it beside. */}
        {!wide && (
          <View style={styles.headerActions}>
            <HeaderButton
              icon="albums-outline"
              label="Your chats"
              onPress={() => router.push('/chats')}
            />
            <HeaderButton icon="create-outline" label="New chat" onPress={() => openChat('new')} />
          </View>
        )}
      </View>

      <QueryState query={chat}>
        {() =>
          started ? (
            <ScrollView
              ref={scroll}
              style={{ flex: 1 }}
              contentContainerStyle={[styles.messages, width]}
              keyboardShouldPersistTaps="handled"
            >
              {messages.map((message, index) => {
                // An answer is retried by asking its question again, in place.
                const question =
                  message.role === 'assistant' && messages[index - 1]?.role === 'user'
                    ? messages[index - 1]
                    : undefined;
                return (
                  <MessageBubble
                    key={message.id}
                    message={message}
                    knownEvidence={report.data?.evidence ?? {}}
                    findingTitles={findingTitles}
                    busy={send.isPending}
                    onEdit={
                      message.role === 'user' ? (text) => resend(text, message.id) : undefined
                    }
                    onRetry={question ? () => resend(question.text, question.id) : undefined}
                    onRate={
                      message.role === 'assistant'
                        ? (rating) => rate.mutate({ id: message.id, rating })
                        : undefined
                    }
                  />
                );
              })}
              {pendingText === undefined && <MemoryPrompts />}
              {pendingText !== undefined && (
                <>
                  <View
                    style={[
                      styles.pendingMine,
                      { backgroundColor: colors.surfaceRaised, borderColor: colors.border },
                    ]}
                  >
                    <Text>{pendingText}</Text>
                  </View>
                  <Thinking expert={pendingExpert} />
                </>
              )}
              {sendError}
            </ScrollView>
          ) : noData ? (
            <ScrollView contentContainerStyle={[styles.noData, width]}>
              <NoData shows="Ask answers questions about your sleep, recovery and activity" />
            </ScrollView>
          ) : (
            <Animated.View exiting={FadeOut.duration(150)} style={[styles.greeting, width]}>
              <Greeting expert={expert} />
              {/* The first question's error, e.g. no data yet, shows before any conversation. */}
              {sendError}
            </Animated.View>
          )
        }
      </QueryState>

      {started && attachment?.kind === 'finding' && (
        <ScrollView
          horizontal
          style={[styles.quickRail, width]}
          showsHorizontalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={styles.quickReplies}
        >
          {FINDING_SUGGESTIONS.map((text) => (
            <Chip key={text} label={text} disabled={send.isPending} onPress={() => submit(text)} />
          ))}
        </ScrollView>
      )}

      {!noData && (
        <Animated.View
          layout={MOVE}
          style={[
            styles.composer,
            width,
            // Above the floating tab bar, except while the keyboard covers it.
            { paddingBottom: started ? (keyboardOpen ? 0 : tabBarHeight) + spacing.sm : spacing.md },
          ]}
        >
          <Composer
            value={draft}
            onChangeText={setDraft}
            onSubmit={() => submit(draft)}
            expert={expert}
            onExpertChange={setExpert}
            depth={depth}
            onDepthChange={setDepth}
            attachmentLabel={attachmentLabel(attachment, findings)}
            onAttach={(at) => {
              setAnchor(at);
              setAttaching(true);
            }}
            onClearAttachment={() => setAttachment(undefined)}
            busy={send.isPending}
            collapsible={!started}
            placeholder={started ? 'Ask a follow-up' : 'Ask about your sleep, recovery, activity…'}
            maxLength={MAX_LENGTH}
          />
        </Animated.View>
      )}

      {!started && !noData && (
        <Animated.View exiting={FadeOut.duration(150)} style={[styles.below, width]}>
          <View style={styles.suggestions}>
            {suggestions.map((text, i) => (
              <Animated.View key={`${expert}-${text}`} entering={FadeIn.delay(i * 40).duration(DURATION.fast)}>
                <Chip label={text} onPress={() => submit(text)} />
              </Animated.View>
            ))}
          </View>
        </Animated.View>
      )}

      <AttachSheet
        visible={attaching}
        findings={findings}
        available={available}
        anchor={anchor}
        onClose={() => setAttaching(false)}
        onPick={(picked) => {
          setAttachment(picked);
          setAttaching(false);
        }}
      />
    </KeyboardAvoidingView>
  );

  if (!wide) return conversation;
  return (
    <View style={[styles.split, { backgroundColor: colors.background }]}>
      {sidebarOpen ? (
        <View
          style={[
            styles.sidebar,
            { borderColor: colors.border, paddingTop: insets.top + spacing.lg },
          ]}
        >
          <ConversationList
            current={openId}
            newOpen={target === 'new'}
            onSelect={(id) => openChat(id)}
            onNew={() => openChat('new')}
            onCollapse={() => toggleSidebar(false)}
          />
        </View>
      ) : (
        <View
          style={[styles.rail, { borderColor: colors.border, paddingTop: insets.top + spacing.lg }]}
        >
          <IconButton
            icon="chevron-forward"
            label="Show your chats"
            onPress={() => toggleSidebar(true)}
          />
          <IconButton icon="create-outline" label="New chat" onPress={() => openChat('new')} />
        </View>
      )}
      {conversation}
    </View>
  );
}

function HeaderButton({
  icon,
  label,
  onPress,
}: {
  icon: 'albums-outline' | 'create-outline';
  label: string;
  onPress: () => void;
}) {
  const colors = useColors();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={6}
      style={({ pressed }) => [styles.headerButton, pressed && { backgroundColor: colors.track }]}
    >
      <Ionicons name={icon} size={20} color={colors.text} />
    </Pressable>
  );
}

/** The empty page: the selected expert's icon, a question, and what the answers are based on. */
function Greeting({ expert }: { expert: ExpertChoice }) {
  const color = useExpertColor(expert);
  const info = expertInfo(expert);
  return (
    <>
      <Animated.View
        key={expert}
        entering={FadeIn.duration(250)}
        style={[styles.greetingIcon, { backgroundColor: `${color}22`, borderColor: `${color}44` }]}
      >
        <Ionicons name={info.icon} size={24} color={color} />
      </Animated.View>
      <Text variant="title" style={{ textAlign: 'center' }}>
        {expert === 'auto' ? 'What do you want to know?' : `Ask the ${info.label} expert`}
      </Text>
      <Text color="muted" style={styles.disclaimer}>
        Answers come from your own Fitbit data and show what they are based on. Patterns, not
        medical advice.
      </Text>
    </>
  );
}

function useKeyboardOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const shown = Keyboard.addListener('keyboardWillShow', () => setOpen(true));
    const hidden = Keyboard.addListener('keyboardWillHide', () => setOpen(false));
    const shownAndroid = Keyboard.addListener('keyboardDidShow', () => setOpen(true));
    const hiddenAndroid = Keyboard.addListener('keyboardDidHide', () => setOpen(false));
    return () => [shown, hidden, shownAndroid, hiddenAndroid].forEach((s) => s.remove());
  }, []);
  return open;
}

const styles = StyleSheet.create({
  header: {
    ...column,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  headerActions: { flexDirection: 'row', gap: spacing.xs },
  headerButton: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  split: { flex: 1, flexDirection: 'row' },
  rail: {
    width: RAIL,
    alignItems: 'center',
    gap: spacing.sm,
    borderRightWidth: StyleSheet.hairlineWidth,
  },
  sidebar: {
    width: SIDEBAR,
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.lg,
    borderRightWidth: StyleSheet.hairlineWidth,
  },
  greeting: {
    ...column,
    flex: 1,
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.xl,
  },
  greetingIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
  },
  disclaimer: { textAlign: 'center', maxWidth: 340 },
  noData: { ...column, paddingHorizontal: spacing.lg, paddingBottom: 120 },
  below: { ...column, flex: 1, paddingHorizontal: spacing.lg },
  suggestions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  messages: { ...column, padding: spacing.lg, gap: spacing.lg, flexGrow: 1 },
  pendingMine: {
    alignSelf: 'flex-end',
    maxWidth: '82%',
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.lg,
    borderBottomRightRadius: 6,
    borderWidth: StyleSheet.hairlineWidth,
    opacity: 0.6,
  },
  quickRail: { ...column, flexGrow: 0 },
  quickReplies: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  composer: { ...column, paddingHorizontal: spacing.md, paddingTop: spacing.sm },
});
