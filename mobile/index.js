import { registerRootComponent } from 'expo';

import App from './App';
import { registerRingBackgroundHandler } from './src/alarm/handlers';

// Must run before React mounts: Notifee drops background events that arrive
// with no handler registered, and an alarm can fire with the app backgrounded.
registerRingBackgroundHandler();

registerRootComponent(App);
