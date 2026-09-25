"""Общий текстовый ответчик для сетей без Telegram-интерфейса (с 5.7).

⚠️ С ЖИВЫМИ ВК И MAX НЕ ПРОВЕРЕН.

До 5.7 бот во ВКонтакте и MAX был только вторым каналом: адреса задавались
в Telegram, а сюда приходили копии. С общим аккаунтом (`radar/links.py`)
начать можно в любой сети, поэтому здесь — всё, что нужно для тревог:

* `/address улица, дом, город` — найти адрес и **после подтверждения**
  сохранить его (без подтверждённой географии тревога не отправляется —
  поэтому найденное показывается и сохраняется только после «да»);
* геопозиция — то же, с определением адреса по точке;
* `/addresses` — список, `/remove N` — удалить;
* `/link`, код, `/unlink` — общий аккаунт с Telegram, ВК, MAX, Discord;
* `/status` — работает ли мониторинг; `/lang en` — язык ответов.

Настройки категорий, тихие часы, погода и подписки — в Telegram-боте или
по умолчанию: вторая реализация всех экранов поверх текстового чата стоила
бы дороже, чем даёт. Тревоги приходят по всем категориям.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .. import links

log = logging.getLogger("radar.platform.textbot")

PENDING_TTL = 600
SAME_PLACE_M = 40

DISCLAIMER = "Система не заменяет официальные каналы оповещения."

# Ожидающие подтверждения адреса: ключ входа → (адрес, до).
_pending: dict[str, tuple[dict[str, Any], float]] = {}

_ADDRESS_RE = re.compile(r"^/?(?:address|адрес)\s+(.+)$", re.IGNORECASE | re.S)
_REMOVE_RE = re.compile(r"^/?(?:remove|удалить)\s+(\d+)\s*$", re.IGNORECASE)
_LANG_RE = re.compile(r"^/?(?:lang|язык)\s+(ru|en)\s*$", re.IGNORECASE)


def _t(key: str, lang: str, default: str) -> str:
    from .. import i18n

    return i18n.t(key, lang, default)


def reset() -> None:
    _pending.clear()


def pending_for(platform: str, external_id: str | int) -> bool:
    """Ждёт ли адрес подтверждения — для кнопок «Да»/«Нет» в Discord."""
    entry = _pending.get(links.key_of(platform, external_id))
    return bool(entry and entry[1] >= time.time())


def help_text(lang: str, has_addresses: bool) -> str:
    head = _t("text.about", lang,
              "Система «Радар» следит за городскими угрозами и авариями ЖКХ "
              "по вашим адресам и присылает только то, что касается их.")
    if has_addresses:
        state = _t("text.has_addresses", lang,
                   "Адреса заданы — тревоги по ним приходят сюда.")
    else:
        state = _t("text.no_addresses", lang,
                   "Адресов пока нет. Добавьте первый: /address улица, дом, город "
                   "— или отправьте геопозицию.")
    commands = _t("text.commands", lang,
                  "/address улица, дом, город — добавить адрес\n"
                  "/addresses — мои адреса, /remove N — удалить\n"
                  "/link — связать с Telegram, ВК, MAX или Discord\n"
                  "/unlink — отвязать этот аккаунт\n"
                  "/status — работает ли мониторинг\n"
                  "/panel — код входа в веб-панель (для модераторов)\n"
                  "/lang en — English")
    return f"{head}\n\n{state}\n\n{commands}\n\n{_t('text.disclaimer', lang, DISCLAIMER)}"


def status_text(lang: str = "ru") -> str:
    from .. import monitor

    healthy, silent = monitor.alive()
    if healthy:
        return _t("text.status_ok", lang, "✅ Мониторинг работает.")
    return _t("text.status_bad", lang,
              "🚨 Мониторинг молчит около {minutes} мин. Администрация уведомлена."
              ).format(minutes=max(1, silent // 60))


def _describe(place: dict[str, Any]) -> str:
    parts = [str(place.get("name") or "")]
    details = ", ".join(str(place.get(key) or "") for key in ("district", "city", "region")
                        if place.get(key) and str(place.get(key)) not in parts[0])
    return parts[0] + (f" ({details})" if details else "")


async def _geocode_text(query: str, hint: str) -> list[dict[str, Any]]:
    import aiohttp

    from .. import config, geocode

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),
                                     headers={"User-Agent": config.USER_AGENT}) as session:
        return await geocode.forward(session, query, hint)


async def _geocode_point(lat: float, lon: float) -> dict[str, Any]:
    import aiohttp

    from .. import config, geocode

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25),
                                     headers={"User-Agent": config.USER_AGENT}) as session:
        info = await geocode.reverse(session, lat, lon)
    return dict(info, lat=lat, lon=lon)


def _duplicate(user: dict[str, Any] | None, lat: float, lon: float) -> str:
    from ..textutils import haversine_m

    for item in (user or {}).get("locs") or []:
        try:
            if haversine_m(lat, lon, float(item["lat"]), float(item["lon"])) < SAME_PLACE_M:
                return str(item.get("name") or "")
        except (KeyError, TypeError, ValueError):
            continue
    return ""


async def _propose(key: str, place: dict[str, Any], user: dict[str, Any] | None,
                   lang: str) -> str:
    lat, lon = float(place["lat"]), float(place["lon"])
    same = _duplicate(user, lat, lon)
    if same:
        return _t("text.already", lang, "ℹ️ Этот адрес уже сохранён: {name}.").format(name=same)
    _pending[key] = (dict(place, lat=lat, lon=lon), time.time() + PENDING_TTL)
    return _t("text.confirm_address", lang,
              "Нашёл: {place}\nСохранить этот адрес? Ответьте «да» или «нет». "
              "Если не то — уточните: /address улица, дом, город."
              ).format(place=_describe(place))


async def _save_place(owner: str, place: dict[str, Any], lang: str) -> str:
    from .. import config, storage

    user = storage.get_user(owner)
    if user is None:
        user = storage.register(owner)
        user["lang"] = lang if lang in ("ru", "en") else "ru"
    if config.MAX_LOCATIONS and len(user["locs"]) >= config.MAX_LOCATIONS:
        return _t("text.limit", lang, "❌ Достигнут предел адресов ({limit}).").format(
            limit=config.MAX_LOCATIONS)
    location = storage.new_location(
        str(place.get("name") or ""), float(place["lat"]), float(place["lon"]),
        street=place.get("street") or "", house=place.get("house") or "",
        city=place.get("city") or "", district=place.get("district") or "",
        region=place.get("region") or "")
    user["locs"].append(location)
    await storage.save(owner)
    text = _t("text.saved", lang, "🏠 Адрес сохранён: {name}. Тревоги по нему будут "
                                  "приходить сюда.").format(name=location["name"])
    if not location["street"]:
        text += "\n" + _t("text.no_street", lang,
                          "⚠️ Улица не определена — адресные оповещения ЖКХ могут быть "
                          "неточными.")
    return text


def _list(user: dict[str, Any] | None, lang: str) -> str:
    places = (user or {}).get("locs") or []
    if not places:
        return _t("text.empty", lang, "Адресов пока нет. /address улица, дом, город")
    lines = [_t("text.list", lang, "Ваши адреса:")]
    lines += [f"{index}. {_describe(item)}" for index, item in enumerate(places, 1)]
    lines.append(_t("text.remove_hint", lang, "Удалить: /remove N"))
    return "\n".join(lines)


async def answer(platform: str, external_id: str | int, text: str = "", *,
                 location: tuple[float, float] | None = None) -> str:
    """Ответ на сообщение из текстовой сети. Отделён от сети — проверяется офлайн."""
    from .. import storage

    key = links.key_of(platform, external_id)
    owner = await links.canonical(key)
    user = storage.get_user(owner)
    lang = str((user or {}).get("lang") or "ru")
    stripped = (text or "").strip()
    lowered = stripped.lower()

    # Привязка: код, /link, /unlink и «да»/«нет» на предложение связи.
    linked = await links.handle_text(platform, external_id, stripped, lang)
    if linked:
        return linked

    moment = time.time()
    for stale in [name for name, (_, until) in _pending.items() if until < moment]:
        _pending.pop(stale, None)

    if location is not None:
        try:
            place = await _geocode_point(float(location[0]), float(location[1]))
        except Exception:  # noqa: BLE001
            log.warning("Адрес по геопозиции не определён", exc_info=True)
            return _t("text.geo_failed", lang, "Не удалось определить адрес. Попробуйте позже.")
        return await _propose(key, place, user, lang)

    if key in _pending and lowered in links.YES + links.NO:
        place, _ = _pending.pop(key)
        if lowered in links.NO:
            return _t("text.not_saved", lang, "Хорошо, не сохраняю.")
        return await _save_place(owner, place, lang)

    match = _ADDRESS_RE.match(stripped)
    if match:
        hint = ""
        if user and user.get("locs"):
            hint = str(user["locs"][0].get("city") or "")
        try:
            found = await _geocode_text(match.group(1).strip(), hint)
        except Exception:  # noqa: BLE001
            log.warning("Поиск адреса не удался", exc_info=True)
            found = []
        if not found:
            return _t("text.not_found", lang,
                      "Адрес не найден. Уточните: улица, дом, город — или отправьте "
                      "геопозицию.")
        return await _propose(key, found[0], user, lang)

    if lowered in ("/addresses", "addresses", "адреса"):
        return _list(user, lang)

    match = _REMOVE_RE.match(stripped)
    if match:
        places = (user or {}).get("locs") or []
        index = int(match.group(1)) - 1
        if not 0 <= index < len(places):
            return _t("text.no_such", lang, "Такого номера нет. /addresses — список.")
        removed = places.pop(index)
        await storage.save(owner)
        return _t("text.removed", lang, "Удалено: {name}.").format(name=removed.get("name"))

    match = _LANG_RE.match(stripped)
    if match:
        chosen = match.group(1).lower()
        if user is None:
            user = storage.register(owner)
        user["lang"] = chosen
        await storage.save(owner)
        return _t("text.lang_set", chosen, "Язык ответов: русский.")

    if lowered in ("/panel", "panel", "панель"):
        import asyncio

        reply, issued = links.panel_code(owner, user, lang)
        if issued:
            asyncio.get_running_loop().create_task(links.announce_panel(owner, platform))
        return reply

    if lowered in ("/status", "status", "статус"):
        return status_text(lang) + "\n\n" + _t("text.disclaimer", lang, DISCLAIMER)

    return help_text(lang, bool((user or {}).get("locs")))
