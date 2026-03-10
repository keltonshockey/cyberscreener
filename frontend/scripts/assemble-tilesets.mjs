#!/usr/bin/env node
/**
 * QUAEST.TECH — Tileset Assembler
 * Composes real art from downloaded asset packs into the game's tileset PNGs.
 *
 * Sources:
 *  - PunyWorld overworld (CC0) — grass, water, trees, nature
 *  - PathAndObjects (CC-BY-SA) — cobblestone roads, stone, town objects
 *  - 0x72 DungeonTileset II (CC0) — stone walls, floors, doors, columns, banners
 *  - AncientRome icon pack — decoration icons (32×32, scaled to 16×16)
 *
 * Output:
 *  - public/assets/tilesets/terrain.png   (256×128, 16 cols × 8 rows)
 *  - public/assets/tilesets/buildings.png  (256×64, 16 cols × 4 rows)
 *  - public/assets/tilesets/decorations.png (256×64, 16 cols × 4 rows)
 *
 * Run: node scripts/assemble-tilesets.mjs
 */

import sharp from 'sharp';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');
const PACKS = path.join(root, 'public/assets/packs');
const OUT = path.join(root, 'public/assets/tilesets');
const FRAMES = path.join(PACKS, '0x72_DungeonTilesetII/0x72_DungeonTilesetII_v1.7/frames');
const T = 16; // tile size

// ─── Source file paths ───
const SRC = {
  puny:       path.join(PACKS, 'punyworld-overworld-tileset.png'),
  pathObj:    path.join(PACKS, 'PathAndObjects.png'),
  floor0x72:  path.join(PACKS, '0x72_DungeonTilesetII/0x72_DungeonTilesetII_v1.7/atlas_floor-16x16.png'),
  wallsLow:   path.join(PACKS, '0x72_DungeonTilesetII/0x72_DungeonTilesetII_v1.7/atlas_walls_low-16x16.png'),
  wallsHigh:  path.join(PACKS, '0x72_DungeonTilesetII/0x72_DungeonTilesetII_v1.7/atlas_walls_high-16x32.png'),
  // Individual 0x72 frames (all 16×16 unless noted)
  frame: (name) => path.join(FRAMES, name),
  // AncientRome icons (32×32)
  rome: (name) => path.join(PACKS, 'AncientRome', name),
};

// ─── Helpers ───

/** Extract a 16×16 tile from a source image at pixel coords */
async function extractTile(srcPath, sx, sy, w = T, h = T) {
  return sharp(srcPath)
    .extract({ left: sx, top: sy, width: w, height: h })
    .resize(T, T, { kernel: 'nearest' })
    .toBuffer();
}

/** Extract a tile from an individual frame file (may need crop if taller) */
async function extractFrame(frameName, cropTop = 0) {
  const framePath = SRC.frame(frameName);
  const meta = await sharp(framePath).metadata();
  if (meta.height > T) {
    // Crop to 16×16 from the specified offset
    return sharp(framePath)
      .extract({ left: 0, top: cropTop, width: Math.min(meta.width, T), height: T })
      .resize(T, T, { kernel: 'nearest' })
      .toBuffer();
  }
  return sharp(framePath).resize(T, T, { kernel: 'nearest' }).toBuffer();
}

/** Extract a 32×32 AncientRome icon and scale to 16×16 */
async function extractRomeIcon(subpath) {
  return sharp(SRC.rome(subpath))
    .resize(T, T, { kernel: 'nearest' })
    .toBuffer();
}

/** Create a solid-color 16×16 tile */
async function solidTile(r, g, b, a = 255) {
  return sharp({
    create: { width: T, height: T, channels: 4, background: { r, g, b, alpha: a / 255 } }
  }).png().toBuffer();
}

/** Compose tiles onto a canvas */
async function composeTileset(width, height, tiles) {
  // Start with transparent canvas
  const canvas = sharp({
    create: { width, height, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } }
  }).png();

  const composites = [];
  for (const { col, row, buf } of tiles) {
    if (buf) {
      composites.push({
        input: await sharp(buf).resize(T, T, { kernel: 'nearest' }).png().toBuffer(),
        left: col * T,
        top: row * T,
      });
    }
  }

  return canvas.composite(composites).toBuffer();
}

// ═══════════════════════════════════════════════════
// TERRAIN.PNG (256×128) — Ground tiles
// GID mapping: GRASS=1(col0), STONE=9(col8), MARBLE=17(r1c0),
//   ROAD=25(r1c8), WATER=33(r2c0), VOID=41(r2c8)
// ═══════════════════════════════════════════════════

async function buildTerrain() {
  console.log('  Building terrain.png...');
  const tiles = [];

  // ── GRASS (row 0, cols 0-7) — from PunyWorld ──
  // PunyWorld grid: 27 cols × 65 rows at 16px
  // Row 0 starts with grass autotile pieces
  tiles.push({ col: 0, row: 0, buf: await extractTile(SRC.puny, 0, 0) });        // solid grass
  tiles.push({ col: 1, row: 0, buf: await extractTile(SRC.puny, T, 0) });        // grass variant
  tiles.push({ col: 2, row: 0, buf: await extractTile(SRC.puny, T*2, 0) });      // grass edge
  tiles.push({ col: 3, row: 0, buf: await extractTile(SRC.puny, 0, T) });        // grass variant 2
  tiles.push({ col: 4, row: 0, buf: await extractTile(SRC.puny, T, T) });        // grass inner
  tiles.push({ col: 5, row: 0, buf: await extractTile(SRC.puny, T*2, T) });      // grass edge 2
  tiles.push({ col: 6, row: 0, buf: await extractTile(SRC.puny, T*3, 0) });      // grass variant 3
  tiles.push({ col: 7, row: 0, buf: await extractTile(SRC.puny, T*4, 0) });      // grass variant 4

  // ── STONE (row 0, cols 8-15) — from PathAndObjects ──
  // PathAndObjects r6c5 area = cracked grey stone
  tiles.push({ col: 8,  row: 0, buf: await extractTile(SRC.pathObj, T*5, T*6) });   // cracked stone
  tiles.push({ col: 9,  row: 0, buf: await extractTile(SRC.pathObj, T*5, T*5) });   // stone variant
  tiles.push({ col: 10, row: 0, buf: await extractTile(SRC.pathObj, T*5, T*7) });   // stone variant 2
  tiles.push({ col: 11, row: 0, buf: await extractTile(SRC.pathObj, T*4, T*6) });   // stone variant 3
  tiles.push({ col: 12, row: 0, buf: await extractTile(SRC.pathObj, T*4, T*5) });   // stone edge
  tiles.push({ col: 13, row: 0, buf: await extractTile(SRC.pathObj, T*4, T*7) });   // stone edge 2
  tiles.push({ col: 14, row: 0, buf: await extractTile(SRC.pathObj, T*3, T*6) });   // stone edge 3
  tiles.push({ col: 15, row: 0, buf: await extractTile(SRC.pathObj, T*3, T*7) });   // stone edge 4

  // ── MARBLE (row 1, cols 0-7) — from PathAndObjects ──
  // r6c6 = light beige cobblestone, perfect for Roman marble plaza
  tiles.push({ col: 0, row: 1, buf: await extractTile(SRC.pathObj, T*6, T*6) });    // clean cobblestone
  tiles.push({ col: 1, row: 1, buf: await extractTile(SRC.pathObj, T*7, T*6) });    // cobble variant
  tiles.push({ col: 2, row: 1, buf: await extractTile(SRC.pathObj, T*8, T*6) });    // cobble variant 2
  tiles.push({ col: 3, row: 1, buf: await extractTile(SRC.pathObj, T*6, T*7) });    // cobble variant 3
  tiles.push({ col: 4, row: 1, buf: await extractTile(SRC.pathObj, T*7, T*7) });    // cobble edge
  tiles.push({ col: 5, row: 1, buf: await extractTile(SRC.pathObj, T*8, T*7) });    // cobble edge 2
  tiles.push({ col: 6, row: 1, buf: await extractTile(SRC.pathObj, T*6, T*5) });    // cobble inner
  tiles.push({ col: 7, row: 1, buf: await extractTile(SRC.pathObj, T*7, T*5) });    // cobble inner 2

  // ── ROAD (row 1, cols 8-15) — from PathAndObjects ──
  // Slightly different stone variant for roads vs marble plazas
  tiles.push({ col: 8,  row: 1, buf: await extractTile(SRC.pathObj, T*6, T*8) });   // road stone
  tiles.push({ col: 9,  row: 1, buf: await extractTile(SRC.pathObj, T*7, T*8) });   // road variant
  tiles.push({ col: 10, row: 1, buf: await extractTile(SRC.pathObj, T*8, T*8) });   // road variant 2
  tiles.push({ col: 11, row: 1, buf: await extractTile(SRC.pathObj, T*9, T*8) });   // road variant 3
  tiles.push({ col: 12, row: 1, buf: await extractTile(SRC.pathObj, T*6, T*9) });   // road edge
  tiles.push({ col: 13, row: 1, buf: await extractTile(SRC.pathObj, T*7, T*9) });   // road edge 2
  tiles.push({ col: 14, row: 1, buf: await extractTile(SRC.pathObj, T*8, T*9) });   // road edge 3
  tiles.push({ col: 15, row: 1, buf: await extractTile(SRC.pathObj, T*9, T*9) });   // road edge 4

  // ── WATER (row 2, cols 0-7) — from PunyWorld ──
  // Water tiles at rows 12-16 in PunyWorld (teal blue)
  tiles.push({ col: 0, row: 2, buf: await extractTile(SRC.puny, T*8, T*14) });     // solid teal water
  tiles.push({ col: 1, row: 2, buf: await extractTile(SRC.puny, T*8, T*12) });     // water variant
  tiles.push({ col: 2, row: 2, buf: await extractTile(SRC.puny, 0, T*12) });       // water with shore
  tiles.push({ col: 3, row: 2, buf: await extractTile(SRC.puny, 0, T*14) });       // water shore 2
  tiles.push({ col: 4, row: 2, buf: await extractTile(SRC.puny, 0, T*16) });       // water shore 3
  tiles.push({ col: 5, row: 2, buf: await extractTile(SRC.puny, T*8, T*16) });     // water deep
  tiles.push({ col: 6, row: 2, buf: await extractTile(SRC.puny, T*4, T*14) });     // water edge
  tiles.push({ col: 7, row: 2, buf: await extractTile(SRC.puny, T*4, T*12) });     // water edge 2

  // ── VOID (row 2, cols 8-15) — dark tiles ──
  tiles.push({ col: 8,  row: 2, buf: await solidTile(17, 17, 17) });
  tiles.push({ col: 9,  row: 2, buf: await solidTile(22, 22, 22) });
  tiles.push({ col: 10, row: 2, buf: await solidTile(12, 12, 12) });
  tiles.push({ col: 11, row: 2, buf: await solidTile(17, 17, 17) });
  tiles.push({ col: 12, row: 2, buf: await solidTile(15, 15, 20) });
  tiles.push({ col: 13, row: 2, buf: await solidTile(20, 17, 17) });
  tiles.push({ col: 14, row: 2, buf: await solidTile(17, 17, 17) });
  tiles.push({ col: 15, row: 2, buf: await solidTile(10, 10, 10) });

  // ── Extra rows 3-7: filled with PathAndObjects nature tiles ──
  // Row 3: dirt/earth tiles from PathAndObjects
  for (let c = 0; c < 16; c++) {
    tiles.push({ col: c, row: 3, buf: await extractTile(SRC.pathObj, T*c, T*2) });
  }
  // Row 4: more PathAndObjects tiles
  for (let c = 0; c < 16; c++) {
    tiles.push({ col: c, row: 4, buf: await extractTile(SRC.pathObj, T*c, T*3) });
  }
  // Rows 5-7: more PathAndObjects rows for future autotiling
  for (let r = 5; r < 8; r++) {
    for (let c = 0; c < 16; c++) {
      tiles.push({ col: c, row: r, buf: await extractTile(SRC.pathObj, T*c, T*(r-1)) });
    }
  }

  const buf = await composeTileset(256, 128, tiles);
  await sharp(buf).toFile(path.join(OUT, 'terrain.png'));
  console.log('  ✓ terrain.png');
}

// ═══════════════════════════════════════════════════
// BUILDINGS.PNG (256×64) — Walls, doors, shelves
// GID mapping: WALL=129(r0c0), DOOR=145(r1c0), SHELF=149(r1c4)
// ═══════════════════════════════════════════════════

async function buildBuildings() {
  console.log('  Building buildings.png...');
  const tiles = [];

  // ── WALL (row 0, cols 0-15) — from 0x72 wall frames ──
  tiles.push({ col: 0,  row: 0, buf: await extractFrame('wall_mid.png') });
  tiles.push({ col: 1,  row: 0, buf: await extractFrame('wall_left.png') });
  tiles.push({ col: 2,  row: 0, buf: await extractFrame('wall_right.png') });
  tiles.push({ col: 3,  row: 0, buf: await extractFrame('wall_top_mid.png') });
  tiles.push({ col: 4,  row: 0, buf: await extractFrame('wall_top_left.png') });
  tiles.push({ col: 5,  row: 0, buf: await extractFrame('wall_top_right.png') });
  tiles.push({ col: 6,  row: 0, buf: await extractFrame('wall_outer_mid_left.png') });
  tiles.push({ col: 7,  row: 0, buf: await extractFrame('wall_outer_mid_right.png') });
  tiles.push({ col: 8,  row: 0, buf: await extractFrame('wall_edge_left.png') });
  tiles.push({ col: 9,  row: 0, buf: await extractFrame('wall_edge_right.png') });
  tiles.push({ col: 10, row: 0, buf: await extractFrame('wall_edge_top_left.png') });
  tiles.push({ col: 11, row: 0, buf: await extractFrame('wall_edge_top_right.png') });
  tiles.push({ col: 12, row: 0, buf: await extractFrame('edge_down.png') });
  tiles.push({ col: 13, row: 0, buf: await extractFrame('wall_edge_mid_left.png') });
  tiles.push({ col: 14, row: 0, buf: await extractFrame('wall_edge_mid_right.png') });
  // Fill last col with variant
  tiles.push({ col: 15, row: 0, buf: await extractFrame('wall_mid.png') });

  // ── DOOR (row 1, cols 0-3) — from 0x72 door frames (32×32, extract quadrants) ──
  const doorClosed = SRC.frame('doors_leaf_closed.png');
  const doorOpen = SRC.frame('doors_leaf_open.png');
  tiles.push({ col: 0, row: 1, buf: await extractTile(doorClosed, 0, 0) });        // door TL
  tiles.push({ col: 1, row: 1, buf: await extractTile(doorClosed, T, 0) });        // door TR
  tiles.push({ col: 2, row: 1, buf: await extractTile(doorClosed, 0, T) });        // door BL
  tiles.push({ col: 3, row: 1, buf: await extractTile(doorClosed, T, T) });        // door BR

  // ── SHELF (row 1, cols 4-7) — from PathAndObjects objects ──
  // Market stall / shelf objects from lower rows of PathAndObjects
  tiles.push({ col: 4, row: 1, buf: await extractTile(SRC.pathObj, T*16, T*10) }); // shelf/object
  tiles.push({ col: 5, row: 1, buf: await extractTile(SRC.pathObj, T*17, T*10) }); // shelf variant
  tiles.push({ col: 6, row: 1, buf: await extractTile(SRC.pathObj, T*18, T*10) }); // shelf variant 2
  tiles.push({ col: 7, row: 1, buf: await extractTile(SRC.pathObj, T*19, T*10) }); // shelf variant 3

  // ── Extra: door open variants (row 1, cols 8-11) ──
  tiles.push({ col: 8,  row: 1, buf: await extractTile(doorOpen, 0, 0) });
  tiles.push({ col: 9,  row: 1, buf: await extractTile(doorOpen, T, 0) });
  tiles.push({ col: 10, row: 1, buf: await extractTile(doorOpen, 0, T) });
  tiles.push({ col: 11, row: 1, buf: await extractTile(doorOpen, T, T) });

  // ── Row 2-3: Wall variants from 0x72 atlas ──
  // atlas_walls_low: 12 cols × 4 rows
  for (let r = 0; r < 4; r++) {
    for (let c = 0; c < 12; c++) {
      tiles.push({
        col: c, row: 2 + Math.floor(r / 2),
        buf: await extractTile(SRC.wallsLow, c * T, r * T),
      });
    }
  }

  const buf = await composeTileset(256, 64, tiles);
  await sharp(buf).toFile(path.join(OUT, 'buildings.png'));
  console.log('  ✓ buildings.png');
}

// ═══════════════════════════════════════════════════
// DECORATIONS.PNG (256×64) — Pillars, columns, banners, trees, fountain
// GID mapping: PILLAR=193(r0c0), COLUMN=195(r0c2), BANNER=197(r0c4),
//   TREE_TRUNK=199(r0c6), FOUNTAIN_WATER=201(r0c8), FOUNTAIN_RIM=202(r0c9),
//   TREE_CANOPY=209(r1c0), WALL_PARAPET=213(r1c4)
// ═══════════════════════════════════════════════════

async function buildDecorations() {
  console.log('  Building decorations.png...');
  const tiles = [];

  // ── PILLAR (row 0, cols 0-1) — from 0x72 column frame (16×48, take top 16px) ──
  tiles.push({ col: 0, row: 0, buf: await extractFrame('column.png', 0) });     // column top
  tiles.push({ col: 1, row: 0, buf: await extractFrame('column.png', 16) });    // column mid

  // ── COLUMN (row 0, cols 2-3) — from 0x72 column_wall ──
  tiles.push({ col: 2, row: 0, buf: await extractFrame('column_wall.png', 0) });  // wall col top
  tiles.push({ col: 3, row: 0, buf: await extractFrame('column_wall.png', 16) }); // wall col mid

  // ── BANNER (row 0, cols 4-5) — from 0x72 wall banners ──
  tiles.push({ col: 4, row: 0, buf: await extractFrame('wall_banner_red.png') });
  tiles.push({ col: 5, row: 0, buf: await extractFrame('wall_banner_blue.png') });

  // ── TREE_TRUNK (row 0, cols 6-7) — from PunyWorld trees ──
  // Trees in PunyWorld around rows 7-8
  tiles.push({ col: 6, row: 0, buf: await extractTile(SRC.puny, T*4, T*8) });      // tree trunk
  tiles.push({ col: 7, row: 0, buf: await extractTile(SRC.puny, T*2, T*8) });      // tree variant

  // ── FOUNTAIN_WATER (row 0, col 8) — teal water from PunyWorld ──
  tiles.push({ col: 8, row: 0, buf: await extractTile(SRC.puny, T*8, T*14) });     // solid teal water

  // ── FOUNTAIN_RIM (row 0, col 9) — stone edge from PathAndObjects ──
  tiles.push({ col: 9, row: 0, buf: await extractTile(SRC.pathObj, T*5, T*6) });

  // ── Extra decorations (row 0, cols 10-15) ──
  tiles.push({ col: 10, row: 0, buf: await extractFrame('wall_banner_green.png') });
  tiles.push({ col: 11, row: 0, buf: await extractFrame('wall_banner_yellow.png') });
  tiles.push({ col: 12, row: 0, buf: await extractFrame('wall_goo.png') });
  tiles.push({ col: 13, row: 0, buf: await extractFrame('skull.png') });
  // AncientRome icons scaled to 16×16
  tiles.push({ col: 14, row: 0, buf: await extractRomeIcon('Misc/Amphora.png') });
  tiles.push({ col: 15, row: 0, buf: await extractRomeIcon('Misc/Scroll.png') });

  // ── TREE_CANOPY (row 1, cols 0-3) — from PunyWorld tree tops ──
  tiles.push({ col: 0, row: 1, buf: await extractTile(SRC.puny, T*4, T*7) });
  tiles.push({ col: 1, row: 1, buf: await extractTile(SRC.puny, T*2, T*7) });
  tiles.push({ col: 2, row: 1, buf: await extractTile(SRC.puny, T*6, T*7) });
  tiles.push({ col: 3, row: 1, buf: await extractTile(SRC.puny, T*8, T*7) });

  // ── WALL_PARAPET (row 1, cols 4-7) — from 0x72 wall tops ──
  tiles.push({ col: 4, row: 1, buf: await extractFrame('wall_top_mid.png') });
  tiles.push({ col: 5, row: 1, buf: await extractFrame('wall_top_left.png') });
  tiles.push({ col: 6, row: 1, buf: await extractFrame('wall_top_right.png') });
  tiles.push({ col: 7, row: 1, buf: await extractTile(SRC.wallsLow, 0, 0) });

  // ── Extra (row 1, cols 8-15): AncientRome icons ──
  tiles.push({ col: 8,  row: 1, buf: await extractRomeIcon('Architecture/Column.png') });
  tiles.push({ col: 9,  row: 1, buf: await extractRomeIcon('Architecture/Temple.png') });
  tiles.push({ col: 10, row: 1, buf: await extractRomeIcon('Flags & Banners/Banner.png') });
  tiles.push({ col: 11, row: 1, buf: await extractRomeIcon('Flags & Banners/flagSPQR.png') });
  tiles.push({ col: 12, row: 1, buf: await extractRomeIcon('Misc/CoinGold.png') });
  tiles.push({ col: 13, row: 1, buf: await extractRomeIcon('Misc/Laurels.png') });
  tiles.push({ col: 14, row: 1, buf: await extractRomeIcon('Misc/Grapes.png') });
  tiles.push({ col: 15, row: 1, buf: await extractRomeIcon('People/Senate.png') });

  // ── Rows 2-3: More PathAndObjects objects ──
  for (let c = 0; c < 16; c++) {
    tiles.push({ col: c, row: 2, buf: await extractTile(SRC.pathObj, T*c, T*12) });
  }
  for (let c = 0; c < 16; c++) {
    tiles.push({ col: c, row: 3, buf: await extractTile(SRC.pathObj, T*c, T*14) });
  }

  const buf = await composeTileset(256, 64, tiles);
  await sharp(buf).toFile(path.join(OUT, 'decorations.png'));
  console.log('  ✓ decorations.png');
}

// ═══════════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════════

async function main() {
  console.log('🏛️  QUAEST Tileset Assembler');
  console.log('  Source packs:', PACKS);
  console.log('  Output:', OUT);
  console.log('');

  await buildTerrain();
  await buildBuildings();
  await buildDecorations();

  console.log('');
  console.log('✅ All tilesets assembled! Refresh the game to see real art.');
}

main().catch(err => {
  console.error('❌ Assembly failed:', err.message);
  process.exit(1);
});
