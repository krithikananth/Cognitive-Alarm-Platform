import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { initializeNotificationRuntime } from './services/notificationService';

initializeNotificationRuntime().catch((err) => {
  console.error('[Notifications] Unexpected runtime bootstrap failure:', err);
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
