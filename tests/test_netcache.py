#!/usr/bin/env python3
"""Кэш ответов внешних служб — пункт 4 раздела 4.8.

Замер на боевом сервере показал, что цикл почти целиком уходит
на ожидание сети. Часть этих ожиданий не нужна вовсе: мы спрашиваем
одно и то же по нескольку раз.

* **погода** запрашивается на каждую группу локаций каждого пользователя;
  соседи по дому дают одинаковые координаты с точностью до сотых;
* **Nominatim** разрешает один запрос в секунду — это жёстче любого
  нашего таймаута, и каждое попадание в кэш возвращает циклу секунду.
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

from radar import geocode, netcache, weather  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestTTLCache(unittest.TestCase):
    def test_stores_and_returns(self):
        cache = netcache.TTLCache(ttl=10)
        cache.put("k", 42)
        self.assertEqual(cache.get("k"), 42)

    def test_missing_key(self):
        self.assertIsNone(netcache.TTLCache(ttl=10).get("нет"))

    def test_expires(self):
        cache = netcache.TTLCache(ttl=0.01)
        cache.put("k", 1)
        time.sleep(0.03)
        self.assertIsNone(cache.get("k"))

    def test_expired_entry_removed_not_just_hidden(self):
        cache = netcache.TTLCache(ttl=0.01)
        cache.put("k", 1)
        time.sleep(0.03)
        cache.get("k")
        self.assertEqual(len(cache), 0)

    def test_counters(self):
        cache = netcache.TTLCache(ttl=10)
        cache.put("k", 1)
        cache.get("k")
        cache.get("нет")
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 1)
        self.assertAlmostEqual(cache.ratio, 0.5)

    def test_ratio_without_calls(self):
        """Ноль обращений — ноль, а не деление на ноль."""
        self.assertEqual(netcache.TTLCache(ttl=10).ratio, 0.0)

    def test_size_capped(self):
        cache = netcache.TTLCache(ttl=100, limit=5)
        for index in range(20):
            cache.put(index, index)
        self.assertLessEqual(len(cache), 5)

    def test_oldest_evicted_when_nothing_stale(self):
        cache = netcache.TTLCache(ttl=100, limit=3)
        for key in ("a", "b", "c"):
            cache.put(key, key)
            time.sleep(0.001)
        cache.put("d", "d")
        self.assertIsNone(cache.get("a"), "вытеснена должна быть самая старая")
        self.assertEqual(cache.get("d"), "d")

    def test_clear_resets_counters(self):
        cache = netcache.TTLCache(ttl=10)
        cache.put("k", 1)
        cache.get("k")
        cache.clear()
        self.assertEqual(len(cache), 0)
        self.assertEqual(cache.hits, 0)

    def test_stats_shape(self):
        cache = netcache.TTLCache(ttl=10)
        cache.put("k", 1)
        stats = cache.stats()
        for field in ("size", "hits", "misses", "ratio"):
            self.assertIn(field, stats)

    def test_limit_never_below_one(self):
        cache = netcache.TTLCache(ttl=10, limit=0)
        cache.put("a", 1)
        self.assertGreaterEqual(cache.limit, 1)


class TestRoundPoint(unittest.TestCase):
    """Две цифры — около 1.1 км, ровно тот масштаб, на котором система
    и так склеивает локации в группу."""

    def test_neighbours_share_a_key(self):
        first = netcache.round_point(51.5331, 46.0342)
        second = netcache.round_point(51.5334, 46.0339)
        self.assertEqual(first, second)

    def test_distant_points_differ(self):
        self.assertNotEqual(netcache.round_point(51.53, 46.03),
                            netcache.round_point(55.75, 37.61))

    def test_garbage_does_not_raise(self):
        self.assertEqual(netcache.round_point("не число", None), (0.0, 0.0))


class TestWeatherCache(unittest.TestCase):
    SAMPLE = {"current": {"temperature_2m": 20, "weather_code": 0, "is_day": 1}}

    def setUp(self):
        weather.forget_cache()

    def _session(self, calls):
        class Response:
            status = 200

            async def json(self, **_kwargs):
                return TestWeatherCache.SAMPLE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        class Session:
            def get(self, *_a, **_kw):
                calls.append(1)
                return Response()

        return Session()

    def test_second_request_served_from_cache(self):
        calls = []
        session = self._session(calls)
        run(weather.fetch(session, 51.5331, 46.0342))
        run(weather.fetch(session, 51.5334, 46.0339))
        self.assertEqual(len(calls), 1, "соседние точки должны делить запрос")

    def test_distant_point_makes_its_own_request(self):
        calls = []
        session = self._session(calls)
        run(weather.fetch(session, 51.53, 46.03))
        run(weather.fetch(session, 55.75, 37.61))
        self.assertEqual(len(calls), 2)

    def test_languages_share_one_request(self):
        """Кэш держит сырой ответ: разбор зависит от языка, запрос — нет."""
        calls = []
        session = self._session(calls)
        first = run(weather.fetch(session, 51.53, 46.03, lang="ru"))
        second = run(weather.fetch(session, 51.53, 46.03, lang="en"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(first.ok and second.ok)

    def test_failure_not_cached(self):
        """Запомнить сбой значило бы закрепить его на четверть часа."""
        class Boom:
            def get(self, *_a, **_kw):
                raise OSError("сеть недоступна")

        run(weather.fetch(Boom(), 51.53, 46.03))
        calls = []
        session = self._session(calls)
        result = run(weather.fetch(session, 51.53, 46.03))
        self.assertTrue(result.ok)
        self.assertEqual(len(calls), 1)

    def test_stats_available(self):
        self.assertIn("hits", weather.cache_stats())

    def test_ttl_shorter_than_local_time_drift(self):
        """В сводке есть местное время — держать дольше нельзя."""
        self.assertLessEqual(weather.CACHE_TTL, 1800)


class TestGeocodeCache(unittest.TestCase):
    def setUp(self):
        geocode.forget_cache()

    def test_reverse_cached(self):
        calls = []

        async def fake_reverse(*_a, **_kw):
            calls.append(1)
            return {"name": "Чапаева, 12", "city": "Саратов", "street": "Чапаева",
                    "house": "12", "district": "", "region": ""}

        # Проверяем сам кэш, а не разбор ответа Nominatim.
        cache = geocode._REVERSE
        key = netcache.round_point(51.53, 46.03)
        self.assertIsNone(cache.get(key))
        cache.put(key, {"name": "Чапаева, 12"})
        self.assertEqual(cache.get(key)["name"], "Чапаева, 12")

    def test_reverse_ttl_is_long(self):
        """Адреса не переезжают — держим сутки."""
        self.assertGreaterEqual(geocode.REVERSE_TTL, 3600)

    def test_forward_ttl_is_shorter(self):
        """Новый дом в Nominatim может появиться — «нет такого» не вечно."""
        self.assertLess(geocode.FORWARD_TTL, geocode.REVERSE_TTL)

    def test_cached_result_is_a_copy(self):
        """Вызывающий не должен уметь испортить кэш, правя ответ."""
        cache = geocode._REVERSE
        key = netcache.round_point(51.53, 46.03)
        cache.put(key, {"name": "Исходное"})
        got = dict(cache.get(key))
        got["name"] = "Испорченное"
        self.assertEqual(cache.get(key)["name"], "Исходное")

    def test_stats_shape(self):
        stats = geocode.cache_stats()
        self.assertIn("reverse", stats)
        self.assertIn("forward", stats)


if __name__ == "__main__":
    unittest.main(verbosity=2)
