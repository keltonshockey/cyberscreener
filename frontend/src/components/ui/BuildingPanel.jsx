/**
 * QUAEST.TECH — Building Panel Overlay
 * Full-screen overlay panel shown when player enters a building.
 * Renders the corresponding site tab content (Conviction, Anvil, Archive, Basilica).
 * Player can still move in background — walk out of building to auto-dismiss.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import styles from './BuildingPanel.module.css';

// Building metadata for panel headers
const BUILDING_META = {
  curia: {
    name: 'The Curia',
    subtitle: 'Conviction Board',
    desc: 'Long-term stock analysis and scoring',
    icon: '\u{1F3DB}', // classical building
    accentColor: '#B8860B',
  },
  basilica: {
    name: 'Basilica Julia',
    subtitle: 'Command Overview',
    desc: 'Market indices, killer plays, and leaders',
    icon: '\u{1F3E6}', // bank
    accentColor: '#665D1E',
  },
  subura: {
    name: 'The Subura',
    subtitle: 'The Anvil',
    desc: 'Options plays, weight tuning, and Reality Check',
    icon: '\u{2692}',  // hammer & pick
    accentColor: '#888',
  },
  tabularium: {
    name: 'The Tabularium',
    subtitle: 'The Archive',
    desc: 'Backtesting, calibration, and research',
    icon: '\u{1F4DC}', // scroll
    accentColor: '#8B2500',
  },
};

export function BuildingPanel({ buildingId, onClose, children }) {
  const [visible, setVisible] = useState(false);
  const meta = BUILDING_META[buildingId];
  const panelRef = useRef(null);

  // Animate in
  useEffect(() => {
    const t = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(t);
  }, []);

  // ESC to close
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose?.();
      }
    };
    window.addEventListener('keydown', handleKey, true); // capture phase
    return () => window.removeEventListener('keydown', handleKey, true);
  }, [onClose]);

  const handleClose = useCallback(() => {
    setVisible(false);
    setTimeout(() => onClose?.(), 200);
  }, [onClose]);

  // Click outside panel to close
  const handleOverlayClick = useCallback((e) => {
    if (panelRef.current && !panelRef.current.contains(e.target)) {
      handleClose();
    }
  }, [handleClose]);

  if (!meta) return null;

  return (
    <div
      className={`${styles.overlay} ${visible ? styles.visible : ''}`}
      onClick={handleOverlayClick}
    >
      <div className={styles.panel} ref={panelRef}>
        {/* Header */}
        <div className={styles.header} style={{ borderBottomColor: meta.accentColor }}>
          <div className={styles.headerLeft}>
            <span className={styles.headerIcon}>{meta.icon}</span>
            <div>
              <div className={styles.headerTitle}>{meta.name}</div>
              <div className={styles.headerSub}>{meta.subtitle} — {meta.desc}</div>
            </div>
          </div>
          <button className={styles.closeBtn} onClick={handleClose} title="Close (ESC)">
            &times;
          </button>
        </div>

        {/* Content — receives the page component as children */}
        <div className={styles.content}>
          {children}
        </div>

        {/* Footer hint */}
        <div className={styles.footer}>
          <span className={styles.footerKey}>ESC</span> Close
          <span className={styles.footerDivider} />
          Walk outside to return to the world
        </div>
      </div>
    </div>
  );
}
