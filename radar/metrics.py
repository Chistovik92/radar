"""Метрики и здоровье системы в одном месте (с 4.9.9.3).

Закрывает два пункта раздела 4.9 дорожной карты:

* **п.3 «Метрики»** — число оповещений, задержка доставки, расход квоты
  ИИ, доля мёртвых источников. Данные собирались давно, но лежали
  в четырёх местах (`/stats`, `/perf`, `/quota`, ночное письмо проверки
  источников), и ответ на вопрос «как работает система» приходилось
  складывать из них в голове;
* **п.6 «Панель здоровья в боте»** — память, диски, база и контейнеры.
  До 4.9.9.3 бот показывал только размер базы, а диск — лишь ночным
  письмом и лишь при заполнении.

Состояние контейнеров дорожная карта когда-то обещала не показывать:
«нужен сокет Docker, а это доступ ко всему серверу». Довод устарел
с 4.9.6 — сокет смонтирован ради обновления из панели и RustDesk. Раз
цена уже заплачена, чтение списка контейнеров — не новый риск. Если
сокета нет, строка просто объясняет, почему контейнеров не видно.

Сбор отделён от вывода: снимок — обычный словарь, его можно проверить
офлайн, а текст для бота строится отдельной функцией.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
import shutil
import time
from typing import Any

log = logging.getLogger("radar.metrics")

# Порог тревоги по памяти и дискам — те же, что у диагностики установщика
# и ночного письма: разные пороги в разных местах читались бы как разные
# мнения системы о самой себе.
MEMORY_WARN_MB = 300
DISK_WARN_PERCENT = 85


# --------------------------------------------------------------------------
#  Сбор
# --------------------------------------------------------------------------

def system_memory() -> tuple[int, int]:
    """Память машины: (всего, доступно) в МБ. (0, 0) — узнать нельзя."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            info = {
                line.split(":")[0]: int(line.split()[1])
                for line in handle if ":" in line and len(line.split()) > 1
            }
    except (OSError, ValueError):
        return 0, 0
    return info.get("MemTotal", 0) // 1024, info.get("MemAvailable", 0) // 1024


def disks(paths: list[str]) -> list[dict[str, Any]]:
    """Заполненность дисков. Одна точка монтирования — одна строка.

    Пути могут вести на один и тот же диск (данные и музыка рядом) или
    на разные (музыка вынесена на внешний носитель), поэтому повторы
    отсеиваются по паре «всего/свободно».
    """
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            usage = shutil.disk_usage(path or ".")
        except OSError:
            continue
        key = f"{usage.total}:{usage.free}"
        if key in seen:
            continue
        seen.add(key)
        percent = int(usage.used * 100 / usage.total) if usage.total else 0
        rows.append({"path": path, "used": usage.used, "total": usage.total,
                     "percent": percent})
    return rows


def percentile(values: list[float], share: float) -> float:
    """Значение, ниже которого лежит доля `share` выборки. Без numpy."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def latency(samples: list[float]) -> dict[str, float]:
    """Сводка задержки доставки: медиана, 90-й процентиль, число замеров."""
    return {
        "count": float(len(samples)),
        "median": percentile(samples, 0.5),
        "p90": percentile(samples, 0.9),
    }


async def containers() -> tuple[bool, list[dict[str, Any]]]:
    """(доступен ли сокет, контейнеры системы)."""
    from . import dockerapi

    if not dockerapi.available():
        return False, []
    try:
        session = await dockerapi.session()
        async with session:
            return True, await dockerapi.list_containers(session)
    except Exception:  # noqa: BLE001
        log.debug("Контейнеры не прочитаны", exc_info=True)
        return True, []


async def snapshot() -> dict[str, Any]:
    """Всё, что показывает экран метрик. Каждая часть — отдельно
    от остальных: сбой одной не должен прятать другие."""
    from . import ai, config, monitor, sourcecheck

    data: dict[str, Any] = {"at": time.time()}

    try:
        stats = monitor.stats()
        healthy, silent = monitor.alive()
        data["cycle"] = {
            "cycles": int(stats.get("cycles") or 0),
            "alerts": int(stats.get("alerts") or 0),
            "delivered": int(stats.get("delivered") or 0),
            "last_cycle": int(stats.get("last_cycle") or 0),
            "restarts": int(stats.get("restarts") or 0),
            "healthy": healthy,
            "silent": silent,
        }
        data["latency"] = latency(monitor.latency_samples())
    except Exception:  # noqa: BLE001
        log.debug("Счётчики цикла не прочитаны", exc_info=True)

    try:
        data["quota"] = ai.quota_snapshot() if ai.ENABLED else {}
    except Exception:  # noqa: BLE001
        data["quota"] = {}

    data["sources"] = await sourcecheck.last_summary()

    total, available = system_memory()
    data["memory"] = {"total": total, "available": available}

    try:
        from . import music

        paths = [".", music.DIRECTORY, config.MEDIA_DIR]
    except Exception:  # noqa: BLE001
        paths = ["."]
    data["disks"] = disks(paths)

    try:
        from . import dbcare

        if config.is_sqlite():
            data["database"] = {"kind": "SQLite",
                                "report": dbcare.size_report(
                                    dbcare.measure_sqlite(config.DB_FILE), "SQLite")}
        else:
            data["database"] = {"kind": "PostgreSQL", "report": ""}
    except Exception:  # noqa: BLE001
        data["database"] = {}

    socket_ok, rows = await containers()
    data["containers"] = {"socket": socket_ok, "rows": rows}
    return data


# --------------------------------------------------------------------------
#  Вывод
# --------------------------------------------------------------------------

def _size(value: float) -> str:
    from .music import format_size

    return format_size(value)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds} с"
    if seconds < 5400:
        return f"{seconds // 60} мин"
    return f"{seconds // 3600} ч {seconds % 3600 // 60} мин"


def render(data: dict[str, Any]) -> str:
    """Экран метрик для бота."""
    from datetime import datetime

    from .textutils import esc

    lines = ["📊 <b>Метрики и здоровье системы</b>", ""]

    # --- оповещения ---
    cycle = data.get("cycle") or {}
    if cycle:
        mark = "✅" if cycle.get("healthy") else "🚨"
        last = cycle.get("last_cycle") or 0
        when = datetime.fromtimestamp(last).strftime("%H:%M:%S") if last else "ещё не было"
        lines.append("🛰 <b>Оповещения</b>")
        lines.append(f"{mark} Последний проход: <b>{when}</b>"
                     + ("" if cycle.get("healthy")
                        else f" — цикл молчит {cycle.get('silent', 0)} с"))
        lines.append(f"Доставлено оповещений о событиях: <b>{cycle.get('delivered', 0)}</b> "
                     f"· всего сообщений с погодой: {cycle.get('alerts', 0)}")
        lines.append(f"Циклов: {cycle.get('cycles', 0)}"
                     + (f" · перезапусков цикла: <b>{cycle['restarts']}</b>"
                        if cycle.get("restarts") else ""))

    delay = data.get("latency") or {}
    if delay.get("count"):
        lines.append(
            f"Задержка доставки: медиана <b>{_duration(delay['median'])}</b>, "
            f"90% быстрее {_duration(delay['p90'])} "
            f"<i>(замеров: {int(delay['count'])})</i>"
        )
    else:
        lines.append("<i>Задержка доставки: замеров пока нет — считается "
                     "с первого доставленного оповещения.</i>")
    lines.append("")

    # --- ИИ ---
    quota = data.get("quota") or {}
    lines.append("🧠 <b>Квота ИИ</b>")
    if quota:
        used, limit = quota.get("used_today", 0), quota.get("limit_day", 0)
        share = f" ({used * 100 // limit}%)" if limit else ""
        pause = " · ⏸ пауза после 429" if quota.get("paused") else ""
        lines.append(f"За сутки: <b>{used}/{limit}</b>{share}{pause}")
    else:
        lines.append("ИИ выключен — разбор идёт эвристикой.")
    lines.append("")

    # --- источники ---
    sources = data.get("sources") or {}
    lines.append("📡 <b>Источники</b>")
    if sources.get("total"):
        total = sources["total"]
        dead = sources.get("dead", 0)
        lines.append(
            f"Недоступны: <b>{dead} из {total}</b> ({dead * 100 // total}%) · "
            f"молчат: {sources.get('stale', 0)} · живых: {sources.get('alive', 0)}"
        )
        lines.append(f"<i>По проверке {esc(str(sources.get('at', '')))}.</i>")
    else:
        lines.append("<i>Проверок ещё не было: Управление → Источники → "
                     "«Проверить доступность» или ночная проверка.</i>")
    lines.append("")

    # --- машина ---
    lines.append("💻 <b>Сервер</b>")
    memory = data.get("memory") or {}
    if memory.get("total"):
        low = memory["available"] < MEMORY_WARN_MB
        lines.append(
            f"{'⚠️ ' if low else ''}Память: свободно <b>{memory['available']} МБ</b> "
            f"из {memory['total']} МБ"
        )
    for disk in data.get("disks") or []:
        warn = disk["percent"] >= DISK_WARN_PERCENT
        lines.append(
            f"{'⚠️ ' if warn else ''}Диск {esc(str(disk['path']))}: "
            f"{_size(disk['used'])} из {_size(disk['total'])} (<b>{disk['percent']}%</b>)"
        )
    database = data.get("database") or {}
    if database.get("report"):
        lines.append(f"🗄 {esc(database['report'])}")
    elif database.get("kind"):
        lines.append(f"🗄 База: {esc(database['kind'])}")
    lines.append("")

    # --- контейнеры ---
    boxes = data.get("containers") or {}
    lines.append("📦 <b>Контейнеры</b>")
    if not boxes.get("socket"):
        lines.append("<i>Сокет Docker не смонтирован — состояние контейнеров "
                     "боту не видно. Смотрите <code>docker ps</code> на сервере.</i>")
    elif not boxes.get("rows"):
        lines.append("<i>Docker не ответил.</i>")
    else:
        for row in boxes["rows"]:
            state = row.get("state") or ""
            health = row.get("health") or ""
            icon = "🟢" if state == "running" and health != "unhealthy" else (
                "🟠" if state == "running" else "🔴")
            tail = f" · {health}" if health else ""
            lines.append(f"{icon} {esc(row['name'])} — {esc(state)}{esc(tail)}")

    return "\n".join(lines)
