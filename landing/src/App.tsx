import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import {
  ArrowUpRight, Bot, Check, Cloud, Code2, Database,
  LogIn, Radar, Server, ShieldCheck, TerminalSquare, UserRound, Users,
} from 'lucide-react';
import RadarScene from './components/RadarScene';
import HudOverlay from './components/HudOverlay';
import ZolaTerminal from './components/ZolaTerminal';
import LiveWidgets from './components/LiveWidgets';
import TelegramLogin from './components/TelegramLogin';
import { INITIAL_NODES } from './data';
import { pageContent, readConfig } from './content';
import type { Assimilation, ServerNode } from './types';

function Reveal({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduced ? false : { opacity: 0, transform: 'translateY(28px)' }}
      whileInView={{ opacity: 1, transform: 'translateY(0px)' }}
      viewport={{ once: true, amount: 0.16 }}
      transition={{ duration: 0.65, ease: [0.23, 1, 0.32, 1] }}
    >{children}</motion.div>
  );
}

export default function App() {
  const config = useRef(readConfig()).current;
  const content = useRef(pageContent('home', {
    hero_eyebrow: 'RADAR / CITY INTELLIGENCE', hero_title: 'Город под наблюдением.',
    hero_accent: 'Вы — в курсе.', hero_description: 'ИИ связывает городские события с вашими адресами и присылает только важное.',
    hero_primary: 'Запустить бота', hero_secondary: 'Смотреть свой город', scroll_cue: 'ИССЛЕДОВАТЬ СИСТЕМУ',
    capabilities_title: 'Один контур. Весь город.',
    capabilities_text: 'От открытого источника до конкретного адреса: Радар сам выполняет весь путь и показывает, почему сообщение пришло именно вам.',
    capabilities: [
      { title: 'Только то, что касается вас', text: 'Радар читает открытые каналы МЧС, администраций, ЖКХ и RSS. ИИ выделяет город, улицу, дом и тип события, затем сопоставляет его с вашими адресами.', items: ['БПЛА и воздушная тревога', 'ЧС, пожары и эвакуация', 'Вода, свет, газ и отопление', 'Отдельное распознавание отбоя'] },
      { title: 'Город живёт в одном интерфейсе', text: 'Несколько локаций, тихие часы, местный часовой пояс, погода и новостные подборки по расписанию. Важные тревоги остаются бесплатными.', items: ['Почасовой прогноз и три дня', '18 тематик новостных подборок', 'Неограниченное число адресов', 'Русский, English, Українська, 中文 и فارسی'] },
      { title: 'Не только оповещения', text: 'Проект объединяет повседневные инструменты и средства администрирования, не превращая основной сценарий в набор разрозненных ботов.', items: ['ИИ-ассистент с поиском', 'Проверка ссылок и короткие ссылки', 'Музыка, медиа и облачное хранилище', 'Модерация групп и SOS-контакты'] },
      { title: 'Ваши данные — под контролем', text: 'Открытый исходный код GPL-3.0, прозрачные настройки и выбор SQLite или PostgreSQL для хранения данных проекта.', items: ['Резервные копии и перенос базы', 'Роли и аудит действий', 'Метрики, журналы и healthcheck', 'Обновление из панели управления'] },
    ],
    resilience_title: 'Тревога не зависит от настроения сервера.',
    resilience_text: 'Фоновый цикл наблюдает сторож, незавершённые отправки повторяются, тихие часы хранят очередь в базе, а healthcheck показывает реальное состояние мониторинга.',
    resilience: [{ title: 'SQLite ⇄ PostgreSQL', text: 'Перенос данных, миграции и резервные копии.' }, { title: 'Отказоустойчивый контур', text: 'Кэш ИИ, повторная доставка и наблюдение за источниками.' }, { title: 'Контроль доступа', text: 'Четыре роли, инвайты, CSRF-защита и аудит действий.' }],
    utility_title: 'Полезно каждый день', utility_text: 'Радар остаётся одним проектом, даже когда выходит за рамки городских оповещений.',
    utilities: [{ title: 'ИИ и медиа', text: 'Ассистент, музыка, загрузка видео, облачное хранилище и плейлисты.' }, { title: 'Безопасность и группы', text: 'Проверка ссылок, капча, антиспам, журнал модерации и SOS.' }, { title: 'Приватная инфраструктура', text: 'Аренда приватного сервера и управление заказом в боте.' }, { title: 'Несколько платформ', text: 'Telegram, ВКонтакте, Discord и MAX с общей базой пользователей.' }],
    pricing_title: 'Важное — бесплатно.', pricing_accent: 'Дополнительное — честно.',
    pricing_text: 'Оповещения об опасности не требуют оплаты. Одна подписка открывает все новостные тематики и загрузку видео без дневного предела.',
    trial_label: 'Пробный период', trial_days: '7 дней', trial_text: 'Один раз на пользователя. Все возможности единой подписки.', trial_button: 'Начать в Telegram', pricing_link: 'Условия и актуальные тарифы',
    login_title: 'Войти через Telegram', login_text: 'Один безопасный вход. Радар сам откроет кабинет или панель согласно вашей роли.',
    profile_title: 'Личный кабинет', profile_text: 'Локации, подписка и предложение источников · /profile', panel_title: 'Панель управления', panel_text: 'Источники, пользователи и настройки · по роли',
    login_alternative: 'Альтернатива: команда /panel в боте → «Код входа». Код действует 5 минут.', telegram_title: 'Подтвердите личность', telegram_text: 'Telegram передаёт только данные, необходимые для входа. Сессия защищена cookie и проверкой подписи.',
    footer_description: 'Система городского мониторинга\nс открытым исходным кодом.',
  })).current;
  const reducedMotion = Boolean(useReducedMotion());
  const [hydra, setHydra] = useState(false);
  const [nodes, setNodes] = useState<ServerNode[]>(INITIAL_NODES);
  const [assimilation, setAssimilation] = useState<Assimilation | null>(null);
  const eventId = useRef(0);
  const logoClicks = useRef(0);
  const clickReset = useRef<number | undefined>(undefined);

  const startAssimilation = useCallback(() => {
    if (assimilation || reducedMotion || nodes.length === 0) return;
    eventId.current += 1;
    const target = nodes[eventId.current % nodes.length];
    setAssimilation({ id: eventId.current, targetId: target.id, startedAt: performance.now() });
  }, [assimilation, nodes, reducedMotion]);

  const activateHydra = useCallback(() => {
    setHydra(true);
    if (!reducedMotion) {
      eventId.current += 1;
      setAssimilation((current) => current || (nodes.length ? {
        id: eventId.current,
        targetId: nodes[eventId.current % nodes.length].id,
        startedAt: performance.now(),
      } : null));
    }
  }, [nodes, reducedMotion]);

  useEffect(() => {
    document.documentElement.dataset.hydra = hydra ? 'active' : 'inactive';
  }, [hydra]);

  useEffect(() => {
    if (reducedMotion) return;
    const timer = window.setTimeout(startAssimilation, 45000 + Math.random() * 15000);
    return () => window.clearTimeout(timer);
  }, [startAssimilation, reducedMotion]);

  useEffect(() => {
    if (!assimilation) return;
    const current = assimilation;
    const timer = window.setTimeout(() => {
      setNodes((existing) => {
        const target = existing.find((node) => node.id === current.targetId);
        if (!target) return existing;
        const alpha: ServerNode = { ...target, id: `${target.id}-alpha-${current.id}`, name: `${target.name}-ALPHA`, phase: target.phase + 0.5, size: target.size * 0.82 };
        const omega: ServerNode = { ...target, id: `${target.id}-omega-${current.id}`, name: `${target.name}-OMEGA`, phase: target.phase - 0.65, size: target.size * 0.72, speed: -target.speed };
        return [...existing.filter((node) => node.id !== current.targetId), alpha, omega].slice(-8);
      });
      setAssimilation(null);
    }, 8100);
    return () => window.clearTimeout(timer);
  }, [assimilation]);

  const logoClick = () => {
    window.clearTimeout(clickReset.current);
    logoClicks.current += 1;
    if (logoClicks.current >= 3) {
      logoClicks.current = 0;
      activateHydra();
      return;
    }
    clickReset.current = window.setTimeout(() => { logoClicks.current = 0; }, 700);
  };

  const botUrl = `https://t.me/${config.botUsername || 'SecretHeroBot'}`;
  const description = content.hero_description || config.description;

  return (
    <div className={`site-shell ${hydra ? 'hydra-mode' : ''}`}>
      <HudOverlay
        key={hydra ? 'hydra' : 'radar'}
        hydra={hydra}
        eventActive={Boolean(assimilation)}
        nodeCount={nodes.length}
        onLogoClick={logoClick}
        onWhisper={() => setHydra(false)}
      />

      <main>
        <section className="hero-section">
          <div className="scene-layer" aria-label="Интерактивная орбитальная модель Радара">
            <Suspense fallback={<div className="scene-loader">Инициализация ядра…</div>}>
              <RadarScene
                hydra={hydra}
                reducedMotion={reducedMotion}
                assimilation={assimilation}
                nodes={nodes}
                onAssimilationComplete={() => undefined}
              />
            </Suspense>
          </div>
          <div className="hero-vignette" />
          <div className="hero-copy">
            <motion.div
              initial={reducedMotion ? false : { opacity: 0, transform: 'translateY(18px)' }}
              animate={{ opacity: 1, transform: 'translateY(0px)' }}
              transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
            >
              <span className="hero-eyebrow">{hydra ? 'ZOLA ALGORITHM // PROJECT INSIGHT // 1972' : `${content.hero_eyebrow} / v${config.version}`}</span>
              <h1>{hydra ? <>HAIL HYDRA.<br /><em>INSIGHT IS INEVITABLE.</em></> : <>{content.hero_title}<br /><em>{content.hero_accent}</em></>}</h1>
              <p>{hydra ? 'ARNIM ZOLA // ПРОТОКОЛ «ЗИМНИЙ СОЛДАТ» АКТИВЕН. СИСТЕМА ВЫШЛА ИЗ-ПОД КОНТРОЛЯ Щ.И.Т.А. ОРБИТАЛЬНЫЕ УЗЛЫ ПОДЧИНЕНЫ PROJECT INSIGHT.' : description}</p>
              <div className="hero-actions">
                <a className="button-primary" href={botUrl} target="_blank" rel="noreferrer noopener"><Bot size={18} />{content.hero_primary}<ArrowUpRight size={16} /></a>
                <a className="button-secondary" href="#live">{content.hero_secondary}</a>
              </div>
            </motion.div>
          </div>
          <div className="hero-terminal"><ZolaTerminal hydra={hydra} onHydra={activateHydra} /></div>
          <a className="scroll-cue" href="#capabilities" aria-label="Перейти к возможностям"><span />{content.scroll_cue}</a>
        </section>

        <section className="capabilities-section" id="capabilities">
          <Reveal className="section-heading">
            <h2>{content.capabilities_title}</h2>
            <p>{content.capabilities_text}</p>
          </Reveal>
          <div className="capability-grid">
            {content.capabilities.map((group, index) => (
              <Reveal key={group.title} className={`capability-item capability-item-${index + 1}`}>
                <article>
                  <span className="capability-number">{String(index + 1).padStart(2, '0')}</span>
                  <h3>{group.title}</h3>
                  <p>{group.text}</p>
                  <ul>{group.items.map((item) => <li key={item}><Check size={14} />{item}</li>)}</ul>
                </article>
              </Reveal>
            ))}
          </div>
        </section>

        <LiveWidgets />

        <section className="resilience-section">
          <Reveal className="resilience-statement">
            <ShieldCheck size={30} />
            <h2>{content.resilience_title}</h2>
            <p>{content.resilience_text}</p>
          </Reveal>
          <div className="resilience-grid">
            {content.resilience.map((item, index) => {
              const Icon = [Database, Cloud, Users][index] || Database;
              return <Reveal className="resilience-cell" key={item.title}><Icon /><strong>{item.title}</strong><span>{item.text}</span></Reveal>;
            })}
          </div>
        </section>

        <section className="utility-section">
          <Reveal className="section-heading"><h2>{content.utility_title}</h2><p>{content.utility_text}</p></Reveal>
          <div className="utility-list">
            {content.utilities.map((item, index) => {
              const Icon = [Code2, TerminalSquare, Server, Radar][index] || Code2;
              return <div key={item.title}><Icon /><span><strong>{item.title}</strong>{item.text}</span></div>;
            })}
          </div>
        </section>

        <section className="pricing-section" id="pricing">
          <Reveal className="section-heading"><h2>{content.pricing_title}<br />{content.pricing_accent}</h2><p>{content.pricing_text}</p></Reveal>
          <div className="pricing-layout">
            <Reveal className="trial-card"><span>{content.trial_label}</span><strong>{content.trial_days}</strong><p>{content.trial_text}</p><a href={botUrl} target="_blank" rel="noreferrer noopener">{content.trial_button}<ArrowUpRight size={16} /></a></Reveal>
            <div className="plan-list">
              {config.plans.map(([days, stars]) => <div className="plan-row" key={days}><span>{days} дней</span><strong>{stars} ⭐</strong><small>Telegram Stars</small></div>)}
            </div>
          </div>
          <Link className="text-link" to="/pricing">{content.pricing_link}<ArrowUpRight size={15} /></Link>
        </section>

        <section className="login-section" id="login">
          <Reveal className="section-heading"><h2>{content.login_title}</h2><p>{content.login_text}</p></Reveal>
          <div className="login-layout">
            <Reveal className="login-options">
              <a href="/login"><UserRound /><span><strong>{content.profile_title}</strong><small>{content.profile_text}</small></span><ArrowUpRight /></a>
              <a href="/login"><LogIn /><span><strong>{content.panel_title}</strong><small>{content.panel_text}</small></span><ArrowUpRight /></a>
              <p>{content.login_alternative}</p>
            </Reveal>
            <Reveal className="telegram-card"><Radar size={28} /><h3>{content.telegram_title}</h3><p>{content.telegram_text}</p><TelegramLogin botUsername={config.botUsername} /></Reveal>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="footer-brand"><Radar /><strong>РАДАР</strong><span>{content.footer_description.split('\n').map((line, index) => <span key={index}>{index > 0 && <br />}{line}</span>)}</span></div>
        <div><strong>Проект</strong><a href="#capabilities">Возможности</a><a href="#live">Мой город</a><a href="/projects">Наши проекты</a><a href="/downloads">Загрузки</a><a href="https://github.com/Chistovik92/radar" target="_blank" rel="noreferrer noopener">GitHub</a></div>
        <div><strong>Документы</strong><a href="/privacy">Конфиденциальность</a><a href="/terms">Соглашение</a><Link to="/support">Поддержка</Link></div>
        <div><strong>Вход</strong><a href="/profile">Личный кабинет</a><a href="/login">Панель управления</a><a href={botUrl} target="_blank" rel="noreferrer noopener">Telegram-бот</a></div>
        <div className="footer-bottom"><span>© 2026 SecretHero · GPL-3.0</span><span>v{config.version} · CITY INTELLIGENCE · OPEN SOURCE</span></div>
      </footer>
      <span className="mekbuda" aria-hidden="true">mekbuda</span>
    </div>
  );
}
