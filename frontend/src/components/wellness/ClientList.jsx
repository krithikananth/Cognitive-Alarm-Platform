/**
 * The coach's assigned-client roster: search, filters, selectable rows, paging.
 *
 * `total_assigned` (the unfiltered roster size) is what separates "no clients
 * assigned to you" from "no clients match these filters" — the two need very
 * different copy.
 */
import React from 'react';
import { motion } from 'framer-motion';
import { HiOutlineMagnifyingGlass, HiOutlineUserGroup } from 'react-icons/hi2';
import ClientFilters from './ClientFilters';
import { ClientMetric, EmptyState, PanelError, Pagination } from './primitives';
import { fadeUp } from './constants';
import { formatHabitScore } from '../../utils/habitScore';

function ClientRow({ client, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className={`w-full text-left rounded-xl border px-4 py-3 transition ${
        selected
          ? 'border-violet-500/40 bg-violet-500/10'
          : 'border-surface-700/50 bg-surface-900/30 hover:border-surface-600 hover:bg-surface-800/50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-9 h-9 rounded-full gradient-primary flex items-center justify-center text-sm font-bold flex-shrink-0">
          {(client.full_name || client.username || '?')[0].toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-white truncate">
              {client.full_name || client.username}
            </p>
            {client.needs_attention && (
              <span
                className="w-1.5 h-1.5 rounded-full bg-orange-400 flex-shrink-0"
                title="Needs attention"
              />
            )}
          </div>
          <p className="text-xs text-slate-500 truncate">{client.email}</p>
        </div>
        <div className="flex items-center gap-4 flex-shrink-0">
          <ClientMetric label="Habit" value={formatHabitScore(client.habit_score)} />
          <ClientMetric label="Wake" value={Math.round(client.wake_consistency ?? 0)} />
          <ClientMetric label="Streak" value={`${client.streak_days ?? 0}d`} />
          <ClientMetric label="Wakes" value={client.verified_wakes ?? 0} />
        </div>
      </div>
    </button>
  );
}

export default function ClientList({
  clients,
  pageMeta,
  loading,
  error,
  onRetry,
  selectedId,
  onSelect,
  onPrevPage,
  onNextPage,
  ...filterProps
}) {
  const hasClients = (pageMeta?.total_assigned ?? 0) > 0;

  return (
    <motion.div
      id="coach-clients"
      {...fadeUp}
      transition={{ delay: 0.06 }}
      className="card scroll-mt-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineUserGroup className="w-5 h-5 text-violet-400" />
          My Clients
          {pageMeta?.total_assigned > 0 && (
            <span className="text-xs font-normal text-slate-400">
              ({pageMeta.total} of {pageMeta.total_assigned})
            </span>
          )}
        </h2>
        <ClientFilters {...filterProps} />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12" role="status" aria-live="polite">
          <div className="w-8 h-8 border-4 border-accent-500 border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">Loading clients</span>
        </div>
      ) : error && !pageMeta ? (
        <PanelError message="Your client roster could not be loaded." onRetry={onRetry} />
      ) : !hasClients ? (
        <EmptyState
          icon={HiOutlineUserGroup}
          title="No clients assigned yet"
          message="An administrator assigns clients to your roster. Once assigned, their sleep, wake, habit, and challenge analytics appear here."
        />
      ) : clients.length === 0 ? (
        <EmptyState
          icon={HiOutlineMagnifyingGlass}
          title="No clients match these filters"
          message="Try a different search term or switch back to the “All” filter."
        />
      ) : (
        <>
          <div className="space-y-2">
            {clients.map((row) => (
              <ClientRow
                key={row.client_id}
                client={row}
                selected={row.client_id === selectedId}
                onSelect={() => onSelect(row.client_id)}
              />
            ))}
          </div>

          {pageMeta?.total_pages > 1 && (
            <Pagination
              page={pageMeta.page}
              totalPages={pageMeta.total_pages}
              onPrev={onPrevPage}
              onNext={onNextPage}
            />
          )}
        </>
      )}
    </motion.div>
  );
}
