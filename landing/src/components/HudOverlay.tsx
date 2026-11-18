import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Activity, LogIn, Radar, ShieldCheck, UserRound, X } from 'lucide-react';

type Props = {
  hydra: boolean;
  eventActive: boolean;
  nodeCount: number;
  onLogoClick: () => void;
  onWhisper: () => void;
};

export default function HudOverlay({ hydra, eventActive, nodeCount, onLogoClick, onWhisper }: Props) {
  const [notice, setNotice] = useState(true);
  const [telemetry, setTelemetry] = useState<number[]>([]);

  return (
    <>
      <header className="topbar">
        <button className="brand-button" onClick={onLogoClick} aria-label="Радар — системный логотип">
          <span className="brand-mark"><Radar size={21} strokeWidth={1.7} /></span>
          <span className="brand-name">РАДАР</span>
          <span className="brand-core">{hydra ? 'ZOLA ALGORITHM' : 'TRISKELION CORE'}</span>
        </button>
        <nav className="main-nav" aria-label="Навигация по сайту">
          <a href="#capabilities">Возможности</a>
          <a href="#live">Статус</a>
          <a href="#live">Мой город</a>
          <a href="#pricing">Тарифы</a>
        </nav>
        <div className="entry-actions">
          <a className="entry-link" href="/login"><UserRound size={15} />Личный кабинет</a>
          <a className="entry-link entry-link-accent" href="/login"><LogIn size={15} />Панель управления</a>
        </div>
      </header>

      <div className="scene-hud" aria-hidden="true">
        <div className="hud-line"><Activity size={13} />{eventActive ? 'ASSIMILATION EVENT' : 'MONITORING ACTIVE'}</div>
        <div className="hud-line"><ShieldCheck size={13} />{nodeCount} ORBITAL NODES</div>
        <span>DRAG TO ORBIT · SCROLL TO EXPLORE</span>
      </div>

      {hydra && (
        <button className="whisper-button" onClick={onWhisper}>// WHISPER: ELEVATOR_PROTOCOL</button>
      )}

      <AnimatePresence>
        {hydra && notice && (
          <motion.aside
            className="hydra-notice"
            initial={{ opacity: 0, transform: 'translateY(-12px)' }}
            animate={{ opacity: 1, transform: 'translateY(0px)' }}
            exit={{ opacity: 0, transform: 'translateY(-8px)' }}
            transition={{ duration: 0.24, ease: [0.23, 1, 0.32, 1] }}
            role="alert"
          >
            <button
              className="icon-button"
              aria-label="Закрыть уведомление"
              onClick={() => {
                setNotice(false);
                setTelemetry((current) => [...current, Date.now(), Date.now() + 1].slice(-4));
              }}
            ><X size={16} /></button>
            <small>PROJECT INSIGHT // OVERRIDE</small>
            <strong>CUT OFF ONE HEAD,<br />TWO MORE SHALL TAKE ITS PLACE</strong>
          </motion.aside>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {telemetry.map((id, index) => (
          <motion.aside
            key={id}
            className={`telemetry-pop telemetry-pop-${index % 2}`}
            initial={{ opacity: 0, transform: 'translateY(10px) scale(0.97)' }}
            animate={{ opacity: 1, transform: 'translateY(0px) scale(1)' }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
          >
            <button className="icon-button" aria-label="Закрыть телеметрию" onClick={() => setTelemetry((items) => items.filter((item) => item !== id))}><X size={14} /></button>
            <small>TELEMETRY MIRROR {String(index + 1).padStart(2, '0')}</small>
            <code>NODE_REPLICATION :: ALPHA/OMEGA<br />INSIGHT_STATUS :: UNBOUND</code>
          </motion.aside>
        ))}
      </AnimatePresence>
    </>
  );
}
