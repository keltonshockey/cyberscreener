/**
 * QUAEST.TECH — Procedural Map Generator
 * Generates an 80x60 tile map with Roman districts, roads, buildings, and decorations.
 */

import { MAP_COLS, MAP_ROWS, TILE, DISTRICTS } from '../config.js';

/**
 * Create a 2D array [row][col] filled with the base tile type.
 */
function createBlankMap(fillTile = TILE.GRASS) {
  return Array.from({ length: MAP_ROWS }, () =>
    Array.from({ length: MAP_COLS }, () => fillTile)
  );
}

/**
 * Fill a rectangular region with a tile type.
 */
function fillRect(map, x, y, w, h, tile) {
  for (let r = y; r < y + h && r < MAP_ROWS; r++) {
    for (let c = x; c < x + w && c < MAP_COLS; c++) {
      if (r >= 0 && c >= 0) map[r][c] = tile;
    }
  }
}

/**
 * Draw a hollow rectangle (border only).
 */
function strokeRect(map, x, y, w, h, tile) {
  for (let c = x; c < x + w; c++) {
    if (y >= 0 && y < MAP_ROWS) map[y][c] = tile;
    if (y + h - 1 >= 0 && y + h - 1 < MAP_ROWS) map[y + h - 1][c] = tile;
  }
  for (let r = y; r < y + h; r++) {
    if (x >= 0 && x < MAP_COLS) map[r][x] = tile;
    if (x + w - 1 >= 0 && x + w - 1 < MAP_COLS) map[r][x + w - 1] = tile;
  }
}

/**
 * Place a single tile if in bounds.
 */
function place(map, x, y, tile) {
  if (y >= 0 && y < MAP_ROWS && x >= 0 && x < MAP_COLS) {
    map[y][x] = tile;
  }
}

/**
 * Generate the full world map.
 */
export function generateMap() {
  const map = createBlankMap(TILE.GRASS);

  // ── Outer border walls ──
  strokeRect(map, 0, 0, MAP_COLS, MAP_ROWS, TILE.WALL);
  strokeRect(map, 1, 1, MAP_COLS - 2, MAP_ROWS - 2, TILE.WALL);

  // ── Main roads (cross pattern through center) ──
  // Horizontal road at rows 28-31
  fillRect(map, 2, 28, MAP_COLS - 4, 4, TILE.ROAD);
  // Vertical road at cols 38-41
  fillRect(map, 38, 2, 4, MAP_ROWS - 4, TILE.ROAD);

  // Road borders (stone edging)
  for (let c = 2; c < MAP_COLS - 2; c++) {
    place(map, c, 27, TILE.STONE);
    place(map, c, 32, TILE.STONE);
  }
  for (let r = 2; r < MAP_ROWS - 2; r++) {
    place(map, 37, r, TILE.STONE);
    place(map, 42, r, TILE.STONE);
  }

  // ── THE FORUM (center plaza) ──
  const forum = DISTRICTS.find(d => d.id === 'forum');
  fillRect(map, forum.bounds.x, forum.bounds.y, forum.bounds.w, forum.bounds.h, TILE.MARBLE);

  // Forum border columns
  for (let c = forum.bounds.x; c < forum.bounds.x + forum.bounds.w; c += 4) {
    place(map, c, forum.bounds.y, TILE.COLUMN);
    place(map, c, forum.bounds.y + forum.bounds.h - 1, TILE.COLUMN);
  }
  for (let r = forum.bounds.y; r < forum.bounds.y + forum.bounds.h; r += 4) {
    place(map, forum.bounds.x, r, TILE.COLUMN);
    place(map, forum.bounds.x + forum.bounds.w - 1, r, TILE.COLUMN);
  }

  // Central fountain
  const fx = 38, fy = 28;
  fillRect(map, fx, fy, 4, 4, TILE.WATER);
  // Stone rim around fountain
  for (let c = fx - 1; c <= fx + 4; c++) {
    place(map, c, fy - 1, TILE.STONE);
    place(map, c, fy + 4, TILE.STONE);
  }
  for (let r = fy - 1; r <= fy + 4; r++) {
    place(map, fx - 1, r, TILE.STONE);
    place(map, fx + 4, r, TILE.STONE);
  }

  // Forum banners
  place(map, 30, 22, TILE.BANNER);
  place(map, 50, 22, TILE.BANNER);
  place(map, 30, 37, TILE.BANNER);
  place(map, 50, 37, TILE.BANNER);

  // ── THE CURIA (top-left, elite council) ──
  const curia = DISTRICTS.find(d => d.id === 'curia');
  _buildBuilding(map, curia.bounds, TILE.MARBLE, {
    doorSide: 'bottom',
    doorOffset: 10,
    pillars: true,
    pillarSpacing: 4,
    interior: (x, y, w, h) => {
      // Central raised platform
      fillRect(map, x + 5, y + 3, 10, 6, TILE.MARBLE);
      // Throne columns
      place(map, x + 5, y + 3, TILE.PILLAR);
      place(map, x + 14, y + 3, TILE.PILLAR);
      place(map, x + 5, y + 8, TILE.PILLAR);
      place(map, x + 14, y + 8, TILE.PILLAR);
      // Banners
      place(map, x + 9, y + 2, TILE.BANNER);
      place(map, x + 10, y + 2, TILE.BANNER);
    }
  });

  // ── BASILICA JULIA (top-right, scroll display) ──
  const basilica = DISTRICTS.find(d => d.id === 'basilica_julia');
  _buildBuilding(map, basilica.bounds, TILE.MARBLE, {
    doorSide: 'bottom',
    doorOffset: 10,
    pillars: true,
    pillarSpacing: 3,
    interior: (x, y, w, h) => {
      // Two rows of pillars for scroll display
      for (let c = x + 3; c < x + w - 3; c += 4) {
        place(map, c, y + 4, TILE.PILLAR);
        place(map, c, y + 10, TILE.PILLAR);
      }
      // Display banners on walls
      for (let c = x + 2; c < x + w - 2; c += 3) {
        place(map, c, y + 1, TILE.BANNER);
      }
    }
  });

  // ── THE SUBURA (bottom-left, public market) ──
  const subura = DISTRICTS.find(d => d.id === 'subura');
  _buildBuilding(map, subura.bounds, TILE.STONE, {
    doorSide: 'top',
    doorOffset: 11,
    pillars: false,
    interior: (x, y, w, h) => {
      // Market stalls (rows of shelves)
      for (let r = y + 3; r < y + h - 3; r += 3) {
        fillRect(map, x + 3, r, 6, 1, TILE.SHELF);
        fillRect(map, x + 12, r, 6, 1, TILE.SHELF);
      }
      // Open center aisle
      fillRect(map, x + 9, y + 2, 3, h - 4, TILE.ROAD);
    }
  });

  // ── THE TABULARIUM (bottom-right, archives) ──
  const tab = DISTRICTS.find(d => d.id === 'tabularium');
  _buildBuilding(map, tab.bounds, TILE.STONE, {
    doorSide: 'top',
    doorOffset: 11,
    pillars: true,
    pillarSpacing: 5,
    interior: (x, y, w, h) => {
      // Archive shelves along walls
      for (let r = y + 2; r < y + h - 2; r++) {
        place(map, x + 2, r, TILE.SHELF);
        place(map, x + w - 3, r, TILE.SHELF);
      }
      // Reading tables (columns as furniture)
      place(map, x + 7, y + 5, TILE.COLUMN);
      place(map, x + 7, y + 9, TILE.COLUMN);
      place(map, x + 13, y + 5, TILE.COLUMN);
      place(map, x + 13, y + 9, TILE.COLUMN);
      // Central banner
      place(map, x + 10, y + 2, TILE.BANNER);
    }
  });

  // ── Connecting paths from roads to building doors ──
  // Curia door path (bottom of curia to horizontal road)
  fillRect(map, 14, 20, 2, 8, TILE.ROAD);
  // Basilica Julia door path
  fillRect(map, 66, 20, 2, 8, TILE.ROAD);
  // Subura door path (top of subura to horizontal road)
  fillRect(map, 15, 33, 2, 7, TILE.ROAD);
  // Tabularium door path
  fillRect(map, 65, 33, 2, 7, TILE.ROAD);

  // ── Trees scattered in grass areas ──
  const treePositions = [
    [6, 24], [8, 26], [12, 25], [18, 26],
    [62, 24], [66, 26], [70, 25], [74, 26],
    [6, 34], [10, 36], [16, 35], [20, 33],
    [62, 34], [68, 36], [72, 35], [76, 33],
    [30, 3], [34, 5], [46, 3], [50, 5],
    [30, 55], [34, 57], [46, 55], [50, 57],
    [3, 24], [3, 36], [77, 24], [77, 36],
  ];
  for (const [c, r] of treePositions) {
    if (map[r]?.[c] === TILE.GRASS) {
      place(map, c, r, TILE.TREE);
    }
  }

  return map;
}


/**
 * Build a walled building with floor, door, and optional pillars.
 */
function _buildBuilding(map, bounds, floorTile, opts = {}) {
  const { x, y, w, h } = bounds;

  // Floor
  fillRect(map, x, y, w, h, floorTile);

  // Walls
  strokeRect(map, x, y, w, h, TILE.WALL);

  // Door (2-tile wide opening)
  const doorOff = opts.doorOffset || Math.floor(w / 2);
  if (opts.doorSide === 'bottom') {
    place(map, x + doorOff, y + h - 1, TILE.DOOR);
    place(map, x + doorOff + 1, y + h - 1, TILE.DOOR);
  } else if (opts.doorSide === 'top') {
    place(map, x + doorOff, y, TILE.DOOR);
    place(map, x + doorOff + 1, y, TILE.DOOR);
  } else if (opts.doorSide === 'left') {
    place(map, x, y + doorOff, TILE.DOOR);
    place(map, x, y + doorOff + 1, TILE.DOOR);
  } else if (opts.doorSide === 'right') {
    place(map, x + w - 1, y + doorOff, TILE.DOOR);
    place(map, x + w - 1, y + doorOff + 1, TILE.DOOR);
  }

  // Entrance pillars flanking the door
  if (opts.pillars) {
    const sp = opts.pillarSpacing || 4;
    if (opts.doorSide === 'bottom' || opts.doorSide === 'top') {
      const dr = opts.doorSide === 'bottom' ? y + h - 1 : y;
      // Pillars along the front
      for (let c = x + 2; c < x + w - 2; c += sp) {
        if (map[dr]?.[c] !== TILE.DOOR) {
          place(map, c, dr, TILE.COLUMN);
        }
      }
    }
  }

  // Interior decorations
  if (opts.interior) {
    opts.interior(x + 1, y + 1, w - 2, h - 2);
  }
}


/**
 * Get the district at a given tile position.
 */
export function getDistrictAt(col, row) {
  for (const d of DISTRICTS) {
    const { x, y, w, h } = d.bounds;
    if (col >= x && col < x + w && row >= y && row < y + h) {
      return d;
    }
  }
  return null;
}
