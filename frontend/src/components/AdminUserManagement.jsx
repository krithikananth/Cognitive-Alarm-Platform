/**
 * AdminUserManagement — admin-only user table backed entirely by the live API.
 *
 * Listing, search, filtering, sorting and pagination are resolved server-side by
 * GET /admin/users so the view stays correct across pages. Mutations map to the
 * existing user endpoints (PUT /users/{id}, POST /users/{id}/activate,
 * POST /users/{id}/deactivate, DELETE /users/{id}) and always refresh the table.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  HiOutlineUsers, HiOutlineMagnifyingGlass, HiOutlineChevronUp,
  HiOutlineChevronDown, HiOutlineChevronLeft, HiOutlineChevronRight,
  HiOutlineArrowPath, HiOutlinePencilSquare, HiOutlineTrash,
  HiOutlineNoSymbol, HiOutlineCheckCircle, HiOutlineXMark,
  HiOutlineExclamationTriangle,
} from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { adminAPI } from '../services/api';
import useAuthStore from '../store/authStore';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const SEARCH_DEBOUNCE_MS = 350;

const ROLE_OPTIONS = [
  { value: 'user', label: 'User' },
  { value: 'wellness_coach', label: 'Wellness Coach' },
  { value: 'admin', label: 'Admin' },
];

const PER_PAGE_OPTIONS = [10, 20, 50];

const COLUMNS = [
  { key: 'username', label: 'Username' },
  { key: 'email', label: 'Email' },
  { key: 'full_name', label: 'Full Name' },
  { key: 'role', label: 'Role' },
  { key: 'is_active', label: 'Status' },
  { key: 'created_at', label: 'Created' },
  { key: 'total_alarms', label: 'Alarms' },
];

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Flatten FastAPI error payloads (string detail, 422 array, or network error). */
function extractError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((d) => d?.msg).filter(Boolean);
    if (messages.length) return messages.join(', ');
  }
  if (err?.code === 'ERR_NETWORK') {
    return 'Unable to reach the server. Check that the backend is running.';
  }
  return fallback;
}

function roleLabel(role) {
  return ROLE_OPTIONS.find((r) => r.value === role)?.label || role || 'user';
}

function formatCreated(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

// ─── Confirmation dialog ───

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  busyLabel,
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
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
        exit={{ scale: 0.95, opacity: 0 }}
        className="relative w-full max-w-sm glass rounded-2xl p-6 z-10"
      >
        <h2 className="text-lg font-bold text-white mb-2">{title}</h2>
        <p className="text-sm text-slate-400 mb-6">{message}</p>
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
            className={`flex-1 px-4 py-2 rounded-xl text-white font-medium transition disabled:opacity-50 ${danger
                ? 'bg-red-600 hover:bg-red-500'
                : 'bg-primary-600 hover:bg-primary-500'
              }`}
          >
            {busy ? busyLabel : confirmLabel}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ─── Edit user modal ───

function EditUserModal({ user, detail, isSelf, saving, onSave, onClose }) {
  const [form, setForm] = useState({
    full_name: user.full_name || '',
    email: user.email || '',
    role: user.role || 'user',
  });
  const [formError, setFormError] = useState(null);

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const email = form.email.trim();
    if (!email) {
      setFormError('Email is required');
      return;
    }
    if (!EMAIL_PATTERN.test(email)) {
      setFormError('Enter a valid email address');
      return;
    }

    // Only send fields the admin actually changed — the API treats unset
    // fields as "leave alone".
    const payload = {};
    const fullName = form.full_name.trim();
    if (fullName !== (user.full_name || '')) payload.full_name = fullName;
    if (email !== user.email) payload.email = email;
    if (form.role !== user.role) payload.role = form.role;

    if (!Object.keys(payload).length) {
      setFormError('No changes to save');
      return;
    }
    setFormError(null);
    onSave(payload);
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={saving ? undefined : onClose}
      />
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        className="relative w-full max-w-md glass rounded-2xl p-6 z-10"
      >
        <div className="flex items-start justify-between mb-5">
          <div>
            <h2 className="text-lg font-bold text-white">Edit user</h2>
            <p className="text-sm text-slate-400 mt-0.5">@{user.username}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="p-2 rounded-lg hover:bg-surface-700/50 transition disabled:opacity-50"
            aria-label="Close"
          >
            <HiOutlineXMark className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {detail ? (
          <p className="text-xs text-slate-500 mb-4 rounded-lg border border-surface-700/50 px-3 py-2">
            {detail.total_alarms ?? 0} alarms · {detail.verified_wakes ?? 0} verified
            wakes · joined {detail.created_at ? detail.created_at.slice(0, 10) : '—'}
          </p>
        ) : null}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Full name
            </label>
            <input
              type="text"
              value={form.full_name}
              onChange={(e) => setField('full_name', e.target.value)}
              className="input"
              placeholder="Full name"
              maxLength={255}
              disabled={saving}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Email
            </label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setField('email', e.target.value)}
              className="input"
              placeholder="user@example.com"
              maxLength={255}
              disabled={saving}
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Role
            </label>
            <select
              value={form.role}
              onChange={(e) => setField('role', e.target.value)}
              className="input"
              disabled={saving || isSelf}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
            {isSelf ? (
              <p className="text-[11px] text-slate-500 mt-1.5">
                You cannot change your own role.
              </p>
            ) : null}
          </div>

          {formError ? (
            <p className="text-sm text-red-400">{formError}</p>
          ) : null}

          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="btn-secondary flex-1 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="btn-primary flex-1 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
      </motion.div>
    </motion.div>
  );
}

// ─── Main panel ───

export default function AdminUserManagement({ onUsersChanged }) {
  const currentUser = useAuthStore((s) => s.user);

  const [users, setUsers] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState('desc');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);

  const [editingUser, setEditingUser] = useState(null);
  const [editingDetail, setEditingDetail] = useState(null);
  const [saving, setSaving] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [rowBusyId, setRowBusyId] = useState(null);

  const requestIdRef = useRef(0);
  const loadedOnceRef = useRef(false);

  // Debounce the search box so typing does not fire a request per keystroke.
  useEffect(() => {
    const id = window.setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [searchInput]);

  // Any change to the result set must start from the first page, otherwise the
  // requested page can fall outside the new range.
  useEffect(() => {
    setPage(1);
  }, [search, roleFilter, statusFilter, perPage]);

  const queryParams = useMemo(() => {
    const params = { page, per_page: perPage, sort_by: sortBy, sort_order: sortOrder };
    if (search) params.search = search;
    if (roleFilter) params.role = roleFilter;
    if (statusFilter) params.is_active = statusFilter === 'active';
    return params;
  }, [page, perPage, sortBy, sortOrder, search, roleFilter, statusFilter]);

  const loadUsers = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    if (loadedOnceRef.current) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const { data } = await adminAPI.listUsers(queryParams);
      if (requestId !== requestIdRef.current) return;
      setUsers(data?.users || []);
      setTotal(data?.total ?? 0);
      setTotalPages(data?.total_pages ?? 1);
      setError(null);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      setError(extractError(err, 'Failed to load users'));
    } finally {
      if (requestId === requestIdRef.current) {
        loadedOnceRef.current = true;
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [queryParams]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  /** Reload the table (and the surrounding dashboard stats) after a mutation. */
  const refreshAfterMutation = useCallback(async () => {
    // Deleting the last row of a trailing page would leave an empty view.
    if (users.length === 1 && page > 1) {
      setPage((p) => p - 1);
    } else {
      await loadUsers();
    }
    onUsersChanged?.();
  }, [users.length, page, loadUsers, onUsersChanged]);

  const handleSort = (field) => {
    if (sortBy === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(field);
      setSortOrder('asc');
    }
    setPage(1);
  };

  // The row comes from a cached page, so re-read the record before editing and
  // pull the activity detail alongside it.
  const openEditor = async (row) => {
    setEditingUser(row);
    setEditingDetail(null);
    const [fresh, detail] = await Promise.allSettled([
      adminAPI.getUser(row.id),
      adminAPI.getUserDetail(row.id),
    ]);
    if (fresh.status === 'fulfilled') setEditingUser(fresh.value.data);
    if (detail.status === 'fulfilled') setEditingDetail(detail.value.data);
  };

  const handleSaveUser = async (payload) => {
    if (!editingUser) return;
    setSaving(true);
    try {
      await adminAPI.updateUser(editingUser.id, payload);
      toast.success(`Updated ${editingUser.username}`);
      setEditingUser(null);
      setEditingDetail(null);
      await refreshAfterMutation();
    } catch (err) {
      toast.error(extractError(err, 'Failed to update user'));
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async (user) => {
    setRowBusyId(user.id);
    try {
      await adminAPI.activateUser(user.id);
      toast.success(`${user.username} activated`);
      await refreshAfterMutation();
    } catch (err) {
      toast.error(extractError(err, 'Failed to activate user'));
    } finally {
      setRowBusyId(null);
    }
  };

  const handleConfirmedAction = async () => {
    if (!confirmAction) return;
    const { type, user } = confirmAction;
    setActionBusy(true);
    try {
      if (type === 'delete') {
        await adminAPI.deleteUser(user.id);
        toast.success(`${user.username} deleted`);
      } else {
        await adminAPI.deactivateUser(user.id);
        toast.success(`${user.username} deactivated`);
      }
      setConfirmAction(null);
      await refreshAfterMutation();
    } catch (err) {
      toast.error(
        extractError(
          err,
          type === 'delete' ? 'Failed to delete user' : 'Failed to deactivate user',
        ),
      );
    } finally {
      setActionBusy(false);
    }
  };

  const hasFilters = Boolean(search || roleFilter || statusFilter);

  const clearFilters = () => {
    setSearchInput('');
    setSearch('');
    setRoleFilter('');
    setStatusFilter('');
  };

  const SortIcon = ({ field }) => {
    if (sortBy !== field) return null;
    return sortOrder === 'asc' ? (
      <HiOutlineChevronUp className="w-3.5 h-3.5 inline ml-1" />
    ) : (
      <HiOutlineChevronDown className="w-3.5 h-3.5 inline ml-1" />
    );
  };

  const rangeStart = total === 0 ? 0 : (page - 1) * perPage + 1;
  const rangeEnd = Math.min(page * perPage, total);

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.32 }} className="card">
      {/* ─── Header + search ─── */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineUsers className="w-5 h-5 text-primary-400" />
          All Users
          <span className="text-sm text-slate-400 font-normal ml-1">({total})</span>
          {refreshing ? (
            <HiOutlineArrowPath className="w-4 h-4 text-slate-500 animate-spin" />
          ) : null}
        </h2>

        <div className="relative">
          <HiOutlineMagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search users…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            maxLength={100}
            className="pl-9 pr-4 py-2 rounded-xl bg-surface-900/60 border border-surface-700/40 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-primary-500/50 transition w-64"
          />
        </div>
      </div>

      {/* ─── Filters ─── */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className="px-3 py-2 rounded-xl bg-surface-900/60 border border-surface-700/40 text-sm text-white focus:outline-none focus:border-primary-500/50 transition"
          aria-label="Filter by role"
        >
          <option value="">All roles</option>
          {ROLE_OPTIONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 rounded-xl bg-surface-900/60 border border-surface-700/40 text-sm text-white focus:outline-none focus:border-primary-500/50 transition"
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>

        <select
          value={perPage}
          onChange={(e) => setPerPage(Number(e.target.value))}
          className="px-3 py-2 rounded-xl bg-surface-900/60 border border-surface-700/40 text-sm text-white focus:outline-none focus:border-primary-500/50 transition"
          aria-label="Rows per page"
        >
          {PER_PAGE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n} per page
            </option>
          ))}
        </select>

        {hasFilters ? (
          <button
            type="button"
            onClick={clearFilters}
            className="text-sm text-slate-400 hover:text-white transition"
          >
            Clear filters
          </button>
        ) : null}

        <button
          type="button"
          onClick={loadUsers}
          disabled={loading || refreshing}
          className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-50 transition"
        >
          <HiOutlineArrowPath className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ─── Error ─── */}
      {error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 mb-4 flex items-center justify-between gap-3 flex-wrap">
          <span className="text-sm text-red-200 flex items-center gap-2">
            <HiOutlineExclamationTriangle className="w-4 h-4" />
            {error}
          </span>
          <button
            type="button"
            onClick={loadUsers}
            className="text-sm text-red-200 underline hover:text-white transition"
          >
            Retry
          </button>
        </div>
      ) : null}

      {/* ─── Table ─── */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-700/30">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className="text-left py-3 px-3 text-slate-400 font-medium uppercase text-[11px] tracking-wider cursor-pointer hover:text-white transition select-none"
                >
                  {col.label}
                  <SortIcon field={col.key} />
                </th>
              ))}
              <th className="text-right py-3 px-3 text-slate-400 font-medium uppercase text-[11px] tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="text-center py-12">
                  <div className="w-8 h-8 border-4 border-primary-500/30 border-t-primary-500 rounded-full animate-spin mx-auto mb-3" />
                  <p className="text-slate-500">Loading users…</p>
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td
                  colSpan={COLUMNS.length + 1}
                  className="text-center py-12 text-slate-500"
                >
                  {hasFilters ? 'No users match your filters.' : 'No users found.'}
                </td>
              </tr>
            ) : (
              users.map((u, i) => {
                const isSelf = String(u.id) === String(currentUser?.id);
                const busy = rowBusyId === u.id;
                return (
                  <motion.tr
                    key={u.id}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: i * 0.02 }}
                    className="border-b border-surface-700/20 hover:bg-surface-800/40 transition"
                  >
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-500 to-accent-500 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
                          {(u.full_name?.[0] || u.username?.[0] || '?').toUpperCase()}
                        </div>
                        <span className="text-white font-medium">{u.username}</span>
                        {isSelf ? (
                          <span className="text-[10px] uppercase tracking-wider text-slate-500">
                            You
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-slate-400">{u.email}</td>
                    <td className="py-3 px-3 text-slate-300">{u.full_name || '—'}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-lg text-[11px] font-semibold uppercase tracking-wider ${u.role === 'admin'
                            ? 'bg-primary-500/15 text-primary-400 border border-primary-500/30'
                            : 'bg-surface-700/50 text-slate-400 border border-surface-600/30'
                          }`}
                      >
                        {roleLabel(u.role)}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium ${u.is_active !== false ? 'text-emerald-400' : 'text-red-400'
                          }`}
                      >
                        <span
                          className={`w-2 h-2 rounded-full ${u.is_active !== false ? 'bg-emerald-400' : 'bg-red-400'
                            }`}
                        />
                        {u.is_active !== false ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-slate-400">
                      {formatCreated(u.created_at)}
                    </td>
                    <td className="py-3 px-3">
                      <span className="text-white font-semibold">
                        {u.total_alarms ?? 0}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => openEditor(u)}
                          disabled={busy}
                          className="p-2 rounded-lg hover:bg-primary-500/10 transition disabled:opacity-40"
                          title="Edit user"
                          aria-label={`Edit ${u.username}`}
                        >
                          <HiOutlinePencilSquare className="w-4 h-4 text-slate-400 hover:text-primary-400" />
                        </button>

                        {u.is_active !== false ? (
                          <button
                            type="button"
                            onClick={() =>
                              setConfirmAction({ type: 'deactivate', user: u })
                            }
                            disabled={busy || isSelf}
                            className="p-2 rounded-lg hover:bg-orange-500/10 transition disabled:opacity-40 disabled:cursor-not-allowed"
                            title={
                              isSelf
                                ? 'You cannot deactivate your own account'
                                : 'Deactivate user'
                            }
                            aria-label={`Deactivate ${u.username}`}
                          >
                            <HiOutlineNoSymbol className="w-4 h-4 text-slate-400 hover:text-orange-400" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleActivate(u)}
                            disabled={busy}
                            className="p-2 rounded-lg hover:bg-emerald-500/10 transition disabled:opacity-40"
                            title="Activate user"
                            aria-label={`Activate ${u.username}`}
                          >
                            <HiOutlineCheckCircle className="w-4 h-4 text-slate-400 hover:text-emerald-400" />
                          </button>
                        )}

                        <button
                          type="button"
                          onClick={() => setConfirmAction({ type: 'delete', user: u })}
                          disabled={busy || isSelf}
                          className="p-2 rounded-lg hover:bg-red-500/10 transition disabled:opacity-40 disabled:cursor-not-allowed"
                          title={
                            isSelf
                              ? 'You cannot delete your own account'
                              : 'Delete user'
                          }
                          aria-label={`Delete ${u.username}`}
                        >
                          <HiOutlineTrash className="w-4 h-4 text-slate-400 hover:text-red-400" />
                        </button>
                      </div>
                    </td>
                  </motion.tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* ─── Pagination ─── */}
      {!loading && total > 0 ? (
        <div className="flex items-center justify-between gap-3 flex-wrap mt-4 pt-4 border-t border-surface-700/30">
          <p className="text-xs text-slate-500">
            Showing {rangeStart}–{rangeEnd} of {total}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || refreshing}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <HiOutlineChevronLeft className="w-4 h-4" />
              Prev
            </button>
            <span className="text-xs text-slate-500 px-1">
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || refreshing}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              Next
              <HiOutlineChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      ) : null}

      {/* ─── Edit modal ─── */}
      <AnimatePresence>
        {editingUser ? (
          <EditUserModal
            user={editingUser}
            detail={editingDetail}
            isSelf={String(editingUser.id) === String(currentUser?.id)}
            saving={saving}
            onSave={handleSaveUser}
            onClose={() => !saving && (setEditingUser(null), setEditingDetail(null))}
          />
        ) : null}
      </AnimatePresence>

      {/* ─── Destructive-action confirmation ─── */}
      <AnimatePresence>
        {confirmAction ? (
          <ConfirmDialog
            title={
              confirmAction.type === 'delete'
                ? `Delete ${confirmAction.user.username}?`
                : `Deactivate ${confirmAction.user.username}?`
            }
            message={
              confirmAction.type === 'delete'
                ? 'This permanently removes the account along with its alarms, history and notifications. This cannot be undone.'
                : 'The user will be signed out and blocked from logging in until reactivated.'
            }
            confirmLabel={confirmAction.type === 'delete' ? 'Delete' : 'Deactivate'}
            busyLabel={confirmAction.type === 'delete' ? 'Deleting…' : 'Deactivating…'}
            danger={confirmAction.type === 'delete'}
            busy={actionBusy}
            onConfirm={handleConfirmedAction}
            onCancel={() => !actionBusy && setConfirmAction(null)}
          />
        ) : null}
      </AnimatePresence>
    </motion.div>
  );
}
