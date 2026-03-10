/**
 * QUAEST.TECH — Isometric Tileset Generator
 *
 * Generates isometric (diamond-shaped) tileset PNGs using sharp.
 * Tile dimensions: 64×32 ground, 64×48 buildings, 64×64 decorations.
 *
 * Usage: node scripts/generate-isometric-tileset.mjs
 * Output: public/assets/tilesets/terrain-iso.png, buildings-iso.png, decorations-iso.png
 */

import sharp from 'sharp';
import { mkdir } from 'fs/promises';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, '..', 'public', 'assets');

// ── Color helpers ──
function rgba(r, g, b, a = 255) { return [r, g, b, a]; }
function hex(h) { return [(h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF, 255]; }
function darken(c, amt = 30) { return [Math.max(0, c[0] - amt), Math.max(0, c[1] - amt), Math.max(0, c[2] - amt), c[3]]; }
function lighten(c, amt = 20) { return [Math.min(255, c[0] + amt), Math.min(255, c[1] + amt), Math.min(255, c[2] + amt), c[3]]; }

// ── Brand palette ──
const PAL = {
  void: hex(0x111111), stone: hex(0x6B6B6B), stoneDark: hex(0x5A5A5A), stoneLight: hex(0x7A7A7A),
  marble: hex(0xE8E0D4), marbleDark: hex(0xD0C8BC), marbleLight: hex(0xF0EAE0),
  grass: hex(0x4A8B4A), grassDark: hex(0x3E7A3E), grassLight: hex(0x5A9B5A),
  wall: hex(0x3A3A3A), wallDark: hex(0x2A2A2A), wallLight: hex(0x4A4A4A),
  pillar: hex(0xC9A87C), pillarDark: hex(0xB89868), pillarLight: hex(0xD9B88C),
  water: hex(0x4488CC), waterDark: hex(0x3377BB), waterLight: hex(0x5599DD),
  road: hex(0xA09070), roadDark: hex(0x908060), roadLight: hex(0xB0A080),
  door: hex(0x8B5A2B), doorDark: hex(0x7A4A1B), doorLight: hex(0x9B6A3B),
  column: hex(0xBBA888), columnDark: hex(0xAA9878), columnLight: hex(0xCCB898),
  tree: hex(0x2D6B2D), treeDark: hex(0x1D5B1D), treeLight: hex(0x3D7B3D),
  trunk: hex(0x6B4423), banner: hex(0x4E0B59), bannerDark: hex(0x3E0049), bannerLight: hex(0x6E2B79),
  shelf: hex(0x8B6914), shelfDark: hex(0x7B5904), shelfLight: hex(0x9B7924),
  gold: hex(0xDDBB44), goldDim: hex(0xAA8833), white: hex(0xF2F2F2), silver: hex(0xA6A6A6),
  red: hex(0x8B2500), amber: hex(0xB8860B), skin: hex(0xE8C8A0), skinDark: hex(0xD4A574),
  purple: hex(0x4E0B59), purpleDark: hex(0x3E0049), blue: hex(0x336699),
  brown: hex(0x665D1E), brownDark: hex(0x553322), transparent: rgba(0, 0, 0, 0),
  shadow: rgba(0, 0, 0, 80), intFloor: hex(0xD8D0C4),
};

// ── Deterministic random ──
let _seed = 42;
function rand() { _seed = (_seed * 16807) % 2147483647; return (_seed & 0x7fffffff) / 0x7fffffff; }
function resetSeed(s) { _seed = s; }

// ── PixelCanvas with isometric primitives ──
class PixelCanvas {
  constructor(w, h) { this.w = w; this.h = h; this.data = new Uint8Array(w * h * 4); }

  setPixel(x, y, [r, g, b, a]) {
    x = Math.round(x); y = Math.round(y);
    if (x < 0 || x >= this.w || y < 0 || y >= this.h) return;
    const i = (y * this.w + x) * 4;
    if (a < 255 && a > 0) {
      const sa = a / 255, da = 1 - sa;
      this.data[i] = Math.round(r * sa + this.data[i] * da);
      this.data[i+1] = Math.round(g * sa + this.data[i+1] * da);
      this.data[i+2] = Math.round(b * sa + this.data[i+2] * da);
      this.data[i+3] = Math.min(255, this.data[i+3] + a);
    } else {
      this.data[i] = r; this.data[i+1] = g; this.data[i+2] = b; this.data[i+3] = a;
    }
  }

  fillRect(x, y, w, h, color) {
    for (let py = y; py < y + h; py++)
      for (let px = x; px < x + w; px++)
        this.setPixel(px, py, color);
  }

  hLine(x, y, w, color) { for (let px = x; px < x + w; px++) this.setPixel(px, y, color); }
  vLine(x, y, h, color) { for (let py = y; py < y + h; py++) this.setPixel(x, py, color); }

  strokeRect(x, y, w, h, color) {
    this.hLine(x, y, w, color); this.hLine(x, y + h - 1, w, color);
    this.vLine(x, y, h, color); this.vLine(x + w - 1, y, h, color);
  }

  line(x0, y0, x1, y1, color) {
    let dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
    let sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;
    while (true) {
      this.setPixel(x0, y0, color);
      if (x0 === x1 && y0 === y1) break;
      let e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x0 += sx; }
      if (e2 < dx) { err += dx; y0 += sy; }
    }
  }

  // Fill a diamond (isometric tile top face) inscribed in bounding box at (ox,oy) with size tw×th
  fillDiamond(ox, oy, tw, th, color) {
    const cx = tw / 2, cy = th / 2;
    for (let py = 0; py < th; py++) {
      const ratio = py < cy ? py / cy : (th - 1 - py) / cy;
      const halfW = Math.floor(cx * ratio);
      const startX = Math.floor(cx - halfW);
      const endX = Math.ceil(cx + halfW);
      for (let px = startX; px <= endX; px++) {
        this.setPixel(ox + px, oy + py, color);
      }
    }
  }

  // Outline a diamond
  strokeDiamond(ox, oy, tw, th, color) {
    const mx = Math.floor(tw / 2), my = Math.floor(th / 2);
    this.line(ox + mx, oy, ox + tw - 1, oy + my, color);       // top → right
    this.line(ox + tw - 1, oy + my, ox + mx, oy + th - 1, color); // right → bottom
    this.line(ox + mx, oy + th - 1, ox, oy + my, color);       // bottom → left
    this.line(ox, oy + my, ox + mx, oy, color);                 // left → top
  }

  // Fill left face (parallelogram below diamond's left-bottom edge)
  fillLeftFace(ox, oy, tw, th, sideH, color) {
    const mx = Math.floor(tw / 2);
    const my = Math.floor(th / 2);
    // Left face: from bottom-center down-left to left-center down
    for (let row = 0; row < sideH; row++) {
      const y0 = oy + my + row;
      const y1 = oy + th - 1 + row;
      // line from (ox, y0) to (ox + mx, y1)
      for (let py = y0; py <= y1; py++) {
        const t = (py - y0) / Math.max(1, y1 - y0);
        const px = Math.round(ox + t * mx);
        this.setPixel(px, py, color);
      }
    }
    // Fill the area properly
    for (let row = 0; row < sideH; row++) {
      const topY = oy + my + row;
      const botY = oy + th - 1 + row;
      for (let py = topY; py <= botY; py++) {
        const tTop = my > 0 ? (py - topY) / Math.max(1, botY - topY) : 0;
        const xLeft = Math.round(ox + tTop * mx);
        const xRight = Math.round(ox + mx);
        for (let px = xLeft; px <= xRight; px++) {
          this.setPixel(px, py, color);
        }
      }
    }
  }

  // Fill right face (parallelogram below diamond's right-bottom edge)
  fillRightFace(ox, oy, tw, th, sideH, color) {
    const mx = Math.floor(tw / 2);
    const my = Math.floor(th / 2);
    for (let row = 0; row < sideH; row++) {
      const topY = oy + my + row;
      const botY = oy + th - 1 + row;
      for (let py = topY; py <= botY; py++) {
        const t = (py - topY) / Math.max(1, botY - topY);
        const xRight = Math.round(ox + tw - 1 - t * mx);
        const xLeft = Math.round(ox + mx);
        for (let px = xLeft; px <= xRight; px++) {
          this.setPixel(px, py, color);
        }
      }
    }
  }

  // Complete isometric cube: top diamond + left face + right face
  fillIsoCube(ox, oy, tw, th, sideH, topColor, leftColor, rightColor) {
    this.fillLeftFace(ox, oy, tw, th, sideH, leftColor);
    this.fillRightFace(ox, oy, tw, th, sideH, rightColor);
    this.fillDiamond(ox, oy, tw, th, topColor);
  }

  // Diamond with scattered noise pixels
  fillDiamondTextured(ox, oy, tw, th, baseColor, noiseColors, density, seed) {
    this.fillDiamond(ox, oy, tw, th, baseColor);
    resetSeed(seed);
    const cx = tw / 2, cy = th / 2;
    for (let py = 0; py < th; py++) {
      const ratio = py < cy ? py / cy : (th - 1 - py) / cy;
      const halfW = Math.floor(cx * ratio);
      const startX = Math.floor(cx - halfW);
      const endX = Math.ceil(cx + halfW);
      for (let px = startX; px <= endX; px++) {
        if (rand() < density) {
          const nc = noiseColors[Math.floor(rand() * noiseColors.length)];
          this.setPixel(ox + px, oy + py, nc);
        }
      }
    }
  }

  async save(path) {
    await mkdir(dirname(path), { recursive: true });
    await sharp(Buffer.from(this.data), {
      raw: { width: this.w, height: this.h, channels: 4 },
    }).png().toFile(path);
  }
}

// Tile dimensions
const TW = 64, TH = 32;   // ground tiles
const BH = 48;             // building tile height (16px side faces)
const DH = 64;             // decoration tile height (32px tall objects)
const SIDE_H = 16;         // wall side face height

// ══════════════════════════════════════════════════════
// TERRAIN TILESET — 10 cols × 6 rows of 64×32 tiles
// ══════════════════════════════════════════════════════
// Row 0: grass variants (8) + stone (2)
// Row 1: stone cont (6) + marble (4)
// Row 2: marble cont (4) + road (6)
// Row 3: road cont (2) + water (4) + void (4)
// Row 4: interior floor (4) + shadow (4) + reserved (2)
// Row 5: reserved

function generateTerrainIso() {
  const cols = 10, rows = 6;
  const canvas = new PixelCanvas(cols * TW, rows * TH);

  // Helper: draw tile at grid position
  const tile = (c, r, fn) => fn(c * TW, r * TH);

  // Row 0: 8 grass + 2 stone
  for (let c = 0; c < 8; c++) {
    tile(c, 0, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.grass,
        [PAL.grassDark, PAL.grassLight], 0.08, c * 100 + 1);
    });
  }
  for (let c = 0; c < 2; c++) {
    tile(c + 8, 0, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.stone,
        [PAL.stoneDark, PAL.stoneLight], 0.06, c * 200 + 50);
      canvas.strokeDiamond(ox, oy, TW, TH, PAL.stoneDark);
    });
  }

  // Row 1: 6 stone + 4 marble
  for (let c = 0; c < 6; c++) {
    tile(c, 1, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.stone,
        [PAL.stoneDark, PAL.stoneLight], 0.06, c * 200 + 100);
      canvas.strokeDiamond(ox, oy, TW, TH, PAL.stoneDark);
    });
  }
  for (let c = 0; c < 4; c++) {
    tile(c + 6, 1, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.marble,
        [PAL.marbleDark, PAL.marbleLight], 0.04, c * 300 + 1);
      canvas.strokeDiamond(ox, oy, TW, TH, [...PAL.marbleDark.slice(0, 3), 100]);
    });
  }

  // Row 2: 4 marble + 6 road
  for (let c = 0; c < 4; c++) {
    tile(c, 2, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.marble,
        [PAL.marbleDark, PAL.marbleLight], 0.04, c * 300 + 100);
      canvas.strokeDiamond(ox, oy, TW, TH, [...PAL.marbleDark.slice(0, 3), 100]);
    });
  }
  for (let c = 0; c < 6; c++) {
    tile(c + 4, 2, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.road,
        [PAL.roadDark, PAL.roadLight], 0.08, c * 400 + 1);
      canvas.strokeDiamond(ox, oy, TW, TH, [...PAL.roadDark.slice(0, 3), 80]);
    });
  }

  // Row 3: 2 road + 4 water + 4 void
  for (let c = 0; c < 2; c++) {
    tile(c, 3, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.road,
        [PAL.roadDark, PAL.roadLight], 0.08, c * 400 + 100);
    });
  }
  for (let c = 0; c < 4; c++) {
    tile(c + 2, 3, (ox, oy) => {
      canvas.fillDiamond(ox, oy, TW, TH, PAL.water);
      // Ripple highlights
      resetSeed(c * 500);
      for (let i = 0; i < 8; i++) {
        const rx = Math.floor(rand() * (TW - 8)) + 4;
        const ry = Math.floor(rand() * (TH - 4)) + 2;
        canvas.setPixel(ox + rx, oy + ry, PAL.waterLight);
        canvas.setPixel(ox + rx + 1, oy + ry, PAL.waterLight);
      }
    });
  }
  for (let c = 0; c < 4; c++) {
    tile(c + 6, 3, (ox, oy) => {
      canvas.fillDiamond(ox, oy, TW, TH, PAL.void);
    });
  }

  // Row 4: 4 interior floor + 4 shadow + 2 reserved
  for (let c = 0; c < 4; c++) {
    tile(c, 4, (ox, oy) => {
      canvas.fillDiamondTextured(ox, oy, TW, TH, PAL.intFloor,
        [PAL.marbleDark, PAL.marbleLight], 0.03, c * 600 + 1);
      canvas.strokeDiamond(ox, oy, TW, TH, [...PAL.marbleDark.slice(0, 3), 60]);
    });
  }
  for (let c = 0; c < 4; c++) {
    tile(c + 4, 4, (ox, oy) => {
      canvas.fillDiamond(ox, oy, TW, TH, PAL.shadow);
    });
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// BUILDINGS TILESET — 10 cols × 4 rows of 64×48 tiles
// ══════════════════════════════════════════════════════
// Row 0: wall cubes (6) + wall surface flat (4)
// Row 1: wall dark (2) + wall light (2) + door (2) + shelf (2) + window wall (2)
// Row 2: parapet (4) + reserved (6)
// Row 3: reserved

function generateBuildingsIso() {
  const cols = 10, rows = 4;
  const canvas = new PixelCanvas(cols * TW, rows * BH);

  const tile = (c, r, fn) => fn(c * TW, r * BH);

  // Row 0: 6 wall cubes + 4 wall surface (flat top)
  for (let c = 0; c < 6; c++) {
    tile(c, 0, (ox, oy) => {
      canvas.fillIsoCube(ox, oy, TW, TH, SIDE_H,
        PAL.wallLight, darken(PAL.wall, 15), darken(PAL.wall, 30));
      // Block pattern on left face
      resetSeed(c * 700);
      for (let i = 0; i < 4; i++) {
        const bx = ox + Math.floor(rand() * 30) + 2;
        const by = oy + TH / 2 + Math.floor(rand() * (SIDE_H - 2));
        canvas.setPixel(bx, by, PAL.wallDark);
      }
    });
  }
  for (let c = 0; c < 4; c++) {
    tile(c + 6, 0, (ox, oy) => {
      canvas.fillDiamond(ox, oy, TW, TH, PAL.wallLight);
      canvas.strokeDiamond(ox, oy, TW, TH, PAL.wallDark);
    });
  }

  // Row 1: 2 dark walls + 2 light walls + 2 doors + 2 shelves + 2 window walls
  for (let c = 0; c < 2; c++) {
    tile(c, 1, (ox, oy) => {
      canvas.fillIsoCube(ox, oy, TW, TH, SIDE_H,
        PAL.wallDark, darken(PAL.wallDark, 15), darken(PAL.wallDark, 25));
    });
  }
  for (let c = 0; c < 2; c++) {
    tile(c + 2, 1, (ox, oy) => {
      canvas.fillIsoCube(ox, oy, TW, TH, SIDE_H,
        PAL.stoneLight, PAL.stone, PAL.stoneDark);
    });
  }
  // Doors
  for (let c = 0; c < 2; c++) {
    tile(c + 4, 1, (ox, oy) => {
      canvas.fillIsoCube(ox, oy, TW, TH, SIDE_H,
        PAL.wallLight, darken(PAL.wall, 15), darken(PAL.wall, 30));
      // Door opening on right face
      const doorW = 12, doorH = 12;
      const dx = ox + TW / 2 + 4;
      const dy = oy + TH / 2 + SIDE_H - doorH;
      canvas.fillRect(dx, dy, doorW, doorH, PAL.door);
      canvas.fillRect(dx + 2, dy + 2, doorW - 4, doorH - 2, PAL.doorDark);
      // Handle
      canvas.setPixel(dx + doorW - 3, dy + doorH / 2, PAL.gold);
    });
  }
  // Shelves
  for (let c = 0; c < 2; c++) {
    tile(c + 6, 1, (ox, oy) => {
      canvas.fillIsoCube(ox, oy, TW, TH, SIDE_H,
        PAL.shelf, darken(PAL.shelf, 20), darken(PAL.shelf, 35));
      // Shelf lines on right face
      canvas.hLine(ox + TW / 2, oy + TH / 2 + 4, TW / 4, PAL.shelfDark);
      canvas.hLine(ox + TW / 2, oy + TH / 2 + 10, TW / 4, PAL.shelfDark);
    });
  }
  // Window walls
  for (let c = 0; c < 2; c++) {
    tile(c + 8, 1, (ox, oy) => {
      canvas.fillIsoCube(ox, oy, TW, TH, SIDE_H,
        PAL.wallLight, darken(PAL.wall, 15), darken(PAL.wall, 30));
      // Window on right face
      const wx = ox + TW / 2 + 6, wy = oy + TH / 2 + 2;
      canvas.fillRect(wx, wy, 8, 6, PAL.waterLight);
      canvas.strokeRect(wx, wy, 8, 6, PAL.wallDark);
    });
  }

  // Row 2: 4 parapet + reserved
  for (let c = 0; c < 4; c++) {
    tile(c, 2, (ox, oy) => {
      // Parapet: thin diamond top with crenellations
      canvas.fillDiamond(ox, oy, TW, TH, PAL.wallDark);
      canvas.strokeDiamond(ox, oy, TW, TH, PAL.wallLight);
      // Small gaps for crenellation effect
      canvas.fillRect(ox + 16, oy + 4, 4, 4, PAL.transparent);
      canvas.fillRect(ox + 44, oy + 4, 4, 4, PAL.transparent);
      canvas.fillRect(ox + 30, oy + 2, 4, 3, PAL.transparent);
    });
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// DECORATIONS TILESET — 10 cols × 4 rows of 64×64 tiles
// ══════════════════════════════════════════════════════
// Row 0: pillar (2) + column (2) + banner (2) + tree trunk (2) + fountain base (2)
// Row 1: tree canopy (4) + wall parapet overlay (4) + reserved (2)
// Row 2-3: reserved

function generateDecorationsIso() {
  const cols = 10, rows = 4;
  const canvas = new PixelCanvas(cols * TW, rows * DH);

  const tile = (c, r, fn) => fn(c * TW, r * DH);

  // Row 0: pillars
  for (let c = 0; c < 2; c++) {
    tile(c, 0, (ox, oy) => {
      // Small diamond base
      canvas.fillDiamond(ox + 16, oy + 40, 32, 16, PAL.pillarDark);
      // Shaft
      canvas.fillRect(ox + 24, oy + 10, 16, 38, PAL.pillar);
      // Capital
      canvas.fillRect(ox + 20, oy + 6, 24, 6, PAL.pillarLight);
      // Base
      canvas.fillRect(ox + 20, oy + 48, 24, 4, PAL.pillarDark);
      // Fluting
      canvas.vLine(ox + 28, oy + 12, 34, [...PAL.pillarDark.slice(0, 3), 80]);
      canvas.vLine(ox + 36, oy + 12, 34, [...PAL.pillarDark.slice(0, 3), 80]);
    });
  }

  // Columns
  for (let c = 0; c < 2; c++) {
    tile(c + 2, 0, (ox, oy) => {
      canvas.fillRect(ox + 26, oy + 8, 12, 48, PAL.column);
      canvas.fillRect(ox + 22, oy + 4, 20, 6, PAL.columnLight);
      canvas.fillRect(ox + 22, oy + 52, 20, 6, PAL.columnLight);
    });
  }

  // Banners
  for (let c = 0; c < 2; c++) {
    tile(c + 4, 0, (ox, oy) => {
      // Pole
      canvas.fillRect(ox + 30, oy + 2, 4, 58, PAL.silver);
      // Cloth
      canvas.fillRect(ox + 18, oy + 8, 28, 24, PAL.banner);
      // Gold detail
      canvas.hLine(ox + 22, oy + 14, 20, PAL.gold);
      canvas.hLine(ox + 22, oy + 22, 20, PAL.gold);
      // Gold finial
      canvas.fillRect(ox + 29, oy, 6, 4, PAL.gold);
    });
  }

  // Tree trunks
  for (let c = 0; c < 2; c++) {
    tile(c + 6, 0, (ox, oy) => {
      // Trunk
      canvas.fillRect(ox + 26, oy + 8, 12, 52, PAL.trunk);
      // Root flare
      canvas.fillRect(ox + 22, oy + 50, 20, 10, PAL.trunk);
      // Bark texture
      canvas.setPixel(ox + 30, oy + 20, PAL.brownDark);
      canvas.setPixel(ox + 34, oy + 30, PAL.brownDark);
      canvas.setPixel(ox + 28, oy + 40, PAL.brownDark);
    });
  }

  // Fountain (large, ornate — single tile used for center of forum)
  for (let c = 0; c < 2; c++) {
    tile(c + 8, 0, (ox, oy) => {
      // Stone pedestal base
      canvas.fillIsoCube(ox + 4, oy + 28, 56, 26, 8,
        PAL.stoneDark, darken(PAL.stoneDark, 15), darken(PAL.stoneDark, 25));
      canvas.strokeDiamond(ox + 4, oy + 28, 56, 26, PAL.stoneLight);
      // Water basin
      canvas.fillIsoCube(ox + 10, oy + 20, 44, 22, 12,
        PAL.water, darken(PAL.water, 20), darken(PAL.water, 30));
      // Water surface sparkles
      resetSeed(c * 800);
      for (let i = 0; i < 12; i++) {
        const sx = ox + 18 + Math.floor(rand() * 28);
        const sy = oy + 24 + Math.floor(rand() * 14);
        canvas.setPixel(sx, sy, PAL.white);
        canvas.setPixel(sx + 1, sy, [...PAL.white.slice(0, 3), 160]);
      }
      // Center column/spout
      canvas.fillRect(ox + 28, oy + 4, 8, 22, PAL.stone);
      canvas.fillRect(ox + 26, oy + 2, 12, 4, PAL.stoneLight);
      canvas.fillRect(ox + 30, oy + 0, 4, 2, PAL.stoneLight);
      // Water spray droplets above spout
      canvas.setPixel(ox + 26, oy + 6, PAL.waterLight);
      canvas.setPixel(ox + 38, oy + 8, PAL.waterLight);
      canvas.setPixel(ox + 24, oy + 10, PAL.waterLight);
      canvas.setPixel(ox + 40, oy + 12, PAL.waterLight);
      canvas.setPixel(ox + 22, oy + 14, PAL.waterLight);
      canvas.setPixel(ox + 42, oy + 14, PAL.waterLight);
      // Basin rim highlight
      canvas.strokeDiamond(ox + 10, oy + 20, 44, 22, PAL.stoneLight);
    });
  }

  // Row 1: tree canopies
  for (let c = 0; c < 4; c++) {
    tile(c, 1, (ox, oy) => {
      // Large circle-ish canopy
      const cx = 32, cy = 28;
      for (let py = 0; py < DH; py++) {
        for (let px = 0; px < TW; px++) {
          const dx = px - cx, dy = (py - cy) * 1.3;
          if (dx * dx + dy * dy < 600) {
            const shade = (dx + dy) < 0 ? PAL.treeLight : PAL.tree;
            canvas.setPixel(ox + px, oy + py, shade);
          }
        }
      }
      // Leaf highlights
      resetSeed(c * 900);
      for (let i = 0; i < 12; i++) {
        const lx = Math.floor(rand() * 48) + 8;
        const ly = Math.floor(rand() * 48) + 8;
        canvas.setPixel(ox + lx, oy + ly, PAL.grassLight);
      }
    });
  }

  // Wall parapet overlays
  for (let c = 0; c < 4; c++) {
    tile(c + 4, 1, (ox, oy) => {
      canvas.fillDiamond(ox, oy + 8, TW, TH, PAL.wallDark);
      canvas.strokeDiamond(ox, oy + 8, TW, TH, PAL.wallLight);
    });
  }

  return canvas;
}

// ══════════════════════════════════════════════════════
// CHARACTER SPRITES — 4 cols × 4 rows of 32×48 frames
// ══════════════════════════════════════════════════════

// ── Improved character generator with per-type features ──

function generateIsoCharacterV2(cfg) {
  const FW = 32, FH = 48;
  const canvas = new PixelCanvas(FW * 4, FH * 4);
  const dirs = ['down', 'left', 'right', 'up'];

  for (let row = 0; row < 4; row++) {
    for (let frame = 0; frame < 4; frame++) {
      _drawCharFrame(canvas, frame * FW, row * FH, dirs[row], frame, cfg);
    }
  }
  return canvas;
}

function _drawCharFrame(c, ox, oy, dir, frame, cfg) {
  const { bodyColor, headColor, accentColor, hairColor, hairStyle, features, capeColor } = cfg;
  const bodyDark = darken(bodyColor, 20);
  const bodyLight = lighten(bodyColor, 12);

  // ── Shadow ellipse ──
  for (let py = 41; py < 46; py++) {
    for (let px = 7; px < 25; px++) {
      const dx = px - 16, dy = (py - 43) * 2.2;
      if (dx * dx + dy * dy < 90) c.setPixel(ox + px, oy + py, PAL.shadow);
    }
  }

  // ── Cape behind body (up view) ──
  if (features?.includes('cape') && dir === 'up') {
    const cc = capeColor || darken(bodyColor, 15);
    c.fillRect(ox + 8, oy + 20, 16, 18, cc);
    c.fillRect(ox + 9, oy + 37, 14, 3, darken(cc, 12));
  }

  // ── Legs with walk cycle ──
  const legOff = frame === 1 ? -2 : frame === 3 ? 2 : 0;
  c.fillRect(ox + 11 + legOff, oy + 34, 4, 7, bodyDark);
  c.fillRect(ox + 17 - legOff, oy + 34, 4, 7, bodyDark);
  // Boots
  const bootCol = darken(PAL.brownDark, 10);
  c.fillRect(ox + 10 + legOff, oy + 39, 5, 3, bootCol);
  c.fillRect(ox + 17 - legOff, oy + 39, 5, 3, bootCol);
  c.setPixel(ox + 11 + legOff, oy + 39, PAL.brownDark);
  c.setPixel(ox + 18 - legOff, oy + 39, PAL.brownDark);

  // ── Torso ──
  c.fillRect(ox + 9, oy + 20, 14, 14, bodyColor);
  // Shading
  c.fillRect(ox + 9, oy + 20, 2, 14, bodyDark);
  c.fillRect(ox + 21, oy + 20, 2, 14, bodyLight);
  // Collar highlight
  c.hLine(ox + 10, oy + 19, 12, bodyLight);

  // ── Belt ──
  c.hLine(ox + 9, oy + 28, 14, accentColor);
  c.hLine(ox + 9, oy + 29, 14, darken(accentColor, 15));
  c.setPixel(ox + 16, oy + 28, lighten(accentColor, 25));

  // ── Shoulders ──
  c.fillRect(ox + 7, oy + 19, 18, 3, bodyColor);
  c.hLine(ox + 7, oy + 19, 18, bodyLight);

  // ── Arms with swing ──
  const armSwing = frame === 1 ? -1 : frame === 3 ? 1 : 0;
  if (dir === 'left') {
    c.fillRect(ox + 6, oy + 21 - armSwing, 3, 10, bodyDark);
    c.fillRect(ox + 6, oy + 29 - armSwing, 3, 2, headColor);
  } else if (dir === 'right') {
    c.fillRect(ox + 23, oy + 21 + armSwing, 3, 10, bodyDark);
    c.fillRect(ox + 23, oy + 29 + armSwing, 3, 2, headColor);
  } else {
    c.fillRect(ox + 5, oy + 21 - armSwing, 3, 10, bodyDark);
    c.fillRect(ox + 5, oy + 29 - armSwing, 3, 2, headColor);
    c.fillRect(ox + 24, oy + 21 + armSwing, 3, 10, bodyDark);
    c.fillRect(ox + 24, oy + 29 + armSwing, 3, 2, headColor);
  }

  // ── Neck ──
  c.fillRect(ox + 13, oy + 17, 6, 4, headColor);

  // ── Head (rounded shape) ──
  c.fillRect(ox + 10, oy + 7, 12, 10, headColor);
  c.fillRect(ox + 12, oy + 5, 8, 2, headColor);
  c.setPixel(ox + 13, oy + 4, headColor);
  c.setPixel(ox + 18, oy + 4, headColor);
  // Ear highlights
  c.setPixel(ox + 9, oy + 10, darken(headColor, 10));
  c.setPixel(ox + 22, oy + 10, darken(headColor, 10));

  // ── Face ──
  if (dir === 'down') {
    c.setPixel(ox + 13, oy + 11, PAL.void); c.setPixel(ox + 19, oy + 11, PAL.void);
    c.setPixel(ox + 12, oy + 11, PAL.white); c.setPixel(ox + 18, oy + 11, PAL.white);
    c.hLine(ox + 14, oy + 15, 4, darken(headColor, 20));
  } else if (dir === 'left') {
    c.setPixel(ox + 11, oy + 11, PAL.void); c.setPixel(ox + 10, oy + 11, PAL.white);
  } else if (dir === 'right') {
    c.setPixel(ox + 20, oy + 11, PAL.void); c.setPixel(ox + 21, oy + 11, PAL.white);
  }

  // ── Hair ──
  const hc = hairColor || darken(headColor, 40);
  switch (hairStyle) {
    case 'short':
      c.fillRect(ox + 10, oy + 4, 12, 4, hc);
      c.fillRect(ox + 12, oy + 3, 8, 1, hc);
      if (dir === 'up') c.fillRect(ox + 10, oy + 4, 12, 8, hc);
      if (dir === 'left') c.fillRect(ox + 9, oy + 5, 2, 5, hc);
      if (dir === 'right') c.fillRect(ox + 21, oy + 5, 2, 5, hc);
      break;
    case 'curly':
      c.fillRect(ox + 9, oy + 3, 14, 6, hc);
      c.fillRect(ox + 12, oy + 2, 8, 1, hc);
      c.setPixel(ox + 9, oy + 8, hc); c.setPixel(ox + 22, oy + 8, hc);
      c.setPixel(ox + 10, oy + 9, hc); c.setPixel(ox + 21, oy + 9, hc);
      if (dir === 'up') c.fillRect(ox + 9, oy + 3, 14, 10, hc);
      break;
    case 'helmet':
      c.fillRect(ox + 9, oy + 3, 14, 8, PAL.silver);
      c.fillRect(ox + 12, oy + 2, 8, 1, PAL.silver);
      // Crest plume
      c.fillRect(ox + 14, oy, 4, 3, PAL.red);
      c.fillRect(ox + 15, oy - 1, 2, 1, PAL.red);
      // Nose guard (front)
      if (dir === 'down') c.fillRect(ox + 15, oy + 9, 2, 5, PAL.silver);
      // Cheek guards
      c.fillRect(ox + 9, oy + 8, 2, 7, darken(PAL.silver, 15));
      c.fillRect(ox + 21, oy + 8, 2, 7, darken(PAL.silver, 15));
      break;
    case 'long':
      c.fillRect(ox + 9, oy + 3, 14, 6, hc);
      c.fillRect(ox + 12, oy + 2, 8, 1, hc);
      if (dir !== 'right') c.fillRect(ox + 8, oy + 5, 2, 14, hc);
      if (dir !== 'left') c.fillRect(ox + 22, oy + 5, 2, 14, hc);
      if (dir === 'up') c.fillRect(ox + 9, oy + 3, 14, 16, hc);
      break;
    case 'bald':
      c.fillRect(ox + 11, oy + 5, 10, 2, darken(headColor, 8));
      break;
    case 'headband':
      c.fillRect(ox + 10, oy + 4, 12, 3, hc);
      c.fillRect(ox + 9, oy + 6, 14, 2, accentColor);
      break;
  }

  // ── Character-specific features ──
  // Cape (side/front views)
  if (features?.includes('cape') && dir !== 'up') {
    const cc = capeColor || darken(bodyColor, 15);
    if (dir === 'down') {
      c.fillRect(ox + 6, oy + 21, 2, 14, cc);
      c.fillRect(ox + 24, oy + 21, 2, 14, cc);
    }
  }

  // Spear
  if (features?.includes('spear') && (dir === 'right' || dir === 'down')) {
    c.vLine(ox + 26, oy + 2, 32, PAL.silver);
    c.fillRect(ox + 25, oy + 1, 3, 5, lighten(PAL.silver, 15));
  }

  // Scroll
  if (features?.includes('scroll') && (dir === 'down' || dir === 'right')) {
    c.fillRect(ox + 25, oy + 27, 4, 7, PAL.marbleLight);
    c.hLine(ox + 25, oy + 27, 4, PAL.road);
    c.hLine(ox + 25, oy + 33, 4, PAL.road);
  }

  // Coin pouch
  if (features?.includes('pouch')) {
    const px = dir === 'left' ? 6 : 20;
    c.fillRect(ox + px, oy + 28, 4, 4, darken(PAL.brown, 10));
    c.setPixel(ox + px + 2, oy + 29, PAL.gold);
  }

  // Apron
  if (features?.includes('apron')) {
    c.fillRect(ox + 10, oy + 28, 12, 6, lighten(bodyColor, 25));
    c.hLine(ox + 10, oy + 28, 12, lighten(bodyColor, 35));
  }

  // Glasses
  if (features?.includes('glasses') && (dir === 'down' || dir === 'left' || dir === 'right')) {
    c.hLine(ox + 11, oy + 10, 10, PAL.silver);
  }
}

// ══════════════════════════════════════════════════════
// PARTICLES — 8×8 sprites (scaled up from 4×4)
// ══════════════════════════════════════════════════════

function generateIsoParticle(color, pattern) {
  const canvas = new PixelCanvas(8, 8);
  if (pattern === 'dot') {
    canvas.fillRect(2, 2, 4, 4, color);
  } else if (pattern === 'cross') {
    canvas.fillRect(3, 1, 2, 6, color);
    canvas.fillRect(1, 3, 6, 2, color);
  } else if (pattern === 'leaf') {
    canvas.setPixel(1, 3, color); canvas.setPixel(2, 2, color);
    canvas.setPixel(3, 1, color); canvas.setPixel(3, 2, color);
    canvas.setPixel(4, 3, color); canvas.setPixel(4, 4, color);
    canvas.setPixel(5, 5, color); canvas.setPixel(6, 6, color);
  }
  return canvas;
}

function generateIsoInteractIcon() {
  const canvas = new PixelCanvas(24, 24);
  for (let y = 0; y < 24; y++) {
    for (let x = 0; x < 24; x++) {
      const dx = Math.abs(x - 11.5), dy = Math.abs(y - 11.5);
      if (dx + dy < 10) {
        canvas.setPixel(x, y, dx + dy < 7 ? PAL.gold : PAL.goldDim);
      }
    }
  }
  return canvas;
}

// ══════════════════════════════════════════════════════
// MAIN
// ══════════════════════════════════════════════════════

async function main() {
  console.log('Generating isometric tilesets...');

  const terrain = generateTerrainIso();
  await terrain.save(join(OUT, 'tilesets', 'terrain-iso.png'));
  console.log(`  terrain-iso.png (${terrain.w}x${terrain.h})`);

  const buildings = generateBuildingsIso();
  await buildings.save(join(OUT, 'tilesets', 'buildings-iso.png'));
  console.log(`  buildings-iso.png (${buildings.w}x${buildings.h})`);

  const decorations = generateDecorationsIso();
  await decorations.save(join(OUT, 'tilesets', 'decorations-iso.png'));
  console.log(`  decorations-iso.png (${decorations.w}x${decorations.h})`);

  // Characters at 32×48 per frame
  const characters = [
    { name: 'player',        bodyColor: PAL.purple, headColor: PAL.skin,     accentColor: PAL.gold,   hairColor: hex(0x2A1A0A), hairStyle: 'curly',    features: ['cape'], capeColor: darken(PAL.purple, 20) },
    { name: 'npc-guard',     bodyColor: PAL.red,    headColor: PAL.skinDark, accentColor: PAL.gold,   hairColor: null,          hairStyle: 'helmet',   features: ['spear'] },
    { name: 'npc-merchant',  bodyColor: PAL.brown,  headColor: PAL.skin,     accentColor: PAL.amber,  hairColor: hex(0x4A3520), hairStyle: 'short',    features: ['pouch'] },
    { name: 'npc-scholar',   bodyColor: PAL.blue,   headColor: PAL.skin,     accentColor: PAL.silver, hairColor: hex(0x888888), hairStyle: 'long',     features: ['scroll'] },
    { name: 'npc-archivist', bodyColor: darken(PAL.blue, 15), headColor: PAL.skin, accentColor: PAL.gold, hairColor: hex(0x888888), hairStyle: 'bald', features: ['glasses', 'scroll'] },
    { name: 'npc-vendor',    bodyColor: PAL.brown,  headColor: PAL.skinDark, accentColor: PAL.amber,  hairColor: hex(0x3A2A10), hairStyle: 'headband', features: ['apron'] },
  ];
  for (const ch of characters) {
    const sprite = generateIsoCharacterV2(ch);
    await sprite.save(join(OUT, 'sprites', `${ch.name}.png`));
    console.log(`  sprites/${ch.name}.png (${sprite.w}x${sprite.h})`);
  }

  // Particles
  const particles = [
    { name: 'dust',    color: PAL.silver,     pattern: 'dot' },
    { name: 'sparkle', color: PAL.white,      pattern: 'cross' },
    { name: 'leaf',    color: PAL.grassLight,  pattern: 'leaf' },
    { name: 'smoke',   color: PAL.silver,     pattern: 'dot' },
  ];
  for (const p of particles) {
    const tex = generateIsoParticle(p.color, p.pattern);
    await tex.save(join(OUT, 'particles', `${p.name}.png`));
    console.log(`  particles/${p.name}.png (${tex.w}x${tex.h})`);
  }

  // UI
  const icon = generateIsoInteractIcon();
  await icon.save(join(OUT, 'ui', 'interact-icon.png'));
  console.log('  ui/interact-icon.png (24x24)');

  console.log('\nDone! Isometric assets written to public/assets/');
}

main().catch(console.error);
