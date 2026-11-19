import PageLayout from '../components/PageLayout';

export default function Privacy() {
  return (
    <PageLayout>
      <div className="doc-page">
        <header className="page-title">
          <p className="update-date">Обновлено: ноябрь 2026</p>
          <h1>Политика конфиденциальности</h1>
          <p className="page-subtitle">
            Какие данные собираются, как используются и где хранятся
          </p>
        </header>

        <section className="doc-intro">
          <p><strong>Проект:</strong> «Радар» (далее — Проект, Бот, Система) — система мониторинга городских угроз и аварий ЖКХ по адресам пользователя.</p>
          <p><strong>Бот в Telegram:</strong> <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener">@SecretHeroBot</a></p>
          <p><strong>Репозиторий:</strong> <a href="https://github.com/Chistovik92/radar" target="_blank" rel="noreferrer noopener">github.com/Chistovik92/radar</a></p>
          <p><strong>Автор:</strong> SecretHero</p>
          <p><strong>Версия:</strong> 5.11.6 (ноябрь 2026)</p>
        </section>

        <section className="doc-section">
          <h2>1. Какие данные собираются</h2>
          <p>Проект собирает минимально необходимые данные для предоставления сервиса оповещений:</p>
          <ul>
            <li><strong>Telegram ID</strong> — уникальный идентификатор пользователя в Telegram (число).</li>
            <li><strong>Локации</strong> — города, улицы, номера домов, которые пользователь добавляет через бота для получения оповещений. Координаты (lat/lon) определяются автоматически по введённому адресу.</li>
            <li><strong>Настройки уведомлений</strong> — типы событий (БПЛА, МЧС, ЖКХ, погода), тихие часы, формат сообщений (текст/картинка), включение/выключение категорий.</li>
            <li><strong>Роль в системе</strong> — user / moderator / admin / superadmin (назначается администраторами).</li>
            <li><strong>Подписка и доступы к приватному серверу</strong> — при покупке: ID подписки, срок действия, выданные ключи доступа.</li>
            <li><strong>Технические логи</strong> — IP-адреса при входе в веб-панель (для защиты от брутфорса), User-Agent, время запросов. Хранятся в памяти процесса панели, не записываются в БД.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>2. Для чего используются данные</h2>
          <ul>
            <li>Сопоставление входящих событий (МЧС, ЖКХ, БПЛА, погода) с локациями пользователя и отправка релевантных оповещений в Telegram.</li>
            <li>Предоставление погоды по сохранённым координатам (через Open-Meteo API).</li>
            <li>Работа веб-панели: авторизация через Telegram Login Widget, отображение профиля, локаций, истории оповещений.</li>
            <li>Управление подписками и доступами к приватному серверу (если пользователь их приобрёл).</li>
            <li>Модерация источников и пользователей (для модераторов и выше).</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>3. Куда передаются данные</h2>
          <ul>
            <li><strong>Telegram</strong> — оповещения, меню бота, веб-апп виджеты, платежи через Telegram Stars. Данные не выходят за пределы чата пользователя с ботом.</li>
            <li><strong>Google Gemini API</strong> — тексты постов из публичных каналов/РСС отправляются для извлечения структурированных событий (город, улица, дом, тип, время, рекомендации). Передаются только тексты постов, без персональных идентификаторов пользователей.</li>
            <li><strong>Open-Meteo API</strong> — запрос погоды по координатам (lat/lon). Никаких идентификаторов пользователя не передаётся.</li>
            <li><strong>Платёжные сервисы</strong> — при оплате обрабатываются сумма, описание товара и идентификатор заказа; зачисление подписки происходит по подтверждению платежа.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>4. Хранение и безопасность</h2>
          <ul>
            <li>Основная БД: SQLite (файл <code>radar.db</code>) или PostgreSQL — на сервере пользователя (self-hosted). Автор проекта не имеет доступа к вашей базе.</li>
            <li>Бэкапы: создаются командой <code>/backup</code> в панели или скриптом, хранятся на том же сервере в зашифрованном виде (age/GPG).</li>
            <li>Сессии веб-панели: в памяти процесса, TTL 4 часа, куки с флагом <code>HttpOnly; Secure; SameSite=Lax</code>.</li>
            <li>Пароли не хранятся — вход только через Telegram Login Widget (HMAC от токена бота) или разовый код из бота.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>5. Права пользователя</h2>
          <ul>
            <li>Удаление своего аккаунта: в боте → Меню → Профиль → «Удалить аккаунт» (полная очистка локаций, настроек, истории, подписок).</li>
            <li>Экспорт данных: через веб-панель (профиль) или запрос в поддержку.</li>
            <li>Отказ от оповещений: отключение категорий в настройках или блокировка бота.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>6. Сроки хранения</h2>
          <ul>
            <li>Локации и настройки — до удаления аккаунта пользователем.</li>
            <li>История оповещений — последние 500 сообщений на пользователя (ротация).</li>
            <li>Логи авторизации в панели — в памяти, очищаются при перезапуске панели.</li>
            <li>Данные подписок и доступов — до истечения срока + 30 дней для поддержки.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>7. Cookies и локальное хранение</h2>
          <ul>
            <li><code>radar_session</code> — сессия веб-панели (HttpOnly, Secure, SameSite=Lax).</li>
            <li><code>radar_theme</code> — выбранная тема (localStorage, не передаётся на сервер).</li>
            <li>Никаких tracking-куки, пикселей, аналитики (GA, Яндекс.Метрика и т.д.) — нет.</li>
          </ul>
        </section>

        <section className="doc-section">
          <h2>8. Контакты по вопросам конфиденциальности</h2>
          <p>Тикет-система: <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noreferrer noopener">@SecretHeroSupportBot</a></p>
          <p>Email: <a href="mailto:support@radar-project.ru">support@radar-project.ru</a></p>
        </section>
      </div>
    </PageLayout>
  );
}
