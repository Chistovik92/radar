import PageLayout from '../components/PageLayout';
import { ArrowUpRight, Radar, Smartphone, Router, Layers } from 'lucide-react';

const PROJECTS = [
  {
    icon: Radar,
    name: 'Радар',
    tagline: 'Мониторинг городских угроз и аварий ЖКХ',
    description:
      'Telegram-бот и веб-панель, которые следят за каналами МЧС, администраций, ЖКХ и RSS-лентами, сопоставляют события с вашими адресами и присылают только то, что касается вас. Открытый исходный код, GPL-3.0.',
    links: [
      { label: 'Сайт проекта', href: '/' },
      { label: 'GitHub', href: 'https://github.com/Chistovik92/radar' },
      { label: 'Бот @SecretHeroBot', href: 'https://t.me/SecretHeroBot' },
    ],
  },
  {
    icon: Smartphone,
    name: 'HydraVPN',
    tagline: 'Мультипротокольный VPN-клиент',
    description:
      'Один VPN для Android, Windows, Linux, macOS и iOS. Один аккаунт с ботом «Радар», умная маршрутизация, раздельное туннелирование и управление роутером. Скачайте в разделе «Загрузки».',
    links: [
      { label: 'Загрузки', href: '/downloads' },
      { label: 'GitHub', href: 'https://github.com/Chistovik92/HydraVPN' },
      { label: 'Сайт', href: 'https://gidravpn.ru' },
    ],
  },
  {
    icon: Router,
    name: 'HydraVPN for Routers',
    tagline: 'VPN и обход DPI для роутеров',
    description:
      'Комплексное решение на базе sing-box, zapret и ByeDPI для OpenWRT, KeeneticOS и MikroTik RouterOS. Единый интерфейс и JSON API на всех платформах. Скачайте в разделе «Загрузки».',
    links: [
      { label: 'Загрузки', href: '/downloads' },
      { label: 'GitHub', href: 'https://github.com/Chistovik92/HydraVPNforRouters' },
    ],
  },
];

export default function Projects() {
  return (
    <PageLayout>
      <div className="projects-page">
        <header className="page-title">
          <p className="update-date">Семейство проектов SecretHero</p>
          <h1>Наши проекты</h1>
          <p className="page-subtitle">
            Открытые инструменты, объединённые одним аккаунтом и одной философией — полезное под контролем пользователя.
          </p>
        </header>

        <div className="projects-grid">
          {PROJECTS.map((project) => (
            <article className="project-card" key={project.name}>
              <div className="project-icon"><project.icon size={26} /></div>
              <h2>{project.name}</h2>
              <p className="project-tagline">{project.tagline}</p>
              <p className="project-description">{project.description}</p>
              <div className="project-links">
                {project.links.map((link) => (
                  <a key={link.label} href={link.href} target={link.href.startsWith('http') ? '_blank' : undefined} rel="noreferrer noopener">
                    {link.label} {link.href.startsWith('http') && <ArrowUpRight size={14} />}
                  </a>
                ))}
              </div>
            </article>
          ))}
        </div>

        <section className="doc-section">
          <div className="project-future">
            <Layers size={22} />
            <p>
              Раздел наполняется. Здесь будут появляться новые проекты — следите за обновлениями в{' '}
              <a href="https://github.com/Chistovik92" target="_blank" rel="noreferrer noopener">GitHub-профиле SecretHero</a> и в{' '}
              <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener">боте «Радар»</a>.
            </p>
          </div>
        </section>
      </div>
    </PageLayout>
  );
}
