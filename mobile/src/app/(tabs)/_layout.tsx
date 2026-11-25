import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import { router, Tabs } from 'expo-router';
import { type ComponentProps, useEffect } from 'react';
import { StyleSheet, useWindowDimensions } from 'react-native';

import { useAutoSync, useNotifications, useSyncTimezone } from '@/api/hooks';
import { usePersonal } from '@/lib/features';
import { select } from '@/lib/haptics';
import { useSession } from '@/lib/session';
import { tourSeen } from '@/lib/tour';
import { floatingTabBar as glass } from '@/lib/platform';
import { CONTENT_WIDTH, fonts, useColors, useScheme } from '@/theme';

type IconName = ComponentProps<typeof Ionicons>['name'];

const TABS: {
  name: string;
  title: string;
  icon: IconName;
  iconActive: IconName;
  supervisors?: boolean; // shown only to supervisors
  recipients?: boolean; // shown only to HR and supervisors: check-in alerts (docs/escalation.md)
  personal?: boolean; // part of the individual side, hidden when it is off (docs/pivot.md)
  notHr?: boolean; // hidden from HR accounts, which see check-in alerts only
}[] = [
  { name: 'index', title: 'Today', icon: 'pulse-outline', iconActive: 'pulse', notHr: true },
  { name: 'team', title: 'Team', icon: 'people-outline', iconActive: 'people', supervisors: true },
  {
    name: 'checkins',
    title: 'Check-ins',
    icon: 'hand-left-outline',
    iconActive: 'hand-left',
    recipients: true,
  },
  {
    name: 'ask',
    title: 'Ask',
    icon: 'chatbubble-outline',
    iconActive: 'chatbubble',
    personal: true,
  },
  {
    name: 'reminders',
    title: 'Reminders',
    icon: 'notifications-outline',
    iconActive: 'notifications',
  },
  { name: 'settings', title: 'Settings', icon: 'settings-outline', iconActive: 'settings' },
];

export default function TabLayout() {
  const { account } = useSession();
  useAutoSync(); // signed in from here on: keep the data fresh without a button
  useSyncTimezone();
  const unread = useNotifications().data?.unread ?? 0;
  const supervisor = account?.role === 'supervisor';
  const personal = usePersonal();
  const hr = account?.role === 'hr';
  const recipient = supervisor || hr;
  // HR opens on Check-ins: Today is someone's own data, which an HR account does not have.
  useEffect(() => {
    if (hr) router.replace('/checkins');
  }, [hr]);
  const colors = useColors();
  const email = account?.email;
  // The first time an account opens the app on this device, show the guide once. Not for HR: the
  // guide is about one's own Fitbit data, and an HR account has none here.
  useEffect(() => {
    if (!email || hr) return;
    let live = true;
    void tourSeen(email).then((seen) => {
      if (live && !seen) router.push('/tour');
    });
    return () => {
      live = false;
    };
  }, [email, hr]);
  const scheme = useScheme();
  // On wide screens keep the tabs within the content column instead of spread edge to edge.
  const { width } = useWindowDimensions();
  const inset = Math.max(0, (width - CONTENT_WIDTH) / 2);
  return (
    <Tabs
      screenListeners={{ tabPress: () => select() }}
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.text,
        tabBarInactiveTintColor: colors.faint,
        tabBarLabelStyle: { fontFamily: fonts.medium, fontSize: 11, lineHeight: 15, flexShrink: 0 },
        tabBarStyle: {
          backgroundColor: glass ? 'transparent' : colors.surface,
          borderTopColor: colors.border,
          borderTopWidth: StyleSheet.hairlineWidth,
          paddingHorizontal: inset,
          // iOS adds the home-indicator inset below the bar; elsewhere give the labels room.
          ...(glass ? { position: 'absolute' } : { height: 62, paddingTop: 6, paddingBottom: 8 }),
        },
        tabBarBackground: glass
          ? () => (
              <BlurView
                tint={scheme === 'dark' ? 'systemChromeMaterialDark' : 'systemChromeMaterialLight'}
                intensity={90}
                style={StyleSheet.absoluteFill}
              />
            )
          : undefined,
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      {TABS.map(({ name, title, icon, iconActive, supervisors, recipients, personal: own, notHr }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            // With the individual side off, Reminders keeps only the inbox.
            title: name === 'reminders' && !personal ? 'Inbox' : title,
            // hidden, not just disabled
            href:
              (supervisors && !supervisor) || (recipients && !recipient) || (own && !personal) ||
              (notHr && hr)
                ? null
                : undefined,
            // Unread notifications show on Reminders, where the inbox is.
            tabBarBadge: name === 'reminders' && unread > 0 ? Math.min(unread, 9) : undefined,
            tabBarBadgeStyle: { backgroundColor: colors.accent, fontSize: 10 },
            tabBarIcon: ({ focused, size }) => (
              <Ionicons
                name={focused ? iconActive : icon}
                size={size - 2}
                color={focused ? colors.text : colors.faint}
              />
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
