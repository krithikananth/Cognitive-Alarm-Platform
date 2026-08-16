import { useLayoutEffect, useMemo, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import {
    Card,
    Chip,
    Field,
    FormError,
    PrimaryButton,
    SectionLabel,
    Stepper,
    TextButton,
    ToggleRow,
    theme,
} from '../components';
import useAlarmStore from '../store/alarmStore';
import {
    ALARM_TYPES,
    BASE_DAYS_BY_TYPE,
    CHALLENGE_TYPES,
    DAY_LABELS,
    DIFFICULTIES,
    isValidDateInput,
    parseAlarmTime,
    toApiTime,
} from '../utils/time';

function initialForm(alarm) {
    const time = parseAlarmTime(alarm?.alarm_time);
    return {
        title: alarm?.title ?? 'Alarm',
        description: alarm?.description ?? '',
        label: alarm?.label ?? '',
        hour: time.hour,
        minute: time.minute,
        period: time.period,
        alarmType: alarm?.alarm_type ?? 'daily',
        daysOfWeek: Array.isArray(alarm?.days_of_week) ? alarm.days_of_week : [],
        oneTimeDate: alarm?.one_time_date ?? '',
        snoozeLimit: alarm?.snooze_limit ?? 3,
        snoozeIntervalMinutes: alarm?.snooze_interval_minutes ?? 5,
        challengeType: alarm?.challenge_type ?? 'random',
        challengeCount: alarm?.challenge_count ?? 1,
        challengeDifficulty: alarm?.challenge_difficulty ?? 'medium',
        volume: alarm?.volume ?? 80,
        vibrate: alarm?.vibrate ?? true,
    };
}

// Create/edit alarm (spec §2, task 5).
export default function AlarmEditScreen({ navigation, route }) {
    const alarm = route?.params?.alarm ?? null;
    const isEdit = Boolean(alarm?.id);

    const [form, setForm] = useState(() => initialForm(alarm));
    const [fieldErrors, setFieldErrors] = useState({});

    const saving = useAlarmStore((state) => state.saving);
    const saveError = useAlarmStore((state) => state.saveError);
    const createAlarm = useAlarmStore((state) => state.createAlarm);
    const updateAlarm = useAlarmStore((state) => state.updateAlarm);

    useLayoutEffect(() => {
        navigation.setOptions({ title: isEdit ? 'Edit alarm' : 'New alarm' });
    }, [navigation, isEdit]);

    const patch = (changes) => setForm((current) => ({ ...current, ...changes }));

    const allowedDays = BASE_DAYS_BY_TYPE[form.alarmType] ?? null;

    const selectType = (nextType) => {
        const nextAllowed = BASE_DAYS_BY_TYPE[nextType];
        patch({
            alarmType: nextType,
            // Days outside the new pattern can never fire, so drop them instead of
            // sending a selection the backend would silently discard.
            daysOfWeek: nextAllowed
                ? form.daysOfWeek.filter((day) => nextAllowed.includes(day))
                : [],
        });
    };

    const toggleDay = (day) => {
        patch({
            daysOfWeek: form.daysOfWeek.includes(day)
                ? form.daysOfWeek.filter((value) => value !== day)
                : [...form.daysOfWeek, day].sort((a, b) => a - b),
        });
    };

    const timePreview = useMemo(
        () => toApiTime({ hour: form.hour, minute: form.minute, period: form.period }),
        [form.hour, form.minute, form.period]
    );

    const validate = () => {
        const errors = {};
        if (!form.title.trim()) {
            errors.title = 'Give the alarm a name.';
        }
        const hour = Number(form.hour);
        if (!Number.isInteger(hour) || hour < 1 || hour > 12) {
            errors.hour = 'Hour must be 1-12.';
        }
        const minute = Number(form.minute);
        if (!Number.isInteger(minute) || minute < 0 || minute > 59) {
            errors.minute = 'Minutes must be 0-59.';
        }
        if (form.alarmType === 'one_time' && form.oneTimeDate.trim()) {
            if (!isValidDateInput(form.oneTimeDate.trim())) {
                errors.oneTimeDate = 'Use YYYY-MM-DD.';
            }
        }
        setFieldErrors(errors);
        return Object.keys(errors).length === 0;
    };

    const buildPayload = () => ({
        title: form.title.trim(),
        description: form.description.trim() || null,
        label: form.label.trim() || null,
        alarm_time: timePreview,
        alarm_type: form.alarmType,
        // An empty selection means "the pattern's own days" to the backend.
        days_of_week: allowedDays && form.daysOfWeek.length ? form.daysOfWeek : null,
        one_time_date:
            form.alarmType === 'one_time' && form.oneTimeDate.trim()
                ? form.oneTimeDate.trim()
                : null,
        snooze_limit: form.snoozeLimit,
        snooze_interval_minutes: form.snoozeIntervalMinutes,
        challenge_type: form.challengeType,
        challenge_count: form.challengeCount,
        challenge_difficulty: form.challengeDifficulty,
        volume: form.volume,
        vibrate: form.vibrate,
    });

    const submit = async () => {
        if (!validate()) return;
        const payload = buildPayload();
        const saved = isEdit
            ? await updateAlarm(alarm.id, payload)
            : await createAlarm(payload);
        if (saved) {
            navigation.goBack();
        }
    };

    return (
        <ScrollView
            style={styles.screen}
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
        >
            <FormError message={saveError} />

            <Card>
                <SectionLabel>Basics</SectionLabel>
                <Field
                    testID="alarm-title"
                    label="Title"
                    value={form.title}
                    onChangeText={(value) => patch({ title: value })}
                    error={fieldErrors.title}
                    placeholder="Morning Alarm"
                />
                <Field
                    testID="alarm-description"
                    label="Description (optional)"
                    value={form.description}
                    onChangeText={(value) => patch({ description: value })}
                    placeholder="Why this alarm matters"
                />
                <Field
                    testID="alarm-label"
                    label="Label (optional)"
                    value={form.label}
                    onChangeText={(value) => patch({ label: value })}
                    placeholder="work"
                />
            </Card>

            <Card>
                <SectionLabel>Time</SectionLabel>
                <View style={styles.timeRow}>
                    <View style={styles.timeInput}>
                        <Field
                            testID="alarm-hour"
                            label="Hour"
                            value={form.hour}
                            onChangeText={(value) => patch({ hour: value.replace(/\D/g, '') })}
                            keyboardType="number-pad"
                            maxLength={2}
                            error={fieldErrors.hour}
                        />
                    </View>
                    <View style={styles.timeInput}>
                        <Field
                            testID="alarm-minute"
                            label="Minute"
                            value={form.minute}
                            onChangeText={(value) => patch({ minute: value.replace(/\D/g, '') })}
                            keyboardType="number-pad"
                            maxLength={2}
                            error={fieldErrors.minute}
                        />
                    </View>
                    <View style={styles.periodGroup}>
                        {['AM', 'PM'].map((period) => (
                            <Chip
                                key={period}
                                testID={`alarm-period-${period}`}
                                label={period}
                                selected={form.period === period}
                                onPress={() => patch({ period })}
                            />
                        ))}
                    </View>
                </View>
                <Text testID="alarm-time-preview" style={styles.hint}>
                    Rings at {timePreview} in your profile timezone.
                </Text>
            </Card>

            <Card>
                <SectionLabel>Repeat</SectionLabel>
                <View style={styles.chipRow}>
                    {ALARM_TYPES.map((type) => (
                        <Chip
                            key={type.value}
                            testID={`alarm-type-${type.value}`}
                            label={type.label}
                            selected={form.alarmType === type.value}
                            onPress={() => selectType(type.value)}
                        />
                    ))}
                </View>

                {allowedDays ? (
                    <>
                        <View style={styles.chipRow}>
                            {DAY_LABELS.map((label, day) => (
                                <Chip
                                    key={label}
                                    testID={`alarm-day-${day}`}
                                    label={label}
                                    selected={form.daysOfWeek.includes(day)}
                                    disabled={!allowedDays.includes(day)}
                                    onPress={() => toggleDay(day)}
                                />
                            ))}
                        </View>
                        <Text style={styles.hint}>
                            Leave every day unselected to use the pattern's default days.
                        </Text>
                    </>
                ) : (
                    <Field
                        testID="alarm-one-time-date"
                        label="Date (optional)"
                        value={form.oneTimeDate}
                        onChangeText={(value) => patch({ oneTimeDate: value })}
                        placeholder="YYYY-MM-DD"
                        autoCapitalize="none"
                        error={fieldErrors.oneTimeDate}
                    />
                )}
            </Card>

            <Card>
                <SectionLabel>Challenge</SectionLabel>
                <View style={styles.chipRow}>
                    {CHALLENGE_TYPES.map((type) => (
                        <Chip
                            key={type.value}
                            testID={`alarm-challenge-${type.value}`}
                            label={type.label}
                            selected={form.challengeType === type.value}
                            onPress={() => patch({ challengeType: type.value })}
                        />
                    ))}
                </View>
                <View style={styles.chipRow}>
                    {DIFFICULTIES.map((level) => (
                        <Chip
                            key={level}
                            testID={`alarm-difficulty-${level}`}
                            label={level}
                            selected={form.challengeDifficulty === level}
                            onPress={() => patch({ challengeDifficulty: level })}
                        />
                    ))}
                </View>
                <Stepper
                    testID="alarm-challenge-count"
                    label="Puzzles to solve"
                    value={form.challengeCount}
                    min={1}
                    max={10}
                    onChange={(value) => patch({ challengeCount: value })}
                />
            </Card>

            <Card>
                <SectionLabel>Snooze &amp; sound</SectionLabel>
                <Stepper
                    testID="alarm-snooze-limit"
                    label="Snooze limit"
                    value={form.snoozeLimit}
                    min={0}
                    max={10}
                    onChange={(value) => patch({ snoozeLimit: value })}
                />
                <Stepper
                    testID="alarm-snooze-interval"
                    label="Snooze interval"
                    value={form.snoozeIntervalMinutes}
                    min={1}
                    max={60}
                    suffix=" min"
                    onChange={(value) => patch({ snoozeIntervalMinutes: value })}
                />
                <Stepper
                    testID="alarm-volume"
                    label="Volume"
                    value={form.volume}
                    min={0}
                    max={100}
                    step={5}
                    suffix="%"
                    onChange={(value) => patch({ volume: value })}
                />
                <ToggleRow
                    testID="alarm-vibrate"
                    label="Vibrate"
                    value={form.vibrate}
                    onValueChange={(value) => patch({ vibrate: value })}
                />
            </Card>

            <PrimaryButton
                testID="alarm-save"
                label={isEdit ? 'Save changes' : 'Create alarm'}
                busy={saving}
                onPress={submit}
            />
            <View style={styles.cancel}>
                <TextButton
                    testID="alarm-cancel"
                    label="Cancel"
                    onPress={() => navigation.goBack()}
                />
            </View>
        </ScrollView>
    );
}

const styles = StyleSheet.create({
    screen: { flex: 1, backgroundColor: theme.background },
    content: { padding: 16, paddingBottom: 40 },
    timeRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
    timeInput: { width: 88 },
    periodGroup: { flexDirection: 'row', paddingTop: 24 },
    chipRow: { flexDirection: 'row', flexWrap: 'wrap' },
    hint: { color: theme.muted, fontSize: 12, marginTop: 4, marginBottom: 4 },
    cancel: { alignItems: 'center', marginTop: 8 },
});

