"""Схема редактируемого текстового контента публичного лендинга.

В ``meta['landing_content']`` сохраняются только отличия от этих значений.
Схема намеренно описывает поля, а не блоки страницы: добавить колонку или
изменить макет через панель нельзя. Privacy и Terms сюда не входят — их
собственные тексты «Радара» остаются в серверном ``public_pages.py``.
"""

# --------------------------------------------------------------------------
# Система «Радар» — мониторинг городских угроз и аварий ЖКХ
# Автор: SecretHero · https://github.com/Chistovik92/radar
# Лицензия: GPL-3.0
# --------------------------------------------------------------------------

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

META_KEY = "landing_content"
TEXT_LIMIT = 500
LONGTEXT_LIMIT = 10_000
URL_LIMIT = 500


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"  # text, longtext, url, textlist, list
    default: Any = ""
    limit: int = TEXT_LIMIT
    hint: str = ""
    fields: tuple["Field", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PageSchema:
    key: str
    title: str
    description: str
    fields: tuple[Field, ...]


def f(key: str, label: str, default: str = "", kind: str = "text", **kwargs) -> Field:
    if kind == "longtext":
        kwargs.setdefault("limit", LONGTEXT_LIMIT)
    elif kind == "url":
        kwargs.setdefault("limit", URL_LIMIT)
    return Field(key, label, kind, default, **kwargs)


def lines(key: str, label: str, default: list[str]) -> Field:
    return f(key, label, default, "textlist", hint="Одна строка — один пункт. Порядок и число пунктов фиксированы разметкой страницы.")


def items(key: str, label: str, fields: tuple[Field, ...], default: list[dict]) -> Field:
    return f(key, label, default, "list", fields=fields)


FEATURE = (
    f("title", "Заголовок"), f("text", "Описание", kind="longtext"),
    lines("items", "Пункты", []),
)
CARD = (
    f("icon", "Значок"), f("name", "Название"), f("price", "Цена"),
    f("period", "Период"), lines("features", "Возможности", []),
    f("button", "Текст кнопки"),
)
PROJECT_LINKS = (f("label", "Подпись"), f("href", "Ссылка", kind="url"),)
PLATFORM = (
    f("title", "Платформа"), f("files", "Файлы"), f("note", "Примечание", kind="longtext"),
)
VPN_PLAN = (f("name", "Название"), f("price", "Цена"), f("period", "Период"), f("note", "Примечание", kind="longtext"))
TEXT_PAIR = (f("title", "Заголовок"), f("text", "Текст", kind="longtext"))
FAQ = (f("question", "Вопрос"), f("answer", "Ответ", kind="longtext"))
CHANNEL = (
    f("icon", "Значок"), f("title", "Название"), f("description", "Описание", kind="longtext"),
    f("button", "Текст ссылки"), f("href", "Адрес ссылки", kind="url"),
)


PAGES: dict[str, PageSchema] = {
    "home": PageSchema("home", "Главная", "Первый экран, возможности, надёжность, тарифы и вход.", (
        f("hero_eyebrow", "Надзаголовок", "RADAR / CITY INTELLIGENCE"),
        f("hero_title", "Заголовок", "Город под наблюдением."),
        f("hero_accent", "Вторая строка заголовка", "Вы — в курсе."),
        f("hero_description", "Описание", "ИИ связывает городские события с вашими адресами и присылает только важное.", "longtext"),
        f("hero_primary", "Основная кнопка", "Запустить бота"),
        f("hero_secondary", "Вторая кнопка", "Смотреть свой город"),
        f("scroll_cue", "Подсказка прокрутки", "ИССЛЕДОВАТЬ СИСТЕМУ"),
        f("capabilities_title", "Возможности: заголовок", "Один контур. Весь город."),
        f("capabilities_text", "Возможности: описание", "От открытого источника до конкретного адреса: Радар сам выполняет весь путь и показывает, почему сообщение пришло именно вам.", "longtext"),
        items("capabilities", "Группы возможностей", FEATURE, [
            {"title": "Только то, что касается вас", "text": "Радар читает открытые каналы МЧС, администраций, ЖКХ и RSS. ИИ выделяет город, улицу, дом и тип события, затем сопоставляет его с вашими адресами.", "items": ["БПЛА и воздушная тревога", "ЧС, пожары и эвакуация", "Вода, свет, газ и отопление", "Отдельное распознавание отбоя"]},
            {"title": "Город живёт в одном интерфейсе", "text": "Несколько локаций, тихие часы, местный часовой пояс, погода и новостные подборки по расписанию. Важные тревоги остаются бесплатными.", "items": ["Почасовой прогноз и три дня", "18 тематик новостных подборок", "Неограниченное число адресов", "Русский, English, Українська, 中文 и فارسی"]},
            {"title": "Не только оповещения", "text": "Проект объединяет повседневные инструменты и средства администрирования, не превращая основной сценарий в набор разрозненных ботов.", "items": ["ИИ-ассистент с поиском", "Проверка ссылок и короткие ссылки", "Музыка, медиа и облачное хранилище", "Модерация групп и SOS-контакты"]},
            {"title": "Ваши данные — под контролем", "text": "Открытый исходный код GPL-3.0, прозрачные настройки и выбор SQLite или PostgreSQL для хранения данных проекта.", "items": ["Резервные копии и перенос базы", "Роли и аудит действий", "Метрики, журналы и healthcheck", "Обновление из панели управления"]},
        ]),
        f("resilience_title", "Надёжность: заголовок", "Тревога не зависит от настроения сервера."),
        f("resilience_text", "Надёжность: описание", "Фоновый цикл наблюдает сторож, незавершённые отправки повторяются, тихие часы хранят очередь в базе, а healthcheck показывает реальное состояние мониторинга.", "longtext"),
        items("resilience", "Свойства надёжности", TEXT_PAIR, [
            {"title": "SQLite ⇄ PostgreSQL", "text": "Перенос данных, миграции и резервные копии."},
            {"title": "Отказоустойчивый контур", "text": "Кэш ИИ, повторная доставка и наблюдение за источниками."},
            {"title": "Контроль доступа", "text": "Четыре роли, инвайты, CSRF-защита и аудит действий."},
        ]),
        f("utility_title", "Полезное: заголовок", "Полезно каждый день"),
        f("utility_text", "Полезное: описание", "Радар остаётся одним проектом, даже когда выходит за рамки городских оповещений.", "longtext"),
        items("utilities", "Полезные функции", TEXT_PAIR, [
            {"title": "ИИ и медиа", "text": "Ассистент, музыка, загрузка видео, облачное хранилище и плейлисты."},
            {"title": "Безопасность и группы", "text": "Проверка ссылок, капча, антиспам, журнал модерации и SOS."},
            {"title": "Приватная инфраструктура", "text": "Аренда приватного сервера и управление заказом в боте."},
            {"title": "Несколько платформ", "text": "Telegram, ВКонтакте, Discord и MAX с общей базой пользователей."},
        ]),
        f("pricing_title", "Тарифы: заголовок", "Важное — бесплатно."),
        f("pricing_accent", "Тарифы: вторая строка", "Дополнительное — честно."),
        f("pricing_text", "Тарифы: описание", "Оповещения об опасности не требуют оплаты. Одна подписка открывает все новостные тематики и загрузку видео без дневного предела.", "longtext"),
        f("trial_label", "Пробный период: подпись", "Пробный период"),
        f("trial_days", "Пробный период: срок", "7 дней"),
        f("trial_text", "Пробный период: описание", "Один раз на пользователя. Все возможности единой подписки.", "longtext"),
        f("trial_button", "Пробный период: кнопка", "Начать в Telegram"),
        f("pricing_link", "Ссылка на тарифы", "Условия и актуальные тарифы"),
        f("login_title", "Вход: заголовок", "Войти через Telegram"),
        f("login_text", "Вход: описание", "Один безопасный вход. Радар сам откроет кабинет или панель согласно вашей роли.", "longtext"),
        f("profile_title", "Личный кабинет", "Личный кабинет"),
        f("profile_text", "Личный кабинет: описание", "Локации, подписка и предложение источников · /profile"),
        f("panel_title", "Панель управления", "Панель управления"),
        f("panel_text", "Панель: описание", "Источники, пользователи и настройки · по роли"),
        f("login_alternative", "Альтернативный вход", "Альтернатива: команда /panel в боте → «Код входа». Код действует 5 минут.", "longtext"),
        f("telegram_title", "Telegram: заголовок", "Подтвердите личность"),
        f("telegram_text", "Telegram: описание", "Telegram передаёт только данные, необходимые для входа. Сессия защищена cookie и проверкой подписи.", "longtext"),
        f("footer_description", "Описание в подвале", "Система городского мониторинга\nс открытым исходным кодом.", "longtext"),
    )),
    "pricing": PageSchema("pricing", "Тарифы", "Вводный текст, карточки, примечания, сравнение и порядок оплаты. Цены подписки берутся из настроек бота.", (
        f("updated", "Дата обновления", "Обновлено: ноябрь 2026"),
        f("title", "Заголовок", "Тарифы и цены"),
        f("subtitle", "Подзаголовок", "Оповещения бесплатно навсегда. Актуальные тарифы подписки и порядок оформления", "longtext"),
        f("intro", "Введение", "Радар — честные цены, без скрытых платежей. Все оповещения об угрозах — бесплатно навсегда.", "longtext"),
        f("payment_intro", "Про оплату", "Подписка на подборки оплачивается через Telegram Stars. Способы оплаты аренды приватного сервера и итоговая сумма показываются в боте до подтверждения заказа.", "longtext"),
        items("free_card", "Бесплатная карточка", CARD, [{"icon": "🛡", "name": "Оповещения об угрозах", "price": "0 ₽", "period": "бесплатно навсегда", "features": ["БПЛА / ракетная опасность / воздушная тревога / отбой", "МЧС: ЧС, штормовые предупреждения, эвакуация", "ЖКХ: вода, свет, газ, отопление — адресно", "Базовая погода (текст): текущая, 8 ч, 3 дня", "Проверка ссылок — 200/сутки", "ИИ-ассистент — базовый лимит", "Без рекламы, без трекинга"], "button": "Запустить бота"}]),
        items("digest_card", "Карточка новостной подписки", CARD, [{"icon": "📰", "name": "Новостные подборки", "price": "", "period": "", "features": ["18 тематик в одной подписке", "ИИ-сводки и доставка по расписанию", "Погода картинкой", "Скачивание видео без дневного лимита подписчика"], "button": "Оформить в боте за Stars"}]),
        items("vpn_card", "Карточка приватного сервера", CARD, [{"icon": "🔐", "name": "Аренда приватного сервера", "price": "Тарифы VPN", "period": "срок и цена до оплаты", "features": ["Аренда приватного сервера", "Срок, трафик и число устройств зависят от тарифа", "Управление заказом в боте"], "button": "Тарифы VPN и загрузка"}]),
        f("notes_title", "Примечания: заголовок", "Важные замечания:"),
        lines("notes", "Примечания", ["Цены подписки указаны в Telegram Stars (⭐); стоимость аренды сервера показывается в выбранном тарифе.", "Приватный сервер предоставляется для законного использования по назначению.", "Подписка на подборки оплачивается Stars; доступные способы оплаты аренды зависят от настроек бота.", "Возврат средств: заявка в поддержку в течение 14 дней, если сервис не предоставлен.", "Сам-хостинг (установка на свой сервер) — полностью бесплатно, код открыт (GPL-3.0)."]),
        f("comparison_title", "Сравнение: заголовок", "Сравнение: бесплатно vs подписка"),
        lines("comparison_headers", "Сравнение: колонки", ["Функция", "Бесплатно", "Подписка (Stars)"]),
        items("comparison", "Строки сравнения", (lines("cells", "Ячейки", []),), [
            {"cells": ["Тревоги БПЛА / МЧС / ЖКХ", "✅ Полностью", "✅ Полностью"]},
            {"cells": ["Погода (текст)", "✅ Текущая, 8ч, 3 дня", "✅ + картинка, вектор ветра, луна"]},
            {"cells": ["Новостные подборки", "❌", "✅ 18 тем, ИИ-сводки, расписание"]},
            {"cells": ["Проверка ссылок", "200/сутки", "Без лимита"]},
            {"cells": ["ИИ-ассистент", "Базовый лимит", "Расширенный лимит"]},
            {"cells": ["Аренда приватного сервера", "❌", "Отдельно (₽)"]},
        ]),
        f("pay_title", "Оплата: заголовок", "Как оплатить"),
        lines("pay_steps", "Шаги оплаты", ["Откройте бота: @SecretHeroBot", "Меню → «Подписки» или «Сервер»", "Выберите тариф и один из доступных способов оплаты", "Доступ активируется автоматически"]),
        f("support_question", "Вопрос перед поддержкой", "Вопросы по оплате?"),
        f("support_link", "Ссылка поддержки", "Напишите в поддержку"),
    )),
    "support": PageSchema("support", "Поддержка", "Каналы, SLA, рекомендации и FAQ.", (
        f("updated", "Дата обновления", "Обновлено: ноябрь 2026"), f("title", "Заголовок", "Поддержка"),
        f("subtitle", "Подзаголовок", "Тикет-система, контакты, SLA и ответы на частые вопросы", "longtext"),
        f("intro", "Введение", "Радар — бот мониторинга городских угроз и аварий ЖКХ. Мы отвечаем на вопросы по установке, настройке, оплате, багам и предложениям.", "longtext"),
        f("channels_title", "Каналы: заголовок", "Каналы поддержки"),
        items("channels", "Каналы", CHANNEL, [
            {"icon": "🎫", "title": "Тикет-бот (рекомендуется)", "description": "Создайте тикет — получите номер, статус и ответ в личку. История сохраняется.", "button": "Открыть @SecretHeroSupportBot", "href": "https://t.me/SecretHeroSupportBot"},
            {"icon": "👤", "title": "Прямой контакт автора", "description": "Для срочных вопросов, безопасности, партнёрства. Отвечаю в рабочее время.", "button": "Написать @SecretHeroSupport", "href": "https://t.me/SecretHeroSupport"},
            {"icon": "📧", "title": "Email", "description": "Для официальных обращений, договоров, претензий, GDPR-запросов.", "button": "admin@hydravpsvpn.ru", "href": "mailto:admin@hydravpsvpn.ru"},
        ]),
        f("sla_title", "SLA: заголовок", "SLA — время ответа"),
        lines("sla", "SLA", ["Рабочее время: пн–пт 09:00–20:00 (МСК).", "Первичный ответ: до 4 часов в рабочее время, до 24 часов — в нерабочее.", "Решение типовых вопросов: 1–2 рабочих дня.", "Сложные баги / установка: до 5 рабочих дней."]),
        f("speed_up_title", "Ускорение помощи: заголовок", "Что ускорит помощь"),
        lines("speed_up", "Что подготовить", ["Версия бота/панели (/version в боте или футер панели).", "Способ установки: Docker (install.sh) / Docker Compose / ручная.", "ОС и архитектура сервера (ARM / x64).", "Логи: docker logs radar_container --tail 100 или journalctl -u radar -n 100.", "Скриншот ошибки или полный текст traceback.", "Что уже пробовали исправить."]),
        f("faq_title", "FAQ: заголовок", "Частые вопросы (FAQ)"),
        items("faq", "Вопросы и ответы", FAQ, [
            {"question": "Бот не присылает оповещения", "answer": "Проверьте: локации добавлены верно (город/улица/дом)? Включены ли нужные категории в настройках? Не включены ли «тихие часы»? Бот не заблокирован? Источники в городе настроены админом (команда /sources в панели)?"},
            {"question": "Погода не работает / «нет координат»", "answer": "Удалите локацию и добавьте заново — координаты определяются при добавлении. Если город не находится — напишите в поддержку, добавим в геокодер."},
            {"question": "Как купить подписку / арендовать сервер", "answer": "В боте: Меню → Подписки / Сервер → выбрать тариф → оплатить Stars или через платёжную систему. Доступ придёт автоматически."},
            {"question": "Хочу установить у себя (self-hosted)", "answer": "Требования: Docker, Docker Compose, порт 80/443, домен (для HTTPS и TG Login Widget). По вопросам установки и настройки обращайтесь к @SecretHeroSupportBot или admin@hydravpsvpn.ru."},
        ]),
        f("contact_title", "Обращение: заголовок", "Как отправить обращение"),
        f("contact_text", "Обращение: текст", "Откройте тикет-бота @SecretHeroSupportBot и опишите вопрос там — он создаст обращение и покажет его номер. Если бот недоступен, напишите @SecretHeroSupport.", "longtext"),
    )),
    "downloads": PageSchema("downloads", "Загрузки", "Описания приложений, платформы, тарифы и инструкции. Адреса официальных репозиториев остаются в коде.", (
        f("title", "Заголовок", "Загрузки приложений"),
        f("subtitle", "Подзаголовок", "HydraVPN — один VPN для телефона, компьютера и роутера. Скачайте приложение под свою платформу.", "longtext"),
        f("client_name", "Клиент: название", "HydraVPN"), f("client_tagline", "Клиент: подпись", "Мультипротокольный VPN-клиент для всех платформ"),
        f("client_version", "Клиент: версия", "0.8.3"),
        f("client_description", "Клиент: описание", "Один проект, один аккаунт (бот «Радар» / HydraVPN), одно управление — телефон, компьютер и домашний роутер. Поддерживает sing-box, Xray, AmneziaWG, умную маршрутизацию, раздельное туннелирование и управление роутером.", "longtext"),
        items("client_platforms", "Клиент: платформы", PLATFORM, [
            {"title": "Android 8+", "files": "APK (arm64, armv7, x86, x86_64)", "note": "Телефоны, планшеты, Android TV / Google TV"},
            {"title": "Windows 10/11 x64", "files": ".msi / .exe / portable .zip", "note": "Windows 7 SP1 и 32-бит — Hydra Classic"},
            {"title": "Linux x64 / arm64", "files": ".deb, .rpm, .AppImage, .tar.gz", "note": "Raspberry Pi OS 32-бит — Hydra Classic (Java 11+)"},
            {"title": "macOS 12+", "files": ".dmg (Apple Silicon / Intel)", "note": ""},
            {"title": "iOS 17+", "files": ".ipa (без подписи)", "note": "Ставится через переподпись (AltStore, Sideloadly)"},
        ]),
        f("download_button", "Кнопка скачивания", "Скачать"), f("source_button", "Кнопка исходников", "Исходный код"),
        f("update_title", "Обновления: заголовок", "Обновления приложение скачивает само."),
        f("update_text", "Обновления: текст", "Кнопка «Обновить» загружает файл под вашу систему (SHA-256 из релиза проверяется) и запускает установку. Ставьте файлы только из официального релиза на GitHub — SHA-256 указан в каждом релизе.", "longtext"),
        f("router_name", "Роутеры: название", "HydraVPN for Routers"), f("router_tagline", "Роутеры: подпись", "Решение для обхода DPI на роутерах"),
        f("router_version", "Роутеры: версия", "1.3.3"),
        f("router_description", "Роутеры: описание", "Комплексное, не зависящее от платформы решение на базе sing-box, zapret и ByeDPI для роутеров. Единое решение для OpenWRT, KeeneticOS и MikroTik RouterOS с полной функциональной совместимостью.", "longtext"),
        items("router_platforms", "Роутеры: платформы", PLATFORM, [
            {"title": "OpenWRT 21.02+", "files": "IPK (APK — через install.sh)", "note": "Init: procd"},
            {"title": "KeeneticOS 3.7+", "files": "IPK (Entware)", "note": "Init: ndm/Entware"},
            {"title": "RouterOS 7+", "files": "TAR (контейнер)", "note": "Init: systemd/container"},
        ]),
        f("vpn_title", "VPN: заголовок", "Тарифы VPN"),
        f("vpn_intro", "VPN: введение", "Доступ к VPN выдаётся через бота «Радар»: раздел 🔐 VPN — там же можно оформить и продлить подписку. С 12.08.2026 действует обновлённая тарифная сетка и праздничная акция.", "longtext"),
        items("vpn_plans", "Тарифы VPN", VPN_PLAN, [
            {"name": "Неделя", "price": "0 ₽", "period": "пробный ключ — бесплатно", "note": ""},
            {"name": "Месяц", "price": "550 ₽", "period": "🔥 Спеццена по акции", "note": ""},
            {"name": "Три месяца", "price": "1 250 ₽", "period": "срок: 90 дней", "note": ""},
            {"name": "Полгода", "price": "2 300 ₽", "period": "срок: 180 дней", "note": ""},
            {"name": "Год", "price": "4 200 ₽", "period": "🔥 Выгодное предложение на длительный период", "note": ""},
        ]),
        f("vpn_note", "VPN: примечание", "В «Радаре» встроена продажа VPN: оплата через Crypto Pay или с подтверждением администратора, тарифы настраиваются в разделе «Ключи».", "longtext"),
        f("locations_title", "Локации: заголовок", "Локации и условия подключения"),
        f("locations", "Доступные локации", "Доступные локации: Финляндия 🇫🇮, Россия 🇷🇺, Казахстан 🇰🇿, США 🇺🇸, Франция 🇫🇷, Польша 🇵🇱, Латвия 🇱🇻, Швеция 🇸🇪, Нидерланды 🇳🇱, Германия 🇩🇪, Эстония 🇪🇪, Румыния 🇷🇴.", "longtext"),
        items("connection_terms", "Условия подключения", TEXT_PAIR, [
            {"title": "Два ключа на пользователя", "text": "К каждому ключу можно подключить от 5 до 10 устройств (минимум 5, максимум 10)."},
            {"title": "Программа лояльности", "text": "🔥 АКЦИЯ — за каждого приведённого друга вы получаете 1 полный месяц в подарок (или дополнительные дни/недели по программе лояльности)."},
        ]),
        f("services_title", "Услуги: заголовок", "Дополнительные услуги"), f("routers_title", "Роутеры: услуги", "Роутеры"),
        f("routers_intro", "Роутеры: пояснение", "Для работы с сервером и раздачи доступа по всей домашней сети."),
        items("services", "Дополнительные услуги", VPN_PLAN, [
            {"name": "Роутер", "price": "от 3 500 ₽", "period": "гарантия 1 год", "note": ""},
            {"name": "Прошивка и настройка", "price": "1 500 ₽", "period": "подарочный доступ на 3 месяца", "note": ""},
            {"name": "Доставка", "price": "от 200 ₽", "period": "по РФ и СНГ", "note": ""},
            {"name": "Удалённый доступ", "price": "1 000 ₽", "period": "при технической возможности", "note": "при подключении белого статического IP у провайдера или дополнительной опции (от 150 ₽ / месяц)"},
        ]),
        f("support_title", "Техподдержка: заголовок", "Техническая поддержка"),
        items("support_terms", "Условия техподдержки", TEXT_PAIR, [
            {"title": "В течение полугода", "text": "Техническая поддержка включена на первые шесть месяцев."},
            {"title": "Дальше — по обращению или подпиской", "text": "Разовое обращение — от 1 000 ₽, подписка на тех-помощь — 150 ₽ / месяц."},
        ]),
        f("individual_title", "Индивидуальные тарифы: заголовок", "Индивидуальные тарифы"),
        f("individual_text", "Индивидуальные тарифы: текст", "Выбор локаций и от 10 до 25 ключей под ваши задачи. Условия подбираются индивидуально — напишите в поддержку или в бота «Радар».", "longtext"),
        f("install_title", "Установка: заголовок", "Как установить и настроить приложения"),
        items("install_steps", "Шаги установки", TEXT_PAIR, [
            {"title": "Скачайте файл под свою платформу", "text": "Каждый релиз публикуется сразу со всеми платформами. Выберите версию из таблицы выше."},
            {"title": "Установите и войдите в аккаунт", "text": "В боте «Радар» откройте раздел 🔐 VPN → «Подключить приложение» и введите одноразовый код — HydraVPN подхватит ваши подписки. Один аккаунт на телефон, компьютер и роутер."},
            {"title": "Для роутера — разверните пакет", "text": "OpenWRT — через install.sh; KeeneticOS — пакет Entware; MikroTik — контейнер TAR. Подробности — в README репозитория."},
        ]),
        f("resources_title", "Ресурсы: заголовок", "Поддержка и ресурсы"),
    )),
    "projects": PageSchema("projects", "Проекты", "Карточки проектов и их ссылки. Число карточек фиксировано текущей разметкой.", (
        f("eyebrow", "Надзаголовок", "Семейство проектов SecretHero"), f("title", "Заголовок", "Наши проекты"),
        f("subtitle", "Подзаголовок", "Открытые инструменты, объединённые одним аккаунтом и одной философией — полезное под контролем пользователя.", "longtext"),
        items("projects", "Проекты", (
            f("name", "Название"), f("tagline", "Подпись"), f("description", "Описание", kind="longtext"),
            items("links", "Ссылки", PROJECT_LINKS, []),
        ), [
            {"name": "Радар", "tagline": "Мониторинг городских угроз и аварий ЖКХ", "description": "Telegram-бот и веб-панель, которые следят за каналами МЧС, администраций, ЖКХ и RSS-лентами, сопоставляют события с вашими адресами и присылают только то, что касается вас. Открытый исходный код, GPL-3.0.", "links": [{"label": "Сайт проекта", "href": "/"}, {"label": "GitHub", "href": "https://github.com/Chistovik92/radar"}, {"label": "Бот @SecretHeroBot", "href": "https://t.me/SecretHeroBot"}]},
            {"name": "HydraVPN", "tagline": "Мультипротокольный VPN-клиент", "description": "Один VPN для Android, Windows, Linux, macOS и iOS. Один аккаунт с ботом «Радар», умная маршрутизация, раздельное туннелирование и управление роутером. Скачайте в разделе «Загрузки».", "links": [{"label": "Загрузки", "href": "/downloads"}, {"label": "GitHub", "href": "https://github.com/Chistovik92/HydraVPN"}, {"label": "Сайт", "href": "https://gidravpn.ru"}]},
            {"name": "HydraVPN for Routers", "tagline": "VPN и обход DPI для роутеров", "description": "Комплексное решение на базе sing-box, zapret и ByeDPI для OpenWRT, KeeneticOS и MikroTik RouterOS. Единый интерфейс и JSON API на всех платформах. Скачайте в разделе «Загрузки».", "links": [{"label": "Загрузки", "href": "/downloads"}, {"label": "GitHub", "href": "https://github.com/Chistovik92/HydraVPNforRouters"}]},
            {"name": "opendisk", "tagline": "Облачные хранилища как локальные диски", "description": "Бесплатный клиент для облачных хранилищ на базе rclone: подключение облаков как дисков в Windows и Linux, просмотр файлов на Android. Яндекс.Диск, Облако Mail.ru, Google Drive, Dropbox, S3 и другие сервисы. Kotlin / Compose Multiplatform, MIT.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/opendisk"}, {"label": "Сайт", "href": "https://chistovik92.github.io/opendisk/"}]},
            {"name": "NeuroCode Android", "tagline": "Клиент для LLM на устройстве", "description": "Открытый клиент для языковых моделей: запуск как на самом устройстве, так и для удалённого выполнения через консоль. Kotlin.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/NeuroCode-Android"}]},
            {"name": "LocalDoc AI", "tagline": "Локальная читалка с нейросетями", "description": "Кроссплатформенная читалка книг и веб-страниц (Android + iOS) с озвучкой и полностью локальными нейросетями — без облака и телеметрии. Поддержка EPUB, FB2, PDF, DOCX и десятков форматов, локальный RAG, OCR и синтез речи на устройстве. Kotlin Multiplatform + Compose Multiplatform.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/LocalDoc-AI---KMP"}]},
            {"name": "med-roster", "tagline": "Графики смен и табели для поликлиники", "description": "Автоматизация составления графиков смен и расчёта табелей учёта рабочего времени (Т-13) для персонала детской и взрослой поликлиники. Импорт реальных графиков из Excel, поиск ошибок, правка в браузере и выгрузка готовых официальных форм. Сборка установщиков — GitHub Actions.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/med-roster"}]},
            {"name": "MeshkitKeen", "tagline": "Управление mesh-сетью Keenetic", "description": "Форк KeenKit, добавляющий неинтерактивный режим и управление mesh-узлами (ретрансляторами/экстендерами) с головного роутера-контроллера. Статус всех устройств, перезагрузка, Wi-Fi по диапазонам и OTA-обновление прошивки — с одного экрана.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/MeshkitKeen"}]},
            {"name": "torrserver-docker-manager", "tagline": "Менеджер TorrServer в Docker", "description": "Docker-менеджер для TorrServer с двумя режимами установки — простой запуск и развёртывание торрент-сервера в контейнере с автообновлением.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/torrserver-docker-manager"}]},
            {"name": "Harness", "tagline": "Десктоп-приложение для DeepSeek Harness", "description": "Настольное приложение в стиле Claude Code / ChatGPT / Gemini на базе DeepSeek Harness. Объединяет несколько LLM-провайдеров (DeepSeek, OpenAI, Claude, Gemini, Groq и др.) с локальной историей чатов, шифрованием ключей API и запуском локальных моделей Hugging Face. Electron + React.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/Harness"}]},
            {"name": "ZHeroDiZk", "tagline": "Удалённый доступ в классе RustDesk", "description": "Открытая система удалённого доступа в классе RustDesk и AnyDesk: собственный сервер, кроссплатформенные клиенты, управляемые права доступа и аудит. Rust.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/ZHeroDiZk"}]},
            {"name": "servAI", "tagline": "AI-сервер одной командой", "description": "Установщик «AI-сервера» для Ubuntu 24.04+ и Debian 12+: одним скриптом ставит официальные консольные ИИ-клиенты (Claude Code, Codex CLI, Gemini CLI, Aider), рабочего пользователя, tmux-раскладку из четырёх агентов и опционально веб-IDE.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/servAI"}]},
            {"name": "zeropentime", "tagline": "Децентрализованная альтернатива ZeroTier", "description": "Открытая децентрализованная замена ZeroTier на базе AmneziaWG 3: защищённые виртуальные сети, NAT traversal, ретрансляция, fallback VLESS+REALITY, exit-узлы и веб-управление. Go.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/zeropentime"}]},
            {"name": "winOpenCodeMod", "tagline": "Провайдеры в настройках OpenCode Desktop", "description": "GUI-плагин для OpenCode Desktop, возвращающий форму «Custom provider» (как в v1.19.x) в раздел Settings → Providers. Добавление, правка и удаление собственных OpenAI-совместимых провайдеров без ручной правки opencode.json. TypeScript + Solid.js.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/winOpenCodeMod"}]},
            {"name": "DataOpenCode", "tagline": "Перенос настроек OpenCode между компьютерами", "description": "Безопасный аддитивный перенос провайдеров, моделей, API-ключей и диалогов OpenCode между Windows-компьютерами: экспорт в zip-архив и развёртывание на другой машине без перезаписи локальных настроек. Поддержка V1 ↔ V2, защита ZIP и резервные копии.", "links": [{"label": "GitHub", "href": "https://github.com/Chistovik92/DataOpenCode"}]},
        ]),
        f("future_text", "Завершающий текст", "Больше проектов — в GitHub-профиле SecretHero. Следите за обновлениями в боте «Радар».", "longtext"),
    )),
}


def _merge(default: Any, stored: Any) -> Any:
    if isinstance(default, dict):
        if not isinstance(stored, Mapping):
            return copy.deepcopy(default)
        result = copy.deepcopy(default)
        for key, value in stored.items():
            if not isinstance(key, str):
                continue
            result[key] = _merge(default[key], value) if key in default else copy.deepcopy(value)
        return result
    if isinstance(default, list):
        return copy.deepcopy(stored) if isinstance(stored, list) else copy.deepcopy(default)
    return copy.deepcopy(stored) if isinstance(stored, str) else copy.deepcopy(default)


def default_content() -> dict[str, dict[str, Any]]:
    return {
        key: {item.key: copy.deepcopy(item.default) for item in schema.fields}
        for key, schema in PAGES.items()
    }


def merge_with_meta(stored: Any) -> dict[str, dict[str, Any]]:
    """Добирает новые поля из схемы и сохраняет неизвестные данные из meta."""
    return _merge(default_content(), stored)


async def load_content() -> dict[str, dict[str, Any]]:
    from ..db import repo

    return merge_with_meta(await repo.get_meta(META_KEY, {}))


def _compact(default: Any, value: Any) -> Any:
    """Возвращает только отличия; равные дефолту ветки в meta не нужны."""
    if isinstance(default, dict) and isinstance(value, dict):
        result = {}
        for key, item in value.items():
            compacted = _compact(default[key], item) if key in default else copy.deepcopy(item)
            if compacted is not _UNCHANGED:
                result[key] = compacted
        return result if result else _UNCHANGED
    if isinstance(default, list) and isinstance(value, list) and default != value:
        return copy.deepcopy(value)
    if default == value and type(default) is type(value):
        return _UNCHANGED
    return copy.deepcopy(value)


_UNCHANGED = object()


async def save_content(content: Mapping[str, Any]) -> None:
    from ..db import repo

    compacted = _compact(default_content(), dict(content))
    await repo.set_meta(META_KEY, {} if compacted is _UNCHANGED else compacted)


def changed_pages(stored: Any) -> set[str]:
    if not isinstance(stored, Mapping):
        return set()
    return {key for key in PAGES if isinstance(stored.get(key), Mapping) and bool(stored.get(key))}
