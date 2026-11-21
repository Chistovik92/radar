import PageLayout from '../components/PageLayout';
import { pageContent } from '../content';

export default function Support() {
  const content = pageContent('support', {
    updated: 'Обновлено: ноябрь 2026', title: 'Поддержка', subtitle: 'Тикет-система, контакты, SLA и ответы на частые вопросы',
    intro: 'Радар — бот мониторинга городских угроз и аварий ЖКХ. Мы отвечаем на вопросы по установке, настройке, оплате, багам и предложениям.', channels_title: 'Каналы поддержки',
    channels: [
      { icon: '🎫', title: 'Тикет-бот (рекомендуется)', description: 'Создайте тикет — получите номер, статус и ответ в личку. История сохраняется.', button: 'Открыть @SecretHeroSupportBot', href: 'https://t.me/SecretHeroSupportBot' },
      { icon: '👤', title: 'Прямой контакт автора', description: 'Для срочных вопросов, безопасности, партнёрства. Отвечаю в рабочее время.', button: 'Написать @SecretHeroSupport', href: 'https://t.me/SecretHeroSupport' },
      { icon: '📧', title: 'Email', description: 'Для официальных обращений, договоров, претензий, GDPR-запросов.', button: 'admin@hydravpsvpn.ru', href: 'mailto:admin@hydravpsvpn.ru' },
    ],
    sla_title: 'SLA — время ответа', sla: ['Рабочее время: пн–пт 09:00–20:00 (МСК).', 'Первичный ответ: до 4 часов в рабочее время, до 24 часов — в нерабочее.', 'Решение типовых вопросов: 1–2 рабочих дня.', 'Сложные баги / установка: до 5 рабочих дней.'],
    speed_up_title: 'Что ускорит помощь', speed_up: ['Версия бота/панели (/version в боте или футер панели).', 'Способ установки: Docker (install.sh) / Docker Compose / ручная.', 'ОС и архитектура сервера (ARM / x64).', 'Логи: docker logs radar_container --tail 100 или journalctl -u radar -n 100.', 'Скриншот ошибки или полный текст traceback.', 'Что уже пробовали исправить.'], faq_title: 'Частые вопросы (FAQ)',
    faq: [{ question: 'Бот не присылает оповещения', answer: 'Проверьте: локации добавлены верно (город/улица/дом)? Включены ли нужные категории в настройках? Не включены ли «тихие часы»? Бот не заблокирован? Источники в городе настроены админом (команда /sources в панели)?' }, { question: 'Погода не работает / «нет координат»', answer: 'Удалите локацию и добавьте заново — координаты определяются при добавлении. Если город не находится — напишите в поддержку, добавим в геокодер.' }, { question: 'Как купить подписку / арендовать сервер', answer: 'В боте: Меню → Подписки / Сервер → выбрать тариф → оплатить Stars или через платёжную систему. Доступ придёт автоматически.' }, { question: 'Хочу установить у себя (self-hosted)', answer: 'Требования: Docker, Docker Compose, порт 80/443, домен (для HTTPS и TG Login Widget). По вопросам установки и настройки обращайтесь к @SecretHeroSupportBot или admin@hydravpsvpn.ru.' }],
    contact_title: 'Как отправить обращение', contact_text: 'Откройте тикет-бота @SecretHeroSupportBot и опишите вопрос там — он создаст обращение и покажет его номер. Если бот недоступен, напишите @SecretHeroSupport.',
  });
  return (
    <PageLayout><div className="doc-page">
      <header className="page-title"><p className="update-date">{content.updated}</p><h1>{content.title}</h1><p className="page-subtitle">{content.subtitle}</p></header>
      <section className="doc-intro"><p>{content.intro}</p></section>
      <section className="doc-section"><h2>{content.channels_title}</h2><div className="contact-grid">{content.channels.map((channel) => <article className="contact-card" key={channel.title}><div className="contact-icon">{channel.icon}</div><h3 className="contact-title">{channel.title}</h3><p className="contact-desc">{channel.description}</p><a href={channel.href} target="_blank" rel="noreferrer noopener" className="contact-link">{channel.button}</a></article>)}</div></section>
      <section className="doc-section"><h2>{content.sla_title}</h2><ul>{content.sla.map((line) => <li key={line}>{line}</li>)}</ul></section>
      <section className="doc-section"><h2>{content.speed_up_title}</h2><ol>{content.speed_up.map((line) => <li key={line}>{line}</li>)}</ol></section>
      <section className="doc-section"><h2>{content.faq_title}</h2>{content.faq.map((item) => <div key={item.question}><h3>{item.question}</h3><p>{item.answer}</p></div>)}</section>
      <section className="doc-section"><h2>{content.contact_title}</h2><p>{content.contact_text}</p></section>
    </div></PageLayout>
  );
}
