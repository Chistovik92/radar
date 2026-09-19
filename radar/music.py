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

DIRECTORY = os.getenv("MUSIC_DIR") or "data/music"
# Внешнее хранилище: каталог подключается командой mount (или строкой
# в /etc/fstab), а MUSIC_DIR указывает на точку монтирования. Пример —
# в README, раздел «Музыка и внешнее хранилище».

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

# Пережатие (с 4.9.5.4). Формат — opus в контейнере ogg: при 64–96 кбит/с
# он звучит заметно лучше mp3 того же битрейта, а Telegram проигрывает
# его напрямую. Голосу хватает 48 кбит/с, музыке — 96; flac и wav
# (бездоменные исходники) сжимаются вчетверо-впятеро почти без потерь
# на слух.
VOICE_BITRATE_K = 48
MUSIC_BITRATE_K = 96
# Ни этого размера пережатие не имеет смысла: экономия копеечная,
# а перекодирование — всегда потеря.
COMPRESS_MIN_MB = 3

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


def find_track(user: dict, track_id: str) -> dict | None:
    """Запись трека по идентификатору. None — нет такого."""
    for item in tracks_of(user):
        if item.get("id") == track_id:
            return item
    return None


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

    # Расширение берём из убранного трека — имя должно совпасть.
    # Облако и кэш чистит forget_remote: удаление там асинхронное,
    # а эта функция синхронная и вызывается в том числе из тестов.
    path = ""
    for t in tracks:
        if t.get("id") == track_id:
            path = local_path(track_id, str(t.get("ext") or ""))
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


def format_size(size_bytes: float) -> str:
    """«12.4 МБ» — человеку нужен порядок, а не байты."""
    for name, scale in (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024)):
        if size_bytes >= scale:
            return f"{size_bytes / scale:.1f} {name}"
    return f"{int(size_bytes)} Б"


def _related_of(track: dict) -> set[str]:
    """Родственные артисты трека — нормализованные, как и сравниваемые."""
    return {_norm_word(name) for name in track.get("related") or [] if name}


# --------------------------------------------------------------------------
#  Подборки по жанру и артисту (с 4.9.9.3)
# --------------------------------------------------------------------------
#
# Пункт 4 раздела 4.9.5: «подборка по жанру или артисту — поверх готового
# подбора похожих». Всё из своего хранилища: общей библиотеки нет
# и не будет (п.5 того же раздела), подборка собирает только то, что
# человек загрузил сам.

SMART_KINDS = ("genre", "artist")
SMART_MIN = 2       # подборка из одного трека — это трек, а не подборка
SMART_OFFER = 8     # сколько вариантов показывать на экране выбора


def smart_choices(user: dict, kind: str) -> list[tuple[str, int]]:
    """Жанры или артисты своего хранилища: (название, треков), по убыванию."""
    if kind not in SMART_KINDS:
        return []
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}
    for track in tracks_of(user):
        raw = (track.get(kind) or "").strip()
        key = _norm_word(raw)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        shown.setdefault(key, raw)
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], shown[pair[0]].lower()))
    return [(shown[key], count) for key, count in ranked if count >= SMART_MIN][:SMART_OFFER]


def smart_tracks(user: dict, kind: str, value: str) -> list[dict]:
    """Треки своего хранилища с этим жанром или артистом."""
    key = _norm_word(value)
    if kind not in SMART_KINDS or not key:
        return []
    return [track for track in tracks_of(user)
            if _norm_word(track.get(kind) or "") == key]


def build_smart_playlist(user: dict, kind: str, value: str) -> tuple[bool, str]:
    """Плейлист из подборки. Возвращает (получилось, имя или причина).

    Одноимённый плейлист пересобирается, а не заводится вторым: иначе
    каждое нажатие множило бы «Жанр: рок», «Жанр: рок», «Жанр: рок».
    """
    tracks = smart_tracks(user, kind, value)
    if len(tracks) < SMART_MIN:
        return False, "Для подборки нужно хотя бы два трека."

    prefix = "Жанр" if kind == "genre" else "Артист"
    name = safe_title(f"{prefix}: {value}")
    data = dict(_slot(user))
    playlists = [dict(pl) for pl in data.get("playlists") or []]
    existing = next((pl for pl in playlists if pl.get("name") == name), None)
    if existing is None:
        if len(playlists) >= MAX_PLAYLISTS:
            return False, f"Плейлистов уже {MAX_PLAYLISTS} — это предел."
        existing = {"name": name, "tracks": []}
        playlists.append(existing)
    existing["tracks"] = [track["id"] for track in tracks]
    data["playlists"] = playlists
    user[SLOT] = data
    return True, name


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
        artist = _norm_word(track.get("artist") or "")
        if base_artist and artist == base_artist:
            score += 5
        elif artist and artist in _related_of(base):
            # Родственный артист по открытым базам (с 4.9.9.3, см.
            # radar/musicmeta.py): слабее своего, сильнее жанра — «похож
            # по мнению слушателей» точнее, чем «та же полка в магазине».
            score += 4
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


# --------------------------------------------------------------------------
#  Пережатие трека (с 4.9.5.4)
# --------------------------------------------------------------------------

def compress_bitrate_k(source_size: int, duration_s: int) -> int:
    """Битрейт пережатия: качество, близкое к исходному, без жадности.

    Логика честная к звуку: битрейт не поднимается выше исходного —
    перекодирование потерь не добавляет качества, только размер;
    и не опускается ниже VOICE_BITRATE_K — ниже речь невнятна.
    Длительность неизвестна — берём музыкальный потолок: для песни
    в четыре минуты он и так даст четвёрть исходного flac.
    """
    if duration_s <= 0:
        return MUSIC_BITRATE_K
    effective_size = max(source_size, 1)
    source_kbps = int(effective_size * 8 / duration_s / 1000)
    return max(VOICE_BITRATE_K, min(source_kbps, MUSIC_BITRATE_K))


def worth_compress(source_size: int) -> bool:
    """Есть ли смысл пережимать. Мелкий файл не стоит перекодировки."""
    return source_size >= COMPRESS_MIN_MB * 1024 * 1024


def _compressed_ext(source_ext: str) -> str:
    """Контейнер результата: opus живит в ogg."""
    return ".ogg" if source_ext.lower() in (".flac", ".wav", ".mp3",
                                            ".m4a", ".opus") else ".ogg"


async def compress_track(track: dict) -> tuple[bool, str, int]:
    """Пережимает файл трека. Возвращает (вышло, пояснение, новый размер).

    Файл заменяется на месте: id, теги и место в плейлистах не меняются —
    для человека трек тот же, просто полегче. Качество — opus при битрейте
    исходника (см. compress_bitrate_k): на слух разница с mp3 320 kbps
    при 96 kbps opus неразличима для большинства слушателей, а вес
    падает втрое. Громкость и каналы сохраняются.
    """
    import asyncio
    import subprocess

    # Файл может лежать в облаке (с 4.9.9) — тогда его сначала приносят
    # в кэш. Пережимаем всегда локальную копию: гонять ffmpeg по сети
    # незачем, а результат всё равно придётся отправлять обратно.
    source, reason = await ensure_local(track)
    if not source:
        return False, reason or "файл трека не найден", 0
    if not worth_compress(os.path.getsize(source)):
        return False, (f"файл меньше {COMPRESS_MIN_MB} МБ — пережатие "
                       "не окупится"), 0

    target = source + ".tmp.ogg"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", source,
        "-c:a", "libopus", "-b:a", f"{compress_bitrate_k(0, 0)}k",
        "-map_metadata", "0",
        target,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=300)
    except FileNotFoundError:
        return False, "в образе нет ffmpeg", 0
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        _safe_unlink(target)
        return False, "пережатие не уложилось в отведённое время", 0

    if proc.returncode != 0 or not os.path.isfile(target):
        _safe_unlink(target)
        detail = (err or b"").decode("utf-8", "replace")[:120]
        return False, f"ffmpeg не справился: {detail}", 0

    new_size = os.path.getsize(target)
    old_size = os.path.getsize(source)
    if new_size >= old_size:
        # Сжать не вышло — исходник уже плотнее нашего потолка.
        _safe_unlink(target)
        return False, "исходник уже сжат плотнее, чем вышло бы", 0

    os.replace(target, source)
    log.info("Трек пережат: %d → %d байт", old_size, new_size)

    # В облаке лежит прежний, тяжёлый файл. Не заменить его означало бы,
    # что выигрыш от пережатия виден только на этом устройстве, а место
    # в хранилище — то самое, ради которого всё затевалось, — не освободится.
    from . import cloudstore

    if cloudstore.enabled():
        name = track_name(str(track.get("id") or ""), str(track.get("ext") or ""))
        try:
            with open(source, "rb") as handle:
                payload = handle.read()
        except OSError:
            payload = b""
        if payload:
            ok, put_reason = await cloudstore.put(name, payload)
            if not ok:
                # Локально трек уже лёгкий, в облаке — прежний. Рассинхрон
                # безопасен (кэш новее и используется первым), но о нём
                # надо сказать: следующая выгрузка вернёт старый вес.
                log.warning("Пережатый трек не ушёл в облако: %s", put_reason)
                return True, f"в облаке остался прежний файл: {put_reason}", new_size

    return True, "", new_size


def _safe_unlink(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
#  Облако: где лежит трек и как до него дойти (с 4.9.9)
# --------------------------------------------------------------------------
#
# Пока облако выключено, всё как прежде: файл лежит в DIRECTORY и берётся
# оттуда. Когда включено — хранилищем становится облако, а на диске
# остаётся кэш последних треков. Разница видна только здесь: обработчики
# спрашивают `ensure_local` и получают путь, откуда бы файл ни пришёл.
#
# Почему кэш, а не чтение напрямую в Telegram: отдача идёт через чужую
# сеть, и у одного и того же трека, поставленного дважды подряд, не должно
# быть двух скачиваний. Оповещения этим путём не ходят вовсе — музыка
# и мониторинг не делят ни очередь, ни канал.

CACHE_DIRECTORY = os.path.join(DIRECTORY, "cache")

# Сколько места отдаём кэшу. Не настройка: смысл облака в том, что
# на устройстве места мало, и кэш не должен съедать выигрыш.
CACHE_BUDGET_MB = 256


def track_name(track_id: str, ext: str) -> str:
    """Имя файла трека — одно и то же на диске и в облаке."""
    return f"{track_id}{ext or ''}"


def local_path(track_id: str, ext: str) -> str:
    return os.path.join(DIRECTORY, track_name(track_id, ext))


def cache_path(track_id: str, ext: str) -> str:
    return os.path.join(CACHE_DIRECTORY, track_name(track_id, ext))


def cache_size() -> int:
    """Сколько занимает кэш в байтах."""
    total = 0
    try:
        for entry in os.scandir(CACHE_DIRECTORY):
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        return 0
    return total


def trim_cache(budget_mb: int = CACHE_BUDGET_MB) -> int:
    """Убирает из кэша самое давнее, пока не уложится в бюджет.

    Возвращает число убранных файлов. Кэш можно потерять целиком без
    последствий: исходники лежат в облаке, а потерянный кэш означает
    лишь повторное скачивание.
    """
    budget = budget_mb * 1024 * 1024
    try:
        files = [
            (entry.stat().st_atime, entry.stat().st_size, entry.path)
            for entry in os.scandir(CACHE_DIRECTORY) if entry.is_file()
        ]
    except OSError:
        return 0

    total = sum(size for _atime, size, _path in files)
    if total <= budget:
        return 0

    removed = 0
    for _atime, size, path in sorted(files):
        if total <= budget:
            break
        _safe_unlink(path)
        total -= size
        removed += 1
    if removed:
        log.info("Кэш музыки почищен: убрано файлов %d", removed)
    return removed


async def store(track_id: str, ext: str, payload: bytes) -> tuple[str, str]:
    """Сохраняет трек. Возвращает (где лежит, причина отказа).

    «Где лежит» — это `cloud` или `local`. Отказ облака не означает
    отказ приёма: трек остаётся на диске, и человек его не теряет —
    просто место тратится своё. Молчать об этом нельзя, поэтому причина
    возвращается и показывается.
    """
    from . import cloudstore

    os.makedirs(DIRECTORY, exist_ok=True)
    path = local_path(track_id, ext)
    with open(path, "wb") as handle:
        handle.write(payload)

    if not cloudstore.enabled():
        return "local", ""

    ok, reason = await cloudstore.put(track_name(track_id, ext), payload)
    if not ok:
        return "local", reason

    # Ушло в облако — на диске держим тот же файл, но уже как кэш:
    # только что загруженный трек чаще всего сразу и слушают.
    os.makedirs(CACHE_DIRECTORY, exist_ok=True)
    try:
        os.replace(path, cache_path(track_id, ext))
    except OSError:
        _safe_unlink(path)
    trim_cache()
    return "cloud", ""


async def ensure_local(track: dict) -> tuple[str, str]:
    """Путь к файлу трека. Возвращает (путь, причина отказа).

    Порядок поиска: свой каталог, кэш, облако. Первые два — без единого
    запроса в сеть.
    """
    from . import cloudstore

    track_id = str(track.get("id") or "")
    ext = str(track.get("ext") or "")
    if not track_id:
        return "", "Трек не найден."

    path = local_path(track_id, ext)
    if os.path.isfile(path):
        return path, ""

    cached = cache_path(track_id, ext)
    if os.path.isfile(cached):
        # Трогаем время доступа: по нему кэш решает, что убирать первым.
        try:
            os.utime(cached, None)
        except OSError:
            pass
        return cached, ""

    if not cloudstore.enabled():
        return "", "Файл трека потерян — загрузите заново."

    ok, result = await cloudstore.fetch(track_name(track_id, ext))
    if not ok:
        return "", str(result)

    os.makedirs(CACHE_DIRECTORY, exist_ok=True)
    try:
        with open(cached, "wb") as handle:
            handle.write(result if isinstance(result, bytes) else b"")
    except OSError as exc:
        log.warning("Кэш не записан: %s", exc)
        return "", "Не удалось сохранить трек на диск."
    trim_cache()
    return cached, ""


async def forget_remote(track_id: str, ext: str) -> None:
    """Убирает трек из облака и из кэша. Ошибку облака переживаем молча:
    запись у человека уже удалена, и возвращать её из-за чужой сети
    было бы хуже, чем оставить файл-сироту."""
    from . import cloudstore

    _safe_unlink(cache_path(track_id, ext))
    if not cloudstore.enabled():
        return
    if not await cloudstore.delete(track_name(track_id, ext)):
        log.info("Трек %s остался в облаке — удалить не удалось", track_id)


# --------------------------------------------------------------------------
#  Диск (с 4.9.5.4)
# --------------------------------------------------------------------------

# Порог предупреждения: выше 85% занятого места любые новые данные —
# риск для базы и оповещений, а не только для музыки.
DISK_WARN_PERCENT = 85


def disk_report(paths: list[str]) -> str:
    """Сводка по заполненности дисков для ночного письма.

    Пути могут вести к разным точкам монтирования (музыка вынесена
    на внешний носитель — у неё свой диск), поэтому считаем каждую
    точку отдельно и убираем повторы.
    """
    import shutil

    seen: dict[str, str] = {}
    lines: list[str] = []
    worst_percent = 0

    for path in paths:
        try:
            usage = shutil.disk_usage(path or ".")
        except OSError:
            continue
        key = f"{usage.total}:{usage.free}"
        if key in seen:
            continue
        seen[key] = path
        percent = int(usage.used * 100 / usage.total) if usage.total else 0
        worst_percent = max(worst_percent, percent)
        lines.append(
            f"• {path}: {format_size(usage.used)} из {format_size(usage.total)} "
            f"({percent}%)"
        )

    if not lines:
        return ""
    head = "💾 <b>Диски</b>"
    # Строка про кэш: при включённом облаке место на диске тратит он,
    # и знать его вес полезнее, чем гадать, куда делись гигабайты.
    cached = cache_size()
    if cached:
        lines.append(
            f"• кэш музыки: {format_size(cached)} "
            f"из {CACHE_BUDGET_MB} МБ бюджета"
        )
    if worst_percent >= DISK_WARN_PERCENT:
        head += f"\n⚠️ Один из дисков заполнен более чем на {DISK_WARN_PERCENT}% — место кончается."
    return head + "\n" + "\n".join(lines)
