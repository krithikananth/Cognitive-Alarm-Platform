/**
 * AdminDashboard — admin-only page showing platform stats and user management.
 * Platform analysis loads exclusively from /admin/* APIs with date filters
 * and automatic refresh so metrics and charts stay in sync with the backend.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineUsers, HiOutlineClock, HiOutlineShieldCheck,
  HiOutlineExclamationTriangle,
  HiOutlineChartBar, HiOutlineBellAlert, HiOutlineSparkles,
  HiOutlineHeart, HiOutlineServerStack, HiOutlineDocumentChartBar,
  HiOutlineUserGroup, HiOutlineCheckCircle, HiOutlineCalendarDays,
  HiOutlineArrowPath, HiOutlineArrowDownTray, HiOutlineFire,
  HiOutlineGlobeAlt, HiOutlineCog6Tooth, HiOutlineMegaphone,
  HiOutlineWrenchScrewdriver,
} from 'react-icons/hi2';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import toast from 'react-hot-toast';
import { adminAPI, readErrorDetail } from '../services/api';
import { formatHabitScore } from '../utils/habitScore';
import AdminUserManagement from '../components/AdminUserManagement';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const PRESETS = [
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
];

const AUTO_REFRESH_MS = 60_000;

const SYSTEM_REPORT_ICONS = {
  user: HiOutlineUsers,
  alarm: HiOutlineBellAlert,
  habit: HiOutlineFire,
  platform: HiOutlineGlobeAlt,
};

const SYSTEM_REPORT_FALLBACK = [
  { type: 'user', title: 'User Report', description: 'User growth and engagement' },
  { type: 'alarm', title: 'Alarm Report', description: 'Alarm activity and inventory' },
  { type: 'habit', title: 'Habit Report', description: 'Habit scores and streaks' },
  { type: 'platform', title: 'Platform Report', description: 'Cross-cutting platform health' },
];

const BREAKDOWN_LABELS = {
  wake_up_consistency: 'Wake Consistency',
  challenge_completion: 'Challenge Completion',
  snooze_reduction: 'Snooze Reduction',
  sleep_adherence: 'Sleep Adherence',
};

function isHabitScoreKey(key) {
  return key === 'habit_score' || key === 'current_habit_score'
    || key === 'avg_habit_score' || key === 'min_habit_score'
    || key === 'max_habit_score' || key.endsWith('_habit_score');
}

function formatMetricValue(key, value) {
  if (value === null || value === undefined) return '—';
  if (isHabitScoreKey(key)) return formatHabitScore(value);
  if (typeof value === 'number') {
    if (String(key).endsWith('_pct') || String(key).includes('rate_pct')) {
      return `${Number(value).toFixed(1)}%`;
    }
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return null;
  return String(value);
}

function ReportSummaryGrid({ summary }) {
  if (!summary) return null;
  const entries = Object.entries(summary).filter(([, v]) => {
    if (v === null || v === undefined) return true;
    return typeof v !== 'object';
  });
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="rounded-xl border border-surface-700/50 bg-surface-900/40 px-4 py-3"
        >
          <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
            {key.replace(/_/g, ' ')}
          </p>
          <p className="text-lg font-semibold text-white">
            {formatMetricValue(key, value)}
          </p>
        </div>
      ))}
    </div>
  );
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(1)}%`;
}

function num(value, decimals = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(decimals);
}

function DistList({ data, emptyLabel = 'No data' }) {
  const entries = Object.entries(data || {});
  if (!entries.length) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>;
  }
  const total = entries.reduce((sum, [, v]) => sum + (Number(v) || 0), 0) || 1;
  return (
    <div className="space-y-2">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center gap-3">
          <span className="text-xs text-slate-400 w-28 truncate capitalize">
            {(key || 'unknown').replace(/_/g, ' ')}
          </span>
          <div className="flex-1 h-2 rounded-full bg-surface-800 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-primary-500 to-accent-500"
              style={{ width: `${Math.min(100, (Number(value) / total) * 100)}%` }}
            />
          </div>
          <span className="text-xs text-white font-medium w-8 text-right">{value}</span>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value, hint }) {
  return (
    <div className="rounded-xl bg-surface-900/50 border border-surface-700/30 px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-semibold text-white">{value}</p>
      {hint ? <p className="text-[11px] text-slate-500 mt-0.5">{hint}</p> : null}
    </div>
  );
}

function SectionCard({ icon: Icon, title, subtitle, children, delay = 0.2 }) {
  return (
    <motion.div {...fadeUp} transition={{ delay }} className="card">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Icon className="w-5 h-5 text-primary-400" />
          {title}
        </h2>
        {subtitle ? <p className="text-sm text-slate-400 mt-1">{subtitle}</p> : null}
      </div>
      {children}
    </motion.div>
  );
}

function AdminToggleRow({ label, description, checked, onChange, disabled = false }) {
  return (
    <label
      className={`flex items-start justify-between gap-4 py-2 ${
        disabled ? 'opacity-50' : 'cursor-pointer'
      }`}
    >
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-200">{label}</p>
        {description ? (
          <p className="text-xs text-slate-500 mt-0.5">{description}</p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
          checked ? 'bg-primary-500' : 'bg-surface-600'
        } disabled:cursor-not-allowed`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </label>
  );
}

function ThresholdInput({ label, value, onChange, hint }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1.5">{label}</label>
      <input
        type="number"
        min={0}
        max={100}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="input w-full"
      />
      {hint ? <p className="text-[11px] text-slate-500 mt-1">{hint}</p> : null}
    </div>
  );
}

function NotificationSettingsPanel() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [broadcasting, setBroadcasting] = useState(false);
  const [settings, setSettings] = useState(null);
  const [announceTitle, setAnnounceTitle] = useState('');
  const [announceBody, setAnnounceBody] = useState('');
  const [sendPush, setSendPush] = useState(true);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await adminAPI.getNotificationSettings();
      setSettings(data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to load notification settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const updateField = (key, value) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const payload = {
        email_notifications_enabled: !!settings.email_notifications_enabled,
        push_notifications_enabled: !!settings.push_notifications_enabled,
        maintenance_mode: !!settings.maintenance_mode,
        maintenance_message: settings.maintenance_message || undefined,
        habit_score_alert_threshold: Number(settings.habit_score_alert_threshold),
        consistency_alert_threshold: Number(settings.consistency_alert_threshold),
        snooze_alert_threshold: Number(settings.snooze_alert_threshold),
      };
      const { data } = await adminAPI.updateNotificationSettings(payload);
      setSettings(data);
      toast.success('Notification settings saved');
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleBroadcast = async () => {
    const title = announceTitle.trim();
    const body = announceBody.trim();
    if (!title || !body) {
      toast.error('Announcement title and body are required');
      return;
    }
    setBroadcasting(true);
    try {
      const { data } = await adminAPI.broadcastAnnouncement({
        title,
        body,
        send_push: sendPush,
      });
      toast.success(
        `Broadcast sent to ${data.users_targeted} user${data.users_targeted === 1 ? '' : 's'}`,
      );
      setAnnounceTitle('');
      setAnnounceBody('');
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Broadcast failed');
    } finally {
      setBroadcasting(false);
    }
  };

  if (loading) {
    return (
      <SectionCard
        icon={HiOutlineCog6Tooth}
        title="Notification Settings"
        subtitle="Platform-wide email, push, maintenance, and alert thresholds"
        delay={0.27}
      >
        <p className="text-sm text-slate-500">Loading settings…</p>
      </SectionCard>
    );
  }

  if (!settings) {
    return (
      <SectionCard
        icon={HiOutlineCog6Tooth}
        title="Notification Settings"
        subtitle="Platform-wide email, push, maintenance, and alert thresholds"
        delay={0.27}
      >
        <button type="button" onClick={loadSettings} className="btn-secondary">
          Retry
        </button>
      </SectionCard>
    );
  }

  return (
    <SectionCard
      icon={HiOutlineCog6Tooth}
      title="Notification Settings"
      subtitle="Platform-wide email, push, maintenance, and alert thresholds"
      delay={0.27}
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Channel + maintenance toggles */}
        <div className="space-y-1 rounded-xl border border-surface-700/40 bg-surface-900/40 px-4 py-3">
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Channels</p>
          <AdminToggleRow
            label="Email Notifications"
            description={
              settings.smtp_configured
                ? 'Global kill-switch for the email channel'
                : 'SMTP not configured — toggle still saved for when email is ready'
            }
            checked={!!settings.email_notifications_enabled}
            onChange={(v) => updateField('email_notifications_enabled', v)}
          />
          <AdminToggleRow
            label="Push Notifications"
            description={
              settings.fcm_available
                ? 'Global kill-switch for FCM push delivery'
                : 'FCM unavailable — toggle still gates push queue processing'
            }
            checked={!!settings.push_notifications_enabled}
            onChange={(v) => updateField('push_notifications_enabled', v)}
          />
          <div className="border-t border-surface-700/40 my-2 pt-2">
            <p className="text-xs uppercase tracking-wider text-slate-500 mb-2 flex items-center gap-1.5">
              <HiOutlineWrenchScrewdriver className="w-3.5 h-3.5" />
              Maintenance
            </p>
            <AdminToggleRow
              label="Maintenance Mode"
              description="Blocks non-admin write requests and shows the status message"
              checked={!!settings.maintenance_mode}
              onChange={(v) => updateField('maintenance_mode', v)}
            />
            <div className="mt-2">
              <label className="block text-xs text-slate-400 mb-1.5">Maintenance message</label>
              <input
                type="text"
                value={settings.maintenance_message || ''}
                onChange={(e) => updateField('maintenance_message', e.target.value)}
                className="input w-full"
                placeholder="Scheduled maintenance message"
                maxLength={500}
              />
            </div>
          </div>
        </div>

        {/* Alert thresholds */}
        <div className="space-y-3 rounded-xl border border-surface-700/40 bg-surface-900/40 px-4 py-3">
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-1">
            System alert thresholds
          </p>
          <p className="text-xs text-slate-500 mb-3">
            Habit alerts fire when a metric falls below these scores (0–100).
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <ThresholdInput
              label="Habit score"
              value={settings.habit_score_alert_threshold ?? 30}
              onChange={(v) => updateField('habit_score_alert_threshold', v)}
              hint="Overall habit score"
            />
            <ThresholdInput
              label="Consistency"
              value={settings.consistency_alert_threshold ?? 30}
              onChange={(v) => updateField('consistency_alert_threshold', v)}
              hint="Wake-up consistency"
            />
            <ThresholdInput
              label="Snooze reduction"
              value={settings.snooze_alert_threshold ?? 30}
              onChange={(v) => updateField('snooze_alert_threshold', v)}
              hint="Snooze discipline"
            />
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="btn-primary disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save Settings'}
        </button>
        <button
          type="button"
          onClick={loadSettings}
          disabled={saving}
          className="btn-secondary disabled:opacity-50"
        >
          Reset
        </button>
        {settings.updated_at ? (
          <span className="text-xs text-slate-500">
            Last saved {new Date(settings.updated_at).toLocaleString()}
          </span>
        ) : null}
      </div>

      {/* Broadcast */}
      <div className="mt-6 pt-5 border-t border-surface-700/50">
        <div className="flex items-center gap-2 mb-3">
          <HiOutlineMegaphone className="w-4 h-4 text-primary-400" />
          <h3 className="text-sm font-semibold text-white">Broadcast announcement</h3>
        </div>
        <p className="text-xs text-slate-500 mb-3">
          Sends an in-app notification to every active user. Optionally queues push when global push is enabled.
        </p>
        <div className="space-y-3">
          <input
            type="text"
            value={announceTitle}
            onChange={(e) => setAnnounceTitle(e.target.value)}
            className="input w-full"
            placeholder="Announcement title"
            maxLength={255}
          />
          <textarea
            value={announceBody}
            onChange={(e) => setAnnounceBody(e.target.value)}
            rows={3}
            className="input w-full resize-none"
            placeholder="Announcement message"
            maxLength={2000}
          />
          <AdminToggleRow
            label="Also send push"
            description="Queue push channel when global push notifications are enabled"
            checked={sendPush}
            onChange={setSendPush}
            disabled={!settings.push_notifications_enabled}
          />
          <button
            type="button"
            onClick={handleBroadcast}
            disabled={broadcasting}
            className="btn-secondary disabled:opacity-50"
          >
            {broadcasting ? 'Broadcasting…' : 'Broadcast to all users'}
          </button>
        </div>
      </div>
    </SectionCard>
  );
}

function ChartPanel({ chartKey, data, dataKey, xKey, fill, emptyLabel, height = 'h-40' }) {
  if (!data?.length) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>;
  }
  return (
    <div className={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart key={chartKey} data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
          <XAxis
            dataKey={xKey}
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            tickFormatter={(v) => (xKey === 'date' ? String(v).slice(5) : v)}
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={32} allowDecimals={false} />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 8,
            }}
          />
          <Bar dataKey={dataKey} fill={fill} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function AdminDashboard() {
  const [data, setData] = useState(null);
  const [statistics, setStatistics] = useState(null);
  const [alarms, setAlarms] = useState(null);
  const [recommendations, setRecommendations] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [reports, setReports] = useState(null);
  const [systemReportTypes, setSystemReportTypes] = useState([]);
  const [systemReportType, setSystemReportType] = useState('user');
  const [systemReport, setSystemReport] = useState(null);
  const [systemReportLoading, setSystemReportLoading] = useState(false);
  const [exporting, setExporting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  const [days, setDays] = useState(30);
  const [useCustomRange, setUseCustomRange] = useState(false);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);

  const requestIdRef = useRef(0);

  const dateParams = useMemo(() => {
    if (useCustomRange && startDate && endDate) {
      return { start_date: startDate, end_date: endDate };
    }
    return { days };
  }, [useCustomRange, startDate, endDate, days]);

  const periodLabel = useMemo(() => {
    if (useCustomRange && startDate && endDate) {
      return `${startDate} → ${endDate}`;
    }
    return `Last ${days} days`;
  }, [useCustomRange, startDate, endDate, days]);

  const chartKey = useMemo(
    () =>
      useCustomRange && startDate && endDate
        ? `custom-${startDate}-${endDate}-${lastUpdated || 0}`
        : `days-${days}-${lastUpdated || 0}`,
    [useCustomRange, startDate, endDate, days, lastUpdated],
  );

  const loadDashboard = useCallback(async ({ silent = false } = {}) => {
    if (useCustomRange && (!startDate || !endDate)) {
      return;
    }

    const requestId = ++requestIdRef.current;
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const [dashRes, statsRes, alarmsRes, recsRes, analyticsRes, reportsRes] =
        await Promise.all([
          adminAPI.getDashboard(dateParams),
          adminAPI.getStatistics(dateParams),
          adminAPI.getAlarms(dateParams),
          adminAPI.getRecommendations(dateParams),
          adminAPI.getAnalytics(dateParams),
          adminAPI.getReports(),
        ]);
      if (requestId !== requestIdRef.current) return;

      setData(dashRes.data);
      setStatistics(statsRes.data);
      setAlarms(alarmsRes.data);
      setRecommendations(recsRes.data);
      setAnalytics(analyticsRes.data);
      setReports(reportsRes.data);
      setError(null);
      setLastUpdated(Date.now());
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      setError(err.response?.data?.detail || 'Failed to load admin dashboard');
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [dateParams, useCustomRange, startDate, endDate]);

  const loadSystemReport = useCallback(async () => {
    if (!systemReportType) return;
    if (useCustomRange && (!startDate || !endDate)) return;

    setSystemReportLoading(true);
    try {
      const { data } = await adminAPI.getSystemReport(systemReportType, dateParams);
      setSystemReport(data);
    } catch (err) {
      toast.error(await readErrorDetail(err, 'Failed to load system report'));
      setSystemReport(null);
    } finally {
      setSystemReportLoading(false);
    }
  }, [systemReportType, dateParams, useCustomRange, startDate, endDate]);

  const handleExportSystemReport = async (format) => {
    if (!systemReportType) return;
    if (useCustomRange && (!startDate || !endDate)) {
      toast.error('Select both start and end dates');
      return;
    }
    setExporting(format);
    try {
      const res = await adminAPI.exportSystemReport(
        systemReportType,
        format,
        dateParams,
      );
      const blob = new Blob([res.data], { type: res.headers['content-type'] });
      const disposition = res.headers['content-disposition'] || '';
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename =
        match?.[1]
        || `icap_${systemReportType}_report.${format === 'pdf' ? 'pdf' : 'xlsx'}`;
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`${format.toUpperCase()} downloaded`);
    } catch (err) {
      toast.error(await readErrorDetail(err, 'Export failed'));
    } finally {
      setExporting(null);
    }
  };

  // Initial load + reload when date filters change
  useEffect(() => {
    loadDashboard({ silent: Boolean(data) });
  }, [loadDashboard]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await adminAPI.listSystemReports();
        if (!cancelled) {
          setSystemReportTypes(data?.reports || SYSTEM_REPORT_FALLBACK);
        }
      } catch {
        if (!cancelled) setSystemReportTypes(SYSTEM_REPORT_FALLBACK);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    loadSystemReport();
  }, [loadSystemReport]);

  // Automatic refresh of platform analysis
  useEffect(() => {
    if (!autoRefresh) return undefined;
    const id = window.setInterval(() => {
      loadDashboard({ silent: true });
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [autoRefresh, loadDashboard]);

  // ─── Loading State (first paint only) ───
  if (loading && !data) {
    return (
      <div className="max-w-7xl mx-auto flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-primary-500/30 border-t-primary-500 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400">Loading admin dashboard…</p>
        </div>
      </div>
    );
  }

  // ─── Error State ───
  if (error && !data) {
    return (
      <div className="max-w-7xl mx-auto flex items-center justify-center min-h-[60vh]">
        <div className="text-center card max-w-md">
          <HiOutlineExclamationTriangle className="w-12 h-12 text-red-400 mx-auto mb-4" />
          <h2 className="text-lg font-semibold text-white mb-2">Access Denied</h2>
          <p className="text-slate-400">{error}</p>
        </div>
      </div>
    );
  }

  const users = data?.users || [];
  const totalUsers = data?.total_users ?? users.length;
  const totalAlarms = data?.total_alarms ?? 0;
  const engagement = data?.engagement || {};
  const habitOverview = recommendations?.habit_score_overview || {};
  const habitBreakdown = habitOverview.avg_breakdown || {};
  const integrity = reports?.data_integrity || {};
  const last24h = reports?.last_24h || {};
  const system = reports?.system || {};
  const periodActivity = alarms?.period_activity || {};
  const periodDays =
    data?.period?.days ??
    analytics?.period_days ??
    statistics?.period_days ??
    days;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* ─── Header ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0 }} className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <HiOutlineShieldCheck className="w-6 h-6 text-primary-400" />
            <h1 className="text-2xl font-bold text-white font-display">Admin Dashboard</h1>
          </div>
          <p className="text-slate-400">Manage users and monitor platform activity</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-slate-500">{periodLabel}</span>
          {lastUpdated ? (
            <span className="text-xs text-slate-500">
              Updated {new Date(lastUpdated).toLocaleTimeString()}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => loadDashboard({ silent: true })}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-50"
          >
            <HiOutlineArrowPath className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </motion.div>

      {/* ─── Date range + auto-refresh ─── */}
      <motion.div
        {...fadeUp}
        transition={{ delay: 0.05 }}
        className="rounded-2xl border border-surface-700/40 bg-surface-900/40 p-4 md:p-5 space-y-4"
      >
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-slate-300 text-sm font-medium">
            <HiOutlineCalendarDays className="w-4 h-4" />
            Platform analysis date filter
          </div>
          <label className="inline-flex items-center gap-2 text-sm text-slate-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-surface-600 bg-surface-900 text-primary-500 focus:ring-primary-500/40"
            />
            Auto-refresh every 60s
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.days}
              type="button"
              onClick={() => {
                setUseCustomRange(false);
                setDays(p.days);
              }}
              className={`px-3 py-1.5 rounded-lg text-sm border transition ${
                !useCustomRange && days === p.days
                  ? 'bg-primary-600/20 border-primary-500/40 text-primary-200'
                  : 'border-surface-600 text-slate-400 hover:text-white'
              }`}
            >
              {p.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setUseCustomRange(true)}
            className={`px-3 py-1.5 rounded-lg text-sm border transition ${
              useCustomRange
                ? 'bg-primary-600/20 border-primary-500/40 text-primary-200'
                : 'border-surface-600 text-slate-400 hover:text-white'
            }`}
          >
            Custom range
          </button>
        </div>

        {useCustomRange && (
          <div className="flex flex-wrap gap-3 items-end">
            <label className="text-sm text-slate-400">
              Start
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="mt-1 block rounded-lg bg-surface-900 border border-surface-600 px-3 py-2 text-white"
              />
            </label>
            <label className="text-sm text-slate-400">
              End
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="mt-1 block rounded-lg bg-surface-900 border border-surface-600 px-3 py-2 text-white"
              />
            </label>
            {useCustomRange && (!startDate || !endDate) ? (
              <p className="text-xs text-amber-400 pb-2">Select both start and end dates</p>
            ) : null}
          </div>
        )}

        {error && data ? (
          <p className="text-sm text-amber-400">{error}</p>
        ) : null}
      </motion.div>

      {/* ─── Stats Row ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.1 }} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={HiOutlineUsers}
          label="Total Users"
          value={totalUsers}
          color="from-primary-500 to-primary-700"
        />
        <StatCard
          icon={HiOutlineClock}
          label="Total Alarms"
          value={totalAlarms}
          color="from-accent-500 to-accent-700"
        />
        <StatCard
          icon={HiOutlineShieldCheck}
          label="Admin Users"
          value={users.filter((u) => u.role === 'admin').length}
          color="from-emerald-500 to-teal-600"
        />
        <StatCard
          icon={HiOutlineUsers}
          label="Active Users"
          value={data?.active_users ?? users.filter((u) => u.is_active !== false).length}
          color="from-orange-500 to-red-600"
        />
      </motion.div>

      {/* ─── User Analytics + Active Users ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SectionCard
          icon={HiOutlineChartBar}
          title="User Analytics"
          subtitle={`Growth and engagement over ${periodDays} days`}
          delay={0.15}
        >
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Metric label="New Users" value={data?.new_users_in_period ?? 0} />
            <Metric
              label="Growth Rate"
              value={pct(data?.user_growth_rate_pct)}
              hint={`Prev period: ${data?.new_users_previous_period ?? 0}`}
            />
            <Metric
              label="Engaged Users"
              value={engagement.engaged_users ?? 0}
              hint={pct(engagement.engagement_rate_pct)}
            />
            <Metric
              label="Verified Users"
              value={data?.verified_users ?? 0}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Metric label="Wake Events" value={engagement.wake_events ?? 0} />
            <Metric label="Wake Success" value={pct(engagement.wake_success_rate_pct)} />
            <Metric label="Challenges" value={engagement.challenge_attempts ?? 0} />
            <Metric label="Challenge Accuracy" value={pct(engagement.challenge_accuracy_pct)} />
          </div>
          <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Registration Trend</p>
          <ChartPanel
            chartKey={`reg-${chartKey}`}
            data={statistics?.registration_trend}
            dataKey="registrations"
            xKey="date"
            fill="#818cf8"
            emptyLabel="No registrations in this period."
          />
        </SectionCard>

        <SectionCard
          icon={HiOutlineUserGroup}
          title="Active Users"
          subtitle="Role mix and top performers"
          delay={0.18}
        >
          <div className="mb-4">
            <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Role Distribution</p>
            <DistList data={data?.role_distribution} emptyLabel="No roles found" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Top Performers</p>
            {(data?.top_performers || []).length === 0 ? (
              <p className="text-sm text-slate-500">No verified wakes in this period.</p>
            ) : (
              <div className="space-y-2">
                {data.top_performers.map((p) => (
                  <div
                    key={p.user_id}
                    className="flex items-center justify-between rounded-lg bg-surface-900/40 px-3 py-2"
                  >
                    <div>
                      <p className="text-sm text-white font-medium">{p.username}</p>
                      <p className="text-[11px] text-slate-500">{p.email}</p>
                    </div>
                    <span className="text-sm text-emerald-400 font-semibold">
                      {p.verified_wakes} wakes
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </SectionCard>
      </div>

      {/* ─── Alarm Statistics + Habit Score ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SectionCard
          icon={HiOutlineBellAlert}
          title="Alarm Statistics"
          subtitle="Platform-wide alarm configuration and activity"
          delay={0.2}
        >
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Metric label="Active Alarms" value={alarms?.active_alarms ?? 0} />
            <Metric label="Inactive Alarms" value={alarms?.inactive_alarms ?? 0} />
            <Metric label="Period Wakes" value={periodActivity.wake_events ?? 0} />
            <Metric label="Success Rate" value={pct(periodActivity.success_rate_pct)} />
            <Metric label="Snoozes" value={periodActivity.snooze_events ?? 0} />
            <Metric label="Snooze / Wake" value={num(periodActivity.snooze_per_wake, 2)} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Alarm Types</p>
              <DistList data={alarms?.type_distribution} />
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Challenge Types</p>
              <DistList data={alarms?.challenge_type_distribution} />
            </div>
          </div>
        </SectionCard>

        <SectionCard
          icon={HiOutlineHeart}
          title="Habit Score Overview"
          subtitle="Platform habit-score distribution and components"
          delay={0.22}
        >
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Metric label="Avg Score" value={formatHabitScore(habitOverview.avg_habit_score)} />
            <Metric label="Max Score" value={formatHabitScore(habitOverview.max_habit_score)} />
            <Metric label="≥ 70" value={habitOverview.users_above_70 ?? 0} />
            <Metric label="< 40" value={habitOverview.users_below_40 ?? 0} />
          </div>
          <div className="space-y-2">
            {Object.keys(BREAKDOWN_LABELS).map((key) => (
              <div key={key} className="flex items-center gap-3">
                <span className="text-xs text-slate-400 w-36">{BREAKDOWN_LABELS[key]}</span>
                <div className="flex-1 h-2 rounded-full bg-surface-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400"
                    style={{ width: `${Math.min(100, Number(habitBreakdown[key] || 0))}%` }}
                  />
                </div>
                <span className="text-xs text-white font-medium w-10 text-right">
                  {num(habitBreakdown[key], 0)}
                </span>
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      {/* ─── Recommendation Statistics + Platform Analytics ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SectionCard
          icon={HiOutlineSparkles}
          title="Recommendation Statistics"
          subtitle="Signals that drive coaching recommendations"
          delay={0.24}
        >
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Metric label="Profiles" value={recommendations?.total_profiles ?? 0} />
            <Metric
              label="With Goals"
              value={recommendations?.signal_summary?.users_with_goals ?? 0}
            />
            <Metric
              label="Avg Streak"
              value={num(recommendations?.streak_summary?.avg_current_streak, 1)}
            />
            <Metric
              label="Avg Consistency"
              value={num(recommendations?.consistency_summary?.avg_consistency_score, 1)}
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Preferred Difficulty</p>
              <DistList data={recommendations?.difficulty_distribution?.user_preference} />
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Adapted Difficulty</p>
              <DistList data={recommendations?.difficulty_distribution?.adapted} />
            </div>
          </div>
        </SectionCard>

        <SectionCard
          icon={HiOutlineDocumentChartBar}
          title="Platform Analytics"
          subtitle="Ingested analytics events across the platform"
          delay={0.26}
        >
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Metric label="Events (Period)" value={analytics?.events_in_period ?? 0} />
            <Metric label="All-Time Events" value={analytics?.total_events_all_time ?? 0} />
            <Metric label="Unique Users" value={analytics?.unique_users ?? 0} />
            <Metric label="Avg / Day" value={num(analytics?.avg_events_per_day, 1)} />
          </div>
          <ChartPanel
            chartKey={`ingest-${chartKey}`}
            data={analytics?.ingestion_trend}
            dataKey="events"
            xKey="date"
            fill="#818cf8"
            emptyLabel="No analytics events in this period."
          />
          <div className="mt-4">
            <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">By Source</p>
            <DistList data={analytics?.by_source} emptyLabel="No source breakdown" />
          </div>
        </SectionCard>
      </div>

      {/* ─── Notification Settings ─── */}
      <NotificationSettingsPanel />

      {/* ─── System Health ─── */}
      <SectionCard
        icon={HiOutlineServerStack}
        title="System Health"
        subtitle="Runtime status and data integrity"
        delay={0.28}
      >
        <div className="flex items-center gap-2 mb-4">
          <HiOutlineCheckCircle
            className={`w-5 h-5 ${
              (integrity.issues_found || 0) === 0 ? 'text-emerald-400' : 'text-orange-400'
            }`}
          />
          <span className="text-sm text-white font-medium capitalize">
            {system.status || 'unknown'}
          </span>
          <span className="text-xs text-slate-500">
            {system.platform} v{system.version}
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <Metric label="Integrity Issues" value={integrity.issues_found ?? 0} />
          <Metric label="Missing Profiles" value={integrity.users_without_profiles ?? 0} />
          <Metric label="Orphaned Alarms" value={integrity.orphaned_alarms ?? 0} />
          <Metric label="Active Sessions" value={integrity.active_challenge_sessions ?? 0} />
          <Metric
            label="Redis"
            value={reports?.configuration?.redis_enabled ? 'On' : 'Off'}
          />
          <Metric
            label="DB Rows"
            value={reports?.database?.total_rows ?? 0}
          />
        </div>
        <div className="grid grid-cols-3 gap-3 mt-4">
          <Metric label="Signups (24h)" value={last24h.new_signups ?? 0} />
          <Metric label="Wakes (24h)" value={last24h.wake_events ?? 0} />
          <Metric label="Challenges (24h)" value={last24h.challenge_attempts ?? 0} />
        </div>
      </SectionCard>

      {/* ─── System Reports ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.3 }} className="card space-y-5">
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <HiOutlineDocumentChartBar className="w-5 h-5 text-primary-400" />
              System Reports
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              Generate User, Alarm, Habit, and Platform reports for {periodLabel}. Export PDF or Excel.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleExportSystemReport('pdf')}
              disabled={!!exporting || systemReportLoading}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-500 text-white text-sm font-medium disabled:opacity-50"
            >
              <HiOutlineArrowDownTray className="w-4 h-4" />
              {exporting === 'pdf' ? 'Exporting…' : 'PDF'}
            </button>
            <button
              type="button"
              onClick={() => handleExportSystemReport('excel')}
              disabled={!!exporting || systemReportLoading}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-600 bg-surface-800/80 hover:bg-surface-700 text-slate-200 text-sm font-medium disabled:opacity-50"
            >
              <HiOutlineArrowDownTray className="w-4 h-4" />
              {exporting === 'excel' ? 'Exporting…' : 'Excel'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {(systemReportTypes.length ? systemReportTypes : SYSTEM_REPORT_FALLBACK).map((rt) => {
            const Icon = SYSTEM_REPORT_ICONS[rt.type] || HiOutlineDocumentChartBar;
            const selected = systemReportType === rt.type;
            return (
              <button
                key={rt.type}
                type="button"
                onClick={() => setSystemReportType(rt.type)}
                className={`text-left rounded-xl border px-4 py-3 transition ${
                  selected
                    ? 'border-primary-500/50 bg-primary-600/15'
                    : 'border-surface-700/40 bg-surface-900/40 hover:border-surface-600'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon className={`w-4 h-4 ${selected ? 'text-primary-300' : 'text-slate-400'}`} />
                  <span className={`text-sm font-medium ${selected ? 'text-white' : 'text-slate-200'}`}>
                    {rt.title}
                  </span>
                </div>
                <p className="text-xs text-slate-500 line-clamp-2">{rt.description}</p>
              </button>
            );
          })}
        </div>

        {systemReportLoading ? (
          <div className="flex items-center justify-center py-10">
            <div className="w-8 h-8 border-4 border-primary-500/30 border-t-primary-500 rounded-full animate-spin" />
          </div>
        ) : systemReport ? (
          <div className="space-y-4">
            {systemReport.is_empty ? (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                {systemReport.empty_message || 'No data for this period.'}
              </div>
            ) : null}

            <ReportSummaryGrid summary={systemReport.sections?.summary} />

            {Array.isArray(systemReport.insights) && systemReport.insights.length > 0 ? (
              <div>
                <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Insights</p>
                <ul className="space-y-1.5">
                  {systemReport.insights.map((insight) => (
                    <li
                      key={insight}
                      className="text-sm text-slate-300 flex gap-2"
                    >
                      <span className="text-primary-400 mt-0.5">•</span>
                      <span>{insight}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {(systemReport.sections?.tables || []).slice(0, 2).map((table) => {
              if (!table?.headers?.length || !table?.rows?.length) return null;
              return (
                <div key={table.title} className="overflow-x-auto">
                  <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                    {table.title}
                  </p>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-700/30">
                        {table.headers.map((h) => (
                          <th
                            key={h}
                            className="text-left py-2 px-2 text-slate-400 font-medium uppercase text-[11px] tracking-wider"
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.slice(0, 8).map((row) => (
                        <tr
                          key={`${table.title}-${row.join('-')}`}
                          className="border-b border-surface-800/40"
                        >
                          {row.map((cell, idx) => (
                            <td key={`${table.headers[idx]}-${cell}`} className="py-2 px-2 text-slate-300">
                              {cell == null ? '—' : String(cell)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-slate-500 py-6 text-center">
            Select a report type to generate a preview.
          </p>
        )}
      </motion.div>

      {/* ─── User Management ─── */}
      <AdminUserManagement onUsersChanged={() => loadDashboard({ silent: true })} />
    </div>
  );
}

// ─── Sub-components ───

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="stat-card">
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center mb-2`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <p className="stat-value">{value}</p>
      <p className="text-sm text-slate-400">{label}</p>
    </div>
  );
}
