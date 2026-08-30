#!/usr/bin/env python3
"""Файл .env: приоритет над окружением, запись на месте, права.

Проверки написаны после поломки, найденной на живом сервере. Файл .env
не был смонтирован в контейнер: Compose передавал его значения через
`env_file`, а окружение читается один раз, при создании контейнера.
Из-за этого бот выдавал короткие ссылки на домен, стёртый из .env двумя
днями раньше, а ключи, заданные через раздел настроек, уходили в файл
внутри контейнера и исчезали при первом же обновлении.

Отсюда два требования, которые здесь и закреплены:

* значение из .env перевешивает значение из окружения процесса —
  иначе правка на хосте не действует до пересоздания контейнера;
* запись сохраняет ИНОД файла. Bind-mount привязан к иноду, и подмена
  через переименование оставила бы контейнер читать прежний файл.
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import stubcheck  # noqa: E402

stubcheck.install()

from radar import backup, secrets  # noqa: E402

SAMPLE = "\n".join([
    "# комментарий сохраняется",
    "BOT_TOKEN=123:abc",
    "SHORT_BASE_URL=https://boot.example.ru",
    "",
])


class EnvFileCase(unittest.TestCase):
    """Общая подготовка: свой .env во временном каталоге."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, ".env")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(SAMPLE)

        self.saved_path = secrets.ENV_PATH
        secrets.ENV_PATH = self.path

        # Копия перед правкой к предмету проверки не относится, а в тестах
        # создала бы каталог в репозитории.
        patcher = mock.patch.object(backup, "backup_env", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.saved_environ = dict(os.environ)

    def tearDown(self) -> None:
        secrets.ENV_PATH = self.saved_path
        os.environ.clear()
        os.environ.update(self.saved_environ)
        self.directory.cleanup()

    def contents(self) -> str:
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()


class ReadPriority(EnvFileCase):
    """Что перевешивает: файл или окружение процесса."""

    def test_file_wins_over_environment(self) -> None:
        # Ровно эта ситуация была на сервере: в окружении контейнера
        # остался домен, стёртый из .env двумя днями раньше.
        os.environ["SHORT_BASE_URL"] = "https://home.example.ru"
        self.assertEqual(secrets.get("SHORT_BASE_URL"),
                         "https://boot.example.ru")

    def test_environment_used_when_key_absent(self) -> None:
        os.environ["GEMINI_API_KEY"] = "из-окружения"
        self.assertEqual(secrets.get("GEMINI_API_KEY"), "из-окружения")

    def test_missing_file_is_not_an_error(self) -> None:
        secrets.ENV_PATH = os.path.join(self.directory.name, "нет-такого")
        os.environ["BOT_TOKEN"] = "запасной"
        self.assertEqual(secrets.get("BOT_TOKEN"), "запасной")


class WriteKeepsInode(EnvFileCase):
    """Запись не должна подменять файл новым."""

    def inode(self) -> int:
        return os.stat(self.path).st_ino

    def test_inode_survives_write(self) -> None:
        # Главное свойство: файл правится на месте. Инод тот же — значит
        # контейнер, которому .env смонтирован, увидит новое значение.
        before = self.inode()
        self.assertTrue(secrets.write("SHORT_BASE_URL", "https://новый.ру"))
        self.assertEqual(secrets.get("SHORT_BASE_URL"), "https://новый.ру")
        if before:  # на некоторых файловых системах st_ino нулевой
            self.assertEqual(self.inode(), before)

    def test_no_rename_involved(self) -> None:
        # Подмена через переименование в точку монтирования вернула бы
        # EBUSY, а пройдя — увела бы хост и контейнер в разные файлы.
        # Проверяем прямо: os.replace не вызывается вовсе.
        with mock.patch.object(os, "replace") as replace:
            self.assertTrue(secrets.write("BOT_TOKEN", "456:xyz"))
        replace.assert_not_called()
        self.assertEqual(secrets.get("BOT_TOKEN"), "456:xyz")

    def test_no_temporary_file_left(self) -> None:
        secrets.write("BOT_TOKEN", "456:xyz")
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_other_lines_and_comment_survive(self) -> None:
        secrets.write("SHORT_BASE_URL", "https://новый.ру")
        text = self.contents()
        self.assertIn("# комментарий сохраняется", text)
        self.assertIn("BOT_TOKEN=123:abc", text)

    def test_new_key_appended(self) -> None:
        self.assertTrue(secrets.write("WEB_PUBLIC_URL", "https://панель.ру"))
        self.assertEqual(secrets.get("WEB_PUBLIC_URL"), "https://панель.ру")

    def test_failed_chmod_does_not_fail_write(self) -> None:
        # В контейнере файл может принадлежать другому пользователю.
        # Значение уже на диске — считать запись неудавшейся нельзя.
        with mock.patch.object(os, "chmod", side_effect=OSError(1, "не тот владелец")):
            self.assertTrue(secrets.write("BOT_TOKEN", "789:qwe"))
        self.assertEqual(secrets.get("BOT_TOKEN"), "789:qwe")


class Registry(unittest.TestCase):
    """Настройки, которые обязаны быть доступны из бота."""

    def test_web_public_url_is_editable(self) -> None:
        # Ключ читался в /panel, но в перечне его не было: адрес панели
        # правился только руками в файле.
        self.assertIn("WEB_PUBLIC_URL", secrets.BY_KEY)

    def test_short_base_url_is_editable(self) -> None:
        self.assertIn("SHORT_BASE_URL", secrets.BY_KEY)


class BackupLocation(unittest.TestCase):
    """Копии бота обязаны переживать пересоздание контейнера."""

    def test_directory_is_inside_data(self) -> None:
        # Наружу смонтирован только data/. Каталог рядом с кодом жил
        # внутри контейнера и очищался при каждом обновлении.
        self.assertTrue(
            backup.DIRECTORY.replace(os.sep, "/").startswith("data/"),
            f"копии бота вне data/: {backup.DIRECTORY}",
        )


if __name__ == "__main__":
    unittest.main()
