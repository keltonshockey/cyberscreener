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
export const fetchLatestScores = (limit = 600) => api(`/scores/latest?limit=${limit}`);
export const fetchPersonalizedScores = (limit = 600) => api(`/scores/latest/personalized?limit=${limit}`);
export const fetchScoreHistory = (ticker, days = 180) => api(`/scores/${ticker}?days=${days}`);
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
export const fetchWatchlist = () => api('/watchlist');
export const addWatchlistTicker = (ticker, notes, sector) =>
  api('/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticker, notes, sector }) });
export const removeWatchlistTicker = (ticker) => api(`/watchlist/${ticker}`, { method: 'DELETE' });

// ── AI Analysis ──
export const analyzePlaysTicker = (ticker) => api(`/plays/${ticker}/analyze`, { method: 'POST' });
export const fetchAIStatus = () => api('/ai/status');

// ── Admin ──
export const promoteUser = (userId) => api(`/admin/promote/${userId}`, { method: 'POST' });
