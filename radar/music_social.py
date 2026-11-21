"""Социальная механика внешнего музыкального каталога (6.0.0).

Здесь нет Telegram и сети: только записи пользователя и JSON в ``meta``.
Плейлисты содержат идентификаторы, а не аудио. Счётчики лайков вычисляются по
множествам пользователей, поэтому повторный toggle не накручивает статистику.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from . import music, storage

PLAYLISTS_KEY = "music_playlists"
LIKES_KEY = "music_likes"
DISLIKES_KEY = "music_dislikes"
VIEWS_KEY = "music_views"
HISTORY_TTL = 30 * 86400
MAX_HISTORY = 100
MAX_RECENT = 5
MAX_PUBLIC_PLAYLISTS = 20
MAX_PLAYLIST_TRACKS = 100

_lock = asyncio.Lock()


def history_of(user: dict, now: int | None = None) -> list[dict[str, Any]]:
    """История за 30 дней, новая запись первая; старые удаляются при чтении."""
    now = int(time.time() if now is None else now)
    data = dict(music._slot(user))
    result = []
    for item in data.get("history") or []:
        if not isinstance(item, dict) or not item.get("track_id"):
            continue
        try:
            at = int(item.get("at") or 0)
        except (TypeError, ValueError):
            continue
        if now - at <= HISTORY_TTL:
            result.append({"track_id": str(item["track_id"]), "at": at})
    data["history"] = result
    user[music.SLOT] = data
    return list(result)


def record_history(user: dict, track_id: str, now: int | None = None) -> None:
    now = int(time.time() if now is None else now)
    track_id = str(track_id or "")[:80]
    if not track_id:
        return
    items = [item for item in history_of(user, now) if item["track_id"] != track_id]
    items.insert(0, {"track_id": track_id, "at": now})
    data = dict(music._slot(user))
    data["history"] = items[:MAX_HISTORY]
    data["played"] = max(0, int(data.get("played") or 0)) + 1
    user[music.SLOT] = data


def remove_history(user: dict, track_id: str) -> bool:
    items = history_of(user)
    kept = [item for item in items if item["track_id"] != track_id]
    if len(kept) == len(items):
        return False
    data = dict(music._slot(user))
    data["history"] = kept
    user[music.SLOT] = data
    return True


def clear_history(user: dict) -> None:
    data = dict(music._slot(user))
    data["history"] = []
    user[music.SLOT] = data


def remember_query(user: dict, query: str) -> None:
    query = " ".join(str(query or "").split())[:200]
    if not query:
        return
    items = [item for item in recent_queries(user) if item.casefold() != query.casefold()]
    items.insert(0, query)
    data = dict(music._slot(user))
    data["recent"] = items[:MAX_RECENT]
    user[music.SLOT] = data


def recent_queries(user: dict) -> list[str]:
    return [str(item) for item in (music._slot(user).get("recent") or []) if item]


def set_profile(user: dict, *, about: str | None = None, hidden: bool | None = None) -> None:
    data = dict(music._slot(user))
    profile = dict(data.get("profile") or {})
    if about is not None:
        profile["about"] = " ".join(str(about).split())[:500]
    if hidden is not None:
        profile["hidden"] = bool(hidden)
    data["profile"] = profile
    user[music.SLOT] = data


def profile(user: dict) -> dict[str, Any]:
    data = music._slot(user)
    value = data.get("profile") or {}
    return {
        "about": str(value.get("about") or "")[:500],
        "hidden": bool(value.get("hidden")),
        "played": max(0, int(data.get("played") or 0)),
    }


def _uids(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = value.get("users") or value.get("liked_by") or []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item)))


def _counts(reactions: dict[str, Any], track_id: str) -> tuple[int, int]:
    likes = len(_uids((reactions.get(LIKES_KEY) or {}).get(track_id)))
    dislikes = len(_uids((reactions.get(DISLIKES_KEY) or {}).get(track_id)))
    return likes, dislikes


async def reaction_counts(track_id: str) -> tuple[int, int]:
    likes = await storage.meta_get(LIKES_KEY, {})
    dislikes = await storage.meta_get(DISLIKES_KEY, {})
    return len(_uids((likes or {}).get(track_id))), len(_uids((dislikes or {}).get(track_id)))


async def _toggle_reaction(track_id: str, uid: str | int, like: bool) -> tuple[bool, int, int]:
    track_id = str(track_id or "")[:80]
    uid = str(uid)
    if not track_id:
        return False, 0, 0
    primary_key = LIKES_KEY if like else DISLIKES_KEY
    other_key = DISLIKES_KEY if like else LIKES_KEY
    async with _lock:
        primary = dict(await storage.meta_get(primary_key, {}) or {})
        other = dict(await storage.meta_get(other_key, {}) or {})
        users = _uids(primary.get(track_id))
        active = uid not in users
        if active:
            users.append(uid)
        else:
            users.remove(uid)
        primary[track_id] = users
        other_users = [item for item in _uids(other.get(track_id)) if item != uid]
        other[track_id] = other_users
        await storage.meta_set(primary_key, primary)
        await storage.meta_set(other_key, other)
    return active, (len(users) if like else len(other_users)), (len(other_users) if like else len(users))


async def toggle_like(track_id: str, uid: str | int) -> tuple[bool, int, int]:
    return await _toggle_reaction(track_id, uid, True)


async def toggle_dislike(track_id: str, uid: str | int) -> tuple[bool, int, int]:
    return await _toggle_reaction(track_id, uid, False)


async def register_view(track_id: str) -> int:
    track_id = str(track_id or "")[:80]
    if not track_id:
        return 0
    async with _lock:
        views = dict(await storage.meta_get(VIEWS_KEY, {}) or {})
        count = max(0, int(views.get(track_id) or 0)) + 1
        views[track_id] = count
        await storage.meta_set(VIEWS_KEY, views)
        return count


async def top_tracks(limit: int = 20) -> list[dict[str, Any]]:
    catalog = await storage.meta_get("music_catalog", {})
    views = await storage.meta_get(VIEWS_KEY, {})
    result = []
    for track_id, raw in (catalog or {}).items():
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["id"] = str(track_id)
        item["views"] = max(0, int((views or {}).get(track_id) or 0))
        if item["views"] > 0:
            result.append(item)
    result.sort(key=lambda item: (item["views"], int(item.get("duration") or 0)), reverse=True)
    return result[:max(1, min(int(limit), 100))]


async def random_track() -> dict[str, Any] | None:
    catalog = await storage.meta_get("music_catalog", {})
    choices = [(str(key), value) for key, value in (catalog or {}).items()
               if isinstance(value, dict)]
    if not choices:
        return None
    track_id, raw = secrets.SystemRandom().choice(choices)
    return {**raw, "id": track_id}


def _clean_playlist(raw: dict[str, Any], playlist_id: str = "") -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or playlist_id)[:16],
        "name": music.safe_title(str(raw.get("name") or "Плейлист")),
        "founder_id": str(raw.get("founder_id") or ""),
        "tracks": list(dict.fromkeys(str(item) for item in (raw.get("tracks") or []) if item))[:MAX_PLAYLIST_TRACKS],
        "liked_by": _uids(raw.get("liked_by")),
        "views": max(0, int(raw.get("views") or 0)),
        "likes": len(_uids(raw.get("liked_by"))),
        "is_public": bool(raw.get("is_public", True)),
        "created": max(0, int(raw.get("created") or 0)),
    }


async def create_public_playlist(uid: str | int, name: str, *, is_public: bool = True) -> dict[str, Any] | None:
    uid = str(uid)
    async with _lock:
        playlists = dict(await storage.meta_get(PLAYLISTS_KEY, {}) or {})
        owned = [item for item in playlists.values()
                 if isinstance(item, dict) and str(item.get("founder_id")) == uid]
        if len(owned) >= MAX_PUBLIC_PLAYLISTS:
            return None
        playlist_id = secrets.token_hex(8)
        item = _clean_playlist({
            "id": playlist_id, "name": name, "founder_id": uid,
            "is_public": is_public, "created": int(time.time()),
        }, playlist_id)
        playlists[playlist_id] = item
        await storage.meta_set(PLAYLISTS_KEY, playlists)
        return dict(item)


async def toggle_public_track(playlist_id: str, uid: str | int, track_id: str) -> bool | None:
    uid = str(uid)
    async with _lock:
        playlists = dict(await storage.meta_get(PLAYLISTS_KEY, {}) or {})
        raw = playlists.get(playlist_id)
        if not isinstance(raw, dict) or str(raw.get("founder_id")) != uid:
            return None
        item = _clean_playlist(raw, playlist_id)
        tracks = list(item["tracks"])
        if track_id in tracks:
            tracks.remove(track_id)
            added = False
        elif len(tracks) >= MAX_PLAYLIST_TRACKS:
            return None
        else:
            tracks.append(track_id)
            added = True
        item["tracks"] = tracks
        playlists[playlist_id] = item
        await storage.meta_set(PLAYLISTS_KEY, playlists)
        return added


async def public_playlist_view(playlist_id: str, viewer_id: str | int, *, count_view: bool = True) -> dict[str, Any] | None:
    viewer_id = str(viewer_id)
    async with _lock:
        playlists = dict(await storage.meta_get(PLAYLISTS_KEY, {}) or {})
        raw = playlists.get(playlist_id)
        if not isinstance(raw, dict):
            return None
        item = _clean_playlist(raw, playlist_id)
        if not item["is_public"] and item["founder_id"] != viewer_id:
            return None
        if count_view and item["founder_id"] != viewer_id:
            item["views"] += 1
            playlists[playlist_id] = item
            await storage.meta_set(PLAYLISTS_KEY, playlists)
        return dict(item)


async def toggle_playlist_like(playlist_id: str, uid: str | int) -> bool:
    uid = str(uid)
    async with _lock:
        playlists = dict(await storage.meta_get(PLAYLISTS_KEY, {}) or {})
        raw = playlists.get(playlist_id)
        if not isinstance(raw, dict):
            return False
        item = _clean_playlist(raw, playlist_id)
        if not item["is_public"] and item["founder_id"] != uid:
            return False
        users = list(item["liked_by"])
        active = uid not in users
        if active:
            users.append(uid)
        else:
            users.remove(uid)
        item["liked_by"] = users
        item["likes"] = len(users)
        playlists[playlist_id] = item
        await storage.meta_set(PLAYLISTS_KEY, playlists)
        return active


async def user_playlists(uid: str | int) -> list[dict[str, Any]]:
    """Все плейлисты владельца, включая скрытые из публичного топа."""
    playlists = await storage.meta_get(PLAYLISTS_KEY, {})
    result = [_clean_playlist(raw, str(key)) for key, raw in (playlists or {}).items()
              if isinstance(raw, dict) and str(raw.get("founder_id")) == str(uid)]
    result.sort(key=lambda item: item["created"], reverse=True)
    return result


async def top_playlists(limit: int = 20) -> list[dict[str, Any]]:
    playlists = await storage.meta_get(PLAYLISTS_KEY, {})
    result = [_clean_playlist(raw, str(key)) for key, raw in (playlists or {}).items()
              if isinstance(raw, dict) and raw.get("is_public", True)]
    result.sort(key=lambda item: (item["likes"], item["views"], item["created"]), reverse=True)
    return result[:max(1, min(int(limit), 100))]


async def delete_public_playlist(playlist_id: str, uid: str | int) -> bool:
    async with _lock:
        playlists = dict(await storage.meta_get(PLAYLISTS_KEY, {}) or {})
        raw = playlists.get(playlist_id)
        if not isinstance(raw, dict) or str(raw.get("founder_id")) != str(uid):
            return False
        playlists.pop(playlist_id, None)
        await storage.meta_set(PLAYLISTS_KEY, playlists)
        return True


async def share_track(track_id: str) -> dict[str, Any] | None:
    from . import musicsearch

    track = await musicsearch.catalog_get(track_id)
    return {**track, "id": track_id} if track else None


async def share_playlist(playlist_id: str, uid: str | int) -> dict[str, Any] | None:
    return await public_playlist_view(playlist_id, uid, count_view=False)


async def stats(user: dict, uid: str | int | None = None) -> dict[str, int]:
    """Прослушано/лайки/избранное/плейлисты для карточки профиля."""
    likes = await storage.meta_get(LIKES_KEY, {})
    uid = str(uid if uid is not None else (user.get("id") or user.get("uid") or ""))
    own_likes = sum(1 for users in (likes or {}).values() if uid and uid in _uids(users))
    playlists = await storage.meta_get(PLAYLISTS_KEY, {})
    own_playlists = sum(1 for item in (playlists or {}).values()
                        if isinstance(item, dict) and str(item.get("founder_id")) == uid)
    return {
        "played": profile(user)["played"],
        "likes": own_likes,
        "saved": len(music.saved_tracks(user)),
        "playlists": own_playlists,
    }
