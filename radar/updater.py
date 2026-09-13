"""Обновление системы из веб-панели.

Панель живёт внутри контейнера, а `install.sh` — хостовый скрипт: он
пересобирает образ и перезапускает тот самый контейнер, в котором панель
и работает. Прямо изнутри его не выполнить, поэтому обновление
запускается одноразовым контейнером-исполнителем через сокет Docker.

Что важно понимать про цену этого решения (4.9.6):

* сокет Docker внутри контейнера равносилен правам root на хосте.
  Поэтому возможность `panel_update` по умолчанию выключена: включение
  должно быть осознанным действием, а не побочным эффектом обновления;
* панель не выполняет произвольные команды — только один заранее
  заданный сценарий. Терминала сервера в панели нет и не будет,
  это правило проекта;
* каталог установки монтируется в исполнитель ПО ТОМУ ЖЕ пути, что
  и на хосте. Иначе `docker compose` внутри исполнителя передал бы
  демону пути вида `/work/data`, которых на хосте не существует,
  и тома бота развалились бы.

Шаги обновления показывать отдельно не нужно: установщик уже пишет
пошаговый журнал в `data/logs/installer_log_*.txt`, а этот каталог
смонтирован в контейнер — панель просто читает свежий журнал.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from . import dockerapi, features

log = logging.getLogger("radar.updater")

# Сокет и версия API — общие для всего, что говорит с Docker Engine
# по этому сокету (см. radar/dockerapi.py). Имена оставлены здесь же,
# чтобы не переписывать остальной модуль: они те же объекты, что
# в dockerapi, а не копии.
SOCKET = dockerapi.SOCKET
API = dockerapi.API
CONTAINER = "radar_updater"
IMAGE = "docker:cli"

# Метка запуска: по ней панель отличает журнал своего обновления
# от журналов ручных установок.
MARKER = Path("data/update.started")

RELEASES_LATEST = "https://api.github.com/repos/Chistovik92/radar/releases/latest"
RAW_BASE = "https://raw.githubusercontent.com/Chistovik92/radar"

# Сценарий исполнителя. bash нужен самому установщику (он не на sh),
# compose — его основной инструмент, curl — скачать установщик; в образе
# docker:cli их может не быть.
#
# До 4.9.8.9 здесь запускался install.sh, лежащий на сервере. Но установщик
# несёт код бота ВНУТРИ себя и свою копию в каталог не обновляет — кнопка
# «Обновить» честно проходила все девять шагов и ставила ту же версию, что
# стояла. Теперь исполнитель берёт установщик последнего выпуска с GitHub,
# проверяет его синтаксис и только потом подменяет серверную копию.
#
# Ошибки до старта установщика пишутся в data/logs/installer_log_*: панель
# показывает самый свежий такой журнал, и без этого человек видел бы
# «обновление запущено» над журналом ПРОШЛОЙ установки.
# Разбор tag_name — sed, а не grep -P: в Alpine grep из busybox, -P там нет.
SCRIPT = r"""
set -e
cd "$RADAR_HOST_DIR"
mkdir -p data/logs
note="data/logs/installer_log_$(date +%Y%m%d-%H%M%S)-fetch.txt"
say() { printf '%s\n' "$*" | tee -a "$note"; }
apk add --no-cache bash curl >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || apk add --no-cache docker-cli-compose >/dev/null 2>&1 || true
for tool in bash curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        say "ОШИБКА: в исполнителе нет $tool — apk не смог его поставить (нет сети?)"
        exit 1
    fi
done
say "Узнаю последний выпуск на GitHub"
tag="$(curl -fsSL --max-time 20 "$RADAR_RELEASES_LATEST" \
      | sed -n 's/.*"tag_name"[^"]*"\([^"]*\)".*/\1/p' | head -n 1)" || tag=""
if [ -z "$tag" ]; then
    say "ОШИБКА: не удалось узнать последний выпуск (нет связи с api.github.com?)"
    exit 1
fi
say "Последний выпуск: $tag"
if ! curl -fsSL --max-time 120 -o install.sh.new "$RADAR_RAW_BASE/$tag/install.sh"; then
    rm -f install.sh.new
    say "ОШИБКА: не удалось скачать установщик $tag"
    exit 1
fi
if ! bash -n install.sh.new; then
    rm -f install.sh.new
    say "ОШИБКА: скачанный установщик $tag повреждён"
    exit 1
fi
mv -f install.sh.new install.sh
chmod +x install.sh
say "Установщик $tag на месте, запускаю"
bash install.sh --skip-updates
"""


def host_dir() -> str:
    """Каталог установки на хосте. Пусто — значит compose его не передал."""
    return (os.getenv("RADAR_HOST_DIR") or "").strip()


def ready() -> tuple[bool, str]:
    """Можно ли запускать обновление отсюда. Второе — причина отказа."""
    if not features.enabled("panel_update"):
        return False, "Возможность «Обновление из панели» выключена."
    if not os.path.exists(SOCKET):
        return False, ("Сокет Docker не проброшен в контейнер: обновление "
                       "запускать нечем. Нужен свежий docker-compose.yml "
                       "и пересоздание контейнера.")
    # Сокет может быть виден и всё равно недоступен: он принадлежит
    # root:docker с правами 660, а бот работает под uid 1000. Проверяем
    # доступ, а не наличие, — иначе человек нажимает кнопку и получает
    # «Permission denied» вместо понятного объяснения.
    if not os.access(SOCKET, os.W_OK):
        return False, ("Сокет Docker виден, но контейнеру не хватает прав "
                       "на него: бот работает не от root, а сокет открыт "
                       "только группе docker. Нужно передать контейнеру "
                       "номер этой группы — DOCKER_GID.")
    if not host_dir():
        return False, ("Не передан путь установки на хосте (RADAR_HOST_DIR). "
                       "Обновите docker-compose.yml и пересоздайте контейнер.")
    return True, ""


async def _session():
    """Тонкая обёртка над dockerapi.session() — сохранена ради тестов,
    которые патчат именно `radar.updater._session`."""
    return await dockerapi.session()


async def running() -> bool:
    """Идёт ли обновление прямо сейчас."""
    try:
        session = await _session()
    except Exception:  # noqa: BLE001
        return False

    async with session:
        try:
            filters = json.dumps({"name": [CONTAINER], "status": ["running"]})
            async with session.get(f"{API}/containers/json",
                                   params={"filters": filters}) as response:
                if response.status != 200:
                    return False
                return bool(await response.json())
        except Exception:  # noqa: BLE001
            log.debug("Состояние исполнителя не получено", exc_info=True)
            return False


async def _ensure_image(session) -> tuple[bool, str]:
    """Гарантирует, что образ исполнителя есть локально.

    На свежем сервере демон Docker знает только образы бота — `docker:cli`
    туда никто не тянул, и `containers/create` тут же отвечает
    `No such image: docker:cli`. `docker compose` в такой ситуации сам
    делает `pull`, а прямой вызов Engine API — нет, поэтому это нужно
    сделать явно, один раз, перед созданием исполнителя.
    """
    try:
        async with session.get(f"{API}/images/{IMAGE}/json") as response:
            if response.status == 200:
                return True, ""
    except Exception:  # noqa: BLE001
        log.debug("Проверка наличия образа %s не удалась", IMAGE, exc_info=True)

    log.info("Образ %s не найден локально — качаю", IMAGE)
    name, _, tag = IMAGE.partition(":")
    try:
        async with session.post(
            f"{API}/images/create",
            params={"fromImage": name, "tag": tag or "latest"},
        ) as response:
            # Демон отвечает построчным JSON (по объекту на этап загрузки),
            # а не одним документом — ошибка может прийти и с HTTP 200.
            body = await response.text()
            if response.status != 200:
                return False, body[:200]
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("error"):
                    return False, str(event["error"])
    except Exception as exc:  # noqa: BLE001
        log.exception("Образ %s не скачан", IMAGE)
        return False, str(exc)
    return True, ""


async def _drop_old(session) -> None:
    """Убирает исполнителя прошлого запуска, если он остался."""
    try:
        async with session.delete(f"{API}/containers/{CONTAINER}",
                                  params={"force": "1"}) as response:
            await response.read()
    except Exception:  # noqa: BLE001
        log.debug("Прошлый исполнитель не удалён", exc_info=True)


async def start(actor: str) -> tuple[bool, str]:
    """Запускает обновление. Возвращает (получилось, причина отказа)."""
    allowed, reason = ready()
    if not allowed:
        return False, reason

    if await running():
        return False, "Обновление уже идёт."

    directory = host_dir()
    payload = {
        "Image": IMAGE,
        "Cmd": ["sh", "-c", SCRIPT],
        "Env": [
            f"RADAR_HOST_DIR={directory}",
            # Каталог установщик выбирает по RADAR_HOME, а не по текущему.
            # Без неё он брал $HOME/radar_bot, то есть /root/radar_bot
            # ВНУТРИ исполнителя: установка из любого другого каталога
            # уходила в одноразовый контейнер и пропадала вместе с ним.
            f"RADAR_HOME={directory}",
            f"RADAR_RELEASES_LATEST={RELEASES_LATEST}",
            f"RADAR_RAW_BASE={RAW_BASE}",
            # Установщик понимает обе переменные: вопросов не задаёт,
            # «бегущие» полосы в журнал не пишет.
            "RADAR_ASKED=1",
            "NO_ANIMATION=1",
            "HOME=/root",
        ],
        "WorkingDir": directory,
        "HostConfig": {
            "Binds": [
                f"{SOCKET}:{SOCKET}",
                f"{directory}:{directory}",
            ],
            "AutoRemove": False,
            "NetworkMode": "bridge",
        },
    }

    try:
        session = await _session()
    except Exception as exc:  # noqa: BLE001
        log.error("Сокет Docker недоступен: %s", exc)
        return False, "Сокет Docker недоступен."

    async with session:
        ok, reason = await _ensure_image(session)
        if not ok:
            log.error("Образ %s недоступен: %s", IMAGE, reason)
            return False, f"Образ {IMAGE} не скачан: {reason}"

        await _drop_old(session)
        try:
            async with session.post(f"{API}/containers/create",
                                    params={"name": CONTAINER},
                                    json=payload) as response:
                body = await response.json()
                if response.status not in (200, 201):
                    message = str(body.get("message") or body)
                    log.error("Исполнитель не создан: %s", message)
                    return False, f"Исполнитель не создан: {message}"
                container_id = body.get("Id") or CONTAINER

            async with session.post(f"{API}/containers/{container_id}/start") as response:
                if response.status not in (204, 304):
                    message = (await response.text())[:200]
                    log.error("Исполнитель не запущен: %s", message)
                    return False, f"Исполнитель не запущен: {message}"
        except Exception as exc:  # noqa: BLE001
            log.exception("Обновление не запущено")
            return False, f"Обновление не запущено: {exc}"

    try:
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        log.debug("Метка запуска не записана", exc_info=True)

    log.warning("Обновление системы запущено из панели (%s)", actor)
    return True, ""


def started_at() -> float:
    """Когда обновление запускали из панели. 0 — не запускали."""
    try:
        return float(MARKER.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0


def progress(lines: int = 40) -> tuple[str, str]:
    """Последние строки журнала установки: (имя журнала, текст)."""
    from . import logs as logs_module

    items = [item for item in logs_module.collect()
             if item.name.startswith("installer_log_")]
    if not items:
        return "", ""
    latest = items[0]
    return latest.name, logs_module.tail(latest, lines)
