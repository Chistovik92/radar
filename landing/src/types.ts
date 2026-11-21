export type ServerNode = {
  id: string;
  name: string;
  alias: string;
  feature: string;
  radius: number;
  size: number;
  speed: number;
  phase: number;
  tilt: number;
  color: string;
  accent: string;
  kind: 'station' | 'archive' | 'relay' | 'planet';
};

export type Assimilation = {
  id: number;
  targetId: string;
  startedAt: number;
};

export type RadarConfig = {
  botUsername: string;
  publicUrl: string;
  description: string;
  version: string;
  plans: Array<[number, number]>;
  content?: Record<string, Record<string, unknown>>;
};

export type SceneProps = {
  hydra: boolean;
  reducedMotion: boolean;
  assimilation: Assimilation | null;
  nodes: ServerNode[];
  onAssimilationComplete: (targetId: string) => void;
};
