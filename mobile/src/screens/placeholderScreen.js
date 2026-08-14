import { StyleSheet, Text, View } from 'react-native';

// Temporary stand-in so the screen tree matches the spec layout before each screen is
// implemented (spec §10, tasks 4-10).
export function createPlaceholderScreen(name) {
  function PlaceholderScreen() {
    return (
      <View style={styles.container}>
        <Text style={styles.text}>{name}</Text>
      </View>
    );
  }
  PlaceholderScreen.displayName = name;
  return PlaceholderScreen;
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#0f172a' },
  text: { color: '#e2e8f0', fontSize: 18 },
});
