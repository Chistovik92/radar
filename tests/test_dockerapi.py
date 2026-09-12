#!/usr/bin/env python3
"""Общий клиент Docker Engine API (4.9.8.4): демультиплексирование потока
`docker exec`, exec_run, container_action.

Вынесен из radar/updater.py, когда radar/rustdesk.py понадобились ровно
те же операции над ЧУЖИМ контейнером — здесь закреплён именно протокольный
разбор (заголовки кадров), потому что ошибиться в нём тихо и легко:
неверная длина кадра оставляет мусорные байты в выводе команды.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import dockerapi  # noqa: E402
from tests._fakedocker import FakeResponse, FakeSession  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def frame(payload: bytes, stream: int = 1) -> bytes:
    """Один кадр мультиплексированного потока docker exec без TTY."""
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


class TestDemux(unittest.TestCase):
    def test_single_frame(self):
        raw = frame(b"hello\n")
        self.assertEqual(dockerapi._demux(raw), "hello\n")

    def test_multiple_frames_concatenate(self):
        raw = frame(b"line one\n") + frame(b"line two\n", stream=2)
        self.assertEqual(dockerapi._demux(raw), "line one\nline two\n")

    def test_empty_stream(self):
        self.assertEqual(dockerapi._demux(b""), "")

    def test_truncated_trailing_bytes_ignored(self):
        # Меньше 8 байт хвоста — не полноценный заголовок, отбрасывается.
        raw = frame(b"ok\n") + b"\x01\x00\x00"
        self.assertEqual(dockerapi._demux(raw), "ok\n")


class TestExecRun(unittest.TestCase):
    def test_success(self):
        session = FakeSession({
            ("POST", "/containers/hbbs/exec"): FakeResponse(200, {"Id": "exec1"}),
            ("POST", "/exec/exec1/start"): FakeResponse(200, frame(b"content\n")),
        })
        ok, out = run(dockerapi.exec_run(session, "hbbs", ["cat", "/tmp/x"]))
        self.assertTrue(ok, out)
        self.assertEqual(out, "content\n")

    def test_container_not_found(self):
        session = FakeSession({
            ("POST", "/containers/ghost/exec"): FakeResponse(
                404, {"message": "No such container: ghost"}
            ),
        })
        ok, reason = run(dockerapi.exec_run(session, "ghost", ["cat", "/tmp/x"]))
        self.assertFalse(ok)
        self.assertIn("ghost", reason)

    def test_start_failure_reported(self):
        session = FakeSession({
            ("POST", "/containers/hbbs/exec"): FakeResponse(200, {"Id": "exec1"}),
            ("POST", "/exec/exec1/start"): FakeResponse(500, "internal error"),
        })
        ok, reason = run(dockerapi.exec_run(session, "hbbs", ["cat", "/tmp/x"]))
        self.assertFalse(ok)
        self.assertIn("internal error", reason)

    def test_missing_exec_id_reported(self):
        session = FakeSession({
            ("POST", "/containers/hbbs/exec"): FakeResponse(200, {}),
        })
        ok, reason = run(dockerapi.exec_run(session, "hbbs", ["cat", "/tmp/x"]))
        self.assertFalse(ok)
        self.assertTrue(reason)


class TestContainerAction(unittest.TestCase):
    def test_restart_success(self):
        session = FakeSession({
            ("POST", "/containers/hbbs/restart"): FakeResponse(204),
        })
        ok, reason = run(dockerapi.container_action(session, "hbbs", "restart"))
        self.assertTrue(ok, reason)

    def test_not_found(self):
        session = FakeSession({
            ("POST", "/containers/ghost/stop"): FakeResponse(404),
        })
        ok, reason = run(dockerapi.container_action(session, "ghost", "stop"))
        self.assertFalse(ok)
        self.assertIn("ghost", reason)

    def test_unknown_action_rejected_before_any_request(self):
        session = FakeSession({})
        ok, reason = run(dockerapi.container_action(session, "hbbs", "delete"))
        self.assertFalse(ok)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
