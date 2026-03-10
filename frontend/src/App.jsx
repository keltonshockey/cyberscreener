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
import { BasilicaPage } from './pages/BasilicaPage';
import { ConvictionPage } from './pages/ConvictionPage';
import { AnvilPage } from './pages/AnvilPage';
import { ArchivePage } from './pages/ArchivePage';

// Lazy-load World page (includes Phaser ~1MB) — only downloaded when user visits /world
const WorldPage = lazy(() => import('./pages/WorldPage').then(m => ({ default: m.WorldPage })));
import { fetchStats, fetchLatestScores, fetchBacktest, triggerScan, fetchScanStatus } from './api/endpoints';
import { getStoredTz } from './utils/formatters';

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
  const tz = getStoredTz();

  // ── Load core data ──
  const loadData = useCallback(async () => {
    const [s, l] = await Promise.all([
      fetchStats(),
      fetchLatestScores(600),
    ]);
    if (s) setStats(s);
    if (l) setLatest(l);
  }, []);

  useEffect(() => {
    loadData();
    // Refresh every 5 minutes
    const interval = setInterval(loadData, 300000);
    return () => clearInterval(interval);
  }, [loadData]);

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

  // Anvil default ticker from location state
  const anvilTicker = location.state?.ticker || null;

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
      <NavBar onRunScan={handleRunScan} scanRunning={scanRunning} />

      <main style={{ flex: 1, padding: '20px 24px', maxWidth: 1400, width: '100%', margin: '0 auto' }}>
        <Routes>
          <Route
            path="/"
            element={<BasilicaPage stats={stats} latest={latest} tz={tz} />}
          />
          <Route
            path="/conviction"
            element={<ConvictionPage latest={latest} />}
          />
          <Route
            path="/anvil"
            element={<AnvilPage latest={latest} defaultTicker={anvilTicker} tz={tz} />}
          />
          <Route
            path="/archive"
            element={<ArchivePage backtest={backtest} tz={tz} />}
          />
          <Route
            path="/world"
            element={
              <Suspense fallback={<div style={{ textAlign: 'center', padding: 60, color: 'var(--color-text-secondary)' }}>Loading world...</div>}>
                <WorldPage />
              </Suspense>
            }
          />
        </Routes>
      </main>

      <Footer />
    </div>
  );
}
