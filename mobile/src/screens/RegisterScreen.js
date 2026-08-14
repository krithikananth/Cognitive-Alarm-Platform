import { useEffect, useState } from 'react';

import {
    AuthScreenLayout,
    Field,
    FormError,
    LinkButton,
    PrimaryButton,
} from '../components/authUi';
import useAuthStore from '../store/authStore';

// Mirrors the backend UserCreate validators so an obvious mistake is caught
// before a round trip, rather than returning as a 422 list.
const USERNAME_PATTERN = /^[a-zA-Z0-9_]+$/;

export function passwordProblem(password) {
    if (password.length < 8) return 'Use at least 8 characters.';
    if (!/[A-Z]/.test(password)) return 'Add an uppercase letter.';
    if (!/[a-z]/.test(password)) return 'Add a lowercase letter.';
    if (!/\d/.test(password)) return 'Add a digit.';
    return null;
}

export function usernameProblem(username) {
    if (username.length < 3) return 'Use at least 3 characters.';
    if (!USERNAME_PATTERN.test(username)) return 'Letters, digits and underscores only.';
    return null;
}

// Account registration (spec §5, task 4).
export default function RegisterScreen({ navigation }) {
    const [email, setEmail] = useState('');
    const [username, setUsername] = useState('');
    const [fullName, setFullName] = useState('');
    const [password, setPassword] = useState('');
    const register = useAuthStore((state) => state.register);
    const submitting = useAuthStore((state) => state.submitting);
    const error = useAuthStore((state) => state.error);
    const clearError = useAuthStore((state) => state.clearError);

    useEffect(() => clearError, [clearError]);

    const usernameError = username ? usernameProblem(username) : null;
    const passwordError = password ? passwordProblem(password) : null;
    const canSubmit =
        email.trim().length > 0 &&
        username.length > 0 &&
        password.length > 0 &&
        !usernameError &&
        !passwordError;

    return (
        <AuthScreenLayout
            title="Create your account"
            subtitle="One account works across the phone and the web dashboard."
        >
            <FormError message={error} />
            <Field
                testID="register-email"
                label="Email"
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                placeholder="you@example.com"
            />
            <Field
                testID="register-username"
                label="Username"
                value={username}
                onChangeText={setUsername}
                autoCapitalize="none"
                placeholder="sleepy_owl"
                error={usernameError}
            />
            <Field
                testID="register-full-name"
                label="Full name (optional)"
                value={fullName}
                onChangeText={setFullName}
                placeholder="Alex Morgan"
            />
            <Field
                testID="register-password"
                label="Password"
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoCapitalize="none"
                placeholder="At least 8 characters"
                error={passwordError}
            />
            <PrimaryButton
                testID="register-submit"
                label="Create account"
                busy={submitting}
                disabled={!canSubmit}
                onPress={() =>
                    register({
                        email: email.trim(),
                        username: username.trim(),
                        password,
                        fullName: fullName.trim(),
                    })
                }
            />
            <LinkButton
                testID="register-go-login"
                label="Already registered? Sign in"
                onPress={() => navigation.navigate('Login')}
            />
        </AuthScreenLayout>
    );
}
