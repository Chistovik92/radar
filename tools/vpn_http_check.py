#!/usr/bin/env python3
"""Проверка VPN-клиентов по настоящему HTTP, без настоящих панелей (5.0.1).

Офлайн-тесты (`tests/test_vpn.py`) подменяют `_call` и проверяют разметку
запросов, но не транспорт: куки, CSRF, заголовки входа, JSON против
формы, закрепление сертификата, жизнь сессии. Здесь всё это идёт по
сети — на `127.0.0.1` поднимаются эмуляторы API десяти панелей, и через
них прогоняются настоящие клиенты из `radar/vpnpanels.py`, **все разом**,
а затем выдача через `radar/vpn.py` на все десять слотов одновременно.

Эмуляторы написаны по исходному коду панелей (сентябрь 2026) и повторяют
то, на что опирается клиент: пути, способ входа, форму тела и ответа,
коды ошибок. Это проверка согласованности клиента с прочитанным кодом
панелей и проверка транспорта. Это **не** проверка настоящих панелей:
их формат может разойтись с прочитанным — для этого есть
`python3 -m radar vpn selftest --yes` на сервере.

Нужен настоящий aiohttp (как в образе бота), поэтому скрипт запускается
отдельным процессом, а не внутри набора тестов с заглушками:

    python3 tools/vpn_http_check.py
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from aiohttp import web
except ImportError:  # pragma: no cover - зависит от окружения
    print("Нужен aiohttp: pip install aiohttp (в образе бота он есть).")
    sys.exit(2)

from radar import features, vpn, vpnpanels  # noqa: E402

TOKEN = "secret-token"
USER, PASSWORD = "admin", "pw"


def ok(obj: Any = None, msg: str = "") -> web.Response:
    return web.json_response({"success": True, "msg": msg, "obj": obj})


def fail(msg: str) -> web.Response:
    return web.json_response({"success": False, "msg": msg, "obj": None})


# --------------------------------------------------------------------------
#  Эмуляторы
# --------------------------------------------------------------------------

def xui_app(generation: int, legacy: bool = False) -> web.Application:
    """3x-ui 2.x/3.x и x-ui (alireza0): вход куки+CSRF или Bearer."""
    root = "/xui/API" if legacy else "/panel/api"
    state: dict[str, Any] = {"inbound": {"id": 1, "protocol": "vless", "clients": []},
                             "records": {}, "traffic": {}, "sessions": {}}

    def authed(request: web.Request, mutation: bool) -> bool:
        if not legacy and request.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        sid = request.cookies.get("sid")
        session = state["sessions"].get(sid)
        if not session or not session.get("user"):
            return False
        if mutation and generation == 3 and not legacy:
            return request.headers.get("X-CSRF-Token") == session.get("csrf")
        return True

    async def csrf(request: web.Request) -> web.Response:
        if legacy or generation == 2:
            raise web.HTTPNotFound()
        sid = request.cookies.get("sid") or uuid.uuid4().hex
        session = state["sessions"].setdefault(sid, {})
        session.setdefault("csrf", uuid.uuid4().hex)
        response = ok(session["csrf"])
        response.set_cookie("sid", sid)
        return response

    async def login(request: web.Request) -> web.Response:
        form = await request.post()
        sid = request.cookies.get("sid") or uuid.uuid4().hex
        session = state["sessions"].setdefault(sid, {})
        if generation == 3 and not legacy:
            # Как session.ValidateCSRFToken: пустой ожидаемый токен — отказ.
            expected = session.get("csrf")
            if not expected or request.headers.get("X-CSRF-Token") != expected:
                raise web.HTTPForbidden()
        if (form.get("username"), form.get("password")) != (USER, PASSWORD):
            return fail("wrong username or password")
        # Как в 3x-ui: вход создаёт новую сессию со своим токеном.
        new_sid = uuid.uuid4().hex
        state["sessions"][new_sid] = {"user": USER, "csrf": uuid.uuid4().hex}
        response = ok(None)
        response.set_cookie("sid", new_sid)
        return response

    def guard(handler, mutation=False):
        async def wrapped(request: web.Request) -> web.Response:
            if not authed(request, False):
                # Без входа 3x-ui прячет API: 404, а не 401.
                raise web.HTTPNotFound()
            if mutation and not authed(request, True):
                # CSRFMiddleware: вошёл, но без токена — 403.
                raise web.HTTPForbidden()
            return await handler(request)
        return wrapped

    async def get_inbound(request: web.Request) -> web.Response:
        inbound = state["inbound"]
        if int(request.match_info["id"]) != inbound["id"]:
            return fail("record not found")
        clients = inbound["clients"] if generation == 2 else [
            {"email": email, **rec} for email, rec in state["records"].items()]
        return ok({"id": inbound["id"], "protocol": inbound["protocol"],
                   "settings": json.dumps({"clients": clients})})

    # --- 2.x ---
    async def add_client(request: web.Request) -> web.Response:
        body = await request.json()
        for client in json.loads(body["settings"])["clients"]:
            if not isinstance(client.get("expiryTime"), int):
                return fail("bad expiryTime")
            if "tgId" in client and not isinstance(client["tgId"], (str if legacy else int)):
                return fail("json: cannot unmarshal tgId")
            state["inbound"]["clients"].append(client)
        return ok(None, "Client(s) added")

    async def update_client(request: web.Request) -> web.Response:
        body = await request.json()
        client = json.loads(body["settings"])["clients"][0]
        key = request.match_info["key"]
        for index, old in enumerate(state["inbound"]["clients"]):
            if old.get("id") == key or old.get("password") == key:
                state["inbound"]["clients"][index] = client
                return ok(None)
        return fail("client not found")

    async def traffic(request: web.Request) -> web.Response:
        email = request.match_info["email"]
        return ok({"email": email, "up": 100, "down": 23})

    # --- 3.x ---
    async def rec_get(request: web.Request) -> web.Response:
        email = request.match_info["email"]
        rec = state["records"].get(email)
        if rec is None:
            return fail("Ошибка получения: record not found")
        return ok({"client": {"email": email, **rec}, "inboundIds": [1], "usedTraffic": 123})

    async def rec_add(request: web.Request) -> web.Response:
        body = await request.json()
        client = dict(body["client"])
        if body.get("inboundIds") != [1]:
            return fail("inbound not found")
        email = client.pop("email")
        client["uuid"] = client.pop("id", "")
        state["records"][email] = client
        return ok(None)

    async def rec_update(request: web.Request) -> web.Response:
        email = request.match_info["email"]
        if email not in state["records"]:
            return fail("record not found")
        body = dict(await request.json())
        body.pop("email", None)
        body["uuid"] = body.pop("id", "")
        state["records"][email] = body  # правка заменяет целиком
        return ok(None)

    app = web.Application()
    app.router.add_get("/csrf-token", csrf)
    app.router.add_post("/login", login)
    app.router.add_get(root + "/inbounds/get/{id}", guard(get_inbound))
    if generation == 2:
        app.router.add_post(root + "/inbounds/addClient", guard(add_client, True))
        app.router.add_post(root + "/inbounds/updateClient/{key}", guard(update_client, True))
        app.router.add_get(root + "/inbounds/getClientTraffics/{email}", guard(traffic))
    else:
        app.router.add_get(root + "/clients/get/{email}", guard(rec_get))
        app.router.add_post(root + "/clients/add", guard(rec_add, True))
        app.router.add_post(root + "/clients/update/{email}", guard(rec_update, True))
    return app


def sui_app() -> web.Application:
    clients: dict[int, dict[str, Any]] = {}

    def authed(request: web.Request) -> bool:
        return request.headers.get("Token") == TOKEN

    async def get_action(request: web.Request) -> web.Response:
        if not authed(request):
            return fail("invalid token")
        if request.match_info["action"] != "clients":
            return fail("unknown action")
        wanted = request.query.get("id")
        if wanted:
            rows = [clients[int(item)] for item in wanted.split(",") if int(item) in clients]
        else:
            rows = [{key: value for key, value in item.items() if key not in ("config", "links")}
                    for item in clients.values()]
        return ok({"clients": rows})

    async def post_action(request: web.Request) -> web.Response:
        if not authed(request):
            return fail("invalid token")
        form = await request.post()
        data = json.loads(form["data"])
        if form["object"] != "clients":
            return fail("unknown object")
        if form["action"] == "new":
            if any(item["name"] == data["name"] for item in clients.values()):
                return fail("duplicate name")
            if "vless" not in (data.get("config") or {}):
                return fail("config missing")
            data["id"] = len(clients) + 1
        elif data.get("id") not in clients:
            return fail("record not found")
        clients[data["id"]] = data
        return ok({"clients": list(clients.values())})

    app = web.Application()
    app.router.add_get("/app/apiv2/{action}", get_action)
    app.router.add_post("/app/apiv2/save", post_action)
    return app


def marzban_app(flavor: str) -> web.Application:
    """Marzban, PasarGuard и Marzneshin: JWT по паролю, ключ API у PasarGuard."""
    users: dict[str, dict[str, Any]] = {}
    jwt = "eyJhbGciOi.eyJzdWIi.signature"
    base = "/api/users" if flavor == "marzneshin" else "/api/user"

    def authed(request: web.Request) -> bool:
        if request.headers.get("Authorization") == f"Bearer {jwt}":
            return True
        return flavor == "pasarguard" and request.headers.get("X-Api-Key") == TOKEN

    async def token(request: web.Request) -> web.Response:
        form = await request.post()
        if (form.get("username"), form.get("password")) != (USER, PASSWORD):
            return web.json_response({"detail": "Incorrect username or password"}, status=401)
        return web.json_response({"access_token": jwt, "token_type": "bearer"})

    def guard(handler):
        async def wrapped(request: web.Request) -> web.Response:
            if not authed(request):
                return web.json_response({"detail": "Not authenticated"}, status=401)
            return await handler(request)
        return wrapped

    def view(user: dict[str, Any]) -> web.Response:
        shown = dict(user)
        shown["used_traffic"] = 555
        shown["subscription_url"] = f"/sub/{user['username']}/token"
        return web.json_response(shown)

    async def create(request: web.Request) -> web.Response:
        body = await request.json()
        name = body["username"]
        if name in users:
            return web.json_response({"detail": "User already exists"}, status=409)
        if flavor == "marzban" and not body.get("proxies"):
            return web.json_response({"detail": "Each user needs at least one proxy"}, status=422)
        if flavor == "marzban" and not isinstance(body.get("expire"), int):
            return web.json_response({"detail": "expire must be int"}, status=422)
        if flavor == "marzneshin":
            body.setdefault("enabled", True)
        users[name] = body
        return view(body)

    async def get(request: web.Request) -> web.Response:
        user = users.get(request.match_info["name"])
        if user is None:
            return web.json_response({"detail": "User not found"}, status=404)
        return view(user)

    async def modify(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name not in users:
            return web.json_response({"detail": "User not found"}, status=404)
        body = await request.json()
        if flavor == "marzneshin" and body.get("username") != name:
            return web.json_response({"detail": "username required"}, status=422)
        for key, value in body.items():
            # null — «не менять», как во всех трёх.
            if value is not None:
                users[name][key] = value
        return view(users[name])

    async def toggle(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        users[name]["enabled"] = request.match_info["action"] == "enable"
        return view(users[name])

    async def admin(request: web.Request) -> web.Response:
        return web.json_response({"username": USER})

    app = web.Application()
    app.router.add_post("/api/admins/token" if flavor == "marzneshin" else "/api/admin/token",
                        token)
    app.router.add_get("/api/admins/current" if flavor == "marzneshin" else "/api/admin",
                       guard(admin))
    app.router.add_post(base, guard(create))
    app.router.add_get(base + "/{name}", guard(get))
    app.router.add_put(base + "/{name}", guard(modify))
    if flavor == "marzneshin":
        app.router.add_post(base + "/{name}/{action}", guard(toggle))
    return app


def remnawave_app() -> web.Application:
    users: dict[str, dict[str, Any]] = {}

    def authed(request: web.Request) -> bool:
        return (request.headers.get("Authorization") == f"Bearer {TOKEN}"
                and request.headers.get("X-Forwarded-Proto") == "https")

    def guard(handler):
        async def wrapped(request: web.Request) -> web.Response:
            if not authed(request):
                return web.json_response({"message": "Unauthorized"}, status=401)
            return await handler(request)
        return wrapped

    def wrap(user: dict[str, Any]) -> web.Response:
        return web.json_response({"response": {
            **user, "userTraffic": {"usedTrafficBytes": 777},
            "subscriptionUrl": f"https://sub.example/{user['shortUuid']}"}})

    async def create(request: web.Request) -> web.Response:
        body = await request.json()
        if not body.get("expireAt"):
            return web.json_response({"message": "expireAt required"}, status=400)
        user = {**body, "id": len(users) + 1, "shortUuid": uuid.uuid4().hex[:8]}
        users[body["username"]] = user
        return wrap(user)

    async def by_name(request: web.Request) -> web.Response:
        user = users.get(request.match_info["name"])
        if user is None:
            return web.json_response({"message": "User not found"}, status=404)
        return wrap(user)

    async def patch(request: web.Request) -> web.Response:
        body = await request.json()
        user = users.get(body.get("username") or "")
        if user is None:
            return web.json_response({"message": "At least one of username, id"}, status=400)
        user.update({k: v for k, v in body.items() if k not in ("username", "uuid")})
        return wrap(user)

    async def action(request: web.Request) -> web.Response:
        user_id = int(request.match_info["id"])
        for user in users.values():
            if user["id"] == user_id:
                user["status"] = "ACTIVE" if request.match_info["act"] == "enable" else "DISABLED"
                return wrap(user)
        return web.json_response({"message": "User not found"}, status=404)

    app = web.Application()
    app.router.add_post("/api/users", guard(create))
    app.router.add_patch("/api/users", guard(patch))
    app.router.add_get("/api/users/by-username/{name}", guard(by_name))
    app.router.add_post("/api/users/{id}/actions/{act}", guard(action))
    return app


def hiddify_app() -> web.Application:
    users: dict[str, dict[str, Any]] = {}
    prefix = "/adminpath/api/v2/admin"

    def guard(handler):
        async def wrapped(request: web.Request) -> web.Response:
            if request.headers.get("Hiddify-API-Key") != TOKEN:
                return web.json_response({"msg": "unauthorized"}, status=401)
            return await handler(request)
        return wrapped

    async def me(request: web.Request) -> web.Response:
        return web.json_response({"name": "owner"})

    async def create(request: web.Request) -> web.Response:
        body = await request.json()
        body.setdefault("current_usage_GB", 0.5)
        users[body["uuid"]] = body
        return web.json_response(body)

    async def get(request: web.Request) -> web.Response:
        user = users.get(request.match_info["uuid"])
        if user is None:
            return web.json_response({"msg": "not found"}, status=404)
        return web.json_response(user)

    async def patch(request: web.Request) -> web.Response:
        user = users.get(request.match_info["uuid"])
        if user is None:
            return web.json_response({"msg": "not found"}, status=404)
        user.update(await request.json())
        return web.json_response(user)

    app = web.Application()
    app.router.add_get(prefix + "/me/", guard(me))
    app.router.add_post(prefix + "/user/", guard(create))
    app.router.add_get(prefix + "/user/{uuid}/", guard(get))
    app.router.add_patch(prefix + "/user/{uuid}/", guard(patch))
    return app


def outline_app() -> web.Application:
    keys: dict[str, dict[str, Any]] = {}
    prefix = "/SeCrEt"

    async def server(request: web.Request) -> web.Response:
        return web.json_response({"name": "Outline Test"})

    async def put_key(request: web.Request) -> web.Response:
        key_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        key = {"id": key_id, "name": body.get("name", ""), "port": 443,
               "method": "chacha20-ietf-poly1305",
               "accessUrl": f"ss://{base64.b64encode(key_id.encode()).decode()}@127.0.0.1:443/?outline=1"}
        if "limit" in body:
            key["dataLimit"] = body["limit"]
        keys[key_id] = key
        return web.json_response(key, status=201)

    async def get_key(request: web.Request) -> web.Response:
        key = keys.get(request.match_info["id"])
        if key is None:
            return web.json_response({"code": "NotFound"}, status=404)
        return web.json_response(key)

    async def limit(request: web.Request) -> web.Response:
        key = keys[request.match_info["id"]]
        if request.method == "PUT":
            key["dataLimit"] = (await request.json())["limit"]
        else:
            key.pop("dataLimit", None)
        return web.Response(status=204)

    async def transfer(request: web.Request) -> web.Response:
        return web.json_response({"bytesTransferredByUserId": {k: 4096 for k in keys}})

    app = web.Application()
    app.router.add_get(prefix + "/server", server)
    app.router.add_put(prefix + "/access-keys/{id}", put_key)
    app.router.add_get(prefix + "/access-keys/{id}", get_key)
    app.router.add_put(prefix + "/access-keys/{id}/data-limit", limit)
    app.router.add_delete(prefix + "/access-keys/{id}/data-limit", limit)
    app.router.add_get(prefix + "/metrics/transfer", transfer)
    return app


def wgeasy_app() -> web.Application:
    clients: dict[int, dict[str, Any]] = {}
    expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()

    def guard(handler):
        async def wrapped(request: web.Request) -> web.Response:
            if request.headers.get("Authorization") != expected:
                return web.json_response({"statusMessage": "Unauthorized"}, status=401)
            return await handler(request)
        return wrapped

    async def listing(request: web.Request) -> web.Response:
        return web.json_response(list(clients.values()))

    async def create(request: web.Request) -> web.Response:
        body = await request.json()
        client_id = len(clients) + 1
        clients[client_id] = {"id": client_id, "name": body["name"], "enabled": True,
                              "expiresAt": body.get("expiresAt"), "ipv4Address": f"10.8.0.{client_id + 1}",
                              "mtu": 1420, "transferRx": 10, "transferTx": 20, "oneTimeLink": None}
        return web.json_response({"success": True, "clientId": client_id})

    async def get(request: web.Request) -> web.Response:
        return web.json_response(clients[int(request.match_info["id"])])

    async def update(request: web.Request) -> web.Response:
        body = await request.json()
        client = clients[int(request.match_info["id"])]
        for field in ("name", "enabled", "expiresAt", "ipv4Address", "mtu"):
            if field not in body:
                return web.json_response({"statusMessage": f"{field} required"}, status=400)
        client.update({k: body[k] for k in ("name", "enabled", "expiresAt", "ipv4Address", "mtu")})
        return web.json_response({"success": True})

    async def toggle(request: web.Request) -> web.Response:
        client = clients[int(request.match_info["id"])]
        client["enabled"] = request.match_info["act"] == "enable"
        return web.json_response({"success": True})

    async def one_time(request: web.Request) -> web.Response:
        clients[int(request.match_info["id"])]["oneTimeLink"] = {"oneTimeLink": uuid.uuid4().hex}
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_get("/api/client", guard(listing))
    app.router.add_post("/api/client", guard(create))
    app.router.add_get("/api/client/{id}", guard(get))
    app.router.add_post("/api/client/{id}", guard(update))
    app.router.add_post("/api/client/{id}/generateOneTimeLink", guard(one_time))
    app.router.add_post("/api/client/{id}/{act}", guard(toggle))
    return app


# --------------------------------------------------------------------------
#  Запуск
# --------------------------------------------------------------------------

def self_signed(directory: str) -> tuple[ssl.SSLContext, str]:
    """Самоподписанный сертификат для Outline и его SHA-256 — как certSha256."""
    cert, key = os.path.join(directory, "cert.pem"), os.path.join(directory, "key.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key, "-out", cert, "-days", "1", "-subj", "/CN=127.0.0.1"],
                   check=True, capture_output=True)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert, key)
    der = ssl.PEM_cert_to_DER_cert(Path(cert).read_text())
    return context, hashlib.sha256(der).hexdigest().upper()


async def serve(app: web.Application, context: ssl.SSLContext | None = None
                ) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
    return runner, f"{'https' if context else 'http'}://127.0.0.1:{port}"


async def build_panels(tmp: str) -> tuple[list[web.AppRunner], dict[str, vpnpanels.Panel]]:
    tls, fingerprint = self_signed(tmp)
    specs = [
        ("3x-ui 3.x (Bearer)", xui_app(3), None,
         lambda url: vpnpanels.XuiPanel(url, token=TOKEN, inbound=1, sub_url=url + "/sub")),
        ("3x-ui 3.x (пароль+CSRF)", xui_app(3), None,
         lambda url: vpnpanels.XuiPanel(url, user=USER, password=PASSWORD, inbound=1,
                                        sub_url=url + "/sub")),
        ("3x-ui 2.x (пароль)", xui_app(2), None,
         lambda url: vpnpanels.XuiPanel(url, user=USER, password=PASSWORD, inbound=1,
                                        sub_url=url + "/sub")),
        ("x-ui alireza0", xui_app(2, legacy=True), None,
         lambda url: vpnpanels.XuiLegacyPanel(url, user=USER, password=PASSWORD, inbound=1,
                                              sub_url=url + "/sub")),
        ("s-ui", sui_app(), None,
         lambda url: vpnpanels.SuiPanel(url + "/app", token=TOKEN, groups=("1",),
                                        sub_url=url + "/sub")),
        ("Marzban (пароль)", marzban_app("marzban"), None,
         lambda url: vpnpanels.MarzbanPanel(url, user=USER, password=PASSWORD)),
        ("PasarGuard (ключ API)", marzban_app("pasarguard"), None,
         lambda url: vpnpanels.PasarGuardPanel(url, token=TOKEN, groups=("1",))),
        ("Marzneshin (пароль)", marzban_app("marzneshin"), None,
         lambda url: vpnpanels.MarzneshinPanel(url, user=USER, password=PASSWORD, groups=("1",))),
        ("Remnawave", remnawave_app(), None,
         lambda url: vpnpanels.RemnawavePanel(url, token=TOKEN, groups=("sq",))),
        ("Hiddify", hiddify_app(), None,
         lambda url: vpnpanels.HiddifyPanel(url + "/adminpath", token=TOKEN,
                                            sub_url=url + "/clientpath")),
        ("Outline (TLS, отпечаток)", outline_app(), tls,
         lambda url: vpnpanels.OutlinePanel(url + "/SeCrEt", cert=fingerprint)),
        ("wg-easy", wgeasy_app(), None,
         lambda url: vpnpanels.WgEasyPanel(url, user=USER, password=PASSWORD)),
    ]
    runners, panels = [], {}
    for title, app, context, factory in specs:
        runner, url = await serve(app, context)
        runners.append(runner)
        panels[title] = factory(url)
    # Отпечаток чужого сертификата должен отказывать, а не пропускать.
    panels["Outline (чужой отпечаток)"] = vpnpanels.OutlinePanel(
        panels["Outline (TLS, отпечаток)"].url, cert="00" * 32)
    return runners, panels


async def run_panels(panels: dict[str, vpnpanels.Panel]) -> dict[str, tuple[bool, str]]:
    async def one(title: str, panel: vpnpanels.Panel) -> tuple[bool, str]:
        try:
            notes = await vpn.selftest_panel(panel)
            return True, "; ".join(notes)
        except vpnpanels.PanelError as exc:
            return False, f"PanelError: {exc}"
        except AssertionError as exc:
            return False, f"проверка не прошла: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    results = await asyncio.gather(*(one(t, p) for t, p in panels.items()))
    return dict(zip(panels, results))


async def run_issue(panels: dict[str, vpnpanels.Panel]) -> tuple[bool, str]:
    """Выдача через radar/vpn.py на все панели сразу, как нажмёт суперадминистратор."""
    usable = [panel for title, panel in panels.items() if "чужой" not in title]
    fresh = [type(p)(p.url, token=p.token, user=p.user, password=p.password,
                     groups=p.groups, inbound=p.inbound, sub_url=p.sub_url, cert=p.cert)
             for p in usable]
    slots = [vpn.Slot(index + 1, p.title, p) for index, p in enumerate(fresh)]
    meta: dict[str, Any] = {}

    async def meta_get(key, default=None):
        return json.loads(json.dumps(meta.get(key, default)))

    async def meta_set(key, value):
        meta[key] = json.loads(json.dumps(value))

    # Хранилище бота тянет базу данных; здесь хватает таблицы в памяти.
    import radar
    import types

    storage = types.ModuleType("radar.storage")
    storage.meta_get = meta_get
    storage.meta_set = meta_set

    features.set_local("vpn", True)
    with mock.patch.object(vpn, "SLOTS", len(slots)), \
            mock.patch.object(vpn, "slots", lambda: slots), \
            mock.patch.object(vpn, "_setting", lambda key: ""), \
            mock.patch.dict(sys.modules, {"radar.storage": storage}), \
            mock.patch.object(radar, "storage", storage, create=True):
        try:
            await vpn.issue("7", [s.key for s in slots], "1", "admin")
            return False, "администратор смог выдать — так быть не должно"
        except vpnpanels.PanelError:
            pass
        await vpn.request("7")
        started = time.monotonic()
        results = await vpn.issue("7", [s.key for s in slots], "1", "superadmin")
        spent = time.monotonic() - started
        failed = {k: str(v) for k, v in results.items() if isinstance(v, vpnpanels.PanelError)}
        if failed:
            return False, f"выдача не прошла: {failed}"
        again = await vpn.issue("7", [s.key for s in slots], "1", "superadmin")
        for key in results:
            if results[key].subscription_url and again[key].subscription_url \
                    and slots[int(key) - 1].client.link_kind != "config":
                assert results[key].subscription_url == again[key].subscription_url, key
        statuses = await vpn.statuses("7")
        broken = [k for k, v in statuses.items() if not isinstance(v, vpnpanels.Account)]
        if broken:
            return False, f"состояние не прочитано на слотах {broken}"
        for slot in slots:
            if slot.client.supports_expiry:
                await vpn.extend("7", slot.key, 5, "superadmin")
        await vpn.revoke("7", slots[0].key, "superadmin")
        left = vpn.issued_slots(await vpn.record("7"))
        if slots[0].key in left or len(left) != len(slots) - 1:
            return False, f"отзыв не сработал: {left}"
        if "https://" in json.dumps(meta) or "ss://" in json.dumps(meta):
            return False, "ссылка попала в базу"
    return True, (f"{len(slots)} панелей: выдача параллельно за {spent:.2f} с, повторная "
                  f"выдача вернула те же ключи, продление, отзыв — в порядке")


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        runners, panels = await build_panels(tmp)
        try:
            results = await run_panels(panels)
            issue_ok, issue_note = await run_issue(panels)
        finally:
            for runner in runners:
                await runner.cleanup()

    failures = 0
    print("Клиенты VPN-панелей по HTTP, все одновременно:\n")
    for title, (passed, note) in results.items():
        expected_fail = "чужой" in title
        good = passed != expected_fail
        failures += 0 if good else 1
        mark = "✅" if good else "❌"
        if expected_fail and not passed:
            note = "отказ, как и должно быть: " + note
        print(f"  {mark} {title}: {note}")
    print(f"\n  {'✅' if issue_ok else '❌'} radar/vpn.py: {issue_note}")
    failures += 0 if issue_ok else 1
    print("\nЭто проверка по эмуляторам, написанным по исходникам панелей, "
          "а не по настоящим панелям.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
