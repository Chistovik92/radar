"""Сжатие ролика под предел отправки.

Последнее средство из раздела 4.7.9 дорожной карты, и относиться к нему
надо соответственно. Разрезание на части было отвергнуто раньше: человек
не должен собирать видео обратно сам.

**Чего это стоит на одноплатнике.** RK3318 — четыре Cortex-A53. Программное
кодирование x264 идёт на нём 5–15 кадров в секунду, то есть десятиминутный
ролик 720p сжимается от двадцати минут до часа. Тот самый процессор в это
время должен разбирать сообщения об угрозах. Поэтому:

* сжатие включается флагом и запускается только по явной кнопке;
* ffmpeg идёт с `nice` и ограниченным числом потоков — оповещения важнее
  ролика, и при нехватке процессора страдать должен ролик;
* есть жёсткий таймаут: зависшее кодирование не должно занимать машину
  до перезагрузки;
* время называется заранее. «Ждите» без числа — это не предупреждение.

**Предел, который нельзя обойти арифметикой.** Битрейт определяется
длительностью: 50 МБ на час видео — это 110 кбит/с, а столько не хватает
ни на какое разрешение. Поэтому длинные ролики отвергаются с объяснением,
а не сжимаются в нечитаемую кашу. Отдать мыло вместо видео — обмануть
ожидание, а не выполнить просьбу.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("radar.transcode")

# Запас под контейнер и погрешность кодировщика: ffmpeg держит средний
# битрейт, но не попадает в целевой размер до байта.
SAFETY = 0.92
# Звук. 96 кбит/с — разборчивая речь; ниже опускаемся только когда
# на видео иначе не остаётся ничего.
AUDIO_KBPS = 96
AUDIO_KBPS_LOW = 64
# Порог, ниже которого на звук уходит слишком большая доля.
LOW_AUDIO_BUDGET_KBPS = 400

# Разрешение по достижимому битрейту. Ниже нижней границы сжимать
# бессмысленно: получится не видео, а набор квадратов.
LADDER = (
    (1500, 720),
    (800, 480),
    (400, 360),
    (200, 240),
)
MIN_VIDEO_KBPS = LADDER[-1][0]

# Скорость кодирования на одном ядре A53, кадров в секунду, по высоте
# кадра. Числа грубые и намеренно пессимистичные: обещать сорок минут
# и уложиться в двадцать лучше, чем наоборот.
FPS_BY_HEIGHT = ((240, 45.0), (360, 28.0), (480, 18.0), (720, 9.0), (1080, 4.0))
ASSUMED_FPS = 30          # исходная частота кадров, когда её не сообщили
THREADS = 2               # из четырёх ядер: два оставляем циклу оповещений


@dataclass(frozen=True)
class Plan:
    """Что и с какими параметрами кодировать."""

    height: int              # целевая высота кадра
    video_kbps: int
    audio_kbps: int
    target_mb: float
    duration_s: int

    @property
    def total_kbps(self) -> int:
        return self.video_kbps + self.audio_kbps


def budget_kbps(target_mb: float, duration_s: int) -> int:
    """Сколько килобит в секунду помещается в целевой размер."""
    if duration_s <= 0:
        return 0
    bits = target_mb * SAFETY * 1024 * 1024 * 8
    return max(0, int(bits / duration_s / 1000))


def plan(duration_s: int, target_mb: float, source_height: int = 0) -> Plan | None:
    """Подбирает параметры или возвращает None, если смысла нет.

    None означает «сжимать нечего смысла», а не «ошибка»: битрейта
    не хватит даже на 240p. Такой ролик надо не сжимать, а сказать
    человеку правду о его длительности.
    """
    if duration_s <= 0 or target_mb <= 0:
        return None

    total = budget_kbps(target_mb, duration_s)
    audio = AUDIO_KBPS if total >= LOW_AUDIO_BUDGET_KBPS else AUDIO_KBPS_LOW
    video = total - audio
    if video < MIN_VIDEO_KBPS:
        return None

    height = LADDER[-1][1]
    for need, candidate in LADDER:
        if video >= need:
            height = candidate
            break

    # Вверх не растягиваем: увеличение разрешения при сжатии — это
    # трата битрейта на выдуманные пиксели.
    if source_height:
        height = min(height, source_height)

    return Plan(
        height=height,
        video_kbps=video,
        audio_kbps=audio,
        target_mb=target_mb,
        duration_s=duration_s,
    )


def estimate_seconds(plan_: Plan, fps: float = ASSUMED_FPS,
                     cores: int = THREADS) -> int:
    """Сколько примерно займёт кодирование. Оценка пессимистичная."""
    per_core = FPS_BY_HEIGHT[-1][1]
    for height, speed in FPS_BY_HEIGHT:
        if plan_.height <= height:
            per_core = speed
            break

    rate = per_core * max(1, cores)
    frames = plan_.duration_s * max(1.0, fps)
    return max(5, int(frames / rate))


def human_time(seconds: int) -> str:
    """«около 25 минут» — человеку нужен порядок, а не точность."""
    if seconds < 90:
        return "меньше минуты"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"около {minutes} мин"
    hours = minutes / 60
    return f"около {hours:.1f} ч".replace(".0 ", " ")


def ffmpeg_args(source: str, target: str, plan_: Plan,
                nice: bool = True) -> list[str]:
    """Командная строка ffmpeg.

    Один проход, а не два: два дают лучшее качество при заданном размере,
    но удваивают время, а времени тут и так нет. `maxrate` с `bufsize`
    удерживают пики, чтобы файл не вылез за предел на сложных сценах.
    """
    command: list[str] = []
    if nice:
        # Оповещения важнее ролика: при нехватке процессора уступает он.
        command += ["nice", "-n", "19"]

    command += [
        "ffmpeg", "-y",
        "-i", source,
        "-c:v", "libx264",
        # На A53 всё, что медленнее veryfast, превращает минуты в часы.
        "-preset", "veryfast",
        "-threads", str(THREADS),
        "-b:v", f"{plan_.video_kbps}k",
        "-maxrate", f"{int(plan_.video_kbps * 1.5)}k",
        "-bufsize", f"{plan_.video_kbps * 2}k",
        "-vf", f"scale=-2:{plan_.height}",
        "-c:a", "aac",
        "-b:a", f"{plan_.audio_kbps}k",
        # h264 + aac + faststart — то, что Telegram проигрывает встроенным
        # проигрывателем без оговорок. Ради этого всё и затевалось.
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        "-loglevel", "error",
        target,
    ]
    return command


def parse_progress(line: str, duration_s: int) -> float | None:
    """Доля выполненного из строки `-progress`. None — строка не о том.

    ffmpeg с `-progress` печатает `out_time_us=12345678` — микросекунды
    обработанного материала.
    """
    text = (line or "").strip()
    if not text.startswith("out_time_us="):
        return None
    if duration_s <= 0:
        return None

    raw = text.split("=", 1)[1].strip()
    try:
        microseconds = int(raw)
    except ValueError:
        return None
    if microseconds < 0:
        return 0.0
    return min(1.0, microseconds / 1_000_000 / duration_s)


async def run(source: str, target: str, plan_: Plan, *,
              timeout_s: int, on_progress=None) -> tuple[bool, str]:
    """Запускает ffmpeg. Возвращает (получилось, объяснение отказа).

    Таймаут обязателен: зависшее кодирование не должно занимать
    одноплатник до перезагрузки. При срыве процесс убивается, а недоделок
    на диске не остаётся — их убирает вызывающая сторона.
    """
    import asyncio
    import os
    import shutil

    command = ffmpeg_args(source, target, plan_, nice=bool(shutil.which("nice")))

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return False, "ffmpeg недоступен — сжатие невозможно."
    except Exception as exc:  # noqa: BLE001
        log.warning("ffmpeg не запустился: %s", exc)
        return False, "Не удалось запустить сжатие."

    async def pump() -> None:
        assert process.stdout is not None
        while True:
            raw = await process.stdout.readline()
            if not raw:
                return
            share = parse_progress(raw.decode("utf-8", "replace"),
                                   plan_.duration_s)
            if share is not None and on_progress is not None:
                on_progress(share)

    reader = asyncio.create_task(pump())
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        reader.cancel()
        return False, (
            f"Сжатие не уложилось в {human_time(timeout_s)} и остановлено. "
            f"Выберите качество ниже."
        )
    finally:
        reader.cancel()

    if process.returncode != 0:
        stderr = b""
        if process.stderr is not None:
            try:
                stderr = await process.stderr.read()
            except Exception:  # noqa: BLE001
                pass
        log.warning("ffmpeg вернул %s: %s", process.returncode,
                    stderr.decode("utf-8", "replace")[:400])
        return False, "Сжатие не удалось — подробности в журнале."

    if not os.path.exists(target) or os.path.getsize(target) == 0:
        return False, "Сжатие завершилось, но файл не появился."

    return True, ""


def too_long_message(duration_s: int, target_mb: float) -> str:
    """Объяснение отказа: почему ролик не сжать под предел."""
    total = budget_kbps(target_mb, duration_s)
    minutes = max(1, round(duration_s / 60))
    return (
        f"Ролик идёт {minutes} мин, и чтобы уложить его в {target_mb:.0f} МБ, "
        f"пришлось бы сжать до {total} кбит/с. Этого не хватит даже "
        f"на 240p — вместо видео получится набор квадратов. "
        f"Скачайте часть ролика или поднимите собственный Bot API Server: "
        f"с ним предел станет 2 ГБ."
    )
