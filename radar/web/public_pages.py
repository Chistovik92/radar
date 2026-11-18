"""Публичные страницы сервиса: Privacy, Terms, Support, Pricing.

Все страницы рендерятся без авторизации. Контент адаптирован из шаблонов telegra.ph
с данными проекта Radar.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from .. import __version__ as VERSION
# PAGE_STYLE local

# Общие стили для публичных страниц
PUBLIC_STYLE = """
/* ============================================================
   PUBLIC PAGES STYLES (Privacy, Terms, Support, Pricing)
   ============================================================ */

.public-page {
  max-width: 880px;
  margin: 0 auto;
  padding: clamp(40px, 6vw, 64px) clamp(20px, 5vw, 60px);
}
.public-header {
  text-align: center;
  margin-bottom: 48px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--line);
}
.public-title {
  margin: 0 0 12px;
  font-size: clamp(28px, 4vw, 38px);
  font-weight: 800;
  letter-spacing: -0.5px;
  color: var(--text);
}
.public-subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 16px;
  max-width: 640px;
  margin-left: auto;
  margin-right: auto;
}
.public-content {
  line-height: 1.8;
  color: var(--text);
}
.public-content h2 {
  margin: 32px 0 16px;
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}
.public-content h3 {
  margin: 24px 0 12px;
  font-size: 17px;
  font-weight: 600;
  color: var(--text);
}
.public-content p { margin: 0 0 16px; }
.public-content ul { margin: 0 0 16px; padding-left: 24px; }
.public-content li { margin-bottom: 8px; line-height: 1.7; }
.public-content a { color: var(--link); text-decoration: none; }
.public-content a:hover { text-decoration: underline; }
.public-content code {
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9em;
  color: var(--accent);
}
.public-content pre {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px;
  overflow-x: auto;
  margin: 16px 0;
}
.public-content pre code { background: none; padding: 0; color: var(--text); }
.public-content blockquote {
  border-left: 3px solid var(--accent);
  padding-left: 16px;
  margin: 16px 0;
  color: var(--muted);
  font-style: italic;
}
.public-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 24px 0;
  font-size: 14px;
}
.public-content th, .public-content td {
  border: 1px solid var(--line);
  padding: 12px 16px;
  text-align: left;
}
.public-content th { background: var(--surface-2); font-weight: 700; }
.public-content tr:nth-child(even) td { background: var(--surface-2); }

/* Support form */
.support-form {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 28px;
  margin-top: 24px;
}
.form-group { margin-bottom: 20px; }
.form-label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: var(--text);
}
.form-input, .form-select, .form-textarea {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 15px;
  font-family: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.form-input:focus, .form-select:focus, .form-textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.form-textarea { min-height: 140px; resize: vertical; }
.form-submit {
  width: 100%;
  padding: 14px 24px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.form-submit:hover { box-shadow: 0 4px 16px rgba(79, 140, 255, 0.4); }
.form-submit:active { transform: scale(0.98); }
.form-note { margin-top: 12px; font-size: 13px; color: var(--muted); text-align: center; }

/* Pricing cards */
.pricing-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  margin-top: 32px;
}
.pricing-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 32px 28px;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
}
.pricing-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow);
  border-color: var(--accent);
}
.pricing-card.popular { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.pricing-name { font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.pricing-price { font-size: 36px; font-weight: 800; color: var(--text); margin-bottom: 4px; }
.pricing-period { color: var(--muted); font-size: 14px; margin-bottom: 20px; }
.pricing-features { list-style: none; padding: 0; margin: 0 0 24px; flex: 1; }
.pricing-features li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 14px;
  color: var(--text);
  line-height: 1.5;
}
.pricing-features li::before {
  content: "✓";
  color: var(--ok);
  font-weight: 700;
  flex-shrink: 0;
}
.pricing-btn {
  display: block;
  text-align: center;
  padding: 14px 24px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 15px;
  text-decoration: none;
  transition: transform 0.15s, background 0.15s;
}
.pricing-btn-primary {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: white;
}
.pricing-btn-primary:hover { background: linear-gradient(135deg, var(--accent-2), var(--accent)); }
.pricing-btn-ghost {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--line);
}
.pricing-btn-ghost:hover { border-color: var(--accent); }
.pricing-note { margin-top: 24px; padding-top: 24px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }

/* Contact cards */
.contact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 20px;
  margin-top: 24px;
}
.contact-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 24px;
  text-align: center;
  transition: transform 0.2s, border-color 0.2s;
}
.contact-card:hover { transform: translateY(-2px); border-color: var(--accent); }
.contact-icon { font-size: 36px; margin-bottom: 12px; }
.contact-title { margin: 0 0 8px; font-size: 17px; font-weight: 700; color: var(--text); }
.contact-desc { margin: 0 0 16px; color: var(--muted); font-size: 14px; }
.contact-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--text);
  text-decoration: none;
  font-weight: 600;
  font-size: 14px;
  transition: border-color 0.15s, background 0.15s;
}
.contact-link:hover { border-color: var(--accent); background: var(--accent-soft); }

/* Last updated badge */
.last-updated {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 24px;
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
"""

# Базовый шаблон страницы
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#141824">
  <title>{title} — Радар v{VERSION}</title>
  <style>{PAGE_STYLE}{PUBLIC_STYLE}</style>
  <script>
(function() {
  const KEY = 'radar_theme';
  const root = document.documentElement;
  const themes = ['dark', 'light', 'matrix', 'ark'];
  function apply(t) {
    root.setAttribute('data-theme', t);
    localStorage.setItem(KEY, t);
  }
  function init() {
    const saved = localStorage.getItem(KEY);
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    apply(saved || (prefersDark ? 'dark' : 'light'));
  }
  window.RadarTheme = { apply, init, themes };
  init();
})();
</script>
</head>
<body>
  <header>
    <div class="brand">Радар <span class="version">v{VERSION}</span></div>
    <nav>
      <a href="/">Лендинг</a>
      <a href="/privacy">Политика</a>
      <a href="/terms">Соглашение</a>
      <a href="/support">Поддержка</a>
      <a href="/pricing">Тарифы</a>
      <a href="/login">Вход</a>
    </nav>
  </header>

  <main>
    <article class="public-page">
      <header class="public-header">
        <span class="last-updated">Обновлено: ноябрь 2026</span>
        <h1 class="public-title">{title}</h1>
        <p class="public-subtitle">{subtitle}</p>
      </header>
      <div class="public-content">
{content}
      </div>
    </article>
  </main>

  <footer class="landing-footer">
    <div class="footer-grid">
      <div class="footer-col">
        <h4>Проект</h4>
        <ul>
          <li><a href="https://github.com/Chistovik92/radar">GitHub репозиторий</a></li>
          <li><a href="https://github.com/Chistovik92/radar/releases">Релизы</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Документы</h4>
        <ul>
          <li><a href="/privacy">Политика конфиденциальности</a></li>
          <li><a href="/terms">Пользовательское соглашение</a></li>
          <li><a href="/support">Поддержка</a></li>
          <li><a href="/pricing">Тарифы и цены</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Бот и каналы</h4>
        <ul>
          <li><a href="https://t.me/SecretHeroBot">@SecretHeroBot</a></li>
          <li><a href="https://t.me/SecretHeroSupport">Поддержка (@SecretHeroSupport)</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Технически</h4>
        <ul>
          <li>Python 3.11+ · aiohttp · aiogram</li>
          <li>SQLite / PostgreSQL (asyncpg)</li>
          <li>Docker · Caddy · systemd</li>
          <li>ARM (RK3318) / x64</li>
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <span>Радар v{VERSION} · </span>
      <a href="https://github.com/Chistovik92/radar/blob/main/LICENSE">GPL-3.0</a>
      <span> · Автор: </span>
      <a href="https://github.com/Chistovik92">SecretHero</a>
      <span> · </span>
      <span class="mekbuda">mekbuda</span>
    </div>
  </footer>
</body>
</html>"""


# ============================================================
# POLICY — Политика конфиденциальности
# ============================================================

PRIVACY_CONTENT = """
<p><strong>Проект:</strong> «Радар» (далее — Проект, Бот, Система) — система мониторинга городских угроз и аварий ЖКХ по адресам пользователя.</p>
<p><strong>Бот в Telegram:</strong> <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener">@SecretHeroBot</a></p>
<p><strong>Репозиторий:</strong> <a href="https://github.com/Chistovik92/radar" target="_blank" rel="noopener">github.com/Chistovik92/radar</a></p>
<p><strong>Автор:</strong> SecretHero</p>
<p><strong>Версия:</strong> {VERSION} (ноябрь 2026)</p>

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

<h2>2. Для чего используются данные</h2>
<ul>
  <li>Сопоставление входящих событий (МЧС, ЖКХ, БПЛА, погода) с локациями пользователя и отправка релевантных оповещений в Telegram.</li>
  <li>Предоставление погоды по сохранённым координатам (через Open-Meteo API).</li>
  <li>Работа веб-панели: авторизация через Telegram Login Widget, отображение профиля, локаций, истории оповещений.</li>
  <li>Управление подписками и доступами к приватному серверу (если пользователь их приобрёл).</li>
  <li>Модерация источников и пользователей (для модераторов и выше).</li>
</ul>

<h2>3. Куда передаются данные</h2>
<ul>
  <li><strong>Telegram</strong> — оповещения, меню бота, веб-апп виджеты, платежи через Telegram Stars. Данные не выходят за пределы чата пользователя с ботом.</li>
  <li><strong>Google Gemini API</strong> — тексты постов из публичных каналов/РСС отправляются для извлечения структурированных событий (город, улица, дом, тип, время, рекомендации). Передаются только тексты постов, без персональных идентификаторов пользователей.</li>
  <li><strong>Open-Meteo API</strong> — запрос погоды по координатам (lat/lon). Никаких идентификаторов пользователя не передаётся.</li>
  <li><strong>Платёжные сервисы</strong> — при оплате обрабатываются сумма, описание товара и идентификатор заказа; зачисление подписки происходит по подтверждению платежа.</li>
</ul>

<h2>4. Хранение и безопасность</h2>
<ul>
  <li>Основная БД: SQLite (файл <code>radar.db</code>) или PostgreSQL — на сервере пользователя (self-hosted). Автор проекта не имеет доступа к вашей базе.</li>
  <li>Бэкапы: создаются командой <code>/backup</code> в панели или скриптом, хранятся на том же сервере в зашифрованном виде (age/GPG).</li>
  <li>Сессии веб-панели: в памяти процесса, TTL 4 часа, куки с флагом <code>HttpOnly; Secure; SameSite=Lax</code>.</li>
  <li>Пароли не хранятся — вход только через Telegram Login Widget (HMAC от токена бота) или разовый код из бота.</li>
</ul>

<h2>5. Права пользователя</h2>
<ul>
  <li>Удаление своего аккаунта: в боте → Меню → Профиль → «Удалить аккаунт» (полная очистка локаций, настроек, истории, подписок).</li>
  <li>Экспорт данных: через веб-панель (профиль) или запрос в поддержку.</li>
  <li>Отказ от оповещений: отключение категорий в настройках или блокировка бота.</li>
</ul>

<h2>6. Сроки хранения</h2>
<ul>
  <li>Локации и настройки — до удаления аккаунта пользователем.</li>
  <li>История оповещений — последние 500 сообщений на пользователя (ротация).</li>
  <li>Логи авторизации в панели — в памяти, очищаются при перезапуске панели.</li>
  <li>Данные подписок и доступов — до истечения срока + 30 дней для поддержки.</li>
</ul>

<h2>7. Cookies и локальное хранение</h2>
<ul>
  <li><code>radar_session</code> — сессия веб-панели (HttpOnly, Secure, SameSite=Lax).</li>
  <li><code>radar_theme</code> — выбранная тема (localStorage, не передаётся на сервер).</li>
  <li>Никаких tracking-куки, пикселей, аналитики (GA, Яндекс.Метрика и т.д.) — нет.</li>
</ul>

<h2>8. Контакты по вопросам конфиденциальности</h2>
<p>Тикет-система: <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener">@SecretHeroSupportBot</a><br>
Email: <a href="mailto:support@radar-project.ru">support@radar-project.ru</a></p>
"""


# ============================================================
# TERMS — Пользовательское соглашение
# ============================================================

TERMS_CONTENT = """
<p><strong>Проект:</strong> «Радар» — бот и веб-панель для мониторинга городских угроз и аварий ЖКХ.<br>
<strong>Бот:</strong> <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener">@SecretHeroBot</a><br>
<strong>Автор:</strong> SecretHero<br>
<strong>Версия:</strong> {VERSION} (ноябрь 2026)</p>

<h2>1. Общие положения</h2>
<p>Начиная пользоваться ботом @SecretHeroBot и веб-панелью, вы соглашаетесь с настоящими условиями. Если не согласны — не используйте сервис.</p>
<p>Проект предоставляется «как есть» (as is), без гарантий бесперебойной работы, точности оповещений или доступности источников. Бот <strong>не заменяет официальные каналы оповещения</strong> (МЧС, администрация, сирены, СМС-рассылки).</p>

<h2>2. Бесплатные функции (всегда бесплатно)</h2>
<ul>
  <li>Оповещения об угрозах: БПЛА, ракетная опасность, воздушная тревога, отбой.</li>
  <li>Оповещения МЧС: ЧС, штормовые предупреждения, эвакуация, паводки, пожары.</li>
  <li>Оповещения ЖКХ: отключения воды, электричества, газа, отопления — адресно по улице/дому.</li>
  <li>Базовая погода: текущая, почасовая (8 ч), 3 дня — текстом.</li>
  <li>Проверка ссылок на фишинг — 200 запросов в сутки.</li>
  <li>ИИ-ассистент (базовый лимит запросов в сутки).</li>
</ul>

<h2>3. Платные функции</h2>
<table>
  <thead>
    <tr><th>Продукт</th><th>Цена</th><th>Описание</th></tr>
  </thead>
  <tbody>
    {DIGEST_PLAN_ROWS}
    <tr><td>Погода картинкой</td><td>Входит в подборки</td><td>Готовое изображение: дневная/ночная тема, вектор ветра, фаза луны</td></tr>
    <tr><td>Аренда приватного сервера</td><td>Цена показана в боте</td><td>Срок, трафик и число устройств зависят от тарифа</td></tr>
    <tr><td>Проверка ссылок (без лимита)</td><td>Входит в подборки</td><td>Подписчики — без дневного лимита</td></tr>
  </tbody>
</table>
<p><strong>Важно:</strong> Подписка на подборки оплачивается через Telegram Stars. Доступные способы оплаты аренды сервера показываются в боте перед заказом.</p>

<h2>4. Подписка и отмена</h2>
<ul>
  <li>Подписка на подборки оформляется на выбранный срок через Telegram Stars; автоматического продления нет.</li>
  <li>Аренда приватного сервера оформляется на выбранный срок; доступ выдаётся после подтверждения оплаты.</li>
  <li>Возврат средств: по заявке в поддержке в течение 14 дней с момента оплаты, если сервис не был предоставлен.</li>
</ul>

<h2>5. Ограничения ответственности</h2>
<ul>
  <li>Бот агрегирует публичные источники. Точность, полнота и своевременность зависят от источников.</li>
  <li>ИИ (Gemini) может ошибаться в извлечении адресов или типа события. Всегда проверяйте первоисточник (ссылка в оповещении).</li>
  <li>Проект не несёт ответственности за упущенные угрозы, ложные срабатывания или задержки доставки сообщений Telegram.</li>
  <li>Приватный сервер предоставляется для законного использования по назначению. Ответственность за использование лежит на пользователе.</li>
</ul>

<h2>6. Запреты</h2>
<ul>
  <li>Автоматизированные запросы к API бота/панели без согласия автора (rate limit: 30 req/min).</li>
  <li>Перепродажа доступов к приватному серверу, подборок или ключей без согласования.</li>
  <li>Попытки несанкционированного доступа, инъекции, DoS, сканирование уязвимостей.</li>
  <li>Использование бота для спама, рассылок, мошенничества.</li>
</ul>

<h2>7. Интеллектуальная собственность</h2>
<p>Код проекта — GPL-3.0 (<a href="https://github.com/Chistovik92/radar/blob/main/LICENSE" target="_blank" rel="noopener">LICENSE</a>). Вы можете форкать, модифицировать, запускать у себя. Название «Радар», бренд @SecretHeroBot, логотип — товарные знаки автора; при форке меняйте название и брендинг.</p>

<h2>8. Изменения условий</h2>
<p>Условия могут обновляться. Актуальная версия всегда на этой странице. Продолжение использования после изменений означает согласие.</p>

<h2>9. Контакты</h2>
<p>Поддержка: <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener">@SecretHeroSupportBot</a> (тикет-бот)<br>
Email: <a href="mailto:support@radar-project.ru">support@radar-project.ru</a></p>
"""


# ============================================================
# SUPPORT — Поддержка
# ============================================================

SUPPORT_CONTENT = """
<p><strong>Радар v{VERSION}</strong> — бот мониторинга городских угроз и аварий ЖКХ.<br>
Мы отвечаем на вопросы по установке, настройке, оплате, багам и предложениям.</p>

<h2>Каналы поддержки</h2>
<div class="contact-grid">
  <article class="contact-card">
    <div class="contact-icon">🎫</div>
    <h3 class="contact-title">Тикет-бот (рекомендуется)</h3>
    <p class="contact-desc">Создайте тикет — получите номер, статус и ответ в личку. История сохраняется.</p>
    <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener" class="contact-link">Открыть @SecretHeroSupportBot</a>
  </article>
  <article class="contact-card">
    <div class="contact-icon">👤</div>
    <h3 class="contact-title">Прямой контакт автора</h3>
    <p class="contact-desc">Для срочных вопросов, безопасности, партнёрства. Отвечаю в рабочее время.</p>
    <a href="https://t.me/SecretHeroSupport" target="_blank" rel="noopener" class="contact-link">Написать @SecretHeroSupport</a>
  </article>
  <article class="contact-card">
    <div class="contact-icon">📧</div>
    <h3 class="contact-title">Email</h3>
    <p class="contact-desc">Для официальных обращений, договоров, претензий, GDPR-запросов.</p>
    <a href="mailto:support@radar-project.ru" class="contact-link">support@radar-project.ru</a>
  </article>
</div>

<h2>SLA — время ответа</h2>
<ul>
  <li><strong>Рабочее время:</strong> пн–пт 09:00–17:30 (МСК).</li>
  <li><strong>Первичный ответ:</strong> до 4 часов в рабочее время, до 24 часов — в нерабочее.</li>
  <li><strong>Решение типовых вопросов:</strong> 1–2 рабочих дня.</li>
  <li><strong>Сложные баги / установка:</strong> до 5 рабочих дней.</li>
</ul>

<h2>Что ускорит помощь</h2>
<ol>
  <li>Версия бота/панели (<code>/version</code> в боте или футер панели).</li>
  <li>Способ установки: Docker (install.sh) / Docker Compose / ручная.</li>
  <li>ОС и архитектура сервера (ARM / x64).</li>
  <li>Логи: <code>docker logs radar_container --tail 100</code> или <code>journalctl -u radar -n 100</code>.</li>
  <li>Скриншот ошибки или полный текст traceback.</li>
  <li>Что уже пробовали исправить.</li>
</ol>

<h2>Частые вопросы (FAQ)</h2>
<h3>Бот не присылает оповещения</h3>
<p>Проверьте: локации добавлены верно (город/улица/дом)? Включены ли нужные категории в настройках? Не включены ли «тихие часы»? Бот не заблокирован? Источники в городе настроены админом (команда <code>/sources</code> в панели)?</p>

<h3>Погода не работает / «нет координат»</h3>
<p>Удалите локацию и добавьте заново — координаты определяются при добавлении. Если город не находится — напишите в поддержку, добавим в геокодер.</p>

<h3>Как купить подписку / арендовать сервер</h3>
<p>В боте: Меню → Подписки / Сервер → выбрать тариф → оплатить Stars или через платёжную систему. Доступ придёт автоматически.</p>

<h3>Хочу установить у себя (self-hosted)</h3>
<p>Одна команда: <code>bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)</code><br>
Требования: Docker, Docker Compose, порт 80/443, домен (для HTTPS и TG Login Widget).</p>

<h2>Как отправить обращение</h2>
<p>Откройте <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener">тикет-бота</a> и опишите вопрос там — он создаст обращение и покажет его номер. Если бот недоступен, напишите <a href="https://t.me/SecretHeroSupport" target="_blank" rel="noopener">@SecretHeroSupport</a>.</p>
"""


# ============================================================
# PRICING — Тарифы и цены
# ============================================================

PRICING_CONTENT = """
<p><strong>Радар v{VERSION}</strong> — честные цены, без скрытых платежей. Все оповещения об угрозах — <strong>бесплатно навсегда</strong>.</p>
<p>Подписка на подборки оплачивается через Telegram Stars. Способы оплаты аренды приватного сервера и итоговая сумма показываются в боте до подтверждения заказа.</p>

<div class="pricing-grid">
  <article class="pricing-card">
    <div class="pricing-name">🛡 Оповещения об угрозах</div>
    <div class="pricing-price">0 ₽</div>
    <div class="pricing-period">бесплатно навсегда</div>
    <ul class="pricing-features">
      <li>БПЛА / ракетная опасность / воздушная тревога / отбой</li>
      <li>МЧС: ЧС, штормовые предупреждения, эвакуация</li>
      <li>ЖКХ: вода, свет, газ, отопление — адресно</li>
      <li>Базовая погода (текст): текущая, 8 ч, 3 дня</li>
      <li>Проверка ссылок — 200/сутки</li>
      <li>ИИ-ассистент — базовый лимит</li>
      <li>Без рекламы, без трекинга</li>
    </ul>
    <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener" class="pricing-btn pricing-btn-primary">Запустить бота</a>
  </article>

  {DIGEST_PLAN_CARDS}

  <article class="pricing-card">
    <div class="pricing-name">🔐 Аренда приватного сервера</div>
    <div class="pricing-price">Тарифы в боте</div>
    <div class="pricing-period">срок и цена до оплаты</div>
    <ul class="pricing-features">
      <li>Аренда приватного сервера</li>
      <li>Срок, трафик и число устройств зависят от тарифа</li>
      <li>Управление заказом в боте</li>
    </ul>
    <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener" class="pricing-btn pricing-btn-ghost">Узнать тарифы в боте</a>
  </article>
</div>

<div class="pricing-note">
  <p><strong>Важные замечания:</strong></p>
  <ul>
    <li>Цены подписки указаны в Telegram Stars (⭐); стоимость аренды сервера показывается в выбранном тарифе.</li>
    <li>Приватный сервер предоставляется для законного использования по назначению.</li>
    <li>Подписка на подборки оплачивается Stars; доступные способы оплаты аренды зависят от настроек бота.</li>
    <li>Возврат средств: заявка в поддержку в течение 14 дней, если сервис не предоставлен.</li>
    <li>Сам-хостинг (установка на свой сервер) — полностью бесплатно, код открыт (GPL-3.0).</li>
  </ul>
</div>

<h2>Сравнение: бесплатно vs подписка</h2>
<table>
  <thead>
    <tr><th>Функция</th><th>Бесплатно</th><th>Подписка (Stars)</th></tr>
  </thead>
  <tbody>
    <tr><td>Тревоги БПЛА / МЧС / ЖКХ</td><td>✅ Полностью</td><td>✅ Полностью</td></tr>
    <tr><td>Погода (текст)</td><td>✅ Текущая, 8ч, 3 дня</td><td>✅ + картинка, вектор ветра, луна</td></tr>
    <tr><td>Новостные подборки</td><td>❌</td><td>✅ 18 тем, ИИ-сводки, расписание</td></tr>
    <tr><td>Проверка ссылок</td><td>200/сутки</td><td>Без лимита</td></tr>
    <tr><td>ИИ-ассистент</td><td>Базовый лимит</td><td>Расширенный лимит</td></tr>
    <tr><td>Аренда приватного сервера</td><td>❌</td><td>Отдельно (₽)</td></tr>
  </tbody>
</table>

<h2>Как оплатить</h2>
<ol>
  <li>Откройте бота: <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener">@SecretHeroBot</a></li>
  <li>Меню → «Подписки» или «Сервер»</li>
  <li>Выберите тариф и один из доступных способов оплаты</li>
  <li>Доступ активируется автоматически</li>
</ol>

<p style="text-align:center; margin-top:32px; color:var(--muted);">
  Вопросы по оплате? <a href="/support">Напишите в поддержку</a>
</p>
"""


def _with_plans(content: str) -> str:
    """Публичные цены берутся из того же списка, что и счета в боте."""
    from ..digest import TOPICS
    from ..handlers.digest import _plans

    plans = _plans()
    rows = "".join(
        f'<tr><td>Новостные подборки — {days} дней</td>'
        f'<td>{stars} ⭐</td><td>{len(TOPICS)} тематик, ИИ-сводки, '
        'доставка по расписанию</td></tr>'
        for days, stars in plans
    )
    cards = "".join(
        f'<article class="pricing-card{" popular" if index == 0 else ""}">'
        f'<div class="pricing-name">📰 Новостные подборки</div>'
        f'<div class="pricing-price">{stars} ⭐</div>'
        f'<div class="pricing-period">{days} дней</div>'
        '<ul class="pricing-features">'
        f'<li>{len(TOPICS)} тематик в одной подписке</li>'
        '<li>ИИ-сводки и доставка по расписанию</li>'
        '<li>Погода картинкой</li>'
        '<li>Скачивание видео без дневного лимита подписчика</li>'
        '</ul>'
        '<a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener" '
        'class="pricing-btn pricing-btn-primary">Оформить в боте за Stars</a>'
        '</article>'
        for index, (days, stars) in enumerate(plans)
    )
    return (content
            .replace("{DIGEST_PLAN_ROWS}", rows)
            .replace("{DIGEST_PLAN_CARDS}", cards))


def _render_page(title: str, subtitle: str, content: str) -> str:
    """Рендерит страницу по шаблону."""
    # Базовые стили панели — лениво (panel импортирует public_pages наверху,
    # import на уровне модуля замкнул бы цикл).
    from .panel import PAGE_STYLE  # noqa: F401  (подстановка ниже)

    # Нельзя применять str.format ко всему HTML: фигурные скобки в JS и CSS
    # являются кодом, а не placeholders. Подставляем только известные имена.
    page = PAGE_TEMPLATE
    for key, value in {
        "title": title,
        "subtitle": subtitle,
        "content": content.replace("{VERSION}", VERSION),
        "VERSION": VERSION,
        "PAGE_STYLE": PAGE_STYLE,
        "PUBLIC_STYLE": PUBLIC_STYLE,
    }.items():
        page = page.replace("{" + key + "}", value)
    return page


def render_privacy_page() -> str:
    return _render_page(
        "Политика конфиденциальности",
        "Какие данные собираются, как используются и где хранятся",
        PRIVACY_CONTENT,
    )


def render_terms_page() -> str:
    return _render_page(
        "Пользовательское соглашение",
        "Правила использования, бесплатные и платные функции, ограничения ответственности",
        _with_plans(TERMS_CONTENT),
    )


def render_support_page() -> str:
    return _render_page(
        "Поддержка",
        "Тикет-система, контакты, SLA и ответы на частые вопросы",
        SUPPORT_CONTENT,
    )


def render_pricing_page() -> str:
    return _render_page(
        "Тарифы и цены",
        "Оповещения бесплатно навсегда. Актуальные тарифы подписки и порядок оформления",
        _with_plans(PRICING_CONTENT),
    )
