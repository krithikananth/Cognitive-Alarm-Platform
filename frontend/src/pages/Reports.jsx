/**
 * Reports — generate and export lifestyle analytics reports.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineDocumentText,
  HiOutlineArrowDownTray,
  HiOutlineCalendarDays,
  HiOutlineExclamationTriangle,
  HiOutlineFire,
  HiOutlineSun,
  HiOutlinePuzzlePiece,
  HiOutlineBolt,
  HiOutlineMoon,
} from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { reportsAPI } from '../services/api';
import { formatHabitScore } from '../utils/habitScore';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const REPORT_ICONS = {
  habit: HiOutlineFire,
  wake: HiOutlineSun,
  challenge: HiOutlinePuzzlePiece,
  productivity: HiOutlineBolt,
  sleep: HiOutlineMoon,
};

const PRESETS = [
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
];

function isHabitScoreKey(key) {
  return key === 'habit_score' || key === 'current_habit_score' || key.endsWith('_habit_score');
}

function formatMetricValue(key, value) {
  if (value === null || value === undefined) return '—';
  if (isHabitScoreKey(key)) return formatHabitScore(value);
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return null;
  return String(value);
}

function SummaryGrid({ summary }) {
  if (!summary) return null;
  const entries = Object.entries(summary).filter(([, v]) => {
    if (v === null || v === undefined) return true;
    return typeof v !== 'object';
  });

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
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

export default function Reports() {
  const [reportTypes, setReportTypes] = useState([]);
  const [selectedType, setSelectedType] = useState('habit');
  const [days, setDays] = useState(30);
  const [useCustomRange, setUseCustomRange] = useState(false);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(null);

  const dateParams = useMemo(() => {
    if (useCustomRange && startDate && endDate) {
      return { start_date: startDate, end_date: endDate };
    }
    return { days };
  }, [useCustomRange, startDate, endDate, days]);

  const loadTypes = useCallback(async () => {
    try {
      const { data } = await reportsAPI.list();
      setReportTypes(data.reports || []);
      if (data.reports?.length && !selectedType) {
        setSelectedType(data.reports[0].type);
      }
    } catch {
      toast.error('Failed to load report types');
    }
  }, [selectedType]);

  const loadReport = useCallback(async () => {
    if (!selectedType) return;
    if (useCustomRange && (!startDate || !endDate)) {
      toast.error('Select both start and end dates');
      return;
    }
    setLoading(true);
    try {
      const { data } = await reportsAPI.get(selectedType, dateParams);
      setReport(data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to load report');
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [selectedType, dateParams, useCustomRange, startDate, endDate]);

  useEffect(() => {
    loadTypes();
  }, [loadTypes]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const handleExport = async (format) => {
    if (!selectedType) return;
    setExporting(format);
    try {
      const res = await reportsAPI.export(selectedType, format, dateParams);
      const blob = new Blob([res.data], { type: res.headers['content-type'] });
      const disposition = res.headers['content-disposition'] || '';
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename =
        match?.[1] ||
        `icap_${selectedType}_report.${format === 'pdf' ? 'pdf' : 'xlsx'}`;
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
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Export failed');
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="space-y-6">
      <motion.div {...fadeUp} className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-primary-300 mb-2">
            <HiOutlineDocumentText className="w-5 h-5" />
            <span className="text-xs uppercase tracking-wider font-medium">Reports</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-white">Lifestyle Reports</h1>
          <p className="text-slate-400 mt-1 text-sm">
            Export habit, wake, challenge, productivity, and sleep analytics.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => handleExport('pdf')}
            disabled={!!exporting || loading}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-500 text-white text-sm font-medium disabled:opacity-50"
          >
            <HiOutlineArrowDownTray className="w-4 h-4" />
            {exporting === 'pdf' ? 'Exporting…' : 'PDF'}
          </button>
          <button
            type="button"
            onClick={() => handleExport('excel')}
            disabled={!!exporting || loading}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-600 bg-surface-800/80 hover:bg-surface-700 text-slate-200 text-sm font-medium disabled:opacity-50"
          >
            <HiOutlineArrowDownTray className="w-4 h-4" />
            {exporting === 'excel' ? 'Exporting…' : 'Excel'}
          </button>
        </div>
      </motion.div>

      {/* Filters */}
      <motion.div
        {...fadeUp}
        transition={{ delay: 0.05 }}
        className="glass rounded-2xl border border-surface-700/40 p-4 md:p-5 space-y-4"
      >
        <div className="flex items-center gap-2 text-slate-300 text-sm font-medium">
          <HiOutlineCalendarDays className="w-4 h-4" />
          Date filter
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
          </div>
        )}
      </motion.div>

      {/* Report type cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {(reportTypes.length
          ? reportTypes
          : [
              { type: 'habit', title: 'Habit Report', description: '' },
              { type: 'wake', title: 'Wake Report', description: '' },
              { type: 'challenge', title: 'Challenge Performance', description: '' },
              { type: 'productivity', title: 'Productivity Report', description: '' },
              { type: 'sleep', title: 'Sleep Analytics', description: '' },
            ]
        ).map((rt) => {
          const Icon = REPORT_ICONS[rt.type] || HiOutlineDocumentText;
          const active = selectedType === rt.type;
          return (
            <button
              key={rt.type}
              type="button"
              onClick={() => setSelectedType(rt.type)}
              className={`text-left rounded-2xl border p-4 transition ${
                active
                  ? 'border-primary-500/40 bg-primary-600/15'
                  : 'border-surface-700/50 bg-surface-900/30 hover:border-surface-500'
              }`}
            >
              <Icon className={`w-5 h-5 mb-2 ${active ? 'text-primary-300' : 'text-slate-400'}`} />
              <p className="text-sm font-semibold text-white">{rt.title}</p>
              {rt.description ? (
                <p className="text-xs text-slate-500 mt-1 line-clamp-2">{rt.description}</p>
              ) : null}
            </button>
          );
        })}
      </div>

      {/* Preview */}
      <motion.div
        {...fadeUp}
        transition={{ delay: 0.1 }}
        className="glass rounded-2xl border border-surface-700/40 p-5 md:p-6 min-h-[280px]"
      >
        {loading ? (
          <div className="flex items-center justify-center py-16 text-slate-400 text-sm">
            Loading report…
          </div>
        ) : !report ? (
          <div className="flex items-center justify-center py-16 text-slate-400 text-sm">
            Unable to load report.
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
              <div>
                <h2 className="text-xl font-bold text-white">{report.title}</h2>
                <p className="text-sm text-slate-400 mt-1">{report.description}</p>
                <p className="text-xs text-slate-500 mt-2">
                  {report.period?.start_date} → {report.period?.end_date} · {report.period?.days} days
                </p>
              </div>
            </div>

            {report.is_empty && (
              <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-amber-200">
                <HiOutlineExclamationTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium">No data for this period</p>
                  <p className="text-sm text-amber-200/80">
                    {report.empty_message
                      || 'No data available for this period. Complete a verified wake-up to unlock this report.'}
                  </p>
                </div>
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-slate-300 mb-3 uppercase tracking-wide">
                Summary
              </h3>
              <SummaryGrid summary={report.sections?.summary} />
            </div>

            {Array.isArray(report.insights) && report.insights.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-slate-300 mb-3 uppercase tracking-wide">
                  Insights
                </h3>
                <ul className="space-y-2">
                  {report.insights.map((insight, idx) => (
                    <li
                      key={idx}
                      className="text-sm text-slate-300 rounded-lg border border-surface-700/40 px-3 py-2"
                    >
                      {typeof insight === 'string' ? insight : JSON.stringify(insight)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}
