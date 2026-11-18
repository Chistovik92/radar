import { useEffect, useMemo, useRef } from 'react';
import { Html, Line } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { Assimilation, ServerNode } from '../types';

const planetVertex = /* glsl */ `
  varying vec3 vPosition;
  varying vec3 vNormal;
  void main() {
    vPosition = position;
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const planetFragment = /* glsl */ `
  uniform float uTime;
  uniform vec3 uColor;
  uniform vec3 uAccent;
  uniform float uHydra;
  varying vec3 vPosition;
  varying vec3 vNormal;

  float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }

  float noise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y),
      f.z
    );
  }

  void main() {
    vec3 p = vPosition * 5.0 + vec3(uTime * 0.025, 0.0, 0.0);
    float terrain = noise(p) * 0.6 + noise(p * 2.1) * 0.3 + noise(p * 4.2) * 0.1;
    float grid = pow(abs(sin(vPosition.y * 22.0)), 28.0) * 0.25;
    float light = 0.32 + 0.68 * max(dot(vNormal, normalize(vec3(0.5, 0.8, 1.0))), 0.0);
    vec3 base = mix(uColor, uAccent, smoothstep(0.58, 0.82, terrain) + grid);
    base = mix(base, vec3(0.48, 0.015, 0.025), uHydra * 0.55);
    gl_FragColor = vec4(base * light, 1.0);
  }
`;

function orbitPoints(radius: number, tilt: number) {
  return Array.from({ length: 129 }, (_, index) => {
    const angle = (index / 128) * Math.PI * 2;
    return new THREE.Vector3(
      Math.cos(angle) * radius,
      Math.sin(angle) * radius * tilt,
      Math.sin(angle) * radius * 0.58,
    );
  });
}

type BodyProps = {
  node: ServerNode;
  hydra: boolean;
  reducedMotion: boolean;
  assimilation: Assimilation | null;
};

function ServerBody({ node, hydra, reducedMotion, assimilation }: BodyProps) {
  const group = useRef<THREE.Group>(null);
  const material = useRef<THREE.ShaderMaterial>(null);
  const beam = useRef<THREE.Line>(null);
  const pulse = useRef<THREE.Mesh>(null);
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uColor: { value: new THREE.Color(node.color) },
    uAccent: { value: new THREE.Color(node.accent) },
    uHydra: { value: 0 },
  }), [node.color, node.accent]);

  useEffect(() => {
    beam.current?.computeLineDistances();
  }, []);

  useFrame(({ clock }, delta) => {
    const object = group.current;
    if (!object) return;
    const time = reducedMotion ? node.phase : clock.elapsedTime * node.speed + node.phase;
    const base = new THREE.Vector3(
      Math.cos(time) * node.radius,
      Math.sin(time) * node.radius * node.tilt,
      Math.sin(time) * node.radius * 0.58,
    );
    const targeted = assimilation?.targetId === node.id;
    if (targeted && assimilation) {
      const elapsed = (performance.now() - assimilation.startedAt) / 1000;
      const pull = THREE.MathUtils.clamp((elapsed - 2.0) / 5.6, 0, 1);
      const eased = pull * pull * (3 - 2 * pull);
      const spiralAngle = time + eased * Math.PI * 6;
      const radius = node.radius * (1 - eased);
      object.position.set(
        Math.cos(spiralAngle) * radius,
        base.y * (1 - eased),
        Math.sin(spiralAngle) * radius * 0.58,
      );
      const shrink = Math.max(0.025, 1 - Math.pow(pull, 2.2));
      object.scale.setScalar(shrink);
      object.visible = pull < 0.995;
    } else {
      object.position.copy(base);
      object.scale.setScalar(1);
      object.visible = true;
    }
    object.rotation.y = reducedMotion ? node.phase : clock.elapsedTime * 0.16 + node.phase;
    if (material.current) {
      material.current.uniforms.uTime.value = reducedMotion ? 0 : clock.elapsedTime;
      material.current.uniforms.uHydra.value = THREE.MathUtils.damp(
        material.current.uniforms.uHydra.value, hydra ? 1 : 0, 4, delta,
      );
    }
    if (beam.current) {
      const positions = beam.current.geometry.attributes.position as THREE.BufferAttribute;
      positions.setXYZ(1, -object.position.x, -object.position.y, -object.position.z);
      positions.needsUpdate = true;
      const beamMaterial = beam.current.material as THREE.LineDashedMaterial & { dashOffset: number };
      beamMaterial.dashOffset = reducedMotion ? 0 : -clock.elapsedTime * 0.65;
      beamMaterial.opacity = targeted ? 0.1 : 0.24;
      beam.current.computeLineDistances();
    }
    if (pulse.current) {
      const progress = reducedMotion ? 0.4 : (clock.elapsedTime * 0.24 + node.phase) % 1;
      pulse.current.position.copy(object.position).multiplyScalar(-progress);
      pulse.current.visible = !targeted;
    }
  });

  return (
    <group ref={group}>
      <mesh>
        <icosahedronGeometry args={[node.size, 5]} />
        <shaderMaterial
          ref={material}
          uniforms={uniforms}
          vertexShader={planetVertex}
          fragmentShader={planetFragment}
        />
      </mesh>
      {node.kind === 'station' && (
        <group rotation={[Math.PI / 2, 0, 0]}>
          {[0, 1, 2].map((arm) => (
            <mesh key={arm} rotation={[0, 0, arm * Math.PI * 2 / 3]} position={[0, node.size * 1.25, 0]}>
              <boxGeometry args={[node.size * 0.28, node.size * 1.9, node.size * 0.22]} />
              <meshStandardMaterial color="#64748b" metalness={0.9} roughness={0.28} emissive={node.accent} emissiveIntensity={0.18} />
            </mesh>
          ))}
          <mesh>
            <torusGeometry args={[node.size * 1.45, 0.025, 8, 64]} />
            <meshBasicMaterial color={node.accent} />
          </mesh>
        </group>
      )}
      {node.kind === 'archive' && (
        <group rotation={[Math.PI / 2, 0, 0]}>
          <mesh>
            <torusGeometry args={[node.size * 1.25, 0.045, 8, 64]} />
            <meshStandardMaterial color="#a8a29e" metalness={0.8} roughness={0.4} />
          </mesh>
          <mesh rotation={[0.4, 0.2, 0]}>
            <torusGeometry args={[node.size * 1.5, 0.018, 8, 64]} />
            <meshBasicMaterial color={node.accent} transparent opacity={0.65} />
          </mesh>
        </group>
      )}
      {node.kind === 'relay' && (
        <group>
          <mesh rotation={[Math.PI / 2.6, 0.2, 0]}>
            <torusGeometry args={[node.size * 1.55, 0.035, 8, 64]} />
            <meshBasicMaterial color={node.accent} transparent opacity={0.8} />
          </mesh>
          <mesh position={[0, node.size * 1.2, 0]}>
            <cylinderGeometry args={[0.025, 0.025, node.size * 1.8, 8]} />
            <meshStandardMaterial color="#94a3b8" metalness={0.85} roughness={0.25} />
          </mesh>
        </group>
      )}
      <primitive
        ref={beam}
        object={useMemo(() => new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
          new THREE.LineDashedMaterial({ color: node.accent, transparent: true, opacity: 0.24, dashSize: 0.16, gapSize: 0.24 }),
        ), [node.accent])}
      />
      <mesh ref={pulse}>
        <sphereGeometry args={[0.035, 8, 8]} />
        <meshBasicMaterial color={node.accent} blending={THREE.AdditiveBlending} />
      </mesh>
      <Html position={[0, node.size + 0.36, 0]} center distanceFactor={15} zIndexRange={[5, 0]}>
        <div className="orbital-label">
          <span>{node.name}</span>
          <small>{node.feature}</small>
        </div>
      </Html>
    </group>
  );
}

function DataAsteroids({ assimilation, reducedMotion }: { assimilation: Assimilation | null; reducedMotion: boolean }) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const group = useRef<THREE.Group>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const particles = useMemo(() => Array.from({ length: 180 }, (_, index) => {
    const angle = index * 2.399963;
    const radius = 3.25 + ((index * 37) % 100) / 100 * 1.25;
    return {
      angle,
      radius,
      y: Math.sin(index * 1.73) * 0.32,
      scale: 0.018 + (index % 7) * 0.009,
    };
  }), []);

  useFrame(({ clock }) => {
    if (group.current && !reducedMotion) group.current.rotation.y = clock.elapsedTime * 0.055;
    if (!mesh.current) return;
    const pull = assimilation
      ? THREE.MathUtils.clamp((performance.now() - assimilation.startedAt - 1800) / 5200, 0, 1)
      : 0;
    particles.forEach((particle, index) => {
      const selected = index % 4 === 0;
      const localPull = selected ? pull : 0;
      const angle = particle.angle + localPull * Math.PI * 5;
      const radius = particle.radius * (1 - localPull * 0.96);
      dummy.position.set(Math.cos(angle) * radius, particle.y * (1 - localPull), Math.sin(angle) * radius * 0.36);
      dummy.rotation.set(angle, angle * 0.7, angle * 0.3);
      dummy.scale.setScalar(particle.scale * (1 - localPull * 0.85));
      dummy.updateMatrix();
      mesh.current!.setMatrixAt(index, dummy.matrix);
    });
    mesh.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <group ref={group} rotation={[0.18, 0, -0.08]}>
      <instancedMesh ref={mesh} args={[undefined, undefined, particles.length]}>
        <dodecahedronGeometry args={[1, 0]} />
        <meshStandardMaterial color="#78716c" metalness={0.65} roughness={0.65} />
      </instancedMesh>
    </group>
  );
}

type Props = {
  nodes: ServerNode[];
  hydra: boolean;
  reducedMotion: boolean;
  assimilation: Assimilation | null;
};

export default function PlanetaryServers({ nodes, hydra, reducedMotion, assimilation }: Props) {
  return (
    <group>
      {nodes.map((node) => (
        <Line
          key={`orbit-${node.id}`}
          points={orbitPoints(node.radius, node.tilt)}
          color={hydra ? '#7f1d1d' : '#64748b'}
          transparent
          opacity={0.16}
          lineWidth={0.45}
        />
      ))}
      <DataAsteroids assimilation={assimilation} reducedMotion={reducedMotion} />
      {nodes.map((node) => (
        <ServerBody key={node.id} node={node} hydra={hydra} reducedMotion={reducedMotion} assimilation={assimilation} />
      ))}
    </group>
  );
}
