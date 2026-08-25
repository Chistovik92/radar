#!/usr/bin/env python3
"""Сжатие ролика под предел отправки.

Разрезание на части было отвергнуто: человек не должен собирать видео
обратно сам. Осталось сжатие — и у него есть предел, который не обходится
арифметикой: битрейт задаётся длительностью. 50 МБ на час видео — это
110 кбит/с, чего не хватает ни на какое разрешение.

Поэтому главное, что проверяют тесты, — не то, что сжатие работает,
а то, что оно **отказывается** там, где результат был бы обманом
ожиданий.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import transcode  # noqa: E402


MINUTE = 60


class TestBudget(unittest.TestCase):
    def test_shorter_clip_gets_more_bitrate(self):
        short = transcode.budget_kbps(50, 5 * MINUTE)
        long = transcode.budget_kbps(50, 30 * MINUTE)
        self.assertGreater(short, long)

    def test_safety_margin_applied(self):
        """Кодировщик не попадает в целевой размер до байта."""
        exact = 50 * 1024 * 1024 * 8 / (5 * MINUTE) / 1000
        self.assertLess(transcode.budget_kbps(50, 5 * MINUTE), exact)

    def test_zero_duration_is_zero(self):
        self.assertEqual(transcode.budget_kbps(50, 0), 0)
        self.assertEqual(transcode.budget_kbps(50, -10), 0)


class TestPlanRefuses(unittest.TestCase):
    """Отказ важнее результата: мыло вместо видео — обман ожидания."""

    def test_hour_long_clip_refused(self):
        self.assertIsNone(transcode.plan(60 * MINUTE, 50))

    def test_very_long_clip_refused(self):
        self.assertIsNone(transcode.plan(3 * 60 * MINUTE, 50))

    def test_zero_duration_refused(self):
        self.assertIsNone(transcode.plan(0, 50))

    def test_zero_target_refused(self):
        self.assertIsNone(transcode.plan(5 * MINUTE, 0))

    def test_refusal_explains_the_arithmetic(self):
        text = transcode.too_long_message(60 * MINUTE, 50)
        self.assertIn("кбит/с", text)
        self.assertIn("240p", text)
        self.assertIn("2 ГБ", text)   # подсказка про свой Bot API Server

    def test_boundary_between_yes_and_no(self):
        """Где-то между 20 и 60 минутами проходит граница — она должна
        быть монотонной, а не случайной."""
        results = [transcode.plan(minutes * MINUTE, 50) is not None
                   for minutes in range(2, 70, 2)]
        # После первого отказа не должно снова появляться согласие.
        if False in results:
            first_no = results.index(False)
            self.assertNotIn(True, results[first_no:])


class TestPlanChoices(unittest.TestCase):
    def test_short_clip_keeps_decent_height(self):
        made = transcode.plan(3 * MINUTE, 50)
        self.assertIsNotNone(made)
        self.assertGreaterEqual(made.height, 480)

    def test_longer_clip_drops_height(self):
        short = transcode.plan(3 * MINUTE, 50)
        longer = transcode.plan(20 * MINUTE, 50)
        self.assertIsNotNone(longer)
        self.assertLess(longer.height, short.height)

    def test_never_upscales(self):
        """Растягивать вверх — тратить битрейт на выдуманные пиксели."""
        made = transcode.plan(2 * MINUTE, 50, source_height=240)
        self.assertEqual(made.height, 240)

    def test_audio_reduced_on_tight_budget(self):
        # 20 минут при 50 МБ — уже впритык (граница отказа около 24),
        # но план ещё выдаётся: на звук уходит меньше.
        roomy = transcode.plan(2 * MINUTE, 50)
        tight = transcode.plan(20 * MINUTE, 50)
        self.assertIsNotNone(tight)
        self.assertEqual(roomy.audio_kbps, transcode.AUDIO_KBPS)
        self.assertEqual(tight.audio_kbps, transcode.AUDIO_KBPS_LOW)

    def test_total_fits_the_target(self):
        """Сумма потоков должна укладываться в целевой размер."""
        made = transcode.plan(10 * MINUTE, 50)
        produced_mb = made.total_kbps * 1000 * made.duration_s / 8 / 1024 / 1024
        self.assertLessEqual(produced_mb, 50)

    def test_bigger_target_allows_bigger_height(self):
        small = transcode.plan(10 * MINUTE, 50)
        large = transcode.plan(10 * MINUTE, 500)
        self.assertGreater(large.height, small.height)


class TestEstimate(unittest.TestCase):
    def test_longer_clip_takes_longer_at_same_height(self):
        """Оговорка, найденная тестом: сравнивать надо при равной высоте.

        Длинному ролику достаётся меньшее разрешение, а оно кодируется
        быстрее — поэтому «длиннее» само по себе не значит «дольше».
        Зависимость от длительности видна только при равном кадре.
        """
        short = transcode.Plan(height=480, video_kbps=800, audio_kbps=96,
                               target_mb=50, duration_s=3 * MINUTE)
        longer = transcode.Plan(height=480, video_kbps=800, audio_kbps=96,
                                target_mb=50, duration_s=15 * MINUTE)
        self.assertGreater(transcode.estimate_seconds(longer),
                           transcode.estimate_seconds(short))

    def test_bigger_frame_takes_longer_at_same_duration(self):
        small = transcode.Plan(height=240, video_kbps=300, audio_kbps=64,
                               target_mb=50, duration_s=10 * MINUTE)
        big = transcode.Plan(height=720, video_kbps=2000, audio_kbps=96,
                             target_mb=50, duration_s=10 * MINUTE)
        self.assertGreater(transcode.estimate_seconds(big),
                           transcode.estimate_seconds(small))

    def test_estimate_is_pessimistic_not_instant(self):
        """Обещать сорок минут и уложиться в двадцать лучше, чем наоборот."""
        made = transcode.plan(10 * MINUTE, 50)
        self.assertGreater(transcode.estimate_seconds(made), 60)

    def test_human_time_reads_naturally(self):
        self.assertEqual(transcode.human_time(30), "меньше минуты")
        self.assertIn("мин", transcode.human_time(25 * MINUTE))
        self.assertIn("ч", transcode.human_time(90 * MINUTE))


class TestFfmpegArgs(unittest.TestCase):
    def setUp(self):
        self.plan = transcode.plan(5 * MINUTE, 50)

    def test_output_is_telegram_friendly(self):
        """h264 + aac + faststart — то, ради чего всё затевалось."""
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan)
        self.assertIn("libx264", args)
        self.assertIn("aac", args)
        self.assertIn("+faststart", args)

    def test_threads_limited(self):
        """Два ядра из четырёх остаются циклу оповещений."""
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan)
        index = args.index("-threads")
        self.assertEqual(int(args[index + 1]), transcode.THREADS)
        self.assertLess(transcode.THREADS, 4)

    def test_nice_prefix_when_available(self):
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan, nice=True)
        self.assertEqual(args[0], "nice")
        self.assertIn("19", args[:3])

    def test_no_nice_prefix_when_absent(self):
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan, nice=False)
        self.assertEqual(args[0], "ffmpeg")

    def test_fast_preset(self):
        """На A53 всё медленнее veryfast превращает минуты в часы."""
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan)
        index = args.index("-preset")
        self.assertIn(args[index + 1], ("veryfast", "superfast", "ultrafast"))

    def test_peaks_are_capped(self):
        """Без maxrate файл вылезет за предел на сложных сценах."""
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan)
        self.assertIn("-maxrate", args)
        self.assertIn("-bufsize", args)

    def test_scale_keeps_even_width(self):
        """scale=-2 — ширина кратна двум, иначе x264 откажется."""
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan)
        index = args.index("-vf")
        self.assertTrue(args[index + 1].startswith("scale=-2:"))

    def test_paths_present(self):
        args = transcode.ffmpeg_args("in.mp4", "out.mp4", self.plan)
        self.assertIn("in.mp4", args)
        self.assertEqual(args[-1], "out.mp4")


class TestProgress(unittest.TestCase):
    def test_share_from_out_time(self):
        share = transcode.parse_progress("out_time_us=60000000", 120)
        self.assertAlmostEqual(share, 0.5, places=2)

    def test_other_lines_ignored(self):
        for line in ("frame=42", "speed=1.2x", "", "bitrate=N/A"):
            with self.subTest(line=line):
                self.assertIsNone(transcode.parse_progress(line, 120))

    def test_never_exceeds_one(self):
        self.assertEqual(transcode.parse_progress("out_time_us=999999999", 10), 1.0)

    def test_negative_treated_as_zero(self):
        self.assertEqual(transcode.parse_progress("out_time_us=-5", 10), 0.0)

    def test_garbage_value_ignored(self):
        self.assertIsNone(transcode.parse_progress("out_time_us=N/A", 120))

    def test_unknown_duration_ignored(self):
        self.assertIsNone(transcode.parse_progress("out_time_us=1000", 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
