#!/usr/bin/env python3
"""Адаптер ВКонтакте и зеркало тревог по настоящему HTTP (5.6).

На 127.0.0.1 поднимается эмулятор API ВКонтакте и сервера Long Poll,
написанный по исходникам vkbottle (polling/base.py, bot_polling.py), и через
него проходит настоящий `VkTransport` вместе с ответчиком и зеркалом:

1. ключ сообщества — в теле POST, а не в адресе;
2. `groups.getLongPollServer` → Long Poll с `act=a_check`;
3. коды сбоя: 1 — новый `ts` из ответа, 2 — новый ключ при прежнем `ts`,
   3 — сервер заново;
4. сквозной путь: код из Telegram → сообщение боту в ВК → «да» →
   общий аккаунт → тревога в Telegram → копия в ВК через `messages.send`;
5. адрес из ВК (5.7): `/address` → подтверждение → адрес в общем профиле
   (геокодер подменён: Nominatim — не предмет этой проверки);
6. ошибка 5 (неверный ключ) → адаптер останавливается.

Проверка согласованности с прочитанным кодом vkbottle и транспорта —
не проверка настоящего ВКонтакте.

    python3 tools/vk_http_check.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from aiohttp import web
except ImportError:  # pragma: no cover
    print("Нужен aiohttp: pip install aiohttp (в образе бота он есть).")
    sys.exit(2)

try:
    import dotenv  # noqa: F401
except ImportError:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

TOKEN = "vk-group-token"


class Emulator:
    def __init__(self) -> None:
        self.base = ""
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, str]] = []
        self.token_in_url = False
        self.servers = 0
        self.failures = [1, 2, 3]     # по одному сбою каждого вида
        self.ts = 10
        self.key = "K1"
        self.revoke = False

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/method/{method}", self.method)
        app.router.add_post("/lp", self.longpoll)
        return app

    async def method(self, request: web.Request) -> web.Response:
        if "access_token" in request.query:
            self.token_in_url = True
        form = await request.post()
        if form.get("access_token") != TOKEN or self.revoke:
            return web.json_response({"error": {"error_code": 5,
                                                "error_msg": "User authorization failed"}})
        if form.get("v") != "5.199":
            return web.json_response({"error": {"error_code": 8, "error_msg": "bad version"}})
        method = request.match_info["method"]
        if method == "groups.getLongPollServer":
            self.servers += 1
            self.key = f"K{self.servers}"
            return web.json_response({"response": {
                "server": self.base + "/lp", "key": self.key, "ts": str(self.ts)}})
        if method == "messages.send":
            self.sent.append({key: str(value) for key, value in form.items()
                              if key != "access_token"})
            return web.json_response({"response": len(self.sent)})
        return web.json_response({"error": {"error_code": 3, "error_msg": "unknown method"}})

    async def longpoll(self, request: web.Request) -> web.Response:
        form = await request.post()
        if form.get("act") != "a_check":
            return web.json_response({"failed": 4})
        if form.get("key") != self.key:
            return web.json_response({"failed": 2})
        if self.failures:
            failed = self.failures.pop(0)
            if failed == 1:
                self.ts += 1
                return web.json_response({"failed": 1, "ts": str(self.ts)})
            if failed == 2:
                self.key = "expired"
                return web.json_response({"failed": 2})
            return web.json_response({"failed": 3})
        try:
            update = await asyncio.wait_for(self.queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            return web.json_response({"ts": str(self.ts), "updates": []})
        self.ts += 1
        return web.json_response({"ts": str(self.ts), "updates": [update]})


def message(from_id: int, text: str) -> dict[str, Any]:
    return {"type": "message_new", "group_id": 1, "object": {"message": {
        "id": 1, "from_id": from_id, "peer_id": from_id, "text": text}}}


async def main() -> int:
    from radar import links, mirror
    from radar.platforms import textbot, vk, vkbot

    emulator = Emulator()
    runner = web.AppRunner(emulator.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    emulator.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"  # noqa: SLF001

    meta: dict[str, Any] = {}

    async def meta_get(key, default=None):
        return json.loads(json.dumps(meta.get(key, default)))

    async def meta_set(key, value):
        meta[key] = json.loads(json.dumps(value))

    import radar

    users: dict[str, Any] = {}

    async def save(uid=None):
        return None

    async def drop_user(uid):
        users.pop(str(uid), None)

    def register(uid, username=""):
        users[str(uid)] = {"role": "user", "locs": [], "settings": {}, "lang": ""}
        return users[str(uid)]

    def new_location(name, lat, lon, **extra):
        return dict(extra, id=f"l{len(users)}", name=name, lat=lat, lon=lon)

    storage = types.ModuleType("radar.storage")
    storage.meta_get = meta_get
    storage.meta_set = meta_set
    storage.users = lambda: users
    storage.get_user = lambda uid: users.get(str(uid))
    storage.register = register
    storage.save = save
    storage.drop_user = drop_user
    storage.new_location = new_location

    async def geocode(query, hint):
        return [{"name": "Тверская, 1", "lat": "55.757", "lon": "37.613",
                 "street": "Тверская", "house": "1", "city": "Москва",
                 "district": "", "region": ""}]

    checks: list[tuple[str, bool, str]] = []
    transport = vk.VkTransport(TOKEN, "123", vkbot.reply)
    with mock.patch.object(vk, "API", emulator.base + "/method"), \
            mock.patch.object(vk, "WAIT", 1), \
            mock.patch.dict(sys.modules, {"radar.storage": storage}), \
            mock.patch.object(radar, "storage", storage, create=True), \
            mock.patch.object(textbot, "_geocode_text", geocode):
        mirror.register("vk", transport.send_text)
        task = asyncio.ensure_future(transport.start())
        try:
            register("100")
            code = links.new_code("100")
            await emulator.queue.put(message(555, "привет"))
            await emulator.queue.put(message(555, code))
            await emulator.queue.put(message(555, "да"))
            # Ждём и связь, и третий ответ: «связаны» уходит после записи
            # связи, и проверка, читавшая ответы сразу, ловила гонку.
            for _ in range(100):
                if await links.owner_of("vk", "555") and len(emulator.sent) >= 3:
                    break
                await asyncio.sleep(0.1)
            owner = await links.owner_of("vk", "555")
            checks.append(("коды сбоя Long Poll 1, 2, 3 пережиты",
                           not emulator.failures and emulator.servers >= 3,
                           f"серверов запрошено: {emulator.servers}"))
            checks.append(("код из Telegram и «да» связали аккаунты", owner == "100",
                           f"основной профиль: {owner or '—'}"))
            replies = [item["message"] for item in emulator.sent]
            checks.append(("ответчик: справка, вопрос о связи, подтверждение",
                           len(replies) >= 3 and "/address" in replies[0]
                           and "«да»" in replies[1] and "связаны" in replies[2],
                           f"ответов: {len(replies)}"))
            await emulator.queue.put(message(555, "/address Тверская 1, Москва"))
            await emulator.queue.put(message(555, "да"))
            for _ in range(60):
                if users["100"]["locs"]:
                    break
                await asyncio.sleep(0.1)
            checks.append(("адрес из ВК лёг в общий профиль после «да»",
                           len(users["100"]["locs"]) == 1,
                           f"адресов в профиле: {len(users['100']['locs'])}"))
            before = len(emulator.sent)
            mirror.alert("100", "🚨 <b>Тревога</b> по адресу <a href=\"https://map\">ул. Ленина</a>")
            mirror.alert("200", "чужая тревога")
            await mirror.drain()
            copy = emulator.sent[before:]
            checks.append(("копия тревоги ушла в ВК только привязанному",
                           len(copy) == 1 and copy[0]["peer_id"] == "555"
                           and copy[0]["message"] == "🚨 Тревога по адресу ул. Ленина (https://map)"
                           and copy[0].get("random_id", "").isdigit(),
                           copy[0]["message"] if copy else "—"))
            checks.append(("ключ сообщества — в теле, не в адресе", not emulator.token_in_url,
                           "в адресе" if emulator.token_in_url else "в теле POST"))
            emulator.revoke = True
            emulator.key = "revoked"
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
                stopped = True
            except asyncio.TimeoutError:
                stopped = False
            checks.append(("ошибка 5 останавливает адаптер", stopped,
                           "остановлен" if stopped else "крутится в цикле"))
        finally:
            task.cancel()
            await transport.stop()
            mirror.unregister("vk")
            await runner.cleanup()

    failures = 0
    print("Адаптер ВКонтакте и зеркало тревог по HTTP:\n")
    for title, ok, note in checks:
        failures += 0 if ok else 1
        print(f"  {'✅' if ok else '❌'} {title}: {note}")
    print("\nЭто проверка по эмулятору, написанному по исходникам vkbottle, "
          "а не по настоящему ВКонтакте.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
