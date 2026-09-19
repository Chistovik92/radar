#!/usr/bin/env python3
"""Исправления 4.9.9.2: каждое — случай с живого сервера.

* пересказ прошедшей ракетной опасности уходил тревогой;
* памятка ЖКХ приходила как авария;
* картинки из записи «искались» вечно;
* сетевая проверка ссылок не работала с 4.9.4 и выглядела как «чисто»;
* чаты со своей ссылкой не были видны пользователям.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from multitool.linkcheck import netcheck, report  # noqa: E402
from multitool.linkcheck.analyze import NetResult, Verdict  # noqa: E402
from radar import chatlink, images, matching  # noqa: E402
from radar.matching import Analysis  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def threat(raw: str, **extra) -> Analysis:
    """Разбор, каким его вернула бы модель, не заметившая прошлого."""
    payload = {
        "relevant": True, "categories": ["bpla"], "severity": "critical",
        "scope": "city", "city": "Саратов", "summary": raw[:200],
    }
    payload.update(extra)
    return Analysis.from_payload(payload, source="news", raw=raw)


class PastThreatTests(unittest.TestCase):
    """Новость о прошедшей опасности — сводка, а не тревога."""

    def test_past_announcement_is_historical(self):
        for raw in (
            "Вечером в Саратове была объявлена ракетная опасность.",
            "Ракетная опасность действовала с 21:10 до 22:40.",
            "Ночью в области объявлялась ракетная опасность.",
            "В регионе вводилась беспилотная опасность, сообщает ТАСС.",
            "Ранее в городе была введена ракетная опасность.",
        ):
            self.assertTrue(threat(raw).historical, raw)

    def test_live_announcement_stays_alert(self):
        for raw in (
            "Внимание! В Саратове введена ракетная опасность.",
            "Объявлена ракетная опасность. Пройдите в укрытие.",
            "Ракетная опасность действует, оставайтесь в укрытии.",
        ):
            self.assertFalse(threat(raw).historical, raw)

    def test_live_cue_beats_past_tense(self):
        """Прошедшее время рядом с призывом укрыться — опасность ещё
        действует. Ошибиться здесь в сторону тишины хуже, чем наоборот."""
        raw = ("Ракетная опасность была объявлена в 21:10. "
               "Оставайтесь в укрытии до отбоя.")
        self.assertFalse(threat(raw).historical)

    def test_past_threat_goes_to_recap_not_alert(self):
        item = threat("Ракетная опасность действовала с 21:10 до 22:40.")
        location = {"id": "1", "name": "Дом", "city": "Саратов",
                    "lat": 51.53, "lon": 46.03}
        messages = matching.plan_alerts([location], {"bpla": True}, [item],
                                        1000, "Саратов")
        self.assertEqual(messages, [])


class GuidanceTests(unittest.TestCase):
    """Памятка — целиком, со ссылкой, без «опасности»."""

    RAW = ("Памятка жителям: что делать при прорыве трубы, запахе газа "
           "или проблемах с проводкой. Номера аварийных служб: 04, 112.")

    def _jkh(self, **extra):
        payload = {"relevant": True, "categories": ["jkh"],
                   "severity": "warning", "scope": "street", "city": "Саратов",
                   "streets": [{"street": "Детский проезд", "houses": ["55"]}],
                   "summary": "Инструкция о действиях при авариях"}
        payload.update(extra)
        return Analysis.from_payload(payload, source="komgkhsar64",
                                     raw=self.RAW)

    def test_detected_without_model(self):
        item = self._jkh()
        self.assertTrue(item.guidance)
        self.assertEqual(item.scope, "city")
        self.assertEqual(item.streets, [])

    def test_model_flag_trusted(self):
        item = Analysis.from_payload(
            {"relevant": True, "categories": ["jkh"], "guidance": True,
             "city": "Саратов"},
            source="x", raw="Любой текст без ключевых слов")
        self.assertTrue(item.guidance)

    def test_message_is_calm_and_complete(self):
        text = matching.build_guidance(self._jkh())
        self.assertIn("Памятка", text)
        self.assertNotIn("ОПАСНОСТЬ", text)
        self.assertNotIn("ЖКХ и аварии", text)
        self.assertIn("Номера аварийных служб: 04, 112", text)
        self.assertIn("https://t.me/komgkhsar64", text)

    def test_delivered_as_guidance(self):
        location = {"id": "1", "name": "Дом", "city": "Саратов",
                    "lat": 51.53, "lon": 46.03}
        messages = matching.plan_alerts([location], {"jkh": True},
                                        [self._jkh()], 1000, "Саратов")
        self.assertEqual([kind for kind, _ in messages], ["guidance"])

    def test_live_emergency_is_not_guidance(self):
        """Порядок действий внутри живого оповещения памяткой не делает."""
        raw = ("Внимание! Ракетная опасность. Порядок действий: "
               "пройдите в укрытие.")
        self.assertFalse(threat(raw).guidance)

    def test_post_link_preferred(self):
        item = self._jkh()
        item.link = "https://t.me/komgkhsar64/1234"
        self.assertEqual(matching.source_link(item),
                         "https://t.me/komgkhsar64/1234")


class ChannelLinkTests(unittest.TestCase):
    """У поста из канала теперь есть ссылка на оригинал."""

    def test_post_link_parsed(self):
        from radar import sources

        # Разбор идёт через настоящий BeautifulSoup. В офлайн-окружении
        # вместо него заглушка stubcheck, и проверять на ней нечего.
        if not hasattr(sources.BeautifulSoup, "find_all") and \
                getattr(sources.BeautifulSoup, "__module__", "") != "bs4":
            self.skipTest("bs4 не установлен")

        page = (
            '<div class="tgme_widget_message" data-post="komgkhsar64/1234">'
            '<div class="tgme_widget_message_text">'
            "Плановое отключение воды на улице Чапаева с 10 до 16 часов."
            "</div></div>"
        )
        items = sources.parse_channel(page, "komgkhsar64", 10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].link, "https://t.me/komgkhsar64/1234")


class ImageCollectTests(unittest.TestCase):
    """Картинки качаются параллельно, по порядку, без падений."""

    def test_order_kept_and_failures_skipped(self):
        async def fake_fetch(_session, link, _limit):
            await asyncio.sleep(0.01 if link.endswith("1.jpg") else 0)
            if "bad" in link:
                return b"", "не вышло"
            return link.encode(), ""

        links = ["https://a/1.jpg", "https://a/bad.jpg", "https://a/3.jpg"]
        with mock.patch.object(images, "fetch", fake_fetch):
            got = run(images.download_all(None, links, 10))
        self.assertEqual([data for data, _ in got],
                         [b"https://a/1.jpg", b"https://a/3.jpg"])

    def test_parallel_limit_respected(self):
        state = {"now": 0, "peak": 0}

        async def fake_fetch(_session, link, _limit):
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.01)
            state["now"] -= 1
            return b"x", ""

        links = [f"https://a/{i}.jpg" for i in range(12)]
        with mock.patch.object(images, "fetch", fake_fetch):
            run(images.download_all(None, links, 10, parallel=3))
        self.assertLessEqual(state["peak"], 3)

    def test_budget_is_bounded(self):
        self.assertLessEqual(images.TOTAL_BUDGET, 180)
        self.assertLess(images.REQUEST_TIMEOUT, images.TOTAL_BUDGET)

    def test_notice_edit_cannot_crash(self):
        """«message is not modified» больше не роняет поиск картинок."""
        from aiogram.exceptions import TelegramBadRequest

        from radar.handlers import media as media_handlers

        class Notice:
            async def edit_text(self, _text):
                raise TelegramBadRequest("message is not modified")

        run(media_handlers._edit_quietly(Notice(), "текст"))


class LinkCheckTests(unittest.TestCase):
    """Сетевая часть проверки ссылок."""

    def test_session_is_not_coroutine(self):
        """Корутина не бывает контекстным менеджером: с 4.9.4 по 4.9.9.1
        из-за этого каждая сетевая проверка кончалась TypeError."""
        self.assertFalse(inspect.iscoroutinefunction(netcheck._session))

    def test_unchecked_is_not_shown_as_clean(self):
        verdict = Verdict(url="https://example.com",
                          net=NetResult(success=False, notes=["timeout"]))
        text = report.build_report(verdict)
        self.assertNotIn("✅", text)
        self.assertIn("не определён", text)
        self.assertIn("сайт не ответил вовремя", text)

    def test_notes_humanized(self):
        self.assertIn("ключ", report.humanize_note("no api key"))
        self.assertIn("DNS", report.humanize_note("dns failed"))
        self.assertEqual(report.humanize_note("что-то новое"), "что-то новое")

    def test_safe_browsing_key_not_in_url(self):
        source = inspect.getsource(netcheck.safe_browsing)
        self.assertNotIn("?key=", source)
        self.assertIn("X-Goog-Api-Key", source)

    def test_certificate_read_via_peercert(self):
        source = inspect.getsource(netcheck.cert_info)
        self.assertIn('"peercert"', source)
        self.assertNotIn(".getpeercert(", source)


class PublishedChatsTests(unittest.TestCase):
    """В меню пользователей — только чаты со своей ссылкой."""

    def tearDown(self) -> None:
        chatlink._published.clear()

    def test_only_manual_links_published(self):
        async def rows():
            return [
                {"chat_id": -1, "title": "Двор", "invite": "https://t.me/+abc"},
                {"chat_id": -2, "title": "Закрытый", "invite": ""},
                {"chat_id": -3, "title": "Битый", "invite": "javascript:x"},
            ]

        with mock.patch("radar.db.repo.chat_list", rows):
            count = run(chatlink.refresh_published())
        self.assertEqual(count, 1)
        self.assertEqual(chatlink.published(),
                         [(-1, "Двор", "https://t.me/+abc")])

    def test_menu_button_follows_list(self):
        from radar import keyboards

        def has_button(markup):
            return any(button.callback_data == "grp:list"
                       for row in markup.inline_keyboard for button in row)

        chatlink._published.clear()
        self.assertFalse(has_button(keyboards.main_menu("user", {})))
        chatlink._published.append((-1, "Двор", "https://t.me/+abc"))
        self.assertTrue(has_button(keyboards.main_menu("user", {})))


if __name__ == "__main__":
    unittest.main()
