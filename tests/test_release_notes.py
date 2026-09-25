#!/usr/bin/env python3
"""Автоматический выпуск (5.0): версия, текст релиза и запрет выпуска назад.

Сам workflow в тестах не запускается — проверяется то, что он берёт
из репозитория: без этого релиз вышел бы с пустым текстом или старым
номером, и заметили бы это уже на странице релизов.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import release_notes  # noqa: E402


class CurrentTree(unittest.TestCase):
    def test_version_matches_package(self):
        with open(os.path.join(ROOT, "radar", "__init__.py"), encoding="utf-8") as handle:
            self.assertIn(f'"{release_notes.current_version()}"', handle.read())

    def test_current_version_has_text(self):
        title, body = release_notes.notes(release_notes.current_version())
        self.assertIn(release_notes.current_version(), title)
        self.assertTrue(body.strip())

    def test_workflow_uses_the_script(self):
        path = os.path.join(ROOT, ".github", "workflows", "release.yml")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for command in ("pending", "title", "body"):
            self.assertIn(f"release_notes.py {command}", text)
        self.assertIn("--target \"$sha\"", text)
        self.assertIn("conclusion == 'success'", text)


class Fallback(unittest.TestCase):
    """Без написанного руками файла текст собирается из RELEASES."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="radar-rel-"))
        (self.tmp / "radar").mkdir()
        (self.tmp / "radar" / "__init__.py").write_text('__version__ = "9.1"\n', encoding="utf-8")
        (self.tmp / "main.py").write_text(
            'RELEASES: list = [\n'
            '    ("9.1", ["🔐 <b>Жирно</b> и <code>код</code> &amp; '
            '<a href=\\"https://x.example\\">ссылка</a>"]),\n'
            '    ("9.0", ["старое"]),\n'
            ']\n', encoding="utf-8")

    def test_markdown_from_releases(self):
        title, body = release_notes.notes("9.1", self.tmp)
        self.assertEqual(title, "v9.1")
        self.assertEqual(body, "- 🔐 **Жирно** и `код` & [ссылка](https://x.example)\n")

    def test_written_file_wins(self):
        (self.tmp / "docs" / "releases").mkdir(parents=True)
        (self.tmp / "docs" / "releases" / "9.1.md").write_text(
            "# v9.1 — подзаголовок\n\nТекст.\n", encoding="utf-8")
        self.assertEqual(release_notes.notes("9.1", self.tmp),
                         ("v9.1 — подзаголовок", "Текст.\n"))

    def test_no_text_is_an_error(self):
        with self.assertRaises(SystemExit):
            release_notes.notes("9.2", self.tmp)


class Pending(unittest.TestCase):
    """Два выпуска в одной ветке — по релизу на каждый, на своём коммите."""

    def setUp(self):
        import shutil
        import subprocess

        if shutil.which("git") is None:
            self.skipTest("нет git")
        self.tmp = Path(tempfile.mkdtemp(prefix="radar-git-"))
        self.run_git = lambda *args: subprocess.run(
            ["git", *args], cwd=self.tmp, check=True, capture_output=True, text=True).stdout
        self.run_git("init", "-q")
        self.run_git("config", "user.email", "t@example.com")
        self.run_git("config", "user.name", "t")
        (self.tmp / "radar").mkdir()
        self.shas = {}
        for version in ("5.0.2", "5.5", "5.6"):
            (self.tmp / "radar" / "__init__.py").write_text(
                f'__version__ = "{version}"\n', encoding="utf-8")
            self.run_git("add", "-A")
            self.run_git("commit", "-q", "-m", version)
            self.shas[version] = self.run_git("rev-parse", "HEAD").strip()
        # Правка после выпуска без смены номера — релиз должен встать на неё.
        (self.tmp / "note.txt").write_text("x", encoding="utf-8")
        self.run_git("add", "-A")
        self.run_git("commit", "-q", "-m", "после 5.6")
        self.shas["5.6"] = self.run_git("rev-parse", "HEAD").strip()

    def test_each_version_on_its_commit(self):
        result = release_notes.pending(["v5.0.2"], root=self.tmp)
        self.assertEqual(result, [("5.5", self.shas["5.5"]), ("5.6", self.shas["5.6"])])

    def test_nothing_older_than_released(self):
        self.assertEqual(release_notes.pending(["v5.5"], root=self.tmp),
                         [("5.6", self.shas["5.6"])])
        self.assertEqual(release_notes.pending(["v5.6"], root=self.tmp), [])

    def test_title_for_older_version(self):
        (self.tmp / "docs" / "releases").mkdir(parents=True)
        (self.tmp / "docs" / "releases" / "5.5.md").write_text("# v5.5 — старый\n\nТекст\n",
                                                                encoding="utf-8")
        self.assertEqual(release_notes.notes("5.5", self.tmp)[0], "v5.5 — старый")


class Ordering(unittest.TestCase):
    def test_newer_than_all(self):
        self.assertTrue(release_notes.is_newer("5.0", ["v4.9.9.4", "v4.9.9"]))
        self.assertTrue(release_notes.is_newer("4.10", ["v4.9.9.4"]))
        self.assertTrue(release_notes.is_newer("5.0", []))

    def test_not_newer(self):
        self.assertFalse(release_notes.is_newer("4.9.9.3", ["v4.9.9.4"]))
        self.assertFalse(release_notes.is_newer("5.0", ["v5.0"]))

    def test_foreign_tags_ignored(self):
        self.assertTrue(release_notes.is_newer("5.0", ["nightly", "v4.9"]))


if __name__ == "__main__":
    unittest.main()
