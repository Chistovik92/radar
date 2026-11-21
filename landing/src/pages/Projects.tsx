import PageLayout from '../components/PageLayout';
import {
  ArrowUpRight, Radar, Smartphone, Router, Layers,
  Cloud, Bot, BookOpen, CalendarDays, Wifi, Server, Monitor, Lock, Cpu, Network,
  Settings2, ArrowLeftRight,
} from 'lucide-react';
import { pageContent } from '../content';

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
  {
    icon: Cloud,
    name: 'opendisk',
    tagline: 'Облачные хранилища как локальные диски',
    description:
      'Бесплатный клиент для облачных хранилищ на базе rclone: подключение облаков как дисков в Windows и Linux, просмотр файлов на Android. Яндекс.Диск, Облако Mail.ru, Google Drive, Dropbox, S3 и другие сервисы. Kotlin / Compose Multiplatform, MIT.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/opendisk' },
      { label: 'Сайт', href: 'https://chistovik92.github.io/opendisk/' },
    ],
  },
  {
    icon: Bot,
    name: 'NeuroCode Android',
    tagline: 'Клиент для LLM на устройстве',
    description:
      'Открытый клиент для языковых моделей: запуск как на самом устройстве, так и для удалённого выполнения через консоль. Kotlin.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/NeuroCode-Android' },
    ],
  },
  {
    icon: BookOpen,
    name: 'LocalDoc AI',
    tagline: 'Локальная читалка с нейросетями',
    description:
      'Кроссплатформенная читалка книг и веб-страниц (Android + iOS) с озвучкой и полностью локальными нейросетями — без облака и телеметрии. Поддержка EPUB, FB2, PDF, DOCX и десятков форматов, локальный RAG, OCR и синтез речи на устройстве. Kotlin Multiplatform + Compose Multiplatform.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/LocalDoc-AI---KMP' },
    ],
  },
  {
    icon: CalendarDays,
    name: 'med-roster',
    tagline: 'Графики смен и табели для поликлиники',
    description:
      'Автоматизация составления графиков смен и расчёта табелей учёта рабочего времени (Т-13) для персонала детской и взрослой поликлиники. Импорт реальных графиков из Excel, поиск ошибок, правка в браузере и выгрузка готовых официальных форм. Сборка установщиков — GitHub Actions.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/med-roster' },
    ],
  },
  {
    icon: Wifi,
    name: 'MeshkitKeen',
    tagline: 'Управление mesh-сетью Keenetic',
    description:
      'Форк KeenKit, добавляющий неинтерактивный режим и управление mesh-узлами (ретрансляторами/экстендерами) с головного роутера-контроллера. Статус всех устройств, перезагрузка, Wi-Fi по диапазонам и OTA-обновление прошивки — с одного экрана.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/MeshkitKeen' },
    ],
  },
  {
    icon: Server,
    name: 'torrserver-docker-manager',
    tagline: 'Менеджер TorrServer в Docker',
    description:
      'Docker-менеджер для TorrServer с двумя режимами установки — простой запуск и развёртывание торрент-сервера в контейнере с автообновлением.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/torrserver-docker-manager' },
    ],
  },
  {
    icon: Monitor,
    name: 'Harness',
    tagline: 'Десктоп-приложение для DeepSeek Harness',
    description:
      'Настольное приложение в стиле Claude Code / ChatGPT / Gemini на базе DeepSeek Harness. Объединяет несколько LLM-провайдеров (DeepSeek, OpenAI, Claude, Gemini, Groq и др.) с локальной историей чатов, шифрованием ключей API и запуском локальных моделей Hugging Face. Electron + React.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/Harness' },
    ],
  },
  {
    icon: Lock,
    name: 'ZHeroDiZk',
    tagline: 'Удалённый доступ в классе RustDesk',
    description:
      'Открытая система удалённого доступа в классе RustDesk и AnyDesk: собственный сервер, кроссплатформенные клиенты, управляемые права доступа и аудит. Rust.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/ZHeroDiZk' },
    ],
  },
  {
    icon: Cpu,
    name: 'servAI',
    tagline: 'AI-сервер одной командой',
    description:
      'Установщик «AI-сервера» для Ubuntu 24.04+ и Debian 12+: одним скриптом ставит официальные консольные ИИ-клиенты (Claude Code, Codex CLI, Gemini CLI, Aider), рабочего пользователя, tmux-раскладку из четырёх агентов и опционально веб-IDE.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/servAI' },
    ],
  },
  {
    icon: Network,
    name: 'zeropentime',
    tagline: 'Децентрализованная альтернатива ZeroTier',
    description:
      'Открытая децентрализованная замена ZeroTier на базе AmneziaWG 3: защищённые виртуальные сети, NAT traversal, ретрансляция, fallback VLESS+REALITY, exit-узлы и веб-управление. Go.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/zeropentime' },
    ],
  },
  {
    icon: Settings2,
    name: 'winOpenCodeMod',
    tagline: 'Провайдеры в настройках OpenCode Desktop',
    description:
      'GUI-плагин для OpenCode Desktop, возвращающий форму «Custom provider» (как в v1.19.x) в раздел Settings → Providers. Добавление, правка и удаление собственных OpenAI-совместимых провайдеров без ручной правки opencode.json. TypeScript + Solid.js.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/winOpenCodeMod' },
    ],
  },
  {
    icon: ArrowLeftRight,
    name: 'DataOpenCode',
    tagline: 'Перенос настроек OpenCode между компьютерами',
    description:
      'Безопасный аддитивный перенос провайдеров, моделей, API-ключей и диалогов OpenCode между Windows-компьютерами: экспорт в zip-архив и развёртывание на другой машине без перезаписи локальных настроек. Поддержка V1 ↔ V2, защита ZIP и резервные копии.',
    links: [
      { label: 'GitHub', href: 'https://github.com/Chistovik92/DataOpenCode' },
    ],
  },
];

export default function Projects() {
  const content = pageContent('projects', {
    eyebrow: 'Семейство проектов SecretHero', title: 'Наши проекты',
    subtitle: 'Открытые инструменты, объединённые одним аккаунтом и одной философией — полезное под контролем пользователя.',
    projects: PROJECTS.map(({ icon: _icon, ...project }) => project),
    future_text: 'Больше проектов — в GitHub-профиле SecretHero. Следите за обновлениями в боте «Радар».',
  });
  return (
    <PageLayout>
      <div className="projects-page">
        <header className="page-title">
          <p className="update-date">{content.eyebrow}</p>
          <h1>{content.title}</h1>
          <p className="page-subtitle">{content.subtitle}</p>
        </header>

        <div className="projects-grid">
          {content.projects.map((project, index) => {
            const Icon = PROJECTS[index]?.icon || Radar;
            return <article className="project-card" key={project.name}>
              <div className="project-icon"><Icon size={26} /></div>
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
            </article>;
          })}
        </div>

        <section className="doc-section">
          <div className="project-future">
            <Layers size={22} />
            <p>{content.future_text}</p>
          </div>
        </section>
      </div>
    </PageLayout>
  );
}
