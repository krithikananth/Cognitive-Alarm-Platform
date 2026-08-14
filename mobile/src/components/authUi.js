import { useState } from 'react';
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from 'react-native';

export const theme = {
    background: '#0f172a',
    surface: '#1e293b',
    border: '#334155',
    text: '#e2e8f0',
    muted: '#94a3b8',
    accent: '#38bdf8',
    danger: '#f87171',
};

export function AuthScreenLayout({ title, subtitle, children }) {
    return (
        <KeyboardAvoidingView
            style={styles.flex}
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
            <ScrollView
                contentContainerStyle={styles.scroll}
                keyboardShouldPersistTaps="handled"
            >
                <Text style={styles.title}>{title}</Text>
                {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
                <View style={styles.card}>{children}</View>
            </ScrollView>
        </KeyboardAvoidingView>
    );
}

export function Field({ label, error, ...inputProps }) {
    const [focused, setFocused] = useState(false);
    return (
        <View style={styles.field}>
            <Text style={styles.label}>{label}</Text>
            <TextInput
                style={[styles.input, focused && styles.inputFocused]}
                placeholderTextColor={theme.muted}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                {...inputProps}
            />
            {error ? <Text style={styles.fieldError}>{error}</Text> : null}
        </View>
    );
}

export function PrimaryButton({ label, onPress, busy, disabled, testID }) {
    const inactive = busy || disabled;
    return (
        <Pressable
            testID={testID}
            accessibilityRole="button"
            accessibilityState={{ disabled: Boolean(inactive), busy: Boolean(busy) }}
            onPress={onPress}
            disabled={inactive}
            style={[styles.button, inactive && styles.buttonDisabled]}
        >
            {busy ? (
                <ActivityIndicator color="#0f172a" />
            ) : (
                <Text style={styles.buttonLabel}>{label}</Text>
            )}
        </Pressable>
    );
}

export function LinkButton({ label, onPress, testID }) {
    return (
        <Pressable testID={testID} accessibilityRole="link" onPress={onPress}>
            <Text style={styles.link}>{label}</Text>
        </Pressable>
    );
}

export function FormError({ message }) {
    if (!message) return null;
    return (
        <View accessibilityRole="alert" style={styles.errorBox}>
            <Text style={styles.errorText}>{message}</Text>
        </View>
    );
}

const styles = StyleSheet.create({
    flex: { flex: 1, backgroundColor: theme.background },
    scroll: { flexGrow: 1, justifyContent: 'center', padding: 24 },
    title: { color: theme.text, fontSize: 26, fontWeight: '700' },
    subtitle: { color: theme.muted, fontSize: 14, marginTop: 6, marginBottom: 20 },
    card: {
        backgroundColor: theme.surface,
        borderRadius: 16,
        padding: 20,
        borderWidth: 1,
        borderColor: theme.border,
    },
    field: { marginBottom: 14 },
    label: { color: theme.muted, fontSize: 13, marginBottom: 6 },
    input: {
        backgroundColor: theme.background,
        borderWidth: 1,
        borderColor: theme.border,
        borderRadius: 10,
        paddingHorizontal: 12,
        paddingVertical: 10,
        color: theme.text,
        fontSize: 16,
    },
    inputFocused: { borderColor: theme.accent },
    fieldError: { color: theme.danger, fontSize: 12, marginTop: 4 },
    button: {
        backgroundColor: theme.accent,
        borderRadius: 10,
        paddingVertical: 14,
        alignItems: 'center',
        marginTop: 6,
    },
    buttonDisabled: { opacity: 0.6 },
    buttonLabel: { color: '#0f172a', fontSize: 16, fontWeight: '700' },
    link: { color: theme.accent, fontSize: 14, textAlign: 'center', marginTop: 16 },
    errorBox: {
        backgroundColor: '#7f1d1d',
        borderRadius: 10,
        padding: 12,
        marginBottom: 14,
    },
    errorText: { color: '#fecaca', fontSize: 13 },
});
