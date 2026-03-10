/**
 * QUAEST.TECH — District Panel
 * Renders the appropriate dashboard page inline when the player enters a building.
 * Slides in from the right side of the World page.
 */

import { useEffect, useCallback, useRef } from 'react';
import { BasilicaPage } from '../../pages/BasilicaPage';
import { ConvictionPage } from '../../pages/ConvictionPage';
import { AnvilPage } from '../../pages/AnvilPage';
import { ArchivePage } from '../../pages/ArchivePage';
import s from './DistrictPanel.module.css';

export function DistrictPanel({ district, onClose, stats, latest, backtest, tz, gameRef }) {
  const panelRef = useRef(null);

  // Disable Phaser keyboard when interacting with panel content
  const disableGameKeys = useCallback(() => {
    const game = gameRef?.current?.getGame?.();
    if (game) {
      const scene = game.scene.getScene('WorldScene');
      if (scene?.input?.keyboard) scene.input.keyboard.enabled = false;
    }
  }, [gameRef]);

  const enableGameKeys = useCallback(() => {
    const game = gameRef?.current?.getGame?.();
    if (game) {
      const scene = game.scene.getScene('WorldScene');
      if (scene?.input?.keyboard) scene.input.keyboard.enabled = true;
    }
  }, [gameRef]);

  // Re-enable game keys when panel closes
  useEffect(() => {
    return () => enableGameKeys();
  }, [enableGameKeys]);

  if (!district || !district.page) return null;

  const renderPage = () => {
    switch (district.page) {
      case 'basilica':
        return <BasilicaPage stats={stats} latest={latest} tz={tz} />;
      case 'conviction':
        return <ConvictionPage latest={latest} />;
      case 'anvil':
        return <AnvilPage latest={latest} tz={tz} />;
      case 'archive':
        return <ArchivePage backtest={backtest} tz={tz} />;
      default:
        return null;
    }
  };

  return (
    <div
      ref={panelRef}
      className={s.panel}
      onFocus={disableGameKeys}
      onMouseDown={disableGameKeys}
      onBlur={enableGameKeys}
    >
      {/* Panel header */}
      <div className={s.header} style={{ borderLeftColor: district.labelColor }}>
        <div className={s.headerInfo}>
          <span className={s.districtDot} style={{ background: district.labelColor }} />
          <h2 className={s.title}>{district.name}</h2>
          <span className={s.desc}>{district.desc}</span>
        </div>
        <button className={s.closeBtn} onClick={onClose} title="Close panel">
          {'✕'}
        </button>
      </div>

      {/* Scrollable page content */}
      <div className={s.content}>
        {renderPage()}
      </div>
    </div>
  );
}
