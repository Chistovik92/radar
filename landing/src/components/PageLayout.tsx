import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Radar } from 'lucide-react';
import ZolaTerminal from './ZolaTerminal';

interface PageLayoutProps {
  children: React.ReactNode;
  version?: string;
}

export default function PageLayout({ children, version = '6.0.1' }: PageLayoutProps) {
  const [hydra, setHydra] = useState(false);
  const [logoClicks, setLogoClicks] = useState(0);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const logoClickTimer = useRef<NodeJS.Timeout | null>(null);

  const handleHydra = useCallback(() => {
    setHydra(true);
    // Пасхалка активирована - можно добавить визуальные эффекты
  }, []);

  const handleLogoClick = useCallback(() => {
    setLogoClicks((prev) => prev + 1);
    if (logoClickTimer.current) clearTimeout(logoClickTimer.current);
    logoClickTimer.current = setTimeout(() => setLogoClicks(0), 2000);
  }, []);

  useEffect(() => {
    if (logoClicks >= 3) {
      handleHydra();
      setLogoClicks(0);
    }
  }, [logoClicks, handleHydra]);

  const handleWhisper = useCallback(() => {
    setHydra(false);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.hydra = hydra ? 'active' : 'inactive';
  }, [hydra]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '`' && e.ctrlKey) {
        e.preventDefault();
        setTerminalOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="page-layout">
      <header className="page-header">
        <nav className="page-nav">
          <Link to="/" className="logo-link">
            <Radar 
              size={24} 
              onClick={handleLogoClick}
              style={{ cursor: 'pointer' }}
              aria-label="TRISKELION Logo"
            />
            <span>РАДАР</span>
          </Link>
          <div className="nav-links">
            <Link to="/">Лендинг</Link>
            <Link to="/downloads">Загрузки</Link>
            <Link to="/projects">Проекты</Link>
            <Link to="/pricing">Тарифы</Link>
            <Link to="/support">Поддержка</Link>
            <a href="/privacy">Политика</a>
            <a href="/terms">Соглашение</a>
            <a href="/login">Вход</a>
          </div>
        </nav>
      </header>

      <main className="page-content">
        {children}
      </main>

      <footer className="page-footer">
        <div className="footer-columns">
          <div>
            <strong>Проект</strong>
            <a href="https://github.com/Chistovik92/radar" target="_blank" rel="noreferrer noopener">GitHub репозиторий</a>
            <a href="https://github.com/Chistovik92/radar/releases" target="_blank" rel="noreferrer noopener">Релизы</a>
          </div>
          <div>
            <strong>Документы</strong>
            <a href="/privacy">Политика конфиденциальности</a>
            <a href="/terms">Пользовательское соглашение</a>
            <Link to="/support">Поддержка</Link>
            <Link to="/pricing">Тарифы и цены</Link>
          </div>
          <div>
            <strong>Приложения</strong>
            <Link to="/downloads">Загрузки</Link>
            <Link to="/projects">Наши проекты</Link>
            <a href="https://github.com/Chistovik92/HydraVPN" target="_blank" rel="noreferrer noopener">HydraVPN</a>
            <a href="https://github.com/Chistovik92/HydraVPNforRouters" target="_blank" rel="noreferrer noopener">HydraVPN for Routers</a>
          </div>
          <div>
            <strong>Бот и каналы</strong>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener">@SecretHeroBot</a>
            <a href="https://t.me/SecretHeroSupport" target="_blank" rel="noreferrer noopener">Поддержка (@SecretHeroSupport)</a>
          </div>
          <div>
            <strong>Технически</strong>
            <p>Python 3.11+ · aiohttp · aiogram</p>
            <p>SQLite / PostgreSQL (asyncpg)</p>
            <p>Docker · Caddy · systemd</p>
            <p>ARM (RK3318) / x64</p>
          </div>
        </div>
        <div className="footer-bottom">
          <span>Радар v{version} · <a href="https://github.com/Chistovik92/radar/blob/main/LICENSE" target="_blank" rel="noreferrer noopener">GPL-3.0</a> · Автор: <a href="https://github.com/Chistovik92" target="_blank" rel="noreferrer noopener">SecretHero</a> · mekbuda</span>
        </div>
      </footer>

      {hydra && (
        <button 
          className="whisper-button"
          onClick={handleWhisper}
          aria-label="Return control"
        >
          // WHISPER: ELEVATOR_PROTOCOL
        </button>
      )}

      {terminalOpen && (
        <ZolaTerminal
          hydra={hydra}
          onHydra={handleHydra}
        />
      )}
    </div>
  );
}
