#!/usr/bin/env python3
"""Бот в группе не должен вести себя как в личной переписке (с 4.9.8.11).

До этого выпуска добавление бота в группу означало: «Доступ к системе
закрыт» каждому участнику раз в десять минут, регистрация знакомых
как пользователей бота, вопрос о языке в общем чате и — хуже всего —
ИИ-ассистент, отвечающий на ЛЮБОЙ текст, потому что его обработчик
ловит `F.text` без фильтра чата.

Здесь закреплён инвариант, а не текст: каждый личный роутер обязан
получить фильтр личного чата, а групповой — фильтр группы.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class Routing(unittest.TestCase):
    def setUp(self) -> None:
        self.source = read("radar", "handlers", "__init__.py")

    def test_private_filter_is_applied_centrally(self):
        # Одним местом, а не двадцатью декораторами: иначе новый раздел
        # рано или поздно окажется без фильтра.
        self.assertIn('module.router.message.filter(F.chat.type == "private")',
                      self.source)

    def test_group_router_is_group_only(self):
        self.assertIn('group.router.message.filter(', self.source)
        self.assertIn('"group", "supergroup"', self.source)

    def test_every_included_router_is_in_the_private_list(self):
        # Роутер, подключённый в обход списка, остался бы без фильтра.
        included = set(re.findall(r"dp\.include_router\((\w+)\.router\)",
                                  self.source))
        listed = set(re.findall(r"^\s{4}(\w+),", self.source, re.M))
        # «group» подключается отдельно и намеренно, «module» — переменная
        # цикла, который как раз и навешивает фильтр на весь список.
        for name in included - {"group", "module"}:
            with self.subTest(router=name):
                self.assertIn(name, listed)

    def test_group_router_goes_first(self):
        group_at = self.source.index("dp.include_router(group.router)")
        loop_at = self.source.index("for module in PRIVATE_ROUTERS")
        self.assertLess(group_at, loop_at)


class Middleware(unittest.TestCase):
    def setUp(self) -> None:
        self.source = read("radar", "middlewares.py")

    def test_non_private_chats_skip_registration(self):
        early = self.source.index('!= "private"')
        register = self.source.index("storage.register")
        self.assertLess(early, register)

    def test_access_denied_is_not_sent_to_groups(self):
        early = self.source.index('!= "private"')
        denied = self.source.index("Доступ к системе")
        self.assertLess(early, denied)


class Assistant(unittest.TestCase):
    def test_catch_all_still_exists_and_is_now_fenced(self):
        # Сам перехват текста остаётся — он нужен в личной переписке.
        # Важно, что теперь он огорожен фильтром чата на уровне setup().
        self.assertIn("@router.message(F.text)",
                      read("radar", "handlers", "assistant.py"))
        self.assertIn("assistant,", read("radar", "handlers", "__init__.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
