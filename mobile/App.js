// Must be the first import for react-native-screens/native-stack gestures.
import 'react-native-gesture-handler';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import useAlarmSync from './src/alarm/useAlarmSync';
import RootNavigator from './src/navigation';

export default function App() {
  useAlarmSync();
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <RootNavigator />
    </SafeAreaProvider>
  );
}

