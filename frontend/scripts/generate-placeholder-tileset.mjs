/**
 * QUAEST.TECH — Placeholder Tileset Generator
 *
 * Generates tileset PNG files using sharp from raw pixel data.
 * These are placeholder assets — replace with real pixel art tilesets later.
 *
 * Usage: node scripts/generate-placeholder-tileset.mjs
 * Output: public/assets/tilesets/*.png, public/assets/sprites/*.png, public/assets/particles/*.png
 */

import sharp from 'sharp';
import { writeFile, mkdir } from 'fs/promises';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, '..', 'public', 'assets');

const T = 16; // tile size

// ── Color helpers ──

function rgba(r, g, b, a = 255) { return [r, g, b, a]; }
function hex(h) {
  return [(h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF, 255];
}

// ── Quaest.tech brand palette ──
const PAL = {
  void:         hex(0x111111),
  stone:        hex(0x6B6B6B),
  stoneDark:    hex(0x5A5A5A),
  stoneLight:   hex(0x7A7A7A),
  marble:       hex(0xE8E0D4),
  marbleDark:   hex(0xD0C8BC),
  marbleLight:  hex(0xF0EAE0),
  grass:        hex(0x4A8B4A),
  grassDark:    hex(0x3E7A3E),
  grassLight:   hex(0x5A9B5A),
  wall:         hex(0x3A3A3A),
  wallDark:     hex(0x2A2A2A),
  wallLight:    hex(0x4A4A4A),
  pillar:       hex(0xC9A87C),
  pillarDark:   hex(0xB89868),
  pillarLight:  hex(0xD9B88C),
  water:        hex(0x4488CC),
  waterDark:    hex(0x3377BB),
  waterLight:   hex(0x5599DD),
  road:         hex(0xA09070),
  roadDark:     hex(0x908060),
  roadLight:    hex(0xB0A080),
  door:         hex(0x8B5A2B),
  doorDark:     hex(0x7A4A1B),
  doorLight:    hex(0x9B6A3B),
  column:       hex(0xBBA888),
  columnDark:   hex(0xAA9878),
  columnLight:  hex(0xCCB898),
  tree:         hex(0x2D6B2D),
  treeDark:     hex(0x1D5B1D),
  treeLight:    hex(0x3D7B3D),
  trunk:        hex(0x6B4423),
  banner:       hex(0x4E0B59),
  bannerDark:   hex(0x3E0049),
  bannerLight:  hex(0x6E2B79),
  shelf:        hex(0x8B6914),
  shelfDark:    hex(0x7B5904),
  shelfLight:   hex(0x9B7924),
  gold:         hex(0xDDBB44),
  goldDim:      hex(0xAA8833),
  white:        hex(0xF2F2F2),
  silver:       hex(0xA6A6A6),
  red:          hex(0x8B2500),
  amber:        hex(0xB8860B),
  skin:         hex(0xE8C8A0),
  skinDark:     hex(0xD4A574),
  purple:       hex(0x4E0B59),
  purpleDark:   hex(0x3E0049),
  blue:         hex(0x336699),
  brown:        hex(0x665D1E),
  brownDark:    hex(0x553322),
  transparent:  rgba(0, 0, 0, 0),
};

// ── Pixel buffer drawing primitives ──

class PixelCanvas {
  constructor(w, h) {
    this.w = w;
    this.h = h;
    this.data = new Uint8Array(w * h * 4);
  }

  setPixel(x, y, [r, g, b, a]) {
    if (x < 0 || x >= this.w || y < 0 || y >= this.h) return;
    const i = (y * this.w + x) * 4;
    if (a < 255 && a > 0) {
      // Alpha blend
      const sa = a / 255;
      const da = 1 - sa;
      this.data[i]     = Math.round(r * sa + this.data[i] * da);
      this.data[i + 1] = Math.round(g * sa + this.data[i + 1] * da);
      this.data[i + 2] = Math.round(b * sa + this.data[i + 2] * da);
      this.data[i + 3] = Math.min(255, this.data[i + 3] + a);
    } else {
      this.data[i] = r;
      this.data[i + 1] = g;
      this.data[i + 2] = b;
      this.data[i + 3] = a;
    }
  }

  fillRect(x, y, w, h, color) {
    for (let py = y; py < y + h; py++)
      for (let px = x; px < x + w; px++)
        this.setPixel(px, py, color);
  }

  hLine(x, y, w, color) {
    for (let px = x; px < x + w; px++) this.setPixel(px, y, color);
  }

  vLine(x, y, h, color) {
    for (let py = y; py < y + h; py++) this.setPixel(x, py, color);
  }

  strokeRect(x, y, w, h, color) {
    this.hLine(x, y, w, color);
    this.hLine(x, y + h - 1, w, color);
    this.vLine(x, y, h, color);
    this.vLine(x + w - 1, y, h, color);
  }

  // Draw a tile at grid position (col, row) within the tileset atlas
  drawTileAt(col, row, drawFn) {
    const ox = col * T;
    const oy = row * T;
    drawFn(ox, oy);
  }

  async save(path) {
    await mkdir(dirname(path), { recursive: true });
    await sharp(Buffer.from(this.data), {
      raw: { width: this.w, height: this.h, channels: 4 },
    }).png().toFile(path);
  }
}

// ── Deterministic random ──
let _seed = 42;
function rand() {
  _seed = (_seed * 16807) % 2147483647;
  return (_seed & 0x7fffffff) / 0x7fffffff;
}
function resetSeed(s) { _seed = s; }

// ══════════════════════════════════════════════════════
// TERRAIN TILESET — 16 tiles wide, rows of tile types
// ══════════════════════════════════════════════════════
//
// Layout (16 columns × 8 rows = 128 tile slots):
// Row 0: grass variants (8) + stone variants (8)
// Row 1: marble variants (8) + road variants (8)
// Row 2: water variants (4) + water anim frames (4) + void (8)
// Row 3: reserved for future terrain
// Rows 4-7: reserved
//
// GIDs (1-indexed for Tiled): grass=1-8, stone=9-16, marble=17-24, road=25-32, water=33-36, void=41-48

function generateTerrain() {
  const canvas = new PixelCanvas(T * 16, T * 8);

  // Row 0: grass (cols 0-7) + stone (cols 8-15)
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.grass);
      resetSeed(c * 200 + 1);
      for (let i = 0; i < 6; i++) {
        const bx = Math.floor(rand() * 14) + 1;
        const by = Math.floor(rand() * 14) + 1;
        const shade = rand() > 0.5 ? PAL.grassLight : PAL.grassDark;
        canvas.setPixel(ox + bx, oy + by, shade);
        canvas.setPixel(ox + bx, oy + by + 1, shade);
      }
    });
  }
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c + 8, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.stone);
      // Mortar pattern
      canvas.hLine(ox, oy + 8, T, PAL.stoneDark);
      canvas.vLine(ox + 4 + (c % 4) * 2, oy, 8, PAL.stoneDark);
      canvas.vLine(ox + 12 - (c % 3), oy + 8, 8, PAL.stoneDark);
      resetSeed(c * 300 + 2);
      for (let i = 0; i < 3; i++) {
        canvas.setPixel(ox + Math.floor(rand() * 14) + 1, oy + Math.floor(rand() * 14) + 1,
          [...PAL.stoneLight.slice(0, 3), 80]);
      }
    });
  }

  // Row 1: marble (cols 0-7) + road (cols 8-15)
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.marble);
      // Veining
      canvas.setPixel(ox + 3 + (c % 5), oy + 2, PAL.marbleDark);
      canvas.setPixel(ox + 4 + (c % 5), oy + 3, PAL.marbleDark);
      canvas.setPixel(ox + 10 + (c % 3), oy + 6, PAL.marbleDark);
      canvas.setPixel(ox + 11 + (c % 3), oy + 7, PAL.marbleDark);
      // Border
      canvas.strokeRect(ox, oy, T, T, [...PAL.marbleDark.slice(0, 3), 100]);
    });
  }
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c + 8, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.road);
      // Cobblestone grid
      canvas.strokeRect(ox + 1, oy + 1, 6, 6, [...PAL.roadDark.slice(0, 3), 80]);
      canvas.strokeRect(ox + 8, oy + 1, 7, 6, [...PAL.roadDark.slice(0, 3), 80]);
      canvas.strokeRect(ox + 1, oy + 8, 7, 7, [...PAL.roadDark.slice(0, 3), 80]);
      canvas.strokeRect(ox + 9, oy + 8, 6, 7, [...PAL.roadDark.slice(0, 3), 80]);
    });
  }

  // Row 2: water (cols 0-3 base, 4-7 anim frames) + void (cols 8-15)
  for (let c = 0; c < 4; c++) {
    canvas.drawTileAt(c, 2, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.water);
      // Ripples
      canvas.hLine(ox + 2, oy + 5, 12, PAL.waterLight);
      canvas.hLine(ox + 4, oy + 10, 8, PAL.waterLight);
      // Sparkle
      canvas.setPixel(ox + 6 + c, oy + 3, PAL.white);
      canvas.setPixel(ox + 10 - c, oy + 8, PAL.white);
    });
  }
  // Water animation frames (shifted ripples)
  for (let c = 0; c < 4; c++) {
    canvas.drawTileAt(c + 4, 2, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.water);
      canvas.hLine(ox + 2 + c, oy + 5 + (c % 2), 12 - c, PAL.waterLight);
      canvas.hLine(ox + 4 - c, oy + 10 - (c % 2), 8 + c, PAL.waterLight);
      canvas.setPixel(ox + 6 + c * 2, oy + 3 + c, PAL.white);
    });
  }
  // Void tiles
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c + 8, 2, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.void);
    });
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// BUILDINGS TILESET — walls, doors, shelves, floors
// ══════════════════════════════════════════════════════
//
// Layout (16 × 4):
// Row 0: wall variants (8) + wall top variants (8)
// Row 1: door variants (4) + shelf variants (4) + interior floor (8)
// Row 2-3: reserved

function generateBuildings() {
  const canvas = new PixelCanvas(T * 16, T * 4);

  // Row 0: walls (cols 0-7) + wall tops (cols 8-15)
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.wall);
      // Block pattern
      canvas.strokeRect(ox, oy, T, T, PAL.wallDark);
      canvas.hLine(ox, oy + 5, T, PAL.wallDark);
      canvas.hLine(ox, oy + 11, T, PAL.wallDark);
      canvas.vLine(ox + 8 + (c % 4), oy, 5, PAL.wallDark);
      canvas.vLine(ox + 4 + (c % 3), oy + 5, 6, PAL.wallDark);
      canvas.vLine(ox + 12 - (c % 4), oy + 11, 5, PAL.wallDark);
      // Top highlight
      canvas.hLine(ox + 1, oy + 1, T - 2, [...PAL.wallLight.slice(0, 3), 40]);
    });
  }
  // Wall tops (for overlay layer)
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c + 8, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T / 2, PAL.wallDark);
      canvas.fillRect(ox, oy + T / 2, T, T / 2, PAL.transparent);
      canvas.hLine(ox, oy + T / 2 - 1, T, PAL.wallLight);
    });
  }

  // Row 1: doors (0-3) + shelves (4-7) + interior floors (8-15)
  for (let c = 0; c < 4; c++) {
    canvas.drawTileAt(c, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.door);
      canvas.strokeRect(ox + 2, oy, 12, T, PAL.doorDark);
      canvas.vLine(ox + 8, oy + 2, 12, [...PAL.doorLight.slice(0, 3), 80]);
      // Handle
      canvas.fillRect(ox + 10, oy + 8, 2, 2, PAL.gold);
    });
  }
  for (let c = 0; c < 4; c++) {
    canvas.drawTileAt(c + 4, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.shelf);
      canvas.hLine(ox, oy + 4, T, PAL.shelfDark);
      canvas.hLine(ox, oy + 10, T, PAL.shelfDark);
      // Items
      canvas.fillRect(ox + 2, oy + 1, 3, 3, PAL.shelfLight);
      canvas.fillRect(ox + 8, oy + 1, 4, 3, PAL.shelfLight);
      canvas.fillRect(ox + 3, oy + 5, 4, 5, PAL.shelfLight);
      canvas.fillRect(ox + 10, oy + 6, 3, 4, PAL.shelfLight);
    });
  }
  // Interior floor tiles (subtle marble variations)
  for (let c = 0; c < 8; c++) {
    canvas.drawTileAt(c + 8, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.marble);
      canvas.strokeRect(ox, oy, T, T, [...PAL.marbleDark.slice(0, 3), 60]);
    });
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// DECORATIONS TILESET — pillars, columns, banners, trees, fountain
// ══════════════════════════════════════════════════════
//
// Layout (16 × 4):
// Row 0: pillar (2) + column (2) + banner (2) + tree trunk (2) + fountain (4) + misc (4)
// Row 1: tree canopy variants (8) + wall parapet (8)  [for overlay layer]
// Row 2-3: reserved

function generateDecorations() {
  const canvas = new PixelCanvas(T * 16, T * 4);

  // Row 0 col 0-1: pillars
  for (let c = 0; c < 2; c++) {
    canvas.drawTileAt(c, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.transparent);
      // Base
      canvas.fillRect(ox + 3, oy + 12, 10, 4, PAL.pillarDark);
      // Shaft
      canvas.fillRect(ox + 5, oy + 2, 6, 10, PAL.pillar);
      // Capital
      canvas.fillRect(ox + 3, oy, 10, 3, PAL.pillarLight);
      // Fluting
      canvas.vLine(ox + 7, oy + 3, 9, [...PAL.pillarDark.slice(0, 3), 80]);
      canvas.vLine(ox + 9, oy + 3, 9, [...PAL.pillarDark.slice(0, 3), 80]);
    });
  }

  // Col 2-3: columns
  for (let c = 0; c < 2; c++) {
    canvas.drawTileAt(c + 2, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.transparent);
      canvas.fillRect(ox + 5, oy + 1, 6, 14, PAL.column);
      canvas.fillRect(ox + 4, oy, 8, 2, PAL.columnLight);
      canvas.fillRect(ox + 4, oy + 14, 8, 2, PAL.columnLight);
    });
  }

  // Col 4-5: banners
  for (let c = 0; c < 2; c++) {
    canvas.drawTileAt(c + 4, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.transparent);
      // Pole
      canvas.fillRect(ox + 7, oy, 2, T, PAL.silver);
      // Cloth
      canvas.fillRect(ox + 3, oy + 2, 10, 8, PAL.banner);
      // Gold detail
      canvas.hLine(ox + 5, oy + 4, 6, PAL.gold);
      canvas.hLine(ox + 5, oy + 6, 6, PAL.gold);
    });
  }

  // Col 6-7: tree trunks (bottom half — goes on Walls layer for collision)
  for (let c = 0; c < 2; c++) {
    canvas.drawTileAt(c + 6, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.transparent);
      // Trunk
      canvas.fillRect(ox + 6, oy, 4, T, PAL.trunk);
      // Root flare
      canvas.fillRect(ox + 5, oy + 12, 6, 4, PAL.trunk);
      // Bark texture
      canvas.setPixel(ox + 7, oy + 4, PAL.brownDark);
      canvas.setPixel(ox + 8, oy + 8, PAL.brownDark);
    });
  }

  // Col 8-11: fountain parts (center water, rim pieces)
  canvas.drawTileAt(8, 0, (ox, oy) => {
    canvas.fillRect(ox, oy, T, T, PAL.water);
    // Sparkles
    canvas.setPixel(ox + 4, oy + 4, PAL.white);
    canvas.setPixel(ox + 10, oy + 9, PAL.white);
    canvas.setPixel(ox + 7, oy + 12, PAL.white);
    canvas.hLine(ox + 3, oy + 6, 10, PAL.waterLight);
  });
  canvas.drawTileAt(9, 0, (ox, oy) => {
    // Stone rim
    canvas.fillRect(ox, oy, T, T, PAL.stone);
    canvas.strokeRect(ox, oy, T, T, PAL.stoneDark);
    canvas.fillRect(ox + 2, oy + 2, T - 4, T - 4, PAL.stoneLight);
  });

  // Col 12-15: reserved / misc decorations
  for (let c = 12; c < 16; c++) {
    canvas.drawTileAt(c, 0, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.transparent);
    });
  }

  // Row 1: tree canopies (overlay layer — render above player)
  for (let c = 0; c < 4; c++) {
    canvas.drawTileAt(c, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, T, PAL.transparent);
      // Canopy (circle-ish)
      for (let py = 0; py < T; py++) {
        for (let px = 0; px < T; px++) {
          const dx = px - 7.5, dy = py - 7.5;
          if (dx * dx + dy * dy < 42) {
            const shade = (dx + dy) < 0 ? PAL.treeLight : PAL.tree;
            canvas.setPixel(ox + px, oy + py, shade);
          }
        }
      }
      // Leaf detail
      resetSeed(c * 500);
      for (let i = 0; i < 5; i++) {
        const lx = Math.floor(rand() * 12) + 2;
        const ly = Math.floor(rand() * 12) + 2;
        canvas.setPixel(ox + lx, oy + ly, PAL.grassLight);
      }
    });
  }
  // Wall parapets (overlay)
  for (let c = 4; c < 8; c++) {
    canvas.drawTileAt(c, 1, (ox, oy) => {
      canvas.fillRect(ox, oy, T, 6, PAL.wallDark);
      canvas.fillRect(ox, oy + 6, T, T - 6, PAL.transparent);
      canvas.hLine(ox, oy + 5, T, PAL.wallLight);
      // Crenellation
      canvas.fillRect(ox + 2, oy, 3, 3, PAL.transparent);
      canvas.fillRect(ox + 9, oy, 3, 3, PAL.transparent);
    });
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// CHARACTER SPRITE SHEETS — 4 cols × 4 rows (64×64)
// Each row = direction: down, left, right, up
// Each col = animation frame: idle, step-L, idle2, step-R
// ══════════════════════════════════════════════════════

function generateCharacter(bodyColor, headColor, accentColor, name) {
  const canvas = new PixelCanvas(T * 4, T * 4);
  const dirs = ['down', 'left', 'right', 'up'];

  for (let row = 0; row < 4; row++) {
    for (let frame = 0; frame < 4; frame++) {
      const ox = frame * T;
      const oy = row * T;
      const dir = dirs[row];

      // Body
      canvas.fillRect(ox + 4, oy + 6, 8, 8, bodyColor);

      // Head
      canvas.fillRect(ox + 5, oy + 1, 6, 5, headColor);

      // Eyes
      if (dir === 'down') {
        canvas.setPixel(ox + 6, oy + 3, PAL.void);
        canvas.setPixel(ox + 9, oy + 3, PAL.void);
      } else if (dir === 'left') {
        canvas.setPixel(ox + 5, oy + 3, PAL.void);
      } else if (dir === 'right') {
        canvas.setPixel(ox + 10, oy + 3, PAL.void);
      }

      // Accent (collar/belt)
      canvas.hLine(ox + 4, oy + 6, 8, accentColor);

      // Arms
      if (dir === 'left') {
        canvas.fillRect(ox + 3, oy + 7, 1, 4, headColor);
      } else if (dir === 'right') {
        canvas.fillRect(ox + 12, oy + 7, 1, 4, headColor);
      } else {
        canvas.fillRect(ox + 3, oy + 7, 1, 4, headColor);
        canvas.fillRect(ox + 12, oy + 7, 1, 4, headColor);
      }

      // Feet (animated)
      const footColor = PAL.brownDark;
      if (frame === 0 || frame === 2) {
        // Standing
        canvas.fillRect(ox + 5, oy + 14, 3, 2, footColor);
        canvas.fillRect(ox + 9, oy + 14, 3, 2, footColor);
      } else if (frame === 1) {
        // Step left
        canvas.fillRect(ox + 4, oy + 14, 3, 2, footColor);
        canvas.fillRect(ox + 10, oy + 14, 3, 2, footColor);
      } else {
        // Step right
        canvas.fillRect(ox + 6, oy + 14, 3, 2, footColor);
        canvas.fillRect(ox + 8, oy + 14, 3, 2, footColor);
      }
    }
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// PARTICLE TEXTURES — tiny 4×4 sprites
// ══════════════════════════════════════════════════════

function generateParticle(color, pattern = 'dot') {
  const canvas = new PixelCanvas(4, 4);
  if (pattern === 'dot') {
    canvas.setPixel(1, 1, color);
    canvas.setPixel(2, 1, color);
    canvas.setPixel(1, 2, color);
    canvas.setPixel(2, 2, color);
  } else if (pattern === 'cross') {
    canvas.setPixel(1, 0, color);
    canvas.setPixel(0, 1, color);
    canvas.setPixel(1, 1, color);
    canvas.setPixel(2, 1, color);
    canvas.setPixel(1, 2, color);
  } else if (pattern === 'leaf') {
    canvas.setPixel(0, 1, color);
    canvas.setPixel(1, 0, color);
    canvas.setPixel(1, 1, color);
    canvas.setPixel(2, 1, color);
    canvas.setPixel(2, 2, color);
    canvas.setPixel(3, 3, color);
  }
  return canvas;
}

// ══════════════════════════════════════════════════════
// UI TEXTURES
// ══════════════════════════════════════════════════════

function generateInteractIcon() {
  const canvas = new PixelCanvas(16, 16);
  // Diamond shape
  for (let y = 0; y < 16; y++) {
    for (let x = 0; x < 16; x++) {
      const dx = Math.abs(x - 7.5), dy = Math.abs(y - 7.5);
      if (dx + dy < 7) {
        const inner = dx + dy < 5;
        canvas.setPixel(x, y, inner ? PAL.gold : PAL.goldDim);
      }
    }
  }
  return canvas;
}

// ══════════════════════════════════════════════════════
// MAIN
// ══════════════════════════════════════════════════════

async function main() {
  console.log('Generating placeholder tilesets...');

  // Tilesets
  const terrain = generateTerrain();
  await terrain.save(join(OUT, 'tilesets', 'terrain.png'));
  console.log('  terrain.png (256x128)');

  const buildings = generateBuildings();
  await buildings.save(join(OUT, 'tilesets', 'buildings.png'));
  console.log('  buildings.png (256x64)');

  const decorations = generateDecorations();
  await decorations.save(join(OUT, 'tilesets', 'decorations.png'));
  console.log('  decorations.png (256x64)');

  // Characters
  const characters = [
    { name: 'player',        body: PAL.purple,  head: PAL.skin,     accent: PAL.gold },
    { name: 'npc-guard',     body: PAL.red,     head: PAL.skinDark, accent: PAL.gold },
    { name: 'npc-merchant',  body: PAL.brown,   head: PAL.skin,     accent: PAL.amber },
    { name: 'npc-scholar',   body: PAL.blue,    head: PAL.skin,     accent: PAL.silver },
    { name: 'npc-archivist', body: PAL.blue,    head: PAL.skin,     accent: PAL.gold },
    { name: 'npc-vendor',    body: PAL.brown,   head: PAL.skinDark, accent: PAL.amber },
  ];

  for (const ch of characters) {
    const sprite = generateCharacter(ch.body, ch.head, ch.accent, ch.name);
    await sprite.save(join(OUT, 'sprites', `${ch.name}.png`));
    console.log(`  sprites/${ch.name}.png (64x64)`);
  }

  // Particles
  const particles = [
    { name: 'dust',    color: PAL.silver,    pattern: 'dot' },
    { name: 'sparkle', color: PAL.white,     pattern: 'cross' },
    { name: 'leaf',    color: PAL.grassLight, pattern: 'leaf' },
    { name: 'smoke',   color: PAL.silver,    pattern: 'dot' },
  ];

  for (const p of particles) {
    const tex = generateParticle(p.color, p.pattern);
    await tex.save(join(OUT, 'particles', `${p.name}.png`));
    console.log(`  particles/${p.name}.png (4x4)`);
  }

  // UI
  const icon = generateInteractIcon();
  await icon.save(join(OUT, 'ui', 'interact-icon.png'));
  console.log('  ui/interact-icon.png (16x16)');

  console.log('\nDone! Assets written to public/assets/');
}

main().catch(console.error);
