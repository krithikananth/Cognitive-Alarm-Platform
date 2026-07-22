/**
 * Main App component with routing.
 */
import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import useAuthStore from './store/authStore';

// Pages
import Login from './pages/Login';
import Register from './pages/Register';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import VerifyEmail from './pages/VerifyEmail';
import OAuthCallback from './pages/OAuthCallback';
import Dashboard from './pages/Dashboard';
import AlarmManager from './pages/AlarmManager';
import Profile from './pages/Profile';
import Analytics from './pages/Analytics';
import AdminDashboard from './pages/AdminDashboard';
import Layout from './components/Layout';

import ActiveAlarmModal from './components/ActiveAlarmModal';
import { trackAlarmMissed } from './services/analyticsTracker';
import useAlarmStore from './store/alarmStore';
import useActiveAlarmStore from './store/activeAlarmStore';

/** Trigger window (ms) — matches ring detection; past this = missed. */
const ALARM_TRIGGER_WINDOW_MS = 120000;
/** Do not mark very stale triggers as missed (avoids spam on old data). */
const ALARM_MISS_MAX_AGE_MS = 24 * 60 * 60 * 1000;

// Protected Route wrapper
function ProtectedRoute({ children }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

// Guest Route wrapper (redirect logged-in users)
function GuestRoute({ children }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  if (isAuthenticated) {
    return <Navigate to={user?.role === 'admin' ? '/admin' : '/dashboard'} replace />;
  }
  return children;
}

// Authenticated home: admins land on Admin Panel, users on Dashboard
function HomeRedirect() {
  const user = useAuthStore((s) => s.user);
  return <Navigate to={user?.role === 'admin' ? '/admin' : '/dashboard'} replace />;
}

// Component to watch time and trigger alarms
function AlarmWatcher() {
  const { alarms, fetchAlarms } = useAlarmStore();
  const { triggerAlarm, isRinging } = useActiveAlarmStore();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const firedRef = React.useRef(new Set());
  
  // Fetch alarms initially and refresh every 30 seconds
  React.useEffect(() => {
    if (isAuthenticated) {
      fetchAlarms();
      const refreshInterval = setInterval(() => fetchAlarms(), 30000);
      return () => clearInterval(refreshInterval);
    }
  }, [isAuthenticated, fetchAlarms]);
  
  // Check every 5 seconds if any alarm should ring (or was missed)
  React.useEffect(() => {
    if (!isAuthenticated) return;

    const checkAlarms = () => {
      const now = new Date();
      const ringingId = useActiveAlarmStore.getState().ringingAlarmId;

      for (const alarm of alarms) {
        if (!alarm.is_active || !alarm.next_trigger_at) continue;
        // Don't treat the currently ringing alarm as missed
        if (ringingId === alarm.id) continue;

        // Key by id + trigger time so snooze / next-day re-rings work
        const fireKey = `${alarm.id}:${alarm.next_trigger_at}`;
        if (firedRef.current.has(fireKey)) continue;

        // Backend returns UTC datetime — ensure proper parsing
        let triggerTimeStr = alarm.next_trigger_at;
        if (
          !triggerTimeStr.endsWith('Z') &&
          !triggerTimeStr.includes('+') &&
          !triggerTimeStr.includes('-', 10)
        ) {
          triggerTimeStr += 'Z';
        }
        const triggerTime = new Date(triggerTimeStr);
        const diffMs = now.getTime() - triggerTime.getTime();

        // Trigger if we're within 0 to 120 seconds past the trigger time
        if (
          !isRinging &&
          diffMs >= 0 &&
          diffMs < ALARM_TRIGGER_WINDOW_MS
        ) {
          firedRef.current.add(fireKey);
          triggerAlarm(alarm.id);
          break;
        }

        // Past the ring window and never fired → miss (client analytics only)
        if (
          diffMs >= ALARM_TRIGGER_WINDOW_MS &&
          diffMs < ALARM_MISS_MAX_AGE_MS
        ) {
          firedRef.current.add(fireKey);
          trackAlarmMissed(
            alarm.id,
            {
              next_trigger_at: alarm.next_trigger_at,
              delay_seconds: Math.round(diffMs / 1000),
            },
            fireKey
          );
        }
      }
    };

    checkAlarms();
    const interval = setInterval(checkAlarms, 5000);

    return () => clearInterval(interval);
  }, [alarms, isAuthenticated, isRinging, triggerAlarm]);
  
  return null;
}

function App() {
  return (
    <Router>
      <AlarmWatcher />
      <ActiveAlarmModal />
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: '#1e293b',
            color: '#e2e8f0',
            border: '1px solid #334155',
            borderRadius: '12px',
          },
          success: { iconTheme: { primary: '#10b981', secondary: '#1e293b' } },
          error: { iconTheme: { primary: '#ef4444', secondary: '#1e293b' } },
        }}
      />
      <Routes>
        {/* Guest Routes */}
        <Route path="/login" element={<GuestRoute><Login /></GuestRoute>} />
        <Route path="/register" element={<GuestRoute><Register /></GuestRoute>} />
        <Route path="/forgot-password" element={<GuestRoute><ForgotPassword /></GuestRoute>} />
        <Route path="/reset-password" element={<GuestRoute><ResetPassword /></GuestRoute>} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/oauth/callback" element={<OAuthCallback />} />

        {/* Protected Routes (inside Layout) */}
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<HomeRedirect />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="alarms" element={<AlarmManager />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="profile" element={<Profile />} />
          <Route path="admin" element={<AdminDashboard />} />
        </Route>

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
