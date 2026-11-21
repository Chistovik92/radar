import type { RadarConfig } from './types';

export const DEFAULT_CONFIG: RadarConfig = {
  botUsername: 'SecretHeroBot',
  publicUrl: '',
  description: '',
  version: '6.0.2',
  plans: [[30, 150], [90, 400], [365, 1400]],
};

export function readConfig(): RadarConfig {
  const element = document.getElementById('radar-config');
  if (!element?.textContent) return DEFAULT_CONFIG;
  try {
    return { ...DEFAULT_CONFIG, ...JSON.parse(element.textContent) } as RadarConfig;
  } catch {
    return DEFAULT_CONFIG;
  }
}

/** Сервер уже слил meta со схемой; локальный fallback нужен старому HTML. */
export function pageContent<T extends Record<string, unknown>>(key: string, fallback: T): T {
  const value = readConfig().content?.[key];
  return value && typeof value === 'object' && !Array.isArray(value) ? value as T : fallback;
}
