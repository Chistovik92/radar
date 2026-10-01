"""Музыка в голосовом канале Discord по ссылке (с 5.9.7).

⚠️ С ЖИВЫМ DISCORD НЕ ПРОВЕРЕНО.

Что умеет: `/play` принимает ссылку на трек, плейлист или файл —
YouTube, SoundCloud, Bandcamp, Яндекс Музыка, прямые ссылки на аудио и всё,
что открывает yt-dlp, — а также просто слова для поиска. Бот входит в тот
голосовой канал, где сидит попросивший, ставит треки в очередь и играет.

Почему `discord.py`. Голос — отдельный протокол (Voice Gateway, UDP,
шифрование), а с 2026-03-02 Discord требует от всех голосовых клиентов,
ботов в том числе, сквозное шифрование DAVE: клиент без него просто не
подключится. `discord.py` 2.7 тянет DAVE через пакет `davey` (`pip install
discord.py[voice]`), самописный клиент на `aiohttp` пришлось бы дополнять
этим самим. Поэтому голос идёт отдельным соединением `discord.Client` с
минимальными намерениями (серверы и голосовые состояния), а команды и кнопки
по-прежнему обслуживает адаптер `platforms/discord.py` — решение автора
допустить `discord.py` в зависимости действует только для голоса.

Устройство. Логика очереди не знает про `discord.py`: она говорит с
«хозяином голоса» через четыре метода (`connect`, `play`, `stop`,
`disconnect`) — поэтому проверяется без Discord и без звука. Поток берётся
у yt-dlp **в момент проигрывания**, а не при постановке в очередь: ссылки
на поток живут часы, и трек, простоявший час в очереди, иначе не заиграл бы.
Звук отдаётся ffmpeg-ом в Opus (`FFmpegOpusAudio`, копирование без
перекодирования, когда источник уже Opus) — на одноплатнике это решает,
потянет ли он голос вообще.

О праве. Скачивание и проигрывание с YouTube и подобных сервисов нарушает их
условия использования; такие боты регулярно блокируют. Возможность выключена
по умолчанию, а ответственность за ссылки лежит на том, кто включает её на
своём сервере.

Чего нет: Spotify, Apple Music, Deezer и прочих сервисов с защитой (DRM) —
yt-dlp их не открывает; бот так и отвечает.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import re
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("radar.discordmusic")

MAX_QUEUE = 50
MAX_MINUTES = 180            # длиннее — не ставим: ролик на пять часов держит канал
MAX_GUILDS = 2               # одновременных голосовых подключений: ARM, один процессор
PLAYLIST_LIMIT = 25
IDLE_LEAVE = 300             # секунд тишины, после которых бот выходит из канала
SWEEP_EVERY = 30
RESOLVE_TIMEOUT = 60
LINK_LIMIT = 500
SEARCH_LIMIT = 200

PROTECTED = ("open.spotify.com", "spotify.link", "music.apple.com",
             "deezer.com", "tidal.com", "music.amazon.com")
PLAYLIST_HINT = re.compile(r"(/playlist\b|/sets/|/album/|/albums/|/artist/)", re.I)


# --------------------------------------------------------------------------
#  Ссылки и описание трека
# --------------------------------------------------------------------------

@dataclass
class Track:
    page: str                       # что просили: ссылка или слова для поиска
    title: str = ""
    duration: int = 0               # секунды; 0 — неизвестно (поток)
    requester: str = ""
    stream: str = ""                # прямой адрес потока — заполняется при проигрывании
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.title or self.page


def format_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def clean_request(text: str) -> tuple[str, str]:
    """Что просят сыграть: (вид, значение). Вид — «link», «search» или «»
    (пусто — просьба не разобрана)."""
    text = (text or "").strip()
    if not text:
        return "", ""
    first = text.split()[0]
    if re.match(r"^https?://", first, re.I):
        if len(first) > LINK_LIMIT:
            return "", ""
        return "link", first
    if "://" in first:
        return "", ""
    return "search", text[:SEARCH_LIMIT]


def protected_service(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == name or host.endswith("." + name) for name in PROTECTED)


def wants_playlist(url: str) -> bool:
    """Просят весь список или один трек. Ролик внутри списка
    (`watch?v=…&list=…`) — один трек: так ждёт человек, скопировавший
    адрес из строки браузера."""
    if PLAYLIST_HINT.search(urlparse(url).path):
        return True
    query = parse_qs(urlparse(url).query)
    return "list" in query and "v" not in query


def ffmpeg_before_options(track: Track) -> str:
    """Параметры ffmpeg до источника: переподключение при обрыве и
    заголовки, без которых часть площадок отдаёт 403."""
    parts = ["-reconnect", "1", "-reconnect_streamed", "1",
             "-reconnect_delay_max", "5"]
    if track.headers:
        # ffmpeg ждёт заголовки одной строкой, разделённой CRLF.
        header = "".join(f"{key}: {value}\r\n" for key, value in track.headers.items()
                         if key.lower() in ("user-agent", "referer", "origin",
                                            "cookie", "accept", "accept-language")
                         and "\n" not in str(value) and "\r" not in str(value))
        if header:
            parts += ["-headers", header]
    return " ".join(shlex.quote(item) for item in parts)


# --------------------------------------------------------------------------
#  yt-dlp
# --------------------------------------------------------------------------

def _audio_options(proxy: str, cookies: str, clients: tuple[str, ...] | None,
                   playlist: bool) -> dict[str, Any]:
    from . import media

    options = media.probe_options(proxy=proxy, cookies=cookies,
                                  clients=clients)
    options.update({
        "format": "bestaudio/best",
        "noplaylist": not playlist,
        "skip_download": True,
    })
    if playlist:
        # Плейлист разбирается плоско: заголовки без потоков — потоки берутся
        # у каждого трека в момент проигрывания.
        options["extract_flat"] = "in_playlist"
        options["playlistend"] = PLAYLIST_LIMIT
    return options


def _extract_blocking(target: str, options: dict[str, Any]) -> dict[str, Any]:
    import yt_dlp

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(target, download=False)
    return info if isinstance(info, dict) else {}


async def extract(target: str, *, playlist: bool = False, proxy: str = "",
                  cookies: str = "",
                  run: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
                  ) -> dict[str, Any]:
    """Описание ссылки у yt-dlp. Каскад клиентов YouTube — тот же, что у
    загрузки видео: сначала без cookies, при осечке — умолчания."""
    from . import media

    runner = run or _extract_blocking
    loop = asyncio.get_running_loop()
    last: BaseException | None = None
    for clients in (media.YOUTUBE_COOKIELESS, None):
        options = _audio_options(proxy, cookies, clients, playlist)
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, runner, target, options), RESOLVE_TIMEOUT)
        except asyncio.TimeoutError as exc:
            last = exc
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
            if clients is None or not media.worth_client_retry(exc):
                break
    raise RuntimeError(str(last) if last else "не удалось открыть ссылку")


def tracks_from(info: dict[str, Any], requester: str, page: str) -> list[Track]:
    """Описание yt-dlp → треки. У плейлиста — по записи, у трека — один."""
    entries = info.get("entries")
    if entries is not None:
        found = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            target = str(entry.get("webpage_url") or entry.get("url") or "")
            if not target:
                continue
            found.append(Track(page=target, title=str(entry.get("title") or ""),
                               duration=int(entry.get("duration") or 0),
                               requester=requester))
            if len(found) >= PLAYLIST_LIMIT:
                break
        return found
    return [Track(page=str(info.get("webpage_url") or page),
                  title=str(info.get("title") or ""),
                  duration=int(info.get("duration") or 0), requester=requester,
                  stream=str(info.get("url") or ""),
                  headers=dict(info.get("http_headers") or {}))]


# --------------------------------------------------------------------------
#  Очередь и игрок
# --------------------------------------------------------------------------

class VoiceHost:
    """Что нужно очереди от голоса. Настоящий — `DiscordPyHost`."""

    async def connect(self, guild: str, channel: str) -> Any: ...
    async def play(self, handle: Any, track: Track,
                   after: Callable[[BaseException | None], None]) -> None: ...
    def stop(self, handle: Any) -> None: ...
    def pause(self, handle: Any) -> None: ...
    def resume(self, handle: Any) -> None: ...
    async def disconnect(self, handle: Any) -> None: ...
    def channel_of(self, handle: Any) -> str: ...


@dataclass
class Player:
    guild: str
    channel: str
    handle: Any
    queue: list[Track] = field(default_factory=list)
    current: Track | None = None
    paused: bool = False
    idle_since: float = 0.0


@dataclass
class Outcome:
    ok: bool
    text: str


class Manager:
    """Очереди по серверам. Всё, что меняет состояние, идёт под одной
    блокировкой: нажатия приходят параллельно, а очередь — одна."""

    def __init__(self, host: VoiceHost, *, clock: Callable[[], float] = time.time,
                 extractor: Callable[..., Awaitable[dict[str, Any]]] = extract,
                 guard: Callable[[str], Awaitable[bool]] | None = None,
                 max_queue: int = MAX_QUEUE, max_minutes: int = MAX_MINUTES,
                 max_guilds: int = MAX_GUILDS, proxy: str = "",
                 cookies: Callable[[], str] | None = None) -> None:
        self.host = host
        self.clock = clock
        self.extractor = extractor
        self.guard = guard
        self.max_queue = max_queue
        self.max_minutes = max_minutes
        self.max_guilds = max_guilds
        self.proxy = proxy
        self.cookies = cookies or (lambda: "")
        self.players: dict[str, Player] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- постановка -------------------------------------------------

    async def add(self, guild: str, channel: str, user: str, request: str) -> Outcome:
        kind, value = clean_request(request)
        if not kind:
            return Outcome(False, "Пришлите ссылку (http…) или слова для поиска.")
        if kind == "link":
            if protected_service(value):
                return Outcome(False, "Spotify, Apple Music, Deezer и подобные "
                                      "сервисы отдают защищённый поток — их не "
                                      "открыть. Пришлите ссылку YouTube, SoundCloud, "
                                      "Bandcamp или на аудиофайл — или слова для поиска.")
            if self.guard is not None and not await self.guard(value):
                return Outcome(False, "Эта ссылка ведёт во внутреннюю сеть — не открываю.")
        target = value if kind == "link" else f"ytsearch1:{value}"
        playlist = kind == "link" and wants_playlist(value)

        try:
            info = await self.extractor(target, playlist=playlist, proxy=self.proxy,
                                        cookies=self.cookies())
        except Exception as exc:  # noqa: BLE001
            log.info("Музыка: ссылка не открылась: %s", exc)
            return Outcome(False, f"Не удалось открыть ссылку: {_short(exc)}")

        if info.get("_type") == "playlist" and "entries" in info and not playlist:
            # Поиск вернул список — берём первый результат.
            entries = [item for item in (info.get("entries") or []) if item]
            info = entries[0] if entries else {}
        tracks = tracks_from(info, user, value)
        if not tracks:
            return Outcome(False, "Ничего не нашлось по этому запросу.")

        limit = self.max_minutes * 60
        tracks = [t for t in tracks if not (limit and t.duration > limit)]
        if not tracks:
            return Outcome(False, f"Трек длиннее {self.max_minutes} мин — не ставлю.")

        async with self._lock:
            self._loop = asyncio.get_running_loop()
            player = self.players.get(guild)
            if player is None:
                if len(self.players) >= self.max_guilds:
                    return Outcome(False, "Бот уже играет на другом сервере — "
                                          "одновременных каналов не больше "
                                          f"{self.max_guilds}.")
                try:
                    handle = await self.host.connect(guild, channel)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Музыка: вход в канал не удался: %s", exc)
                    return Outcome(False, "Не удалось войти в голосовой канал: "
                                          "проверьте права «Подключаться» и «Говорить».")
                player = Player(guild=guild, channel=channel, handle=handle)
                self.players[guild] = player
            elif player.channel != channel:
                return Outcome(False, "Бот играет в другом голосовом канале этого сервера.")

            room = self.max_queue - len(player.queue)
            if room <= 0:
                return Outcome(False, f"Очередь заполнена ({self.max_queue}).")
            accepted = tracks[:room]
            player.queue.extend(accepted)
            player.idle_since = 0.0
            if player.current is None:
                await self._start_next(player)
            position = len(player.queue)

        first = accepted[0]
        if len(accepted) > 1:
            text = f"Добавлено треков: {len(accepted)} (первый: {first.label})."
        elif player.current is first:
            text = f"▶️ Играет: {first.label} [{format_duration(first.duration)}]"
        else:
            text = f"➕ В очереди №{position}: {first.label} [{format_duration(first.duration)}]"
        return Outcome(True, text)

    # --- проигрывание -----------------------------------------------

    async def _start_next(self, player: Player) -> None:
        """Запускает следующий трек. Вызывать под блокировкой."""
        while player.queue:
            track = player.queue.pop(0)
            try:
                if not track.stream:
                    info = await self.extractor(track.page, playlist=False,
                                                proxy=self.proxy, cookies=self.cookies())
                    fresh = tracks_from(info, track.requester, track.page)
                    if not fresh or not fresh[0].stream:
                        raise RuntimeError("у ссылки нет аудиопотока")
                    stream = fresh[0]
                    track.stream, track.headers = stream.stream, stream.headers
                    track.title = track.title or stream.title
                    track.duration = track.duration or stream.duration
                if self.guard is not None and not await self.guard(track.stream):
                    raise RuntimeError("поток ведёт во внутреннюю сеть")
                player.current, player.paused = track, False
                await self.host.play(player.handle, track,
                                     lambda error, g=player.guild: self._ended(g, error))
                return
            except Exception as exc:  # noqa: BLE001
                # Негодный трек пропускаем и пробуем следующий: из-за одной
                # битой ссылки очередь вставать не должна.
                log.info("Музыка: трек %s не заиграл: %s", track.label, exc)
                player.current = None
        player.current = None
        player.idle_since = self.clock()

    def _ended(self, guild: str, error: BaseException | None) -> None:
        """Вызывается из потока звука: возвращаемся в цикл событий."""
        if error:
            log.info("Музыка: трек закончился с ошибкой: %s", error)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._advance(guild), loop)

    async def _advance(self, guild: str) -> None:
        async with self._lock:
            player = self.players.get(guild)
            if player is None:
                return
            player.current = None
            await self._start_next(player)

    # --- управление -------------------------------------------------

    def _player(self, guild: str) -> Player | None:
        return self.players.get(guild)

    async def skip(self, guild: str) -> Outcome:
        async with self._lock:
            player = self._player(guild)
            if player is None or player.current is None:
                return Outcome(False, "Сейчас ничего не играет.")
            title = player.current.label
            # stop() вызовет обратный вызов, и очередь пойдёт дальше сама.
            self.host.stop(player.handle)
        return Outcome(True, f"⏭ Пропущено: {title}")

    async def stop(self, guild: str) -> Outcome:
        async with self._lock:
            player = self.players.pop(guild, None)
            if player is None:
                return Outcome(False, "Бот не в голосовом канале.")
            player.queue.clear()
            player.current = None
            self.host.stop(player.handle)
            await self.host.disconnect(player.handle)
        return Outcome(True, "⏹ Остановлено, очередь очищена.")

    async def pause(self, guild: str) -> Outcome:
        async with self._lock:
            player = self._player(guild)
            if player is None or player.current is None or player.paused:
                return Outcome(False, "Нечего ставить на паузу.")
            self.host.pause(player.handle)
            player.paused = True
        return Outcome(True, "⏸ Пауза.")

    async def resume(self, guild: str) -> Outcome:
        async with self._lock:
            player = self._player(guild)
            if player is None or not player.paused:
                return Outcome(False, "Пауза не включена.")
            self.host.resume(player.handle)
            player.paused = False
        return Outcome(True, "▶️ Продолжаю.")

    def queue_text(self, guild: str) -> str:
        player = self._player(guild)
        if player is None or (player.current is None and not player.queue):
            return "Очередь пуста."
        lines = []
        if player.current is not None:
            mark = "⏸" if player.paused else "▶️"
            lines.append(f"{mark} {player.current.label} [{format_duration(player.current.duration)}]")
        for number, track in enumerate(player.queue[:10], 1):
            lines.append(f"{number}. {track.label} [{format_duration(track.duration)}]")
        if len(player.queue) > 10:
            lines.append(f"… и ещё {len(player.queue) - 10}")
        return "\n".join(lines)

    # --- уход из канала ---------------------------------------------

    async def sweep(self) -> list[str]:
        """Выходит из каналов, где тихо дольше положенного. Возвращает серверы."""
        left = []
        async with self._lock:
            now = self.clock()
            for guild, player in list(self.players.items()):
                playing = player.current is not None
                if playing or player.queue:
                    player.idle_since = 0.0
                    continue
                if not player.idle_since:
                    player.idle_since = now
                    continue
                if now - player.idle_since >= IDLE_LEAVE:
                    self.players.pop(guild, None)
                    try:
                        await self.host.disconnect(player.handle)
                    except Exception:  # noqa: BLE001
                        log.debug("Музыка: выход из канала не удался", exc_info=True)
                    left.append(guild)
        return left


def _short(exc: BaseException) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip().splitlines()
    first = text[0] if text else type(exc).__name__
    first = re.sub(r"^ERROR:\s*", "", first)
    return first[:200]


# --------------------------------------------------------------------------
#  Настоящий голос: discord.py
# --------------------------------------------------------------------------

class DiscordPyHost(VoiceHost):
    """Голосовое соединение на `discord.py` (с поддержкой DAVE через `davey`).

    Отдельный `discord.Client` с минимальными намерениями: серверы и
    голосовые состояния. Слеш-команды он не обслуживает — этим занят адаптер.
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self.client: Any = None
        self.ready = asyncio.Event()

    async def start(self) -> None:
        import discord

        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_ready() -> None:
            log.info("Discord, голос: готов (%d серверов)", len(self.client.guilds))
            self.ready.set()

        await self.client.start(self.token)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def connect(self, guild: str, channel: str) -> Any:
        await asyncio.wait_for(self.ready.wait(), 30)
        target = self.client.get_channel(int(channel))
        if target is None:
            target = await self.client.fetch_channel(int(channel))
        voice = target.guild.voice_client
        if voice is not None and voice.channel.id != target.id:
            await voice.move_to(target)
        elif voice is None:
            voice = await target.connect(timeout=30, self_deaf=True)
        return voice

    async def play(self, handle: Any, track: Track,
                   after: Callable[[BaseException | None], None]) -> None:
        import discord

        source = await self.open_source(discord, track)
        if handle.is_playing() or handle.is_paused():
            handle.stop()
        handle.play(source, after=after)

    @staticmethod
    async def open_source(discord: Any, track: Track) -> Any:
        """Звук трека в Opus. Источник уже Opus (webm с YouTube) — копируем без
        перекодирования, это решает, потянет ли голос одноплатник.

        `from_probe` не годится: битрейт для перекодирования он берёт у
        источника, а у lossless-файла (wav, flac) это 700–1400 кбит/с —
        libopus отказывается открываться при более чем 512, и трек молча
        не играл (поймано `tools/discord_music_check.py` на wav). Поэтому
        пробуем сами и ограничиваем битрейт.
        """
        codec: str | None = None
        bitrate: int | None = None
        try:
            codec, bitrate = await discord.FFmpegOpusAudio.probe(
                track.stream, method="fallback")
        except Exception:  # noqa: BLE001
            log.debug("Музыка: проба источника не удалась", exc_info=True)
        kbps = min(max(int(bitrate or 128), 64), 256)
        return discord.FFmpegOpusAudio(
            track.stream, bitrate=kbps, codec=codec,
            before_options=ffmpeg_before_options(track), options="-vn")

    def stop(self, handle: Any) -> None:
        handle.stop()

    def pause(self, handle: Any) -> None:
        handle.pause()

    def resume(self, handle: Any) -> None:
        handle.resume()

    async def disconnect(self, handle: Any) -> None:
        await handle.disconnect(force=True)

    def channel_of(self, handle: Any) -> str:
        channel = getattr(handle, "channel", None)
        return str(getattr(channel, "id", "") or "")
