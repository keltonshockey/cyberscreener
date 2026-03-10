/**
 * QUAEST.TECH — 3rd Person Follow Camera
 * PerspectiveCamera that auto-rotates behind the player during movement.
 * Right-click drag for manual orbit, scroll to zoom.
 */

import * as THREE from 'three';
import {
  CAMERA_FOV, CAMERA_DISTANCE, CAMERA_MIN_DISTANCE, CAMERA_MAX_DISTANCE,
  CAMERA_MIN_PHI, CAMERA_MAX_PHI, CAMERA_ORBIT_SPEED, CAMERA_LERP,
  CAMERA_FOLLOW_PAUSE,
} from '../config.js';

export class CameraController {
  constructor(renderer) {
    this._canvas = renderer.domElement;
    const aspect = this._canvas.clientWidth / this._canvas.clientHeight;

    // Perspective camera
    this.camera = new THREE.PerspectiveCamera(CAMERA_FOV, aspect, 0.1, 500);

    // Orbit parameters (spherical coordinates)
    this.theta = Math.PI / 4;           // horizontal angle (radians)
    this.phi = Math.PI / 5;             // vertical tilt (0=top-down, π/2=horizon)
    this.radius = CAMERA_DISTANCE;
    this._radiusTarget = CAMERA_DISTANCE;

    // Follow target
    this.targetPos = new THREE.Vector3();
    this.currentPos = new THREE.Vector3();

    // Mouse orbit state (right-click only)
    this._dragging = false;
    this._lastMouse = { x: 0, y: 0 };

    // Auto-follow override (pauses after manual orbit)
    this._followPaused = false;
    this._followPauseTimer = null;

    // Bind input handlers
    this._onMouseDown = (e) => this._handleMouseDown(e);
    this._onMouseMove = (e) => this._handleMouseMove(e);
    this._onMouseUp = (e) => this._handleMouseUp(e);
    this._onWheel = (e) => { e.preventDefault(); this._handleWheel(e); };
    this._onContext = (e) => e.preventDefault();

    this._canvas.addEventListener('mousedown', this._onMouseDown);
    window.addEventListener('mousemove', this._onMouseMove);
    window.addEventListener('mouseup', this._onMouseUp);
    this._canvas.addEventListener('wheel', this._onWheel, { passive: false });
    this._canvas.addEventListener('contextmenu', this._onContext);

    // Set initial camera position
    this._applySpherical();
  }

  /** The horizontal angle for camera-relative movement. */
  get orbitTheta() { return this.theta; }

  /**
   * Set the position the camera should follow (usually the player).
   */
  setTarget(x, y, z) {
    this.targetPos.set(x, y, z);
  }

  /**
   * Set target orbit radius (for indoor/outdoor transitions).
   */
  setDistanceTarget(dist) {
    this._radiusTarget = Math.max(CAMERA_MIN_DISTANCE, Math.min(CAMERA_MAX_DISTANCE, dist));
  }

  /** Reset orbit radius to outdoor default. */
  resetDistanceTarget() {
    this._radiusTarget = CAMERA_DISTANCE;
  }

  /**
   * Auto-follow: smoothly rotate theta toward a target angle.
   * Called each frame when the player is moving.
   * @param {number} targetTheta - angle to lerp toward (behind player)
   * @param {number} lerpFactor - blend speed (0-1)
   */
  followTheta(targetTheta, lerpFactor) {
    if (this._followPaused || this._dragging) return;

    // Shortest-angle lerp
    let diff = targetTheta - this.theta;
    while (diff > Math.PI) diff -= Math.PI * 2;
    while (diff < -Math.PI) diff += Math.PI * 2;

    this.theta += diff * lerpFactor;
  }

  /**
   * Update camera each frame.
   */
  update() {
    // Lerp follow position toward target
    this.currentPos.lerp(this.targetPos, CAMERA_LERP);

    // Lerp radius toward target
    if (Math.abs(this.radius - this._radiusTarget) > 0.01) {
      this.radius += (this._radiusTarget - this.radius) * 0.06;
    }

    // Apply spherical → cartesian
    this._applySpherical();
  }

  /** Handle window resize. */
  handleResize(width, height) {
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  /** Destroy — remove event listeners. */
  destroy() {
    this._canvas.removeEventListener('mousedown', this._onMouseDown);
    window.removeEventListener('mousemove', this._onMouseMove);
    window.removeEventListener('mouseup', this._onMouseUp);
    this._canvas.removeEventListener('wheel', this._onWheel);
    this._canvas.removeEventListener('contextmenu', this._onContext);
    if (this._followPauseTimer) clearTimeout(this._followPauseTimer);
  }

  // ── Private ──

  _applySpherical() {
    const sp = Math.sin(this.phi);
    const cp = Math.cos(this.phi);
    const st = Math.sin(this.theta);
    const ct = Math.cos(this.theta);

    this.camera.position.set(
      this.currentPos.x + this.radius * sp * st,
      this.currentPos.y + this.radius * cp,
      this.currentPos.z + this.radius * sp * ct,
    );
    this.camera.lookAt(this.currentPos);
  }

  _handleMouseDown(e) {
    // Right-click only for manual orbit
    if (e.button === 2) {
      this._dragging = true;
      this._lastMouse.x = e.clientX;
      this._lastMouse.y = e.clientY;
      this._canvas.style.cursor = 'grabbing';
    }
  }

  _handleMouseMove(e) {
    if (!this._dragging) return;

    const dx = e.clientX - this._lastMouse.x;
    const dy = e.clientY - this._lastMouse.y;
    this._lastMouse.x = e.clientX;
    this._lastMouse.y = e.clientY;

    // Horizontal drag → rotate theta
    this.theta -= dx * CAMERA_ORBIT_SPEED;

    // Vertical drag → tilt phi
    this.phi = Math.max(
      CAMERA_MIN_PHI,
      Math.min(CAMERA_MAX_PHI, this.phi + dy * CAMERA_ORBIT_SPEED)
    );

    // Pause auto-follow after manual orbit
    this._followPaused = true;
    if (this._followPauseTimer) clearTimeout(this._followPauseTimer);
    this._followPauseTimer = setTimeout(() => {
      this._followPaused = false;
    }, CAMERA_FOLLOW_PAUSE);
  }

  _handleMouseUp(e) {
    if (e.button === 2) {
      this._dragging = false;
      this._canvas.style.cursor = 'default';
    }
  }

  _handleWheel(e) {
    const zoomDelta = e.deltaY > 0 ? 2 : -2;
    this._radiusTarget = Math.max(
      CAMERA_MIN_DISTANCE,
      Math.min(CAMERA_MAX_DISTANCE, this._radiusTarget + zoomDelta)
    );
  }
}
