import { useCallback, useEffect, useRef, useState } from 'react';
import {
    Alert,
    BackHandler,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from 'react-native';
import { useKeepAwake } from 'expo-keep-awake';

import {
    Card,
    ErrorBanner,
    Field,
    LoadingBlock,
    PrimaryButton,
    TextButton,
    theme,
} from '../components';
import useRingStore, { RING_STATUS, selectCanSnooze } from '../store/ringStore';

const formatSeconds = (value) => {
    const total = Math.max(0, Math.floor(value));
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};

// The critical screen: full ring lifecycle over the lock screen (spec §6.3, task 7).
// Nothing here may let the user leave without solving, snoozing or giving up.
export default function RingScreen() {
    useKeepAwake();

    const status = useRingStore((state) => state.status);
    const title = useRingStore((state) => state.title);
    const challenge = useRingStore((state) => state.challenge);
    const issuedAt = useRingStore((state) => state.issuedAt);
    const progress = useRingStore((state) => state.progress);
    const feedback = useRingStore((state) => state.feedback);
    const error = useRingStore((state) => state.error);
    const outcome = useRingStore((state) => state.outcome);
    const busy = useRingStore((state) => state.busy);
    const snoozeCount = useRingStore((state) => state.snoozeCount);
    const snoozeLimit = useRingStore((state) => state.snoozeLimit);
    const canSnooze = useRingStore(selectCanSnooze);

    const loadChallenge = useRingStore((state) => state.loadChallenge);
    const submitAnswer = useRingStore((state) => state.submitAnswer);
    const snooze = useRingStore((state) => state.snooze);
    const giveUp = useRingStore((state) => state.giveUp);
    const stopRing = useRingStore((state) => state.stopRing);

    const [answer, setAnswer] = useState('');
    const [remaining, setRemaining] = useState(null);
    const timedOutRef = useRef(false);

    // A new challenge means a new attempt: clear the previous selection and
    // re-arm the timeout latch.
    useEffect(() => {
        setAnswer('');
        timedOutRef.current = false;
    }, [challenge]);

    // Back must not escape the ring; the navigator already disables the header
    // and the swipe gesture, and this closes the last route out.
    useEffect(() => {
        const subscription = BackHandler.addEventListener('hardwareBackPress', () => true);
        return () => subscription.remove();
    }, []);

    useEffect(() => {
        const limit = Number(challenge?.time_limit_seconds);
        if (status !== RING_STATUS.CHALLENGE || !Number.isFinite(limit) || limit <= 0) {
            setRemaining(null);
            return undefined;
        }
        const startedAt = issuedAt ?? Date.now();
        const tick = () =>
            setRemaining(Math.max(0, limit - Math.floor((Date.now() - startedAt) / 1000)));
        tick();
        const timer = setInterval(tick, 1000);
        return () => clearInterval(timer);
    }, [status, challenge, issuedAt]);

    // Let the server rule on the timeout rather than judging it here — it owns
    // the issuance instant and the grace period.
    useEffect(() => {
        if (remaining !== 0 || busy || timedOutRef.current) return;
        if (status !== RING_STATUS.CHALLENGE) return;
        timedOutRef.current = true;
        submitAnswer(answer);
    }, [remaining, busy, status, answer, submitAnswer]);

    const confirmGiveUp = useCallback(() => {
        Alert.alert(
            'Give up?',
            'This records an unverified wake and breaks your streak.',
            [
                { text: 'Keep trying', style: 'cancel' },
                { text: 'Give up', style: 'destructive', onPress: () => giveUp() },
            ]
        );
    }, [giveUp]);

    if (status === RING_STATUS.DISMISSED || status === RING_STATUS.ABANDONED) {
        const wakefulness = outcome?.wakefulness || {};
        return (
            <View style={styles.screen} testID="ring-summary">
                <View style={styles.summary}>
                    <Text style={styles.summaryTitle}>
                        {status === RING_STATUS.DISMISSED ? 'Wake verified' : 'Wake not verified'}
                    </Text>
                    <Text style={styles.summaryMessage}>
                        {outcome?.message ||
                            (status === RING_STATUS.DISMISSED
                                ? 'Alarm dismissed.'
                                : 'This alarm was closed without solving the challenge.')}
                    </Text>
                    {wakefulness?.level ? (
                        <Text testID="ring-wakefulness" style={styles.summaryMeta}>
                            Wakefulness: {wakefulness.level}
                        </Text>
                    ) : null}
                    {Number.isFinite(Number(outcome?.success_streak)) ? (
                        <Text style={styles.summaryMeta}>Streak: {outcome.success_streak}</Text>
                    ) : null}
                </View>
                <PrimaryButton testID="ring-done" label="Done" onPress={stopRing} />
            </View>
        );
    }

    const options = Array.isArray(challenge?.options) ? challenge.options : [];

    return (
        <ScrollView
            style={styles.screen}
            contentContainerStyle={styles.content}
            testID="ring-screen"
        >
            <Text style={styles.alarmTitle}>{title}</Text>
            <Text style={styles.subtitle}>Solve the challenge to stop the alarm</Text>

            {status === RING_STATUS.ERROR ? (
                <ErrorBanner testID="ring-error" message={error} onRetry={loadChallenge} />
            ) : null}

            {feedback ? (
                <View testID="ring-feedback" accessibilityRole="alert" style={styles.feedback}>
                    <Text style={styles.feedbackText}>{feedback}</Text>
                </View>
            ) : null}

            {status === RING_STATUS.LOADING ? <LoadingBlock testID="ring-loading" /> : null}

            {status === RING_STATUS.CHALLENGE && challenge ? (
                <Card testID="ring-challenge">
                    <View style={styles.challengeHeader}>
                        <Text style={styles.step}>
                            Step {progress.current} of {progress.total}
                        </Text>
                        {remaining === null ? null : (
                            <Text
                                testID="ring-countdown"
                                style={[styles.countdown, remaining <= 5 && styles.countdownUrgent]}
                            >
                                {formatSeconds(remaining)}
                            </Text>
                        )}
                    </View>

                    <Text testID="ring-prompt" style={styles.prompt}>
                        {challenge.prompt}
                    </Text>
                    <Text style={styles.challengeMeta}>
                        {String(challenge.type || '').replace('_', ' ')} · {challenge.difficulty}
                        {challenge.ai_generated ? ' · AI' : ''}
                    </Text>

                    {options.length ? (
                        options.map((option, index) => {
                            const label = String(option);
                            const selected = answer === label;
                            return (
                                <Pressable
                                    key={`${label}-${index}`}
                                    testID={`ring-option-${index}`}
                                    accessibilityRole="button"
                                    accessibilityState={{ selected }}
                                    disabled={busy}
                                    onPress={() => setAnswer(label)}
                                    style={[styles.option, selected && styles.optionSelected]}
                                >
                                    <Text
                                        style={[
                                            styles.optionLabel,
                                            selected && styles.optionLabelSelected,
                                        ]}
                                    >
                                        {label}
                                    </Text>
                                </Pressable>
                            );
                        })
                    ) : (
                        <Field
                            testID="ring-answer"
                            label="Your answer"
                            value={answer}
                            onChangeText={setAnswer}
                            autoCapitalize="none"
                            autoCorrect={false}
                            editable={!busy}
                        />
                    )}

                    <PrimaryButton
                        testID="ring-submit"
                        label="Submit"
                        busy={busy}
                        disabled={!answer}
                        onPress={() => submitAnswer(answer)}
                    />
                </Card>
            ) : null}

            <View style={styles.footer}>
                <TextButton
                    testID="ring-snooze"
                    label={
                        canSnooze ? `Snooze (${snoozeLimit - snoozeCount} left)` : 'No snoozes left'
                    }
                    disabled={!canSnooze || busy}
                    onPress={snooze}
                />
                <TextButton
                    testID="ring-give-up"
                    label="Give up"
                    tone="danger"
                    disabled={busy}
                    onPress={confirmGiveUp}
                />
            </View>
        </ScrollView>
    );
}

const styles = StyleSheet.create({
    screen: { flex: 1, backgroundColor: theme.background },
    content: { padding: 20, paddingTop: 48 },
    alarmTitle: { color: theme.text, fontSize: 30, fontWeight: '700' },
    subtitle: { color: theme.muted, fontSize: 14, marginTop: 6, marginBottom: 20 },
    challengeHeader: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 10,
    },
    step: { color: theme.muted, fontSize: 13, fontWeight: '600' },
    countdown: { color: theme.accent, fontSize: 18, fontWeight: '700' },
    countdownUrgent: { color: theme.danger },
    prompt: { color: theme.text, fontSize: 20, lineHeight: 28 },
    challengeMeta: { color: theme.muted, fontSize: 12, marginTop: 8, marginBottom: 14 },
    option: {
        borderWidth: 1,
        borderColor: theme.border,
        borderRadius: 10,
        paddingVertical: 14,
        paddingHorizontal: 14,
        marginBottom: 10,
        backgroundColor: theme.background,
    },
    optionSelected: { borderColor: theme.accent, backgroundColor: '#0b3a4a' },
    optionLabel: { color: theme.text, fontSize: 16 },
    optionLabelSelected: { color: theme.accent, fontWeight: '700' },
    feedback: {
        backgroundColor: '#78350f',
        borderRadius: 10,
        padding: 12,
        marginBottom: 12,
    },
    feedbackText: { color: '#fde68a', fontSize: 13 },
    footer: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginTop: 8,
    },
    summary: { flex: 1, justifyContent: 'center', paddingHorizontal: 20 },
    summaryTitle: { color: theme.text, fontSize: 28, fontWeight: '700' },
    summaryMessage: { color: theme.muted, fontSize: 15, marginTop: 10, lineHeight: 22 },
    summaryMeta: { color: theme.muted, fontSize: 13, marginTop: 8 },
});
