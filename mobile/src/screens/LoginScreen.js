import { useEffect, useState } from 'react';

import {
    AuthScreenLayout,
    Field,
    FormError,
    LinkButton,
    PrimaryButton,
} from '../components/authUi';
import useAuthStore from '../store/authStore';

// Email/password login; Google OAuth deferred (spec §5, task 4).
export default function LoginScreen({ navigation }) {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const login = useAuthStore((state) => state.login);
    const submitting = useAuthStore((state) => state.submitting);
    const error = useAuthStore((state) => state.error);
    const clearError = useAuthStore((state) => state.clearError);

    useEffect(() => clearError, [clearError]);

    const canSubmit = email.trim().length > 0 && password.length > 0;

    return (
        <AuthScreenLayout
            title="ICAP Alarm"
            subtitle="Sign in to sync your alarms to this device."
        >
            <FormError message={error} />
            <Field
                testID="login-email"
                label="Email"
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                textContentType="emailAddress"
                placeholder="you@example.com"
            />
            <Field
                testID="login-password"
                label="Password"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoCapitalize="none"
                textContentType="password"
                placeholder="Your password"
            />
            <PrimaryButton
                testID="login-submit"
                label="Sign in"
                busy={submitting}
                disabled={!canSubmit}
                onPress={() => login(email.trim(), password)}
            />
            <LinkButton
                testID="login-go-register"
                label="No account? Create one"
                onPress={() => navigation.navigate('Register')}
            />
        </AuthScreenLayout>
    );
}
