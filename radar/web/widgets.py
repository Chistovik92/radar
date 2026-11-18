"""Telegram Mini App widgets API: Weather, News, Danger status.

Provides /api/widget/* endpoints for Telegram Mini App integration.
Widgets are rendered via Telegram Web App JS from CDN.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import math
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

from .. import config, geocode, weather

log = logging.getLogger("radar.web.widgets")


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": config.USER_AGENT},
    )


def _safe_url(value: Any) -> str:
    """В публичный href попадают только обычные веб-ссылки."""
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def _internal_error() -> web.Response:
    return web.json_response({
        "ok": False,
        "error": "internal_error",
        "message": "Сервис временно недоступен",
    }, status=500)


# ============================================================
# WIDGET API ROUTES
# ============================================================

async def widget_weather(request: web.Request) -> web.Response:
    """Weather widget data: /api/widget/weather?city=auto&theme=dark"""
    city = request.query.get("city", "auto").strip()[:120]
    theme = request.query.get("theme", "dark")

    try:
        lat: float | None = None
        lon: float | None = None
        raw_lat = request.query.get("lat")
        raw_lon = request.query.get("lon")
        if raw_lat is not None or raw_lon is not None:
            try:
                lat = float(raw_lat or "")
                lon = float(raw_lon or "")
            except ValueError:
                lat = lon = None
            if (lat is None or lon is None or not math.isfinite(lat)
                    or not math.isfinite(lon) or not -90 <= lat <= 90
                    or not -180 <= lon <= 180):
                return web.json_response({
                    "ok": False,
                    "error": "coordinates_invalid",
                    "message": "Некорректные координаты",
                }, status=400)
        else:
            query = config.DEFAULT_CITY if city in ("", "auto") else city
            if not query:
                return web.json_response({
                    "ok": False,
                    "error": "city_required",
                    "message": "Разрешите геолокацию или укажите город",
                }, status=400)
            async with _session() as session:
                found = await geocode.forward(session, query)
            if found:
                lat = float(found[0]["lat"])
                lon = float(found[0]["lon"])

        if lat is None or lon is None:
            return web.json_response({
                "ok": False,
                "error": "city_unknown",
                "message": "Город не найден — укажите точнее",
            }, status=404)

        async with _session() as session:
            data = await weather.fetch(session, lat, lon)
        if not data.ok:
            return web.json_response({
                "ok": False,
                "error": "weather_unavailable",
                "message": data.error or "Сервис погоды временно недоступен",
            }, status=503)

        condition, icon = weather.describe(data.code, data.is_day)
        result = {
            "ok": True,
            "city": city,
            "temperature": data.temp,
            "feels_like": data.feels,
            "condition": condition,
            "icon": icon,
            "humidity": data.humidity,
            "wind_speed": data.wind,
            "wind_dir": data.wind_dir,
            "pressure": data.pressure,
            "uv_index": None,
            "forecast": [
                {
                    "date": day.label,
                    "temp_min": day.low,
                    "temp_max": day.high,
                    "condition": weather.describe(day.code, True)[0],
                    "icon": weather.describe(day.code, True)[1],
                }
                for day in data.daily[:5]
            ],
            "theme": theme,
        }
        return web.json_response(result)
    except Exception:  # noqa: BLE001
        log.exception("widget_weather error")
        return _internal_error()


async def widget_news(request: web.Request) -> web.Response:
    """News widget data: /api/widget/news?limit=5&theme=dark"""
    try:
        limit = int(request.query.get("limit", "5"))
    except ValueError:
        limit = 0
    if not 1 <= limit <= 20:
        return web.json_response({
            "ok": False,
            "error": "limit_invalid",
            "message": "Параметр limit должен быть от 1 до 20",
        }, status=400)
    theme = request.query.get("theme", "dark")
    category = request.query.get("category", "all")

    try:
        # Импорт ленивый: repo тянет sqlalchemy, а этот модуль импортируется
        # из app_http_check.py на чистом Python (без БД). Как и в panel.py.
        from ..db import repo

        categories = None if category in ("", "all") else [category]
        events = await repo.recent_events(limit=limit, categories=categories)
        result = {
            "ok": True,
            "items": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "summary": (item["summary"] or "")[:200],
                    "source": item["source"],
                    "url": _safe_url(item["url"]),
                    "published_at": item["published_at"],
                    "category": item["categories"][0] if item["categories"] else "",
                }
                for item in events
            ],
            "theme": theme,
        }
        return web.json_response(result)
    except Exception:  # noqa: BLE001
        log.exception("widget_news error")
        return _internal_error()


async def widget_danger(request: web.Request) -> web.Response:
    """Danger status widget: /api/widget/danger?city=auto&theme=dark"""
    theme = request.query.get("theme", "dark")
    city = request.query.get("city", "auto").strip()[:120]
    if city == "auto":
        city = config.DEFAULT_CITY
    if not city:
        return web.json_response({
            "ok": False,
            "error": "city_required",
            "message": "Укажите город для проверки статуса",
        }, status=400)

    try:
        # Импорт ленивый — см. widget_news (sqlalchemy недоступен без БД).
        from ..db import repo

        state = await repo.danger_state(city=city, hours=24)
        bpla = state["bpla"]
        mchs = state["mchs"]

        if bpla or mchs:
            result = {
                "ok": True,
                "active": True,
                "type": "air_raid" if bpla > 0 else "mchs",
                "level": "red" if bpla > 0 else "yellow",
                "message": (
                    "За последние сутки есть события БПЛА/ракетной опасности"
                    if bpla > 0 else "Есть экстренные оповещения МЧС"
                ),
                "area": city,
                "started_at": None,
                "icon": "🚨" if bpla > 0 else "🆘",
                "label": "Воздушная тревога" if bpla > 0 else "Оповещение МЧС",
                "theme": theme,
            }
        else:
            result = {
                "ok": True,
                "active": False,
                "type": "none",
                "level": "green",
                "message": "Опасностей не обнаружено",
                "theme": theme,
            }
        return web.json_response(result)
    except Exception:  # noqa: BLE001
        log.exception("widget_danger error")
        return _internal_error()


# ============================================================
# JAVASCRIPT MODULE FOR TELEGRAM MINI APP
# ============================================================

WIDGET_JS = """
/* ============================================================
   Radar Telegram Mini App Widgets
   Auto-initializes widgets in data-widget containers
   ============================================================ */

(function() {
  'use strict';

  const API_BASE = '/api/widget';
  let currentTheme = 'dark';

  function detectTheme() {
    if (window.Telegram && window.Telegram.WebApp) {
      return window.Telegram.WebApp.colorScheme || 'dark';
    }
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }

  currentTheme = detectTheme();

  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.onEvent('themeChanged', function() {
      currentTheme = window.Telegram.WebApp.colorScheme || 'dark';
      refreshAllWidgets();
    });
  }

  async function fetchJSON(url) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return await res.json();
    } catch (e) {
      console.warn('[Radar Widget] Fetch failed:', url, e);
      return null;
    }
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function setLoading(el) {
    el.innerHTML = '<div class="widget-loading">Загрузка…</div>';
  }

  function setError(el, msg) {
    el.innerHTML = '<div class="widget-error">' + escapeHtml(msg) + '</div>';
  }

  async function initWeather() {
    const wrap = document.getElementById('widget-weather');
    if (!wrap) return;
    const content = wrap.querySelector('.widget-content');
    setLoading(content);

    const city = wrap.dataset.city || 'auto';
    const data = await fetchJSON(API_BASE + '/weather?city=' + encodeURIComponent(city) + '&theme=' + currentTheme);
    if (!data || !data.ok) {
      setError(content, data?.message || 'Не удалось загрузить погоду');
      return;
    }
    renderWeather(content, data);
  }

  function renderWeather(el, d) {
    const c = d.temperature;
    const fl = d.feels_like;
    const cond = d.condition || '—';
    const icon = d.icon || '🌤️';
    const humidity = d.humidity;
    const wind = d.wind_speed;
    const windDir = d.wind_dir || '';
    const pressure = d.pressure;
    const uv = d.uv_index;

    let html = '<div class="weather-current">';
    html += '<div class="weather-main">';
    html += '<span class="weather-icon" style="font-size:48px;">' + escapeHtml(icon) + '</span>';
    html += '<div class="weather-temp">' + (c !== null && c !== undefined ? c + '°' : '—') + '</div>';
    html += '</div>';
    html += '<div class="weather-details">';
    html += '<div class="weather-feels">Ощущается: ' + (fl !== null && fl !== undefined ? fl + '°' : '—') + '</div>';
    html += '<div class="weather-cond">' + escapeHtml(cond) + '</div>';
    html += '</div>';
    html += '</div>';

    if (humidity !== null || wind !== null || pressure !== null) {
      html += '<div class="weather-meta">';
      if (humidity !== null) html += '<span class="weather-item">💧 ' + humidity + '%</span>';
      if (wind !== null) html += '<span class="weather-item">💨 ' + wind + ' м/с ' + escapeHtml(windDir) + '</span>';
      if (pressure !== null) html += '<span class="weather-item">📊 ' + pressure + ' гПа</span>';
      if (uv !== null) html += '<span class="weather-item">☀️ UV ' + uv + '</span>';
      html += '</div>';
    }

    if (d.forecast && d.forecast.length) {
      html += '<div class="weather-forecast">';
      for (const f of d.forecast) {
        html += '<div class="forecast-day">';
        html += '<span class="fc-date">' + escapeHtml(f.date) + '</span>';
        html += '<span class="fc-icon">' + escapeHtml(f.icon || '🌤️') + '</span>';
        html += '<span class="fc-temp">' + (f.temp_min !== null ? f.temp_min + '°' : '—') + ' / ' + (f.temp_max !== null ? f.temp_max + '°' : '—') + '</span>';
        html += '<span class="fc-cond">' + escapeHtml(f.condition || '') + '</span>';
        html += '</div>';
      }
      html += '</div>';
    }

    el.innerHTML = html;
  }

  async function initNews() {
    const wrap = document.getElementById('widget-news');
    if (!wrap) return;
    const content = wrap.querySelector('.widget-content');
    setLoading(content);

    const limit = wrap.dataset.limit || '5';
    const category = wrap.dataset.category || 'all';
    const data = await fetchJSON(API_BASE + '/news?limit=' + limit + '&category=' + encodeURIComponent(category) + '&theme=' + currentTheme);
    if (!data || !data.ok) {
      setError(content, data?.message || 'Не удалось загрузить новости');
      return;
    }
    renderNews(content, data);
  }

  function renderNews(el, d) {
    if (!d.items || !d.items.length) {
      el.innerHTML = '<div class="widget-empty">Новостей пока нет</div>';
      return;
    }

    let html = '<div class="news-list">';
    for (const item of d.items) {
      html += '<a class="news-item" href="' + escapeHtml(item.url) + '" target="_blank" rel="noopener">';
      html += '<div class="news-title">' + escapeHtml(item.title) + '</div>';
      if (item.summary) {
        html += '<div class="news-summary">' + escapeHtml(item.summary) + '</div>';
      }
      html += '<div class="news-meta">';
      if (item.source) html += '<span class="news-source">' + escapeHtml(item.source) + '</span>';
      if (item.published_at) html += '<span class="news-time">' + escapeHtml(item.published_at) + '</span>';
      if (item.category) html += '<span class="news-cat">' + escapeHtml(item.category) + '</span>';
      html += '</div>';
      html += '</a>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  async function initDanger() {
    const wrap = document.getElementById('widget-danger');
    if (!wrap) return;
    const content = wrap.querySelector('.widget-content');
    setLoading(content);

    const city = wrap.dataset.city || 'auto';
    const data = await fetchJSON(API_BASE + '/danger?city=' + encodeURIComponent(city) + '&theme=' + currentTheme);
    if (!data || !data.ok) {
      setError(content, data?.message || 'Не удалось загрузить статус опасности');
      return;
    }
    renderDanger(content, data);
  }

  function renderDanger(el, d) {
    let html = '<div class="danger-status">';
    const active = d.active === true;
    const type = d.type || 'none';
    const level = d.level || 'green';

    const badgeClass = 'danger-' + level;
    const icons = {
      uav: '✈️',
      missile: '🚀',
      air_raid: '🔔',
      artillery: '💥',
      chemical: '☣️',
      nuclear: '☢️',
      all_clear: '✅',
      none: '🛡️',
    };
    const labels = {
      uav: 'Беспилотник',
      missile: 'Ракетная угроза',
      air_raid: 'Воздушная тревога',
      artillery: 'Артиллерийский обстрел',
      chemical: 'Химическая угроза',
      nuclear: 'Ядерная угроза',
      all_clear: 'Тревога снята',
      none: 'Спокойно',
    };

    html += '<div class="danger-badge ' + badgeClass + '">' + (icons[type] || '⚠️') + ' ' + (labels[type] || 'Неизвестно') + '</div>';
    if (d.message) html += '<div class="danger-message">' + escapeHtml(d.message) + '</div>';
    if (d.area) html += '<div class="danger-area">Район: ' + escapeHtml(d.area) + '</div>';
    if (d.started_at) html += '<div class="danger-time">Начало: ' + escapeHtml(d.started_at) + '</div>';
    if (!active) {
      html += '<div class="danger-all-clear">✅ Опасностей не обнаружено</div>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  function refreshAllWidgets() {
    initWeather();
    initNews();
    initDanger();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refreshAllWidgets);
  } else {
    refreshAllWidgets();
  }

  window.RadarWidgets = {
    refresh: refreshAllWidgets,
    initWeather,
    initNews,
    initDanger,
    setTheme: (t) => { currentTheme = t; refreshAllWidgets(); },
  };
})();
"""


def routes(web_module):
    """Return aiohttp routes for widget API."""
    return [
        web_module.get("/api/widget/weather", widget_weather),
        web_module.get("/api/widget/news", widget_news),
        web_module.get("/api/widget/danger", widget_danger),
    ]


__all__ = ["routes", "WIDGET_JS", "widget_weather", "widget_news", "widget_danger"]
