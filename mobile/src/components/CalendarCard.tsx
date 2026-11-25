import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Linking, Platform, StyleSheet, View } from 'react-native';

import { api } from '@/api';
import { keys, useCalendarStatus } from '@/api/hooks';
import { ApiError } from '@/api/http';
import { Row } from '@/components/list';
import { Text } from '@/components/Text';
import { Button } from '@/components/ui';
import { timeAgo } from '@/lib/format';
import { spacing } from '@/theme';

/**
 * Connecting Google Calendar, read-only, through the same Google sign-in as Google Health.
 * Only meeting times are read and only daily counts are kept (backend/app/sync/calendar.py).
 */
export function CalendarCard() {
  const client = useQueryClient();
  const status = useCalendarStatus();
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const calendar = status.data;

  async function connect() {
    setOpening(true);
    setError(null);
    try {
      const { url } = await api.connectGoogle('calendar');
      if (!url) {
        await client.invalidateQueries({ queryKey: keys.calendar }); // the mock connects at once
      } else if (Platform.OS === 'web') {
        window.location.assign(url); // Google sends the browser back to Settings
        return;
      } else {
        await Linking.openURL(url);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not start connecting.');
    }
    setOpening(false);
  }

  async function disconnect() {
    setError(null);
    try {
      await api.disconnectCalendar();
      await client.invalidateQueries({ queryKey: keys.calendar });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not disconnect.');
    }
  }

  if (calendar?.connected) {
    return (
      <View>
        <Row
          icon="calendar-outline"
          title={
            calendar.lastError ? 'The latest calendar sync failed' : 'Google Calendar connected'
          }
          tone={calendar.lastError ? 'danger' : undefined}
          detail={
            calendar.lastError
              ? `${calendar.lastError}${calendar.lastSync ? ` Last good sync ${timeAgo(calendar.lastSync)}.` : ''} It tries again within half an hour.`
              : calendar.lastSync
                ? `${calendar.days} days of meeting load · synced ${timeAgo(calendar.lastSync)}`
                : 'Reading your calendar…'
          }
        />
        <Row
          icon="close-circle-outline"
          title="Disconnect Google Calendar"
          detail="Stops reading your calendar; Google Health stays connected. Synced days are kept."
          tone="danger"
          onPress={disconnect}
        />
        {error ? <Text color="danger">{error}</Text> : null}
      </View>
    );
  }
  return (
    <View style={styles.block}>
      <Text color="muted">
        Read-only. Patterns reads when your meetings are, never their titles, people or notes, and
        keeps only daily totals: time in meetings, after hours, back to back, focus time. Your team
        figures use them from at least 5 people.
      </Text>
      <Button
        label={opening ? 'Opening Google…' : 'Connect Google Calendar'}
        disabled={opening || status.isLoading}
        onPress={connect}
      />
      {error ? <Text color="danger">{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  block: { gap: spacing.sm, paddingVertical: spacing.md },
});
