#!/usr/bin/env python3
"""Проверка готовности системы до запуска бота.

Запускается внутри контейнера, где установлены все зависимости, и проверяет
то, что нельзя проверить снаружи: конфигурацию, подключение к базе, создание
схемы, запись и чтение данных, разбор старого `db.json`, доступность Telegram.

Смысл в том, чтобы ошибка обнаруживалась один раз и с понятным объяснением,
а не превращалась в цикл перезапусков контейнера.

    python -m radar.doctor            # полная проверка
    python -m radar.doctor --quick    # без обращений к сети
    python -m radar.doctor --json     # машиночитаемый отчёт
    python -m radar.doctor --stream   # с метками прогресса для установщика

Модуль лежит внутри пакета, а не в tools/, намеренно: tools исключён
из контекста сборки образа, и попытка скопировать оттуда файл ломала build.

Код возврата: 0 — всё в порядке, 1 — есть ошибки, 2 — только предупреждения.
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
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK = "ok"
WARN = "warn"
ERROR = "error"

MARKS = {OK: "✓", WARN: "!", ERROR: "✗"}


@dataclass
class Result:
    name: str
    status: str
    message: str = ""
    hint: str = ""
    detail: str = ""


@dataclass
class Report:
    checks: list[Result] = field(default_factory=list)

    def add(self, name: str, status: str, message: str = "", hint: str = "", detail: str = "") -> None:
        self.checks.append(Result(name, status, message, hint, detail))

    @property
    def errors(self) -> list[Result]:
        return [item for item in self.checks if item.status == ERROR]

    @property
    def warnings(self) -> list[Result]:
        return [item for item in self.checks if item.status == WARN]

    def code(self) -> int:
        if self.errors:
            return 1
        return 2 if self.warnings else 0


report = Report()

# Порядок и подписи проверок: установщик показывает по ним шкалу.
STAGES = (
    ("imports", "зависимости"),
    ("resources", "память и диск"),
    ("config", "конфигурация"),
    ("database", "подключение к базе"),
    ("schema", "схема и запись данных"),
    ("import_file", "данные прежней версии"),
    ("telegram", "доступ к Telegram"),
)

STREAM = False
_stage_index = 0


def announce(key: str) -> None:
    """Сообщает установщику, какая проверка началась.

    Метка машиночитаемая: установщик по ней рисует шкалу, а человек
    в обычном режиме её не видит.
    """
    global _stage_index
    if not STREAM:
        return
    titles = dict(STAGES)
    _stage_index += 1
    print(f"##STAGE {_stage_index} {len(STAGES)} {titles.get(key, key)}", flush=True)


# --------------------------------------------------------------------------
#  Проверки
# --------------------------------------------------------------------------

def check_imports() -> bool:
    """Все ли зависимости на месте и импортируются."""
    announce("imports")
    modules = {
        "aiogram": "Telegram-клиент",
        "aiohttp": "HTTP-клиент",
        "sqlalchemy": "работа с базой",
        "bs4": "разбор веб-страниц",
        "dotenv": "чтение .env",
    }
    missing: list[str] = []
    for name, purpose in modules.items():
        try:
            __import__(name)
        except ImportError as exc:
            missing.append(f"{name} ({purpose}): {exc}")

    if missing:
        report.add(
            "Зависимости", ERROR,
            f"не установлены: {len(missing)}",
            "Пересоберите образ: docker compose build --no-cache",
            "\n".join(missing),
        )
        return False
    report.add("Зависимости", OK, f"проверено модулей: {len(modules)}")
    return True


def check_config() -> bool:
    """Обязательные параметры и типичные ошибки в них."""
    announce("config")
    try:
        from radar import config
    except Exception as exc:  # noqa: BLE001
        report.add("Конфигурация", ERROR, str(exc),
                   "Проверьте .env и переменные окружения", traceback.format_exc())
        return False

    problems: list[str] = []
    if not config.BOT_TOKEN:
        problems.append("BOT_TOKEN не задан")
    elif ":" not in config.BOT_TOKEN:
        problems.append("BOT_TOKEN не похож на токен (нет двоеточия)")
    if not config.SUPERADMIN_ID:
        problems.append("SUPERADMIN_ID не задан или равен нулю")

    if problems:
        report.add("Конфигурация", ERROR, "; ".join(problems),
                   "Откройте .env и заполните недостающее")
        return False

    backend = "SQLite" if config.is_sqlite() else "PostgreSQL"
    report.add("Конфигурация", OK, f"версия {config.VERSION}, база {backend}")

    if not config.GEMINI_API_KEY:
        report.add("Ключ Gemini", WARN, "не задан",
                   "Бот будет работать на эвристическом разборе без ИИ")
    else:
        report.add("Ключ Gemini", OK, "задан")
    return True


async def check_database() -> bool:
    """Подключение, создание схемы и полный цикл записи-чтения."""
    announce("database")
    from radar import config
    from radar.db import engine as db_engine

    try:
        await db_engine.wait_ready(attempts=15, delay=2.0)
    except Exception as exc:  # noqa: BLE001
        hint = (
            "Проверьте DB_FILE и права на каталог data/"
            if config.is_sqlite()
            else "Проверьте, что контейнер radar_db поднят, и совпадает ли DB_PASSWORD"
        )
        report.add("Подключение к базе", ERROR, str(exc)[:200], hint, traceback.format_exc())
        return False
    report.add("Подключение к базе", OK, config.database_url().split("@")[-1][:60])

    try:
        created, tables, repaired = await db_engine.ensure_schema()
        await db_engine.stamp_alembic()
    except Exception as exc:  # noqa: BLE001
        report.add("Схема базы", ERROR, str(exc)[:200],
                   "Возможна несовместимость версии базы", traceback.format_exc())
        return False

    if repaired:
        report.add("Схема базы", WARN,
                   f"была несовместима и пересоздана, таблиц: {tables}",
                   "Данные пользователей сохранены, история событий очищена")
    else:
        report.add("Схема базы", OK,
                   f"{'создана' if created else 'актуальна'}, таблиц: {tables}")

    # Отдельная проверка: все ли поля моделей есть в базе. Раньше добавление
    # поля в модель ломало запросы на уже созданной базе.
    try:
        absent = await db_engine.missing_columns()
    except Exception as exc:  # noqa: BLE001
        report.add("Столбцы таблиц", WARN, str(exc)[:160])
    else:
        if absent:
            details = "; ".join(
                f"{table}: {', '.join(columns)}" for table, columns in absent.items()
            )
            report.add("Столбцы таблиц", ERROR, details,
                       "Схема не дополнена — запросы будут падать")
        else:
            report.add("Столбцы таблиц", OK, "все поля моделей на месте")

    # Полный цикл: запись, чтение, удаление. Именно здесь всплывали ошибки
    # ленивой подгрузки, которых не видно при простом подключении.
    announce("schema")
    from radar.db import repo

    probe_id = "doctor:0"
    try:
        sample = repo.default_user("user", "doctor")
        sample["locs"] = [repo.new_location("Проверочная улица, 1", 51.5, 46.0, city="Тест")]
        await repo.save_user(probe_id, sample)

        loaded = await repo.load_users()
        if probe_id not in loaded:
            raise RuntimeError("записанный пользователь не читается обратно")
        if len(loaded[probe_id]["locs"]) != 1:
            raise RuntimeError("локация не сохранилась")

        sample["locs"] = []
        await repo.save_user(probe_id, sample)          # проверка удаления локаций
        await repo.set_feature("history", True, 0)      # проверка таблицы флагов
        await repo.set_meta("doctor", {"value": "ok"})  # проверка служебной таблицы
    except Exception as exc:  # noqa: BLE001
        report.add("Запись и чтение", ERROR, str(exc)[:200],
                   "Схема или модели несовместимы с базой", traceback.format_exc())
        return False
    finally:
        try:
            await repo.delete_user(probe_id)
        except Exception:  # noqa: BLE001
            pass

    report.add("Запись и чтение", OK, "полный цикл пройден")
    return True


async def check_import_file() -> None:
    """Читается ли файл прежней версии, если он есть."""
    announce("import_file")
    from radar import config
    from radar.db import importer

    path = config.DATA_FILE
    if not os.path.exists(path):
        report.add("Данные прежней версии", OK, "файла нет, начинаем с чистой базы")
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        data = importer._normalize(raw if isinstance(raw, dict) else {})
    except Exception as exc:  # noqa: BLE001
        report.add("Данные прежней версии", ERROR, str(exc)[:200],
                   f"Файл {path} повреждён; переименуйте его, чтобы начать с нуля",
                   traceback.format_exc())
        return

    users = len(data["users"])
    locations = sum(len(item["locs"]) for item in data["users"].values())
    report.add("Данные прежней версии", OK,
               f"готово к переносу: пользователей {users}, локаций {locations}, "
               f"источников {len(data['channels'])}")


async def check_telegram() -> None:
    """Принимает ли Telegram наш токен."""
    announce("telegram")
    import aiohttp

    from radar import config

    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getMe"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.get(url) as response:
                payload = await response.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        report.add("Telegram", WARN, f"сеть недоступна: {exc}",
                   "Проверьте подключение или настройте выход через прокси")
        return

    if payload.get("ok"):
        name = (payload.get("result") or {}).get("username", "?")
        report.add("Telegram", OK, f"токен принят, бот @{name}")
    else:
        report.add("Telegram", ERROR,
                   str(payload.get("description", "неизвестная ошибка"))[:160],
                   "Проверьте BOT_TOKEN в .env — возможно, он отозван")


def check_resources() -> None:
    """Хватит ли памяти и места."""
    announce("resources")
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            info = {
                line.split(":")[0]: int(line.split()[1])
                for line in handle if ":" in line
            }
        total = info.get("MemTotal", 0) // 1024
        available = info.get("MemAvailable", 0) // 1024
        if available < 150:
            report.add("Память", ERROR, f"доступно {available} МБ из {total} МБ",
                       "Освободите память или добавьте файл подкачки")
        elif available < 300:
            report.add("Память", WARN, f"доступно {available} МБ из {total} МБ",
                       "Работать будет, но без запаса")
        else:
            report.add("Память", OK, f"доступно {available} МБ из {total} МБ")
    except Exception:  # noqa: BLE001
        pass

    try:
        stat = os.statvfs("/app/data")
        free = stat.f_bavail * stat.f_frsize // (1024 * 1024)
        if free < 200:
            report.add("Диск", ERROR, f"свободно {free} МБ", "Освободите место")
        else:
            report.add("Диск", OK, f"свободно {free} МБ")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
#  Запуск
# --------------------------------------------------------------------------

async def run(quick: bool) -> None:
    if not check_imports():
        return
    check_resources()
    if not check_config():
        return
    if not await check_database():
        return
    await check_import_file()
    if not quick:
        await check_telegram()

    from radar.db import engine as db_engine

    await db_engine.dispose()


def render(as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(item) for item in report.checks],
                         ensure_ascii=False, indent=2))
        return

    print()
    for item in report.checks:
        print(f"  {MARKS[item.status]} {item.name}: {item.message}")
        if item.hint and item.status != OK:
            print(f"      → {item.hint}")

    print()
    if report.errors:
        print(f"  Ошибок: {len(report.errors)}, предупреждений: {len(report.warnings)}")
        print("\n  Подробности:")
        for item in report.errors:
            print(f"\n  ── {item.name} ──")
            print(f"  {item.message}")
            if item.detail:
                tail = item.detail.strip().splitlines()[-6:]
                for line in tail:
                    print(f"    {line}")
    elif report.warnings:
        print(f"  Всё работает, предупреждений: {len(report.warnings)}")
    else:
        print("  Все проверки пройдены")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Диагностика системы «Радар»")
    parser.add_argument("--quick", action="store_true", help="без обращений к сети")
    parser.add_argument("--json", action="store_true", help="машиночитаемый отчёт")
    parser.add_argument("--stream", action="store_true",
                        help="печатать метки прогресса для установщика")
    args = parser.parse_args()

    global STREAM
    STREAM = args.stream

    try:
        asyncio.run(run(args.quick))
    except Exception as exc:  # noqa: BLE001
        report.add("Диагностика", ERROR, str(exc)[:200],
                   "Непредвиденная ошибка проверки", traceback.format_exc())

    render(args.json)
    return report.code()


if __name__ == "__main__":
    sys.exit(main())
