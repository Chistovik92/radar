"""Проверка ссылок на признаки мошенничества — команда /check.

Функция приехала из отдельного бота linkcheck (с 4.9.4 — часть «Радара»
за флагом возможности): статический разбор адреса плюс необязательные
сетевые проверки. Вывод перечисляет признаки и никогда не говорит
«ссылка безопасна» — это честнее, чем обещать гарантию.

Отдельного процесса и токена больше нет: тот бот пришлось бы узнавать
заранее, а /check живёт в основном боте и включается тумблером.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import config, features, i18n, secrets
from ..tg import back_kb

log = logging.getLogger("radar.handlers.linkcheck")
router = Router(name="linkcheck")

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

# Ограничение частоты: сетевые проверки ходят в чужие сервисы, и один
# человек очередью ссылок мог бы занять их на всех.
_hits: dict[int, list[float]] = defaultdict(list)


def _allowed(user_id: int) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    _hits[user_id] = [t for t in _hits[user_id] if now - t < 60]
    if len(_hits[user_id]) >= config.LINKCHECK_RATE_LIMIT:
        return False
    _hits[user_id].append(now)
    return True


@router.message(Command("check"))
async def cmd_check(message: Message, user: dict) -> None:
    lang = i18n.language_of(user)

    if not features.enabled("linkcheck"):
        await message.answer(
            i18n.t("linkcheck.off", lang, "Проверка ссылок отключена.")
        )
        return

    args = (message.text or "").split(maxsplit=1)
    match = URL_RE.search(args[1] if len(args) > 1 else "")
    if not match:
        await message.answer(
            i18n.t(
                "linkcheck.usage", lang,
                "🔍 Пришлите ссылку после команды:\n"
                "<code>/check https://пример.рф/страница</code>",
            ),
            reply_markup=back_kb(),
        )
        return

    if not _allowed(message.from_user.id):
        await message.answer(
            i18n.t(
                "linkcheck.slow_down", lang,
                "⚠️ Слишком много проверок подряд. Подождите минуту.",
            )
        )
        return

    url = match.group(0)
    await message.answer(i18n.t("linkcheck.working", lang, "⏳ Проверяю ссылку…"))

    # Импорт внутри обработчика: утилиты мультитула не грузятся, пока
    # флаг выключен, и правка в них не трогает остального бота.
    from multitool.linkcheck.analyze import analyze
    from multitool.linkcheck.report import build_report

    verdict = analyze(url)

    if config.LINKCHECK_NET:
        from multitool.linkcheck.netcheck import NetResult, full_check

        key = (secrets.get("SAFE_BROWSING_API_KEY") or "").strip()
        try:
            verdict.net = await asyncio.wait_for(
                full_check(url, key), timeout=config.LINKCHECK_TIMEOUT
            )
        except asyncio.TimeoutError:
            verdict.net = NetResult(notes=["timeout"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Сетевая проверка не удалась: %s", exc)
            verdict.net = NetResult(notes=[f"error: {type(exc).__name__}"])

    log.info("Проверена ссылка: %s (счёт %d)", url[:80], verdict.score)
    await message.answer(
        build_report(verdict),
        disable_web_page_preview=True,
    )
