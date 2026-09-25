"""Общий аккаунт одного человека в разных сетях (с 5.6, в обе стороны — с 5.7).

Один человек — один профиль: адреса, настройки, роль и подписка. Telegram,
ВКонтакте, MAX и Discord — равноправные способы в него войти. Начать можно
в любой сети, остальные привязываются одноразовым кодом:

1. в одной сети человек просит код (`/link` или кнопка «🔗 Привязка»),
   бот присылает шестизначный код, живущий 10 минут;
2. в другой сети человек отправляет этот код боту;
3. бот спрашивает подтверждение — и после «да» аккаунты становятся одним:
   адреса и настройки общие, тревоги приходят во все связанные сети.

**Основной ключ профиля.** Если в аккаунте есть Telegram, профиль всегда
хранится под Telegram-идентификатором — так, как он хранился до 5.7.
Поэтому весь Telegram-код, где ключ человека — `from_user.id`, работает
без правок. Когда к аккаунту ВК, заведённому без Telegram, привязывается
Telegram, профиль ВК переезжает под Telegram-ключ, а ВК становится его
способом входа. Без Telegram основным остаётся аккаунт, выдавший код.

**Слияние двух профилей.** Если у обеих сторон уже были адреса, они
объединяются (точка ближе 40 м считается той же), недостающие настройки
берутся у второго. Роль — всегда у основного профиля: роли выдаются
в Telegram, и слияние не должно их ни повышать, ни отбирать. На площадке
у аккаунта одна запись: два Telegram в одном аккаунте не сливаются.

**Почему нужно подтверждение.** Код связывает не только тревоги,
но и адреса: привязанная сеть может их читать и менять. Человеку можно
подсунуть чужой код («введите, это проверка»), и тогда чужой аккаунт
получил бы его адреса. Поэтому код только предлагает связь, а «да»
на стороне того, кто его ввёл, её заключает; о каждой привязке узнают
все сети аккаунта, и отвязать лишнее можно из любой (`/unlink`).

Перебор закрыт: не больше пяти неверных кодов с одного аккаунта за десять
минут. Кодов миллион, так что угадать за пять попыток — один шанс на 200 000.
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
import secrets as pysecrets
import time
from typing import Any

from . import identity

log = logging.getLogger("radar.links")

META_KEY = "account_links"
CODE_TTL = 600
MAX_FAILURES = 5
TELEGRAM = identity.TELEGRAM
PLATFORMS = (identity.TELEGRAM, identity.VK, identity.MAX, identity.DISCORD)
TITLES = {identity.TELEGRAM: "Telegram", identity.VK: "ВКонтакте",
          identity.MAX: "MAX", identity.DISCORD: "Discord"}
# Точки ближе этого при слиянии профилей — одна и та же локация.
SAME_PLACE_M = 40

YES = ("да", "yes", "д", "y", "ок", "ok")
NO = ("нет", "no", "н", "n")

_CODE_RE = re.compile(r"^\s*(?:/?link\s+)?(\d{6})\s*$", re.IGNORECASE)

# Коды живут в памяти: перезапуск бота обнуляет их, и это правильно —
# код на десять минут не стоит того, чтобы переживать перезапуск.
_codes: dict[str, tuple[str, float]] = {}          # код → (ключ выдавшего, до)
_failures: dict[str, list[float]] = {}             # ключ → неверные попытки
_pending: dict[str, tuple[str, float]] = {}        # ключ вводившего → (выдавший, до)
_lock = asyncio.Lock()


def extract_code(text: str) -> str:
    """Код из сообщения: «123456» или «/link 123456». Пусто — не код."""
    match = _CODE_RE.match(text or "")
    return match.group(1) if match else ""


def key_of(platform: str, external_id: str | int) -> str:
    return identity.key_of(platform, external_id)


def _clean(now: float) -> None:
    for code in [code for code, (_, until) in _codes.items() if until < now]:
        _codes.pop(code, None)
    for who in [who for who, (_, until) in _pending.items() if until < now]:
        _pending.pop(who, None)
    for key in list(_failures):
        _failures[key] = [moment for moment in _failures[key] if now - moment < CODE_TTL]
        if not _failures[key]:
            _failures.pop(key)


def new_code(key: str | int, now: float | None = None) -> str:
    """Код привязки для аккаунта с ключом `key` (любая сеть). Прежний гасится."""
    moment = now if now is not None else time.time()
    owner = str(key)
    _clean(moment)
    for code in [code for code, (issuer, _) in _codes.items() if issuer == owner]:
        _codes.pop(code, None)
    while True:
        code = f"{pysecrets.randbelow(10 ** 6):06d}"
        if code not in _codes:
            break
    _codes[code] = (owner, moment + CODE_TTL)
    return code


#  Хранение связей: {основной ключ: {площадка: идентификатор}}
#  Собственная площадка основного ключа в словаре не повторяется —
#  тот же вид, что был в 5.6, поэтому прежние привязки читаются как есть.

async def _load() -> dict[str, dict[str, str]]:
    from . import storage

    value = await storage.meta_get(META_KEY, {})
    return {str(owner): dict(mapping) for owner, mapping in
            (value.items() if isinstance(value, dict) else []) if isinstance(mapping, dict)}


async def _save(links: dict[str, dict[str, str]]) -> None:
    from . import storage

    await storage.meta_set(META_KEY, {owner: mapping for owner, mapping in links.items()
                                      if mapping})


def _canonical_in(links: dict[str, dict[str, str]], key: str) -> str:
    ident = identity.parse(key)
    for owner, mapping in links.items():
        if mapping.get(ident.platform) == ident.external_id and owner != ident.key:
            return owner
    return ident.key


def _members(links: dict[str, dict[str, str]], owner: str) -> dict[str, str]:
    """Все способы входа аккаунта: {площадка: идентификатор}."""
    own = identity.parse(owner)
    members = {own.platform: own.external_id}
    for platform, external in (links.get(owner) or {}).items():
        members.setdefault(platform, str(external))
    return members


async def canonical(key: str | int) -> str:
    """Основной ключ профиля, к которому относится этот вход."""
    return _canonical_in(await _load(), str(key))


async def members(key: str | int) -> dict[str, str]:
    """Все сети аккаунта, куда входит `key`: {площадка: идентификатор}."""
    links = await _load()
    return _members(links, _canonical_in(links, str(key)))


async def links_of(uid: str | int) -> dict[str, str]:
    """Прочие сети аккаунта с основным ключом `uid` — куда слать копии."""
    return dict((await _load()).get(str(uid)) or {})


async def owner_of(platform: str, external_id: str | int) -> str:
    """Основной ключ аккаунта, к которому привязан этот вход. Пусто — ни к чему."""
    links = await _load()
    key = key_of(platform, external_id)
    found = _canonical_in(links, key)
    return found if found != key else ""


#  Привязка

def _conflict(first: dict[str, str], second: dict[str, str]) -> str:
    """Общая площадка у двух аккаунтов — связать нельзя."""
    for platform in PLATFORMS:
        if platform in first and platform in second:
            return (f"В обоих аккаунтах уже есть {TITLES[platform]}: у аккаунта "
                    f"одна запись в каждой сети. Сначала отвяжите лишний (/unlink).")
    return ""


async def propose(platform: str, external_id: str | int, code: str,
                  now: float | None = None) -> tuple[dict[str, str], str]:
    """Проверить код и предложить связь. Возвращает (сети аккаунта, выдавшего
    код; причина отказа). Связь заключает `confirm` — после «да»."""
    moment = now if now is not None else time.time()
    if platform not in PLATFORMS:
        return {}, "Эта площадка не привязывается."
    who = key_of(platform, external_id)
    async with _lock:
        _clean(moment)
        if len(_failures.get(who, [])) >= MAX_FAILURES:
            return {}, "Слишком много неверных кодов. Подождите десять минут."
        entry = _codes.get(code)
        if entry is None:
            _failures.setdefault(who, []).append(moment)
            return {}, "Код не подошёл или устарел. Получите новый."
        issuer, _ = entry
        _codes.pop(code, None)
        links = await _load()
        first = _canonical_in(links, issuer)
        second = _canonical_in(links, who)
        if first == second:
            return {}, "Эти аккаунты уже связаны."
        theirs, ours = _members(links, first), _members(links, second)
        reason = _conflict(theirs, ours)
        if reason:
            return {}, reason
        _pending[who] = (issuer, moment + CODE_TTL)
    return theirs, ""


def pending_for(platform: str, external_id: str | int) -> bool:
    _clean(time.time())
    return key_of(platform, external_id) in _pending


def decline(platform: str, external_id: str | int) -> bool:
    return _pending.pop(key_of(platform, external_id), None) is not None


async def confirm(platform: str, external_id: str | int,
                  now: float | None = None) -> tuple[str, str]:
    """Заключить предложенную связь. Возвращает (основной ключ, причина отказа)."""
    moment = now if now is not None else time.time()
    who = key_of(platform, external_id)
    async with _lock:
        _clean(moment)
        entry = _pending.pop(who, None)
        if entry is None:
            return "", "Нечего подтверждать: сначала отправьте код."
        issuer, _ = entry
        links = await _load()
        first = _canonical_in(links, issuer)
        second = _canonical_in(links, who)
        if first == second:
            return first, ""
        theirs, ours = _members(links, first), _members(links, second)
        reason = _conflict(theirs, ours)
        if reason:
            return "", reason
        # Профиль живёт под Telegram-ключом, если он есть; иначе — у выдавшего.
        if TELEGRAM in ours and TELEGRAM not in theirs:
            target, source = second, first
        else:
            target, source = first, second
        joined = _members(links, target)
        for platform_name, external in _members(links, source).items():
            joined.setdefault(platform_name, external)
        own = identity.parse(target).platform
        links.pop(source, None)
        links[target] = {name: value for name, value in joined.items() if name != own}
        await _save(links)
        await merge_profiles(target, source)
    log.info("Аккаунты связаны: %s", ", ".join(sorted(joined)))
    return target, ""


async def redeem(platform: str, external_id: str | int, code: str,
                 now: float | None = None) -> tuple[str, str]:
    """Код и подтверждение разом — для кода, который сам себе и подтверждение
    (тесты, привязка из доверенного места). Возвращает (основной ключ, причина)."""
    _members_found, reason = await propose(platform, external_id, code, now)
    if reason:
        return "", reason
    return await confirm(platform, external_id, now)


async def merge_profiles(target: str, source: str) -> None:
    """Профиль `source` вливается в `target`, `source` удаляется.

    Роль, язык и часовой пояс — у основного профиля; недостающее берётся
    у второго. Адреса объединяются без повторов.
    """
    from . import storage
    from .textutils import haversine_m

    kept = storage.get_user(target)
    moved = storage.get_user(source)
    if moved is None:
        return
    if kept is None:
        # Основного профиля ещё нет — второй переезжает под его ключ целиком.
        # Журнал доставок второго при удалении записи уходит вместе с ней.
        await storage.drop_user(source)
        storage.users()[target] = moved
        await storage.save(target)
        return

    ids = {item.get("id") for item in kept.get("locs") or []}
    kept.setdefault("locs", [])
    for location in moved.get("locs") or []:
        try:
            lat, lon = float(location.get("lat")), float(location.get("lon"))
        except (TypeError, ValueError):
            continue
        if any(haversine_m(lat, lon, float(item.get("lat") or 0), float(item.get("lon") or 0))
               < SAME_PLACE_M for item in kept["locs"]):
            continue
        item = dict(location)
        while item.get("id") in ids:
            item["id"] = pysecrets.token_hex(4)
        ids.add(item["id"])
        kept["locs"].append(item)

    settings = kept.setdefault("settings", {})
    for name, value in (moved.get("settings") or {}).items():
        settings.setdefault(name, value)
    for field in ("lang", "tz", "quiet_from", "quiet_to", "username"):
        if not kept.get(field) and moved.get(field):
            kept[field] = moved[field]
    if not kept.get("digest") and moved.get("digest"):
        kept["digest"] = moved["digest"]
    contacts = list(kept.get("sos_contacts") or [])
    for contact in moved.get("sos_contacts") or []:
        if contact not in contacts:
            contacts.append(contact)
    kept["sos_contacts"] = contacts
    if moved.get("created") and (not kept.get("created") or moved["created"] < kept["created"]):
        kept["created"] = moved["created"]

    await storage.drop_user(source)
    await storage.save(target)


#  Отвязка

async def unlink(uid: str | int, platform: str | None = None) -> list[str]:
    """Снять привязку сетей с аккаунта `uid` (одну или все, кроме основной).
    Отвязанная сеть остаётся без профиля: адреса остаются в основном."""
    async with _lock:
        links = await _load()
        owner = _canonical_in(links, str(uid))
        mapping = links.get(owner) or {}
        removed = [key for key in list(mapping) if platform in (None, key)]
        for key in removed:
            mapping.pop(key, None)
        links[owner] = mapping
        await _save(links)
    return removed


async def unlink_external(platform: str, external_id: str | int) -> bool:
    """«/unlink» из любой сети: этот вход отделяется от аккаунта.

    Если это вход основного профиля — отделяются все остальные: профиль
    остаётся там, где он хранится.
    """
    key = key_of(platform, external_id)
    async with _lock:
        links = await _load()
        owner = _canonical_in(links, key)
        if owner != key:
            links[owner].pop(platform, None)
        elif links.get(key):
            links.pop(key)
        else:
            return False
        await _save(links)
    return True


def reset() -> None:
    """Для тестов: забыть коды, попытки и ожидающие подтверждения."""
    _codes.clear()
    _failures.clear()
    _pending.clear()


def pending_codes() -> dict[str, Any]:
    return dict(_codes)


#  Тексты

def _t(key: str, lang: str, default: str) -> str:
    from . import i18n

    return i18n.t(key, lang, default)


def titles(platforms: dict[str, str] | list[str]) -> str:
    return ", ".join(TITLES.get(name, name) for name in PLATFORMS if name in platforms)


def code_text(code: str, lang: str = "ru") -> str:
    return _t("link.code_any", lang,
              "Ваш код: {code}\nОтправьте его боту в другой сети — в Telegram "
              "командой /link {code}, во ВКонтакте, MAX или Discord можно просто "
              "кодом. Код действует 10 минут.").format(code=code)


def proposal_text(theirs: dict[str, str], lang: str = "ru") -> str:
    return _t("link.confirm", lang,
              "Связать этот аккаунт с аккаунтом, где есть {nets}?\n\n"
              "Адреса и настройки станут общими, тревоги будут приходить во все "
              "связанные сети. Если код вам прислал кто-то другой — откажитесь: "
              "он получит доступ к вашим адресам.").format(nets=titles(theirs))


def linked_text(lang: str = "ru") -> str:
    return _t("link.done", lang,
              "✅ Аккаунты связаны. Адреса и настройки теперь общие, тревоги "
              "приходят во все связанные сети. Отвязать — /unlink.")


def notice_text(platform: str, lang: str = "ru") -> str:
    return _t("link.notice", lang,
              "🔗 К вашему аккаунту привязан {net}. Если это были не вы — "
              "отвяжите его: /unlink в той сети или «Привязка» в настройках "
              "Telegram-бота.").format(net=TITLES.get(platform, platform))


UNLINKED = "Привязка снята: этот аккаунт больше не связан с остальными."
NOT_LINKED = "Этот аккаунт ни с чем не связан."


async def announce(owner: str, platform: str) -> None:
    """Сообщить во все сети аккаунта о новой привязке. Сбой не мешает связи."""
    from . import storage
    from .tg import send_html

    lang = str((storage.get_user(owner) or {}).get("lang") or "ru")
    for name, external in (await members(owner)).items():
        if name == platform:
            continue
        try:
            await send_html(key_of(name, external), notice_text(platform, lang))
        except Exception:  # noqa: BLE001
            log.debug("Уведомление о привязке не доставлено в %s", name)


def panel_code(owner: str, user: dict[str, Any] | None,
               lang: str = "ru") -> tuple[str, bool]:
    """Код входа в веб-панель для основного ключа профиля (5.7).
    Возвращает (текст ответа, выдан ли код)."""
    from . import features, roles

    if not features.enabled("web_panel"):
        return _t("panel.off", lang, "Веб-панель выключена."), False
    if not roles.is_moderator((user or {}).get("role")):
        return _t("panel.denied", lang, "Веб-панель — для модераторов и выше."), False
    from .web import auth

    code = auth.issue_login_code(owner)
    return _t("panel.code", lang,
              "Код входа в веб-панель: {code}\nОдноразовый, действует 5 минут. "
              "Введите его на странице входа панели. Если вы его не запрашивали — "
              "ничего не делайте.").format(code=code), True


async def announce_panel(owner: str, platform: str) -> None:
    """Сообщить в остальные сети аккаунта, что запрошен вход в панель."""
    from . import storage
    from .tg import send_html

    lang = str((storage.get_user(owner) or {}).get("lang") or "ru")
    text = _t("panel.notice", lang,
              "🔐 Запрошен код входа в веб-панель из {net}. Если это были не вы — "
              "отвяжите ту сеть (/unlink).").format(net=TITLES.get(platform, platform))
    for name, external in (await members(owner)).items():
        if name == platform:
            continue
        try:
            await send_html(key_of(name, external), text)
        except Exception:  # noqa: BLE001
            log.debug("Уведомление о входе в панель не доставлено в %s", name)


async def handle_text(platform: str, external_id: str | int, text: str,
                      lang: str = "ru") -> str:
    """Код, «да»/«нет», /link или /unlink из текстовой сети. Пусто — не об этом."""
    stripped = (text or "").strip()
    lowered = stripped.lower()
    if lowered in ("/unlink", "unlink", "отвязать"):
        done = await unlink_external(platform, external_id)
        return _t("link.unlinked_net", lang, UNLINKED) if done \
            else _t("link.not_linked", lang, NOT_LINKED)
    if lowered in ("/link", "link", "привязать"):
        return code_text(new_code(await canonical(key_of(platform, external_id))), lang)
    if pending_for(platform, external_id):
        if lowered in YES:
            owner, reason = await confirm(platform, external_id)
            if not owner:
                return f"❌ {reason}"
            asyncio.get_running_loop().create_task(announce(owner, platform))
            return linked_text(lang)
        if lowered in NO:
            decline(platform, external_id)
            return _t("link.declined", lang, "Хорошо, аккаунты не связаны.")
    code = extract_code(stripped)
    if not code:
        return ""
    theirs, reason = await propose(platform, external_id, code)
    if reason:
        return f"❌ {reason}"
    return proposal_text(theirs, lang) + "\n\n" + _t(
        "link.answer", lang, "Ответьте «да» или «нет».")
