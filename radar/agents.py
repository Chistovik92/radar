#!/usr/bin/env python3
"""Свои агенты ИИ: несколько сервисов вместо одного.

До 4.8.8 «свой агент» был ровно один: пара ключей `CUSTOM_AI_URL`
и `CUSTOM_AI_KEY` в общем списке настроек. Она и выглядела как две
случайные строки среди двух десятков чужих ключей, и позволяла подключить
только один сервис — а их бывает несколько: локальная модель на этой же
машине, корпоративный шлюз, чей-то прокси.

Теперь агентов несколько, и у каждого три поля:

* **название** — то, как агент показан в списке моделей. Его задаёт
  суперадминистратор, потому что «свой агент 3» ничего не говорит,
  а «Локальная Llama» говорит всё;
* **базовый адрес** — основание совместимого с OpenAI эндпоинта,
  без `/chat/completions`;
* **ключ** — если сервис его не спрашивает, годится любая непустая строка.

Где это лежит
-------------

В `.env`, как и все остальные ключи: правило проекта — секреты живут
только там. Список хранится пронумерованными именами:

    CUSTOM_AI_1_TITLE, CUSTOM_AI_1_URL, CUSTOM_AI_1_KEY
    CUSTOM_AI_2_TITLE, ...

Своя таблица в базе выглядела бы аккуратнее, но увела бы ключи из `.env`
в базу — то есть в резервные копии, в дампы и в выгрузки. Ради опрятности
списка это плохой размен.

Прежняя пара `CUSTOM_AI_URL`/`CUSTOM_AI_KEY` не забыта: пока первый слот
пуст, она показывается как первый агент. Молча потерять уже настроенный
сервис при обновлении нельзя.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from . import secrets

log = logging.getLogger("radar.agents")

# Сколько слотов показывает бот. В переписке длинный список неудобен,
# и пять — обозримый предел; в панели ограничения нет.
BOT_SLOTS = secrets.AGENT_SLOTS

# Предел на всякий случай: номер приходит из формы, то есть снаружи.
MAX_SLOT = 50

MAX_TITLE = 32

# Прежняя пара, до 4.8.8 — единственный способ подключить свой сервис.
LEGACY_URL_ENV = "CUSTOM_AI_URL"
LEGACY_KEY_ENV = "CUSTOM_AI_KEY"

_SLOT_RE = re.compile(r"^\d{1,2}$")


@dataclass(frozen=True)
class Agent:
    slot: int
    title: str
    url: str
    key: str
    model: str = ""
    legacy: bool = False

    @property
    def name(self) -> str:
        """Ключ провайдера: по нему запоминается выбор модели."""
        return "custom" if self.legacy else f"custom{self.slot}"

    @property
    def ready(self) -> bool:
        """Годен ли агент к работе.

        Ключ без адреса никуда не ведёт, поэтому нужны оба. Название
        необязательно: без него подставляется запасное.
        """
        return bool(self.url and self.key)

    @property
    def shown(self) -> str:
        return self.title or f"Свой агент {self.slot}"


def valid_slot(value: object) -> bool:
    text = str(value or "").strip()
    if not _SLOT_RE.match(text):
        return False
    return 1 <= int(text) <= MAX_SLOT


def env_names(slot: int) -> tuple[str, str, str, str]:
    """Имена настроек слота: название, адрес, ключ.

    Берутся у secrets, а не собираются здесь заново: те же имена нужны
    перечню настроек, и два места сборки разошлись бы при первой правке.
    """
    return secrets.agent_env_names(slot)


def valid_url(url: str) -> bool:
    """Основание адреса. Схему проверяем строго: без неё запрос не уйдёт."""
    text = (url or "").strip()
    return text.startswith(("http://", "https://")) and len(text) > 10


def _read(slot: int) -> Agent | None:
    title_env, url_env, key_env, model_env = env_names(slot)
    title = (secrets.get(title_env) or "").strip()[:MAX_TITLE]
    url = (secrets.get(url_env) or "").strip().rstrip("/")
    key = (secrets.get(key_env) or "").strip()
    model = (secrets.get(model_env) or "").strip()
    if not title and not url and not key:
        return None
    return Agent(slot=slot, title=title, url=url, key=key, model=model)


def legacy() -> Agent | None:
    """Прежняя пара как агент. None — она не заполнена."""
    url = (secrets.get(LEGACY_URL_ENV) or "").strip().rstrip("/")
    key = (secrets.get(LEGACY_KEY_ENV) or "").strip()
    if not url and not key:
        return None
    return Agent(slot=1, title="Свой агент", url=url, key=key, legacy=True)


def load() -> list[Agent]:
    """Все заведённые агенты, по возрастанию слота.

    Прежняя пара показывается первым слотом, пока он пуст: обновление
    не должно молча терять уже настроенный сервис.
    """
    found: list[Agent] = []
    for slot in range(1, MAX_SLOT + 1):
        agent = _read(slot)
        if agent is not None:
            found.append(agent)

    if not any(item.slot == 1 for item in found):
        old = legacy()
        if old is not None:
            found.insert(0, old)
    return found


def ready() -> list[Agent]:
    """Только те, которыми можно пользоваться."""
    return [item for item in load() if item.ready]


def by_name(name: str) -> Agent | None:
    for item in load():
        if item.name == name:
            return item
    return None


def free_slot() -> int:
    """Первый незанятый номер. 0 — свободных нет."""
    busy = {item.slot for item in load()}
    for slot in range(1, MAX_SLOT + 1):
        if slot not in busy:
            return slot
    return 0


def save(slot: int, title: str, url: str, key: str, model: str = "") -> bool:
    """Записывает слот целиком. False — слот или адрес негодные.

    Пустой ключ допустим: часть сервисов его не спрашивает, и требовать
    выдуманную строку значило бы усложнять на ровном месте. Пустой адрес
    не допустим — по нему некуда обращаться.
    """
    if not valid_slot(slot):
        return False
    url = (url or "").strip().rstrip("/")
    if not valid_url(url):
        return False

    title_env, url_env, key_env, model_env = env_names(int(slot))
    ok = secrets.write(title_env, (title or "").strip()[:MAX_TITLE])
    ok = secrets.write(url_env, url) and ok
    ok = secrets.write(key_env, (key or "").strip()) and ok
    ok = secrets.write(model_env, (model or "").strip()) and ok
    if ok:
        log.info("Свой агент в слоте %s сохранён", slot)
    return ok


def forget(slot: int) -> bool:
    """Очищает слот. Прежняя пара очищается вместе со слотом 1."""
    if not valid_slot(slot):
        return False
    for name in env_names(int(slot)):
        secrets.write(name, "")
    if int(slot) == 1:
        # Иначе очищенный первый слот тут же снова заполнился бы прежней
        # парой, и кнопка «удалить» выглядела бы сломанной.
        secrets.write(LEGACY_URL_ENV, "")
        secrets.write(LEGACY_KEY_ENV, "")
    log.info("Свой агент в слоте %s удалён", slot)
    return True
