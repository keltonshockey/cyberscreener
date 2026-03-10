/**
 * QUAEST.TECH — World Scene (Isometric)
 * Main game scene: isometric Tiled tilemap rendering with grid-based collision,
 * Y-sort entities, data-driven NPCs, particle effects, and basic lighting.
 */

import Phaser from 'phaser';
import { TILE_W, TILE_H, PLAYER_SPEED, COLORS } from '../config.js';
import { NPC } from '../entities/NPC.js';

export class WorldScene extends Phaser.Scene {
  constructor() {
    super({ key: 'WorldScene' });
  }

  create() {
    this._callbacksRef = this.game.registry.get('callbacks');

    // ── Tilemap (Phaser auto-detects isometric from JSON) ──
    const map = this.make.tilemap({ key: 'roman-city' });
    this.map = map;

    const terrainTiles = map.addTilesetImage('terrain', 'terrain');
    const buildingTiles = map.addTilesetImage('buildings', 'buildings');
    const decoTiles = map.addTilesetImage('decorations', 'decorations');
    const allTilesets = [terrainTiles, buildingTiles, decoTiles];

    this.groundLayer = map.createLayer('Ground', allTilesets);
    this.groundDecorLayer = map.createLayer('GroundDecor', allTilesets);
    this.wallLayer = map.createLayer('Walls', allTilesets);
    this.wallTopLayer = map.createLayer('WallTops', allTilesets);

    if (this.groundLayer) this.groundLayer.setDepth(0);
    if (this.groundDecorLayer) this.groundDecorLayer.setDepth(1);
    if (this.wallLayer) this.wallLayer.setDepth(2);
    if (this.wallTopLayer) this.wallTopLayer.setDepth(10000);

    // NO arcade physics tile collider — we use grid-based collision instead

    // ── Player ──
    this._createPlayer(map);

    // ── NPCs ──
    this.npcs = [];
    this._createNPCs(map);

    // ── Districts ──
    this.districtZones = [];
    this._createDistrictZones(map);

    // ── Particles ──
    this._createParticleEmitters(map);

    // ── Lighting ──
    this._setupLighting(map);

    // ── Camera ──
    const worldW = (map.width + map.height) * TILE_W / 2;
    const worldH = (map.width + map.height) * TILE_H / 2;
    // Isometric maps can extend into negative X. Set bounds accordingly.
    const offsetX = -map.height * TILE_W / 2;
    this.cameras.main.setBounds(offsetX, 0, worldW, worldH);
    this.cameras.main.startFollow(this.player, true, 0.08, 0.08);
    this.cameras.main.setZoom(1.2);

    // ── Input ──
    this.cursors = this.input.keyboard.createCursorKeys();
    this.wasd = this.input.keyboard.addKeys({
      up: Phaser.Input.Keyboard.KeyCodes.W,
      down: Phaser.Input.Keyboard.KeyCodes.S,
      left: Phaser.Input.Keyboard.KeyCodes.A,
      right: Phaser.Input.Keyboard.KeyCodes.D,
    });
    this.interactKey = this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.E);

    // ── UI overlays ──
    this.currentDistrict = null;
    this.labelTween = null;
    this.interactTarget = null;
    this._clickMoveTimer = null;
    this._dialogBubble = null;
    this.playerDir = 'down';

    this._createDistrictLabel();
    this._createInteractPrompt();
    this._createMinimap();
    this._createCoordDisplay();

    // ── Click-to-move ──
    this.input.on('pointerdown', (pointer) => {
      const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
      this._movePlayerTo(worldPoint.x, worldPoint.y);
    });

    // ── Interact key ──
    this.interactKey.on('down', () => {
      if (this.interactTarget) this._handleInteraction(this.interactTarget);
    });

    this._checkDistrict();

    // Debug: verify spawn position and collision
    const spawnTile = this._worldToTile(this.player.x, this.player.y);
    const blocked = this._isBlocked(this.player.x, this.player.y);
    console.log(`[QUAEST] Spawn: world(${this.player.x.toFixed(0)}, ${this.player.y.toFixed(0)}) → tile(${spawnTile.x}, ${spawnTile.y}) blocked=${blocked}`);
  }

  update(time, delta) {
    if (!this.player) return;

    // ── Isometric movement ──
    // In isometric: W=NW (screen up-left), S=SE (screen down-right),
    // A=SW (screen down-left), D=NE (screen up-right)
    const speed = PLAYER_SPEED;
    let moveX = 0, moveY = 0; // tile-grid direction

    const upPressed = this.cursors.up.isDown || this.wasd.up.isDown;
    const downPressed = this.cursors.down.isDown || this.wasd.down.isDown;
    const leftPressed = this.cursors.left.isDown || this.wasd.left.isDown;
    const rightPressed = this.cursors.right.isDown || this.wasd.right.isDown;

    // Map screen directions to isometric grid movement
    if (upPressed) { moveX -= 1; moveY -= 1; }    // NW on grid
    if (downPressed) { moveX += 1; moveY += 1; }   // SE on grid
    if (leftPressed) { moveX -= 1; moveY += 1; }   // SW on grid
    if (rightPressed) { moveX += 1; moveY -= 1; }   // NE on grid

    // Convert grid movement to screen velocity
    let vx = 0, vy = 0;
    if (moveX !== 0 || moveY !== 0) {
      // Isometric projection: screen = (gridX - gridY) * TW/2, (gridX + gridY) * TH/2
      const len = Math.sqrt(moveX * moveX + moveY * moveY);
      const normX = moveX / len;
      const normY = moveY / len;
      // Convert to screen-space velocity
      vx = (normX - normY) * (TILE_W / 2) * (speed / TILE_W);
      vy = (normX + normY) * (TILE_H / 2) * (speed / TILE_W);
      // Scale to maintain consistent speed
      const screenLen = Math.sqrt(vx * vx + vy * vy);
      if (screenLen > 0) {
        vx = (vx / screenLen) * speed;
        vy = (vy / screenLen) * speed;
      }
    }

    // Cancel click-to-move on keyboard input
    if (vx !== 0 || vy !== 0) {
      if (this._clickMoveTimer) {
        this._clickMoveTimer.remove();
        this._clickMoveTimer = null;
      }
    }

    // ── Grid-based collision check ──
    if (vx !== 0 || vy !== 0) {
      const dt = delta / 1000;
      const newX = this.player.x + vx * dt;
      const newY = this.player.y + vy * dt;

      if (!this._isBlocked(newX, newY)) {
        this.player.x = newX;
        this.player.y = newY;
      } else if (!this._isBlocked(newX, this.player.y)) {
        this.player.x = newX;
      } else if (!this._isBlocked(this.player.x, newY)) {
        this.player.y = newY;
      }
    }

    // ── Animation ──
    const moving = vx !== 0 || vy !== 0;
    if (moving) {
      if (Math.abs(vx) > Math.abs(vy)) {
        this.playerDir = vx < 0 ? 'left' : 'right';
      } else {
        this.playerDir = vy < 0 ? 'up' : 'down';
      }
      this.player.anims.play(`player-walk-${this.playerDir}`, true);
    } else {
      this.player.anims.play(`player-idle-${this.playerDir}`, true);
    }

    // ── Y-sort depth ──
    this.player.setDepth(this.player.y + 3);

    // ── Update NPCs ──
    for (const npc of this.npcs) {
      npc.update(time, delta);
    }

    // ── District / interaction / UI ──
    this._checkDistrict();
    this._checkInteractionProximity();
    this._updateMinimap();
    this._updateCoords();
  }

  // ── Isometric coordinate conversion ──
  // Manual formula — bypasses Phaser's worldToTileXY which factors in camera
  // scroll and can produce wrong results when passed world coordinates.
  _worldToTile(worldX, worldY) {
    return {
      x: Math.floor((worldX / (TILE_W / 2) + worldY / (TILE_H / 2)) / 2),
      y: Math.floor((worldY / (TILE_H / 2) - worldX / (TILE_W / 2)) / 2),
    };
  }

  // ── Grid-based collision ──

  _isBlocked(worldX, worldY) {
    const tp = this._worldToTile(worldX, worldY);
    const tx = tp.x;
    const ty = tp.y;
    // Out of bounds = blocked
    if (tx < 0 || tx >= this.map.width || ty < 0 || ty >= this.map.height) return true;
    // Check wall layer for solid tiles (walls, pillars, columns, fountains, shelves)
    if (this.wallLayer) {
      const tile = this.wallLayer.getTileAt(tx, ty);
      if (tile && tile.properties && tile.properties.solid) return true;
    }
    // Check ground layer for solid tiles (water, void)
    if (this.groundLayer) {
      const gTile = this.groundLayer.getTileAt(tx, ty);
      if (gTile && gTile.properties && gTile.properties.solid) return true;
    }
    return false;
  }

  // ── Notify React ──

  _notify(type, data) {
    const cbs = this._callbacksRef?.current;
    if (!cbs) return;
    if (type === 'district' && cbs.onDistrictChange) cbs.onDistrictChange(data);
    if (type === 'interact' && cbs.onInteract) cbs.onInteract(data);
  }

  // ─────────────────────────────────────────────
  // PLAYER
  // ─────────────────────────────────────────────

  _createPlayer(map) {
    const spawnLayer = map.getObjectLayer('Spawns');
    const spawnObj = spawnLayer?.objects?.find(o => o.type === 'player_spawn');

    let spawnX, spawnY;
    if (spawnObj) {
      spawnX = spawnObj.x;
      spawnY = spawnObj.y;
    } else {
      // Default: tile (22, 16)
      const def = this._tileToWorld(22, 16);
      spawnX = def.x;
      spawnY = def.y;
    }

    this.player = this.add.sprite(spawnX, spawnY, 'player');
    this.player.setOrigin(0.5, 0.85);
    this.player.setDepth(10);
  }

  _tileToWorld(col, row) {
    return {
      x: (col - row) * (TILE_W / 2),
      y: (col + row) * (TILE_H / 2),
    };
  }

  // ─────────────────────────────────────────────
  // CLICK-TO-MOVE
  // ─────────────────────────────────────────────

  _movePlayerTo(worldX, worldY) {
    const dx = worldX - this.player.x;
    const dy = worldY - this.player.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 16) return;

    if (this._isBlocked(worldX, worldY)) return;

    const angle = Math.atan2(dy, dx);
    const vx = Math.cos(angle) * PLAYER_SPEED;
    const vy = Math.sin(angle) * PLAYER_SPEED;

    // Start moving
    this._clickMoveVx = vx;
    this._clickMoveVy = vy;

    if (this._clickMoveTimer) this._clickMoveTimer.remove();
    this._clickMoveTimer = this.time.addEvent({
      delay: 16,
      repeat: Math.ceil((dist / PLAYER_SPEED) * 60),
      callback: () => {
        if (!this.player) return;
        const newX = this.player.x + vx / 60;
        const newY = this.player.y + vy / 60;
        if (!this._isBlocked(newX, newY)) {
          this.player.x = newX;
          this.player.y = newY;
        } else {
          this._clickMoveTimer?.remove();
          this._clickMoveTimer = null;
        }
      },
    });
  }

  // ─────────────────────────────────────────────
  // NPCs (from Tiled object layer)
  // ─────────────────────────────────────────────

  _createNPCs(map) {
    const spawnLayer = map.getObjectLayer('Spawns');
    if (!spawnLayer) return;

    for (const obj of spawnLayer.objects) {
      if (obj.type !== 'npc_spawn') continue;

      const props = {};
      for (const p of (obj.properties || [])) {
        props[p.name] = p.value;
      }

      const npc = new NPC(this, {
        x: obj.x,
        y: obj.y,
        npcId: props.npcId,
        name: obj.name,
        spriteKey: props.spriteKey,
        behavior: props.behavior || 'idle',
      });

      this.npcs.push(npc);
    }
  }

  // ─────────────────────────────────────────────
  // DISTRICTS (from Tiled object layer)
  // ─────────────────────────────────────────────

  _createDistrictZones(map) {
    const zoneLayer = map.getObjectLayer('Zones');
    if (!zoneLayer) return;

    for (const obj of zoneLayer.objects) {
      if (obj.type !== 'district') continue;

      const props = {};
      for (const p of (obj.properties || [])) {
        props[p.name] = p.value;
      }

      this.districtZones.push({
        id: props.districtId,
        name: obj.name,
        desc: props.desc,
        color: parseInt((props.color || '#4E0B59').replace('#', ''), 16),
        labelColor: props.labelColor || props.color,
        locked: props.locked || null,
        rect: new Phaser.Geom.Rectangle(obj.x, obj.y, obj.width, obj.height),
      });
    }
  }

  _createDistrictLabel() {
    const cx = this.cameras.main.width / 2;

    this.districtLabelBg = this.add.rectangle(cx, 8, 200, 40, 0x000000, 0.7)
      .setScrollFactor(0).setOrigin(0.5, 0).setDepth(200).setVisible(false);

    this.districtLabel = this.add.text(cx, 14, '', {
      fontFamily: 'Cinzel, serif', fontSize: '12px', fontStyle: 'bold',
      color: '#F2F2F2', align: 'center',
    }).setScrollFactor(0).setOrigin(0.5, 0).setDepth(201).setVisible(false);

    this.districtDescText = this.add.text(cx, 28, '', {
      fontFamily: 'Inter, sans-serif', fontSize: '7px',
      color: '#A6A6A6', align: 'center',
    }).setScrollFactor(0).setOrigin(0.5, 0).setDepth(201).setVisible(false);
  }

  _checkDistrict() {
    const px = this.player.x;
    const py = this.player.y;

    let found = null;
    for (const zone of this.districtZones) {
      if (zone.rect.contains(px, py)) { found = zone; break; }
    }

    const distId = found?.id || null;
    const prevId = this.currentDistrict?.id || null;

    if (distId !== prevId) {
      this.currentDistrict = found;
      if (found) this._showDistrictLabel(found);
      else this._hideDistrictLabel();
      this._notify('district', found);
    }
  }

  _showDistrictLabel(district) {
    const cx = this.cameras.main.width / 2;
    this.districtLabel.setText(district.name.toUpperCase());
    this.districtDescText.setText(district.desc);

    const textW = Math.max(this.districtLabel.width, this.districtDescText.width) + 24;
    this.districtLabelBg.setSize(textW, 40).setPosition(cx, 8);
    this.districtLabel.setPosition(cx, 14);
    this.districtDescText.setPosition(cx, 28);

    [this.districtLabelBg, this.districtLabel, this.districtDescText].forEach(o => {
      o.setVisible(true).setAlpha(1);
    });

    if (this.labelTween) this.labelTween.stop();
    this.labelTween = this.tweens.add({
      targets: [this.districtLabelBg, this.districtLabel, this.districtDescText],
      alpha: 0, delay: 3000, duration: 1000,
      onComplete: () => {
        [this.districtLabelBg, this.districtLabel, this.districtDescText].forEach(o => o.setVisible(false));
      },
    });
  }

  _hideDistrictLabel() {
    if (this.labelTween) this.labelTween.stop();
    [this.districtLabelBg, this.districtLabel, this.districtDescText].forEach(o => o?.setVisible(false));
  }

  // ─────────────────────────────────────────────
  // INTERACTION
  // ─────────────────────────────────────────────

  _createInteractPrompt() {
    this.interactPrompt = this.add.container(0, 0).setDepth(150).setVisible(false);
    const bg = this.add.rectangle(0, 0, 100, 20, 0x000000, 0.8).setOrigin(0.5, 1);
    this.interactPromptText = this.add.text(0, -10, '[E] Talk', {
      fontFamily: 'monospace', fontSize: '8px', color: '#DDBB44', align: 'center',
    }).setOrigin(0.5, 0.5);
    this.interactPrompt.add([bg, this.interactPromptText]);
  }

  _checkInteractionProximity() {
    const px = this.player.x;
    const py = this.player.y;
    const range = 80; // wider range for isometric (tiles are 64px wide)

    let nearest = null;
    let nearestDist = Infinity;

    for (const npc of this.npcs) {
      const dist = Phaser.Math.Distance.Between(px, py, npc.sprite.x, npc.sprite.y);
      if (dist < range && dist < nearestDist) {
        nearest = npc;
        nearestDist = dist;
      }
    }

    if (nearest) {
      this.interactTarget = nearest;
      this.interactPrompt.setPosition(nearest.sprite.x, nearest.sprite.y - 30);
      this.interactPrompt.setVisible(true);
      this.interactPromptText.setText(`[E] ${nearest.npcName}`);
      nearest.facePlayer(px, py);
    } else {
      this.interactTarget = null;
      this.interactPrompt.setVisible(false);
    }
  }

  _handleInteraction(npc) {
    const dialog = npc.getDialog();
    const name = npc.npcName;
    this._showDialogBubble(npc.sprite.x, npc.sprite.y - 40, dialog);
    this._notify('interact', { name, dialog, type: 'npc' });
  }

  _showDialogBubble(x, y, text) {
    if (this._dialogBubble) this._dialogBubble.destroy();

    const txt = this.add.text(x, y - 8, text, {
      fontFamily: 'sans-serif', fontSize: '8px', color: '#F2F2F2',
      align: 'center', wordWrap: { width: 160 },
    }).setOrigin(0.5, 1).setDepth(160);

    const bounds = txt.getBounds();
    const bg = this.add.rectangle(
      x, y - 8 - bounds.height / 2,
      bounds.width + 16, bounds.height + 10,
      0x1A1A1A, 0.9
    ).setOrigin(0.5, 0.5).setDepth(159);

    const border = this.add.rectangle(
      x, y - 8 - bounds.height / 2,
      bounds.width + 18, bounds.height + 12,
      COLORS.IMPERIAL_PURPLE, 0.6
    ).setOrigin(0.5, 0.5).setDepth(158);

    const container = this.add.container(0, 0, [border, bg, txt]).setDepth(160);
    this._dialogBubble = container;

    this.time.delayedCall(4000, () => {
      this.tweens.add({
        targets: container, alpha: 0, duration: 500,
        onComplete: () => container.destroy(),
      });
    });
  }

  // ─────────────────────────────────────────────
  // PARTICLES
  // ─────────────────────────────────────────────

  _createParticleEmitters(map) {
    const particleLayer = map.getObjectLayer('Particles');
    if (!particleLayer) return;

    for (const obj of particleLayer.objects) {
      if (obj.type !== 'particle') continue;
      const props = {};
      for (const p of (obj.properties || [])) props[p.name] = p.value;
      this._buildEmitter(props.emitterId, obj.x, obj.y);
    }
  }

  _buildEmitter(emitterId, x, y) {
    switch (emitterId) {
      case 'fountain_mist':
        this.add.particles(x, y, 'particle-sparkle', {
          speed: { min: 8, max: 20 }, angle: { min: -120, max: -60 },
          lifespan: { min: 800, max: 1500 }, scale: { start: 0.8, end: 0 },
          alpha: { start: 0.6, end: 0 }, frequency: 200, quantity: 1,
          blendMode: 'ADD', depth: 5,
        });
        break;
      case 'ambient_dust':
        this.add.particles(x, y, 'particle-dust', {
          speed: { min: 2, max: 6 }, angle: { min: 0, max: 360 },
          lifespan: { min: 3000, max: 6000 }, scale: { start: 0.5, end: 0.2 },
          alpha: { start: 0.15, end: 0 }, frequency: 1500, quantity: 1,
          emitZone: { type: 'random', source: new Phaser.Geom.Rectangle(-150, -150, 300, 300) },
          depth: 50,
        });
        break;
      case 'torch_smoke':
        this.add.particles(x, y, 'particle-smoke', {
          speed: { min: 3, max: 8 }, angle: { min: -100, max: -80 },
          lifespan: { min: 1000, max: 2000 }, scale: { start: 0.5, end: 1.0 },
          alpha: { start: 0.3, end: 0 }, frequency: 400, quantity: 1,
          tint: 0xA6A6A6, depth: 101,
        });
        break;
      case 'falling_leaves':
        this.add.particles(x, y, 'particle-leaf', {
          speed: { min: 5, max: 15 }, angle: { min: 60, max: 120 },
          lifespan: { min: 2000, max: 4000 }, scale: { start: 0.8, end: 0.4 },
          alpha: { start: 0.7, end: 0 }, rotate: { min: 0, max: 360 },
          frequency: 3000, quantity: 1, depth: 99,
        });
        break;
    }
  }

  // ─────────────────────────────────────────────
  // LIGHTING
  // ─────────────────────────────────────────────

  _setupLighting(_map) {
    if (this.groundLayer) this.groundLayer.setTint(0xDDDDDD);
    if (this.wallLayer) this.wallLayer.setTint(0xBBBBCC);
  }

  // ─────────────────────────────────────────────
  // MINIMAP
  // ─────────────────────────────────────────────

  _createMinimap() {
    if (!this.map) return;

    const mapCols = this.map.width;
    const mapRows = this.map.height;
    const s = 3; // scale: pixels per isometric half-unit

    // Calculate actual minimap bounds from tile positions
    // Each tile (col,row) maps to pixel (col-row+mapRows)*s/2, (col+row)*s/2
    const mmxMin = Math.floor((0 - (mapRows - 1) + mapRows) * s / 2);
    const mmxMax = Math.ceil(((mapCols - 1) + mapRows) * s / 2);
    const mmyMax = Math.ceil(((mapCols - 1) + (mapRows - 1)) * s / 2);
    const mw = mmxMax - mmxMin + s + 2;
    const mh = mmyMax + s + 2;

    const padding = 6;
    const vw = 800;
    const vh = 480;
    const mx = vw - mw - padding;
    const my = vh - mh - padding;

    const ct = this.add.container(0, 0).setScrollFactor(0).setDepth(190);

    // Background with slight padding
    ct.add(this.add.rectangle(mx + mw / 2, my + mh / 2, mw + 4, mh + 4, 0x000000, 0.7)
      .setScrollFactor(0));

    // ── Render actual tile data ──
    const gfx = this.add.graphics().setScrollFactor(0);

    // GID → color mapping (matches the brand palette used in tileset generator)
    const gidColor = (gid) => {
      if (gid === 0) return -1;
      if (gid >= 1 && gid <= 8) return 0x4A8B4A;     // grass
      if (gid >= 9 && gid <= 16) return 0x6B6B6B;     // stone
      if (gid >= 17 && gid <= 24) return 0xD8D0C4;    // marble
      if (gid >= 25 && gid <= 32) return 0xA09070;    // road
      if (gid >= 33 && gid <= 36) return 0x4488CC;    // water
      if (gid >= 37 && gid <= 40) return 0x222222;    // void
      if (gid >= 41 && gid <= 44) return 0xC8C0B4;    // interior floor
      if (gid >= 45 && gid <= 48) return 0x333333;    // shadow
      if (gid >= 61 && gid <= 74) return 0x3A3A3A;    // walls
      if (gid >= 75 && gid <= 76) return 0x8B5A2B;    // doors
      if (gid >= 77 && gid <= 78) return 0x8B6914;    // shelves
      if (gid >= 79 && gid <= 84) return 0x4A4A4A;    // window walls / parapets
      if (gid >= 101 && gid <= 102) return 0xC9A87C;  // pillars
      if (gid >= 103 && gid <= 104) return 0xBBA888;  // columns
      if (gid >= 105 && gid <= 106) return 0x6E2B79;  // banners
      if (gid >= 107 && gid <= 108) return 0x6B4423;  // tree trunks
      if (gid >= 109 && gid <= 110) return 0x5599DD;  // fountain
      if (gid >= 111 && gid <= 114) return 0x2D6B2D;  // tree canopy
      if (gid >= 115 && gid <= 118) return 0x3A3A3A;  // wall parapet
      return 0x555555;
    };

    // Draw ground layer
    for (let row = 0; row < mapRows; row++) {
      for (let col = 0; col < mapCols; col++) {
        const tile = this.groundLayer?.getTileAt(col, row);
        if (!tile) continue;
        const color = gidColor(tile.index);
        if (color < 0) continue;
        const px = mx + (col - row + mapRows) * s / 2;
        const py = my + (col + row) * s / 2;
        gfx.fillStyle(color, 0.85);
        gfx.fillRect(px, py, Math.ceil(s / 2) + 1, Math.ceil(s / 2));
      }
    }

    // Draw ground decor layer on top
    if (this.groundDecorLayer) {
      for (let row = 0; row < mapRows; row++) {
        for (let col = 0; col < mapCols; col++) {
          const tile = this.groundDecorLayer.getTileAt(col, row);
          if (!tile) continue;
          const color = gidColor(tile.index);
          if (color < 0) continue;
          const px = mx + (col - row + mapRows) * s / 2;
          const py = my + (col + row) * s / 2;
          gfx.fillStyle(color, 0.9);
          gfx.fillRect(px, py, Math.ceil(s / 2) + 1, Math.ceil(s / 2));
        }
      }
    }

    // Draw wall layer on top (buildings, obstacles)
    for (let row = 0; row < mapRows; row++) {
      for (let col = 0; col < mapCols; col++) {
        const tile = this.wallLayer?.getTileAt(col, row);
        if (!tile) continue;
        const color = gidColor(tile.index);
        if (color < 0) continue;
        const px = mx + (col - row + mapRows) * s / 2;
        const py = my + (col + row) * s / 2;
        gfx.fillStyle(color, 1.0);
        gfx.fillRect(px, py, Math.ceil(s / 2) + 1, Math.ceil(s / 2));
      }
    }

    ct.add(gfx);

    // Thin border outline
    const border = this.add.graphics().setScrollFactor(0);
    border.lineStyle(1, 0x4E0B59, 0.4);
    border.strokeRect(mx - 2, my - 2, mw + 4, mh + 4);
    ct.add(border);

    // Player dot (bright, on top)
    this.minimapPlayer = this.add.circle(mx, my, 3, 0xFFDD44).setScrollFactor(0).setDepth(192);

    this._minimapPos = { mx, my, mw, mh, scale: s, mapCols, mapRows };
  }

  _updateMinimap() {
    if (!this.minimapPlayer || !this._minimapPos) return;
    const { mx, my, scale, mapRows } = this._minimapPos;

    // Use manual world-to-tile conversion (consistent with _isBlocked)
    const tp = this._worldToTile(this.player.x, this.player.y);
    const mmx = (tp.x - tp.y + mapRows) * scale / 2;
    const mmy = (tp.x + tp.y) * scale / 2;

    this.minimapPlayer.setPosition(mx + mmx, my + mmy);
  }

  // ─────────────────────────────────────────────
  // COORDINATES
  // ─────────────────────────────────────────────

  _createCoordDisplay() {
    this.coordText = this.add.text(6, 6, '', {
      fontFamily: 'monospace', fontSize: '8px', color: '#A6A6A6',
    }).setScrollFactor(0).setDepth(190);
  }

  _updateCoords() {
    const tp = this._worldToTile(this.player.x, this.player.y);
    this.coordText.setText(`${tp.x}, ${tp.y}`);
  }
}
