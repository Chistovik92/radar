import PageLayout from '../components/PageLayout';
import { ArrowUpRight, Download, Smartphone, Monitor, Router, Server, ShieldCheck } from 'lucide-react';

const HYDRA_CLIENT = {
  name: 'HydraVPN',
  tagline: 'Мультипротокольный VPN-клиент для всех платформ',
  version: '0.8.3',
  repo: 'https://github.com/Chistovik92/HydraVPN',
  releases: 'https://github.com/Chistovik92/HydraVPN/releases',
  site: 'https://gidravpn.ru',
  telegram: 'https://t.me/+WWJFBZVhxBs4ZmNi',
  appId: 'ru.gidravpn.hydra',
  description:
    'Один проект, один аккаунт (бот «Радар» / HydraVPN), одно управление — телефон, компьютер и домашний роутер. Поддерживает sing-box, Xray, AmneziaWG, умную маршрутизацию, раздельное туннелирование и управление роутером.',
  platforms: [
    { icon: Smartphone, title: 'Android 8+', files: 'APK (arm64, armv7, x86, x86_64)', note: 'Телефоны, планшеты, Android TV / Google TV' },
    { icon: Monitor, title: 'Windows 10/11 x64', files: '.msi / .exe / portable .zip', note: 'Windows 7 SP1 и 32-бит — Hydra Classic' },
    { icon: Server, title: 'Linux x64 / arm64', files: '.deb, .rpm, .AppImage, .tar.gz', note: 'Raspberry Pi OS 32-бит — Hydra Classic (Java 11+)' },
    { icon: Monitor, title: 'macOS 12+', files: '.dmg (Apple Silicon / Intel)', note: '' },
    { icon: Smartphone, title: 'iOS 17+', files: '.ipa (без подписи)', note: 'Ставится через переподпись (AltStore, Sideloadly)' },
  ],
};

const HYDRA_ROUTER = {
  name: 'HydraVPN for Routers',
  tagline: 'Решение для обхода DPI на роутерах',
  version: '1.3.3',
  repo: 'https://github.com/Chistovik92/HydraVPNforRouters',
  releases: 'https://github.com/Chistovik92/HydraVPNforRouters/releases',
  description:
    'Комплексное, не зависящее от платформы решение на базе sing-box, zapret и ByeDPI для роутеров. Единое решение для OpenWRT, KeeneticOS и MikroTik RouterOS с полной функциональной совместимостью.',
  platforms: [
    { icon: Router, title: 'OpenWRT 21.02+', files: 'IPK (APK — через install.sh)', note: 'Init: procd' },
    { icon: Router, title: 'KeeneticOS 3.7+', files: 'IPK (Entware)', note: 'Init: ndm/Entware' },
    { icon: Router, title: 'RouterOS 7+', files: 'TAR (контейнер)', note: 'Init: systemd/container' },
  ],
};

export default function Downloads() {
  return (
    <PageLayout>
      <div className="downloads-page">
        <header className="page-title">
          <p className="update-date">Последние версии: HydraVPN {HYDRA_CLIENT.version} · Router {HYDRA_ROUTER.version}</p>
          <h1>Загрузки приложений</h1>
          <p className="page-subtitle">
            HydraVPN — один VPN для телефона, компьютера и роутера. Скачайте приложение под свою платформу.
          </p>
        </header>

        {/* ============ HydraVPN (клиент) ============ */}
        <section className="app-section">
          <div className="app-header">
            <div>
              <h2>{HYDRA_CLIENT.name}</h2>
              <p>{HYDRA_CLIENT.tagline}</p>
            </div>
            <div className="app-header-actions">
              <a className="button-primary" href={HYDRA_CLIENT.releases} target="_blank" rel="noreferrer noopener">
                <Download size={18} /> Скачать {HYDRA_CLIENT.version}
              </a>
              <a className="button-secondary" href={HYDRA_CLIENT.repo} target="_blank" rel="noreferrer noopener">
                Исходный код <ArrowUpRight size={15} />
              </a>
            </div>
          </div>

          <p className="app-description">{HYDRA_CLIENT.description}</p>

          <div className="platform-grid">
            {HYDRA_CLIENT.platforms.map((p) => (
              <article className="platform-card" key={p.title}>
                <p.icon size={22} />
                <h3>{p.title}</h3>
                <span className="platform-files">{p.files}</span>
                {p.note && <span className="platform-note">{p.note}</span>}
              </article>
            ))}
          </div>

          <div className="install-note">
            <ShieldCheck size={20} />
            <div>
              <strong>Обновления приложение скачивает само.</strong>
              <p>
                Кнопка «Обновить» загружает файл под вашу систему (SHA-256 из релиза проверяется) и запускает установку.
                Ставьте файлы только из официального релиза на GitHub — SHA-256 указан в каждом релизе.
              </p>
            </div>
          </div>
        </section>

        {/* ============ HydraVPN for Routers ============ */}
        <section className="app-section">
          <div className="app-header">
            <div>
              <h2>{HYDRA_ROUTER.name}</h2>
              <p>{HYDRA_ROUTER.tagline}</p>
            </div>
            <div className="app-header-actions">
              <a className="button-primary" href={HYDRA_ROUTER.releases} target="_blank" rel="noreferrer noopener">
                <Download size={18} /> Скачать {HYDRA_ROUTER.version}
              </a>
              <a className="button-secondary" href={HYDRA_ROUTER.repo} target="_blank" rel="noreferrer noopener">
                Исходный код <ArrowUpRight size={15} />
              </a>
            </div>
          </div>

          <p className="app-description">{HYDRA_ROUTER.description}</p>

          <div className="platform-grid">
            {HYDRA_ROUTER.platforms.map((p) => (
              <article className="platform-card" key={p.title}>
                <p.icon size={22} />
                <h3>{p.title}</h3>
                <span className="platform-files">{p.files}</span>
                <span className="platform-note">{p.note}</span>
              </article>
            ))}
          </div>
        </section>

        {/* ============ Инструкция ============ */}
        <section className="doc-section">
          <h2>Тарифы VPN</h2>
          <p>
            Доступ к VPN выдаётся через бота «Радар»: раздел <code>🔐 VPN</code> — там же можно оформить и продлить подписку.
            Актуальные цены на аренду приватного сервера и сроки показываются в боте до подтверждения заказа.
          </p>
          {/* TODO: замените плейсхолдеры на реальные тарифы VPN */}
          <div className="vpn-plans">
            <article className="vpn-plan-card">
              <h3>Тариф 1</h3>
              <div className="vpn-plan-price">— ₽</div>
              <span className="vpn-plan-period">срок: —</span>
            </article>
            <article className="vpn-plan-card">
              <h3>Тариф 2</h3>
              <div className="vpn-plan-price">— ₽</div>
              <span className="vpn-plan-period">срок: —</span>
            </article>
            <article className="vpn-plan-card">
              <h3>Тариф 3</h3>
              <div className="vpn-plan-price">— ₽</div>
              <span className="vpn-plan-period">срок: —</span>
            </article>
          </div>
          <p className="doc-hint">
            В «Радаре» встроена продажа VPN: оплата через Crypto Pay или с подтверждением администратора,
            тарифы настраиваются в разделе «Ключи». Подробнее — в разделе{' '}
            <a href="/pricing">«Тарифы и цены»</a>.
          </p>
        </section>

        <section className="doc-section">
          <h2>Как установить и настроить</h2>
          <ol className="howto-list">
            <li>
              <strong>Скачайте файл под свою платформу</strong>
              <p>Каждый релиз публикуется сразу со всеми платформами. Выберите версию из таблицы выше.</p>
            </li>
            <li>
              <strong>Установите и войдите в аккаунт</strong>
              <p>
                В боте «Радар» откройте раздел <code>🔐 VPN</code> → «Подключить приложение» и введите одноразовый код —
                HydraVPN подхватит ваши подписки. Один аккаунт на телефон, компьютер и роутер.
              </p>
            </li>
            <li>
              <strong>Для роутера — разверните пакет</strong>
              <p>
                OpenWRT — через <code>install.sh</code>; KeeneticOS — пакет Entware; MikroTik — контейнер TAR.
                Подробности — в README репозитория {HYDRA_ROUTER.name}.
              </p>
            </li>
          </ol>
          <p className="doc-hint">
            Вопросы по установке? <a href={HYDRA_CLIENT.telegram} target="_blank" rel="noreferrer noopener">Telegram-чат Hydra</a> ·{' '}
            <a href={HYDRA_CLIENT.site} target="_blank" rel="noreferrer noopener">Сайт {HYDRA_CLIENT.site.replace('https://', '')}</a>
          </p>
        </section>

        <section className="doc-section">
          <h2>Поддержка и ресурсы</h2>
          <ul>
            <li><strong>HydraVPN:</strong> <a href={HYDRA_CLIENT.repo} target="_blank" rel="noreferrer noopener">GitHub-репозиторий</a> · <a href={HYDRA_CLIENT.releases} target="_blank" rel="noreferrer noopener">Релизы</a> · appId <code>{HYDRA_CLIENT.appId}</code></li>
            <li><strong>HydraVPN for Routers:</strong> <a href={HYDRA_ROUTER.repo} target="_blank" rel="noreferrer noopener">GitHub-репозиторий</a> · <a href={HYDRA_ROUTER.releases} target="_blank" rel="noreferrer noopener">Релизы</a></li>
          </ul>
        </section>
      </div>
    </PageLayout>
  );
}
