/**
 * QUAEST.TECH — NPC Entity (Isometric)
 * Creates a sprite with data-driven behavior (idle, patrol, wander).
 * Uses manual position updates instead of arcade physics.
 */

import Phaser from 'phaser';
import { NPC_REGISTRY } from './NPCData.js';

export class NPC {
  constructor(scene, config) {
    this.scene = scene;
    this.config = config;

    const regData = NPC_REGISTRY[config.npcId];
    this.data = regData || {};
    this.npcId = config.npcId;
    this.npcName = config.name || this.data.name || 'NPC';

    const spriteKey = config.spriteKey || this.data.spriteKey || 'npc-scholar';

    // Create sprite (no physics — we do grid-based collision at scene level)
    this.sprite = scene.add.sprite(config.x, config.y, spriteKey);
    this.sprite.setOrigin(0.5, 0.85);

    this.sprite.setData('npcInstance', this);
    this.sprite.setData('name', this.npcName);
    this.sprite.setData('type', 'npc');

    this.spriteKey = spriteKey;
    this.dialogIndex = 0;
    this.facing = this.data.facing || 'down';
    this.behavior = config.behavior || this.data.behavior || 'idle';
    this._behaviorTimer = null;
    this._vx = 0;
    this._vy = 0;

    this._playAnim('idle');

    if (this.behavior === 'patrol') this._initPatrol();
    else if (this.behavior === 'wander') this._initWander();
  }

  update(time, delta) {
    // Y-sort depth
    this.sprite.setDepth(this.sprite.y + 3);

    // Apply velocity manually
    if (this._vx !== 0 || this._vy !== 0) {
      const dt = delta / 1000;
      const newX = this.sprite.x + this._vx * dt;
      const newY = this.sprite.y + this._vy * dt;
      // Check collision via scene
      if (this.scene._isBlocked && !this.scene._isBlocked(newX, newY)) {
        this.sprite.x = newX;
        this.sprite.y = newY;
      }
    }
  }

  getDialog() {
    const dialogs = this.data.dialog || ['...'];
    const text = dialogs[this.dialogIndex % dialogs.length];
    this.dialogIndex++;
    return text;
  }

  facePlayer(playerX, playerY) {
    const dx = playerX - this.sprite.x;
    const dy = playerY - this.sprite.y;
    if (Math.abs(dx) > Math.abs(dy)) {
      this.facing = dx < 0 ? 'left' : 'right';
    } else {
      this.facing = dy < 0 ? 'up' : 'down';
    }
    this._playAnim('idle');
  }

  destroy() {
    if (this._behaviorTimer) this._behaviorTimer.remove();
    this.sprite.destroy();
  }

  _playAnim(state) {
    const key = `${this.spriteKey}-${state}-${this.facing}`;
    if (this.scene.anims.exists(key)) {
      this.sprite.anims.play(key, true);
    }
  }

  _setFacingFromVelocity() {
    if (Math.abs(this._vx) > Math.abs(this._vy)) {
      this.facing = this._vx < 0 ? 'left' : 'right';
    } else if (this._vy !== 0) {
      this.facing = this._vy < 0 ? 'up' : 'down';
    }
  }

  // ── Patrol behavior ──

  _initPatrol() {
    this.patrolIndex = 0;
    this.spawnX = this.sprite.x;
    this.spawnY = this.sprite.y;
    this._moveToNextPatrolPoint();
  }

  _moveToNextPatrolPoint() {
    const path = this.data.patrolPath;
    if (!path || path.length === 0) return;

    const target = path[this.patrolIndex % path.length];
    // Scale patrol paths for isometric (4x larger tiles)
    const tx = this.spawnX + target.x * 4;
    const ty = this.spawnY + target.y * 4;

    const dx = tx - this.sprite.x;
    const dy = ty - this.sprite.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < 8) {
      this.patrolIndex++;
      this._moveToNextPatrolPoint();
      return;
    }

    const speed = (this.data.patrolSpeed || 30) * 2.5;
    this._vx = (dx / dist) * speed;
    this._vy = (dy / dist) * speed;
    this._setFacingFromVelocity();
    this._playAnim('walk');

    const travelTime = (dist / speed) * 1000;
    this._behaviorTimer = this.scene.time.delayedCall(travelTime, () => {
      this._vx = 0;
      this._vy = 0;
      this._playAnim('idle');

      const pauseMs = this.data.pauseDuration || 2000;
      this._behaviorTimer = this.scene.time.delayedCall(pauseMs, () => {
        this.patrolIndex++;
        this._moveToNextPatrolPoint();
      });
    });
  }

  // ── Wander behavior ──

  _initWander() {
    this.spawnX = this.sprite.x;
    this.spawnY = this.sprite.y;
    this._scheduleWander();
  }

  _scheduleWander() {
    const pauseMs = this.data.wanderPause || 3000;
    const jitter = Math.random() * pauseMs * 0.5;
    this._behaviorTimer = this.scene.time.delayedCall(pauseMs + jitter, () => {
      this._doWander();
    });
  }

  _doWander() {
    // Scale wander radius for isometric (4x)
    const radius = (this.data.wanderRadius || 48) * 4;
    const angle = Math.random() * Math.PI * 2;
    const dist = Math.random() * radius;
    const tx = this.spawnX + Math.cos(angle) * dist;
    const ty = this.spawnY + Math.sin(angle) * dist;

    const dx = tx - this.sprite.x;
    const dy = ty - this.sprite.y;
    const d = Math.sqrt(dx * dx + dy * dy);

    if (d < 8) {
      this._scheduleWander();
      return;
    }

    const speed = (this.data.wanderSpeed || 30) * 2.5;
    this._vx = (dx / d) * speed;
    this._vy = (dy / d) * speed;
    this._setFacingFromVelocity();
    this._playAnim('walk');

    const travelTime = (d / speed) * 1000;
    this._behaviorTimer = this.scene.time.delayedCall(travelTime, () => {
      this._vx = 0;
      this._vy = 0;
      this._playAnim('idle');
      this._scheduleWander();
    });
  }
}
