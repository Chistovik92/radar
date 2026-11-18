import { Suspense, useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import { Bloom, ChromaticAberration, EffectComposer } from '@react-three/postprocessing';
import * as THREE from 'three';
import BlackHole from './BlackHole';
import HydraTentacles from './HydraTentacles';
import PlanetaryServers from './PlanetaryServers';
import type { SceneProps } from '../types';

function Scene({ hydra, reducedMotion, assimilation, nodes }: SceneProps) {
  const aberration = useMemo(() => new THREE.Vector2(0.0018, 0.0026), []);
  return (
    <>
      <color attach="background" args={['#030407']} />
      <fog attach="fog" args={['#030407', 18, 42]} />
      <ambientLight intensity={0.24} />
      <directionalLight position={[4, 8, 6]} intensity={1.25} color="#e2e8f0" />
      <Suspense fallback={null}>
        <Stars radius={45} depth={24} count={reducedMotion ? 900 : 1800} factor={2.6} saturation={0.15} fade speed={reducedMotion ? 0 : 0.35} />
        <BlackHole hydra={hydra} reducedMotion={reducedMotion} />
        <PlanetaryServers nodes={nodes} hydra={hydra} reducedMotion={reducedMotion} assimilation={assimilation} />
        <HydraTentacles hydra={hydra} reducedMotion={reducedMotion} assimilation={assimilation} />
        {!reducedMotion && (
          <EffectComposer multisampling={0}>
            <Bloom mipmapBlur intensity={hydra ? 1.35 : 0.9} luminanceThreshold={0.24} luminanceSmoothing={0.55} />
            {assimilation ? <ChromaticAberration offset={aberration} radialModulation modulationOffset={0.25} /> : <></>}
          </EffectComposer>
        )}
      </Suspense>
      <OrbitControls
        makeDefault
        enablePan={false}
        enableDamping={!reducedMotion}
        dampingFactor={0.055}
        minDistance={8}
        maxDistance={21}
        minPolarAngle={Math.PI * 0.23}
        maxPolarAngle={Math.PI * 0.76}
        autoRotate={!reducedMotion}
        autoRotateSpeed={0.18}
      />
    </>
  );
}

export default function RadarScene(props: SceneProps) {
  return (
    <Canvas
      className="radar-canvas"
      camera={{ position: [0, 3.4, 14.5], fov: 46, near: 0.1, far: 100 }}
      dpr={[1, 1.55]}
      frameloop={props.reducedMotion ? 'demand' : 'always'}
      gl={{ antialias: false, alpha: false, powerPreference: 'high-performance' }}
    >
      <Scene {...props} />
    </Canvas>
  );
}
