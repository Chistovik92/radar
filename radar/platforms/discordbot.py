"""Discord как канал сообщества: сводки и статус системы (с 5.5).

⚠️ С ЖИВЫМ DISCORD НЕ ПРОВЕРЕН.

Замысел дорожной карты — «не оповещения по адресам, а канал для
сообщества». Поэтому здесь три вещи и ни одной тревоги:

* **ответчик на слеш-команды** `/about`, `/help`, `/status`, `/summary` —
  как встроенный ответчик MAX: говорит, что это за система, где живут
  оповещения, и жив ли мониторинг;
* **суточная сводка** в канал `DISCORD_CHANNEL_ID` в `DISCORD_SUMMARY_TIME`:
  сколько событий было по категориям и сколько отбоев. Без адресов,
  городов и текста — сводка публичная. Событие в прошлом — сводка,
  а не тревога, и так она и подписана;
* **смена статуса мониторинга**: цикл замолчал — сообщение в канал,
  поднялся снова — ещё одно. Это то же самое, что видит администрация,
  но без чисел, которые постороннему ничего не скажут.

Формулировка «не заменяет официальные каналы оповещения» есть
в каждом публичном сообщении — правило проекта.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .. import discordverify
from ..textutils import esc
from .base import Button, EventKind, InboundEvent, OutboundMessage

log = logging.getLogger("radar.platform.discordbot")

DISCLAIMER = "<i>Система не заменяет официальные каналы оповещения.</i>"

ABOUT = (
    "<b>Система «Радар»</b>\n\n"
    "Следит за городскими угрозами и авариями ЖКХ: читает каналы служб "
    "и ленты СМИ, разбирает сообщения и присылает оповещения по адресам "
    "тех, кто их задал.\n\n"
    "<b>Здесь, в Discord, — сводки и статус системы.</b> Тревоги по своим "
    "адресам можно получать в личные сообщения: /address — добавить адрес, "
    "/link — связать с аккаунтом в Telegram, ВК или MAX. Без подтверждённого "
    "адреса тревога не отправляется.\n\n" + DISCLAIMER
)

HELP = (
    "<b>Команды</b>\n"
    "/about — что это такое\n"
    "/status — работает ли мониторинг\n"
    "/summary — сводка за сутки\n"
    "/address — добавить адрес, /addresses — мои адреса, /remove — удалить\n"
    "/link — общий аккаунт с Telegram, ВК, MAX; /unlink — отвязать\n"
    "/help — этот список"
)

COMMANDS = (
    ("about", "Что это за система"),
    ("status", "Работает ли мониторинг"),
    ("summary", "Сводка событий за сутки"),
    ("help", "Список команд"),
    # Общий аккаунт (5.7): ответы видит только сам человек.
    ("address", "Добавить адрес для тревог", [("query", "Улица, дом, город", True)]),
    ("addresses", "Мои адреса"),
    ("remove", "Удалить адрес", [("number", "Номер из /addresses", True)]),
    ("link", "Связать с Telegram, ВК или MAX", [("code", "Код из другой сети", False)]),
    ("unlink", "Отвязать этот аккаунт от остальных"),
    # Проверка участников (5.9.5): команда только для управляющих сервером.
    ("verifysetup", "Поставить кнопку проверки участников в этот канал"),
)
RESTRICTED = ("verifysetup",)

# Музыка в голосовом канале (5.9.7).
MUSIC_COMMANDS = (
    ("play", "Играть музыку по ссылке или названию",
     [("query", "Ссылка (YouTube, SoundCloud, файл…) или слова для поиска", True)]),
    ("skip", "Пропустить трек"),
    ("pause", "Пауза"),
    ("resume", "Продолжить"),
    ("stop", "Остановить и выйти из канала"),
    ("queue", "Что в очереди"),
)
MUSIC_NAMES = tuple(item[0] for item in MUSIC_COMMANDS)

# Команды общего аккаунта: личное, поэтому ответ видит только автор.
PERSONAL = ("address", "addresses", "remove", "link", "unlink")
YES_ID, NO_ID = "txt:yes", "txt:no"

SUMMARY_META = "discord_summary_date"
CHECK_EVERY = 60


def _setting(key: str) -> str:
    from .. import secrets

    return str(secrets.get(key) or "").strip()


def enabled() -> bool:
    from .. import features

    return features.enabled("platform_discord") and bool(_setting("DISCORD_BOT_TOKEN"))


def telegram_button(username: str = "") -> list[list[Button]]:
    if not username:
        return []
    return [[Button(text="Оповещения — в Telegram", url=f"https://t.me/{username}")]]


def status_text(healthy: bool, silent: int) -> str:
    if healthy:
        return "✅ Мониторинг работает."
    minutes = max(1, silent // 60)
    return (f"🚨 Мониторинг молчит около {minutes} мин. Администрация "
            f"уведомлена, цикл поднимается заново.")


def summary_text(counts: dict[str, int], moment: datetime) -> str:
    """Сводка за сутки: категории и отбои. Ни адресов, ни текста."""
    from ..matching import CATEGORY_ICONS, CATEGORY_TITLES

    total = int(counts.get("_total") or 0)
    lines = [f"<b>Сводка за сутки</b> · {moment.strftime('%d.%m.%Y %H:%M')}", ""]
    if not total:
        lines.append("За сутки разобранных событий не было.")
    else:
        lines.append(f"Разобрано событий: <b>{total}</b>")
        for key, title in CATEGORY_TITLES.items():
            count = int(counts.get(key) or 0)
            if count:
                lines.append(f"{CATEGORY_ICONS.get(key, '•')} {title}: {count}")
        clear = int(counts.get("_all_clear") or 0)
        if clear:
            lines.append(f"✅ Отбоев: {clear}")
    lines.append("")
    lines.append("Это сводка о прошедшем, а не тревога. Оповещения по адресам "
                 "приходят лично тем, кто их задал.")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def answer_for(event: InboundEvent, *, status: str, summary: str = "",
               username: str = "") -> OutboundMessage:
    """Что ответить на команду. Отделено от сети — проверяется офлайн."""
    button = telegram_button(username)
    if event.kind is EventKind.COMMAND:
        if event.command in ("about", "start"):
            return OutboundMessage(text=ABOUT, keyboard=button)
        if event.command == "status":
            return OutboundMessage(text=status + "\n\n" + DISCLAIMER)
        if event.command == "summary":
            return OutboundMessage(text=summary or "Сводка пока недоступна.")
        return OutboundMessage(text=HELP, keyboard=button)
    return OutboundMessage(text=HELP, keyboard=button)


async def _counts() -> dict[str, int]:
    from ..db import repo

    try:
        return await repo.event_breakdown(24)
    except Exception:  # noqa: BLE001
        log.warning("Discord: сводка не собрана — база недоступна")
        return {}


def _status() -> tuple[bool, int]:
    from .. import monitor

    return monitor.alive()


async def reply(event: InboundEvent, transport: Any) -> None:
    """Обработчик взаимодействий: ответ — первым делом, у Discord 3 секунды.

    Сводка требует запроса к базе, поэтому по /summary она собирается
    после того, как Discord уже получил ответ «собираю».
    """
    from .maxbot import telegram_username

    if event.kind is EventKind.COMMAND and event.command in MUSIC_NAMES:
        await music_command(event, transport)
        return
    if (event.kind is EventKind.COMMAND and event.command == "verifysetup") or (
            event.kind is EventKind.CALLBACK and event.payload.startswith("dv:")):
        await verification(event, transport)
        return
    if (event.kind is EventKind.COMMAND and event.command in PERSONAL) or (
            event.kind is EventKind.CALLBACK and event.payload in (YES_ID, NO_ID)):
        await personal(event, transport)
        return
    healthy, silent = _status()
    status = status_text(healthy, silent)
    if event.kind is EventKind.COMMAND and event.command == "summary":
        await transport.respond(event, OutboundMessage(text="Собираю сводку…"))
        text = summary_text(await _counts(), datetime.now())
        await transport.send(event.chat_id, OutboundMessage(text=text))
        return
    message = answer_for(event, status=status, username=await telegram_username())
    await transport.respond(event, message, ephemeral=event.command == "help")


async def personal(event: InboundEvent, transport: Any) -> None:
    """Адреса и привязка — общий ответчик `textbot`, ответ виден только автору.

    Discord не читает текст сообщений (намерение Message Content не
    запрашивается), поэтому «да»/«нет» здесь — кнопки.
    """
    from .. import links
    from . import textbot

    user_id = event.identity.external_id
    if event.kind is EventKind.CALLBACK:
        text = "да" if event.payload == YES_ID else "нет"
    else:
        text = event.text
    answer = await textbot.answer("discord", user_id, text)
    keyboard: list[list[Button]] = []
    if links.pending_for("discord", user_id) or textbot.pending_for("discord", user_id):
        keyboard = [[Button(text="Да", payload=YES_ID), Button(text="Нет", payload=NO_ID)]]
    await transport.respond(event, OutboundMessage(text=esc(answer), keyboard=keyboard),
                            update=event.kind is EventKind.CALLBACK, ephemeral=True)


# --------------------------------------------------------------------------
#  Проверка участников (5.9.5)
# --------------------------------------------------------------------------

GATE = discordverify.Gate()
START_ID, ANSWER_ID = "dv:start", "dv:answer"
SWEEP_EVERY = 60
MANAGE_GUILD, ADMINISTRATOR = 0x20, 0x8


def verify_enabled() -> bool:
    """Включена ли проверка: флаг и роль «проверен» заданы."""
    from .. import features

    return features.enabled("discord_verify") and bool(_setting("DISCORD_VERIFY_ROLE_ID"))


def _number(key: str, default: int = 0) -> int:
    try:
        return max(0, int(_setting(key) or default))
    except ValueError:
        return default


def _can_manage(raw: dict[str, Any]) -> bool:
    try:
        bits = int((raw.get("member") or {}).get("permissions") or 0)
    except (TypeError, ValueError):
        return False
    return bool(bits & (MANAGE_GUILD | ADMINISTRATOR))


async def _journal(transport: Any, text: str) -> None:
    """Запись для модераторов в канал журнала, если он задан."""
    channel = _setting("DISCORD_LOG_CHANNEL_ID")
    log.info("Discord, проверка: %s", text)
    if channel:
        await transport.send(channel, OutboundMessage(text=text, silent=True))


def _again(text: str) -> OutboundMessage:
    return OutboundMessage(text=text, keyboard=[[Button(text="Попробовать снова",
                                                        payload=START_ID)]])


async def verification(event: InboundEvent, transport: Any) -> None:
    """Кнопка «Я человек» → вопрос в окне → роль «проверен»."""
    raw = event.raw or {}
    guild = str(raw.get("guild_id") or "")
    user = event.identity.external_id
    role = _setting("DISCORD_VERIFY_ROLE_ID")

    if event.kind is EventKind.COMMAND:
        if not _can_manage(raw):
            await transport.respond(event, OutboundMessage(
                text="Команда только для управляющих сервером."), ephemeral=True)
        elif not verify_enabled():
            await transport.respond(event, OutboundMessage(
                text="Проверка выключена: включите возможность «Discord: проверка "
                     "участников» и задайте DISCORD_VERIFY_ROLE_ID."), ephemeral=True)
        else:
            await transport.respond(event, OutboundMessage(
                text="<b>Проверка</b>\n\nНажмите кнопку и ответьте на короткий "
                     "вопрос — так видно, что вы не скрипт. Без проверки остальные "
                     "каналы закрыты.",
                keyboard=[[Button(text="✅ Я человек", payload=START_ID)]]))
        return

    if not verify_enabled() or not guild:
        await transport.respond(event, OutboundMessage(text="Проверка сейчас выключена."),
                                ephemeral=True)
        return

    roles_now = [str(item) for item in (raw.get("member") or {}).get("roles") or []]
    if role in roles_now:
        GATE.passed(guild, user)
        await transport.respond(event, OutboundMessage(text="Вы уже проверены."),
                                ephemeral=True)
        return

    if event.payload == START_ID:
        from .. import links

        # Аккаунт уже связан с проверенным в другой сети — вопрос не нужен.
        if await links.owner_of("discord", user):
            if await transport.add_role(guild, user, role):
                GATE.passed(guild, user)
                await transport.respond(event, OutboundMessage(
                    text="✅ Аккаунт связан с проверенным в другой сети — "
                         "проверка пройдена."), ephemeral=True)
                return
        question = GATE.ask(guild, user)
        await transport.respond_modal(event, ANSWER_ID, "Проверка", question,
                                      placeholder="Ответ", max_length=20)
        return

    # ANSWER_ID
    result = GATE.check(guild, user, event.text)
    if result == discordverify.OK:
        if await transport.add_role(guild, user, role):
            await transport.respond(event, OutboundMessage(
                text="✅ Проверка пройдена, добро пожаловать."), ephemeral=True)
        else:
            await transport.respond(event, OutboundMessage(
                text="Ответ верный, но выдать роль не удалось — сообщите "
                     "администрации (у бота нет права управлять ролями или его "
                     "роль ниже роли «проверен»)."), ephemeral=True)
            await _journal(transport, f"Не удалось выдать роль участнику {user}: "
                                      "проверьте права бота.")
    elif result == discordverify.WRONG:
        left = GATE.attempts_left(guild, user)
        await transport.respond(event, _again(f"Неверно. Осталось попыток: {left}."),
                                ephemeral=True)
    elif result == discordverify.LOCKED:
        await transport.respond(event, OutboundMessage(
            text="Попытки закончились. Вы можете вернуться по приглашению и "
                 "пройти проверку заново."), ephemeral=True)
        GATE.passed(guild, user)
        if await transport.kick(guild, user):
            await _journal(transport, f"Исключён {user}: не прошёл проверку "
                                      f"за {discordverify.MAX_ATTEMPTS} попытки.")
    else:
        await transport.respond(event, _again("Вопрос устарел — нажмите ещё раз."),
                                ephemeral=True)


async def on_member_add(data: dict[str, Any], transport: Any) -> None:
    """Вступление: сразу исключить явный мусор, остальных поставить на учёт."""
    if not verify_enabled():
        return
    person = data.get("user") or {}
    if person.get("bot"):
        return
    guild, user = str(data.get("guild_id") or ""), str(person.get("id") or "")
    if not guild or not user:
        return
    verdict = discordverify.evaluate(
        user, str(person.get("username") or ""), str(person.get("global_name") or ""),
        min_days=_number("DISCORD_MIN_ACCOUNT_DAYS"))
    if verdict.action == "kick":
        if await transport.kick(guild, user):
            await _journal(transport, f"Исключён {user} при вступлении: {verdict.reason}.")
        return
    GATE.joined(guild, user)


async def verify_sweeper(transport: Any) -> None:
    """Исключает тех, кто так и не прошёл проверку за отведённое время."""
    while True:
        await asyncio.sleep(SWEEP_EVERY)
        if not verify_enabled():
            continue
        try:
            for guild, user in GATE.overdue(_number("DISCORD_VERIFY_MINUTES", 10)):
                GATE.passed(guild, user)
                if await transport.kick(guild, user):
                    await _journal(transport, f"Исключён {user}: не прошёл проверку "
                                              "вовремя.")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Discord: сбой сторожа проверки", exc_info=True)


# --------------------------------------------------------------------------
#  Музыка (5.9.7)
# --------------------------------------------------------------------------

MUSIC: Any = None        # discordmusic.Manager, пока возможность включена


def music_enabled() -> bool:
    from .. import features

    return features.enabled("discord_music")


def _dj_allowed(raw: dict[str, Any]) -> bool:
    """Ограничение по роли DJ. Не задана — музыкой управляют все."""
    role = _setting("DISCORD_DJ_ROLE_ID")
    if not role:
        return True
    roles_now = [str(item) for item in (raw.get("member") or {}).get("roles") or []]
    return role in roles_now or _can_manage(raw)


async def music_command(event: InboundEvent, transport: Any) -> None:
    raw = event.raw or {}
    guild = str(raw.get("guild_id") or "")
    user = event.identity.external_id

    async def say(text: str, *, ephemeral: bool = True) -> None:
        await transport.respond(event, OutboundMessage(text=esc(text)), ephemeral=ephemeral)

    if not guild:
        await say("Музыка работает только на сервере.")
        return
    if MUSIC is None:
        await say("Музыка выключена.")
        return
    if not _dj_allowed(raw):
        await say("Музыкой управляют участники с ролью DJ.")
        return

    command = event.command
    if command == "queue":
        await say(MUSIC.queue_text(guild), ephemeral=False)
    elif command in ("skip", "pause", "resume", "stop"):
        outcome = await getattr(MUSIC, command)(guild)
        await say(outcome.text, ephemeral=not outcome.ok)
    else:
        channel = await transport.voice_channel_of(guild, user)
        if not channel:
            await say("Зайдите в голосовой канал и повторите команду.")
            return
        # Ответ — сразу, у Discord три секунды; поиск может идти дольше.
        await transport.respond(event, OutboundMessage(text="🔎 Ищу…"))
        outcome = await MUSIC.add(guild, channel, user, event.args)
        await transport.edit_original(event, OutboundMessage(text=esc(outcome.text)))


def _build_music() -> tuple[Any, Any] | None:
    """Очередь и голос, если возможность включена и `discord.py` стоит."""
    from .. import config, discordmusic, features, netguard, secrets

    if not features.enabled("discord_music"):
        return None
    try:
        import discord  # noqa: F401
    except ImportError:
        log.warning("Discord: музыка включена, но discord.py не установлен "
                    "(pip install -r requirements-voice.txt) — голос недоступен")
        return None
    host = discordmusic.DiscordPyHost(_setting("DISCORD_BOT_TOKEN"))
    manager = discordmusic.Manager(
        host, guard=netguard.allowed, proxy=config.EGRESS_PROXY,
        cookies=lambda: (secrets.get("MEDIA_COOKIES") or config.MEDIA_COOKIES).strip(),
        max_queue=_number("DISCORD_MUSIC_QUEUE", discordmusic.MAX_QUEUE) or discordmusic.MAX_QUEUE,
        max_minutes=_number("DISCORD_MUSIC_MAX_MINUTES", discordmusic.MAX_MINUTES)
        or discordmusic.MAX_MINUTES,
        max_guilds=_number("DISCORD_MUSIC_GUILDS", discordmusic.MAX_GUILDS)
        or discordmusic.MAX_GUILDS)
    return host, manager


async def music_sweeper(manager: Any) -> None:
    from .. import discordmusic

    while True:
        await asyncio.sleep(discordmusic.SWEEP_EVERY)
        try:
            await manager.sweep()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Discord: сбой сторожа музыки", exc_info=True)


async def run(transport: Any) -> None:
    """Всё, что делает Discord: команды, Gateway и публикации в канал."""
    global MUSIC
    from .. import mirror

    # Тревоги общего аккаунта — в личные сообщения (5.7).
    mirror.register("discord", transport.send_text)
    extra: list[Any] = []
    music = _build_music()
    commands = COMMANDS
    if music is not None:
        host, MUSIC = music
        commands = COMMANDS + MUSIC_COMMANDS
        extra += [host.start(), music_sweeper(MUSIC)]
    try:
        await transport.set_commands(commands, restricted=RESTRICTED)
    except Exception:  # noqa: BLE001
        log.warning("Discord: слеш-команды не заданы", exc_info=True)

    async def member_added(data: dict[str, Any]) -> None:
        await on_member_add(data, transport)

    transport.member_handler = member_added
    await asyncio.gather(transport.start(), community(transport),
                         verify_sweeper(transport), *extra)


def due(now: datetime, when: str, last_date: str) -> bool:
    """Пора ли публиковать сводку: время наступило, а сегодня её ещё не было."""
    try:
        hour, minute = (int(part) for part in (when or "20:00").split(":", 1))
    except ValueError:
        hour, minute = 20, 0
    today = now.strftime("%Y-%m-%d")
    return last_date != today and (now.hour, now.minute) >= (hour, minute)


async def community(transport: Any) -> None:
    """Публикации в канал: суточная сводка и смена статуса мониторинга.

    Отдельная задача с шагом в минуту. Цикл оповещений о ней не знает:
    Discord недоступен — сводка не выйдет, тревоги в Telegram пойдут как
    обычно.
    """
    from .. import storage

    channel = _setting("DISCORD_CHANNEL_ID")
    if not channel:
        log.info("Discord: DISCORD_CHANNEL_ID не задан — публикаций в канал не будет")
        return
    last_healthy = True
    while True:
        try:
            healthy, silent = _status()
            if healthy != last_healthy:
                await transport.send(channel, OutboundMessage(
                    text=status_text(healthy, silent) + "\n\n" + DISCLAIMER))
                last_healthy = healthy
            now = datetime.now()
            last = str(await storage.meta_get(SUMMARY_META, "") or "")
            if due(now, _setting("DISCORD_SUMMARY_TIME"), last):
                # Отметка — до отправки: лучше пропустить одну сводку при
                # сбое, чем прислать две после перезапуска.
                await storage.meta_set(SUMMARY_META, now.strftime("%Y-%m-%d"))
                await transport.send(channel, OutboundMessage(
                    text=summary_text(await _counts(), now), silent=True))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("Discord: публикация в канал не удалась", exc_info=True)
        await asyncio.sleep(CHECK_EVERY)
