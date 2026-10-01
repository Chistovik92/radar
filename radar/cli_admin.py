"""Команды консоли для пользователей, ключей, журналов и статистики (с 5.9.3.1).

Продолжение `radar.cli`: тот же принцип — подкоманды зовут те же функции,
что обработчики бота и панели (`roles`, `storage`, `secrets`, `logs`,
`audit`), а не повторяют их логику. Права: консоль на сервере — это
владелец установки, то есть суперадминистратор; но правила ролей остаются
теми же, что в боте: суперадминистратора изменить нельзя никому,
а сам для себя консоль «пользователем» не является.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
from typing import Any

from . import cli
from .clitext import L

OK, FAILED, NEEDS_YES = cli.OK, cli.FAILED, cli.NEEDS_YES

# Кто записан в журнал действий, когда правку сделала консоль.
ACTOR = "консоль"
ACTOR_EN = "console"
# Роль консоли для проверок прав — как у владельца установки.
CONSOLE_ROLE = "superadmin"


def audit(action: str, detail: str = "") -> None:
    """Запись в журнал действий — тот же, что у панели. Значения секретов
    сюда не попадают: только имя и действие."""
    try:
        from .web import audit as journal

        journal.record(ACTOR, action, detail)
    except Exception:  # noqa: BLE001
        # Журнал вторичен: упавшая запись не должна отменять уже сделанное.
        pass


# --------------------------------------------------------------------------
#  Пользователи
# --------------------------------------------------------------------------

def _card(key: str, record: dict[str, Any]) -> dict[str, Any]:
    """Что показываем о человеке. Без контактов SOS и без подборок: это
    личное, и в консольный вывод (а оттуда — в журналы cron) не должно
    попадать."""
    return {
        "key": key,
        "role": record.get("role", "user"),
        "username": record.get("username", ""),
        "lang": record.get("lang", ""),
        "tz": record.get("tz", ""),
        "weather_mode": record.get("weather_mode", ""),
        "weather_time": record.get("weather_time", ""),
        "quiet": [record.get("quiet_from", ""), record.get("quiet_to", "")],
        "created": record.get("created", 0),
        "locations": [
            {"id": item.get("id", ""), "name": item.get("name", ""),
             "city": item.get("city", "")}
            for item in (record.get("locs") or [])
        ],
    }


def cmd_users(args) -> int:
    from . import roles, storage

    async def run():
        people = storage.users()

        if args.action == "list":
            rows = [
                {"key": key, "role": item.get("role", "user"),
                 "locations": len(item.get("locs") or [])}
                for key, item in people.items()
                if not args.role or item.get("role", "user") == args.role
            ]
            word = L("локаций", "locations")
            cli._out(rows, args.json, lambda data: [
                print(f"{row['key']:>12}  {roles.title(row['role'], L('ru', 'en')):<22} "
                      f"{word}: {row['locations']}")
                for row in data
            ])
            return OK

        if not args.key:
            cli._err(L("Нужен ключ пользователя (например 123456789 или vk:5).",
                       "A user key is required (for example 123456789 or vk:5)."))
            return FAILED
        record = storage.get_user(args.key)
        if record is None:
            cli._err(L("Пользователь не найден.", "User not found."))
            return FAILED
        role = record.get("role")

        if args.action == "show":
            def show(card):
                for name, value in card.items():
                    if name != "locations":
                        print(f"{name}: {value}")
                for item in card["locations"]:
                    print(f"  • {item['name']} {item['city']} [{item['id']}]")

            cli._out(_card(args.key, record), args.json, show)
            return OK

        if args.action == "role":
            if args.value not in (roles.USER, roles.MODERATOR, roles.ADMIN):
                cli._err(L("Роль: user, moderator или admin (суперадмина "
                           "выдаёт только установка).",
                           "Role: user, moderator or admin (superadmin is set "
                           "only by the installation)."))
                return FAILED
            if not roles.can_assign(CONSOLE_ROLE, role, args.value):
                cli._err(L("Роль этого пользователя изменить нельзя.",
                           "This user's role cannot be changed."))
                return FAILED
            record["role"] = args.value
            await storage.save()
            audit("роль изменена", f"{args.key}: {args.value}")
            print(L(f"{args.key}: роль — {args.value}", f"{args.key}: role is {args.value}"))
            return OK

        if args.action == "delete":
            if not roles.can_delete_user(CONSOLE_ROLE, role):
                cli._err(L("Этого пользователя удалить нельзя.",
                           "This user cannot be deleted."))
                return FAILED
            if not args.yes:
                cli._err(L("Удаление уберёт человека вместе с адресами. Повторите с --yes.",
                           "Deleting removes the person with all addresses. Repeat with --yes."))
                return NEEDS_YES
            await storage.drop_user(args.key)
            audit("пользователь удалён", args.key)
            print(L(f"{args.key}: удалён", f"{args.key}: deleted"))
            return OK

        # time: часовой пояс и время погоды (как в панели).
        from . import timezones
        from .quiet import parse_time

        changed = []
        if args.tz:
            if timezones.parse(args.tz) is None:
                cli._err(L("Часовой пояс не разобран.", "Time zone not understood."))
                return FAILED
            record["tz"] = args.tz
            changed.append(L("пояс", "zone"))
        if args.weather_time:
            if parse_time(args.weather_time) is None:
                cli._err(L("Время нужно в виде 08:00.", "Time must look like 08:00."))
                return FAILED
            record["weather_time"] = args.weather_time
            record["weather_mode"] = "time"
            changed.append(L("время погоды", "weather time"))
        if not changed:
            cli._err(L("Нечего менять: укажите --tz и/или --weather-time.",
                       "Nothing to change: give --tz and/or --weather-time."))
            return FAILED
        await storage.save()
        audit("время пользователя изменено", f"{args.key}: {', '.join(changed)}")
        print(L("Сохранено: ", "Saved: ") + ", ".join(changed))
        return OK

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  Ключи и значения .env
# --------------------------------------------------------------------------

def cmd_keys(args) -> int:
    from . import secrets

    if args.action == "list":
        data = {
            group: [
                {"name": item.key, "title": item.title,
                 "value": secrets.display(item)}
                for item in items
            ]
            for group, items in secrets.by_group().items()
        }
        cli._out(data, args.json, lambda d: [
            print(f"[{group}] {item['name']}: {item['value']}")
            for group, items in d.items() for item in items
        ])
        return OK

    if args.action == "pending":
        names = sorted(secrets.PENDING_RESTART)
        cli._out(names, args.json, lambda d: [print(n) for n in d] or print(
            L("Всё применено.", "Everything is applied.")))
        return OK

    setting = secrets.BY_KEY.get(args.name)
    if setting is None:
        cli._err(L(f"Неизвестный ключ: {args.name}", f"Unknown key: {args.name}"))
        return FAILED

    if args.action == "get":
        # Секретное значение консоль не печатает: журналы cron и история
        # терминала читаются не только владельцем. Полное — в .env.
        value = secrets.display(setting)
        cli._out({"name": args.name, "value": value}, args.json,
                 lambda d: print(f"{d['name']}: {d['value']}"))
        return OK

    if not secrets.writable():
        cli._err(L("Файл .env недоступен на запись", ".env is not writable"))
        return FAILED

    value = "" if args.action == "unset" else secrets.normalize_value(setting, args.value)
    problem = secrets.check_value(setting, value) or secrets.validate_extra(args.name, value)
    if problem:
        cli._err(problem)
        return FAILED
    if not secrets.write(args.name, value):
        cli._err(L(f"Не удалось записать {args.name}", f"Could not write {args.name}"))
        return FAILED
    # Имя ключа — в журнал, значение — никогда.
    audit("ключ очищен" if not value else "ключ изменён", args.name)
    if not value:
        print(L(f"{args.name}: очищено", f"{args.name}: cleared"))
    else:
        print(L(f"{args.name}: записано ({secrets.mask(value)})",
                f"{args.name}: saved ({secrets.mask(value)})"))
    if args.name in secrets.PENDING_RESTART:
        print(L("Применится после перезапуска бота.",
                "Takes effect after the bot restarts."), file=sys.stderr)
    return OK


# --------------------------------------------------------------------------
#  Статистика
# --------------------------------------------------------------------------

def cmd_stats(args) -> int:
    from . import __version__, roles, storage

    async def run():
        counters: dict[str, int] = {}
        locations = 0
        for user in storage.users().values():
            role = user.get("role", "user")
            counters[role] = counters.get(role, 0) + 1
            locations += len(user.get("locs") or [])
        payload: dict[str, Any] = {
            "version": __version__,
            "users": len(storage.users()),
            "by_role": counters,
            "locations": locations,
            "channels": len(storage.channels()),
            "rss": len(storage.rss_feeds()),
            "pending_sources": len(storage.pending()),
            # Счётчики цикла живут в памяти бота: консоль отдельным
            # процессом видела бы нули и выдавала их за правду.
            "live": cli.in_bot(),
        }
        if cli.in_bot():
            from . import monitor

            payload["monitor"] = monitor.stats()

        def show(d):
            print(L(f"Радар v{d['version']}", f"Radar v{d['version']}"))
            print(L(f"Пользователей: {d['users']} (",
                    f"Users: {d['users']} (") + ", ".join(
                f"{roles.title(r, L('ru', 'en'))}: {c}"
                for r, c in sorted(d["by_role"].items())) + ")")
            print(L(f"Локаций: {d['locations']}", f"Locations: {d['locations']}"))
            print(L(f"Каналов: {d['channels']}, RSS: {d['rss']}, "
                    f"в очереди: {d['pending_sources']}",
                    f"Channels: {d['channels']}, RSS: {d['rss']}, "
                    f"queued: {d['pending_sources']}"))
            if "monitor" in d:
                m = d["monitor"]
                print(L(f"Циклов: {m.get('cycles')}, сообщений: {m.get('items')}, "
                        f"оповещений: {m.get('alerts')}",
                        f"Cycles: {m.get('cycles')}, messages: {m.get('items')}, "
                        f"alerts: {m.get('alerts')}"))
            else:
                print(L("Счётчики мониторинга — только у запущенного бота.",
                        "Monitoring counters exist only in a running bot."))

        cli._out(payload, args.json, show)
        return OK

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  Журналы
# --------------------------------------------------------------------------

def cmd_logs(args) -> int:
    from . import logs

    if args.action == "list":
        rows = [{"name": item.name, "kind": item.kind, "size": item.size_human,
                 "age": item.age_human} for item in logs.collect()]
        cli._out(rows, args.json, lambda data: [
            print(f"{row['name']:<28} {row['kind']:<10} {row['size']:>9}  {row['age']}")
            for row in data
        ] or print(L("журналов нет", "no logs")))
        return OK

    if args.action == "tail":
        item = logs.find(args.name or "bot.log")
        if item is None:
            cli._err(L("Такого журнала нет.", "No such log."))
            return FAILED
        print(logs.tail(item, max(1, min(args.lines, 2000))), end="")
        return OK

    # clear
    kinds = {args.kind} if args.kind else None
    if not args.yes:
        cli._err(L("Журналы будут удалены (текущий bot.log остаётся). Повторите с --yes.",
                   "Logs will be deleted (the current bot.log stays). Repeat with --yes."))
        return NEEDS_YES
    removed, freed = logs.purge(kinds)
    audit("журналы очищены", f"{removed}")
    print(L(f"Удалено файлов: {removed}, освобождено {freed // 1024} КБ",
            f"Files removed: {removed}, freed {freed // 1024} KB"))
    return OK


# --------------------------------------------------------------------------
#  Журнал действий
# --------------------------------------------------------------------------

def _audit_lines(limit: int) -> list[dict[str, str]]:
    """Читает файл журнала, а не память: консоль — отдельный процесс."""
    from . import config

    path = os.path.join(config.LOG_DIR, "audit.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()[-limit:]
    except OSError:
        return []
    rows = []
    for line in reversed(lines):
        parts = line.split("\t")
        parts += [""] * (4 - len(parts))
        rows.append({"when": parts[0], "actor": parts[1],
                     "action": parts[2], "detail": parts[3]})
    return rows


def cmd_audit(args) -> int:
    from .web import audit as journal

    if args.action == "tail":
        rows = _audit_lines(max(1, min(args.limit, 1000)))
        cli._out(rows, args.json, lambda data: [
            print(f"{r['when']}  {r['actor']:<10} {r['action']} {r['detail']}")
            for r in data
        ] or print(L("записей нет", "no entries")))
        return OK

    if not args.yes:
        cli._err(L("Журнал действий в памяти будет очищен (файл audit.log "
                   "остаётся). Повторите с --yes.",
                   "The in-memory action log will be cleared (audit.log stays). "
                   "Repeat with --yes."))
        return NEEDS_YES
    print(L(f"Очищено записей в памяти: {journal.clear()}",
            f"In-memory entries cleared: {journal.clear()}"))
    return OK


# --------------------------------------------------------------------------
#  Разбор аргументов
# --------------------------------------------------------------------------

def register(subparsers, common) -> None:
    users = subparsers.add_parser("users", help=L("пользователи", "users"),
                                  parents=[common])
    users.add_argument("action", nargs="?", default="list",
                       choices=["list", "show", "role", "delete", "time"])
    users.add_argument("key", nargs="?", default="")
    users.add_argument("value", nargs="?", default="",
                       help=L("role: user | moderator | admin", "role: user | moderator | admin"))
    users.add_argument("--role", default="",
                       help=L("list: только эта роль", "list: only this role"))
    users.add_argument("--tz", default="", help=L("time: часовой пояс", "time: time zone"))
    users.add_argument("--weather-time", dest="weather_time", default="",
                       help=L("time: время погоды ЧЧ:ММ", "time: weather time HH:MM"))
    users.add_argument("--yes", action="store_true")
    users.set_defaults(func=cmd_users)

    keys = subparsers.add_parser("keys", help=L("ключи, токены и значения .env",
                                                "keys, tokens and .env values"),
                                 parents=[common])
    keys.add_argument("action", choices=["list", "get", "set", "unset", "pending"])
    keys.add_argument("name", nargs="?", default="")
    keys.add_argument("value", nargs="?", default="")
    keys.set_defaults(func=cmd_keys)

    stats = subparsers.add_parser("stats", help=L("статистика", "statistics"),
                                  parents=[common])
    stats.set_defaults(func=cmd_stats)

    logs_cmd = subparsers.add_parser("logs", help=L("журналы бота", "bot logs"),
                                 parents=[common])
    logs_cmd.add_argument("action", choices=["list", "tail", "clear"])
    logs_cmd.add_argument("name", nargs="?", default="",
                      help=L("tail: имя файла (по умолчанию bot.log)",
                             "tail: file name (default bot.log)"))
    logs_cmd.add_argument("--lines", type=int, default=60)
    logs_cmd.add_argument("--kind", default="",
                      help=L("clear: bot | installer | doctor | other",
                             "clear: bot | installer | doctor | other"))
    logs_cmd.add_argument("--yes", action="store_true")
    logs_cmd.set_defaults(func=cmd_logs)

    audit_cmd = subparsers.add_parser("audit", help=L("журнал действий", "action log"),
                                    parents=[common])
    audit_cmd.add_argument("action", choices=["tail", "clear"])
    audit_cmd.add_argument("--limit", type=int, default=50)
    audit_cmd.add_argument("--yes", action="store_true")
    audit_cmd.set_defaults(func=cmd_audit)
