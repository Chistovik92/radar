"""Сокращение ссылок.

Служебный сервис, не публичный. Сокращаются два вида ссылок:

* автоматически — источники в новостных подборках, чтобы длинный адрес
  не съедал строку;
* вручную — суперадминистратором через `/short <адрес>`.

Открывать сокращение всем пользователям намеренно не стали. Публичный
сокращатель — приманка для фишинга и спама: через неделю домен попадает
в списки Safe Browsing, и вместе с ним перестают открываться ссылки
в оповещениях об опасности. Риск ложится не на сервис, а на всё, что
живёт на том же домене.

Хранилище — тот же слой, что у остальных данных. Код детерминированный:
одна и та же ссылка всегда даёт один короткий адрес, поэтому повторное
сокращение не плодит записи.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse

from . import config, secrets

log = logging.getLogger("radar.shortener")

# Алфавит без похожих знаков: ноль и «O», единица и «l» в переписанном
# от руки адресе неразличимы, а короткие ссылки диктуют голосом.
ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"
CODE_LENGTH = 6

# Схемы, которые разрешено сокращать. Без ограничения короткая ссылка
# может увести на javascript: или file: — то есть стать оружием.
ALLOWED_SCHEMES = ("http", "https")

_MAX_URL = 2000


def base_url() -> str:
    """Адрес, на котором отдаются короткие ссылки.

    Задаётся администратором в SHORT_BASE_URL. Пока адрес не задан,
    сокращение отключено: выдавать ссылку, которая никуда не ведёт,
    хуже, чем не сокращать вовсе.
    """
    value = (secrets.get("SHORT_BASE_URL") or "").strip().rstrip("/")
    return value


def enabled() -> bool:
    return bool(base_url())


def valid(url: str) -> bool:
    """Пригодна ли ссылка к сокращению."""
    if not url or len(url) > _MAX_URL:
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def code_for(url: str) -> str:
    """Детерминированный код ссылки.

    Хэш, а не счётчик: одна новость может попасть в несколько подборок,
    и повторное сокращение обязано дать тот же адрес, не создавая записей.
    Подмешивается локальная соль, иначе код чужой ссылки на другом
    экземпляре «Радара» совпал бы с нашим.
    """
    salt = (secrets.get("SHORT_SALT") or config.VERSION).encode("utf-8")
    digest = hashlib.blake2s(url.strip().encode("utf-8"), key=salt[:32],
                             digest_size=8).digest()
    number = int.from_bytes(digest, "big")
    code = ""
    for _ in range(CODE_LENGTH):
        number, position = divmod(number, len(ALPHABET))
        code += ALPHABET[position]
    return code


def short_url(code: str) -> str:
    return f"{base_url()}/s/{code}"


_CODE_RE = re.compile(r"^[" + ALPHABET + r"]{1,16}$")


def valid_code(code: str) -> bool:
    return bool(_CODE_RE.match(code or ""))
