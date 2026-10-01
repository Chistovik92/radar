"""Действия администрации, общие для панели и консоли (с 5.9.8).

Раньше правка партнёрских проектов и перезапуск бота жили внутри
обработчиков веб-панели, и консоли пришлось бы повторять их логику. А две
копии правил расходятся: лимит проектов, разбор формы и порядок действий
в одном месте обновили бы, в другом — забыли. Здесь они лежат один раз;
панель и консоль зовут эти функции и каждая добавляет своё — редирект или
вывод, запись в журнал действий.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("radar.ops")


@dataclass
class Result:
    ok: bool
    message: str
    extra: str = ""      # что вызывающему нужно для журнала: «changed», «added»…


# --------------------------------------------------------------------------
#  Партнёрские проекты
# --------------------------------------------------------------------------

async def partner_save(data: Any) -> Result:
    """Заводит или правит проект по полям формы (словарь или форма панели)."""
    from . import partners

    projects = await partners.load()
    slug = str(data.get("slug", "")).strip().lower()
    existing = next((item for item in projects if item.slug == slug), None)
    if existing is None and len(projects) >= partners.MAX_PROJECTS:
        return Result(False, f"Больше {partners.MAX_PROJECTS} проектов не бывает")

    # Разбор формы живёт в самом модуле партнёров: второй набор правил
    # разошёлся бы с ботом.
    project = partners.from_form(data, existing)
    if project is None:
        return Result(False, "Проверьте короткое имя, название и ссылку")

    rest = [item for item in projects if item.slug != project.slug]
    await partners.save(rest + [project])
    return Result(True, f"Сохранено: {project.title}",
                  ("changed" if existing else "added") + ":" + project.slug)


async def partner_remove(slug: str) -> Result:
    from . import partners

    slug = (slug or "").strip().lower()
    projects = await partners.load()
    rest = [item for item in projects if item.slug != slug]
    if len(rest) == len(projects):
        return Result(False, "Такого проекта нет")
    await partners.save(rest)
    return Result(True, "Проект удалён", slug)


# --------------------------------------------------------------------------
#  Перезапуск бота
# --------------------------------------------------------------------------

# Ссылки на задачи: asyncio держит на них только слабую, и перезапуск,
# о котором никто не помнит, мог бы не состояться.
_tasks: set[asyncio.Task] = set()


async def restart_bot(delay: float = 2.0) -> Result:
    """Перезапускает контейнер бота через docker.sock.

    Ответ вызывающему должен успеть уйти: перезапускается тот самый процесс,
    что отвечает, поэтому само действие откладывается.
    """
    from . import dockerapi

    if not dockerapi.available():
        return Result(False, "Нет доступа к docker — перезапустите на сервере")

    async def later() -> None:
        await asyncio.sleep(delay)
        docker = await dockerapi.session()
        try:
            name = "radar_container"
            if not await dockerapi.container_exists(docker, name):
                name = socket.gethostname()
            await dockerapi.container_action(docker, name, "restart")
        except Exception:  # noqa: BLE001
            log.warning("Перезапуск бота не удался", exc_info=True)
        finally:
            await docker.close()

    task = asyncio.get_running_loop().create_task(later())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return Result(True, "Перезапуск начат — через полминуты бот вернётся")
