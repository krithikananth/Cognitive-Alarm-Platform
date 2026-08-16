// Shared presentational components (spec §2, tasks 5-10).
import {
    ActivityIndicator,
    Pressable,
    StyleSheet,
    Switch,
    Text,
    View,
} from 'react-native';

import { theme } from './authUi';

export { theme, Field, FormError, PrimaryButton, LinkButton } from './authUi';

export function Card({ children, style, testID }) {
    return (
        <View testID={testID} style={[styles.card, style]}>
            {children}
        </View>
    );
}

export function SectionLabel({ children }) {
    return <Text style={styles.sectionLabel}>{children}</Text>;
}

export function Chip({ label, selected, disabled, onPress, testID }) {
    return (
        <Pressable
            testID={testID}
            accessibilityRole="button"
            accessibilityState={{ selected: Boolean(selected), disabled: Boolean(disabled) }}
            onPress={disabled ? undefined : onPress}
            disabled={disabled}
            style={[
                styles.chip,
                selected && styles.chipSelected,
                disabled && styles.chipDisabled,
            ]}
        >
            <Text style={[styles.chipLabel, selected && styles.chipLabelSelected]}>
                {label}
            </Text>
        </Pressable>
    );
}

/**
 * Bounded +/- control.
 *
 * Numeric text inputs are avoided on purpose: clearing one yields `Number('')
 * === 0`, which silently rewrites a saved value. A stepper cannot express an
 * empty state, so the bug is designed out rather than guarded against.
 */
export function Stepper({ label, value, min = 0, max = 100, step = 1, suffix, onChange, testID }) {
    const clamp = (next) => Math.min(Math.max(next, min), max);
    return (
        <View style={styles.stepperRow}>
            <Text style={styles.rowLabel}>{label}</Text>
            <View style={styles.stepperControls}>
                <Pressable
                    testID={testID ? `${testID}-decrement` : undefined}
                    accessibilityRole="button"
                    accessibilityLabel={`Decrease ${label}`}
                    disabled={value <= min}
                    onPress={() => onChange(clamp(value - step))}
                    style={[styles.stepperButton, value <= min && styles.stepperButtonDisabled]}
                >
                    <Text style={styles.stepperSymbol}>−</Text>
                </Pressable>
                <Text testID={testID ? `${testID}-value` : undefined} style={styles.stepperValue}>
                    {value}
                    {suffix || ''}
                </Text>
                <Pressable
                    testID={testID ? `${testID}-increment` : undefined}
                    accessibilityRole="button"
                    accessibilityLabel={`Increase ${label}`}
                    disabled={value >= max}
                    onPress={() => onChange(clamp(value + step))}
                    style={[styles.stepperButton, value >= max && styles.stepperButtonDisabled]}
                >
                    <Text style={styles.stepperSymbol}>+</Text>
                </Pressable>
            </View>
        </View>
    );
}

export function ToggleRow({ label, value, onValueChange, testID }) {
    return (
        <View style={styles.toggleRow}>
            <Text style={styles.rowLabel}>{label}</Text>
            <Switch
                testID={testID}
                accessibilityLabel={label}
                value={Boolean(value)}
                onValueChange={onValueChange}
                trackColor={{ false: theme.border, true: theme.accent }}
                thumbColor={theme.text}
            />
        </View>
    );
}

export function EmptyState({ title, message, testID }) {
    return (
        <View testID={testID} style={styles.empty}>
            <Text style={styles.emptyTitle}>{title}</Text>
            {message ? <Text style={styles.emptyMessage}>{message}</Text> : null}
        </View>
    );
}

export function ErrorBanner({ message, onRetry, testID }) {
    if (!message) return null;
    return (
        <View testID={testID} accessibilityRole="alert" style={styles.errorBox}>
            <Text style={styles.errorText}>{message}</Text>
            {onRetry ? (
                <Pressable accessibilityRole="button" onPress={onRetry}>
                    <Text style={styles.retry}>Try again</Text>
                </Pressable>
            ) : null}
        </View>
    );
}

export function TextButton({ label, onPress, tone = 'accent', testID, disabled }) {
    return (
        <Pressable
            testID={testID}
            accessibilityRole="button"
            accessibilityState={{ disabled: Boolean(disabled) }}
            onPress={onPress}
            disabled={disabled}
            style={styles.textButton}
        >
            <Text
                style={[
                    styles.textButtonLabel,
                    tone === 'danger' && styles.textButtonDanger,
                    disabled && styles.textButtonDisabled,
                ]}
            >
                {label}
            </Text>
        </Pressable>
    );
}

export function LoadingBlock({ testID }) {
    return (
        <View testID={testID} style={styles.loading}>
            <ActivityIndicator color={theme.accent} size="large" />
        </View>
    );
}

const styles = StyleSheet.create({
    card: {
        backgroundColor: theme.surface,
        borderRadius: 16,
        borderWidth: 1,
        borderColor: theme.border,
        padding: 16,
        marginBottom: 12,
    },
    sectionLabel: {
        color: theme.muted,
        fontSize: 13,
        fontWeight: '600',
        textTransform: 'uppercase',
        letterSpacing: 0.6,
        marginBottom: 8,
        marginTop: 4,
    },
    chip: {
        borderWidth: 1,
        borderColor: theme.border,
        borderRadius: 999,
        paddingHorizontal: 14,
        paddingVertical: 8,
        marginRight: 8,
        marginBottom: 8,
        backgroundColor: theme.background,
    },
    chipSelected: { backgroundColor: theme.accent, borderColor: theme.accent },
    chipDisabled: { opacity: 0.35 },
    chipLabel: { color: theme.text, fontSize: 14 },
    chipLabelSelected: { color: '#0f172a', fontWeight: '700' },
    rowLabel: { color: theme.text, fontSize: 15, flexShrink: 1 },
    stepperRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 12,
    },
    stepperControls: { flexDirection: 'row', alignItems: 'center' },
    stepperButton: {
        width: 40,
        height: 40,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: theme.border,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: theme.background,
    },
    stepperButtonDisabled: { opacity: 0.4 },
    stepperSymbol: { color: theme.text, fontSize: 20, lineHeight: 22 },
    stepperValue: {
        color: theme.text,
        fontSize: 16,
        fontWeight: '600',
        minWidth: 56,
        textAlign: 'center',
    },
    toggleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 12,
    },
    empty: { alignItems: 'center', paddingVertical: 48, paddingHorizontal: 24 },
    emptyTitle: { color: theme.text, fontSize: 17, fontWeight: '700' },
    emptyMessage: {
        color: theme.muted,
        fontSize: 14,
        marginTop: 8,
        textAlign: 'center',
        lineHeight: 20,
    },
    errorBox: {
        backgroundColor: '#7f1d1d',
        borderRadius: 10,
        padding: 12,
        marginBottom: 12,
    },
    errorText: { color: '#fecaca', fontSize: 13 },
    retry: { color: '#fecaca', fontSize: 13, fontWeight: '700', marginTop: 8 },
    textButton: { paddingVertical: 6, paddingHorizontal: 4 },
    textButtonLabel: { color: theme.accent, fontSize: 14, fontWeight: '600' },
    textButtonDanger: { color: theme.danger },
    textButtonDisabled: { opacity: 0.5 },
    loading: { paddingVertical: 48, alignItems: 'center' },
});

