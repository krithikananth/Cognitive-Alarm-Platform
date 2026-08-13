/**
 * Data layer for the Wellness Coach dashboard.
 *
 * Owns every /coach/* request plus the roster filters, the 7/30/90-day window,
 * and the currently selected client. Keeping it out of the view means the
 * panels stay presentational and each one can be told, individually, whether
 * its own request succeeded, failed, or simply returned no data.
 *
 * Per-resource errors matter: the client panels are five independent requests,
 * so a single failure must surface as an error in that panel rather than as an
 * empty chart that looks like "this client has no activity".
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { coachAPI } from '../services/api';
import { CLIENTS_PER_PAGE } from '../components/wellness/constants';

const CLIENT_RESOURCES = [
  'detail',
  'behavioral',
  'recommendations',
  'productivity',
  'challenge',
  'sleepTrends',
  'wakeConsistency',
  'habitScore',
];

const NO_CLIENT_ERRORS = Object.freeze(
  CLIENT_RESOURCES.reduce((acc, key) => ({ ...acc, [key]: null }), {})
);

const EMPTY_CLIENT_DATA = {
  clientDetail: null,
  behavioral: null,
  digest: null,
  productivity: null,
  challenge: null,
  sleepTrends: null,
  wakeConsistency: null,
  habitScore: null,
};

/** Message for a failed panel request, distinguishing 403/404 from an outage. */
function errorMessage(reason, fallback) {
  const status = reason?.response?.status;
  if (status === 403 || status === 404) {
    return 'This client is no longer available on your roster.';
  }
  return fallback;
}

export default function useCoachDashboard() {
  // ── Roster state ──
  const [overview, setOverview] = useState(null);
  const [clients, setClients] = useState([]);
  const [pageMeta, setPageMeta] = useState(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortKey, setSortKey] = useState('full_name:asc');
  const [days, setDays] = useState(30);
  const [loadedRosterDays, setLoadedRosterDays] = useState(null);
  const [rosterLoading, setRosterLoading] = useState(true);
  const [rosterError, setRosterError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // ── Selected client state ──
  const [selectedId, setSelectedId] = useState(null);
  const [clientRow, setClientRow] = useState(null);
  const [clientData, setClientData] = useState(EMPTY_CLIENT_DATA);
  const [clientErrors, setClientErrors] = useState(NO_CLIENT_ERRORS);
  const [clientLoading, setClientLoading] = useState(false);
  const [loadedClientDays, setLoadedClientDays] = useState(null);

  const rosterRequestRef = useRef(0);
  const clientRequestRef = useRef(0);

  // Debounce search so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const loadRoster = useCallback(
    async (isRefresh = false) => {
      const requestId = ++rosterRequestRef.current;
      if (isRefresh) setRefreshing(true);
      else setRosterLoading(true);
      setRosterError(null);

      const [sortBy, sortOrder] = sortKey.split(':');
      const results = await Promise.allSettled([
        coachAPI.getOverview(days),
        coachAPI.listClients({
          page,
          per_page: CLIENTS_PER_PAGE,
          search: search || undefined,
          status: statusFilter,
          sort_by: sortBy,
          sort_order: sortOrder,
          days,
        }),
      ]);

      if (requestId !== rosterRequestRef.current) return;

      const [overviewRes, clientsRes] = results;
      setOverview(overviewRes.status === 'fulfilled' ? overviewRes.value.data : null);

      if (clientsRes.status === 'fulfilled') {
        const payload = clientsRes.value.data;
        setClients(payload.clients || []);
        setPageMeta(payload);
      } else {
        setClients([]);
        setPageMeta(null);
      }

      // Either half failing leaves the roster view incomplete, so say so
      // instead of rendering a partially-blank overview as if it were real.
      if (results.some((r) => r.status === 'rejected')) {
        setRosterError('Failed to load your client roster.');
      }

      setLoadedRosterDays(days);
      setRosterLoading(false);
      setRefreshing(false);
    },
    [days, page, search, statusFilter, sortKey]
  );

  useEffect(() => {
    loadRoster(false);
  }, [loadRoster]);

  // Keep a valid selection as the roster changes; default to the first client.
  useEffect(() => {
    if (!clients.length) {
      setSelectedId(null);
      return;
    }
    setSelectedId((current) => {
      if (current && clients.some((c) => c.client_id === current)) return current;
      return clients[0].client_id;
    });
  }, [clients]);

  // Roster rows already carry the headline metrics, so show them immediately
  // while the deeper per-client analytics load.
  useEffect(() => {
    setClientRow(clients.find((c) => c.client_id === selectedId) || null);
  }, [clients, selectedId]);

  const loadClient = useCallback(async (clientId, windowDays) => {
    if (!clientId) return;
    const requestId = ++clientRequestRef.current;
    setClientLoading(true);
    setClientErrors(NO_CLIENT_ERRORS);

    const results = await Promise.allSettled([
      coachAPI.getClient(clientId, windowDays),
      coachAPI.getBehavioral(clientId, windowDays),
      coachAPI.getRecommendations(clientId),
      coachAPI.getProductivity(clientId, windowDays),
      coachAPI.getChallengePerformance(clientId, windowDays),
      coachAPI.getSleepTrends(clientId, windowDays),
      coachAPI.getWakeConsistency(clientId, windowDays),
      coachAPI.getHabitScore(clientId, windowDays),
    ]);

    if (requestId !== clientRequestRef.current) return;

    const [
      detailRes,
      behavioralRes,
      digestRes,
      productivityRes,
      challengeRes,
      sleepTrendsRes,
      wakeConsistencyRes,
      habitScoreRes,
    ] = results;

    setClientData({
      clientDetail: detailRes.status === 'fulfilled' ? detailRes.value.data : null,
      behavioral:
        behavioralRes.status === 'fulfilled' ? behavioralRes.value.data.data : null,
      digest: digestRes.status === 'fulfilled' ? digestRes.value.data : null,
      productivity:
        productivityRes.status === 'fulfilled' ? productivityRes.value.data.data : null,
      challenge:
        challengeRes.status === 'fulfilled' ? challengeRes.value.data.data : null,
      sleepTrends:
        sleepTrendsRes.status === 'fulfilled' ? sleepTrendsRes.value.data.data : null,
      wakeConsistency:
        wakeConsistencyRes.status === 'fulfilled'
          ? wakeConsistencyRes.value.data.data
          : null,
      habitScore:
        habitScoreRes.status === 'fulfilled' ? habitScoreRes.value.data.data : null,
    });

    const fallbacks = {
      detail: 'Profile details could not be loaded.',
      behavioral: 'Behaviour analytics could not be loaded.',
      recommendations: 'Coaching recommendations could not be loaded.',
      productivity: 'Productivity analytics could not be loaded.',
      challenge: 'Challenge performance could not be loaded.',
      sleepTrends: 'Sleep trends could not be loaded.',
      wakeConsistency: 'Wake consistency could not be loaded.',
      habitScore: 'Habit score could not be loaded.',
    };
    setClientErrors(
      CLIENT_RESOURCES.reduce((acc, key, index) => {
        const result = results[index];
        acc[key] =
          result.status === 'rejected'
            ? errorMessage(result.reason, fallbacks[key])
            : null;
        return acc;
      }, {})
    );

    setLoadedClientDays(windowDays);
    setClientLoading(false);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setClientData(EMPTY_CLIENT_DATA);
      setClientErrors(NO_CLIENT_ERRORS);
      return;
    }
    loadClient(selectedId, days);
  }, [selectedId, days, loadClient]);

  const reloadClient = useCallback(() => {
    if (selectedId) loadClient(selectedId, days);
  }, [loadClient, selectedId, days]);

  const refreshAll = useCallback(() => {
    loadRoster(true);
    reloadClient();
  }, [loadRoster, reloadClient]);

  const clientErrorSummary = useMemo(
    () =>
      CLIENT_RESOURCES.every((key) => clientErrors[key])
        ? 'Failed to load this client’s coaching data.'
        : null,
    [clientErrors]
  );

  // True while the visible numbers still describe the previously selected
  // window — prevents 7-day copy from being shown next to 30-day figures.
  const periodIsLoading =
    loadedRosterDays !== days || Boolean(selectedId && loadedClientDays !== days);

  // Each panel prefers its dedicated route's payload and falls back to the
  // behavioural umbrella, so one failed request degrades instead of blanking.
  const merge = (extra) =>
    extra ? { ...(clientData.behavioral || {}), ...extra } : clientData.behavioral;

  return {
    // roster
    overview,
    clients,
    pageMeta,
    page,
    setPage,
    searchInput,
    setSearchInput,
    statusFilter,
    setStatusFilter,
    sortKey,
    setSortKey,
    days,
    setDays,
    rosterLoading,
    rosterError,
    refreshing,
    reloadRoster: () => loadRoster(true),
    refreshAll,
    // selection
    selectedId,
    setSelectedId,
    clientRow,
    ...clientData,
    behaviourPayload: merge(clientData.wakeConsistency),
    habitPayload: merge(clientData.habitScore),
    sleepPayload: merge(clientData.sleepTrends),
    clientErrors,
    clientErrorSummary,
    clientLoading,
    reloadClient,
    periodIsLoading,
  };
}
