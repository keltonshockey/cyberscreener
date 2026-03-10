/**
 * QUAEST.TECH — NPC Data Registry
 * Data-driven definitions for all NPCs. Keyed by npcId.
 * spriteKey, dialog, behavior, etc. are all defined here.
 * WorldScene reads spawn positions from the Tiled object layer
 * and looks up behavior/dialog from this registry.
 */

export const NPC_REGISTRY = {
  praetorian_guard: {
    spriteKey: 'npc-guard',
    name: 'Praetorian Guard',
    dialog: [
      'Halt! The Curia is reserved for STEEL+ rank citizens.',
      'Move along, citizen. Only the proven may enter.',
      'The Emperor watches over us all.',
    ],
    behavior: 'patrol',
    patrolPath: [
      { x: 0, y: 0 },
      { x: 48, y: 0 },
      { x: 48, y: 32 },
      { x: 0, y: 32 },
    ],
    patrolSpeed: 40,
    pauseDuration: 2000,
    facing: 'down',
    interactRadius: 40,
  },

  basilica_guard: {
    spriteKey: 'npc-guard',
    name: 'Basilica Guard',
    dialog: [
      'Welcome to the Basilica Julia. Pin your Scrolls to the pillars.',
      'Only strategies forged in The Forge may be displayed here.',
      'The Scrolls of the wise line these halls.',
    ],
    behavior: 'idle',
    facing: 'left',
    interactRadius: 40,
  },

  marcus_merchant: {
    spriteKey: 'npc-merchant',
    name: 'Marcus the Merchant',
    dialog: [
      'Buy low, sell high — the oldest strategy in Rome.',
      'I have scrolls, analysis, and market rumors.',
      'The Anvil is where the real trades are forged.',
    ],
    behavior: 'wander',
    wanderRadius: 48,
    wanderSpeed: 30,
    wanderPause: 3000,
    facing: 'down',
    interactRadius: 40,
  },

  seneca_scholar: {
    spriteKey: 'npc-scholar',
    name: 'Seneca the Scholar',
    dialog: [
      'The Archives hold great wisdom. Study the data before you forge.',
      'Patience and analysis — the twin pillars of profit.',
      'Every great strategy begins with research.',
    ],
    behavior: 'idle',
    facing: 'down',
    interactRadius: 40,
  },

  market_vendor: {
    spriteKey: 'npc-vendor',
    name: 'Market Vendor',
    dialog: [
      'Fresh analysis, hot off the scroll! Visit the Anvil for options plays.',
      'Step right up! The best signals in the Subura.',
      'Conviction scores, RC grades — I have it all!',
    ],
    behavior: 'idle',
    facing: 'right',
    interactRadius: 40,
  },

  archivist: {
    spriteKey: 'npc-archivist',
    name: 'Archivist',
    dialog: [
      'The Tabularium stores all records. Backtest your strategies here.',
      'Every trade tells a story. The Archive remembers them all.',
      'Quintile analysis reveals the truth behind the scores.',
    ],
    behavior: 'idle',
    facing: 'left',
    interactRadius: 40,
  },
};
