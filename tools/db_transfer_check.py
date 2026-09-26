#!/usr/bin/env python3
"""Перенос данных SQLite ⇄ PostgreSQL на настоящих базах (с 5.9).

Текущий код наполняет базу данными всех видов (пользователи с адресами,
подписками и SOS-контактами — в том числе с ключами vk:/max:, источники,
флаги, meta, события с доставками, короткая ссылка, промокод, чат
с предупреждением), затем:

1. перенос A → B и сверка содержимого строка в строку (даты — в UTC);
2. новые записи в B — счётчики автоинкремента не должны конфликтовать;
3. обратный перенос B → C и сверка;
4. перенос в непустую базу отвергается, с replace — заменяет;
5. бот поднимает C тем же путём, что main.py.

Без PG_URL A, B и C — файлы SQLite: так проверяется вся логика переноса
и типов (шаг CI). С `PG_URL=postgresql+asyncpg://…` B — эта база
PostgreSQL (она будет очищена): так проверены SQLite → PostgreSQL → SQLite.

    python3 tools/db_transfer_check.py
    PG_URL=postgresql+asyncpg://radar@127.0.0.1:5432/radar python3 tools/db_transfer_check.py

Нужны SQLAlchemy[asyncio] и aiosqlite (для PostgreSQL — asyncpg).
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

PHASE = r'''import asyncio, json, os, sys, types
from datetime import datetime, timezone
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))

async def fill():
    from radar.db import engine, repo
    await engine.ensure_schema()
    for i, uid in enumerate(["123456789", "987654321", "vk:5", "max:9"]):
        user = repo.default_user("superadmin" if i == 0 else "user", f"u{i}")
        user["locs"].append(repo.new_location(f"Дом {i}", 51.5 + i / 100, 46.0, city="Саратов", street="Московская", house=str(i)))
        user["digest"] = {"topics": ["city"], "times": ["08:30"]}
        user["sos_contacts"] = [{"key": "555", "confirmed": True}]
        await repo.save_user(uid, user)
    await repo.sync_sources(["@a", "@b"], ["https://e.ru/rss"], ["club1"], ["@p"])
    await repo.set_feature("weather", True, 1)
    await repo.set_meta("account_links", {"123456789": {"vk": "5"}})
    await repo.set_meta("vpn_accounts", {"123456789": {"panels": {"1": {"name": "old", "adopted": True}}}})
    for n in range(3):
        event = types.SimpleNamespace(relevant=True, source="@a", raw=f"Авария {n}", summary=f"Авария {n}", link="",
            categories=["water"], severity="warning", scope="street", all_clear=False, city="Саратов", region="", districts=[], streets=["Московская"], engine="heuristic")
        eid = await repo.store_event(event)
        await repo.record_delivery(eid, "123456789", None)
    await repo.save_short_link("abc123", "https://example.ru", 123456789)
    await repo.save_promo("hydra", "123456789", "HYDRA-0001", datetime.now(timezone.utc))
    await repo.chat_save(-100123, "Двор", True)
    await repo.warn_add(-100123, 42)
    await engine.dispose()

async def dump():
    from sqlalchemy import select
    from radar.db import engine
    from radar.db.models import Base
    result = {}
    eng = engine.get_engine()
    async with eng.connect() as conn:
        for table in Base.metadata.sorted_tables:
            order = list(table.primary_key.columns)
            rows = (await conn.execute(select(table).order_by(*order))).mappings().all()
            clean = []
            for row in rows:
                item = {}
                for k, v in row.items():
                    if isinstance(v, datetime):
                        v = (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
                    item[k] = v
                clean.append(item)
            result[table.name] = clean
    await engine.dispose()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))

async def grow():
    """Новые записи после переноса — проверка счётчиков PostgreSQL."""
    from radar.db import engine, repo
    await engine.ensure_schema()
    user = repo.default_user("user", "new")
    user["locs"].append(repo.new_location("Новый", 51.7, 46.2))
    await repo.save_user("555000111", user)
    event = types.SimpleNamespace(relevant=True, source="@b", raw="Новое", summary="Новое", link="",
        categories=["gas"], severity="info", scope="city", all_clear=False, city="Саратов", region="", districts=[], streets=[], engine="heuristic")
    eid = await repo.store_event(event)
    ok = await repo.record_delivery(eid, "555000111", None)
    await repo.save_promo("hydra", "555000111", "HYDRA-0002", datetime.now(timezone.utc))
    await repo.warn_add(-100123, 43)
    await engine.dispose()
    print("grow ok", eid, ok)

async def load_check():
    from radar.db import engine, repo
    from radar import storage
    created, tables, repaired = await engine.ensure_schema()
    await storage.load()
    print("users", len(storage.users()), "repaired", repaired, "vk", storage.get_user("vk:5")["locs"][0]["street"])
    await engine.dispose()

asyncio.run(globals()[sys.argv[1]]())
'''


def main() -> int:
    try:
        import aiosqlite  # noqa: F401
        import sqlalchemy  # noqa: F401
    except ImportError:
        print("Нужны SQLAlchemy[asyncio] и aiosqlite: pip install 'SQLAlchemy[asyncio]' aiosqlite")
        return 2
    pg = os.environ.get("PG_URL", "").strip()
    checks: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "phase.py"
        script.write_text(PHASE, encoding="utf-8")
        one = f"sqlite+aiosqlite:///{tmp}/one.sqlite"
        two = pg or f"sqlite+aiosqlite:///{tmp}/two.sqlite"
        three = f"sqlite+aiosqlite:///{tmp}/three.sqlite"
        env = dict(os.environ, PYTHONPATH=str(ROOT), BOT_TOKEN="1:x", DB_PASSWORD="x")

        def phase(name: str, url: str) -> subprocess.CompletedProcess:
            backend = "postgres" if url.startswith("postgresql") else "sqlite"
            return subprocess.run([sys.executable, str(script), name], cwd=ROOT,
                                  env=dict(env, DATABASE_URL=url, DB_BACKEND=backend),
                                  capture_output=True, text=True)

        def copy(src: str, dst: str, replace: bool = False) -> subprocess.CompletedProcess:
            # Та же заглушка dotenv, что в PHASE: в CI ставятся только драйверы баз.
            code = ("import asyncio,sys,types\n"
                    "sys.modules.setdefault('dotenv', types.SimpleNamespace("
                    "load_dotenv=lambda *a, **k: None))\n"
                    "from radar.db import transfer\n"
                    f"print(asyncio.run(transfer.copy({src!r}, {dst!r}, replace={replace})))")
            return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                  capture_output=True, text=True)

        if pg:
            code = ("import asyncio,asyncpg\nasync def m():\n"
                    f"    c=await asyncpg.connect({pg.replace('+asyncpg', '')!r})\n"
                    "    await c.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')\n"
                    "    await c.close()\nasyncio.run(m())")
            subprocess.run([sys.executable, "-c", code], check=True)

        filled = phase("fill", one)
        checks.append(("база наполнена текущим кодом", filled.returncode == 0,
                       (filled.stderr.strip().splitlines() or [""])[-1][:120]))
        first = copy(one, two)
        checks.append(("перенос A → B", first.returncode == 0,
                       (first.stdout.strip() or first.stderr.strip().splitlines()[-1])[:160]))
        same = phase("dump", one).stdout == phase("dump", two).stdout
        checks.append(("содержимое B совпадает с A строка в строку", same, ""))
        grown = phase("grow", two)
        checks.append(("новые записи в B без конфликта ключей", grown.returncode == 0,
                       (grown.stdout.strip() or grown.stderr.strip().splitlines()[-1])[:120]))
        back = copy(two, three)
        checks.append(("обратный перенос B → C", back.returncode == 0,
                       (back.stdout.strip() or back.stderr.strip().splitlines()[-1])[:160]))
        same = phase("dump", two).stdout == phase("dump", three).stdout
        checks.append(("содержимое C совпадает с B строка в строку", same, ""))
        refused = copy(two, three)
        checks.append(("перенос в непустую базу отвергается", refused.returncode != 0
                       and "не пуста" in refused.stderr, ""))
        replaced = copy(two, three, replace=True)
        checks.append(("с replace непустая база заменяется", replaced.returncode == 0, ""))
        loaded = phase("load_check", three)
        checks.append(("бот поднимает перенесённую базу", loaded.returncode == 0
                       and "repaired False" in loaded.stdout, loaded.stdout.strip()[:120]))

    failures = 0
    kind = "PostgreSQL" if pg else "SQLite"
    print(f"Перенос данных SQLite ⇄ {kind}:\n")
    for title, ok, note in checks:
        failures += 0 if ok else 1
        print(f"  {'✅' if ok else '❌'} {title}" + (f": {note}" if note and not ok else ""))
    if not pg:
        print("\nPostgreSQL не проверялся: задайте PG_URL, чтобы B была базой PostgreSQL.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
