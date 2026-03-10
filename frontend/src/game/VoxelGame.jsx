/**
 * QUAEST.TECH — Voxel Game React Wrapper
 * Manages Three.js VoxelWorld lifecycle within React.
 * Drop-in replacement for PhaserGame.jsx.
 */

import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react';
import { VoxelWorld } from './voxel/VoxelWorld.js';

const VoxelGame = forwardRef(function VoxelGame({ onDistrictChange, onInteract, onBuildingEnter, onBuildingExit }, ref) {
  const containerRef = useRef(null);
  const worldRef = useRef(null);
  const callbacksRef = useRef({ onDistrictChange, onInteract, onBuildingEnter, onBuildingExit });

  // Keep callbacks ref updated without re-creating world
  callbacksRef.current = { onDistrictChange, onInteract, onBuildingEnter, onBuildingExit };

  // Expose world instance to parent
  useImperativeHandle(ref, () => ({
    getWorld: () => worldRef.current,
    setKeyboardEnabled: (enabled) => worldRef.current?.setKeyboardEnabled(enabled),
  }));

  useEffect(() => {
    if (!containerRef.current || worldRef.current) return;

    const world = new VoxelWorld(containerRef.current, {
      onDistrictChange: (...args) => callbacksRef.current.onDistrictChange?.(...args),
      onInteract: (...args) => callbacksRef.current.onInteract?.(...args),
      onBuildingEnter: (...args) => callbacksRef.current.onBuildingEnter?.(...args),
      onBuildingExit: (...args) => callbacksRef.current.onBuildingExit?.(...args),
    });

    worldRef.current = world;
    world.init().catch(console.error);

    return () => {
      if (worldRef.current) {
        worldRef.current.destroy();
        worldRef.current = null;
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
        position: 'relative',
      }}
    />
  );
});

export { VoxelGame };
