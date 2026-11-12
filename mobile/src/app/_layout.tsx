import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from '@expo-google-fonts/inter';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';
import { View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import { SessionProvider, useSession } from '@/lib/session';
import { fonts, ThemeProvider, useColors, useScheme } from '@/theme';

// A screen that crashes shows an error with a retry button instead of taking down the app.
export { ErrorBoundary } from 'expo-router';

export default function RootLayout() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        // Data changes at most daily: reuse it for a minute instead of refetching on every visit.
        defaultOptions: { queries: { retry: 1, staleTime: 60_000 } },
      }),
  );
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <SessionProvider>
            {/* If the font fails to load, carry on with the system font rather than a blank app. */}
            {fontsLoaded || fontError ? <Navigation /> : <Splash />}
          </SessionProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}

function Splash() {
  const colors = useColors();
  return <View style={{ flex: 1, backgroundColor: colors.background }} />;
}

function Navigation() {
  const colors = useColors();
  const scheme = useScheme();
  const { state, account } = useSession();
  // Until the stored session is read, show nothing rather than flash the landing page.
  if (state.phase === 'loading') return <Splash />;
  const approved = account?.status === 'approved';
  // Where a route that is not available in this phase leads: the phase's own first screen.
  const home = state.phase === 'signedOut' ? '/welcome' : approved ? '/' : '/waiting';
  return (
    <>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.background },
          headerShadowVisible: false,
          headerTintColor: colors.text,
          headerTitleStyle: { fontFamily: fonts.semibold },
          headerBackButtonDisplayMode: 'minimal',
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        {/* Each route exists only in its phase, so a deep link can never skip sign-in or
            approval: signed out, pending or rejected, and approved. */}
        <Stack.Protected guard={state.phase === 'signedOut'} redirectTo={home}>
          <Stack.Screen name="welcome" options={{ headerShown: false }} />
          <Stack.Screen name="sign-up" options={{ headerShown: false }} />
          <Stack.Screen name="sign-in" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={state.phase === 'signedIn' && !approved} redirectTo={home}>
          <Stack.Screen name="waiting" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={approved} redirectTo={home}>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="finding/[id]" options={{ title: '' }} />
          <Stack.Screen name="entries" options={{ title: 'Logged food and workouts' }} />
          <Stack.Screen name="metric/[metric]" options={{ title: '' }} />
          <Stack.Screen name="workout/[id]" options={{ title: '' }} />
          <Stack.Screen name="reminder/[id]" options={{ title: 'Reminder' }} />
          <Stack.Screen name="chats" options={{ title: 'Your chats' }} />
          <Stack.Screen name="team-chat" options={{ title: 'Ask about your team' }} />
          <Stack.Screen name="teams" options={{ title: 'Teams' }} />
          <Stack.Screen name="memory" options={{ title: '' }} />
          <Stack.Screen name="data" options={{ headerShown: false }} />
          <Stack.Screen
            name="evidence/[id]"
            options={{
              title: 'Evidence',
              presentation: 'formSheet',
              sheetAllowedDetents: [0.6, 1],
              sheetGrabberVisible: true,
              contentStyle: { backgroundColor: colors.background },
            }}
          />
          <Stack.Protected guard={account?.isAdmin === true} redirectTo={home}>
            <Stack.Screen name="approvals" options={{ title: 'Access requests' }} />
          </Stack.Protected>
        </Stack.Protected>
      </Stack>
    </>
  );
}
