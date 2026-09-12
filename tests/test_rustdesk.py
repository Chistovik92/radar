#!/usr/bin/env python3
"""RustDesk из бота (4.9.8.4): адрес и ключ, число подключений, управление.

Установщик сам разворачивает hbbs/hbbr (профиль rustdesk в
docker-compose.yml) и сверяет, что под ожидаемым именем контейнера
действительно образ rustdesk-server, а не что-то чужое, — строковые
проверки в конце файла закрепляют именно это, по образцу RunnerRecipe
в tests/test_updater.py.
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
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import config, dockerapi, features, rustdesk  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _DummySession:
    """Заглушка вместо aiohttp-сессии: exec_run/container_action здесь
    подменяются напрямую, сама сессия ни разу не используется по-настоящему."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def _fake_session():
    return _DummySession()


class Readiness(unittest.TestCase):
    def tearDown(self) -> None:
        features.set_local("rustdesk", False)

    def test_refuses_while_flag_off(self):
        features.set_local("rustdesk", False)
        allowed, reason = rustdesk.ready()
        self.assertFalse(allowed)
        self.assertIn("выключена", reason)

    def test_refuses_without_socket(self):
        features.set_local("rustdesk", True)
        with mock.patch("os.path.exists", return_value=False):
            allowed, reason = rustdesk.ready()
        self.assertFalse(allowed)
        self.assertIn("Сокет Docker", reason)

    def test_refuses_when_socket_not_writable(self):
        features.set_local("rustdesk", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.access", return_value=False):
            allowed, reason = rustdesk.ready()
        self.assertFalse(allowed)
        self.assertIn("DOCKER_GID", reason)

    def test_ready_when_all_hold(self):
        features.set_local("rustdesk", True)
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.access", return_value=True):
            allowed, reason = rustdesk.ready()
        self.assertTrue(allowed, reason)


def _hex_port(port: int) -> str:
    return f"{port:04X}"


class TestCountEstablished(unittest.TestCase):
    """Парсинг /proc/net/tcp{,6}: только ESTABLISHED (st=01) на нужном порту."""

    def test_established_on_target_port_counted(self):
        port = _hex_port(rustdesk.ID_PORT)
        text = (
            "  sl  local_address rem_address   st\n"
            f"   0: 00000000:{port} 00000000:0000 01\n"
            f"   1: 0100007F:{port} 00000000:0000 01\n"
        )
        self.assertEqual(rustdesk._count_established(text, rustdesk.ID_PORT), 2)

    def test_listening_socket_not_counted(self):
        # st=0A — LISTEN, не ESTABLISHED
        port = _hex_port(rustdesk.ID_PORT)
        text = f"   0: 00000000:{port} 00000000:0000 0A\n"
        self.assertEqual(rustdesk._count_established(text, rustdesk.ID_PORT), 0)

    def test_other_port_not_counted(self):
        # Соединение установлено, но на другом порту
        port = _hex_port(rustdesk.RELAY_PORT)
        text = f"   0: 00000000:{port} 00000000:0000 01\n"
        self.assertEqual(rustdesk._count_established(text, rustdesk.ID_PORT), 0)

    def test_ipv6_line_counted(self):
        # /proc/net/tcp6: местный адрес длиннее, порт всё равно последний
        port = _hex_port(rustdesk.ID_PORT)
        text = (
            f"   0: 00000000000000000000000000000000:{port} "
            "00000000000000000000000000000000:0000 01\n"
        )
        self.assertEqual(rustdesk._count_established(text, rustdesk.ID_PORT), 1)

    def test_mixed_ports_and_states(self):
        id_port = _hex_port(rustdesk.ID_PORT)
        relay_port = _hex_port(rustdesk.RELAY_PORT)
        text = "\n".join([
            f"   0: 00000000:{id_port} 00000000:0000 01",   # свой порт, established — считается
            f"   1: 00000000:{id_port} 00000000:0000 06",   # свой порт, но TIME_WAIT
            f"   2: 00000000:{relay_port} 00000000:0000 01",  # established, но другой порт
        ])
        self.assertEqual(rustdesk._count_established(text, rustdesk.ID_PORT), 1)


class ClientInfo(unittest.TestCase):
    def setUp(self) -> None:
        features.set_local("rustdesk", True)
        self._exists = mock.patch("os.path.exists", return_value=True).start()
        self._access = mock.patch("os.access", return_value=True).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(features.set_local, "rustdesk", False)

    def test_missing_public_host(self):
        with mock.patch.object(config, "RUSTDESK_PUBLIC_HOST", ""):
            ok, reason = rustdesk.client_info()
        self.assertFalse(ok)
        self.assertIn("RUSTDESK_PUBLIC_HOST", reason)

    def test_missing_key_file(self):
        with mock.patch.object(config, "RUSTDESK_PUBLIC_HOST", "1.2.3.4"), \
             mock.patch.object(config, "RUSTDESK_KEY_PATH", "/no/such/file.pub"):
            ok, reason = rustdesk.client_info()
        self.assertFalse(ok)

    def test_success_reads_key_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".pub", delete=False) as handle:
            handle.write("AAAAC3NzaC1lZDI1NTE5AAAA...\n")
            path = handle.name
        try:
            with mock.patch.object(config, "RUSTDESK_PUBLIC_HOST", "1.2.3.4"), \
                 mock.patch.object(config, "RUSTDESK_KEY_PATH", path):
                ok, info = rustdesk.client_info()
            self.assertTrue(ok, info)
            self.assertEqual(info["host"], "1.2.3.4")
            self.assertEqual(info["id_port"], 21116)
            self.assertEqual(info["relay_port"], 21117)
            self.assertEqual(info["key"], "AAAAC3NzaC1lZDI1NTE5AAAA...")
        finally:
            os.unlink(path)


class ConnectionsAndControl(unittest.TestCase):
    def setUp(self) -> None:
        features.set_local("rustdesk", True)
        mock.patch("os.path.exists", return_value=True).start()
        mock.patch("os.access", return_value=True).start()
        mock.patch("radar.dockerapi.session", _fake_session).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(features.set_local, "rustdesk", False)

    def test_connection_counts_success(self):
        async def fake_exec(session, name, cmd):
            port = _hex_port(rustdesk.ID_PORT if name == rustdesk.HBBS else rustdesk.RELAY_PORT)
            return True, f"   0: 00000000:{port} 00000000:0000 01\n"

        with mock.patch("radar.dockerapi.exec_run", fake_exec):
            ok, counts = run(rustdesk.connection_counts())
        self.assertTrue(ok, counts)
        self.assertEqual(counts, {"hbbs": 1, "hbbr": 1})

    def test_connection_counts_reports_exec_failure(self):
        async def fake_exec(session, name, cmd):
            return False, "контейнер не найден"

        with mock.patch("radar.dockerapi.exec_run", fake_exec):
            ok, reason = run(rustdesk.connection_counts())
        self.assertFalse(ok)
        self.assertIn(rustdesk.HBBS, reason)

    def test_control_restarts_both_containers(self):
        calls = []

        async def fake_action(session, name, action):
            calls.append((name, action))
            return True, ""

        with mock.patch("radar.dockerapi.container_action", fake_action):
            ok, reason = run(rustdesk.control("restart"))
        self.assertTrue(ok, reason)
        self.assertEqual(calls, [(rustdesk.HBBS, "restart"), (rustdesk.HBBR, "restart")])

    def test_control_collects_both_errors(self):
        async def fake_action(session, name, action):
            return False, f"{name} упал"

        with mock.patch("radar.dockerapi.container_action", fake_action):
            ok, reason = run(rustdesk.control("stop"))
        self.assertFalse(ok)
        self.assertIn(rustdesk.HBBS, reason)
        self.assertIn(rustdesk.HBBR, reason)

    def test_control_rejects_unknown_action(self):
        ok, reason = run(rustdesk.control("delete"))
        self.assertFalse(ok)
        self.assertIn("delete", reason)


class Deployed(unittest.TestCase):
    """Развёрнут ли сервер вообще. Без этой проверки панель показывала
    кнопки управления там, где контейнеров нет, и они отвечали
    «No such container» — на живом сервере так и вышло (4.9.8.5)."""

    def setUp(self) -> None:
        features.set_local("rustdesk", True)
        mock.patch("os.path.exists", return_value=True).start()
        mock.patch("os.access", return_value=True).start()
        mock.patch("radar.dockerapi.session", _fake_session).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(features.set_local, "rustdesk", False)

    def test_both_present(self):
        async def exists(session, name):
            return True

        with mock.patch("radar.dockerapi.container_exists", exists):
            ok, reason = run(rustdesk.deployed())
        self.assertTrue(ok, reason)

    def test_missing_container_is_named(self):
        async def missing(session, name):
            return False

        with mock.patch("radar.dockerapi.container_exists", missing):
            ok, reason = run(rustdesk.deployed())
        self.assertFalse(ok)
        self.assertIn(rustdesk.HBBS, reason)
        self.assertIn("не разворачивали", reason)

    def test_flag_off_reported_before_docker(self):
        features.set_local("rustdesk", False)
        ok, reason = run(rustdesk.deployed())
        self.assertFalse(ok)
        self.assertIn("выключена", reason)


class InstallerAnswer(unittest.TestCase):
    """Ответ «д» через SSH приходил с хвостом (возврат каретки), и `case`
    со сравнением целой строкой отвечал «Пропущено» на согласие —
    поймано на живом сервере в 4.9.8.5."""

    def setUp(self) -> None:
        self.template = open(os.path.join(ROOT, "tools", "install.template.sh"),
                             encoding="utf-8").read()

    def test_helper_exists_and_strips_tail(self):
        self.assertIn("answer_is_yes()", self.template)
        self.assertIn("value=\"${value//$'\\r'/}\"", self.template)
        self.assertIn('value="${value//[[:space:]]/}"', self.template)

    def test_both_questions_use_helper(self):
        self.assertEqual(self.template.count('answer_is_yes "$answer"'), 2)
        # Прежнее сравнение целой строкой не должно вернуться
        self.assertNotIn("y|Y|yes|д|Д|да|ДА) : ;;", self.template)

    def test_host_answer_also_trimmed(self):
        # Адрес с «\r» на конце уехал бы в .env, и клиенты искали бы
        # несуществующий хост.
        self.assertIn("host_now=\"${host_now//$'\\r'/}\"", self.template)


class InstallerDomainReuse(unittest.TestCase):
    """Домен, на который выдан сертификат панели, установщик предлагает
    сам — спрашивать тот же адрес второй раз незачем."""

    def setUp(self) -> None:
        self.template = open(os.path.join(ROOT, "tools", "install.template.sh"),
                             encoding="utf-8").read()

    def test_domain_suggested_in_prompt(self):
        self.assertIn('printf "  %s [%s] " "$(t rustdesk_host_ask)" "$suggested"',
                      self.template)

    def test_empty_answer_accepts_suggestion(self):
        self.assertIn('[ -z "$host_now" ] && host_now="$suggested"', self.template)

    def test_helpers_defined_once(self):
        self.assertEqual(self.template.count("configured_domain() {"), 1)
        self.assertEqual(self.template.count("tls_certificate_present() {"), 1)

    def test_helpers_defined_before_the_question_runs(self):
        # В bash функция существует только после своего объявления.
        # Раньше обе жили рядом с offer_tls — ниже места, где задаётся
        # вопрос про RustDesk, и вызов оттуда упал бы «command not found».
        definition = self.template.index("configured_domain() {")
        call_site = self.template.index("\nask_rustdesk\n")
        self.assertLess(definition, call_site)


class InstallerIntegration(unittest.TestCase):
    """Установщик разворачивает и сверяет RustDesk сам — это закреплено
    строковыми проверками, как RunnerRecipe в test_updater.py."""

    def test_compose_defines_hbbs_and_hbbr_under_rustdesk_profile(self):
        compose = open(os.path.join(ROOT, "docker-compose.yml"),
                       encoding="utf-8").read()
        self.assertIn("radar_hbbs", compose)
        self.assertIn("radar_hbbr", compose)
        self.assertIn('profiles: ["rustdesk"]', compose)
        self.assertIn("rustdesk/rustdesk-server", compose)

    def test_bot_gets_readonly_access_to_rustdesk_data(self):
        compose = open(os.path.join(ROOT, "docker-compose.yml"),
                       encoding="utf-8").read()
        self.assertIn("./data/rustdesk:/app/data/rustdesk:ro", compose)

    def test_installer_asks_and_verifies(self):
        template = open(os.path.join(ROOT, "tools", "install.template.sh"),
                        encoding="utf-8").read()
        self.assertIn("ask_rustdesk()", template)
        self.assertIn("verify_rustdesk_containers()", template)
        self.assertIn("--profile rustdesk", template)
        self.assertIn("ask_rustdesk\n", template)

    def test_installer_checks_image_not_just_name(self):
        # Баг-класс: чужой контейнер под тем же именем не должен молча
        # считаться "уже развёрнутым RustDesk".
        template = open(os.path.join(ROOT, "tools", "install.template.sh"),
                        encoding="utf-8").read()
        self.assertIn("rustdesk_mismatch", template)


class PanelRoutes(unittest.TestCase):
    """Страница RustDesk в веб-панели закрыта правами суперадминистратора —
    тот же риск-класс, что «Обновление», по образцу PanelRoutes
    в tests/test_updater.py."""

    def setUp(self) -> None:
        self.source = open(os.path.join(ROOT, "radar", "web", "panel.py"),
                           encoding="utf-8").read()

    def test_page_is_owner_only(self) -> None:
        index = self.source.index("async def rustdesk_page")
        self.assertIn("@owner_only", self.source[index - 40:index])

    def test_action_is_post_with_form_guard(self) -> None:
        self.assertIn('web.post("/rustdesk/action", rustdesk_action)', self.source)
        self.assertNotIn('web.get("/rustdesk/action"', self.source)
        index = self.source.index("async def rustdesk_action")
        body = self.source[index:index + 400]
        self.assertIn('_guarded_form(request, "superadmin")', body)

    def test_menu_item_always_visible(self) -> None:
        was = features.enabled("rustdesk")
        features.set_local("rustdesk", False)
        try:
            from radar.web import panel

            pages = [item[2] for item in panel._links_for("superadmin")]
        finally:
            features.set_local("rustdesk", was)
        self.assertIn("rustdesk", pages)

    def test_rustdesk_lives_under_overview(self) -> None:
        from radar.web import panel

        overview = next(group for group in panel._nav_groups("superadmin")
                        if group[2] == "home")
        self.assertIn("rustdesk", [item[2] for item in overview[3]])

    def test_page_offers_to_enable_itself(self) -> None:
        self.assertIn('name="key" value="rustdesk"', self.source)
        self.assertIn("Включить RustDesk", self.source)

    def test_toggle_returns_where_it_came_from(self) -> None:
        self.assertIn('name="back" value="/rustdesk"', self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
