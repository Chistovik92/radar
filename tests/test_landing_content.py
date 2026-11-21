#!/usr/bin/env python3
"""Офлайн-проверки CMS лендинга: схема, merge, формы и права."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import stubcheck  # noqa: E402

stubcheck.install()

from radar.db import repo  # noqa: E402
from radar.web import landing, landing_content, panel, sitepages  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_keys_are_nonempty_and_unique(self) -> None:
        self.assertEqual(set(landing_content.PAGES), {"home", "pricing", "support", "downloads", "projects"})
        self.assertNotIn("privacy", landing_content.PAGES)
        self.assertNotIn("terms", landing_content.PAGES)

        def check(fields) -> None:
            keys = [item.key for item in fields]
            self.assertTrue(all(keys))
            self.assertEqual(len(keys), len(set(keys)))
            for item in fields:
                self.assertGreater(item.limit, 0)
                check(item.fields)

        for schema in landing_content.PAGES.values():
            check(schema.fields)

    def test_merge_fills_defaults_and_preserves_unknown_values(self) -> None:
        merged = landing_content.merge_with_meta({
            "home": {"hero_title": "Новый заголовок", "future": "сохранить"},
            "future_page": {"text": "тоже сохранить"},
        })
        self.assertEqual(merged["home"]["hero_title"], "Новый заголовок")
        self.assertEqual(merged["home"]["hero_accent"], "Вы — в курсе.")
        self.assertEqual(merged["home"]["future"], "сохранить")
        self.assertEqual(merged["future_page"]["text"], "тоже сохранить")

    def test_bad_scalar_and_list_types_fall_back_to_defaults(self) -> None:
        merged = landing_content.merge_with_meta({"home": {"hero_title": 42, "capabilities": "no"}})
        defaults = landing_content.default_content()["home"]
        self.assertEqual(merged["home"]["hero_title"], defaults["hero_title"])
        self.assertEqual(merged["home"]["capabilities"], defaults["capabilities"])

    def test_load_uses_meta_and_empty_database_uses_defaults(self) -> None:
        with mock.patch.object(repo, "get_meta", new=mock.AsyncMock(return_value={})):
            self.assertEqual(asyncio.run(landing_content.load_content()), landing_content.default_content())
        with mock.patch.object(repo, "get_meta", new=mock.AsyncMock(return_value={"home": {"hero_title": "CMS"}})):
            loaded = asyncio.run(landing_content.load_content())
        self.assertEqual(loaded["home"]["hero_title"], "CMS")
        self.assertEqual(loaded["support"]["title"], "Поддержка")

    def test_save_keeps_only_overrides(self) -> None:
        content = landing_content.default_content()
        content["home"]["hero_title"] = "Изменено"
        content["home"]["unknown"] = "совместимость"
        with mock.patch.object(repo, "set_meta", new=mock.AsyncMock()) as save:
            asyncio.run(landing_content.save_content(content))
        stored = save.await_args.args[1]
        self.assertEqual(stored["home"], {"hero_title": "Изменено", "unknown": "совместимость"})
        self.assertNotIn("support", stored)


class FormTests(unittest.TestCase):
    def test_render_escapes_text_and_has_csrf(self) -> None:
        values = landing_content.default_content()["home"]
        values["hero_title"] = '<img src=x onerror="alert(1)">'
        page = sitepages.edit_body("home", "token<\"", values)
        self.assertIn("&lt;img src=x onerror=", page)
        self.assertNotIn('<img src=x onerror="alert(1)">', page)
        self.assertIn('name="csrf"', page)
        self.assertIn('maxlength="500"', page)

    def test_textlist_maxlength_covers_each_line_and_separators(self) -> None:
        values = landing_content.default_content()["support"]
        page = sitepages.edit_body("support", "token", values)
        self.assertIn('name="sla" maxlength="2003"', page)
        self.assertIn("Максимум 500 символов в строке.", page)
        values["sla"] = [""]
        self.assertIn('name="sla" maxlength="500"', sitepages.edit_body("support", "token", values))

    def test_apply_form_reads_nested_lists_and_ignores_unknown_post(self) -> None:
        values = landing_content.default_content()["projects"]
        values["title"] = "Старое"
        values["projects"][0]["name"] = "Старое"
        values["projects"][0]["links"][0]["label"] = "Старое"
        values["projects"][0]["links"][0]["href"] = "/"
        form = {"title": "Проекты CMS", "projects.0.name": "Радар CMS",
                "projects.0.links.0.label": "Открыть", "projects.0.links.0.href": "/new",
                "unexpected": "ignored"}
        parsed, problem = sitepages.apply_form("projects", form, values)
        self.assertEqual(problem, "")
        self.assertEqual(parsed["title"], "Проекты CMS")
        self.assertEqual(parsed["projects"][0]["name"], "Радар CMS")
        self.assertEqual(parsed["projects"][0]["links"][0], {"label": "Открыть", "href": "/new"})
        self.assertNotIn("unexpected", parsed)

    def test_limits_urls_and_list_shape_are_enforced(self) -> None:
        values = landing_content.default_content()["support"]
        parsed, problem = sitepages.apply_form("support", {"title": "x" * 501}, values)
        self.assertEqual(parsed, {})
        self.assertIn("500", problem)
        _parsed, problem = sitepages.apply_form(
            "support", {"channels.0.href": "javascript:alert(1)"}, values)
        self.assertIn("разрешены", problem)
        _parsed, problem = sitepages.apply_form("support", {"sla": "одна"}, values)
        self.assertIn("ровно 4", problem)
        _parsed, problem = sitepages.apply_form("support", {"title": "одна\nдве"}, values)
        self.assertIn("одной строкой", problem)
        _parsed, problem = sitepages.apply_form(
            "support", {"sla": "x" * 501 + "\n2\n3\n4"}, values)
        self.assertIn("строка длиннее 500", problem)
        self.assertEqual(sitepages.apply_form("missing", {}), ({}, "Неизвестная страница"))

    def test_overview_marks_only_changed_page(self) -> None:
        page = sitepages.overview_body({"home": {"hero_title": "Другое"}})
        self.assertIn("изменено", page)
        self.assertEqual(page.count("по умолчанию"), len(landing_content.PAGES) - 1)


class LandingPayloadTests(unittest.TestCase):
    def test_content_is_embedded_and_script_cannot_be_closed(self) -> None:
        content = landing_content.default_content()
        content["home"]["hero_title"] = '</script><script>alert("x")</script>'
        with mock.patch("radar.handlers.digest._plans", return_value=[]):
            page = landing.render_landing_page("radar_bot", "https://radar.example", content)
        raw = re.search(r'<script id="radar-config" type="application/json">(.*?)</script>', page).group(1)
        payload = json.loads(raw)
        self.assertEqual(payload["content"]["home"]["hero_title"], '</script><script>alert("x")</script>')
        self.assertNotIn('</script><script>alert("x")</script>', page)
        self.assertIn("\\u003c/script>", page)


class StaticFrontendTests(unittest.TestCase):
    def test_privacy_and_terms_are_not_spa_routes_or_links(self) -> None:
        source_dir = Path(ROOT) / "landing" / "src"
        main = (source_dir / "main.tsx").read_text(encoding="utf-8")
        self.assertNotIn("Privacy", main)
        self.assertNotIn("Terms", main)
        self.assertNotIn('path="/privacy"', main)
        self.assertNotIn('path="/terms"', main)
        for relative in ("App.tsx", "components/PageLayout.tsx"):
            source = (source_dir / relative).read_text(encoding="utf-8")
            self.assertNotIn('to="/privacy"', source)
            self.assertNotIn('to="/terms"', source)
            self.assertIn('href="/privacy"', source)
            self.assertIn('href="/terms"', source)

    def test_downloads_and_projects_consume_every_schema_field(self) -> None:
        pages_dir = Path(ROOT) / "landing" / "src" / "pages"
        for page_key, filename in (("downloads", "Downloads.tsx"), ("projects", "Projects.tsx")):
            source = (pages_dir / filename).read_text(encoding="utf-8")
            self.assertIn(f"pageContent('{page_key}'", source)
            for item in landing_content.PAGES[page_key].fields:
                with self.subTest(page=page_key, field=item.key):
                    self.assertIn(f"content.{item.key}", source)
        downloads = (pages_dir / "Downloads.tsx").read_text(encoding="utf-8")
        self.assertIn("https://github.com/Chistovik92/HydraVPN/releases", downloads)
        self.assertIn("https://github.com/Chistovik92/HydraVPNforRouters/releases", downloads)


class AccessTests(unittest.TestCase):
    def test_site_handlers_use_owner_guard_and_csrf(self) -> None:
        source = inspect.getsource(panel.create_app)
        self.assertRegex(source, r'@owner_only\s+async def site_overview')
        self.assertRegex(source, r'@owner_only\s+async def site_edit')
        self.assertRegex(source, r'async def site_save\(request\):[\s\S]*?_guarded_form\(request, "superadmin"\)')
        self.assertIn('web.get("/site", site_overview)', source)
        self.assertIn('web.get("/site/{page}", site_edit)', source)
        self.assertIn('web.post("/site/{page}", site_save)', source)

    def test_site_navigation_is_owner_only(self) -> None:
        owner = panel._nav_groups("superadmin")
        admin = panel._nav_groups("admin")
        self.assertIn("site", {group[2] for group in owner})
        self.assertNotIn("site", {group[2] for group in admin})


if __name__ == "__main__":
    unittest.main()
