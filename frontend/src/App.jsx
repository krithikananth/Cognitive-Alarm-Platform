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
import Dashboard from './pages/Dashboard';
import AlarmManager from './pages/AlarmManager';
import Profile from './pages/Profile';
import AdminDashboard from './pages/AdminDashboard';
import Layout from './components/Layout';

import ActiveAlarmModal from './components/ActiveAlarmModal';
import useAlarmStore from './store/alarmStore';
import useActiveAlarmStore from './store/activeAlarmStore';

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

// Component to watch time and trigger alarms
function AlarmWatcher() {
  const { alarms, fetchAlarms } = useAlarmStore();
  const { triggerAlarm, isRinging } = useActiveAlarmStore();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  
  // Fetch alarms initially
  React.useEffect(() => {
    if (isAuthenticated) fetchAlarms();
  }, [isAuthenticated, fetchAlarms]);
  
  // Check every 10 seconds if any alarm should ring
  React.useEffect(() => {
    if (!isAuthenticated || isRinging) return;
    
    const interval = setInterval(() => {
      const now = new Date();
      
      for (const alarm of alarms) {
        if (!alarm.is_active || !alarm.next_trigger_at) continue;
        
        const triggerTime = new Date(alarm.next_trigger_at);
        // If current time is past the trigger time (within 60 seconds to avoid stale triggers)
        const diffMs = now - triggerTime;
        if (diffMs >= 0 && diffMs < 60000) {
          triggerAlarm(alarm.id);
          break; // Only trigger one alarm at a time
        }
      }
    }, 10000);
    
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

        {/* Protected Routes (inside Layout) */}
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="alarms" element={<AlarmManager />} />
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
