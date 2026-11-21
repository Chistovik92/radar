import PageLayout from '../components/PageLayout';

export default function Support() {
  return (
    <PageLayout>
      <div className="doc-page">
        <header className="page-title">
          <p className="update-date">Обновлено: ноябрь 2026</p>
          <h1>Поддержка</h1>
          <p className="page-subtitle">
            Тикет-система, контакты, SLA и ответы на частые вопросы
          </p>
        </header>

        <section className="doc-intro">
          <p><strong>Радар</strong> — бот мониторинга городских угроз и аварий ЖКХ. Мы отвечаем на вопросы по установке, настройке, оплате, багам и предложениям.</p>
        </section>

        <section className="doc-section">
          <h2>Каналы поддержки</h2>
          <div className="contact-grid">
            <article className="contact-card">
              <div className="contact-icon">🎫</div>
              <h3 className="contact-title">Тикет-бот (рекомендуется)</h3>
              <p className="contact-desc">Создайте тикет — получите номер, статус и ответ в личку. История сохраняется.</p>
              <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noreferrer noopener" className="contact-link">Открыть @SecretHeroSupportBot</a>
            </article>
            <article className="contact-card">
              <div className="contact-icon">👤</div>
              <h3 className="contact-title">Прямой контакт автора</h3>
              <p className="contact-desc">Для срочных вопросов, безопасности, партнёрства. Отвечаю в рабочее время.</p>
              <a href="https://t.me/SecretHeroSupport" target="_blank" rel="noreferrer noopener" className="contact-link">Написать @SecretHeroSupport</a>
            </article>
            <article className="contact-card">
              <div className="contact-icon">📧</div>
              <h3 className="contact-title">Email</h3>
              <p className="contact-desc">Для официальных обращений, договоров, претензий, GDPR-запросов.</p>
              <a href="mailto:admin@hydravpsvpn.ru" className="contact-link">admin@hydravpsvpn.ru</a>
            </article>
          </div>
        </section>

        <section className="doc-section">
          <h2>SLA — время ответа</h2>
          <ul>
            <li><strong>Рабочее время:</strong> пн–пт 09:00–17:30 (МСК).</li>
            <li><strong>Первичный ответ:</strong> до 4 часов в рабочее время, до 24 часов — в нерабочее.</li>
            <li><strong>Решение типовых вопросов:</strong> 1–2 рабочих дня.</li>
            <li><strong>Сложные баги / установка:</strong> до 5 рабочих дней.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>Что ускорит помощь</h2>
          <ol>
            <li>Версия бота/панели (<code>/version</code> в боте или футер панели).</li>
            <li>Способ установки: Docker (install.sh) / Docker Compose / ручная.</li>
            <li>ОС и архитектура сервера (ARM / x64).</li>
            <li>Логи: <code>docker logs radar_container --tail 100</code> или <code>journalctl -u radar -n 100</code>.</li>
            <li>Скриншот ошибки или полный текст traceback.</li>
            <li>Что уже пробовали исправить.</li>
          </ol>
        </section>

        <section className="doc-section">
          <h2>Частые вопросы (FAQ)</h2>
          <h3>Бот не присылает оповещения</h3>
          <p>Проверьте: локации добавлены верно (город/улица/дом)? Включены ли нужные категории в настройках? Не включены ли «тихие часы»? Бот не заблокирован? Источники в городе настроены админом (команда <code>/sources</code> в панели)?</p>

          <h3>Погода не работает / «нет координат»</h3>
          <p>Удалите локацию и добавьте заново — координаты определяются при добавлении. Если город не находится — напишите в поддержку, добавим в геокодер.</p>

          <h3>Как купить подписку / арендовать сервер</h3>
          <p>В боте: Меню → Подписки / Сервер → выбрать тариф → оплатить Stars или через платёжную систему. Доступ придёт автоматически.</p>

          <h3>Хочу установить у себя (self-hosted)</h3>
          <p>Одна команда: <code>bash &lt;(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)</code></p>
          <p>Требования: Docker, Docker Compose, порт 80/443, домен (для HTTPS и TG Login Widget).</p>
        </section>

        <section className="doc-section">
          <h2>Как отправить обращение</h2>
          <p>Откройте <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noreferrer noopener">тикет-бота</a> и опишите вопрос там — он создаст обращение и покажет его номер. Если бот недоступен, напишите <a href="https://t.me/SecretHeroSupport" target="_blank" rel="noreferrer noopener">@SecretHeroSupport</a>.</p>
        </section>
      </div>
    </PageLayout>
  );
}
