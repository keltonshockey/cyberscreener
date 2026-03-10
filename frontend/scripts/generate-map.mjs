/**
 * QUAEST.TECH — Isometric Map Generator
 *
 * Generates a Tiled-compatible JSON map with orientation:'isometric'.
 * Tile size: 64×32 (2:1 isometric ratio). Grid: 50 cols × 40 rows.
 *
 * Usage: node scripts/generate-map.mjs
 * Output: public/assets/maps/roman-city.json
 */

import { writeFile, mkdir } from 'fs/promises';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, '..', 'public', 'assets', 'maps', 'roman-city.json');

const TW = 64;    // tile width
const TH = 32;    // tile height
const COLS = 50;
const ROWS = 40;

// ── Isometric coordinate helpers ──
function tileToWorld(col, row) {
  return {
    x: (col - row) * (TW / 2),
    y: (col + row) * (TH / 2),
  };
}

// ── GID mapping for isometric tilesets ──
// terrain-iso.png: 10 cols × 6 rows = 60 slots, firstgid=1
// buildings-iso.png: 10 cols × 4 rows = 40 slots, firstgid=61
// decorations-iso.png: 10 cols × 4 rows = 40 slots, firstgid=101

const GID = {
  EMPTY: 0,
  // Terrain (firstgid=1)
  GRASS: 1, STONE: 9, MARBLE: 17, ROAD: 25, WATER: 33, VOID: 37,
  INT_FLOOR: 41, SHADOW: 45,
  // Buildings (firstgid=61)
  WALL: 61, WALL_SURFACE: 67, WALL_DARK: 71, WALL_LIGHT: 73,
  DOOR: 75, SHELF: 77, WINDOW_WALL: 79, PARAPET: 81,
  // Decorations (firstgid=101)
  PILLAR: 101, COLUMN: 103, BANNER: 105, TREE_TRUNK: 107,
  FOUNTAIN: 109, TREE_CANOPY: 111, WALL_PARAPET: 115,
  // Building-specific (firstgid=121)
  CURIA_WALL: 121, BASILICA_WALL: 123, SUBURA_WALL: 125, TABULARIUM_WALL: 127,
  CURIA_DOOR: 129, BASILICA_DOOR: 131, SUBURA_DOOR: 133, TABULARIUM_DOOR: 135,
};

// ── Deterministic random ──
let _seed = 42;
function rand() { _seed = (_seed * 16807) % 2147483647; return (_seed & 0x7fffffff) / 0x7fffffff; }
function resetSeed(s) { _seed = s; }
function vary(base, count = 8) { return base + Math.floor(rand() * count); }

// ── Layer helpers ──

function createLayer(name) {
  return { name, data: new Array(COLS * ROWS).fill(0) };
}

function setTile(layer, col, row, gid) {
  if (row >= 0 && row < ROWS && col >= 0 && col < COLS) {
    layer.data[row * COLS + col] = gid;
  }
}

function getTile(layer, col, row) {
  if (row >= 0 && row < ROWS && col >= 0 && col < COLS) {
    return layer.data[row * COLS + col];
  }
  return 0;
}

function fillRect(layer, x, y, w, h, gid, randomize = false, varCount = 8) {
  for (let r = y; r < y + h && r < ROWS; r++) {
    for (let c = x; c < x + w && c < COLS; c++) {
      if (r >= 0 && c >= 0) {
        resetSeed(r * 1000 + c * 7 + gid);
        setTile(layer, c, r, randomize ? vary(gid, varCount) : gid);
      }
    }
  }
}

function strokeRect(layer, x, y, w, h, gid) {
  for (let c = x; c < x + w; c++) {
    setTile(layer, c, y, gid);
    setTile(layer, c, y + h - 1, gid);
  }
  for (let r = y; r < y + h; r++) {
    setTile(layer, x, r, gid);
    setTile(layer, x + w - 1, r, gid);
  }
}

// ── Map generation ──

function generateMapData() {
  const ground = createLayer('Ground');
  const groundDecor = createLayer('GroundDecor');
  const walls = createLayer('Walls');
  const wallTops = createLayer('WallTops');

  // Base terrain: grass everywhere
  fillRect(ground, 0, 0, COLS, ROWS, GID.GRASS, true);

  // ── Natural landscape border (no walls) ──
  // Outer 2-tile border: barren dirt/rocks
  for (let c = 0; c < COLS; c++) {
    for (let r = 0; r < ROWS; r++) {
      const atEdge = c < 2 || c >= COLS - 2 || r < 2 || r >= ROWS - 2;
      if (atEdge) {
        resetSeed(r * 1000 + c * 7 + 999);
        setTile(ground, c, r, vary(GID.STONE, 8)); // rocky barren ground
      }
    }
  }

  // Scattered rocks (small wall blocks on border area)
  const rockPositions = [
    [0, 5], [1, 8], [0, 15], [1, 22], [0, 30], [1, 35],
    [48, 6], [49, 12], [48, 20], [49, 28], [48, 34], [49, 38],
    [5, 0], [12, 1], [20, 0], [30, 1], [38, 0], [44, 1],
    [6, 39], [14, 38], [22, 39], [32, 38], [40, 39], [46, 38],
    // Scattered boulders further in
    [3, 0], [0, 3], [49, 3], [46, 0],
    [0, 37], [3, 39], [46, 39], [49, 37],
  ];
  for (const [c, r] of rockPositions) {
    if (c >= 0 && c < COLS && r >= 0 && r < ROWS) {
      setTile(walls, c, r, GID.WALL);
    }
  }

  // Pond in bottom-left corner (water tiles)
  fillRect(ground, 0, 33, 3, 4, GID.WATER, true, 4);
  fillRect(ground, 1, 32, 2, 1, GID.WATER, true, 4);
  fillRect(ground, 0, 37, 2, 1, GID.WATER, true, 4);

  // Dirt paths leading to map edges (connecting to roads)
  // West path (connecting east-west road to left edge)
  fillRect(ground, 0, 18, 2, 3, GID.ROAD, true, 8);
  // East path
  fillRect(ground, COLS - 2, 18, 2, 3, GID.ROAD, true, 8);
  // North path
  fillRect(ground, 24, 0, 3, 2, GID.ROAD, true, 8);
  // South path
  fillRect(ground, 24, ROWS - 2, 3, 2, GID.ROAD, true, 8);

  // Extra trees at edges for natural feel
  const edgeTrees = [
    [0, 2], [1, 4], [0, 10], [1, 14], [0, 20], [1, 26],
    [48, 2], [49, 4], [48, 10], [49, 14], [48, 25], [49, 30],
    [4, 0], [8, 1], [15, 0], [35, 1], [42, 0], [48, 1],
    [4, 39], [10, 38], [18, 39], [36, 38], [44, 39],
  ];
  for (const [c, r] of edgeTrees) {
    const g = getTile(ground, c, r);
    if (g && g !== GID.WATER && g !== GID.ROAD) {
      setTile(walls, c, r, GID.TREE_TRUNK);
      setTile(wallTops, c, r, GID.TREE_CANOPY);
    }
  }

  // Main roads (3 tiles wide)
  // East-West road
  fillRect(ground, 2, 18, COLS - 4, 3, GID.ROAD, true, 8);
  // North-South road
  fillRect(ground, 24, 2, 3, ROWS - 4, GID.ROAD, true, 8);

  // Road edging (stone)
  for (let c = 2; c < COLS - 2; c++) {
    resetSeed(c * 11 + 17);
    setTile(groundDecor, c, 17, vary(GID.STONE, 8));
    resetSeed(c * 11 + 21);
    setTile(groundDecor, c, 21, vary(GID.STONE, 8));
  }
  for (let r = 2; r < ROWS - 2; r++) {
    resetSeed(r * 13 + 23);
    setTile(groundDecor, 23, r, vary(GID.STONE, 8));
    resetSeed(r * 13 + 27);
    setTile(groundDecor, 27, r, vary(GID.STONE, 8));
  }

  // ── Building helper ──
  function buildBuilding(bounds, floorGid, opts = {}) {
    const { x, y, w, h } = bounds;
    const wallThick = 1;
    const wallGid = opts.wallGid || GID.WALL;
    const doorGid = opts.doorGid || GID.DOOR;

    // Floor
    fillRect(ground, x, y, w, h, GID.INT_FLOOR, true, 4);
    fillRect(ground, x + wallThick, y + wallThick, w - wallThick * 2, h - wallThick * 2, floorGid, true);

    // Walls on all edges (building-specific)
    strokeRect(walls, x, y, w, h, wallGid);
    // WallTops for roof occlusion
    fillRect(wallTops, x, y, w, h, GID.WALL_PARAPET);

    // Door (building-specific)
    const doorOff = opts.doorOffset || Math.floor(w / 2);
    const doorW = 2;
    if (opts.doorSide === 'bottom') {
      for (let dc = 0; dc < doorW; dc++) {
        setTile(walls, x + doorOff + dc, y + h - 1, doorGid);
        setTile(wallTops, x + doorOff + dc, y + h - 1, GID.EMPTY);
        setTile(wallTops, x + doorOff + dc, y + h - 2, GID.EMPTY);
      }
    } else if (opts.doorSide === 'top') {
      for (let dc = 0; dc < doorW; dc++) {
        setTile(walls, x + doorOff + dc, y, doorGid);
        setTile(wallTops, x + doorOff + dc, y, GID.EMPTY);
        setTile(wallTops, x + doorOff + dc, y + 1, GID.EMPTY);
      }
    }

    // Pillars
    if (opts.pillars) {
      const sp = opts.pillarSpacing || 3;
      const entranceRow = opts.doorSide === 'bottom' ? y + h - 1 : y;
      for (let c = x + 1; c < x + w - 1; c += sp) {
        const inDoor = c >= x + doorOff && c < x + doorOff + doorW;
        if (!inDoor) setTile(walls, c, entranceRow, GID.COLUMN);
      }
    }

    // Interior
    if (opts.interior) {
      const ix = x + wallThick;
      const iy = y + wallThick;
      const iw = w - wallThick * 2;
      const ih = h - wallThick * 2;
      if (iw > 0 && ih > 0) opts.interior(ix, iy, iw, ih);
    }
  }

  // ── THE FORUM (center plaza) ──
  const forum = { x: 16, y: 12, w: 18, h: 14 };
  fillRect(ground, forum.x, forum.y, forum.w, forum.h, GID.MARBLE, true);

  // Forum border columns
  for (let c = forum.x; c < forum.x + forum.w; c += 3) {
    setTile(walls, c, forum.y, GID.COLUMN);
    setTile(walls, c, forum.y + forum.h - 1, GID.COLUMN);
  }
  for (let r = forum.y; r < forum.y + forum.h; r += 3) {
    setTile(walls, forum.x, r, GID.COLUMN);
    setTile(walls, forum.x + forum.w - 1, r, GID.COLUMN);
  }

  // Fountain (single centered tile in forum)
  setTile(walls, 25, 19, GID.FOUNTAIN);

  // Forum banners
  setTile(walls, 19, 13, GID.BANNER);
  setTile(walls, 31, 13, GID.BANNER);
  setTile(walls, 19, 24, GID.BANNER);
  setTile(walls, 31, 24, GID.BANNER);

  // Stone paths in forum — converging on fountain at (25,19)
  fillRect(groundDecor, 24, 13, 2, 6, GID.STONE, true);  // north path
  fillRect(groundDecor, 24, 20, 2, 5, GID.STONE, true);  // south path
  fillRect(groundDecor, 18, 18, 7, 2, GID.STONE, true);  // west path
  fillRect(groundDecor, 26, 18, 6, 2, GID.STONE, true);  // east path

  // Forum interior columns
  setTile(walls, 20, 15, GID.COLUMN);
  setTile(walls, 30, 15, GID.COLUMN);
  setTile(walls, 20, 23, GID.COLUMN);
  setTile(walls, 30, 23, GID.COLUMN);

  // ── THE CURIA (top-left) ──
  buildBuilding({ x: 3, y: 3, w: 12, h: 10 }, GID.MARBLE, {
    wallGid: GID.CURIA_WALL, doorGid: GID.CURIA_DOOR,
    doorSide: 'bottom', doorOffset: 5, pillars: true, pillarSpacing: 3,
    interior: (ix, iy, iw, ih) => {
      setTile(walls, ix + 1, iy + 1, GID.PILLAR);
      setTile(walls, ix + iw - 2, iy + 1, GID.PILLAR);
      setTile(walls, ix + Math.floor(iw / 2), iy, GID.BANNER);
    },
  });

  // ── BASILICA JULIA (top-right) ──
  buildBuilding({ x: 35, y: 3, w: 12, h: 10 }, GID.MARBLE, {
    wallGid: GID.BASILICA_WALL, doorGid: GID.BASILICA_DOOR,
    doorSide: 'bottom', doorOffset: 5, pillars: true, pillarSpacing: 3,
    interior: (ix, iy, iw, ih) => {
      for (let r = iy + 1; r < iy + ih - 1; r += 2) {
        setTile(walls, ix + 1, r, GID.PILLAR);
        setTile(walls, ix + iw - 2, r, GID.PILLAR);
      }
      for (let c = ix + 1; c < ix + iw - 1; c += 2) {
        setTile(walls, c, iy, GID.BANNER);
      }
    },
  });

  // ── THE SUBURA (bottom-left) ──
  buildBuilding({ x: 3, y: 27, w: 14, h: 10 }, GID.STONE, {
    wallGid: GID.SUBURA_WALL, doorGid: GID.SUBURA_DOOR,
    doorSide: 'top', doorOffset: 6,
    interior: (ix, iy, iw, ih) => {
      for (let r = iy + 1; r < iy + ih - 1; r += 2) {
        fillRect(walls, ix + 1, r, Math.min(3, iw - 2), 1, GID.SHELF);
        if (iw > 6) fillRect(walls, ix + iw - 4, r, 3, 1, GID.SHELF);
      }
      fillRect(ground, ix + Math.floor(iw / 2) - 1, iy, 2, ih, GID.ROAD, true);
    },
  });

  // ── THE TABULARIUM (bottom-right) ──
  buildBuilding({ x: 33, y: 27, w: 14, h: 10 }, GID.STONE, {
    wallGid: GID.TABULARIUM_WALL, doorGid: GID.TABULARIUM_DOOR,
    doorSide: 'top', doorOffset: 6, pillars: true, pillarSpacing: 4,
    interior: (ix, iy, iw, ih) => {
      for (let r = iy; r < iy + ih; r++) {
        setTile(walls, ix, r, GID.SHELF);
        setTile(walls, ix + iw - 1, r, GID.SHELF);
      }
      setTile(walls, ix + Math.floor(iw / 2), iy, GID.BANNER);
    },
  });

  // ── Connecting paths ──
  fillRect(ground, 9, 13, 2, 5, GID.ROAD, true);
  fillRect(ground, 40, 13, 2, 5, GID.ROAD, true);
  fillRect(ground, 9, 21, 2, 6, GID.ROAD, true);
  fillRect(ground, 40, 21, 2, 6, GID.ROAD, true);

  // ── Trees ──
  const treePositions = [
    [5, 16], [7, 17], [10, 16], [13, 15],
    [38, 16], [42, 17], [45, 16], [47, 15],
    [5, 23], [8, 24], [12, 23], [14, 22],
    [38, 23], [43, 24], [46, 23], [47, 22],
    [20, 2], [28, 3], [32, 2], [22, 37],
    [28, 38], [32, 37], [3, 16], [3, 24],
    [47, 16], [47, 24],
  ];
  for (const [c, r] of treePositions) {
    const g = getTile(ground, c, r);
    if (g >= GID.GRASS && g < GID.GRASS + 8) {
      setTile(walls, c, r, GID.TREE_TRUNK);
      setTile(wallTops, c, r, GID.TREE_CANOPY);
    }
  }

  return { ground, groundDecor, walls, wallTops };
}

// ── Object layer data ──

const NPC_SPAWNS = [
  { name: 'Praetorian Guard', type: 'npc_spawn', col: 10, row: 19,
    properties: [
      { name: 'npcId', type: 'string', value: 'praetorian_guard' },
      { name: 'spriteKey', type: 'string', value: 'npc-guard' },
      { name: 'behavior', type: 'string', value: 'patrol' },
    ] },
  { name: 'Basilica Guard', type: 'npc_spawn', col: 41, row: 19,
    properties: [
      { name: 'npcId', type: 'string', value: 'basilica_guard' },
      { name: 'spriteKey', type: 'string', value: 'npc-guard' },
      { name: 'behavior', type: 'string', value: 'idle' },
    ] },
  { name: 'Marcus the Merchant', type: 'npc_spawn', col: 25, row: 15,
    properties: [
      { name: 'npcId', type: 'string', value: 'marcus_merchant' },
      { name: 'spriteKey', type: 'string', value: 'npc-merchant' },
      { name: 'behavior', type: 'string', value: 'wander' },
    ] },
  { name: 'Seneca the Scholar', type: 'npc_spawn', col: 25, row: 23,
    properties: [
      { name: 'npcId', type: 'string', value: 'seneca_scholar' },
      { name: 'spriteKey', type: 'string', value: 'npc-scholar' },
      { name: 'behavior', type: 'string', value: 'idle' },
    ] },
  { name: 'Market Vendor', type: 'npc_spawn', col: 10, row: 32,
    properties: [
      { name: 'npcId', type: 'string', value: 'market_vendor' },
      { name: 'spriteKey', type: 'string', value: 'npc-vendor' },
      { name: 'behavior', type: 'string', value: 'idle' },
    ] },
  { name: 'Archivist', type: 'npc_spawn', col: 40, row: 32,
    properties: [
      { name: 'npcId', type: 'string', value: 'archivist' },
      { name: 'spriteKey', type: 'string', value: 'npc-archivist' },
      { name: 'behavior', type: 'string', value: 'idle' },
    ] },
];

// District zones — defined in tile coords, converted to world bounding rects
const DISTRICT_ZONE_DEFS = [
  { name: 'The Forum', districtId: 'forum', col: 16, row: 12, w: 18, h: 14,
    desc: 'Central plaza \u2014 all roads lead here.', color: '#4E0B59' },
  { name: 'The Curia', districtId: 'curia', col: 3, row: 3, w: 12, h: 10,
    desc: 'Elite council chamber. STEEL+ Tempering Grade required.', color: '#B8860B', locked: 'STEEL' },
  { name: 'Basilica Julia', districtId: 'basilica_julia', col: 35, row: 3, w: 12, h: 10,
    desc: 'Hall of Scrolls \u2014 pin your strategies for all to see.', color: '#665D1E' },
  { name: 'The Subura', districtId: 'subura', col: 3, row: 27, w: 14, h: 10,
    desc: 'Public market square. New citizens begin here.', color: '#666666' },
  { name: 'The Tabularium', districtId: 'tabularium', col: 33, row: 27, w: 14, h: 10,
    desc: 'Imperial archives \u2014 research and historical data.', color: '#8B2500' },
];

const PARTICLE_DEFS = [
  { name: 'Fountain Mist', emitterId: 'fountain_mist', col: 25, row: 19 },
  { name: 'Forum Dust', emitterId: 'ambient_dust', col: 25, row: 19 },
];

const LIGHT_DEFS = [
  { name: 'Forum Torch NW', col: 17, row: 13, radius: 100, color: '#FFEEDD', intensity: 1.0 },
  { name: 'Forum Torch NE', col: 33, row: 13, radius: 100, color: '#FFEEDD', intensity: 1.0 },
  { name: 'Forum Torch SW', col: 17, row: 25, radius: 100, color: '#FFEEDD', intensity: 1.0 },
  { name: 'Forum Torch SE', col: 33, row: 25, radius: 100, color: '#FFEEDD', intensity: 1.0 },
  { name: 'Basilica Light', col: 41, row: 8, radius: 120, color: '#DDCC88', intensity: 0.8 },
];

// ── Build Tiled JSON ──

function buildTiledJSON(layers) {
  const { ground, groundDecor, walls, wallTops } = layers;

  // Player spawn at tile (22, 16) — near forum center
  const playerWorld = tileToWorld(22, 16);
  const playerSpawn = {
    name: 'Player Spawn', type: 'player_spawn',
    x: playerWorld.x, y: playerWorld.y, width: 0, height: 0, properties: [],
  };

  // Convert NPC spawns to world coords
  const npcObjects = NPC_SPAWNS.map(s => {
    const w = tileToWorld(s.col, s.row);
    return { name: s.name, type: s.type, x: w.x, y: w.y, width: 0, height: 0, properties: s.properties };
  });

  // Convert district zones to world bounding rects
  const zoneObjects = DISTRICT_ZONE_DEFS.map(z => {
    // Compute 4 corners of tile-space rect in world coords
    const topLeft = tileToWorld(z.col, z.row);
    const topRight = tileToWorld(z.col + z.w, z.row);
    const botLeft = tileToWorld(z.col, z.row + z.h);
    const botRight = tileToWorld(z.col + z.w, z.row + z.h);
    // Bounding rect
    const minX = Math.min(topLeft.x, topRight.x, botLeft.x, botRight.x);
    const minY = Math.min(topLeft.y, topRight.y, botLeft.y, botRight.y);
    const maxX = Math.max(topLeft.x, topRight.x, botLeft.x, botRight.x);
    const maxY = Math.max(topLeft.y, topRight.y, botLeft.y, botRight.y);

    const props = [
      { name: 'districtId', type: 'string', value: z.districtId },
      { name: 'desc', type: 'string', value: z.desc },
      { name: 'color', type: 'string', value: z.color },
      { name: 'labelColor', type: 'string', value: z.color },
    ];
    if (z.locked) props.push({ name: 'locked', type: 'string', value: z.locked });

    return { name: z.name, type: 'district', x: minX, y: minY,
      width: maxX - minX, height: maxY - minY, properties: props };
  });

  // Convert particles
  const particleObjects = PARTICLE_DEFS.map(p => {
    const w = tileToWorld(p.col, p.row);
    return { name: p.name, type: 'particle', x: w.x, y: w.y, width: 0, height: 0,
      properties: [{ name: 'emitterId', type: 'string', value: p.emitterId }] };
  });

  // Convert lights
  const lightObjects = LIGHT_DEFS.map(l => {
    const w = tileToWorld(l.col, l.row);
    return { name: l.name, type: 'light', x: w.x, y: w.y, width: 0, height: 0,
      properties: [
        { name: 'radius', type: 'int', value: l.radius },
        { name: 'color', type: 'string', value: l.color },
        { name: 'intensity', type: 'float', value: l.intensity },
      ] };
  });

  let nextObjId = 1;
  function addId(obj) {
    return { ...obj, id: nextObjId++, visible: true, rotation: 0,
      width: obj.width || 0, height: obj.height || 0 };
  }

  return {
    compressionlevel: -1,
    height: ROWS,
    width: COLS,
    tileheight: TH,
    tilewidth: TW,
    infinite: false,
    orientation: 'isometric',
    renderorder: 'right-down',
    tiledversion: '1.10.2',
    type: 'map',
    version: '1.10',
    nextlayerid: 9,
    nextobjectid: nextObjId + 50,

    tilesets: [
      {
        columns: 10,
        firstgid: 1,
        image: '../tilesets/terrain-iso.png',
        imageheight: 192,
        imagewidth: 640,
        margin: 0,
        name: 'terrain',
        spacing: 0,
        tilecount: 60,
        tileheight: TH,
        tilewidth: TW,
        tiles: [
          // Water solid (GID 33-36 → ids 32-35)
          { id: 32, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 33, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 34, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 35, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Void solid (GID 37-40 → ids 36-39)
          { id: 36, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 37, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 38, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 39, properties: [{ name: 'solid', type: 'bool', value: true }] },
        ],
      },
      {
        columns: 10,
        firstgid: 61,
        image: '../tilesets/buildings-iso.png',
        imageheight: 192,
        imagewidth: 640,
        margin: 0,
        name: 'buildings',
        spacing: 0,
        tilecount: 40,
        tileheight: 48,
        tilewidth: TW,
        tiles: [
          // Wall cubes solid (GID 61-66 → ids 0-5)
          { id: 0, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 1, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 2, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 3, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 4, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 5, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Dark walls solid (GID 71-72 → ids 10-11)
          { id: 10, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 11, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Light walls solid (GID 73-74 → ids 12-13)
          { id: 12, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 13, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Shelves solid (GID 77-78 → ids 16-17)
          { id: 16, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 17, properties: [{ name: 'solid', type: 'bool', value: true }] },
        ],
      },
      {
        columns: 10,
        firstgid: 101,
        image: '../tilesets/decorations-iso.png',
        imageheight: 256,
        imagewidth: 640,
        margin: 0,
        name: 'decorations',
        spacing: 0,
        tilecount: 40,
        tileheight: 64,
        tilewidth: TW,
        tiles: [
          // Pillars solid (GID 101-102 → ids 0-1)
          { id: 0, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 1, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Columns solid (GID 103-104 → ids 2-3)
          { id: 2, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 3, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Tree trunks solid (GID 107-108 → ids 6-7)
          { id: 6, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 7, properties: [{ name: 'solid', type: 'bool', value: true }] },
          // Fountain solid (GID 109-110 → ids 8-9)
          { id: 8, properties: [{ name: 'solid', type: 'bool', value: true }] },
          { id: 9, properties: [{ name: 'solid', type: 'bool', value: true }] },
        ],
      },
    ],

    layers: [
      { id: 1, name: 'Ground', type: 'tilelayer', visible: true, opacity: 1, x: 0, y: 0,
        width: COLS, height: ROWS, data: ground.data },
      { id: 2, name: 'GroundDecor', type: 'tilelayer', visible: true, opacity: 1, x: 0, y: 0,
        width: COLS, height: ROWS, data: groundDecor.data },
      { id: 3, name: 'Walls', type: 'tilelayer', visible: true, opacity: 1, x: 0, y: 0,
        width: COLS, height: ROWS, data: walls.data },
      { id: 4, name: 'WallTops', type: 'tilelayer', visible: true, opacity: 1, x: 0, y: 0,
        width: COLS, height: ROWS, data: wallTops.data },
      { id: 5, name: 'Spawns', type: 'objectgroup', visible: true, opacity: 1, x: 0, y: 0,
        draworder: 'topdown', objects: [addId(playerSpawn), ...npcObjects.map(addId)] },
      { id: 6, name: 'Zones', type: 'objectgroup', visible: true, opacity: 1, x: 0, y: 0,
        draworder: 'topdown', color: '#4E0B59', objects: zoneObjects.map(addId) },
      { id: 7, name: 'Particles', type: 'objectgroup', visible: true, opacity: 1, x: 0, y: 0,
        draworder: 'topdown', objects: particleObjects.map(addId) },
      { id: 8, name: 'Lights', type: 'objectgroup', visible: true, opacity: 1, x: 0, y: 0,
        draworder: 'topdown', objects: lightObjects.map(addId) },
    ],
  };
}

// ── Main ──

async function main() {
  console.log('Generating isometric Tiled map JSON...');

  const layers = generateMapData();
  const tiledJSON = buildTiledJSON(layers);

  await mkdir(dirname(OUT), { recursive: true });
  await writeFile(OUT, JSON.stringify(tiledJSON, null, 2));

  console.log(`  Written to: ${OUT}`);
  console.log(`  Size: ${COLS}x${ROWS} tiles, orientation: isometric`);
  console.log(`  Tile: ${TW}x${TH}px`);
  console.log(`  Tile layers: Ground, GroundDecor, Walls, WallTops`);
  console.log(`  Object layers: Spawns (${NPC_SPAWNS.length + 1}), Zones (${DISTRICT_ZONE_DEFS.length}), Particles, Lights`);
}

main().catch(console.error);
