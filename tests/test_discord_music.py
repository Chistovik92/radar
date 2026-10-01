#!/usr/bin/env python3
"""Музыка в голосовом канале Discord (с 5.9.7).

Голос и звук здесь не проверяются — только то, что можно проверить без
Discord: разбор просьб, очередь, лимиты, пропуск битого трека, права, защита
от внутренних адресов и параметры ffmpeg.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import discordmusic as dm, features, secrets  # noqa: E402
from radar.platforms import discordbot  # noqa: E402
from radar.platforms.base import EventKind  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Parsing(unittest.TestCase):
    def test_requests(self):
        self.assertEqual(dm.clean_request("https://youtu.be/x extra words"),
                         ("link", "https://youtu.be/x"))
        self.assertEqual(dm.clean_request("  queen bohemian rhapsody "),
                         ("search", "queen bohemian rhapsody"))
        self.assertEqual(dm.clean_request(""), ("", ""))
        self.assertEqual(dm.clean_request("file:///etc/passwd"), ("", ""))
        self.assertEqual(dm.clean_request("ftp://x/y.mp3"), ("", ""))
        self.assertEqual(dm.clean_request("https://x/" + "a" * 600), ("", ""))

    def test_protected_services(self):
        for url in ("https://open.spotify.com/track/1", "https://music.apple.com/a",
                    "https://www.deezer.com/track/1", "https://tidal.com/x"):
            self.assertTrue(dm.protected_service(url), url)
        for url in ("https://youtu.be/x", "https://soundcloud.com/a/b",
                    "https://notspotify.com/x"):
            self.assertFalse(dm.protected_service(url), url)

    def test_playlist_hint(self):
        for url in ("https://www.youtube.com/playlist?list=PL1",
                    "https://soundcloud.com/a/sets/mix",
                    "https://x.bandcamp.com/album/one"):
            self.assertTrue(dm.wants_playlist(url), url)
        # Ролик внутри списка — один трек, как просили.
        self.assertFalse(dm.wants_playlist("https://www.youtube.com/watch?v=abc&list=PL1"))
        self.assertFalse(dm.wants_playlist("https://youtu.be/abc"))

    def test_duration_format(self):
        self.assertEqual(dm.format_duration(0), "—")
        self.assertEqual(dm.format_duration(65), "1:05")
        self.assertEqual(dm.format_duration(3725), "1:02:05")

    def test_tracks_from_single_and_playlist(self):
        single = dm.tracks_from({"title": "T", "duration": 10, "url": "https://cdn/x",
                                 "webpage_url": "https://p", "http_headers": {"User-Agent": "u"}},
                                "5", "https://p")
        self.assertEqual((single[0].title, single[0].stream, single[0].requester),
                         ("T", "https://cdn/x", "5"))
        flat = dm.tracks_from({"entries": [
            {"title": "A", "url": "https://a", "duration": 1}, None, {"title": "no url"},
            {"title": "B", "webpage_url": "https://b"}]}, "5", "x")
        self.assertEqual([t.page for t in flat], ["https://a", "https://b"])
        self.assertTrue(all(not t.stream for t in flat))       # поток — при проигрывании

    def test_playlist_is_capped(self):
        entries = [{"title": str(n), "url": f"https://p/{n}"} for n in range(100)]
        self.assertEqual(len(dm.tracks_from({"entries": entries}, "1", "x")), dm.PLAYLIST_LIMIT)

    def test_ffmpeg_options_are_shell_safe(self):
        track = dm.Track(page="p", stream="s", headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux)", "Referer": "https://r/",
            "X-Evil": "a b", "Cookie": "a=1\r\nInjected: 1"})
        before = shlex.split(dm.ffmpeg_before_options(track))
        self.assertIn("-reconnect", before)
        headers = before[before.index("-headers") + 1]
        self.assertIn("User-Agent: Mozilla/5.0 (X11; Linux)\r\n", headers)
        self.assertNotIn("X-Evil", headers)                    # только известные заголовки
        self.assertNotIn("Injected", headers)                  # перевод строки в значении
        self.assertEqual(shlex.split(dm.ffmpeg_before_options(dm.Track(page="p")))[0],
                         "-reconnect")


class FakeHost(dm.VoiceHost):
    def __init__(self, fail_connect=False, fail_streams=()):
        self.fail_connect, self.fail_streams = fail_connect, set(fail_streams)
        self.connected, self.played, self.stopped = [], [], 0
        self.disconnected, self.after = 0, None
        self.paused = False

    async def connect(self, guild, channel):
        if self.fail_connect:
            raise RuntimeError("no permission")
        self.connected.append((guild, channel))
        return object()

    async def play(self, handle, track, after):
        if track.stream in self.fail_streams:
            raise RuntimeError("ffmpeg failed")
        self.played.append(track.label)
        self.after = after

    def stop(self, handle):
        self.stopped += 1

    def pause(self, handle):
        self.paused = True

    def resume(self, handle):
        self.paused = False

    async def disconnect(self, handle):
        self.disconnected += 1


def info(title, stream="https://cdn/ok", duration=100):
    return {"title": title, "url": stream, "duration": duration,
            "webpage_url": f"https://page/{title}"}


class Queue(unittest.TestCase):
    def manager(self, host=None, infos=None, **kw):
        host = host or FakeHost()
        infos = infos or {}
        self.calls = []

        async def extractor(target, **options):
            self.calls.append((target, options))
            found = infos.get(target)
            if isinstance(found, Exception):
                raise found
            return found if found is not None else info(target)

        async def guard(url):
            return "internal" not in url

        return dm.Manager(host, extractor=extractor, guard=guard, **kw), host

    def test_first_track_plays_and_second_queues(self):
        manager, host = self.manager()

        async def go():
            first = await manager.add("g", "c", "u", "https://a")
            second = await manager.add("g", "c", "u", "https://b")
            return first, second

        first, second = run(go())
        self.assertTrue(first.ok and "Играет" in first.text)
        self.assertTrue(second.ok and "№1" in second.text)
        self.assertEqual(host.connected, [("g", "c")])        # вошли один раз
        self.assertEqual(host.played, ["https://a"])

    def test_finished_track_advances_queue(self):
        manager, host = self.manager()

        async def go():
            await manager.add("g", "c", "u", "https://a")
            await manager.add("g", "c", "u", "https://b")
            host.after(None)               # звук закончился в потоке плеера
            await asyncio.sleep(0.05)

        run(go())
        self.assertEqual(len(host.played), 2)

    def test_broken_track_is_skipped_not_fatal(self):
        host = FakeHost(fail_streams=["https://bad"])
        manager, host = self.manager(host, infos={
            "https://a": info("A", "https://bad"), "https://b": info("B", "https://good")})

        async def go():
            return await manager.add("g", "c", "u", "https://a"), await manager.add("g", "c", "u", "https://b")

        run(go())
        self.assertEqual(host.played, ["B"])

    def test_playlist_entries_resolve_lazily_at_play_time(self):
        playlist = {"entries": [{"title": "One", "url": "https://p/1"},
                                {"title": "Two", "url": "https://p/2"}]}
        manager, host = self.manager(infos={
            "https://x.com/playlist?list=1": playlist,
            "https://p/1": info("One", "https://cdn/1"), "https://p/2": info("Two", "https://cdn/2")})
        outcome = run(manager.add("g", "c", "u", "https://x.com/playlist?list=1"))
        self.assertIn("Добавлено треков: 2", outcome.text)
        self.assertEqual(host.played, ["One"])
        resolved = [target for target, _ in self.calls]
        self.assertEqual(resolved, ["https://x.com/playlist?list=1", "https://p/1"])  # второй — потом

    def test_search_uses_ytsearch_and_takes_first_result(self):
        search = {"_type": "playlist", "entries": [info("First hit"), info("Second hit")]}
        manager, host = self.manager(infos={"ytsearch1:queen": search})
        outcome = run(manager.add("g", "c", "u", "queen"))
        self.assertTrue(outcome.ok)
        self.assertEqual(host.played, ["First hit"])

    def test_spotify_explained(self):
        manager, host = self.manager()
        outcome = run(manager.add("g", "c", "u", "https://open.spotify.com/track/1"))
        self.assertFalse(outcome.ok)
        self.assertIn("Spotify", outcome.text)
        self.assertEqual(self.calls, [])
        self.assertEqual(host.connected, [])

    def test_internal_addresses_refused_before_any_request(self):
        manager, host = self.manager()
        outcome = run(manager.add("g", "c", "u", "https://internal.local/a.mp3"))
        self.assertFalse(outcome.ok)
        self.assertEqual(self.calls, [])

    def test_internal_stream_refused_at_play_time(self):
        manager, host = self.manager(infos={"https://ok": info("X", "https://internal/stream")})
        run(manager.add("g", "c", "u", "https://ok"))
        self.assertEqual(host.played, [])

    def test_too_long_track(self):
        manager, host = self.manager(infos={"https://a": info("A", duration=99999)},
                                     max_minutes=10)
        outcome = run(manager.add("g", "c", "u", "https://a"))
        self.assertFalse(outcome.ok)
        self.assertEqual(host.connected, [])

    def test_queue_limit(self):
        manager, host = self.manager(max_queue=2)

        async def go():
            return [await manager.add("g", "c", "u", f"https://t{n}") for n in range(4)]

        outcomes = run(go())
        self.assertEqual([o.ok for o in outcomes], [True, True, True, False])
        self.assertIn("заполнена", outcomes[-1].text)

    def test_guild_limit(self):
        manager, host = self.manager(max_guilds=1)

        async def go():
            return await manager.add("g1", "c", "u", "https://a"), await manager.add("g2", "c", "u", "https://b")

        first, second = run(go())
        self.assertTrue(first.ok)
        self.assertFalse(second.ok)
        self.assertEqual(host.connected, [("g1", "c")])

    def test_other_voice_channel_refused(self):
        manager, host = self.manager()

        async def go():
            await manager.add("g", "c1", "u", "https://a")
            return await manager.add("g", "c2", "u", "https://b")

        self.assertIn("другом голосовом", run(go()).text)

    def test_connect_failure_leaves_no_ghost_player(self):
        manager, host = self.manager(FakeHost(fail_connect=True))
        outcome = run(manager.add("g", "c", "u", "https://a"))
        self.assertFalse(outcome.ok)
        self.assertIn("права", outcome.text)
        self.assertEqual(manager.players, {})

    def test_extractor_error_is_reported_cleanly(self):
        manager, host = self.manager(infos={"https://a": RuntimeError(
            "\x1b[0;31mERROR:\x1b[0m [youtube] x: Video unavailable\nsecond line")})
        outcome = run(manager.add("g", "c", "u", "https://a"))
        self.assertFalse(outcome.ok)
        self.assertIn("Video unavailable", outcome.text)
        self.assertNotIn("\x1b", outcome.text)
        self.assertNotIn("second line", outcome.text)

    def test_controls(self):
        manager, host = self.manager()

        async def go():
            self.assertFalse((await manager.skip("g")).ok)         # ничего не играет
            await manager.add("g", "c", "u", "https://a")
            await manager.add("g", "c", "u", "https://b")
            pause = await manager.pause("g")
            again = await manager.pause("g")
            resume = await manager.resume("g")
            skip = await manager.skip("g")
            queue = manager.queue_text("g")
            stop = await manager.stop("g")
            return pause, again, resume, skip, queue, stop

        pause, again, resume, skip, queue, stop = run(go())
        self.assertTrue(pause.ok and not again.ok and resume.ok and skip.ok and stop.ok)
        self.assertIn("1.", queue)
        self.assertEqual(host.disconnected, 1)
        self.assertEqual(manager.players, {})
        self.assertEqual(manager.queue_text("g"), "Очередь пуста.")

    def test_idle_player_leaves_after_timeout(self):
        clock = {"t": 1000.0}
        host = FakeHost()
        manager = dm.Manager(host, clock=lambda: clock["t"], guard=None,
                             extractor=lambda target, **kw: _coro(info(target)))

        async def go():
            await manager.add("g", "c", "u", "https://a")
            host.after(None)
            await asyncio.sleep(0.05)               # трек закончился, очередь пуста
            await manager.sweep()                   # засекли тишину
            clock["t"] += dm.IDLE_LEAVE - 1
            early = await manager.sweep()
            clock["t"] += 2
            late = await manager.sweep()
            return early, late

        early, late = run(go())
        self.assertEqual((early, late), ([], ["g"]))
        self.assertEqual(host.disconnected, 1)


async def _coro(value):
    return value


class Extraction(unittest.TestCase):
    def test_cascade_retries_with_default_clients(self):
        seen = []

        def runner(target, options):
            seen.append(options.get("extractor_args"))
            if len(seen) == 1:
                raise RuntimeError("Video unavailable")
            return {"title": "T", "url": "https://cdn"}

        data = run(dm.extract("https://youtu.be/x", run=runner))
        self.assertEqual(data["title"], "T")
        self.assertIsNotNone(seen[0])                         # сначала клиенты без cookies
        self.assertIsNone(seen[1])                            # потом умолчания yt-dlp

    def test_non_retryable_error_stops(self):
        calls = []

        def runner(target, options):
            calls.append(1)
            raise RuntimeError("HTTP Error 404")

        with self.assertRaises(RuntimeError):
            run(dm.extract("https://x/a.mp3", run=runner))
        self.assertEqual(len(calls), 1)

    def test_options_ask_for_audio_without_download(self):
        options = dm._audio_options("", "", None, False)
        self.assertEqual(options["format"], "bestaudio/best")
        self.assertTrue(options["noplaylist"])
        self.assertTrue(options["skip_download"])
        flat = dm._audio_options("socks5://p", "/c.txt", None, True)
        self.assertEqual(flat["extract_flat"], "in_playlist")
        self.assertEqual(flat["playlistend"], dm.PLAYLIST_LIMIT)
        self.assertEqual((flat["proxy"], flat["cookiefile"]), ("socks5://p", "/c.txt"))


# --------------------------------------------------------------------------
#  Команды в Discord
# --------------------------------------------------------------------------

class FakeTransport:
    def __init__(self, voice="900"):
        self.voice = voice
        self.responses, self.edits = [], []

    async def respond(self, event, message, *, update=False, ephemeral=False):
        self.responses.append((message.text, ephemeral))

    async def edit_original(self, event, message):
        self.edits.append(message.text)

    async def voice_channel_of(self, guild, user):
        return self.voice


class FakeManager:
    def __init__(self):
        self.added, self.calls = [], []

    async def add(self, guild, channel, user, query):
        self.added.append((guild, channel, user, query))
        return dm.Outcome(True, "▶️ Играет: <b>X</b>")

    async def skip(self, guild):
        self.calls.append("skip")
        return dm.Outcome(True, "⏭")

    stop = pause = resume = skip

    def queue_text(self, guild):
        return "очередь"


def event(command, args="", roles=(), perms=0, guild="1"):
    from radar.identity import make
    from radar.platforms.base import InboundEvent

    raw = {"id": "i", "token": "t", "member": {"roles": list(roles), "permissions": str(perms)}}
    if guild:
        raw["guild_id"] = guild
    return InboundEvent(platform="discord", identity=make("discord", "42"), chat_id="9",
                        kind=EventKind.COMMAND, command=command, args=args, text=f"/{command} {args}",
                        raw=raw)


class Commands(unittest.TestCase):
    def setUp(self):
        self.was = discordbot.MUSIC
        discordbot.MUSIC = FakeManager()
        self.values = {"DISCORD_DJ_ROLE_ID": ""}
        self.patch = mock.patch.object(secrets, "get", lambda k: self.values.get(k, ""))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        discordbot.MUSIC = self.was

    def test_play_needs_a_voice_channel(self):
        t = FakeTransport(voice="")
        run(discordbot.music_command(event("play", "https://a"), t))
        self.assertIn("голосовой канал", t.responses[-1][0])
        self.assertEqual(discordbot.MUSIC.added, [])

    def test_play_acknowledges_then_edits(self):
        t = FakeTransport()
        run(discordbot.music_command(event("play", "https://a"), t))
        self.assertEqual(t.responses[0][0], "🔎 Ищу…")                  # первым — ответ Discord
        self.assertEqual(discordbot.MUSIC.added, [("1", "900", "42", "https://a")])
        self.assertIn("&lt;b&gt;X&lt;/b&gt;", t.edits[-1])               # чужой текст экранируется

    def test_dj_role_restricts(self):
        self.values["DISCORD_DJ_ROLE_ID"] = "55"
        t = FakeTransport()
        run(discordbot.music_command(event("skip"), t))
        self.assertIn("DJ", t.responses[-1][0])
        run(discordbot.music_command(event("skip", roles=["55"]), t))
        run(discordbot.music_command(event("skip", perms=0x20), t))      # управляющий — всегда
        self.assertEqual(discordbot.MUSIC.calls, ["skip", "skip"])

    def test_only_on_servers_and_when_enabled(self):
        t = FakeTransport()
        run(discordbot.music_command(event("play", "x", guild=""), t))
        self.assertIn("только на сервере", t.responses[-1][0])
        discordbot.MUSIC = None
        run(discordbot.music_command(event("play", "x"), t))
        self.assertIn("выключена", t.responses[-1][0])

    def test_commands_are_registered_and_routed(self):
        names = [item[0] for item in discordbot.MUSIC_COMMANDS]
        self.assertEqual(names, ["play", "skip", "pause", "resume", "stop", "queue"])
        self.assertEqual(discordbot.MUSIC_COMMANDS[0][2][0][2], True)    # запрос обязателен
        # Имена не пересекаются с прежними командами.
        self.assertFalse(set(names) & {item[0] for item in discordbot.COMMANDS})

    def test_flag_is_off_by_default(self):
        flag = features.resolve("discord_music")
        self.assertIsNotNone(flag)
        self.assertFalse(flag.default)
        self.assertFalse(discordbot.music_enabled())


class Transport(unittest.TestCase):
    def test_voice_channel_and_edit_original(self):
        from radar.platforms import discord
        from radar.platforms.base import OutboundMessage

        transport = discord.DiscordTransport("t")
        transport.application_id = "app"
        sent = []

        async def request(method, path, body=None, **kw):
            sent.append((method, path, body))
            return {"channel_id": "777"} if "voice-states" in path else {}

        transport.request = request
        self.assertEqual(run(transport.voice_channel_of("g", "u")), "777")
        ev = event("play", "x")
        run(transport.edit_original(ev, OutboundMessage(text="готово")))
        method, path, body = sent[-1]
        self.assertEqual((method, path), ("PATCH", "/webhooks/app/t/messages/@original"))
        self.assertEqual(body["content"], "готово")
        self.assertEqual(body["allowed_mentions"], {"parse": []})

        async def missing(method, path, body=None, **kw):
            return None

        transport.request = missing
        self.assertEqual(run(transport.voice_channel_of("g", "u")), "")


class Packaging(unittest.TestCase):
    def test_voice_requirements_are_optional_in_the_image(self):
        def read(name):
            with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                return handle.read()

        text, voice, main = read("Dockerfile"), read("requirements-voice.txt"), read("requirements.txt")
        self.assertIn("discord.py[voice]", voice)
        self.assertNotIn("discord.py", main)                  # основной образ не зависит от голоса
        self.assertIn("requirements-voice.txt \\\n || echo", text)   # сбой установки не роняет сборку


if __name__ == "__main__":
    unittest.main(verbosity=2)
