/**
 * QUAEST.TECH — Voxel NPC
 * Billboard sprite NPC with patrol/wander/idle behaviors.
 * Ported from NPC.js with grid-space coordinates (no ×4 multiplier).
 */

import * as THREE from 'three';
import { NPC_REGISTRY } from '../entities/NPCData.js';
import { MAP_COLS, MAP_ROWS, BLOCK_SIZE } from '../config.js';
import { generateSpriteSheet, spriteKeyToCharacterType } from './SpriteGenerator.js';

const FRAME_W = 32;
const FRAME_H = 48;
const SHEET_COLS = 4;
const SHEET_ROWS = 4;
const ANIM_FPS = 6;

const DIR_MAP = { down: 0, left: 1, right: 2, up: 3 };

export class VoxelNPC {
  constructor(scene, spawnData, collisionMap) {
    this.scene = scene;
    this.collisionMap = collisionMap;
    this.npcId = spawnData.npcId;
    this.data = NPC_REGISTRY[this.npcId] || {};
    this.npcName = spawnData.name || this.data.name || 'NPC';

    const spriteKey = spawnData.spriteKey || this.data.spriteKey || 'npc-scholar';

    // Position in 3D grid space
    this.spawnX = (spawnData.col + 0.5) * BLOCK_SIZE;
    this.spawnZ = (spawnData.row + 0.5) * BLOCK_SIZE;
    this.x = this.spawnX;
    this.z = this.spawnZ;

    this.facing = this.data.facing || 'down';
    this.behavior = spawnData.behavior || this.data.behavior || 'idle';
    this.dialogIndex = 0;

    this._vx = 0;
    this._vz = 0;
    this._animTime = 0;
    this._behaviorTimer = 0;
    this._behaviorState = 'idle'; // 'idle' | 'moving' | 'paused'
    this._patrolIndex = 0;

    // Generate sprite sheet procedurally (Roman-themed characters)
    const charType = spriteKeyToCharacterType(spriteKey);
    const spriteCanvas = generateSpriteSheet(charType);
    this._texture = new THREE.CanvasTexture(spriteCanvas);
    this._texture.magFilter = THREE.NearestFilter;
    this._texture.minFilter = THREE.NearestFilter;
    this._texture.colorSpace = THREE.SRGBColorSpace;
    this._texture.repeat.set(1 / SHEET_COLS, 1 / SHEET_ROWS);
    this._setFrame(0, DIR_MAP[this.facing] || 0);

    // Create billboard sprite
    const material = new THREE.SpriteMaterial({ map: this._texture, transparent: true });
    this.sprite = new THREE.Sprite(material);
    this.sprite.scale.set(1.5, 2.25, 1);
    this.sprite.position.set(this.x, 2.2, this.z);
    scene.add(this.sprite);

    // Init behavior
    if (this.behavior === 'patrol') this._initPatrol();
    else if (this.behavior === 'wander') this._scheduleWander(0);
  }

  update(delta, time) {
    // Process behavior timers
    if (this._behaviorTimer > 0) {
      this._behaviorTimer -= delta;
      if (this._behaviorTimer <= 0) {
        this._onBehaviorTimer();
      }
    }

    // Apply velocity
    if (this._vx !== 0 || this._vz !== 0) {
      const newX = this.x + this._vx * delta;
      const newZ = this.z + this._vz * delta;
      if (!this._isBlocked(newX, newZ)) {
        this.x = newX;
        this.z = newZ;
      }
    }

    // Update sprite position
    this.sprite.position.set(this.x, 2.2, this.z);

    // Animate
    const moving = this._vx !== 0 || this._vz !== 0;
    const dirRow = DIR_MAP[this.facing] || 0;
    if (moving) {
      this._animTime += delta;
      const frame = Math.floor(this._animTime * ANIM_FPS) % SHEET_COLS;
      this._setFrame(frame, dirRow);
    } else {
      // Idle: alternate between frames 0 and 1
      this._animTime += delta;
      const frame = Math.floor(this._animTime * 2) % 2;
      this._setFrame(frame, dirRow);
    }
  }

  getDialog() {
    const dialogs = this.data.dialog || ['...'];
    const text = dialogs[this.dialogIndex % dialogs.length];
    this.dialogIndex++;
    return text;
  }

  facePlayer(px, pz) {
    const dx = px - this.x;
    const dz = pz - this.z;
    if (Math.abs(dx) > Math.abs(dz)) {
      this.facing = dx > 0 ? 'right' : 'left';
    } else {
      this.facing = dz > 0 ? 'down' : 'up';
    }
  }

  // ── Patrol ──

  _initPatrol() {
    this._patrolIndex = 0;
    this._moveToNextPatrolPoint();
  }

  _moveToNextPatrolPoint() {
    const path = this.data.patrolPath;
    if (!path || path.length === 0) return;

    const target = path[this._patrolIndex % path.length];
    // patrolPath is in pixel offsets from old system — convert to block offsets
    // Old system used ×4, so these are already in reasonable pixel units
    // In the old NPC.js they multiplied by 4 again. Here we just use them directly as block offsets
    const tx = this.spawnX + target.x / 10; // Scale down from old pixel coords
    const tz = this.spawnZ + target.y / 10;

    const dx = tx - this.x;
    const dz = tz - this.z;
    const dist = Math.sqrt(dx * dx + dz * dz);

    if (dist < 0.2) {
      this._patrolIndex++;
      this._moveToNextPatrolPoint();
      return;
    }

    const speed = (this.data.patrolSpeed || 40) / 10; // scale from pixels to blocks/s
    this._vx = (dx / dist) * speed;
    this._vz = (dz / dist) * speed;
    this._setFacing();
    this._behaviorState = 'moving';
    this._behaviorTimer = dist / speed;
    this._behaviorCallback = 'patrolPause';
  }

  // ── Wander ──

  _scheduleWander(pause) {
    const pauseMs = pause || (this.data.wanderPause || 3000);
    const jitter = Math.random() * pauseMs * 0.5;
    this._behaviorTimer = (pauseMs + jitter) / 1000;
    this._behaviorCallback = 'doWander';
    this._behaviorState = 'idle';
  }

  _doWander() {
    const radius = (this.data.wanderRadius || 48) / 10; // scale to blocks
    const angle = Math.random() * Math.PI * 2;
    const dist = Math.random() * radius;
    const tx = this.spawnX + Math.cos(angle) * dist;
    const tz = this.spawnZ + Math.sin(angle) * dist;

    const dx = tx - this.x;
    const dz = tz - this.z;
    const d = Math.sqrt(dx * dx + dz * dz);

    if (d < 0.2) {
      this._scheduleWander();
      return;
    }

    const speed = (this.data.wanderSpeed || 30) / 10;
    this._vx = (dx / d) * speed;
    this._vz = (dz / d) * speed;
    this._setFacing();
    this._behaviorState = 'moving';
    this._behaviorTimer = d / speed;
    this._behaviorCallback = 'wanderPause';
  }

  // ── Behavior timer callback ──

  _onBehaviorTimer() {
    const cb = this._behaviorCallback;
    this._behaviorCallback = null;

    if (cb === 'patrolPause') {
      this._vx = 0;
      this._vz = 0;
      this._behaviorTimer = (this.data.pauseDuration || 2000) / 1000;
      this._behaviorCallback = 'patrolNext';
    } else if (cb === 'patrolNext') {
      this._patrolIndex++;
      this._moveToNextPatrolPoint();
    } else if (cb === 'doWander') {
      this._doWander();
    } else if (cb === 'wanderPause') {
      this._vx = 0;
      this._vz = 0;
      this._scheduleWander();
    }
  }

  _setFacing() {
    if (Math.abs(this._vx) > Math.abs(this._vz)) {
      this.facing = this._vx > 0 ? 'right' : 'left';
    } else if (this._vz !== 0) {
      this.facing = this._vz > 0 ? 'down' : 'up';
    }
  }

  _setFrame(col, row) {
    this._texture.offset.set(col / SHEET_COLS, 1 - (row + 1) / SHEET_ROWS);
  }

  _isBlocked(x, z) {
    const col = Math.floor(x / BLOCK_SIZE);
    const row = Math.floor(z / BLOCK_SIZE);
    if (col < 0 || col >= MAP_COLS || row < 0 || row >= MAP_ROWS) return true;
    return this.collisionMap[row * MAP_COLS + col];
  }

  destroy() {
    if (this.sprite.parent) this.sprite.parent.remove(this.sprite);
    this._texture.dispose();
    this.sprite.material.dispose();
  }
}
