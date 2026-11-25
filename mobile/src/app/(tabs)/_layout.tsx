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
  personal?: boolean; // part of the individual side, hidden when it is off (docs/pivot.md)
}[] = [
  { name: 'index', title: 'Today', icon: 'pulse-outline', iconActive: 'pulse' },
  { name: 'team', title: 'Team', icon: 'people-outline', iconActive: 'people', supervisors: true },
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
  const colors = useColors();
  const email = account?.email;
  // The first time an account opens the app on this device, show the guide once.
  useEffect(() => {
    if (!email) return;
    let live = true;
    void tourSeen(email).then((seen) => {
      if (live && !seen) router.push('/tour');
    });
    return () => {
      live = false;
    };
  }, [email]);
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
      {TABS.map(({ name, title, icon, iconActive, supervisors, personal: own }) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            // With the individual side off, Reminders keeps only the inbox.
            title: name === 'reminders' && !personal ? 'Inbox' : title,
            // hidden, not just disabled
            href: (supervisors && !supervisor) || (own && !personal) ? null : undefined,
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
