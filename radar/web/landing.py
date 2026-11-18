"""Лендинг проекта: публичная страница с виджетами, TG Login и Platega compliance.

Рендерится без авторизации. Секции:
  1. Hero — заголовок, CTA в бот, версия
  2. Features — сетка возможностей (8-10 карточек)
  3. How it works — 3 шага
  4. Demo — скриншоты/описание интерфейсов
  5. Documents — КНОПКИ (privacy, terms, support, pricing)
  6. Installation — табы: Bash / Docker / Ручная
  7. TG Login Widget — вход через Telegram (data-size="large")
  8. Footer — GitHub, лицензия, автор, кодовое слово mekbuda (скрыто)
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
from typing import Any

from .. import __version__ as VERSION
from .. import config, features

# CSS для лендинга — расширяет базовые стили панели
LANDING_STYLE = """
/* ============================================================
   LANDING PAGE STYLES
   ============================================================ */

/* Hero section */
.hero {
  position: relative;
  padding: clamp(48px, 8vw, 80px) clamp(20px, 5vw, 60px);
  text-align: center;
  background:
    radial-gradient(ellipse 80% 50% at 50% 0%, var(--accent-soft), transparent 70%),
    var(--bg);
  overflow: hidden;
}
.hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(circle at 20% 20%, var(--accent-soft) 0%, transparent 40%),
    radial-gradient(circle at 80% 80%, var(--accent-2) 0%, transparent 30%);
  opacity: 0.6;
  pointer-events: none;
}
.hero-content { position: relative; z-index: 1; max-width: 880px; margin: 0 auto; }
.hero-badge {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 20px;
  letter-spacing: 0.3px;
}
.hero h1 {
  margin: 0 0 16px;
  font-size: clamp(28px, 5vw, 44px);
  line-height: 1.15;
  font-weight: 800;
  letter-spacing: -0.5px;
  color: var(--text);
}
.hero-subtitle {
  margin: 0 auto 28px;
  max-width: 720px;
  font-size: clamp(16px, 2.5vw, 20px);
  line-height: 1.7;
  color: var(--muted);
}
.hero-subtitle strong { color: var(--text); }
.hero-cta { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; margin-bottom: 24px; }
.btn {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 14px 28px;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  border: none;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s, background 0.15s;
}
.btn:active { transform: scale(0.98); }
.btn-primary {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: white;
  box-shadow: 0 4px 16px rgba(79, 140, 255, 0.35);
}
.btn-primary:hover { box-shadow: 0 6px 24px rgba(79, 140, 255, 0.45); }
.btn-ghost {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--line);
}
.btn-ghost:hover { background: var(--surface-3); border-color: var(--accent); }
.tg-icon { width: 20px; height: 20px; flex-shrink: 0; }
.hero-trust {
  display: flex;
  gap: 24px;
  justify-content: center;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 13px;
}
.hero-trust span { display: flex; align-items: center; gap: 6px; }

/* Widget row under hero */
.widget-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  max-width: 1200px;
  margin: -40px auto 60px;
  padding: 0 20px;
  position: relative;
  z-index: 2;
}
@media (max-width: 640px) {
  .widget-row { grid-template-columns: 1fr; margin-top: -20px; }
}
.widget {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px;
  box-shadow: var(--shadow);
  transition: transform 0.2s, box-shadow 0.2s;
}
.widget:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
.widget-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}
.widget-icon { font-size: 22px; }
.widget-title { font-weight: 700; font-size: 15px; color: var(--text); }
.widget-content { min-height: 120px; }
.widget-loading { display: flex; align-items: center; justify-content: center; height: 120px; color: var(--muted); font-size: 14px; }
.widget-error { color: var(--bad); font-size: 13px; text-align: center; padding: 10px; }

/* Weather widget */
.weather-current { display: flex; align-items: flex-start; gap: 16px; margin-bottom: 12px; }
.weather-main { flex: 1; text-align: left; }
.weather-temp { font-size: 42px; font-weight: 700; line-height: 1; color: var(--text); }
.weather-desc { color: var(--muted); font-size: 14px; margin-top: 4px; }
.weather-details { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 12px; color: var(--muted); }
.weather-detail { display: flex; align-items: center; gap: 6px; }
.weather-hourly { display: flex; gap: 8px; overflow-x: auto; padding: 4px 0 8px; margin: 0 -4px; scroll-snap-type: x mandatory; }
.weather-hour { flex: 0 0 auto; width: 56px; text-align: center; scroll-snap-align: start; }
.weather-hour-time { font-size: 11px; color: var(--muted); }
.weather-hour-icon { font-size: 20px; margin: 4px 0; }
.weather-hour-temp { font-size: 13px; font-weight: 600; color: var(--text); }
.weather-daily { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line); }
.weather-day { text-align: center; }
.weather-day-label { font-size: 11px; color: var(--muted); }
.weather-day-icon { font-size: 18px; margin: 4px 0; }
.weather-day-temps { display: flex; justify-content: center; gap: 10px; font-size: 12px; }
.weather-day-low { color: var(--muted); }
.weather-day-high { font-weight: 600; color: var(--text); }

/* News widget */
.news-list { display: flex; flex-direction: column; gap: 10px; }
.news-item { padding: 10px 12px; background: var(--surface-2); border-radius: 10px; border: 1px solid var(--line); transition: border-color 0.15s; }
.news-item:hover { border-color: var(--accent); }
.news-item-title { font-weight: 600; font-size: 13px; color: var(--text); margin-bottom: 4px; line-height: 1.4; }
.news-item-meta { display: flex; gap: 10px; font-size: 11px; color: var(--muted); }
.news-item-topic { padding: 2px 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-weight: 600; font-size: 10px; text-transform: uppercase; }
.news-item-time { white-space: nowrap; }

/* Danger widget */
.danger-status { text-align: center; padding: 8px 0; }
.danger-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 12px;
}
.danger-red { background: var(--bad-soft); color: var(--bad); border: 1px solid var(--bad); }
.danger-yellow { background: var(--warn-soft); color: var(--warn); border: 1px solid var(--warn); }
.danger-green { background: var(--ok-soft); color: var(--ok); border: 1px solid var(--ok); }
.danger-message { font-size: 14px; line-height: 1.5; color: var(--text); margin-bottom: 10px; }
.danger-matched { font-size: 12px; color: var(--muted); }
.danger-whitelist { font-size: 11px; color: var(--warn); margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--line); }

/* Sections */
.section {
  padding: clamp(48px, 6vw, 72px) clamp(20px, 5vw, 60px);
}
.section-header { text-align: center; margin-bottom: 48px; }
.section-title {
  margin: 0 0 12px;
  font-size: clamp(24px, 4vw, 34px);
  font-weight: 800;
  letter-spacing: -0.3px;
  color: var(--text);
}
.section-subtitle { margin: 0; color: var(--muted); font-size: 16px; max-width: 640px; margin-left: auto; margin-right: auto; }

/* Feature grid */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 20px;
  max-width: 1200px;
  margin: 0 auto;
}
.feature-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 28px 24px;
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
}
.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow);
  border-color: var(--accent);
}
.feature-icon { font-size: 32px; margin-bottom: 14px; display: block; }
.feature-title { margin: 0 0 8px; font-size: 17px; font-weight: 700; color: var(--text); }
.feature-desc { margin: 0; font-size: 14px; line-height: 1.6; color: var(--muted); }

/* How it works */
.steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  max-width: 1000px;
  margin: 0 auto;
  position: relative;
}
.steps::before {
  content: "";
  position: absolute;
  top: 36px;
  left: 50%;
  right: 50%;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--line), transparent);
  z-index: 0;
}
@media (max-width: 768px) { .steps::before { display: none; } }
.step {
  position: relative;
  z-index: 1;
  text-align: center;
  padding: 0 16px;
}
.step-number {
  width: 72px;
  height: 72px;
  margin: 0 auto 18px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 800;
  box-shadow: 0 4px 16px rgba(79, 140, 255, 0.3);
}
.step-title { margin: 0 0 8px; font-size: 18px; font-weight: 700; color: var(--text); }
.step-desc { margin: 0; font-size: 14px; color: var(--muted); line-height: 1.6; }

/* Demo gallery */
.demo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  max-width: 1200px;
  margin: 0 auto;
}
.demo-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  transition: transform 0.2s, box-shadow 0.2s;
}
.demo-card:hover { transform: translateY(-4px); box-shadow: var(--shadow); }
.demo-image { aspect-ratio: 16/10; background: var(--surface-2); display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 14px; overflow: hidden; }
.demo-image img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s; }
.demo-card:hover .demo-image img { transform: scale(1.03); }
.demo-caption { padding: 16px; }
.demo-caption-title { margin: 0 0 4px; font-size: 15px; font-weight: 700; color: var(--text); }
.demo-caption-desc { margin: 0; font-size: 13px; color: var(--muted); }

/* Documents section — buttons, not links */
.doc-buttons {
  display: flex;
  gap: 14px;
  justify-content: center;
  flex-wrap: wrap;
  max-width: 900px;
  margin: 0 auto;
}
.doc-btn {
  flex: 1 1 200px;
  max-width: 280px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 22px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  text-decoration: none;
  color: var(--text);
  transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.doc-btn:hover { transform: translateY(-2px); border-color: var(--accent); box-shadow: var(--shadow); }
.doc-btn-icon { font-size: 24px; flex-shrink: 0; }
.doc-btn-content { display: flex; flex-direction: column; gap: 2px; }
.doc-btn-title { font-weight: 700; font-size: 15px; }
.doc-btn-desc { font-size: 12px; color: var(--muted); }

/* Installation tabs */
.install-tabs { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-bottom: 24px; }
.install-tab {
  padding: 10px 20px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.install-tab:hover { border-color: var(--accent); color: var(--text); }
.install-tab.active { background: var(--accent); border-color: var(--accent); color: white; }
.install-panel { display: none; max-width: 800px; margin: 0 auto; }
.install-panel.active { display: block; animation: fadeIn 0.2s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.install-code { background: var(--surface-2); border: 1px solid var(--line); border-radius: 12px; padding: 20px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; line-height: 1.6; overflow-x: auto; color: var(--text); position: relative; }
.install-code-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; color: var(--muted); font-size: 12px; }
.copy-btn { padding: 6px 12px; border-radius: 8px; background: var(--surface-3); border: 1px solid var(--line); color: var(--text); font-size: 12px; cursor: pointer; }
.copy-btn:hover { background: var(--accent); border-color: var(--accent); }
.install-steps { margin-top: 16px; }
.install-step { display: flex; gap: 14px; margin-bottom: 16px; }
.install-step-num { flex-shrink: 0; width: 28px; height: 28px; border-radius: 50%; background: var(--accent); color: white; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }
.install-step-text { color: var(--text); line-height: 1.6; }

/* TG Login section */
.tg-login-section {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 40px;
  max-width: 560px;
  margin: 0 auto;
  text-align: center;
}
.tg-login-title { margin: 0 0 8px; font-size: 22px; font-weight: 700; color: var(--text); }
.tg-login-desc { margin: 0 0 24px; color: var(--muted); font-size: 15px; }
.tg-login-hint { margin-top: 16px; font-size: 13px; color: var(--muted); }
.tg-login-hint summary { cursor: pointer; color: var(--link); }
.tg-login-hint p { margin: 8px 0 0; font-size: 12px; line-height: 1.5; }

/* Footer */
.landing-footer {
  border-top: 1px solid var(--line);
  padding: 32px clamp(20px, 5vw, 60px);
  background: var(--surface);
  color: var(--muted);
  font-size: 13px;
}
.footer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 24px;
  max-width: 1000px;
  margin: 0 auto 24px;
}
.footer-col h4 { margin: 0 0 12px; font-size: 14px; font-weight: 700; color: var(--text); }
.footer-col ul { margin: 0; padding: 0; list-style: none; }
.footer-col li { margin-bottom: 8px; }
.footer-col a { color: var(--muted); text-decoration: none; transition: color 0.15s; }
.footer-col a:hover { color: var(--accent); }
.footer-bottom { text-align: center; padding-top: 20px; border-top: 1px solid var(--line); }
.footer-bottom a { color: var(--muted); text-decoration: none; }
.footer-bottom a:hover { color: var(--accent); }

/* Code word for moderation — hidden */
.mekbuda { display: none !important; visibility: hidden; position: absolute; left: -9999px; }

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


def render_landing_page(
    bot_username: str = "",
    public_url: str = "",
) -> str:
    """Рендерит полную HTML-страницу лендинга."""
    # Базовые стили панели берём лениво: panel импортирует landing наверху,
    # поэтому import на уровне модуля замкнул бы цикл. К моменту вызова
    # render_landing_page panel уже полностью загружен.
    from .panel import PAGE_STYLE  # noqa: F401  (используется в f-строке ниже)

    # Подключаем Telegram Web App JS для виджетов
    tg_webapp_js = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'

    # Описание сайта-визитки редактируется из панели (суперадмин).
    # Пусто — показываем текст по умолчанию.
    from .. import secrets as secrets_module

    custom_desc = str(secrets_module.get("LANDING_DESCRIPTION") or "").strip()
    hero_subtitle = (
        html.escape(custom_desc) if custom_desc else
        "ИИ разбирает каналы МЧС, админок, ЖКХ и RSS-ленты. "
        "Сопоставляет с вашими локациями. Присылает только то, что касается вас. "
        "<strong>Тревоги всегда бесплатно.</strong>"
    )

    # Telegram Login Widget
    if bot_username:
        tg_login_widget = (
            f'<script async src="https://telegram.org/js/telegram-widget.js?22" '
            f'data-telegram-login="{html.escape(bot_username)}" data-size="large" '
            f'data-auth-url="/auth" data-request-access="write"></script>'
        )
    else:
        tg_login_widget = (
            '<div class="btn-ghost" style="pointer-events:none; opacity:0.6;">'
            'Бот не настроен — настройте @BotFather и WEB_PUBLIC_URL</div>'
        )

    # Theme toggle script (shared with panel)
    theme_toggle_script = """
<script>
(function() {
  const KEY = 'radar_theme';
  const root = document.documentElement;
  const themes = ['dark', 'light', 'matrix', 'ark'];
  function apply(t) {
    root.setAttribute('data-theme', t);
    localStorage.setItem(KEY, t);
    try { Telegram?.WebApp?.setHeaderColor?.(getComputedStyle(root).getPropertyValue('--surface').trim()); } catch {}
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
"""

    # Widgets initialization script
    widgets_script = """
<script>
(function() {
  const API_BASE = '/api/widget';
  let currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';

  async function fetchJSON(url) {
    try {
      const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return await res.json();
    } catch (e) {
      console.warn('Widget fetch failed:', e);
      return null;
    }
  }

  function setError(el, msg) {
    el.innerHTML = '<div class="widget-error">' + htmlEscape(msg) + '</div>';
  }
  function setLoading(el) {
    el.innerHTML = '<div class="widget-loading">Загрузка…</div>';
  }
  function htmlEscape(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // Weather widget
  async function initWeather() {
    const wrap = document.getElementById('widget-weather');
    if (!wrap) return;
    const content = wrap.querySelector('.widget-content');
    setLoading(content);

    // Try to get user's location
    let lat, lon, city = 'auto';
    try {
      const pos = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 5000, maximumAge: 300000 });
      });
      lat = pos.coords.latitude;
      lon = pos.coords.longitude;
    } catch {
      // Fallback: use IP-based or default city
    }

    const params = new URLSearchParams({ theme: currentTheme });
    if (lat !== undefined && lon !== undefined) { params.set('lat', lat); params.set('lon', lon); }
    else { params.set('city', city); }

    const data = await fetchJSON(API_BASE + '/weather?' + params.toString());
    if (!data || !data.ok) { setError(content, data?.message || 'Не удалось загрузить погоду'); return; }
    renderWeather(content, data);
  }

  function renderWeather(el, d) {
    const daily = (d.forecast || []).slice(0, 3);
    const number = value => value !== null && value !== undefined && Number.isFinite(Number(value));

    let html = '<div class="weather-current">';
    html += '<div class="weather-main">';
    html += '<div class="weather-temp">' + (number(d.temperature) ? Math.round(d.temperature) : '—') + '°</div>';
    html += '<div class="weather-desc">' + htmlEscape(d.condition || '') + '</div>';
    html += '</div>';
    html += '<div class="weather-details">';
    if (number(d.feels_like)) html += '<div class="weather-detail">🤗 ' + Math.round(d.feels_like) + '°</div>';
    if (number(d.wind_speed)) html += '<div class="weather-detail">💨 ' + d.wind_speed + ' м/с</div>';
    if (number(d.humidity)) html += '<div class="weather-detail">💧 ' + d.humidity + '%</div>';
    if (number(d.pressure)) html += '<div class="weather-detail">📊 ' + Math.round(d.pressure) + ' гПа</div>';
    html += '</div></div>';

    if (daily.length) {
      html += '<div class="weather-daily">';
      daily.forEach(day => {
        html += '<div class="weather-day">';
        html += '<div class="weather-day-label">' + htmlEscape(day.date) + '</div>';
        html += '<div class="weather-day-icon">' + htmlEscape(day.icon || '') + '</div>';
        html += '<div class="weather-day-temps">';
        html += '<span class="weather-day-low">' + (number(day.temp_min) ? Math.round(day.temp_min) : '—') + '°</span>';
        html += '<span class="weather-day-high">' + (number(day.temp_max) ? Math.round(day.temp_max) : '—') + '°</span>';
        html += '</div></div>';
      });
      html += '</div>';
    }
    el.innerHTML = html;
  }

  // News widget
  async function initNews() {
    const wrap = document.getElementById('widget-news');
    if (!wrap) return;
    const content = wrap.querySelector('.widget-content');
    setLoading(content);

    const data = await fetchJSON(API_BASE + '/news?category=all&limit=5&theme=' + currentTheme);
    if (!data || !data.ok) { setError(content, data?.message || 'Не удалось загрузить новости'); return; }
    renderNews(content, data);
  }

  function renderNews(el, d) {
    const items = d.items || [];
    if (!items.length) { el.innerHTML = '<div class="widget-error">Новостей нет</div>'; return; }
    let html = '<div class="news-list">';
    items.forEach(item => {
      html += item.url
        ? '<a class="news-item" href="' + htmlEscape(item.url) + '" target="_blank" rel="noopener">'
        : '<div class="news-item">';
      html += '<div class="news-item-title">' + htmlEscape(item.title) + '</div>';
      if (item.summary) html += '<div class="news-item-summary">' + htmlEscape(item.summary) + '</div>';
      html += '<div class="news-item-meta">';
      if (item.source) html += '<span class="news-item-source">' + htmlEscape(item.source) + '</span>';
      if (item.category) html += '<span class="news-item-topic">' + htmlEscape(item.category) + '</span>';
      if (item.published_at) html += '<span class="news-item-time">' + htmlEscape(item.published_at) + '</span>';
      html += '</div>' + (item.url ? '</a>' : '</div>');
    });
    html += '</div>';
    el.innerHTML = html;
  }

  // Danger widget
  async function initDanger() {
    const wrap = document.getElementById('widget-danger');
    if (!wrap) return;
    const content = wrap.querySelector('.widget-content');
    setLoading(content);

    const data = await fetchJSON(API_BASE + '/danger?city=auto&theme=' + currentTheme);
    if (!data || !data.ok) { setError(content, data?.message || 'Не удалось загрузить статус'); return; }
    renderDanger(content, data);
  }

  function renderDanger(el, d) {
    let html = '<div class="danger-status">';
    const active = d.active === true;
    const type = d.type || 'none';
    const level = d.level || 'green';

    const badgeClass = 'danger-' + level;
    const icons = { uav: '🛸', missile: '🚀', air_raid: '🚨', all_clear: '✅', none: '🟢' };
    const labels = { uav: 'Опасность БПЛА', missile: 'Ракетная опасность', air_raid: 'Воздушная тревога', all_clear: 'Отбой', none: 'Спокойно' };

    html += '<div class="danger-badge ' + badgeClass + '">' + (icons[type] || '🔔') + ' ' + (labels[type] || 'Статус') + '</div>';
    if (d.message) html += '<div class="danger-message">' + htmlEscape(d.message) + '</div>';
    if (d.locations_matched && d.locations_matched.length) {
      html += '<div class="danger-matched">Соответствует локациям: ' + d.locations_matched.map(htmlEscape).join(', ') + '</div>';
    }
    if (d.whitelist_info) {
      html += '<div class="danger-whitelist">' + htmlEscape(d.whitelist_info) + '</div>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  // Installation tabs and copy buttons
  document.querySelectorAll('.install-tab[data-tab]').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.install-tab').forEach(item => {
        const selected = item === button;
        item.classList.toggle('active', selected);
        item.setAttribute('aria-selected', String(selected));
      });
      document.querySelectorAll('.install-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === 'panel-' + button.dataset.tab);
      });
    });
  });
  document.querySelectorAll('[data-copy-target]').forEach(button => {
    button.addEventListener('click', async () => {
      const source = document.querySelector(button.dataset.copyTarget);
      if (!source) return;
      try {
        await navigator.clipboard.writeText(source.textContent);
        button.textContent = 'Скопировано';
        setTimeout(() => { button.textContent = 'Копировать'; }, 1500);
      } catch {
        button.textContent = 'Выделите и скопируйте вручную';
      }
    });
  });

  // Theme change listener
  const observer = new MutationObserver(mutations => {
    for (const m of mutations) {
      if (m.attributeName === 'data-theme') {
        currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        initWeather(); initNews(); initDanger();
        break;
      }
    }
  });
  observer.observe(document.documentElement, { attributes: true });

  // Init all
  document.addEventListener('DOMContentLoaded', () => {
    initWeather();
    initNews();
    initDanger();
  });

  // Expose for manual refresh
  window.RadarWidgets = { refresh: () => { initWeather(); initNews(); initDanger(); } };
})();
</script>
"""

    # Полная HTML страница
    return f"""<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Радар — оповещения об угрозах и авариях ЖКХ по вашим адресам. ИИ разбирает каналы МЧС, админок, ЖКХ и RSS. Тревоги бесплатно.">
  <meta name="theme-color" content="#141824">
  <title>Радар — оповещения об угрозах и авариях ЖКХ</title>
  <style>{PAGE_STYLE}{LANDING_STYLE}</style>
  {tg_webapp_js}
  {theme_toggle_script}
</head>
<body>
  <header>
    <div class="brand">Радар <span class="version">v{VERSION}</span></div>
    <nav>
      <a href="#features">Возможности</a>
      <a href="#how">Как работает</a>
      <a href="#demo">Демо</a>
      <a href="#docs">Документы</a>
      <a href="#install">Установка</a>
    </nav>
  </header>

  <main>
    <!-- 1. HERO -->
    <section class="hero" aria-labelledby="hero-title">
      <div class="hero-content">
        <span class="hero-badge">v{VERSION} · GPL-3.0 · ARM Ready</span>
        <h1 id="hero-title">Радар — оповещения об угрозах и авариях ЖКХ по вашим адресам</h1>
        <p class="hero-subtitle">
          {hero_subtitle}
        </p>
        <div class="hero-cta">
          <a href="https://t.me/SecretHeroBot" class="btn btn-primary" target="_blank" rel="noopener">
            <svg class="tg-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm5.52 16.34l-4.52-3.96v-3.72l4.52-3.96 1.58 1.38-3.1 2.72 3.1 2.72-1.58 1.38z"/></svg>
            Запустить в Telegram
          </a>
          <a href="#features" class="btn btn-ghost">Возможности</a>
        </div>
        <div class="hero-trust">
          <span>197 коммитов</span>
          <span>105 тегов</span>
          <span>Docker</span>
          <span>SQLite/PostgreSQL</span>
        </div>
      </div>
    </section>

    <!-- Widgets row under hero -->
    <div class="widget-row" role="region" aria-label="Виджеты">
      <div id="widget-weather" class="widget" data-city="auto" data-theme="auto">
        <div class="widget-header"><span class="widget-icon">🌤</span><span class="widget-title">Погода</span></div>
        <div class="widget-content"><div class="widget-loading">Загрузка…</div></div>
      </div>
      <div id="widget-news" class="widget" data-topics="alerts,utilities" data-limit="5">
        <div class="widget-header"><span class="widget-icon">📰</span><span class="widget-title">Новости</span></div>
        <div class="widget-content"><div class="widget-loading">Загрузка…</div></div>
      </div>
      <div id="widget-danger" class="widget" data-city="auto">
        <div class="widget-header"><span class="widget-icon">🛡</span><span class="widget-title">Статус опасности</span></div>
        <div class="widget-content"><div class="widget-loading">Загрузка…</div></div>
      </div>
    </div>

    <!-- 2. FEATURES -->
    <section class="section" id="features" aria-labelledby="features-title">
      <div class="section-header">
        <h2 class="section-title" id="features-title">Возможности</h2>
        <p class="section-subtitle">Всё, что нужно для мониторинга города — в одном боте и веб-панели</p>
      </div>
      <div class="feature-grid">
        <article class="feature-card">
          <span class="feature-icon">🛸</span>
          <h3 class="feature-title">БПЛА / ракетная опасность</h3>
          <p class="feature-desc">Мгновенные оповещения всего города. Типы: БПЛА, ракетная опасность, воздушная тревога, отбой. Совпадение с вашими локациями.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🆘</span>
          <h3 class="feature-title">МЧС: ЧС и штормовые предупреждения</h3>
          <p class="feature-desc">Официальные каналы МЧС, администраций области/района/города. Эвакуация, паводки, пожары, сильны ветра.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🛠</span>
          <h3 class="feature-title">ЖКХ: вода, свет, газ, отопление</h3>
          <p class="feature-desc">Адресно по улице и дому. Отключения ГВС/ХВС, электричество, газ, отопление. Кластеризация радиусом 1 км.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🌤</span>
          <h3 class="feature-title">Погода — почасовая, 3 дня, картинкой</h3>
          <p class="feature-desc">Текущая, ощущается, ветер с порывами, влажность, давление, восход/закат, фаза луны. Дневная/ночная тема, вектор ветра.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">📰</span>
          <h3 class="feature-title">Новостные подборки (Telegram Stars)</h3>
          <p class="feature-desc">18 тематик, ИИ-сводки, доставка по расписанию. Платные — через Telegram Stars, подписчики получают без лимита.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🔗</span>
          <h3 class="feature-title">Проверка ссылок на фишинг</h3>
          <p class="feature-desc">200 проверок в сутки бесплатно. Подписчики — без лимита. Кэш результатов, база фишинговых доменов.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🎵</span>
          <h3 class="feature-title">Музыка в облаке (rclone)</h3>
          <p class="feature-desc">Кэш 256 Мб, пережатие в Opus, стриминг в Telegram. Подключение любого S3/WebDAV/облака через rclone.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🔐</span>
          <h3 class="feature-title">Аренда приватного сервера</h3>
          <p class="feature-desc">Аренда приватного сервера. Срок, трафик и число устройств зависят от выбранного тарифа. Управление заказом в боте.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">🤖</span>
          <h3 class="feature-title">ИИ-ассистент (Gemini / DeepSeek)</h3>
          <p class="feature-desc">Поиск в интернете, анализ файлов, генерация кода, переводчик. Настройка моделей и промптов в панели.</p>
        </article>
        <article class="feature-card">
          <span class="feature-icon">👥</span>
          <h3 class="feature-title">Модерация групп</h3>
          <p class="feature-desc">Антиспам, капча на входе, лестница наказаний (warn/mute/ban), автоочистка, лог действий.</p>
        </article>
      </div>
    </section>

    <!-- 3. HOW IT WORKS -->
    <section class="section" id="how" aria-labelledby="how-title">
      <div class="section-header">
        <h2 class="section-title" id="how-title">Как это работает</h2>
        <p class="section-subtitle">Три шага — и вы получаете только релевантные оповещения</p>
      </div>
      <div class="steps">
        <article class="step">
          <div class="step-number">1</div>
          <h3 class="step-title">Добавьте бота и укажите адреса</h3>
          <p class="step-desc">Запустите @SecretHeroBot, нажмите «Мои локации» и добавьте город, улицу, дом. Можно добавить несколько адресов — работа, дача, родители.</p>
        </article>
        <article class="step">
          <div class="step-number">2</div>
          <h3 class="step-title">Бот мониторит источники 24/7</h3>
          <p class="step-desc">ИИ (Gemini) разбирает каналы МЧС, админок, ЖКХ, RSS-ленты СМИ. Извлекает тип события, город, улицу, дом, время, рекомендации.</p>
        </article>
        <article class="step">
          <div class="step-number">3</div>
          <h3 class="step-title">Получаете оповещение только если совпало</h3>
          <p class="step-desc">Событие сопоставляется с вашими локациями. Пришло — значит это ваш район. Настройте тихие часы, формат (текст/картинка), погоду.</p>
        </article>
      </div>
    </section>

    <!-- 4. DEMO -->
    <section class="section" id="demo" aria-labelledby="demo-title">
      <div class="section-header">
        <h2 class="section-title" id="demo-title">Демо / Скриншоты</h2>
        <p class="section-subtitle">Интерфейс бота, веб-панель, погода картинкой, формат оповещения</p>
      </div>
      <div class="demo-grid">
        <article class="demo-card">
          <div class="demo-image">📱<br><small>Интерфейс бота</small></div>
          <div class="demo-caption">
            <h3 class="demo-caption-title">Меню бота</h3>
            <p class="demo-caption-desc">Локации, настройки уведомлений, погода, подписки, сервер, ИИ-ассистент — всё в одном меню.</p>
          </div>
        </article>
        <article class="demo-card">
          <div class="demo-image">🖥<br><small>Веб-панель</small></div>
          <div class="demo-caption">
            <h3 class="demo-caption-title">Обзор панели</h3>
            <p class="demo-caption-desc">Статистика, пользователи, источники, ключи, сервер, подписки, обновления — 4 темы оформления.</p>
          </div>
        </article>
        <article class="demo-card">
          <div class="demo-image">🌤<br><small>Погода картинкой</small></div>
          <div class="demo-caption">
            <h3 class="demo-caption-title">Погода как картинка</h3>
            <p class="demo-caption-desc">Дневная/ночная тема, вектор ветра, фаза луны, почасовая шкала, 3 дня — готовое изображение.</p>
          </div>
        </article>
        <article class="demo-card">
          <div class="demo-image">🛸<br><small>Оповещение БПЛА</small></div>
          <div class="demo-caption">
            <h3 class="demo-caption-title">Формат тревоги</h3>
            <p class="demo-caption-desc">🚨 ОПАСНОСТЬ — Город • БПЛА / ракетная • список совпавших локаций • памятка по укрытию.</p>
          </div>
        </article>
      </div>
    </section>

    <!-- 5. DOCUMENTS (buttons, not links) -->
    <section class="section" id="docs" aria-labelledby="docs-title">
      <div class="section-header">
        <h2 class="section-title" id="docs-title">Документы</h2>
        <p class="section-subtitle">Всегда доступны отдельными кнопками — в боте и на сайте</p>
      </div>
      <div class="doc-buttons">
        <a href="/privacy" class="doc-btn">
          <span class="doc-btn-icon">📄</span>
          <div class="doc-btn-content">
            <span class="doc-btn-title">Политика конфиденциальности</span>
            <span class="doc-btn-desc">Какие данные собираются и как используются</span>
          </div>
        </a>
        <a href="/terms" class="doc-btn">
          <span class="doc-btn-icon">📄</span>
          <div class="doc-btn-content">
            <span class="doc-btn-title">Пользовательское соглашение</span>
            <span class="doc-btn-desc">Правила использования, бесплатные и платные функции</span>
          </div>
        </a>
        <a href="/support" class="doc-btn">
          <span class="doc-btn-icon">🎫</span>
          <div class="doc-btn-content">
            <span class="doc-btn-title">Поддержка</span>
            <span class="doc-btn-desc">Тикет-система, контакты, SLA ответа</span>
          </div>
        </a>
        <a href="/pricing" class="doc-btn">
          <span class="doc-btn-icon">💰</span>
          <div class="doc-btn-content">
            <span class="doc-btn-title">Тарифы и цены</span>
            <span class="doc-btn-desc">Оповещения бесплатно, подборки Stars, сервер, лимиты</span>
          </div>
        </a>
      </div>
    </section>

    <!-- 6. INSTALLATION -->
    <section class="section" id="install" aria-labelledby="install-title">
      <div class="section-header">
        <h2 class="section-title" id="install-title">Установка и развёртывание</h2>
        <p class="section-subtitle">Одна команда, Docker Compose или ручная настройка — на выбор</p>
      </div>
      <div class="install-tabs" role="tablist">
        <button class="install-tab active" role="tab" data-tab="bash" aria-selected="true">Bash (рекомендуется)</button>
        <button class="install-tab" role="tab" data-tab="docker" aria-selected="false">Docker Compose</button>
        <button class="install-tab" role="tab" data-tab="manual" aria-selected="false">Ручная</button>
      </div>

      <div class="install-panel active" id="panel-bash" role="tabpanel">
        <div class="install-code">
          <div class="install-code-header">
            <span>Установка / обновление одной командой</span>
            <button class="copy-btn" data-copy-target="#code-bash">Копировать</button>
          </div>
          <pre id="code-bash">bash <(curl -fsSL https://raw.githubusercontent.com/Chistovik92/radar/main/install.sh)</pre>
        </div>
        <div class="install-steps">
          <div class="install-step">
            <span class="install-step-num">1</span>
            <div class="install-step-text">Скрипт определит архитектуру (ARM/x64), ОС, проверит Docker и Docker Compose.</div>
          </div>
          <div class="install-step">
            <span class="install-step-num">2</span>
            <div class="install-step-text">Создаст .env с настройками, сгенерирует секреты, настроит Caddy (HTTPS).</div>
          </div>
          <div class="install-step">
            <span class="install-step-num">3</span>
            <div class="install-step-text">Запустит контейнеры <code>radar_container</code> и <code>radar_db</code>. Готово.</div>
          </div>
        </div>
      </div>

      <div class="install-panel" id="panel-docker" role="tabpanel">
        <div class="install-code">
          <div class="install-code-header">
            <span>Docker Compose</span>
            <button class="copy-btn" data-copy-target="#code-docker">Копировать</button>
          </div>
          <pre id="code-docker">git clone https://github.com/Chistovik92/radar.git
cd radar
cp .env.example .env  # отредактируйте BOT_TOKEN, ADMIN_IDS, WEB_PUBLIC_URL
docker compose up -d</pre>
        </div>
        <div class="install-steps">
          <div class="install-step">
            <span class="install-step-num">1</span>
            <div class="install-step-text">Клонируйте репозиторий, скопируйте .env.example → .env.</div>
          </div>
          <div class="install-step">
            <span class="install-step-num">2</span>
            <div class="install-step-text">Заполните обязательные переменные: BOT_TOKEN, ADMIN_IDS, WEB_PUBLIC_URL.</div>
          </div>
          <div class="install-step">
            <span class="install-step-num">3</span>
            <div class="install-step-text">Запустите <code>docker compose up -d</code>. Панель на порту 8080 (или через Caddy на 443).</div>
          </div>
        </div>
      </div>

      <div class="install-panel" id="panel-manual" role="tabpanel">
        <div class="install-code">
          <div class="install-code-header">
            <span>Ручная установка (systemd + Python)</span>
            <button class="copy-btn" data-copy-target="#code-manual">Копировать</button>
          </div>
          <pre id="code-manual">python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # настройте
python -m radar.db.init_db
python -m radar.bot</pre>
        </div>
        <div class="install-steps">
          <div class="install-step">
            <span class="install-step-num">1</span>
            <div class="install-step-text">Python 3.11+, виртуальное окружение, зависимости из requirements.txt.</div>
          </div>
          <div class="install-step">
            <span class="install-step-num">2</span>
            <div class="install-step-text">Настройте .env (BOT_TOKEN, ADMIN_IDS, DATABASE_URL, WEB_PUBLIC_URL).</div>
          </div>
          <div class="install-step">
            <span class="install-step-num">3</span>
            <div class="install-step-text">Инициализируйте БД (<code>python -m radar.db.init_db</code>), запустите бота и панель.</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 7. TG LOGIN WIDGET -->
    <section class="section" aria-labelledby="login-title">
      <h2 class="section-title" id="login-title" style="display:none;">Вход в панель</h2>
      <div class="tg-login-section">
        <h3 class="tg-login-title">Войти в веб-панель</h3>
        <p class="tg-login-desc">Авторизация через Telegram — пароли не храним. Доступ по ролям бота.</p>
        <div id="tg-login-widget">{tg_login_widget}</div>
        <details class="tg-login-hint">
          <summary>Куда попаду после входа?</summary>
          <p>👤 Пользователь → <strong>/profile</strong> (свои локации, настройки, история, виджеты)</p>
          <p>🛡 Модератор → <strong>/sources</strong> (модерация источников + профиль)</p>
          <p>👑 Администратор → <strong>/users</strong> (пользователи, назначение ролей + выше)</p>
          <p>⭐️ Суперадмин → <strong>/settings</strong> (полный доступ: сервер, ключи, обновления, RustDesk)</p>
        </details>
        <p class="tg-login-hint" style="margin-top:12px;">
          Альтернатива: в боте <code>/panel</code> → «Код входа» (действует 5 минут)
        </p>
      </div>
    </section>
  </main>

  <footer class="landing-footer">
    <div class="footer-grid">
      <div class="footer-col">
        <h4>Проект</h4>
        <ul>
          <li><a href="https://github.com/Chistovik92/radar">GitHub репозиторий</a></li>
          <li><a href="https://github.com/Chistovik92/radar/releases">Релизы</a></li>
          <li><a href="https://github.com/Chistovik92/radar/blob/main/docs/ROADMAP.md">Дорожная карта</a></li>
          <li><a href="https://github.com/Chistovik92/radar/blob/main/docs/STATUS.md">Статус проекта</a></li>
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

  {widgets_script}
</body>
</html>
"""


# For backward compatibility with panel.py's _login_page style
def _landing_page(bot_username: str = "", public_url: str = "") -> str:
    """Alias for render_landing_page."""
    return render_landing_page(bot_username, public_url)