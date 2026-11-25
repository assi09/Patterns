import { type StyleProp, StyleSheet, View, type ViewStyle } from 'react-native';

import { useTeamCalendar } from '@/api/hooks';
import { Row, Section } from '@/components/list';
import { Text } from '@/components/Text';
import { calendarEmpty, loadChange, loadValue, plannedWeek } from '@/lib/calendar';
import { windowLabel } from '@/lib/format';
import { spacing } from '@/theme';

/**
 * The team's meeting load from members' calendars: a median per person, the change against each
 * person's own usual week, and what is already planned next week. Never from fewer than 5.
 */
export function MeetingLoad({ teamId, style }: { teamId: string; style?: StyleProp<ViewStyle> }) {
  const load = useTeamCalendar(teamId);
  const data = load.data;
  if (!data) return null;
  const shown = data.metrics.filter((m) => m.sufficient);
  const empty = calendarEmpty(data);
  const planned = windowLabel(plannedWeek(data.week));
  return (
    <Section
      title="Meeting load"
      style={style}
      footer={`From the calendars of ${data.connected} ${data.connected === 1 ? 'member' : 'members'}: when meetings are, never what they are. Each figure is the middle person, compared with their own usual week.`}
    >
      {empty ? (
        <View style={styles.empty}>
          <Text color="muted">{empty}</Text>
        </View>
      ) : (
        <>
          <Text variant="caption" color="muted" style={styles.week}>
            {windowLabel(data.week)}, against each person&apos;s 4 weeks before
          </Text>
          {shown.map((m) => (
            <Row
              key={m.metric}
              icon={ICONS[m.metric] ?? 'calendar-outline'}
              title={`${m.label}: ${loadValue(m.medianWeek ?? 0, m.unit)} a person`}
              detail={[
                loadChange(m),
                `${m.membersUp ?? 0} up, ${m.membersDown ?? 0} down`,
                m.medianPlanned != null
                  ? `planned ${planned}: ${loadValue(m.medianPlanned, m.unit)}`
                  : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            />
          ))}
        </>
      )}
    </Section>
  );
}

const ICONS: Record<
  string,
  'time-outline' | 'moon-outline' | 'repeat-outline' | 'people-outline' | 'eye-outline'
> = {
  meeting_minutes: 'time-outline',
  after_hours_minutes: 'moon-outline',
  back_to_back: 'repeat-outline',
  meetings: 'people-outline',
  focus_minutes: 'eye-outline',
};

const styles = StyleSheet.create({
  empty: { paddingVertical: spacing.md },
  week: { paddingTop: spacing.sm },
});
