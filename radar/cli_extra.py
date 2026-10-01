"""Консоль: проверка ссылок, cookies, история, события, облако, музыка,
чаты (ссылка, объявление, предупреждения) и короткие ссылки (с 5.9.10).

Последняя партия паритета с ботом и панелью. Как и прежние, зовёт те же
функции, что обработчики: разбор ссылок — `multitool.linkcheck`, cookies —
`radar.cookies`, облако — `radar.rclonerc`, объявления — `radar.chatpost`.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
from typing import Any

from . import cli
from .cli_admin import audit
from .cli_ops import _need_yes, _result, pairs
from .clitext import L
from .textutils import strip_tags

OK, FAILED, NEEDS_YES = cli.OK, cli.FAILED, cli.NEEDS_YES


# --------------------------------------------------------------------------
#  Проверка ссылки
# --------------------------------------------------------------------------

def cmd_check(args) -> int:
    """Та же проверка, что /check, без дневной квоты (консоль — владелец)."""
    from . import config, secrets

    async def run():
        from multitool.linkcheck.analyze import analyze
        from multitool.linkcheck.report import build_report

        verdict = analyze(args.url)
        if config.LINKCHECK_NET and not args.no_net:
            from multitool.linkcheck.netcheck import full_check

            key = (secrets.get("SAFE_BROWSING_API_KEY") or "").strip()
            try:
                verdict.net = await full_check(args.url, key)
            except Exception as exc:  # noqa: BLE001
                cli._err(L(f"Сетевая проверка не удалась: {exc}", f"Network check failed: {exc}"))
        report = strip_tags(build_report(verdict))
        cli._out({"url": args.url, "score": verdict.score, "report": report}, args.json,
                 lambda d: print(d["report"]))
        return OK

    return cli._run(run())


# --------------------------------------------------------------------------
#  Cookies
# --------------------------------------------------------------------------

def cmd_cookies(args) -> int:
    from . import cookies

    if args.action == "status":
        cli._out({"connected": cookies.connected(), "text": cookies.describe()}, args.json,
                 lambda d: print(d["text"]))
        return OK
    if not args.file:
        cli._err(L("cookies set ФАЙЛ (выгрузка Netscape)", "cookies set FILE (a Netscape export)"))
        return FAILED
    try:
        with open(args.file, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        cli._err(L(f"Файл не прочитан: {exc}", f"Could not read the file: {exc}"))
        return FAILED
    ok, note = cookies.store(data)
    if not ok:
        cli._err(L(f"Cookies не приняты: {note}", f"Cookies rejected: {note}"))
        return FAILED
    audit("cookies обновлены", f"{len(data)} байт")
    print(L("Файл cookies обновлён.", "The cookies file was updated."))
    return OK


# --------------------------------------------------------------------------
#  История и события
# --------------------------------------------------------------------------

def cmd_history(args) -> int:
    from .db import repo

    async def run():
        events = await repo.history(args.uid, days=args.days, limit=args.limit)
        rows = [{"when": e.created_at.strftime("%Y-%m-%d %H:%M"),
                 "categories": list(getattr(e, "categories", None) or []),
                 "summary": (getattr(e, "summary", "") or "").strip()} for e in events]
        cli._out(rows, args.json, lambda data: [
            print(f"{r['when']}  {','.join(r['categories']) or '-':<14} {r['summary'][:160]}")
            for r in data] or print(L(f"За {args.days} дн. ничего не приходило.",
                                      f"Nothing was sent in {args.days} days.")))
        return OK

    return cli._run(cli._with_storage(run))


def cmd_events(args) -> int:
    from .db import repo

    async def run():
        stats = await repo.event_stats(days=args.days)
        cli._out(stats, args.json, lambda d: print(
            L(f"За {args.days} дн.: событий {d['events']}, доставок {d['deliveries']}",
              f"In {args.days} days: events {d['events']}, deliveries {d['deliveries']}")))
        return OK

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  Музыка: расход по людям
# --------------------------------------------------------------------------

def cmd_music(args) -> int:
    from . import music, storage

    async def run():
        if args.action == "list":
            if not args.uid:
                cli._err(L("music list UID", "music list UID"))
                return FAILED
            user = storage.get_user(args.uid)
            if user is None:
                cli._err(L("Пользователь не найден.", "User not found."))
                return FAILED
            rows = [{"id": t.get("id"), "name": t.get("name"), "size": int(t.get("size") or 0)}
                    for t in music.tracks_of(user)]
            cli._out(rows, args.json, lambda data: [
                print(f"{r['id']}  {music.format_size(r['size']):>9}  {r['name']}")
                for r in data] or print(L("треков нет", "no tracks")))
            return OK

        rows, total_tracks, total_bytes = [], 0, 0
        for uid, user in storage.users().items():
            tracks = music.tracks_of(user)
            if not tracks:
                continue
            size = sum(int(t.get("size") or 0) for t in tracks)
            total_tracks += len(tracks)
            total_bytes += size
            rows.append({"uid": uid, "username": user.get("username", ""),
                         "tracks": len(tracks), "playlists": len(music.playlists_of(user)),
                         "bytes": size})
        payload = {"people": rows, "tracks": total_tracks, "bytes": total_bytes,
                   "cache_bytes": music.cache_size()}
        cli._out(payload, args.json, lambda d: (
            [print(f"{r['uid']:>14} {r['tracks']:>5} tr {music.format_size(r['bytes']):>9}  "
                   f"{r['username']}") for r in d["people"]],
            print(L(f"Всего: {d['tracks']} треков, {music.format_size(d['bytes'])}; "
                    f"кэш облака {music.format_size(d['cache_bytes'])}",
                    f"Total: {d['tracks']} tracks, {music.format_size(d['bytes'])}; "
                    f"cloud cache {music.format_size(d['cache_bytes'])}"))))
        return OK

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  Облако музыки (rclone)
# --------------------------------------------------------------------------

def cmd_cloud(args) -> int:
    from . import rclonerc

    async def run():
        action, items = args.action, args.items
        if action == "list":
            ok, data = await rclonerc.remotes()
            if not ok:
                cli._err(str(data))
                return FAILED
            names = list(data or [])
            cli._out(names, args.json, lambda d: [print(n) for n in d]
                     or print(L("хранилищ нет", "no remotes")))
            return OK
        if action == "check":
            ok, note = await rclonerc.check()
            cli._out({"ok": ok, "note": note}, args.json,
                     lambda d: print(f"{'OK' if d['ok'] else 'FAIL'}: {d['note']}"))
            return OK if ok else FAILED
        if action == "add":
            fields, bad = pairs(args.set)
            if bad or len(items) < 2:
                cli._err(bad or L("cloud add ИМЯ ВИД --set поле=значение …",
                                  "cloud add NAME KIND --set field=value …"))
                return FAILED
            ok, reason = await rclonerc.create(items[0], items[1], fields)
            if not ok:
                cli._err(reason)
                return FAILED
            audit("заведено облако", f"{items[0]} ({items[1]})")
            print(L(f"Хранилище «{items[0]}» заведено. Впишите имя в MUSIC_CLOUD_REMOTE "
                    "и перезапустите профиль cloud.",
                    f"Remote “{items[0]}” created. Put its name in MUSIC_CLOUD_REMOTE "
                    "and restart the cloud profile."))
            return OK
        # forget
        if not items:
            cli._err(L("cloud forget ИМЯ --yes", "cloud forget NAME --yes"))
            return FAILED
        if _need_yes(args, f"Запись о «{items[0]}» будет убрана (файлы в облаке останутся).",
                     f"The entry for “{items[0]}” will be removed (files in the cloud stay)."):
            return NEEDS_YES
        ok, reason = await rclonerc.forget(items[0])
        if not ok:
            cli._err(reason)
            return FAILED
        audit("убрано облако", items[0])
        print(L("Запись убрана.", "Entry removed."))
        return OK

    return cli._run(run())


# --------------------------------------------------------------------------
#  Чаты: ссылка, объявление, предупреждения; короткие ссылки
# --------------------------------------------------------------------------

async def chat_action(chat_id: int, args) -> int:
    from . import chatlink, chatpost, features
    from .db import repo

    rest = list(getattr(args, "rest", []) or [])

    if args.action == "invite":
        link = rest[0].strip() if rest else ""
        if link and not chatlink.valid_invite(link):
            cli._err(L("Нужен адрес вида https://t.me/…", "An address like https://t.me/… is required"))
            return FAILED
        if not await repo.chat_set_invite(chat_id, link):
            cli._err(L("Чат не найден.", "Chat not found."))
            return FAILED
        chatlink.forget(chat_id)
        await chatlink.refresh_published()
        audit("задана ссылка чата" if link else "снята ссылка чата", str(chat_id))
        print(L("Ссылка сохранена." if link else "Своя ссылка снята.",
                "Link saved." if link else "Custom link removed."))
        return OK

    if args.action == "warns":
        if not rest or not rest[0].lstrip("-").isdigit():
            cli._err(L("chats warns ЧАТ ПОЛЬЗОВАТЕЛЬ [--reset]", "chats warns CHAT USER [--reset]"))
            return FAILED
        user = int(rest[0])
        if getattr(args, "reset", False):
            await repo.warn_reset(chat_id, user)
            audit("предупреждения сброшены", f"{chat_id}:{user}")
        count = await repo.warn_count(chat_id, user)
        cli._out({"chat": chat_id, "user": user, "warnings": count}, args.json,
                 lambda d: print(L(f"Предупреждений: {d['warnings']}", f"Warnings: {d['warnings']}")))
        return OK

    # announce
    if not features.enabled("chat_post"):
        cli._err(L("Возможность «Сообщения в группы» выключена: features on chat_post.",
                   "The “Messages to groups” feature is off: features on chat_post."))
        return FAILED
    row = await repo.chat_get(chat_id)
    if row is None:
        cli._err(L("Чат не найден.", "Chat not found."))
        return FAILED
    text = " ".join(rest)
    ok, reason = chatpost.validate(text)
    if not ok:
        cli._err(reason)
        return FAILED
    draft = chatpost.Draft(chat_id=chat_id, title=row.get("title") or str(chat_id), text=text.strip())
    print(strip_tags(chatpost.preview(draft)))
    if not args.yes:
        cli._err(L("Ничего не отправлено. Повторите с --yes — объявление не отзывается.",
                   "Nothing sent. Repeat with --yes — an announcement cannot be recalled."))
        return NEEDS_YES
    if not cli.in_bot():
        cli._err(L("Отправка идёт через соединение бота с Telegram: запустите бота и повторите.",
                   "Sending goes through the bot's Telegram connection: start the bot and repeat."))
        return FAILED
    from .tg import bot

    try:
        await bot.send_message(chat_id, draft.text)
    except Exception as exc:  # noqa: BLE001
        audit("объявление не ушло", f"{chat_id}: {str(exc)[:60]}")
        cli._err(L(f"Не отправилось: {str(exc)[:120]}", f"Not sent: {str(exc)[:120]}"))
        return FAILED
    audit("объявление отправлено", f"{chat_id} ({len(draft.text)} знаков)")
    print(L("Отправлено.", "Sent."))
    return OK


async def short_add(url: str, as_json: bool) -> int:
    from . import shortener
    from .db import repo

    if not shortener.enabled():
        cli._err(L("Сокращение не настроено: задайте SHORT_BASE_URL.",
                   "Shortening is not configured: set SHORT_BASE_URL."))
        return FAILED
    if not shortener.valid(url):
        cli._err(L("Нужен полный адрес со схемой http:// или https://.",
                   "A full address with http:// or https:// is required."))
        return FAILED
    code = shortener.code_for(url)
    await repo.save_short_link(code, url, 0)
    audit("короткая ссылка создана", code)
    cli._out({"code": code, "short": shortener.short_url(code), "url": url}, as_json,
             lambda d: print(d["short"]))
    return OK


def register(subparsers, common) -> None:
    check_cmd = subparsers.add_parser("check", help=L("проверить ссылку на признаки мошенничества",
                                                      "check a link for scam signs"),
                                      parents=[common])
    check_cmd.add_argument("url")
    check_cmd.add_argument("--no-net", action="store_true",
                           help=L("только разбор адреса, без сети", "address analysis only, no network"))
    check_cmd.set_defaults(func=cmd_check)

    cookies_cmd = subparsers.add_parser("cookies", help=L("cookies для загрузки видео и музыки",
                                                          "cookies for video and music"),
                                        parents=[common])
    cookies_cmd.add_argument("action", choices=["status", "set"])
    cookies_cmd.add_argument("file", nargs="?", default="")
    cookies_cmd.set_defaults(func=cmd_cookies)

    history_cmd = subparsers.add_parser("history", help=L("что приходило человеку", "what a person received"),
                                        parents=[common])
    history_cmd.add_argument("uid")
    history_cmd.add_argument("--days", type=int, default=30)
    history_cmd.add_argument("--limit", type=int, default=20)
    history_cmd.set_defaults(func=cmd_history)

    events_cmd = subparsers.add_parser("events", help=L("события и доставки за период",
                                                        "events and deliveries over a period"),
                                       parents=[common])
    events_cmd.add_argument("--days", type=int, default=7)
    events_cmd.set_defaults(func=cmd_events)

    music_cmd = subparsers.add_parser("music", help=L("музыка: расход по людям", "music: usage per person"),
                                      parents=[common])
    music_cmd.add_argument("action", nargs="?", choices=["usage", "list"], default="usage")
    music_cmd.add_argument("uid", nargs="?", default="")
    music_cmd.set_defaults(func=cmd_music)

    cloud_cmd = subparsers.add_parser("cloud", help=L("облако музыки (rclone)", "music cloud (rclone)"),
                                      parents=[common])
    cloud_cmd.add_argument("action", choices=["list", "check", "add", "forget"])
    cloud_cmd.add_argument("items", nargs="*")
    cloud_cmd.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ")
    cloud_cmd.add_argument("--yes", action="store_true")
    cloud_cmd.set_defaults(func=cmd_cloud)
