/**
 * QUAEST.TECH — App Shell
 * Root component with router, data loading, and auth state management.
 */

import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { Header } from './components/layout/Header';
import { NavBar } from './components/layout/NavBar';
import { Footer } from './components/layout/Footer';
import { LoginPage } from './auth/LoginPage';
import { RegisterPage } from './auth/RegisterPage';
import { QuaestorCreator } from './auth/QuaestorCreator';
import { WatchlistPage } from './pages/WatchlistPage';
import { BasilicaPage } from './pages/BasilicaPage';
import { ConvictionPage } from './pages/ConvictionPage';
import { PactumPage } from './pages/PactumPage';
import { ArchivePage } from './pages/ArchivePage';
import { TickerPage } from './pages/TickerPage';

// Lazy-load World page (includes Phaser ~1MB) — only downloaded when user visits /world
const WorldPage = lazy(() => import('./pages/WorldPage').then(m => ({ default: m.WorldPage })));
import { fetchStats, fetchLatestScores, fetchBacktest, triggerScan, fetchScanStatus, fetchUiConfig } from './api/endpoints';
import { getStoredTz } from './utils/formatters';

// World PAUSE notice (SESSION-SLIM-SCOPE): shown on a direct /world visit
// while the world is paused. Source stays in the repo; flip WORLD_ENABLED=1
// on the server to revive — no rebuild.
function WorldPaused() {
  return (
    <div style={{ textAlign: 'center', padding: 80, color: 'var(--color-text-secondary)' }}>
      <div style={{ fontSize: 15, letterSpacing: '0.12em', marginBottom: 10 }}>WORLD VIEW IS PAUSED</div>
      <div style={{ fontSize: 13 }}>
        The 3D city is on hold while the scoring core gets rebuilt. It will return.
      </div>
    </div>
  );
}

export function App() {
  const { user, profile } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  // ── Auth flow state ──
  const [authMode, setAuthMode] = useState(null); // 'login' | 'register' | 'creator' | null
  const [showAuth, setShowAuth] = useState(false);

  // ── Data state ──
  const [stats, setStats] = useState(null);
  const [latest, setLatest] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [scanRunning, setScanRunning] = useState(false);
  // World pause flag — paused by default until /config/ui says otherwise.
  const [worldEnabled, setWorldEnabled] = useState(false);
  const tz = getStoredTz();

  useEffect(() => {
    fetchUiConfig().then(c => setWorldEnabled(!!c?.world_enabled)).catch(() => {});
  }, []);

  // ── Load core data (non-blocking — scores first, stats deferred) ──
  const loadScores = useCallback(async () => {
    const l = await fetchLatestScores(600);
    if (l) setLatest(l);
  }, []);

  const loadStats = useCallback(async () => {
    const s = await fetchStats();
    if (s) setStats(s);
  }, []);

  const loadData = useCallback(async () => {
    await Promise.all([loadScores(), loadStats()]);
  }, [loadScores, loadStats]);

  useEffect(() => {
    // Load scores immediately (renders page), stats in parallel (non-blocking)
    loadScores();
    loadStats();
    // Refresh every 5 minutes
    const interval = setInterval(loadData, 300000);
    return () => clearInterval(interval);
  }, [loadScores, loadStats, loadData]);

  // Load backtest lazily when Archive page is visited
  useEffect(() => {
    if (location.pathname === '/archive' && !backtest) {
      fetchBacktest(180, 30).then(d => { if (d) setBacktest(d); });
    }
  }, [location.pathname, backtest]);

  // ── Scan handler ──
  const handleRunScan = useCallback(async () => {
    setScanRunning(true);
    await triggerScan();
    // Poll for completion
    const poll = setInterval(async () => {
      const s = await fetchScanStatus();
      if (s && s.status !== 'running') {
        clearInterval(poll);
        setScanRunning(false);
        loadData(); // Refresh data
      }
    }, 5000);
    // Timeout after 5 minutes
    setTimeout(() => { clearInterval(poll); setScanRunning(false); }, 300000);
  }, [loadData]);

  // ── Auth flow handlers ──
  const handleAuthClick = () => {
    setAuthMode('login');
    setShowAuth(true);
  };

  const handleLoginSuccess = (result) => {
    setShowAuth(false);
    setAuthMode(null);
    if (!result.hasProfile) {
      setAuthMode('creator');
    }
  };

  const handleRegisterSuccess = () => {
    setAuthMode('creator');
  };

  const handleCreatorDone = () => {
    setAuthMode(null);
  };

  // Pactum default ticker from location state
  const pactumTicker = location.state?.ticker || null;

  // ── Auth screens (overlay the main app) ──
  if (showAuth && authMode === 'login') {
    return (
      <LoginPage
        onSwitchToRegister={() => setAuthMode('register')}
        onSuccess={handleLoginSuccess}
      />
    );
  }

  if (showAuth && authMode === 'register') {
    return (
      <RegisterPage
        onSwitchToLogin={() => setAuthMode('login')}
        onSuccess={handleRegisterSuccess}
      />
    );
  }

  if (authMode === 'creator') {
    return <QuaestorCreator onCreated={handleCreatorDone} />;
  }

  // ── Main app ──
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <Header onAuthClick={handleAuthClick} latest={latest} />
      <NavBar onRunScan={handleRunScan} scanRunning={scanRunning} worldEnabled={worldEnabled} />

      <main style={{ flex: 1, padding: '20px 24px', maxWidth: 1400, width: '100%', margin: '0 auto' }}>
        <Routes>
          {/* v3: the monthly Valuation Watchlist IS the front page; the old
              overview keeps its full self at /basilica (demotion of anything
              else is deliberately out of scope here -- session V3c). */}
          <Route
            path="/"
            element={<WatchlistPage />}
          />
          <Route
            path="/basilica"
            element={<BasilicaPage stats={stats} latest={latest} tz={tz} />}
          />
          <Route
            path="/conviction"
            element={<ConvictionPage latest={latest} />}
          />
          <Route
            path="/pactum"
            element={<PactumPage latest={latest} defaultTicker={pactumTicker} tz={tz} />}
          />
          <Route
            path="/ticker/:symbol"
            element={<TickerPage latest={latest} tz={tz} />}
          />
          <Route
            path="/archive"
            element={<ArchivePage backtest={backtest} tz={tz} />}
          />
          <Route
            path="/world"
            element={
              worldEnabled ? (
                <Suspense fallback={<div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-secondary)' }}>Loading world...</div>}>
                  <WorldPage />
                </Suspense>
              ) : (
                <WorldPaused />
              )
            }
          />
        </Routes>
      </main>

      <Footer />
    </div>
  );
}
