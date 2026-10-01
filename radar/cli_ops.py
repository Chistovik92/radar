"""Консоль: подписки, VPN-панели и доступы, партнёры, перезапуск (с 5.9.8).

Продолжение `radar.cli`, как и `cli_admin`: подкоманды зовут те же функции,
что обработчики панели (`adminpages.subscriptions_act`, `access_act`,
`vpnslots`, `ops`, `redeem`, `partners`) — разбор, проверки и права живут
там один раз. От формы панели консоль берёт только вид: словарь с методом
`getall`.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

from typing import Any

from . import cli
from .clitext import L
from .cli_admin import audit

OK, FAILED, NEEDS_YES = cli.OK, cli.FAILED, cli.NEEDS_YES
CONSOLE = "консоль"
ROLE = "superadmin"


class Form(dict):
    """Поля формы так, как их отдаёт панель: `get` и `getall`."""

    def getall(self, key: str, default: Any = None) -> list[str]:
        value = self.get(key)
        if value is None:
            return list(default or [])
        return list(value) if isinstance(value, (list, tuple)) else [value]


def pairs(items: list[str] | None) -> tuple[dict[str, str], str]:
    """`--set КЛЮЧ=ЗНАЧЕНИЕ` → словарь. Вторым — причина отказа."""
    found: dict[str, str] = {}
    for item in items or []:
        key, sign, value = item.partition("=")
        if not sign or not key.strip():
            return {}, L(f"Нужно КЛЮЧ=ЗНАЧЕНИЕ, получено «{item}».",
                         f"Expected KEY=VALUE, got “{item}”.")
        found[key.strip()] = value
    return found, ""


def _need_yes(args, text_ru: str, text_en: str) -> bool:
    if getattr(args, "yes", False):
        return False
    cli._err(L(text_ru + " Повторите с --yes.", text_en + " Repeat with --yes."))
    return True


def _result(message: str, error: str, as_json: bool) -> int:
    payload = {"ok": not error, "message": message or error}
    cli._out(payload, as_json, lambda d: print(d["message"]) if not error
             else cli._err(d["message"]))
    return FAILED if error else OK


# --------------------------------------------------------------------------
#  Подписка бота
# --------------------------------------------------------------------------

def cmd_subs(args) -> int:
    from . import redeem, storage, subscription
    from .web import adminpages

    async def run():
        action, items = args.action, args.items

        if action == "list":
            needle = (args.q or "").strip().lower()
            rows = []
            for uid, user in storage.users().items():
                if needle:
                    if needle not in str(uid).lower() and needle not in str(
                            user.get("username", "")).lower():
                        continue
                elif not subscription.paid(user):
                    continue
                rows.append({"uid": uid, "username": user.get("username", ""),
                             "until": subscription.paid_until(user),
                             "paid": subscription.paid(user),
                             "trial": subscription.on_trial(user)})
            cli._out(rows, args.json, lambda data: [
                print(f"{r['uid']:>14}  {r['until'] or '—':<12} {r['username']}")
                for r in data] or print(L("нет оплаченных подписок",
                                          "no paid subscriptions")))
            return OK

        if action == "codes":
            rows = [{"code": c.get("code"), "days": c.get("days"),
                     "used_by": c.get("used_by") or "", "used_at": c.get("used_at") or ""}
                    for c in await redeem.load()]
            cli._out(rows, args.json, lambda data: [
                print(f"{r['code']:<24} {r['days']:>4} дн.  "
                      + (f"{L('использован', 'used')}: {r['used_by']}" if r["used_by"]
                         else L("свободен", "free"))) for r in data
            ] or print(L("кодов нет", "no codes")))
            return OK

        if action == "grant":
            if len(items) != 2:
                cli._err(L("subs grant UID ДНЕЙ", "subs grant UID DAYS"))
                return FAILED
            done, failed = await adminpages.subscriptions_act(
                Form(action="grant", uid=items[0], days=items[1]))
            if not failed:
                audit("подписка выдана", f"{items[0]}: {items[1]} дн.")
            return _result(done, failed, args.json)

        if action == "revoke":
            if not items:
                cli._err(L("subs revoke UID", "subs revoke UID"))
                return FAILED
            if _need_yes(args, "Оплаченный срок будет снят.", "The paid term will be removed."):
                return NEEDS_YES
            done, failed = await adminpages.subscriptions_act(
                Form(action="revoke", uid=items[0]))
            if not failed:
                audit("подписка снята", items[0])
            return _result(done, failed, args.json)

        if action == "code-add":
            if not items:
                cli._err(L("subs code-add КОД [КОД…] [--days N]",
                           "subs code-add CODE [CODE…] [--days N]"))
                return FAILED
            done, failed = await adminpages.subscriptions_act(
                Form(action="code_add", codes="\n".join(items),
                     days=str(args.days or redeem.DEFAULT_DAYS)))
            if not failed:
                audit("коды подписки заведены", str(len(items)))
            return _result(done, failed, args.json)

        # code-drop
        if not items:
            cli._err(L("subs code-drop КОД", "subs code-drop CODE"))
            return FAILED
        done, failed = await adminpages.subscriptions_act(Form(action="code_drop", code=items[0]))
        if not failed:
            audit("код подписки удалён", items[0])
        return _result(done, failed, args.json)

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  VPN: панели, доступы, заказы, приложения
# --------------------------------------------------------------------------

VPN_ADMIN = ("panels", "panel-save", "panel-remove", "panel-check", "access", "issue",
             "deny", "extend", "on", "off", "revoke", "orders", "order-confirm",
             "order-retry", "order-cancel", "app-revoke")


def vpn_admin(args) -> int:
    from . import appapi, vpn, vpnsales, vpnslots
    from .web import adminpages

    async def run():
        action, items = args.action, args.items

        def need(count: int, usage: str) -> bool:
            if len(items) < count:
                cli._err(L("Использование: ", "Usage: ") + usage)
                return True
            return False

        if action == "panels":
            rows = []
            for number in vpnslots.numbers():
                if not vpnslots.configured(number):
                    continue
                values = vpnslots.read(number)
                rows.append({
                    "slot": number, "kind": values.get("KIND", ""),
                    "title": values.get("TITLE", ""), "url": values.get("URL", ""),
                    # Секреты не печатаем: только факт, что заданы.
                    "secret_set": any(values.get(f) for f in vpnslots.SECRET_FIELDS),
                    "issued": await vpnslots.issued_on(number)})
            cli._out(rows, args.json, lambda data: [
                print(f"#{r['slot']}  {r['kind']:<11} {r['title']:<20} {r['url']}  "
                      f"{L('выдано', 'issued')}: {r['issued']}") for r in data
            ] or print(L("панелей нет", "no panels")))
            return OK

        if action == "panel-save":
            if need(1, "vpn panel-save N --set KIND=3xui --set URL=… --set TITLE=…"):
                return FAILED
            fields, bad = pairs(args.set)
            if bad or not items[0].isdigit():
                cli._err(bad or L("Номер слота — число.", "The slot number is a number."))
                return FAILED
            unknown = [k for k in fields if k not in vpnslots.FIELDS]
            if unknown:
                cli._err(L("Нет таких полей: ", "No such fields: ") + ", ".join(unknown)
                         + " (" + ", ".join(vpnslots.FIELDS) + ")")
                return FAILED
            problem = vpnslots.save(int(items[0]), fields)
            if problem:
                cli._err(problem)
                return FAILED
            audit("VPN-панель сохранена", f"слот {items[0]}")
            print(L(f"Слот {items[0]} сохранён. Проверьте: vpn panel-check {items[0]}",
                    f"Slot {items[0]} saved. Check it: vpn panel-check {items[0]}"))
            return OK

        if action == "panel-remove":
            if need(1, "vpn panel-remove N --yes") or not items[0].isdigit():
                return FAILED
            issued = await vpnslots.issued_on(int(items[0]))
            if _need_yes(args, f"Слот {items[0]} будет освобождён (выдано на нём: {issued}; "
                               "доступы в панели останутся).",
                         f"Slot {items[0]} will be freed ({issued} issued on it; "
                         "accesses on the panel stay)."):
                return NEEDS_YES
            if not vpnslots.remove(int(items[0])):
                cli._err(L("Удалить не удалось.", "Could not remove."))
                return FAILED
            audit("VPN-панель удалена", f"слот {items[0]}")
            print(L(f"Слот {items[0]} освобождён", f"Slot {items[0]} freed"))
            return OK

        if action == "panel-check":
            if need(1, "vpn panel-check N") or not items[0].isdigit():
                return FAILED
            ok, note = await vpnslots.check(int(items[0]))
            cli._out({"slot": int(items[0]), "ok": ok, "note": note}, args.json,
                     lambda d: print(f"{'OK' if d['ok'] else 'FAIL'} #{d['slot']}: {d['note']}"))
            return OK if ok else FAILED

        if action == "access":
            if not items:
                payload = {"pending": await vpn.pending(), "issued": await vpn.issued()}
                cli._out(payload, args.json, lambda d: (
                    print(L("Заявки: ", "Requests: ") + (", ".join(d["pending"]) or "—")),
                    print(L("Выдано: ", "Issued: ") + (", ".join(d["issued"]) or "—"))))
                return OK
            entry = await vpn.record(items[0])
            results = await vpn.statuses(items[0]) if entry and entry.get("panels") else {}
            rows = {key: (vpn.describe(value) if hasattr(value, "enabled") else str(value))
                    for key, value in results.items()}
            cli._out({"uid": items[0], "panels": rows}, args.json, lambda d: [
                print(f"#{k}: {v}") for k, v in d["panels"].items()
            ] or print(L("доступ не выдан", "no access issued")))
            return OK

        if action in ("issue", "deny", "extend", "on", "off", "revoke"):
            usage = {"issue": "vpn issue UID --slot N [--slot M]", "deny": "vpn deny UID",
                     "extend": "vpn extend UID SLOT DAYS", "on": "vpn on UID SLOT",
                     "off": "vpn off UID SLOT", "revoke": "vpn revoke UID SLOT --yes"}[action]
            want = {"issue": 1, "deny": 1, "extend": 3}.get(action, 2)
            if need(want, usage):
                return FAILED
            form = Form(uid=items[0])
            if action == "issue":
                form.update(action="issue", slot=list(args.slot or []))
            elif action == "deny":
                form.update(action="deny")
            elif action == "extend":
                form.update(action="extend", slot=items[1], days=items[2])
            elif action in ("on", "off"):
                form.update(action="toggle", slot=items[1], value="1" if action == "on" else "0")
            else:
                if _need_yes(args, "Доступ будет отозван, запись в панели удалена.",
                             "Access will be revoked and the panel entry deleted."):
                    return NEEDS_YES
                form.update(action="revoke", slot=items[1])
            done, failed = await adminpages.access_act(form, CONSOLE, ROLE)
            if not failed:
                audit("VPN: " + form["action"], items[0])
            return _result(done, failed, args.json)

        if action == "orders":
            rows = [{"id": o.get("id"), "uid": o.get("uid"), "status": o.get("status"),
                     "plan": o.get("plan")} for o in await vpnsales.recent(30)]
            cli._out(rows, args.json, lambda data: [
                print(f"{str(r['id']):<12} {str(r['uid']):>12}  {r['status']}") for r in data
            ] or print(L("заказов нет", "no orders")))
            return OK

        if action in ("order-confirm", "order-retry", "order-cancel"):
            if need(1, f"vpn {action} ORDER"):
                return FAILED
            uid = ""
            if action == "order-cancel":
                found = await vpnsales.order(items[0])
                uid = str((found or {}).get("uid") or "")
            done, failed = await adminpages.access_act(
                Form(action=action.replace("-", "_"), order=items[0], uid=uid), CONSOLE, ROLE)
            if not failed:
                audit("VPN: " + action, items[0])
            return _result(done, failed, args.json)

        # app-revoke
        if need(1, "vpn app-revoke UID [--device ID]"):
            return FAILED
        count = await appapi.revoke(items[0], args.device or None)
        audit("устройство приложения отключено", items[0])
        cli._out({"uid": items[0], "revoked": count}, args.json,
                 lambda d: print(L(f"Отключено устройств: {d['revoked']}",
                                   f"Devices disconnected: {d['revoked']}")))
        return OK

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  Партнёрские проекты
# --------------------------------------------------------------------------

def cmd_partners(args) -> int:
    from . import ops, partners, promo

    async def run():
        action, items = args.action, args.items
        projects = await partners.load()

        if action == "list":
            rows = [{"slug": p.slug, "title": p.title, "url": p.url, "visible": p.visible,
                     "clicks": p.clicks, "promo": p.promo_kind} for p in
                    partners.order_projects(projects)]
            cli._out(rows, args.json, lambda data: [
                print(f"{r['slug']:<16} {'+' if r['visible'] else '-'} {r['clicks']:>5}  "
                      f"{r['title']}  {r['url']}") for r in data
            ] or print(L("проектов нет", "no projects")))
            return OK

        if not items:
            cli._err(L("Нужно короткое имя проекта (slug).", "A project slug is required."))
            return FAILED
        slug = items[0].strip().lower()
        existing = next((p for p in projects if p.slug == slug), None)

        if action == "show":
            if existing is None:
                cli._err(L("Такого проекта нет.", "No such project."))
                return FAILED
            cli._out(existing.to_dict(), args.json, lambda d: [
                print(f"{k}: {v}") for k, v in d.items()])
            return OK

        if action == "save":
            fields, bad = pairs(args.set)
            if bad:
                cli._err(bad)
                return FAILED
            # Незаданные поля остаются прежними: правка названия не должна
            # стирать описание и промокод.
            base = {k: ("" if v is None else str(v)) for k, v in
                    (existing.to_dict().items() if existing else [])}
            if existing is not None:
                base["visible"] = "1" if existing.visible else ""
            base.update(fields)
            if "visible" in fields:
                base["visible"] = "1" if fields["visible"].lower() in ("1", "true", "yes", "да") else ""
            base["slug"] = slug
            result = await ops.partner_save(Form(base))
            if result.ok:
                audit("партнёр изменён" if existing else "партнёр добавлен", slug)
            return _result(result.message if result.ok else "",
                           "" if result.ok else result.message, args.json)

        if action == "remove":
            if _need_yes(args, f"Проект «{slug}» будет удалён.", f"Project “{slug}” will be deleted."):
                return NEEDS_YES
            result = await ops.partner_remove(slug)
            if result.ok:
                audit("партнёр удалён", slug)
            return _result(result.message if result.ok else "",
                           "" if result.ok else result.message, args.json)

        # export
        rows = await promo.export_for_partner(slug)
        print(promo.render_csv(rows), end="")
        return OK

    return cli._run(cli._with_storage(run))


# --------------------------------------------------------------------------
#  Перезапуск и раздача файлов
# --------------------------------------------------------------------------

def cmd_restart(args) -> int:
    from . import ops

    if _need_yes(args, "Бот перезапустится, оповещения встанут на полминуты.",
                 "The bot will restart; alerts pause for about half a minute."):
        return NEEDS_YES
    result = cli._run(ops.restart_bot())
    if result.ok:
        audit("перезапуск бота из консоли", "")
    return _result(result.message if result.ok else "",
                   "" if result.ok else result.message, args.json)


def files_remove(args) -> int:
    from . import filedrop

    if not args.token:
        cli._err(L("Нужен токен раздачи: files remove ТОКЕН --yes.",
                   "A share token is required: files remove TOKEN --yes."))
        return FAILED
    if _need_yes(args, "Ссылка будет отключена, файл удалён.",
                 "The link will be disabled and the file deleted."):
        return NEEDS_YES
    if filedrop.remove(args.token):
        audit("ссылка на файл отключена", args.token[:8])
        print(L("Ссылка отключена, файл удалён", "Link disabled, file deleted"))
        return OK
    cli._err(L("Такой ссылки уже нет", "No such link any more"))
    return FAILED


# --------------------------------------------------------------------------
#  Разбор аргументов
# --------------------------------------------------------------------------

def register(subparsers, common) -> None:
    subs_cmd = subparsers.add_parser("subs", help=L("подписка бота и коды", "bot subscription and codes"),
                                 parents=[common])
    subs_cmd.add_argument("action", choices=["list", "codes", "grant", "revoke", "code-add", "code-drop"])
    subs_cmd.add_argument("items", nargs="*")
    subs_cmd.add_argument("--q", default="", help=L("list: искать по ключу или имени",
                                                 "list: search by key or username"))
    subs_cmd.add_argument("--days", type=int, default=0, help=L("code-add: дней на код",
                                                             "code-add: days per code"))
    subs_cmd.add_argument("--yes", action="store_true")
    subs_cmd.set_defaults(func=cmd_subs)

    partners_cmd = subparsers.add_parser("partners", help=L("партнёрские проекты", "partner projects"),
                                     parents=[common])
    partners_cmd.add_argument("action", choices=["list", "show", "save", "remove", "export"])
    partners_cmd.add_argument("items", nargs="*")
    partners_cmd.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                          help=L("save: поле проекта (title, url, description, icon, order, "
                                 "visible, promo_kind, promo_value, promo_prefix, promo_terms)",
                                 "save: a project field (title, url, description, icon, order, "
                                 "visible, promo_kind, promo_value, promo_prefix, promo_terms)"))
    partners_cmd.add_argument("--yes", action="store_true")
    partners_cmd.set_defaults(func=cmd_partners)

    restart_cmd = subparsers.add_parser("restart", help=L("перезапустить бота (через docker.sock)",
                                                      "restart the bot (through docker.sock)"),
                                    parents=[common])
    restart_cmd.add_argument("--yes", action="store_true")
    restart_cmd.set_defaults(func=cmd_restart)
