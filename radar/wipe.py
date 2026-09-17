"""Полное удаление системы с сервера, запускаемое из панели.

Зачем отдельный модуль, а не кнопка в updater: обновление и удаление
похожи только способом запуска. Всё остальное разное — у удаления нет
ни шагов, ни журнала установки, зато есть требование, которого нет
больше нигде: подтверждение словом, а не нажатием.

Почему одноразовый контейнер. Панель живёт внутри `radar_container`,
а он входит в удаляемое. Стереть себя изнутри нельзя: процесс умрёт
на половине работы и оставит машину в состоянии, которое хуже обоих
исходов. Поэтому удаление выполняет отдельный контейнер `radar_wiper`,
который в список удаляемых не входит и переживает снос всего остального.

Скрипт берётся с GitHub, а не с сервера: тот, что лежит рядом
с установкой, может быть старше набора контейнеров и оставить часть
из них живыми — ровно это и было в `tools/uninstall.sh` до 4.9.8.10.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import os

from . import dockerapi, features, updater

log = logging.getLogger("radar.wipe")

SOCKET = dockerapi.SOCKET
API = dockerapi.API
# Имя нарочно не из семейства radar_*, которое стирает сам скрипт:
# исполнитель не должен попасть под собственную команду.
CONTAINER = "radar_wiper"
IMAGE = "docker:cli"

# Слово подтверждения. Кнопки мало: действие необратимо, а промах
# по экрану телефона стоит дешевле, чем всё остальное в этом модуле.
CONFIRM_WORD = "УДАЛИТЬ"

SCRIPT = r"""
set -e
cd "$RADAR_HOST_DIR"
apk add --no-cache bash curl >/dev/null 2>&1 || true
for tool in bash curl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ОШИБКА: в исполнителе нет $tool (нет сети?)" >&2
        exit 1
    fi
done
tag="$(curl -fsSL --max-time 20 "$RADAR_RELEASES_LATEST" \
      | sed -n 's/.*"tag_name"[^"]*"\([^"]*\)".*/\1/p' | head -n 1)" || tag=""
if [ -z "$tag" ]; then
    echo "ОШИБКА: не удалось узнать последний выпуск" >&2
    exit 1
fi
if ! curl -fsSL --max-time 60 -o /tmp/uninstall.sh \
        "$RADAR_RAW_BASE/$tag/tools/uninstall.sh"; then
    echo "ОШИБКА: не удалось скачать скрипт удаления $tag" >&2
    exit 1
fi
if ! bash -n /tmp/uninstall.sh; then
    echo "ОШИБКА: скачанный скрипт удаления повреждён" >&2
    exit 1
fi
echo "Скрипт удаления $tag получен, стираю установку"
RADAR_HOME="$RADAR_HOST_DIR" bash /tmp/uninstall.sh --yes
"""


def ready() -> tuple[bool, str]:
    """Можно ли стирать отсюда. Второе — причина отказа."""
    if not features.enabled("panel_wipe"):
        return False, "Возможность «Удаление из панели» выключена."
    if not os.path.exists(SOCKET):
        return False, ("Сокет Docker не проброшен в контейнер: удалять "
                       "нечем. Нужен свежий docker-compose.yml "
                       "и пересоздание контейнера.")
    if not os.access(SOCKET, os.W_OK):
        return False, ("Сокет Docker виден, но контейнеру не хватает прав "
                       "на него: нужен номер группы docker — DOCKER_GID.")
    if not updater.host_dir():
        return False, ("Не передан путь установки на хосте (RADAR_HOST_DIR). "
                       "Обновите docker-compose.yml и пересоздайте контейнер.")
    return True, ""


def confirmed(word: str) -> bool:
    """Введено ли слово подтверждения. Регистр и пробелы прощаем,
    опечатку — нет: это последний рубеж перед необратимым."""
    return (word or "").strip().upper() == CONFIRM_WORD


async def start(actor: str) -> tuple[bool, str]:
    """Запускает удаление. Возвращает (получилось, причина отказа)."""
    allowed, reason = ready()
    if not allowed:
        return False, reason

    directory = updater.host_dir()
    payload = {
        "Image": IMAGE,
        "Cmd": ["sh", "-c", SCRIPT],
        "Env": [
            f"RADAR_HOST_DIR={directory}",
            f"RADAR_RELEASES_LATEST={updater.RELEASES_LATEST}",
            f"RADAR_RAW_BASE={updater.RAW_BASE}",
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
        session = await dockerapi.session()
    except Exception as exc:  # noqa: BLE001
        log.error("Сокет Docker недоступен: %s", exc)
        return False, "Сокет Docker недоступен."

    async with session:
        # Образ тот же, что у обновления, и тянется тем же кодом:
        # заводить вторую такую функцию значило бы чинить потом обе.
        ok, why = await updater._ensure_image(session)
        if not ok:
            return False, f"Образ {IMAGE} не скачан: {why}"

        try:
            async with session.delete(f"{API}/containers/{CONTAINER}",
                                      params={"force": "1"}) as response:
                await response.read()
        except Exception:  # noqa: BLE001
            log.debug("Прошлый исполнитель не удалён", exc_info=True)

        try:
            async with session.post(f"{API}/containers/create",
                                    params={"name": CONTAINER},
                                    json=payload) as response:
                body = await response.json()
                if response.status not in (200, 201):
                    message = str(body.get("message") or body)
                    log.error("Исполнитель удаления не создан: %s", message)
                    return False, f"Исполнитель не создан: {message}"
                container_id = body.get("Id") or CONTAINER

            async with session.post(
                    f"{API}/containers/{container_id}/start") as response:
                if response.status not in (204, 304):
                    message = (await response.text())[:200]
                    log.error("Исполнитель удаления не запущен: %s", message)
                    return False, f"Исполнитель не запущен: {message}"
        except Exception as exc:  # noqa: BLE001
            log.exception("Удаление не запущено")
            return False, f"Удаление не запущено: {exc}"

    log.warning("ЗАПУЩЕНО ПОЛНОЕ УДАЛЕНИЕ СИСТЕМЫ из панели (%s)", actor)
    return True, ""
