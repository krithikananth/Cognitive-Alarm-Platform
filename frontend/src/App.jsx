/**
 * Main App component with routing.
 */
import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import useAuthStore from './store/authStore';

// Pages.
// Every page is a separate webpack chunk: a visitor on /login must not download
// the charting library that only the dashboards use. Login is the one eager
// page because it is the landing route for an anonymous visitor, so lazily
// loading it would only add a round trip to first paint.
import Login from './pages/Login';
import PageFallback from './components/PageFallback';

const Register = React.lazy(() => import('./pages/Register'));
const ForgotPassword = React.lazy(() => import('./pages/ForgotPassword'));
const ResetPassword = React.lazy(() => import('./pages/ResetPassword'));
const VerifyEmail = React.lazy(() => import('./pages/VerifyEmail'));
const OAuthCallback = React.lazy(() => import('./pages/OAuthCallback'));
const UserDashboard = React.lazy(() => import('./pages/UserDashboard'));
const WellnessCoachDashboard = React.lazy(() => import('./pages/WellnessCoachDashboard'));
const AlarmManager = React.lazy(() => import('./pages/AlarmManager'));
const Profile = React.lazy(() => import('./pages/Profile'));
const Analytics = React.lazy(() => import('./pages/Analytics'));
const Recommendations = React.lazy(() => import('./pages/Recommendations'));
const Reports = React.lazy(() => import('./pages/Reports'));
const AdminDashboard = React.lazy(() => import('./pages/AdminDashboard'));
const PracticeChallenge = React.lazy(() => import('./pages/PracticeChallenge'));
const AccessDenied = React.lazy(() => import('./pages/AccessDenied'));
const NotFound = React.lazy(() => import('./pages/NotFound'));

import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';

import ActiveAlarmModal from './components/ActiveAlarmModal';
import { trackAlarmMissed } from './services/analyticsTracker';
import { hasActiveSession } from './services/api';
import useAlarmStore from './store/alarmStore';
import useActiveAlarmStore from './store/activeAlarmStore';
import {
  ROLES,
  ACCESS_DENIED_PATH,
  homePathForRole,
  hasRouteAccess,
} from './utils/routeAccess';

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
    return <Navigate to={homePathForRole(user?.role)} replace />;
  }
  return children;
}

// Authenticated home: admins land on Admin Panel, coaches on their roster
function HomeRedirect() {
  const user = useAuthStore((s) => s.user);
  return <Navigate to={homePathForRole(user?.role)} replace />;
}

// Coaches have their own dashboard, so /dashboard is not theirs to open.
function DashboardRoute() {
  const user = useAuthStore((s) => s.user);
  if (user?.role === ROLES.WELLNESS_COACH) {
    return <Navigate to={homePathForRole(user.role)} replace />;
  }
  return <UserDashboard />;
}

// Role-gated route: redirects before the restricted page can mount or call its
// APIs. Authentication itself stays with the surrounding ProtectedRoute.
function RoleRoute({ allowedRoles, children }) {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  if (!hasRouteAccess(user?.role, allowedRoles)) {
    return (
      <Navigate
        to={ACCESS_DENIED_PATH}
        replace
        state={{ from: location.pathname }}
      />
    );
  }
  return children;
}

// Component to watch time and trigger alarms
function AlarmWatcher() {
  const { alarms, fetchAlarms } = useAlarmStore();
  const { triggerAlarm, isRinging } = useActiveAlarmStore();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const firedRef = React.useRef(new Set());
  const location = useLocation();
  const navigate = useNavigate();

  // Deep link from a server-dispatched alarm push (/alarms?ring=<id>).
  // The push is what makes a ring survive a closed tab; landing here hands the
  // user to the exact same wake cycle the in-page watcher starts.
  React.useEffect(() => {
    if (!isAuthenticated) return;
    const ringId = Number(new URLSearchParams(location.search).get('ring'));
    if (!ringId) return;

    navigate(location.pathname, { replace: true });
    if (!useActiveAlarmStore.getState().isRinging) {
      triggerAlarm(ringId);
    }
  }, [isAuthenticated, location.pathname, location.search, navigate, triggerAlarm]);

  // Fetch alarms initially and refresh every 30 seconds.
  // Require an active session marker so we don't hit /alarms/ before login
  // finishes (or after a failed refresh cleared the session).
  React.useEffect(() => {
    if (!isAuthenticated || !hasActiveSession()) return undefined;
    fetchAlarms();
    const refreshInterval = setInterval(() => {
      if (hasActiveSession()) {
        fetchAlarms();
      }
    }, 30000);
    return () => clearInterval(refreshInterval);
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

// Keeps a render failure inside the page that caused it. Re-keying on the
// pathname clears the fallback as soon as the user navigates elsewhere, so a
// single broken route can never trap the session.
function RoutedErrorBoundary({ children }) {
  const location = useLocation();
  return (
    <ErrorBoundary name="route" resetKey={location.pathname}>
      {children}
    </ErrorBoundary>
  );
}

function App() {
  return (
    <Router>
      <AlarmWatcher />
      {/* Its own boundary: the ringing modal renders outside the routed tree,
          so a crash here would otherwise take the whole app down with it. */}
      <ErrorBoundary name="active-alarm" fallback={null}>
        <ActiveAlarmModal />
      </ErrorBoundary>
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
      <RoutedErrorBoundary>
        {/* Guest/standalone routes suspend here. Routes inside Layout have
            their own boundary around <Outlet />, so navigating between pages
            never blanks the app shell. */}
        <React.Suspense fallback={<PageFallback />}>
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
              <Route path="dashboard" element={<DashboardRoute />} />
              <Route
                path="wellness"
                element={
                  <RoleRoute allowedRoles={[ROLES.WELLNESS_COACH]}>
                    <WellnessCoachDashboard />
                  </RoleRoute>
                }
              />
              <Route path="practice" element={<PracticeChallenge />} />
              <Route path="alarms" element={<AlarmManager />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="recommendations" element={<Recommendations />} />
              <Route path="reports" element={<Reports />} />
              <Route path="profile" element={<Profile />} />
              <Route
                path="admin"
                element={
                  <RoleRoute allowedRoles={[ROLES.ADMIN]}>
                    <AdminDashboard />
                  </RoleRoute>
                }
              />
              <Route path="access-denied" element={<AccessDenied />} />

              {/* Unmatched routes: 404 inside the app shell. Guests still hit
                ProtectedRoute first and are sent to /login. */}
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </React.Suspense>
      </RoutedErrorBoundary>
    </Router>
  );
}

export default App;
