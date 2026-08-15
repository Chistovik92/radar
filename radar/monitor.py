"""Фоновый цикл: сбор источников, разбор через ИИ, группировка и рассылка."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import aiohttp

from . import ai, config, features, geocode, sos, sources, storage, weather
from .matching import Analysis, build_recap, cluster_title, geo_matches, plan_alerts
from .textutils import cluster_center, cluster_locations
from .tg import back_kb, send_html

log = logging.getLogger("radar.monitor")

seen = sources.SeenStore()
_stats = {"cycles": 0, "items": 0, "alerts": 0, "last_cycle": 0}

def stats() -> dict[str, Any]:
    return dict(_stats, seen=len(seen), cache=ai.cache_size(), **ai.counters())


# --------------------------------------------------------------------------
#  Погода: пора ли отправлять
# --------------------------------------------------------------------------

def weather_due(user: dict[str, Any], now_ts: int, now: datetime) -> bool:
    mode = user.get("weather_mode", "interval")
    if mode == "interval":
        interval = int(user.get("weather_interval") or 0)
        if interval <= 0:
            return False
        return now_ts - int(user.get("last_weather") or 0) >= interval * 60

    target = str(user.get("weather_time") or "08:00")
    try:
        hour, minute = (int(part) for part in target.split(":"))
    except ValueError:
        return False
    if user.get("last_fixed_date") == now.strftime("%Y-%m-%d"):
        return False
    # Сравниваем по окну, а не по точной минуте: цикл может длиться дольше минуты.
    return (now.hour, now.minute) >= (hour, minute)


# --------------------------------------------------------------------------
#  Геокодирование «хвостов» из старой базы
# --------------------------------------------------------------------------

async def backfill_geocode(session: aiohttp.ClientSession) -> None:
    """Дозаполняет город/улицу/дом у локаций, перенесённых из версий 2.x."""
    pending: list[dict[str, Any]] = []
    for user in storage.users().values():
        for loc in user.get("locs") or []:
            if loc.get("city") or not (loc.get("lat") or loc.get("lon")):
                continue
            pending.append(loc)
    if not pending:
        return

    log.info("Дозаполняю адреса для %d локаций из старой базы", len(pending))
    for loc in pending:
        info = await geocode.reverse(session, float(loc["lat"]), float(loc["lon"]))
        for key in ("street", "house", "city", "district", "region"):
            if info.get(key):
                loc[key] = info[key]
        if loc.get("name", "").replace(" ", "").replace(",", "").replace(".", "").isdigit():
            loc["name"] = info.get("name") or loc["name"]
    await storage.save()
    log.info("Адреса дозаполнены")


# --------------------------------------------------------------------------
#  Рассылка одному пользователю
# --------------------------------------------------------------------------

async def dispatch_user(
    session: aiohttp.ClientSession,
    uid: str,
    user: dict[str, Any],
    analyses: list[Analysis],
    now_ts: int,
    now: datetime,
) -> bool:
    """Готовит и отправляет сообщения одному пользователю. True — база изменена."""
    locations = user.get("locs") or []
    if not locations:
        return False

    messages = plan_alerts(
        locations,
        user.get("settings") or {},
        analyses,
        config.CLUSTER_RADIUS_M,
        config.DEFAULT_CITY,
    )

    sent = 0
    for _kind, text in messages:
        if await send_html(uid, text, back_kb()):
            sent += 1
        await asyncio.sleep(0.3)

    changed = False
    if weather_due(user, now_ts, now):
        clusters = cluster_locations(locations, config.CLUSTER_RADIUS_M)
        for index, cluster in enumerate(clusters):
            lat, lon = cluster_center(cluster)
            data = await weather.fetch(session, lat, lon)
            markup = back_kb() if index == len(clusters) - 1 else None
            await send_html(uid, weather.render(data, cluster_title(cluster)), markup)
            sent += 1
            await asyncio.sleep(0.2)
        user["last_weather"] = now_ts
        if user.get("weather_mode") == "time":
            user["last_fixed_date"] = now.strftime("%Y-%m-%d")
        changed = True

    _stats["alerts"] += sent
    return changed


# --------------------------------------------------------------------------
#  Цикл
# --------------------------------------------------------------------------

# Завершившиеся события копятся до утренней и вечерней сводки: тревожить
# ими сразу бессмысленно, а знать о них полезно.
_recap_pool: list[Analysis] = []
_recap_sent: dict[str, str] = {}

RECAP_HOURS = (9, 20)


def collect_recap(analyses: list[Analysis]) -> None:
    for item in analyses:
        if item.historical and item.relevant:
            _recap_pool.append(item)
    # Держим разумный объём: сводка за сутки, а не за месяц
    del _recap_pool[:-100]


def recap_due(now: datetime) -> str | None:
    """Пора ли отправлять сводку. Возвращает метку периода или None."""
    if not _recap_pool:
        return None
    for hour in RECAP_HOURS:
        if now.hour == hour:
            marker = f"{now:%Y-%m-%d}-{hour}"
            if _recap_sent.get("last") != marker:
                return marker
    return None


async def send_recap(now: datetime) -> None:
    """Утренняя и вечерняя сводка по тому, что уже произошло."""
    marker = recap_due(now)
    if marker is None:
        return

    _recap_sent["last"] = marker
    period = "за ночь" if now.hour < 12 else "за день"

    delivered = 0
    for uid, user in list(storage.users().items()):
        locations = user.get("locs") or []
        if not locations:
            continue
        enabled = {key for key, value in (user.get("settings") or {}).items() if value}

        relevant = [
            item for item in _recap_pool
            if (set(item.categories) & enabled)
            and any(geo_matches(item, loc) for loc in locations)
        ]
        if not relevant:
            continue

        hint = str(locations[0].get("city") or "")
        text = build_recap(relevant, period, hint)
        if text and await send_html(uid, text, back_kb()):
            delivered += 1
        await asyncio.sleep(0.3)

    log.info("Сводка %s разослана: %d получателей", period, delivered)
    _recap_pool.clear()


async def repeat_sos() -> None:
    """Повторяет активные сигналы SOS, пока отправитель не дал отбой."""
    if not features.enabled("sos"):
        return

    for alert in sos.due_alerts():
        owner = storage.get_user(alert.owner)
        if owner is None:
            sos.stop_alert(alert.owner)
            continue

        alert.repeats += 1
        alert.last_sent = time.time()
        text = sos.build_alert(
            owner.get("username") or f"ID {alert.owner}",
            "",
            alert.lat,
            alert.lon,
            alert.address,
            alert.note,
            repeat=alert.repeats,
        )
        for contact in sos.confirmed_contacts(owner):
            await send_html(contact.key, text)
        log.info("Повтор сигнала SOS от %s (%d)", alert.owner, alert.repeats)

        if alert.repeats >= sos.MAX_REPEATS:
            sos.stop_alert(alert.owner)
            await send_html(
                alert.owner,
                "🆘 Повторы сигнала прекращены — достигнут предел. "
                "Нажмите SOS заново, если помощь всё ещё нужна.",
            )


async def cycle(session: aiohttp.ClientSession, *, warmup: bool = False) -> None:
    items = await sources.collect(
        session,
        storage.channels(),
        storage.rss_feeds(),
        seen,
        config.MSG_PER_SOURCE,
        warmup=warmup,
    )
    if warmup:
        log.info("Первый проход: %d сообщений помечены прочитанными", len(seen))
        return

    _stats["cycles"] += 1
    _stats["items"] += len(items)
    _stats["last_cycle"] = int(time.time())

    analyses: list[Analysis] = []
    if items:
        try:
            parsed = await ai.analyze_batch(
                [(item.text, item.source, item.link) for item in items]
            )
        except Exception:  # noqa: BLE001
            log.exception("Пакетный разбор сообщений не удался")
            parsed = []
        analyses = [analysis for analysis in parsed if analysis.relevant]
        collect_recap(analyses)
        counters = ai.counters()
        log.info(
            "Новых сообщений: %d, значимых: %d | запросов к ИИ: %d, "
            "отсеяно фильтром: %d, из кэша: %d, эвристикой: %d",
            len(items), len(analyses), counters["requests"],
            counters["prefiltered"], counters["cached"], counters["heuristic"],
        )

    now_ts = int(time.time())
    now = datetime.now()
    changed = False
    for uid, user in list(storage.users().items()):
        try:
            if await dispatch_user(session, uid, user, analyses, now_ts, now):
                changed = True
        except Exception:  # noqa: BLE001
            log.exception("Ошибка рассылки пользователю %s", uid)
    if changed:
        await storage.save()


async def run() -> None:
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "ru,en;q=0.8"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            await backfill_geocode(session)
        except Exception:  # noqa: BLE001
            log.exception("Дозаполнение адресов не удалось")

        await cycle(session, warmup=True)

        while True:
            started = time.monotonic()
            try:
                await repeat_sos()
                await send_recap(datetime.now())
                await cycle(session)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Сбой цикла мониторинга")
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(15.0, config.POLL_INTERVAL - elapsed))
