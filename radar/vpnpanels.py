"""Единый слой поверх VPN-панелей (с 5.0, десять видов — с 5.0.1).

Раздел выдачи не знает, какая панель стоит за слотом: он зовёт шесть
действий — завести, найти, сдвинуть срок, сменить лимит трафика,
выключить, включить — и получает одну и ту же запись `Account`. Панелей
может быть несколько сразу, и разных: у каждого слота свой клиент, своя
сессия и свои ошибки, и отказ одной панели не задевает остальные.

**Сверено по исходникам, а не по памяти.** В 5.0 клиенты писались
по документации, и при сверке с кодом самих панелей (сентябрь 2026)
нашлись три ошибки: 3x-ui 3.x убрала `addClient`/`updateClient`,
PasarGuard ждёт ключ API в `X-Api-Key` и `0` для «бессрочно» при правке,
Remnawave правит запись по `username` или `id`, а не по `uuid`. Всё это
учтено ниже, у каждого класса — ссылка на то, откуда взят формат.

**SDK не тянем.** Нужные вызовы укладываются в `aiohttp`, который уже
есть; официальный клиент одной только Remnawave принёс бы четыре пакета
на машину с 512 МБ.

**Ключи — не в журналах.** UUID, пароли, ссылки подписки и токены
не пишутся ни при успехе, ни при ошибке: в сообщение об ошибке идёт
статус и текст панели, но не то, что мы ей отправили.

⚠️ Ни один клиент не обращался к живой панели: формат сверен с исходным
кодом панелей, разбор ответов закреплён офлайн-тестами. Первая проверка
на сервере — кнопка «Проверить панели» в разделе.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import base64
import json
import logging
import math
import re
import secrets as pysecrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger("radar.vpnpanels")

TIMEOUT = 20
GB = 1024 ** 3
DAY = 86400

# «Бессрочно» у панелей, которые без срока не умеют: Remnawave требует
# дату, Hiddify — число дней. Всё дальше этого года считаем бессрочным.
FOREVER_YEAR = 2099
FOREVER_DAYS = 10000
# Hiddify не знает «без предела трафика»: ставим заведомо недостижимый.
UNLIMITED_GB = 100000

# Имя учётной записи уходит в URL панели и в её интерфейс. Самое узкое
# из правил — у Marzban и PasarGuard: строчные латинские буквы, цифры
# и подчёркивание, от 3 до 32 знаков.
_NAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


class PanelError(Exception):
    """Отказ панели, понятный человеку. Секретов в тексте нет."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Account:
    """Учётная запись в панели, одинаковая для всех видов."""

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
    находит ту же запись, а не заводит вторую. Всё, что не буква
    и не цифра (двоеточие в ключах MAX), становится подчёркиванием.
    """
    cleaned = re.sub(r"[^a-z0-9]", "_", str(uid).lower())
    return f"radar_{cleaned}"[:32]


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

    Встречаются: секунды (Marzban), миллисекунды (3x-ui), ISO-строка
    с «Z» или смещением (PasarGuard, Remnawave, Marzneshin), None.
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


def _json(text: str) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _detail(payload: Any) -> str:
    """Текст ошибки из ответа панели, коротко."""
    if isinstance(payload, dict):
        for key in ("msg", "message", "detail", "error", "statusMessage"):
            value = payload.get(key)
            if value:
                return str(value)[:200]
    return "без пояснения"


def _fingerprint(value: str) -> bytes | None:
    """SHA-256 сертификата из строки вида «AB:CD:…» или «abcd…»."""
    cleaned = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(cleaned) != 64:
        return None
    return bytes.fromhex(cleaned)


# --------------------------------------------------------------------------
#  Общая часть
# --------------------------------------------------------------------------

class Panel:
    """Общий интерфейс. Наследники задают разметку запросов и разбор ответов.

    Сессия живёт одну операцию: `async with panel:` открывает её, входит
    в панель один раз и закрывает в конце. Вызов без `async with` открывает
    сессию сам. Долгоживущая сессия с куками панели — ещё одно состояние,
    которое пришлось бы чинить после перезапуска панели, а вызовы редкие:
    их нажимает человек.
    """

    kind = ""
    title = ""
    # Что панель умеет. Раздел не предлагает того, чего нет.
    supports_expiry = True
    supports_traffic = True
    # Что получает человек: подписку, готовый ключ или файл настроек.
    link_kind = "subscription"

    def __init__(self, url: str, *, token: str = "", user: str = "",
                 password: str = "", groups: tuple[str, ...] = (),
                 inbound: int = 0, sub_url: str = "", cert: str = "") -> None:
        self.url = (url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.user = (user or "").strip()
        self.password = password or ""
        self.groups = tuple(str(item).strip() for item in groups if str(item).strip())
        self.inbound = int(inbound or 0)
        self.sub_url = (sub_url or "").strip().rstrip("/")
        self.cert = (cert or "").strip()
        self._session: Any = None
        self._headers: dict[str, str] = {}
        self._depth = 0

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
            missing.append("адрес")
        if not self.token and not (self.user and self.password):
            missing.append("токен или логин с паролем")
        if self.cert and _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата (64 шестнадцатеричных знака)")
        return missing

    async def subscription_url(self, name: str) -> str:
        account = await self.get_user(name)
        if account is None:
            raise PanelError("Учётной записи в панели нет.")
        if not account.subscription_url:
            raise PanelError("Панель не сообщила ссылку.")
        return account.subscription_url

    # --- сессия ---

    def _base_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    async def _login(self) -> None:
        """Вход, если он нужен. По умолчанию хватает заголовков."""

    def _ssl(self) -> Any:
        """Закрепление сертификата: для панелей на самоподписанном.

        Отпечаток задан — проверяется только он (так работает Outline,
        и так же можно подключить 3x-ui на голом IP). Не задан — обычная
        проверка по цепочке. Отключить проверку совсем нельзя: адрес
        панели и токен — это ключи от всех выданных доступов.
        """
        pinned = _fingerprint(self.cert)
        if pinned is None:
            return None
        import aiohttp

        return aiohttp.Fingerprint(pinned)

    async def __aenter__(self) -> "Panel":
        self._depth += 1
        if self._session is not None:
            return self
        import aiohttp

        problems = self.problems()
        if problems:
            self._depth -= 1
            raise PanelError("Панель не настроена: " + ", ".join(problems) + ".")
        # unsafe=True: без него aiohttp не хранит куки, выданные адресом
        # по IP, а панели в домашней сети открывают именно так.
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        )
        self._headers = self._base_headers()
        try:
            await self._login()
        except BaseException:
            await self._close()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._depth -= 1
        if self._depth <= 0:
            await self._close()

    async def _close(self) -> None:
        session, self._session = self._session, None
        self._depth = 0
        if session is not None:
            await session.close()

    async def _request(self, method: str, path: str, *, body: Any = None,
                       form: dict[str, str] | None = None,
                       headers: dict[str, str] | None = None) -> tuple[int, str]:
        """Сырой запрос внутри открытой сессии: (статус, текст)."""
        import aiohttp

        url = path if path.startswith("http") else f"{self.url}/{path.lstrip('/')}"
        merged = dict(self._headers)
        merged.update(headers or {})
        try:
            async with self._session.request(
                method, url, json=body, data=form, headers=merged, ssl=self._ssl(),
            ) as response:
                return response.status, await response.text()
        except aiohttp.ServerFingerprintMismatch:
            raise PanelError("Сертификат панели не совпал с заданным отпечатком.")
        except aiohttp.ClientError as exc:
            log.warning("Панель %s недоступна: %s", self.kind, type(exc).__name__)
            raise PanelError("Панель не отвечает — проверьте адрес и что она запущена.")
        except Exception as exc:  # noqa: BLE001
            log.warning("Сбой обращения к панели %s: %s", self.kind, type(exc).__name__)
            raise PanelError("Обращение к панели не удалось.")

    async def _call(self, method: str, path: str, *, body: Any = None,
                    form: dict[str, str] | None = None,
                    missing_ok: bool = False, text: bool = False) -> Any:
        """Запрос к панели. Возвращает разобранный JSON (или текст при
        `text`), None на 404 при `missing_ok`; иначе — `PanelError`."""
        if self._session is None:
            async with self:
                return await self._call(method, path, body=body, form=form,
                                        missing_ok=missing_ok, text=text)
        status, raw = await self._request(method, path, body=body, form=form)
        if status == 404 and missing_ok:
            return None
        if status in (401, 403):
            raise PanelError("Панель не приняла вход: проверьте токен или пароль.",
                             status)
        payload = _json(raw)
        if status >= 400:
            raise PanelError(f"Панель ответила HTTP {status}: {_detail(payload)}", status)
        if text:
            return raw
        if payload is None and raw.strip():
            raise PanelError("Панель ответила не JSON — возможно, неверный адрес "
                             "или путь панели.", status)
        return payload


# --------------------------------------------------------------------------
#  3x-ui и x-ui (alireza0)
# --------------------------------------------------------------------------

class XuiPanel(Panel):
    """3x-ui (MHSanaei) — обе ветки, 2.x и 3.x.

    Сверено с `internal/web/controller/{api,client,inbound}.go` 3x-ui 3.8.5
    и `web/controller/inbound.go` ветки 2.x:

    * 3.x: клиент — отдельная сущность, `clients/add`, `clients/get/:email`,
      `clients/update/:email`; подключения ему назначаются списком;
    * 2.x: клиент живёт внутри подключения, `inbounds/addClient`,
      `inbounds/updateClient/:key`, `inbounds/getClientTraffics/:email`.

    Ветка определяется на первом обращении: у 2.x маршрута
    `clients/get` нет, и панель отвечает 404.

    Вход: токен из «Настройки → Безопасность → API» (заголовок Bearer)
    или логин с паролем. В 3.x вход по паролю закрыт CSRF: токен
    берётся с `/csrf-token` и отправляется заголовком `X-CSRF-Token`
    при входе и при каждом изменении.
    """

    kind = "3xui"
    title = "3x-ui"
    api_root = "panel/api"
    tokens_allowed = True

    # Протоколы 2.x, у которых клиент определяется одним полем. Shadowsocks
    # не берём: у методов 2022 года пароль — ключ строгой длины, и выдать
    # его вслепую, не зная метода подключения, значит выдать нерабочий.
    _KEY_FIELD = {"vless": "id", "vmess": "id", "trojan": "password"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._generation = 0   # 0 — ещё не известна, 2 или 3

    def problems(self) -> list[str]:
        missing = []
        if not self.url:
            missing.append("адрес")
        if not (self.token and self.tokens_allowed) and not (self.user and self.password):
            missing.append("токен или логин с паролем" if self.tokens_allowed
                           else "логин с паролем (токенов у этой панели нет)")
        if self.inbound <= 0:
            missing.append("номер подключения (inbound)")
        if self.cert and _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата (64 шестнадцатеричных знака)")
        return missing

    async def _csrf(self) -> str:
        status, raw = await self._request("GET", "csrf-token")
        payload = _json(raw) if status == 200 else None
        if isinstance(payload, dict) and payload.get("success"):
            return str(payload.get("obj") or "")
        return ""

    async def _login(self) -> None:
        if self.token and self.tokens_allowed:
            self._headers["Authorization"] = f"Bearer {self.token}"
            return
        csrf = await self._csrf()
        extra = {"X-CSRF-Token": csrf} if csrf else {}
        status, raw = await self._request("POST", "login", form={
            "username": self.user, "password": self.password,
        }, headers=extra)
        payload = _json(raw)
        if not (isinstance(payload, dict) and payload.get("success")):
            raise PanelError(f"{self.title} не приняла логин или пароль.", status)
        if csrf:
            # После входа сессия новая, и токен берём заново: прежний
            # мог остаться привязанным к анонимной сессии.
            self._headers["X-CSRF-Token"] = await self._csrf() or csrf

    async def _api(self, method: str, path: str, **kwargs: Any) -> Any:
        payload = await self._call(method, f"{self.api_root}/{path}", **kwargs)
        if not isinstance(payload, dict) or not payload.get("success"):
            raise PanelError(f"{self.title} отказала: {_detail(payload)}")
        return payload.get("obj")

    async def _gen(self) -> int:
        if self._generation:
            return self._generation
        payload = await self._call("GET", f"{self.api_root}/clients/get/radar_probe",
                                   missing_ok=True)
        self._generation = 2 if payload is None else 3
        return self._generation

    async def _inbound(self) -> tuple[str, list[dict[str, Any]]]:
        """Протокол подключения и список его клиентов."""
        obj = await self._api("GET", f"inbounds/get/{self.inbound}")
        if not isinstance(obj, dict):
            raise PanelError(f"{self.title} не нашла подключение {self.inbound}.")
        return str(obj.get("protocol") or ""), parse_xui_clients(obj.get("settings"))

    def _key_field(self, protocol: str) -> str:
        field = self._KEY_FIELD.get(protocol)
        if field is None:
            raise PanelError(f"Протокол подключения «{protocol or '?'}» не поддерживается: "
                             "нужен vless, vmess или trojan.")
        return field

    # --- ветка 3.x ---

    async def _record3(self, name: str) -> dict[str, Any] | None:
        payload = await self._call("GET", f"{self.api_root}/clients/get/{name}")
        if isinstance(payload, dict) and not payload.get("success"):
            # Отсутствие записи панель сообщает ответом 200 с текстом
            # ошибки базы, а не статусом 404.
            if "not found" in str(payload.get("msg") or "").lower():
                return None
            raise PanelError(f"{self.title} отказала: {_detail(payload)}")
        obj = payload.get("obj") if isinstance(payload, dict) else None
        return obj if isinstance(obj, dict) and isinstance(obj.get("client"), dict) else None

    async def _update3(self, name: str, fields: dict[str, Any]) -> None:
        record = await self._record3(name)
        if record is None:
            raise PanelError("Учётной записи в панели нет.")
        client = xui3_client_from_record(record["client"])
        client.update(fields)
        await self._api("POST", f"clients/update/{name}", body=client)

    # --- ветка 2.x ---

    async def _find2(self, name: str) -> tuple[str, dict[str, Any] | None]:
        protocol, clients = await self._inbound()
        for client in clients:
            if client.get("email") == name:
                return protocol, client
        return protocol, None

    async def _update2(self, name: str, fields: dict[str, Any]) -> None:
        protocol, client = await self._find2(name)
        if client is None:
            raise PanelError("Учётной записи в панели нет.")
        client = dict(client)
        client.update(fields)
        key = client.get(self._key_field(protocol)) or ""
        await self._api("POST", f"inbounds/updateClient/{key}",
                        body=xui_client_body(self.inbound, client))

    async def _change(self, name: str, fields: dict[str, Any]) -> None:
        if await self._gen() == 3:
            await self._update3(name, fields)
        else:
            await self._update2(name, fields)

    # --- общий интерфейс ---

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        if await self._gen() == 3:
            if await self._record3(name) is not None:
                raise PanelError("Такая учётная запись в панели уже есть.")
            client = new_xui_client(name, "vless", "id", expire, traffic)
            # Пароль нужен trojan, uuid — vless и vmess: в 3.x клиент один
            # на все назначенные подключения, поэтому задаём оба.
            client["password"] = pysecrets.token_urlsafe(18)
            await self._api("POST", "clients/add",
                            body={"client": client, "inboundIds": [self.inbound]})
            return xui_account(client, None, self.sub_url)
        protocol, existing = await self._find2(name)
        if existing is not None:
            raise PanelError("Такая учётная запись в панели уже есть.")
        client = new_xui_client(name, protocol, self._key_field(protocol), expire, traffic)
        await self._api("POST", "inbounds/addClient",
                        body=xui_client_body(self.inbound, client))
        return xui_account(client, None, self.sub_url)

    async def get_user(self, name: str) -> Account | None:
        if await self._gen() == 3:
            record = await self._record3(name)
            if record is None:
                return None
            return xui3_account(record, self.sub_url)
        _, client = await self._find2(name)
        if client is None:
            return None
        traffic = await self._api("GET", f"inbounds/getClientTraffics/{name}")
        return xui_account(client, traffic if isinstance(traffic, dict) else None,
                           self.sub_url)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._change(name, {"expiryTime": int(expire) * 1000 if expire else 0})

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._change(name, {"totalGB": int(traffic)})

    async def disable(self, name: str) -> None:
        await self._change(name, {"enable": False})

    async def enable(self, name: str) -> None:
        await self._change(name, {"enable": True})

    async def subscription_url(self, name: str) -> str:
        if not self.sub_url:
            raise PanelError("Не задан адрес подписки панели, например "
                             "https://example.ru:2096/sub.")
        return await super().subscription_url(name)

    async def check(self) -> str:
        protocol, clients = await self._inbound()
        generation = await self._gen()
        if generation == 2:
            self._key_field(protocol)
        note = (f"{self.title} {generation}.x отвечает, подключение {self.inbound}: "
                f"{protocol}, клиентов {len(clients)}")
        if not self.sub_url:
            note += "; ⚠️ адрес подписки не задан — ссылку выдать не получится"
        return note


class XuiLegacyPanel(XuiPanel):
    """x-ui (alireza0): та же модель, что у 3x-ui 2.x, под `/xui/API`.

    Сверено с `web/controller/api.go` (APIBasePath = "/xui/API"). Токенов
    у этой панели нет — только вход по логину и паролю, без CSRF.
    """

    kind = "xui"
    title = "x-ui"
    api_root = "xui/API"
    tokens_allowed = False

    async def _gen(self) -> int:
        self._generation = 2
        return 2


def parse_xui_clients(settings: Any) -> list[dict[str, Any]]:
    """Клиенты из поля settings подключения: там JSON строкой."""
    if isinstance(settings, str):
        settings = _json(settings or "{}")
    if not isinstance(settings, dict):
        return []
    clients = settings.get("clients")
    return [item for item in clients if isinstance(item, dict)] if isinstance(clients, list) else []


def new_xui_client(name: str, protocol: str, key_field: str,
                   expire: int, traffic: int) -> dict[str, Any]:
    # tgId не передаём: в 3x-ui это число, в x-ui — строка, и пустое
    # значение одной ломает разбор другой. Отсутствующее поле обе
    # панели принимают как пустое.
    client: dict[str, Any] = {
        "email": name,
        "limitIp": 0,
        # Поле названо totalGB, но хранит байты — так в самой панели.
        "totalGB": int(traffic),
        "expiryTime": int(expire) * 1000 if expire else 0,
        "enable": True,
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
    """Тело addClient и updateClient 2.x: клиенты — JSON строкой внутри JSON."""
    return {"id": int(inbound), "settings": json.dumps({"clients": [client]})}


def xui3_client_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Запись клиента 3.x (ClientRecord) → тело правки (model.Client).

    Правка в 3.x заменяет клиента целиком, поэтому отправляется всё,
    что панель о нём знает; в записи uuid лежит полем `uuid`, а в теле
    правки он же называется `id`.
    """
    fields = ("password", "auth", "flow", "security", "email", "limitIp",
              "totalGB", "expiryTime", "enable", "tgId", "subId", "group",
              "comment", "limitHwid")
    client = {key: record[key] for key in fields if key in record}
    if record.get("uuid"):
        client["id"] = record["uuid"]
    return client


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


def xui3_account(record: dict[str, Any], sub_url: str) -> Account:
    client = record.get("client") or {}
    account = xui_account(client, None, sub_url)
    return Account(account.name, account.enabled, account.expire,
                   account.traffic_limit, _int(record.get("usedTraffic")),
                   account.subscription_url)


# --------------------------------------------------------------------------
#  s-ui (alireza0)
# --------------------------------------------------------------------------

class SuiPanel(Panel):
    """s-ui: sing-box под управлением панели, API `apiv2` с заголовком Token.

    Сверено с `api/apiV2Handler.go`, `service/client.go` и фронтендом
    `s-ui-frontend/src/types/clients.ts`: учётные данные клиента для
    каждого протокола генерирует не сервер, а тот, кто заводит клиента, —
    `random_configs` ниже повторяет `randomConfigs` фронтенда.

    В `groups` — номера подключений (inbounds), к которым привязывается
    клиент. Ссылка подписки — адрес подписки панели плюс имя клиента.
    """

    kind = "sui"
    title = "s-ui"

    def problems(self) -> list[str]:
        missing = [] if self.url else ["адрес"]
        if not self.token:
            missing.append("токен API (Настройки → API)")
        if self.cert and _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата (64 шестнадцатеричных знака)")
        return missing

    def _base_headers(self) -> dict[str, str]:
        headers = super()._base_headers()
        headers["Token"] = self.token
        return headers

    async def _api(self, method: str, action: str, **kwargs: Any) -> Any:
        payload = await self._call(method, f"apiv2/{action}", **kwargs)
        if not isinstance(payload, dict) or not payload.get("success"):
            raise PanelError(f"s-ui отказала: {_detail(payload)}")
        return payload.get("obj")

    def _inbounds(self) -> list[int]:
        return [int(item) for item in self.groups if item.isdigit()]

    async def _find(self, name: str) -> dict[str, Any] | None:
        obj = await self._api("GET", "clients")
        clients = obj.get("clients") if isinstance(obj, dict) else None
        for item in clients or []:
            if isinstance(item, dict) and item.get("name") == name:
                full = await self._api("GET", f"clients?id={int(item['id'])}")
                rows = full.get("clients") if isinstance(full, dict) else None
                return rows[0] if rows else item
        return None

    async def _save(self, action: str, client: dict[str, Any]) -> None:
        await self._api("POST", "save", form={
            "object": "clients", "action": action, "data": json.dumps(client),
        })

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        if await self._find(name) is not None:
            raise PanelError("Такая учётная запись в панели уже есть.")
        client = {
            "enable": True, "name": name, "config": random_configs(name),
            "inbounds": self._inbounds(), "links": [],
            "volume": int(traffic), "expiry": int(expire or 0),
            "up": 0, "down": 0, "desc": "", "group": "",
        }
        await self._save("new", client)
        return sui_account(client, self.sub_url)

    async def get_user(self, name: str) -> Account | None:
        found = await self._find(name)
        return sui_account(found, self.sub_url) if found else None

    async def _change(self, name: str, fields: dict[str, Any]) -> None:
        client = await self._find(name)
        if client is None:
            raise PanelError("Учётной записи в панели нет.")
        client = dict(client)
        client.update(fields)
        await self._save("edit", client)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._change(name, {"expiry": int(expire or 0)})

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._change(name, {"volume": int(traffic)})

    async def disable(self, name: str) -> None:
        await self._change(name, {"enable": False})

    async def enable(self, name: str) -> None:
        await self._change(name, {"enable": True})

    async def subscription_url(self, name: str) -> str:
        if not self.sub_url:
            raise PanelError("Не задан адрес подписки s-ui, например "
                             "https://example.ru:2096/sub.")
        return await super().subscription_url(name)

    async def check(self) -> str:
        obj = await self._api("GET", "clients")
        count = len((obj or {}).get("clients") or []) if isinstance(obj, dict) else 0
        note = f"s-ui отвечает, клиентов {count}"
        if not self._inbounds():
            note += "; ⚠️ подключения не заданы — клиенту не назначатся inbounds"
        return note


def random_configs(name: str) -> dict[str, dict[str, Any]]:
    """Учётные данные клиента s-ui для всех протоколов — как во фронтенде."""
    mixed = pysecrets.token_urlsafe(8)[:10]
    ss16 = base64.b64encode(pysecrets.token_bytes(16)).decode()
    ss32 = base64.b64encode(pysecrets.token_bytes(32)).decode()
    ident = str(uuid.uuid4())
    return {
        "mixed": {"username": name, "password": mixed},
        "socks": {"username": name, "password": mixed},
        "http": {"username": name, "password": mixed},
        "shadowsocks": {"name": name, "password": ss32},
        "shadowsocks16": {"name": name, "password": ss16},
        "shadowtls": {"name": name, "password": ss32},
        "vmess": {"name": name, "uuid": ident, "alterId": 0},
        "vless": {"name": name, "uuid": ident, "flow": "xtls-rprx-vision"},
        "anytls": {"name": name, "password": mixed},
        "trojan": {"name": name, "password": mixed},
        "naive": {"username": name, "password": mixed},
        "hysteria": {"name": name, "auth_str": mixed},
        "snell": {"name": name, "userkey": pysecrets.token_urlsafe(24)[:32]},
        "tuic": {"name": name, "uuid": ident, "password": mixed},
        "hysteria2": {"name": name, "password": mixed},
    }


def sui_account(client: dict[str, Any], sub_url: str) -> Account:
    name = str(client.get("name") or "")
    return Account(
        name=name,
        enabled=bool(client.get("enable", True)),
        expire=parse_time(client.get("expiry")),
        traffic_limit=_int(client.get("volume")),
        traffic_used=_int(client.get("up")) + _int(client.get("down")),
        subscription_url=f"{sub_url}/{name}" if sub_url and name else "",
    )


# --------------------------------------------------------------------------
#  Marzban, PasarGuard, Marzneshin — одна линия
# --------------------------------------------------------------------------

def _is_jwt(token: str) -> bool:
    return token.startswith("eyJ") and token.count(".") == 2


def _absolute(link: str, base_url: str) -> str:
    """Панель отдаёт путь без адреса, если адрес подписки в её
    настройках не задан: дописываем свой, иначе ссылка не откроется."""
    link = str(link or "")
    return f"{base_url}{link}" if link.startswith("/") else link


class MarzbanPanel(Panel):
    """Marzban (Gozargah): `/api/user`, срок — unix-время, 0 — бессрочно.

    Сверено с `app/routers/user.py` и `app/models/user.py`. У пользователя
    обязателен хотя бы один протокол (`proxies`); подключения, не указанные
    явно, панель назначает сама — все подключения этого протокола.
    В `groups` — протоколы через запятую, по умолчанию vless.
    """

    kind = "marzban"
    title = "Marzban"
    token_path = "api/admin/token"
    admin_path = "api/admin"

    async def _login(self) -> None:
        if self.token:
            self._headers["Authorization"] = f"Bearer {self.token}"
            return
        status, raw = await self._request("POST", self.token_path, form={
            "username": self.user, "password": self.password,
        })
        payload = _json(raw)
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise PanelError(f"{self.title} не приняла логин или пароль.", status)
        self._headers["Authorization"] = f"Bearer {token}"

    def _protocols(self) -> list[str]:
        known = ("vless", "vmess", "trojan", "shadowsocks")
        chosen = [item.lower() for item in self.groups if item.lower() in known]
        return chosen or ["vless"]

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {
            "username": name,
            "proxies": {protocol: {} for protocol in self._protocols()},
            "inbounds": {},
            "expire": int(expire or 0),
            "data_limit": int(traffic),
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
        }
        return marzban_account(await self._call("POST", "api/user", body=body), self.url)

    async def get_user(self, name: str) -> Account | None:
        payload = await self._call("GET", f"api/user/{name}", missing_ok=True)
        return marzban_account(payload, self.url) if payload else None

    async def _modify(self, name: str, body: dict[str, Any]) -> None:
        await self._call("PUT", f"api/user/{name}", body=body)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._modify(name, {"expire": int(expire or 0)})

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._modify(name, {"data_limit": int(traffic)})

    async def disable(self, name: str) -> None:
        await self._modify(name, {"status": "disabled"})

    async def enable(self, name: str) -> None:
        await self._modify(name, {"status": "active"})

    async def check(self) -> str:
        payload = await self._call("GET", self.admin_path)
        who = payload.get("username") if isinstance(payload, dict) else ""
        return f"{self.title} отвечает, вход как {who or 'администратор'}"


def marzban_account(payload: Any, base_url: str) -> Account:
    if not isinstance(payload, dict):
        raise PanelError("Панель ответила непонятно.")
    return Account(
        name=str(payload.get("username") or ""),
        enabled=str(payload.get("status") or "").lower() in ("active", "on_hold"),
        expire=parse_time(payload.get("expire")),
        traffic_limit=_int(payload.get("data_limit")),
        traffic_used=_int(payload.get("used_traffic")),
        subscription_url=_absolute(payload.get("subscription_url"), base_url),
    )


class PasarGuardPanel(MarzbanPanel):
    """PasarGuard (наследник Marzban): доступ задаётся группами.

    Сверено с `app/routers/user.py`, `app/models/user.py`
    и `app/routers/authentication.py`:

    * ключ API панели передаётся заголовком `X-Api-Key`, а Bearer — только
      для JWT, полученного входом (в 5.0 ключ уходил Bearer'ом);
    * при правке `expire: null` значит «не менять», а бессрочно — `0`
      (в 5.0 «бессрочно» отправлялось как null и срок не менялся).

    В `groups` — номера групп через запятую.
    """

    kind = "pasarguard"
    title = "PasarGuard"

    async def _login(self) -> None:
        if self.token and not _is_jwt(self.token):
            self._headers["X-Api-Key"] = self.token
            return
        await super()._login()

    def _groups(self) -> list[int]:
        return [int(item) for item in self.groups if item.isdigit()]

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {
            "username": name,
            "status": "active",
            "expire": to_iso(expire) if expire else 0,
            "data_limit": int(traffic),
            "data_limit_reset_strategy": "no_reset",
            "group_ids": self._groups(),
            "proxy_settings": {},
        }
        return marzban_account(await self._call("POST", "api/user", body=body), self.url)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._modify(name, {"expire": to_iso(expire) if expire else 0})

    async def check(self) -> str:
        note = await super().check()
        if not self._groups():
            note += "; ⚠️ группы не заданы — новые записи останутся без узлов"
        return note


class MarzneshinPanel(MarzbanPanel):
    """Marzneshin: `/api/users`, срок — стратегия плюс дата, доступ — сервисы.

    Сверено с `app/routes/user.py` и `app/models/user.py`. Включение
    и выключение — отдельные действия; правка требует имя в теле.
    В `groups` — номера сервисов через запятую.
    """

    kind = "marzneshin"
    title = "Marzneshin"
    token_path = "api/admins/token"
    admin_path = "api/admins/current"

    def _services(self) -> list[int]:
        return [int(item) for item in self.groups if item.isdigit()]

    @staticmethod
    def _expiry(expire: int) -> dict[str, Any]:
        if not expire:
            return {"expire_strategy": "never", "expire_date": None}
        return {"expire_strategy": "fixed_date", "expire_date": to_iso(expire)}

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {
            "username": name,
            "data_limit": int(traffic),
            "data_limit_reset_strategy": "no_reset",
            "service_ids": self._services(),
            "note": "",
            **self._expiry(expire),
        }
        return marzneshin_account(await self._call("POST", "api/users", body=body),
                                  self.url)

    async def get_user(self, name: str) -> Account | None:
        payload = await self._call("GET", f"api/users/{name}", missing_ok=True)
        return marzneshin_account(payload, self.url) if payload else None

    async def _modify(self, name: str, body: dict[str, Any]) -> None:
        await self._call("PUT", f"api/users/{name}", body={"username": name, **body})

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._modify(name, self._expiry(expire))

    async def disable(self, name: str) -> None:
        await self._call("POST", f"api/users/{name}/disable")

    async def enable(self, name: str) -> None:
        await self._call("POST", f"api/users/{name}/enable")

    async def check(self) -> str:
        note = await super().check()
        if not self._services():
            note += "; ⚠️ сервисы не заданы — новые записи останутся без узлов"
        return note


def marzneshin_account(payload: Any, base_url: str) -> Account:
    if not isinstance(payload, dict):
        raise PanelError("Marzneshin ответила непонятно.")
    never = str(payload.get("expire_strategy") or "") == "never"
    return Account(
        name=str(payload.get("username") or ""),
        enabled=bool(payload.get("enabled", True)),
        expire=0 if never else parse_time(payload.get("expire_date")),
        traffic_limit=_int(payload.get("data_limit")),
        traffic_used=_int(payload.get("used_traffic")),
        subscription_url=_absolute(payload.get("subscription_url"), base_url),
    )


# --------------------------------------------------------------------------
#  Remnawave
# --------------------------------------------------------------------------

class RemnawavePanel(Panel):
    """Remnawave: пользователь по имени, доступ — внутренние «отряды».

    Сверено с `libs/contract` (commands/users, api/controllers/users.ts):
    правка — `PATCH /api/users` с `username` или числовым `id` в теле,
    действия — `/api/users/:id/actions/{enable,disable}`. Ранние версии
    опознавали запись по `uuid`; он отправляется вместе с именем, если
    панель его вернула, — новая версия лишнее поле отбрасывает.
    """

    kind = "remnawave"
    title = "Remnawave"

    def problems(self) -> list[str]:
        missing = [] if self.url else ["адрес"]
        # Входа по паролю у API Remnawave нет: только токен из API Tokens.
        if not self.token:
            missing.append("токен API")
        if self.cert and _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата (64 шестнадцатеричных знака)")
        return missing

    def _base_headers(self) -> dict[str, str]:
        headers = super()._base_headers()
        headers["Authorization"] = f"Bearer {self.token}"
        # Бэкенд, вызванный напрямую по HTTP внутри сети Docker, отказывает
        # без этих заголовков: он ждёт, что стоит за прокси с TLS.
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

    async def _ref(self, name: str) -> str:
        user = await self._raw(name)
        ref = (user or {}).get("uuid") or (user or {}).get("id")
        if not ref:
            raise PanelError("Учётной записи в панели нет.")
        return str(ref)

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
        user = await self._raw(name)
        if user is None:
            raise PanelError("Учётной записи в панели нет.")
        body: dict[str, Any] = {"username": name}
        if user.get("uuid"):
            body["uuid"] = user["uuid"]
        body.update(fields)
        await self._call("PATCH", "api/users", body=body)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._patch(name, {"expireAt": to_iso(expire)})

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._patch(name, {"trafficLimitBytes": int(traffic)})

    async def disable(self, name: str) -> None:
        await self._call("POST", f"api/users/{await self._ref(name)}/actions/disable")

    async def enable(self, name: str) -> None:
        await self._call("POST", f"api/users/{await self._ref(name)}/actions/enable")

    async def check(self) -> str:
        # Запрос несуществующего имени: 404 значит «вход принят, записи
        # нет», 401 — токен не тот. Прав на статистику у токена может
        # и не быть, а на пользователей они нужны в любом случае.
        await self._raw("radar_probe")
        note = "Remnawave отвечает, токен принят"
        if not self.groups:
            note += "; ⚠️ отряды не заданы — новые записи останутся без узлов"
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
#  Hiddify
# --------------------------------------------------------------------------

class HiddifyPanel(Panel):
    """Hiddify Manager: API v2 администратора, ключ — заголовок Hiddify-API-Key.

    Сверено с `hiddifypanel/panel/commercial/restapi/v2/admin`. Адрес —
    вместе с путём администратора (`https://домен/<admin_proxy_path>`),
    ключ — uuid администратора. Пользователь опознаётся uuid; он выводится
    из имени детерминированно, поэтому повторная выдача находит ту же запись.

    Срока как даты у Hiddify нет: есть дата начала и число дней. Продление
    ставит начало на сегодня и пересчитывает дни до нужной даты. Без
    предела трафика панель не умеет — ставится заведомо недостижимый.
    Ссылка — страница пользователя по адресу клиентского пути
    (`https://домен/<client_proxy_path>`), с неё ставятся все приложения.
    """

    kind = "hiddify"
    title = "Hiddify"

    def problems(self) -> list[str]:
        missing = [] if self.url else ["адрес с путём администратора"]
        if not self.token:
            missing.append("ключ API (uuid администратора)")
        if self.cert and _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата (64 шестнадцатеричных знака)")
        return missing

    def _base_headers(self) -> dict[str, str]:
        headers = super()._base_headers()
        headers["Hiddify-API-Key"] = self.token
        return headers

    @staticmethod
    def user_uuid(name: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"radar:{name}"))

    @staticmethod
    def _period(expire: int) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        if not expire:
            days = FOREVER_DAYS
        else:
            start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
            days = max(1, math.ceil((int(expire) - start.timestamp()) / DAY))
        return {"start_date": today.isoformat(), "package_days": days}

    @staticmethod
    def _limit(traffic: int) -> float:
        return round(traffic / GB, 3) if traffic else float(UNLIMITED_GB)

    def _path(self, name: str = "") -> str:
        suffix = f"{self.user_uuid(name)}/" if name else ""
        return f"api/v2/admin/user/{suffix}"

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {
            "uuid": self.user_uuid(name), "name": name, "mode": "no_reset",
            "usage_limit_GB": self._limit(traffic), "enable": True,
            **self._period(expire),
        }
        return hiddify_account(await self._call("POST", self._path(), body=body),
                               self.sub_url)

    async def get_user(self, name: str) -> Account | None:
        payload = await self._call("GET", self._path(name), missing_ok=True)
        return hiddify_account(payload, self.sub_url) if payload else None

    async def _patch(self, name: str, body: dict[str, Any]) -> None:
        await self._call("PATCH", self._path(name), body=body)

    async def set_expiry(self, name: str, expire: int) -> None:
        await self._patch(name, self._period(expire))

    async def set_traffic(self, name: str, traffic: int) -> None:
        await self._patch(name, {"usage_limit_GB": self._limit(traffic)})

    async def disable(self, name: str) -> None:
        await self._patch(name, {"enable": False})

    async def enable(self, name: str) -> None:
        await self._patch(name, {"enable": True})

    async def subscription_url(self, name: str) -> str:
        if not self.sub_url:
            raise PanelError("Не задан адрес клиентской страницы Hiddify, "
                             "например https://example.ru/<client_proxy_path>.")
        return await super().subscription_url(name)

    async def check(self) -> str:
        payload = await self._call("GET", "api/v2/admin/me/")
        who = payload.get("name") if isinstance(payload, dict) else ""
        note = f"Hiddify отвечает, вход как {who or 'администратор'}"
        if not self.sub_url:
            note += "; ⚠️ адрес клиентской страницы не задан — ссылку выдать не получится"
        return note


def hiddify_account(payload: Any, sub_url: str) -> Account:
    if not isinstance(payload, dict):
        raise PanelError("Hiddify ответила непонятно.")
    expire = 0
    days = _int(payload.get("package_days"))
    start = str(payload.get("start_date") or "")
    if days and days < FOREVER_DAYS:
        try:
            began = date.fromisoformat(start[:10]) if start else datetime.now(timezone.utc).date()
            expire = int(datetime(began.year, began.month, began.day,
                                  tzinfo=timezone.utc).timestamp()) + days * DAY
        except ValueError:
            expire = 0
    limit_gb = float(payload.get("usage_limit_GB") or 0)
    user_id = str(payload.get("uuid") or "")
    return Account(
        name=str(payload.get("name") or ""),
        enabled=bool(payload.get("enable", True)),
        expire=expire,
        traffic_limit=0 if limit_gb >= UNLIMITED_GB else int(limit_gb * GB),
        traffic_used=int(float(payload.get("current_usage_GB") or 0) * GB),
        subscription_url=f"{sub_url}/{user_id}/" if sub_url and user_id else "",
    )


# --------------------------------------------------------------------------
#  Outline
# --------------------------------------------------------------------------

class OutlinePanel(Panel):
    """Outline (Jigsaw): API управления сервера shadowbox.

    Сверено с `src/shadowbox/server/api.yml`. Адрес — `apiUrl` целиком,
    с секретным путём: он и есть вход, токена нет. Сертификат у сервера
    самоподписанный, поэтому отпечаток `certSha256` обязателен — без
    закрепления адрес с секретом ушёл бы любому, кто встал посередине.

    Ключ заводится с нашим идентификатором (`PUT /access-keys/:id`), так
    что повторная выдача находит его же. Сроков Outline не знает вовсе,
    а «выключить» у него — это предел трафика в ноль байт. Человек
    получает готовый ключ `ss://`, а не подписку.
    """

    kind = "outline"
    title = "Outline"
    supports_expiry = False
    link_kind = "key"

    def problems(self) -> list[str]:
        missing = [] if self.url else ["apiUrl сервера"]
        if _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата certSha256")
        return missing

    async def _key(self, name: str) -> dict[str, Any] | None:
        payload = await self._call("GET", f"access-keys/{name}", missing_ok=True)
        return payload if isinstance(payload, dict) else None

    async def _usage(self, name: str) -> int:
        payload = await self._call("GET", "metrics/transfer")
        table = payload.get("bytesTransferredByUserId") if isinstance(payload, dict) else None
        return _int((table or {}).get(name))

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body: dict[str, Any] = {"name": name}
        if traffic:
            body["limit"] = {"bytes": int(traffic)}
        payload = await self._call("PUT", f"access-keys/{name}", body=body)
        return outline_account(payload, 0)

    async def get_user(self, name: str) -> Account | None:
        key = await self._key(name)
        if key is None:
            return None
        return outline_account(key, await self._usage(name))

    async def set_expiry(self, name: str, expire: int) -> None:
        raise PanelError("Outline не поддерживает сроки: доступ действует, "
                         "пока его не отключат.")

    async def set_traffic(self, name: str, traffic: int) -> None:
        if traffic:
            await self._call("PUT", f"access-keys/{name}/data-limit",
                             body={"limit": {"bytes": int(traffic)}})
        else:
            await self._call("DELETE", f"access-keys/{name}/data-limit")

    async def disable(self, name: str) -> None:
        await self._call("PUT", f"access-keys/{name}/data-limit",
                         body={"limit": {"bytes": 0}})

    async def enable(self, name: str) -> None:
        await self._call("DELETE", f"access-keys/{name}/data-limit")

    async def check(self) -> str:
        payload = await self._call("GET", "server")
        title = payload.get("name") if isinstance(payload, dict) else ""
        return f"Outline отвечает: {title or 'сервер'}; сроков у Outline нет"


def outline_account(key: Any, used: int) -> Account:
    if not isinstance(key, dict):
        raise PanelError("Outline ответил непонятно.")
    limit = key.get("dataLimit")
    limit_bytes = _int(limit.get("bytes")) if isinstance(limit, dict) else 0
    disabled = isinstance(limit, dict) and limit_bytes == 0
    return Account(
        name=str(key.get("name") or key.get("id") or ""),
        enabled=not disabled,
        expire=0,
        traffic_limit=limit_bytes,
        traffic_used=used,
        subscription_url=str(key.get("accessUrl") or ""),
    )


# --------------------------------------------------------------------------
#  wg-easy
# --------------------------------------------------------------------------

class WgEasyPanel(Panel):
    """wg-easy (15.x): WireGuard с веб-интерфейсом, вход — Basic.

    Сверено с `src/server/api/client` и `utils/session.ts`. Клиент — это
    числовой id, имя уникальностью не охраняется, поэтому ищем по имени
    в общем списке. Правка заменяет клиента целиком: читаем, меняем поле,
    отправляем обратно. Предела трафика у wg-easy нет.

    WireGuard — не подписка, а файл настроек. Человек получает одноразовую
    ссылку на него: она работает один раз, и при повторном показе бот
    выпускает новую.
    """

    kind = "wgeasy"
    title = "wg-easy"
    supports_traffic = False
    link_kind = "config"

    def problems(self) -> list[str]:
        missing = [] if self.url else ["адрес"]
        if not (self.user and self.password):
            missing.append("логин с паролем")
        if self.cert and _fingerprint(self.cert) is None:
            missing.append("отпечаток сертификата (64 шестнадцатеричных знака)")
        return missing

    def _base_headers(self) -> dict[str, str]:
        headers = super()._base_headers()
        pair = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        headers["Authorization"] = f"Basic {pair}"
        return headers

    async def _find(self, name: str) -> dict[str, Any] | None:
        payload = await self._call("GET", "api/client")
        for item in payload if isinstance(payload, list) else []:
            if isinstance(item, dict) and item.get("name") == name:
                return item
        return None

    async def _id(self, name: str) -> int:
        found = await self._find(name)
        if not found or found.get("id") is None:
            raise PanelError("Учётной записи в панели нет.")
        return int(found["id"])

    async def create_user(self, name: str, expire: int, traffic: int) -> Account:
        body = {"name": name, "expiresAt": to_iso(expire) if expire else None}
        await self._call("POST", "api/client", body=body)
        found = await self._find(name)
        if found is None:
            raise PanelError("wg-easy не показала только что созданного клиента.")
        return wgeasy_account(found, "")

    async def get_user(self, name: str) -> Account | None:
        found = await self._find(name)
        return wgeasy_account(found, "") if found else None

    async def set_expiry(self, name: str, expire: int) -> None:
        client_id = await self._id(name)
        full = await self._call("GET", f"api/client/{client_id}")
        if not isinstance(full, dict):
            raise PanelError("wg-easy ответила непонятно.")
        full["expiresAt"] = to_iso(expire) if expire else None
        await self._call("POST", f"api/client/{client_id}", body=full)

    async def set_traffic(self, name: str, traffic: int) -> None:
        raise PanelError("У wg-easy нет предела трафика.")

    async def disable(self, name: str) -> None:
        await self._call("POST", f"api/client/{await self._id(name)}/disable")

    async def enable(self, name: str) -> None:
        await self._call("POST", f"api/client/{await self._id(name)}/enable")

    async def subscription_url(self, name: str) -> str:
        client_id = await self._id(name)
        await self._call("POST", f"api/client/{client_id}/generateOneTimeLink")
        found = await self._find(name)
        link = (found or {}).get("oneTimeLink")
        code = link.get("oneTimeLink") if isinstance(link, dict) else link
        if not code:
            raise PanelError("wg-easy не выдала одноразовую ссылку.")
        return f"{self.url}/cnf/{code}"

    async def check(self) -> str:
        payload = await self._call("GET", "api/client")
        count = len(payload) if isinstance(payload, list) else 0
        return f"wg-easy отвечает, клиентов {count}; предела трафика у wg-easy нет"


def wgeasy_account(client: dict[str, Any], link: str) -> Account:
    return Account(
        name=str(client.get("name") or ""),
        enabled=bool(client.get("enabled", True)),
        expire=parse_time(client.get("expiresAt")),
        traffic_limit=0,
        traffic_used=_int(client.get("transferRx")) + _int(client.get("transferTx")),
        subscription_url=link,
    )


# --------------------------------------------------------------------------
#  Выбор панели
# --------------------------------------------------------------------------

KINDS: dict[str, type[Panel]] = {
    cls.kind: cls for cls in (
        XuiPanel, XuiLegacyPanel, SuiPanel, MarzbanPanel, PasarGuardPanel,
        MarzneshinPanel, RemnawavePanel, HiddifyPanel, OutlinePanel, WgEasyPanel,
    )
}

# Как люди пишут название панели в .env — не только как в коде.
_ALIASES = {
    "3x-ui": "3xui", "x-ui-3": "3xui", "mhsanaei": "3xui",
    "x-ui": "xui", "alireza": "xui",
    "s-ui": "sui",
    "pasar": "pasarguard", "pasar-guard": "pasarguard",
    "remna": "remnawave",
    "hiddify-manager": "hiddify",
    "shadowbox": "outline",
    "wg-easy": "wgeasy", "wireguard": "wgeasy",
}

# Что сознательно не поддерживается — чтобы на вопрос «а эта?» был ответ.
UNSUPPORTED = {
    "amnezia": "AmneziaVPN управляется по SSH, HTTP API для выдачи ключей у неё нет.",
    "xray": "Голый Xray или sing-box не хранит пользователей: нужна панель над ним.",
    "singbox": "Голый Xray или sing-box не хранит пользователей: нужна панель над ним.",
}


def normalize_kind(value: str) -> str:
    key = (value or "").strip().lower()
    return _ALIASES.get(key, key)


def build(kind: str, **options: Any) -> Panel | None:
    """Клиент нужной панели или None, если название незнакомое."""
    cls = KINDS.get(normalize_kind(kind))
    return cls(**options) if cls else None
