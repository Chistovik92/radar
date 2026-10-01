"""Раздел «Настройки» веб-панели: всё, что раньше жило в «Ключах» и «Возможностях» (5.9.2.2).

Человек думает темами — «Discord», «медиа», «журнал», — а не списком
переменных окружения и переключателей. До 5.9.2.2 тумблеры были на одной
странице, значения на другой, а половина значений не правилась вовсе.
Здесь каждая тема — карточка: её переключатели и её значения рядом.

Состав карточек задан данными (`SECTIONS`), поэтому новую настройку или
возможность достаточно добавить в реестр (`secrets.SETTINGS`, `features.FLAGS`)
и в одну из карточек; тест следит, чтобы ничто не осталось без страницы.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import html
from dataclasses import dataclass, field

from .. import features, secrets


@dataclass(frozen=True)
class Card:
    title: str
    groups: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    note: str = ""
    links: tuple[tuple[str, str], ...] = ()     # (адрес, подпись)


@dataclass(frozen=True)
class Section:
    key: str
    path: str
    title: str
    intro: str
    cards: tuple[Card, ...] = field(default_factory=tuple)


SECTIONS: tuple[Section, ...] = (
    Section("platforms", "/settings/platforms", "Платформы",
            "Мессенджеры, в которых работает бот, и их токены.", (
        Card("Telegram", groups=("Telegram",),
             note="Основная платформа. Свой Bot API Server снимает предел в 50 МБ "
                  "для загрузки файлов."),
        Card("ВКонтакте", flags=("platform_vk",), groups=("ВКонтакте",),
             note="Бот сообщества и токен для чтения источников."),
        Card("Discord", flags=("platform_discord", "discord_verify"), groups=("Discord",)),
        Card("MAX", flags=("platform_max",), groups=("MAX",)),
        Card("Одноклассники", groups=("Одноклассники",),
             note="Ключи для чтения источников из Одноклассников."),
    )),
    Section("ai", "/settings/ai", "ИИ",
            "Провайдеры, модели и лимиты разбора новостей и ассистента.", (
        Card("Возможности", flags=("ai_analysis", "ai_assistant", "provider_switch")),
        Card("Ключи провайдеров", groups=("ИИ",),
             links=(("/agents", "Свои агенты и их модели — раздел «Агенты»"),)),
        Card("Модели и лимиты", groups=("ИИ: модели и лимиты",),
             note="Лимиты — это квоты вашего тарифа у провайдера; завышенные значения "
                  "приведут к отказам 429."),
    )),
    Section("alerts", "/settings/alerts", "Оповещения и источники",
            "Как бот собирает новости, что отправляет и кому.", (
        Card("Оповещения", flags=("alerts", "weather", "all_clear", "whitelist_notice",
                                  "weather_image", "weather_image_all", "vpn_ad_filter",
                                  "quiet_hours", "antispam"),
             note="Оповещения об угрозах бесплатны всегда."),
        Card("Источники", flags=("source_telegram", "source_rss", "source_vk",
                                 "source_export", "source_autocheck"),
             groups=("Оповещения и источники",),
             links=(("/sources", "Список источников"),)),
        Card("Новости и подборки", flags=("digest", "digest_paid", "digest_suggestions",
                                          "digest_summaries"),
             links=(("/subscriptions", "Тарифы и подписка бота"),)),
        Card("Экстренное и модерация", flags=("sos", "moderation", "captcha_kick", "deleted_cleanup", "cas_check", "chat_post"),
             links=(("/chats", "Чаты под модерацией"),)),
        Card("Данные", flags=("backup_schedule", "history"),
             links=(("/backup", "Резервные копии"),)),
    )),
    Section("media", "/settings/media", "Медиа и облако",
            "Загрузка видео, музыка, облачное хранилище, раздача файлов.", (
        Card("Загрузка видео", flags=("media_download", "media_transcode"),
             groups=("Загрузка видео",),
             note="Файл cookies для закрытых записей присылается боту: команда /cookies."),
        Card("Музыка и облако", flags=("music", "music_meta", "music_cloud"),
             groups=("Облако музыки",),
             links=(("/cloud", "Облачные хранилища (rclone): добавить и проверить"),
                    ("/media", "Плейлисты"))),
        Card("Раздача файлов", groups=("Раздача файлов",),
             links=(("/files", "Файлы в раздаче"),)),
    )),
    Section("links", "/settings/links", "Ссылки и защита",
            "Короткие ссылки и проверка ссылок на опасность.", (
        Card("Короткие ссылки", flags=("link_shortener",), groups=("Короткие ссылки",),
             links=(("/links", "Список ссылок"),)),
        Card("Проверка ссылок", flags=("linkcheck",), groups=("Проверка ссылок",)),
    )),
    Section("system", "/settings/system", "Система",
            "Веб-панель, сеть, журнал, обслуживание, удалённый доступ, реклама проекта.", (
        Card("Веб-панель", flags=("web_panel",), groups=("Веб-панель",),
             note="Смена адреса или порта может отрезать вас от панели: проверьте "
                  "значения до перезапуска."),
        Card("Сеть", flags=("egress_proxy",), groups=("Сеть",)),
        Card("Журнал", groups=("Журнал",)),
        Card("Обслуживание", flags=("disk_watch", "maintenance", "restart_notice",
                                    "panel_update", "panel_wipe"),
             links=(("/maintenance", "Обслуживание"), ("/update", "Обновление"),
                    ("/wipe", "Удаление сервера"))),
        Card("RustDesk", flags=("rustdesk",), groups=("RustDesk",),
             links=(("/rustdesk", "Сервер удалённого доступа"),)),
        Card("Реклама и партнёры", flags=("partners", "promo_button", "promo_codes"),
             groups=("Реклама",),
             note="Реклама не появляется внутри тревожных сообщений — переключателя "
                  "для этого нет и не будет.",
             links=(("/partners", "Партнёры"),)),
    )),
)

BY_PATH = {section.path: section for section in SECTIONS}

# Что настраивается на других страницах панели: VPN и подписка бота.
ELSEWHERE_FLAGS = ("vpn", "vpn_sales", "app_api")
ELSEWHERE_GROUPS = ("Свои агенты", "Подписка бота", "Продажа VPN")

NOT_FROM_PANEL = (
    ("SUPERADMIN_ID", "владелец бота: неверное значение оставит бота без хозяина"),
    ("SECRET_KEY", "ключ шифрования: смена сделает прежние данные нечитаемыми"),
    ("DATABASE_URL, DB_*", "подключение к базе; смену базы с переносом данных делает установщик"),
    ("DATA_FILE, ENV_FILE, LOG_DIR", "пути внутри контейнера"),
    ("PROMO_IN_ALERTS", "реклама внутри тревожных сообщений запрещена правилами проекта"),
)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _hidden(token: str, **fields: str) -> str:
    parts = [f'<input type="hidden" name="csrf" value="{esc(token)}">']
    parts.extend(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in fields.items())
    return "".join(parts)


def _note(kind: str, text: str) -> str:
    if not text:
        return ""
    return f'<div class="card {"ok" if kind == "ok" else "bad"}">{esc(text)}</div>'


def _is_group_shown(group: str) -> bool:
    shown = set(ELSEWHERE_GROUPS)
    for section in SECTIONS:
        for card in section.cards:
            shown.update(card.groups)
    return group in shown or group.startswith("VPN")


def unplaced_groups() -> list[str]:
    """Группы значений без страницы — тест не даёт им появиться."""
    return [group for group in secrets.GROUPS if not _is_group_shown(group)]


def unplaced_flags() -> list[str]:
    placed = set(ELSEWHERE_FLAGS)
    for section in SECTIONS:
        for card in section.cards:
            placed.update(card.flags)
    return [flag.key for flag in features.FLAGS if flag.key not in placed and not flag.locked]


def _flag_rows(keys: tuple[str, ...], token: str, back: str) -> str:
    rows = []
    for key in keys:
        flag = features.resolve(key)
        if flag is None:
            continue
        on = features.enabled(key)
        state = '<span class="ok">включено</span>' if on else '<span class="muted">выключено</span>'
        if flag.locked:
            action = '<span class="muted">всегда включено</span>'
            state = ""
        else:
            word = "выключить" if on else "включить"
            action = ('<form method="post" action="/features/toggle">'
                      + _hidden(token, key=key, back=back)
                      + f'<button class="ghost" type="submit">{word}</button></form>')
        rows.append(f"<tr><td>{esc(flag.title)}<br>"
                    f'<span class="muted">{esc(flag.description)}</span></td>'
                    f"<td>{state}</td>"
                    f'<td style="text-align:right;width:1%">{action}</td></tr>')
    return f"<table>{''.join(rows)}</table>" if rows else ""


def _card_html(card: Card, token: str, back: str) -> str:
    from .panel import _setting_row

    body = []
    if card.note:
        body.append(f'<p class="muted">{esc(card.note)}</p>')
    body.append(_flag_rows(card.flags, token, back))
    for group in card.groups:
        for setting in secrets.SETTINGS:
            if setting.group == group:
                body.append(_setting_row(setting, token, back))
    if card.links:
        body.append("<p>" + " ".join(
            f'<a class="btn ghost" href="{esc(href)}">{esc(label)}</a>' for href, label in card.links)
            + "</p>")
    return f'<div class="card"><h3>{esc(card.title)}</h3>{"".join(body)}</div>'


def restart_card(token: str, can_restart: bool) -> str:
    """Что изменено и ждёт перезапуска. Пусто, если ничего."""
    if not secrets.PENDING_RESTART:
        return ""
    titles = []
    for key in sorted(secrets.PENDING_RESTART):
        setting = secrets.BY_KEY.get(key)
        titles.append(esc(setting.title if setting else key))
    listing = "; ".join(titles)
    if can_restart:
        action = ('<form method="post" action="/settings/restart" '
                  "onsubmit=\"return confirm('Бот перезапустится: несколько секунд он не ответит.')\">"
                  + _hidden(token) + '<button type="submit">Перезапустить бота</button></form>')
    else:
        action = ('<p class="muted">Доступа к docker из бота нет — перезапустите на сервере: '
                  "<code>docker compose restart</code>.</p>")
    return ('<div class="card warn"><b>Изменено и ждёт перезапуска:</b> '
            f"{listing}.{action}</div>")


def section_body(section: Section, token: str, message: str = "", failed: str = "",
                 can_restart: bool = False) -> str:
    parts = [_note("ok", message), _note("bad", failed), restart_card(token, can_restart),
             f'<p class="muted">{esc(section.intro)}</p>']
    parts.extend(_card_html(card, token, section.path) for card in section.cards)
    return "".join(parts)


def overview_body(token: str, message: str = "", failed: str = "",
                  can_restart: bool = False) -> str:
    parts = [_note("ok", message), _note("bad", failed), restart_card(token, can_restart)]
    tiles = []
    for section in SECTIONS:
        flags = [key for card in section.cards for key in card.flags if features.resolve(key)]
        on = sum(1 for key in flags if features.enabled(key))
        groups = {group for card in section.cards for group in card.groups}
        items = [s for s in secrets.SETTINGS if s.group in groups]
        filled = sum(1 for s in items if secrets.get(s.key))
        tiles.append(
            f'<div class="card"><h3><a href="{esc(section.path)}">{esc(section.title)}</a></h3>'
            f'<p class="muted">{esc(section.intro)}</p>'
            f"<p>Возможностей включено: <b>{on}</b> из {len(flags)} · "
            f"значений задано: <b>{filled}</b> из {len(items)}</p></div>")
    parts.append('<div class="grid">' + "".join(tiles) + "</div>")
    parts.append(
        '<div class="card"><h3>Другие разделы</h3><p>'
        '<a class="btn ghost" href="/vpn">VPN</a> '
        '<a class="btn ghost" href="/subscriptions">Подписка бота</a> '
        '<a class="btn ghost" href="/agents">Агенты ИИ</a> '
        '<a class="btn ghost" href="/features">Все возможности списком</a> '
        '<a class="btn ghost" href="/keys">Все значения списком</a></p></div>')
    rows = "".join(f"<tr><td><code>{esc(name)}</code></td><td>{esc(why)}</td></tr>"
                   for name, why in NOT_FROM_PANEL)
    parts.append('<details class="card"><summary><b>Что из панели не меняется — и почему</b></summary>'
                 f"<table>{rows}</table>"
                 '<p class="muted">Эти значения задаёт установщик при установке и переезде.</p></details>')
    return "".join(parts)
