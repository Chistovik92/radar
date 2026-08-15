"""Веб-панель администратора: отдельный процесс поверх aiohttp.

Панель запускается своей задачей и падает независимо от бота: исключение
здесь не должно останавливать оповещения. Поэтому весь запуск обёрнут
в защиту, а флаг `web_panel` позволяет выключить её на живой системе.

Терминала сервера в панели нет и не планируется: удалённое выполнение команд
из браузера при утечке сессии отдаёт весь сервер, а не данные бота.
Управление сервером остаётся через SSH.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
import logging
from typing import Any

from .. import config, features, roles, storage
from . import auth

log = logging.getLogger("radar.web")

PAGE_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; background:#171b24; color:#e8ecf3;
       font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
header { background:#1f2532; padding:14px 22px; display:flex;
         align-items:center; gap:18px; border-bottom:1px solid #2b3242; }
header b { font-size:17px; }
nav a { color:#9fb4d4; text-decoration:none; margin-right:16px; }
nav a:hover, nav a.active { color:#5ea8ff; }
main { padding:22px; max-width:1100px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 18px; }
table { width:100%; border-collapse:collapse; background:#1f2532;
        border-radius:10px; overflow:hidden; }
th, td { padding:10px 14px; text-align:left; border-bottom:1px solid #2b3242; }
th { color:#92a0b8; font-weight:600; font-size:13px; text-transform:uppercase; }
tr:last-child td { border-bottom:none; }
.card { background:#1f2532; border-radius:10px; padding:18px; margin-bottom:16px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
        gap:14px; margin-bottom:20px; }
.metric b { display:block; font-size:26px; margin-bottom:4px; }
.metric span { color:#92a0b8; font-size:13px; }
.ok { color:#6bd08a; } .warn { color:#ffc45e; } .bad { color:#ff7a7a; }
.muted { color:#92a0b8; }
.login { max-width:420px; margin:80px auto; text-align:center; }
"""


def _layout(title: str, body: str, active: str = "", role: str = "") -> str:
    links = [
        ("/", "Обзор", "home"),
        ("/users", "Пользователи", "users"),
        ("/sources", "Источники", "sources"),
        ("/events", "События", "events"),
        ("/features", "Возможности", "features"),
        ("/audit", "Журнал", "audit"),
    ]
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{name}</a>'
        for href, name, key in links
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — Радар</title><style>{PAGE_STYLE}</style></head>
<body>
<header><b>Радар</b><nav>{nav}</nav>
<span class="muted" style="margin-left:auto">{html.escape(role)} ·
<a href="/logout" style="color:#9fb4d4">выйти</a></span></header>
<main><h1>{html.escape(title)}</h1>{body}</main></body></html>"""


def _login_page(bot_username: str, message: str = "") -> str:
    warning = f'<p class="bad">{html.escape(message)}</p>' if message else ""
    widget = (
        f'<script async src="https://telegram.org/js/telegram-widget.js?22" '
        f'data-telegram-login="{html.escape(bot_username)}" data-size="large" '
        f'data-auth-url="/auth" data-request-access="write"></script>'
        if bot_username else
        '<p class="warn">Имя бота не определено — вход недоступен.</p>'
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход — Радар</title><style>{PAGE_STYLE}</style></head>
<body><div class="login">
<h1>Панель системы «Радар»</h1>
<p class="muted">Вход через Telegram. Доступ — с роли администратора.</p>
{warning}{widget}
</div></body></html>"""


# --------------------------------------------------------------------------
#  Данные для страниц
# --------------------------------------------------------------------------

def _overview_body() -> str:
    users = storage.users()
    locations = sum(len(item.get("locs") or []) for item in users.values())
    by_role: dict[str, int] = {}
    for item in users.values():
        by_role[item.get("role", "user")] = by_role.get(item.get("role", "user"), 0) + 1

    metrics = [
        ("Пользователей", len(users)),
        ("Локаций", locations),
        ("Каналов", len(storage.channels())),
        ("Лент RSS", len(storage.rss_feeds())),
        ("Сообществ VK", len(storage.vk_groups())),
        ("Сессий панели", auth.active_sessions()),
    ]
    cards = "".join(
        f'<div class="card metric"><b>{value}</b><span>{html.escape(name)}</span></div>'
        for name, value in metrics
    )

    roles_rows = "".join(
        f"<tr><td>{html.escape(roles.title(key))}</td><td>{count}</td></tr>"
        for key, count in sorted(by_role.items())
    )
    return (
        f'<div class="grid">{cards}</div>'
        f'<div class="card"><h3>Роли</h3><table>'
        f"<tr><th>Роль</th><th>Человек</th></tr>{roles_rows}</table></div>"
    )


def _users_body() -> str:
    rows = []
    for key, item in sorted(storage.users().items()):
        locations = item.get("locs") or []
        cities = ", ".join(
            sorted({str(loc.get("city") or "") for loc in locations if loc.get("city")})
        )
        rows.append(
            f"<tr><td><code>{html.escape(key)}</code></td>"
            f"<td>{html.escape(roles.title(item.get('role', 'user')))}</td>"
            f"<td>{len(locations)}</td>"
            f"<td>{html.escape(cities or '—')}</td></tr>"
        )
    return (
        '<div class="card"><table><tr><th>Ключ</th><th>Роль</th>'
        f"<th>Локаций</th><th>Города</th></tr>{''.join(rows)}</table></div>"
    )


def _sources_body() -> str:
    def block(title: str, items: list[str]) -> str:
        rows = "".join(f"<tr><td>{html.escape(item)}</td></tr>" for item in items)
        return (
            f'<div class="card"><h3>{html.escape(title)} — {len(items)}</h3>'
            f"<table>{rows or '<tr><td class=muted>пусто</td></tr>'}</table></div>"
        )

    return (
        block("Telegram-каналы", list(storage.channels()))
        + block("RSS-ленты", list(storage.rss_feeds()))
        + block("Сообщества VK", list(storage.vk_groups()))
        + block("В очереди модерации", list(storage.pending()))
    )


async def _events_body() -> str:
    try:
        from ..db import repo

        stats = await repo.event_stats(days=7)
    except Exception as exc:  # noqa: BLE001
        return f'<div class="card bad">История недоступна: {html.escape(str(exc))}</div>'

    return (
        '<div class="grid">'
        f'<div class="card metric"><b>{stats["events"]}</b>'
        "<span>событий за неделю</span></div>"
        f'<div class="card metric"><b>{stats["deliveries"]}</b>'
        "<span>доставок за неделю</span></div>"
        "</div>"
        '<div class="card muted">Лента событий по адресам доступна в боте: '
        "карточка локации → «Что было по этому адресу».</div>"
    )


def _features_body() -> str:
    rows = []
    for group, items in features.by_group().items():
        rows.append(f'<tr><th colspan="2">{html.escape(group)}</th></tr>')
        for flag in items:
            state = (
                '<span class="muted">всегда включено</span>' if flag.locked
                else ('<span class="ok">включено</span>' if features.enabled(flag.key)
                      else '<span class="muted">выключено</span>')
            )
            rows.append(
                f"<tr><td>{html.escape(flag.title)}<br>"
                f'<span class="muted">{html.escape(flag.description)}</span></td>'
                f"<td>{state}</td></tr>"
            )
    return (
        f'<div class="card"><table>{"".join(rows)}</table></div>'
        '<div class="card muted">Переключаются в боте: /features. '
        "Панель показывает состояние, но не меняет его — критичные "
        "переключатели остаются за подтверждённым каналом.</div>"
    )


def _audit_body() -> str:
    from . import audit

    rows = "".join(
        f"<tr><td>{html.escape(item.when)}</td>"
        f"<td><code>{html.escape(item.actor)}</code></td>"
        f"<td>{html.escape(item.action)}</td>"
        f"<td>{html.escape(item.detail)}</td></tr>"
        for item in audit.recent(120)
    )
    return (
        '<div class="card"><table><tr><th>Время</th><th>Кто</th>'
        f"<th>Действие</th><th>Подробности</th></tr>"
        f"{rows or '<tr><td colspan=4 class=muted>записей нет</td></tr>'}</table></div>"
    )


# --------------------------------------------------------------------------
#  Сервер
# --------------------------------------------------------------------------

async def create_app() -> Any:
    """Собирает приложение. Импорт aiohttp внутри — панель необязательна."""
    from aiohttp import web

    from . import audit

    application = web.Application()
    bot_username = {"value": ""}

    async def resolve_username(_app) -> None:
        try:
            from ..tg import bot

            me = await bot.get_me()
            bot_username["value"] = me.username or ""
        except Exception:  # noqa: BLE001
            log.warning("Имя бота для виджета входа не определено")

    application.on_startup.append(resolve_username)

    def current_session(request):
        return auth.session_by_token(request.cookies.get(auth.SESSION_COOKIE, ""))

    def guard(handler):
        async def wrapper(request):
            session = current_session(request)
            if session is None:
                raise web.HTTPFound("/login")
            return await handler(request, session)
        return wrapper

    async def login(request):
        return web.Response(
            text=_login_page(bot_username["value"], request.query.get("error", "")),
            content_type="text/html",
        )

    async def authenticate(request):
        data = dict(request.query)
        address = request.headers.get("X-Forwarded-For", request.remote or "")

        def role_lookup(key: str) -> str:
            user = storage.get_user(key)
            return user.get("role", "") if user else ""

        session, reason = auth.authenticate(
            data, config.BOT_TOKEN, role_lookup, address
        )
        if session is None:
            audit.record("—", "неудачный вход", reason)
            raise web.HTTPFound(f"/login?error={reason}")

        audit.record(session.user_key, "вход в панель", session.role)
        response = web.HTTPFound("/")
        response.set_cookie(
            auth.SESSION_COOKIE, session.token,
            max_age=auth.SESSION_TTL, httponly=True, samesite="Lax",
            secure=config.WEB_HTTPS,
        )
        raise response

    async def logout(request):
        token = request.cookies.get(auth.SESSION_COOKIE, "")
        session = auth.session_by_token(token)
        if session is not None:
            audit.record(session.user_key, "выход из панели", "")
        auth.drop_session(token)
        response = web.HTTPFound("/login")
        response.del_cookie(auth.SESSION_COOKIE)
        raise response

    @guard
    async def overview(_request, session):
        return web.Response(
            text=_layout("Обзор", _overview_body(), "home", roles.title(session.role)),
            content_type="text/html",
        )

    @guard
    async def users_page(_request, session):
        return web.Response(
            text=_layout("Пользователи", _users_body(), "users", roles.title(session.role)),
            content_type="text/html",
        )

    @guard
    async def sources_page(_request, session):
        return web.Response(
            text=_layout("Источники", _sources_body(), "sources", roles.title(session.role)),
            content_type="text/html",
        )

    @guard
    async def events_page(_request, session):
        body = await _events_body()
        return web.Response(
            text=_layout("События", body, "events", roles.title(session.role)),
            content_type="text/html",
        )

    @guard
    async def features_page(_request, session):
        return web.Response(
            text=_layout("Возможности", _features_body(), "features",
                         roles.title(session.role)),
            content_type="text/html",
        )

    @guard
    async def audit_page(_request, session):
        if not roles.is_superadmin(session.role):
            raise web.HTTPFound("/")
        return web.Response(
            text=_layout("Журнал действий", _audit_body(), "audit",
                         roles.title(session.role)),
            content_type="text/html",
        )

    async def health(_request):
        return web.json_response({"status": "ok", "version": config.VERSION})

    application.add_routes([
        web.get("/login", login),
        web.get("/auth", authenticate),
        web.get("/logout", logout),
        web.get("/", overview),
        web.get("/users", users_page),
        web.get("/sources", sources_page),
        web.get("/events", events_page),
        web.get("/features", features_page),
        web.get("/audit", audit_page),
        web.get("/health", health),
    ])
    return application


async def run() -> None:
    """Запускает панель. Любая ошибка здесь не должна касаться бота."""
    if not features.enabled("web_panel"):
        log.info("Веб-панель выключена флагом web_panel")
        return

    try:
        from aiohttp import web

        application = await create_app()
        runner = web.AppRunner(application)
        await runner.setup()
        site = web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT)
        await site.start()
        log.info(
            "Веб-панель слушает %s:%d (HTTPS %s)",
            config.WEB_HOST, config.WEB_PORT,
            "через reverse proxy" if config.WEB_HTTPS else "выключен",
        )
        if not config.WEB_HTTPS:
            log.warning(
                "WEB_HTTPS выключен: панель отдаёт cookie без флага secure. "
                "Открывать её наружу в таком виде нельзя."
            )
    except Exception:  # noqa: BLE001
        log.exception("Веб-панель не запустилась — бот продолжает работу")
