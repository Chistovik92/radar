#!/usr/bin/env python3
"""Проверка обновления со старых выпусков на текущий код (с 5.8.1).

Для каждого тега (по умолчанию все v4.9*) код этого выпуска создаёт базу
и наполняет её — пользователи, адреса, источники, флаги, meta, событие
с доставкой, короткая ссылка, промокод, чат; затем текущий код поднимает
её тем же путём, что main.py при старте (ensure_schema → storage.load →
load_features), и сверяет, что ничего не потеряно, схема не пересоздана,
а запись в новом формате (ключ vk:…, meta 5.x) проходит.

    python3 tools/upgrade_check.py                         # все v4.9*, SQLite
    python3 tools/upgrade_check.py v4.9.8.14 v4.9.9.4
    DATABASE_URL=postgresql+asyncpg://radar@127.0.0.1:5432/radar \
        python3 tools/upgrade_check.py --postgres           # пустая база PostgreSQL

Нужны теги в клоне (git fetch --tags) и зависимости из requirements.txt.
В обязательные проверки не входит: без тегов и базы его не запустить.
Именно им в 5.8.1 проверен переход со всех 43 выпусков 4.9 на SQLite
и PostgreSQL 16.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OLD_PHASE = r'''"""Фаза старой версии: создать базу кодом 4.9.x и наполнить её."""
import asyncio, os, sys, types
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
from radar.db import engine, repo

async def main():
    created, tables = (await engine.create_schema())[:2]
    user = repo.default_user("superadmin", "owner")
    user["locs"].append(repo.new_location("Дом", 51.533, 46.034, city="Саратов", street="Московская", house="1"))
    user["lang"] = "ru"
    await repo.save_user("123456789", user)
    other = repo.default_user("user", "neighbor")
    other["locs"].append(repo.new_location("Дача", 51.6, 46.1, city="Саратов"))
    other["quiet_from"], other["quiet_to"] = "23:00", "07:00"
    await repo.save_user("987654321", other)
    await repo.sync_sources(["@saratov_news"], ["https://example.ru/rss"], ["club1"], ["@pending"])
    await repo.set_feature("weather", True, 123456789)
    await repo.set_feature("digest", True, 123456789)
    await repo.set_meta("announced_version", {"value": os.environ.get("OLD_VERSION", "4.9")})
    await repo.set_meta("partners", {"hydra": {"title": "Hydra"}})
    event = types.SimpleNamespace(relevant=True, source="@saratov_news", raw="Авария водопровода на Московской", summary="Авария", link="",
        categories=["water"], severity="warning", scope="street", all_clear=False, city="Саратов", region="", districts=[], streets=["Московская"], engine="heuristic")
    event_id = await repo.store_event(event)
    await repo.record_delivery(event_id, "123456789", user["locs"][0]["id"])
    await repo.save_short_link("abc123", "https://example.ru", 123456789)
    if hasattr(repo, "save_promo"):
        await repo.save_promo("hydra", "123456789", "HYDRA-0001", __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    if hasattr(repo, "chat_save"):
        await repo.chat_save(-100123, "Двор", True)
    print("old:", os.environ.get("OLD_VERSION"), "tables", tables, "event", event_id)
    await engine.dispose()

asyncio.run(main())
'''

NEW_PHASE = r'''"""Фаза 5.8: запуск на базе старой версии в том же порядке, что main.py."""
import asyncio, os, sys, types
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
from radar.db import engine, repo
from radar import storage, features

async def main():
    created, tables, repaired = await engine.ensure_schema()
    compatible, reason = await engine.check_schema_compatible()
    missing = await engine.missing_columns()
    await storage.load()
    flags = await repo.load_features()
    features.apply(flags)
    users = storage.users()
    owner = users["123456789"]
    problems = []
    if repaired: problems.append("схема ПЕРЕСОЗДАНА (история потеряна)")
    if not compatible: problems.append("несовместима: " + reason)
    if any(missing.values()): problems.append(f"не хватает столбцов: {missing}")
    if owner["role"] != "superadmin" or owner["locs"][0]["street"] != "Московская": problems.append("профиль владельца искажён")
    if users["987654321"]["quiet_from"] != "23:00": problems.append("тихие часы потеряны")
    if storage.channels() != ["@saratov_news"] or storage.vk_groups() != ["club1"]: problems.append("источники потеряны")
    if not (flags.get("weather") and flags.get("digest")): problems.append(f"флаги потеряны: {flags}")
    if (await repo.get_meta("partners")) != {"hydra": {"title": "Hydra"}}: problems.append("meta потеряна")
    hist = await repo.history("123456789", limit=10) if "limit" in repo.history.__code__.co_varnames else await repo.history("123456789")
    if not hist: problems.append("история доставок пуста")
    if await repo.resolve_short_link("abc123") != "https://example.ru": problems.append("короткая ссылка потеряна")
    if await repo.promo_for_user("hydra", "123456789") is None: problems.append("промокод потерян")
    # Новое в 5.x поверх старых данных: сохранение, ключ vk:, meta 5.x
    owner["lang"] = "en"
    users["987654321"]["tz"] = "+03:00"   # пересохраняются оба: save() пишет только изменённых
    storage.register("vk:5")["locs"].append(storage.new_location("ВК-дом", 51.5, 46.0))
    await storage.save()
    await repo.set_meta("account_links", {"123456789": {"vk": "7"}})
    await repo.set_meta("vpn_accounts", {"123456789": {"panels": {}}})
    await storage.load()
    if storage.get_user("vk:5") is None or storage.get_user("123456789")["lang"] != "en": problems.append("сохранение 5.x не прошло")
    # После пересохранения кодом 5.8 старые поля должны остаться прежними:
    # запись в новом формате не имеет права затирать то, что пришло из 4.9.
    again = storage.users()
    if again["987654321"]["quiet_from"] != "23:00": problems.append("тихие часы затёрты при сохранении")
    if again["123456789"]["locs"][0]["street"] != "Московская" or again["123456789"]["role"] != "superadmin":
        problems.append("профиль затёрт при сохранении")
    if len(again["987654321"]["locs"]) != 1: problems.append("адреса затёрты при сохранении")
    if hasattr(repo, "chat_list"):
        await repo.chat_list()
    print("new: tables", tables, "created", created, "repaired", repaired, "users", len(storage.users()))
    print("ПРОБЛЕМЫ:" if problems else "OK", *problems, sep="\n  ")
    await engine.dispose()
    sys.exit(1 if problems else 0)

asyncio.run(main())
'''


def tags(pattern: str = "v4.9*") -> list[str]:
    out = subprocess.run(["git", "tag", "-l", pattern], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout.split()
    return sorted(out, key=lambda tag: [int(part) for part in tag.lstrip("v").split(".")])


def reset_postgres(url: str) -> None:
    """Пустая база перед каждым тегом: DROP SCHEMA public CASCADE."""
    import asyncio

    import asyncpg

    async def run() -> None:
        plain = url.replace("postgresql+asyncpg://", "postgresql://")
        connection = await asyncpg.connect(plain)
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await connection.close()

    asyncio.run(run())


def check(tag: str, work: Path, postgres: bool) -> tuple[bool, str]:
    old = work / tag
    if not old.exists():
        archive = subprocess.run(["git", "archive", tag, "radar"], cwd=ROOT, check=True,
                                 capture_output=True).stdout
        old.mkdir(parents=True)
        subprocess.run(["tar", "-x", "-C", str(old)], input=archive, check=True)
    env = dict(os.environ, BOT_TOKEN="1:x", OLD_VERSION=tag, DB_PASSWORD="x")
    if postgres:
        reset_postgres(env["DATABASE_URL"])
        env["DB_BACKEND"] = "postgres"
    else:
        db = work / "upgrade.sqlite"
        for extra in ("", "-wal", "-shm"):
            Path(str(db) + extra).unlink(missing_ok=True)
        env.update(DATABASE_URL=f"sqlite+aiosqlite:///{db}", DB_BACKEND="sqlite")
    (work / "old_phase.py").write_text(OLD_PHASE, encoding="utf-8")
    (work / "new_phase.py").write_text(NEW_PHASE, encoding="utf-8")
    first = subprocess.run([sys.executable, str(work / "old_phase.py")], cwd=old,
                           env=dict(env, PYTHONPATH=str(old)), capture_output=True, text=True)
    if first.returncode:
        return False, "старый код не создал базу: " + first.stderr.strip().splitlines()[-1]
    second = subprocess.run([sys.executable, str(work / "new_phase.py")], cwd=ROOT,
                            env=dict(env, PYTHONPATH=str(ROOT)), capture_output=True, text=True)
    lines = [line for line in second.stdout.splitlines() if line.strip()]
    if second.returncode:
        detail = lines[-3:] or second.stderr.strip().splitlines()[-1:]
        return False, " ".join(detail)
    return True, lines[0] if lines else ""


def main(argv: list[str]) -> int:
    postgres = "--postgres" in argv
    wanted = [item for item in argv if not item.startswith("--")] or tags()
    if postgres and not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        print("Для --postgres задайте DATABASE_URL=postgresql+asyncpg://… на пустую базу.")
        return 2
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for tag in wanted:
            ok, note = check(tag, Path(tmp), postgres)
            failures += 0 if ok else 1
            print(f"  {'✅' if ok else '❌'} {tag}: {note}")
    base = "PostgreSQL" if postgres else "SQLite"
    print(f"\nОбновление на текущий код ({base}): проверено {len(wanted)}, с ошибками {failures}.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
