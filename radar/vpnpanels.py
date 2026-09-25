"""Единый слой поверх VPN-панелей: 3x-ui, PasarGuard, Remnawave (с 5.0).

Раздел продаж и выдачи не знает, какая панель стоит на сервере: он зовёт
шесть действий — завести, найти, сдвинуть срок, сменить лимит трафика,
выключить и включить — и получает одну и ту же запись `Account`. Смена
панели на сервере — это смена `VPN_PANEL` в `.env`, а не переписывание
раздела.

**SDK не тянем.** У Remnawave есть официальный `remnawave-api`, но он
приносит `httpx`, `pydantic`, `orjson` и ещё два пакета на машину, где
весь бот живёт в 512 МБ. Нужные вызовы укладываются в `aiohttp`,
который уже есть.

**Ключи — не в журналах.** UUID клиента, ссылка подписки и токен панели
в журнал не пишутся ни при успехе, ни при ошибке: в сообщение об ошибке
идёт статус и текст панели, но не то, что мы ей отправили.

⚠️ Клиенты написаны по документации панелей и не проверялись на живом
сервере. Разбор ответов закреплён офлайн-тестами, но формат ответа
панели меняется от выпуска к выпуску, и первая проверка — кнопка
«Проверить панель» в разделе.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import re
import secrets as pysecrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("radar.vpnpanels")

TIMEOUT = 20
GB = 1024 ** 3

# Remnawave не принимает пользователя без срока: «бессрочно» у неё —
# это дата далеко впереди. Всё, что дальше этого года, считаем бессрочным.
FOREVER_YEAR = 2099

# Имя учётной записи уходит в URL панели и в её интерфейс. Самое узкое
# из трёх правил — у Remnawave: латиница, цифры, дефис и подчёркивание,
# от 3 до 36 знаков.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,36}$")


class PanelError(Exception):
    """Отказ панели, понятный человеку. Секретов в тексте нет."""


@dataclass(frozen=True)
class Account:
    """Учётная запись в панели, одинаковая для всех трёх."""

    name: str
    enabled: bool
    expire: int = 0            # unix-время окончания, 0 — бессрочно
    traffic_limit: int = 0     # байты, 0 — без предела
    traffic_used: int = 0      # байты
    subscription_url: str = ""


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.fullmatch(name or ""))


def account_name(uid: str | int) -> str:
    """Имя учётной записи для пользователя бота.

    Выводится из ключа пользователя детерминированно: повторная выдача
    находит ту же запись, а не заводит вторую. Недопустимые знаки
    (двоеточие в ключах MAX) заменяются подчёркиванием.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(uid))
    return f"radar_{cleaned}"[:36]


# --------------------------------------------------------------------------
#  Время: у каждой панели свой формат
# --------------------------------------------------------------------------

def to_iso(ts: int) -> str:
    """unix-время → ISO 8601 в UTC. 0 — «бессрочно» в виде далёкой даты."""
    if not ts:
        return f"{FOREVER_YEAR}-12-31T00:00:00.000Z"
    moment = datetime.fromtimestamp(int(ts), timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_time(value: Any) -> int:
    """Срок из ответа панели → unix-время; 0 — бессрочно или не указан.

    Встречаются: секунды (Marzban-наследие), миллисекунды (3x-ui),
    ISO-строка с «Z» или смещением (PasarGuard, Remnawave), None.
    """
    if value in (None, "", 0):
        return 0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
        if number <= 0:
            return 0
        # Всё, что больше 10^11, — миллисекунды: в секундах это 5138 год.
        return number // 1000 if number > 10 ** 11 else number
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return parse_time(int(text))
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if moment.year >= FOREVER_YEAR:
        return 0
    return int(moment.timestamp())


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
#  Общая часть
# --------------------------------------------------------------------------

class Panel:
    """Общий интерфейс. Наследники задают разметку запросов и разбор ответов.

    Каждое действие открывает свою сессию: вызовы редкие (их нажимает
    человек), а долгоживущая сессия с куками панели — ещё одно состояние,
    которое надо чинить после перезапуска панели.
    """

    kind = ""
    title = ""

    def __init__(self, url: str, *, token: str = "", user: str = "",
                 password: str = "", groups: tuple[str, ...] = (),
                 inbound: int = 0, sub_url: str = "") -> None:
        self.url = (url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.user = (user or "").strip()
        self.password = password or ""
        self.groups = tuple(item for item in groups if item)
        self.inbound = int(inbound or 0)
        self.sub_url = (sub_url or "").strip().rstrip("/")

    # --- то, что обязаны задать наследники ---

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        raise NotImplementedError

    async def get_user(self, name: str) -> Account | None:
        raise NotImplementedError

    async def set_expiry(self, name: str, expire: int) -> None:
        raise NotImplementedError

    async def set_traffic(self, name: str, traffic: int) -> None:
        raise NotImplementedError

    async def disable(self, name: str) -> None:
        raise NotImplementedError

    async def enable(self, name: str) -> None:
        raise NotImplementedError

    async def check(self) -> str:
        """Отвечает ли панель и принимает ли вход. Строка — для человека."""
        raise NotImplementedError

    def problems(self) -> list[str]:
        """Чего не хватает в настройках. Пусто — можно обращаться."""
        missing = []
        if not self.url:
            missing.append("VPN_PANEL_URL")
        if not self.token and not (self.user and self.password):
            missing.append("VPN_PANEL_TOKEN или VPN_PANEL_USER с VPN_PANEL_PASS")
        return missing

    async def subscription_url(self, name: str) -> str:
        account = await self.get_user(name)
        if account is None:
            raise PanelError("Учётной записи в панели нет.")
        if not account.subscription_url:
            raise PanelError("Панель не сообщила ссылку подписки.")
        return account.subscription_url

    # --- обмен с панелью ---

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _login(self, session: Any, headers: dict[str, str]) -> None:
        """Вход по логину и паролю, если токена нет. По умолчанию не нужен."""

    async def _call(self, method: str, path: str, *, body: Any = None,
                    form: dict[str, str] | None = None,
                    missing_ok: bool = False) -> Any:
        """Запрос к панели. Возвращает разобранный JSON или None на 404
        при `missing_ok`. Любая другая неудача — `PanelError`."""
        import aiohttp

        problems = self.problems()
        if problems:
            raise PanelError("Панель не настроена: " + ", ".join(problems) + ".")

        url = f"{self.url}/{path.lstrip('/')}"
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        # unsafe=True: без него aiohttp не хранит куки, выданные адресом
        # по IP, а 3x-ui внутри домашней сети открывают именно так.
        jar = aiohttp.CookieJar(unsafe=True)
        headers = self._headers()
        try:
            async with aiohttp.ClientSession(timeout=timeout,
                                             cookie_jar=jar) as session:
                await self._login(session, headers)
                async with session.request(method, url, json=body, data=form,
                                           headers=headers) as response:
                    status = response.status
                    text = await response.text()
        except PanelError:
            raise
        except aiohttp.ClientError as exc:
            log.warning("Панель %s недоступна: %s", self.kind, type(exc).__name__)
            raise PanelError("Панель не отвечает — проверьте адрес и что она запущена.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Сбой обращения к панели %s: %s", self.kind, type(exc).__name__)
            raise PanelError("Обращение к панели не удалось.")

        if status == 404 and missing_ok:
            return None
        if status in (401, 403):
            raise PanelError("Панель не приняла вход: проверьте токен или пароль.")
        payload: Any = None
        if text:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
        if status >= 400:
            raise PanelError(f"Панель ответила HTTP {status}: {_detail(payload)}")
        if payload is None:
            raise PanelError("Панель ответила не JSON — возможно, неверный адрес "
                             "или путь панели.")
        return payload


def _detail(payload: Any) -> str:
    """Текст ошибки из ответа панели, коротко."""
    if isinstance(payload, dict):
        for key in ("msg", "message", "detail", "error"):
            value = payload.get(key)
            if value:
                return str(value)[:200]
    return "без пояснения"


# --------------------------------------------------------------------------
#  3x-ui
# --------------------------------------------------------------------------

class XuiPanel(Panel):
    """3x-ui: клиенты живут внутри входящего подключения (inbound).

    Клиент задаётся целиком: чтобы сдвинуть срок, надо прочитать его
    из настроек подключения, поменять поле и отправить весь объект
    обратно — отдельного «продлить» у панели нет.
    """

    kind = "3xui"
    title = "3x-ui"

    # Протоколы, у которых клиент определяется одним полем. Shadowsocks
    # не берём: у методов 2022 года пароль — ключ строгой длины, и выдать
    # его вслепую, не зная метода подключения, значит выдать нерабочий.
    _KEY_FIELD = {"vless": "id", "vmess": "id", "trojan": "password"}

    def problems(self) -> list[str]:
        missing = super().problems()
        if self.inbound <= 0:
            missing.append("VPN_XUI_INBOUND")
        return missing

    async def _login(self, session: Any, headers: dict[str, str]) -> None:
        if self.token:
            return
        async with session.post(f"{self.url}/login", data={
            "username": self.user, "password": self.password,
        }) as response:
            text = await response.text()
        try:
            ok = bool(json.loads(text).get("success"))
        except (ValueError, AttributeError):
            ok = False
        if not ok:
            raise PanelError("3x-ui не приняла логин или пароль.")

    async def _api(self, method: str, path: str, **kwargs: Any) -> Any:
        payload = await self._call(method, path, **kwargs)
        if not isinstance(payload, dict) or not payload.get("success"):
            raise PanelError(f"3x-ui отказала: {_detail(payload)}")
        return payload.get("obj")

    async def _inbound(self) -> tuple[str, list[dict[str, Any]]]:
        """Протокол подключения и список его клиентов."""
        obj = await self._api("GET", f"panel/api/inbounds/get/{self.inbound}")
        if not isinstance(obj, dict):
            raise PanelError("3x-ui не нашла подключение VPN_XUI_INBOUND.")
        return str(obj.get("protocol") or ""), parse_xui_clients(obj.get("settings"))

    async def _find(self, name: str) -> tuple[str, dict[str, Any] | None]:
        protocol, clients = await self._inbound()
        for client in clients:
            if client.get("email") == name:
                return protocol, client
        return protocol, None

    def _key_field(self, protocol: str) -> str:
        field = self._KEY_FIELD.get(protocol)
        if field is None:
            raise PanelError(f"Протокол подключения «{protocol or '?'}» не поддерживается: "
                             "нужен vless, vmess или trojan.")
        return field

    async def _update(self, protocol: str, client: dict[str, Any]) -> None:
        key = client.get(self._key_field(protocol)) or ""
        await self._api("POST", f"panel/api/inbounds/updateClient/{key}",
                        body=xui_client_body(self.inbound, client))

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        protocol, existing = await self._find(name)
        if existing is not None:
            raise PanelError("Такая учётная запись в панели уже есть.")
        client = new_xui_client(name, protocol, self._key_field(protocol),
                                expire, traffic)
        await self._api("POST", "panel/api/inbounds/addClient",
                        body=xui_client_body(self.inbound, client))
        return xui_account(client, None, self.sub_url)

    async def get_user(self, name: str) -> Account | None:
        _, client = await self._find(name)
        if client is None:
            return None
        traffic = await self._api(
            "GET", f"panel/api/inbounds/getClientTraffics/{name}")
        return xui_account(client, traffic if isinstance(traffic, dict) else None,
                           self.sub_url)

    async def _change(self, name: str, **fields: Any) -> None:
        protocol, client = await self._find(name)
        if client is None:
            raise PanelError("Учётной записи в панели нет.")
        client = dict(client)
        client.update(fields)
        await self._update(protocol, client)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._change(name, expiryTime=int(expire) * 1000 if expire else 0)

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._change(name, totalGB=int(traffic))

    async def disable(self, name: str) -> None:
        await self._change(name, enable=False)

    async def enable(self, name: str) -> None:
        await self._change(name, enable=True)

    async def subscription_url(self, name: str) -> str:
        if not self.sub_url:
            raise PanelError("Не задан VPN_SUB_URL — адрес подписки 3x-ui, "
                             "например https://example.ru:2096/sub.")
        return await super().subscription_url(name)

    async def check(self) -> str:
        protocol, clients = await self._inbound()
        self._key_field(protocol)
        note = f"3x-ui отвечает, подключение {self.inbound}: {protocol}, клиентов {len(clients)}"
        if not self.sub_url:
            note += "; ⚠️ VPN_SUB_URL не задан — ссылку подписки выдать не получится"
        return note


def parse_xui_clients(settings: Any) -> list[dict[str, Any]]:
    """Клиенты из поля settings подключения: там JSON строкой."""
    if isinstance(settings, str):
        try:
            settings = json.loads(settings or "{}")
        except ValueError:
            return []
    if not isinstance(settings, dict):
        return []
    clients = settings.get("clients")
    return [item for item in clients if isinstance(item, dict)] if isinstance(clients, list) else []


def new_xui_client(name: str, protocol: str, key_field: str,
                   expire: int, traffic: int) -> dict[str, Any]:
    client: dict[str, Any] = {
        "email": name,
        "limitIp": 0,
        # Поле названо totalGB, но хранит байты — так в самой 3x-ui.
        "totalGB": int(traffic),
        "expiryTime": int(expire) * 1000 if expire else 0,
        "enable": True,
        "tgId": "",
        "subId": pysecrets.token_hex(8),
        "reset": 0,
    }
    if key_field == "password":
        client["password"] = pysecrets.token_urlsafe(18)
    else:
        client["id"] = str(uuid.uuid4())
        if protocol == "vless":
            client["flow"] = ""
    return client


def xui_client_body(inbound: int, client: dict[str, Any]) -> dict[str, Any]:
    """Тело addClient и updateClient: клиенты — JSON строкой внутри JSON."""
    return {"id": int(inbound), "settings": json.dumps({"clients": [client]})}


def xui_account(client: dict[str, Any], traffic: dict[str, Any] | None,
                sub_url: str) -> Account:
    used = 0
    if traffic:
        used = _int(traffic.get("up")) + _int(traffic.get("down"))
    sub_id = str(client.get("subId") or "")
    return Account(
        name=str(client.get("email") or ""),
        enabled=bool(client.get("enable", True)),
        expire=parse_time(client.get("expiryTime")),
        traffic_limit=_int(client.get("totalGB")),
        traffic_used=used,
        subscription_url=f"{sub_url}/{sub_id}" if sub_url and sub_id else "",
    )


# --------------------------------------------------------------------------
#  PasarGuard
# --------------------------------------------------------------------------

class PasarGuardPanel(Panel):
    """PasarGuard (линия Marzban): пользователь по имени, доступ — группами."""

    kind = "pasarguard"
    title = "PasarGuard"

    async def _login(self, session: Any, headers: dict[str, str]) -> None:
        if self.token:
            return
        async with session.post(f"{self.url}/api/admin/token", data={
            "username": self.user, "password": self.password,
        }) as response:
            text = await response.text()
        try:
            token = json.loads(text).get("access_token")
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise PanelError("PasarGuard не приняла логин или пароль.")
        headers["Authorization"] = f"Bearer {token}"

    def _groups(self) -> list[int]:
        ids = []
        for item in self.groups:
            if str(item).strip().isdigit():
                ids.append(int(item))
        return ids

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {
            "username": name,
            "status": "active",
            "expire": to_iso(expire) if expire else None,
            "data_limit": int(traffic),
            "data_limit_reset_strategy": "no_reset",
            "group_ids": self._groups(),
            "proxy_settings": {},
        }
        return pasarguard_account(await self._call("POST", "api/user", body=body),
                                  self.url)

    async def get_user(self, name: str) -> Account | None:
        payload = await self._call("GET", f"api/user/{name}", missing_ok=True)
        return pasarguard_account(payload, self.url) if payload else None

    async def _modify(self, name: str, body: dict[str, Any]) -> None:
        await self._call("PUT", f"api/user/{name}", body=body)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._modify(name, {"expire": to_iso(expire) if expire else None})

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._modify(name, {"data_limit": int(traffic)})

    async def disable(self, name: str) -> None:
        await self._modify(name, {"status": "disabled"})

    async def enable(self, name: str) -> None:
        await self._modify(name, {"status": "active"})

    async def check(self) -> str:
        payload = await self._call("GET", "api/admin")
        who = payload.get("username") if isinstance(payload, dict) else ""
        note = f"PasarGuard отвечает, вход как {who or 'администратор'}"
        if not self._groups():
            note += "; ⚠️ VPN_GROUPS пуст — новым записям не назначатся группы"
        return note


def pasarguard_account(payload: Any, base_url: str) -> Account:
    if not isinstance(payload, dict):
        raise PanelError("PasarGuard ответила непонятно.")
    link = str(payload.get("subscription_url") or "")
    # Панель отдаёт путь без адреса, если в её настройках адрес
    # подписки не задан: дописываем свой, иначе ссылка не откроется.
    if link.startswith("/"):
        link = f"{base_url}{link}"
    return Account(
        name=str(payload.get("username") or ""),
        enabled=str(payload.get("status") or "").lower() in ("active", "on_hold"),
        expire=parse_time(payload.get("expire")),
        traffic_limit=_int(payload.get("data_limit")),
        traffic_used=_int(payload.get("used_traffic")),
        subscription_url=link,
    )


# --------------------------------------------------------------------------
#  Remnawave
# --------------------------------------------------------------------------

class RemnawavePanel(Panel):
    """Remnawave: пользователь — это uuid, доступ — внутренние «отряды»."""

    kind = "remnawave"
    title = "Remnawave"

    def problems(self) -> list[str]:
        missing = []
        if not self.url:
            missing.append("VPN_PANEL_URL")
        # Входа по паролю у API Remnawave нет: только токен из раздела
        # API Tokens.
        if not self.token:
            missing.append("VPN_PANEL_TOKEN")
        return missing

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        # Бэкенд Remnawave, вызванный напрямую по HTTP внутри сети Docker,
        # отказывает без этих заголовков: он ждёт, что стоит за обратным
        # прокси с TLS.
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-For"] = "127.0.0.1"
        return headers

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        return payload.get("response") if isinstance(payload, dict) else None

    async def _raw(self, name: str) -> dict[str, Any] | None:
        payload = await self._call("GET", f"api/users/by-username/{name}",
                                   missing_ok=True)
        user = self._unwrap(payload) if payload else None
        return user if isinstance(user, dict) else None

    async def _uuid(self, name: str) -> str:
        user = await self._raw(name)
        if not user or not user.get("uuid"):
            raise PanelError("Учётной записи в панели нет.")
        return str(user["uuid"])

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {
            "username": name,
            "status": "ACTIVE",
            "expireAt": to_iso(expire),
            "trafficLimitBytes": int(traffic),
            "trafficLimitStrategy": "NO_RESET",
            "activeInternalSquads": list(self.groups),
        }
        user = self._unwrap(await self._call("POST", "api/users", body=body))
        return remnawave_account(user)

    async def get_user(self, name: str) -> Account | None:
        user = await self._raw(name)
        return remnawave_account(user) if user else None

    async def _patch(self, name: str, fields: dict[str, Any]) -> None:
        body = {"uuid": await self._uuid(name)}
        body.update(fields)
        await self._call("PATCH", "api/users", body=body)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._patch(name, {"expireAt": to_iso(expire)})

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._patch(name, {"trafficLimitBytes": int(traffic)})

    async def disable(self, name: str) -> None:
        await self._call("POST", f"api/users/{await self._uuid(name)}/actions/disable")

    async def enable(self, name: str) -> None:
        await self._call("POST", f"api/users/{await self._uuid(name)}/actions/enable")

    async def check(self) -> str:
        await self._call("GET", "api/users?size=1&start=0")
        note = "Remnawave отвечает, токен принят"
        if not self.groups:
            note += "; ⚠️ VPN_GROUPS пуст — новым записям не назначатся отряды"
        return note


def remnawave_account(user: Any) -> Account:
    if not isinstance(user, dict):
        raise PanelError("Remnawave ответила непонятно.")
    # Израсходованный трафик в 2.x переехал во вложенный userTraffic;
    # у ранних выпусков он лежит прямо в записи.
    traffic = user.get("userTraffic")
    used = traffic.get("usedTrafficBytes") if isinstance(traffic, dict) else None
    if used is None:
        used = user.get("usedTrafficBytes")
    return Account(
        name=str(user.get("username") or ""),
        enabled=str(user.get("status") or "").upper() == "ACTIVE",
        expire=parse_time(user.get("expireAt")),
        traffic_limit=_int(user.get("trafficLimitBytes")),
        traffic_used=_int(used),
        subscription_url=str(user.get("subscriptionUrl") or ""),
    )


# --------------------------------------------------------------------------
#  Выбор панели
# --------------------------------------------------------------------------

KINDS: dict[str, type[Panel]] = {
    XuiPanel.kind: XuiPanel,
    PasarGuardPanel.kind: PasarGuardPanel,
    RemnawavePanel.kind: RemnawavePanel,
}

# Как люди пишут название панели в .env — не только как в коде.
_ALIASES = {
    "3x-ui": "3xui", "xui": "3xui", "x-ui": "3xui",
    "pasar": "pasarguard", "pasar-guard": "pasarguard",
    "remna": "remnawave",
}


def normalize_kind(value: str) -> str:
    key = (value or "").strip().lower()
    return _ALIASES.get(key, key)


def build(kind: str, **options: Any) -> Panel | None:
    """Клиент нужной панели или None, если название незнакомое."""
    cls = KINDS.get(normalize_kind(kind))
    return cls(**options) if cls else None
