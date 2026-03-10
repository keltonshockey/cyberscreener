/**
 * QUAEST.TECH — Boot Scene
 * Loads all tileset, sprite, particle, and UI assets with a branded progress bar.
 * Defines all character animations.
 */

import Phaser from 'phaser';
import { COLORS } from '../config.js';

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: 'BootScene' });
  }

  preload() {
    this._createProgressBar();

    // Cache-bust suffix — use timestamp so every reload fetches fresh assets
    const v = `?v=${Date.now()}`;

    // ── Tilemap ──
    this.load.tilemapTiledJSON('roman-city', 'assets/maps/roman-city.json' + v);

    // ── Tilesets (isometric) ──
    this.load.image('terrain', 'assets/tilesets/terrain-iso.png' + v);
    this.load.image('buildings', 'assets/tilesets/buildings-iso.png' + v);
    this.load.image('decorations', 'assets/tilesets/decorations-iso.png' + v);

    // ── Character sprite sheets (4 cols × 4 rows of 32×48 frames) ──
    const cfg = { frameWidth: 32, frameHeight: 48 };
    this.load.spritesheet('player', 'assets/sprites/player.png' + v, cfg);
    this.load.spritesheet('npc-guard', 'assets/sprites/npc-guard.png' + v, cfg);
    this.load.spritesheet('npc-merchant', 'assets/sprites/npc-merchant.png' + v, cfg);
    this.load.spritesheet('npc-scholar', 'assets/sprites/npc-scholar.png' + v, cfg);
    this.load.spritesheet('npc-archivist', 'assets/sprites/npc-archivist.png' + v, cfg);
    this.load.spritesheet('npc-vendor', 'assets/sprites/npc-vendor.png' + v, cfg);

    // ── Particles ──
    this.load.image('particle-dust', 'assets/particles/dust.png' + v);
    this.load.image('particle-sparkle', 'assets/particles/sparkle.png' + v);
    this.load.image('particle-leaf', 'assets/particles/leaf.png' + v);
    this.load.image('particle-smoke', 'assets/particles/smoke.png' + v);

    // ── UI ──
    this.load.image('interact-icon', 'assets/ui/interact-icon.png' + v);
  }

  create() {
    this._createAnimations();
    this.scene.start('WorldScene');
  }

  _createProgressBar() {
    const { width, height } = this.cameras.main;
    const barW = 200;
    const barH = 12;
    const x = (width - barW) / 2;
    const y = height / 2;

    // Background
    this.add.rectangle(width / 2, y, barW + 4, barH + 4, 0x1A1A1A).setOrigin(0.5);
    this.add.rectangle(width / 2, y, barW + 4, barH + 4)
      .setStrokeStyle(1, COLORS.IMPERIAL_PURPLE).setOrigin(0.5);

    // Fill bar
    const fill = this.add.rectangle(x + 2, y - barH / 2 + 2, 0, barH, COLORS.IMPERIAL_PURPLE)
      .setOrigin(0, 0);

    // Title
    this.add.text(width / 2, y - 30, 'QUAEST.TECH', {
      fontFamily: 'Cinzel, serif',
      fontSize: '14px',
      color: '#F2F2F2',
    }).setOrigin(0.5);

    // Percentage
    const pctText = this.add.text(width / 2, y + 16, '0%', {
      fontFamily: 'monospace',
      fontSize: '8px',
      color: '#A6A6A6',
    }).setOrigin(0.5);

    this.load.on('progress', (value) => {
      fill.width = barW * value;
      pctText.setText(`${Math.floor(value * 100)}%`);
    });
  }

  _createAnimations() {
    // Direction → sprite sheet row mapping
    // Sheet layout: row 0=down, row 1=left, row 2=right, row 3=up
    // Each row has 4 frames (cols 0-3)
    const dirs = [
      { key: 'down', row: 0 },
      { key: 'left', row: 1 },
      { key: 'right', row: 2 },
      { key: 'up', row: 3 },
    ];

    // Player animations
    for (const { key: dir, row } of dirs) {
      this.anims.create({
        key: `player-walk-${dir}`,
        frames: this.anims.generateFrameNumbers('player', {
          start: row * 4,
          end: row * 4 + 3,
        }),
        frameRate: 8,
        repeat: -1,
      });
      this.anims.create({
        key: `player-idle-${dir}`,
        frames: [{ key: 'player', frame: row * 4 }],
        frameRate: 1,
      });
    }

    // NPC animations (same sheet layout)
    const npcKeys = ['npc-guard', 'npc-merchant', 'npc-scholar', 'npc-archivist', 'npc-vendor'];
    for (const npcKey of npcKeys) {
      for (const { key: dir, row } of dirs) {
        this.anims.create({
          key: `${npcKey}-idle-${dir}`,
          frames: this.anims.generateFrameNumbers(npcKey, {
            start: row * 4,
            end: row * 4 + 1,
          }),
          frameRate: 2,
          repeat: -1,
        });
        this.anims.create({
          key: `${npcKey}-walk-${dir}`,
          frames: this.anims.generateFrameNumbers(npcKey, {
            start: row * 4,
            end: row * 4 + 3,
          }),
          frameRate: 6,
          repeat: -1,
        });
      }
    }
  }
}
