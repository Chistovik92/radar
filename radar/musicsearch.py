"""Поиск и получение музыки из бесплатного каталога SoundCloud/YouTube.

Движок адаптирован из ``core/app_logic.py`` проекта not_a_music
(https://github.com/pythoneer-dev-q/not_a_music, Apache-2.0). В отличие от
исходника он не импортирует MongoDB и настройки другого бота: метаданные
передаются через асинхронный адаптер, лимит выдачи — параметром клиента.

SoundCloud — основной источник; YouTube добирает выдачу и заменяет премиум-
превью SoundCloud Go+. DRM, защищённые сервисы и короткие сниппеты отсекаются.
yt-dlp работает в executor и не блокирует цикл оповещений. Аудио возвращается
в памяти только на время отправки в Telegram; постоянного файлового архива
этот модуль не создаёт.

⚠️ Скачивание с YouTube может нарушать условия площадки. Публичный поиск
включается отдельным флагом ``music_search`` на следующих этапах 6.0.0.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
import shutil
import socket
import tempfile
import time
from typing import Any, Awaitable, Callable, Optional

import aiohttp
from aiohttp import ClientTimeout

log = logging.getLogger("radar.musicsearch")

BAR_FILLED = "█"
BAR_EMPTY = "░"
ICON_HOURGLASS = "⏳"
ICON_DOWNLOAD = "⬇"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BAD_VERSION_WORDS = (
    "slowed", "nightcore", "sped up", "speed up", "speedup", "8d audio", "reverb",
    "remix", "cover", "instrumental", "karaoke", "mashup", "extended", "loop",
    "tiktok version", "chopped",
)
_DRM_PROTOCOLS = ("ctr-", "cbc-")
_SC_API_BASE = "https://api-v2.soundcloud.com/"
_API_FAIL_LIMIT = 3
_API_COOLDOWN = 120.0


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name) or default))
    except (TypeError, ValueError):
        return default


DL_WORKERS = _env_int("YTDLP_DL_WORKERS", 3)
DL_CHUNK = _env_int("YTDLP_DL_CHUNK", 1_048_576, 1024)
DL_RETRIES = _env_int("YTDLP_DL_RETRIES", 3)
MAX_DOWNLOAD_BYTES = _env_int("MUSIC_SEARCH_MAX_MB", 50) * 1024 * 1024


class AudioBuffer(io.BytesIO):
    """Временные байты с настоящим расширением скачанной дорожки."""

    def __init__(self, data: bytes, ext: str = ""):
        super().__init__(data)
        self.ext = str(ext or "").lower().lstrip(".")


class TrackUnavailable(Exception):
    """Трек нельзя получить целиком: нет ссылки, обрыв, DRM или превью."""


_AIOHTTP_ERRORS = tuple(
    value for value in (getattr(aiohttp, "ClientError", None),)
    if isinstance(value, type) and issubclass(value, BaseException)
)
_DOWNLOAD_FALLBACK_ERRORS = (
    TrackUnavailable, asyncio.TimeoutError, TimeoutError, OSError
) + _AIOHTTP_ERRORS


class _ApiUnauthorized(Exception):
    """SoundCloud отклонил client_id — его нужно обновить."""


class _DiagLogger:
    """Логгер yt-dlp с ограничением одинаковых сообщений."""

    _seen: dict[str, int] = {}
    _LIMIT = 5

    def __init__(self, quiet: bool = True):
        self.quiet = quiet

    def _emit(self, level: int, msg: object) -> None:
        text = " ".join(str(msg).split())
        if not text:
            return
        key = text[:120]
        count = self._seen.get(key, 0) + 1
        self._seen[key] = count
        if count <= self._LIMIT:
            log.log(level, "yt-dlp: %s", text[:300])

    def debug(self, msg: object) -> None:
        if not self.quiet and not str(msg).startswith("[debug] "):
            self._emit(logging.DEBUG, msg)

    def info(self, msg: object) -> None:
        if not self.quiet:
            self._emit(logging.INFO, msg)

    def warning(self, msg: object) -> None:
        self._emit(logging.WARNING, msg)

    def error(self, msg: object) -> None:
        self._emit(logging.ERROR, msg)


def ytdl_env_opts() -> dict[str, Any]:
    """Общие с «Радаром» настройки yt-dlp из окружения.

    ``YTDLP_*`` имеют приоритет; cookies и прокси по умолчанию берутся из уже
    существующих ``MEDIA_COOKIES`` и ``EGRESS_PROXY``. Второй файл настроек для
    музыки не требуется.
    """
    opts: dict[str, Any] = {}
    cookies = (os.getenv("YTDLP_COOKIES") or os.getenv("MEDIA_COOKIES") or "").strip()
    if cookies and os.path.isfile(cookies):
        opts["cookiefile"] = cookies
    clients = [
        item.strip() for item in (os.getenv("YTDLP_PLAYER_CLIENT") or "").split(",")
        if item.strip()
    ]
    if clients:
        opts["extractor_args"] = {"youtube": {"player_client": clients}}
    proxy = (os.getenv("YTDLP_PROXY") or os.getenv("EGRESS_PROXY") or "").strip()
    if proxy:
        opts["proxy"] = proxy
    runtimes: dict[str, dict[str, str]] = {}
    for raw in (os.getenv("YTDLP_JS_RUNTIMES") or "deno,node").split(","):
        item = raw.strip().lower()
        if not item:
            continue
        if ":" in item:
            name, _, path = item.partition(":")
            if name.strip():
                runtimes[name.strip()] = {"path": path.strip()}
        else:
            runtimes[item] = {}
    opts["js_runtimes"] = runtimes
    return opts


def _pick_best_audio(
    formats: list[dict[str, Any]] | None,
    prefer_ext: tuple[str, ...] = ("m4a", "mp3"),
    min_compatible_ratio: float = 0.8,
    allow_hls: bool = True,
) -> dict[str, Any] | None:
    """Выбрать лучшую полноразмерную аудиодорожку без DRM и видео."""
    candidates: list[dict[str, Any]] = []
    for fmt in formats or []:
        if not isinstance(fmt, dict):
            continue
        ext = str(fmt.get("ext") or "").lower()
        protocol = str(fmt.get("protocol") or "")
        note = str(fmt.get("format_note") or "").lower()
        if fmt.get("has_drm"):
            continue
        if str(fmt.get("vcodec") or "none").lower() not in ("none", ""):
            continue
        if not fmt.get("url"):
            continue
        if ext == "mhtml" or "storyboard" in note:
            continue
        if "preview" in str(fmt.get("format_id") or "").lower() or "preview" in note:
            continue
        if protocol in ("m3u8", "m3u8_native") and not allow_hls:
            continue
        if not (protocol.startswith("http") or protocol in ("m3u8", "m3u8_native")):
            continue
        candidates.append(fmt)
    if not candidates:
        return None

    def bitrate(fmt: dict[str, Any]) -> float:
        try:
            return float(fmt.get("abr") or fmt.get("tbr") or 0)
        except (TypeError, ValueError):
            return 0.0

    compatible = max(
        (item for item in candidates if str(item.get("ext") or "").lower() in prefer_ext),
        key=bitrate,
        default=None,
    )
    best = max(candidates, key=bitrate, default=None)
    if compatible and (not best or bitrate(compatible) >= bitrate(best) * min_compatible_ratio):
        return compatible
    return best or compatible


def score_candidate(query: str, candidate: dict[str, Any], duration_hint: int = 0) -> float:
    """Оценить YouTube-кандидата по длительности, словам и версии записи."""
    score = 0.0
    title_l = str(candidate.get("title") or "").lower()
    query_l = (query or "").lower()
    try:
        duration = float(candidate.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration_hint and duration:
        diff = abs(duration - duration_hint) / max(float(duration_hint), 1.0)
        if diff <= 0.05:
            score += 3.0
        elif diff <= 0.15:
            score += 2.0
        elif diff <= 0.3:
            score += 1.0
        else:
            score -= 2.5
    words = {word for word in re.split(r"\W+", query_l) if len(word) > 2}
    if words:
        found = {word for word in re.split(r"\W+", title_l) if len(word) > 2}
        score += 2.0 * len(words & found) / len(words)
    for word in _BAD_VERSION_WORDS:
        if word in title_l and word not in query_l:
            score -= 2.0
            break
    return score


def parse_content_range(value: str) -> tuple[int, int, int]:
    """``bytes 0-1023/4096`` → ``(0, 1023, 4096)``."""
    match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", str(value or "").strip(), re.I)
    if not match:
        return 0, 0, 0
    total = 0 if match.group(3) == "*" else int(match.group(3))
    return int(match.group(1)), int(match.group(2)), total


def format_progress_bar(downloaded: int, total: int, width: int = 10) -> str:
    downloaded = max(0, int(downloaded or 0))
    total = max(0, int(total or 0))
    width = max(1, int(width))
    if total <= 0:
        return f"{ICON_HOURGLASS} <b>Загрузка…</b> <code>{downloaded / 1_048_576:.1f} MB</code>"
    pct = min(1.0, downloaded / total)
    filled = int(width * pct)
    bar = BAR_FILLED * filled + BAR_EMPTY * (width - filled)
    return (
        f"<code>[{bar}] {int(pct * 100)}%</code> "
        f"({downloaded / 1_048_576:.1f}/{total / 1_048_576:.1f} MB)"
    )


def track_display_name(artist: str = "", title: str = "") -> str:
    artist = str(artist or "").strip().strip("-—–").strip()
    title = str(title or "").strip().strip("-—–").strip()
    if artist and title and artist.lower() != title.lower():
        return f"{artist} — {title}"
    return artist or title


class TelegramProgressReporter:
    """Редкие правки сообщения с HTML-прогрессом загрузки."""

    UPDATE_INTERVAL = 1.8

    def __init__(self, edit_func: Callable[[str], Awaitable[Any]], title: str = ""):
        self._edit = edit_func
        self._title = html.escape(track_display_name(title=title), quote=False) if title else ""
        self._last_update = 0.0

    def render(self, downloaded: int, total: int) -> str:
        if self._title:
            header = f"{ICON_DOWNLOAD} <b>Загружаю трек</b>\n<i>{self._title}</i>\n\n"
        else:
            header = f"{ICON_DOWNLOAD} <b>Загружаю трек…</b>\n\n"
        return f"{header}{format_progress_bar(downloaded, total)}"

    async def update(self, downloaded: int, total: int, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_update < self.UPDATE_INTERVAL:
            return
        self._last_update = now
        try:
            await self._edit(self.render(downloaded, total))
        except Exception:  # Telegram не должен ронять уже идущую загрузку.
            log.debug("Не удалось обновить прогресс музыки", exc_info=True)


def _clean_track_id(raw_id: object) -> str:
    raw = str(raw_id or "").strip()
    return raw.split(":")[-1] if raw.startswith("soundcloud:tracks:") else raw


def merge_cached_records(
    stored: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Слить JSON-кэши ``meta``, не мутируя входы и не теряя неизвестные id.

    Одинаковый track_id обновляется по полям: например, свежий title не стирает
    ранее сохранённые cover/url. Эта же безопасная merge-семантика нужна CMS.
    """
    result: dict[str, dict[str, Any]] = {}
    for source in (stored, incoming):
        if not isinstance(source, dict):
            continue
        for track_id, value in source.items():
            if not isinstance(value, dict):
                continue
            key = str(track_id)
            result[key] = {**result.get(key, {}), **value}
    return result


# JSON в meta обновляется read-modify-write. Один lock на процесс не даёт
# одновременным поискам и отправкам стереть чужие идентификаторы.
_meta_lock = asyncio.Lock()
CATALOG_KEY = "music_catalog"
FILES_KEY = "music_files"
MAX_CATALOG_RECORDS = 5000
MAX_FILE_RECORDS = 2000


async def catalog_get(track_id: str) -> dict[str, Any]:
    """Плоские метаданные трека; повреждённая/отсутствующая запись → {}."""
    from . import storage

    value = await storage.meta_get(CATALOG_KEY, {})
    if not isinstance(value, dict):
        return {}
    record = value.get(str(track_id))
    return dict(record) if isinstance(record, dict) else {}


async def catalog_merge(tracks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Дополнить каталог найденными треками, не затирая данные пустыми полями."""
    from . import storage

    async with _meta_lock:
        stored = await storage.meta_get(CATALOG_KEY, {})
        incoming: dict[str, dict[str, Any]] = {}
        for track in tracks:
            if not isinstance(track, dict) or not track.get("id"):
                continue
            track_id = _clean_track_id(track["id"])[:80]
            if not track_id:
                continue
            image = track.get("imageInfo") or {}
            values = {
                "title": str(track.get("title") or "").strip()[:200],
                "artist": str(track.get("artist") or "").strip()[:200],
                "duration": max(0, int(float(track.get("duration") or 0))),
                "cover": str(track.get("cover") or image.get("imageUrl") or "")[:2000],
                "url": str(track.get("url") or "")[:2000],
                "query_str": str(track.get("query_str") or "")[:400],
                "source": str(track.get("source") or "")[:8],
            }
            incoming[track_id] = {key: value for key, value in values.items()
                                  if value not in ("", 0, None)}
        merged = merge_cached_records(stored if isinstance(stored, dict) else {}, incoming)
        if len(merged) > MAX_CATALOG_RECORDS:
            merged = dict(list(merged.items())[-MAX_CATALOG_RECORDS:])
        if incoming:
            await storage.meta_set(CATALOG_KEY, merged)
        return merged


async def file_id_get(track_id: str) -> str:
    from . import storage

    files = await storage.meta_get(FILES_KEY, {})
    if not isinstance(files, dict):
        return ""
    value = files.get(_clean_track_id(track_id))
    if isinstance(value, dict):
        value = value.get("file_id")
    return str(value or "")


async def file_id_set(track_id: str, file_id: str) -> None:
    """Запомнить только Telegram file_id, не содержимое аудиофайла."""
    from . import storage

    track_id = _clean_track_id(track_id)[:80]
    file_id = str(file_id or "").strip()[:300]
    if not track_id or not file_id:
        return
    async with _meta_lock:
        current = await storage.meta_get(FILES_KEY, {})
        files = {str(key): (dict(value) if isinstance(value, dict) else str(value))
                 for key, value in (current or {}).items()
                 if isinstance(value, dict) or (isinstance(value, str) and value)}
        previous = files.get(track_id)
        files[track_id] = ({**previous, "file_id": file_id}
                           if isinstance(previous, dict) else file_id)
        if len(files) > MAX_FILE_RECORDS:
            files = dict(list(files.items())[-MAX_FILE_RECORDS:])
        await storage.meta_set(FILES_KEY, files)


async def file_id_forget(track_id: str) -> None:
    """Убрать отклонённый Telegram идентификатор перед повторной загрузкой."""
    from . import storage

    track_id = _clean_track_id(track_id)
    async with _meta_lock:
        current = await storage.meta_get(FILES_KEY, {})
        files = dict(current) if isinstance(current, dict) else {}
        if track_id in files:
            files.pop(track_id, None)
            await storage.meta_set(FILES_KEY, files)


_search_cache: dict[str, tuple[dict[str, Any], float]] = {}
_cache_ttl = 180
_track_state_cache: dict[str, tuple[dict[str, Any], float]] = {}
_state_ttl = 3600
_sc_client_id: Optional[str] = None
_api_fail_count = 0
_api_disabled_until_ts = 0.0


def _load_client_id(force: bool = False) -> Optional[str]:
    global _sc_client_id
    if _sc_client_id and not force:
        return _sc_client_id
    _sc_client_id = None
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "logger": _DiagLogger()}) as ydl:
            extractor = ydl.get_info_extractor("Soundcloud")
            extractor.set_downloader(ydl)
            extractor.initialize()
            _sc_client_id = getattr(extractor, "_CLIENT_ID", None) or None
    except Exception as exc:
        log.info("client_id SoundCloud недоступен: %s", exc)
    return _sc_client_id


def _is_playable_transcoding(transcoding: dict[str, Any]) -> bool:
    if not isinstance(transcoding, dict):
        return False
    protocol = str((transcoding.get("format") or {}).get("protocol") or "")
    url = str(transcoding.get("url") or "")
    if protocol.startswith(_DRM_PROTOCOLS) or "/encrypted-hls" in url:
        return False
    if transcoding.get("snipped") is True or "/preview/" in url:
        return False
    return bool(protocol or url)


def is_premium_track(state: Optional[dict[str, Any]]) -> bool:
    """True для Go+/DRM/блокировки; неизвестное состояние не отбрасывается."""
    if not state:
        return False
    policy = str(state.get("policy") or "").upper()
    if policy and policy != "ALLOW":
        return True
    if state.get("streamable") is False:
        return True
    if state.get("state") and state.get("state") != "finished":
        return True
    if str(state.get("monetization_model") or "").upper() == "SUB_HIGH_TIER":
        return True
    transcodings = (state.get("media") or {}).get("transcodings") or []
    return bool(transcodings) and not any(_is_playable_transcoding(item) for item in transcodings)


async def _api_get(session: aiohttp.ClientSession, path: str, params: dict[str, Any]) -> Any:
    async with session.get(
        f"{_SC_API_BASE}{path}", params=params, timeout=ClientTimeout(total=15)
    ) as response:
        if response.status in (401, 403):
            raise _ApiUnauthorized()
        response.raise_for_status()
        return await response.json(content_type=None)


async def fetch_track_states(track_ids: list[object]) -> dict[str, dict[str, Any]]:
    ids = [str(item) for item in track_ids if item]
    if not ids:
        return {}
    loop = asyncio.get_running_loop()
    session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(family=socket.AF_INET, limit=10)
    )
    result: dict[str, dict[str, Any]] = {}
    try:
        pending = ids
        for attempt in (0, 1):
            client_id = await loop.run_in_executor(None, lambda force=attempt > 0: _load_client_id(force))
            if not client_id:
                return result
            retry: list[str] = []
            for start in range(0, len(pending), 50):
                chunk = pending[start:start + 50]
                try:
                    data = await _api_get(
                        session, "tracks", {"ids": ",".join(chunk), "client_id": client_id}
                    )
                except _ApiUnauthorized:
                    retry.extend(chunk)
                    continue
                except Exception as exc:
                    log.info("Состояния SoundCloud недоступны: %s", exc)
                    continue
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("id") is not None:
                            result[str(item["id"])] = item
            if not retry:
                break
            pending = retry
    finally:
        await session.close()
    return result


async def get_track_states(track_ids: list[object], use_cache: bool = True) -> dict[str, dict[str, Any]]:
    ids = [str(item) for item in track_ids if item]
    if not ids:
        return {}
    if len(_track_state_cache) > 5000:
        _track_state_cache.clear()
    now = time.monotonic()
    result: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for track_id in ids:
        cached = _track_state_cache.get(track_id)
        if use_cache and cached and now < cached[1]:
            result[track_id] = cached[0]
        else:
            missing.append(track_id)
    fetched = await fetch_track_states(missing) if missing else {}
    for track_id, state in fetched.items():
        _track_state_cache[track_id] = (state, now + _state_ttl)
    result.update(fetched)
    return result


def _entry_from_api(item: dict[str, Any]) -> dict[str, Any]:
    duration_ms = item.get("full_duration") or item.get("duration") or 0
    user = item.get("user") or {}
    artwork = item.get("artwork_url") or user.get("avatar_url") or ""
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "uploader": user.get("username"),
        "duration": float(duration_ms) / 1000.0,
        "webpage_url": item.get("permalink_url"),
        "thumbnails": [{"url": artwork.replace("-large.", "-t500x500.")}] if artwork else [],
        "_api_state": item,
    }


async def search_via_api(query: str, limit: int = 40) -> list[dict[str, Any]]:
    session = aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(family=socket.AF_INET, limit=10)
    )
    loop = asyncio.get_running_loop()
    try:
        for attempt in (0, 1):
            client_id = await loop.run_in_executor(None, lambda force=attempt > 0: _load_client_id(force))
            if not client_id:
                return []
            try:
                data = await _api_get(session, "search/tracks", {
                    "q": query,
                    "client_id": client_id,
                    "limit": max(1, min(int(limit), 200)),
                    "offset": 0,
                    "linked_partitioning": 1,
                })
            except _ApiUnauthorized:
                continue
            except Exception as exc:
                if getattr(exc, "status", None) == 429 and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                log.info("Поиск SoundCloud api-v2 не удался: %s", exc)
                return []
            collection = (data or {}).get("collection") or []
            return [_entry_from_api(item) for item in collection if isinstance(item, dict)]
    finally:
        await session.close()
    return []


def _api_disabled_until() -> float:
    return _api_disabled_until_ts if time.monotonic() < _api_disabled_until_ts else 0.0


def _api_health_ok() -> None:
    global _api_fail_count, _api_disabled_until_ts
    _api_fail_count = 0
    _api_disabled_until_ts = 0.0


def _api_health_fail() -> None:
    global _api_fail_count, _api_disabled_until_ts
    _api_fail_count += 1
    if _api_fail_count >= _API_FAIL_LIMIT:
        _api_disabled_until_ts = time.monotonic() + _API_COOLDOWN
        log.warning("SoundCloud api-v2 отключён на %.0f с после серии сбоев", _API_COOLDOWN)


MetadataLoader = Callable[[str], Awaitable[dict[str, Any]]]


class MusicSearchClient:
    """Асинхронный гибридный клиент поиска и скачивания."""

    LIMIT_ON_PAGE = 7
    MIN_DURATION = 35
    MAX_QUERY = 200

    def __init__(self, *, metadata: MetadataLoader | None = None, search_limit: int = LIMIT_ON_PAGE):
        self._session: aiohttp.ClientSession | None = None
        self._own_session = False
        self._metadata = metadata
        self.search_limit = max(1, min(int(search_limit), 50))

    async def __aenter__(self) -> "MusicSearchClient":
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                family=socket.AF_INET, ttl_dns_cache=300, keepalive_timeout=60, limit=50
            )
        )
        self._own_session = True
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._own_session and self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    def _ydl_opts(quiet: bool = True) -> dict[str, Any]:
        return {
            "quiet": quiet,
            "no_warnings": False,
            "ignoreerrors": True,
            "logger": _DiagLogger(quiet),
            "socket_timeout": 15,
            "retries": 3,
            "skip_download": True,
            "lazy_extractors": True,
            "nocheckcertificate": True,
            "source_address": "0.0.0.0",
            "noplaylist": True,
            **ytdl_env_opts(),
        }

    @staticmethod
    def _extract_cover(entry: dict[str, Any]) -> str:
        thumbs = [item for item in (entry.get("thumbnails") or []) if isinstance(item, dict) and item.get("url")]
        if thumbs:
            best = sorted(thumbs, key=lambda item: item.get("width") or 0)
            return str(best[-1]["url"])
        return str(entry.get("thumbnail") or "")

    @staticmethod
    def _is_garbage(entry: dict[str, Any], min_dur: int = MIN_DURATION) -> bool:
        try:
            duration = float(entry.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        title = str(entry.get("title") or "").strip().lower()
        if duration and (duration < min_dur or abs(duration - 30.0) < 0.9):
            return True
        if not title or title in ("untitled", "[deleted]", "[private]", "deleted"):
            return True
        return "preview" in title or "snippet" in title

    @staticmethod
    def _extract_sync(opts: dict[str, Any], url: str) -> dict[str, Any] | None:
        import yt_dlp

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info if isinstance(info, dict) else None
        except Exception as exc:
            log.info("yt-dlp %s: %s", url[:70], exc)
            return None

    async def _sc_search_entries(self, query: str, total_fetch: int) -> list[dict[str, Any]]:
        errors: list[str] = []
        if not _api_disabled_until():
            try:
                entries = await search_via_api(query, limit=total_fetch)
            except Exception as exc:
                entries = []
                errors.append(f"api-v2: {exc}")
            if entries:
                _api_health_ok()
                return entries
            _api_health_fail()
        else:
            errors.append("api-v2 временно отключён")
        options = {**self._ydl_opts(), "extract_flat": True}
        entries = await asyncio.get_running_loop().run_in_executor(
            None, self._extract_sync, options, f"scsearch{total_fetch}:{query}"
        )
        found = [item for item in ((entries or {}).get("entries") or []) if isinstance(item, dict)]
        if not found:
            log.info("SoundCloud не дал результатов: %s", "; ".join(errors) or "пустая выдача")
        return found

    async def _yt_search_entries(self, query: str, limit: int) -> list[dict[str, Any]]:
        options = {**self._ydl_opts(), "extract_flat": True}
        info = await asyncio.get_running_loop().run_in_executor(
            None, self._extract_sync, options, f"ytsearch{max(1, limit)}:{query}"
        )
        return [item for item in ((info or {}).get("entries") or []) if isinstance(item, dict)]

    async def search_track(self, query: str, page: int = 1, limit: int | None = None) -> dict[str, Any]:
        query = str(query or "").strip()[:self.MAX_QUERY]
        page = int(page)
        if page < 1:
            raise ValueError("page must be >= 1")
        if not query:
            return {"items": [], "paginationInfo": {"lastPage": 1}}
        per_page = max(1, min(int(limit or self.search_limit), 50))
        cache_key = f"{query.casefold()}_{page}_{per_page}"
        now = time.monotonic()
        cached = _search_cache.get(cache_key)
        if cached and now < cached[1]:
            return cached[0]
        if len(_search_cache) > 500:
            _search_cache.clear()

        page_start = (page - 1) * per_page
        page_end = page * per_page
        total_fetch = min(200, max(40, page_end * 3 + 1))
        raw_entries = await self._sc_search_entries(query, total_fetch)
        valid = [item for item in raw_entries if item and not self._is_garbage(item, self.MIN_DURATION)]
        valid = await self._drop_premium(valid)

        combined: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in valid:
            track_id = _clean_track_id(entry.get("id"))
            if not track_id or track_id in seen:
                continue
            seen.add(track_id)
            title = str(entry.get("title") or "Unknown").strip()
            artist = str(entry.get("uploader") or entry.get("channel") or "SoundCloud").strip()
            combined.append({
                "id": track_id,
                "fileId": track_id,
                "title": title,
                "artist": artist,
                "duration": int(float(entry.get("duration") or 0)),
                "imageInfo": {"imageUrl": self._extract_cover(entry)},
                "url": entry.get("webpage_url") or entry.get("url") or "",
                "query_str": f"{artist} - {title}",
                "source": "sc",
            })

        # YouTube — часть общей последовательности, а не отдельная первая
        # страница на каждом запросе. Один дополнительный элемент честно
        # показывает наличие следующей страницы.
        if len(combined) <= page_end:
            yt_entries = await self._yt_search_entries(query, page_end - len(combined) + 4)
            for entry in yt_entries:
                youtube_id = entry.get("id")
                track_id = f"yt_{youtube_id}" if youtube_id else ""
                if not track_id or track_id in seen:
                    continue
                try:
                    duration = float(entry.get("duration") or 0)
                except (TypeError, ValueError):
                    duration = 0.0
                if duration < 30 or duration > 1800:
                    continue
                seen.add(track_id)
                title = str(entry.get("title") or "Unknown").strip()
                artist = str(entry.get("uploader") or entry.get("channel") or "YouTube Music").strip()
                combined.append({
                    "id": track_id,
                    "fileId": track_id,
                    "title": title,
                    "artist": artist,
                    "duration": int(duration),
                    "imageInfo": {"imageUrl": self._extract_cover(entry)},
                    "url": f"https://www.youtube.com/watch?v={youtube_id}",
                    "query_str": f"{artist} - {title}",
                    "source": "yt",
                })
        items = combined[page_start:page_end]
        result = {
            "items": items,
            "paginationInfo": {"lastPage": page + 1 if len(combined) > page_end else page},
        }
        _search_cache[cache_key] = (result, now + _cache_ttl)
        return result

    async def _drop_premium(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not entries:
            return entries
        ids = [_clean_track_id(entry.get("id")) for entry in entries]
        states = {
            _clean_track_id(entry.get("id")): entry.get("_api_state")
            for entry in entries if entry.get("_api_state")
        }
        missing = [track_id for track_id in ids if track_id and track_id not in states]
        if missing:
            states.update(await get_track_states(missing))
        if not states:
            return entries
        kept = []
        for entry, track_id in zip(entries, ids):
            state = states.get(track_id)
            if is_premium_track(state):
                continue
            full_duration = (state or {}).get("full_duration")
            if full_duration:
                entry["duration"] = full_duration / 1000
            kept.append(entry)
        return kept

    async def top_tracks(self, page: int = 1) -> dict[str, Any]:
        return await self.search_track("popular music", page=page)

    @staticmethod
    def _yt_result(track_id: str, info: dict[str, Any], fmt: dict[str, Any], url: str) -> dict[str, Any]:
        return {
            "id": track_id,
            "fileId": track_id,
            "title": info.get("title") or "Unknown",
            "artist": info.get("uploader") or info.get("channel") or "YouTube",
            "duration": int(float(info.get("duration") or 0)),
            "download": fmt.get("url"),
            "filesize": int(fmt.get("filesize") or fmt.get("filesize_approx") or 0),
            "abr": fmt.get("abr") or fmt.get("tbr"),
            "format_id": fmt.get("format_id"),
            "ext": str(fmt.get("ext") or "").lower(),
            "direct": str(fmt.get("protocol") or "").startswith("http"),
            "page": url,
            "imageInfo": {"imageUrl": MusicSearchClient._extract_cover(info)},
            "url": url,
        }

    async def _stored_meta(self, track_id: str) -> dict[str, Any]:
        if self._metadata is None:
            return {}
        try:
            value = await self._metadata(track_id)
            return value if isinstance(value, dict) else {}
        except Exception:
            log.info("Кэш метаданных трека %s недоступен", track_id, exc_info=True)
            return {}

    async def _find_youtube(self, query: str, duration_hint: int = 0) -> dict[str, Any] | None:
        if not query:
            return None
        entries = await self._yt_search_entries(query, 5)
        if not entries:
            return None
        best = max(entries, key=lambda item: score_candidate(query, item, duration_hint))
        video_id = best.get("id")
        if not video_id:
            return None
        return await asyncio.get_running_loop().run_in_executor(
            None, self._extract_sync, self._ydl_opts(),
            f"https://www.youtube.com/watch?v={video_id}",
        )

    async def get_track_info(self, track_id: str) -> dict[str, Any] | None:
        track_id = _clean_track_id(track_id)
        if not track_id:
            return None
        loop = asyncio.get_running_loop()
        if track_id.startswith("yt_"):
            real_id = track_id[3:]
            url = f"https://www.youtube.com/watch?v={real_id}"
            info = await loop.run_in_executor(None, self._extract_sync, self._ydl_opts(), url)
            if not info:
                return None
            fmt = _pick_best_audio(info.get("formats"), prefer_ext=("m4a",))
            return self._yt_result(track_id, info, fmt, url) if fmt else None

        sc_url = f"https://api.soundcloud.com/tracks/{track_id}"
        info = await loop.run_in_executor(None, self._extract_sync, self._ydl_opts(), sc_url)
        fmt = _pick_best_audio((info or {}).get("formats"), prefer_ext=("mp3", "m4a"))
        if fmt and info:
            return {
                "id": track_id,
                "fileId": track_id,
                "title": info.get("title") or "Unknown",
                "artist": info.get("uploader") or info.get("channel") or "SoundCloud",
                "duration": int(float(info.get("duration") or 0)),
                "download": fmt.get("url"),
                "filesize": int(fmt.get("filesize") or fmt.get("filesize_approx") or 0),
                "abr": fmt.get("abr") or fmt.get("tbr"),
                "format_id": fmt.get("format_id"),
                "ext": str(fmt.get("ext") or "").lower(),
                "direct": str(fmt.get("protocol") or "").startswith("http"),
                "page": sc_url,
                "imageInfo": {"imageUrl": self._extract_cover(info)},
                "url": info.get("webpage_url") or sc_url,
            }
        meta = await self._stored_meta(track_id)
        query = track_display_name(
            (info or {}).get("uploader") or meta.get("artist") or meta.get("name"),
            (info or {}).get("title") or meta.get("title"),
        )
        duration_hint = int(float((info or {}).get("duration") or meta.get("duration") or 0))
        yt_info = await self._find_youtube(query, duration_hint)
        if not yt_info:
            return None
        yt_fmt = _pick_best_audio(yt_info.get("formats"), prefer_ext=("m4a",))
        if not yt_fmt:
            return None
        result = self._yt_result(
            track_id, yt_info, yt_fmt, f"https://www.youtube.com/watch?v={yt_info.get('id')}"
        )
        if duration_hint:
            result["duration"] = result["duration"] or duration_hint
        return result

    async def _download_with_ytdlp(
        self,
        info: dict[str, Any],
        progress_cb: Callable[[int, int], Awaitable[Any]] | None = None,
    ) -> io.BytesIO:
        tmpdir = tempfile.mkdtemp(prefix="radar_music_")
        state = {"done": 0, "total": int(info.get("filesize") or 0)}

        def hook(status: dict[str, Any]) -> None:
            if status.get("status") == "downloading":
                state["done"] = int(status.get("downloaded_bytes") or 0)
                state["total"] = int(
                    status.get("total_bytes") or status.get("total_bytes_estimate") or state["total"]
                )
            elif status.get("status") == "finished":
                state["done"] = state["total"] or state["done"]

        async def poll() -> None:
            while True:
                if progress_cb:
                    try:
                        await progress_cb(state["done"], state["total"])
                    except Exception:
                        pass
                await asyncio.sleep(0.4)

        page = str(info.get("page") or info.get("url") or "")
        format_id = str(info.get("format_id") or "")
        attempts = ([f"{format_id}/bestaudio/best"] if format_id else []) + ["bestaudio/best"]
        loop = asyncio.get_running_loop()
        last_error: object = "нет данных"
        try:
            for selector in attempts:
                options = {
                    **self._ydl_opts(),
                    "format": selector,
                    "noprogress": True,
                    "ignoreerrors": False,
                    "skip_download": False,
                    "max_filesize": MAX_DOWNLOAD_BYTES,
                    "progress_hooks": [hook],
                    "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
                }

                def download() -> int:
                    import yt_dlp

                    with yt_dlp.YoutubeDL(options) as ydl:
                        return int(ydl.download([page]))

                poller = loop.create_task(poll())
                try:
                    code = await loop.run_in_executor(None, download)
                except Exception as exc:
                    last_error = exc
                    continue
                finally:
                    poller.cancel()
                    try:
                        await poller
                    except asyncio.CancelledError:
                        pass
                if code != 0:
                    last_error = f"yt-dlp вернул код {code}"
                    continue
                candidates = []
                for name in os.listdir(tmpdir):
                    path = os.path.join(tmpdir, name)
                    if os.path.isfile(path) and not name.endswith(".part"):
                        candidates.append((os.path.getsize(path), path))
                if not candidates:
                    last_error = "yt-dlp ничего не записал"
                    continue
                size, path = max(candidates)
                if size > MAX_DOWNLOAD_BYTES:
                    last_error = "файл превышает лимит отправки"
                    continue
                expected = int(info.get("filesize") or 0)
                if expected and size < expected * 0.8:
                    last_error = f"скачано {size} из {expected} байт"
                    continue
                with open(path, "rb") as handle:
                    data = handle.read(MAX_DOWNLOAD_BYTES + 1)
                if data and len(data) <= MAX_DOWNLOAD_BYTES:
                    return AudioBuffer(data, os.path.splitext(path)[1])
                last_error = "пустой или слишком большой файл"
            raise TrackUnavailable(f"yt-dlp не смог скачать: {last_error}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    async def _fetch_range(
        session: aiohttp.ClientSession,
        url: str,
        headers: dict[str, str],
        start: int,
        end: int,
        timeout: ClientTimeout,
        attempts: int | None = None,
    ) -> tuple[object, bytes, int]:
        last_status: object = None
        for attempt in range(max(1, attempts or DL_RETRIES)):
            try:
                async with session.get(
                    url, headers={**headers, "Range": f"bytes={start}-{end}"}, timeout=timeout
                ) as response:
                    last_status = response.status
                    _, _, total = parse_content_range(response.headers.get("Content-Range"))
                    if response.status in (200, 206):
                        buf = bytearray()
                        async for chunk in response.content.iter_chunked(262144):
                            buf += chunk
                            if len(buf) > MAX_DOWNLOAD_BYTES:
                                raise TrackUnavailable("аудио превышает лимит отправки")
                        return response.status, bytes(buf), total
                    if response.status in (401, 403):
                        return response.status, b"", 0
            except TrackUnavailable:
                raise
            except Exception as exc:
                last_status = type(exc).__name__
            await asyncio.sleep(0.4 * (attempt + 1))
        return last_status, b"", 0

    @staticmethod
    async def _fetch_stream(
        session: aiohttp.ClientSession,
        url: str,
        headers: dict[str, str],
        timeout: ClientTimeout,
        progress_cb: Callable[[int, int], Awaitable[Any]] | None = None,
    ) -> tuple[bytes, int]:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            if response.status in (401, 403):
                raise TrackUnavailable(f"сервер отклонил запрос (HTTP {response.status})")
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD_BYTES:
                raise TrackUnavailable("аудио превышает лимит отправки")
            buf = bytearray()
            async for chunk in response.content.iter_chunked(262144):
                buf += chunk
                if len(buf) > MAX_DOWNLOAD_BYTES:
                    raise TrackUnavailable("аудио превышает лимит отправки")
                if progress_cb:
                    try:
                        await progress_cb(len(buf), total)
                    except Exception:
                        pass
            return bytes(buf), total

    async def _plain_or_fail(
        self,
        session: aiohttp.ClientSession,
        url: str,
        headers: dict[str, str],
        timeout: ClientTimeout,
        progress_cb: Callable[[int, int], Awaitable[Any]] | None,
        expected: int,
    ) -> bytes:
        data, total = await self._fetch_stream(session, url, headers, timeout, progress_cb)
        if expected and len(data) < expected:
            raise TrackUnavailable(f"получено {len(data)} из {expected} байт")
        if total and len(data) != total:
            raise TrackUnavailable(f"получено {len(data)} из {total} байт")
        return data

    async def _download_bytes(
        self,
        session: aiohttp.ClientSession,
        url: str,
        progress_cb: Callable[[int, int], Awaitable[Any]] | None,
        timeout_total: int,
        total_hint: int,
    ) -> bytes:
        timeout = ClientTimeout(total=timeout_total, connect=15)
        headers = {"User-Agent": _BROWSER_UA}
        status, head, total = await self._fetch_range(
            session, url, headers, 0, max(DL_CHUNK - 1, 1), timeout
        )
        total = int(total or total_hint or 0)
        if total > MAX_DOWNLOAD_BYTES:
            raise TrackUnavailable("аудио превышает лимит отправки")

        async def report(done: int) -> None:
            if progress_cb:
                try:
                    await progress_cb(done, total)
                except Exception:
                    pass

        if status not in (200, 206):
            return await self._plain_or_fail(session, url, headers, timeout, progress_cb, total)
        parts = [head]
        downloaded = len(head)
        await report(downloaded)
        if status == 206 and total and downloaded < total:
            pending = list(range(downloaded, total, DL_CHUNK))
            semaphore = asyncio.Semaphore(max(1, min(DL_WORKERS, len(pending))))
            results: dict[int, tuple[object, bytes]] = {}

            async def one(offset: int) -> None:
                async with semaphore:
                    got_status, chunk, _ = await self._fetch_range(
                        session, url, headers, offset,
                        min(offset + DL_CHUNK - 1, total - 1), timeout,
                    )
                    results[offset] = (got_status, chunk)

            await asyncio.gather(*(one(offset) for offset in pending))
            if any(not chunk for _, chunk in results.values()):
                return await self._plain_or_fail(session, url, headers, timeout, progress_cb, total)
            for offset, (_, chunk) in sorted(results.items()):
                parts.append(chunk)
                downloaded += len(chunk)
                await report(downloaded)
            data = b"".join(parts)
            if len(data) != total:
                raise TrackUnavailable(f"получено {len(data)} из {total} байт")
            return data
        if status == 206 and not total:
            start = downloaded
            while True:
                got_status, chunk, _ = await self._fetch_range(
                    session, url, headers, start, start + DL_CHUNK - 1, timeout
                )
                if not chunk:
                    raise TrackUnavailable(f"обрыв на {start} байт (HTTP {got_status})")
                parts.append(chunk)
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise TrackUnavailable("аудио превышает лимит отправки")
                start += len(chunk)
                await report(downloaded)
                if len(chunk) < DL_CHUNK:
                    break
        return b"".join(parts)

    async def _stream_to_buffer(
        self,
        url: str,
        *,
        progress_cb: Callable[[int, int], Awaitable[Any]] | None = None,
        total_hint: int = 0,
        label: str = "",
        timeout_total: int = 300,
        ext: str = "",
    ) -> AudioBuffer:
        session = self._session
        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(family=socket.AF_INET, limit=20)
            )
        try:
            data = await self._download_bytes(session, url, progress_cb, timeout_total, total_hint)
            return AudioBuffer(data, ext)
        finally:
            if own_session and session:
                await session.close()

    async def download_track(
        self,
        track_id: str,
        progress_cb: Callable[[int, int], Awaitable[Any]] | None = None,
    ) -> io.BytesIO:
        info = await self.get_track_info(track_id)
        if not info or not info.get("download"):
            raise TrackUnavailable("DRM_OR_NOT_FOUND")
        if not info.get("direct", True):
            return await self._download_with_ytdlp(info, progress_cb)
        try:
            return await self._stream_to_buffer(
                str(info["download"]),
                progress_cb=progress_cb,
                total_hint=int(info.get("filesize") or 0),
                label=str(info.get("title") or track_id)[:60],
                ext=str(info.get("ext") or ""),
            )
        except _DOWNLOAD_FALLBACK_ERRORS as exc:
            log.info("Прямое скачивание %s не удалось (%s), пробую yt-dlp", track_id, exc)
            return await self._download_with_ytdlp(info, progress_cb)
