/**
 * Coach/client assignment management for admins.
 *
 * Assignments are what scope a wellness coach's data access, so without this
 * surface the coach dashboard can never be populated: the APIs existed but
 * nothing in the app called them.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineArrowPath,
  HiOutlineLink,
  HiOutlinePlus,
  HiOutlineTrash,
  HiOutlineUserGroup,
} from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { adminAPI, readErrorDetail } from '../services/api';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const PER_PAGE = 10;
/** Enough to cover a realistic coach/client roster in one picker load. */
const PICKER_LIMIT = 100;

function formatWhen(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleDateString();
}

function personLabel(user) {
  const name = user.full_name || user.username || `User ${user.id}`;
  return user.email ? `${name} (${user.email})` : name;
}

function ConfirmRemoval({ assignment, busy, onConfirm, onCancel }) {
  const coach = assignment.coach_full_name || assignment.coach_username;
  const client = assignment.client_full_name || assignment.client_username;
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={busy ? undefined : onCancel}
      />
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="relative w-full max-w-sm glass rounded-2xl p-6 z-10"
      >
        <h2 className="text-lg font-bold text-white mb-2">Remove assignment?</h2>
        <p className="text-sm text-slate-400 mb-6">
          {coach} will immediately lose access to {client}&apos;s data. The record is
          kept so past coaching stays auditable.
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="btn-secondary flex-1 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="flex-1 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500 text-white font-medium transition disabled:opacity-50"
          >
            {busy ? 'Removing…' : 'Remove'}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

export default function AdminCoachAssignments() {
  const [assignments, setAssignments] = useState([]);
  const [meta, setMeta] = useState(null);
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [coaches, setCoaches] = useState([]);
  const [clients, setClients] = useState([]);
  const [coachId, setCoachId] = useState('');
  const [clientId, setClientId] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState(null);
  const [removing, setRemoving] = useState(false);

  const query = useMemo(
    // The API's `is_active` filter defaults to true and has no "all" value, so
    // the toggle switches the list between live and archived rather than
    // widening it. Removal is a soft delete, so archived rows still exist.
    () => ({ page, per_page: PER_PAGE, is_active: !includeInactive }),
    [page, includeInactive]
  );

  const loadAssignments = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await adminAPI.listCoachAssignments(query);
      setAssignments(data.assignments || []);
      setMeta(data);
      setError(null);
    } catch (err) {
      setError((await readErrorDetail(err, '')) || 'Failed to load assignments');
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    loadAssignments();
  }, [loadAssignments]);

  useEffect(() => {
    let cancelled = false;
    const loadPickers = async () => {
      try {
        const [coachRes, clientRes] = await Promise.all([
          adminAPI.listUsers({ role: 'wellness_coach', per_page: PICKER_LIMIT }),
          adminAPI.listUsers({ role: 'user', per_page: PICKER_LIMIT }),
        ]);
        if (cancelled) return;
        setCoaches(coachRes.data.users || []);
        setClients(clientRes.data.users || []);
      } catch {
        if (!cancelled) toast.error('Could not load coach and client lists');
      }
    };
    loadPickers();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAssign = async (event) => {
    event.preventDefault();
    if (!coachId || !clientId || saving) return;
    setSaving(true);
    try {
      await adminAPI.createCoachAssignment({
        coach_id: Number(coachId),
        client_id: Number(clientId),
        notes: notes.trim() || undefined,
      });
      toast.success('Client assigned to coach');
      setClientId('');
      setNotes('');
      setPage(1);
      await loadAssignments();
    } catch (err) {
      toast.error((await readErrorDetail(err, '')) || 'Failed to assign client');
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async () => {
    if (!pendingRemoval || removing) return;
    setRemoving(true);
    try {
      await adminAPI.removeCoachAssignment(
        pendingRemoval.coach_id,
        pendingRemoval.client_id
      );
      toast.success('Assignment removed');
      setPendingRemoval(null);
      await loadAssignments();
    } catch (err) {
      toast.error((await readErrorDetail(err, '')) || 'Failed to remove assignment');
    } finally {
      setRemoving(false);
    }
  };

  const totalPages = meta?.total_pages ?? 1;

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.34 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineLink className="w-5 h-5 text-primary-400" />
          Coach Assignments
          {meta?.total != null ? (
            <span className="text-sm text-slate-400 font-normal ml-1">
              ({meta.total})
            </span>
          ) : null}
        </h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(e) => {
                setPage(1);
                setIncludeInactive(e.target.checked);
              }}
            />
            Show removed
          </label>
          <button
            type="button"
            onClick={loadAssignments}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-50"
          >
            <HiOutlineArrowPath className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <p className="text-xs text-slate-500 mb-4">
        A wellness coach can only see clients assigned here. Removing an assignment
        revokes that access immediately.
      </p>

      {/* ─── Assign form ─── */}
      <form
        onSubmit={handleAssign}
        className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-5 p-4 rounded-xl border border-surface-700/50 bg-surface-900/30"
      >
        <label className="text-xs text-slate-400 md:col-span-1">
          Coach
          <select
            value={coachId}
            onChange={(e) => setCoachId(e.target.value)}
            className="input mt-1 w-full"
            aria-label="Coach"
          >
            <option value="">Select a coach…</option>
            {coaches.map((coach) => (
              <option key={coach.id} value={coach.id}>
                {personLabel(coach)}
              </option>
            ))}
          </select>
        </label>

        <label className="text-xs text-slate-400 md:col-span-1">
          Client
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="input mt-1 w-full"
            aria-label="Client"
          >
            <option value="">Select a client…</option>
            {clients.map((client) => (
              <option key={client.id} value={client.id}>
                {personLabel(client)}
              </option>
            ))}
          </select>
        </label>

        <label className="text-xs text-slate-400 md:col-span-1">
          Notes (optional)
          <input
            type="text"
            value={notes}
            maxLength={500}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Coaching context"
            className="input mt-1 w-full"
            aria-label="Assignment notes"
          />
        </label>

        <div className="flex items-end">
          <button
            type="submit"
            disabled={!coachId || !clientId || saving}
            className="btn-primary w-full inline-flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <HiOutlinePlus className="w-4 h-4" />
            {saving ? 'Assigning…' : 'Assign'}
          </button>
        </div>
      </form>

      {/* ─── Assignment list ─── */}
      {error && !assignments.length ? (
        <p className="text-sm text-red-300 py-6 text-center" role="alert">
          {error}
        </p>
      ) : loading && !assignments.length ? (
        <div className="flex items-center justify-center py-10" role="status" aria-live="polite">
          <div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">Loading assignments</span>
        </div>
      ) : !assignments.length ? (
        <div className="flex flex-col items-center justify-center py-10 text-slate-500">
          <HiOutlineUserGroup className="w-8 h-8 mb-2 opacity-50" />
          <p className="text-sm">
            {includeInactive ? 'No removed assignments' : 'No coach assignments yet'}
          </p>
          <p className="text-xs mt-1">
            {includeInactive
              ? 'Assignments you remove are kept here so past coaching stays auditable.'
              : 'Assign a client above to give a coach access to their analytics.'}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400 border-b border-surface-700/50">
                <th className="pb-2 pr-3 font-medium">Coach</th>
                <th className="pb-2 pr-3 font-medium">Client</th>
                <th className="pb-2 pr-3 font-medium">Notes</th>
                <th className="pb-2 pr-3 font-medium">Status</th>
                <th className="pb-2 pr-3 font-medium">Assigned</th>
                <th className="pb-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((row) => (
                <tr key={row.id} className="border-b border-surface-700/30">
                  <td className="py-3 pr-3 text-white">
                    {row.coach_full_name || row.coach_username}
                  </td>
                  <td className="py-3 pr-3 text-slate-300">
                    <span className="text-white">
                      {row.client_full_name || row.client_username}
                    </span>
                    {row.client_email ? (
                      <span className="block text-xs text-slate-500">
                        {row.client_email}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-3 pr-3 text-slate-400">{row.notes || '—'}</td>
                  <td className="py-3 pr-3">
                    <span
                      className={`inline-flex items-center gap-1.5 text-xs font-medium ${row.is_active ? 'text-emerald-400' : 'text-slate-500'
                        }`}
                    >
                      <span
                        className={`w-2 h-2 rounded-full ${row.is_active ? 'bg-emerald-400' : 'bg-slate-500'
                          }`}
                      />
                      {row.is_active ? 'Active' : 'Removed'}
                    </span>
                  </td>
                  <td className="py-3 pr-3 text-slate-400">
                    {formatWhen(row.created_at)}
                  </td>
                  <td className="py-3 text-right">
                    {row.is_active ? (
                      <button
                        type="button"
                        onClick={() => setPendingRemoval(row)}
                        className="p-2 rounded-lg hover:bg-red-500/10 transition"
                        title="Remove assignment"
                        aria-label={`Remove ${row.client_username} from ${row.coach_username}`}
                      >
                        <HiOutlineTrash className="w-4 h-4 text-slate-400 hover:text-red-400" />
                      </button>
                    ) : (
                      <span className="text-xs text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 ? (
        <div className="flex items-center justify-between mt-4 text-sm">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 rounded-lg border border-surface-600 text-slate-300 disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-slate-500">
            Page {meta?.page ?? page} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 rounded-lg border border-surface-600 text-slate-300 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      ) : null}

      {pendingRemoval ? (
        <ConfirmRemoval
          assignment={pendingRemoval}
          busy={removing}
          onConfirm={handleRemove}
          onCancel={() => !removing && setPendingRemoval(null)}
        />
      ) : null}
    </motion.div>
  );
}
