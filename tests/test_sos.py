#!/usr/bin/env python3
"""Кнопка SOS и устойчивость системы к отказам.

Проверяется поведение в ситуациях, которые случаются в бою: недоступный
источник, повреждённые данные, пустые ответы, отсутствующие поля, обрыв
сети. Система должна деградировать предсказуемо, а не падать.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import sos  # noqa: E402
from radar.matching import Analysis, heuristic_analysis, plan_alerts  # noqa: E402


def blank_user() -> dict:
    return {"role": "user", "locs": [], "sos_contacts": []}


# ==========================================================================
#  SOS
# ==========================================================================

class TestSosContacts(unittest.TestCase):
    def setUp(self):
        self.user = blank_user()
        sos._active.clear()

    def test_add_and_list(self):
        contact, error = sos.add_contact(self.user, "12345", "Мама")
        self.assertEqual(error, "")
        self.assertIsNotNone(contact)
        self.assertEqual(len(sos.contacts_of(self.user)), 1)
        self.assertFalse(contact.confirmed)
        self.assertTrue(contact.invite)

    def test_duplicate_rejected(self):
        sos.add_contact(self.user, "12345", "Мама")
        contact, error = sos.add_contact(self.user, "12345", "Мама ещё раз")
        self.assertIsNone(contact)
        self.assertIn("уже добавлен", error)

    def test_limit_enforced(self):
        for index in range(sos.MAX_CONTACTS):
            sos.add_contact(self.user, f"1000{index}", f"Контакт {index}")
        contact, error = sos.add_contact(self.user, "99999", "Лишний")
        self.assertIsNone(contact)
        self.assertIn("Больше", error)

    def test_remove(self):
        sos.add_contact(self.user, "12345", "Мама")
        self.assertTrue(sos.remove_contact(self.user, "12345"))
        self.assertFalse(sos.remove_contact(self.user, "12345"))
        self.assertEqual(sos.contacts_of(self.user), [])

    def test_unconfirmed_not_counted(self):
        sos.add_contact(self.user, "12345", "Мама")
        self.assertEqual(sos.confirmed_contacts(self.user), [])

    def test_confirmation_by_invite(self):
        contact, _ = sos.add_contact(self.user, "12345", "Мама")
        confirmed = sos.confirm_by_invite(self.user, contact.invite, "12345")
        self.assertIsNotNone(confirmed)
        self.assertEqual(len(sos.confirmed_contacts(self.user)), 1)

    def test_wrong_invite_ignored(self):
        sos.add_contact(self.user, "12345", "Мама")
        self.assertIsNone(sos.confirm_by_invite(self.user, "чужой-код", "999"))

    def test_find_by_invite_across_users(self):
        other = blank_user()
        contact, _ = sos.add_contact(other, "777", "Брат")
        found = sos.find_by_invite({"1": self.user, "2": other}, contact.invite)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], "2")

    def test_invites_are_unique(self):
        first, _ = sos.add_contact(self.user, "1111", "А")
        second, _ = sos.add_contact(self.user, "2222", "Б")
        self.assertNotEqual(first.invite, second.invite)

    def test_serialization_roundtrip(self):
        sos.add_contact(self.user, "12345", "Мама")
        restored = sos.Contact.from_dict(self.user["sos_contacts"][0])
        self.assertEqual(restored.key, "12345")
        self.assertEqual(restored.title, "Мама")

    def test_broken_contact_record_survives(self):
        """Мусор в данных не должен ронять разбор списка."""
        self.user["sos_contacts"] = [{}, {"key": "5"}, {"title": "без ключа"}]
        contacts = sos.contacts_of(self.user)
        self.assertEqual(len(contacts), 3)
        self.assertEqual(contacts[1].key, "5")


class TestSosMessages(unittest.TestCase):
    def test_alert_contains_essentials(self):
        text = sos.build_alert("Иван", "@ivan", 51.533, 46.034, "улица Чапаева, 12")
        self.assertIn("ПРОСЬБА О ПОМОЩИ", text)
        self.assertIn("51.533", text)
        self.assertIn("Чапаева", text)
        self.assertIn("112", text)
        self.assertIn("maps.google.com", text)

    def test_alert_escapes_input(self):
        text = sos.build_alert("<script>", "", 51.5, 46.0, "<b>адрес</b>")
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_repeat_marked(self):
        text = sos.build_alert("Иван", "", 51.5, 46.0, repeat=3)
        self.assertIn("Повтор 3", text)

    def test_receipt_lists_failures(self):
        contacts = [sos.Contact(key="1", title="Мама", confirmed=True)]
        text = sos.build_receipt(contacts, ["Мама"])
        self.assertIn("Не доставлено", text)
        self.assertIn("112", text)

    def test_invite_text_has_link(self):
        text = sos.build_invite_text("Иван", "SecretHeroBot", "abc123")
        self.assertIn("?start=sos_abc123", text)


class TestSosAlerts(unittest.TestCase):
    def setUp(self):
        sos._active.clear()

    def tearDown(self):
        sos._active.clear()

    def test_start_and_stop(self):
        sos.start_alert("42", 51.5, 46.0, "адрес", "")
        self.assertIsNotNone(sos.active_alert("42"))
        self.assertTrue(sos.stop_alert("42"))
        self.assertIsNone(sos.active_alert("42"))

    def test_repeat_not_due_immediately(self):
        sos.start_alert("42", 51.5, 46.0, "", "")
        self.assertEqual(sos.due_alerts(), [])

    def test_repeat_due_after_interval(self):
        alert = sos.start_alert("42", 51.5, 46.0, "", "")
        alert.last_sent = time.time() - sos.REPEAT_MINUTES * 60 - 1
        self.assertEqual(len(sos.due_alerts()), 1)

    def test_repeat_limit(self):
        alert = sos.start_alert("42", 51.5, 46.0, "", "")
        alert.repeats = sos.MAX_REPEATS
        alert.last_sent = 0
        self.assertEqual(sos.due_alerts(), [])

    def test_stop_unknown_is_safe(self):
        self.assertFalse(sos.stop_alert("нет такого"))


# ==========================================================================
#  Отказоустойчивость
# ==========================================================================

class TestResilienceParsing(unittest.TestCase):
    """Разбор не должен падать на неполных и повреждённых данных."""

    def test_empty_text(self):
        analysis = heuristic_analysis("", source="x")
        self.assertFalse(analysis.relevant)

    def test_huge_text(self):
        analysis = heuristic_analysis("отключение воды " * 5000, source="x")
        self.assertTrue(analysis.relevant)
        self.assertLessEqual(len(analysis.summary), 400)

    def test_payload_missing_fields(self):
        analysis = Analysis.from_payload({}, source="s", raw="текст")
        self.assertFalse(analysis.relevant)
        self.assertEqual(analysis.categories, [])

    def test_payload_wrong_types(self):
        analysis = Analysis.from_payload(
            {"relevant": "да", "categories": "jkh", "streets": "улица",
             "districts": None, "severity": 42, "scope": []},
            source="s", raw="текст",
        )
        self.assertIsInstance(analysis.categories, list)
        self.assertIsInstance(analysis.streets, list)
        self.assertIn(analysis.severity, ("info", "warning", "critical"))

    def test_unknown_categories_dropped(self):
        analysis = Analysis.from_payload(
            {"relevant": True, "categories": ["jkh", "выдуманное", 5]},
            source="s", raw="т",
        )
        self.assertEqual(analysis.categories, ["jkh"])

    def test_relevant_without_categories_is_noise(self):
        analysis = Analysis.from_payload(
            {"relevant": True, "categories": []}, source="s", raw="т"
        )
        self.assertFalse(analysis.relevant)


class TestResiliencePlanning(unittest.TestCase):
    """Планировщик оповещений на неполных данных."""

    def test_location_without_coordinates(self):
        loc = {"id": "a", "name": "Без координат", "lat": 0.0, "lon": 0.0,
               "city": "Саратов", "district": "", "region": "", "street": "", "house": ""}
        alert = Analysis(relevant=True, categories=["bpla"], scope="city",
                         city="Саратов", summary="БПЛА", source="s")
        messages = plan_alerts([loc], {"bpla": True}, [alert])
        self.assertEqual(len(messages), 1)

    def test_location_missing_keys(self):
        """Локация из старой базы без части полей не должна ронять разбор."""
        loc = {"id": "a", "name": "Старая", "lat": 51.5, "lon": 46.0}
        alert = Analysis(relevant=True, categories=["bpla"], scope="city",
                         city="Саратов", summary="БПЛА", source="s")
        # Разбор не падает; сообщения нет — у локации неизвестна география,
        # а рассылать тревогу «на всякий случай» опаснее, чем промолчать
        self.assertEqual(plan_alerts([loc], {"bpla": True}, [alert]), [])

    def test_location_without_city_gets_address_alert(self):
        """Адресное событие доходит и до локации без города — по улице."""
        loc = {"id": "a", "name": "Чапаева, 12", "lat": 51.5, "lon": 46.0,
               "street": "улица Чапаева", "house": "12"}
        alert = Analysis(relevant=True, categories=["jkh"], scope="street",
                         streets=[{"street": "улица Чапаева", "houses": ["12"]}],
                         summary="Нет воды", source="s")
        self.assertEqual(len(plan_alerts([loc], {"jkh": True}, [alert])), 1)

    def test_empty_settings(self):
        loc = {"id": "a", "name": "A", "lat": 51.5, "lon": 46.0, "city": "Саратов"}
        alert = Analysis(relevant=True, categories=["bpla"], scope="city",
                         city="Саратов", source="s")
        self.assertEqual(plan_alerts([loc], {}, [alert]), [])

    def test_many_locations_do_not_explode(self):
        locs = [
            {"id": str(i), "name": f"Точка {i}", "lat": 51.5 + i * 0.01,
             "lon": 46.0, "city": "Саратов"}
            for i in range(60)
        ]
        alert = Analysis(relevant=True, categories=["bpla"], scope="city",
                         city="Саратов", summary="БПЛА", source="s")
        messages = plan_alerts(locs, {"bpla": True}, [alert])
        # Военная угроза — одно сообщение на город, сколько бы точек ни было
        self.assertEqual(len(messages), 1)


class TestResilienceStorage(unittest.TestCase):
    """Импортёр на повреждённых данных."""

    def setUp(self):
        from radar.db import importer

        self.importer = importer

    def test_garbage_input(self):
        for payload in ({}, {"users": None}, {"users": {"1": "строка"}},
                        {"channels": 42}, {"users": {"1": {"locs": "не список"}}}):
            data = self.importer._normalize(dict(payload))
            self.assertIn("users", data)
            self.assertIsInstance(data["users"], dict)

    def test_location_without_name_skipped(self):
        data = self.importer._normalize(
            {"users": {"7": {"role": "user", "locs": [{"lat": 1, "lon": 2}]}}}
        )
        self.assertEqual(data["users"]["7"]["locs"], [])

    def test_settings_normalized(self):
        data = self.importer._normalize(
            {"users": {"7": {"role": "user", "settings": {"jkh": "да"}}}}
        )
        for key in ("jkh", "bpla", "mchs", "whitelist"):
            self.assertIn(key, data["users"]["7"]["settings"])

    def test_json_roundtrip_survives(self):
        """Нормализованные данные должны сериализоваться без потерь."""
        data = self.importer._normalize(
            {"users": {"7": {"role": "user",
                             "locs": [{"name": "Улица, 1", "lat": 51.5, "lon": 46.0}]}}}
        )
        restored = json.loads(json.dumps(data, ensure_ascii=False))
        self.assertEqual(restored["users"]["7"]["locs"][0]["name"], "Улица, 1")


class TestResilienceFeatures(unittest.TestCase):
    def test_unknown_flag_is_off_not_error(self):
        from radar import features

        self.assertFalse(features.enabled("несуществующий_флаг"))

    def test_apply_ignores_garbage(self):
        from radar import features

        features.apply({"alerts": False, "чепуха": True, "sos": "да"})
        self.assertTrue(features.enabled("alerts"))   # ядро не выключается
        self.assertTrue(features.enabled("sos"))      # строка приводится к bool
        features.apply({})


if __name__ == "__main__":
    unittest.main(verbosity=2)
