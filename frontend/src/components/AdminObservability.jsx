/**
 * Observability panel: threshold alerts and the active logging configuration.
 *
 * Both endpoints existed but had no consumer, so an admin had no way to see
 * whether the platform was breaching its own latency/error thresholds.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineArrowPath,
  HiOutlineBellAlert,
  HiOutlineCheckCircle,
  HiOutlineDocumentText,
} from 'react-icons/hi2';
import { systemAPI, readErrorDetail } from '../services/api';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const SEVERITY_STYLES = {
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
};

function Field({ label, value }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className="text-sm font-medium text-white break-words">{value ?? '—'}</p>
    </div>
  );
}

export default function AdminObservability() {
  const [alerts, setAlerts] = useState(null);
  const [logging, setLogging] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [alertRes, logRes] = await Promise.all([
        systemAPI.getAlerts(),
        systemAPI.getLogging(),
      ]);
      setAlerts(alertRes.data);
      setLogging(logRes.data);
      setError(null);
    } catch (err) {
      setError((await readErrorDetail(err, '')) || 'Failed to load observability data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const firing = alerts?.firing || [];

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.36 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineBellAlert className="w-5 h-5 text-primary-400" />
          Observability
          {alerts ? (
            <span
              className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border ${alerts.active_count > 0
                  ? SEVERITY_STYLES[alerts.worst_severity] || SEVERITY_STYLES.warning
                  : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                }`}
            >
              {alerts.active_count > 0 ? `${alerts.active_count} firing` : 'healthy'}
            </span>
          ) : null}
        </h2>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-50"
        >
          <HiOutlineArrowPath className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && !alerts ? (
        <p className="text-sm text-red-300" role="alert">{error}</p>
      ) : (
        <div className="space-y-5">
          {/* ── Threshold alerts ── */}
          <div>
            <p className="text-xs text-slate-500 mb-2">
              Evaluated {alerts?.evaluated_at || 'not yet'} · thresholds: p95{' '}
              {alerts?.thresholds?.api_p95_ms ?? '—'} ms, errors{' '}
              {alerts?.thresholds?.api_error_rate_pct ?? '—'}%, challenge p95{' '}
              {alerts?.thresholds?.challenge_generation_p95_ms ?? '—'} ms
            </p>

            {firing.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-emerald-300">
                <HiOutlineCheckCircle className="w-4 h-4" />
                No thresholds breached.
              </div>
            ) : (
              <ul className="space-y-2">
                {firing.map((alert) => (
                  <li
                    key={alert.rule || alert.alert_message}
                    className={`rounded-xl border px-3 py-2 text-sm ${SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.warning
                      }`}
                  >
                    <span className="font-semibold">{alert.rule || 'alert'}</span>
                    {alert.alert_message ? ` — ${alert.alert_message}` : null}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ── Logging configuration ── */}
          <div>
            <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-2">
              <HiOutlineDocumentText className="w-4 h-4 text-slate-400" />
              Logging
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <Field label="Level" value={logging?.level} />
              <Field label="Format" value={logging?.format} />
              <Field label="Environment" value={logging?.environment} />
              <Field label="Handlers" value={(logging?.handlers || []).join(', ')} />
              <Field label="Log file" value={logging?.log_file || 'stdout only'} />
              <Field label="Access log" value={logging?.access_log ? 'on' : 'off'} />
              <Field label="Request id header" value={logging?.request_id_header} />
              <Field label="Service" value={logging?.service} />
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
