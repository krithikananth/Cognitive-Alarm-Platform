import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import { initializeNotificationRuntime } from './services/notificationService';
import {
  installGlobalErrorHandlers,
  reportClientError,
} from './services/errorReporting';

// Installed first so failures during the rest of the bootstrap are captured.
installGlobalErrorHandlers();

initializeNotificationRuntime().catch((err) => {
  console.error('[Notifications] Unexpected runtime bootstrap failure:', err);
  reportClientError(err, {
    source: 'manual',
    context: { phase: 'notification-bootstrap' },
  });
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <ErrorBoundary name="root" title="The app failed to start">
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
