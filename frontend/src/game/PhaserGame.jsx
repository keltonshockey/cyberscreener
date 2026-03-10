/**
 * QUAEST.TECH — Phaser Game React Wrapper
 * Manages Phaser lifecycle within React, passes callbacks for cross-framework communication.
 */

import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react';
import Phaser from 'phaser';
import { BootScene } from './scenes/BootScene.js';
import { WorldScene } from './scenes/WorldScene.js';

const PhaserGame = forwardRef(function PhaserGame({ onDistrictChange, onInteract, width, height }, ref) {
  const containerRef = useRef(null);
  const gameRef = useRef(null);
  const callbacksRef = useRef({ onDistrictChange, onInteract });

  // Keep callbacks ref updated without re-creating game
  callbacksRef.current = { onDistrictChange, onInteract };

  // Expose game instance to parent
  useImperativeHandle(ref, () => ({
    getGame: () => gameRef.current,
    getScene: (key) => gameRef.current?.scene?.getScene(key),
  }));

  useEffect(() => {
    if (!containerRef.current || gameRef.current) return;

    const config = {
      type: Phaser.AUTO,
      parent: containerRef.current,
      width: width || 800,
      height: height || 480,
      pixelArt: true,
      antialias: false,
      roundPixels: true,
      backgroundColor: '#111111',
      physics: {
        default: 'arcade',
        arcade: {
          gravity: { y: 0 },
          debug: false,
        },
      },
      scene: [BootScene, WorldScene],
      scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
        width: 800,
        height: 480,
      },
    };

    const game = new Phaser.Game(config);
    gameRef.current = game;

    // Store callbacks ref in the game registry so scenes can access them
    game.registry.set('callbacks', callbacksRef);

    return () => {
      if (gameRef.current) {
        gameRef.current.destroy(true);
        gameRef.current = null;
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        aspectRatio: '5 / 3',
        background: '#111',
        borderRadius: 12,
        overflow: 'hidden',
        imageRendering: 'pixelated',
      }}
    />
  );
});

export { PhaserGame };
