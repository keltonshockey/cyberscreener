/**
 * QUAEST.TECH — Block Type Definitions
 * Maps GID ranges from the Tiled map to 3D block properties.
 * Each block type defines height (in cube units), solidity, and texture keys.
 */

// Block type definitions
export const BLOCK_TYPES = {
  grass:       { height: 1, solid: false, top: 'grass_top',    side: 'grass_side' },
  stone:       { height: 1, solid: false, top: 'stone_top',    side: 'stone_side' },
  marble:      { height: 1, solid: false, top: 'marble_top',   side: 'marble_side' },
  road:        { height: 1, solid: false, top: 'road_top',     side: 'road_side' },
  water:       { height: 0.7, solid: true,  top: 'water_top',   side: 'water_side' },
  void:        { height: 0, solid: true,  top: null,           side: null },
  int_floor:   { height: 1, solid: false, top: 'int_floor_top', side: 'stone_side' },
  shadow:      { height: 1, solid: false, top: 'stone_top',    side: 'stone_side' },
  wall:        { height: 3, solid: true,  top: 'wall_top',     side: 'wall_side' },
  wall_surface:{ height: 3, solid: true,  top: 'wall_top',     side: 'wall_light_side' },
  wall_dark:   { height: 3, solid: true,  top: 'wall_top',     side: 'wall_dark_side' },
  wall_light:  { height: 3, solid: true,  top: 'wall_top',     side: 'wall_light_side' },
  door:        { height: 3, solid: false, top: 'wall_top',     side: 'door_side' },
  shelf:       { height: 2, solid: true,  top: 'shelf_top',    side: 'shelf_side' },
  window_wall: { height: 3, solid: true,  top: 'wall_top',     side: 'window_side' },
  parapet:     { height: 3, solid: true,  top: 'parapet_top',  side: 'wall_side' },
  pillar:      { height: 4, solid: true,  top: 'pillar_top',   side: 'pillar_side' },
  column:      { height: 4, solid: true,  top: 'column_top',   side: 'column_side' },
  banner:      { height: 3, solid: false, top: 'banner_top',   side: 'banner_side' },
  tree_trunk:  { height: 4, solid: true,  top: 'trunk_top',    side: 'trunk_side' },
  fountain:    { height: 2, solid: true,  top: 'fountain_top', side: 'fountain_side' },
  tree_canopy: { height: 3, solid: false, top: 'leaf_top',     side: 'leaf_side' },
  wall_parapet:{ height: 4, solid: true,  top: 'parapet_top',  side: 'wall_side' },
  // Building-specific walls
  curia_wall:      { height: 4, solid: true,  top: 'curia_wall_top',      side: 'curia_wall_side' },
  basilica_wall:   { height: 4, solid: true,  top: 'basilica_wall_top',   side: 'basilica_wall_side' },
  subura_wall:     { height: 3, solid: true,  top: 'subura_wall_top',     side: 'subura_wall_side' },
  tabularium_wall: { height: 5, solid: true,  top: 'tabularium_wall_top', side: 'tabularium_wall_side' },
  curia_door:      { height: 4, solid: false, top: 'curia_wall_top',      side: 'door_side' },
  basilica_door:   { height: 4, solid: false, top: 'basilica_wall_top',   side: 'door_side' },
  subura_door:     { height: 3, solid: false, top: 'subura_wall_top',     side: 'door_side' },
  tabularium_door: { height: 5, solid: false, top: 'tabularium_wall_top', side: 'door_side' },
  pediment:        { height: 1, solid: true,  top: 'curia_wall_top',      side: 'pediment_side' },
  arch_block:      { height: 3, solid: true,  top: 'tabularium_wall_top', side: 'arch_side' },
};

// GID range to block type mapping
// Each entry: [minGid, maxGid, blockType]
const GID_RANGES = [
  // Terrain (firstgid=1)
  [1,  8,  'grass'],
  [9,  16, 'stone'],
  [17, 24, 'marble'],
  [25, 32, 'road'],
  [33, 36, 'water'],
  [37, 40, 'void'],
  [41, 44, 'int_floor'],
  [45, 48, 'shadow'],
  // Buildings (firstgid=61)
  [61, 66, 'wall'],
  [67, 70, 'wall_surface'],
  [71, 72, 'wall_dark'],
  [73, 74, 'wall_light'],
  [75, 76, 'door'],
  [77, 78, 'shelf'],
  [79, 80, 'window_wall'],
  [81, 84, 'parapet'],
  // Decorations (firstgid=101)
  [101, 102, 'pillar'],
  [103, 104, 'column'],
  [105, 106, 'banner'],
  [107, 108, 'tree_trunk'],
  [109, 110, 'fountain'],
  [111, 114, 'tree_canopy'],
  [115, 118, 'wall_parapet'],
  // Building-specific (firstgid=121)
  [121, 122, 'curia_wall'],
  [123, 124, 'basilica_wall'],
  [125, 126, 'subura_wall'],
  [127, 128, 'tabularium_wall'],
  [129, 130, 'curia_door'],
  [131, 132, 'basilica_door'],
  [133, 134, 'subura_door'],
  [135, 136, 'tabularium_door'],
  [137, 138, 'pediment'],
  [139, 140, 'arch_block'],
];

// Build a fast lookup array (max GID ~150)
const _lookup = new Array(150).fill(null);
for (const [min, max, type] of GID_RANGES) {
  for (let gid = min; gid <= max; gid++) {
    _lookup[gid] = type;
  }
}

/**
 * Get block type name from a tile GID.
 * @param {number} gid - Tile GID from map data
 * @returns {string|null} Block type key, or null if empty/unknown
 */
export function getBlockType(gid) {
  if (gid <= 0 || gid >= _lookup.length) return null;
  return _lookup[gid];
}

/**
 * Get full block definition from a tile GID.
 * @param {number} gid - Tile GID from map data
 * @returns {object|null} Block definition with height, solid, top, side
 */
export function getBlockDef(gid) {
  const type = getBlockType(gid);
  if (!type) return null;
  return BLOCK_TYPES[type];
}
