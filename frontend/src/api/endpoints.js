/**
 * QUAEST.TECH — API Endpoints
 * Typed wrapper functions for all backend routes.
 */

import { api } from './client';

// ── Auth ──
export const authLogin = (email, password) =>
  api('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });

export const authRegister = (email, password, augur_name) =>
  api('/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password, augur_name }) });

export const authRefresh = (refresh_token) =>
  api('/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token }) });

export const authMe = () => api('/auth/me');
export const authLogout = () => api('/auth/logout', { method: 'POST' });

// ── Augur / Quaestor ──
export const augurCreate = (attrs) =>
  api('/augur/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(attrs) });

export const augurRespec = (attrs) =>
  api('/augur/respec', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(attrs) });

export const augurProfile = () => api('/augur/profile');
export const augurPublic = (id) => api(`/augur/${id}`);
export const augurLeaderboard = () => api('/augur/leaderboard/top');

// ── Scores ──
export const fetchStats = () => api('/stats');
// Baseline-vs-layers config: membership, captions, ref weights (SESSION-BASELINE-WEIGHTS).
export const fetchLayers = () => api('/layers');
export const fetchLatestScores = (limit = 600) => api(`/scores/latest?limit=${limit}`);
export const fetchPersonalizedScores = (limit = 600) => api(`/scores/latest/personalized?limit=${limit}`);
export const fetchScoreHistory = (ticker, days = 180) => api(`/scores/${ticker}?days=${days}`);
// Recent close-price series per ticker for real grid sparklines (§3).
export const fetchSparklines = (tickers, points = 30) =>
  api(`/prices/sparklines?tickers=${encodeURIComponent((tickers || []).join(','))}&points=${points}`);
export const fetchSignals = (ticker, limit = 40) => api(`/signals/${ticker}/recent?limit=${limit}`);
export const fetchMomentumSignals = (limit = 20) => api(`/signals/momentum?limit=${limit}`);

// ── Scans ──
export const triggerScan = () => api('/scan', { method: 'POST' });
export const fetchScanStatus = () => api('/scan/status');

// ── Plays ──
export const generatePlays = (ticker) => api(`/plays/${ticker}/generate`, { method: 'POST' });
export const fetchPlayStatus = (ticker) => api(`/plays/${ticker}/status`);
export const fetchPlayHistory = (limit = 50) => api(`/plays/history/all?limit=${limit}`);
export const fetchKillerPlays = (limit = 6) => api(`/killer-plays?limit=${limit}`);
export const fetchBuyZone = (limit = 6) => api(`/buy-zone?limit=${limit}`);
export const fetchInversePlays = (limit = 8) => api(`/inverse-plays?limit=${limit}`);
export const sendKillerAlerts = () => api('/alerts/send-killer-plays', { method: 'POST' });

// ── Weights ──
export const fetchWeights = () => api('/weights');
export const updateWeights = (weights) =>
  api('/weights', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(weights) });
export const fetchWeightsHistory = (limit = 30) => api(`/weights/history?limit=${limit}`);

// ── Backtest ──
export const fetchBacktest = (days = 180, forwardPeriod = 30) =>
  api(`/backtest?days=${days}&forward_period=${forwardPeriod}`);
export const runCalibrate = (dryRun = false) =>
  api(`/calibrate${dryRun ? '?dry_run=true' : ''}`, { method: 'POST' });

// ── Market ──
export const fetchMarketIndices = () => api('/market/indices');
export const fetchChart = (ticker, days = 180) => api(`/chart/${ticker}?days=${days}`);

// ── Intel ──
export const fetchIntelNews = () => api('/intel/news');
export const fetchIntelOutages = () => api('/intel/outages');

// ── Watchlist ──
// Monthly Valuation Watchlist snapshot (read-only, previous-month scan).
export const fetchValuationWatchlist = (limit = 25) => api(`/watchlist/valuation?limit=${limit}`);
export const fetchWatchlist = () => api('/watchlist');
export const addWatchlistTicker = (ticker, notes, sector) =>
  api('/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker, notes, sector }) });
export const removeWatchlistTicker = (ticker) => api(`/watchlist/${ticker}`, { method: 'DELETE' });

// ── AI Analysis ──
export const analyzePlaysTicker = (ticker) => api(`/plays/${ticker}/analyze`, { method: 'POST' });
export const fetchAIStatus = () => api('/ai/status');

// The per-ticker narrative helper (fetchNarrative) was retired frontend-only
// in V3C (D3, 2026-08-10). The backend /narrative/{ticker} endpoint and the
// mill pipeline stay live and dormant; reintroduce a helper here to revive.

// ── UI config (runtime feature flags, e.g. the world pause) ──
export const fetchUiConfig = () => api('/config/ui');

// ── Admin ──
export const promoteUser = (userId) => api(`/admin/promote/${userId}`, { method: 'POST' });
