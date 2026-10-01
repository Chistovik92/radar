#!/usr/bin/env python3
"""Консоль: ИИ, метрики, замеры, сеть (с 5.9.9).

Проверяется, что команды живых данных не выдают нули за правду вне бота,
не печатают ключи, не делают разрушающего без --yes и зовут общие с панелью
функции (`ops`).
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import agents, ai, aibench, cli, ops, provider, secrets  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "tests"))
from test_cli_ops import Store  # noqa: E402


def run(argv, in_bot=False):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        if in_bot:
            # Как в боте: цикл крутится в своём потоке, команда — в другом.
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()
            cli.attach(loop)
            try:
                code = cli.main(["--local", "--lang", "en"] + argv)
            finally:
                cli.attach(None)
                loop.call_soon_threadsafe(loop.stop)
                thread.join(2)
                loop.close()
        else:
            code = cli.main(["--local", "--lang", "en"] + argv)
    return code, out.getvalue(), err.getvalue()


def agent(slot=1, key="SECRETKEY"):
    return agents.Agent(slot=slot, title="Mine", url="https://llm.example/v1", key=key, model="m1")


class Status(unittest.TestCase):
    def test_status_outside_bot_says_counters_are_bot_only(self):
        with Store():
            code, out, _ = run(["ai", "status", "--json"])
            _, plain, _ = run(["ai", "status"])
        self.assertEqual(code, cli.OK)
        data = json.loads(out)
        self.assertFalse(data["live"])
        self.assertIn("running bot", plain)

    def test_live_only_commands_refuse_outside_bot(self):
        with Store():
            for argv in (["ai", "reset", "7"], ["ai", "set-model", "gemini-x"],
                         ["ai", "models", "--refresh"], ["ai", "bench", "--yes"], ["perf"]):
                with self.subTest(argv=argv):
                    code, _o, err = run(argv)
                    self.assertEqual(code, cli.FAILED)
                    self.assertIn("running bot", err)


class Models(unittest.TestCase):
    def test_models_listing(self):
        with Store(), mock.patch.object(ai, "models_report", lambda: {
                "assistant": "g-a", "analysis": "g-b", "available": ["gemini-1", "other"],
                "unavailable": ["gemini-0"]}):
            code, out, _ = run(["ai", "models"])
        self.assertEqual(code, cli.OK)
        self.assertIn("gemini-1", out)
        self.assertNotIn("other", out)                      # как в боте — только Gemini

    def test_set_model_uses_the_shared_rule(self):
        pinned = []
        with Store(), mock.patch.object(ai, "models_report", lambda: {"available": ["ok-model"]}), \
                mock.patch.object(ai, "pin_model", lambda role, name: pinned.append((role, name)) or True):
            self.assertEqual(run(["ai", "set-model", "bad"], in_bot=True)[0], cli.FAILED)
            self.assertEqual(pinned, [])                         # недоступную не закрепляем
            code, out, _ = run(["ai", "set-model", "ok-model", "--target", "analysis"], in_bot=True)
        self.assertEqual(code, cli.OK)
        self.assertEqual(pinned, [(ai.ANALYSIS, "ok-model")])

    def test_ops_pin_matches_the_bot_command(self):
        with mock.patch.object(ai, "models_report", lambda: {"available": []}), \
                mock.patch.object(ai, "pin_model", lambda role, name: True):
            result = asyncio.run(ops.pin_model("anything", "assistant"))
        self.assertTrue(result.ok)                             # список неизвестен — не мешаем


class Providers(unittest.TestCase):
    def test_provider_list_never_prints_keys(self):
        with Store(), mock.patch.object(
                secrets, "get", lambda k: "TOPSECRETVALUE" if k.endswith("_KEY") else ""):
            code, out, _ = run(["ai", "provider", "--json"])
            plain = run(["ai", "provider"])[1]
            expected = len(provider.all_infos())
        self.assertEqual(code, cli.OK)
        self.assertNotIn("TOPSECRETVALUE", out + plain)
        self.assertEqual(len(json.loads(out)), expected)

    def test_provider_select(self):
        chosen = []
        with Store(), mock.patch.object(provider, "select", lambda n: chosen.append(n) or n == "gemini"):
            self.assertEqual(run(["ai", "provider", "gemini"])[0], cli.OK)
            self.assertEqual(run(["ai", "provider", "nope"])[0], cli.FAILED)
        self.assertEqual(chosen, ["gemini", "nope"])


class Agents(unittest.TestCase):
    def test_list_hides_key(self):
        with Store(), mock.patch.object(agents, "load", lambda: [agent()]):
            code, out, _ = run(["ai", "agents", "--json"])
            plain = run(["ai", "agents"])[1]
        self.assertEqual(code, cli.OK)
        self.assertNotIn("SECRETKEY", out + plain)
        self.assertTrue(json.loads(out)[0]["key_set"])

    def test_save_keeps_old_key_when_empty(self):
        saved = []
        with Store(), mock.patch.object(agents, "load", lambda: [agent()]), \
                mock.patch.object(agents, "save", lambda *a: saved.append(a) or True):
            code, _o, _e = run(["ai", "agent-save", "1", "--set", "title=New",
                                "--set", "url=https://llm.example/v2"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(saved[0], (1, "New", "https://llm.example/v2", "SECRETKEY", ""))

    def test_save_validates(self):
        with Store(), mock.patch.object(agents, "save", lambda *a: True):
            self.assertEqual(run(["ai", "agent-save", "1", "--set", "url=ftp://x"])[0], cli.FAILED)
            self.assertEqual(run(["ai", "agent-save", "abc", "--set", "url=https://x.y"])[0], cli.FAILED)
            self.assertEqual(run(["ai", "agent-save"])[0], cli.FAILED)
            self.assertEqual(run(["ai", "agent-save", "1", "--set", "oops"])[0], cli.FAILED)

    def test_remove_needs_yes(self):
        forgotten = []
        with Store(), mock.patch.object(agents, "forget", lambda s: forgotten.append(s) or True):
            self.assertEqual(run(["ai", "agent-remove", "2"])[0], cli.NEEDS_YES)
            self.assertEqual(forgotten, [])
            self.assertEqual(run(["ai", "agent-remove", "2", "--yes"])[0], cli.OK)
        self.assertEqual(forgotten, [2])

    def test_agent_model(self):
        with Store(), mock.patch.object(provider, "set_model", lambda n, m: True):
            self.assertEqual(run(["ai", "agent-model", "gemini", "m2"])[0], cli.OK)
            self.assertEqual(run(["ai", "agent-model", "no-such", "m2"])[0], cli.FAILED)
            self.assertEqual(run(["ai", "agent-model", "gemini"])[0], cli.FAILED)


class Observability(unittest.TestCase):
    def test_bench_needs_yes_and_keys(self):
        with Store(), mock.patch.object(aibench, "configured_providers", lambda: []):
            self.assertEqual(run(["ai", "bench", "--yes"], in_bot=True)[0], cli.FAILED)
        with Store(), mock.patch.object(aibench, "configured_providers", lambda: [object()]), \
                mock.patch.object(aibench, "is_running", lambda: False):
            self.assertEqual(run(["ai", "bench"], in_bot=True)[0], cli.NEEDS_YES)

    def test_ask_refuses_without_providers(self):
        with Store(), mock.patch.object(ai, "ENABLED", False), \
                mock.patch.object(provider, "available", lambda: []):
            code, _o, err = run(["ai", "ask", "hello"])
        self.assertEqual(code, cli.FAILED)
        self.assertIn("no provider key", err)

    def test_metrics_strips_markup(self):
        from radar import metrics

        async def snapshot():
            return {"x": 1}

        with Store(), mock.patch.object(metrics, "snapshot", snapshot), \
                mock.patch.object(metrics, "render", lambda d: "🩺 <b>Metrics</b>\nok"):
            code, out, _ = run(["metrics"])
            code_json, out_json, _ = run(["metrics", "--json"])
        self.assertEqual(code, cli.OK)
        self.assertNotIn("<b>", out)
        self.assertEqual(json.loads(out_json), {"x": 1})

    def test_perf_in_bot_and_reset(self):
        from radar import profiling

        reset = []
        with Store(), mock.patch.object(profiling, "reset", lambda: reset.append(1)):
            code, out, _ = run(["perf", "--reset"], in_bot=True)
        self.assertEqual(code, cli.OK)
        self.assertEqual(reset, [1])

    def test_net_status(self):
        from radar import proxy
        from radar.handlers import network

        with Store(), mock.patch.object(network, "_load_state", lambda: object()), \
                mock.patch.object(proxy, "describe", lambda s: "🌐 <b>Direct</b> connection"):
            code, out, _ = run(["net"])
        self.assertEqual(code, cli.OK)
        self.assertEqual(out.strip(), "🌐 Direct connection")


class Parsing(unittest.TestCase):
    def test_subcommands_parse(self):
        parser = cli.build_parser()
        for argv in (["ai", "status"], ["ai", "set-model", "m", "--target", "analysis"],
                     ["ai", "agent-save", "1", "--set", "a=b"], ["metrics"], ["perf", "--reset"],
                     ["net"]):
            with self.subTest(argv=argv):
                self.assertTrue(callable(parser.parse_args(argv).func))

    def test_parity_progress(self):
        import lint_cli_parity

        done = sum(1 for v in {**lint_cli_parity.BOT, **lint_cli_parity.PANEL}.values()
                   if v.startswith("cli:"))
        self.assertGreaterEqual(done, 72)


if __name__ == "__main__":
    unittest.main(verbosity=2)
