"""Консоль: ИИ, метрики, замеры, сеть (с 5.9.9).

Продолжение `radar.cli`. Часть данных живёт только в памяти работающего
бота — счётчики квоты, замеры цикла, выбранная модель, история диалогов
ассистента, — поэтому эти команды осмысленны внутри бота (консоль передаёт
их ему через `adminsock`); без бота они говорят об этом, а не выдают нули
за правду.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
from typing import Any

from . import cli
from .cli_admin import audit
from .cli_ops import Form, _need_yes, _result, pairs
from .clitext import L
from .textutils import strip_tags

OK, FAILED, NEEDS_YES = cli.OK, cli.FAILED, cli.NEEDS_YES

AI_ACTIONS = ("status", "models", "set-model", "provider", "health", "ask", "reset",
              "bench", "agents", "agent-save", "agent-remove", "agent-model")


def _live_only() -> bool:
    """True — команда не выполнена: нужен работающий бот."""
    if cli.in_bot():
        return False
    cli._err(L("Эти данные живут в памяти работающего бота. Запустите его и повторите.",
               "This data lives in the running bot's memory. Start it and repeat."))
    return True


def cmd_ai(args) -> int:
    from . import agents, ai, aibench, ops, provider, secrets

    async def run():
        action, items = args.action, args.items

        if action == "status":
            payload = {"counters": ai.counters(), "quota": ai.quota_snapshot(),
                       "models": ai.models_report(), "provider": provider.current(),
                       "enabled": bool(ai.ENABLED), "live": cli.in_bot()}
            cli._out(payload, args.json, lambda d: (
                print(L("ИИ: ", "AI: ") + (L("включён", "on") if d["enabled"] else
                                            L("выключен (эвристика)", "off (heuristics)"))),
                print(L("Провайдер разбора: ", "Analysis provider: ") + str(d["provider"])),
                print(L("Модель ассистента: ", "Assistant model: ") + d["models"]["assistant"]),
                print(L("Модель разбора: ", "Analysis model: ") + d["models"]["analysis"]),
                print(L("Запросов: ", "Requests: ") + str(d["counters"].get("requests", 0))
                      + (L("", "") if d["live"] else
                         L("  (счётчики — только у запущенного бота)",
                           "  (counters exist only in a running bot)")))))
            return OK

        if action == "models":
            if args.refresh:
                if _live_only():
                    return FAILED
                await ai.discover_models()
            report = ai.models_report()
            cli._out(report, args.json, lambda d: (
                print(L("Ассистент: ", "Assistant: ") + d["assistant"]),
                print(L("Разбор новостей: ", "News analysis: ") + d["analysis"]),
                print(L("Доступно ключу: ", "Available to the key: ")
                      + (", ".join(m for m in d["available"] if "gemini" in m) or "—")),
                print(L("Отключены ключом: ", "Disabled by the key: ")
                      + (", ".join(d["unavailable"]) or "—"))))
            return OK

        if action == "set-model":
            if not items:
                cli._err(L("ai set-model ИМЯ [--target assistant|analysis]",
                           "ai set-model NAME [--target assistant|analysis]"))
                return FAILED
            if _live_only():
                return FAILED
            result = await ops.pin_model(items[0], args.target)
            if result.ok:
                audit("модель закреплена", items[0])
            return _result(result.message if result.ok else "",
                           "" if result.ok else result.message, args.json)

        if action == "provider":
            infos = provider.all_infos()
            if items:
                if not provider.select(items[0]):
                    cli._err(L("Нет такого провайдера или не задан его ключ.",
                               "No such provider, or its key is not set."))
                    return FAILED
                audit("провайдер выбран", items[0])
                print(L(f"Провайдер: {items[0]}", f"Provider: {items[0]}"))
                return OK
            active = provider.current()
            rows = [{"key": i.key, "title": i.title, "configured": bool(secrets.get(i.env)),
                     "active": i.key == active} for i in infos.values()]
            cli._out(rows, args.json, lambda data: [
                print(f"{'*' if r['active'] else ' '} {r['key']:<12} {r['title']:<28}"
                      f" {L('ключ есть', 'key set') if r['configured'] else '—'}") for r in data])
            return OK

        if action == "health":
            results = await (provider.check(items[0]) if items else provider.check_all())
            if items:
                results = {items[0]: results}
            payload = {k: {"ok": v.ok, "balance": v.balance, "detail": v.detail}
                       for k, v in results.items()}
            cli._out(payload, args.json, lambda d: [
                print(f"{'OK  ' if v['ok'] else 'FAIL'} {k}: {v['balance'] or v['detail']}")
                for k, v in d.items()])
            return OK if all(v.ok for v in results.values()) else FAILED

        if action == "ask":
            if not items:
                cli._err(L("ai ask ВОПРОС…", "ai ask QUESTION…"))
                return FAILED
            if not ai.ENABLED and not provider.available():
                cli._err(L("ИИ недоступен: не задан ни один ключ провайдера.",
                           "AI is unavailable: no provider key is set."))
                return FAILED
            try:
                answer = await ai.assistant([], " ".join(items))
            except ai.AIError as exc:
                cli._err(L(f"Ошибка ИИ: {exc}", f"AI error: {exc}"))
                return FAILED
            cli._out({"answer": answer}, args.json, lambda d: print(d["answer"]))
            return OK

        if action == "reset":
            if not items:
                cli._err(L("ai reset UID", "ai reset UID"))
                return FAILED
            if _live_only():
                return FAILED
            from .handlers import assistant

            had = assistant._history.pop(str(items[0]), None) is not None
            print(L("Контекст очищен." if had else "Контекста не было.",
                    "Context cleared." if had else "There was no context."))
            return OK

        if action == "bench":
            if _live_only():
                return FAILED
            ready = aibench.configured_providers()
            if not ready:
                cli._err(L("Нет провайдеров с ключами.", "No providers with keys."))
                return FAILED
            if aibench.is_running():
                cli._err(L("Проверка уже идёт.", "A check is already running."))
                return FAILED
            if _need_yes(args, f"Проверка {len(ready)} провайдеров займёт несколько минут "
                               "и потратит их квоту.",
                         f"Checking {len(ready)} providers takes minutes and spends their quota."):
                return NEEDS_YES
            report = await aibench.run()
            print(strip_tags(aibench.render(report)))
            return OK

        if action == "agents":
            rows = [{"slot": a.slot, "title": a.shown, "url": a.url, "model": a.model,
                     "ready": a.ready, "key_set": bool(a.key)} for a in agents.load()]
            cli._out(rows, args.json, lambda data: [
                print(f"#{r['slot']} {r['title']:<24} {r['url']}  "
                      f"{L('готов', 'ready') if r['ready'] else L('не готов', 'not ready')}")
                for r in data] or print(L("агентов нет", "no agents")))
            return OK

        if action == "agent-save":
            fields, bad = pairs(args.set)
            if bad or not items:
                cli._err(bad or L("ai agent-save СЛОТ --set title=… --set url=… --set key=… "
                                  "[--set model=…]",
                                  "ai agent-save SLOT --set title=… --set url=… --set key=… "
                                  "[--set model=…]"))
                return FAILED
            result = await ops.agent_save(Form(slot=items[0], **fields))
            if result.ok:
                audit("свой агент сохранён", f"слот {result.extra}")
            return _result(result.message if result.ok else "",
                           "" if result.ok else result.message, args.json)

        if action == "agent-remove":
            if not items:
                cli._err(L("ai agent-remove СЛОТ --yes", "ai agent-remove SLOT --yes"))
                return FAILED
            if _need_yes(args, f"Агент в слоте {items[0]} будет удалён вместе с ключом.",
                         f"The agent in slot {items[0]} will be deleted with its key."):
                return NEEDS_YES
            result = await ops.agent_remove(items[0])
            if result.ok:
                audit("свой агент удалён", f"слот {result.extra}")
            return _result(result.message if result.ok else "",
                           "" if result.ok else result.message, args.json)

        # agent-model
        if len(items) < 2:
            cli._err(L("ai agent-model ПРОВАЙДЕР МОДЕЛЬ", "ai agent-model PROVIDER MODEL"))
            return FAILED
        result = await ops.agent_model(items[0], items[1])
        if result.ok:
            audit("модель провайдера изменена", result.extra)
        return _result(result.message if result.ok else "",
                       "" if result.ok else result.message, args.json)

    return cli._run(cli._with_storage(run))


def cmd_metrics(args) -> int:
    from . import metrics

    async def run():
        data = await metrics.snapshot()
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        else:
            print(strip_tags(metrics.render(data)))
        return OK

    return cli._run(run())


def cmd_perf(args) -> int:
    from . import profiling

    if _live_only():
        return FAILED
    if args.reset:
        profiling.reset()
        audit("замеры сброшены", "")
        print(L("Счётчики сброшены.", "Counters reset."))
        return OK
    from .handlers import perf

    stages = {key: {"calls": s.calls, "average": s.average, "worst": s.worst,
                    "last": s.last, "total": s.total}
              for key, s in profiling.snapshot().items()}
    cli._out(stages, args.json, lambda _d: print(strip_tags(perf._report())))
    return OK


def cmd_net(args) -> int:
    from . import proxy
    from .handlers import network

    text = strip_tags(proxy.describe(network._load_state()))
    cli._out({"status": text}, args.json, lambda d: print(d["status"]))
    return OK


def register(subparsers, common) -> None:
    ai_cmd = subparsers.add_parser("ai", help=L("ИИ: модели, провайдер, агенты, квота",
                                                "AI: models, provider, agents, quota"),
                                   parents=[common])
    ai_cmd.add_argument("action", choices=AI_ACTIONS)
    ai_cmd.add_argument("items", nargs="*")
    ai_cmd.add_argument("--refresh", action="store_true",
                        help=L("models: запросить список у провайдера",
                               "models: ask the provider for the list"))
    ai_cmd.add_argument("--target", default="assistant", choices=["assistant", "analysis"],
                        help=L("set-model: для ассистента или для разбора новостей",
                               "set-model: for the assistant or for news analysis"))
    ai_cmd.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                        help=L("agent-save: title, url, key, model",
                               "agent-save: title, url, key, model"))
    ai_cmd.add_argument("--yes", action="store_true")
    ai_cmd.set_defaults(func=cmd_ai)

    metrics_cmd = subparsers.add_parser("metrics", help=L("метрики и здоровье системы",
                                                          "system metrics and health"),
                                        parents=[common])
    metrics_cmd.set_defaults(func=cmd_metrics)

    perf_cmd = subparsers.add_parser("perf", help=L("время цикла по стадиям и ресурсы",
                                                    "cycle timing by stage and resources"),
                                     parents=[common])
    perf_cmd.add_argument("--reset", action="store_true",
                          help=L("сбросить счётчики", "reset the counters"))
    perf_cmd.set_defaults(func=cmd_perf)

    net_cmd = subparsers.add_parser("net", help=L("выход в сеть и прокси: состояние",
                                                  "egress and proxy: status"),
                                    parents=[common])
    net_cmd.set_defaults(func=cmd_net)
