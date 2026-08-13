/**
 * Notification bell icon with live unread badge + dropdown panel.
 *
 * Shows the most recent notifications inline. Clicking the bell toggles
 * a dropdown. Each notification can be marked as read. The panel also
 * links to a "Send Test" action for easy verification.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { HiOutlineBell, HiOutlineCheck, HiOutlineBeaker } from 'react-icons/hi2';
import { notificationAPI, hasActiveSession } from '../services/api';
import {
  requestNotificationPermission,
  getNotificationPermission,
  syncLocalPendingNotifications,
} from '../services/notificationService';
import toast from 'react-hot-toast';

/** Map notification_type → emoji + label */
const TYPE_META = {
  bedtime_reminder: { emoji: '🌙', label: 'Bedtime' },
  wake_reminder: { emoji: '⏰', label: 'Wake' },
  habit_alert: { emoji: '📉', label: 'Habit' },
  challenge_reminder: { emoji: '🧩', label: 'Challenge' },
  progress_update: { emoji: '📊', label: 'Progress' },
  motivational: { emoji: '💪', label: 'Motivation' },
  announcement: { emoji: '📢', label: 'Announcement' },
};

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const diffS = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diffS < 60) return 'just now';
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m ago`;
  if (diffS < 86400) return `${Math.floor(diffS / 3600)}h ago`;
  return `${Math.floor(diffS / 86400)}d ago`;
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [permStatus, setPermStatus] = useState('default');
  const [coords, setCoords] = useState({ top: 0, right: 0 });
  // Anchors the bell button; the dropdown itself is portaled to <body> so it
  // can never be trapped by an ancestor's stacking context (e.g. a
  // `backdrop-filter`/`.glass` header) or clipped by `overflow: hidden`.
  const anchorRef = useRef(null);
  const panelRef = useRef(null);

  // Close on outside click (checks both the bell button and the portaled panel)
  useEffect(() => {
    const handler = (e) => {
      if (
        anchorRef.current && !anchorRef.current.contains(e.target) &&
        (!panelRef.current || !panelRef.current.contains(e.target))
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Keep the portaled dropdown anchored to the bell icon's current position
  useEffect(() => {
    if (!open) return undefined;

    const updatePosition = () => {
      const btn = anchorRef.current;
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      setCoords({
        top: rect.bottom + 8,
        right: Math.max(8, window.innerWidth - rect.right),
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [open]);

  // Poll unread count every 30s — only when a session exists (avoids
  // startup 401s if Layout mounts briefly without a usable session).
  const fetchUnread = useCallback(async () => {
    if (!hasActiveSession()) return;
    try {
      const { data } = await notificationAPI.getUnreadCount();
      setUnreadCount(data.unread_count || 0);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchUnread();
    const interval = setInterval(fetchUnread, 30000);
    return () => clearInterval(interval);
  }, [fetchUnread]);

  // Check browser notification permission
  useEffect(() => {
    setPermStatus(getNotificationPermission());
  }, []);

  // Fetch notifications when panel opens
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    notificationAPI.getNotifications({ page: 1, per_page: 10 })
      .then(({ data }) => {
        setNotifications(data.notifications || []);
        setUnreadCount(data.unread_count || 0);
      })
      .catch(() => { })
      .finally(() => setLoading(false));
  }, [open]);

  const handleMarkRead = async (id) => {
    try {
      await notificationAPI.markRead({ notification_ids: [id] });
      setNotifications((prev) =>
        prev.map((n) =>
          n.id === id ? { ...n, read_at: new Date().toISOString(), status: 'read' } : n
        )
      );
      setUnreadCount((c) => Math.max(0, c - 1));
    } catch { /* silent */ }
  };

  const handleMarkAllRead = async () => {
    const unreadIds = notifications.filter((n) => !n.read_at).map((n) => n.id);
    if (!unreadIds.length) return;
    try {
      await notificationAPI.markRead({ notification_ids: unreadIds });
      setNotifications((prev) =>
        prev.map((n) => ({ ...n, read_at: new Date().toISOString(), status: 'read' }))
      );
      // Only the loaded page was marked, so ask the server for the remaining
      // count instead of assuming the badge is now empty.
      await fetchUnread();
    } catch { /* silent */ }
  };

  const handleSendTest = async () => {
    try {
      const { data } = await notificationAPI.sendTest();
      toast.success(`Test notification sent! (ID: ${data.notification_id})`);
      // Refresh the panel
      const { data: fresh } = await notificationAPI.getNotifications({ page: 1, per_page: 10 });
      setNotifications(fresh.notifications || []);
      setUnreadCount(fresh.unread_count || 0);
    } catch (err) {
      toast.error('Failed to send test notification');
    }
  };

  const handleEnablePush = async () => {
    const token = await requestNotificationPermission();
    if (token) {
      toast.success('Push notifications enabled!');
      setPermStatus('granted');
      await syncLocalPendingNotifications();
    } else if (Notification.permission === 'denied') {
      toast.error('Notifications blocked. Enable in browser settings.');
      setPermStatus('denied');
    } else if (Notification.permission === 'granted') {
      // Permission is granted but Firebase issued no token, so reminders are
      // scheduled in this tab only. The console carries the exact cause.
      toast('Reminders enabled for this tab — background push unavailable', {
        icon: 'ℹ️',
      });
      setPermStatus('granted');
      await syncLocalPendingNotifications();
    } else {
      toast.error('Could not enable notifications. Please try again.');
      setPermStatus(getNotificationPermission());
    }
  };

  return (
    <div ref={anchorRef} className="relative">
      {/* Bell Button */}
      <button
        id="notification-bell"
        onClick={() => setOpen((prev) => !prev)}
        className="p-2.5 rounded-xl hover:bg-surface-800 transition relative"
        aria-label="Notifications"
      >
        <HiOutlineBell className="w-5 h-5 text-slate-300" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-primary-500 text-[10px] font-bold text-white px-1 animate-pulse">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown Panel — portaled to <body> so it always paints above alarm
          cards, dialogs, drawers and other dashboard widgets, regardless of
          stacking contexts or overflow-hidden ancestors in the page tree. */}
      {open && createPortal(
        <div
          ref={panelRef}
          style={{
            position: 'fixed',
            top: coords.top,
            right: coords.right,
            maxWidth: 'calc(100vw - 1rem)',
          }}
          className="w-[380px] max-h-[480px] glass rounded-2xl shadow-2xl border border-surface-600/50 z-[9999] flex flex-col overflow-hidden animate-fade-in"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700/50">
            <h3 className="text-sm font-semibold text-white">Notifications</h3>
            <div className="flex items-center gap-2">
              {unreadCount > 0 && (
                <button
                  onClick={handleMarkAllRead}
                  className="text-xs text-primary-400 hover:text-primary-300 transition"
                >
                  Mark all read
                </button>
              )}
              <button
                onClick={handleSendTest}
                className="p-1.5 rounded-lg hover:bg-surface-700/50 transition"
                title="Send test notification"
              >
                <HiOutlineBeaker className="w-4 h-4 text-slate-400" />
              </button>
            </div>
          </div>

          {/* Enable Push Banner */}
          {permStatus !== 'granted' && permStatus !== 'unsupported' && (
            <div className="px-4 py-2.5 bg-primary-500/10 border-b border-primary-500/20">
              <button
                onClick={handleEnablePush}
                className="text-xs text-primary-300 hover:text-primary-200 font-medium transition"
              >
                🔔 Enable push notifications for reminders
              </button>
            </div>
          )}

          {/* Notification List */}
          <div className="flex-1 overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center py-8">
                <div className="w-5 h-5 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
              </div>
            )}

            {!loading && notifications.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 text-slate-500">
                <HiOutlineBell className="w-8 h-8 mb-2 opacity-50" />
                <p className="text-sm">No notifications yet</p>
                <button
                  onClick={handleSendTest}
                  className="mt-3 text-xs text-primary-400 hover:text-primary-300 transition"
                >
                  Send a test notification →
                </button>
              </div>
            )}

            {!loading && notifications.map((notif) => {
              const meta = TYPE_META[notif.notification_type] || { emoji: '🔔', label: 'Alert' };
              const isUnread = !notif.read_at;

              return (
                <div
                  key={notif.id}
                  className={`flex items-start gap-3 px-4 py-3 border-b border-surface-700/30 transition hover:bg-surface-700/20 ${isUnread ? 'bg-primary-500/5' : ''
                    }`}
                >
                  {/* Type Icon */}
                  <div className="w-9 h-9 rounded-xl bg-surface-700/50 flex items-center justify-center text-lg flex-shrink-0 mt-0.5">
                    {meta.emoji}
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[10px] uppercase tracking-wider text-slate-500 font-medium">
                        {meta.label}
                      </span>
                      <span className="text-[10px] text-slate-600">
                        {timeAgo(notif.sent_at || notif.scheduled_at)}
                      </span>
                      {isUnread && (
                        <span className="w-1.5 h-1.5 rounded-full bg-primary-400 flex-shrink-0" />
                      )}
                    </div>
                    <p className="text-sm font-medium text-slate-200 leading-tight">
                      {notif.title}
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5 line-clamp-2">
                      {notif.body}
                    </p>
                  </div>

                  {/* Mark Read Button */}
                  {isUnread && (
                    <button
                      onClick={() => handleMarkRead(notif.id)}
                      className="p-1.5 rounded-lg hover:bg-surface-700/50 transition flex-shrink-0 mt-1"
                      title="Mark as read"
                    >
                      <HiOutlineCheck className="w-3.5 h-3.5 text-slate-500 hover:text-primary-400" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {/* Footer */}
          {notifications.length > 0 && (
            <div className="px-4 py-2.5 border-t border-surface-700/50 text-center">
              <span className="text-[11px] text-slate-500">
                {unreadCount > 0 ? `${unreadCount} unread` : 'All caught up ✓'}
              </span>
            </div>
          )}
        </div>,
        document.body
      )}
    </div>
  );
}
