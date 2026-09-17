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
import sys
from typing import Any, Callable

# Коды возврата: годится для cron и для скриптов.
OK = 0
FAILED = 1
NEEDS_YES = 2   # разрушающее действие без --yes


def _out(payload: Any, as_json: bool, plain: Callable[[Any], None]) -> None:
    """Вывод в двух видах. JSON — для скриптов, обычный — для человека."""
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        plain(payload)


async def _with_storage(action: Callable[[], Any]) -> Any:
    """Поднимает базу ровно настолько, насколько нужно для чтения.

    Схему не трогаем: её приводит в порядок бот при старте, и менять
    её из командной строки — способ получить расхождение между тем,
    что думает бот, и тем, что лежит на диске.
    """
    from . import storage
    from .db import engine as db_engine

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

def cmd_sources(args) -> int:
    from . import sourceedit as se

    kinds = (se.TELEGRAM, se.RSS, se.VK)

    async def run():
        if args.action == "list":
            data = {kind: se.listing(kind) for kind in kinds}
            _out(data, args.json, lambda d: [
                print(f"{kind}: {', '.join(items) or 'пусто'}")
                for kind, items in d.items()
            ])
            return OK

        if args.action == "add":
            added, skipped = se.add(args.kind, args.value)
            _out({"added": added, "skipped": skipped}, args.json, lambda d: print(
                f"добавлено: {', '.join(d['added']) or '—'}; "
                f"пропущено: {', '.join(d['skipped']) or '—'}"))
            return OK if added else FAILED

        removed = se.remove(args.kind, args.value)
        _out({"removed": removed}, args.json,
             lambda d: print("удалено" if d["removed"] else "не найдено"))
        return OK if removed else FAILED

    return asyncio.run(_with_storage(run))


# --------------------------------------------------------------------------
#  Пользователи
# --------------------------------------------------------------------------

def cmd_users(args) -> int:
    from . import roles, storage

    async def run():
        people = storage.users()
        rows = [
            {
                "key": key,
                "role": item.get("role", "user"),
                "locations": len(item.get("locations") or []),
            }
            for key, item in people.items()
        ]
        _out(rows, args.json, lambda data: [
            print(f"{row['key']:>12}  {roles.title(row['role']):<22} "
                  f"локаций: {row['locations']}")
            for row in data
        ])
        return OK

    return asyncio.run(_with_storage(run))


# --------------------------------------------------------------------------
#  Возможности
# --------------------------------------------------------------------------

def cmd_features(args) -> int:
    from . import features
    from .db import repo

    async def run():
        if args.action == "list":
            data = features.snapshot()
            _out(data, args.json, lambda d: [
                print(f"{'вкл ' if value else 'выкл'}  {key}")
                for key, value in sorted(d.items())
            ])
            return OK

        flag = features.resolve(args.key)
        if flag is None:
            print(f"Неизвестная возможность: {args.key}", file=sys.stderr)
            return FAILED
        if flag.locked:
            print(f"{flag.title} — ядро системы, выключить нельзя",
                  file=sys.stderr)
            return FAILED

        value = args.action == "on"
        # Ровно та же пара действий, что в обработчике панели: память
        # и база. Одной записи мало — переживёт только до перезапуска.
        features.set_local(flag.key, value)
        await repo.set_feature(flag.key, value, "командная строка")
        print(f"{flag.title}: {'включено' if value else 'выключено'}")
        return OK

    return asyncio.run(_with_storage(run))


# --------------------------------------------------------------------------
#  Ключи
# --------------------------------------------------------------------------

def cmd_keys(args) -> int:
    from . import secrets

    if args.action == "list":
        data = {
            group: [
                {"name": item.name, "value": secrets.display(item)}
                for item in items
            ]
            for group, items in secrets.by_group().items()
        }
        _out(data, args.json, lambda d: [
            print(f"[{group}] {item['name']}: {item['value']}")
            for group, items in d.items() for item in items
        ])
        return OK

    if not secrets.writable():
        print("Файл .env недоступен на запись", file=sys.stderr)
        return FAILED
    if not secrets.write(args.name, args.value):
        print(f"Не удалось записать {args.name}", file=sys.stderr)
        return FAILED
    print(f"{args.name}: записано ({secrets.mask(args.value)})")
    return OK


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
        ] or print("копий нет"))
        return OK

    path, error = backup.create_sync("командная строка")
    if error or path is None:
        print(f"Копия не создана: {error}", file=sys.stderr)
        return FAILED
    print(f"Копия создана: {path}")
    return OK


def cmd_db(args) -> int:
    from . import config, dbcare

    if args.action == "size":
        # Тот же источник пути, что у самого dbcare.vacuum_sqlite.
        size = dbcare.measure_sqlite(config.DB_FILE)
        payload = {"bytes": size, "human": dbcare.format_size(size)}
        _out(payload, args.json, lambda d: print(f"база: {d['human']}"))
        return OK

    if not args.yes:
        print("Уплотнение базы останавливает запись. Повторите с --yes.",
              file=sys.stderr)
        return NEEDS_YES

    before, after, note = asyncio.run(dbcare.vacuum_sqlite())
    payload = {"before": before, "after": after, "note": note}
    _out(payload, args.json, lambda d: print(
        f"{dbcare.format_size(d['before'])} → {dbcare.format_size(d['after'])}"
        f"  {d['note']}"))
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
        print("Будут удалены ВСЕ короткие ссылки. Повторите с --yes.",
              file=sys.stderr)
        return NEEDS_YES

    async def run():
        if args.action == "list":
            rows = await repo.short_link_list()
            _out(rows, args.json, lambda data: [
                print(f"{row.get('code')}  →  {row.get('url')}") for row in data
            ] or print("ссылок нет"))
            return OK

        if args.action == "remove":
            done = await repo.remove_short_link(args.code)
            print("удалено" if done else "не найдено")
            return OK if done else FAILED

        count = await repo.clear_short_links()
        print(f"удалено ссылок: {count}")
        return OK

    return asyncio.run(_with_storage(run))


def cmd_chats(args) -> int:
    """Чаты под модерацией. Те же данные, что показывает панель."""
    from .db import repo

    async def run():
        if args.action == "list":
            rows = await repo.chat_list()
            _out(rows, args.json, lambda data: [
                print(f"{row['chat_id']:>15}  "
                      f"{'вкл ' if row['enabled'] else 'выкл'}  "
                      f"{row['title'] or '—'}")
                for row in data
            ] or print("чатов нет"))
            return OK

        if not args.chat_id:
            print("Нужен идентификатор чата: radar chats on -100…",
                  file=sys.stderr)
            return FAILED

        chat_id = int(args.chat_id)
        if args.action == "forget":
            done = await repo.chat_forget(chat_id)
            print("забыт" if done else "такого чата нет")
            return OK if done else FAILED

        await repo.chat_save(chat_id, enabled=args.action == "on")
        print(f"{chat_id}: модерация "
              f"{'включена' if args.action == 'on' else 'выключена'}")
        return OK

    return asyncio.run(_with_storage(run))


def cmd_files(args) -> int:
    from . import filedrop

    rows = [{"token": drop.token, "name": drop.name} for drop in filedrop.listing()]
    _out(rows, args.json, lambda data: [
        print(f"{row['token']}  {row['name']}") for row in data
    ] or print("раздач нет"))
    return OK


# --------------------------------------------------------------------------
#  RustDesk
# --------------------------------------------------------------------------

def cmd_rustdesk(args) -> int:
    from . import rustdesk

    allowed, reason = rustdesk.ready()
    if not allowed:
        print(reason, file=sys.stderr)
        return FAILED

    if args.action == "info":
        ok, payload = rustdesk.client_info()
        if not ok:
            print(payload, file=sys.stderr)
            return FAILED
        _out(payload, args.json, lambda d: print(
            f"ID Server:    {d['host']}:{d['id_port']}\n"
            f"Relay Server: {d['host']}:{d['relay_port']}\n"
            f"Key:          {d['key']}"))
        return OK

    if args.action == "connections":
        ok, payload = asyncio.run(rustdesk.connection_counts())
        if not ok:
            print(payload, file=sys.stderr)
            return FAILED
        _out(payload, args.json, lambda d: print(
            f"hbbs: {d['hbbs']} онлайн, hbbr: {d['hbbr']} активных сессий"))
        return OK

    if args.action in ("stop", "restart") and not args.yes:
        print(f"Действие «{args.action}» прервёт подключения. "
              "Повторите с --yes.", file=sys.stderr)
        return NEEDS_YES

    ok, reason = asyncio.run(rustdesk.control(args.action))
    print(reason or "готово", file=sys.stderr if not ok else sys.stdout)
    return OK if ok else FAILED


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
        prog="radar", description="Управление «Радаром» из командной строки")
    parser.add_argument("--json", action="store_true",
                        help="машиночитаемый вывод")

    # --json принимается и до подкоманды, и после неё: писать
    # «radar --json version» помнит не каждый, а «radar version --json»
    # набирается само. SUPPRESS обязателен — без него флаг подкоманды
    # со своим значением по умолчанию затирал бы корневой.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        default=argparse.SUPPRESS,
                        help="машиночитаемый вывод")

    subparsers = parser.add_subparsers(dest="command", required=True,
                                       parser_class=argparse.ArgumentParser)

    sources = subparsers.add_parser("sources", help="источники", parents=[common])
    sources.add_argument("action", choices=["list", "add", "remove"])
    sources.add_argument("kind", nargs="?", default="",
                         help="telegram | rss | vk")
    sources.add_argument("value", nargs="?", default="")
    sources.set_defaults(func=cmd_sources)

    users = subparsers.add_parser("users", help="пользователи", parents=[common])
    users.add_argument("action", nargs="?", choices=["list"], default="list")
    users.set_defaults(func=cmd_users)

    feats = subparsers.add_parser("features", help="возможности", parents=[common])
    feats.add_argument("action", choices=["list", "on", "off"])
    feats.add_argument("key", nargs="?", default="")
    feats.set_defaults(func=cmd_features)

    keys = subparsers.add_parser("keys", help="ключи и токены", parents=[common])
    keys.add_argument("action", choices=["list", "set"])
    keys.add_argument("name", nargs="?", default="")
    keys.add_argument("value", nargs="?", default="")
    keys.set_defaults(func=cmd_keys)

    backup_cmd = subparsers.add_parser("backup", help="резервные копии", parents=[common])
    backup_cmd.add_argument("action", choices=["list", "create"])
    backup_cmd.set_defaults(func=cmd_backup)

    db_cmd = subparsers.add_parser("db", help="обслуживание базы", parents=[common])
    db_cmd.add_argument("action", choices=["size", "vacuum"])
    db_cmd.add_argument("--yes", action="store_true")
    db_cmd.set_defaults(func=cmd_db)

    links = subparsers.add_parser("links", help="короткие ссылки", parents=[common])
    links.add_argument("action", choices=["list", "remove", "clear"])
    links.add_argument("code", nargs="?", default="")
    links.add_argument("--yes", action="store_true")
    links.set_defaults(func=cmd_links)

    chats = subparsers.add_parser("chats", help="чаты под модерацией",
                                  parents=[common])
    chats.add_argument("action", choices=["list", "on", "off", "forget"])
    chats.add_argument("chat_id", nargs="?", default="")
    chats.set_defaults(func=cmd_chats)

    files = subparsers.add_parser("files", help="раздача файлов", parents=[common])
    files.add_argument("action", nargs="?", choices=["list"], default="list")
    files.set_defaults(func=cmd_files)

    rd = subparsers.add_parser("rustdesk", help="сервер удалённого доступа", parents=[common])
    rd.add_argument("action",
                    choices=["info", "connections", "start", "stop", "restart"])
    rd.add_argument("--yes", action="store_true")
    rd.set_defaults(func=cmd_rustdesk)

    doc = subparsers.add_parser("doctor", help="диагностика", parents=[common])
    doc.add_argument("--quick", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    ver = subparsers.add_parser("version", help="версия", parents=[common])
    ver.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return FAILED
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    sys.exit(main())
