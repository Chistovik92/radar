#!/usr/bin/env python3
"""Свой агент и выбор модели у провайдера — 4.8.2.

До этой версии в списке провайдеров было двое: Gemini и DeepSeek. При этом
`.env` предлагал завести ключи OpenRouter, Mistral, Moonshot, Qwen, Z.ai
и OpenAI — то есть ключ завести было можно, а выбрать провайдера нельзя.
Ключ, который никуда не подключается, ничем не лучше тумблера,
не включающего функцию.

Второе: у OpenRouter моделей десятки, и вписывать имя руками — верный
способ опечататься так, что выяснится это при первом разборе настоящей
тревоги. Поэтому список забирается у самого провайдера.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import provider, secrets  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestCatalogue(unittest.TestCase):
    def test_promised_keys_have_providers(self):
        """Ключ из .env, которому не соответствует провайдер, — обман."""
        keys = {item.key for item in secrets.SETTINGS if item.group == "ИИ"}
        wired = {item.env for item in provider.PROVIDERS.values()}
        # Anthropic намеренно без провайдера: у него свой протокол,
        # не совместимый с OpenAI. Все остальные должны быть подключены.
        expected = {
            "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
            "MISTRAL_API_KEY", "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY",
            "ZAI_API_KEY", "OPENAI_API_KEY", "CEREBRAS_API_KEY",
        }
        self.assertTrue(expected <= keys, "ключи пропали из secrets")
        self.assertTrue(expected <= wired, f"без провайдера: {expected - wired}")

    def test_every_openai_provider_has_a_url(self):
        for name, info in provider.PROVIDERS.items():
            if info.kind != provider.KIND_OPENAI or info.custom:
                continue
            with self.subTest(provider=name):
                self.assertTrue(info.base_url, f"{name} без адреса")
                self.assertFalse(info.base_url.endswith("/"))

    def test_gemini_is_its_own_kind(self):
        """У Gemini свой протокол, и путать его с OpenAI нельзя."""
        self.assertEqual(provider.PROVIDERS[provider.GEMINI].kind,
                         provider.KIND_GEMINI)

    def test_custom_provider_declared(self):
        info = provider.PROVIDERS[provider.CUSTOM]
        self.assertTrue(info.custom)
        self.assertEqual(info.base_url, "", "адрес своего агента задаёт человек")

    def test_openrouter_has_no_default_model(self):
        """Выбрать модель за человека — потратить его деньги на своё
        усмотрение."""
        self.assertEqual(provider.PROVIDERS[provider.OPENROUTER].default_model, "")


class TestAvailability(unittest.TestCase):
    def test_key_alone_is_enough_for_normal_provider(self):
        with mock.patch.object(secrets, "get",
                               side_effect=lambda k: "ключ" if k == "MISTRAL_API_KEY" else ""):
            names = [item.key for item in provider.available()]
        self.assertIn(provider.MISTRAL, names)

    def test_custom_needs_an_address_too(self):
        """Ключ без адреса никуда не ведёт — предлагать такое нельзя."""
        with mock.patch.object(secrets, "get",
                               side_effect=lambda k: "ключ" if k == provider.CUSTOM_KEY_ENV else ""):
            names = [item.key for item in provider.available()]
        self.assertNotIn(provider.CUSTOM, names)

    def test_custom_appears_with_address(self):
        values = {provider.CUSTOM_KEY_ENV: "ключ",
                  provider.CUSTOM_URL_ENV: "http://ollama:11434/v1"}
        with mock.patch.object(secrets, "get", side_effect=lambda k: values.get(k, "")):
            names = [item.key for item in provider.available()]
        self.assertIn(provider.CUSTOM, names)

    def test_no_keys_no_providers(self):
        with mock.patch.object(secrets, "get", return_value=""):
            self.assertEqual(provider.available(), [])


class TestCustomUrl(unittest.TestCase):
    def test_trailing_slash_removed(self):
        """Иначе получился бы адрес с двойной косой чертой."""
        with mock.patch.object(secrets, "get", return_value="http://host:8080/v1/"):
            self.assertEqual(provider.PROVIDERS[provider.CUSTOM].url(),
                             "http://host:8080/v1")

    def test_builtin_url_not_taken_from_secrets(self):
        with mock.patch.object(secrets, "get", return_value="подмена"):
            self.assertIn("deepseek", provider.PROVIDERS[provider.DEEPSEEK].url())


class TestModelChoice(unittest.TestCase):
    def test_setting_name(self):
        self.assertEqual(provider.model_env("openrouter"), "AI_MODEL_OPENROUTER")

    def test_default_when_nothing_chosen(self):
        with mock.patch.object(secrets, "get", return_value=""):
            self.assertEqual(provider.model_of(provider.DEEPSEEK), "deepseek-chat")

    def test_chosen_wins_over_default(self):
        with mock.patch.object(secrets, "get",
                               side_effect=lambda k: "своя-модель"
                               if k == "AI_MODEL_DEEPSEEK" else ""):
            self.assertEqual(provider.model_of(provider.DEEPSEEK), "своя-модель")

    def test_unknown_provider(self):
        self.assertEqual(provider.model_of("выдумка"), "")
        self.assertFalse(provider.set_model("выдумка", "что-то"))


class TestListModels(unittest.TestCase):
    def _session(self, payload, status=200):
        class Response:
            def __init__(self):
                self.status = status

            async def json(self, **_kw):
                return payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        class Session:
            def get(self, *_a, **_kw):
                return Response()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        return Session()

    def _run(self, payload, status=200, name=None):
        name = name or provider.OPENROUTER

        # Патчим `provider.aiohttp`, а не сам модуль aiohttp: соседние
        # файлы тестов ставят свои заглушки, и в общем прогоне объект
        # в sys.modules оказывается не тем, который держит provider.
        # В одиночку тест при этом проходил — ровно та ловушка, ради
        # которой в проекте прогоняют каждый файл отдельно.
        with mock.patch.object(secrets, "get", return_value="ключ"), \
             mock.patch.object(provider.aiohttp, "ClientSession",
                               return_value=self._session(payload, status)):
            return run(provider.list_models(name))

    def test_openai_format_parsed(self):
        names = self._run({"data": [{"id": "gpt-x"}, {"id": "llama-y"}]})
        self.assertEqual(names, ["gpt-x", "llama-y"])

    def test_sorted_for_stable_order(self):
        """У OpenRouter порядок выдачи произвольный — выбирать в таком
        списке неудобно."""
        names = self._run({"data": [{"id": "я"}, {"id": "а"}, {"id": "м"}]})
        self.assertEqual(names, sorted(names))

    def test_duplicates_removed(self):
        names = self._run({"data": [{"id": "one"}, {"id": "one"}]})
        self.assertEqual(names, ["one"])

    def test_garbage_entries_skipped(self):
        names = self._run({"data": [{"id": "ok"}, {}, None, {"id": ""}]})
        self.assertEqual(names, ["ok"])

    def test_http_error_returns_empty(self):
        self.assertEqual(self._run({}, status=401), [])

    def test_gemini_not_supported_here(self):
        """У Gemini свой протокол и свой discover_models."""
        with mock.patch.object(secrets, "get", return_value="ключ"):
            self.assertEqual(run(provider.list_models(provider.GEMINI)), [])

    def test_without_key_no_request(self):
        with mock.patch.object(secrets, "get", return_value=""):
            self.assertEqual(run(provider.list_models(provider.OPENROUTER)), [])

    def test_custom_without_url_no_request(self):
        values = {provider.CUSTOM_KEY_ENV: "ключ"}
        with mock.patch.object(secrets, "get", side_effect=lambda k: values.get(k, "")):
            self.assertEqual(run(provider.list_models(provider.CUSTOM)), [])


class TestFreeFirst(unittest.TestCase):
    """Бесплатные модели вперёд: их у OpenRouter помечают суффиксом."""

    def test_free_moved_up(self):
        names = provider.free_first(["a/model", "b/model:free", "c/model"])
        self.assertEqual(names[0], "b/model:free")

    def test_order_within_groups_kept(self):
        names = provider.free_first(["a", "b", "x:free", "y:free"])
        self.assertEqual(names, ["x:free", "y:free", "a", "b"])

    def test_empty(self):
        self.assertEqual(provider.free_first([]), [])


class GeminiModelList(unittest.TestCase):
    """Ключ Google заведён — список моделей обязан быть.

    Раньше `list_models` отказывала всему, что не совместимо с OpenAI,
    и человек с рабочим ключом Google видел пустой список: ключ есть,
    а выбрать нечего. Вводить ключ заново он не обязан — спросить модели
    можно и так, своим протоколом.
    """

    def test_gemini_asks_its_own_api(self) -> None:
        from radar import ai, provider

        async def fake_discover():
            return ["gemini-3.6-flash", "gemini-3.5-pro"]

        with mock.patch.object(ai, "discover_models", fake_discover):
            names = asyncio.run(provider.list_models(provider.GEMINI))
        self.assertEqual(names, ["gemini-3.6-flash", "gemini-3.5-pro"])

    def test_failure_is_not_an_error(self) -> None:
        from radar import ai, provider

        async def broken():
            raise RuntimeError("сеть недоступна")

        with mock.patch.object(ai, "discover_models", broken):
            self.assertEqual(asyncio.run(provider.list_models(provider.GEMINI)), [])

    def test_limit_respected(self) -> None:
        from radar import ai, provider

        async def many():
            return [f"model-{i}" for i in range(100)]

        with mock.patch.object(ai, "discover_models", many):
            self.assertEqual(
                len(asyncio.run(provider.list_models(provider.GEMINI, limit=5))), 5)


class AssistantRouting(unittest.TestCase):
    """Ассистентом может быть не только Gemini."""

    def test_openai_provider_used_for_chat(self) -> None:
        # До 4.9.1 свободный диалог всегда уходил в Gemini: человек
        # переключал провайдера, а отвечал ему прежний.
        from radar import ai, provider

        seen = {}

        async def fake_chat(messages, name="", **kwargs):
            seen["name"] = name
            seen["messages"] = messages
            return "ответ"

        with mock.patch.object(provider, "current", return_value="deepseek"),                 mock.patch.object(ai, "_openai_chat", fake_chat):
            answer = asyncio.run(ai.assistant([], "вопрос"))

        self.assertEqual(answer, "ответ")
        self.assertEqual(seen["name"], "deepseek")
        self.assertEqual(seen["messages"][-1]["content"], "вопрос")
        self.assertEqual(seen["messages"][0]["role"], "system")

    def test_history_converted(self) -> None:
        from radar import ai

        # Свои объекты вместо клиентских: в офлайн-проверках библиотека
        # Gemini подменена заглушкой, и её Content ничего не хранит.
        class Part:
            def __init__(self, text):
                self.text = text

        class Turn:
            def __init__(self, role, text):
                self.role = role
                self.parts = [Part(text)]

        history = [Turn("user", "первый"), Turn("model", "ответ")]
        messages = ai._as_messages(history, "второй")
        self.assertEqual([item["role"] for item in messages],
                         ["system", "user", "assistant", "user"])
        self.assertEqual(messages[-1]["content"], "второй")


if __name__ == "__main__":
    unittest.main(verbosity=2)
