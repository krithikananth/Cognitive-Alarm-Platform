import { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import AlarmListScreen from '../screens/AlarmListScreen';
import AlarmEditScreen from '../screens/AlarmEditScreen';
import DashboardScreen from '../screens/DashboardScreen';
import LoginScreen from '../screens/LoginScreen';
import PermissionsScreen from '../screens/PermissionsScreen';
import ProfileScreen from '../screens/ProfileScreen';
import RegisterScreen from '../screens/RegisterScreen';
import RingScreen from '../screens/RingScreen';
import useAuthStore, { AUTH_STATUS } from '../store/authStore';

const Stack = createNativeStackNavigator();

const screenOptions = {
  headerStyle: { backgroundColor: '#0f172a' },
  headerTintColor: '#e2e8f0',
  contentStyle: { backgroundColor: '#0f172a' },
};

// Root navigator. Alarm CRUD, ring and permission screens are still placeholders
// (spec tasks 5-8); only the auth flow is real.
export default function RootNavigator() {
  const status = useAuthStore((state) => state.status);
  const restore = useAuthStore((state) => state.restore);

  useEffect(() => {
    restore();
  }, [restore]);

  if (status === AUTH_STATUS.UNKNOWN) {
    return (
      <View style={styles.splash} testID="auth-restoring">
        <ActivityIndicator color="#38bdf8" size="large" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={screenOptions}>
        {status === AUTH_STATUS.AUTHENTICATED ? (
          <Stack.Group>
            <Stack.Screen
              name="AlarmList"
              component={AlarmListScreen}
              options={{ title: 'Alarms' }}
            />
            <Stack.Screen name="AlarmEdit" component={AlarmEditScreen} />
            <Stack.Screen name="Dashboard" component={DashboardScreen} />
            <Stack.Screen name="Profile" component={ProfileScreen} />
            <Stack.Screen name="Permissions" component={PermissionsScreen} />
            <Stack.Screen
              name="Ring"
              component={RingScreen}
              // The ring must not be escapable with a swipe or the header back arrow.
              options={{ headerShown: false, gestureEnabled: false }}
            />
          </Stack.Group>
        ) : (
          <Stack.Group screenOptions={{ headerShown: false }}>
            <Stack.Screen name="Login" component={LoginScreen} />
            <Stack.Screen name="Register" component={RegisterScreen} />
          </Stack.Group>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0f172a',
  },
});
