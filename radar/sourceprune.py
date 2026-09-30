"""Удаление молчащих источников (с 5.9.2.1).

`sourcecheck` находит источники, которые умерли или затихли, но убирать их
приходилось руками по одному. Здесь — отбор и удаление одним действием.

Осторожность важнее скорости, потому что ошибка тут необратима для списка:

* по умолчанию ничего не удаляется — показывается, что было бы удалено;
* «молчит» — это последний пост старше заданного числа дней. Источник без
  даты постов (часть лент их не отдаёт) не молчащий, а неопределённый,
  и остаётся;
* недоступные удаляются только по явной просьбе: «не ответил» бывает
  от сети, а не от источника;
* если недоступна большая часть списка, это почти наверняка сеть или
  блокировка у самого сервера, и удаление отказывается работать,
  пока его не попросят об этом прямо (`force`);
* сообщества ВКонтакте не проверяются (проверка — заглушка) и не трогаются.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from . import sourcecheck

log = logging.getLogger("radar.sourceprune")

DEFAULT_DAYS = 30
# Доля недоступных, выше которой отчёту не верим (сеть, а не источники).
SUSPICIOUS_SHARE = 0.5
# Меньше проверенных — доля ничего не говорит.
SUSPICIOUS_MIN = 4


@dataclass(frozen=True)
class Candidate:
    status: sourcecheck.SourceStatus
    reason: str

    @property
    def kind(self) -> str:
        return self.status.kind

    @property
    def ref(self) -> str:
        return self.status.ref


def silent_days(status: sourcecheck.SourceStatus, now: datetime | None = None) -> int | None:
    """Сколько дней молчит источник. None — дата последнего поста неизвестна."""
    if status.last_post is None:
        return None
    moment = now or datetime.now(timezone.utc)
    return max(0, (moment - status.last_post).days)


def select(report: sourcecheck.CheckReport, days: int = DEFAULT_DAYS, *,
           dead: bool = False, now: datetime | None = None) -> list[Candidate]:
    """Что убрать: молчащие дольше `days` и, если просили, недоступные."""
    chosen: list[Candidate] = []
    for status in report.statuses:
        if status.kind == "vk":
            continue
        if status.state == sourcecheck.DEAD:
            if dead:
                chosen.append(Candidate(status, "недоступен: " + (status.note or "нет ответа")))
            continue
        quiet = silent_days(status, now)
        if quiet is not None and quiet > days:
            chosen.append(Candidate(status, f"молчит {quiet} дн (порог {days})"))
    return chosen


def suspicious(report: sourcecheck.CheckReport) -> str:
    """Причина не верить отчёту, если он похож на сбой сети. Пусто — верим."""
    checked = [item for item in report.statuses if item.kind != "vk"]
    if len(checked) < SUSPICIOUS_MIN:
        return ""
    dead = sum(1 for item in checked if item.state == sourcecheck.DEAD)
    if dead / len(checked) > SUSPICIOUS_SHARE:
        return (f"недоступны {dead} из {len(checked)} — похоже на сбой сети "
                "или блокировку у самого сервера, а не на гибель источников")
    return ""


def apply(candidates: list[Candidate]) -> list[Candidate]:
    """Убирает отобранные из списков источников. Сохранение — на вызывающем."""
    from . import sourceedit

    removed: list[Candidate] = []
    for item in candidates:
        if sourceedit.remove(item.kind, item.ref):
            removed.append(item)
    if removed:
        log.info("Убрано молчащих источников: %d", len(removed))
    return removed


__all__ = ["Candidate", "DEFAULT_DAYS", "silent_days", "select", "suspicious", "apply"]
