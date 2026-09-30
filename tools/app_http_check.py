"""Проверка API для приложений по настоящему HTTP (5.9.1).

Тесты (`tests/test_appapi.py`) идут на заглушках и транспорта не видят:
заголовок Authorization, коды ответов, JSON в теле, отсутствие кэширования,
поведение при выключенном флаге. Здесь маршруты `radar/web/appapi.py`
поднимаются на 127.0.0.1 в настоящем aiohttp и опрашиваются настоящим
клиентом — как это будет делать приложение.

Нужен настоящий aiohttp:

    python3 tools/app_http_check.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import aiohttp
    from aiohttp import web
except ImportError:  # pragma: no cover
    print("Нужен aiohttp: pip install aiohttp (в образе бота он есть).")
    sys.exit(2)

try:
    import dotenv  # noqa: F401
except ImportError:  # как в db_transfer_check: конфигу нужен только load_dotenv
    stub = types.ModuleType("dotenv")
    stub.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = stub

import radar  # noqa: E402

# Настоящий storage тянет SQLAlchemy и базу; API нужны лишь meta_* и get_user.
storage = types.ModuleType("radar.storage")
sys.modules["radar.storage"] = storage
radar.storage = storage

from radar import appapi, features, vpn  # noqa: E402
from radar.vpnpanels import Account  # noqa: E402
from radar.web import appapi as routes  # noqa: E402
from radar.web import auth  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    print(("  ok   " if condition else "  FAIL ") + name + ("" if condition else f"  {detail}"))
    if not condition:
        failures.append(name)


async def main() -> int:
    meta: dict = {}
    state = {"on": True}

    async def meta_get(key, default=None):
        return meta.get(key, default)

    async def meta_set(key, value):
        meta[key] = value

    client_obj = SimpleNamespace(kind="3xui", link_kind="subscription")
    slot = SimpleNamespace(key="1", title="Главный", client=client_obj)

    async def record(uid):
        return {"state": "active", "panels": {"1": {"name": "radar_42"}}}

    async def statuses(uid):
        return {"1": Account("radar_42", True, 1900000000, 10 ** 10, 1000,
                             "https://sub.example/xyz")}

    storage.meta_get = meta_get
    storage.meta_set = meta_set
    storage.get_user = lambda uid: {"username": "ivan", "blocked": False}
    patches = [
        mock.patch.object(features, "enabled", lambda name: state["on"]),
        mock.patch.object(vpn, "record", record),
        mock.patch.object(vpn, "statuses", statuses),
        mock.patch.object(vpn, "slots", lambda: [slot]),
    ]
    for item in patches:
        item.start()
    auth._attempts.clear()

    application = web.Application()
    application.add_routes(routes.routes(web))
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    base = f"http://127.0.0.1:{port}/api/v1/app"

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"{base}/ping") as reply:
                body = await reply.json()
                check("ping отвечает версией API", reply.status == 200 and body["api"] == 1, body)

            async with http.get(f"{base}/me") as reply:
                check("без токена — 401", reply.status == 401, reply.status)

            async with http.get(f"{base}/me",
                                headers={"Authorization": "Bearer wrong"}) as reply:
                check("чужой токен — 401", reply.status == 401, reply.status)

            async with http.post(f"{base}/link", json={"code": "12345678"}) as reply:
                check("неверный код — 401", reply.status == 401, reply.status)

            async with http.post(f"{base}/link", data="не json") as reply:
                check("не JSON — 400", reply.status == 400, reply.status)

            code = appapi.issue_code("42")
            async with http.post(f"{base}/link", json={
                    "code": code, "device": "Pixel 8", "app": "hydravpn"}) as reply:
                body = await reply.json()
                check("обмен кода — 201 и токен", reply.status == 201 and body.get("token"), body)
                check("ответ не кэшируется", reply.headers.get("Cache-Control") == "no-store")
            token = body["token"]
            headers = {"Authorization": f"Bearer {token}"}

            async with http.post(f"{base}/link", json={"code": code}) as reply:
                check("код одноразовый", reply.status == 401, reply.status)

            async with http.get(f"{base}/me", headers=headers) as reply:
                body = await reply.json()
                check("профиль", reply.status == 200 and body["user_id"] == "42"
                      and body["vpn"]["panels"] == 1 and body["device"]["app"] == "hydravpn", body)

            async with http.get(f"{base}/subscriptions", headers=headers) as reply:
                body = await reply.json()
                item = (body.get("subscriptions") or [{}])[0]
                check("подписка со ссылкой и сроком",
                      reply.status == 200 and item.get("url") == "https://sub.example/xyz"
                      and item.get("expire") == 1900000000 and item.get("state") == "ok", body)

            state["on"] = False
            async with http.get(f"{base}/subscriptions", headers=headers) as reply:
                check("флаг выключен — 404", reply.status == 404, reply.status)
            state["on"] = True

            async with http.delete(f"{base}/session", headers=headers) as reply:
                check("выход — 200", reply.status == 200, reply.status)
            async with http.get(f"{base}/me", headers=headers) as reply:
                check("после выхода токен мёртв", reply.status == 401, reply.status)
    finally:
        await runner.cleanup()
        for item in patches:
            item.stop()

    print()
    if failures:
        print(f"Провалено проверок: {len(failures)}")
        return 1
    print("API для приложений по HTTP: всё сошлось.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
