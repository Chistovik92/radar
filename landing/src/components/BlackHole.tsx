import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

const diskVertex = /* glsl */ `
  varying vec3 vPosition;
  varying vec2 vUv;
  void main() {
    vPosition = position;
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const diskFragment = /* glsl */ `
  uniform float uTime;
  uniform float uHydra;
  varying vec3 vPosition;
  varying vec2 vUv;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0)), f.x), f.y);
  }

  float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 5; i++) {
      value += amplitude * noise(p);
      p = p * 2.03 + 7.17;
      amplitude *= 0.5;
    }
    return value;
  }

  void main() {
    float radius = length(vPosition.xy);
    float angle = atan(vPosition.y, vPosition.x);
    float kepler = uTime * (0.45 + 2.2 / max(radius, 0.4));
    vec2 flow = vec2(angle * 3.2 - kepler, radius * 4.6);
    float clouds = fbm(flow + fbm(flow * 1.7));
    float bands = 0.55 + 0.45 * sin(radius * 38.0 + clouds * 7.0 - kepler * 2.0);
    float doppler = 0.72 + 0.48 * cos(angle + 0.35);
    float edge = smoothstep(1.45, 1.7, radius) * (1.0 - smoothstep(3.7, 4.25, radius));
    float alpha = edge * (0.25 + clouds * 0.85) * (0.65 + bands * 0.35);

    vec3 amber = mix(vec3(1.0, 0.32, 0.015), vec3(1.0, 0.87, 0.42), clouds);
    vec3 crimson = mix(vec3(0.25, 0.005, 0.02), vec3(0.86, 0.035, 0.06), clouds);
    vec3 color = mix(amber, crimson, uHydra) * doppler * (1.0 + bands * 0.45);
    gl_FragColor = vec4(color, alpha);
  }
`;

const fresnelVertex = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vView = normalize(-(viewMatrix * world).xyz);
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const fresnelFragment = /* glsl */ `
  uniform float uHydra;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float fresnel = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 5.5);
    vec3 photon = mix(vec3(1.0, 0.95, 0.88), vec3(1.0, 0.12, 0.08), uHydra);
    gl_FragColor = vec4(photon * fresnel * 1.8, fresnel * 0.92);
  }
`;

type BlackHoleProps = { hydra: boolean; reducedMotion: boolean };

export default function BlackHole({ hydra, reducedMotion }: BlackHoleProps) {
  const disk = useRef<THREE.ShaderMaterial>(null);
  const photon = useRef<THREE.ShaderMaterial>(null);
  const halo = useRef<THREE.Group>(null);
  const diskUniforms = useMemo(() => ({
    uTime: { value: 0 },
    uHydra: { value: 0 },
  }), []);
  const photonUniforms = useMemo(() => ({ uHydra: { value: 0 } }), []);

  useFrame(({ clock }, delta) => {
    if (disk.current) {
      if (!reducedMotion) disk.current.uniforms.uTime.value = clock.elapsedTime;
      disk.current.uniforms.uHydra.value = THREE.MathUtils.damp(
        disk.current.uniforms.uHydra.value, hydra ? 1 : 0, 3.5, delta,
      );
    }
    if (photon.current) {
      photon.current.uniforms.uHydra.value = disk.current?.uniforms.uHydra.value ?? 0;
    }
    if (halo.current && !reducedMotion) {
      halo.current.rotation.z = Math.sin(clock.elapsedTime * 0.16) * 0.035;
    }
  });

  return (
    <group>
      <mesh>
        <sphereGeometry args={[1.35, 64, 64]} />
        <meshBasicMaterial color="#000000" />
      </mesh>
      <mesh scale={1.025}>
        <sphereGeometry args={[1.35, 64, 64]} />
        <shaderMaterial
          ref={photon}
          uniforms={photonUniforms}
          vertexShader={fresnelVertex}
          fragmentShader={fresnelFragment}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[1.45, 4.25, 256, 8]} />
        <shaderMaterial
          ref={disk}
          uniforms={diskUniforms}
          vertexShader={diskVertex}
          fragmentShader={diskFragment}
          side={THREE.DoubleSide}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      <group ref={halo}>
        <mesh scale={[1, 1.18, 1]}>
          <torusGeometry args={[1.58, 0.025, 12, 160]} />
          <meshBasicMaterial
            color={hydra ? '#dc2626' : '#fff3e0'}
            transparent
            opacity={0.72}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
        <mesh scale={[1.22, 1.4, 1]} rotation={[0, 0, Math.PI / 2]}>
          <torusGeometry args={[1.58, 0.012, 8, 128]} />
          <meshBasicMaterial
            color={hydra ? '#7f1d1d' : '#ff9e00'}
            transparent
            opacity={0.32}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </mesh>
      </group>
      <pointLight color={hydra ? '#dc2626' : '#ff9e00'} intensity={32} distance={18} decay={2} />
    </group>
  );
}
