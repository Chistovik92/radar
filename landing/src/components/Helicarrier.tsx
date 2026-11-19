import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

const helicarrierVertex = /* glsl */ `
  varying vec3 vPosition;
  varying vec3 vNormal;
  varying vec2 vUv;
  void main() {
    vPosition = position;
    vNormal = normalize(normalMatrix * normal);
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const helicarrierFragment = /* glsl */ `
  uniform float uTime;
  uniform float uHydra;
  varying vec3 vPosition;
  varying vec3 vNormal;
  varying vec2 vUv;

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
    // Базовый цвет металла Хеликериера — темный серо-синий
    vec3 baseColor = mix(vec3(0.12, 0.15, 0.18), vec3(0.08, 0.10, 0.13), vUv.y);
    
    // Панельная структура
    float panels = step(0.5, fract(vPosition.x * 4.5 + vPosition.z * 3.2));
    baseColor *= 0.85 + panels * 0.15;
    
    // Освещение — Fresnel эффект
    float fresnel = pow(1.0 - abs(dot(vNormal, vec3(0.0, 0.0, 1.0))), 2.5);
    vec3 rimLight = vec3(0.2, 0.4, 0.6) * fresnel * 0.4;
    
    // Подсветка двигателей — синие огни
    float engineGlow = smoothstep(0.65, 0.75, abs(vPosition.x)) * smoothstep(0.3, 0.4, abs(vPosition.z));
    vec3 engines = vec3(0.1, 0.5, 1.0) * engineGlow * (0.6 + 0.4 * sin(uTime * 3.0));
    
    // HYDRA mode: красные огни вместо синих
    if (uHydra > 0.5) {
      engines = vec3(1.0, 0.05, 0.05) * engineGlow * (0.7 + 0.3 * sin(uTime * 4.5));
      rimLight = vec3(0.8, 0.1, 0.1) * fresnel * 0.5;
      baseColor = mix(baseColor, vec3(0.15, 0.02, 0.02), uHydra * 0.3);
    }
    
    // Детализация — антенны и структуры
    float detail = noise(vPosition * 8.0) * 0.08;
    
    vec3 color = baseColor + rimLight + engines + vec3(detail);
    
    // Туман для глубины
    float fog = smoothstep(0.0, 20.0, length(vPosition));
    color = mix(color, vec3(0.01, 0.01, 0.02), fog * 0.3);
    
    gl_FragColor = vec4(color, 1.0);
  }
`;

interface HelicarrierProps {
  hydra: boolean;
}

export default function Helicarrier({ hydra }: HelicarrierProps) {
  const mesh = useRef<THREE.Mesh>(null!);
  const material = useRef<THREE.ShaderMaterial>(null!);

  useFrame(({ clock }) => {
    if (!mesh.current || !material.current) return;

    const time = clock.getElapsedTime();
    material.current.uniforms.uTime.value = time;
    material.current.uniforms.uHydra.value = hydra ? 1.0 : 0.0;

    // Патрулирующая траектория — восьмерка в горизонтальной плоскости
    const radius = 12;
    const speed = 0.12;
    mesh.current.position.x = Math.sin(time * speed) * radius;
    mesh.current.position.z = Math.sin(time * speed * 2) * radius * 0.5;
    mesh.current.position.y = 5 + Math.sin(time * speed * 0.5) * 0.8; // Небольшое вертикальное покачивание

    // Наклон по направлению движения
    const dx = Math.cos(time * speed) * radius * speed;
    const dz = Math.cos(time * speed * 2) * radius * speed;
    mesh.current.rotation.y = Math.atan2(dx, dz);
    mesh.current.rotation.z = -dx * 0.05; // Небольшой крен
    mesh.current.rotation.x = dz * 0.03;
  });

  return (
    <mesh ref={mesh} position={[0, 5, 0]}>
      <boxGeometry args={[3.5, 0.4, 2.2]} />
      <shaderMaterial
        ref={material}
        vertexShader={helicarrierVertex}
        fragmentShader={helicarrierFragment}
        uniforms={{
          uTime: { value: 0 },
          uHydra: { value: 0 },
        }}
        side={THREE.DoubleSide}
      />
      
      {/* Мостик Хеликериера */}
      <mesh position={[0, 0.35, 0.2]}>
        <boxGeometry args={[1.2, 0.5, 0.8]} />
        <meshStandardMaterial
          color={hydra ? '#1a0505' : '#1a2530'}
          metalness={0.8}
          roughness={0.3}
          emissive={hydra ? '#440000' : '#002244'}
          emissiveIntensity={0.3}
        />
      </mesh>
      
      {/* Взлетная полоса — декоративные линии */}
      <mesh position={[0, 0.21, 0]}>
        <planeGeometry args={[3.2, 1.8]} />
        <meshBasicMaterial
          color={hydra ? '#220000' : '#1a3040'}
          transparent
          opacity={0.4}
        />
      </mesh>
    </mesh>
  );
}
