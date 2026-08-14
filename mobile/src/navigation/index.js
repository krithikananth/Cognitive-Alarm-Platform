import { Text, StyleSheet } from 'react-native';

// Placeholder root navigator. Real stack (Login/Register/AlarmList/AlarmEdit/Ring/
// Dashboard/Profile/Permissions) is wired in spec task 4 onwards.
export default function RootNavigator() {
  return <Text style={styles.text}>Navigation not wired yet</Text>;
}

const styles = StyleSheet.create({
  text: { color: '#e2e8f0', fontSize: 16, marginBottom: 8 },
});
