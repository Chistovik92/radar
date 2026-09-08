"""Куда боту можно ходить по ссылке, присланной человеком.

Ссылку в бот присылает кто угодно, а запрос по ней делает бот — изнутри
docker-сети, где рядом стоят база, sing-box и Bot API Server, а у облачных
хостингов по адресу 169.254.169.254 отвечает служба метаданных. Ссылка
вида `http://radar_db:5432` или `http://127.0.0.1:8080/keys` превращает
бота в посредника, через которого снаружи щупают внутреннюю сеть: даже
код ответа, показанный человеку («сервер ответил кодом 200»), уже
говорит, что за этим адресом кто-то живёт.

Проверять адрес до запроса мало: сервер отвечает редиректом на
`127.0.0.1`, а домен с коротким TTL отдаёт публичный адрес на проверку
и внутренний — на само соединение (DNS rebinding). Поэтому фильтр стоит
не перед запросом, а в резолвере соединения: aiohttp соединяется только
с теми адресами, которые вернул резолвер, и каждый редирект проходит
ту же проверку заново.

Модуль появился в 4.9.5.6 по итогам разбора: в linkcheck такая проверка
была с самого начала (`multitool/linkcheck/netcheck.py`), а в разборе
ссылок на картинки и видео её не было вовсе.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

log = logging.getLogger("radar.netguard")


def is_public_ip(value: str) -> bool:
    """Публичный ли адрес. Всё сомнительное считаем внутренним."""
    try:
        addr = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _resolver_base():
    """DefaultResolver aiohttp. Импорт внутри: офлайн-проверки без сети."""
    import aiohttp

    return aiohttp.DefaultResolver()


def resolver():
    """Резолвер, который отдаёт только публичные адреса.

    Наследование объявлено здесь, а не на уровне модуля: базовый класс
    живёт в aiohttp, а он в офлайн-проверках подменяется заглушкой.
    """
    import aiohttp

    class PublicOnlyResolver(aiohttp.abc.AbstractResolver):
        def __init__(self) -> None:
            self._inner = _resolver_base()

        async def resolve(self, host, port=0, family=socket.AF_INET):
            infos = await self._inner.resolve(host, port, family)
            allowed = [item for item in infos if is_public_ip(str(item["host"]))]
            if not allowed:
                log.info("Адрес %s ведёт во внутреннюю сеть — запрос отклонён", host)
                raise OSError(f"адрес {host} ведёт во внутреннюю сеть")
            return allowed

        async def close(self) -> None:
            await self._inner.close()

    return PublicOnlyResolver()


def connector(**kwargs):
    """TCPConnector, который не соединится с внутренним адресом."""
    import aiohttp

    kwargs.setdefault("resolver", resolver())
    kwargs.setdefault("ttl_dns_cache", 0)   # иначе кэш пережил бы проверку
    return aiohttp.TCPConnector(**kwargs)


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").strip()
    except ValueError:
        return ""


async def allowed(url: str) -> bool:
    """Ведёт ли ссылка наружу. Для тех, кому резолвер не подставить.

    yt-dlp ходит своей сетевой частью, и резолвер aiohttp на неё
    не действует — там остаётся только проверка до запроса. От подмены
    адреса между проверкой и запросом она не спасает, но закрывает
    прямые ссылки на внутренние адреса, а это основной случай.
    """
    import asyncio

    host = host_of(url)
    if not host:
        return False

    # Адрес мог быть записан числом — тогда резолвить нечего.
    try:
        ipaddress.ip_address(host)
        return is_public_ip(host)
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        log.info("Имя %s не разобрано: %s", host, exc)
        return False

    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        return False
    # Достаточно одного внутреннего адреса, чтобы отказать: имя с двумя
    # записями, одна из которых 127.0.0.1, — это и есть обход проверки.
    return all(is_public_ip(item) for item in addresses)
