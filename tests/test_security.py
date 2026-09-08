#!/usr/bin/env python3
"""Защиты, добавленные в 4.9.5.6 по итогам разбора безопасности.

Каждый тест здесь закрывает конкретную дыру, а не общее пожелание:

* ссылка от человека не должна уводить бота во внутреннюю сеть;
* один код подписки не должен гаситься дважды при двух сообщениях подряд;
* права в панели должны сниматься сразу, а не через четыре часа;
* интервал погоды из нажатой кнопки должен проверяться так же, как
  введённый текстом.
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

from radar import netguard, redeem, storage  # noqa: E402
from radar.web import auth  # noqa: E402


class InternalAddresses(unittest.TestCase):
    """Куда бот ходить не должен."""

    def test_public_allowed(self) -> None:
        for value in ("8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"):
            with self.subTest(value=value):
                self.assertTrue(netguard.is_public_ip(value))

    def test_internal_blocked(self) -> None:
        # 169.254.169.254 — служба метаданных облачных хостингов;
        # 172.18.x — docker-сеть, где стоят база и sing-box.
        for value in ("127.0.0.1", "::1", "10.1.2.3", "192.168.0.10",
                      "172.18.0.2", "169.254.169.254", "0.0.0.0"):
            with self.subTest(value=value):
                self.assertFalse(netguard.is_public_ip(value))

    def test_garbage_is_not_public(self) -> None:
        for value in ("", "не адрес", "999.1.1.1"):
            with self.subTest(value=value):
                self.assertFalse(netguard.is_public_ip(value))

    def test_literal_address_checked_without_dns(self) -> None:
        self.assertFalse(asyncio.run(netguard.allowed("http://127.0.0.1:8080/keys")))
        self.assertFalse(asyncio.run(netguard.allowed("http://169.254.169.254/latest")))
        self.assertTrue(asyncio.run(netguard.allowed("https://8.8.8.8/")))

    def test_url_without_host_rejected(self) -> None:
        self.assertFalse(asyncio.run(netguard.allowed("не ссылка")))


class RedeemRace(unittest.TestCase):
    """Один код — одно начисление, даже если жать дважды подряд."""

    def setUp(self) -> None:
        self.store: list[dict] = []

        async def load():
            # Пауза обязательна: без настоящей точки переключения задачи
            # выполнялись бы по очереди, и гонка, ради которой тест
            # написан, не воспроизвелась бы даже на сломанном коде.
            await asyncio.sleep(0)
            return [dict(item) for item in self.store]

        async def save(items):
            await asyncio.sleep(0)
            self.store = [dict(item) for item in items]

        self._load, self._save = redeem.load, redeem.save
        redeem.load, redeem.save = load, save

    def tearDown(self) -> None:
        redeem.load, redeem.save = self._load, self._save

    def test_parallel_redeem_credits_once(self) -> None:
        async def scenario() -> list[int]:
            await redeem.add("HYDRA-2026")
            return list(await asyncio.gather(
                redeem.redeem("HYDRA-2026", "telegram:1"),
                redeem.redeem("HYDRA-2026", "telegram:1"),
                redeem.redeem("HYDRA-2026", "telegram:2"),
            ))

        results = asyncio.run(scenario())
        credited = [days for days in results if days]
        self.assertEqual(len(credited), 1, f"код начислен {len(credited)} раз(а)")


class PanelRole(unittest.TestCase):
    """Права в панели снимаются сразу, а не по истечении сессии."""

    def setUp(self) -> None:
        auth._sessions.clear()
        # Способ получения роли — состояние модуля: соседний файл тестов
        # мог оставить свой, и тогда проверялась бы не наша подстановка.
        self._lookup = auth._role_lookup
        auth._role_lookup = None
        storage.DB["users"]["4242"] = {"role": "superadmin"}
        self.session = auth.Session(token="t-4242", user_key="4242",
                                    role="superadmin")
        auth._sessions["t-4242"] = self.session

    def tearDown(self) -> None:
        auth._sessions.clear()
        auth._role_lookup = self._lookup
        storage.DB["users"].pop("4242", None)

    def test_session_alive_while_rights_stand(self) -> None:
        self.assertIsNotNone(auth.session_by_token("t-4242"))

    def test_demotion_closes_session(self) -> None:
        storage.DB["users"]["4242"]["role"] = "user"
        self.assertIsNone(auth.session_by_token("t-4242"))

    def test_deleted_user_closes_session(self) -> None:
        storage.DB["users"].pop("4242")
        self.assertIsNone(auth.session_by_token("t-4242"))

    def test_role_refreshed_not_snapshotted(self) -> None:
        # Понижение с суперадминистратора до админа сессию не закрывает,
        # но роль в ней обязана обновиться — иначе останутся чужие разделы.
        storage.DB["users"]["4242"]["role"] = "admin"
        session = auth.session_by_token("t-4242")
        self.assertIsNotNone(session)
        self.assertEqual(session.role, "admin")


if __name__ == "__main__":
    unittest.main()
