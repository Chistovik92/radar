#!/usr/bin/env python3
"""Обновление системы из панели (4.9.6).

Кнопка запускает не произвольную команду, а один заранее заданный
сценарий, и только при трёх выполненных условиях: возможность включена,
сокет Docker проброшен, путь установки на хосте передан. Здесь закреплены
именно они — потому что каждое несоблюдённое условие выглядит на живом
сервере одинаково («кнопка не работает»), а причины разные.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import features, updater  # noqa: E402


class FakeResponse:
    """Одна из немногих строк реального ответа Docker Engine API,
    нужных исполнителю: статус, JSON, необработанный текст."""

    def __init__(self, status: int, body="") -> None:
        self.status = status
        self._body = body

    async def json(self):
        return self._body if isinstance(self._body, (dict, list)) else {}

    async def text(self) -> str:
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body, ensure_ascii=False)

    async def read(self) -> bytes:
        return b""

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    """Подменяет aiohttp.ClientSession: без сокета Docker и без сети.

    `routes` — {(метод, кусок пути в конце URL): FakeResponse}, сверяется
    по суффиксу, потому что реальный код всегда обращается к одному хосту
    (`API`), различаются только пути.
    """

    def __init__(self, routes: dict[tuple[str, str], FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def _resolve(self, method: str, url: str) -> FakeResponse:
        for (want_method, suffix), response in self.routes.items():
            if want_method == method and url.endswith(suffix):
                return response
        raise AssertionError(f"неожиданный запрос: {method} {url}")

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("GET", url))
        return self._resolve("GET", url)

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("POST", url))
        return self._resolve("POST", url)

    def delete(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("DELETE", url))
        return self._resolve("DELETE", url)

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class Readiness(unittest.TestCase):
    def tearDown(self) -> None:
        features.set_local("panel_update", False)

    def test_disabled_by_default(self) -> None:
        # Сокет Docker в контейнере равносилен root на хосте: возможность
        # обязана быть выключенной, пока её не включили руками.
        flag = features.resolve("panel_update")
        self.assertIsNotNone(flag)
        self.assertFalse(flag.default)

    def test_refuses_while_flag_off(self) -> None:
        features.set_local("panel_update", False)
        allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("выключена", reason)

    def test_refuses_without_socket(self) -> None:
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=False):
            allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("Сокет Docker", reason)

    def test_refuses_when_socket_not_writable(self) -> None:
        # Живой случай с сервера: сокет проброшен, но контейнер не в группе
        # docker — кнопка отвечала «Permission denied» вместо объяснения.
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.access", return_value=False):
            allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("прав", reason)
        self.assertIn("DOCKER_GID", reason)

    def test_refuses_without_host_dir(self) -> None:
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.access", return_value=True), \
             mock.patch.dict(os.environ, {"RADAR_HOST_DIR": ""}, clear=False):
            allowed, reason = updater.ready()
        self.assertFalse(allowed)
        self.assertIn("RADAR_HOST_DIR", reason)

    def test_ready_when_all_three_hold(self) -> None:
        features.set_local("panel_update", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.access", return_value=True), \
             mock.patch.dict(os.environ, {"RADAR_HOST_DIR": "/root/radar_bot"}):
            allowed, reason = updater.ready()
        self.assertTrue(allowed, reason)

    def test_start_refused_when_not_ready(self) -> None:
        features.set_local("panel_update", False)
        started, reason = asyncio.run(updater.start("тест"))
        self.assertFalse(started)
        self.assertIn("выключена", reason)


class RunnerRecipe(unittest.TestCase):
    """Сценарий исполнителя: важны детали, которые ломают обновление молча."""

    def test_installer_gets_no_questions(self) -> None:
        # Без RADAR_ASKED установщик ждал бы ответа у терминала, которого
        # у исполнителя нет, и обновление зависло бы на первом вопросе.
        source = open(os.path.join(ROOT, "radar", "updater.py"),
                      encoding="utf-8").read()
        self.assertIn('"RADAR_ASKED=1"', source)
        self.assertIn('"NO_ANIMATION=1"', source)

    def test_compose_passes_docker_group(self) -> None:
        # Без группы docker сокет виден, но недоступен: это и был отказ
        # «Permission denied» на живом сервере в 4.9.6.1.
        compose = open(os.path.join(ROOT, "docker-compose.yml"),
                       encoding="utf-8").read()
        self.assertIn("group_add", compose)
        self.assertIn("DOCKER_GID", compose)

    def test_installer_fills_docker_group(self) -> None:
        template = open(os.path.join(ROOT, "tools", "install.template.sh"),
                        encoding="utf-8").read()
        self.assertIn("getent group docker", template)
        self.assertIn("set_env_value DOCKER_GID", template)

    def test_host_path_is_mounted_as_itself(self) -> None:
        # Каталог обязан попасть в исполнитель по своему же пути: иначе
        # docker compose передаст демону пути, которых на хосте нет,
        # и тома бота отвалятся при первом же обновлении.
        source = open(os.path.join(ROOT, "radar", "updater.py"),
                      encoding="utf-8").read()
        self.assertIn('f"{directory}:{directory}"', source)

    def test_script_runs_installer_with_bash(self) -> None:
        # install.sh написан на bash, а в образе docker:cli его нет.
        self.assertIn("apk add --no-cache bash", updater.SCRIPT)
        self.assertIn("bash install.sh", updater.SCRIPT)

    def test_script_keeps_system_packages_alone(self) -> None:
        # Обновлять пакеты системы изнутри контейнера бессмысленно.
        self.assertIn("--skip-updates", updater.SCRIPT)

    def test_compose_is_ensured(self) -> None:
        self.assertIn("docker compose version", updater.SCRIPT)


class ImagePull(unittest.TestCase):
    """4.9.8.3: свежий сервер валился на первой же кнопке — демон Docker
    не знал `docker:cli`, а код ни разу не пытался его скачать."""

    def test_skips_pull_when_image_already_present(self) -> None:
        session = FakeSession({
            ("GET", f"/images/{updater.IMAGE}/json"): FakeResponse(200, {"Id": "sha256:x"}),
        })
        ok, reason = asyncio.run(updater._ensure_image(session))
        self.assertTrue(ok, reason)
        self.assertNotIn(("POST", f"{updater.API}/images/create"), session.calls)

    def test_pulls_missing_image(self) -> None:
        pull_log = "\n".join(json.dumps(e) for e in [
            {"status": "Pulling from library/docker", "id": "cli"},
            {"status": "Download complete"},
            {"status": "Status: Downloaded newer image for docker:cli"},
        ])
        session = FakeSession({
            ("GET", f"/images/{updater.IMAGE}/json"): FakeResponse(404, {"message": "no such image"}),
            ("POST", f"{updater.API}/images/create"): FakeResponse(200, pull_log),
        })
        ok, reason = asyncio.run(updater._ensure_image(session))
        self.assertTrue(ok, reason)
        self.assertIn(("POST", f"{updater.API}/images/create"), session.calls)

    def test_pull_error_is_reported(self) -> None:
        # Docker отвечает построчным JSON и может вернуть HTTP 200
        # с ошибкой внутри потока — например, тег не существует.
        pull_log = json.dumps({"errorDetail": {"message": "manifest unknown"},
                                "error": "manifest unknown"})
        session = FakeSession({
            ("GET", f"/images/{updater.IMAGE}/json"): FakeResponse(404, {}),
            ("POST", f"{updater.API}/images/create"): FakeResponse(200, pull_log),
        })
        ok, reason = asyncio.run(updater._ensure_image(session))
        self.assertFalse(ok)
        self.assertIn("manifest unknown", reason)

    def test_start_stops_before_create_when_pull_fails(self) -> None:
        features.set_local("panel_update", True)
        session = FakeSession({
            ("GET", f"{updater.API}/containers/json"): FakeResponse(200, []),
            ("GET", f"/images/{updater.IMAGE}/json"): FakeResponse(404, {}),
            ("POST", f"{updater.API}/images/create"):
                FakeResponse(500, "registry unavailable"),
        })

        async def fake_session():
            return session

        try:
            with mock.patch("os.path.exists", return_value=True), \
                 mock.patch("os.access", return_value=True), \
                 mock.patch.dict(os.environ, {"RADAR_HOST_DIR": "/root/radar_bot"}), \
                 mock.patch("radar.updater._session", fake_session):
                started, reason = asyncio.run(updater.start("тест"))
        finally:
            features.set_local("panel_update", False)

        self.assertFalse(started)
        self.assertIn(f"Образ {updater.IMAGE} не скачан", reason)
        # Главное: до создания самого исполнителя дело не дошло —
        # иначе пользователь снова увидит «No such image» вместо
        # понятной причины.
        self.assertNotIn(("POST", f"{updater.API}/containers/create"), session.calls)


class PanelRoutes(unittest.TestCase):
    """Маршруты обновления закрыты правами суперадминистратора."""

    def setUp(self) -> None:
        self.source = open(os.path.join(ROOT, "radar", "web", "panel.py"),
                           encoding="utf-8").read()

    def test_page_is_owner_only(self) -> None:
        index = self.source.index("async def update_page")
        self.assertIn("@owner_only", self.source[index - 40:index])

    def test_start_is_post_with_form_guard(self) -> None:
        # Запуск обновления обязан идти POST-ом с токеном формы: по GET
        # его можно было бы вызвать чужой страницей через редирект.
        self.assertIn('web.post("/update/start", update_start)', self.source)
        self.assertNotIn('web.get("/update/start"', self.source)
        index = self.source.index("async def update_start")
        body = self.source[index:index + 400]
        self.assertIn('_guarded_form(request, "superadmin")', body)

    def test_menu_item_always_visible(self) -> None:
        # Раздел не прячется за выключенной возможностью: спрятанный пункт
        # не находят, и включать его человеку оказывается нечем. Проверяем
        # само меню, а не текст файла: разметка меняется, правило — нет.
        from radar import features
        from radar.web import panel

        was = features.enabled("panel_update")
        features.set_local("panel_update", False)
        try:
            pages = [item[2] for item in panel._links_for("superadmin")]
        finally:
            features.set_local("panel_update", was)
        self.assertIn("update", pages)

    def test_update_lives_under_overview(self) -> None:
        from radar.web import panel

        overview = next(group for group in panel._nav_groups("superadmin")
                        if group[2] == "home")
        self.assertIn("update", [item[2] for item in overview[3]])

    def test_page_offers_to_enable_itself(self) -> None:
        self.assertIn('name="key" value="panel_update"', self.source)
        self.assertIn("Включить обновление из панели", self.source)

    def test_toggle_returns_where_it_came_from(self) -> None:
        # Иначе включение из раздела «Обновление» выбрасывало бы человека
        # в «Возможности», и дорогу назад он ищет сам.
        self.assertIn('name="back" value="/update"', self.source)


if __name__ == "__main__":
    unittest.main()
