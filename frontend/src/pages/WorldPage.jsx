/**
 * QUAEST.TECH — The World (3D Voxel Forum)
 * Roman city where Quaestors explore buildings that contain the site's content.
 * Each building maps to a site tab:
 *   Curia      -> Conviction (stock scores)
 *   Basilica   -> Overview (market dashboard)
 *   Subura     -> Anvil (options plays)
 *   Tabularium -> Archive (backtest/research)
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { BuildingPanel } from '../components/ui/BuildingPanel';
import { useAuth } from '../auth/AuthContext';
import { VoxelGame } from '../game/VoxelGame';
import { DISTRICT_INFO } from '../game/config';
import { fetchStats, fetchLatestScores, fetchBacktest } from '../api/endpoints';
import { getStoredTz } from '../utils/formatters';

// Lazy imports for page content (code-split already by Vite)
import { BasilicaPage } from './BasilicaPage';
import { ConvictionPage } from './ConvictionPage';
import { AnvilPage } from './AnvilPage';
import { ArchivePage } from './ArchivePage';
import styles from './WorldPage.module.css';

// Building -> Tab mapping
const BUILDING_TAB = {
  basilica: 'basilica',
  curia: 'conviction',
  subura: 'anvil',
  tabularium: 'archive',
};

export function WorldPage() {
  const { user, profile } = useAuth();
  const gameRef = useRef(null);
  const [currentDistrict, setCurrentDistrict] = useState(null);
  const [dialogLog, setDialogLog] = useState([]);
  const [chatInput, setChatInput] = useState('');

  // Building panel state
  const [activeBuilding, setActiveBuilding] = useState(null);

  // Data state for embedded pages
  const [stats, setStats] = useState(null);
  const [latest, setLatest] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [dataLoaded, setDataLoaded] = useState(false);
  const tz = getStoredTz();

  // Load site data when a building is first entered
  const loadSiteData = useCallback(async () => {
    if (dataLoaded) return;
    const [s, l] = await Promise.all([
      fetchStats(),
      fetchLatestScores(600),
    ]);
    if (s) setStats(s);
    if (l) setLatest(l);
    setDataLoaded(true);
  }, [dataLoaded]);

  // Load backtest data lazily when archive building is entered
  const loadBacktest = useCallback(async () => {
    if (backtest) return;
    const d = await fetchBacktest(180, 30);
    if (d) setBacktest(d);
  }, [backtest]);

  const onDistrictChange = useCallback((district) => {
    setCurrentDistrict(district);
    if (district) {
      setDialogLog(prev => [
        ...prev.slice(-19),
        { type: 'system', text: `Entered ${district.name}`, time: new Date() },
      ]);
    }
  }, []);

  const onInteract = useCallback((interaction) => {
    setDialogLog(prev => [
      ...prev.slice(-19),
      {
        type: interaction.type,
        name: interaction.name,
        text: interaction.dialog,
        time: new Date(),
      },
    ]);
  }, []);

  const onBuildingEnter = useCallback((buildingId) => {
    setActiveBuilding(buildingId);
    // Load data for the panel
    loadSiteData();
    if (buildingId === 'tabularium') loadBacktest();
    // Log entry
    setDialogLog(prev => [
      ...prev.slice(-19),
      { type: 'system', text: `Entered building interior`, time: new Date() },
    ]);
  }, [loadSiteData, loadBacktest]);

  const onBuildingExit = useCallback(() => {
    setActiveBuilding(null);
  }, []);

  const handlePanelClose = useCallback(() => {
    setActiveBuilding(null);
  }, []);

  const handleChat = (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    setDialogLog(prev => [
      ...prev.slice(-19),
      {
        type: 'player',
        name: profile?.name || user?.email || 'You',
        text: chatInput,
        time: new Date(),
      },
    ]);
    setChatInput('');
  };

  // Render the content for the active building
  const renderBuildingContent = () => {
    if (!activeBuilding) return null;
    const tab = BUILDING_TAB[activeBuilding];

    switch (tab) {
      case 'basilica':
        return <BasilicaPage stats={stats} latest={latest} tz={tz} />;
      case 'conviction':
        return <ConvictionPage latest={latest} />;
      case 'anvil':
        return <AnvilPage latest={latest} defaultTicker={null} tz={tz} />;
      case 'archive':
        return <ArchivePage backtest={backtest} tz={tz} />;
      default:
        return <div style={{ padding: 40, textAlign: 'center', color: 'var(--color-text-secondary)' }}>This building is empty...</div>;
    }
  };

  return (
    <div className={styles.layout}>
      {/* Game viewport */}
      <div className={styles.gameContainer}>
        <VoxelGame
          ref={gameRef}
          onDistrictChange={onDistrictChange}
          onInteract={onInteract}
          onBuildingEnter={onBuildingEnter}
          onBuildingExit={onBuildingExit}
        />

        {/* Controls hint */}
        <div className={styles.controlsBar}>
          <span className={styles.controlKey}>WASD</span> Move
          <span className={styles.controlDivider} />
          <span className={styles.controlKey}>E</span> Interact
          <span className={styles.controlDivider} />
          <span className={styles.controlKey}>Click</span> Walk to
          <span className={styles.controlDivider} />
          Enter a building to access its tools
        </div>
      </div>

      {/* Sidebar */}
      <div className={styles.sidebar}>
        {/* District info */}
        <Card style={{ padding: 14 }}>
          <div className={styles.sectionLabel}>Current Location</div>
          {currentDistrict ? (
            <div className={styles.districtInfo}>
              <div className={styles.districtName} style={{ color: currentDistrict.labelColor }}>
                {currentDistrict.name}
              </div>
              <div className={styles.districtDesc}>{currentDistrict.desc}</div>
              {currentDistrict.locked && (
                <Badge color="var(--forge-amber)" variant="soft">
                  Requires {currentDistrict.locked}+ Grade
                </Badge>
              )}
            </div>
          ) : (
            <div className={styles.districtDesc}>Wandering the roads...</div>
          )}
        </Card>

        {/* Building guide */}
        <Card style={{ padding: 14 }}>
          <div className={styles.sectionLabel}>Buildings</div>
          <div className={styles.legendList}>
            {[
              { id: 'basilica', name: 'Basilica Julia', tab: 'Overview', color: '#665D1E', icon: '\u{1F3E6}' },
              { id: 'curia', name: 'The Curia', tab: 'Conviction', color: '#B8860B', icon: '\u{1F3DB}' },
              { id: 'subura', name: 'The Subura', tab: 'Anvil', color: '#888', icon: '\u{2692}' },
              { id: 'tabularium', name: 'The Tabularium', tab: 'Archive', color: '#8B2500', icon: '\u{1F4DC}' },
            ].map(b => (
              <div
                key={b.id}
                className={`${styles.legendItem} ${activeBuilding === b.id ? styles.legendActive : ''}`}
              >
                <span className={styles.legendDot} style={{ background: b.color }} />
                <span className={styles.legendName}>
                  <span style={{ marginRight: 4 }}>{b.icon}</span>
                  {b.name}
                </span>
                <span className={styles.legendTab}>{b.tab}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Chat / Dialog log */}
        <Card style={{ padding: 14, flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div className={styles.sectionLabel}>Scroll Feed</div>
          <div className={styles.chatLog}>
            {dialogLog.length === 0 ? (
              <div className={styles.chatEmpty}>
                Walk up to NPCs and press <strong>E</strong> to interact.
                <br />
                Enter buildings to access site tools.
              </div>
            ) : (
              dialogLog.map((msg, i) => (
                <div key={i} className={`${styles.chatMsg} ${styles[`chat_${msg.type}`]}`}>
                  {msg.name && <span className={styles.chatName}>{msg.name}</span>}
                  <span className={styles.chatText}>{msg.text}</span>
                </div>
              ))
            )}
          </div>

          {/* Chat input */}
          <form className={styles.chatForm} onSubmit={handleChat}>
            <input
              className={styles.chatInput}
              type="text"
              placeholder={user ? 'Say something...' : 'Sign in to chat'}
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              disabled={!user}
              onFocus={() => {
                gameRef.current?.setKeyboardEnabled(false);
              }}
              onBlur={() => {
                if (!activeBuilding) {
                  gameRef.current?.setKeyboardEnabled(true);
                }
              }}
            />
            <button className={styles.chatSend} type="submit" disabled={!user || !chatInput.trim()}>
              Send
            </button>
          </form>
        </Card>
      </div>

      {/* Building content overlay */}
      {activeBuilding && (
        <BuildingPanel
          buildingId={activeBuilding}
          onClose={handlePanelClose}
        >
          {renderBuildingContent()}
        </BuildingPanel>
      )}
    </div>
  );
}
