"""Сетевые проверки: раскрытие редиректов, возраст домена, Safe Browsing.

Все функции асинхронны, каждая возвращает деградированный результат
вместо исключения — так тесты могут подменять сессию, а бот не падает.

Адрес проверяемой ссылки проверяется на частные подсети: запрос
к 127.0.0.1 или 10.x из бота, живущего на сервере, — это обращение
к самому серверу, и отдавать его наружу нельзя.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger("radar.linkcheck.netcheck")

TIMEOUT = aiohttp.ClientTimeout(total=12, connect=6)
MAX_REDIRECTS = 5
RDAP_BOOTSTRAP = "https://rdap.org/domain/"


async def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LinkCheck/1.0)"},
        trust_env=True,
    )


def _is_public_ip(ip: str) -> bool:
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast)
    except ValueError:
        return False


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        return [info[4][0] for info in infos]
    except Exception as exc:  # noqa: BLE001
        log.warning("resolve failed %s: %s", host, exc)
        return []


async def expand(url: str) -> "NetResult":
    from .analyze import NetResult

    res = NetResult()
    res.chain = [url]
    cur = url

    for _ in range(MAX_REDIRECTS):
        parsed = urlparse(cur)
        host = parsed.netloc.split("@")[-1].split(":")[0]
        ips = await _resolve(host)
        if not ips:
            res.notes.append("dns failed")
            res.final_url = cur
            return res
        if not all(_is_public_ip(ip) for ip in ips):
            res.notes.append("private ip blocked")
            res.final_url = cur
            return res

        try:
            async with _session() as sess:
                async with sess.head(cur, allow_redirects=False) as resp:
                    if 300 <= resp.status < 400:
                        location = resp.headers.get("Location")
                        if not location:
                            break
                        cur = location if location.startswith("http") else f"{parsed.scheme}://{host}{location}"
                        res.chain.append(cur)
                        continue
                    res.success = True
                    res.final_url = cur
                    return res
        except asyncio.TimeoutError:
            res.notes.append("timeout")
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("expand failed %s: %s", cur, exc)
            res.notes.append(f"error: {type(exc).__name__}")
            break
    res.final_url = cur
    return res


async def domain_age(host: str) -> "NetResult":
    from .analyze import NetResult

    res = NetResult()
    try:
        async with _session() as sess:
            async with sess.get(f"{RDAP_BOOTSTRAP}{host}") as resp:
                if resp.status != 200:
                    res.notes.append(f"rdap {resp.status}")
                    return res
                data = await resp.json(content_type=None)
                events = data.get("events", [])
                for ev in events:
                    if ev.get("eventAction") == "registration":
                        reg = ev.get("eventDate")
                        if reg:
                            dt = datetime.fromisoformat(reg.replace("Z", "+00:00"))
                            res.domain_age_days = (datetime.now(timezone.utc) - dt).days
                            break
    except Exception as exc:  # noqa: BLE001
        log.warning("rdap failed %s: %s", host, exc)
        res.notes.append(f"rdap error: {type(exc).__name__}")
    return res


async def safe_browsing(url: str, api_key: str | None) -> "NetResult":
    from .analyze import NetResult

    res = NetResult()
    if not api_key:
        res.notes.append("no api key")
        return res
    try:
        body = {
            "client": {"clientId": "radar-linkcheck", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING",
                                "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }
        async with _session() as sess:
            async with sess.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={api_key}",
                json=body,
            ) as resp:
                if resp.status != 200:
                    res.notes.append(f"safebrowsing {resp.status}")
                    return res
                data = await resp.json(content_type=None)
                matches = data.get("threatMatches", [])
                for m in matches:
                    t = m.get("threatType", "unknown")
                    res.threats.append(t)
                res.success = True
    except Exception as exc:  # noqa: BLE001
        log.warning("safebrowsing failed %s: %s", url, exc)
        res.notes.append(f"safebrowsing error: {type(exc).__name__}")
    return res


async def cert_info(host: str) -> "NetResult":
    from .analyze import NetResult

    res = NetResult()
    writer = None
    try:
        loop = asyncio.get_running_loop()
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        # Соединение закрывается в finally независимо от того, дошло ли
        # дело до сертификата: раньше при отсутствии сокета у writer оно
        # утекало и висело до таймаута.
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 443, ssl=ctx),
            timeout=6,
        )
        sock = writer.get_extra_info("socket")
        if sock:
            cert = sock.getpeercert()
            not_after = cert.get("notAfter")
            if not_after:
                expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                expires = expires.replace(tzinfo=timezone.utc)
                res.cert_valid_days = (expires - datetime.now(timezone.utc)).days
                res.success = True
    except Exception as exc:  # noqa: BLE001
        log.warning("cert failed %s: %s", host, exc)
        res.notes.append(f"cert error: {type(exc).__name__}")
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
    return res


async def full_check(url: str, api_key: str | None = None) -> "NetResult":
    from .analyze import NetResult

    chain = await expand(url)
    if not chain.success:
        return chain

    parsed = urlparse(chain.final_url)
    host = parsed.netloc.split("@")[-1].split(":")[0]

    age = await domain_age(host)
    sb = await safe_browsing(chain.final_url, api_key)
    cert = await cert_info(host)

    return NetResult(
        success=True,
        final_url=chain.final_url,
        chain=chain.chain,
        domain_age_days=age.domain_age_days,
        cert_valid_days=cert.cert_valid_days,
        threats=sb.threats,
        notes=chain.notes + age.notes + sb.notes + cert.notes,
    )
