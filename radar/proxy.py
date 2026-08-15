"""Выход бота в интернет через внешний узел: подписки, ключи, выбор сервера.

Как это устроено
----------------
Бот сам не устанавливает соединение: он ходит через локальный SOCKS5, который
поднимает sing-box в соседнем контейнере. Здесь — разбор ключей и подписок,
список серверов и генерация конфигурации для sing-box.

Ключевое правило: **добавление ключа ничего не включает**. Из подписки
приходят десятки серверов разных протоколов, и выбирать за администратора,
через какой именно пойдёт трафик бота, неправильно — от этого зависит
и скорость, и то, из какой страны бот виден площадкам. Пока сервер не выбран
явно, выход в сеть остаётся прямым.

Поддерживаются: подписка (base64-список или построчный), VLESS, Shadowsocks,
Trojan, а также готовые SOCKS5 и HTTP-прокси.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

log = logging.getLogger("radar.proxy")

SUPPORTED = ("vless", "ss", "trojan", "socks5", "http")

LOCAL_PORT = 1080
CONFIG_PATH = "data/singbox/config.json"


@dataclass
class Server:
    """Один узел из подписки или отдельной ссылки."""

    protocol: str
    host: str
    port: int
    title: str = ""
    uuid: str = ""            # VLESS
    password: str = ""        # Shadowsocks, Trojan, SOCKS5
    method: str = ""          # Shadowsocks
    security: str = ""        # tls | reality | none
    sni: str = ""
    flow: str = ""
    public_key: str = ""      # Reality
    short_id: str = ""
    fingerprint: str = ""
    transport: str = ""       # ws | grpc | tcp
    path: str = ""
    host_header: str = ""
    raw: str = ""

    @property
    def key(self) -> str:
        """Устойчивый идентификатор: подписка может менять порядок серверов."""
        return f"{self.protocol}:{self.host}:{self.port}"

    @property
    def label(self) -> str:
        name = self.title or self.host
        marker = self.protocol.upper()
        if self.security in ("reality", "tls"):
            marker += f"+{self.security}"
        return f"{name} · {marker}"

    def to_outbound(self) -> dict[str, Any]:
        """Конфигурация исходящего соединения для sing-box."""
        outbound: dict[str, Any] = {
            "type": self.protocol if self.protocol != "ss" else "shadowsocks",
            "tag": "proxy",
            "server": self.host,
            "server_port": self.port,
        }

        if self.protocol == "vless":
            outbound["uuid"] = self.uuid
            if self.flow:
                outbound["flow"] = self.flow
        elif self.protocol == "ss":
            outbound["method"] = self.method or "aes-256-gcm"
            outbound["password"] = self.password
        elif self.protocol == "trojan":
            outbound["password"] = self.password
        elif self.protocol in ("socks5", "http"):
            outbound["type"] = "socks" if self.protocol == "socks5" else "http"
            if self.password:
                outbound["username"] = self.uuid or "user"
                outbound["password"] = self.password
            return outbound

        if self.security == "reality":
            outbound["tls"] = {
                "enabled": True,
                "server_name": self.sni or self.host,
                "utls": {"enabled": True, "fingerprint": self.fingerprint or "chrome"},
                "reality": {
                    "enabled": True,
                    "public_key": self.public_key,
                    "short_id": self.short_id,
                },
            }
        elif self.security == "tls":
            outbound["tls"] = {
                "enabled": True,
                "server_name": self.sni or self.host,
                "insecure": False,
            }

        if self.transport == "ws":
            outbound["transport"] = {
                "type": "ws",
                "path": self.path or "/",
                "headers": {"Host": self.host_header or self.sni or self.host},
            }
        elif self.transport == "grpc":
            outbound["transport"] = {"type": "grpc", "service_name": self.path or ""}

        return outbound


# --------------------------------------------------------------------------
#  Разбор
# --------------------------------------------------------------------------

def _decode_base64(text: str) -> str:
    """Мягкое декодирование: подписки часто без выравнивания и в URL-варианте."""
    cleaned = re.sub(r"\s+", "", text)
    cleaned = cleaned.replace("-", "+").replace("_", "/")
    padding = len(cleaned) % 4
    if padding:
        cleaned += "=" * (4 - padding)
    try:
        return base64.b64decode(cleaned).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return ""


def parse_vless(uri: str) -> Server | None:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if parsed.scheme != "vless" or not parsed.hostname:
        return None

    query = parse_qs(parsed.query)

    def first(name: str, default: str = "") -> str:
        values = query.get(name)
        return values[0] if values else default

    return Server(
        protocol="vless",
        host=parsed.hostname,
        port=parsed.port or 443,
        title=unquote(parsed.fragment or ""),
        uuid=parsed.username or "",
        security=first("security", "none"),
        sni=first("sni") or first("peer"),
        flow=first("flow"),
        public_key=first("pbk"),
        short_id=first("sid"),
        fingerprint=first("fp"),
        transport=first("type", "tcp"),
        path=unquote(first("path")),
        host_header=first("host"),
        raw=uri,
    )


def parse_shadowsocks(uri: str) -> Server | None:
    """Формат ss:// встречается в двух видах: с base64 и без."""
    body = uri[5:]
    fragment = ""
    if "#" in body:
        body, fragment = body.split("#", 1)

    if "@" not in body:
        decoded = _decode_base64(body)
        if "@" not in decoded:
            return None
        body = decoded
        credentials, _, address = body.rpartition("@")
    else:
        credentials, _, address = body.rpartition("@")
        if ":" not in credentials:
            decoded = _decode_base64(credentials)
            if decoded:
                credentials = decoded

    if ":" not in credentials or ":" not in address:
        return None
    method, _, password = credentials.partition(":")
    host, _, port = address.partition(":")
    port = port.split("?")[0].split("/")[0]

    try:
        port_number = int(port)
    except ValueError:
        return None

    return Server(
        protocol="ss", host=host, port=port_number,
        title=unquote(fragment), method=method, password=password, raw=uri,
    )


def parse_trojan(uri: str) -> Server | None:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    query = parse_qs(parsed.query)
    return Server(
        protocol="trojan",
        host=parsed.hostname,
        port=parsed.port or 443,
        title=unquote(parsed.fragment or ""),
        password=parsed.username or "",
        security="tls",
        sni=(query.get("sni") or [""])[0],
        transport=(query.get("type") or ["tcp"])[0],
        path=unquote((query.get("path") or [""])[0]),
        raw=uri,
    )


def parse_plain_proxy(uri: str) -> Server | None:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if parsed.scheme not in ("socks5", "socks", "http", "https") or not parsed.hostname:
        return None
    protocol = "socks5" if parsed.scheme.startswith("socks") else "http"
    return Server(
        protocol=protocol,
        host=parsed.hostname,
        port=parsed.port or (1080 if protocol == "socks5" else 8080),
        title=parsed.hostname,
        uuid=parsed.username or "",
        password=parsed.password or "",
        raw=uri,
    )


def parse_uri(uri: str) -> Server | None:
    text = (uri or "").strip()
    if not text:
        return None
    if text.startswith("vless://"):
        return parse_vless(text)
    if text.startswith("ss://"):
        return parse_shadowsocks(text)
    if text.startswith("trojan://"):
        return parse_trojan(text)
    if text.startswith(("socks5://", "socks://", "http://", "https://")):
        # Ссылка на подписку тоже начинается с http — отличаем по содержимому
        return parse_plain_proxy(text)
    return None


def parse_subscription(payload: str) -> list[Server]:
    """Разбирает содержимое подписки: base64-блок или список ссылок."""
    text = (payload or "").strip()
    if not text:
        return []

    # Подписки чаще всего приходят одним base64-блоком
    if "://" not in text:
        decoded = _decode_base64(text)
        if decoded:
            text = decoded

    servers: list[Server] = []
    seen: set[str] = set()
    for line in text.splitlines():
        server = parse_uri(line.strip())
        if server is not None and server.key not in seen:
            seen.add(server.key)
            servers.append(server)
    return servers


def is_subscription_url(text: str) -> bool:
    """Ссылка на подписку, а не готовый прокси."""
    value = (text or "").strip().lower()
    if not value.startswith(("http://", "https://")):
        return False
    # У прокси нет пути; у подписки он почти всегда есть
    parsed = urlparse(value)
    return bool(parsed.path and parsed.path not in ("/", ""))


# --------------------------------------------------------------------------
#  Состояние
# --------------------------------------------------------------------------

@dataclass
class ProxyState:
    """Что известно о выходе в сеть."""

    source: str = ""                       # ссылка на подписку или сам ключ
    servers: list[Server] = field(default_factory=list)
    selected: str = ""                     # key выбранного сервера
    enabled: bool = False

    @property
    def active(self) -> Server | None:
        if not self.enabled or not self.selected:
            return None
        return next((item for item in self.servers if item.key == self.selected), None)

    def by_protocol(self) -> dict[str, list[Server]]:
        grouped: dict[str, list[Server]] = {}
        for server in self.servers:
            grouped.setdefault(server.protocol, []).append(server)
        return grouped


def build_config(server: Server, port: int = LOCAL_PORT) -> dict[str, Any]:
    """Конфигурация sing-box: локальный SOCKS5 → выбранный узел."""
    return {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "socks",
                "tag": "in",
                "listen": "0.0.0.0",
                "listen_port": port,
                "sniff": True,
            }
        ],
        "outbounds": [server.to_outbound(), {"type": "direct", "tag": "direct"}],
        "route": {"final": "proxy"},
    }


def render_config(server: Server, port: int = LOCAL_PORT) -> str:
    return json.dumps(build_config(server, port), ensure_ascii=False, indent=2)


def describe(state: ProxyState) -> str:
    """Состояние для сообщения в боте."""
    from .textutils import esc

    lines = ["🌐 <b>Выход в интернет</b>", ""]

    if not state.servers:
        lines.append("Ключ или подписка не добавлены — бот ходит напрямую.")
        return "\n".join(lines)

    grouped = state.by_protocol()
    summary = ", ".join(
        f"{protocol.upper()}: {len(items)}" for protocol, items in sorted(grouped.items())
    )
    lines.append(f"Загружено серверов: <b>{len(state.servers)}</b> ({esc(summary)})")

    active = state.active
    if active is not None:
        lines.append(f"Активен: <b>{esc(active.label)}</b>")
    elif state.selected:
        lines.append("Сервер выбран, но выход через него выключен.")
    else:
        lines.append(
            "⚠️ Сервер не выбран — трафик идёт напрямую.\n"
            "<i>Ключ сам по себе ничего не включает: выберите узел "
            "и протокол вручную.</i>"
        )
    return "\n".join(lines)
