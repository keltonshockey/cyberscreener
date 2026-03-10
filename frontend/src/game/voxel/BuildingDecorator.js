/**
 * QUAEST.TECH — Building Decorator
 * Adds Roman architectural details (pediments, colonnades, arched facades, etc.)
 * to building exterior and roof GeomCollectors after the base mesh is built.
 *
 * Called per-building with access to exterior + roof collectors so decorative
 * geometry merges into the same mesh for efficient rendering.
 */

import { BLOCK_SIZE, BUILDING_DEFS } from '../config.js';

/**
 * Decorate a building's exterior with architectural features.
 * @param {string} buildingId - Key into BUILDING_DEFS
 * @param {{ exterior: GeomCollector, roof: GeomCollector, interior: GeomCollector }} collectors
 * @param {object} atlas - Texture atlas
 */
export function decorateBuilding(buildingId, collectors, atlas) {
  const def = BUILDING_DEFS[buildingId];
  if (!def || !def.features) return;

  const b = def.bounds;
  const features = def.features;

  for (const feature of features) {
    switch (feature) {
      // ── Curia features ──
      case 'pitched_roof':
        _addPitchedRoof(b, def, collectors.roof, atlas);
        break;
      case 'pediment':
        _addPediment(b, def, collectors.exterior, atlas);
        break;
      case 'entrance_columns':
        _addEntranceColumns(b, def, collectors.exterior, atlas);
        break;
      case 'corner_pilasters':
        _addCornerPilasters(b, def, collectors.exterior, atlas);
        break;
      case 'narrow_windows':
        _addNarrowWindows(b, def, collectors.exterior, atlas);
        break;

      // ── Basilica features ──
      case 'colonnade':
        _addColonnade(b, def, collectors.exterior, atlas);
        break;
      case 'nave_roof':
        _addNaveRoof(b, def, collectors.roof, atlas);
        break;
      case 'tiered_roof':
        _addTieredRoof(b, def, collectors.roof, atlas);
        break;
      case 'regular_windows':
        _addRegularWindows(b, def, collectors.exterior, atlas);
        break;
      case 'engaged_columns':
        _addEngagedColumns(b, def, collectors.exterior, atlas);
        break;

      // ── Subura features ──
      case 'flat_terracotta_roof':
        _addFlatTerracottaRoof(b, def, collectors.roof, atlas);
        break;
      case 'uneven_roof':
        _addUnevenRoof(b, def, collectors.roof, atlas);
        break;
      case 'market_stalls':
        _addMarketStalls(b, def, collectors.exterior, atlas);
        break;
      case 'awning':
        _addAwning(b, def, collectors.exterior, atlas);
        break;

      // ── Tabularium features ──
      case 'arched_facade':
        _addArchedFacade(b, def, collectors.exterior, atlas);
        break;
      case 'grand_portico':
        _addGrandPortico(b, def, collectors.exterior, atlas);
        break;
      case 'crenellated_parapet':
        _addCrenellatedParapet(b, def, collectors.roof, atlas);
        break;
      case 'corner_turrets':
        _addCornerTurrets(b, def, collectors.roof, atlas);
        break;
    }
  }
}

// ─────────────────────────────────────────────────────────────
//  HELPER: add a decorative block to a collector
// ─────────────────────────────────────────────────────────────

function _addDecoBlock(col, row, baseY, height, topTex, sideTex, collector, atlas) {
  collector.addBlock(col, row, baseY, height, topTex, sideTex, atlas);
}

// Wall height helper — different buildings have different wall heights
function _wallH(def) {
  // Match the block type height from the building's wall texture
  const tex = def.wallTexSide;
  if (tex === 'curia_wall_side') return 4;
  if (tex === 'basilica_wall_side') return 4;
  if (tex === 'subura_wall_side') return 3;
  if (tex === 'tabularium_wall_side') return 5;
  return 3;
}

// ─────────────────────────────────────────────────────────────
//  CURIA — Roman Senate House
//  Austere, rectangular, pediment above entrance, tall columns
// ─────────────────────────────────────────────────────────────

/** Stepped triangular pediment above the door */
function _addPediment(b, def, col, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh; // stacks on wall

  if (def.doorSide === 'bottom') {
    // Pediment runs along the bottom edge, centered over the door
    const doorCenter = b.x + def.doorOffset;
    const halfW = Math.floor(b.w / 2);

    // Level 1: wide base spanning most of the front
    for (let dx = -halfW + 2; dx <= halfW - 2; dx++) {
      _addDecoBlock(doorCenter + dx, b.y + b.h - 1, topY, 0.6,
        def.wallTexTop, def.wallTexSide, col, atlas);
    }
    // Level 2: narrower
    for (let dx = -halfW + 4; dx <= halfW - 4; dx++) {
      _addDecoBlock(doorCenter + dx, b.y + b.h - 1, topY + 0.6, 0.4,
        def.wallTexTop, def.wallTexSide, col, atlas);
    }
    // Level 3: peak
    for (let dx = -1; dx <= 1; dx++) {
      _addDecoBlock(doorCenter + dx, b.y + b.h - 1, topY + 1.0, 0.3,
        def.wallTexTop, def.wallTexSide, col, atlas);
    }
  } else if (def.doorSide === 'top') {
    const doorCenter = b.x + def.doorOffset;
    const halfW = Math.floor(b.w / 2);
    for (let dx = -halfW + 2; dx <= halfW - 2; dx++) {
      _addDecoBlock(doorCenter + dx, b.y, topY, 0.6,
        def.wallTexTop, def.wallTexSide, col, atlas);
    }
    for (let dx = -halfW + 4; dx <= halfW - 4; dx++) {
      _addDecoBlock(doorCenter + dx, b.y, topY + 0.6, 0.4,
        def.wallTexTop, def.wallTexSide, col, atlas);
    }
    for (let dx = -1; dx <= 1; dx++) {
      _addDecoBlock(doorCenter + dx, b.y, topY + 1.0, 0.3,
        def.wallTexTop, def.wallTexSide, col, atlas);
    }
  }
}

/** Two tall columns flanking the entrance door */
function _addEntranceColumns(b, def, col, atlas) {
  const doorC = b.x + def.doorOffset;
  const doorW = def.doorWidth;

  if (def.doorSide === 'bottom') {
    const row = b.y + b.h; // one tile outside the building
    // Left column
    _addDecoBlock(doorC - 1, row, 1, 5, 'column_top', 'column_side', col, atlas);
    // Right column
    _addDecoBlock(doorC + doorW, row, 1, 5, 'column_top', 'column_side', col, atlas);
  } else if (def.doorSide === 'top') {
    const row = b.y - 1; // one tile outside
    _addDecoBlock(doorC - 1, row, 1, 5, 'column_top', 'column_side', col, atlas);
    _addDecoBlock(doorC + doorW, row, 1, 5, 'column_top', 'column_side', col, atlas);
  }
}

/** Pilasters at all 4 corners of the building */
function _addCornerPilasters(b, def, col, atlas) {
  const wh = _wallH(def);
  const corners = [
    [b.x, b.y],
    [b.x + b.w - 1, b.y],
    [b.x, b.y + b.h - 1],
    [b.x + b.w - 1, b.y + b.h - 1],
  ];
  for (const [cx, cy] of corners) {
    // Taller column on top of existing wall
    _addDecoBlock(cx, cy, 1 + wh, 1.5, 'column_top', 'column_side', col, atlas);
  }
}

/** Narrow window blocks at intervals along side walls (upper portion) */
function _addNarrowWindows(b, def, col, atlas) {
  const wh = _wallH(def);
  // Left wall (col = b.x), windows every 3 tiles
  for (let r = b.y + 2; r < b.y + b.h - 2; r += 3) {
    _addDecoBlock(b.x - 1, r, 1 + wh - 1.5, 1.0, null, 'window_side', col, atlas);
  }
  // Right wall
  for (let r = b.y + 2; r < b.y + b.h - 2; r += 3) {
    _addDecoBlock(b.x + b.w, r, 1 + wh - 1.5, 1.0, null, 'window_side', col, atlas);
  }
}

// ─────────────────────────────────────────────────────────────
//  BASILICA — Colonnaded Hall of Justice
//  Colonnade along front, tiered roof, engaged columns on sides
// ─────────────────────────────────────────────────────────────

/** Row of columns every 2 tiles along the front */
function _addColonnade(b, def, col, atlas) {
  if (def.doorSide === 'bottom') {
    const row = b.y + b.h; // outside front
    for (let c = b.x; c <= b.x + b.w - 1; c += 2) {
      _addDecoBlock(c, row, 1, 5, 'column_top', 'column_side', col, atlas);
    }
  } else if (def.doorSide === 'top') {
    const row = b.y - 1;
    for (let c = b.x; c <= b.x + b.w - 1; c += 2) {
      _addDecoBlock(c, row, 1, 5, 'column_top', 'column_side', col, atlas);
    }
  }
}

/** Center section of roof higher than edges (stepped parapet) */
function _addTieredRoof(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;

  // Center 60% gets an extra tier
  const margin = Math.floor(b.w * 0.2);
  for (let c = b.x + margin; c < b.x + b.w - margin; c++) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r++) {
      _addDecoBlock(c, r, topY, 0.8, def.wallTexTop, def.wallTexSide, roofCol, atlas);
    }
  }
  // Peak ridge along center row
  const midRow = b.y + Math.floor(b.h / 2);
  for (let c = b.x + margin + 1; c < b.x + b.w - margin - 1; c++) {
    _addDecoBlock(c, midRow, topY + 0.8, 0.4, def.wallTexTop, def.wallTexSide, roofCol, atlas);
  }
}

/** Evenly spaced window blocks along both long walls */
function _addRegularWindows(b, def, col, atlas) {
  const wh = _wallH(def);
  // Windows along top and bottom walls every 2 tiles
  for (let c = b.x + 1; c < b.x + b.w - 1; c += 2) {
    // Top wall
    _addDecoBlock(c, b.y - 1, 1 + wh - 1.5, 1.0, null, 'window_side', col, atlas);
    // Bottom wall
    _addDecoBlock(c, b.y + b.h, 1 + wh - 1.5, 1.0, null, 'window_side', col, atlas);
  }
}

/** Pilasters between windows on side walls */
function _addEngagedColumns(b, def, col, atlas) {
  const wh = _wallH(def);
  // Left and right side walls
  for (let r = b.y + 1; r < b.y + b.h - 1; r += 3) {
    _addDecoBlock(b.x - 1, r, 1, wh + 1, 'column_top', 'column_side', col, atlas);
    _addDecoBlock(b.x + b.w, r, 1, wh + 1, 'column_top', 'column_side', col, atlas);
  }
}

// ─────────────────────────────────────────────────────────────
//  SUBURA — Market District
//  Rough stone, uneven roofline, market stalls, awnings
// ─────────────────────────────────────────────────────────────

/** Left half height lower, right half higher (irregular roofline) */
function _addUnevenRoof(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;
  const midCol = b.x + Math.floor(b.w / 2);

  // Right half gets an extra half-block of height
  for (let c = midCol; c < b.x + b.w; c++) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r++) {
      _addDecoBlock(c, r, topY, 0.5, def.wallTexTop, def.wallTexSide, roofCol, atlas);
    }
  }
  // Random-ish raised patches on left for variety
  for (let c = b.x + 1; c < midCol; c += 3) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r += 2) {
      _addDecoBlock(c, r, topY, 0.3, def.wallTexTop, def.wallTexSide, roofCol, atlas);
    }
  }
}

/** Low shelf/counter blocks outside entrance (market stalls) */
function _addMarketStalls(b, def, col, atlas) {
  if (def.doorSide === 'top') {
    const row = b.y - 1;
    // Stalls flanking entrance
    for (let c = b.x; c < b.x + def.doorOffset - 1; c += 2) {
      _addDecoBlock(c, row, 1, 1.5, 'shelf_top', 'shelf_side', col, atlas);
    }
    for (let c = b.x + def.doorOffset + def.doorWidth + 1; c < b.x + b.w; c += 2) {
      _addDecoBlock(c, row, 1, 1.5, 'shelf_top', 'shelf_side', col, atlas);
    }
  } else if (def.doorSide === 'bottom') {
    const row = b.y + b.h;
    for (let c = b.x; c < b.x + def.doorOffset - 1; c += 2) {
      _addDecoBlock(c, row, 1, 1.5, 'shelf_top', 'shelf_side', col, atlas);
    }
    for (let c = b.x + def.doorOffset + def.doorWidth + 1; c < b.x + b.w; c += 2) {
      _addDecoBlock(c, row, 1, 1.5, 'shelf_top', 'shelf_side', col, atlas);
    }
  }
}

/** 1-block overhang above door (awning) using banner texture */
function _addAwning(b, def, col, atlas) {
  const doorC = b.x + def.doorOffset;
  const doorW = def.doorWidth;

  if (def.doorSide === 'top') {
    for (let c = doorC - 1; c <= doorC + doorW; c++) {
      _addDecoBlock(c, b.y - 1, 1 + 2.5, 0.3, 'banner_top', 'banner_side', col, atlas);
    }
  } else if (def.doorSide === 'bottom') {
    for (let c = doorC - 1; c <= doorC + doorW; c++) {
      _addDecoBlock(c, b.y + b.h, 1 + 2.5, 0.3, 'banner_top', 'banner_side', col, atlas);
    }
  }
}

// ─────────────────────────────────────────────────────────────
//  TABULARIUM — State Archives
//  Massive, imposing: arched facade, grand portico, crenellated parapet
// ─────────────────────────────────────────────────────────────

/** Tall pilasters every 3 tiles along front face */
function _addArchedFacade(b, def, col, atlas) {
  const wh = _wallH(def);
  if (def.doorSide === 'top') {
    const row = b.y;
    for (let c = b.x; c <= b.x + b.w - 1; c += 3) {
      // Tall pilaster alongside wall
      _addDecoBlock(c, row - 1, 1, wh + 1.5, 'column_top', 'column_side', col, atlas);
    }
    // Arch blocks between pilasters at mid-height
    for (let c = b.x + 1; c <= b.x + b.w - 2; c += 3) {
      _addDecoBlock(c, row - 1, 1 + wh - 1.5, 1.2, null, 'arch_side', col, atlas);
    }
  } else if (def.doorSide === 'bottom') {
    const row = b.y + b.h - 1;
    for (let c = b.x; c <= b.x + b.w - 1; c += 3) {
      _addDecoBlock(c, row + 1, 1, wh + 1.5, 'column_top', 'column_side', col, atlas);
    }
    for (let c = b.x + 1; c <= b.x + b.w - 2; c += 3) {
      _addDecoBlock(c, row + 1, 1 + wh - 1.5, 1.2, null, 'arch_side', col, atlas);
    }
  }
}

/** 4 thick columns flanking entrance */
function _addGrandPortico(b, def, col, atlas) {
  const doorC = b.x + def.doorOffset;
  const doorW = def.doorWidth;

  if (def.doorSide === 'top') {
    const row = b.y - 1;
    // 2 columns on each side of door
    _addDecoBlock(doorC - 2, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
    _addDecoBlock(doorC - 1, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
    _addDecoBlock(doorC + doorW, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
    _addDecoBlock(doorC + doorW + 1, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
  } else if (def.doorSide === 'bottom') {
    const row = b.y + b.h;
    _addDecoBlock(doorC - 2, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
    _addDecoBlock(doorC - 1, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
    _addDecoBlock(doorC + doorW, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
    _addDecoBlock(doorC + doorW + 1, row, 1, 6, 'pillar_top', 'pillar_side', col, atlas);
  }
}

/** Notched parapet blocks along entire roof perimeter */
function _addCrenellatedParapet(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;

  // Place alternating blocks around the perimeter (every other tile)
  // Top edge
  for (let c = b.x; c < b.x + b.w; c += 2) {
    _addDecoBlock(c, b.y, topY, 0.8, 'parapet_top', def.wallTexSide, roofCol, atlas);
  }
  // Bottom edge
  for (let c = b.x; c < b.x + b.w; c += 2) {
    _addDecoBlock(c, b.y + b.h - 1, topY, 0.8, 'parapet_top', def.wallTexSide, roofCol, atlas);
  }
  // Left edge
  for (let r = b.y + 1; r < b.y + b.h - 1; r += 2) {
    _addDecoBlock(b.x, r, topY, 0.8, 'parapet_top', def.wallTexSide, roofCol, atlas);
  }
  // Right edge
  for (let r = b.y + 1; r < b.y + b.h - 1; r += 2) {
    _addDecoBlock(b.x + b.w - 1, r, topY, 0.8, 'parapet_top', def.wallTexSide, roofCol, atlas);
  }
}

// ─────────────────────────────────────────────────────────────
//  HISTORICALLY ACCURATE ROOF TYPES
// ─────────────────────────────────────────────────────────────

/**
 * CURIA — Pitched gable roof (like a Roman temple)
 * Simple two-slope A-frame with terracotta tiles.
 * Historical: The Curia Julia had a steep gabled bronze roof.
 */
function _addPitchedRoof(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;

  // The ridge runs along the longer axis (east-west for wider buildings)
  const midRow = b.y + Math.floor(b.h / 2);
  const halfDepth = Math.floor(b.h / 2);

  // Build stepped triangular cross-section along the depth
  // Layer 0: full width flat base
  for (let c = b.x; c < b.x + b.w; c++) {
    for (let r = b.y; r < b.y + b.h; r++) {
      _addDecoBlock(c, r, topY, 0.4, 'terracotta_top', 'terracotta_side', roofCol, atlas);
    }
  }

  // Layer 1: narrower (1 tile in from each depth edge)
  for (let c = b.x; c < b.x + b.w; c++) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r++) {
      _addDecoBlock(c, r, topY + 0.4, 0.4, 'terracotta_top', 'terracotta_side', roofCol, atlas);
    }
  }

  // Layer 2: even narrower (2 tiles in)
  for (let c = b.x; c < b.x + b.w; c++) {
    for (let r = b.y + 2; r < b.y + b.h - 2; r++) {
      _addDecoBlock(c, r, topY + 0.8, 0.4, 'terracotta_top', 'terracotta_side', roofCol, atlas);
    }
  }

  // Layer 3: ridge beam (center 2 rows)
  for (let c = b.x; c < b.x + b.w; c++) {
    for (let r = midRow - 1; r <= midRow; r++) {
      _addDecoBlock(c, r, topY + 1.2, 0.3, 'terracotta_top', 'terracotta_side', roofCol, atlas);
    }
  }
}

/**
 * BASILICA — Nave roof with raised clerestory
 * Historical: Roman basilicas had a high central nave with lower side aisles.
 * The central nave roof was raised, with clerestory windows letting light in.
 * Covered with clay tiles (tegulae and imbrices).
 */
function _addNaveRoof(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;

  // Side aisles: low flat sections on left and right thirds
  const aisleW = Math.floor(b.w / 4);

  // Left aisle - low roof
  for (let c = b.x; c < b.x + aisleW; c++) {
    for (let r = b.y; r < b.y + b.h; r++) {
      _addDecoBlock(c, r, topY, 0.5, 'tile_roof_top', 'tile_roof_side', roofCol, atlas);
    }
  }

  // Right aisle - low roof
  for (let c = b.x + b.w - aisleW; c < b.x + b.w; c++) {
    for (let r = b.y; r < b.y + b.h; r++) {
      _addDecoBlock(c, r, topY, 0.5, 'tile_roof_top', 'tile_roof_side', roofCol, atlas);
    }
  }

  // Central nave - raised section
  for (let c = b.x + aisleW; c < b.x + b.w - aisleW; c++) {
    for (let r = b.y; r < b.y + b.h; r++) {
      _addDecoBlock(c, r, topY, 1.2, 'tile_roof_top', 'tile_roof_side', roofCol, atlas);
    }
  }

  // Ridge beam along center of nave
  const midCol = b.x + Math.floor(b.w / 2);
  for (let r = b.y; r < b.y + b.h; r++) {
    _addDecoBlock(midCol, r, topY + 1.2, 0.3, 'terracotta_top', 'terracotta_side', roofCol, atlas);
  }
}

/**
 * SUBURA — Flat terracotta/thatch roof with uneven patches
 * Historical: Insulae (Roman apartment blocks) had flat roofs
 * covered with terracotta tiles, often patched with thatch/wood.
 * The poor district had mismatched, irregular roofing.
 */
function _addFlatTerracottaRoof(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;

  // Main flat terracotta layer
  for (let c = b.x; c < b.x + b.w; c++) {
    for (let r = b.y; r < b.y + b.h; r++) {
      _addDecoBlock(c, r, topY, 0.3, 'terracotta_top', 'terracotta_side', roofCol, atlas);
    }
  }

  // Uneven patches - some areas have thatch patches (higher/lower)
  const midCol = b.x + Math.floor(b.w / 2);
  // Right half slightly raised (different building section)
  for (let c = midCol; c < b.x + b.w; c++) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r++) {
      _addDecoBlock(c, r, topY + 0.3, 0.3, 'thatch_top', 'thatch_side', roofCol, atlas);
    }
  }

  // Random raised patches on left (repairs/additions)
  for (let c = b.x + 1; c < midCol; c += 3) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r += 2) {
      _addDecoBlock(c, r, topY + 0.3, 0.2, 'thatch_top', 'thatch_side', roofCol, atlas);
    }
  }

  // Wood beam accents across the top
  for (let c = b.x; c < b.x + b.w; c += 4) {
    for (let r = b.y; r < b.y + b.h; r++) {
      _addDecoBlock(c, r, topY + 0.3, 0.15, 'shelf_top', 'shelf_side', roofCol, atlas);
    }
  }
}

/**
 * TABULARIUM — Corner turrets (watchtower-like projections)
 * Historical: The Tabularium was a massive state building overlooking
 * the Forum. Its imposing design included projecting corner elements
 * that doubled as defensive positions. Stone/slate roofing.
 */
function _addCornerTurrets(b, def, roofCol, atlas) {
  const wh = _wallH(def);
  const topY = 1 + wh;

  // Flat slate roof over main building
  for (let c = b.x + 1; c < b.x + b.w - 1; c++) {
    for (let r = b.y + 1; r < b.y + b.h - 1; r++) {
      _addDecoBlock(c, r, topY, 0.4, 'slate_top', 'slate_side', roofCol, atlas);
    }
  }

  // 4 corner turrets (2x2 blocks, taller than main roof)
  const turretH = 2.5;
  const corners = [
    [b.x, b.y],                         // top-left
    [b.x + b.w - 2, b.y],              // top-right
    [b.x, b.y + b.h - 2],              // bottom-left
    [b.x + b.w - 2, b.y + b.h - 2],   // bottom-right
  ];

  for (const [cx, cy] of corners) {
    // Turret walls (tall extension of corner)
    _addDecoBlock(cx, cy, topY, turretH, 'slate_top', def.wallTexSide, roofCol, atlas);
    _addDecoBlock(cx + 1, cy, topY, turretH, 'slate_top', def.wallTexSide, roofCol, atlas);
    _addDecoBlock(cx, cy + 1, topY, turretH, 'slate_top', def.wallTexSide, roofCol, atlas);
    _addDecoBlock(cx + 1, cy + 1, topY, turretH, 'slate_top', def.wallTexSide, roofCol, atlas);

    // Turret cap (slightly wider parapet at top)
    _addDecoBlock(cx, cy, topY + turretH, 0.3, 'parapet_top', def.wallTexSide, roofCol, atlas);
    _addDecoBlock(cx + 1, cy, topY + turretH, 0.3, 'parapet_top', def.wallTexSide, roofCol, atlas);
    _addDecoBlock(cx, cy + 1, topY + turretH, 0.3, 'parapet_top', def.wallTexSide, roofCol, atlas);
    _addDecoBlock(cx + 1, cy + 1, topY + turretH, 0.3, 'parapet_top', def.wallTexSide, roofCol, atlas);
  }
}
