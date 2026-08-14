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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger("radar.media")

# Лимит обычного Bot API. С собственным сервером поднимается до 2000 МБ.
CLOUD_LIMIT_MB = 50
LOCAL_LIMIT_MB = 1900

# Как часто разрешено править сообщение с прогрессом: Telegram считает
# частые правки флудом и отвечает 429.
PROGRESS_INTERVAL = 3.0

SUPPORTED_HINT = (
    "YouTube, VK Видео, RuTube, Одноклассники, Дзен, TikTok, X, Instagram"
)

_URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
_UNSAFE = re.compile(r"[^\w\-. ]+", re.U)


@dataclass
class Format:
    """Один вариант качества."""

    label: str                 # «1080p», «Максимальное»
    height: int = 0            # 0 — качество не определено
    size_mb: float = 0.0       # 0 — размер неизвестен
    ext: str = "mp4"
    note: str = ""

    @property
    def selector(self) -> str:
        """Строка выбора формата для yt-dlp."""
        if self.height:
            return (
                f"bestvideo[height<={self.height}]+bestaudio/"
                f"best[height<={self.height}]/best"
            )
        return "bestvideo+bestaudio/best"

    @property
    def title(self) -> str:
        if self.size_mb:
            return f"{self.label} · ~{self.size_mb:.0f} МБ"
        return self.label


def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def safe_filename(title: str, limit: int = 60) -> str:
    """Имя файла без символов, ломающих файловую систему и Telegram."""
    cleaned = _UNSAFE.sub(" ", title or "video").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:limit].strip() or "video")


def size_limit_mb(local_server: bool) -> int:
    return LOCAL_LIMIT_MB if local_server else CLOUD_LIMIT_MB


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

        current = best.get(height)
        if current is None or (size_mb and size_mb > current.size_mb):
            best[height] = Format(
                label=f"{height}p",
                height=height,
                size_mb=size_mb,
                ext=str(item.get("ext") or "mp4"),
            )

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


def friendly_error(error: BaseException | str) -> str:
    """Переводит типичные ошибки yt-dlp в понятное объяснение."""
    text = str(error).lower()

    if "unsupported url" in text:
        return f"Площадка не поддерживается. Работают: {SUPPORTED_HINT}."
    if "private" in text or "login required" in text or "sign in" in text:
        return (
            "Видео закрыто настройками приватности или требует входа. "
            "Для таких ссылок нужен файл cookies."
        )
    if "video unavailable" in text or "not available" in text:
        return "Видео недоступно — удалено или ограничено по региону."
    if "age" in text and "restrict" in text:
        return "Видео с возрастным ограничением: нужен файл cookies."
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
    """Качество по умолчанию: лучшее из помещающихся в лимит."""
    known = [item for item in formats if item.size_mb]
    for item in sorted(known, key=lambda value: value.height, reverse=True):
        if item.size_mb <= limit_mb:
            return item
    ordered = sorted(formats, key=lambda value: value.height)
    return ordered[0] if ordered else None
