#!/usr/bin/env python3
"""Музыка Discord: звуковой тракт на настоящих yt-dlp, ffmpeg и discord.py (с 5.9.7).

Офлайн-тесты подменяют извлечение и голос и звука не слышат. Этот скрипт
гоняет настоящее: поднимает на 127.0.0.1 раздачу короткого звукового
файла и прогоняет его по всему тракту, кроме самого Discord:

    ссылка → yt-dlp (общий извлекатель) → Track → очередь Manager →
    DiscordPyHost.play → ffmpeg с параметрами из `ffmpeg_before_options` →
    Opus-кадры, читаемые так, как их читает голосовой клиент.

Вместо `VoiceClient` — заглушка, которая вычитывает пакеты. Проверяется,
что параметры ffmpeg разбираются настоящим ffmpeg, поток читается по HTTP
с заголовками, звук превращается в Opus, а по окончании очередь переходит
к следующему треку.

Нужны `yt-dlp`, `discord.py[voice]` и `ffmpeg` в PATH. Без них скрипт
сообщает об этом и завершается кодом 2 (в CI не запускается).

Что остаётся непроверенным: соединение с настоящим Discord — вход в канал,
шифрование DAVE, отправка пакетов. Для этого нужен живой сервер.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import http.server
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if shutil.which("ffmpeg") is None:
    print("Нужен ffmpeg в PATH.")
    sys.exit(2)
try:
    import discord  # noqa: F401
    import yt_dlp  # noqa: F401
except ImportError as exc:
    print(f"Нужны yt-dlp и discord.py[voice]: {exc}")
    sys.exit(2)

try:
    import dotenv  # noqa: F401
except ImportError:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from radar import discordmusic  # noqa: E402


class FakeVoiceClient:
    """Голосовой клиент без Discord: читает Opus-кадры, как это делает настоящий."""

    def __init__(self) -> None:
        self.packets = 0
        self.bytes = 0
        self.first_header = b""
        self.finished = threading.Event()
        self._playing = False

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return False

    def stop(self) -> None:
        self._playing = False

    def play(self, source, after=None) -> None:
        self._playing = True

        def pump() -> None:
            error = None
            try:
                while self._playing:
                    frame = source.read()
                    if not frame:
                        break
                    self.packets += 1
                    self.bytes += len(frame)
            except Exception as exc:  # noqa: BLE001
                error = exc
            finally:
                try:
                    source.cleanup()
                except Exception:  # noqa: BLE001
                    pass
                self._playing = False
                self.finished.set()
                if after:
                    after(error)

        threading.Thread(target=pump, daemon=True).start()


class Host(discordmusic.DiscordPyHost):
    """Настоящее `play` (ffmpeg → Opus), но без входа в Discord."""

    def __init__(self) -> None:
        super().__init__("token")
        self.voice = FakeVoiceClient()

    async def connect(self, guild: str, channel: str):
        return self.voice

    async def disconnect(self, handle) -> None:
        return None


class Handler(http.server.SimpleHTTPRequestHandler):
    seen_agents: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        Handler.seen_agents.append(self.headers.get("User-Agent", ""))
        super().do_GET()

    def log_message(self, *args) -> None:
        pass


async def main() -> int:
    work = Path(tempfile.mkdtemp())
    wav = work / "tone.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", str(wav)], check=True)

    handler = lambda *a, **k: Handler(*a, directory=str(work), **k)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/tone.wav"

    host = Host()
    # Защита от внутренних адресов здесь выключена: проверяется тракт, а не она
    # (её проверяют офлайн-тесты), и раздача идёт с 127.0.0.1.
    manager = discordmusic.Manager(host, guard=None)
    checks: list[tuple[str, bool, str]] = []
    try:
        first = await manager.add("g", "c", "42", url)
        second = await manager.add("g", "c", "42", url)
        for _ in range(300):
            if host.voice.finished.is_set() and manager.players["g"].current is None:
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)
    finally:
        server.shutdown()

    track_ok = first.ok and "Играет" in first.text and second.ok and "№1" in second.text
    checks.append(("yt-dlp открыл прямую ссылку, трек встал, второй — в очередь", track_ok,
                   f"{first.text!r} / {second.text!r}"))
    checks.append(("ffmpeg разобрал параметры и отдал Opus-кадры", host.voice.packets > 50,
                   f"кадров: {host.voice.packets}, байт: {host.voice.bytes}"))
    # Две секунды звука при кадрах по 20 мс — около ста на трек.
    checks.append(("по окончании первого очередь запустила второй (кадров на два трека)",
                   host.voice.packets > 150, f"кадров: {host.voice.packets}"))
    checks.append(("поток запрошен по HTTP", bool(Handler.seen_agents),
                   f"запросов: {len(Handler.seen_agents)}"))
    failed = [item for item in checks if not item[1]]

    print("Звуковой тракт музыки Discord (без соединения с Discord):\n")
    for title, ok, note in checks:
        print(f"  {'✅' if ok else '❌'} {title}: {note}")
    print("\nВход в канал, шифрование DAVE и отправка пакетов не проверялись — "
          "для этого нужен живой Discord.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
