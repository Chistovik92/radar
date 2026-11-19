#!/usr/bin/env python3
"""Публичные страницы и JSON-контракты виджетов."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import config, weather  # noqa: E402
from radar.db import repo as db_repo  # noqa: E402
from radar.web import landing, public_pages, widgets  # noqa: E402


def body(response) -> dict:
    return json.loads(response.text)


class PublicPages(unittest.TestCase):
    def test_all_pages_render_with_literal_js_braces(self) -> None:
        for render in (public_pages.render_privacy_page,
                       public_pages.render_terms_page,
                       public_pages.render_support_page,
                       public_pages.render_pricing_page):
            with self.subTest(render=render.__name__):
                page = render()
                self.assertIn("<!doctype html>", page.lower())
                self.assertNotIn("{VERSION}", page)

    def test_support_has_only_real_contacts(self) -> None:
        page = public_pages.render_support_page()
        self.assertNotIn("/support/submit", page)
        self.assertIn("SecretHeroSupportBot", page)

    def test_prices_come_from_bot_plans(self) -> None:
        with mock.patch("radar.handlers.digest._plans", return_value=[(10, 123)]):
            pricing = public_pages.render_pricing_page()
            terms = public_pages.render_terms_page()
        self.assertIn("123 ⭐", pricing)
        self.assertIn("10 дней", pricing)
        self.assertIn("123 ⭐", terms)
        self.assertNotIn("start=subscribe", pricing)
        self.assertNotIn("Platega", pricing)

    def test_custom_landing_description_is_escaped(self) -> None:
        with mock.patch("radar.secrets.get", return_value="<img src=x onerror=alert(1)>"):
            page = landing.render_landing_page("radar_bot", "https://radar.example")
        self.assertIn("\\u003cimg src=x onerror=alert(1)>", page)
        self.assertNotIn("<img src=x onerror=alert(1)>", page)
        self.assertIn('<div id="root"></div>', page)
        self.assertIn('id="radar-config"', page)
        self.assertIn('/landing/landing.js', page)
        self.assertIn('/landing/landing.css', page)

    def test_landing_assets_are_an_explicit_allowlist(self) -> None:
        request = SimpleNamespace(match_info={"asset": "../landing.py"})
        with mock.patch.object(landing, "web", SimpleNamespace(HTTPNotFound=LookupError)):
            with self.assertRaises(LookupError):
                import asyncio
                asyncio.run(landing.landing_asset(request))


class DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class WidgetApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Контракт ответа проверяем маленькой реализацией json_response:
        # CI запускает этот файл до установки внешних зависимостей.
        def json_response(data, status=200):
            return SimpleNamespace(status=status, text=json.dumps(data))

        self.web_patch = mock.patch.object(
            widgets, "web", SimpleNamespace(json_response=json_response))
        self.web_patch.start()
        self.addCleanup(self.web_patch.stop)

    async def test_location_uses_visitor_ip(self) -> None:
        # Основной сервис — ip-api.com (HTTP, поля status/lat/lon). Возвращает
        # город сразу, до запасного ipwho.is дело не доходит.
        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def json(self, content_type=None):
                return {
                    "status": "success", "city": "Саратов",
                    "regionName": "Саратовская область",
                    "country": "Россия", "lat": 51.53, "lon": 46.03,
                }

        class Session(DummySession):
            def get(self, url, params=None):
                self.url = url
                self.params = params
                return Response()

        session = Session()
        request = SimpleNamespace(
            headers={"X-Forwarded-For": "8.8.8.8, 10.0.0.1"}, remote="10.0.0.1")
        with (mock.patch.object(config, "WEB_HTTPS", True),
              mock.patch.object(widgets, "_session", return_value=session)):
            response = await widgets.widget_location(request)
        payload = body(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["city"], "Саратов")
        self.assertEqual(payload["region"], "Саратовская область")
        self.assertTrue(payload["approximate"])
        self.assertNotIn("ip", payload)
        self.assertEqual(session.url, "http://ip-api.com/json/8.8.8.8")

    async def test_location_falls_back_to_ipwhois(self) -> None:
        # ip-api.com не ответил — переходим на запасной ipwho.is (HTTPS).
        class IpApiResponse:
            status = 403

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def json(self, content_type=None):
                return {}

        class IpwhoisResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def json(self, content_type=None):
                return {
                    "success": True, "city": "Саратов",
                    "region": "Саратовская область", "country": "Россия",
                    "latitude": 51.53, "longitude": 46.03,
                }

        class Session(DummySession):
            def get(self, url, params=None):
                self.urls.append(url)
                if "ipwho.is" in url:
                    return IpwhoisResponse()
                return IpApiResponse()

        session = Session()
        session.urls = []
        request = SimpleNamespace(headers={}, remote="8.8.8.8")
        with (mock.patch.object(config, "WEB_HTTPS", False),
              mock.patch.object(widgets, "_session", return_value=session)):
            response = await widgets.widget_location(request)
        payload = body(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["city"], "Саратов")
        self.assertIn("http://ip-api.com/json/8.8.8.8", session.urls)
        self.assertIn("https://ipwho.is/8.8.8.8", session.urls)

    async def test_location_does_not_send_private_ip_to_external_service(self) -> None:
        session = mock.Mock()
        request = SimpleNamespace(headers={}, remote="127.0.0.1")
        with (mock.patch.object(config, "WEB_HTTPS", False),
              mock.patch.object(widgets, "_session", return_value=session) as factory):
            response = await widgets.widget_location(request)
        self.assertEqual(response.status, 404)
        self.assertEqual(body(response)["error"], "location_unavailable")
        factory.assert_not_called()

    async def test_weather_uses_browser_coordinates(self) -> None:
        data = weather.Weather(
            ok=True, temp=12.4, feels=10.1, code=1, humidity=70,
            wind=3.2, pressure=1010,
            daily=[weather.Day("завтра", 5.0, 10.0, 20, 2)],
        )
        with (mock.patch.object(widgets, "_session", DummySession),
              mock.patch.object(widgets.geocode, "forward",
                                new=mock.AsyncMock()) as forward,
              mock.patch.object(widgets.weather, "fetch",
                                new=mock.AsyncMock(return_value=data)) as fetch):
            response = await widgets.widget_weather(SimpleNamespace(
                query={"lat": "0", "lon": "37.6", "city": "auto"}))
        self.assertEqual(response.status, 200)
        self.assertEqual(body(response)["temperature"], 12.4)
        self.assertEqual(body(response)["forecast"][0]["date"], "завтра")
        fetch.assert_awaited_once_with(mock.ANY, 0.0, 37.6)
        forward.assert_not_awaited()

    async def test_weather_auto_uses_default_city(self) -> None:
        found = [{"lat": "55.7", "lon": "37.6"}]
        with (mock.patch.object(config, "DEFAULT_CITY", "Москва"),
              mock.patch.object(widgets, "_session", DummySession),
              mock.patch.object(widgets.geocode, "forward",
                                new=mock.AsyncMock(return_value=found)) as forward,
              mock.patch.object(widgets.weather, "fetch",
                                new=mock.AsyncMock(return_value=weather.Weather(ok=True)))):
            response = await widgets.widget_weather(SimpleNamespace(query={"city": "auto"}))
        self.assertEqual(response.status, 200)
        forward.assert_awaited_once_with(mock.ANY, "Москва")

    async def test_weather_rejects_bad_coordinates(self) -> None:
        response = await widgets.widget_weather(SimpleNamespace(
            query={"lat": "nan", "lon": "37.6"}))
        self.assertEqual(response.status, 400)
        self.assertEqual(body(response)["error"], "coordinates_invalid")

    async def test_news_rejects_bad_limit_before_database(self) -> None:
        for value in ("abc", "0", "-1", "21"):
            with self.subTest(value=value):
                response = await widgets.widget_news(SimpleNamespace(query={"limit": value}))
                self.assertEqual(response.status, 400)

    async def test_news_sanitizes_link_scheme(self) -> None:
        recent = mock.AsyncMock(return_value=[{
            "id": 1, "title": "Новость", "summary": "", "source": "RSS",
            "url": "javascript:alert(1)", "categories": ["mchs"],
            "published_at": "2026-11-18T00:00:00+00:00",
        }])
        with mock.patch.object(db_repo, "recent_events", recent):
            response = await widgets.widget_news(SimpleNamespace(query={}))
        self.assertEqual(response.status, 200)
        self.assertEqual(body(response)["items"][0]["url"], "")

    async def test_danger_uses_latest_state_for_requested_city(self) -> None:
        danger = mock.AsyncMock(return_value={"bpla": False, "mchs": True})
        latest = mock.AsyncMock(return_value=None)
        with (mock.patch.object(config, "DEFAULT_CITY", "Москва"),
              mock.patch.object(db_repo, "danger_state", danger),
              mock.patch.object(db_repo, "latest_threat", latest)):
            response = await widgets.widget_danger(SimpleNamespace(query={"city": "auto"}))
        self.assertEqual(response.status, 200)
        self.assertEqual(body(response)["type"], "mchs")
        danger.assert_awaited_once_with(city="Москва", hours=24)
        latest.assert_awaited_once_with(city="Москва", hours=72)

    async def test_danger_reports_latest_threat_event(self) -> None:
        # Последнее событие БПЛА по городу — виджет показывает его детали.
        danger = mock.AsyncMock(return_value={"bpla": True, "mchs": False})
        latest = mock.AsyncMock(return_value={
            "type": "air_raid", "severity": "critical", "all_clear": False,
            "summary": "Опасность атаки БПЛА", "source": "t.me/gub",
            "published_at": "2026-11-19T10:00:00+00:00",
        })
        with (mock.patch.object(config, "DEFAULT_CITY", "Саратов"),
              mock.patch.object(db_repo, "danger_state", danger),
              mock.patch.object(db_repo, "latest_threat", latest)):
            response = await widgets.widget_danger(SimpleNamespace(query={"city": "auto"}))
        self.assertEqual(response.status, 200)
        payload = body(response)
        self.assertTrue(payload["active"])
        self.assertEqual(payload["type"], "air_raid")
        self.assertEqual(payload["started_at"], "2026-11-19T10:00:00+00:00")
        self.assertEqual(payload["message"], "Опасность атаки БПЛА")

    async def test_danger_no_data_reports_clear(self) -> None:
        danger = mock.AsyncMock(return_value={"bpla": False, "mchs": False})
        latest = mock.AsyncMock(return_value=None)
        with (mock.patch.object(config, "DEFAULT_CITY", "Москва"),
              mock.patch.object(db_repo, "danger_state", danger),
              mock.patch.object(db_repo, "latest_threat", latest)):
            response = await widgets.widget_danger(SimpleNamespace(query={"city": "auto"}))
        self.assertEqual(response.status, 200)
        payload = body(response)
        self.assertFalse(payload["active"])
        self.assertEqual(payload["level"], "green")
        self.assertEqual(payload["message"], "Опасностей не обнаружено")

    async def test_internal_errors_are_not_exposed(self) -> None:
        recent = mock.AsyncMock(side_effect=RuntimeError("database password"))
        with mock.patch.object(db_repo, "recent_events", recent):
            response = await widgets.widget_news(SimpleNamespace(query={}))
        self.assertEqual(response.status, 500)
        self.assertNotIn("database password", response.text)
class RepoDangerState(unittest.IsolatedAsyncioTestCase):
    async def test_latest_all_clear_wins_and_city_is_filtered(self) -> None:
        rows = [
            SimpleNamespace(city="Москва", categories=["bpla"],
                            all_clear=True, severity="info"),
            SimpleNamespace(city="Москва", categories=["bpla"],
                            all_clear=False, severity="critical"),
            SimpleNamespace(city="Саратов", categories=["mchs"],
                            all_clear=False, severity="warning"),
        ]
        active = SimpleNamespace(scalars=mock.AsyncMock(
            return_value=SimpleNamespace(all=lambda: rows)))

        class Session:
            async def __aenter__(self):
                return active

            async def __aexit__(self, *args):
                return None

        class Column:
            def __ge__(self, other):
                return None

            def desc(self):
                return None

        with (mock.patch.object(db_repo, "session", Session),
              mock.patch.object(db_repo, "Event",
                                SimpleNamespace(created_at=Column()))):
            state = await db_repo.danger_state("Москва")
        self.assertEqual(state, {"bpla": False, "mchs": False})


if __name__ == "__main__":
    unittest.main()
