import { useCallback, useEffect, useLayoutEffect } from 'react';
import { Alert, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';

import {
    Card,
    EmptyState,
    ErrorBanner,
    LoadingBlock,
    TextButton,
    ToggleRow,
    theme,
} from '../components';
import useAlarmStore from '../store/alarmStore';
import { describeRecurrence, formatAlarmTime, formatCountdown } from '../utils/time';

// Alarm list + toggle + "Alarm health" banner (spec §6.4, tasks 5 and 8).
export default function AlarmListScreen({ navigation }) {
    const alarms = useAlarmStore((state) => state.alarms);
    const loading = useAlarmStore((state) => state.loading);
    const refreshing = useAlarmStore((state) => state.refreshing);
    const error = useAlarmStore((state) => state.error);
    const fetchAlarms = useAlarmStore((state) => state.fetchAlarms);
    const toggleAlarm = useAlarmStore((state) => state.toggleAlarm);
    const deleteAlarm = useAlarmStore((state) => state.deleteAlarm);

    useEffect(() => {
        fetchAlarms();
    }, [fetchAlarms]);

    // The list is the source of truth for the ring schedule, so it re-reads the
    // server whenever the user comes back from the editor.
    useEffect(
        () => navigation.addListener('focus', () => fetchAlarms({ refresh: true })),
        [navigation, fetchAlarms]
    );

    useLayoutEffect(() => {
        navigation.setOptions({
            headerRight: () => (
                <TextButton
                    testID="alarm-list-new"
                    label="+ New"
                    onPress={() => navigation.navigate('AlarmEdit', {})}
                />
            ),
        });
    }, [navigation]);

    const confirmDelete = useCallback(
        (alarm) => {
            Alert.alert(
                'Delete alarm',
                `"${alarm.title}" will stop ringing. This cannot be undone.`,
                [
                    { text: 'Cancel', style: 'cancel' },
                    {
                        text: 'Delete',
                        style: 'destructive',
                        onPress: () => deleteAlarm(alarm.id),
                    },
                ]
            );
        },
        [deleteAlarm]
    );

    const renderAlarm = useCallback(
        ({ item }) => {
            const countdown = item.is_active ? formatCountdown(item.next_trigger_at) : null;
            return (
                <Card testID={`alarm-card-${item.id}`}>
                    <View style={styles.cardHeader}>
                        <View style={styles.cardHeading}>
                            <Text style={[styles.time, !item.is_active && styles.dimmed]}>
                                {formatAlarmTime(item.alarm_time)}
                            </Text>
                            <Text style={styles.title}>{item.title}</Text>
                        </View>
                    </View>

                    <Text style={styles.meta}>{describeRecurrence(item)}</Text>
                    <Text testID={`alarm-next-${item.id}`} style={styles.meta}>
                        {item.is_active
                            ? countdown
                                ? `Next ring ${countdown}`
                                : 'Next ring not scheduled yet'
                            : 'Off'}
                    </Text>
                    <Text style={styles.meta}>
                        {item.challenge_count}x {item.challenge_type.replace('_', ' ')} ·{' '}
                        {item.challenge_difficulty} · {item.snooze_limit} snoozes
                    </Text>

                    <ToggleRow
                        testID={`alarm-toggle-${item.id}`}
                        label={item.is_active ? 'Armed' : 'Disarmed'}
                        value={item.is_active}
                        onValueChange={(next) => toggleAlarm(item.id, next)}
                    />

                    <View style={styles.actions}>
                        <TextButton
                            testID={`alarm-edit-${item.id}`}
                            label="Edit"
                            onPress={() => navigation.navigate('AlarmEdit', { alarm: item })}
                        />
                        <TextButton
                            testID={`alarm-delete-${item.id}`}
                            label="Delete"
                            tone="danger"
                            onPress={() => confirmDelete(item)}
                        />
                    </View>
                </Card>
            );
        },
        [confirmDelete, navigation, toggleAlarm]
    );

    if (loading && alarms.length === 0) {
        return (
            <View style={styles.screen}>
                <LoadingBlock testID="alarm-list-loading" />
            </View>
        );
    }

    return (
        <View style={styles.screen}>
            <FlatList
                testID="alarm-list"
                data={alarms}
                keyExtractor={(item) => String(item.id)}
                renderItem={renderAlarm}
                contentContainerStyle={styles.listContent}
                ListHeaderComponent={
                    <ErrorBanner
                        testID="alarm-list-error"
                        message={error}
                        onRetry={() => fetchAlarms()}
                    />
                }
                ListEmptyComponent={
                    <EmptyState
                        testID="alarm-list-empty"
                        title="No alarms yet"
                        message="Create one and it will ring on this device, even offline."
                    />
                }
                refreshControl={
                    <RefreshControl
                        refreshing={refreshing}
                        onRefresh={() => fetchAlarms({ refresh: true })}
                        tintColor={theme.accent}
                    />
                }
            />
        </View>
    );
}

const styles = StyleSheet.create({
    screen: { flex: 1, backgroundColor: theme.background },
    listContent: { padding: 16, paddingBottom: 32, flexGrow: 1 },
    cardHeader: { flexDirection: 'row', justifyContent: 'space-between' },
    cardHeading: { flexShrink: 1 },
    time: { color: theme.text, fontSize: 30, fontWeight: '700' },
    dimmed: { color: theme.muted },
    title: { color: theme.text, fontSize: 16, marginTop: 2 },
    meta: { color: theme.muted, fontSize: 13, marginTop: 6 },
    actions: {
        flexDirection: 'row',
        justifyContent: 'flex-end',
        gap: 16,
        borderTopWidth: 1,
        borderTopColor: theme.border,
        paddingTop: 8,
    },
});

