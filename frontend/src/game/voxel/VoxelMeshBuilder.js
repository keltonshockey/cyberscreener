/**
 * QUAEST.TECH — Voxel Mesh Builder
 * Reads tile layer data from the map JSON and creates Three.js geometry.
 * Produces per-building mesh groups for occlusion / indoor-outdoor transitions.
 */

import * as THREE from 'three';
import { getBlockType, getBlockDef } from './BlockTypes.js';
import { getTexUV } from './TextureAtlas.js';
import { MAP_COLS, MAP_ROWS, BLOCK_SIZE, BUILDING_DEFS } from '../config.js';
import { decorateBuilding } from './BuildingDecorator.js';

// ─── GeomCollector: accumulates quads into a single merged BufferGeometry ───

class GeomCollector {
  constructor() {
    this.vertices = [];
    this.uvs = [];
    this.indices = [];
    this.vOff = 0;
  }

  addFace(v0, v1, v2, v3, texName, atlas) {
    const [u0, vb, u1, vt] = getTexUV(atlas, texName);
    for (const v of [v0, v1, v2, v3]) {
      this.vertices.push(v[0], v[1], v[2]);
    }
    this.uvs.push(u0, vb, u1, vb, u1, vt, u0, vt);
    this.indices.push(
      this.vOff, this.vOff + 1, this.vOff + 2,
      this.vOff, this.vOff + 2, this.vOff + 3
    );
    this.vOff += 4;
  }

  addBlock(col, row, baseY, height, topTex, sideTex, atlas) {
    if (!topTex && !sideTex) return;
    const x = col * BLOCK_SIZE;
    const z = row * BLOCK_SIZE;
    const y0 = baseY * BLOCK_SIZE;
    const y1 = (baseY + height) * BLOCK_SIZE;
    const s = BLOCK_SIZE;

    // Top face
    if (topTex) {
      this.addFace(
        [x, y1, z + s], [x + s, y1, z + s],
        [x + s, y1, z], [x, y1, z],
        topTex, atlas
      );
    }

    // Side faces (front, right, back, left)
    if (sideTex) {
      this.addFace([x, y0, z + s], [x + s, y0, z + s], [x + s, y1, z + s], [x, y1, z + s], sideTex, atlas);
      this.addFace([x + s, y0, z + s], [x + s, y0, z], [x + s, y1, z], [x + s, y1, z + s], sideTex, atlas);
      this.addFace([x + s, y0, z], [x, y0, z], [x, y1, z], [x + s, y1, z], sideTex, atlas);
      this.addFace([x, y0, z], [x, y0, z + s], [x, y1, z + s], [x, y1, z], sideTex, atlas);
    }
  }

  buildMesh(atlas) {
    if (this.vertices.length === 0) return null;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(this.vertices, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(this.uvs, 2));
    geometry.setIndex(this.indices);
    geometry.computeVertexNormals();

    const material = new THREE.MeshLambertMaterial({
      map: atlas.texture,
      side: THREE.FrontSide,
    });

    return new THREE.Mesh(geometry, material);
  }

  get faceCount() { return this.vOff / 4; }
}

// ─── Tile → Building classification ───

const _buildingBoundsCache = [];
for (const [id, def] of Object.entries(BUILDING_DEFS)) {
  const b = def.bounds;
  _buildingBoundsCache.push({
    id,
    x0: b.x, y0: b.y,
    x1: b.x + b.w - 1,
    y1: b.y + b.h - 1,
  });
}

/**
 * Determine which building a tile belongs to (if any) and whether it's an edge tile.
 * @returns {{ id: string, isEdge: boolean } | null}
 */
function getBuildingForTile(col, row) {
  for (const b of _buildingBoundsCache) {
    if (col >= b.x0 && col <= b.x1 && row >= b.y0 && row <= b.y1) {
      const isEdge = (col === b.x0 || col === b.x1 || row === b.y0 || row === b.y1);
      return { id: b.id, isEdge };
    }
  }
  return null;
}

// ─── Main build function ───

/**
 * Build the voxel world meshes from map layer data.
 * Returns a structured result with per-building mesh groups for occlusion control.
 *
 * @param {object} mapData - Parsed Tiled JSON
 * @param {object} atlas - Texture atlas from createTextureAtlas()
 * @returns {{ worldGroup: THREE.Group, terrainMesh, cityWallsMesh, buildingMeshes }}
 */
export function buildVoxelMeshes(mapData, atlas) {
  // Extract tile layers
  const layers = {};
  for (const layer of mapData.layers) {
    if (layer.type === 'tilelayer') {
      layers[layer.name] = layer.data;
    }
  }

  const ground = layers['Ground'] || [];
  const groundDecor = layers['GroundDecor'] || [];
  const walls = layers['Walls'] || [];
  const wallTops = layers['WallTops'] || [];

  // Create collectors
  const terrainCol = new GeomCollector();
  const cityWallsCol = new GeomCollector();

  const buildingCols = {};
  for (const id of Object.keys(BUILDING_DEFS)) {
    buildingCols[id] = {
      exterior: new GeomCollector(),
      roof: new GeomCollector(),
      interior: new GeomCollector(),
    };
  }

  /**
   * Route a tile to the appropriate collector.
   * @param {'Ground'|'Walls'|'WallTops'} layer
   */
  function getCollector(col, row, layer) {
    const building = getBuildingForTile(col, row);

    if (!building) {
      // Not inside any building
      if (layer === 'Ground') return terrainCol;
      if (layer === 'Walls') return cityWallsCol;
      if (layer === 'WallTops') return cityWallsCol;
      return terrainCol;
    }

    // Inside a building
    const bc = buildingCols[building.id];
    if (layer === 'WallTops') return bc.roof;
    if (layer === 'Walls') {
      return building.isEdge ? bc.exterior : bc.interior;
    }
    // Ground / GroundDecor inside building → interior
    return bc.interior;
  }

  // ── Process Ground layer ──
  for (let row = 0; row < MAP_ROWS; row++) {
    for (let col = 0; col < MAP_COLS; col++) {
      const idx = row * MAP_COLS + col;
      const gid = ground[idx];
      if (!gid) continue;

      const def = getBlockDef(gid);
      if (!def || def.height === 0) continue;

      // GroundDecor may override top texture
      let topTex = def.top;
      const decorGid = groundDecor[idx];
      if (decorGid) {
        const decorDef = getBlockDef(decorGid);
        if (decorDef && decorDef.top) topTex = decorDef.top;
      }

      const baseY = def.top === 'water_top' ? -0.3 : 0;
      const col_ = getCollector(col, row, 'Ground');
      col_.addBlock(col, row, baseY, def.height, topTex, def.side, atlas);
    }
  }

  // ── Process Walls layer ──
  for (let row = 0; row < MAP_ROWS; row++) {
    for (let col = 0; col < MAP_COLS; col++) {
      const idx = row * MAP_COLS + col;
      const gid = walls[idx];
      if (!gid) continue;

      const def = getBlockDef(gid);
      if (!def || def.height === 0) continue;

      const col_ = getCollector(col, row, 'Walls');
      col_.addBlock(col, row, 1, def.height, def.top, def.side, atlas);
    }
  }

  // ── Process WallTops layer ──
  for (let row = 0; row < MAP_ROWS; row++) {
    for (let col = 0; col < MAP_COLS; col++) {
      const idx = row * MAP_COLS + col;
      const gid = wallTops[idx];
      if (!gid) continue;

      const def = getBlockDef(gid);
      if (!def || def.height === 0) continue;

      // Stack on top of whatever is in the walls layer
      const wallGid = walls[idx];
      let wallHeight = 0;
      if (wallGid) {
        const wallDef = getBlockDef(wallGid);
        if (wallDef) wallHeight = wallDef.height;
      }

      const col_ = getCollector(col, row, 'WallTops');
      col_.addBlock(col, row, 1 + wallHeight, def.height, def.top, def.side, atlas);
    }
  }

  // ── Add architectural decorations to buildings ──
  for (const [id, cols] of Object.entries(buildingCols)) {
    decorateBuilding(id, cols, atlas);
  }

  // ── Assemble scene graph ──
  const worldGroup = new THREE.Group();

  const terrainMesh = terrainCol.buildMesh(atlas);
  if (terrainMesh) { terrainMesh.name = 'terrain'; worldGroup.add(terrainMesh); }

  const cityWallsMesh = cityWallsCol.buildMesh(atlas);
  if (cityWallsMesh) { cityWallsMesh.name = 'cityWalls'; worldGroup.add(cityWallsMesh); }

  const buildingMeshes = {};
  for (const [id, cols] of Object.entries(buildingCols)) {
    const bGroup = new THREE.Group();
    bGroup.name = `building_${id}`;

    const exterior = cols.exterior.buildMesh(atlas);
    const roof = cols.roof.buildMesh(atlas);
    const interior = cols.interior.buildMesh(atlas);

    if (exterior) { exterior.name = `${id}_exterior`; bGroup.add(exterior); }
    if (roof) { roof.name = `${id}_roof`; bGroup.add(roof); }
    if (interior) { interior.name = `${id}_interior`; bGroup.add(interior); }

    buildingMeshes[id] = { group: bGroup, exterior, roof, interior };
    worldGroup.add(bGroup);
  }

  // ── Stats ──
  let totalFaces = terrainCol.faceCount + cityWallsCol.faceCount;
  const buildingStats = [];
  for (const [id, cols] of Object.entries(buildingCols)) {
    const ext = cols.exterior.faceCount;
    const rf = cols.roof.faceCount;
    const int_ = cols.interior.faceCount;
    totalFaces += ext + rf + int_;
    buildingStats.push(`${id}(ext:${ext} roof:${rf} int:${int_})`);
  }

  console.log(
    `[QUAEST] Built voxel world: ${totalFaces} faces | ` +
    `terrain:${terrainCol.faceCount} walls:${cityWallsCol.faceCount} | ` +
    buildingStats.join(' ')
  );

  return { worldGroup, terrainMesh, cityWallsMesh, buildingMeshes };
}

/**
 * Build a collision map from the tile data.
 * Returns a flat boolean array [row * MAP_COLS + col] → true if blocked.
 */
export function buildCollisionMap(mapData) {
  const blocked = new Array(MAP_COLS * MAP_ROWS).fill(false);

  const layers = {};
  for (const layer of mapData.layers) {
    if (layer.type === 'tilelayer') {
      layers[layer.name] = layer.data;
    }
  }

  const ground = layers['Ground'] || [];
  const walls = layers['Walls'] || [];

  for (let i = 0; i < MAP_COLS * MAP_ROWS; i++) {
    const gDef = getBlockDef(ground[i]);
    if (gDef && gDef.solid) {
      blocked[i] = true;
      continue;
    }

    const wDef = getBlockDef(walls[i]);
    if (wDef && wDef.solid) {
      blocked[i] = true;
    }
  }

  return blocked;
}

// Re-export GeomCollector for BuildingDecorator
export { GeomCollector, getBuildingForTile };
