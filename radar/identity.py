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
DISCORD = "discord"
VK = "vk"
PLATFORMS = (TELEGRAM, MAX, DISCORD, VK)

DEFAULT_PLATFORM = TELEGRAM

TITLES = {TELEGRAM: "Telegram", MAX: "MAX", DISCORD: "Discord", VK: "ВКонтакте"}


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
    # «vk.5» — тот же ключ в данных кнопки (5.7): двоеточие там разделяет
    # поля, и «usr:card:vk:5» разобралось бы как пользователь «vk».
    for separator in (":", "."):
        if separator in text:
            platform, _, external = text.partition(separator)
            platform = platform.strip().lower()
            if platform in PLATFORMS:
                return Identity(platform, external.strip())
    return Identity(TELEGRAM, text)


def cb_key(key: str | int) -> str:
    """Ключ для данных кнопки: без двоеточия. Telegram-ключ не меняется."""
    return parse(key).key.replace(":", ".")


def make(platform: str, external_id: str | int) -> Identity:
    platform = (platform or DEFAULT_PLATFORM).strip().lower()
    if platform not in PLATFORMS:
        platform = DEFAULT_PLATFORM
    return Identity(platform, str(external_id).strip())


def key_of(platform: str, external_id: str | int) -> str:
    return make(platform, external_id).key


def is_telegram(key: str | int) -> bool:
    return parse(key).platform == TELEGRAM
