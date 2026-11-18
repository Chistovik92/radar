import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { Assimilation } from '../types';

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform float uProgress;
  varying vec2 vUv;
  varying float vWave;
  void main() {
    vUv = uv;
    vec3 transformed = position;
    float envelope = sin(uv.x * 3.14159265);
    float wave = sin(uv.x * 19.0 - uTime * 4.2) * envelope;
    transformed += normal * wave * 0.075 * (0.25 + uProgress);
    transformed.x += sin(uv.x * 11.0 + uTime * 2.1) * envelope * 0.045;
    vWave = wave;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uHydra;
  uniform float uProgress;
  varying vec2 vUv;
  varying float vWave;
  void main() {
    float veins = pow(1.0 - abs(sin(vUv.y * 18.8495 + sin(vUv.x * 13.0))), 12.0);
    float pulse = 0.55 + 0.45 * sin(vUv.x * 30.0 - uTime * 7.0);
    vec3 obsidian = vec3(0.008, 0.012, 0.018) + abs(vWave) * 0.025;
    vec3 energy = mix(vec3(0.05, 0.8, 0.86), vec3(0.95, 0.025, 0.04), uHydra);
    vec3 color = obsidian + energy * veins * pulse * (0.65 + uProgress);
    gl_FragColor = vec4(color, 0.96);
  }
`;

type Tentacle = {
  geometry: THREE.TubeGeometry;
  indexCount: number;
};

export default function HydraTentacles({ assimilation, hydra, reducedMotion }: {
  assimilation: Assimilation | null;
  hydra: boolean;
  reducedMotion: boolean;
}) {
  const meshes = useRef<Array<THREE.Mesh | null>>([]);
  const materials = useRef<Array<THREE.ShaderMaterial | null>>([]);
  const tentacles = useMemo<Tentacle[]>(() => Array.from({ length: 7 }, (_, index) => {
    const angle = index * Math.PI * 2 / 7 + 0.25;
    const direction = new THREE.Vector3(Math.cos(angle), (index % 3 - 1) * 0.22, Math.sin(angle));
    const length = 4.6 + (index % 3) * 1.15;
    const end = direction.clone().multiplyScalar(length);
    const tangent = new THREE.Vector3(-direction.z, 0.25, direction.x);
    const points = [
      direction.clone().multiplyScalar(0.8),
      direction.clone().multiplyScalar(1.7).add(tangent.clone().multiplyScalar(0.45)),
      direction.clone().multiplyScalar(length * 0.58).add(tangent.clone().multiplyScalar(-0.7)),
      end.clone().add(tangent.clone().multiplyScalar(0.55)),
      end.clone().add(direction.clone().multiplyScalar(-0.45)).add(tangent.clone().multiplyScalar(-0.35)),
      end.clone().add(direction.clone().multiplyScalar(-0.75)),
    ];
    const curve = new THREE.CatmullRomCurve3(points);
    const geometry = new THREE.TubeGeometry(curve, 96, 0.075 + index % 2 * 0.018, 8, false);
    return { geometry, indexCount: geometry.index?.count ?? 0 };
  }), []);

  useFrame(({ clock }) => {
    const elapsed = assimilation ? (performance.now() - assimilation.startedAt) / 1000 : 0;
    const growth = assimilation ? THREE.MathUtils.clamp(elapsed / 2.2, 0, 1) : 0;
    const retreat = assimilation ? 1 - THREE.MathUtils.clamp((elapsed - 6.5) / 1.3, 0, 1) : 0;
    tentacles.forEach((tentacle, index) => {
      const mesh = meshes.current[index];
      const material = materials.current[index];
      if (!mesh || !material) return;
      mesh.visible = Boolean(assimilation) && growth > 0.01 && retreat > 0.01;
      mesh.geometry.setDrawRange(0, Math.floor(tentacle.indexCount * growth * retreat / 3) * 3);
      mesh.rotation.y = reducedMotion ? 0 : Math.sin(clock.elapsedTime * 0.8 + index) * 0.035;
      material.uniforms.uTime.value = reducedMotion ? 0 : clock.elapsedTime + index * 0.4;
      material.uniforms.uProgress.value = growth * retreat;
      material.uniforms.uHydra.value = hydra ? 1 : 0;
    });
  });

  return (
    <group>
      {tentacles.map((tentacle, index) => (
        <mesh
          key={index}
          ref={(mesh) => { meshes.current[index] = mesh; }}
          geometry={tentacle.geometry}
          visible={false}
        >
          <shaderMaterial
            ref={(material) => { materials.current[index] = material; }}
            uniforms={{
              uTime: { value: 0 },
              uProgress: { value: 0 },
              uHydra: { value: 0 },
            }}
            vertexShader={vertexShader}
            fragmentShader={fragmentShader}
            side={THREE.DoubleSide}
            transparent
          />
        </mesh>
      ))}
    </group>
  );
}
