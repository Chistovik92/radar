import type { ServerNode } from './types';

export const INITIAL_NODES: ServerNode[] = [
  { id: 'core', name: 'TRISKELION-HUB', alias: 'Центр мониторинга', feature: 'МЧС и городские службы', radius: 4.2, size: 0.5, speed: 0.11, phase: 0.1, tilt: 0.18, color: '#334155', accent: '#f59e0b', kind: 'station' },
  { id: 'archive', name: 'CAMP-LEHIGH-VAULT', alias: 'Архив событий', feature: 'История и источники', radius: 5.5, size: 0.65, speed: -0.075, phase: 1.3, tilt: -0.25, color: '#44403c', accent: '#fbbf24', kind: 'archive' },
  { id: 'chrono', name: 'STRUCKER-CHRONOS', alias: 'Планировщик', feature: 'Тихие часы и подборки', radius: 6.5, size: 0.43, speed: 0.095, phase: 2.7, tilt: 0.32, color: '#164e63', accent: '#22d3ee', kind: 'relay' },
  { id: 'weather', name: 'VORMIR-RELAY', alias: 'Метеорелей', feature: 'Погода по координатам', radius: 7.4, size: 0.56, speed: -0.06, phase: 4.1, tilt: 0.14, color: '#475569', accent: '#38bdf8', kind: 'planet' },
  { id: 'geo', name: 'SIBERIA-1991', alias: 'Географический узел', feature: 'Адресное сопоставление', radius: 8.2, size: 0.72, speed: 0.048, phase: 5.2, tilt: -0.35, color: '#3f3f46', accent: '#f59e0b', kind: 'planet' },
  { id: 'gateway', name: 'TEN-RINGS-GATEWAY', alias: 'Шлюз платформ', feature: 'Telegram, VK, MAX, Discord', radius: 9.1, size: 0.46, speed: -0.055, phase: 3.4, tilt: 0.26, color: '#312e81', accent: '#67e8f9', kind: 'relay' },
];

export const FEATURE_GROUPS = [
  {
    number: '01',
    title: 'Только то, что касается вас',
    text: 'Радар читает открытые каналы МЧС, администраций, ЖКХ и RSS. ИИ выделяет город, улицу, дом и тип события, затем сопоставляет его с вашими адресами.',
    items: ['БПЛА и воздушная тревога', 'ЧС, пожары и эвакуация', 'Вода, свет, газ и отопление', 'Отдельное распознавание отбоя'],
  },
  {
    number: '02',
    title: 'Город живёт в одном интерфейсе',
    text: 'Несколько локаций, тихие часы, местный часовой пояс, погода и новостные подборки по расписанию. Важные тревоги остаются бесплатными.',
    items: ['Почасовой прогноз и три дня', '18 тематик новостных подборок', 'Неограниченное число адресов', 'Русский, English, Українська, 中文 и فارسی'],
  },
  {
    number: '03',
    title: 'Не только оповещения',
    text: 'Проект объединяет повседневные инструменты и средства администрирования, не превращая основной сценарий в набор разрозненных ботов.',
    items: ['ИИ-ассистент с поиском', 'Проверка ссылок и короткие ссылки', 'Музыка, медиа и облачное хранилище', 'Модерация групп и SOS-контакты'],
  },
  {
    number: '04',
    title: 'Ваши данные — под контролем',
    text: 'Открытый исходный код GPL-3.0, прозрачные настройки и выбор SQLite или PostgreSQL для хранения данных проекта.',
    items: ['Резервные копии и перенос базы', 'Роли и аудит действий', 'Метрики, журналы и healthcheck', 'Обновление из панели управления'],
  },
];

export const NORMAL_LOGS = [
  '[MONITOR] source cycle complete :: matching locations',
  '[AI] batch classified :: cache updated',
  '[DELIVERY] alert queue confirmed',
  '[GEO] address index synchronized',
  '[WEATHER] Open-Meteo relay online',
  '[HEALTH] heartbeat persisted :: watchdog armed',
];

export const HYDRA_LOGS = [
  '[16.12.1991] WINTER_SOLDIER_PROTOCOL :: CODE_17 // TARGET: STARK_CONVOY',
  '[ZOLA_AI] Scanning Project Insight targets: Banner_B, Strange_S, Iowa_Valedictorian...',
  '[SEC_CHANNEL] Mitchell Carson -> Ten Rings Syndicate: Yellowjacket_Particles_Transfer [ENCRYPTED]',
  '[MEMORIAL_HASH] Ezekiel 25:17 — "The path of the righteous man..." [STATUS: DECEASED_OVERRIDE]',
  '[TRISKELION] ALEXANDER_PIERCE :: HELICARRIER_SYNC // INSIGHT_01/02/03',
  '[ZOLA_AI] STEVEN_ROGERS :: THREAT_STATUS=SUPER_SOLDIER // NICK_FURY: COMPROMISED',
  '[SIBERIA_1991] LONGING_RUSTED_SEVENTEEN :: WINTER_SOLDIER // COMPLIANT',
];

export const ACTIVATION_PHRASE = 'тоска ржавый семнадцать рассвет печь девять добросердечный возвращение на родину один грузовой вагон';
