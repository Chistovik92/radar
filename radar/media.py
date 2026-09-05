"""Загрузка видео по ссылке: разбор форматов, прогресс, ограничения.

Модуль отделён от сети и от Telegram: здесь только чистая логика — выбор
качества, расчёт прогресса, проверка лимитов, имена файлов. Благодаря этому
поведение проверяется офлайн, а сам yt-dlp вызывается тонкой обёрткой.

Ограничения, которые нельзя обойти кодом
---------------------------------------
* Telegram Bot API отдаёт файлы не больше 50 МБ. Снять лимит до 2 ГБ можно
  только собственным Bot API Server — он поднимается отдельным контейнером
  и требует `api_id` и `api_hash` с my.telegram.org.
* Склейка видео и звука в качестве выше 720p требует ffmpeg. Без него
  доступны только форматы, где дорожки уже соединены.
* Одноплатнику это дорого: скачивание и склейка нагружают процессор и диск
  сильнее, чем весь остальной бот вместе взятый.
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
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger("radar.media")

# Лимит обычного Bot API. С собственным сервером поднимается до 2000 МБ.
CLOUD_LIMIT_MB = 50
LOCAL_LIMIT_MB = 1900
# Ниже этого размера вариант считается обрезком, а не роликом: у части
# площадок встречаются заготовки в десятки килобайт с той же высотой кадра.
# С 4.7.9 из двух вариантов берётся меньший, и без этого порога выбор
# скатывался бы именно к таким огрызкам.
MIN_SANE_MB = 0.3
# Запас сверх утроенного размера: размер известен приблизительно, а место
# на диске нужно не только видео — туда же пишется база.
DISK_HEADROOM_MB = 200
# Ниже этого свободного объёма не начинаем загрузку вообще, каким бы мелким
# ни был ролик. На одноплатнике переполнение диска ломает не видео,
# а весь бот: базе некуда писать, и оповещения прекращаются.
MIN_FREE_MB = 300

# Как часто разрешено править сообщение с прогрессом: Telegram считает
# частые правки флудом и отвечает 429.
PROGRESS_INTERVAL = 3.0

SUPPORTED_HINT = (
    "YouTube, VK Видео, RuTube, Одноклассники, Дзен, TikTok, X, Instagram"
)

_URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
_UNSAFE = re.compile(r"[^\w\-. ]+", re.U)


# Кодеки по убыванию эффективности сжатия: тот же кадр в av1 весит примерно
# вдвое меньше, чем в h264. Для потолка в 50 МБ это разница между 1080p
# и 480p, поэтому кодек важен не меньше высоты кадра.
#
# Но встроенный проигрыватель Telegram надёжно понимает только h264: av1
# и vp9 он на части устройств отдаёт файлом, а не видео. Поэтому эффективный
# кодек мы предпочитаем, а о возможной беде с проигрыванием предупреждаем —
# молча отдать нечитаемый файл хуже, чем отдать меньшее качество.
CODEC_RANK = ("av1", "vp9", "h265", "h264", "vp8", "")
# Проигрывается везде без оговорок.
CODEC_SAFE = {"h264", ""}


def codec_family(raw: str) -> str:
    """Приводит имя кодека из yt-dlp к семейству: av01.0.05M -> av1."""
    name = (raw or "").split(".")[0].strip().lower()
    if name in ("none", "null"):
        return ""
    if name.startswith("av01") or name == "av1":
        return "av1"
    if name.startswith("vp9") or name.startswith("vp09"):
        return "vp9"
    if name.startswith(("hev1", "hvc1", "h265", "hevc")):
        return "h265"
    if name.startswith(("avc1", "avc3", "h264")):
        return "h264"
    if name.startswith("vp8"):
        return "vp8"
    return name


@dataclass
class Format:
    """Один вариант качества."""

    label: str                 # «1080p», «Максимальное»
    height: int = 0            # 0 — качество не определено
    size_mb: float = 0.0       # 0 — размер неизвестен
    ext: str = "mp4"
    note: str = ""
    vcodec: str = ""           # семейство кодека: av1, vp9, h265, h264

    def selector_for(self, limit_mb: int = 0) -> str:
        """Строка выбора формата для yt-dlp.

        При заданном пределе первыми идут варианты, которые в него заведомо
        помещаются. Записи с неизвестным размером не отбрасываются: у части
        площадок он не приходит вовсе, и жёсткое условие оставило бы
        человека вообще без вариантов. Для этого используется `<?` —
        сравнение, которое пропускает формат, если поля нет.

        Хвост цепочки — прежние варианты без ограничения размера. Если под
        предел не попадает ничего, лучше скачать заведомо крупное и честно
        сказать об этом, чем ответить «форматы не найдены».
        """
        height = f"[height<={self.height}]" if self.height else ""

        chain: list[str] = []
        if limit_mb > 0:
            budget = max(1, limit_mb - audio_reserve_mb(limit_mb))
            chain.append(f"bestvideo{height}[filesize<?{budget}M]+bestaudio")
            chain.append(f"best{height}[filesize<?{limit_mb}M]")

        chain.append(f"bestvideo{height}+bestaudio")
        if height:
            chain.append(f"best{height}")
        chain.append("best")
        return "/".join(chain)

    @property
    def selector(self) -> str:
        """Совместимость: выбор без учёта предела размера."""
        return self.selector_for(0)

    @property
    def risky_codec(self) -> bool:
        """Может не проиграться встроенным проигрывателем Telegram."""
        return bool(self.vcodec) and self.vcodec not in CODEC_SAFE

    @property
    def title(self) -> str:
        parts = [self.label]
        if self.size_mb:
            parts.append(f"~{self.size_mb:.0f} МБ")
        if self.risky_codec:
            parts.append(self.vcodec)
        return " · ".join(parts)


def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def safe_filename(title: str, limit: int = 60) -> str:
    """Имя файла без символов, ломающих файловую систему и Telegram."""
    cleaned = _UNSAFE.sub(" ", title or "video").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:limit].strip() or "video")


def size_limit_mb(local_server: bool) -> int:
    return LOCAL_LIMIT_MB if local_server else CLOUD_LIMIT_MB


def free_space_mb(path: str) -> float:
    """Свободно мегабайт в каталоге. При любой неясности — бесконечность.

    Неизвестное место не повод отказывать в загрузке: если `statvfs`
    недоступен или каталога ещё нет, честнее пропустить проверку, чем
    запретить работу по догадке.
    """
    import shutil

    probe = path
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent

    try:
        return shutil.disk_usage(probe or ".").free / (1024 * 1024)
    except OSError:
        return float("inf")


def space_needed_mb(size_mb: float) -> float:
    """Сколько места нужно под загрузку ролика в `size_mb`.

    Втрое с небольшим, и это не перестраховка. yt-dlp качает видео и звук
    отдельными файлами, а затем склеивает их в третий — в пике на диске
    лежат все три сразу. Плюс запас: размер известен приблизительно.
    """
    return max(MIN_FREE_MB, size_mb * 3 + DISK_HEADROOM_MB)


def enough_space(size_mb: float, path: str) -> tuple[bool, str]:
    """Хватит ли места. Второе значение — объяснение при отказе.

    Отказ здесь важнее удобства: на одноплатнике переполнение диска ломает
    не загрузку видео, а весь бот — базе некуда писать, и оповещения
    прекращаются. Ролик подождёт, тревоги нет.
    """
    free = free_space_mb(path)
    if free == float("inf"):
        return True, ""

    need = space_needed_mb(size_mb)
    if free >= need:
        return True, ""

    return False, (
        f"На диске свободно {free:.0f} МБ, а под загрузку нужно около "
        f"{need:.0f} МБ: видео и звук качаются отдельно и склеиваются "
        f"в третий файл. Выберите качество ниже или освободите место."
    )


def audio_reserve_mb(limit_mb: int) -> int:
    """Сколько оставить под звук, подбирая видеопоток.

    yt-dlp качает видео и звук отдельными файлами и сверяет `max_filesize`
    с каждым по отдельности, а не с суммой. Поэтому под потолок нужно
    подбирать видео с запасом — иначе видео уложится ровно в предел,
    а после склейки со звуком его превысит.

    Доля, а не константа: при потолке 50 МБ запас в 5 МБ разумен, при 1900
    он был бы смешным. Сверху ограничен, чтобы на собственном Bot API
    Server не отрезать двести мегабайт впустую.
    """
    return max(3, min(20, round(limit_mb * 0.1)))


def _better(candidate: Format, current: Format) -> bool:
    """Какой из двух вариантов одной высоты брать.

    До 4.7.9 брался САМЫЙ БОЛЬШОЙ файл — для системы с потолком отправки
    это ровно наоборот. Теперь порядок такой:

    1. известный размер лучше неизвестного: «~48 МБ» позволяет решить,
       влезет ли, а пустое место не позволяет ничего;
    2. при известных размерах — меньший файл;
    3. при равных размерах — эффективнее кодек.

    Оговорка про подозрительно мелкие файлы: у части площадок попадаются
    обрезки в десятки килобайт с той же высотой кадра. Меньший размер
    сам по себе не повод их брать, поэтому такие отбрасываются.
    """
    if candidate.size_mb and candidate.size_mb < MIN_SANE_MB:
        return False
    if bool(candidate.size_mb) != bool(current.size_mb):
        return bool(candidate.size_mb)
    if candidate.size_mb and current.size_mb and candidate.size_mb != current.size_mb:
        return candidate.size_mb < current.size_mb

    ranks = {name: index for index, name in enumerate(CODEC_RANK)}
    return ranks.get(candidate.vcodec, 99) < ranks.get(current.vcodec, 99)


def parse_formats(info: dict[str, Any], limit: int = 6) -> list[Format]:
    """Собирает список качеств из ответа yt-dlp.

    Разные площадки отдают метаданные по-разному: у YouTube есть отдельные
    видео- и аудиопотоки с высотой кадра, у TikTok и Instagram высоты часто
    нет вовсе. Поэтому при отсутствии распознанных высот возвращается один
    вариант «максимальное доступное» — это лучше пустого списка.
    """
    best: dict[int, Format] = {}

    for item in info.get("formats") or []:
        if not isinstance(item, dict):
            continue
        height = item.get("height")
        if not isinstance(height, int) or height < 144:
            continue

        size = item.get("filesize") or item.get("filesize_approx") or 0
        size_mb = round(size / (1024 * 1024), 1) if isinstance(size, (int, float)) else 0.0

        candidate = Format(
            label=f"{height}p",
            height=height,
            size_mb=size_mb,
            ext=str(item.get("ext") or "mp4"),
            vcodec=codec_family(str(item.get("vcodec") or "")),
        )

        current = best.get(height)
        if current is None or _better(candidate, current):
            best[height] = candidate

    if not best:
        return [Format(label="Максимальное доступное", height=0)]

    ordered = sorted(best.values(), key=lambda item: item.height, reverse=True)
    return ordered[:limit]


def describe(info: dict[str, Any]) -> str:
    """Короткое описание ролика для сообщения с выбором качества."""
    from .textutils import esc

    title = str(info.get("title") or "Видео")
    uploader = str(info.get("uploader") or info.get("channel") or "")
    duration = info.get("duration")

    lines = [f"🎬 <b>{esc(title[:120])}</b>"]
    if uploader:
        lines.append(f"👤 {esc(uploader[:60])}")
    if isinstance(duration, (int, float)) and duration > 0:
        minutes, seconds = divmod(int(duration), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        lines.append(f"⏱ {stamp}")
    return "\n".join(lines)


def progress_bar(percent: float, length: int = 12) -> str:
    """Полоса прогресса. Символы ASCII — надёжнее в любой локали."""
    value = max(0.0, min(100.0, percent))
    filled = int(length * value / 100)
    return f"[{'#' * filled}{'.' * (length - filled)}] {value:.0f}%"


@dataclass
class Progress:
    """Состояние загрузки. Считает всё, кроме собственно скачивания."""

    total: int = 0
    done: int = 0
    speed: str = ""
    eta: str = ""
    stage: str = "download"        # download | upload | merge
    last_shown: float = field(default=0.0)

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, self.done / self.total * 100)

    def should_refresh(self, now: float | None = None) -> bool:
        """Пора ли обновлять сообщение — защита от флуд-контроля Telegram."""
        moment = now if now is not None else time.time()
        if moment - self.last_shown < PROGRESS_INTERVAL:
            return False
        self.last_shown = moment
        return True

    def render(self) -> str:
        titles = {
            "download": "📥 <b>Скачиваю на сервер</b>",
            "merge": "🔧 <b>Склеиваю видео и звук</b>",
            "upload": "📤 <b>Отправляю в Telegram</b>",
        }
        lines = [titles.get(self.stage, "⏳ <b>Обработка</b>"), "", progress_bar(self.percent)]

        if self.total:
            lines.append(
                f"📦 {self.done / (1024 * 1024):.0f} из {self.total / (1024 * 1024):.0f} МБ"
            )
        if self.speed:
            lines.append(f"🚀 {self.speed}")
        if self.eta:
            lines.append(f"⏱ осталось {self.eta}")
        return "\n".join(lines)


def read_hook(payload: dict[str, Any], progress: Progress) -> bool:
    """Переносит данные хука yt-dlp в состояние. True — пора обновить сообщение."""
    status = payload.get("status")

    if status == "downloading":
        progress.stage = "download"
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
        progress.total = int(total) if isinstance(total, (int, float)) else 0
        done = payload.get("downloaded_bytes") or 0
        progress.done = int(done) if isinstance(done, (int, float)) else 0
        progress.speed = str(payload.get("_speed_str") or "").strip()
        progress.eta = str(payload.get("_eta_str") or "").strip()
        return progress.should_refresh()

    if status == "finished":
        progress.stage = "merge"
        progress.done = progress.total
        return True

    return False


def too_big(size_bytes: int, local_server: bool) -> tuple[bool, str]:
    """Помещается ли файл в лимит отправки."""
    limit = size_limit_mb(local_server)
    size_mb = size_bytes / (1024 * 1024)
    if size_mb <= limit:
        return False, ""

    if local_server:
        return True, (
            f"Файл {size_mb:.0f} МБ превышает предел {limit} МБ даже для "
            "собственного сервера Bot API. Выберите качество ниже."
        )
    return True, (
        f"Файл {size_mb:.0f} МБ, а Telegram принимает от ботов не больше "
        f"{limit} МБ. Выберите качество ниже — или поднимите собственный "
        "Bot API Server, тогда предел станет 2 ГБ."
    )


def build_options(
    target: str,
    selector: str,
    *,
    proxy: str = "",
    cookies: str = "",
    limit_rate: str = "",
    limit_mb: int = 0,
) -> dict[str, Any]:
    """Параметры yt-dlp. Вынесены отдельно, чтобы их можно было проверить."""
    options: dict[str, Any] = {
        "format": selector,
        "outtmpl": target,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Плейлист по ссылке на ролик — частая причина «скачалось не то»
        "noplaylist": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    if limit_mb > 0:
        # Ограничитель на случай, когда размер заранее неизвестен: yt-dlp
        # прервёт загрузку, как только файл перерастёт предел. До 4.7.10
        # размер проверялся уже после полной загрузки — двухгигабайтный
        # ролик выкачивался целиком, чтобы затем получить отказ. На канале
        # одноплатника это десятки минут и весь трафик впустую.
        #
        # Это именно предохранитель, а не гарантия точного попадания:
        # предел сверяется с каждым файлом отдельно, а Telegram смотрит
        # на склеенный. Точная проверка остаётся после склейки.
        options["max_filesize"] = int(limit_mb * 1024 * 1024)
    if proxy:
        options["proxy"] = proxy
    if cookies:
        options["cookiefile"] = cookies
    if limit_rate:
        options["ratelimit"] = limit_rate
    return options


def probe_options(proxy: str = "", cookies: str = "") -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 20,
    }
    if proxy:
        options["proxy"] = proxy
    if cookies:
        options["cookiefile"] = cookies
    return options


# Ответы площадок, означающие «по ссылке не видео, а что-то другое».
# Это не сбой: пост в Instagram, твит с фотографией и сообщение сообщества
# YouTube — записи с картинками, и видео в них нет и не было. Проверено
# на живых ссылках: X отвечает «No video could be found in this tweet»,
# Instagram — «There is no video in this post», а запись сообщества
# YouTube разбирается как вкладка канала, которой не существует.
NO_VIDEO_MARKERS = (
    "no video could be found",
    "there is no video",
    "no video formats found",
    "does not have a",          # youtube:tab о записи сообщества
    "unsupported url",
)

# Ответы, означающие «нужен вход». Формулировки у площадок разные,
# и одной проверки на «sign in» мало: ВКонтакте пишет «signed-in»
# через дефис, и запрос молча уходил в общий отказ.
LOGIN_MARKERS = (
    "private", "login required", "sign in", "signed-in", "signed in",
    "log in", "account", "authoriz", "авториз",
)


def looks_like_no_video(error: BaseException | str) -> bool:
    """Значит ли ошибка, что по ссылке запись с картинками, а не видео."""
    text = str(error).lower()
    if any(marker in text for marker in LOGIN_MARKERS):
        # Закрытая запись — отдельный случай: там видео может и быть,
        # просто его не показывают. Картинку оттуда тоже не достать.
        return False
    return any(marker in text for marker in NO_VIDEO_MARKERS)


# Сколько держать забытое в рабочем каталоге. Шесть часов — заведомо
# больше самой долгой загрузки на медленном канале и заведомо меньше
# суток, за которые мусор успел бы съесть диск.
SWEEP_AFTER_HOURS = 6


def sweep(directory: str, older_than_hours: int = SWEEP_AFTER_HOURS) -> int:
    """Убирает из рабочего каталога то, что осталось от прерванных загрузок.

    Успешная отправка удаляет за собой сама, в `finally`. Но до `finally`
    доходит не всё: загрузка обрывается предохранителем размера, площадка
    отваливается по таймауту, контейнер перезапускают посреди работы —
    и yt-dlp оставляет `.part`, недосклеенные дорожки и сам файл. Ничем
    не убираемые, они копятся до тех пор, пока на диске не кончится место,
    а вместе с местом остановятся и оповещения.

    Возвращает число удалённых файлов.
    """
    import time as time_module

    if not directory or not os.path.isdir(directory):
        return 0

    edge = time_module.time() - older_than_hours * 3600
    removed = 0
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if not os.path.isfile(path) or os.path.getmtime(path) > edge:
                continue
            os.remove(path)
            removed += 1
        except OSError:
            # Файл могли удалить между listdir и remove, а могло не хватить
            # прав. Ни то ни другое не повод останавливать уборку.
            continue
    if removed:
        log.info("Убрано из рабочего каталога: %d файлов", removed)
    return removed


def friendly_error(error: BaseException | str) -> str:
    """Переводит типичные ошибки yt-dlp в понятное объяснение."""
    text = str(error).lower()

    # Порядок ветвей значим: «нужен вход» проверяется раньше «нет видео»,
    # иначе закрытая запись объяснялась бы отсутствием видео в ней.
    if any(marker in text for marker in LOGIN_MARKERS):
        return (
            "Запись закрыта настройками приватности или требует входа. "
            "Для таких ссылок нужен файл cookies: с 4.9.4.5 суперадминистратор "
            "просто присылает cookies.txt в чат (см. /cookies) — сервер "
            "и .env больше не трогаются руками."
        )
    # Незнакомая площадка — отдельный случай от записи с картинками:
    # картинки оттуда попробовать стоит, но объяснение нужно другое,
    # иначе человек будет искать несуществующие картинки в ссылке.
    if "unsupported url" in text:
        return f"Площадка не поддерживается. Работают: {SUPPORTED_HINT}."
    if looks_like_no_video(error):
        return (
            "По ссылке нет видео — похоже, это запись с картинками. "
            "Картинки из неё скачать не вышло: площадка не отдала их "
            "в метаданных страницы. Пришлите прямую ссылку на файл."
        )

    # Сработал предохранитель max_filesize: загрузка прервана на середине,
    # и это хорошая новость — трафик не потрачен целиком. Человеку важно
    # понять, что делать дальше, а не увидеть внутреннюю формулировку.
    if "max-filesize" in text or "larger than max" in text:
        return (
            "Файл оказался больше предела отправки — загрузка остановлена "
            "на середине, чтобы не тратить трафик впустую. Выберите "
            "качество ниже."
        )
    if "video unavailable" in text or "not available" in text:
        return "Видео недоступно — удалено или ограничено по региону."
    if "age" in text and "restrict" in text:
        return "Видео с возрастным ограничением: нужен файл cookies (/cookies)."
    if "timed out" in text or "timeout" in text:
        return "Площадка не ответила вовремя. Попробуйте ещё раз."
    if "http error 429" in text or "too many requests" in text:
        return "Площадка временно ограничила запросы. Подождите несколько минут."
    if "ffmpeg" in text:
        return (
            "Для склейки видео и звука нужен ffmpeg, а он недоступен. "
            "Выберите качество не выше 720p."
        )
    if "proxy" in text or "connection" in text or "resolve" in text:
        return "Не удалось подключиться к площадке. Проверьте сеть или прокси."
    return "Не удалось обработать ссылку."


def choose_default(formats: Iterable[Format], limit_mb: int) -> Format | None:
    """Качество по умолчанию: лучшее из помещающихся в лимит.

    При равной высоте предпочитается вариант, который точно проиграется
    встроенным проигрывателем. Смысл в том, что по умолчанию человек
    получает работающее видео; если ему нужен файл поменьше ценой риска,
    он выберет его сам — варианты видны в списке.
    """
    items = list(formats)
    known = [item for item in items if item.size_mb and item.size_mb <= limit_mb]
    if known:
        return max(known, key=lambda value: (value.height, not value.risky_codec))
    ordered = sorted(items, key=lambda value: value.height)
    return ordered[0] if ordered else None
