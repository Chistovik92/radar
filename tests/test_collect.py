#!/usr/bin/env python3
"""Параллельный обход источников.

Замер на живом сервере (4.7.6.5, RK3318, 35 источников) показал:
стадия «Сбор источников» — 51 секунда при интервале цикла 180, то есть
больше четверти времени; процессорное время за 21 минуту наблюдения —
2 мин 50 с, средняя нагрузка 0.07 на четырёх ядрах. Машина простаивала,
ожидая сеть по одному источнику за раз.

Отчёт `/perf` при этом заключал, что «сбор упирается в сеть, а не
в скорость кода» — верно по букве и обманчиво по сути: последовательное
ожидание лечится не ускорением кода, а наложением ожиданий.

Тесты закрепляют три свойства, каждое из которых можно потерять
незаметно:

1. ожидания действительно накладываются;
2. одновременных запросов не больше предела — иначе тридцать пять
   запросов к t.me с одного адреса выглядят как выкачивание;
3. порядок результатов сохраняется, иначе дедупликация через `seen`
   начнёт приписывать событие то одному источнику, то другому.
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
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import config, sources  # noqa: E402


DELAY = 0.02          # столько «отвечает» каждый источник в тестах


class Tracker:
    """Считает, сколько запросов выполняется одновременно."""

    def __init__(self) -> None:
        self.now = 0
        self.peak = 0
        self.order: list[str] = []

    async def fetch(self, _session, name, _limit) -> list[sources.Item]:
        self.now += 1
        self.peak = max(self.peak, self.now)
        try:
            await asyncio.sleep(DELAY)
            self.order.append(name)
            return [sources.Item(source=name, text=f"сообщение из {name} " * 3,
                                 kind="tg")]
        finally:
            self.now -= 1


def run(coro):
    return asyncio.run(coro)


class TestConcurrency(unittest.TestCase):
    def setUp(self):
        self.seen = sources.SeenStore()
        self.channels = [f"канал{index}" for index in range(12)]

    def collect(self, tracker, concurrency):
        with mock.patch.object(sources, "fetch_channel", tracker.fetch):
            return run(sources.collect(
                None, self.channels, [], self.seen, limit=5,
                concurrency=concurrency,
            ))

    def test_requests_overlap(self):
        """Двенадцать источников по 20 мс не должны занимать 240 мс."""
        tracker = Tracker()
        started = time.monotonic()
        self.collect(tracker, 6)
        spent = time.monotonic() - started

        sequential = len(self.channels) * DELAY
        self.assertLess(spent, sequential / 2,
                        f"обход занял {spent:.3f} с при последовательных "
                        f"{sequential:.3f} с — параллельности нет")

    def test_peak_respects_limit(self):
        tracker = Tracker()
        self.collect(tracker, 4)
        self.assertLessEqual(tracker.peak, 4, f"пик {tracker.peak}")

    def test_peak_reaches_limit(self):
        """Предел должен использоваться, а не оставаться про запас."""
        tracker = Tracker()
        self.collect(tracker, 4)
        self.assertEqual(tracker.peak, 4)

    def test_limit_of_one_is_sequential(self):
        tracker = Tracker()
        self.collect(tracker, 1)
        self.assertEqual(tracker.peak, 1)

    def test_zero_and_negative_do_not_stall(self):
        """Ноль в настройке не должен останавливать сбор насмерть."""
        for bad in (0, -5):
            with self.subTest(concurrency=bad):
                # Своё хранилище на каждую попытку: общее пометило бы
                # сообщения прочитанными на первой же итерации.
                self.seen = sources.SeenStore()
                tracker = Tracker()
                items = self.collect(tracker, bad)
                self.assertEqual(len(items), len(self.channels))
                self.assertEqual(tracker.peak, 1)

    def test_every_source_polled(self):
        tracker = Tracker()
        items = self.collect(tracker, 6)
        self.assertEqual(len(items), len(self.channels))
        self.assertEqual(sorted(tracker.order), sorted(self.channels))


class TestOrder(unittest.TestCase):
    """Порядок результатов — по аргументам, а не по скорости ответа."""

    def test_slow_source_keeps_its_place(self):
        channels = ["медленный", "быстрый1", "быстрый2"]

        async def fetch(_session, name, _limit):
            # Первый источник отвечает дольше всех и всё равно обязан
            # оказаться первым в выдаче.
            await asyncio.sleep(0.05 if name == "медленный" else 0.001)
            return [sources.Item(source=name, text=f"текст {name} " * 5, kind="tg")]

        seen = sources.SeenStore()
        with mock.patch.object(sources, "fetch_channel", fetch):
            items = run(sources.collect(None, channels, [], seen, limit=5,
                                        concurrency=3))

        self.assertEqual([item.source for item in items], channels)

    def test_channels_come_before_feeds(self):
        async def channel(_session, name, _limit):
            await asyncio.sleep(0.01)
            return [sources.Item(source=name, text=f"канал {name} " * 5, kind="tg")]

        async def feed(_session, url, _limit):
            return [sources.Item(source=url, text=f"лента {url} " * 5, kind="rss")]

        seen = sources.SeenStore()
        with mock.patch.object(sources, "fetch_channel", channel), \
             mock.patch.object(sources, "fetch_rss", feed):
            items = run(sources.collect(None, ["к1"], ["https://лента"], seen,
                                        limit=5, concurrency=4))

        self.assertEqual([item.source for item in items], ["к1", "https://лента"])


class TestResilience(unittest.TestCase):
    """Одна мёртвая лента не должна оставлять людей без оповещений."""

    def test_exception_does_not_kill_the_cycle(self):
        async def fetch(_session, name, _limit):
            if name == "битый":
                raise RuntimeError("источник отвалился")
            return [sources.Item(source=name, text=f"текст {name} " * 5, kind="tg")]

        seen = sources.SeenStore()
        with mock.patch.object(sources, "fetch_channel", fetch):
            items = run(sources.collect(None, ["живой1", "битый", "живой2"], [],
                                        seen, limit=5, concurrency=3))

        self.assertEqual([item.source for item in items], ["живой1", "живой2"])

    def test_all_sources_broken_returns_empty(self):
        async def fetch(_session, _name, _limit):
            raise RuntimeError("сеть недоступна")

        seen = sources.SeenStore()
        with mock.patch.object(sources, "fetch_channel", fetch):
            items = run(sources.collect(None, ["а", "б"], [], seen, limit=5,
                                        concurrency=2))

        self.assertEqual(items, [])

    def test_no_sources_at_all(self):
        seen = sources.SeenStore()
        self.assertEqual(run(sources.collect(None, [], [], seen)), [])


class TestSeenStillWorks(unittest.TestCase):
    """Параллельность не должна ломать дедупликацию и разогрев."""

    async def _fetch(self, _session, name, _limit):
        return [sources.Item(source=name, text=f"одно и то же событие {name} " * 3,
                             kind="tg")]

    def test_second_pass_returns_nothing_new(self):
        seen = sources.SeenStore()
        channels = ["а", "б", "в"]
        with mock.patch.object(sources, "fetch_channel", self._fetch):
            first = run(sources.collect(None, channels, [], seen, concurrency=3))
            second = run(sources.collect(None, channels, [], seen, concurrency=3))

        self.assertEqual(len(first), 3)
        self.assertEqual(second, [])

    def test_warmup_marks_without_returning(self):
        seen = sources.SeenStore()
        channels = ["а", "б"]
        with mock.patch.object(sources, "fetch_channel", self._fetch):
            warm = run(sources.collect(None, channels, [], seen, warmup=True,
                                       concurrency=2))
            after = run(sources.collect(None, channels, [], seen, concurrency=2))

        self.assertEqual(warm, [])
        self.assertEqual(after, [], "разогрев не пометил сообщения прочитанными")


class TestEventLoopStaysFree(unittest.TestCase):
    """Разбор не должен держать цикл событий.

    Симптом с боевого сервера (4.7.6.5): «после перезагрузки долго
    отвечает или не отвечает на команды». Причина — `html.parser`
    и `ET.fromstring` считались прямо в цикле событий, а цикл общий
    с опросом Telegram. Пока бот разбирал тридцать пять страниц,
    отвечать на команды было некому. На старте это особенно заметно:
    идёт разогрев по всем источникам разом.

    Замер `/perf` это подтверждал: процессорного времени 1 мин 41 с
    за минуту наблюдения — то есть ядро занято, а не ждёт сеть.
    """

    PARSE_TIME = 0.3      # столько «разбирается» страница в тесте

    def _count_ticks(self, *, in_thread: bool) -> int:
        """Сколько раз посторонняя задача получит управление за время разбора.

        Абсолютное число зависит от гранулярности таймеров (на Windows
        она около 15 мс), поэтому сравниваем два режима между собой,
        а не с константой.
        """
        ticks = {"count": 0}

        async def heartbeat():
            # Изображаем опрос Telegram: если цикл занят, тиков не будет.
            while True:
                await asyncio.sleep(0.001)
                ticks["count"] += 1

        def slow_parse():
            time.sleep(self.PARSE_TIME)
            return []

        async def scenario():
            beat = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.05)     # даём сердцебиению запуститься
            ticks["count"] = 0
            try:
                if in_thread:
                    await asyncio.to_thread(slow_parse)
                else:
                    slow_parse()          # как было до 4.7.7 — прямо в цикле
            finally:
                beat.cancel()
                try:
                    await beat
                except asyncio.CancelledError:
                    pass

        asyncio.run(scenario())
        return ticks["count"]

    def test_parsing_in_thread_keeps_loop_responsive(self):
        blocking = self._count_ticks(in_thread=False)
        threaded = self._count_ticks(in_thread=True)

        # Блокирующий разбор не отдаёт управление вовсе.
        self.assertEqual(blocking, 0, "неожиданно: блокирующий вызов уступил цикл")
        self.assertGreater(
            threaded, blocking,
            "разбор держит цикл событий — бот не отвечал бы на команды",
        )

    def test_channel_parse_is_a_plain_function(self):
        """Разбор должен остаться синхронной функцией: только такую можно
        отдать в поток."""
        self.assertFalse(asyncio.iscoroutinefunction(sources.parse_channel))
        self.assertFalse(asyncio.iscoroutinefunction(sources.parse_rss))

    def test_broken_page_does_not_raise(self):
        """Мусор вместо страницы — пустой список, а не исключение."""
        self.assertEqual(sources.parse_rss("не xml", "https://лента", 5), [])


class TestSetting(unittest.TestCase):
    def test_default_is_bounded_and_sane(self):
        self.assertGreaterEqual(config.SOURCE_CONCURRENCY, 1)
        self.assertLessEqual(
            config.SOURCE_CONCURRENCY, 16,
            "слишком много одновременных запросов к t.me с одного адреса",
        )

    def test_default_beats_sequential(self):
        self.assertGreater(config.SOURCE_CONCURRENCY, 1,
                           "предел 1 вернул бы последовательный обход")


if __name__ == "__main__":
    unittest.main(verbosity=2)
