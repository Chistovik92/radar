"""Публичный React-лендинг и его предсобранные статические ресурсы.

Интерактивная сцена собирается Vite в ``radar/web/static/landing``. Python
не требует Node.js в production и подмешивает только публичную конфигурацию.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
import json
from pathlib import Path

from aiohttp import web

from .. import __version__ as VERSION
from .landing_content import default_content, load_content

STATIC_DIR = Path(__file__).resolve().parent / "static" / "landing"
LANDING_ASSETS = {
    "landing.js": "text/javascript",
    "landing.css": "text/css",
}


def render_landing_page(bot_username: str = "", public_url: str = "",
                        content: dict | None = None) -> str:
    """Возвращает HTML-оболочку React, настройки и тексты из meta + схемы."""
    from .. import secrets as secrets_module
    from ..handlers import digest

    description = str(secrets_module.get("LANDING_DESCRIPTION") or "").strip()
    payload = {
        "botUsername": bot_username,
        "publicUrl": public_url,
        "description": description,
        "version": VERSION,
        "plans": digest._plans(),
        "content": default_content() if content is None else content,
    }
    # JSON в script должен экранировать '<': иначе текст администратора может
    # закрыть элемент script. Unicode escape сохраняет исходную строку в JS.
    config_json = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    safe_bot_username = html.escape(bot_username, quote=True)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="theme-color" content="#05070a" />
  <meta name="description" content="Радар — мониторинг городских угроз, аварий ЖКХ и важных событий по вашим адресам." />
  <title>Радар — город под наблюдением</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Ccircle cx='32' cy='32' r='27' fill='none' stroke='%23f5a623' stroke-width='4'/%3E%3Cpath d='M32 32L54 16M32 5v54M5 32h54' stroke='%23f5a623' stroke-width='3'/%3E%3C/svg%3E" />
  <link rel="stylesheet" href="/landing/landing.css?v={VERSION}" />
</head>
<body>
  <div id="root"></div>
  <noscript>Для интерактивного сайта включите JavaScript. <a href="https://t.me/{safe_bot_username}">Открыть Радар в Telegram</a>.</noscript>
  <script id="radar-config" type="application/json">{config_json}</script>
  <script type="module" src="/landing/landing.js?v={VERSION}"></script>
</body>
</html>
"""


def _landing_page(bot_username: str = "", public_url: str = "") -> str:
    """Совместимость со старым внутренним именем."""
    return render_landing_page(bot_username, public_url)


async def landing_asset(request: web.Request) -> web.StreamResponse:
    """Отдаёт только явно разрешённые сборочные файлы, без обхода каталога."""
    asset = request.match_info["asset"]
    content_type = LANDING_ASSETS.get(asset)
    if content_type is None:
        raise web.HTTPNotFound()
    path = STATIC_DIR / asset
    if not path.is_file():
        raise web.HTTPNotFound(text="Соберите лендинг: cd landing && npm run build")
    response = web.Response(body=path.read_bytes(), content_type=content_type, charset="utf-8")
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
