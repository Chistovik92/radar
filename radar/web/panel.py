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
from urllib.parse import quote

from .. import config, features, roles, shortener, storage
from . import auth

log = logging.getLogger("radar.web")

PAGE_STYLE = """
/* Две темы. Значения собраны в переменные, чтобы правка цвета
   не расползалась по десятку правил: у панели один набор ролей —
   фон, поверхность, текст, приглушённый текст, рамка, ссылка. */
:root {
  --bg: #171b24; --surface: #1f2532; --surface-2: #262d3d;
  --text: #e8ecf3; --muted: #92a0b8; --line: #2b3242;
  --link: #5ea8ff; --link-dim: #9fb4d4;
  --ok: #6bd08a; --warn: #ffc45e; --bad: #ff7a7a;
  --shadow: 0 1px 3px rgba(0,0,0,.35);
  color-scheme: dark;
}
/* Светлая тема. Не инверсия тёмной: на белом фоне те же насыщенности
   выжигают глаза, поэтому акценты взяты темнее, а поверхности — почти
   белые с ощутимой рамкой, иначе карточки сливаются с фоном. */
[data-theme="light"] {
  --bg: #eef1f6; --surface: #ffffff; --surface-2: #f4f6fa;
  --text: #1b212c; --muted: #5d6a80; --line: #d7dde8;
  --link: #1f6fd0; --link-dim: #46536a;
  --ok: #1f8a4c; --warn: #96650a; --bad: #c0342c;
  --shadow: 0 1px 3px rgba(16,24,40,.08);
  color-scheme: light;
}

* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }

header { background:var(--surface); padding:12px 22px; display:flex;
         align-items:center; gap:16px; border-bottom:1px solid var(--line);
         position:sticky; top:0; z-index:5; flex-wrap:wrap; }
header .brand { font-weight:700; font-size:17px; letter-spacing:.2px; }
nav { display:flex; gap:4px; flex-wrap:wrap; }
nav a { color:var(--link-dim); text-decoration:none; padding:6px 10px;
        border-radius:7px; white-space:nowrap; }
nav a:hover { color:var(--link); background:var(--surface-2); }
nav a.active { color:var(--link); background:var(--surface-2); font-weight:600; }
.spacer { margin-left:auto; }
.who { color:var(--muted); font-size:14px; }
.who a { color:var(--link-dim); }

main { padding:22px; max-width:1100px; margin:0 auto; }
h1 { font-size:21px; margin:0 0 18px; }
h3 { margin:0 0 12px; font-size:16px; }

table { width:100%; border-collapse:collapse; background:var(--surface);
        border-radius:10px; overflow:hidden; box-shadow:var(--shadow); }
th, td { padding:10px 14px; text-align:left; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; font-size:13px; text-transform:uppercase;
     letter-spacing:.03em; }
tr:last-child td { border-bottom:none; }

.card { background:var(--surface); border-radius:10px; padding:18px;
        margin-bottom:16px; box-shadow:var(--shadow); }
.card table { box-shadow:none; background:transparent; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
        gap:14px; margin-bottom:20px; }
.metric b { display:block; font-size:26px; margin-bottom:4px; }
.metric span { color:var(--muted); font-size:13px; }
.ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.muted { color:var(--muted); }
.login { max-width:420px; margin:80px auto; text-align:center; }

form.inline { display:flex; gap:10px; margin-top:12px; flex-wrap:wrap; }
input[type=text], input[type=password], input[type=url], textarea, select {
  padding:9px 12px; border-radius:8px; border:1px solid var(--line);
  background:var(--bg); color:var(--text); font:inherit; }
form.inline input[type=text], form.inline input[type=password],
form.inline input[type=url] { flex:1 1 240px; }
textarea { width:100%; min-height:70px; resize:vertical; }
button { padding:9px 16px; border-radius:8px; border:none; cursor:pointer;
         background:var(--link); color:#fff; font:inherit; }
button:hover { filter:brightness(1.08); }
button.ghost { background:var(--surface-2); color:var(--text);
               padding:5px 11px; font-size:13px; }
button.ghost:hover { filter:brightness(1.06); }
button.danger { background:var(--bad); }

.note { padding:11px 14px; border-radius:8px; margin-bottom:16px; }
.note.good { background:color-mix(in srgb, var(--ok) 18%, var(--surface));
             color:var(--ok); }
.note.bad { background:color-mix(in srgb, var(--bad) 18%, var(--surface));
            color:var(--bad); }
.keyrow { display:grid; grid-template-columns:1fr; gap:6px; padding:12px 0;
          border-bottom:1px solid var(--line); }
.keyrow:last-child { border-bottom:none; }
.keyrow .hint { color:var(--muted); font-size:13px; }

/* Переключатель темы. Кнопка, а не хитрый ползунок: она читается
   без объяснений и работает без мыши. */
#theme { background:var(--surface-2); color:var(--text); padding:6px 11px;
         font-size:14px; line-height:1; }

@media (max-width: 640px) {
  header { padding:10px 14px; gap:10px; }
  main { padding:14px; }
  th, td { padding:8px 10px; }
}
"""

# Тема выбирается до отрисовки, иначе страница мигает тёмной и лишь потом
# становится светлой. Скрипт крошечный и стоит в head намеренно.
THEME_SCRIPT = """
(function () {
  try {
    var saved = localStorage.getItem('radar-theme');
    if (!saved) {
      saved = window.matchMedia &&
              window.matchMedia('(prefers-color-scheme: light)').matches
              ? 'light' : 'dark';
    }
    document.documentElement.setAttribute('data-theme', saved);
  } catch (e) { /* приватный режим: остаётся тема по умолчанию */ }
})();
"""

THEME_TOGGLE = """
(function () {
  var button = document.getElementById('theme');
  if (!button) { return; }
  var root = document.documentElement;
  function paint() {
    var light = root.getAttribute('data-theme') === 'light';
    button.textContent = light ? '\u263e' : '\u2600';
    button.title = light ? 'Тёмная тема' : 'Светлая тема';
  }
  paint();
  button.addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('radar-theme', next); } catch (e) {}
    paint();
  });
})();
"""


def _links_for(role: str) -> list[tuple[str, str, str]]:
    """Разделы по роли: панель повторяет права бота, а не расширяет их."""
    links = [("/", "Обзор", "home"), ("/sources", "Источники", "sources")]
    if roles.is_moderator(role):
        links.append(("/users", "Пользователи", "users"))
    if roles.is_admin(role):
        links.append(("/events", "События", "events"))
    if roles.is_superadmin(role):
        links.append(("/keys", "Ключи", "keys"))
        links.append(("/files", "Файлы", "files"))
        links.append(("/features", "Возможности", "features"))
        links.append(("/backup", "Копии", "backup"))
        links.append(("/audit", "Журнал", "audit"))
        if features.enabled("partners"):
            links.append(("/partners", "Партнёры", "partners"))
    return links


def _layout(title: str, body: str, active: str = "", role: str = "",
            role_key: str = "") -> str:
    links = _links_for(role_key)
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{name}</a>'
        for href, name, key in links
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — Радар</title>
<script>{THEME_SCRIPT}</script>
<style>{PAGE_STYLE}</style></head>
<body>
<header>
  <span class="brand">Радар</span>
  <nav>{nav}</nav>
  <span class="spacer"></span>
  <button id="theme" type="button" aria-label="Сменить тему">☀</button>
  <span class="who">{html.escape(role)} · <a href="/logout">выйти</a></span>
</header>
<main><h1>{html.escape(title)}</h1>{body}</main>
<script>{THEME_TOGGLE}</script>
</body></html>"""


def _login_page(bot_username: str, message: str = "",
                public_url: str = "") -> str:
    warning = f'<p class="bad">{html.escape(message)}</p>' if message else ""
    widget = (
        f'<script async src="https://telegram.org/js/telegram-widget.js?22" '
        f'data-telegram-login="{html.escape(bot_username)}" data-size="large" '
        f'data-auth-url="/auth" data-request-access="write"></script>'
        if bot_username else
        '<p class="warn">Имя бота не определено — вход недоступен.</p>'
    )
    # Подсказка про домен. Виджет Telegram при непривязанном домене
    # показывает только «Bot domain invalid» — и по этой надписи нельзя
    # догадаться, что делать. Ошибка не наша: домен привязывается
    # у BotFather, и никакая настройка на сервере её не снимет.
    hint = (
        '<details class="muted" style="margin-top:18px;text-align:left">'
        '<summary>Кнопка не работает или пишет «Bot domain invalid»?</summary>'
        '<p>Домен нужно привязать к боту — это делается в Telegram, '
        'а не на сервере:</p>'
        '<ol>'
        '<li>Откройте <b>@BotFather</b></li>'
        '<li>Команда <code>/setdomain</code></li>'
        '<li>Выберите своего бота'
        + (f' (<b>@{html.escape(bot_username)}</b>)' if bot_username else '')
        + '</li>'
        '<li>Пришлите адрес панели: <code>' + html.escape(public_url or
          'https://ваш-домен') + '</code></li>'
        '</ol>'
        '<p>Адрес должен совпадать точно — со схемой <code>https://</code> '
        'и без пути в конце. По IP-адресу вход через Telegram '
        '<b>не работает вовсе</b>: виджет принимает только домены.</p>'
        '</details>'
    )

    # Тема выбирается и здесь: вход — первая страница, которую человек
    # видит, и встречать его чужой темой было бы странно.
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход — Радар</title>
<script>{THEME_SCRIPT}</script>
<style>{PAGE_STYLE}</style></head>
<body><div class="login">
<h1>Панель системы «Радар»</h1>
<p class="muted">Вход через Telegram. Доступ — с роли администратора.</p>
{warning}{widget}{hint}
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


def _users_body(role: str = "") -> str:
    """Список пользователей. Модератору идентификаторы показываются частично:
    для его задач они не нужны, а утечка списка — лишний риск."""
    full = roles.is_admin(role)
    rows = []
    for key, item in sorted(storage.users().items()):
        locations = item.get("locs") or []
        cities = ", ".join(
            sorted({str(loc.get("city") or "") for loc in locations if loc.get("city")})
        )
        rows.append(
            f"<tr><td><code>{html.escape(key if full else key[:4] + '…')}</code></td>"
            f"<td>{html.escape(roles.title(item.get('role', 'user')))}</td>"
            f"<td>{len(locations)}</td>"
            f"<td>{html.escape(cities or '—')}</td></tr>"
        )
    return (
        '<div class="card"><table><tr><th>Ключ</th><th>Роль</th>'
        f"<th>Локаций</th><th>Города</th></tr>{''.join(rows)}</table></div>"
    )


def _note(kind: str, text: str) -> str:
    """Полоса с итогом действия. Пусто — ничего не показываем."""
    if not text:
        return ""
    css = "good" if kind == "ok" else "bad"
    return f'<div class="note {css}">{html.escape(text)}</div>'


def _sources_body(session, message: str = "", failed: str = "") -> str:
    """Источники: список с удалением и форма добавления.

    Правка открыта модератору — ровно как в боте. Панель повторяет права
    бота, а не расширяет их: иначе роль означала бы разное в двух местах.
    """
    from .. import sourceedit as se

    editable = roles.is_moderator(session.role)
    token = auth.csrf_token(session)

    def rows(kind: str, items: list[str]) -> str:
        if not items:
            return '<tr><td class="muted">пусто</td></tr>'
        out = []
        for item in items:
            action = ""
            if editable:
                action = (
                    '<form method="post" action="/sources/remove" '
                    'style="display:inline">'
                    f'<input type="hidden" name="csrf" value="{token}">'
                    f'<input type="hidden" name="kind" value="{html.escape(kind)}">'
                    f'<input type="hidden" name="value" value="{html.escape(item)}">'
                    '<button class="ghost" type="submit">удалить</button></form>'
                )
            out.append(
                f"<tr><td>{html.escape(item)}</td>"
                f'<td style="text-align:right;width:1%">{action}</td></tr>'
            )
        return "".join(out)

    def card(kind: str, title: str, placeholder: str) -> str:
        items = se.listing(kind)
        form = ""
        if editable:
            form = (
                '<form class="inline" method="post" action="/sources/add">'
                f'<input type="hidden" name="csrf" value="{token}">'
                f'<input type="hidden" name="kind" value="{html.escape(kind)}">'
                f'<input type="text" name="value" placeholder="{html.escape(placeholder)}" '
                'required autocomplete="off">'
                '<button type="submit">Добавить</button></form>'
            )
        return (
            f'<div class="card"><h3>{html.escape(title)} — {len(items)}</h3>'
            f"<table>{rows(kind, items)}</table>{form}</div>"
        )

    pending = list(storage.pending())
    queue_rows = "".join(
        f"<tr><td>{html.escape(item)}</td></tr>" for item in pending
    ) or '<tr><td class="muted">пусто</td></tr>'

    return (
        _note("ok", message)
        + _note("bad", failed)
        + card(se.TELEGRAM, "Telegram-каналы",
               "@channel, ссылка t.me или несколько через запятую")
        + card(se.RSS, "RSS-ленты", "https://example.ru/rss")
        + card(se.VK, "Сообщества VK", "короткое имя или ссылка vk.com/…")
        + '<div class="card"><h3>В очереди модерации — '
        + str(len(pending))
        + f"</h3><table>{queue_rows}</table>"
        + '<p class="muted">Очередь разбирается в боте: предложение '
          "пользователя принимается или отклоняется там, вместе с ответом "
          "приславшему.</p></div>"
    )


def _files_body(session, message: str = "", failed: str = "") -> str:
    """Раздача крупных файлов: кому выдана ссылка, забрали ли, сколько живёт.

    Панель — единственное место, где эту раздачу видно целиком. В боте
    человек видит свою ссылку и всё; администрации нужен обзор: чей файл,
    сколько занимает, скачали или нет, сколько осталось до сгорания.
    """
    from .. import filedrop, roles as roles_module, subscription

    token = auth.csrf_token(session)
    items = [item for item in filedrop.listing() if item.hours_left > 0]

    if not filedrop.enabled():
        return (
            '<div class="card"><b>Раздача выключена.</b> '
            '<span class="muted">Нужен внешний адрес: задайте '
            '<code>SHORT_BASE_URL</code> в разделе ключей. Без него ссылка '
            "вела бы в никуда, поэтому бот её не предлагает.</span></div>"
        )

    total_mb = sum(item.size for item in items) / 1024 / 1024
    head = (
        '<div class="grid">'
        f'<div class="card metric"><b>{len(items)}</b>'
        "<span>файлов в раздаче</span></div>"
        f'<div class="card metric"><b>{total_mb:.0f} МБ</b>'
        f"<span>занято из {filedrop.BUDGET_MB} МБ</span></div>"
        f'<div class="card metric"><b>{filedrop.MAX_FILE_MB // 1024} ГБ</b>'
        "<span>предел на один файл</span></div>"
        f'<div class="card metric"><b>{filedrop.TTL_HOURS} ч</b>'
        "<span>срок жизни ссылки</span></div>"
        "</div>"
    )

    if not items:
        return (_note("ok", message) + _note("bad", failed) + head
                + '<div class="card muted">Сейчас в раздаче пусто.</div>')

    rows = []
    for item in items:
        user = storage.get_user(item.owner) if item.owner else None
        if user is None:
            who = '<span class="muted">неизвестен</span>'
            plan = '<span class="muted">—</span>'
        else:
            name = user.get("username") or item.owner
            who = f"{html.escape(str(name))} "
            who += f'<span class="muted">{html.escape(roles_module.title(user.get("role", "")))}</span>'
            active = subscription.active(user, user.get("role"))
            plan = ('<span class="ok">подписка</span>' if active
                    else '<span class="muted">без подписки</span>')

        taken = (f'<span class="ok">забрали, раз: {item.hits}</span>'
                 if item.hits else '<span class="warn">ещё не скачан</span>')
        link = html.escape(filedrop.url_for(item))
        rows.append(
            "<tr>"
            f'<td><a href="{link}">{html.escape(item.name)}</a><br>'
            f'<span class="muted">{item.size_mb:.0f} МБ</span></td>'
            f"<td>{who}<br>{plan}</td>"
            f"<td>{taken}</td>"
            f"<td>{item.hours_left:.1f} ч</td>"
            '<td style="text-align:right;width:1%">'
            '<form method="post" action="/files/remove">'
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="token" value="{item.token}">'
            '<button class="ghost danger" type="submit">отключить</button>'
            "</form></td></tr>"
        )

    table = (
        '<div class="card"><table><tr>'
        "<th>Файл</th><th>Кому выдана</th><th>Состояние</th>"
        "<th>Осталось</th><th></th></tr>"
        + "".join(rows) + "</table>"
        '<p class="muted">Ссылка — секрет: проверить учётную запись '
        "Telegram при запросе из браузера невозможно, поэтому скачает тот, "
        "кому её переслали. «Отключить» удаляет файл сразу, не дожидаясь "
        "конца срока.</p></div>"
    )
    return _note("ok", message) + _note("bad", failed) + head + table


def _keys_body(session, message: str = "", failed: str = "") -> str:
    """Ключи ИИ и токены сервисов. Только запись, без чтения.

    Значение показывается маской: перехваченная сессия панели не должна
    отдавать ключи целиком. Проверить «тот ли ключ вставлен» по маске
    можно — по первым и последним знакам, — а увести его нельзя.
    """
    from .. import secrets as secrets_module

    token = auth.csrf_token(session)
    groups: dict[str, list] = {}
    for setting in secrets_module.SETTINGS:
        groups.setdefault(setting.group, []).append(setting)

    cards = []
    for group, items in groups.items():
        rows = []
        for setting in items:
            current = secrets_module.get(setting.key)
            shown = (secrets_module.mask(current) if setting.secret
                     else (current or "— не задано —"))
            where = (f' <span class="hint">Где взять: {html.escape(setting.where)}</span>'
                     if setting.where else "")
            restart = (' <span class="warn">применится после перезапуска</span>'
                       if setting.restart else "")
            field = "password" if setting.secret else "text"
            rows.append(
                '<div class="keyrow">'
                f"<div><b>{html.escape(setting.title)}</b> "
                f'<span class="muted">{html.escape(setting.key)}</span></div>'
                f'<div class="hint">{html.escape(setting.hint)}{where}{restart}</div>'
                f'<div class="hint">Сейчас: {html.escape(shown)}</div>'
                '<form class="inline" method="post" action="/keys/set">'
                f'<input type="hidden" name="csrf" value="{token}">'
                f'<input type="hidden" name="key" value="{html.escape(setting.key)}">'
                f'<input type="{field}" name="value" autocomplete="off" '
                'placeholder="новое значение, пусто — очистить">'
                '<button type="submit">Сохранить</button></form>'
                "</div>"
            )
        cards.append(
            f'<div class="card"><h3>{html.escape(group)}</h3>{"".join(rows)}</div>'
        )

    warning = (
        '<div class="card"><b>Значения не показываются.</b> '
        '<span class="muted">Панель принимает новый ключ, но не отдаёт '
        "существующий: доступ к чужой сессии не должен означать доступ "
        "ко всем ключам сразу. Полное значение видно только в файле "
        "<code>.env</code> на сервере.</span></div>"
    )
    return _note("ok", message) + _note("bad", failed) + warning + "".join(cards)



async def _partners_body() -> str:
    """Партнёрские проекты и выдача промокодов.

    Панель повторяет то, что доступно в боте, а не расширяет права:
    раздел открыт суперадминистратору, как и правка в боте.
    """
    from .. import partners

    try:
        projects = partners.order_projects(await partners.load())
    except Exception as exc:  # noqa: BLE001
        return f'<div class="card bad">Список недоступен: {html.escape(str(exc))}</div>'

    if not projects:
        return '<div class="card">Проектов пока нет. Добавьте их в боте.</div>'

    rows = []
    for project in projects:
        state = "виден" if project.visible else "скрыт"
        kind = partners.KIND_TITLES.get(project.promo_kind, "—")
        issued = ""
        if project.has_promo and features.enabled("promo_codes"):
            try:
                from ..db import repo

                count = await repo.promo_count(project.slug)
                issued = (
                    f'<a href="/partners/export?slug={html.escape(project.slug)}">'
                    f"выгрузить ({count})</a>"
                )
            except Exception:  # noqa: BLE001
                issued = '<span class="muted">недоступно</span>'
        rows.append(
            "<tr>"
            f"<td>{html.escape(project.icon)} {html.escape(project.title)}</td>"
            f'<td><a href="{html.escape(project.url)}" rel="noopener noreferrer" '
            f'target="_blank">{html.escape(project.url[:48])}</a></td>'
            f"<td>{state}</td><td>{project.clicks}</td>"
            f"<td>{html.escape(kind)}</td><td>{issued}</td>"
            "</tr>"
        )

    return (
        '<div class="card"><table>'
        "<tr><th>Проект</th><th>Ссылка</th><th>Показ</th><th>Переходы</th>"
        "<th>Промокод</th><th>Коды</th></tr>"
        + "".join(rows)
        + "</table></div>"
        '<p class="muted">Правка проектов и настройка промокодов — в боте, '
        "раздел «Управление». Выгрузка содержит только код и дату выдачи, "
        "без идентификаторов пользователей.</p>"
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

    def guard(handler, minimum: str = "moderator"):
        """Доступ к странице. Роль проверяется на каждом запросе, а не при входе."""
        async def wrapper(request):
            session = current_session(request)
            if session is None:
                raise web.HTTPFound("/login")
            if not roles.at_least(session.role, minimum):
                audit.record(session.user_key, "отказ в доступе", request.path)
                raise web.HTTPFound("/")
            return await handler(request, session)
        return wrapper

    def admin_only(handler):
        return guard(handler, "admin")

    def owner_only(handler):
        return guard(handler, "superadmin")

    async def login(request):
        # Адрес берём из настроек сократителя: он же и есть внешний адрес
        # панели, если сертификат выдавался установщиком. Так подсказка
        # показывает конкретный адрес, а не «ваш-домен».
        from .. import shortener

        public = shortener.base_url()
        if not public:
            host = request.headers.get("Host", "")
            if host and not host.replace(".", "").replace(":", "").isdigit():
                scheme = request.headers.get("X-Forwarded-Proto", "https")
                public = f"{scheme}://{host}"

        return web.Response(
            text=_login_page(
                bot_username["value"], request.query.get("error", ""), public
            ),
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
            text=_layout("Обзор", _overview_body(), "home", roles.title(session.role), session.role),
            content_type="text/html",
        )

    @guard
    async def users_page(_request, session):
        return web.Response(
            text=_layout("Пользователи", _users_body(session.role), "users",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @guard
    async def sources_page(request, session):
        return web.Response(
            text=_layout(
                "Источники",
                _sources_body(session,
                              request.query.get("ok", ""),
                              request.query.get("err", "")),
                "sources", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    @owner_only
    async def keys_page(request, session):
        return web.Response(
            text=_layout(
                "Ключи",
                _keys_body(session,
                           request.query.get("ok", ""),
                           request.query.get("err", "")),
                "keys", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    @owner_only
    async def files_page(request, session):
        return web.Response(
            text=_layout(
                "Файлы",
                _files_body(session,
                            request.query.get("ok", ""),
                            request.query.get("err", "")),
                "files", roles.title(session.role), session.role,
            ),
            content_type="text/html",
        )

    async def files_remove(request):
        from .. import filedrop

        session, data = await _guarded_form(request, "superadmin")
        token = str(data.get("token", ""))
        if filedrop.remove(token):
            audit.record(session.user_key, "ссылка на файл отключена", token[:8])
            raise web.HTTPFound("/files?ok=" + quote("Ссылка отключена, файл удалён"))
        raise web.HTTPFound("/files?err=" + quote("Такой ссылки уже нет"))

    async def _guarded_form(request, minimum: str):
        """Общая часть записи: сессия, роль, токен формы.

        Возвращает (сессия, поля) либо бросает перенаправление. Проверки
        собраны в одном месте намеренно: пропустить одну из них в новом
        обработчике — самый лёгкий способ открыть панель наружу.
        """
        session = current_session(request)
        if session is None:
            raise web.HTTPFound("/login")
        if not roles.at_least(session.role, minimum):
            audit.record(session.user_key, "отказ в доступе", request.path)
            raise web.HTTPFound("/")
        data = await request.post()
        if not auth.csrf_valid(session, data.get("csrf", "")):
            audit.record(session.user_key, "форма отклонена", request.path)
            raise web.HTTPFound("/sources?err=Форма устарела, откройте страницу заново")
        return session, data

    async def sources_add(request):
        from .. import sourceedit as se

        session, data = await _guarded_form(request, "moderator")
        kind = str(data.get("kind", ""))
        if kind not in se.KINDS:
            raise web.HTTPFound("/sources?err=Неизвестный вид источника")

        added, skipped = se.add(kind, str(data.get("value", "")))
        if added:
            await storage.save()
            audit.record(session.user_key, "источники добавлены",
                         f"{kind}: {', '.join(added)}")
        parts = []
        if added:
            parts.append("Добавлено: " + ", ".join(added))
        if skipped:
            # Молчать про пропущенные нельзя: человек видит «добавлено 0»
            # и не понимает, ошибся он или источник уже был.
            parts.append("Пропущено (неверный формат или уже есть): "
                         + ", ".join(skipped))
        key = "ok" if added else "err"
        raise web.HTTPFound(f"/sources?{key}=" + quote("; ".join(parts) or "Ничего не добавлено"))

    async def sources_remove(request):
        from .. import sourceedit as se

        session, data = await _guarded_form(request, "moderator")
        kind = str(data.get("kind", ""))
        value = str(data.get("value", ""))
        if se.remove(kind, value):
            await storage.save()
            audit.record(session.user_key, "источник удалён", f"{kind}: {value}")
            raise web.HTTPFound("/sources?ok=" + quote(f"Удалён: {value}"))
        raise web.HTTPFound("/sources?err=" + quote("Такого источника нет"))

    async def download_drop(request):
        """Отдаёт крупный файл по ссылке из бота.

        Без входа в панель намеренно: ссылку человек открывает в браузере
        или качалкой, где сессии Telegram нет и быть не может. Защита —
        в непредсказуемом имени и в сроке жизни: ссылку выдаёт бот лично
        тому, кто с ним разговаривает.
        """
        from .. import filedrop

        drop = filedrop.find(request.match_info.get("token", ""))
        if drop is None:
            raise web.HTTPNotFound(
                text="Файл не найден или срок ссылки истёк.",
                content_type="text/plain",
            )
        filedrop.note_download(drop.token)
        log.info("Файл отдан по ссылке: %s (%.1f МБ)", drop.name, drop.size_mb)
        return web.FileResponse(
            drop.path,
            headers={
                # Имя из токена, а не из адреса: адрес человек может
                # обрезать, а имя файла должно остаться узнаваемым.
                "Content-Disposition":
                    f'attachment; filename="{drop.token}"; '
                    f"filename*=UTF-8''{quote(drop.name)}",
            },
        )

    async def keys_set(request):
        from .. import secrets as secrets_module

        session, data = await _guarded_form(request, "superadmin")
        key = str(data.get("key", ""))
        if key not in secrets_module.BY_KEY:
            raise web.HTTPFound("/keys?err=" + quote("Неизвестный ключ"))

        value = str(data.get("value", "")).strip()
        if not secrets_module.write(key, value):
            raise web.HTTPFound("/keys?err=" + quote(
                "Записать не удалось — проверьте права на .env"))

        # В журнал уходит имя ключа, но НИКОГДА значение: журнал панели
        # читается в самой панели, и записанный туда ключ свёл бы на нет
        # то, ради чего значения скрыты.
        audit.record(session.user_key,
                     "ключ очищен" if not value else "ключ изменён", key)
        done = "очищен" if not value else "сохранён"
        raise web.HTTPFound("/keys?ok=" + quote(f"{key} {done}"))

    @admin_only
    async def events_page(_request, session):
        body = await _events_body()
        return web.Response(
            text=_layout("События", body, "events", roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def partners_page(_request, session):
        body = await _partners_body()
        return web.Response(
            text=_layout("Партнёры", body, "partners",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def partners_export(request, _session):
        """Выгрузка кодов файлом. Отдаём то же, что и бот, — код и дату."""
        from .. import promo

        slug = request.query.get("slug", "")
        if not slug or len(slug) > 32:
            raise web.HTTPBadRequest(text="Не указан проект")
        rows = await promo.export_for_partner(slug)
        payload = promo.render_csv(rows)
        return web.Response(
            body=payload.encode("utf-8"),
            content_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="promo-{slug}.csv"',
            },
        )

    @owner_only
    async def features_page(_request, session):
        return web.Response(
            text=_layout("Возможности", _features_body(), "features",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def audit_page(_request, session):
        return web.Response(
            text=_layout("Журнал действий", _audit_body(), "audit",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def backup_page(_request, session):
        from . import backup as backup_module

        return web.Response(
            text=_layout("Резервные копии", backup_module.body(), "backup",
                         roles.title(session.role), session.role),
            content_type="text/html",
        )

    @owner_only
    async def backup_create(request, session):
        from . import backup as backup_module

        path, error = await backup_module.create(f"панель:{session.user_key}")
        if error:
            audit.record(session.user_key, "копия не создана", error)
            raise web.HTTPFound("/backup?error=1")
        audit.record(session.user_key, "создана копия", path.name)
        raise web.HTTPFound("/backup")

    @owner_only
    async def backup_download(request, session):
        from . import backup as backup_module

        name = request.query.get("name", "")
        target = backup_module.find(name)
        if target is None:
            raise web.HTTPFound("/backup")
        audit.record(session.user_key, "скачана копия", name)
        return web.FileResponse(target)

    async def health(_request):
        return web.json_response({"status": "ok", "version": config.VERSION})

    async def follow(request):
        """Переход по короткой ссылке.

        Единственный маршрут панели без авторизации — иначе ссылка была бы
        бесполезна. Поэтому он ничего не показывает и ничего не принимает:
        только ищет код и перенаправляет.
        """
        from ..db import repo

        code = request.match_info.get("code", "")
        if not shortener.valid_code(code):
            raise web.HTTPNotFound(text="Ссылка не найдена")
        target = await repo.resolve_short_link(code)
        if not target:
            raise web.HTTPNotFound(text="Ссылка не найдена")
        raise web.HTTPFound(target)

    application.add_routes([
        web.get("/login", login),
        web.get("/auth", authenticate),
        web.get("/logout", logout),
        web.get("/", overview),
        web.get("/users", users_page),
        web.get("/sources", sources_page),
        web.post("/sources/add", sources_add),
        web.post("/sources/remove", sources_remove),
        web.get("/keys", keys_page),
        web.get("/files", files_page),
        web.post("/files/remove", files_remove),
        web.post("/keys/set", keys_set),
        web.get("/events", events_page),
        web.get("/features", features_page),
        web.get("/audit", audit_page),
        web.get("/backup", backup_page),
        web.get("/backup/create", backup_create),
        web.get("/backup/download", backup_download),
        web.get("/health", health),
        web.get("/s/{code}", follow),
        web.get("/d/{token}", download_drop),
        web.get("/d/{token}/{name}", download_drop),
        web.get("/partners", partners_page),
        web.get("/partners/export", partners_export),
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
