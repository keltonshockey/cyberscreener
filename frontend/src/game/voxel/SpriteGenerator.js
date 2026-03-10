/**
 * QUAEST.TECH — Procedural Sprite Generator
 * Generates 4-direction walk-cycle sprite sheets using canvas pixel art.
 * Returns a canvas that can be used as a Three.js texture source.
 *
 * Sheet layout: 4 cols × 4 rows of 32×48 frames
 * Row 0=down, 1=left, 2=right, 3=up
 * Cols 0-3 = walk animation frames
 */

const FRAME_W = 32;
const FRAME_H = 48;
const COLS = 4;
const ROWS = 4;

// ── Character palettes ──

const PALETTES = {
  player: {
    skin:     '#D4A574',
    skinDark: '#B88A5C',
    hair:     '#4A3020',
    tunic:    '#F0E8DC',    // cream toga
    tunicDark:'#D4C8B0',
    accent:   '#5A1068',    // purple trim
    belt:     '#8B6B43',
    sandal:   '#8B5A2B',
    sandalDark:'#6B3A0B',
    eye:      '#2A2A2A',
  },
  legionary: {
    skin:     '#D4A574',
    skinDark: '#B88A5C',
    hair:     '#3A2A1A',
    tunic:    '#8B2500',    // red military tunic
    tunicDark:'#6B1500',
    accent:   '#C8A830',    // gold armor trim
    belt:     '#6B4423',
    sandal:   '#5A3A1B',
    sandalDark:'#3A1A0B',
    eye:      '#2A2A2A',
    helmet:   '#C8A830',    // bronze helmet
    helmetDark:'#A08020',
    shield:   '#8B2500',
    shieldTrim:'#C8A830',
  },
  senator: {
    skin:     '#D4A574',
    skinDark: '#B88A5C',
    hair:     '#A0A0A0',    // grey/white for elder
    tunic:    '#F5F0E8',    // pure white toga
    tunicDark:'#E0D8C8',
    accent:   '#C8A830',    // gold trim (senatorial)
    belt:     '#C8A830',
    sandal:   '#8B5A2B',
    sandalDark:'#6B3A0B',
    eye:      '#2A2A2A',
  },
  merchant: {
    skin:     '#C89860',
    skinDark: '#A87840',
    hair:     '#3A2810',
    tunic:    '#A08050',    // brown working tunic
    tunicDark:'#806030',
    accent:   '#B87333',    // terracotta
    belt:     '#6B4423',
    sandal:   '#5A3A1B',
    sandalDark:'#3A1A0B',
    eye:      '#2A2A2A',
    apron:    '#C4A070',
  },
  scholar: {
    skin:     '#D4A574',
    skinDark: '#B88A5C',
    hair:     '#2A1A0A',
    tunic:    '#3A3050',    // dark scholarly robes
    tunicDark:'#2A2040',
    accent:   '#5A1068',    // purple
    belt:     '#4A3020',
    sandal:   '#4A2A1B',
    sandalDark:'#3A1A0B',
    eye:      '#2A2A2A',
    scroll:   '#E8D8B0',
  },
  guard: {
    skin:     '#C89860',
    skinDark: '#A87840',
    hair:     '#2A1A0A',
    tunic:    '#8B2500',    // military red
    tunicDark:'#6B1500',
    accent:   '#C8A830',
    belt:     '#5A3A1B',
    sandal:   '#5A3A1B',
    sandalDark:'#3A1A0B',
    eye:      '#2A2A2A',
    helmet:   '#C8A830',
    helmetDark:'#A08020',
  },
  vendor: {
    skin:     '#C89860',
    skinDark: '#A87840',
    hair:     '#4A3020',
    tunic:    '#708060',    // muted green tunic
    tunicDark:'#506040',
    accent:   '#B87333',
    belt:     '#8B6B43',
    sandal:   '#6B4423',
    sandalDark:'#4B2403',
    eye:      '#2A2A2A',
    apron:    '#A09070',
  },
  archivist: {
    skin:     '#D4A574',
    skinDark: '#B88A5C',
    hair:     '#606060',    // grey
    tunic:    '#484058',    // dark purple-grey robes
    tunicDark:'#383048',
    accent:   '#5A1068',
    belt:     '#4A3020',
    sandal:   '#4A2A1B',
    sandalDark:'#3A1A0B',
    eye:      '#2A2A2A',
    scroll:   '#E8D8B0',
  },
};

// ── Drawing helpers ──

function px(ctx, x, y, color) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, 1, 1);
}

function rect(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}

// ── Body part drawers ──
// All coordinates relative to frame origin (0,0)
// Frame is 32×48, character centered ~16px wide

/**
 * Draw a character frame.
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} pal - character palette
 * @param {'down'|'left'|'right'|'up'} dir - facing direction
 * @param {number} frame - animation frame (0-3)
 */
function drawCharacter(ctx, pal, dir, frame) {
  const cx = 16; // center X of character
  const legOffset = [0, -1, 0, 1][frame]; // walk cycle leg offset

  if (dir === 'down') {
    _drawFront(ctx, pal, cx, legOffset, frame);
  } else if (dir === 'up') {
    _drawBack(ctx, pal, cx, legOffset, frame);
  } else if (dir === 'left') {
    _drawSide(ctx, pal, cx, legOffset, frame, -1);
  } else {
    _drawSide(ctx, pal, cx, legOffset, frame, 1);
  }
}

function _drawFront(ctx, pal, cx, legOff, frame) {
  // ── Sandals / Feet (bottom) ──
  const footY = 43;
  rect(ctx, cx - 5, footY + legOff, 3, 3, pal.sandal);
  rect(ctx, cx + 2, footY - legOff, 3, 3, pal.sandal);
  px(ctx, cx - 5, footY + 2 + legOff, pal.sandalDark);
  px(ctx, cx + 4, footY + 2 - legOff, pal.sandalDark);

  // ── Legs ──
  rect(ctx, cx - 4, 36 + legOff, 2, 7, pal.skin);
  rect(ctx, cx + 2, 36 - legOff, 2, 7, pal.skin);

  // ── Tunic (body) ──
  rect(ctx, cx - 6, 20, 12, 17, pal.tunic);
  // Tunic shading (right side darker)
  rect(ctx, cx + 2, 22, 4, 13, pal.tunicDark);
  // Tunic bottom hem fold
  rect(ctx, cx - 6, 35, 12, 2, pal.tunicDark);

  // ── Belt ──
  rect(ctx, cx - 6, 30, 12, 2, pal.belt);

  // ── Accent trim ──
  rect(ctx, cx - 6, 20, 12, 1, pal.accent);
  // Vertical stripe (toga fold or decoration)
  rect(ctx, cx - 1, 21, 2, 14, pal.accent);

  // ── Arms ──
  rect(ctx, cx - 8, 22, 2, 10, pal.skin);
  rect(ctx, cx + 6, 22, 2, 10, pal.skin);
  // Sleeve tops
  rect(ctx, cx - 8, 20, 2, 3, pal.tunic);
  rect(ctx, cx + 6, 20, 2, 3, pal.tunic);

  // ── Head ──
  rect(ctx, cx - 4, 8, 8, 12, pal.skin);
  // Jaw shadow
  rect(ctx, cx - 4, 17, 8, 2, pal.skinDark);

  // ── Hair ──
  rect(ctx, cx - 5, 6, 10, 5, pal.hair);
  px(ctx, cx - 5, 11, pal.hair); // sideburn left
  px(ctx, cx + 4, 11, pal.hair); // sideburn right

  // ── Face ──
  px(ctx, cx - 2, 12, pal.eye); // left eye
  px(ctx, cx + 1, 12, pal.eye); // right eye
  px(ctx, cx - 1, 15, pal.skinDark); // mouth
  px(ctx, cx, 15, pal.skinDark);

  // ── Helmet (if legionary/guard) ──
  if (pal.helmet) {
    rect(ctx, cx - 5, 4, 10, 6, pal.helmet);
    rect(ctx, cx - 6, 6, 12, 2, pal.helmetDark); // brim
    rect(ctx, cx - 2, 2, 4, 3, pal.helmet); // crest
    px(ctx, cx - 1, 1, pal.helmetDark);
    px(ctx, cx, 1, pal.helmetDark);
  }

  // ── Apron (merchant/vendor) ──
  if (pal.apron) {
    rect(ctx, cx - 4, 28, 8, 8, pal.apron);
    rect(ctx, cx - 4, 28, 8, 1, pal.belt);
  }

  // ── Scroll (scholar/archivist) ──
  if (pal.scroll) {
    rect(ctx, cx + 6, 26, 3, 8, pal.scroll);
    rect(ctx, cx + 6, 26, 3, 1, pal.belt);
    rect(ctx, cx + 6, 33, 3, 1, pal.belt);
  }

  // Arm swing animation
  if (frame === 1 || frame === 3) {
    // Arms slightly forward/back
    rect(ctx, cx - 8, 21 + (frame === 1 ? -1 : 1), 2, 10, pal.skin);
    rect(ctx, cx + 6, 21 + (frame === 1 ? 1 : -1), 2, 10, pal.skin);
  }
}

function _drawBack(ctx, pal, cx, legOff, frame) {
  // ── Feet ──
  const footY = 43;
  rect(ctx, cx - 5, footY + legOff, 3, 3, pal.sandal);
  rect(ctx, cx + 2, footY - legOff, 3, 3, pal.sandal);

  // ── Legs ──
  rect(ctx, cx - 4, 36 + legOff, 2, 7, pal.skinDark);
  rect(ctx, cx + 2, 36 - legOff, 2, 7, pal.skinDark);

  // ── Tunic (body) ──
  rect(ctx, cx - 6, 20, 12, 17, pal.tunic);
  rect(ctx, cx - 2, 22, 4, 13, pal.tunicDark);
  rect(ctx, cx - 6, 35, 12, 2, pal.tunicDark);

  // ── Belt ──
  rect(ctx, cx - 6, 30, 12, 2, pal.belt);

  // ── Back accent ──
  rect(ctx, cx - 1, 21, 2, 14, pal.accent);

  // ── Arms ──
  rect(ctx, cx - 8, 22, 2, 10, pal.skinDark);
  rect(ctx, cx + 6, 22, 2, 10, pal.skinDark);
  rect(ctx, cx - 8, 20, 2, 3, pal.tunic);
  rect(ctx, cx + 6, 20, 2, 3, pal.tunic);

  // ── Head (back view) ──
  rect(ctx, cx - 4, 8, 8, 12, pal.skinDark);

  // ── Hair (covers back of head) ──
  rect(ctx, cx - 5, 6, 10, 10, pal.hair);

  // ── Helmet ──
  if (pal.helmet) {
    rect(ctx, cx - 5, 4, 10, 8, pal.helmet);
    rect(ctx, cx - 6, 6, 12, 2, pal.helmetDark);
    rect(ctx, cx - 2, 2, 4, 3, pal.helmet);
  }

  if (pal.scroll) {
    rect(ctx, cx + 6, 26, 3, 8, pal.scroll);
    rect(ctx, cx + 6, 26, 3, 1, pal.belt);
    rect(ctx, cx + 6, 33, 3, 1, pal.belt);
  }
}

function _drawSide(ctx, pal, cx, legOff, frame, dir) {
  // dir: -1 = facing left, +1 = facing right
  const ox = dir > 0 ? 0 : 0; // offset for mirroring

  // ── Feet ──
  const footY = 43;
  rect(ctx, cx - 3 + dir, footY + legOff, 4, 3, pal.sandal);
  rect(ctx, cx - 1 - dir, footY - legOff, 4, 3, pal.sandalDark);

  // ── Legs ──
  // Front leg
  rect(ctx, cx - 2 + dir, 36 + legOff, 2, 7, pal.skin);
  // Back leg
  rect(ctx, cx - dir, 36 - legOff, 2, 7, pal.skinDark);

  // ── Tunic ──
  rect(ctx, cx - 5, 20, 10, 17, pal.tunic);
  rect(ctx, cx + (dir > 0 ? 1 : -5), 22, 4, 13, pal.tunicDark);
  rect(ctx, cx - 5, 35, 10, 2, pal.tunicDark);

  // ── Belt ──
  rect(ctx, cx - 5, 30, 10, 2, pal.belt);

  // ── Accent stripe ──
  rect(ctx, cx + (dir > 0 ? -4 : 2), 21, 2, 14, pal.accent);

  // ── Arm (visible side) ──
  const armX = cx + (dir > 0 ? 3 : -5);
  const armSwing = (frame === 1 ? -2 : frame === 3 ? 2 : 0);
  rect(ctx, armX, 22 + armSwing, 2, 10, pal.skin);
  rect(ctx, armX, 20, 2, 3, pal.tunic);

  // ── Head ──
  rect(ctx, cx - 4, 8, 7, 12, pal.skin);
  // Jaw
  rect(ctx, cx - 4, 17, 7, 2, pal.skinDark);

  // ── Hair ──
  rect(ctx, cx - 5 + (dir > 0 ? 1 : 0), 6, 8, 5, pal.hair);
  // Side hair extension
  rect(ctx, cx + (dir > 0 ? -5 : 2), 8, 2, 5, pal.hair);

  // ── Eye (one visible from side) ──
  px(ctx, cx + (dir > 0 ? 1 : -2), 12, pal.eye);

  // ── Nose ──
  px(ctx, cx + (dir > 0 ? 3 : -4), 13, pal.skinDark);

  // ── Helmet ──
  if (pal.helmet) {
    rect(ctx, cx - 5, 4, 9, 6, pal.helmet);
    rect(ctx, cx - 6, 6, 11, 2, pal.helmetDark);
    rect(ctx, cx - 2, 2, 4, 3, pal.helmet);
  }

  // ── Shield (legionary side view) ──
  if (pal.shield && dir > 0) {
    rect(ctx, cx + 4, 22, 3, 12, pal.shield);
    rect(ctx, cx + 4, 22, 3, 1, pal.shieldTrim);
    rect(ctx, cx + 4, 33, 3, 1, pal.shieldTrim);
    rect(ctx, cx + 4, 27, 3, 2, pal.shieldTrim);
  }
  if (pal.shield && dir < 0) {
    rect(ctx, cx - 7, 22, 3, 12, pal.shield);
    rect(ctx, cx - 7, 22, 3, 1, pal.shieldTrim);
    rect(ctx, cx - 7, 33, 3, 1, pal.shieldTrim);
    rect(ctx, cx - 7, 27, 3, 2, pal.shieldTrim);
  }

  // ── Scroll (side view) ──
  if (pal.scroll) {
    const sx = cx + (dir > 0 ? 4 : -6);
    rect(ctx, sx, 28, 2, 6, pal.scroll);
    rect(ctx, sx, 28, 2, 1, pal.belt);
    rect(ctx, sx, 33, 2, 1, pal.belt);
  }

  // ── Apron ──
  if (pal.apron) {
    rect(ctx, cx - 3, 28, 6, 8, pal.apron);
    rect(ctx, cx - 3, 28, 6, 1, pal.belt);
  }
}

// ── Public API ──

const DIR_ORDER = ['down', 'left', 'right', 'up']; // matches DIR_MAP in player/NPC

/**
 * Generate a sprite sheet canvas for the given character type.
 * @param {string} characterType - key into PALETTES (e.g. 'player', 'legionary', 'senator')
 * @returns {HTMLCanvasElement} - 128×192 canvas with 4×4 sprite frames
 */
export function generateSpriteSheet(characterType) {
  const pal = PALETTES[characterType] || PALETTES.player;

  const canvas = document.createElement('canvas');
  canvas.width = FRAME_W * COLS;   // 128
  canvas.height = FRAME_H * ROWS;  // 192
  const ctx = canvas.getContext('2d');

  // Clear to transparent
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Draw each direction row × 4 animation frames
  for (let row = 0; row < ROWS; row++) {
    const dir = DIR_ORDER[row];
    for (let col = 0; col < COLS; col++) {
      ctx.save();
      ctx.translate(col * FRAME_W, row * FRAME_H);
      // Clip to frame
      ctx.beginPath();
      ctx.rect(0, 0, FRAME_W, FRAME_H);
      ctx.clip();
      drawCharacter(ctx, pal, dir, col);
      ctx.restore();
    }
  }

  return canvas;
}

/**
 * Get the character type for an NPC sprite key.
 * Maps old sprite filenames to new procedural types.
 */
export function spriteKeyToCharacterType(spriteKey) {
  const mapping = {
    'npc-guard':     'guard',
    'npc-merchant':  'merchant',
    'npc-scholar':   'scholar',
    'npc-archivist': 'archivist',
    'npc-vendor':    'vendor',
  };
  return mapping[spriteKey] || 'player';
}
