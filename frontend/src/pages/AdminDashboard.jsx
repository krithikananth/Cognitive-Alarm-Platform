/**
 * AdminDashboard — admin-only page showing platform stats and user management.
 */
import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineUsers, HiOutlineClock, HiOutlineShieldCheck,
  HiOutlineExclamationTriangle, HiOutlineMagnifyingGlass,
  HiOutlineChevronUp, HiOutlineChevronDown,
} from 'react-icons/hi2';
import { adminAPI } from '../services/api';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

export default function AdminDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState('created_at');
  const [sortAsc, setSortAsc] = useState(false);

  useEffect(() => {
    adminAPI
      .getDashboard()
      .then((res) => {
        setData(res.data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.response?.data?.detail || 'Failed to load admin dashboard');
        setLoading(false);
      });
  }, []);

  const handleSort = (field) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  const SortIcon = ({ field }) => {
    if (sortField !== field) return null;
    return sortAsc ? (
      <HiOutlineChevronUp className="w-3.5 h-3.5 inline ml-1" />
    ) : (
      <HiOutlineChevronDown className="w-3.5 h-3.5 inline ml-1" />
    );
  };

  // ─── Loading State ───
  if (loading) {
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
  if (error) {
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

  // Filter users by search query
  const filteredUsers = users.filter((u) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      (u.username || '').toLowerCase().includes(q) ||
      (u.email || '').toLowerCase().includes(q) ||
      (u.full_name || '').toLowerCase().includes(q)
    );
  });

  // Sort users
  const sortedUsers = [...filteredUsers].sort((a, b) => {
    let aVal = a[sortField];
    let bVal = b[sortField];
    if (typeof aVal === 'string') aVal = aVal.toLowerCase();
    if (typeof bVal === 'string') bVal = bVal.toLowerCase();
    if (aVal < bVal) return sortAsc ? -1 : 1;
    if (aVal > bVal) return sortAsc ? 1 : -1;
    return 0;
  });

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* ─── Header ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0 }} className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <HiOutlineShieldCheck className="w-6 h-6 text-primary-400" />
            <h1 className="text-2xl font-bold text-white font-display">Admin Dashboard</h1>
          </div>
          <p className="text-slate-400">Manage users and monitor platform activity</p>
        </div>
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
          value={users.filter((u) => u.is_active !== false).length}
          color="from-orange-500 to-red-600"
        />
      </motion.div>

      {/* ─── User Table ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.2 }} className="card">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineUsers className="w-5 h-5 text-primary-400" />
            All Users
            <span className="text-sm text-slate-400 font-normal ml-1">({filteredUsers.length})</span>
          </h2>

          {/* Search */}
          <div className="relative">
            <HiOutlineMagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search users…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-xl bg-surface-900/60 border border-surface-700/40 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-primary-500/50 transition w-64"
            />
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700/30">
                {[
                  { key: 'username', label: 'Username' },
                  { key: 'email', label: 'Email' },
                  { key: 'full_name', label: 'Full Name' },
                  { key: 'role', label: 'Role' },
                  { key: 'is_active', label: 'Status' },
                  { key: 'created_at', label: 'Created' },
                  { key: 'total_alarms', label: 'Alarms' },
                ].map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    className="text-left py-3 px-3 text-slate-400 font-medium uppercase text-[11px] tracking-wider cursor-pointer hover:text-white transition select-none"
                  >
                    {col.label}
                    <SortIcon field={col.key} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedUsers.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500">
                    {searchQuery ? 'No users match your search.' : 'No users found.'}
                  </td>
                </tr>
              ) : (
                sortedUsers.map((u, i) => (
                  <motion.tr
                    key={u.id || i}
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
                      </div>
                    </td>
                    <td className="py-3 px-3 text-slate-400">{u.email}</td>
                    <td className="py-3 px-3 text-slate-300">{u.full_name || '—'}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-lg text-[11px] font-semibold uppercase tracking-wider ${
                          u.role === 'admin'
                            ? 'bg-primary-500/15 text-primary-400 border border-primary-500/30'
                            : 'bg-surface-700/50 text-slate-400 border border-surface-600/30'
                        }`}
                      >
                        {u.role || 'user'}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                          u.is_active !== false
                            ? 'text-emerald-400'
                            : 'text-red-400'
                        }`}
                      >
                        <span
                          className={`w-2 h-2 rounded-full ${
                            u.is_active !== false ? 'bg-emerald-400' : 'bg-red-400'
                          }`}
                        />
                        {u.is_active !== false ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-slate-400">
                      {u.created_at
                        ? new Date(u.created_at).toLocaleDateString('en-US', {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric',
                          })
                        : '—'}
                    </td>
                    <td className="py-3 px-3">
                      <span className="text-white font-semibold">{u.total_alarms ?? 0}</span>
                    </td>
                  </motion.tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </motion.div>
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
