#!/usr/bin/env python3
"""Паритет консоли с ботом и панелью (с 5.9.3.1).

**Зачем.** Требование автора — из терминала сервера должно быть доступно
всё, что умеют бот и панель. Требование без проверки живёт до первой новой
команды: её добавляют в бот, о консоли никто не вспоминает, и через пять
выпусков расхождение снова огромно.

**Что проверяется.** Скрипт находит каждую команду бота (`Command("…")`)
и каждый маршрут панели (`web.get/post("…")`) и сверяет с таблицей ниже.
У каждого пункта в таблице одно из трёх:

* `cli:<команда>` — есть подкоманда консоли; её существование проверяется
  по настоящему парсеру;
* `pending:<причина>` — ещё не сделано; список сокращается с выпусками;
* `na:<причина>` — осмысленной формы в терминале нет (диалог с человеком,
  скачивание файла, вход в панель) или это команды установки на хосте.

Падает, если появилась команда или маршрут, которых нет в таблице (значит,
решение «что делать в консоли» не принято), если пункт таблицы указывает
на несуществующую подкоманду или если в таблице остался пункт, которого
в коде уже нет.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

# --------------------------------------------------------------------------
#  Команды бота
# --------------------------------------------------------------------------

BOT: dict[str, str] = {
    "backup": "cli:backup", "chats": "cli:chats", "features": "cli:features",
    "keys": "cli:keys", "logs": "cli:logs", "logtail": "cli:logs",
    "logclear": "cli:logs", "stats": "cli:stats", "shorts": "cli:links",
    "shortclear": "cli:links", "modon": "cli:chats", "modstatus": "cli:chats",
    "checksources": "cli:sources", "id": "cli:users",
    "cancel": "na:сброс ввода в диалоге", "help": "na:справка бота",
    "menu": "na:меню бота", "language": "na:выбор языка пользователем",
    "link": "na:привязка аккаунта самим человеком",
    "panel": "na:ссылка на панель для человека",
    "ai": "pending:диалог с ассистентом; нужны ai agents/model",
    "ai_admin": "pending:агенты и модели ИИ", "aireset": "pending:сброс диалога ИИ",
    "bench": "pending:замер моделей", "check": "pending:проверка ссылки",
    "cookies": "pending:куки для видео", "digest": "pending:подборки",
    "digestprice": "pending:цена подборок", "history": "pending:история событий",
    "media": "pending:загрузка видео", "metrics": "pending:метрики",
    "models": "pending:модели ИИ", "music": "pending:музыка",
    "network": "pending:сеть и прокси", "partner": "pending:партнёры",
    "perf": "pending:производительность", "provider": "pending:провайдер ИИ",
    "quota": "pending:квота ИИ", "setmodel": "pending:выбор модели",
    "short": "pending:создание короткой ссылки", "sos": "pending:SOS",
    "sub": "pending:подписка", "subscription": "pending:подписка",
    "warn": "pending:предупреждение участнику группы",
}

# --------------------------------------------------------------------------
#  Маршруты панели
# --------------------------------------------------------------------------

PANEL: dict[str, str] = {
    "/": "cli:stats", "/users": "cli:users", "/users/time": "cli:users",
    "/sources": "cli:sources", "/sources/add": "cli:sources",
    "/sources/remove": "cli:sources", "/keys": "cli:keys", "/keys/set": "cli:keys",
    "/features": "cli:features", "/features/toggle": "cli:features",
    "/files": "cli:files", "/links": "cli:links", "/links/remove": "cli:links",
    "/links/clear": "cli:links", "/audit": "cli:audit", "/backup": "cli:backup",
    "/backup/create": "cli:backup", "/maintenance": "cli:db",
    "/rustdesk": "cli:rustdesk", "/rustdesk/action": "cli:rustdesk",
    "/chats": "cli:chats", "/chats/toggle": "cli:chats", "/vpn": "cli:vpn",
    "/settings": "cli:keys", "/vpn/panels/check": "cli:vpn",
    "/backup/download": "na:скачивание файла; копия лежит в data/backups",
    "/update": "na:на хосте: radarctl.sh update",
    "/update/start": "na:на хосте: radarctl.sh update",
    "/wipe": "na:на хосте: radarctl.sh wipe", "/wipe/start": "na:на хосте: radarctl.sh wipe",
    "/login": "na:вход в панель", "/auth": "na:вход в панель",
    "/login/code": "na:вход в панель", "/logout": "na:вход в панель",
    "/health": "na:проверка контейнера", "/s/{code}": "na:публичная короткая ссылка",
    "/d/{token}": "na:публичная раздача файла", "/d/{token}/{name}": "na:публичная раздача файла",
    "/agents": "pending:агенты ИИ", "/agents/save": "pending:агенты ИИ",
    "/agents/model": "pending:агенты ИИ", "/agents/remove": "pending:агенты ИИ",
    "/files/remove": "pending:досрочное отключение раздачи",
    "/events": "pending:поток событий", "/media": "pending:медиа",
    "/chats/invite": "pending:ссылка-приглашение", "/chats/announce": "pending:объявление",
    "/chats/send": "pending:сообщение от имени бота", "/chats/drop": "pending:сброс чата",
    "/settings/restart": "pending:перезапуск бота",
    "/vpn/app-revoke": "pending:отзыв доступа приложения",
    "/vpn/panels": "pending:VPN-панели", "/vpn/panels/save": "pending:VPN-панели",
    "/vpn/panels/remove": "pending:VPN-панели", "/vpn/access": "pending:доступы VPN",
    "/vpn/access/act": "pending:доступы VPN", "/subscriptions": "pending:подписки",
    "/subscriptions/act": "pending:подписки", "/cloud": "pending:облако музыки",
    "/cloud/add": "pending:облако музыки", "/cloud/forget": "pending:облако музыки",
    "/partners": "pending:партнёры", "/partners/save": "pending:партнёры",
    "/partners/remove": "pending:партнёры", "/partners/export": "pending:партнёры",
}


def found_bot() -> set[str]:
    names: set[str] = set()
    paths = list((ROOT / "radar").rglob("*.py")) + [ROOT / "main.py"]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        names.update(re.findall(r'Command\("([a-z_0-9]+)"', text))
    return names


def found_panel() -> set[str]:
    text = (ROOT / "radar" / "web" / "panel.py").read_text(encoding="utf-8")
    return set(re.findall(r'web\.(?:get|post)\("(/[^"]*)"', text))


def cli_commands() -> set[str]:
    import stubcheck

    stubcheck.install()
    from radar import cli

    parser = cli.build_parser()
    for action in parser._actions:  # noqa: SLF001 — публичного способа нет
        if getattr(action, "choices", None) and action.dest == "command":
            return set(action.choices)
    return set()


def main() -> int:
    problems: list[str] = []
    commands = cli_commands()
    stats = {"cli": 0, "pending": 0, "na": 0}

    for title, table, present in (("команда бота", BOT, found_bot()),
                                  ("маршрут панели", PANEL, found_panel())):
        for item in sorted(present - set(table)):
            problems.append(f"{title} «{item}» не внесена в таблицу паритета")
        for item in sorted(set(table) - present):
            problems.append(f"в таблице {title} «{item}», которой в коде нет")
        for item, value in table.items():
            kind, _, rest = value.partition(":")
            if kind not in stats:
                problems.append(f"{title} «{item}»: неизвестный вид «{value}»")
                continue
            stats[kind] += 1
            if kind == "cli" and rest not in commands:
                problems.append(f"{title} «{item}» указывает на несуществующую "
                                f"подкоманду «{rest}»")
            if kind in ("pending", "na") and not rest.strip():
                problems.append(f"{title} «{item}»: не указана причина")

    if problems:
        print("Паритет консоли нарушен:")
        for line in problems:
            print("  ✗", line)
        return 1
    total = sum(stats.values())
    print(f"Паритет консоли: сделано {stats['cli']}, осталось {stats['pending']}, "
          f"вне консоли {stats['na']} (всего {total}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
