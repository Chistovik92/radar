#!/usr/bin/env python3
"""4.9.9.3: всё, что оставалось открытым в дорожной карте до 5.0.

* метрики и здоровье системы одним экраном (4.9, п.3 и п.6);
* реклама VPN в пересылаемых текстах;
* музыка: подборки по жанру и артисту, данные из открытых баз (4.9.5);
* перевод экранов модератора (4.7.5, п.20).
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

from radar import adfilter, digest, features, i18n, metrics, monitor, music, musicmeta  # noqa: E402
from radar.matching import Analysis  # noqa: E402


# --------------------------------------------------------------------------
#  Метрики
# --------------------------------------------------------------------------

class PercentileTests(unittest.TestCase):
    def test_median_and_p90(self):
        values = [float(v) for v in range(1, 101)]
        self.assertEqual(metrics.percentile(values, 0.5), 51.0)
        self.assertEqual(metrics.percentile(values, 0.9), 90.0)

    def test_empty_is_zero(self):
        self.assertEqual(metrics.percentile([], 0.5), 0.0)
        self.assertEqual(metrics.latency([])["count"], 0.0)


class LatencyTests(unittest.TestCase):
    """Задержка пишется только для событий, а не для сводок и памяток."""

    def setUp(self) -> None:
        monitor._latency.clear()

    def tearDown(self) -> None:
        monitor._latency.clear()

    def _analysis(self, raw: str, **flags) -> Analysis:
        item = Analysis(relevant=True, categories=["jkh"], raw=raw)
        for key, value in flags.items():
            setattr(item, key, value)
        return item

    def test_recorded_for_live_events(self):
        now = 10_000.0
        count = monitor.record_latency(
            [self._analysis("авария")], {"авария": now - 120}, now)
        self.assertEqual(count, 1)
        self.assertEqual(monitor.latency_samples(), [120.0])

    def test_skipped_for_history_guidance_and_unknown_time(self):
        now = 10_000.0
        items = [
            self._analysis("вчера", historical=True),
            self._analysis("памятка", guidance=True),
            self._analysis("без времени"),
        ]
        published = {"вчера": now - 60, "памятка": now - 60}
        self.assertEqual(monitor.record_latency(items, published, now), 0)

    def test_old_news_is_not_latency(self):
        """Всплывшая старая новость — не задержка доставки."""
        now = 10_000_000.0
        count = monitor.record_latency(
            [self._analysis("старое")],
            {"старое": now - monitor.LATENCY_CEILING - 1}, now)
        self.assertEqual(count, 0)


class RenderTests(unittest.TestCase):
    """Экран собирается и без половины данных: сбой части не прячет другие."""

    def test_empty_snapshot_renders(self):
        text = metrics.render({})
        self.assertIn("Метрики", text)
        self.assertIn("Сокет Docker не смонтирован", text)

    def test_full_snapshot_renders(self):
        text = metrics.render({
            "cycle": {"cycles": 10, "alerts": 5, "delivered": 3,
                      "last_cycle": 1_700_000_000, "restarts": 1,
                      "healthy": True, "silent": 10},
            "latency": {"count": 4.0, "median": 95.0, "p90": 300.0},
            "quota": {"used_today": 50, "limit_day": 200, "paused": False},
            "sources": {"total": 20, "dead": 2, "stale": 1, "alive": 17,
                        "at": "2026-09-20 03:00"},
            "memory": {"total": 3915, "available": 3084},
            "disks": [{"path": ".", "used": 10, "total": 100, "percent": 90}],
            "database": {"kind": "SQLite", "report": "SQLite: 12 МБ"},
            "containers": {"socket": True, "rows": [
                {"name": "radar_container", "state": "running",
                 "health": "healthy", "status": "Up"},
                {"name": "radar_rclone", "state": "exited",
                 "health": "", "status": "Exited"},
            ]},
        })
        self.assertIn("Доставлено оповещений о событиях: <b>3</b>", text)
        self.assertIn("медиана", text)
        self.assertIn("50/200", text)
        self.assertIn("2 из 20", text)
        self.assertIn("⚠️ Диск", text)          # 90% выше порога
        self.assertIn("🟢 radar_container", text)
        self.assertIn("🔴 radar_rclone", text)


class DisksTests(unittest.TestCase):
    def test_same_disk_listed_once(self):
        rows = metrics.disks([".", "."])
        self.assertEqual(len(rows), 1)

    def test_missing_path_skipped(self):
        self.assertEqual(metrics.disks(["/нет/такого/пути"]), [])


# --------------------------------------------------------------------------
#  Реклама VPN
# --------------------------------------------------------------------------

class VpnAdTests(unittest.TestCase):
    def tearDown(self) -> None:
        features.apply({})

    def test_ad_paragraph_cut_news_kept(self):
        text = ("Завтра с 10 до 16 отключат воду на улице Чапаева.\n\n"
                "Быстрый VPN без блокировок! Промокод RADAR — скидка 50%.")
        cleaned, cut = adfilter.strip(text)
        self.assertEqual(cut, 1)
        self.assertIn("отключат воду", cleaned)
        self.assertNotIn("Промокод", cleaned)
        self.assertIn(adfilter.NEUTRAL_STUB, cleaned)

    def test_news_about_vpn_is_not_ad(self):
        text = "Роскомнадзор заблокировал ещё несколько VPN-протоколов."
        self.assertEqual(adfilter.strip(text), (text, 0))

    def test_legal_marking_in_next_paragraph(self):
        """«Реклама. erid» часто стоит отдельной строкой после VPN."""
        text = "Надёжный VPN для всей семьи.\nРеклама. ООО «Ромашка», erid: 2Vtzq"
        cleaned, cut = adfilter.strip(text)
        self.assertGreaterEqual(cut, 1)
        self.assertNotIn("Надёжный VPN", cleaned)

    def test_consecutive_ad_paragraphs_one_stub(self):
        text = "VPN без блокировок, промокод X.\nПодключай VPN по ссылке, скидка 30%."
        cleaned, _cut = adfilter.strip(text)
        self.assertEqual(cleaned.count(adfilter.NEUTRAL_STUB), 1)

    def test_flag_off_keeps_everything(self):
        features.set_local("vpn_ad_filter", False)
        text = "VPN без блокировок, промокод X."
        self.assertEqual(adfilter.strip(text), (text, 0))

    def test_alerts_never_get_partner(self):
        """Реклама в тревогах недопустима, в том числе своя."""
        from radar import matching

        item = Analysis(relevant=True, categories=["jkh"], source="x",
                        raw="Нет воды.\n\nVPN без блокировок, промокод X.",
                        summary="Нет воды.\n\nVPN без блокировок, промокод X.")
        line = matching._event_line(item)
        self.assertNotIn("промокод", line)
        self.assertNotIn("партнёр", line)
        self.assertNotIn("HydraSite", line)

    def test_digest_gets_one_partner_line(self):
        entries = [
            digest.Entry(topic="utilities", summary="Во вторник отключат горячую воду."),
            digest.Entry(topic="utilities", summary="Быстрый VPN, промокод GAME, скидка 50%."),
            digest.Entry(topic="utilities", summary="Лучший VPN без блокировок — скидка 30%."),
        ]
        subscription = digest.Subscription(topics=["utilities"])
        with mock.patch.object(adfilter, "partner_stub",
                               return_value="PARTNER-STUB"):
            text = digest.build(entries, subscription,
                                digest.datetime(2026, 9, 20, 9, 0))
        self.assertIn("горячую воду", text)
        self.assertNotIn("промокод", text.lower())
        self.assertEqual(text.count("PARTNER-STUB"), 1)


# --------------------------------------------------------------------------
#  Музыка
# --------------------------------------------------------------------------

def library() -> dict:
    user: dict = {}
    for index, (artist, genre) in enumerate([
        ("Кино", "Rock"), ("Кино", "Rock"), ("ДДТ", "rock"),
        ("Земфира", "Pop"), ("Сплин", ""),
    ]):
        music.add_track(user, f"t{index}", name=f"трек {index}", ext=".mp3",
                        size=1, artist=artist, title=f"песня {index}",
                        genre=genre)
    return user


class SmartPlaylistTests(unittest.TestCase):
    def test_choices_counted_and_filtered(self):
        user = library()
        genres = dict(music.smart_choices(user, "genre"))
        # rock и Rock — один жанр; Pop один трек — подборкой не считается
        self.assertEqual(sum(genres.values()), 3)
        self.assertEqual(len(genres), 1)
        artists = dict(music.smart_choices(user, "artist"))
        self.assertEqual(artists, {"Кино": 2})

    def test_build_and_rebuild_without_duplicates(self):
        user = library()
        ok, name = music.build_smart_playlist(user, "genre", "rock")
        self.assertTrue(ok)
        self.assertEqual(len(music.playlist_tracks(user, name)), 3)
        music.build_smart_playlist(user, "genre", "rock")
        names = [pl["name"] for pl in music.playlists_of(user)]
        self.assertEqual(names.count(name), 1)

    def test_single_track_refused(self):
        ok, reason = music.build_smart_playlist(library(), "genre", "Pop")
        self.assertFalse(ok)
        self.assertIn("два", reason)

    def test_related_artist_counts_as_similar(self):
        user = library()
        base = music.find_track(user, "t4")      # Сплин, без жанра
        base["related"] = ["Земфира"]
        found = [t["id"] for t in music.similar(user, "t4")]
        self.assertIn("t3", found)


class MusicMetaTests(unittest.TestCase):
    def test_recording_genre_and_artist(self):
        payload = {"recordings": [{
            "genres": [{"name": "post-punk", "count": 3},
                       {"name": "rock", "count": 7}],
            "artist-credit": [{"artist": {"id": "mbid-1"}}],
        }]}
        self.assertEqual(musicmeta.parse_recording(payload), ("rock", "mbid-1"))

    def test_tags_when_no_genres(self):
        payload = {"recordings": [{"tags": [{"name": "russian", "count": 2}]}]}
        self.assertEqual(musicmeta.parse_recording(payload)[0], "russian")

    def test_nothing_found(self):
        self.assertEqual(musicmeta.parse_recording({}), ("", ""))

    def test_similar_names(self):
        payload = [{"name": "ДДТ"}, {"artist_name": "Аквариум"}, {"name": "ДДТ"}, "мусор"]
        self.assertEqual(musicmeta.parse_similar(payload), ["ДДТ", "Аквариум"])

    def test_own_genre_not_overwritten(self):
        track = {"genre": "Шансон"}
        musicmeta.apply(track, {"genre": "rock", "related": ["X"]})
        self.assertEqual(track["genre"], "Шансон")
        self.assertEqual(track["related"], ["X"])

    def test_lucene_escaped(self):
        self.assertEqual(musicmeta._quote('AC/DC: "Live"'), 'AC\\/DC\\: \\"Live\\"')


# --------------------------------------------------------------------------
#  Переводы экранов модератора
# --------------------------------------------------------------------------

class ModeratorTranslationTests(unittest.TestCase):
    """Каждый ключ экранов модератора переведён — иначе английский
    интерфейс молча показал бы русскую строку."""

    PREFIXES = ("users.", "ucard.", "mod.", "src.", "chats.")

    def test_keys_used_in_code_are_translated(self):
        import re

        used: set[str] = set()
        for name in ("radar/handlers/users.py", "radar/handlers/sources.py",
                     "radar/handlers/chats.py", "radar/keyboards.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                source = handle.read()
            used.update(re.findall(r'"((?:users|ucard|mod|src|chats)\.[a-z_]+)"', source))
        self.assertTrue(used)
        missing = sorted(key for key in used
                         if i18n.t(key, "en", "\x00") == "\x00")
        self.assertEqual(missing, [])

    def test_english_card_has_no_russian_labels(self):
        from radar.handlers import users

        with mock.patch("radar.storage.get_user",
                        return_value={"role": "user", "locs": [], "lang": "en"}):
            text = users._card_text("42", {"lang": "en"})
        self.assertIn("Role", text)
        self.assertNotIn("Роль", text)


if __name__ == "__main__":
    unittest.main()
