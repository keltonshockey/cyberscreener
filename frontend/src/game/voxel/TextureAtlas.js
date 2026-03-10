/**
 * QUAEST.TECH — Procedural Texture Atlas
 * Generates 16x16 pixel-art face textures at runtime using an offscreen canvas.
 * Packed into a 256x256 atlas. Uses NearestFilter for crispy pixel-art look.
 */

import * as THREE from 'three';

// Brand palette (matching generate-isometric-tileset.mjs)
const PAL = {
  // Warmed-up palette to match Roman Mediterranean art direction
  grass:     '#508B48',
  grassDark: '#3C7A36',
  dirt:      '#9B7848',
  dirtDark:  '#7B5828',
  stone:     '#787068',
  stoneDark: '#584E48',
  marble:    '#F0E4D0',
  marbleDark:'#D4C0A0',
  road:      '#B09878',
  roadDark:  '#907058',
  water:     '#4488CC',
  waterDark: '#336699',
  waterLight:'#6CB0EE',
  wall:      '#3D3832',
  wallDark:  '#2C2620',
  wallLight: '#5C5448',
  pillar:    '#D4B088',
  pillarDark:'#B49068',
  door:      '#8B5A2B',
  doorDark:  '#6B3A0B',
  trunk:     '#6B4423',
  trunkDark: '#4B2403',
  leaf:      '#2D6B2D',
  leafDark:  '#1D5B1D',
  leafLight: '#4D8B4D',
  banner:    '#5A1068',
  bannerDark:'#420050',
  gold:      '#E8C840',
  goldDark:  '#C8A830',
  shelf:     '#A88858',
  shelfDark: '#886838',
  bookRed:   '#8B2500',
  bookBlue:  '#2244AA',
  intFloor:  '#E0D4C0',
  intFloorDark: '#C0A890',
  parapet:   '#504840',
  fountain:  '#7799BB',
  fountainDark: '#557799',
  white:     '#F5F0E8',
  windowBlue:'#6688AA',
  // Building-specific (warmer tones)
  curiaMarble:     '#F0E4D0',
  curiaMarbleDark: '#D4C0A0',
  curiaMarbleLight:'#F8ECDC',
  travertine:      '#DCC8A0',
  travertineDark:  '#BCA880',
  terracotta:      '#C47838',
  roughStone:      '#8B8878',
  roughStoneDark:  '#6B6858',
  roughStoneLight: '#A8A490',
  granite:         '#706860',
  graniteDark:     '#504840',
  slate:           '#484040',
  woodBeam:        '#7A5A30',
};

const TEX_SIZE = 16; // each texture is 16x16 pixels
const ATLAS_COLS = 8;
const ATLAS_ROWS = 8;
const ATLAS_W = ATLAS_COLS * TEX_SIZE; // 128
const ATLAS_H = ATLAS_ROWS * TEX_SIZE; // 128

// Texture name → atlas position (col, row)
const TEX_MAP = {};
let _nextSlot = 0;

function assignSlot(name) {
  const col = _nextSlot % ATLAS_COLS;
  const row = Math.floor(_nextSlot / ATLAS_COLS);
  TEX_MAP[name] = { col, row };
  _nextSlot++;
  return { col, row };
}

// Pre-assign all texture slots
const TEX_NAMES = [
  'grass_top', 'grass_side',
  'stone_top', 'stone_side',
  'marble_top', 'marble_side',
  'road_top', 'road_side',
  'water_top', 'water_side',
  'int_floor_top',
  'wall_top', 'wall_side',
  'wall_dark_side', 'wall_light_side',
  'door_side',
  'shelf_top', 'shelf_side',
  'pillar_top', 'pillar_side',
  'column_top', 'column_side',
  'banner_top', 'banner_side',
  'trunk_top', 'trunk_side',
  'leaf_top', 'leaf_side',
  'fountain_top', 'fountain_side',
  'parapet_top',
  'window_side',
  // Building-specific textures
  'curia_wall_side', 'curia_wall_top',
  'basilica_wall_side', 'basilica_wall_top',
  'subura_wall_side', 'subura_wall_top',
  'tabularium_wall_side', 'tabularium_wall_top',
  'pediment_side',
  'arch_side',
  // Roof-specific textures
  'terracotta_top', 'terracotta_side',
  'slate_top', 'slate_side',
  'thatch_top', 'thatch_side',
  'tile_roof_top', 'tile_roof_side',
];

for (const name of TEX_NAMES) {
  assignSlot(name);
}

// Simple seeded random for texture detail
let _seed = 42;
function srand(s) { _seed = s; }
function rand() { _seed = (_seed * 16807 + 1) % 2147483647; return (_seed & 0x7fff) / 0x7fff; }

/**
 * Draw a 16x16 texture at the given atlas slot.
 */
function drawTex(ctx, name, fn) {
  const slot = TEX_MAP[name];
  if (!slot) return;
  const ox = slot.col * TEX_SIZE;
  const oy = slot.row * TEX_SIZE;
  ctx.save();
  ctx.translate(ox, oy);
  ctx.beginPath();
  ctx.rect(0, 0, TEX_SIZE, TEX_SIZE);
  ctx.clip();
  fn(ctx);
  ctx.restore();
}

function fill(ctx, color) {
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, TEX_SIZE, TEX_SIZE);
}

function pixel(ctx, x, y, color) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, 1, 1);
}

function noise(ctx, baseColor, dotColor, density, seed) {
  fill(ctx, baseColor);
  srand(seed || 123);
  for (let i = 0; i < density; i++) {
    const x = Math.floor(rand() * TEX_SIZE);
    const y = Math.floor(rand() * TEX_SIZE);
    pixel(ctx, x, y, dotColor);
  }
}

function bricks(ctx, baseColor, mortarColor, brickH, offsetEvery) {
  fill(ctx, baseColor);
  ctx.fillStyle = mortarColor;
  for (let y = 0; y < TEX_SIZE; y += brickH) {
    ctx.fillRect(0, y, TEX_SIZE, 1); // horizontal mortar
    const off = (Math.floor(y / brickH) % offsetEvery === 0) ? 0 : Math.floor(TEX_SIZE / 2);
    ctx.fillRect(off, y, 1, brickH); // vertical mortar
    ctx.fillRect(off + Math.floor(TEX_SIZE / 2), y, 1, brickH);
  }
}

/**
 * Create the full texture atlas. Returns a THREE.Texture.
 */
export function createTextureAtlas() {
  const canvas = document.createElement('canvas');
  canvas.width = ATLAS_W;
  canvas.height = ATLAS_H;
  const ctx = canvas.getContext('2d');

  // Clear to black
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, ATLAS_W, ATLAS_H);

  // ── Grass ──
  drawTex(ctx, 'grass_top', (c) => {
    noise(c, PAL.grass, PAL.grassDark, 30, 1);
    // Specks of lighter green
    srand(42);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#5A9B5A');
    }
  });
  drawTex(ctx, 'grass_side', (c) => {
    // Top 4px green, bottom 12px dirt
    c.fillStyle = PAL.grass;
    c.fillRect(0, 0, 16, 4);
    c.fillStyle = PAL.dirt;
    c.fillRect(0, 4, 16, 12);
    // Dirt specks
    srand(7);
    for (let i = 0; i < 10; i++) {
      pixel(c, Math.floor(rand() * 16), 4 + Math.floor(rand() * 12), PAL.dirtDark);
    }
    // Grass blades hanging over
    srand(13);
    for (let i = 0; i < 5; i++) {
      pixel(c, Math.floor(rand() * 16), 4, PAL.grassDark);
    }
  });

  // ── Stone ──
  drawTex(ctx, 'stone_top', (c) => {
    bricks(c, PAL.stone, PAL.stoneDark, 4, 2);
  });
  drawTex(ctx, 'stone_side', (c) => {
    bricks(c, PAL.stone, PAL.stoneDark, 5, 2);
  });

  // ── Marble ──
  drawTex(ctx, 'marble_top', (c) => {
    fill(c, PAL.marble);
    // Subtle veins
    srand(55);
    for (let i = 0; i < 12; i++) {
      const x = Math.floor(rand() * 16);
      const y = Math.floor(rand() * 16);
      pixel(c, x, y, PAL.marbleDark);
    }
  });
  drawTex(ctx, 'marble_side', (c) => {
    fill(c, PAL.marbleDark);
    srand(66);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.marble);
    }
  });

  // ── Road ──
  drawTex(ctx, 'road_top', (c) => {
    noise(c, PAL.road, PAL.roadDark, 25, 33);
    // Cobble lines
    srand(88);
    for (let y = 0; y < 16; y += 4) {
      for (let x = 0; x < 16; x += 4) {
        pixel(c, x, y, PAL.roadDark);
      }
    }
  });
  drawTex(ctx, 'road_side', (c) => {
    fill(c, PAL.roadDark);
    srand(44);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.road);
    }
  });

  // ── Water ──
  drawTex(ctx, 'water_top', (c) => {
    fill(c, PAL.water);
    srand(99);
    for (let i = 0; i < 10; i++) {
      const x = Math.floor(rand() * 14) + 1;
      const y = Math.floor(rand() * 14) + 1;
      pixel(c, x, y, PAL.waterLight);
      pixel(c, x + 1, y, PAL.waterLight);
    }
  });
  drawTex(ctx, 'water_side', (c) => {
    fill(c, PAL.waterDark);
  });

  // ── Interior Floor ──
  drawTex(ctx, 'int_floor_top', (c) => {
    // Checkerboard marble
    for (let y = 0; y < 16; y += 4) {
      for (let x = 0; x < 16; x += 4) {
        const light = ((x + y) / 4) % 2 === 0;
        c.fillStyle = light ? PAL.intFloor : PAL.intFloorDark;
        c.fillRect(x, y, 4, 4);
      }
    }
  });

  // ── Wall ──
  drawTex(ctx, 'wall_top', (c) => {
    fill(c, PAL.wallDark);
    srand(11);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.wall);
    }
  });
  drawTex(ctx, 'wall_side', (c) => {
    bricks(c, PAL.wall, PAL.wallDark, 4, 2);
  });
  drawTex(ctx, 'wall_dark_side', (c) => {
    bricks(c, PAL.wallDark, '#1A1A1A', 4, 2);
  });
  drawTex(ctx, 'wall_light_side', (c) => {
    bricks(c, PAL.wallLight, PAL.wall, 4, 2);
  });

  // ── Door ──
  drawTex(ctx, 'door_side', (c) => {
    fill(c, PAL.door);
    // Wood grain vertical lines
    for (let x = 0; x < 16; x += 3) {
      c.fillStyle = PAL.doorDark;
      c.fillRect(x, 0, 1, 16);
    }
    // Door frame top
    c.fillStyle = PAL.doorDark;
    c.fillRect(0, 0, 16, 2);
    // Handle
    pixel(c, 12, 8, PAL.gold);
    pixel(c, 12, 9, PAL.gold);
  });

  // ── Shelf ──
  drawTex(ctx, 'shelf_top', (c) => {
    fill(c, PAL.shelf);
    srand(77);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.shelfDark);
    }
  });
  drawTex(ctx, 'shelf_side', (c) => {
    // Bookshelf: shelves with colored books
    fill(c, PAL.shelfDark);
    srand(22);
    const bookColors = [PAL.bookRed, PAL.bookBlue, PAL.banner, PAL.gold, PAL.door];
    for (let shelfY = 1; shelfY < 16; shelfY += 5) {
      // Shelf plank
      c.fillStyle = PAL.shelf;
      c.fillRect(0, shelfY + 3, 16, 1);
      // Books
      for (let x = 1; x < 15; x += 2) {
        const color = bookColors[Math.floor(rand() * bookColors.length)];
        c.fillStyle = color;
        c.fillRect(x, shelfY, 1, 3);
      }
    }
  });

  // ── Pillar ──
  drawTex(ctx, 'pillar_top', (c) => {
    fill(c, PAL.pillarDark);
    // Circular cap
    c.fillStyle = PAL.pillar;
    c.fillRect(3, 3, 10, 10);
    c.fillRect(5, 1, 6, 14);
    c.fillRect(1, 5, 14, 6);
  });
  drawTex(ctx, 'pillar_side', (c) => {
    // Fluted column
    fill(c, PAL.pillar);
    // Fluting lines
    for (let x = 2; x < 16; x += 3) {
      c.fillStyle = PAL.pillarDark;
      c.fillRect(x, 0, 1, 16);
    }
    // Base and capital
    c.fillStyle = PAL.pillarDark;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
  });

  // ── Column ──
  drawTex(ctx, 'column_top', (c) => {
    fill(c, PAL.marbleDark);
    c.fillStyle = PAL.marble;
    c.fillRect(4, 4, 8, 8);
  });
  drawTex(ctx, 'column_side', (c) => {
    fill(c, PAL.marble);
    c.fillStyle = PAL.marbleDark;
    c.fillRect(0, 0, 16, 1);
    c.fillRect(0, 15, 16, 1);
    // Subtle fluting
    for (let x = 3; x < 16; x += 4) {
      c.fillRect(x, 1, 1, 14);
    }
  });

  // ── Banner ──
  drawTex(ctx, 'banner_top', (c) => {
    fill(c, PAL.banner);
    // Gold trim
    c.fillStyle = PAL.gold;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
  });
  drawTex(ctx, 'banner_side', (c) => {
    fill(c, PAL.banner);
    // Gold trim at edges
    c.fillStyle = PAL.gold;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
    c.fillRect(0, 0, 2, 16);
    c.fillRect(14, 0, 2, 16);
    // Center emblem (simple diamond)
    c.fillStyle = PAL.gold;
    pixel(c, 8, 6, PAL.gold);
    c.fillRect(7, 7, 3, 1);
    c.fillRect(6, 8, 5, 1);
    c.fillRect(7, 9, 3, 1);
    pixel(c, 8, 10, PAL.gold);
  });

  // ── Tree Trunk ──
  drawTex(ctx, 'trunk_top', (c) => {
    // Rings
    fill(c, PAL.trunk);
    c.fillStyle = PAL.trunkDark;
    c.fillRect(4, 4, 8, 8);
    c.fillStyle = PAL.trunk;
    c.fillRect(6, 6, 4, 4);
    c.fillStyle = PAL.trunkDark;
    c.fillRect(7, 7, 2, 2);
  });
  drawTex(ctx, 'trunk_side', (c) => {
    fill(c, PAL.trunk);
    // Bark texture
    srand(33);
    for (let i = 0; i < 15; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.trunkDark);
    }
    // Vertical lines
    for (let x = 3; x < 16; x += 5) {
      c.fillStyle = PAL.trunkDark;
      c.fillRect(x, 0, 1, 16);
    }
  });

  // ── Leaf / Tree Canopy ──
  drawTex(ctx, 'leaf_top', (c) => {
    noise(c, PAL.leaf, PAL.leafLight, 25, 77);
    srand(88);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.leafDark);
    }
  });
  drawTex(ctx, 'leaf_side', (c) => {
    noise(c, PAL.leaf, PAL.leafDark, 20, 55);
    srand(66);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.leafLight);
    }
  });

  // ── Fountain ──
  drawTex(ctx, 'fountain_top', (c) => {
    fill(c, PAL.fountain);
    // Water center
    c.fillStyle = PAL.water;
    c.fillRect(3, 3, 10, 10);
    // Sparkles
    pixel(c, 6, 6, PAL.waterLight);
    pixel(c, 9, 8, PAL.waterLight);
    pixel(c, 7, 10, PAL.waterLight);
    // Stone rim
    c.fillStyle = PAL.stone;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
    c.fillRect(0, 0, 2, 16);
    c.fillRect(14, 0, 2, 16);
  });
  drawTex(ctx, 'fountain_side', (c) => {
    fill(c, PAL.stone);
    // Ornate pattern
    srand(44);
    for (let x = 2; x < 14; x += 3) {
      c.fillStyle = PAL.stoneDark;
      c.fillRect(x, 4, 2, 8);
    }
    c.fillStyle = PAL.stoneDark;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
  });

  // ── Parapet ──
  drawTex(ctx, 'parapet_top', (c) => {
    fill(c, PAL.parapet);
    // Crenellation pattern
    for (let x = 0; x < 16; x += 6) {
      c.fillStyle = PAL.wallDark;
      c.fillRect(x, 0, 3, 4);
    }
    srand(22);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.wallLight);
    }
  });

  // ── Window ──
  drawTex(ctx, 'window_side', (c) => {
    bricks(c, PAL.wall, PAL.wallDark, 4, 2);
    // Window opening
    c.fillStyle = PAL.windowBlue;
    c.fillRect(4, 3, 8, 8);
    // Window frame
    c.fillStyle = PAL.wallDark;
    c.fillRect(4, 3, 8, 1);
    c.fillRect(4, 10, 8, 1);
    c.fillRect(4, 3, 1, 8);
    c.fillRect(11, 3, 1, 8);
    // Cross bar
    c.fillRect(4, 7, 8, 1);
    c.fillRect(7, 3, 1, 8);
  });

  // ── Curia walls (white marble, large ashlar blocks) ──
  drawTex(ctx, 'curia_wall_side', (c) => {
    fill(c, PAL.curiaMarble);
    // Large ashlar block pattern
    c.fillStyle = PAL.curiaMarbleDark;
    for (let y = 0; y < 16; y += 5) {
      c.fillRect(0, y, 16, 1);
      const off = (Math.floor(y / 5) % 2 === 0) ? 0 : 5;
      c.fillRect(off, y, 1, 5);
      c.fillRect(off + 8, y, 1, 5);
    }
    // Subtle marble veins
    srand(201);
    for (let i = 0; i < 6; i++) {
      const x = Math.floor(rand() * 14) + 1;
      const y = Math.floor(rand() * 14) + 1;
      pixel(c, x, y, PAL.curiaMarbleDark);
      pixel(c, x + 1, y, PAL.curiaMarbleDark);
    }
  });
  drawTex(ctx, 'curia_wall_top', (c) => {
    fill(c, PAL.curiaMarbleLight);
    srand(202);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.curiaMarbleDark);
    }
  });

  // ── Basilica walls (cream travertine, horizontal band courses) ──
  drawTex(ctx, 'basilica_wall_side', (c) => {
    fill(c, PAL.travertine);
    // Horizontal band courses
    c.fillStyle = PAL.travertineDark;
    for (let y = 0; y < 16; y += 4) {
      c.fillRect(0, y, 16, 1);
    }
    // Vertical block seams offset
    for (let y = 0; y < 16; y += 4) {
      const off = (Math.floor(y / 4) % 2 === 0) ? 0 : 4;
      c.fillRect(off, y, 1, 4);
      c.fillRect(off + 8, y, 1, 4);
    }
    // Warm stone speckle
    srand(203);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#C4B490');
    }
  });
  drawTex(ctx, 'basilica_wall_top', (c) => {
    fill(c, PAL.terracotta);
    srand(204);
    for (let i = 0; i < 10; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#A06323');
    }
    // Tile pattern
    c.fillStyle = '#A06323';
    for (let y = 0; y < 16; y += 4) {
      c.fillRect(0, y, 16, 1);
    }
  });

  // ── Subura walls (rough grey stone, irregular mortar) ──
  drawTex(ctx, 'subura_wall_side', (c) => {
    fill(c, PAL.roughStone);
    // Irregular block pattern
    c.fillStyle = PAL.roughStoneDark;
    for (let y = 0; y < 16; y += 3) {
      c.fillRect(0, y, 16, 1);
      const off = Math.floor(y * 1.7) % 7;
      c.fillRect(off, y, 1, 3);
      c.fillRect((off + 5) % 16, y, 1, 3);
      c.fillRect((off + 11) % 16, y, 1, 3);
    }
    // Wood beam accents
    c.fillStyle = PAL.woodBeam;
    c.fillRect(0, 7, 16, 2);
    // Rough texture noise
    srand(205);
    for (let i = 0; i < 12; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.roughStoneDark);
    }
    srand(206);
    for (let i = 0; i < 4; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.roughStoneLight);
    }
  });
  drawTex(ctx, 'subura_wall_top', (c) => {
    // Mixed stone and wood roof
    fill(c, '#686050');
    c.fillStyle = PAL.woodBeam;
    for (let x = 0; x < 16; x += 4) {
      c.fillRect(x, 0, 2, 16);
    }
    srand(207);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#585040');
    }
  });

  // ── Tabularium walls (dark granite, precise ashlar) ──
  drawTex(ctx, 'tabularium_wall_side', (c) => {
    fill(c, PAL.granite);
    // Precise ashlar blocks (large, clean-cut)
    c.fillStyle = PAL.graniteDark;
    for (let y = 0; y < 16; y += 4) {
      c.fillRect(0, y, 16, 1);
      const off = (Math.floor(y / 4) % 2 === 0) ? 0 : 5;
      c.fillRect(off, y, 1, 4);
      c.fillRect(off + 8, y, 1, 4);
    }
    // Doric-style horizontal band at top and bottom
    c.fillStyle = PAL.graniteDark;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
    // Slight highlight
    srand(208);
    for (let i = 0; i < 4; i++) {
      pixel(c, Math.floor(rand() * 16), 2 + Math.floor(rand() * 12), '#808080');
    }
  });
  drawTex(ctx, 'tabularium_wall_top', (c) => {
    fill(c, PAL.slate);
    srand(209);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.graniteDark);
    }
  });

  // ── Pediment (triangular gable element) ──
  drawTex(ctx, 'pediment_side', (c) => {
    fill(c, PAL.curiaMarble);
    // Shadow gradient (darker at bottom)
    c.fillStyle = PAL.curiaMarbleDark;
    c.fillRect(0, 10, 16, 6);
    // Cornice line
    c.fillStyle = PAL.curiaMarbleDark;
    c.fillRect(0, 0, 16, 2);
    c.fillRect(0, 14, 16, 2);
    // Center decorative relief
    srand(210);
    for (let i = 0; i < 5; i++) {
      pixel(c, 5 + Math.floor(rand() * 6), 4 + Math.floor(rand() * 6), PAL.curiaMarbleDark);
    }
  });

  // ── Arch (arched opening) ──
  drawTex(ctx, 'arch_side', (c) => {
    fill(c, PAL.granite);
    // Arch opening (dark semicircle area)
    c.fillStyle = '#1A1A2A';
    c.fillRect(3, 4, 10, 12);
    // Arch curve (simplified as stepped)
    c.fillRect(4, 3, 8, 1);
    c.fillRect(5, 2, 6, 1);
    c.fillRect(6, 1, 4, 1);
    // Keystone at top
    c.fillStyle = PAL.graniteDark;
    c.fillRect(7, 0, 2, 2);
    // Pilaster sides
    c.fillStyle = PAL.granite;
    c.fillRect(0, 0, 3, 16);
    c.fillRect(13, 0, 3, 16);
    c.fillStyle = PAL.graniteDark;
    c.fillRect(2, 0, 1, 16);
    c.fillRect(13, 0, 1, 16);
  });

  // ── Terracotta (Roman clay tile roofing) ──
  drawTex(ctx, 'terracotta_top', (c) => {
    fill(c, PAL.terracotta);
    // Tile ridges running horizontally
    c.fillStyle = '#A06323';
    for (let y = 0; y < 16; y += 3) {
      c.fillRect(0, y, 16, 1);
    }
    // Subtle variation
    srand(301);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#C88040');
    }
  });
  drawTex(ctx, 'terracotta_side', (c) => {
    fill(c, PAL.terracotta);
    // Overlapping tile pattern (imbrex and tegula)
    c.fillStyle = '#A06323';
    for (let y = 0; y < 16; y += 4) {
      c.fillRect(0, y, 16, 1);
      // Alternating curved ridges
      const off = (Math.floor(y / 4) % 2 === 0) ? 0 : 4;
      for (let x = off; x < 16; x += 8) {
        c.fillRect(x + 2, y + 1, 2, 3);
      }
    }
    srand(302);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#9B5520');
    }
  });

  // ── Slate (dark stone roofing for Tabularium) ──
  drawTex(ctx, 'slate_top', (c) => {
    fill(c, PAL.slate);
    srand(303);
    for (let i = 0; i < 10; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), PAL.graniteDark);
    }
    // Overlapping shingle lines
    c.fillStyle = '#3A3A3A';
    for (let y = 0; y < 16; y += 4) {
      c.fillRect(0, y, 16, 1);
    }
  });
  drawTex(ctx, 'slate_side', (c) => {
    fill(c, PAL.slate);
    // Layered slate shingle pattern
    c.fillStyle = PAL.graniteDark;
    for (let y = 0; y < 16; y += 3) {
      c.fillRect(0, y, 16, 1);
      const off = (Math.floor(y / 3) % 2 === 0) ? 0 : 3;
      c.fillRect(off, y, 1, 3);
      c.fillRect(off + 6, y, 1, 3);
      c.fillRect(off + 12, y, 1, 3);
    }
  });

  // ── Thatch (rough organic roofing for Subura) ──
  drawTex(ctx, 'thatch_top', (c) => {
    fill(c, '#8B7B55');
    // Straw-like parallel lines
    c.fillStyle = '#7B6B45';
    for (let y = 0; y < 16; y += 2) {
      c.fillRect(0, y, 16, 1);
    }
    srand(304);
    for (let i = 0; i < 12; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#9B8B65');
    }
    srand(305);
    for (let i = 0; i < 4; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#6B5B35');
    }
  });
  drawTex(ctx, 'thatch_side', (c) => {
    fill(c, '#8B7B55');
    c.fillStyle = '#7B6B45';
    for (let x = 0; x < 16; x += 2) {
      c.fillRect(x, 0, 1, 16);
    }
    srand(306);
    for (let i = 0; i < 8; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#6B5B35');
    }
  });

  // ── Clay tile roof (warm red-brown for Basilica nave) ──
  drawTex(ctx, 'tile_roof_top', (c) => {
    fill(c, '#B06030');
    // Tile rows
    c.fillStyle = '#904020';
    for (let y = 0; y < 16; y += 4) {
      c.fillRect(0, y, 16, 1);
      const off = (Math.floor(y / 4) % 2 === 0) ? 0 : 3;
      c.fillRect(off, y + 1, 1, 3);
      c.fillRect(off + 6, y + 1, 1, 3);
      c.fillRect(off + 12, y + 1, 1, 3);
    }
    srand(307);
    for (let i = 0; i < 6; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#C07040');
    }
  });
  drawTex(ctx, 'tile_roof_side', (c) => {
    fill(c, '#B06030');
    c.fillStyle = '#904020';
    for (let y = 0; y < 16; y += 3) {
      c.fillRect(0, y, 16, 1);
    }
    // Ridge highlights
    srand(308);
    for (let i = 0; i < 5; i++) {
      pixel(c, Math.floor(rand() * 16), Math.floor(rand() * 16), '#C88050');
    }
  });

  // Create Three.js texture
  const texture = new THREE.CanvasTexture(canvas);
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.colorSpace = THREE.SRGBColorSpace;

  return { texture, texMap: TEX_MAP, atlasW: ATLAS_W, atlasH: ATLAS_H, texSize: TEX_SIZE };
}

/**
 * Get UV coordinates for a texture name.
 * Returns [u0, v0, u1, v1] in 0-1 range.
 */
export function getTexUV(atlas, texName) {
  const slot = atlas.texMap[texName];
  if (!slot) return [0, 0, 0, 0]; // fallback
  const u0 = (slot.col * atlas.texSize) / atlas.atlasW;
  const v0 = 1 - ((slot.row + 1) * atlas.texSize) / atlas.atlasH; // flip Y for WebGL
  const u1 = ((slot.col + 1) * atlas.texSize) / atlas.atlasW;
  const v1 = 1 - (slot.row * atlas.texSize) / atlas.atlasH;
  return [u0, v0, u1, v1];
}
