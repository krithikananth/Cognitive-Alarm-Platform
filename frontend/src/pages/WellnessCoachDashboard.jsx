/**
 * WellnessCoachDashboard — coaching workspace for a wellness coach's clients.
 *
 * The coach picks a client from their assigned roster and every panel below
 * (behaviour, habits, sleep, challenges) reports on
 * that client for the selected 7/30/90-day window. Scoping is enforced
 * server-side: /coach/* only ever returns users with an active row in
 * coach_assignments, so an unassigned client id 404s.
 *
 * This file is composition only — fetching lives in `useCoachDashboard` and
 * every section is a component under components/wellness.
 */
import React, { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { HiOutlineExclamationTriangle } from 'react-icons/hi2';
import useAuthStore from '../store/authStore';
import useCoachDashboard from '../hooks/useCoachDashboard';
import WellnessHeader from '../components/wellness/WellnessHeader';
import WellnessKpiCards from '../components/wellness/WellnessKpiCards';
import ClientList from '../components/wellness/ClientList';
import ClientDetails, { ClientBanner } from '../components/wellness/ClientDetails';
import BehaviourInsights from '../components/wellness/BehaviourInsights';
import HabitInsights from '../components/wellness/HabitInsights';
import SleepTrends from '../components/wellness/SleepTrends';
import ChallengePerformance from '../components/wellness/ChallengePerformance';
import WellnessAnalytics from '../components/wellness/WellnessAnalytics';
import { clientDisplayName } from '../components/wellness/constants';

export default function WellnessCoachDashboard() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const dash = useCoachDashboard();

  const handleLogout = useCallback(async () => {
    await logout();
    navigate('/login');
  }, [logout, navigate]);

  const clientName = clientDisplayName(dash.clientRow);

  // Initial roster load — nothing meaningful to render yet.
  if (dash.rosterLoading && !dash.pageMeta && !dash.overview) {
    return (
      <div
        className="flex items-center justify-center min-h-[40vh]"
        role="status"
        aria-live="polite"
      >
        <div className="w-10 h-10 border-4 border-accent-500 border-t-transparent rounded-full animate-spin" />
        <span className="sr-only">Loading your coaching workspace</span>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <WellnessHeader
        user={user}
        days={dash.days}
        onDaysChange={dash.setDays}
        onRefresh={dash.refreshAll}
        refreshing={dash.refreshing}
        onLogout={handleLogout}
      />

      {dash.periodIsLoading && (
        <div
          className="flex min-h-64 flex-col items-center justify-center gap-3 border border-surface-700/40 bg-surface-900/30"
          role="status"
          aria-live="polite"
        >
          <div className="w-9 h-9 border-4 border-violet-400 border-t-transparent rounded-full animate-spin" />
          <div className="text-center">
            <p className="text-sm font-medium text-slate-200">Updating dashboard analytics</p>
            <p className="text-xs text-slate-500">Calculating the last {dash.days} days</p>
          </div>
        </div>
      )}

      {/* Panels stay mounted while the window changes, so a period switch never
          shows 7-day copy next to 30-day figures. */}
      <div className={dash.periodIsLoading ? 'hidden' : 'contents'}>
        {dash.rosterError && (
          <div
            className="card flex flex-wrap items-center justify-between gap-3 border-red-500/30"
            role="alert"
          >
            <div className="flex items-center gap-2 text-sm text-red-300">
              <HiOutlineExclamationTriangle className="w-5 h-5" />
              {dash.rosterError}
            </div>
            <button type="button" onClick={dash.reloadRoster} className="btn-secondary text-sm">
              Try again
            </button>
          </div>
        )}

        <WellnessKpiCards
          overview={dash.overview}
          days={dash.days}
          error={dash.rosterError}
          onRetry={dash.reloadRoster}
        />

        <ClientList
          clients={dash.clients}
          pageMeta={dash.pageMeta}
          loading={dash.rosterLoading}
          error={dash.rosterError}
          onRetry={dash.reloadRoster}
          selectedId={dash.selectedId}
          onSelect={dash.setSelectedId}
          onPrevPage={() => dash.setPage((p) => Math.max(1, p - 1))}
          onNextPage={() =>
            dash.setPage((p) => Math.min(dash.pageMeta?.total_pages ?? p, p + 1))
          }
          searchInput={dash.searchInput}
          onSearchChange={dash.setSearchInput}
          sortKey={dash.sortKey}
          onSortChange={(value) => {
            dash.setSortKey(value);
            dash.setPage(1);
          }}
          statusFilter={dash.statusFilter}
          onStatusChange={(value) => {
            dash.setStatusFilter(value);
            dash.setPage(1);
          }}
        />

        {dash.selectedId ? (
          <>
            <ClientBanner clientRow={dash.clientRow} />

            {dash.clientErrorSummary && (
              <div
                className="card flex flex-wrap items-center justify-between gap-3 border-red-500/30"
                role="alert"
              >
                <div className="flex items-center gap-2 text-sm text-red-300">
                  <HiOutlineExclamationTriangle className="w-5 h-5" />
                  {dash.clientErrorSummary}
                </div>
                <button
                  type="button"
                  onClick={dash.reloadClient}
                  className="btn-secondary text-sm"
                >
                  Try again
                </button>
              </div>
            )}

            {dash.clientLoading && !dash.behavioral ? (
              <div
                className="flex items-center justify-center py-16"
                role="status"
                aria-live="polite"
              >
                <div className="w-10 h-10 border-4 border-accent-500 border-t-transparent rounded-full animate-spin" />
                <span className="sr-only">Loading client analytics</span>
              </div>
            ) : (
              <>
                <ClientDetails
                  clientRow={dash.clientRow}
                  clientDetail={dash.clientDetail}
                  behavioral={dash.behavioral}
                  detailError={dash.clientErrors.detail}
                  behavioralError={dash.clientErrors.behavioral}
                  onRetry={dash.reloadClient}
                />

                <BehaviourInsights
                  behavioral={dash.behavioral}
                  days={dash.days}
                  error={dash.clientErrors.behavioral}
                  onRetry={dash.reloadClient}
                />

                <HabitInsights
                  behavioral={dash.behavioral}
                  clientRow={dash.clientRow}
                  days={dash.days}
                  error={dash.clientErrors.behavioral}
                  onRetry={dash.reloadClient}
                />

                <SleepTrends
                  behavioral={dash.behavioral}
                  clientRow={dash.clientRow}
                  days={dash.days}
                  error={dash.clientErrors.behavioral}
                  onRetry={dash.reloadClient}
                />

                <ChallengePerformance
                  challenge={dash.challenge}
                  clientRow={dash.clientRow}
                  error={dash.clientErrors.challenge}
                  onRetry={dash.reloadClient}
                />

                <WellnessAnalytics
                  behavioral={dash.behavioral}
                  challenge={dash.challenge}
                  clientName={clientName}
                  error={dash.clientErrors.behavioral}
                  onRetry={dash.reloadClient}
                />
              </>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
