/**
 * QUAEST.TECH — Player Controller
 * WASD grid movement in 3D space with collision detection.
 * Renders as a billboard sprite using the existing sprite sheet.
 */

import * as THREE from 'three';
import { MAP_COLS, MAP_ROWS, BLOCK_SIZE, VOXEL_PLAYER_SPEED } from '../config.js';
import { generateSpriteSheet } from './SpriteGenerator.js';

// Sprite sheet layout: 4 cols x 4 rows of 32x48 frames
// Row 0=down, 1=left, 2=right, 3=up
const FRAME_W = 32;
const FRAME_H = 48;
const SHEET_COLS = 4;
const SHEET_ROWS = 4;
const ANIM_FPS = 8;

const DIR_MAP = {
  down: 0,
  left: 1,
  right: 2,
  up: 3,
};

export class PlayerController {
  constructor(scene, col, row) {
    this.x = (col + 0.5) * BLOCK_SIZE;
    this.z = (row + 0.5) * BLOCK_SIZE;
    this.facing = 'down';
    this.moving = false;
    this._moveTarget = null;
    this._animTime = 0;
    this._currentFrame = 0;
    this._cameraTheta = Math.PI / 4; // camera orbit angle for relative movement
    this.movementAngle = 0;   // continuous angle of current movement direction
    this.isMoving = false;    // true when player has velocity this frame

    // Generate sprite sheet procedurally (Roman citizen in toga)
    const spriteCanvas = generateSpriteSheet('player');
    this._texture = new THREE.CanvasTexture(spriteCanvas);
    this._texture.magFilter = THREE.NearestFilter;
    this._texture.minFilter = THREE.NearestFilter;
    this._texture.colorSpace = THREE.SRGBColorSpace;

    // Set initial UV repeat for one frame
    this._texture.repeat.set(1 / SHEET_COLS, 1 / SHEET_ROWS);
    this._texture.offset.set(0, 1 - 1 / SHEET_ROWS); // first frame, row 0 (down)

    // Create billboard sprite
    const material = new THREE.SpriteMaterial({
      map: this._texture,
      transparent: true,
    });
    this.sprite = new THREE.Sprite(material);
    this.sprite.scale.set(1.5, 2.25, 1); // width, height proportional to 32x48
    this.sprite.position.set(this.x, 2.2, this.z);
    scene.add(this.sprite);
  }

  /**
   * Set the camera's orbit angle so WASD moves relative to camera facing.
   */
  setCameraAngle(theta) {
    this._cameraTheta = theta;
  }

  /**
   * Set click-to-move target (in block coords, already offset by 0.5).
   */
  setMoveTarget(x, z) {
    this._moveTarget = { x: x * BLOCK_SIZE, z: z * BLOCK_SIZE };
  }

  /**
   * Update player position and animation.
   */
  update(delta, keys, collisionMap) {
    const speed = VOXEL_PLAYER_SPEED * BLOCK_SIZE;
    let vx = 0;
    let vz = 0;

    // WASD input: raw input axes (forward/back/strafe)
    let rawFwd = 0;  // forward = -1, backward = +1
    let rawStrafe = 0; // left = -1, right = +1
    if (keys['KeyW'] || keys['ArrowUp']) rawFwd = -1;
    if (keys['KeyS'] || keys['ArrowDown']) rawFwd = 1;
    if (keys['KeyA'] || keys['ArrowLeft']) rawStrafe = -1;
    if (keys['KeyD'] || keys['ArrowRight']) rawStrafe = 1;

    // Rotate input by camera angle for camera-relative movement
    const hasKeyInput = rawFwd !== 0 || rawStrafe !== 0;
    if (hasKeyInput) {
      const ct = Math.cos(this._cameraTheta);
      const st = Math.sin(this._cameraTheta);
      // Camera looks from (sin(theta), 0, cos(theta)) toward player
      // Forward = toward camera's -lookDir on XZ plane = (-sin(theta), -cos(theta))
      // Right = perpendicular = (cos(theta), -sin(theta))
      vx = rawFwd * (-st) + rawStrafe * ct;
      vz = rawFwd * (-ct) + rawStrafe * (-st);
    }

    // If keyboard input, cancel click-to-move
    if (hasKeyInput) {
      this._moveTarget = null;
    }

    // Click-to-move
    if (!hasKeyInput && this._moveTarget) {
      const dx = this._moveTarget.x - this.x;
      const dz = this._moveTarget.z - this.z;
      const dist = Math.sqrt(dx * dx + dz * dz);

      if (dist < 0.15) {
        this._moveTarget = null;
      } else {
        vx = dx / dist;
        vz = dz / dist;
      }
    }

    // Normalize diagonal movement
    if (vx !== 0 && vz !== 0 && hasKeyInput) {
      const len = Math.sqrt(vx * vx + vz * vz);
      vx /= len;
      vz /= len;
    }

    this.moving = vx !== 0 || vz !== 0;
    this.isMoving = this.moving;
    if (this.moving) {
      this.movementAngle = Math.atan2(vx, vz);
    }

    if (this.moving) {
      // Determine facing from velocity
      // In isometric view: camera looks from (+X, +Y, +Z) toward origin
      // "down" on screen = +X,+Z direction, "up" = -X,-Z
      // "right" on screen = +X,-Z, "left" = -X,+Z
      if (Math.abs(vx) > Math.abs(vz)) {
        this.facing = vx > 0 ? 'right' : 'left';
      } else {
        this.facing = vz > 0 ? 'down' : 'up';
      }

      // Try full movement, then slide
      const newX = this.x + vx * speed * delta;
      const newZ = this.z + vz * speed * delta;

      if (!this._isBlocked(newX, newZ, collisionMap)) {
        this.x = newX;
        this.z = newZ;
      } else if (!this._isBlocked(newX, this.z, collisionMap)) {
        this.x = newX; // slide X
      } else if (!this._isBlocked(this.x, newZ, collisionMap)) {
        this.z = newZ; // slide Z
      }
    }

    // Update sprite position
    this.sprite.position.set(this.x, 2.2, this.z);

    // Animate sprite
    this._updateAnimation(delta);
  }

  _isBlocked(x, z, collisionMap) {
    const col = Math.floor(x / BLOCK_SIZE);
    const row = Math.floor(z / BLOCK_SIZE);
    if (col < 0 || col >= MAP_COLS || row < 0 || row >= MAP_ROWS) return true;
    return collisionMap[row * MAP_COLS + col];
  }

  _updateAnimation(delta) {
    const dirRow = DIR_MAP[this.facing] || 0;

    if (this.moving) {
      this._animTime += delta;
      const frameIndex = Math.floor(this._animTime * ANIM_FPS) % SHEET_COLS;
      this._setFrame(frameIndex, dirRow);
    } else {
      this._animTime = 0;
      this._setFrame(0, dirRow); // idle = first frame
    }
  }

  _setFrame(col, row) {
    // UV offset: col/SHEET_COLS for X, flip Y (bottom-up in UV space)
    this._texture.offset.set(
      col / SHEET_COLS,
      1 - (row + 1) / SHEET_ROWS
    );
  }

  destroy() {
    if (this.sprite.parent) this.sprite.parent.remove(this.sprite);
    this._texture.dispose();
    this.sprite.material.dispose();
  }
}
