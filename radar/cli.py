"""Командная строка: то же, что умеет веб-панель, только из консоли.

Зачем. Панель требует браузера, входа через Telegram и живого домена.
Когда нужно посмотреть источники по ssh, включить возможность из скрипта
или снять копию по расписанию, всё это лишнее — а половина действий
панели к интерфейсу отношения не имеет.

Правило одно: подкоманды зовут ТЕ ЖЕ функции, что и обработчики панели.
Никакой второй реализации — иначе два места начнут расходиться, и хуже
всего это проявится там, где расхождение незаметно: в правах и в записи
на диск.

Запуск внутри контейнера бота:
    python -m radar.cli sources list
    python -m radar.cli features on digest
    python -m radar.cli backup create --yes

Снаружи, с хоста, — через обёртку: bash radarctl.sh …

С 5.9.3 команды выполняет сам работающий бот (см. `adminsock`), а с 5.9.3.1
консоль говорит по-русски и по-английски (`--lang`, см. `clitext`).
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Callable

from .clitext import L

# Коды возврата: годится для cron и для скриптов.
OK = 0
FAILED = 1
NEEDS_YES = 2   # разрушающее действие без --yes


# Цикл событий бота, пока команду выполняет он сам (см. adminsock).
# None — обычный запуск из консоли.
_LOOP: asyncio.AbstractEventLoop | None = None

# Команды, которым бот не нужен: они диагностируют окружение.
LOCAL_ONLY = {"doctor", "version"}
# Что только читает: для них молчание о неработающем боте не страшно.
READ_ACTIONS = {"list", "size", "check", "info", "connections", "show", "get",
                "tail", "pending", "stale", "codes", "panels", "access", "orders",
                "export", "panel-check", "status", "models", "health", "agents", "usage",
                "warns"}


def attach(loop: asyncio.AbstractEventLoop | None) -> None:
    global _LOOP
    _LOOP = loop


def in_bot() -> bool:
    """Выполняется ли команда внутри работающего бота."""
    return _LOOP is not None


def _run(coro: Any) -> Any:
    """asyncio.run для консоли и вызов в цикле бота — изнутри бота."""
    if _LOOP is not None:
        return asyncio.run_coroutine_threadsafe(coro, _LOOP).result()
    return asyncio.run(coro)


def _out(payload: Any, as_json: bool, plain: Callable[[Any], None]) -> None:
    """Вывод в двух видах. JSON — для скриптов, обычный — для человека."""
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        plain(payload)


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _audit(action: str, detail: str = "") -> None:
    """Запись в журнал действий — как делает панель."""
    from .cli_admin import audit

    audit(action, detail)


async def _with_storage(action: Callable[[], Any]) -> Any:
    """Поднимает базу ровно настолько, насколько нужно для чтения.

    Схему не трогаем: её приводит в порядок бот при старте, и менять
    её из командной строки — способ получить расхождение между тем,
    что думает бот, и тем, что лежит на диске.
    """
    from . import storage
    from .db import engine as db_engine

    if _LOOP is not None:
        # Внутри бота база уже поднята, а память — та самая, что видят
        # пользователи. Загрузка с диска затёрла бы несохранённое,
        # а закрытие движка оставило бы бота без базы.
        result = action()
        if asyncio.iscoroutine(result):
            result = await result
        return result

    await db_engine.wait_ready()
    await storage.load()
    try:
        result = action()
        if asyncio.iscoroutine(result):
            result = await result
        return result
    finally:
        await db_engine.dispose()


# --------------------------------------------------------------------------
#  Источники
# --------------------------------------------------------------------------

def _prune_sources(args) -> int:
    """Проверка источников и удаление молчащих (с 5.9.2.1).

    Без --yes только показывает, что было бы удалено: список источников
    нельзя вернуть одной командой.
    """
    from . import sourcecheck, sourceedit as se, sourceprune, storage

    async def run():
        channels, feeds = se.listing(se.TELEGRAM), se.listing(se.RSS)
        if not channels and not feeds:
            _err(L("Источников нет.", "No sources."))
            return FAILED
        _err(L(f"Проверяю: каналов {len(channels)}, лент {len(feeds)} "
               f"(пауза {args.pause} с — это займёт время)",
               f"Checking: {len(channels)} channels, {len(feeds)} feeds "
               f"(pause {args.pause} s — this takes a while)"))
        report = await sourcecheck.check_all(channels, feeds, pause=args.pause)

        chosen = sourceprune.select(report, args.days, dead=args.dead)
        doubt = sourceprune.suspicious(report)
        payload = {
            "checked": report.total, "alive": len(report.alive),
            "stale": len(report.stale), "dead": len(report.dead),
            "candidates": [{"kind": c.kind, "ref": c.ref, "reason": c.reason}
                           for c in chosen],
            "removed": [], "warning": doubt,
        }

        def show(d):
            print(L(f"Проверено {d['checked']}: живых {d['alive']}, затихших "
                    f"{d['stale']}, недоступных {d['dead']}.",
                    f"Checked {d['checked']}: alive {d['alive']}, quiet "
                    f"{d['stale']}, unreachable {d['dead']}."))
            for item in d["candidates"]:
                print(f"  ✗ {item['kind']} {item['ref']} — {item['reason']}")
            if not d["candidates"]:
                print(L("Молчащих источников нет.", "No silent sources."))
            if d["warning"]:
                print("⚠️ " + d["warning"])

        if doubt and not args.force:
            _out(payload, args.json, show)
            _err(L("Удаление отменено. Если уверены — повторите с --force.",
                   "Removal cancelled. If you are sure, repeat with --force."))
            return FAILED
        if not chosen:
            _out(payload, args.json, show)
            return OK
        if not args.yes:
            _out(payload, args.json, show)
            _err(L(f"Ничего не удалено. Убрать {len(chosen)} — повторите с --yes.",
                   f"Nothing removed. To remove {len(chosen)}, repeat with --yes."))
            return NEEDS_YES

        removed = sourceprune.apply(chosen)
        await storage.save()
        _audit("источники убраны", str(len(removed)))
        payload["removed"] = [{"kind": c.kind, "ref": c.ref} for c in removed]
        _out(payload, args.json, lambda d: (
            show(d), print(L(f"Удалено: {len(d['removed'])}.",
                             f"Removed: {len(d['removed'])}."))))
        return OK

    return _run(_with_storage(run))


def cmd_sources(args) -> int:
    from . import sourceedit as se

    if args.action == "prune":
        return _prune_sources(args)

    kinds = (se.TELEGRAM, se.RSS, se.VK)
    # «telegram» в справке, «tg» в коде: принимаем оба, а не молча ничего
    # не находим (до 5.9.2.1 «sources add telegram …» не делало ничего).
    if args.kind == "telegram":
        args.kind = se.TELEGRAM

    async def run():
        from . import storage

        if args.action == "list":
            data = {kind: se.listing(kind) for kind in kinds}
            empty = L("пусто", "empty")
            _out(data, args.json, lambda d: [
                print(f"{kind}: {', '.join(items) or empty}")
                for kind, items in d.items()
            ])
            return OK

        if args.action == "add":
            added, skipped = se.add(args.kind, args.value)
            # Без сохранения правка жила только в памяти процесса и пропадала
            # при выходе (до 5.9.2.1).
            await storage.save()
            _audit("источник добавлен", f"{args.kind} {', '.join(added)}")
            _out({"added": added, "skipped": skipped}, args.json, lambda d: print(
                L(f"добавлено: {', '.join(d['added']) or '—'}; "
                  f"пропущено: {', '.join(d['skipped']) or '—'}",
                  f"added: {', '.join(d['added']) or '—'}; "
                  f"skipped: {', '.join(d['skipped']) or '—'}")))
            return OK if added else FAILED

        removed = se.remove(args.kind, args.value)
        await storage.save()
        _audit("источник удалён", f"{args.kind} {args.value}")
        _out({"removed": removed}, args.json,
             lambda d: print(L("удалено", "removed") if d["removed"]
                             else L("не найдено", "not found")))
        return OK if removed else FAILED

    return _run(_with_storage(run))


# --------------------------------------------------------------------------
#  Возможности
# --------------------------------------------------------------------------

def cmd_features(args) -> int:
    from . import features
    from .db import repo

    async def run():
        if args.action == "list":
            data = features.snapshot()
            on, off = L("вкл ", "on  "), L("выкл", "off ")
            _out(data, args.json, lambda d: [
                print(f"{on if value else off}  {key}")
                for key, value in sorted(d.items())
            ])
            return OK

        flag = features.resolve(args.key)
        if flag is None:
            _err(L(f"Неизвестная возможность: {args.key}",
                   f"Unknown feature: {args.key}"))
            return FAILED
        if flag.locked:
            _err(L(f"{flag.title} — ядро системы, выключить нельзя",
                   f"{flag.title} is part of the core and cannot be switched off"))
            return FAILED

        value = args.action == "on"
        # Ровно та же пара действий, что в обработчике панели: память
        # и база. Одной записи мало — переживёт только до перезапуска.
        features.set_local(flag.key, value)
        await repo.set_feature(flag.key, value, "командная строка")
        _audit("возможность включена" if value else "возможность выключена", flag.key)
        print(f"{flag.title}: " + (L("включено", "enabled") if value
                                   else L("выключено", "disabled")))
        return OK

    return _run(_with_storage(run))


# --------------------------------------------------------------------------
#  Копии и база
# --------------------------------------------------------------------------

def cmd_backup(args) -> int:
    from . import backup

    if args.action == "list":
        rows = [{"name": item.name, "when": item.when, "size": item.size_human}
                for item in backup.listing()]
        _out(rows, args.json, lambda data: [
            print(f"{row['when']}  {row['name']}  {row['size']}")
            for row in data
        ] or print(L("копий нет", "no backups")))
        return OK

    path, error = backup.create_sync("командная строка")
    if error or path is None:
        _err(L(f"Копия не создана: {error}", f"Backup not created: {error}"))
        return FAILED
    _audit("копия создана", str(path))
    print(L(f"Копия создана: {path}", f"Backup created: {path}"))
    return OK


def cmd_db(args) -> int:
    from . import config, dbcare

    if args.action == "copy":
        return _db_copy(args)

    if args.action == "size":
        # Тот же источник пути, что у самого dbcare.vacuum_sqlite.
        size = dbcare.measure_sqlite(config.DB_FILE)
        payload = {"bytes": size, "human": dbcare.format_size(size)}
        _out(payload, args.json, lambda d: print(L(f"база: {d['human']}",
                                                   f"database: {d['human']}")))
        return OK

    if not args.yes:
        _err(L("Уплотнение базы останавливает запись. Повторите с --yes.",
               "Vacuuming the database pauses writes. Repeat with --yes."))
        return NEEDS_YES

    before, after, note = _run(dbcare.vacuum_sqlite())
    payload = {"before": before, "after": after, "note": note}
    _out(payload, args.json, lambda d: print(
        f"{dbcare.format_size(d['before'])} → {dbcare.format_size(d['after'])}"
        f"  {d['note']}"))
    return OK


def _db_copy(args) -> int:
    """Перенос данных между SQLite и PostgreSQL (5.9): `db copy --from sqlite
    --to postgres` и обратно. Цель должна быть пустой; `--replace` заменяет
    её содержимое и, как любое необратимое действие, требует `--yes`."""
    from .db import transfer

    if not args.source or not args.target:
        _err(L("Укажите --from и --to: sqlite или postgres.",
               "Specify --from and --to: sqlite or postgres."))
        return FAILED
    if args.replace and not args.yes:
        _err(L("--replace сотрёт данные в целевой базе. Повторите с --yes.",
               "--replace will erase the target database. Repeat with --yes."))
        return NEEDS_YES
    try:
        source, target = transfer.url_for(args.source), transfer.url_for(args.target)
        copied = _run(transfer.copy(source, target, replace=args.replace))
    except transfer.TransferError as exc:
        _err(L(f"Перенос не выполнен: {exc}", f"Transfer failed: {exc}"))
        return FAILED
    _out(copied, args.json, lambda d: print(
        L("Перенесено: ", "Copied: ") + ", ".join(f"{k} {v}" for k, v in d.items() if v)))
    return OK


# --------------------------------------------------------------------------
#  Ссылки и файлы
# --------------------------------------------------------------------------

def cmd_links(args) -> int:
    from .db import repo

    # Отказ по подтверждению — до всякой базы. Иначе на машине без
    # поднятой базы «забыл --yes» выглядело бы как поломка: код 1
    # вместо 2, и cron не отличил бы одно от другого.
    if args.action == "clear" and not args.yes:
        _err(L("Будут удалены ВСЕ короткие ссылки. Повторите с --yes.",
               "ALL short links will be deleted. Repeat with --yes."))
        return NEEDS_YES

    async def run():
        if args.action == "add":
            from . import cli_extra

            return await cli_extra.short_add(args.code, args.json)

        if args.action == "list":
            rows = await repo.short_link_list()
            _out(rows, args.json, lambda data: [
                print(f"{row.get('code')}  →  {row.get('url')}") for row in data
            ] or print(L("ссылок нет", "no links")))
            return OK

        if args.action == "remove":
            done = await repo.remove_short_link(args.code)
            _audit("короткая ссылка удалена", args.code)
            print(L("удалено", "removed") if done else L("не найдено", "not found"))
            return OK if done else FAILED

        count = await repo.clear_short_links()
        _audit("короткие ссылки очищены", str(count))
        print(L(f"удалено ссылок: {count}", f"links removed: {count}"))
        return OK

    return _run(_with_storage(run))


def cmd_chats(args) -> int:
    """Чаты под модерацией. Те же данные, что показывает панель."""
    from .db import repo

    async def run():
        if args.action == "list":
            rows = await repo.chat_list()
            on, off = L("вкл ", "on  "), L("выкл", "off ")
            _out(rows, args.json, lambda data: [
                print(f"{row['chat_id']:>15}  "
                      f"{on if row['enabled'] else off}  "
                      f"{row['title'] or '—'}")
                for row in data
            ] or print(L("чатов нет", "no chats")))
            return OK

        if not args.chat_id:
            _err(L("Нужен идентификатор чата: radar chats on -100…",
                   "A chat id is required: radar chats on -100…"))
            return FAILED

        chat_id = int(args.chat_id)
        if args.action == "clean":
            return await _clean_deleted(chat_id, args)
        if args.action in ("invite", "announce", "warns"):
            from . import cli_extra

            return await cli_extra.chat_action(chat_id, args)
        if args.action == "forget":
            done = await repo.chat_forget(chat_id)
            print(L("забыт", "forgotten") if done
                  else L("такого чата нет", "no such chat"))
            return OK if done else FAILED

        await repo.chat_save(chat_id, enabled=args.action == "on")
        _audit("модерация чата " + ("включена" if args.action == "on" else "выключена"),
               str(chat_id))
        print(f"{chat_id}: " + (
            L("модерация включена", "moderation enabled") if args.action == "on"
            else L("модерация выключена", "moderation disabled")))
        return OK

    return _run(_with_storage(run))


async def _clean_deleted(chat_id: int, args) -> int:
    """Чистка удалённых аккаунтов в группе (5.9.4): как /cleandeleted.

    Нужен работающий бот: проверка идёт через его Bot API, а известных
    участников бот копит сам, пока работает.
    """
    from . import accounts, features
    from .db import repo

    if not in_bot():
        _err(L("Нужен работающий бот: проверка идёт через его соединение "
               "с Telegram. Запустите бота и повторите.",
               "A running bot is required: the check goes through its Telegram "
               "connection. Start the bot and repeat."))
        return FAILED
    if not features.enabled("deleted_cleanup"):
        _err(L("Возможность «Чистка удалённых аккаунтов» выключена: "
               "features on deleted_cleanup.",
               "The “Deleted account cleanup” feature is off: "
               "features on deleted_cleanup."))
        return FAILED
    from .tg import bot

    ids = await repo.member_ids(chat_id)
    if not ids:
        _err(L("Бот пока не видел в этом чате ни одного участника.",
               "The bot has not seen any members in this chat yet."))
        return FAILED
    scan = await accounts.scan_chat(bot, chat_id, ids)
    payload = {"chat": chat_id, "known": scan.known, "members": scan.members_total,
               "checked": scan.checked, "failed": scan.failed,
               "deleted": scan.deleted, "removed": 0}

    def show(d):
        print(L(f"Известно участников: {scan.coverage}; проверено {d['checked']}, "
                f"не удалось {d['failed']}; удалённых: {len(d['deleted'])}.",
                f"Known members: {scan.coverage}; checked {d['checked']}, "
                f"failed {d['failed']}; deleted: {len(d['deleted'])}."))
        if d["removed"]:
            print(L(f"Исключено: {d['removed']}.", f"Removed: {d['removed']}."))

    if not scan.deleted:
        _out(payload, args.json, show)
        return OK
    if not args.yes:
        _out(payload, args.json, show)
        _err(L(f"Ничего не исключено. Убрать {len(scan.deleted)} — повторите с --yes.",
               f"Nothing removed. To remove {len(scan.deleted)}, repeat with --yes."))
        return NEEDS_YES
    payload["removed"] = await accounts.remove_deleted(bot, chat_id, scan.deleted)
    _audit("удалённые аккаунты исключены", f"{chat_id}: {payload['removed']}")
    _out(payload, args.json, show)
    return OK


def cmd_files(args) -> int:
    from . import filedrop

    if args.action == "remove":
        from . import cli_ops

        return cli_ops.files_remove(args)

    rows = [{"token": drop.token, "name": drop.name} for drop in filedrop.listing()]
    _out(rows, args.json, lambda data: [
        print(f"{row['token']}  {row['name']}") for row in data
    ] or print(L("раздач нет", "no shared files")))
    return OK


# --------------------------------------------------------------------------
#  RustDesk
# --------------------------------------------------------------------------

def cmd_rustdesk(args) -> int:
    from . import rustdesk

    allowed, reason = rustdesk.ready()
    if not allowed:
        _err(reason)
        return FAILED

    if args.action == "info":
        ok, payload = rustdesk.client_info()
        if not ok:
            _err(payload)
            return FAILED
        _out(payload, args.json, lambda d: print(
            f"ID Server:    {d['host']}:{d['id_port']}\n"
            f"Relay Server: {d['host']}:{d['relay_port']}\n"
            f"Key:          {d['key']}"))
        return OK

    if args.action == "connections":
        ok, payload = _run(rustdesk.connection_counts())
        if not ok:
            _err(payload)
            return FAILED
        _out(payload, args.json, lambda d: print(
            L(f"hbbs: {d['hbbs']} онлайн, hbbr: {d['hbbr']} активных сессий",
              f"hbbs: {d['hbbs']} online, hbbr: {d['hbbr']} active sessions")))
        return OK

    if args.action in ("stop", "restart") and not args.yes:
        _err(L(f"Действие «{args.action}» прервёт подключения. Повторите с --yes.",
               f"“{args.action}” will drop connections. Repeat with --yes."))
        return NEEDS_YES

    ok, reason = _run(rustdesk.control(args.action))
    print(reason or L("готово", "done"), file=sys.stderr if not ok else sys.stdout)
    return OK if ok else FAILED


# --------------------------------------------------------------------------
#  VPN (с 5.0.1)
# --------------------------------------------------------------------------

def cmd_vpn(args) -> int:
    """Проверка VPN-панелей на сервере — живая, в отличие от тестов.

    `check` только читает. `selftest` пишет в панели: заводит на каждой
    запись radar_selftest, проходит полный круг и оставляет её выключенной.
    Поэтому он — только с --yes.
    """
    from . import cli_ops, vpn

    if args.action in cli_ops.VPN_ADMIN:
        return cli_ops.vpn_admin(args)

    if not vpn.slots():
        wrong = vpn.unknown_kinds()
        _err((L("Незнакомый вид панели: ", "Unknown panel kind: ") + ", ".join(wrong))
             if wrong else L("Ни одна панель не настроена (VPN1_KIND …).",
                             "No panel is configured (VPN1_KIND …)."))
        return FAILED
    if args.action == "selftest" and not args.yes:
        _err(L("selftest заведёт в каждой панели запись radar_selftest и оставит "
               "её выключенной. Повторите с --yes.",
               "selftest creates a radar_selftest entry on every panel and leaves "
               "it disabled. Repeat with --yes."))
        return NEEDS_YES

    titles = {item.key: f"{item.title} ({item.client.kind})" for item in vpn.slots()}
    runner = vpn.check_all if args.action == "check" else vpn.selftest_all
    results = _run(runner())
    payload = {titles.get(key, key): {"ok": ok, "note": note}
               for key, (ok, note) in sorted(results.items(), key=lambda i: int(i[0]))}
    _out(payload, args.json, lambda d: [
        print(f"{'OK  ' if v['ok'] else 'FAIL'} {k}: {v['note']}") for k, v in d.items()])
    return OK if all(ok for ok, _ in results.values()) else FAILED


def cmd_doctor(args) -> int:
    from . import doctor

    sys.argv = ["radar.doctor"] + (["--quick"] if args.quick else []) \
        + (["--json"] if args.json else [])
    return doctor.main()


def cmd_version(args) -> int:
    from . import __version__

    _out({"version": __version__}, args.json, lambda d: print(d["version"]))
    return OK


# --------------------------------------------------------------------------
#  Разбор аргументов
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description=L("Управление «Радаром» из командной строки",
                      "Manage Radar from the command line"))
    parser.add_argument("--json", action="store_true",
                        help=L("машиночитаемый вывод", "machine-readable output"))
    parser.add_argument("--local", action="store_true",
                        help=L("не обращаться к работающему боту, работать с базой напрямую",
                               "do not contact the running bot, work on the database directly"))
    parser.add_argument("--lang", choices=("ru", "en"), default=argparse.SUPPRESS,
                        help=L("язык вывода (по умолчанию — из RADAR_LANG/LANG, иначе русский)",
                               "output language (default: from RADAR_LANG/LANG, else Russian)"))

    # --json принимается и до подкоманды, и после неё: писать
    # «radar --json version» помнит не каждый, а «radar version --json»
    # набирается само. SUPPRESS обязателен — без него флаг подкоманды
    # со своим значением по умолчанию затирал бы корневой.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS,
                        help=L("машиночитаемый вывод", "machine-readable output"))

    subparsers = parser.add_subparsers(dest="command", required=True,
                                       parser_class=argparse.ArgumentParser)

    sources = subparsers.add_parser("sources", help=L("источники", "sources"),
                                    parents=[common])
    sources.add_argument("action", choices=["list", "add", "remove", "prune"],
                         help=L("prune — проверить и убрать молчащие (без --yes только показать)",
                                "prune — check and remove silent ones (without --yes only shows)"))
    sources.add_argument("kind", nargs="?", default="",
                         help="telegram (tg) | rss | vk")
    sources.add_argument("value", nargs="?", default="")
    sources.add_argument("--days", type=int, default=30,
                         help=L("prune: молчит дольше стольких дней (по умолчанию 30)",
                                "prune: silent for more than this many days (default 30)"))
    sources.add_argument("--dead", action="store_true",
                         help=L("prune: убирать и недоступные, не только молчащие",
                                "prune: also remove unreachable ones, not only silent"))
    sources.add_argument("--yes", action="store_true",
                         help=L("prune: действительно удалить", "prune: really delete"))
    sources.add_argument("--force", action="store_true",
                         help=L("prune: удалять, даже если недоступна большая часть списка",
                                "prune: delete even if most of the list is unreachable"))
    sources.add_argument("--pause", type=float, default=0.8,
                         help=L("prune: пауза между запросами, секунд",
                                "prune: pause between requests, seconds"))
    sources.set_defaults(func=cmd_sources)

    feats = subparsers.add_parser("features", help=L("возможности", "features"),
                                  parents=[common])
    feats.add_argument("action", choices=["list", "on", "off"])
    feats.add_argument("key", nargs="?", default="")
    feats.set_defaults(func=cmd_features)

    backup_cmd = subparsers.add_parser("backup", help=L("резервные копии", "backups"),
                                       parents=[common])
    backup_cmd.add_argument("action", choices=["list", "create"])
    backup_cmd.set_defaults(func=cmd_backup)

    db_cmd = subparsers.add_parser("db", help=L("обслуживание базы", "database upkeep"),
                                   parents=[common])
    db_cmd.add_argument("action", choices=["size", "vacuum", "copy"])
    db_cmd.add_argument("--yes", action="store_true")
    db_cmd.add_argument("--from", dest="source", default="",
                        help=L("откуда переносить: sqlite или postgres (db copy)",
                               "copy from: sqlite or postgres (db copy)"))
    db_cmd.add_argument("--to", dest="target", default="",
                        help=L("куда переносить: sqlite или postgres (db copy)",
                               "copy to: sqlite or postgres (db copy)"))
    db_cmd.add_argument("--replace", action="store_true",
                        help=L("заменить непустую целевую базу (с --yes)",
                               "replace a non-empty target database (with --yes)"))
    db_cmd.set_defaults(func=cmd_db)

    links = subparsers.add_parser("links", help=L("короткие ссылки", "short links"),
                                  parents=[common])
    links.add_argument("action", choices=["list", "remove", "clear", "add"],
                       help=L("add АДРЕС — создать короткую ссылку", "add URL — create a short link"))
    links.add_argument("code", nargs="?", default="")
    links.add_argument("--yes", action="store_true")
    links.set_defaults(func=cmd_links)

    chats = subparsers.add_parser("chats", help=L("чаты под модерацией",
                                                  "moderated chats"),
                                  parents=[common])
    chats.add_argument("action", choices=["list", "on", "off", "forget", "clean", "invite",
                                          "announce", "warns"],
                       help=L("clean — удалённые аккаунты; invite ЧАТ [ССЫЛКА] — своя ссылка "
                              "приглашения; announce ЧАТ ТЕКСТ — объявление от имени бота; "
                              "warns ЧАТ ПОЛЬЗОВАТЕЛЬ — счётчик предупреждений",
                              "clean — deleted accounts; invite CHAT [LINK] — a custom invite "
                              "link; announce CHAT TEXT — an announcement in the bot's name; "
                              "warns CHAT USER — the warning counter"))
    chats.add_argument("chat_id", nargs="?", default="")
    chats.add_argument("rest", nargs="*", help=L("ссылка, текст или пользователь",
                                                  "link, text or user"))
    chats.add_argument("--reset", action="store_true", help=L("warns: сбросить счётчик",
                                                              "warns: reset the counter"))
    chats.add_argument("--yes", action="store_true")
    chats.set_defaults(func=cmd_chats)

    files = subparsers.add_parser("files", help=L("раздача файлов", "file sharing"),
                                  parents=[common])
    files.add_argument("action", nargs="?", choices=["list", "remove"], default="list")
    files.add_argument("token", nargs="?", default="")
    files.add_argument("--yes", action="store_true")
    files.set_defaults(func=cmd_files)

    rd = subparsers.add_parser("rustdesk",
                               help=L("сервер удалённого доступа", "remote access server"),
                               parents=[common])
    rd.add_argument("action",
                    choices=["info", "connections", "start", "stop", "restart"])
    rd.add_argument("--yes", action="store_true")
    rd.set_defaults(func=cmd_rustdesk)

    vpn_cmd = subparsers.add_parser(
        "vpn", help=L("VPN-панели: проверка и полный круг", "VPN panels: check and full cycle"),
        parents=[common])
    from . import cli_ops

    vpn_cmd.add_argument(
        "action", choices=["check", "selftest", *cli_ops.VPN_ADMIN],
        help=L("check/selftest — проверка; panels, panel-save, panel-remove, panel-check — "
               "панели; access, issue, deny, extend, on, off, revoke — доступы; orders, "
               "order-confirm, order-retry, order-cancel — заказы; app-revoke — устройства "
               "приложений",
               "check/selftest — verification; panels, panel-save, panel-remove, panel-check — "
               "panels; access, issue, deny, extend, on, off, revoke — access; orders, "
               "order-confirm, order-retry, order-cancel — orders; app-revoke — app devices"))
    vpn_cmd.add_argument("items", nargs="*", help=L("аргументы действия (UID, слот, дни, заказ)",
                                                     "action arguments (UID, slot, days, order)"))
    vpn_cmd.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                         help=L("panel-save: поле слота (KIND, TITLE, URL, TOKEN, USER, PASS, "
                                "INBOUND, SUB_URL, GROUPS, CERT)",
                                "panel-save: a slot field (KIND, TITLE, URL, TOKEN, USER, PASS, "
                                "INBOUND, SUB_URL, GROUPS, CERT)"))
    vpn_cmd.add_argument("--slot", action="append", default=[],
                         help=L("issue: номер панели (можно несколько)",
                                "issue: a panel number (repeatable)"))
    vpn_cmd.add_argument("--device", default="", help=L("app-revoke: id устройства",
                                                         "app-revoke: device id"))
    vpn_cmd.add_argument("--yes", action="store_true")
    vpn_cmd.set_defaults(func=cmd_vpn)

    doc = subparsers.add_parser("doctor", help=L("диагностика", "diagnostics"),
                                parents=[common])
    doc.add_argument("--quick", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    ver = subparsers.add_parser("version", help=L("версия", "version"), parents=[common])
    ver.set_defaults(func=cmd_version)

    # Остальные области — в отдельном модуле, чтобы этот не рос бесконечно.
    from . import cli_admin

    cli_admin.register(subparsers, common)

    from . import cli_ops as _ops

    _ops.register(subparsers, common)

    from . import cli_ai as _ai

    _ai.register(subparsers, common)

    from . import cli_extra as _extra

    _extra.register(subparsers, common)

    return parser


def _via_bot(args) -> bool:
    if _LOOP is not None or getattr(args, "local", False):
        return False
    if os.getenv("RADAR_CLI_LOCAL"):
        return False
    if args.command in LOCAL_ONLY:
        return False
    # Перенос между базами поднимает собственные подключения.
    return not (args.command == "db" and args.action == "copy")


def main(argv: list[str] | None = None) -> int:
    from . import clitext

    raw = list(sys.argv[1:] if argv is None else argv)
    clitext.set_lang(clitext.detect(raw))
    parser = build_parser()
    args = parser.parse_args(raw)
    if _via_bot(args):
        from . import adminsock

        # Язык оператора передаётся явно: окружение бота — не его.
        reply = adminsock.call(["--lang", clitext.current()] + raw)
        if reply is not None:
            code, out, err = reply
            sys.stdout.write(out)
            sys.stderr.write(err)
            return code
        if getattr(args, "action", "list") not in READ_ACTIONS:
            _err(L("Бот не запущен — правка пойдёт прямо в базу и подхватится "
                   "при его запуске.",
                   "The bot is not running — the change goes straight to the "
                   "database and is picked up at its start."))
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return FAILED
    except Exception as exc:  # noqa: BLE001
        _err(L(f"Ошибка: {exc}", f"Error: {exc}"))
        return FAILED


if __name__ == "__main__":
    sys.exit(main())
