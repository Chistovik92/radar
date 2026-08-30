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

Записи с картинками (с 4.8.4.7)
-------------------------------

Прямая ссылка на файл — не единственный способ прислать картинку. Люди
кидают ссылку на запись: пост в Instagram, твит с фотографией, сообщение
сообщества YouTube. Расширения в такой ссылке нет, и до 4.8.4.7 она
уходила в yt-dlp, который честно отвечал «в этой записи нет видео» —
а человек видел «не удалось обработать ссылку».

Разбор идёт по метаданным страницы: `og:image` и `twitter:image`
заполняют все крупные площадки, потому что по ним строится предпросмотр
ссылки в мессенджерах. Способ не всесильный — площадка может ответить
страницей входа вместо записи, и тогда картинок в метаданных не будет.
Это честное ограничение, а не поломка: без входа закрытую запись
не покажет и браузер.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote

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


# --------------------------------------------------------------------------
#  Картинки из записи (с 4.8.4.7)
# --------------------------------------------------------------------------

# Свойства, которыми площадки объявляют картинку записи. Порядок важен:
# og:image заполняют все, twitter:image — запасной для X и части зеркал.
_META_KEYS = (
    "og:image:secure_url",
    "og:image:url",
    "og:image",
    "twitter:image:src",
    "twitter:image",
)

# Сколько картинок берём из одной записи. Карусель в Instagram бывает
# на десять снимков, но в метаданных отдаётся обычно первая; предел
# нужен на случай страницы, где их объявлено много.
MAX_FROM_PAGE = 10


class _MetaReader(HTMLParser):
    """Собирает содержимое нужных meta-тегов.

    Разбор на стандартной библиотеке, а не на bs4, намеренно: задача —
    вытащить несколько атрибутов из head, и тащить ради неё внешний
    разборщик незачем. Вдобавок bs4 в тестах подменяется заглушкой,
    и код на нём проверялся бы только на живом сервере.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "meta" or len(self.found) >= MAX_FROM_PAGE:
            return
        values = {name.lower(): (value or "") for name, value in attrs}
        name = (values.get("property") or values.get("name") or "").strip().lower()
        if name not in _META_KEYS:
            return
        content = (values.get("content") or "").strip()
        if content:
            self.found.append(content)


# Ключи, которыми площадки перечисляют картинки записи внутри встроенного
# JSON. Метаданные предпросмотра отдают только ПЕРВУЮ картинку, а в посте
# их бывает десяток: карусель в Instagram, несколько фотографий в твите.
# Человек присылает ссылку на запись целиком и ждёт всю запись.
_JSON_KEYS = ("display_url", "displayUrl", "media_url_https")

_JSON_IMAGE = re.compile(
    r'"(?:' + "|".join(_JSON_KEYS) + r')"\s*:\s*"([^"]{8,600}?)"'
)


def _unescape_json_url(value: str) -> str:
    """Адрес из встроенного JSON: экранированные слэши и юникод вместо &."""
    return (value
            .replace("\\/", "/")
            .replace("\\u0026", "&")
            .replace("&amp;", "&"))


def from_json(markup: str) -> list[str]:
    """Картинки, перечисленные во встроенном JSON страницы.

    Разбор нарочно грубый — по ключам, а не по структуре: разметку соцсети
    меняют часто, и полноценный разбор их JSON ломался бы каждый месяц.
    Здесь же худший случай — не найти ничего, и тогда остаются метаданные.
    """
    found: list[str] = []
    for raw in _JSON_IMAGE.findall(markup or ""):
        value = _unescape_json_url(raw)
        if not value.lower().startswith(("http://", "https://")):
            continue
        # Отбрасываем всё, что не картинка: по этим же ключам иногда
        # лежат ссылки на профиль и на видео.
        path = value.split("?")[0].lower()
        if not path.endswith(EXTENSIONS):
            continue
        if value not in found:
            found.append(value)
        if len(found) >= MAX_FROM_PAGE:
            break
    return found


def from_page(markup: str, base_url: str = "") -> list[str]:
    """Ссылки на картинки из метаданных страницы записи.

    Разбор отделён от загрузки намеренно: так его можно проверить офлайн,
    на сохранённой разметке, не выходя в сеть.
    """
    if not markup:
        return []

    reader = _MetaReader()
    try:
        reader.feed(markup)
    except Exception:  # noqa: BLE001
        # Разметка соцсетей бывает битой; половина разобранного лучше,
        # чем отказ целиком — то, что успели собрать, уже пригодно.
        log.debug("Разметка страницы разобрана не полностью", exc_info=True)

    links: list[str] = []
    # Метаданные идут первыми: там лежит главная картинка записи, и она
    # должна прийти человеку первой. Остальные добираются из JSON.
    for value in list(reader.found) + from_json(markup):
        # Относительный адрес встречается у зеркал и самодельных страниц.
        if base_url:
            value = urljoin(base_url, value)
        if not value.lower().startswith(("http://", "https://")):
            continue
        if value not in links:
            links.append(value)
        if len(links) >= MAX_FROM_PAGE:
            break
    return links


async def fetch_page(session, url: str, limit_kb: int = 512) -> str:
    """Разметка страницы записи. Пусто — не получилось.

    Читаем ограниченный кусок: метаданные лежат в head, а тянуть целиком
    страницу соцсети на одноплатник незачем.
    """
    try:
        async with session.get(url) as response:
            if response.status != 200:
                log.info("Страница записи ответила кодом %s", response.status)
                return ""
            kind = (response.headers.get("Content-Type") or "").lower()
            if kind and "html" not in kind:
                return ""
            data = await response.content.read(limit_kb * 1024)
            return data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        log.debug("Страницу записи прочитать не удалось", exc_info=True)
        return ""
