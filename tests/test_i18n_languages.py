#!/usr/bin/env python3
"""Языки интерфейса: русский, английский, украинский, персидский, китайский (с 5.9.6).

Закреплено то, что ломается тихо: пропавшая строка, потерянная подстановка
(`{name}` без значения роняет сообщение на живом сервере), расхождение
HTML-тегов (Telegram откажет разметке), перевод, оставшийся не на своём
языке, и цепочка запасных вариантов.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import astro, i18n, links, timezones, weather  # noqa: E402

NEW = (i18n.UK, i18n.FA, i18n.ZH)
CYRILLIC = re.compile(r"[а-яіїєґ]", re.IGNORECASE)
ARABIC = re.compile(r"[؀-ۿ]")
CJK = re.compile(r"[一-鿿]")


def placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{[a-z_0-9]*\}", text))


def tags(text: str) -> list[str]:
    return sorted(re.findall(r"</?[a-z]+(?: [^>]*)?>", text))


class Completeness(unittest.TestCase):
    def test_every_english_key_is_translated(self):
        for code in NEW:
            with self.subTest(language=code):
                table = i18n.TABLES[code]
                self.assertEqual([k for k in i18n.EN_STRINGS if k not in table], [])
                self.assertEqual([k for k in table if k not in i18n.EN_STRINGS], [])

    def test_no_empty_values(self):
        for code in NEW:
            for key, value in i18n.TABLES[code].items():
                with self.subTest(language=code, key=key):
                    self.assertTrue(value.strip())

    def test_placeholders_survive_translation(self):
        for code in NEW:
            for key, english in i18n.EN_STRINGS.items():
                with self.subTest(language=code, key=key):
                    self.assertEqual(placeholders(i18n.TABLES[code][key]),
                                     placeholders(english))

    def test_html_tags_survive_translation(self):
        for code in NEW:
            for key, english in i18n.EN_STRINGS.items():
                with self.subTest(language=code, key=key):
                    self.assertEqual(tags(i18n.TABLES[code][key]), tags(english))

    def test_commands_stay_latin(self):
        # Команды бота не переводятся: /check работает, «/проверить» — нет.
        for code in NEW:
            for key, english in i18n.EN_STRINGS.items():
                for command in re.findall(r"(?<![\w/])/[a-z_]+", english):
                    with self.subTest(language=code, key=key, command=command):
                        self.assertIn(command, i18n.TABLES[code][key])

    def test_each_language_uses_its_own_script(self):
        checks = {i18n.UK: CYRILLIC, i18n.FA: ARABIC, i18n.ZH: CJK}
        for code, pattern in checks.items():
            table = i18n.TABLES[code]
            # Подписи из латиницы и цифр (GB, VPN, RustDesk) допустимы.
            wordy = [k for k, v in table.items()
                     if re.search(r"[A-Za-z]{4,}", i18n.EN_STRINGS[k])
                     and not re.fullmatch(r"[\W\dA-Za-z]*", v)]
            native = [k for k in wordy if pattern.search(table[k])]
            with self.subTest(language=code):
                self.assertGreater(len(native) / max(1, len(wordy)), 0.97)

    def test_translations_differ_from_english(self):
        for code in NEW:
            same = [k for k, v in i18n.TABLES[code].items()
                    if v == i18n.EN_STRINGS[k] and re.search(r"[a-z]{4,}", v)]
            with self.subTest(language=code):
                # Допустимы только строки, где переводить нечего.
                self.assertLessEqual(len(same), 3, same)


class Lookup(unittest.TestCase):
    def test_languages_and_titles(self):
        self.assertEqual(i18n.LANGUAGES, ("ru", "en", "uk", "fa", "zh"))
        for code in i18n.LANGUAGES:
            self.assertIn(code, i18n.TITLES)

    def test_normalize(self):
        self.assertEqual(i18n.normalize("zh-Hans"), "zh")
        self.assertEqual(i18n.normalize("UK"), "uk")
        self.assertEqual(i18n.normalize("fa_IR"), "fa")
        self.assertEqual(i18n.normalize("xx"), "ru")
        self.assertEqual(i18n.normalize(None), "ru")

    def test_translated_lookup(self):
        self.assertEqual(i18n.t("menu.weather", "uk", "x"), "🌤 Погода")
        self.assertEqual(i18n.t("menu.weather", "zh", "x"), "🌤 天气")
        self.assertEqual(i18n.t("menu.weather", "fa", "x"), "🌤 آب‌وهوا")
        self.assertEqual(i18n.t("menu.weather", "ru", "русский"), "русский")

    def test_fallback_chain(self):
        # Украинцу — русская строка, персу и китайцу — английская.
        self.assertEqual(i18n.t("no.such.key", "uk", "русский"), "русский")
        self.assertEqual(i18n.t("no.such.key", "fa", "русский"), "русский")
        i18n.EN_STRINGS["__probe__"] = "english"
        try:
            self.assertEqual(i18n.t("__probe__", "uk", "русский"), "русский")
            self.assertEqual(i18n.t("__probe__", "fa", "русский"), "english")
            self.assertEqual(i18n.t("__probe__", "zh", "русский"), "english")
            self.assertEqual(i18n.t("__probe__", "en", "русский"), "english")
        finally:
            del i18n.EN_STRINGS["__probe__"]

    def test_language_of_user(self):
        self.assertEqual(i18n.language_of({"lang": "uk"}), "uk")
        self.assertEqual(i18n.language_of({"lang": ""}), "ru")

    def test_translate_target_names(self):
        self.assertEqual(i18n.TARGET_NAMES["zh"], "Simplified Chinese")
        self.assertIn("fa", i18n.TARGET_NAMES)

    def test_every_menu_label_formats_for_every_language(self):
        # Подстановки подходят к тем, что передаёт код.
        samples = {"{n}": 3, "{code}": "ABC", "{url}": "https://x", "{id}": "7",
                   "{name}": "N", "{count}": 2, "{total}": 5, "{page}": 1, "{pages}": 2,
                   "{role}": "R", "{nets}": "VK", "{net}": "VK", "{place}": "P",
                   "{limit}": 9, "{minutes}": 5, "{hours}": 24, "{gb}": 2,
                   "{height}": 480, "{size}": 10, "{time}": "5 min", "{pct}": 50,
                   "{label}": "720p", "{until}": "d", "{left}": 3, "{used}": "1",
                   "{channel}": "c", "{city}": "C", "{removed}": 1, "{channels}": 1,
                   "{feeds}": 1}
        for code in NEW:
            for key, value in i18n.TABLES[code].items():
                found = re.findall(r"\{[a-z_0-9]*\}", value)
                args = {item.strip("{}"): samples.get(item, "?") for item in found}
                with self.subTest(language=code, key=key):
                    value.format(**args)


class Surroundings(unittest.TestCase):
    def test_weekdays_and_rose_for_every_language(self):
        for code in i18n.LANGUAGES:
            with self.subTest(language=code):
                self.assertTrue(weather._day_label("2026-10-05", 5, code))
                self.assertTrue(astro.wind_short(0, code))
        self.assertEqual(weather._day_label("2026-10-05", 5, "zh").split()[0], "周一")
        self.assertEqual(weather._day_label("2026-10-05", 5, "uk").split()[0], "пн")
        self.assertEqual(astro.wind_short(90, "zh"), "东")
        self.assertEqual(astro.wind_short(90, "en"), "E")
        self.assertEqual(astro.wind_short(90, "ru"), "В")

    def test_timezone_label(self):
        self.assertTrue(timezones.label(180, "ru").startswith("МСК"))
        for code in ("en", "uk", "fa", "zh"):
            self.assertTrue(timezones.label(300, code).startswith("UTC"), code)

    def test_text_networks_understand_new_answers(self):
        for word in ("так", "بله", "是", "yes", "да"):
            self.assertIn(word, links.YES)
        for word in ("ні", "خیر", "否", "no", "нет"):
            self.assertIn(word, links.NO)
        self.assertFalse(set(links.YES) & set(links.NO))

    def test_text_networks_switch_language_command(self):
        from radar.platforms import textbot

        for code in ("ru", "en", "uk", "fa", "zh"):
            self.assertTrue(textbot._LANG_RE.match(f"/lang {code}"), code)
        self.assertFalse(textbot._LANG_RE.match("/lang xx"))

    def test_chooser_lists_every_language(self):
        from radar.handlers import language

        keyboard = language.language_keyboard()
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        self.assertEqual([b.callback_data for b in buttons],
                         [f"lng:{code}" for code in i18n.LANGUAGES])
        for code in i18n.LANGUAGES:
            self.assertIn(i18n.TITLES[code], [b.text for b in buttons])
        for word in ("Choose your language", "Выберите язык", "Оберіть мову",
                     "زبان خود را انتخاب کنید", "请选择语言"):
            self.assertIn(word, language.ASK_TEXT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
