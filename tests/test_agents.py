#!/usr/bin/env python3
"""Свои агенты ИИ: слоты, наследие прежней пары, попадание в список моделей.

До 4.8.8 свой агент был ровно один — пара `CUSTOM_AI_URL`/`CUSTOM_AI_KEY`
среди двух десятков чужих ключей. Сервисов бывает несколько: локальная
модель на этой же машине, корпоративный шлюз, чей-то прокси.

Здесь закреплены три вещи, каждая из которых ломается тихо:

* прежняя пара не теряется при обновлении — она показывается первым
  слотом, пока тот пуст;
* агент без адреса или без ключа не попадает в список выбора: предложить
  заведомо неработающее хуже, чем не предложить ничего;
* у каждого агента свой адрес. До 4.8.8 адрес был один на всех, и второй
  агент молча ходил бы по адресу первого.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import agents, provider, secrets  # noqa: E402


class AgentsCase(unittest.TestCase):
    """Настройки подменяются словарём: тесты не трогают .env машины."""

    def setUp(self) -> None:
        self.values: dict[str, str] = {}
        patcher = mock.patch.object(
            secrets, "get", lambda key: self.values.get(key, ""))
        patcher.start()
        self.addCleanup(patcher.stop)

        def write(key: str, value: str) -> bool:
            self.values[key] = value
            return True

        writer = mock.patch.object(secrets, "write", write)
        writer.start()
        self.addCleanup(writer.stop)

    def fill(self, slot: int, title: str = "", url: str = "", key: str = "",
             model: str = "") -> None:
        title_env, url_env, key_env, model_env = agents.env_names(slot)
        self.values[title_env] = title
        self.values[url_env] = url
        self.values[key_env] = key
        self.values[model_env] = model


class Slots(AgentsCase):
    def test_empty_by_default(self) -> None:
        self.assertEqual(agents.load(), [])
        self.assertEqual(agents.ready(), [])

    def test_saved_agent_read_back(self) -> None:
        self.assertTrue(agents.save(2, "Локальная Llama",
                                    "http://ollama:11434/v1", "к"))
        found = agents.load()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].slot, 2)
        self.assertEqual(found[0].title, "Локальная Llama")
        self.assertEqual(found[0].name, "custom2")

    def test_order_by_slot(self) -> None:
        agents.save(3, "третий", "https://c.ru/v1", "к")
        agents.save(1, "первый", "https://a.ru/v1", "к")
        self.assertEqual([item.slot for item in agents.load()], [1, 3])

    def test_trailing_slash_dropped(self) -> None:
        agents.save(1, "имя", "https://a.ru/v1/", "к")
        self.assertEqual(agents.load()[0].url, "https://a.ru/v1")

    def test_bad_url_refused(self) -> None:
        for url in ("", "ollama:11434", "ftp://a.ru", "не адрес"):
            with self.subTest(url=url):
                self.assertFalse(agents.save(1, "имя", url, "к"))

    def test_bad_slot_refused(self) -> None:
        for slot in (0, -1, 999, "нет"):
            with self.subTest(slot=slot):
                self.assertFalse(agents.save(slot, "имя", "https://a.ru/v1", "к"))

    def test_free_slot_skips_busy(self) -> None:
        agents.save(1, "a", "https://a.ru/v1", "к")
        agents.save(2, "b", "https://b.ru/v1", "к")
        self.assertEqual(agents.free_slot(), 3)

    def test_forget_clears(self) -> None:
        agents.save(1, "имя", "https://a.ru/v1", "к")
        self.assertTrue(agents.forget(1))
        self.assertEqual(agents.load(), [])

    def test_title_optional(self) -> None:
        agents.save(4, "", "https://a.ru/v1", "к")
        self.assertEqual(agents.load()[0].shown, "Свой агент 4")


class Readiness(AgentsCase):
    def test_needs_url_and_key(self) -> None:
        # Ключ без адреса никуда не ведёт, адрес без ключа тоже.
        self.fill(1, "без ключа", "https://a.ru/v1", "")
        self.fill(2, "без адреса", "", "к")
        self.assertEqual(agents.ready(), [])

    def test_complete_agent_is_ready(self) -> None:
        self.fill(1, "полный", "https://a.ru/v1", "к")
        self.assertEqual(len(agents.ready()), 1)


class Legacy(AgentsCase):
    """Прежняя пара не должна потеряться при обновлении."""

    def test_shown_as_first_slot(self) -> None:
        self.values[agents.LEGACY_URL_ENV] = "http://ollama:11434/v1"
        self.values[agents.LEGACY_KEY_ENV] = "старый"
        found = agents.load()
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].legacy)
        self.assertEqual(found[0].name, "custom")

    def test_new_slot_one_wins(self) -> None:
        # Заведённый первый слот вытесняет наследие: иначе человек правил
        # бы слот и видел прежнее значение.
        self.values[agents.LEGACY_URL_ENV] = "http://старый/v1"
        self.values[agents.LEGACY_KEY_ENV] = "старый"
        agents.save(1, "новый", "https://новый.ру/v1", "новый")
        found = agents.load()
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].legacy)
        self.assertEqual(found[0].url, "https://новый.ру/v1")

    def test_forgetting_first_slot_clears_legacy_too(self) -> None:
        # Иначе очищенный слот тут же снова заполнился бы наследием,
        # и кнопка «удалить» выглядела бы сломанной.
        self.values[agents.LEGACY_URL_ENV] = "http://старый/v1"
        self.values[agents.LEGACY_KEY_ENV] = "старый"
        agents.forget(1)
        self.assertEqual(agents.load(), [])


class InProviderList(AgentsCase):
    """Агенты обязаны попадать в общий список провайдеров."""

    def test_ready_agent_appears(self) -> None:
        self.fill(2, "Локальная Llama", "http://ollama:11434/v1", "к")
        infos = provider.all_infos()
        self.assertIn("custom2", infos)
        self.assertEqual(infos["custom2"].title, "Локальная Llama")

    def test_each_agent_keeps_its_own_address(self) -> None:
        # Главная поломка, которую чинит 4.8.8: адрес был один на всех,
        # и второй агент ходил бы по адресу первого.
        self.fill(1, "первый", "https://first.ru/v1", "к")
        self.fill(2, "второй", "https://second.ru/v1", "к")
        infos = provider.all_infos()
        self.assertEqual(infos["custom1"].url(), "https://first.ru/v1")
        self.assertEqual(infos["custom2"].url(), "https://second.ru/v1")

    def test_incomplete_agent_not_offered(self) -> None:
        self.fill(1, "без ключа", "https://a.ru/v1", "")
        self.assertNotIn("custom1", {item.key for item in provider.available()})

    def test_complete_agent_offered(self) -> None:
        self.fill(1, "полный", "https://a.ru/v1", "к")
        self.assertIn("custom1", {item.key for item in provider.available()})

    def test_builtins_still_present(self) -> None:
        self.assertIn(provider.GEMINI, provider.all_infos())
        self.assertIn(provider.CUSTOM, provider.all_infos())

    def test_legacy_not_duplicated(self) -> None:
        # Наследие уже описано записью CUSTOM; второй раз показывать его
        # значило бы предложить один сервис дважды.
        self.values[agents.LEGACY_URL_ENV] = "http://ollama:11434/v1"
        self.values[agents.LEGACY_KEY_ENV] = "старый"
        self.assertNotIn("custom1", provider.all_infos())


class SettingsRegistry(unittest.TestCase):
    """Слоты обязаны быть видны в разделе ключей бота."""

    def test_bot_slots_present(self) -> None:
        for slot in range(1, secrets.AGENT_SLOTS + 1):
            for name in secrets.agent_env_names(slot):
                with self.subTest(name=name):
                    self.assertIn(name, secrets.BY_KEY)

    def test_grouped_together(self) -> None:
        self.assertIn(secrets.AGENT_GROUP, secrets.GROUPS)
        group = secrets.by_group()[secrets.AGENT_GROUP]
        # Четыре поля на слот: название, адрес, ключ, модель.
        self.assertEqual(len(group), secrets.AGENT_SLOTS * 4)

    def test_old_pair_left_the_key_list(self) -> None:
        # Две строки среди чужих ключей заменены разделом; иначе один
        # сервис настраивался бы в двух местах сразу.
        self.assertNotIn("CUSTOM_AI_URL", secrets.BY_KEY)
        self.assertNotIn("CUSTOM_AI_KEY", secrets.BY_KEY)

    def test_key_is_secret_and_address_is_not(self) -> None:
        title_env, url_env, key_env, model_env = secrets.agent_env_names(1)
        self.assertFalse(secrets.BY_KEY[url_env].secret)
        self.assertFalse(secrets.BY_KEY[title_env].secret)
        self.assertFalse(secrets.BY_KEY[model_env].secret)
        self.assertTrue(secrets.BY_KEY[key_env].secret)

    def test_model_shares_the_name_with_built_in_providers(self) -> None:
        # Иначе выбранная модель хранилась бы в двух местах: в слоте
        # и в общем выборе модели, который есть у каждого провайдера.
        from radar import provider

        self.assertEqual(secrets.agent_env_names(2)[3],
                         provider.model_env("custom2"))


class Models(AgentsCase):
    """Модель агента вписывается руками: списка у своего сервиса не спросить."""

    def test_model_saved_and_read(self) -> None:
        agents.save(1, "Локальная", "http://ollama:11434/v1", "к", "llama3.1:8b")
        self.assertEqual(agents.load()[0].model, "llama3.1:8b")

    def test_model_optional(self) -> None:
        agents.save(1, "Локальная", "http://ollama:11434/v1", "к")
        self.assertEqual(agents.load()[0].model, "")

    def test_model_reaches_provider(self) -> None:
        from radar import provider

        self.fill(3, "Локальная", "http://ollama:11434/v1", "к", "llama3.1:8b")
        self.assertEqual(provider.model_of("custom3"), "llama3.1:8b")


if __name__ == "__main__":
    unittest.main()
