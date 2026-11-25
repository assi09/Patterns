import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';
import {
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  useWindowDimensions,
  View,
  type TextInputProps,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ApiError } from '@/api/http';
import { PressableScale } from '@/components/PressableScale';
import { Text } from '@/components/Text';
import { useSession } from '@/lib/session';
import { fonts, radius, spacing, useColors } from '@/theme';

type Mode = 'signUp' | 'logIn';

const COPY = {
  signUp: {
    title: 'Create your account',
    switchPrompt: 'Already have an account?',
    switchLabel: 'Sign in',
    switchTo: '/sign-in',
    submit: 'Create account',
  },
  logIn: {
    title: 'Welcome back',
    switchPrompt: "Don't have an account?",
    switchLabel: 'Sign up',
    switchTo: '/sign-up',
    submit: 'Sign in',
  },
} as const;

// A near-square portrait with the face above the middle: a centered crop suits both the tall
// side panel and the short phone banner.
const PHOTO = require('../../assets/landing/auth.jpg');

const WIDE = 768; // side by side from here; a photo banner above the form below it

/** Sign in and sign up: a photo beside (or above) a plain email and password form. */
export function AuthForm({ mode }: { mode: Mode }) {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const wide = width >= WIDE;
  const session = useSession();
  const copy = COPY[mode];
  const signingUp = mode === 'signUp';
  // An HR invitation link: /sign-up?hr=<token> (docs/escalation.md).
  const { hr } = useLocalSearchParams<{ hr?: string }>();
  const hrInvite = signingUp && typeof hr === 'string' && hr ? hr : undefined;

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    email.trim().length > 0 && password.length > 0 && (!signingUp || confirm.length > 0) && !busy;

  async function submit() {
    if (!canSubmit) return;
    if (signingUp && confirm !== password) {
      setError('The two passwords do not match.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const credentials = { email: email.trim(), password, ...(hrInvite && { hrInvite }) };
      await (signingUp ? session.signUp(credentials) : session.logIn(credentials));
      // The routes switch on the session, so there is nowhere to navigate to here.
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Something went wrong. Try again.');
      setBusy(false);
    }
  }

  const inputStyle = [
    styles.input,
    { backgroundColor: colors.surface, borderColor: colors.border, color: colors.text },
  ];
  const shared: TextInputProps = {
    autoCapitalize: 'none',
    autoCorrect: false,
    placeholderTextColor: colors.faint,
    editable: !busy,
    style: inputStyle,
  };
  const eye = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={showPassword ? 'Hide password' : 'Show password'}
      onPress={() => setShowPassword((shown) => !shown)}
      hitSlop={8}
      style={styles.eye}
    >
      <Ionicons
        name={showPassword ? 'eye-off-outline' : 'eye-outline'}
        size={18}
        color={colors.muted}
      />
    </Pressable>
  );

  const photo = (
    <View
      style={
        wide
          ? styles.photoWide
          : [styles.photoBanner, { height: Math.min(height * 0.36, width * 0.9) }]
      }
    >
      <Image source={PHOTO} resizeMode="cover" style={styles.photo} />
      <View style={[StyleSheet.absoluteFill, styles.photoShade]} />
      <View style={[styles.backWrap, { top: insets.top + spacing.md }]}>
        <PressableScale
          accessibilityRole="button"
          accessibilityLabel="Back"
          onPress={() => (router.canGoBack() ? router.back() : router.replace('/welcome'))}
          style={styles.back}
        >
          <Ionicons name="arrow-back" size={20} color="#FFFFFF" />
        </PressableScale>
      </View>
    </View>
  );

  const form = (
    <View style={styles.form}>
      <View style={styles.heading}>
        <Text variant="display" style={styles.title}>
          {copy.title}
        </Text>
        {hrInvite ? (
          <Text color="muted">
            You were invited as a team&apos;s HR contact. Sign up with the address the invitation was
            sent to; your account is ready at once.
          </Text>
        ) : null}
        <View style={styles.switchRow}>
          <Text color="muted">{copy.switchPrompt} </Text>
          <Pressable accessibilityRole="link" onPress={() => router.replace(copy.switchTo)}>
            <Text color="accent" style={{ fontFamily: fonts.semibold }}>
              {copy.switchLabel}
            </Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.field}>
        <Text variant="caption" color="muted">
          Email address
        </Text>
        <TextInput
          {...shared}
          value={email}
          onChangeText={setEmail}
          placeholder="you@example.com"
          keyboardType="email-address"
          autoComplete="email"
          textContentType="emailAddress"
          returnKeyType="next"
          accessibilityLabel="Email"
        />
      </View>

      <View style={styles.field}>
        <Text variant="caption" color="muted">
          Password
        </Text>
        <View>
          <TextInput
            {...shared}
            value={password}
            onChangeText={setPassword}
            placeholder={signingUp ? 'At least 10 characters' : 'Password'}
            secureTextEntry={!showPassword}
            autoComplete={signingUp ? 'new-password' : 'current-password'}
            textContentType={signingUp ? 'newPassword' : 'password'}
            returnKeyType={signingUp ? 'next' : 'go'}
            onSubmitEditing={signingUp ? undefined : submit}
            accessibilityLabel="Password"
            style={[inputStyle, styles.passwordInput]}
          />
          {eye}
        </View>
      </View>

      {signingUp && (
        <View style={styles.field}>
          <Text variant="caption" color="muted">
            Confirm password
          </Text>
          <TextInput
            {...shared}
            value={confirm}
            onChangeText={setConfirm}
            placeholder="Type it again"
            secureTextEntry={!showPassword}
            autoComplete="new-password"
            textContentType="newPassword"
            returnKeyType="go"
            onSubmitEditing={submit}
            accessibilityLabel="Confirm password"
          />
        </View>
      )}

      {error && (
        <View
          accessibilityRole="alert"
          style={[styles.error, { backgroundColor: colors.accentSoft }]}
        >
          <Ionicons name="alert-circle-outline" size={16} color={colors.danger} />
          <Text variant="caption" style={{ flex: 1, color: colors.danger }}>
            {error}
          </Text>
        </View>
      )}

      <PressableScale
        accessibilityRole="button"
        accessibilityState={{ disabled: !canSubmit }}
        onPress={submit}
        disabled={!canSubmit}
        style={[styles.submit, { backgroundColor: colors.text }]}
      >
        <Text variant="bodyStrong" color="background">
          {busy ? 'One moment…' : copy.submit}
        </Text>
      </PressableScale>

      {signingUp && (
        <Text variant="caption" color="faint" style={styles.note}>
          Patterns is in testing, so each new account is approved by hand. You can connect your
          Fitbit once you are in.
        </Text>
      )}
    </View>
  );

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={[styles.screen, wide && styles.row]}
      >
        {wide && photo}
        <ScrollView
          style={styles.screen}
          contentContainerStyle={[
            styles.scroll,
            wide && styles.scrollWide,
            { paddingBottom: insets.bottom + spacing.xxl },
          ]}
          keyboardShouldPersistTaps="handled"
        >
          {!wide && photo}
          <View style={[styles.formWrap, wide && { paddingTop: insets.top }]}>{form}</View>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  row: { flexDirection: 'row' },
  photoWide: { flex: 1, overflow: 'hidden' },
  photoBanner: { width: '100%', overflow: 'hidden' },
  // An explicit size: on the web an image placed only by its edges takes the file's pixel size.
  photo: { position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' },
  photoShade: { backgroundColor: 'rgba(0,0,0,0.15)' },
  backWrap: { position: 'absolute', left: spacing.lg },
  back: {
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(0,0,0,0.3)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scroll: { flexGrow: 1 },
  scrollWide: { justifyContent: 'center' },
  formWrap: { paddingHorizontal: spacing.xl, paddingTop: spacing.xl },
  form: { width: '100%', maxWidth: 400, alignSelf: 'center', gap: spacing.lg },
  heading: { gap: spacing.sm, marginBottom: spacing.sm },
  title: { fontSize: 30, lineHeight: 36 },
  switchRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' },
  field: { gap: 6 },
  input: {
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 16,
    paddingVertical: 13,
    fontFamily: fonts.regular,
    fontSize: 15,
  },
  passwordInput: { paddingRight: 48 },
  eye: { position: 'absolute', right: 14, top: 0, bottom: 0, justifyContent: 'center' },
  error: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
  },
  submit: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 13,
    borderRadius: radius.md,
    marginTop: spacing.xs,
  },
  note: { textAlign: 'center' },
});
