/**
 * Roster search box, sort selector, and status filter chips.
 *
 * All three are applied server-side by CoachService.list_clients (filter →
 * sort → paginate), so they compose correctly across pages instead of only
 * reordering the rows that happen to be on screen.
 */
import React from 'react';
import { HiOutlineMagnifyingGlass } from 'react-icons/hi2';
import { SORT_OPTIONS, STATUS_FILTERS } from './constants';

export default function ClientFilters({
  searchInput,
  onSearchChange,
  sortKey,
  onSortChange,
  statusFilter,
  onStatusChange,
}) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <HiOutlineMagnifyingGlass className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search clients"
            aria-label="Search clients by name, username, or email"
            className="pl-9 pr-3 py-2 text-sm rounded-xl bg-surface-900/60 border border-surface-700/50 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500/50 w-48"
          />
        </div>
        <select
          value={sortKey}
          onChange={(e) => onSortChange(e.target.value)}
          aria-label="Sort clients"
          className="py-2 px-3 text-sm rounded-xl bg-surface-900/60 border border-surface-700/50 text-slate-300 focus:outline-none focus:border-violet-500/50"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div
        className="flex flex-wrap gap-2 mb-4"
        role="group"
        aria-label="Filter clients by status"
        data-testid="coach-status-filters"
      >
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => onStatusChange(filter.value)}
            aria-pressed={statusFilter === filter.value}
            title={filter.hint}
            data-testid={`coach-status-${filter.value}`}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${
              statusFilter === filter.value
                ? 'bg-violet-500/20 text-violet-200 border-violet-500/40'
                : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
            }`}
          >
            {filter.label}
          </button>
        ))}
      </div>
    </>
  );
}
