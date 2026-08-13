"""Идентификация пользователя независимо от мессенджера.

Ключ рабочего набора в памяти — строка вида `telegram:123456` или `max:987`.
Для Telegram допускается краткая форма без префикса: так обработчики версий
3.x, передающие `str(message.from_user.id)`, продолжают работать без правок.

Единая точка разбора нужна затем, чтобы в 4.2 добавление MAX не потребовало
трогать логику ролей, локаций и оповещений — она оперирует ключом, а не
конкретным мессенджером.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass

TELEGRAM = "telegram"
MAX = "max"
PLATFORMS = (TELEGRAM, MAX)

DEFAULT_PLATFORM = TELEGRAM

TITLES = {TELEGRAM: "Telegram", MAX: "MAX"}


@dataclass(frozen=True)
class Identity:
    platform: str
    external_id: str

    @property
    def key(self) -> str:
        """Ключ рабочего набора. Telegram — без префикса, ради совместимости."""
        if self.platform == TELEGRAM:
            return self.external_id
        return f"{self.platform}:{self.external_id}"

    @property
    def title(self) -> str:
        return TITLES.get(self.platform, self.platform)

    def __str__(self) -> str:  # удобно в логах
        return self.key


def parse(key: str | int) -> Identity:
    """Разбирает ключ рабочего набора в пару платформа/идентификатор."""
    text = str(key).strip()
    if ":" in text:
        platform, _, external = text.partition(":")
        platform = platform.strip().lower()
        if platform in PLATFORMS:
            return Identity(platform, external.strip())
    return Identity(TELEGRAM, text)


def make(platform: str, external_id: str | int) -> Identity:
    platform = (platform or DEFAULT_PLATFORM).strip().lower()
    if platform not in PLATFORMS:
        platform = DEFAULT_PLATFORM
    return Identity(platform, str(external_id).strip())


def key_of(platform: str, external_id: str | int) -> str:
    return make(platform, external_id).key


def is_telegram(key: str | int) -> bool:
    return parse(key).platform == TELEGRAM
