import PageLayout from '../components/PageLayout';
import { Link } from 'react-router-dom';
import { Check } from 'lucide-react';
import { pageContent, readConfig } from '../content';

type Card = { icon: string; name: string; price: string; period: string; features: string[]; button: string };
const FREE: Card = { icon: '🛡', name: 'Оповещения об угрозах', price: '0 ₽', period: 'бесплатно навсегда', features: ['БПЛА / ракетная опасность / воздушная тревога / отбой', 'МЧС: ЧС, штормовые предупреждения, эвакуация', 'ЖКХ: вода, свет, газ, отопление — адресно', 'Базовая погода (текст): текущая, 8 ч, 3 дня', 'Проверка ссылок — 200/сутки', 'ИИ-ассистент — базовый лимит', 'Без рекламы, без трекинга'], button: 'Запустить бота' };
const DIGEST: Card = { icon: '📰', name: 'Новостные подборки', price: '', period: '', features: ['18 тематик в одной подписке', 'ИИ-сводки и доставка по расписанию', 'Погода картинкой', 'Скачивание видео без дневного лимита подписчика'], button: 'Оформить в боте за Stars' };
const VPN: Card = { icon: '🔐', name: 'Аренда приватного сервера', price: 'Тарифы VPN', period: 'срок и цена до оплаты', features: ['Аренда приватного сервера', 'Срок, трафик и число устройств зависят от тарифа', 'Управление заказом в боте'], button: 'Тарифы VPN и загрузка' };

export default function Pricing() {
  const config = readConfig();
  const content = pageContent('pricing', {
    updated: 'Обновлено: ноябрь 2026', title: 'Тарифы и цены',
    subtitle: 'Оповещения бесплатно навсегда. Актуальные тарифы подписки и порядок оформления',
    intro: 'Радар — честные цены, без скрытых платежей. Все оповещения об угрозах — бесплатно навсегда.',
    payment_intro: 'Подписка на подборки оплачивается через Telegram Stars. Способы оплаты аренды приватного сервера и итоговая сумма показываются в боте до подтверждения заказа.',
    free_card: [FREE], digest_card: [DIGEST], vpn_card: [VPN], notes_title: 'Важные замечания:',
    notes: ['Цены подписки указаны в Telegram Stars (⭐); стоимость аренды сервера показывается в выбранном тарифе.', 'Приватный сервер предоставляется для законного использования по назначению.', 'Подписка на подборки оплачивается Stars; доступные способы оплаты аренды зависят от настроек бота.', 'Возврат средств: заявка в поддержку в течение 14 дней, если сервис не предоставлен.', 'Сам-хостинг (установка на свой сервер) — полностью бесплатно, код открыт (GPL-3.0).'],
    comparison_title: 'Сравнение: бесплатно vs подписка', comparison_headers: ['Функция', 'Бесплатно', 'Подписка (Stars)'],
    comparison: [{ cells: ['Тревоги БПЛА / МЧС / ЖКХ', '✅ Полностью', '✅ Полностью'] }, { cells: ['Погода (текст)', '✅ Текущая, 8ч, 3 дня', '✅ + картинка, вектор ветра, луна'] }, { cells: ['Новостные подборки', '❌', '✅ 18 тем, ИИ-сводки, расписание'] }, { cells: ['Проверка ссылок', '200/сутки', 'Без лимита'] }, { cells: ['ИИ-ассистент', 'Базовый лимит', 'Расширенный лимит'] }, { cells: ['Аренда приватного сервера', '❌', 'Отдельно (₽)'] }],
    pay_title: 'Как оплатить', pay_steps: ['Откройте бота: @SecretHeroBot', 'Меню → «Подписки» или «Сервер»', 'Выберите тариф и один из доступных способов оплаты', 'Доступ активируется автоматически'],
    support_question: 'Вопросы по оплате?', support_link: 'Напишите в поддержку',
  });
  const botUrl = `https://t.me/${config.botUsername || 'SecretHeroBot'}`;
  const card = (item: Card, key: string, to?: string) => (
    <div className={`pricing-card ${key === 'free' ? 'free' : ''}`} key={key}>
      <div className="card-icon">{item.icon}</div><h3>{item.name}</h3>
      <div className="price"><span className="amount">{item.price}</span><span className="period">{item.period}</span></div>
      <ul className="features">{item.features.map((feature) => <li key={feature}><Check size={16} /> {feature}</li>)}</ul>
      {to ? <Link to={to} className="cta-button">{item.button}</Link> : <a href={botUrl} target="_blank" rel="noreferrer noopener" className="cta-button">{item.button}</a>}
    </div>
  );
  const digest = content.digest_card[0] || DIGEST;
  return (
    <PageLayout><div className="pricing-page">
      <header className="page-title"><p className="update-date">{content.updated}</p><h1>{content.title}</h1><p className="page-subtitle">{content.subtitle}</p></header>
      <section className="intro-section"><p><strong>{content.intro}</strong></p><p>{content.payment_intro}</p></section>
      <section className="pricing-grid">
        {card(content.free_card[0] || FREE, 'free')}
        {config.plans.map(([days, stars]) => card({ ...digest, price: `${stars} ⭐`, period: `${days} дней` }, `digest-${days}`))}
        {card(content.vpn_card[0] || VPN, 'vpn', '/downloads')}
      </section>
      <section className="notes-section"><p><strong>{content.notes_title}</strong></p><ul>{content.notes.map((note) => <li key={note}>{note}</li>)}</ul></section>
      <section className="comparison-section"><h2>{content.comparison_title}</h2><table className="comparison-table">
        <thead><tr>{content.comparison_headers.map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{content.comparison.map((row, index) => <tr key={index}>{row.cells.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody>
      </table></section>
      <section className="how-to-pay"><h2>{content.pay_title}</h2><ol>{content.pay_steps.map((step) => <li key={step}>{step}</li>)}</ol><p>{content.support_question} <Link to="/support">{content.support_link}</Link></p></section>
    </div></PageLayout>
  );
}
