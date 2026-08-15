#!/usr/bin/env python3
"""Выход в сеть, выбор провайдера ИИ и чтение ВКонтакте."""

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import provider, proxy  # noqa: E402

VLESS = (
    "vless://11111111-2222-3333-4444-555555555555@example.ru:443"
    "?security=reality&sni=www.microsoft.com&pbk=ABCdef&sid=1a2b&fp=chrome"
    "&type=tcp&flow=xtls-rprx-vision#Германия%20Reality"
)
SHADOWSOCKS = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@1.2.3.4:8388#Нидерланды"
TROJAN = "trojan://secret@trojan.example:443?sni=trojan.example#Финляндия"
SOCKS = "socks5://10.0.0.1:1080"


class TestParsing(unittest.TestCase):
    def test_vless(self):
        server = proxy.parse_uri(VLESS)
        self.assertIsNotNone(server)
        self.assertEqual(server.protocol, "vless")
        self.assertEqual(server.host, "example.ru")
        self.assertEqual(server.port, 443)
        self.assertEqual(server.security, "reality")
        self.assertEqual(server.public_key, "ABCdef")
        self.assertEqual(server.title, "Германия Reality")

    def test_shadowsocks_base64_credentials(self):
        server = proxy.parse_uri(SHADOWSOCKS)
        self.assertIsNotNone(server)
        self.assertEqual(server.protocol, "ss")
        self.assertEqual(server.method, "aes-256-gcm")
        self.assertEqual(server.password, "password")
        self.assertEqual(server.port, 8388)

    def test_trojan(self):
        server = proxy.parse_uri(TROJAN)
        self.assertEqual(server.protocol, "trojan")
        self.assertEqual(server.password, "secret")
        self.assertEqual(server.security, "tls")

    def test_socks(self):
        server = proxy.parse_uri(SOCKS)
        self.assertEqual(server.protocol, "socks5")
        self.assertEqual(server.port, 1080)

    def test_garbage_rejected(self):
        for text in ("", "просто текст", "ftp://host", "vless://"):
            self.assertIsNone(proxy.parse_uri(text))

    def test_subscription_plain(self):
        payload = "\n".join([VLESS, SHADOWSOCKS, TROJAN])
        servers = proxy.parse_subscription(payload)
        self.assertEqual(len(servers), 3)

    def test_subscription_base64(self):
        import base64

        payload = base64.b64encode("\n".join([VLESS, SOCKS]).encode()).decode()
        servers = proxy.parse_subscription(payload)
        self.assertEqual(len(servers), 2)

    def test_subscription_deduplicates(self):
        servers = proxy.parse_subscription("\n".join([VLESS, VLESS]))
        self.assertEqual(len(servers), 1)

    def test_subscription_skips_broken_lines(self):
        payload = "\n".join([VLESS, "мусор", "", TROJAN])
        self.assertEqual(len(proxy.parse_subscription(payload)), 2)

    def test_subscription_url_detection(self):
        self.assertTrue(proxy.is_subscription_url("https://host:8000/sub/abc"))
        self.assertFalse(proxy.is_subscription_url("http://10.0.0.1:8080"))
        self.assertFalse(proxy.is_subscription_url("vless://x@host:443"))


class TestConfig(unittest.TestCase):
    def test_reality_outbound(self):
        server = proxy.parse_uri(VLESS)
        outbound = server.to_outbound()
        self.assertEqual(outbound["type"], "vless")
        self.assertTrue(outbound["tls"]["reality"]["enabled"])
        self.assertEqual(outbound["tls"]["reality"]["public_key"], "ABCdef")

    def test_shadowsocks_outbound(self):
        outbound = proxy.parse_uri(SHADOWSOCKS).to_outbound()
        self.assertEqual(outbound["type"], "shadowsocks")
        self.assertEqual(outbound["method"], "aes-256-gcm")

    def test_config_has_local_socks(self):
        config = proxy.build_config(proxy.parse_uri(VLESS))
        self.assertEqual(config["inbounds"][0]["listen_port"], proxy.LOCAL_PORT)
        self.assertEqual(config["route"]["final"], "proxy")

    def test_config_is_valid_json(self):
        rendered = proxy.render_config(proxy.parse_uri(TROJAN))
        self.assertIsInstance(json.loads(rendered), dict)


class TestState(unittest.TestCase):
    """Ключ сам по себе ничего не включает — это главное правило."""

    def test_nothing_active_without_selection(self):
        state = proxy.ProxyState(servers=proxy.parse_subscription(VLESS))
        self.assertIsNone(state.active)

    def test_selection_without_enable_is_inactive(self):
        servers = proxy.parse_subscription(VLESS)
        state = proxy.ProxyState(servers=servers, selected=servers[0].key)
        self.assertIsNone(state.active)

    def test_active_after_enable(self):
        servers = proxy.parse_subscription(VLESS)
        state = proxy.ProxyState(
            servers=servers, selected=servers[0].key, enabled=True
        )
        self.assertIsNotNone(state.active)

    def test_describe_warns_when_not_selected(self):
        state = proxy.ProxyState(servers=proxy.parse_subscription(VLESS))
        self.assertIn("не выбран", proxy.describe(state))

    def test_describe_without_servers(self):
        self.assertIn("напрямую", proxy.describe(proxy.ProxyState()))

    def test_grouping_by_protocol(self):
        state = proxy.ProxyState(
            servers=proxy.parse_subscription("\n".join([VLESS, SHADOWSOCKS, TROJAN]))
        )
        self.assertEqual(set(state.by_protocol()), {"vless", "ss", "trojan"})

    def test_key_is_stable(self):
        first = proxy.parse_uri(VLESS)
        second = proxy.parse_uri(VLESS)
        self.assertEqual(first.key, second.key)


class TestProviderSwitch(unittest.TestCase):
    def test_known_providers(self):
        self.assertIn(provider.GEMINI, provider.PROVIDERS)
        self.assertIn(provider.DEEPSEEK, provider.PROVIDERS)

    def test_deepseek_marked_paid(self):
        self.assertTrue(provider.PROVIDERS[provider.DEEPSEEK].paid)
        self.assertFalse(provider.PROVIDERS[provider.GEMINI].paid)

    def test_unknown_provider_rejected(self):
        self.assertFalse(provider.select("что-то", persist=False))

    def test_select_requires_key(self):
        """Без ключа переключение не проходит — иначе разбор молча сломается."""
        self.assertFalse(provider.select(provider.DEEPSEEK, persist=False))

    def test_health_icons(self):
        self.assertEqual(provider.Health(provider="x", ok=True).icon, "✅")
        self.assertEqual(provider.Health(provider="x").icon, "❌")
        self.assertEqual(
            provider.Health(provider="x", ok=True, balance_low=True).icon, "⚠️"
        )

    def test_render_without_keys(self):
        self.assertIn("не задано", provider.render({}))

    def test_render_marks_active(self):
        results = {provider.GEMINI: provider.Health(provider=provider.GEMINI, ok=True)}
        self.assertIn("активен", provider.render(results))


class TestVkParsing(unittest.TestCase):
    """Разбор ответов VK: ошибки приходят с кодом 200."""

    def test_rate_codes_known(self):
        from radar.sources import VK_RATE_CODES

        self.assertIn(6, VK_RATE_CODES)
        self.assertIn(9, VK_RATE_CODES)

    def test_module_exposes_fetch(self):
        from radar import sources

        self.assertTrue(hasattr(sources, "fetch_vk"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
