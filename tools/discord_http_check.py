#!/usr/bin/env python3
"""Адаптер Discord по настоящему WebSocket и HTTP, без настоящего Discord (5.5).

Офлайн-тесты (`tests/test_discord.py`) проверяют машину состояний по одному
сообщению. Здесь всё идёт по сети: на 127.0.0.1 поднимается эмулятор
Gateway и REST, написанный по исходникам discord.py, и через него
проходит настоящий `DiscordTransport`:

1. `GET /oauth2/applications/@me` и `PUT /applications/:id/commands` —
   регистрация слеш-команд;
2. HELLO → IDENTIFY с токеном и намерениями → READY;
3. сердцебиение с подтверждениями;
4. слеш-команда → ответ через `/interactions/:id/:token/callback`
   в пределах трёх секунд;
5. RECONNECT → переподключение по `resume_gateway_url` и RESUME
   с тем же `session_id` и последним номером;
6. 429 с `retry_after` → повтор после паузы;
7. закрытие кодом 4004 → адаптер останавливается, а не долбит сервер.

Это проверка согласованности с прочитанным кодом discord.py и проверка
транспорта — не проверка настоящего Discord.

    python3 tools/discord_http_check.py
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
import time
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from aiohttp import WSMsgType, web
except ImportError:  # pragma: no cover
    print("Нужен aiohttp: pip install aiohttp (в образе бота он есть).")
    sys.exit(2)

try:
    import dotenv  # noqa: F401
except ImportError:
    # Настройки из .env здесь не нужны, а пакет платформ тянет config,
    # который импортирует dotenv. Пустая заглушка — только для проверки.
    import types

    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from radar.platforms import discord, discordbot  # noqa: E402
from radar.platforms.base import OutboundMessage  # noqa: E402

TOKEN = "discord-test-token"


class Emulator:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.connections = 0
        self.callbacks: list[dict[str, Any]] = []
        self.commands: list[Any] = []
        self.messages: list[dict[str, Any]] = []
        self.rate_limited = False
        self.resume_payload: dict[str, Any] | None = None
        self.heartbeats = 0
        self.base = ""
        self.done = asyncio.Event()
        self.dm_requests: list[dict[str, Any]] = []

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/api/v10/gateway/bot", self.gateway_bot)
        app.router.add_get("/api/v10/oauth2/applications/@me", self.me)
        app.router.add_put("/api/v10/applications/{app}/commands", self.put_commands)
        app.router.add_post("/api/v10/interactions/{id}/{token}/callback", self.callback)
        app.router.add_post("/api/v10/channels/{channel}/messages", self.message)
        app.router.add_post("/api/v10/users/@me/channels", self.dm_channel)
        app.router.add_get("/gw/", self.gateway)
        app.router.add_get("/resume/", self.gateway)
        return app

    def authed(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bot {TOKEN}"

    async def gateway_bot(self, request: web.Request) -> web.Response:
        if not self.authed(request):
            return web.json_response({"message": "401: Unauthorized"}, status=401)
        return web.json_response({"url": self.base.replace("http", "ws") + "/gw",
                                  "shards": 1})

    async def me(self, request: web.Request) -> web.Response:
        if not self.authed(request):
            return web.json_response({}, status=401)
        return web.json_response({"id": "A1"})

    async def put_commands(self, request: web.Request) -> web.Response:
        self.commands = await request.json()
        self.log.append(f"commands:{request.match_info['app']}")
        return web.json_response(self.commands)

    async def callback(self, request: web.Request) -> web.Response:
        # Эндпоинт ответа на взаимодействие токен бота не требует —
        # его заменяет токен взаимодействия в пути.
        self.callbacks.append({"id": request.match_info["id"],
                               "token": request.match_info["token"],
                               "body": await request.json(), "at": time.monotonic()})
        return web.Response(status=204)

    async def message(self, request: web.Request) -> web.Response:
        if not self.authed(request):
            return web.json_response({}, status=401)
        if not self.rate_limited:
            self.rate_limited = True
            return web.json_response({"message": "You are being rate limited.",
                                      "retry_after": 0.3, "global": False}, status=429)
        body = await request.json()
        self.messages.append(dict(body, channel=request.match_info["channel"]))
        return web.json_response({"id": str(len(self.messages)), **body})

    async def dm_channel(self, request: web.Request) -> web.Response:
        """Канал личной переписки (5.7): как `start_private_message` в discord.py."""
        if not self.authed(request):
            return web.json_response({}, status=401)
        body = await request.json()
        self.dm_requests.append(body)
        return web.json_response({"id": f"DM{body.get('recipient_id')}", "type": 1})

    async def script(self, ws: web.WebSocketResponse) -> None:
        """READY → пауза на сердцебиения → слеш-команда → RECONNECT."""
        await ws.send_json({"op": 0, "t": "READY", "s": 1, "d": {
            "session_id": "SESSION", "application": {"id": "A1"},
            "resume_gateway_url": self.base.replace("http", "ws") + "/resume"}})
        await asyncio.sleep(0.7)
        self.sent_at = time.monotonic()
        await ws.send_json({"op": 0, "t": "INTERACTION_CREATE", "s": 2, "d": {
            "id": "I1", "token": "ITOKEN", "type": 2, "channel_id": "55",
            "member": {"user": {"id": "42", "username": "u"}},
            "data": {"name": "status"}}})
        await asyncio.sleep(0.4)
        await ws.send_json({"op": 0, "t": "GUILD_CREATE", "s": 3, "d": {}})
        await asyncio.sleep(0.1)
        await ws.send_json({"op": 7, "d": None})

    async def gateway(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        number = self.connections
        resumed = request.path.startswith("/resume")
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": 250}})
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                break
            data = json.loads(frame.data)
            op = data.get("op")
            if op == 1:
                self.heartbeats += 1
                await ws.send_json({"op": 11})
            elif op == 2:
                if data["d"].get("token") != TOKEN:
                    await ws.close(code=4004)
                    break
                self.log.append(f"identify:intents={data['d'].get('intents')}")
                # Сценарий — отдельной задачей: цикл чтения должен и дальше
                # отвечать на сердцебиение, как настоящий Gateway.
                asyncio.ensure_future(self.script(ws))
            elif op == 6:
                self.resume_payload = data["d"]
                self.log.append(f"resume:{resumed}")
                await ws.send_json({"op": 0, "t": "RESUMED", "s": data["d"]["seq"] + 1, "d": {}})
                await asyncio.sleep(0.2)
                self.log.append("fatal")
                await ws.close(code=4004)
                self.done.set()
                break
        self.log.append(f"closed:{number}")
        return ws


class VerifyEmulator(Emulator):
    """Сервер для проверки участников (5.9.5): вступления, окно с вопросом,
    выдача роли, исключение и отказ в привилегированном намерении."""

    def __init__(self) -> None:
        super().__init__()
        self.identifies: list[int] = []
        self.kicked: list[str] = []
        self.roles: list[tuple[str, str]] = []
        self.young = ""
        self.old = ""

    def app(self) -> web.Application:
        app = super().app()
        app.router.add_delete("/api/v10/guilds/{guild}/members/{user}", self.kick)
        app.router.add_put("/api/v10/guilds/{guild}/members/{user}/roles/{role}", self.grant)
        return app

    async def kick(self, request: web.Request) -> web.Response:
        if not self.authed(request):
            return web.json_response({}, status=401)
        self.kicked.append(request.match_info["user"])
        return web.Response(status=204)

    async def grant(self, request: web.Request) -> web.Response:
        if not self.authed(request):
            return web.json_response({}, status=401)
        self.roles.append((request.match_info["user"], request.match_info["role"]))
        return web.Response(status=204)

    async def script(self, ws: web.WebSocketResponse) -> None:
        member = {"roles": [], "permissions": "0"}
        await ws.send_json({"op": 0, "t": "READY", "s": 1, "d": {
            "session_id": "S2", "application": {"id": "A1"},
            "resume_gateway_url": self.base.replace("http", "ws") + "/resume"}})
        await asyncio.sleep(0.3)
        for number, (uid, name) in enumerate(((self.young, "молодой"), (self.old, "старый"))):
            await ws.send_json({"op": 0, "t": "GUILD_MEMBER_ADD", "s": 2 + number, "d": {
                "guild_id": "G1", "user": {"id": uid, "username": name}}})
        await asyncio.sleep(0.3)
        await ws.send_json({"op": 0, "t": "INTERACTION_CREATE", "s": 5, "d": {
            "id": "I2", "token": "T2", "type": 3, "channel_id": "55", "guild_id": "G1",
            "member": dict(member, user={"id": self.old, "username": "старый"}),
            "data": {"custom_id": "dv:start"}}})
        await asyncio.sleep(0.4)
        pending = discordbot.GATE.pending.get(("G1", self.old))
        answer = pending.answer if pending else "?"
        await ws.send_json({"op": 0, "t": "INTERACTION_CREATE", "s": 6, "d": {
            "id": "I3", "token": "T3", "type": 5, "channel_id": "55", "guild_id": "G1",
            "member": dict(member, user={"id": self.old, "username": "старый"}),
            "data": {"custom_id": "dv:answer", "components": [
                {"type": 1, "components": [{"type": 4, "custom_id": "answer",
                                            "value": answer}]}]}}})
        await asyncio.sleep(0.4)
        await ws.close(code=4004)
        self.done.set()

    async def gateway(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": 250}})
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                break
            data = json.loads(frame.data)
            if data.get("op") == 1:
                await ws.send_json({"op": 11})
            elif data.get("op") == 2:
                intents = int(data["d"].get("intents") or 0)
                self.identifies.append(intents)
                if intents & discord.INTENT_MEMBERS and self.connections == 1:
                    # Привилегированное намерение не включено в Developer Portal.
                    await ws.close(code=4014)
                    break
                asyncio.ensure_future(self.script(ws))
        return ws


async def verify_checks() -> list[tuple[str, bool, str]]:
    """Проверка участников на эмуляторе: настоящий транспорт и обработчики."""
    import random

    from radar import discordverify, features, links, secrets

    emulator = VerifyEmulator()
    now = time.time()
    emulator.young = str((int((now - 86400) * 1000) - discordverify.DISCORD_EPOCH_MS) << 22)
    emulator.old = str((int((now - 90 * 86400) * 1000) - discordverify.DISCORD_EPOCH_MS) << 22)
    runner = web.AppRunner(emulator.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    emulator.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"  # noqa: SLF001

    values = {"DISCORD_VERIFY_ROLE_ID": "777", "DISCORD_MIN_ACCOUNT_DAYS": "3",
              "DISCORD_VERIFY_MINUTES": "10", "DISCORD_LOG_CHANNEL_ID": ""}

    async def no_link(platform, external_id):
        return ""

    discordbot.GATE = discordverify.Gate(rng=random.Random(7))
    transport = discord.DiscordTransport(TOKEN, discordbot.reply,
                                         member_events=True)

    async def member_added(data):
        await discordbot.on_member_add(data, transport)

    transport.member_handler = member_added
    features.set_local("discord_verify", True)
    try:
        with mock.patch.object(discord, "API", emulator.base + "/api/v10"), \
                mock.patch.object(discord.random, "random", lambda: 0.0), \
                mock.patch.object(secrets, "get", lambda key: values.get(key, "")), \
                mock.patch.object(links, "owner_of", no_link):
            await asyncio.wait_for(transport.start(), timeout=20)
    except asyncio.TimeoutError:
        pass
    finally:
        features.set_local("discord_verify", False)
        await transport.stop()
        await runner.cleanup()

    modal = next((item for item in emulator.callbacks if item["token"] == "T2"), {})
    modal_body = (modal.get("body") or {})
    fields = ((modal_body.get("data") or {}).get("components") or [{}])[0].get("components") or [{}]
    done = next((item for item in emulator.callbacks if item["token"] == "T3"), {})
    return [
        ("проверка: 4014 → откат намерений без остановки адаптера",
         len(emulator.identifies) >= 2 and bool(emulator.identifies[0] & discord.INTENT_MEMBERS)
         and not emulator.identifies[1] & discord.INTENT_MEMBERS
         and transport.members_denied,
         f"IDENTIFY: {emulator.identifies}"),
        ("проверка: молодой аккаунт исключён при вступлении, старый — нет",
         emulator.kicked == [emulator.young], f"исключены: {emulator.kicked}"),
        ("проверка: кнопка открывает окно (тип 9) с вопросом ≤ 45 знаков",
         modal_body.get("type") == 9
         and (modal_body.get("data") or {}).get("custom_id") == "dv:answer"
         and 0 < len(fields[0].get("label", "")) <= 45,
         f"{fields[0].get('label', '')!r}"),
        ("проверка: верный ответ из окна → роль выдана, ответ виден только ему",
         emulator.roles == [(emulator.old, "777")]
         and done.get("body", {}).get("data", {}).get("flags") == discord.EPHEMERAL,
         f"роли: {emulator.roles}"),
    ]


async def main() -> int:
    emulator = Emulator()
    runner = web.AppRunner(emulator.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    emulator.base = f"http://127.0.0.1:{port}"

    async def handler(event, transport):
        await transport.respond(event, discordbot.answer_for(event, status="✅ Мониторинг работает."))

    transport = discord.DiscordTransport(TOKEN, handler)
    checks: list[tuple[str, bool, str]] = []
    try:
        with mock.patch.object(discord, "API", emulator.base + "/api/v10"), \
                mock.patch.object(discord.random, "random", lambda: 0.0):
            await transport.set_commands(discordbot.COMMANDS)
            started = time.monotonic()
            await asyncio.wait_for(transport.start(), timeout=20)
            stopped_in = time.monotonic() - started
            send_ok = await transport.send("55", OutboundMessage(
                text="<b>Сводка</b> " + "x" * 2500))
            dm_ok = (await transport.send_text("42", "🚨 <b>Тревога</b>")
                     and await transport.send_text("42", "Отбой"))
    except asyncio.TimeoutError:
        checks.append(("адаптер остановился на коде 4004", False,
                       "за 20 с не остановился — переподключается в цикле"))
        stopped_in, send_ok, dm_ok = 0.0, False, False
    finally:
        await transport.stop()
        await runner.cleanup()

    names = [item["name"] for item in emulator.commands]
    address = next((item for item in emulator.commands if item["name"] == "address"), {})
    checks.append(("слеш-команды зарегистрированы, у /address — параметр",
                   "commands:A1" in emulator.log
                   and names == [item[0] for item in discordbot.COMMANDS]
                   and (address.get("options") or [{}])[0].get("type") == 3,
                   ", ".join(names)))
    checks.append(("IDENTIFY с токеном и намерениями GUILDS",
                   "identify:intents=1" in emulator.log, str(emulator.log[:2])))
    checks.append(("сердцебиение и подтверждения", emulator.heartbeats >= 2,
                   f"сердцебиений: {emulator.heartbeats}"))
    callback = emulator.callbacks[0] if emulator.callbacks else {}
    in_time = bool(callback) and callback["at"] - emulator.sent_at < 3
    checks.append(("ответ на слеш-команду через callback, в пределах 3 с",
                   in_time and callback.get("token") == "ITOKEN"
                   and callback["body"]["type"] == 4
                   and "работает" in callback["body"]["data"].get("content", ""),
                   f"{callback.get('body', {}).get('data', {}).get('content', '')[:40]!r}"))
    resume = emulator.resume_payload or {}
    checks.append(("RECONNECT → RESUME по resume_gateway_url",
                   "resume:True" in emulator.log and resume.get("session_id") == "SESSION"
                   and resume.get("seq") == 3,
                   f"{resume}"))
    checks.append(("код 4004 останавливает адаптер", 0 < stopped_in < 20 and "fatal" in emulator.log,
                   f"за {stopped_in:.1f} с"))
    channel_messages = [item for item in emulator.messages if item["channel"] == "55"]
    direct = [item for item in emulator.messages if item["channel"] == "DM42"]
    checks.append(("тревога в личку: канал создан один раз, оба сообщения дошли",
                   dm_ok and len(emulator.dm_requests) == 1
                   and emulator.dm_requests[0].get("recipient_id") == "42"
                   and len(direct) == 2 and direct[0]["content"] == "🚨 **Тревога**",
                   f"каналов: {len(emulator.dm_requests)}, сообщений: {len(direct)}"))
    checks.append(("429 → пауза и повтор, длинный текст разрезан",
                   send_ok and emulator.rate_limited and len(channel_messages) == 2
                   and all(len(m.get("content", "")) <= 2000 for m in channel_messages)
                   and channel_messages[0]["content"].startswith("**Сводка**"),
                   f"сообщений: {len(channel_messages)}"))

    checks.extend(await verify_checks())

    failures = 0
    print("Адаптер Discord по WebSocket и HTTP:\n")
    for title, ok, note in checks:
        failures += 0 if ok else 1
        print(f"  {'✅' if ok else '❌'} {title}: {note}")
    print("\nЭто проверка по эмулятору, написанному по исходникам discord.py, "
          "а не по настоящему Discord.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
