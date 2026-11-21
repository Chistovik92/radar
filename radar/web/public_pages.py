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
<p><strong>Проект:</strong> «Радар» — бот <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener">@SecretHeroBot</a> и
веб-панель <a href="/">radar-project.ru</a> (далее — «Сервис») для мониторинга городских угроз и аварий ЖКХ.</p>
<p><strong>Автор:</strong> SecretHero<br>
<strong>Версия:</strong> {VERSION} (ноябрь 2026)</p>

<h2>1. Общие положения</h2>
<p>1.1. Настоящая Политика конфиденциальности (далее — «Политика») регулирует порядок обработки и защиты информации, которую Пользователь передаёт при использовании Сервиса.</p>
<p>1.2. Используя Сервис, Пользователь подтверждает своё согласие с условиями Политики. Если Пользователь не согласен с условиями — он обязан прекратить использование Сервиса.</p>

<h2>2. Сбор информации</h2>
<p>2.1. Сервис может собирать следующие типы данных:</p>
<ul>
  <li><strong>идентификаторы аккаунта</strong> — Telegram ID (уникальный числовой идентификатор пользователя), никнейм, логин;</li>
  <li><strong>техническую информацию</strong> — IP-адрес и User-Agent при входе в веб-панель (для защиты от перебора паролей), время запросов;</li>
  <li><strong>историю взаимодействий с Сервисом</strong> — добавленные локации (город, улица, дом), настройки уведомлений, история оповещений.</li>
</ul>
<p>2.2. Сервис не требует от Пользователя предоставления паспортных данных, документов, фотографий или другой личной информации, кроме минимально необходимой для работы.</p>
<p>2.3. Техническая информация при входе в веб-панель хранится только в памяти процесса и не записывается в базу данных. Никаких tracking-куки, пикселей и сторонней аналитики (Google Analytics, Яндекс.Метрика и аналоги) Сервис не использует.</p>

<h2>3. Использование информации</h2>
<p>3.1. Сервис может использовать полученную информацию исключительно для:</p>
<ul>
  <li><strong>обеспечения работы функционала</strong> — сопоставление входящих событий (МЧС, ЖКХ, БПЛА, погода) с локациями Пользователя и отправка релевантных оповещений, работа веб-панели и управление подписками;</li>
  <li><strong>связи с Пользователем</strong> — в том числе для уведомлений и поддержки;</li>
  <li><strong>анализа и улучшения работы Сервиса</strong> — модерация источников и пользователей.</li>
</ul>

<h2>4. Передача информации третьим лицам</h2>
<p>4.1. Администрация не передаёт полученные данные третьим лицам, за исключением случаев:</p>
<ul>
  <li>если это требуется по закону;</li>
  <li>если это необходимо для исполнения обязательств перед Пользователем — например, при работе с платёжными системами (обрабатываются сумма, описание товара и идентификатор заказа);</li>
  <li>если Пользователь сам дал на это согласие.</li>
</ul>
<p>4.2. Для работы отдельных функций Сервис обращается к сторонним сервисам: Telegram (доставка оповещений, веб-виджеты, платежи через Telegram Stars), Open-Meteo (прогноз погоды по координатам), Google Gemini (извлечение структурированных событий из публичных постов). В эти сервисы передаётся только минимально необходимое: координаты или текст публикации, без персональных идентификаторов Пользователя.</p>

<h2>5. Хранение и защита данных</h2>
<p>5.1. Данные хранятся в течение срока, необходимого для достижения целей обработки:</p>
<ul>
  <li>локации и настройки — до удаления аккаунта Пользователем;</li>
  <li>история оповещений — последние 500 сообщений на Пользователя (ротация);</li>
  <li>логи авторизации в панели — в памяти, очищаются при перезапуске;</li>
  <li>данные подписок и доступов — до истечения срока плюс 30 дней для поддержки.</li>
</ul>
<p>5.2. Администрация принимает разумные меры для защиты данных (основная БД — SQLite или PostgreSQL на стороне Пользователя, бэкапы в зашифрованном виде, сессии веб-панели с флагом <code>HttpOnly; Secure; SameSite=Lax</code>, вход без хранения паролей — через Telegram Login Widget), но не гарантирует абсолютную безопасность информации при передаче через интернет.</p>

<h2>6. Отказ от ответственности</h2>
<p>6.1. Пользователь понимает и соглашается, что передача информации через интернет всегда сопряжена с рисками.</p>
<p>6.2. Администрация не несёт ответственности за утрату, кражу или раскрытие данных, если это произошло по вине третьих лиц или самого Пользователя.</p>

<h2>7. Изменения в Политике</h2>
<p>7.1. Администрация вправе изменять условия Политики без предварительного уведомления.</p>
<p>7.2. Продолжение использования Сервиса после внесения изменений означает согласие Пользователя с новой редакцией Политики.</p>
<p>По вопросам конфиденциальности и управления своими данными (удаление аккаунта, экспорт данных, отказ от оповещений) Пользователь может обратиться в службу поддержки: <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener">@SecretHeroSupportBot</a> или по email <a href="mailto:admin@hydravpsvpn.ru">admin@hydravpsvpn.ru</a>.</p>
"""


# ============================================================
# TERMS — Пользовательское соглашение
# ============================================================

TERMS_CONTENT = """
<p><strong>Проект:</strong> «Радар» — бот <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener">@SecretHeroBot</a> и
веб-панель <a href="/">radar-project.ru</a> (далее — «Сервис»).<br>
<strong>Автор:</strong> SecretHero<br>
<strong>Версия:</strong> {VERSION} (ноябрь 2026)</p>

<h2>1. Общие положения</h2>
<p>1.1. Настоящее Пользовательское соглашение (далее — «Соглашение») регулирует порядок использования онлайн-сервиса «Радар» — бота <a href="https://t.me/SecretHeroBot" target="_blank" rel="noopener">@SecretHeroBot</a> и веб-панели <a href="/">radar-project.ru</a> (далее — «Сервис»), предоставляемого Администрацией.</p>
<p>1.2. Используя Сервис, включая запуск бота, ввод команды /start, регистрацию, оплату услуг или получение доступа к материалам, Пользователь подтверждает, что полностью ознакомился с условиями настоящего Соглашения и принимает их в полном объёме.</p>
<p>1.3. В случае несогласия с условиями Соглашения Пользователь обязан прекратить использование Сервиса.</p>

<h2>2. Характер услуг и цифровых товаров</h2>
<p>2.1. Сервис предоставляет цифровые товары и услуги нематериального характера, включая, но не ограничиваясь: оповещения об угрозах и авариях ЖКХ, информационные материалы, новостные подборки, аналитические сводки, проверку ссылок, доступ к VPN, аренду приватного сервера и сервисные услуги.</p>
<p>2.2. Материалы, предоставляемые через Сервис, могут включать:</p>
<ul>
  <li>информацию из открытых источников;</li>
  <li>авторские материалы Администрации и/или третьих лиц;</li>
  <li>аналитические обзоры, подборки, рекомендации, структурированные данные.</li>
</ul>
<p>2.3. Пользователь осознаёт и соглашается, что ценность цифровых товаров и услуг Сервиса заключается в систематизации, анализе, форме подачи, сопровождении, поддержке и обновлениях, а не в эксклюзивности отдельных фрагментов информации.</p>
<p>2.4. Сервис не заявляет и не гарантирует уникальность, исключительность или недоступность отдельных элементов материалов вне Сервиса.</p>

<h2>3. Отказ от гарантий и ответственности</h2>
<p>3.1. Сервис предоставляется на условиях «AS IS» («как есть»).</p>
<p>3.2. Администрация не гарантирует:</p>
<ul>
  <li>соответствие Сервиса ожиданиям Пользователя;</li>
  <li>достижение каких-либо финансовых, коммерческих, профессиональных или иных результатов;</li>
  <li>бесперебойную и безошибочную работу Сервиса.</li>
</ul>
<p>3.3. Администрация не несёт ответственности за:</p>
<ul>
  <li>любые прямые или косвенные убытки, включая упущенную выгоду;</li>
  <li>последствия применения Пользователем полученных материалов;</li>
  <li>действия или бездействие третьих лиц;</li>
  <li>временные технические сбои и ограничения доступа.</li>
</ul>
<p>3.4. Все решения о применении материалов, рекомендаций и услуг принимаются Пользователем самостоятельно и на его риск. Сервис не заменяет официальные каналы оповещения (МЧС, администрация, сирены, СМС-рассылки).</p>

<h2>4. Законность использования</h2>
<p>4.1. Сервис не предназначен для поощрения, организации или содействия противоправной деятельности.</p>
<p>4.2. Пользователь обязуется использовать Сервис исключительно в рамках применимого законодательства и правил третьих сторон.</p>
<p>4.3. Ответственность за законность использования материалов и услуг Сервиса полностью возлагается на Пользователя.</p>

<h2>5. Интеллектуальная собственность</h2>
<p>5.1. Все материалы, размещённые в Сервисе, охраняются законодательством об интеллектуальной собственности.</p>
<p>5.2. Пользователю запрещается копировать, распространять, перепродавать, передавать третьим лицам или иным образом использовать материалы Сервиса без разрешения правообладателя.</p>
<p>5.3. Нарушение прав интеллектуальной собственности может повлечь ограничение доступа к Сервису без компенсации.</p>

<h2>6. Ограничение доступа</h2>
<p>6.1. Администрация вправе приостановить или ограничить доступ Пользователя к Сервису в случае:</p>
<ul>
  <li>нарушения условий настоящего Соглашения;</li>
  <li>выявления злоупотреблений;</li>
  <li>требований законодательства или платёжных провайдеров.</li>
</ul>
<p>6.2. Ограничение доступа не освобождает Пользователя от обязательств, возникших ранее.</p>
<p>6.3. Администрация оставляет за собой право отказывать в обслуживании Пользователям, чьи действия могут создавать повышенные риски для Сервиса, платёжных провайдеров или третьих лиц.</p>

<h2>7. Платежи и возвраты</h2>
<p>7.1. Оплата услуг и цифровых товаров производится на условиях, указанных в Сервисе до момента оплаты.</p>
<p>7.2. В связи с нематериальным характером цифровых товаров и услуг, возврат денежных средств после предоставления доступа не осуществляется, за исключением случаев, указанных ниже.</p>
<p>7.3. Возврат средств возможен только если:</p>
<ul>
  <li>услуга не была оказана по технической вине Сервиса;</li>
  <li>доступ к цифровому товару фактически не был предоставлен.</li>
</ul>
<p>7.4. Для рассмотрения вопроса о возврате Пользователь обязан обратиться в службу поддержки в течение 24 часов с момента оплаты.</p>
<p>7.5. Решение о возврате принимается Администрацией индивидуально.</p>
<p>7.6. Пользователь подтверждает, что обязуется не инициировать возврат платежа (chargeback) через платёжные системы без предварительного обращения в службу поддержки Сервиса.</p>

<h2>8. Конфиденциальность</h2>
<p>8.1. Администрация может собирать минимально необходимые технические данные для обеспечения работы Сервиса.</p>
<p>8.2. Администрация принимает разумные меры для защиты данных, однако не гарантирует абсолютную безопасность передаваемой информации.</p>

<h2>9. Изменение условий</h2>
<p>9.1. Администрация вправе вносить изменения в настоящее Соглашение.</p>
<p>9.2. Актуальная версия Соглашения публикуется в Сервисе.</p>
<p>9.3. Продолжение использования Сервиса означает согласие Пользователя с обновлёнными условиями.</p>

<h2>10. Контактная информация</h2>
<p>10.1. По всем вопросам Пользователь может обратиться в службу поддержки через <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener">@SecretHeroSupportBot</a> (тикет-бот) или по email <a href="mailto:admin@hydravpsvpn.ru">admin@hydravpsvpn.ru</a>.</p>

<p><strong>Используя Сервис (в том числе запуская бота и/или вводя команду /start), Пользователь подтверждает, что ознакомлен с настоящим Соглашением и принимает его условия в полном объёме.</strong></p>
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
    <a href="mailto:admin@hydravpsvpn.ru" class="contact-link">admin@hydravpsvpn.ru</a>
  </article>
</div>

<h2>SLA — время ответа</h2>
<ul>
  <li><strong>Рабочее время:</strong> пн–пт 09:00–20:00 (МСК).</li>
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
<p>Требования: Docker, Docker Compose, порт 80/443, домен (для HTTPS и TG Login Widget).</p>
<p>По вопросам установки и настройки обращайтесь к администрации: <a href="https://t.me/SecretHeroSupportBot" target="_blank" rel="noopener">@SecretHeroSupportBot</a> (тикет-бот) или по email <a href="mailto:admin@hydravpsvpn.ru">admin@hydravpsvpn.ru</a>.</p>

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
        "Сбор, использование и защита информации пользователей сервиса",
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
