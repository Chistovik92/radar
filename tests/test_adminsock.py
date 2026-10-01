#!/usr/bin/env python3
"""Канал управления в работающий бот (с 5.9.3).

Закреплено то, из-за чего он появился: команда из консоли должна менять
память ЖИВОГО процесса, а не только базу. И то, что ломается тихо: права
сокета, отсутствие повторного выполнения при обрыве, возврат кода.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import os
import socket
import stat
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import adminsock, cli, features  # noqa: E402

UNIX = adminsock.supported()


class Routing(unittest.TestCase):
    """Какие команды идут через бота, решается до всякого сокета."""

    def parse(self, *argv):
        return cli.build_parser().parse_args(list(argv))

    def test_data_commands_go_through_bot(self):
        for argv in (["features", "on", "digest"], ["sources", "list"],
                     ["users", "list"], ["backup", "create"]):
            with self.subTest(argv=argv):
                self.assertTrue(cli._via_bot(self.parse(*argv)))

    def test_local_only_and_flags(self):
        self.assertFalse(cli._via_bot(self.parse("doctor")))
        self.assertFalse(cli._via_bot(self.parse("version")))
        self.assertFalse(cli._via_bot(self.parse("db", "copy")))
        self.assertFalse(cli._via_bot(self.parse("--local", "features", "list")))

    def test_env_forces_local(self):
        os.environ["RADAR_CLI_LOCAL"] = "1"
        try:
            self.assertFalse(cli._via_bot(self.parse("features", "list")))
        finally:
            del os.environ["RADAR_CLI_LOCAL"]

    def test_no_bot_means_direct(self):
        # Сокета нет — команда выполняется напрямую, а не падает.
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ADMIN_SOCKET"] = os.path.join(tmp, "nope.sock")
            try:
                self.assertIsNone(adminsock.call(["features", "list"]))
            finally:
                del os.environ["ADMIN_SOCKET"]


@unittest.skipUnless(UNIX, "нужны Unix-сокеты")
class Channel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = os.path.join(self.tmp.name, "admin.sock")
        os.environ["ADMIN_SOCKET"] = self.sock

    def tearDown(self):
        del os.environ["ADMIN_SOCKET"]
        self.tmp.cleanup()

    def listening(self) -> bool:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(self.sock)
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def with_server(self, scenario):
        """Поднимает сокет и гоняет сценарий (синхронный клиент — в потоке)."""
        async def go():
            task = asyncio.create_task(adminsock.serve())
            for _ in range(200):
                if await asyncio.to_thread(self.listening):
                    break
                await asyncio.sleep(0.02)
            try:
                return await asyncio.to_thread(scenario)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        return asyncio.run(go())

    def test_version_roundtrip(self):
        from radar import __version__

        code, out, _err = self.with_server(lambda: adminsock.call(["version"]))
        self.assertEqual(code, cli.OK)
        self.assertEqual(out.strip(), __version__)

    def test_socket_is_private(self):
        def check():
            return stat.S_IMODE(os.stat(self.sock).st_mode)

        self.assertEqual(self.with_server(check), 0o600)

    def test_bad_arguments_return_code_not_crash(self):
        code, _out, err = self.with_server(lambda: adminsock.call(["nonsense"]))
        self.assertNotEqual(code, cli.OK)
        self.assertTrue(err)

    def test_flag_change_lands_in_live_process(self):
        """Ради этого всё и затевалось: флаг меняется в памяти бота."""
        from radar.db import repo

        key = next(f.key for f in features.FLAGS if not f.locked)
        was = features.enabled(key)
        saved: list = []

        async def fake_set(k, v, who):
            saved.append((k, v, who))

        original = repo.set_feature
        repo.set_feature = fake_set
        try:
            features.set_local(key, not was)
            code, _o, _e = self.with_server(
                lambda: adminsock.call(["features", "on" if was is False else "off", key]))
            self.assertEqual(code, cli.OK)
            self.assertEqual(features.enabled(key), was is False)
            self.assertEqual(saved[0][0], key)
        finally:
            repo.set_feature = original
            features.set_local(key, was)

    def test_stale_socket_is_replaced(self):
        # Остался от упавшего процесса: файл есть, слушателя нет.
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(self.sock)
        dead.close()
        self.assertTrue(os.path.exists(self.sock))
        code, _out, _err = self.with_server(lambda: adminsock.call(["version"]))
        self.assertEqual(code, cli.OK)


if __name__ == "__main__":
    unittest.main(verbosity=2)
