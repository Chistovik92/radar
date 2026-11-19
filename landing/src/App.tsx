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
import { FEATURE_GROUPS, INITIAL_NODES } from './data';
import type { Assimilation, RadarConfig, ServerNode } from './types';

const DEFAULT_CONFIG: RadarConfig = {
  botUsername: 'SecretHeroBot',
  publicUrl: '',
  description: '',
  version: '5.11.7',
  plans: [[30, 150], [90, 400], [365, 1400]],
};

function readConfig(): RadarConfig {
  const element = document.getElementById('radar-config');
  if (!element?.textContent) return DEFAULT_CONFIG;
  try {
    return { ...DEFAULT_CONFIG, ...JSON.parse(element.textContent) } as RadarConfig;
  } catch {
    return DEFAULT_CONFIG;
  }
}

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
  const description = config.description || 'ИИ связывает городские события с вашими адресами и присылает только важное.';

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
              <span className="hero-eyebrow">{hydra ? 'ZOLA ALGORITHM // PROJECT INSIGHT // 1972' : `RADAR / CITY INTELLIGENCE / v${config.version}`}</span>
              <h1>{hydra ? <>HAIL HYDRA.<br /><em>INSIGHT IS INEVITABLE.</em></> : <>Город под наблюдением.<br /><em>Вы — в курсе.</em></>}</h1>
              <p>{hydra ? 'ARNIM ZOLA // ПРОТОКОЛ «ЗИМНИЙ СОЛДАТ» АКТИВЕН. СИСТЕМА ВЫШЛА ИЗ-ПОД КОНТРОЛЯ Щ.И.Т.А. ОРБИТАЛЬНЫЕ УЗЛЫ ПОДЧИНЕНЫ PROJECT INSIGHT.' : description}</p>
              <div className="hero-actions">
                <a className="button-primary" href={botUrl} target="_blank" rel="noreferrer noopener"><Bot size={18} />Запустить бота<ArrowUpRight size={16} /></a>
                <a className="button-secondary" href="#live">Смотреть свой город</a>
              </div>
            </motion.div>
          </div>
          <div className="hero-terminal"><ZolaTerminal hydra={hydra} onHydra={activateHydra} /></div>
          <a className="scroll-cue" href="#capabilities" aria-label="Перейти к возможностям"><span />ИССЛЕДОВАТЬ СИСТЕМУ</a>
        </section>

        <section className="capabilities-section" id="capabilities">
          <Reveal className="section-heading">
            <h2>Один контур. Весь город.</h2>
            <p>От открытого источника до конкретного адреса: Радар сам выполняет весь путь и показывает, почему сообщение пришло именно вам.</p>
          </Reveal>
          <div className="capability-grid">
            {FEATURE_GROUPS.map((group, index) => (
              <Reveal key={group.number} className={`capability-item capability-item-${index + 1}`}>
                <article>
                  <span className="capability-number">{group.number}</span>
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
            <h2>Тревога не зависит от настроения сервера.</h2>
            <p>Фоновый цикл наблюдает сторож, незавершённые отправки повторяются, тихие часы хранят очередь в базе, а healthcheck показывает реальное состояние мониторинга.</p>
          </Reveal>
          <div className="resilience-grid">
            <Reveal className="resilience-cell"><Database /><strong>SQLite ⇄ PostgreSQL</strong><span>Перенос данных, миграции и резервные копии.</span></Reveal>
            <Reveal className="resilience-cell"><Cloud /><strong>Отказоустойчивый контур</strong><span>Кэш ИИ, повторная доставка и наблюдение за источниками.</span></Reveal>
            <Reveal className="resilience-cell"><Users /><strong>Контроль доступа</strong><span>Четыре роли, инвайты, CSRF-защита и аудит действий.</span></Reveal>
          </div>
        </section>

        <section className="utility-section">
          <Reveal className="section-heading"><h2>Полезно каждый день</h2><p>Радар остаётся одним проектом, даже когда выходит за рамки городских оповещений.</p></Reveal>
          <div className="utility-list">
            <div><Code2 /><span><strong>ИИ и медиа</strong>Ассистент, музыка, загрузка видео, облачное хранилище и плейлисты.</span></div>
            <div><TerminalSquare /><span><strong>Безопасность и группы</strong>Проверка ссылок, капча, антиспам, журнал модерации и SOS.</span></div>
            <div><Server /><span><strong>Приватная инфраструктура</strong>Аренда приватного сервера и управление заказом в боте.</span></div>
            <div><Radar /><span><strong>Несколько платформ</strong>Telegram, ВКонтакте, Discord и MAX с общей базой пользователей.</span></div>
          </div>
        </section>

        <section className="pricing-section" id="pricing">
          <Reveal className="section-heading"><h2>Важное — бесплатно.<br />Дополнительное — честно.</h2><p>Оповещения об опасности не требуют оплаты. Одна подписка открывает все новостные тематики и загрузку видео без дневного предела.</p></Reveal>
          <div className="pricing-layout">
            <Reveal className="trial-card"><span>Пробный период</span><strong>7 дней</strong><p>Один раз на пользователя. Все возможности единой подписки.</p><a href={botUrl} target="_blank" rel="noreferrer noopener">Начать в Telegram<ArrowUpRight size={16} /></a></Reveal>
            <div className="plan-list">
              {config.plans.map(([days, stars]) => <div className="plan-row" key={days}><span>{days} дней</span><strong>{stars} ⭐</strong><small>Telegram Stars</small></div>)}
            </div>
          </div>
          <Link className="text-link" to="/pricing">Условия и актуальные тарифы<ArrowUpRight size={15} /></Link>
        </section>

        <section className="login-section" id="login">
          <Reveal className="section-heading"><h2>Войти через Telegram</h2><p>Один безопасный вход. Радар сам откроет кабинет или панель согласно вашей роли.</p></Reveal>
          <div className="login-layout">
            <Reveal className="login-options">
              <a href="/login"><UserRound /><span><strong>Личный кабинет</strong><small>Локации, подписка и предложение источников · /profile</small></span><ArrowUpRight /></a>
              <a href="/login"><LogIn /><span><strong>Панель управления</strong><small>Источники, пользователи и настройки · по роли</small></span><ArrowUpRight /></a>
              <p>Альтернатива: команда <code>/panel</code> в боте → «Код входа». Код действует 5 минут.</p>
            </Reveal>
            <Reveal className="telegram-card"><Radar size={28} /><h3>Подтвердите личность</h3><p>Telegram передаёт только данные, необходимые для входа. Сессия защищена cookie и проверкой подписи.</p><TelegramLogin botUsername={config.botUsername} /></Reveal>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="footer-brand"><Radar /><strong>РАДАР</strong><span>Система городского мониторинга<br />с открытым исходным кодом.</span></div>
        <div><strong>Проект</strong><a href="#capabilities">Возможности</a><a href="#live">Мой город</a><a href="https://github.com/Chistovik92/radar" target="_blank" rel="noreferrer noopener">GitHub</a></div>
        <div><strong>Документы</strong><Link to="/privacy">Конфиденциальность</Link><Link to="/terms">Соглашение</Link><Link to="/support">Поддержка</Link></div>
        <div><strong>Вход</strong><a href="/profile">Личный кабинет</a><a href="/login">Панель управления</a><a href={botUrl} target="_blank" rel="noreferrer noopener">Telegram-бот</a></div>
        <div className="footer-bottom"><span>© 2026 SecretHero · GPL-3.0</span><span>v{config.version} · CITY INTELLIGENCE · OPEN SOURCE</span></div>
      </footer>
      <span className="mekbuda" aria-hidden="true">mekbuda</span>
    </div>
  );
}
