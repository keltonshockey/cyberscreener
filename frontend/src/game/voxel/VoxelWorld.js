/**
 * QUAEST.TECH — Voxel World
 * Main Three.js scene orchestrator. Loads the map, builds voxel meshes,
 * manages player, NPCs, camera, districts, and the render loop.
 */

import * as THREE from 'three';
import { createTextureAtlas } from './TextureAtlas.js';
import { buildVoxelMeshes, buildCollisionMap } from './VoxelMeshBuilder.js';
import { CameraController } from './CameraController.js';
import { PlayerController } from './PlayerController.js';
import { VoxelNPC } from './VoxelNPC.js';
import { NPC_REGISTRY } from '../entities/NPCData.js';
import { MAP_COLS, MAP_ROWS, BLOCK_SIZE, BUILDING_DEFS, CAMERA_FOLLOW_LERP } from '../config.js';

export class VoxelWorld {
  constructor(container, callbacks) {
    this.container = container;
    this.callbacks = callbacks; // { onDistrictChange, onInteract, onBuildingEnter, onBuildingExit }
    this.running = false;
    this._animId = null;
    this._clock = new THREE.Clock();
    this._npcs = [];
    this._districts = [];
    this._currentDistrict = null;
    this._interactTarget = null;
    this._keyboardEnabled = true;

    // Building state for indoor/outdoor transitions
    this._buildingMeshes = {};
    this._insideBuilding = null; // building id or null

    // ── Renderer ──
    this.renderer = new THREE.WebGLRenderer({
      antialias: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(1); // crispy pixels
    this.renderer.setClearColor(0xCCAA77); // warm horizon color (matches fog)
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(this.renderer.domElement);

    // ── Scene ──
    this.scene = new THREE.Scene();

    // ── Atmospheric fog (depth layering) ──
    this.scene.fog = new THREE.Fog(0xCCAA77, 25, 90);

    // ── Lighting (warm Mediterranean) ──
    this._ambientLight = new THREE.AmbientLight(0xFFF0DD, 0.5);
    this.scene.add(this._ambientLight);

    // Hemisphere fill light (sky blue above, warm earth below)
    this._hemiLight = new THREE.HemisphereLight(0x88AACC, 0x886644, 0.3);
    this.scene.add(this._hemiLight);

    // Sun (warm directional)
    this._sunLight = new THREE.DirectionalLight(0xFFE4C0, 0.9);
    this._sunLight.position.set(40, 60, 25);
    this.scene.add(this._sunLight);

    // Indoor point light (off by default)
    this._indoorLight = new THREE.PointLight(0xffe8c0, 0, 15);
    this._indoorLight.visible = false;
    this.scene.add(this._indoorLight);

    // ── Camera ──
    this.cameraCtrl = new CameraController(this.renderer);
    // Update frustum with actual size
    this.cameraCtrl.handleResize(container.clientWidth, container.clientHeight);

    // ── Input state ──
    this._keys = {};
    this._onKeyDown = (e) => {
      if (!this._keyboardEnabled) return;
      this._keys[e.code] = true;
      if (e.code === 'KeyE') this._tryInteract();
    };
    this._onKeyUp = (e) => { this._keys[e.code] = false; };
    this._onResize = () => {
      const w = this.container.clientWidth;
      const h = this.container.clientHeight;
      this.renderer.setSize(w, h);
      this.cameraCtrl.handleResize(w, h);
    };
    // Click-to-move: only fire if mouse wasn't dragged (to not conflict with orbit)
    this._clickStart = null;
    this._onMouseDown = (e) => {
      if (e.button === 0) this._clickStart = { x: e.clientX, y: e.clientY };
    };
    this._onMouseUp = (e) => {
      if (e.button === 0 && this._clickStart) {
        const dx = e.clientX - this._clickStart.x;
        const dy = e.clientY - this._clickStart.y;
        // Only count as click if mouse barely moved (not an orbit drag)
        if (Math.abs(dx) < 5 && Math.abs(dy) < 5) {
          this._handleClick(e);
        }
        this._clickStart = null;
      }
    };

    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
    this.renderer.domElement.addEventListener('mousedown', this._onMouseDown);
    this.renderer.domElement.addEventListener('mouseup', this._onMouseUp);
    window.addEventListener('resize', this._onResize);
  }

  /**
   * Load the map and start the world.
   */
  async init() {
    // Load map JSON
    const resp = await fetch(`/assets/maps/roman-city.json?v=${Date.now()}`);
    this.mapData = await resp.json();

    // Build texture atlas
    this.atlas = createTextureAtlas();

    // Build voxel meshes (per-building groups for occlusion / indoor-outdoor)
    const result = buildVoxelMeshes(this.mapData, this.atlas);
    this.scene.add(result.worldGroup);
    this._buildingMeshes = result.buildingMeshes;
    this._terrainMesh = result.terrainMesh;
    this._cityWallsMesh = result.cityWallsMesh;

    // Build collision map
    this.collisionMap = buildCollisionMap(this.mapData);

    // Create sky dome (gradient sky background)
    this._createSkyDome();

    // Create ground shadows under buildings and trees
    this._createGroundShadows();

    // Parse object layers
    this._parseObjects();

    // Create player
    this._createPlayer();

    // Create NPCs
    this._createNPCs();

    // Create UI overlays
    this._createOverlays();

    // Create minimap
    this._createMinimap();

    // Start render loop
    this.running = true;
    this._animate();

    console.log('[QUAEST] Voxel world initialized');
  }

  /**
   * Main animation loop.
   */
  _animate() {
    if (!this.running) return;
    this._animId = requestAnimationFrame(() => this._animate());

    const delta = this._clock.getDelta();
    const time = this._clock.getElapsedTime();

    // Update player (pass camera orbit angle for relative movement)
    if (this.player) {
      this.player.setCameraAngle(this.cameraCtrl.orbitTheta);
      this.player.update(delta, this._keys, this.collisionMap);
      this.cameraCtrl.setTarget(this.player.x, 2, this.player.z);

      // Auto-follow: rotate camera behind player when moving
      if (this.player.isMoving) {
        const behindAngle = this.player.movementAngle + Math.PI;
        this.cameraCtrl.followTheta(behindAngle, CAMERA_FOLLOW_LERP);
      }

      // Keep indoor light following player
      if (this._insideBuilding && this._indoorLight.visible) {
        this._indoorLight.position.set(this.player.x, 4, this.player.z);
      }
    }

    // Update camera
    this.cameraCtrl.update();

    // Update NPCs
    for (const npc of this._npcs) {
      npc.update(delta, time);
    }

    // Indoor/outdoor transitions
    this._checkBuildingEntry();

    // Check districts
    this._checkDistrict();

    // Update interact prompt
    this._updateInteractPrompt();

    // Update coordinate display
    this._updateCoords();

    // Update minimap
    this._updateMinimap();

    // Keep sky dome centered on camera
    if (this._skyDome) {
      this._skyDome.position.copy(this.cameraCtrl.camera.position);
    }

    // Render
    this.renderer.render(this.scene, this.cameraCtrl.camera);
  }

  /**
   * Parse spawn points and zones from map object layers.
   */
  _parseObjects() {
    this._playerSpawn = { col: 22, row: 16 }; // default
    this._npcSpawns = [];
    this._districts = [];

    for (const layer of this.mapData.layers) {
      if (layer.type !== 'objectgroup') continue;

      for (const obj of layer.objects || []) {
        if (obj.type === 'player_spawn') {
          // Convert world coords back to tile coords
          // The map stores isometric world coords, we need grid col/row
          // From generate-map: x = (col - row) * 32, y = (col + row) * 16
          const wx = obj.x;
          const wy = obj.y;
          const col = Math.round((wx / 32 + wy / 16) / 2);
          const row = Math.round((wy / 16 - wx / 32) / 2);
          this._playerSpawn = { col, row };
        } else if (obj.type === 'npc_spawn') {
          const props = {};
          for (const p of obj.properties || []) {
            props[p.name] = p.value;
          }
          const wx = obj.x;
          const wy = obj.y;
          const col = Math.round((wx / 32 + wy / 16) / 2);
          const row = Math.round((wy / 16 - wx / 32) / 2);
          this._npcSpawns.push({
            name: obj.name,
            col, row,
            ...props,
          });
        } else if (obj.type === 'district') {
          const props = {};
          for (const p of obj.properties || []) {
            props[p.name] = p.value;
          }
          // Convert isometric world rect to grid rect
          // We'll use a simpler approach: check if player grid pos is inside known district rects
          this._districts.push({
            id: props.districtId,
            name: obj.name,
            desc: props.desc,
            color: props.color,
            labelColor: props.labelColor || props.color,
            locked: props.locked,
            // Store the world-space bounding box
            wx: obj.x,
            wy: obj.y,
            ww: obj.width,
            wh: obj.height,
          });
        }
      }
    }
  }

  /**
   * Create player entity.
   */
  _createPlayer() {
    const { col, row } = this._playerSpawn;
    this.player = new PlayerController(this.scene, col, row);
    console.log(`[QUAEST] Player spawned at tile (${col}, ${row})`);
  }

  /**
   * Create NPC entities from spawn data.
   */
  _createNPCs() {
    for (const spawn of this._npcSpawns) {
      const npc = new VoxelNPC(this.scene, spawn, this.collisionMap);
      this._npcs.push(npc);
    }
    console.log(`[QUAEST] Created ${this._npcs.length} NPCs`);
  }

  /**
   * Check if player is in a district zone.
   */
  _checkDistrict() {
    if (!this.player) return;

    const px = this.player.x;
    const pz = this.player.z;
    // Convert 3D grid position back to isometric world coords for zone matching
    const col = Math.floor(px / BLOCK_SIZE);
    const row = Math.floor(pz / BLOCK_SIZE);
    const isoX = (col - row) * 32;
    const isoY = (col + row) * 16;

    let found = null;
    for (const d of this._districts) {
      if (isoX >= d.wx && isoX <= d.wx + d.ww &&
          isoY >= d.wy && isoY <= d.wy + d.wh) {
        found = d;
        break;
      }
    }

    if (found?.id !== this._currentDistrict?.id) {
      this._currentDistrict = found;
      this.callbacks.onDistrictChange?.(found);

      // Show/hide district label
      if (this._districtLabel) {
        if (found) {
          this._districtLabel.textContent = found.name;
          this._districtLabel.style.color = found.labelColor || '#F2F2F2';
          this._districtLabel.style.opacity = '1';
          clearTimeout(this._districtFadeTimer);
          this._districtFadeTimer = setTimeout(() => {
            if (this._districtLabel) this._districtLabel.style.opacity = '0';
          }, 3000);
        } else {
          this._districtLabel.style.opacity = '0';
        }
      }
    }
  }

  /**
   * Find nearest interactable NPC and show/hide prompt.
   */
  _updateInteractPrompt() {
    if (!this.player) return;

    const px = this.player.x;
    const pz = this.player.z;
    let nearest = null;
    let nearestDist = Infinity;

    for (const npc of this._npcs) {
      const dx = npc.x - px;
      const dz = npc.z - pz;
      const dist = Math.sqrt(dx * dx + dz * dz);
      const radius = (npc.data?.interactRadius || 40) / 10; // scale from old pixel radius to blocks
      if (dist < radius && dist < nearestDist) {
        nearest = npc;
        nearestDist = dist;
      }
    }

    this._interactTarget = nearest;

    if (this._interactPrompt) {
      if (nearest) {
        // Project NPC position to screen
        const npcPos = new THREE.Vector3(nearest.x, 2.5, nearest.z);
        npcPos.project(this.cameraCtrl.camera);
        const hw = this.container.clientWidth / 2;
        const hh = this.container.clientHeight / 2;
        const sx = (npcPos.x * hw) + hw;
        const sy = -(npcPos.y * hh) + hh;

        this._interactPrompt.style.left = `${sx}px`;
        this._interactPrompt.style.top = `${sy - 30}px`;
        this._interactPrompt.textContent = `[E] ${nearest.npcName}`;
        this._interactPrompt.style.display = 'block';
      } else {
        this._interactPrompt.style.display = 'none';
      }
    }
  }

  /**
   * Try to interact with nearest NPC.
   */
  _tryInteract() {
    if (!this._interactTarget) return;

    const npc = this._interactTarget;
    npc.facePlayer(this.player.x, this.player.z);
    const dialog = npc.getDialog();

    this.callbacks.onInteract?.({
      type: 'npc',
      name: npc.npcName,
      dialog: dialog,
    });

    // Show dialog bubble
    if (this._dialogBubble) {
      this._dialogBubble.textContent = dialog;
      this._dialogBubble.style.display = 'block';
      clearTimeout(this._dialogTimer);
      this._dialogTimer = setTimeout(() => {
        if (this._dialogBubble) this._dialogBubble.style.display = 'none';
      }, 4000);
    }
  }

  /**
   * Handle click-to-move.
   */
  _handleClick(event) {
    if (!this.player) return;

    const rect = this.renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, this.cameraCtrl.camera);

    // Intersect with ground plane (y=1, top of ground blocks)
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -1);
    const target = new THREE.Vector3();
    raycaster.ray.intersectPlane(plane, target);

    if (target) {
      // Clamp to grid
      const col = Math.floor(target.x / BLOCK_SIZE);
      const row = Math.floor(target.z / BLOCK_SIZE);
      if (col >= 0 && col < MAP_COLS && row >= 0 && row < MAP_ROWS) {
        if (!this.collisionMap[row * MAP_COLS + col]) {
          this.player.setMoveTarget(col + 0.5, row + 0.5);
        }
      }
    }
  }

  /**
   * Create HTML overlay elements.
   */
  _createOverlays() {
    // District label (top center)
    this._districtLabel = document.createElement('div');
    Object.assign(this._districtLabel.style, {
      position: 'absolute',
      top: '16px',
      left: '50%',
      transform: 'translateX(-50%)',
      fontFamily: 'Cinzel, serif',
      fontSize: '18px',
      color: '#F2F2F2',
      textShadow: '0 2px 8px rgba(0,0,0,0.8)',
      opacity: '0',
      transition: 'opacity 0.5s ease',
      pointerEvents: 'none',
      zIndex: '10',
    });
    this.container.appendChild(this._districtLabel);

    // Interact prompt
    this._interactPrompt = document.createElement('div');
    Object.assign(this._interactPrompt.style, {
      position: 'absolute',
      display: 'none',
      fontFamily: 'monospace',
      fontSize: '11px',
      color: '#F2F2F2',
      background: 'rgba(0,0,0,0.7)',
      padding: '3px 8px',
      borderRadius: '4px',
      border: '1px solid rgba(78,11,89,0.6)',
      transform: 'translateX(-50%)',
      pointerEvents: 'none',
      whiteSpace: 'nowrap',
      zIndex: '10',
    });
    this.container.appendChild(this._interactPrompt);

    // Dialog bubble
    this._dialogBubble = document.createElement('div');
    Object.assign(this._dialogBubble.style, {
      position: 'absolute',
      bottom: '80px',
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'none',
      fontFamily: '"Segoe UI", sans-serif',
      fontSize: '13px',
      color: '#F2F2F2',
      background: 'rgba(0,0,0,0.85)',
      padding: '10px 16px',
      borderRadius: '8px',
      border: '1px solid rgba(78,11,89,0.5)',
      maxWidth: '80%',
      textAlign: 'center',
      pointerEvents: 'none',
      zIndex: '10',
    });
    this.container.appendChild(this._dialogBubble);

    // Coordinates (top left)
    this._coordsEl = document.createElement('div');
    Object.assign(this._coordsEl.style, {
      position: 'absolute',
      top: '8px',
      left: '8px',
      fontFamily: 'monospace',
      fontSize: '10px',
      color: 'rgba(166,166,166,0.7)',
      pointerEvents: 'none',
      zIndex: '10',
    });
    this.container.appendChild(this._coordsEl);
  }

  _updateCoords() {
    if (!this._coordsEl || !this.player) return;
    const col = Math.floor(this.player.x / BLOCK_SIZE);
    const row = Math.floor(this.player.z / BLOCK_SIZE);
    this._coordsEl.textContent = `(${col}, ${row})`;
  }

  /**
   * Create the minimap canvas.
   */
  _createMinimap() {
    const size = 120;
    const canvas = document.createElement('canvas');
    canvas.width = MAP_COLS;
    canvas.height = MAP_ROWS;
    Object.assign(canvas.style, {
      position: 'absolute',
      bottom: '8px',
      right: '8px',
      width: `${size}px`,
      height: `${size * (MAP_ROWS / MAP_COLS)}px`,
      border: '1px solid rgba(78,11,89,0.5)',
      borderRadius: '4px',
      imageRendering: 'pixelated',
      background: '#111',
      zIndex: '10',
    });
    this.container.appendChild(canvas);
    this._minimapCanvas = canvas;
    this._minimapCtx = canvas.getContext('2d');

    // Draw static tiles once
    this._drawMinimapBase();
  }

  _drawMinimapBase() {
    const ctx = this._minimapCtx;
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, MAP_COLS, MAP_ROWS);

    const layers = {};
    for (const layer of this.mapData.layers) {
      if (layer.type === 'tilelayer') layers[layer.name] = layer.data;
    }
    const ground = layers['Ground'] || [];
    const walls = layers['Walls'] || [];

    const colorMap = {
      grass: '#3A6B3A', stone: '#5A5A5A', marble: '#C8C0B0',
      road: '#807060', water: '#3366AA', int_floor: '#B0A890',
      wall: '#2A2A2A', wall_surface: '#4A4A4A', wall_dark: '#1A1A1A',
      wall_light: '#5A5A5A', door: '#6B4A2B', shelf: '#806040',
      pillar: '#A98860', column: '#B0A080', banner: '#4E0B59',
      tree_trunk: '#5B3413', fountain: '#5588AA', parapet: '#3A3A3A',
      window_wall: '#2A2A2A', shadow: '#4A4A4A',
      // Building-specific
      curia_wall: '#E8E0D4', curia_door: '#6B4A2B',
      basilica_wall: '#D4C4A0', basilica_door: '#6B4A2B',
      subura_wall: '#8B8B80', subura_door: '#6B4A2B',
      tabularium_wall: '#707070', tabularium_door: '#6B4A2B',
      pediment: '#E8E0D4', arch_block: '#A09070',
    };

    for (let row = 0; row < MAP_ROWS; row++) {
      for (let col = 0; col < MAP_COLS; col++) {
        const idx = row * MAP_COLS + col;

        // Draw wall if present, else ground
        const wGid = walls[idx];
        const gGid = ground[idx];
        let type = null;

        if (wGid) type = getBlockTypeForMinimap(wGid);
        if (!type && gGid) type = getBlockTypeForMinimap(gGid);

        if (type && colorMap[type]) {
          ctx.fillStyle = colorMap[type];
          ctx.fillRect(col, row, 1, 1);
        }
      }
    }

    // Save base image
    this._minimapBase = ctx.getImageData(0, 0, MAP_COLS, MAP_ROWS);
  }

  _updateMinimap() {
    if (!this._minimapCtx || !this.player || !this._minimapBase) return;
    const ctx = this._minimapCtx;

    // Restore base
    ctx.putImageData(this._minimapBase, 0, 0);

    // Draw player dot
    const col = Math.floor(this.player.x / BLOCK_SIZE);
    const row = Math.floor(this.player.z / BLOCK_SIZE);
    ctx.fillStyle = '#FFD700';
    ctx.fillRect(col - 1, row - 1, 3, 3);

    // Draw NPC dots
    ctx.fillStyle = '#FF4444';
    for (const npc of this._npcs) {
      const nc = Math.floor(npc.x / BLOCK_SIZE);
      const nr = Math.floor(npc.z / BLOCK_SIZE);
      ctx.fillRect(nc, nr, 2, 2);
    }
  }

  /**
   * Enable/disable keyboard input (for chat focus).
   */
  setKeyboardEnabled(enabled) {
    this._keyboardEnabled = enabled;
    if (!enabled) {
      // Clear all keys
      for (const key in this._keys) this._keys[key] = false;
    }
  }

  // ─────────────────────────────────────────────────────
  //  Sky Dome & Ground Shadows
  // ─────────────────────────────────────────────────────

  /**
   * Create a gradient sky dome (large inverted sphere).
   */
  _createSkyDome() {
    // Procedural gradient texture on a canvas
    const skyCanvas = document.createElement('canvas');
    skyCanvas.width = 1;
    skyCanvas.height = 256;
    const ctx = skyCanvas.getContext('2d');

    // Vertical gradient: sky blue → pale gold → warm horizon
    const grad = ctx.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0.0, '#4488AA');   // zenith — blue sky
    grad.addColorStop(0.3, '#6699BB');   // upper sky
    grad.addColorStop(0.5, '#88AACC');   // mid sky
    grad.addColorStop(0.7, '#CCBB99');   // haze
    grad.addColorStop(0.85, '#DDBB88');  // horizon gold
    grad.addColorStop(1.0, '#CC9955');   // warm base
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 1, 256);

    const skyTexture = new THREE.CanvasTexture(skyCanvas);
    skyTexture.needsUpdate = true;

    const skyGeo = new THREE.SphereGeometry(200, 16, 16);
    const skyMat = new THREE.MeshBasicMaterial({
      map: skyTexture,
      side: THREE.BackSide, // render inside faces
      fog: false,           // sky not affected by fog
      depthWrite: false,
    });
    this._skyDome = new THREE.Mesh(skyGeo, skyMat);
    this._skyDome.name = 'skyDome';
    this.scene.add(this._skyDome);
  }

  /**
   * Create dark shadow quads under buildings and trees.
   */
  _createGroundShadows() {
    const shadowGroup = new THREE.Group();
    shadowGroup.name = 'groundShadows';

    const shadowMat = new THREE.MeshBasicMaterial({
      color: 0x000000,
      transparent: true,
      opacity: 0.2,
      depthWrite: false,
      side: THREE.DoubleSide,
    });

    // Shadows under each building (with 1-tile overhang)
    for (const [id, def] of Object.entries(BUILDING_DEFS)) {
      const b = def.bounds;
      const w = (b.w + 2) * BLOCK_SIZE;
      const h = (b.h + 2) * BLOCK_SIZE;
      const geo = new THREE.PlaneGeometry(w, h);
      geo.rotateX(-Math.PI / 2); // lay flat on XZ plane
      const shadow = new THREE.Mesh(geo, shadowMat);
      shadow.position.set(
        (b.x + b.w / 2) * BLOCK_SIZE,
        0.02, // just above ground
        (b.y + b.h / 2) * BLOCK_SIZE
      );
      shadowGroup.add(shadow);
    }

    // Shadows under trees — find tree trunk tiles from map data
    const treeShadowMat = new THREE.MeshBasicMaterial({
      color: 0x000000,
      transparent: true,
      opacity: 0.15,
      depthWrite: false,
      side: THREE.DoubleSide,
    });

    if (this.mapData) {
      const walls = this.mapData.layers.find(l => l.name === 'Walls');
      if (walls && walls.data) {
        for (let row = 0; row < MAP_ROWS; row++) {
          for (let col = 0; col < MAP_COLS; col++) {
            const gid = walls.data[row * MAP_COLS + col];
            // GID 107-108 = tree trunks
            if (gid >= 107 && gid <= 108) {
              const geo = new THREE.PlaneGeometry(2.5 * BLOCK_SIZE, 2.5 * BLOCK_SIZE);
              geo.rotateX(-Math.PI / 2);
              const shadow = new THREE.Mesh(geo, treeShadowMat);
              shadow.position.set(
                (col + 0.5) * BLOCK_SIZE,
                0.02,
                (row + 0.5) * BLOCK_SIZE
              );
              shadowGroup.add(shadow);
            }
          }
        }
      }
    }

    this.scene.add(shadowGroup);
    this._shadowGroup = shadowGroup;
  }

  // ─────────────────────────────────────────────────────
  //  Indoor/Outdoor Building Transitions
  // ─────────────────────────────────────────────────────

  /**
   * Detect if player has entered/exited a building and toggle visibility.
   */
  _checkBuildingEntry() {
    if (!this.player || !this._buildingMeshes) return;

    const playerCol = Math.floor(this.player.x / BLOCK_SIZE);
    const playerRow = Math.floor(this.player.z / BLOCK_SIZE);

    // Check if player is inside any building (1 tile inward from walls = interior)
    let inside = null;
    for (const [id, def] of Object.entries(BUILDING_DEFS)) {
      const b = def.bounds;
      if (playerCol > b.x && playerCol < b.x + b.w - 1 &&
          playerRow > b.y && playerRow < b.y + b.h - 1) {
        inside = id;
        break;
      }
    }

    if (inside !== this._insideBuilding) {
      if (inside) {
        this._enterBuilding(inside);
      } else {
        this._exitBuilding();
      }
      this._insideBuilding = inside;
    }
  }

  _enterBuilding(buildingId) {
    const meshes = this._buildingMeshes[buildingId];
    const def = BUILDING_DEFS[buildingId];
    if (!meshes || !def) return;

    console.log(`[QUAEST] Entering ${buildingId}`);

    // Hide exterior walls and roof so camera can see inside
    if (meshes.exterior) meshes.exterior.visible = false;
    if (meshes.roof) meshes.roof.visible = false;
    // Interior stays visible (floor, shelves, pillars)

    // Pull camera closer
    this.cameraCtrl.setDistanceTarget(def.interiorDistance || 8);

    // Dim outdoor lighting, enable indoor light
    this._ambientLight.intensity = 0.3;
    this._sunLight.intensity = 0.25;
    if (this._hemiLight) this._hemiLight.intensity = 0.1;
    this._indoorLight.visible = true;
    this._indoorLight.intensity = 1.2;
    this._indoorLight.position.set(
      this.player.x, 4, this.player.z
    );

    // Keep terrain + other buildings visible (player can see outside through doorway)

    // Notify React — open the building's content panel
    this.callbacks.onBuildingEnter?.(buildingId);
  }

  _exitBuilding() {
    if (!this._insideBuilding) return;
    const prevId = this._insideBuilding;
    const meshes = this._buildingMeshes[prevId];

    console.log(`[QUAEST] Exiting ${prevId}`);

    // Restore exterior walls and roof
    if (meshes) {
      if (meshes.exterior) meshes.exterior.visible = true;
      if (meshes.roof) meshes.roof.visible = true;
    }

    // Restore camera distance
    this.cameraCtrl.resetDistanceTarget();

    // Restore lighting (warm Mediterranean outdoor values)
    this._ambientLight.intensity = 0.5;
    this._sunLight.intensity = 0.9;
    if (this._hemiLight) this._hemiLight.intensity = 0.3;
    this._indoorLight.visible = false;

    // Notify React — close any open building panel
    this.callbacks.onBuildingExit?.(prevId);
  }

  /**
   * Destroy everything.
   */
  destroy() {
    this.running = false;
    if (this._animId) cancelAnimationFrame(this._animId);

    window.removeEventListener('keydown', this._onKeyDown);
    window.removeEventListener('keyup', this._onKeyUp);
    window.removeEventListener('resize', this._onResize);
    this.renderer.domElement.removeEventListener('mousedown', this._onMouseDown);
    this.renderer.domElement.removeEventListener('mouseup', this._onMouseUp);
    if (this.cameraCtrl) this.cameraCtrl.destroy();

    // Remove overlays
    for (const el of [this._districtLabel, this._interactPrompt, this._dialogBubble, this._coordsEl, this._minimapCanvas]) {
      if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    // Dispose Three.js resources
    this.scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        if (obj.material.map) obj.material.map.dispose();
        obj.material.dispose();
      }
    });
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }

    console.log('[QUAEST] Voxel world destroyed');
  }
}

// Helper for minimap — import directly to avoid circular dep
import { getBlockType } from './BlockTypes.js';
function getBlockTypeForMinimap(gid) {
  return getBlockType(gid);
}
