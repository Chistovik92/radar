#!/usr/bin/env python3
"""Удаление молчащих источников (5.9.2.1): что отбирается и чего не трогаем."""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import sourcecheck, sourceedit, sourceprune, storage  # noqa: E402

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def status(kind, ref, state, days=None, note=""):
    last = NOW - timedelta(days=days) if days is not None else None
    return sourcecheck.SourceStatus(kind=kind, ref=ref, state=state, note=note, last_post=last)


def report(*items):
    return sourcecheck.CheckReport(statuses=list(items))


class SelectTests(unittest.TestCase):
    def test_silent_beyond_threshold_only(self) -> None:
        rep = report(status("tg", "fresh", sourcecheck.ALIVE, 2),
                     status("tg", "old", sourcecheck.STALE, 45),
                     status("tg", "edge", sourcecheck.ALIVE, 30))
        chosen = sourceprune.select(rep, 30, now=NOW)
        self.assertEqual([c.ref for c in chosen], ["old"])
        self.assertIn("45", chosen[0].reason)

    def test_threshold_is_independent_of_stale_days(self) -> None:
        rep = report(status("tg", "mid", sourcecheck.STALE, 20))
        self.assertEqual(sourceprune.select(rep, 30, now=NOW), [])
        self.assertEqual(len(sourceprune.select(rep, 10, now=NOW)), 1)

    def test_unknown_date_is_kept(self) -> None:
        rep = report(status("rss", "https://x/feed", sourcecheck.ALIVE, None))
        self.assertEqual(sourceprune.select(rep, 1, now=NOW), [])

    def test_dead_only_on_request(self) -> None:
        rep = report(status("tg", "gone", sourcecheck.DEAD, None, "нет постов"))
        self.assertEqual(sourceprune.select(rep, 30, now=NOW), [])
        chosen = sourceprune.select(rep, 30, dead=True, now=NOW)
        self.assertEqual([c.ref for c in chosen], ["gone"])
        self.assertIn("нет постов", chosen[0].reason)

    def test_vk_is_never_touched(self) -> None:
        rep = report(status("vk", "club1", sourcecheck.DEAD, None),
                     status("vk", "club2", sourcecheck.STALE, 500))
        self.assertEqual(sourceprune.select(rep, 1, dead=True, now=NOW), [])


class SuspiciousTests(unittest.TestCase):
    def test_mass_failure_is_not_believed(self) -> None:
        rep = report(*[status("tg", f"c{i}", sourcecheck.DEAD) for i in range(4)],
                     status("tg", "ok", sourcecheck.ALIVE, 1))
        self.assertTrue(sourceprune.suspicious(rep))

    def test_few_failures_are_believed(self) -> None:
        rep = report(status("tg", "a", sourcecheck.DEAD),
                     *[status("tg", f"c{i}", sourcecheck.ALIVE, 1) for i in range(5)])
        self.assertEqual(sourceprune.suspicious(rep), "")

    def test_tiny_lists_say_nothing(self) -> None:
        rep = report(status("tg", "a", sourcecheck.DEAD), status("tg", "b", sourcecheck.DEAD))
        self.assertEqual(sourceprune.suspicious(rep), "")


class ApplyTests(unittest.TestCase):
    def test_removes_only_chosen_from_the_lists(self) -> None:
        channels = ["keep", "old"]
        feeds = ["https://x/feed"]
        with mock.patch.object(storage, "channels", lambda: channels), \
                mock.patch.object(storage, "rss_feeds", lambda: feeds), \
                mock.patch.object(storage, "vk_groups", lambda: []):
            rep = report(status("tg", "keep", sourcecheck.ALIVE, 1),
                         status("tg", "old", sourcecheck.STALE, 90),
                         status("rss", "https://x/feed", sourcecheck.STALE, 90))
            removed = sourceprune.apply(sourceprune.select(rep, 30, now=NOW))
        self.assertEqual(sorted(c.ref for c in removed), ["https://x/feed", "old"])
        self.assertEqual(channels, ["keep"])
        self.assertEqual(feeds, [])
        self.assertEqual(sourceedit.TELEGRAM, "tg")



class CliParserTests(unittest.TestCase):
    def test_prune_flags_parse(self) -> None:
        from radar import cli

        args = cli.build_parser().parse_args(
            ["sources", "prune", "--days", "60", "--dead", "--yes", "--pause", "0.1"])
        self.assertEqual((args.action, args.days, args.dead, args.yes, args.force, args.pause),
                         ("prune", 60, True, True, False, 0.1))
        defaults = cli.build_parser().parse_args(["sources", "prune"])
        self.assertEqual((defaults.days, defaults.dead, defaults.yes), (30, False, False))

    def test_old_actions_still_parse(self) -> None:
        from radar import cli

        args = cli.build_parser().parse_args(["sources", "add", "telegram", "some_channel"])
        self.assertEqual((args.action, args.kind, args.value), ("add", "telegram", "some_channel"))


if __name__ == "__main__":
    unittest.main()
