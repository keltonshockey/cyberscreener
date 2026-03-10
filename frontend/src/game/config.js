/**
 * QUAEST.TECH — Game Configuration
 * Runtime constants and brand colors for both 2D (legacy) and 3D voxel rendering.
 */

// Legacy 2D isometric (kept for reference / rollback)
export const TILE_W = 64;
export const TILE_H = 32;
export const TILE_SIZE = 64;
export const PLAYER_SPEED = 100;

// 3D Voxel world constants
export const BLOCK_SIZE = 1;        // 1 world unit per block
export const MAP_COLS = 50;
export const MAP_ROWS = 40;
export const VOXEL_PLAYER_SPEED = 5; // blocks per second

// 3rd-person orbit camera
export const CAMERA_FOV = 60;
export const CAMERA_DISTANCE = 15;       // default orbit radius
export const CAMERA_MIN_DISTANCE = 5;
export const CAMERA_MAX_DISTANCE = 40;
export const CAMERA_MIN_PHI = 0.15;      // min vertical angle (avoid ground)
export const CAMERA_MAX_PHI = 1.4;       // max vertical angle (avoid zenith)
export const CAMERA_ORBIT_SPEED = 0.005; // mouse drag sensitivity
export const CAMERA_LERP = 0.08;         // smooth follow factor
export const CAMERA_INDOOR_DISTANCE = 8; // closer zoom when inside a building
export const CAMERA_FOLLOW_LERP = 0.03;  // how fast camera auto-rotates behind player
export const CAMERA_FOLLOW_PAUSE = 2000; // ms to pause follow after manual orbit

// Brand colors (used by UI overlays, not tile rendering)
export const COLORS = {
  IMPERIAL_PURPLE: 0x4E0B59,
  DENARIUS_SILVER: 0xA6A6A6,
  MARBLE_WHITE: 0xF2F2F2,
  OXIDIZED_BRONZE: 0x665D1E,
  FORGE_RED: 0x8B2500,
  FORGE_AMBER: 0xB8860B,
};

// Building definitions — bounds, door positions, and decorator features
export const BUILDING_DEFS = {
  curia: {
    bounds: { x: 3, y: 3, w: 12, h: 10 },
    doorSide: 'bottom', doorOffset: 5, doorWidth: 2,
    features: ['pitched_roof', 'entrance_columns', 'corner_pilasters', 'narrow_windows'],
    interiorDistance: 8,
    wallTexSide: 'curia_wall_side', wallTexTop: 'curia_wall_top',
  },
  basilica: {
    bounds: { x: 35, y: 3, w: 12, h: 10 },
    doorSide: 'bottom', doorOffset: 5, doorWidth: 2,
    features: ['colonnade', 'nave_roof', 'regular_windows', 'engaged_columns'],
    interiorDistance: 8,
    wallTexSide: 'basilica_wall_side', wallTexTop: 'basilica_wall_top',
  },
  subura: {
    bounds: { x: 3, y: 27, w: 14, h: 10 },
    doorSide: 'top', doorOffset: 6, doorWidth: 2,
    features: ['flat_terracotta_roof', 'market_stalls', 'awning'],
    interiorDistance: 9,
    wallTexSide: 'subura_wall_side', wallTexTop: 'subura_wall_top',
  },
  tabularium: {
    bounds: { x: 33, y: 27, w: 14, h: 10 },
    doorSide: 'top', doorOffset: 6, doorWidth: 2,
    features: ['arched_facade', 'grand_portico', 'crenellated_parapet', 'corner_turrets'],
    interiorDistance: 9,
    wallTexSide: 'tabularium_wall_side', wallTexTop: 'tabularium_wall_top',
  },
};

// Static district info for React sidebar legend
// (the actual zone rectangles are in the Tiled map's Zones object layer)
export const DISTRICT_INFO = [
  { id: 'forum', name: 'The Forum', labelColor: '#4E0B59' },
  { id: 'curia', name: 'The Curia', labelColor: '#B8860B', locked: 'STEEL' },
  { id: 'basilica_julia', name: 'Basilica Julia', labelColor: '#665D1E' },
  { id: 'subura', name: 'The Subura', labelColor: '#666666' },
  { id: 'tabularium', name: 'The Tabularium', labelColor: '#8B2500' },
];
