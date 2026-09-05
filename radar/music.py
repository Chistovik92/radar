"""Музыка и плейлисты (с 4.9.5.2, каркас).

Замысел из дорожной карты (раздел 4.9.5): треки присылаются файлом
или ссылкой, раскладываются по плейлистам, играют встроенным
проигрывателем Telegram.

Этот выпуск — первый шаг, ядро:

* хранение: файлы в `data/music/<id>.mp3`, описание в записи
  пользователя (`user["music"]`): треки и плейлисты;
* каждый слушает только своё — общей библиотеки нет. Раздача чужих
  фонограмм — это распространение, а не прослушивание, и платной
  выдачей треков бот становился бы пиратским сервисом;
* метаданные ID3 (артист, название) разбираются на чистой стандартной
  библиотеке — внешний тег-парсер ради трёх полей не тащим;
* приём файла и отдача — в `handlers/music.py`, сюда только логика.

Что дальше (по плану): подбор похожего по тегам, MusicBrainz,
перемешивание. Всё это поверх этого же хранилища.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("radar.music")

DIRECTORY = "data/music"

# Форматы, которые умеет играть встроенный проигрыватель Telegram.
SUPPORTED_EXT = (".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav")

# Пределы. Файл больше — не принимаем: это уже не «песня в мессенджере»,
# а архив, и держать его на одноплатнике незачем.
MAX_TRACK_MB = 30
# Сколько треков у одного человека без подписки/под ней — как у видео:
# считаем штуки, они понятны и честны.
FREE_TRACKS = 20
SUBSCRIBED_TRACKS = 500

MAX_PLAYLISTS = 20
MAX_TITLE = 60

_UNSAFE = re.compile(r"[^\w\-. ]+", re.U)


# --------------------------------------------------------------------------
#  ID3: три поля на стандартной библиотеке
# --------------------------------------------------------------------------

def _id3_text(data: bytes, tag: bytes) -> str:
    """Текстовый кадр ID3v2 (TIT2/TPE1/TALB). Пусто — не нашли.

    Разбор нарочно простейший: ищем заголовок кадра «TXXн», читаем
    длину из syncsafe-байтов и вынимаем текст. Полный парсер ради
    трёх полей — сотни строк, которые всё равно падают на музыке
    с нестандартными тегами.
    """
    start = data.find(b"ID3")
    if start < 0:
        return ""
    try:
        pos = data.find(tag, start)
        if pos < 0:
            return ""
        # Заголовок кадра: 4 байта имя + 4 байта длина (syncsafe).
        size = ((data[pos + 4] & 0x7F) << 21
                | (data[pos + 5] & 0x7F) << 14
                | (data[pos + 6] & 0x7F) << 7
                | (data[pos + 7] & 0x7F))
        raw = data[pos + 10: pos + 10 + size]
        if not raw:
            return ""
        # Первый байт — кодировка: 0/3 — байтовые, 1/2 — UTF-16.
        encoding = raw[0]
        body = raw[1:]
        if encoding in (1, 2):
            text = body.decode("utf-16", errors="replace")
        else:
            text = body.decode("latin-1", errors="replace")
        return text.split("\x00")[0].strip()
    except Exception:  # noqa: BLE001
        return ""


def read_tags(data: bytes) -> dict[str, str]:
    """Артист, название и жанр из ID3. Пустые — тегов нет."""
    return {
        "artist": _id3_text(data, b"TPE1"),
        "title": _id3_text(data, b"TIT2"),
        "genre": _id3_text(data, b"TCON"),
    }


# --------------------------------------------------------------------------
#  Хранилище: запись пользователя
# --------------------------------------------------------------------------

# user["music"] = {
#   "tracks": [{"id": "abc", "name": "...", "artist": "", "title": "",
#               "size": 123, "ext": ".mp3"}],
#   "playlists": [{"name": "Дорога", "tracks": ["abc", ...]}],
# }

SLOT = "music"


def _slot(user: dict) -> dict:
    data = (user or {}).get(SLOT)
    return data if isinstance(data, dict) else {}


def tracks_of(user: dict) -> list[dict]:
    return list(_slot(user).get("tracks") or [])


def playlists_of(user: dict) -> list[dict]:
    return list(_slot(user).get("playlists") or [])


def track_limit(user: dict, role: str | None = None) -> int:
    """Сколько треков можно держать. Подписка расширяет хранилище."""
    from . import subscription

    if subscription.active(user, role):
        return SUBSCRIBED_TRACKS
    return FREE_TRACKS


def safe_title(name: str) -> str:
    cleaned = _UNSAFE.sub(" ", (name or "").strip()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:MAX_TITLE].strip() or "Без названия"


def add_track(user: dict, track_id: str, *, name: str, ext: str,
              size: int, artist: str = "", title: str = "",
              genre: str = "") -> bool:
    """Записывает трек. False — хранилище переполнено."""
    data = dict(_slot(user))
    tracks = list(data.get("tracks") or [])
    # Лимит по роли проверяет вызывающий: здесь только целостность записи.
    tracks.append({
        "id": track_id, "name": safe_title(name), "ext": ext,
        "size": size, "artist": artist[:80], "title": title[:80],
        "genre": genre[:40],
    })
    data["tracks"] = tracks
    user[SLOT] = data
    return True


def remove_track(user: dict, track_id: str) -> bool:
    """Убирает трек из записи и с диска. False — не было такого."""
    data = dict(_slot(user))
    tracks = list(data.get("tracks") or [])
    rest = [t for t in tracks if t.get("id") != track_id]
    if len(rest) == len(tracks):
        return False

    # Из плейлистов тоже: ссылка на удалённый трек — мусор.
    playlists = []
    for pl in list(data.get("playlists") or []):
        kept = dict(pl)
        kept["tracks"] = [t for t in (pl.get("tracks") or [])
                          if t != track_id]
        playlists.append(kept)

    data["tracks"] = rest
    data["playlists"] = playlists
    user[SLOT] = data

    # Расширение берём из убранного трека — путь должен совпасть.
    path = ""
    for t in tracks:
        if t.get("id") == track_id:
            path = os.path.join(DIRECTORY, f"{track_id}{t.get('ext') or ''}")
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        log.debug("Файл трека не удалён: %s", path)
    return True


def create_playlist(user: dict, name: str) -> bool:
    """Новый плейлист. False — лимит или имя занято."""
    data = dict(_slot(user))
    playlists = list(data.get("playlists") or [])
    if len(playlists) >= MAX_PLAYLISTS:
        return False
    title = safe_title(name)
    if any(pl.get("name") == title for pl in playlists):
        return False
    playlists.append({"name": title, "tracks": []})
    data["playlists"] = playlists
    user[SLOT] = data
    return True


def toggle_in_playlist(user: dict, playlist: str, track_id: str) -> bool | None:
    """Добавить/убрать трек из плейлиста. None — плейлиста нет."""
    data = dict(_slot(user))
    playlists = list(data.get("playlists") or [])
    target = None
    for pl in playlists:
        if pl.get("name") == playlist:
            target = pl
            break
    if target is None:
        return None
    tracks = list(target.get("tracks") or [])
    if track_id in tracks:
        tracks.remove(track_id)
        added = False
    else:
        tracks.append(track_id)
        added = True
    target["tracks"] = tracks
    data["playlists"] = playlists
    user[SLOT] = data
    return added


def playlist_tracks(user: dict, playlist: str) -> list[dict]:
    """Треки плейлиста в его порядке."""
    by_id = {t.get("id"): t for t in tracks_of(user)}
    for pl in playlists_of(user):
        if pl.get("name") == playlist:
            return [by_id[tid] for tid in (pl.get("tracks") or [])
                    if tid in by_id]
    return []


def describe(user: dict, role: str | None = None) -> str:
    """Строка о состоянии: сколько треков, плейлистов, лимит."""
    tracks = tracks_of(user)
    limit = track_limit(user, role)
    playlists = playlists_of(user)
    lines = [
        f"Треков: <b>{len(tracks)}</b> из {limit}",
        f"Плейлистов: <b>{len(playlists)}</b> из {MAX_PLAYLISTS}",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
#  Подбор похожего и перемешивание (с 4.9.5.3)
# --------------------------------------------------------------------------

def _norm_word(value: str) -> str:
    """Нормализованный вид тега: без регистра, пунктуации и пробелов."""
    return re.sub(r"[\W_]+", "", (value or "").lower())


def similar(user: dict, track_id: str, limit: int = 5) -> list[dict]:
    """Похожие треки из загруженного самим человеком.

    Никакой сети: только ID3-теги своего хранилища. Похожесть — сумма
    совпадений тегов:

    * артист совпал полностью — 5 очков (обычно это и есть «похожее»);
    * жанр совпал — 3 очка: жанр честнее называет настроение;
    * разница лет меньше трёх — 1 очко: эпоха, но не «похожесть».

    Без тегов у трека-образца подбор честно пуст: гадать по названию
    файла — дорога к «похожее: всё подряд». Порядок — по очкам,
    внутри одного счёта — как легло хранилище.
    """
    tracks = tracks_of(user)
    base = next((t for t in tracks if t.get("id") == track_id), None)
    if base is None:
        return []

    base_artist = _norm_word(base.get("artist") or "")
    base_genre = _norm_word(base.get("genre") or "")
    base_year = (base.get("year") or "").strip()

    scored: list[tuple[int, dict]] = []
    for track in tracks:
        if track.get("id") == track_id:
            continue

        score = 0
        if base_artist and _norm_word(track.get("artist") or "") == base_artist:
            score += 5
        if base_genre and base_genre == _norm_word(track.get("genre") or ""):
            score += 3
        year = (track.get("year") or "").strip()
        if base_year and year and year.isdigit() and base_year.isdigit():
            if abs(int(year) - int(base_year)) < 3:
                score += 1

        if score > 0:
            scored.append((score, track))

    scored.sort(key=lambda pair: -pair[0])
    return [track for _score, track in scored[:limit]]


def shuffle_playlist(user: dict, playlist: str, seed: str = "") -> list[dict]:
    """Перемешанный плейлист. Порядок пишется в запись: перемешали —
    и плейлист играет в новом порядке, пока не перемешают снова.

    Seed по умолчанию — время: каждое перемешивание даёт новый порядок.
    """
    import random

    tracks = playlist_tracks(user, playlist)
    if not tracks:
        return []

    rng = random.Random(seed or None)
    # Исходный порядок стабилен (по id): второй запуск с тем же seed
    # даёт тот же результат — иначе seed бессмыслен.
    order = sorted(t["id"] for t in tracks)
    rng.shuffle(order)

    data = dict(_slot(user))
    playlists = list(data.get("playlists") or [])
    for pl in playlists:
        if pl.get("name") == playlist:
            pl["tracks"] = order
            break
    data["playlists"] = playlists
    user[SLOT] = data

    by_id = {t.get("id"): t for t in tracks}
    return [by_id[tid] for tid in order if tid in by_id]
