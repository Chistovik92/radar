"""Метаданные треков из открытых баз (с 4.9.9.3).

Пункт 3 раздела 4.9.5 дорожной карты: «источники для подбора». Подбор
похожего работал только по ID3-тегам самого файла, а у половины треков
жанра в тегах нет — и подбор для них был пуст. Здесь два открытых
источника, без ключей и регистрации:

* **MusicBrainz** — жанр и идентификатор артиста по паре «артист —
  название». Жанр дописывается в трек, только если в тегах его не было:
  то, что человек задал сам, не переписывается;
* **ListenBrainz** — родственные артисты по идентификатору: кого слушают
  вместе. Список хранится в треке и учитывается подбором похожего
  *внутри своего хранилища* — общей библиотеки по-прежнему нет.

Last.fm сюда не входит: ему нужен ключ, а его условия ограничивают
перепродажу — для бота с платной ёмкостью это не формальность.

Вежливость к чужим сервисам не обсуждается: MusicBrainz разрешает один
запрос в секунду и требует внятный User-Agent с контактом. Обогащение
идёт фоном после загрузки трека и никогда не задерживает ни ответ
человеку, ни оповещения.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger("radar.musicmeta")

MUSICBRAINZ = "https://musicbrainz.org/ws/2/recording"
LISTENBRAINZ = "https://labs.api.listenbrainz.org/similar-artists/json"
# Алгоритм ListenBrainz — строка из их документации; меняется ими,
# а не нами, поэтому живёт константой рядом с адресом.
LB_ALGORITHM = ("session_based_days_7500_session_300_contribution_5_"
                "threshold_10_limit_100_filter_True_skip_30")

USER_AGENT = "RadarBot/1.0 ( https://github.com/Chistovik92/radar )"
TIMEOUT = 15
MIN_INTERVAL = 1.1      # MusicBrainz: не чаще раза в секунду, с запасом
MAX_RELATED = 15        # родственных артистов хватит и полутора десятков

_last_call = 0.0
_gate = asyncio.Lock()


def enabled() -> bool:
    from . import features

    return features.enabled("music_meta")


async def _polite_pause() -> None:
    """Держит интервал между запросами к MusicBrainz."""
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.monotonic()


def best_genre(recording: dict[str, Any]) -> str:
    """Жанр записи: сначала «genres», потом самый весомый тег."""
    for key in ("genres", "tags"):
        items = recording.get(key) or []
        ranked = sorted(
            (item for item in items if isinstance(item, dict) and item.get("name")),
            key=lambda item: -int(item.get("count") or 0),
        )
        if ranked:
            return str(ranked[0]["name"])[:40]
    return ""


def parse_recording(payload: dict[str, Any]) -> tuple[str, str]:
    """(жанр, MBID артиста) из ответа поиска записи."""
    recordings = payload.get("recordings") or []
    if not recordings:
        return "", ""
    first = recordings[0]
    genre = best_genre(first)
    credit = first.get("artist-credit") or []
    mbid = ""
    if credit and isinstance(credit[0], dict):
        mbid = str((credit[0].get("artist") or {}).get("id") or "")
    return genre, mbid


def parse_similar(payload: Any) -> list[str]:
    """Имена родственных артистов из ответа ListenBrainz."""
    names: list[str] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("artist_name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= MAX_RELATED:
            break
    return names


def _quote(value: str) -> str:
    """Экранирование для языка запросов Lucene в MusicBrainz."""
    special = '+-&|!(){}[]^"~*?:\\/'
    return "".join("\\" + char if char in special else char for char in value)


async def lookup(artist: str, title: str) -> dict[str, Any]:
    """Жанр и родственные артисты. Пустой словарь — ничего не нашлось."""
    import aiohttp

    artist, title = (artist or "").strip(), (title or "").strip()
    if not artist or not title:
        return {}

    query = f'recording:"{_quote(title)}" AND artist:"{_quote(artist)}"'
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    result: dict[str, Any] = {}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with _gate:
                await _polite_pause()
                async with session.get(MUSICBRAINZ, params={
                    "query": query, "fmt": "json", "limit": "1",
                    "inc": "genres+tags",
                }) as response:
                    if response.status != 200:
                        log.info("MusicBrainz ответил %s", response.status)
                        return {}
                    payload = await response.json(content_type=None)
            genre, mbid = parse_recording(payload if isinstance(payload, dict) else {})
            if genre:
                result["genre"] = genre
            if mbid:
                async with session.get(LISTENBRAINZ, params={
                    "artist_mbids": mbid, "algorithm": LB_ALGORITHM,
                }) as response:
                    if response.status == 200:
                        related = parse_similar(await response.json(content_type=None))
                        if related:
                            result["related"] = related
    except Exception as exc:  # noqa: BLE001
        # Метаданные — украшение, а не необходимость: без них трек
        # остаётся на месте и играет, подбор просто беднее.
        log.info("Метаданные трека не получены: %s", type(exc).__name__)
        return result
    return result


def apply(track: dict, meta: dict[str, Any]) -> bool:
    """Дописывает найденное в трек. True — что-то изменилось.

    Жанр из тегов человека не переписывается: если он его задал, значит,
    так и считает, а база может ошибиться с каверов и ремиксов.
    """
    changed = False
    genre = str(meta.get("genre") or "")
    if genre and not (track.get("genre") or "").strip():
        track["genre"] = genre[:40]
        changed = True
    related = [str(name)[:80] for name in meta.get("related") or []][:MAX_RELATED]
    if related and related != track.get("related"):
        track["related"] = related
        changed = True
    return changed
