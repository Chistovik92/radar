"""HTTP-маршруты API для приложений (5.9.1). Логика — в `radar/appapi.py`.

Все ответы — JSON, ошибки — `{"error": "текст"}`. Работает в той же
веб-панели, что и остальное: нужны флаги `web_panel` (сервер) и `app_api`.
Пока `app_api` выключен, маршруты отвечают 404, как будто их нет.

| Метод   | Путь                     | Что делает                              |
|---------|--------------------------|-----------------------------------------|
| GET     | /api/v1/app/ping         | версия API и включён ли он              |
| POST    | /api/v1/app/link         | {code, device, app} -> {token, ...}     |
| GET     | /api/v1/app/me           | профиль и состояние VPN                 |
| GET     | /api/v1/app/subscriptions| подписки по выданным панелям            |
| DELETE  | /api/v1/app/session      | отключить это устройство                |
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from typing import Any

from .. import appapi, config

log = logging.getLogger("radar.web.appapi")

API_VERSION = 1
MAX_BODY = 4096


def _address(request: Any) -> str:
    # Как и у входа в панель: заголовку верим только за обратным прокси.
    if config.WEB_HTTPS:
        return request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    return request.remote or ""


def routes(web: Any) -> list[Any]:
    def reply(payload: dict[str, Any], status: int = 200) -> Any:
        # Ответы содержат ссылки подписок: посредникам их кэшировать нельзя.
        return web.json_response(payload, status=status,
                                 headers={"Cache-Control": "no-store"})

    def refuse(text: str, status: int) -> Any:
        return reply({"error": text}, status)

    def gate() -> Any:
        if not appapi.enabled():
            raise web.HTTPNotFound()

    async def authorised(request: Any) -> dict[str, Any] | Any:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return refuse("нужен заголовок Authorization: Bearer <токен>", 401)
        address = _address(request)
        from .auth import clear_failures, note_failure, rate_limited

        if address and rate_limited(address):
            return refuse("слишком много попыток, подождите", 429)
        session = await appapi.session_of(token.strip())
        if session is None:
            if address:
                note_failure(address)
            return refuse("токен не подошёл или отключён", 401)
        if address:
            clear_failures(address)
        return session

    async def ping(_request):
        gate()
        return reply({"api": API_VERSION, "service": "radar"})

    async def link(request):
        gate()
        if (request.content_length or 0) > MAX_BODY:
            return refuse("слишком большой запрос", 413)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return refuse("ожидается JSON", 400)
        if not isinstance(body, dict):
            return refuse("ожидается JSON-объект", 400)
        token, device_id, why = await appapi.exchange(
            str(body.get("code") or ""), str(body.get("device") or ""),
            str(body.get("app") or ""), _address(request))
        if not token:
            return refuse(why, 429 if "много" in why else 401)
        return reply({"token": token, "device_id": device_id}, 201)

    async def me(request):
        gate()
        session = await authorised(request)
        if not isinstance(session, dict):
            return session
        data = await appapi.profile(session["uid"])
        data["device"] = {"id": session.get("id"), "name": session.get("device"),
                          "app": session.get("app")}
        return reply(data)

    async def subscriptions(request):
        gate()
        session = await authorised(request)
        if not isinstance(session, dict):
            return session
        return reply({"subscriptions": await appapi.subscriptions(session["uid"])})

    async def logout(request):
        gate()
        session = await authorised(request)
        if not isinstance(session, dict):
            return session
        header = request.headers.get("Authorization", "")
        await appapi.revoke_token(header.partition(" ")[2].strip())
        return reply({"status": "revoked"})

    return [
        web.get("/api/v1/app/ping", ping),
        web.post("/api/v1/app/link", link),
        web.get("/api/v1/app/me", me),
        web.get("/api/v1/app/subscriptions", subscriptions),
        web.delete("/api/v1/app/session", logout),
    ]
