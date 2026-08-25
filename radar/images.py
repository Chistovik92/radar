"""Скачивание картинок по ссылке.

Отдельно от видео намеренно: механика другая. Видео проходит через
yt-dlp, где есть выбор качества, склейка и сжатие; картинка — это один
запрос и один файл, и тащить её через тот же путь значило бы обвешать
простую задачу лишним.

Пределы Telegram, которые здесь определяют всё:

* **фото — 10 МБ.** Больше бот отправить фотографией не может;
* **документ — те же 50 МБ**, что и у видео (2 ГБ со своим Bot API
  Server).

Поэтому крупная картинка не отвергается, а уходит документом: она
откроется, просто без предпросмотра в ленте. Отказать было бы хуже —
человек просил файл, а не предпросмотр.

Отдельная осторожность с тем, что приходит по ссылке. Сервер может
объявить один размер, а прислать другой, поэтому:

* заявленный `Content-Length` проверяется до загрузки;
* фактический объём считается по ходу и обрывается при превышении —
  иначе ссылка на бесконечный поток забила бы диск одноплатника, а вместе
  с ним остановила бы оповещения.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, unquote

log = logging.getLogger("radar.images")

# Что считаем картинкой. Список закрытый: расширение — единственное,
# что известно до запроса, и гадать по нему широко не стоит.
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".avif")

# Предел Telegram на отправку фотографией. Крупнее уходит документом.
PHOTO_LIMIT_MB = 10
# Читаем кусками: так фактический размер виден по ходу, а не после.
CHUNK = 64 * 1024

_UNSAFE = re.compile(r"[^\w\-. ]+", re.U)


def looks_like_image(url: str) -> bool:
    """Похожа ли ссылка на прямую ссылку на картинку.

    Смотрим только на путь: параметры запроса часто содержат посторонние
    расширения (`?logo=x.png`), и учитывать их — верный способ принять
    за картинку целую страницу.
    """
    text = (url or "").strip()
    if not text.lower().startswith(("http://", "https://")):
        return False
    try:
        path = urlparse(text).path.lower()
    except ValueError:
        return False
    return path.endswith(EXTENSIONS)


def filename_from(url: str, fallback: str = "image") -> str:
    """Имя файла из ссылки, безопасное для файловой системы и Telegram."""
    try:
        path = urlparse((url or "").strip()).path
    except ValueError:
        path = ""

    raw = unquote(path.rsplit("/", 1)[-1]) if path else ""
    cleaned = _UNSAFE.sub(" ", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned or "." not in cleaned:
        return f"{fallback}.jpg"
    return cleaned[:80]


def as_photo(size_bytes: int) -> bool:
    """Отправлять фотографией или документом.

    Крупная картинка уходит документом, а не отвергается: она откроется,
    просто без предпросмотра. Отказать было бы хуже — человек просил файл.
    """
    return size_bytes <= PHOTO_LIMIT_MB * 1024 * 1024


def too_big_message(size_mb: float, limit_mb: int) -> str:
    return (
        f"Картинка весит {size_mb:.1f} МБ, а предел отправки — {limit_mb} МБ. "
        f"Скачать её не получится."
    )


async def fetch(session, url: str, limit_mb: int) -> tuple[bytes, str]:
    """Скачивает картинку. Возвращает (данные, объяснение отказа).

    Пустые данные означают отказ, и объяснение всегда заполнено.
    Исключения наружу не выпускаем: для человека сетевой сбой и битая
    ссылка — одно и то же событие «не получилось», и разбираться
    в подробностях он не станет.
    """
    limit_bytes = limit_mb * 1024 * 1024

    try:
        async with session.get(url) as response:
            if response.status != 200:
                return b"", f"Сервер ответил кодом {response.status}."

            # Заявленный размер: отсекаем заведомо крупное до загрузки.
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit_bytes:
                return b"", too_big_message(int(declared) / 1024 / 1024, limit_mb)

            kind = (response.headers.get("Content-Type") or "").lower()
            if kind and not kind.startswith("image/"):
                return b"", "По ссылке не картинка, а что-то другое."

            # Считаем фактический объём по ходу: заявленному размеру
            # верить нельзя, а бесконечный поток забил бы диск.
            chunks: list[bytes] = []
            total = 0
            async for piece in response.content.iter_chunked(CHUNK):
                total += len(piece)
                if total > limit_bytes:
                    return b"", too_big_message(total / 1024 / 1024, limit_mb)
                chunks.append(piece)

    except Exception as exc:  # noqa: BLE001
        log.info("Картинка не скачана (%s): %s", url, exc)
        return b"", "Не удалось скачать картинку по этой ссылке."

    data = b"".join(chunks)
    if not data:
        return b"", "По ссылке пусто."
    return data, ""


# --------------------------------------------------------------------------
#  Подпись и описание
# --------------------------------------------------------------------------

# Telegram обрезает сообщение на 4096 знаках. Режем сами и говорим об этом,
# иначе текст обрывается на полуслове без объяснений.
TEXT_LIMIT = 3500


def description_of(info: dict) -> str:
    """Текст описания из метаданных yt-dlp. Пусто — описания нет."""
    for key in ("description", "summary", "alt_title"):
        value = info.get(key) if isinstance(info, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def format_description(info: dict) -> str:
    """Готовое сообщение с описанием или объяснение, что его нет."""
    from .textutils import esc

    title = str((info or {}).get("title") or "").strip()
    text = description_of(info or {})

    if not text:
        return "📝 У этой публикации нет описания."

    parts = []
    if title:
        parts.append(f"📝 <b>{esc(title[:200])}</b>")
        parts.append("")

    if len(text) > TEXT_LIMIT:
        parts.append(esc(text[:TEXT_LIMIT]))
        parts.append("")
        parts.append("<i>…описание длиннее и обрезано.</i>")
    else:
        parts.append(esc(text))

    return "\n".join(parts)
