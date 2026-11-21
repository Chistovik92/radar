import PageLayout from '../components/PageLayout';
import { ArrowUpRight, Download, Smartphone, Monitor, Router, Server, ShieldCheck } from 'lucide-react';
import { pageContent } from '../content';

const CLIENT_LINKS = { repo: 'https://github.com/Chistovik92/HydraVPN', releases: 'https://github.com/Chistovik92/HydraVPN/releases', site: 'https://gidravpn.ru', telegram: 'https://t.me/+WWJFBZVhxBs4ZmNi', appId: 'ru.gidravpn.hydra' };
const ROUTER_LINKS = { repo: 'https://github.com/Chistovik92/HydraVPNforRouters', releases: 'https://github.com/Chistovik92/HydraVPNforRouters/releases' };
const CLIENT_ICONS = [Smartphone, Monitor, Server, Monitor, Smartphone];
const ROUTER_ICONS = [Router, Router, Router];
const DEFAULTS = {
  title: 'Загрузки приложений', subtitle: 'HydraVPN — один VPN для телефона, компьютера и роутера. Скачайте приложение под свою платформу.',
  client_name: 'HydraVPN', client_tagline: 'Мультипротокольный VPN-клиент для всех платформ', client_version: '0.8.3', client_description: 'Один проект, один аккаунт (бот «Радар» / HydraVPN), одно управление — телефон, компьютер и домашний роутер. Поддерживает sing-box, Xray, AmneziaWG, умную маршрутизацию, раздельное туннелирование и управление роутером.',
  client_platforms: [{ title: 'Android 8+', files: 'APK (arm64, armv7, x86, x86_64)', note: 'Телефоны, планшеты, Android TV / Google TV' }, { title: 'Windows 10/11 x64', files: '.msi / .exe / portable .zip', note: 'Windows 7 SP1 и 32-бит — Hydra Classic' }, { title: 'Linux x64 / arm64', files: '.deb, .rpm, .AppImage, .tar.gz', note: 'Raspberry Pi OS 32-бит — Hydra Classic (Java 11+)' }, { title: 'macOS 12+', files: '.dmg (Apple Silicon / Intel)', note: '' }, { title: 'iOS 17+', files: '.ipa (без подписи)', note: 'Ставится через переподпись (AltStore, Sideloadly)' }],
  download_button: 'Скачать', source_button: 'Исходный код', update_title: 'Обновления приложение скачивает само.', update_text: 'Кнопка «Обновить» загружает файл под вашу систему (SHA-256 из релиза проверяется) и запускает установку. Ставьте файлы только из официального релиза на GitHub — SHA-256 указан в каждом релизе.',
  router_name: 'HydraVPN for Routers', router_tagline: 'Решение для обхода DPI на роутерах', router_version: '1.3.3', router_description: 'Комплексное, не зависящее от платформы решение на базе sing-box, zapret и ByeDPI для роутеров. Единое решение для OpenWRT, KeeneticOS и MikroTik RouterOS с полной функциональной совместимостью.',
  router_platforms: [{ title: 'OpenWRT 21.02+', files: 'IPK (APK — через install.sh)', note: 'Init: procd' }, { title: 'KeeneticOS 3.7+', files: 'IPK (Entware)', note: 'Init: ndm/Entware' }, { title: 'RouterOS 7+', files: 'TAR (контейнер)', note: 'Init: systemd/container' }],
  vpn_title: 'Тарифы VPN', vpn_intro: 'Доступ к VPN выдаётся через бота «Радар»: раздел 🔐 VPN — там же можно оформить и продлить подписку. С 12.08.2026 действует обновлённая тарифная сетка и праздничная акция.',
  vpn_plans: [{ name: 'Неделя', price: '0 ₽', period: 'пробный ключ — бесплатно', note: '' }, { name: 'Месяц', price: '550 ₽', period: '🔥 Спеццена по акции', note: '' }, { name: 'Три месяца', price: '1 250 ₽', period: 'срок: 90 дней', note: '' }, { name: 'Полгода', price: '2 300 ₽', period: 'срок: 180 дней', note: '' }, { name: 'Год', price: '4 200 ₽', period: '🔥 Выгодное предложение на длительный период', note: '' }],
  vpn_note: 'В «Радаре» встроена продажа VPN: оплата через Crypto Pay или с подтверждением администратора, тарифы настраиваются в разделе «Ключи».', locations_title: 'Локации и условия подключения',
  locations: 'Доступные локации: Финляндия 🇫🇮, Россия 🇷🇺, Казахстан 🇰🇿, США 🇺🇸, Франция 🇫🇷, Польша 🇵🇱, Латвия 🇱🇻, Швеция 🇸🇪, Нидерланды 🇳🇱, Германия 🇩🇪, Эстония 🇪🇪, Румыния 🇷🇴.',
  connection_terms: [{ title: 'Два ключа на пользователя', text: 'К каждому ключу можно подключить от 5 до 10 устройств (минимум 5, максимум 10).' }, { title: 'Программа лояльности', text: '🔥 АКЦИЯ — за каждого приведённого друга вы получаете 1 полный месяц в подарок (или дополнительные дни/недели по программе лояльности).' }],
  services_title: 'Дополнительные услуги', routers_title: 'Роутеры', routers_intro: 'Для работы с сервером и раздачи доступа по всей домашней сети.',
  services: [{ name: 'Роутер', price: 'от 3 500 ₽', period: 'гарантия 1 год', note: '' }, { name: 'Прошивка и настройка', price: '1 500 ₽', period: 'подарочный доступ на 3 месяца', note: '' }, { name: 'Доставка', price: 'от 200 ₽', period: 'по РФ и СНГ', note: '' }, { name: 'Удалённый доступ', price: '1 000 ₽', period: 'при технической возможности', note: 'при подключении белого статического IP у провайдера или дополнительной опции (от 150 ₽ / месяц)' }],
  support_title: 'Техническая поддержка', support_terms: [{ title: 'В течение полугода', text: 'Техническая поддержка включена на первые шесть месяцев.' }, { title: 'Дальше — по обращению или подпиской', text: 'Разовое обращение — от 1 000 ₽, подписка на тех-помощь — 150 ₽ / месяц.' }],
  individual_title: 'Индивидуальные тарифы', individual_text: 'Выбор локаций и от 10 до 25 ключей под ваши задачи. Условия подбираются индивидуально — напишите в поддержку или в бота «Радар».', install_title: 'Как установить и настроить приложения',
  install_steps: [{ title: 'Скачайте файл под свою платформу', text: 'Каждый релиз публикуется сразу со всеми платформами. Выберите версию из таблицы выше.' }, { title: 'Установите и войдите в аккаунт', text: 'В боте «Радар» откройте раздел 🔐 VPN → «Подключить приложение» и введите одноразовый код — HydraVPN подхватит ваши подписки. Один аккаунт на телефон, компьютер и роутер.' }, { title: 'Для роутера — разверните пакет', text: 'OpenWRT — через install.sh; KeeneticOS — пакет Entware; MikroTik — контейнер TAR. Подробности — в README репозитория.' }], resources_title: 'Поддержка и ресурсы',
};

export default function Downloads() {
  const content = pageContent('downloads', DEFAULTS);
  const application = (kind: 'client' | 'router') => {
    const client = kind === 'client';
    const name = client ? content.client_name : content.router_name;
    const version = client ? content.client_version : content.router_version;
    const platforms = client ? content.client_platforms : content.router_platforms;
    const links = client ? CLIENT_LINKS : ROUTER_LINKS;
    const icons = client ? CLIENT_ICONS : ROUTER_ICONS;
    return <section className="app-section">
      <div className="app-header"><div><h2>{name}</h2><p>{client ? content.client_tagline : content.router_tagline}</p></div><div className="app-header-actions"><a className="button-primary" href={links.releases} target="_blank" rel="noreferrer noopener"><Download size={18} /> {content.download_button} {version}</a><a className="button-secondary" href={links.repo} target="_blank" rel="noreferrer noopener">{content.source_button} <ArrowUpRight size={15} /></a></div></div>
      <p className="app-description">{client ? content.client_description : content.router_description}</p>
      <div className="platform-grid">{platforms.map((platform, index) => { const Icon = icons[index] || Monitor; return <article className="platform-card" key={platform.title}><Icon size={22} /><h3>{platform.title}</h3><span className="platform-files">{platform.files}</span>{platform.note && <span className="platform-note">{platform.note}</span>}</article>; })}</div>
      {client && <div className="install-note"><ShieldCheck size={20} /><div><strong>{content.update_title}</strong><p>{content.update_text}</p></div></div>}
    </section>;
  };
  const planClasses = ['vpn-plan-trial', 'vpn-plan-hot', '', '', 'vpn-plan-best'];
  return <PageLayout><div className="downloads-page">
    <header className="page-title"><p className="update-date">{content.client_name} {content.client_version} · {content.router_name} {content.router_version}</p><h1>{content.title}</h1><p className="page-subtitle">{content.subtitle}</p></header>
    {application('client')}{application('router')}
    <section className="doc-section"><h2>{content.vpn_title}</h2><p>{content.vpn_intro}</p><div className="vpn-plans vpn-plans--five">{content.vpn_plans.map((plan, index) => <article className={`vpn-plan-card ${planClasses[index] || ''}`} key={plan.name}><h3>{plan.name}</h3><div className="vpn-plan-price">{plan.price}</div><span className="vpn-plan-period">{plan.period}</span>{plan.note && <span className="vpn-plan-fine">{plan.note}</span>}</article>)}</div><p className="doc-hint">{content.vpn_note} <a href="/pricing">{content.vpn_title}</a>.</p></section>
    <section className="doc-section"><h2>{content.locations_title}</h2><p className="doc-hint">{content.locations}</p><ul className="howto-list">{content.connection_terms.map((item) => <li key={item.title}><strong>{item.title}</strong><p>{item.text}</p></li>)}</ul></section>
    <section className="doc-section"><h2>{content.services_title}</h2><h3 className="doc-subtitle">{content.routers_title}</h3><p className="doc-hint">{content.routers_intro}</p><div className="vpn-plans">{content.services.map((plan) => <article className="vpn-plan-card" key={plan.name}><h3>{plan.name}</h3><div className="vpn-plan-price">{plan.price}</div><span className="vpn-plan-period">{plan.period}</span>{plan.note && <span className="vpn-plan-fine">{plan.note}</span>}</article>)}</div><h3 className="doc-subtitle">{content.support_title}</h3><ul className="howto-list">{content.support_terms.map((item) => <li key={item.title}><strong>{item.title}</strong><p>{item.text}</p></li>)}</ul></section>
    <section className="doc-section"><h2>{content.individual_title}</h2><p className="doc-hint">{content.individual_text}</p></section>
    <section className="doc-section"><h2>{content.install_title}</h2><ol className="howto-list">{content.install_steps.map((item) => <li key={item.title}><strong>{item.title}</strong><p>{item.text}</p></li>)}</ol><p className="doc-hint"><a href={CLIENT_LINKS.telegram} target="_blank" rel="noreferrer noopener">Telegram-чат Hydra</a> · <a href={CLIENT_LINKS.site} target="_blank" rel="noreferrer noopener">{CLIENT_LINKS.site.replace('https://', '')}</a></p></section>
    <section className="doc-section"><h2>{content.resources_title}</h2><ul><li><strong>{content.client_name}:</strong> <a href={CLIENT_LINKS.repo} target="_blank" rel="noreferrer noopener">GitHub</a> · <a href={CLIENT_LINKS.releases} target="_blank" rel="noreferrer noopener">{content.download_button}</a> · <code>{CLIENT_LINKS.appId}</code></li><li><strong>{content.router_name}:</strong> <a href={ROUTER_LINKS.repo} target="_blank" rel="noreferrer noopener">GitHub</a> · <a href={ROUTER_LINKS.releases} target="_blank" rel="noreferrer noopener">{content.download_button}</a></li></ul></section>
  </div></PageLayout>;
}
