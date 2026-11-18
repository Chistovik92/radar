# План реализации лендинга проекта с входом через TG и виджетами (v5.10.0)

**Версия:** 5.10.0  
**Статус:** Планирование (на согласовании)  
**Автор:** SecretHero  
**Дата:** ноябрь 2026

---

## 1. Цели и требования

### 1.1 Основные задачи
1. **Создать публичную лендинг-страницу проекта** — информативную, красивую, объясняющую ценность продукта
2. **Добавить вход через Telegram Login Widget** внизу страницы с разделением прав доступа по ролям бота
3. **Адаптировать страницу под требования платёжной системы (Платега/Platega)** — сделать информативной и красивой для прохождения модерации
4. **Интегрировать Telegram Mini App виджеты** для отображения погоды, новостей и статуса опасности (БПЛА/ракетная атака)

### 1.2 Требования менеджера платёжной системы (Platega)
> **Ключевые требования из переписки с менеджером:**
> - Политика конфиденциальности (отдельная кнопка в боте/на сайте)
> - Пользовательское соглашение (отдельная кнопка)
> - Контакты поддержки (тикет-система, юзернейм или почта — группа НЕ подходит)
> - Актуальные цены и тарифы
> - Убрать упоминания VPN/обхода блокировок (цензура, DPI, ТСПУ, глушилки, белые списки, LTE)
> - Лимит на транзакцию — 10 000 ₽ (установить ограничение на пополнение и стоимость товаров)
> - Убрать персональные данные (ИП, ООО, ИНН)
> - Добавить кодовое слово «mekbuda» на время согласования
> - Документация должна быть постоянно доступна пользователю — отдельными кнопками в бот или на сайт

### 1.3 Ролевая модель доступа (из бота)
| Роль в боте | Доступ на лендинге после входа через TG |
|---|---|
| Пользователь | Базовый профиль: свои локации, настройки уведомлений, погода, история |
| Модератор | + Модерация источников, просмотр пользователей, добавление локаций |
| Администратор | + Удаление пользователей, назначение модераторов, полная статистика |
| Суперадминистратор | Полный доступ: все настройки, ключи, VPN, подписки, обновления, RustDesk |

---

## 2. Архитектура решения

### 2.1 Новые маршруты в веб-панели (`radar/web/panel.py`)

```python
# Публичные маршруты (без авторизации)
web.get("/", landing_page),           # Лендинг
web.get("/privacy", privacy_page),    # Политика конфиденциальности
web.get("/terms", terms_page),        # Пользовательское соглашение
web.get("/support", support_page),    # Контакты поддержки
web.get("/pricing", pricing_page),    # Тарифы и цены

# Telegram Login Widget (уже есть)
web.get("/login", login),
web.get("/auth", authenticate),
web.post("/login/code", authenticate_code),

# Защищённые маршруты (требуют авторизации + роли)
web.get("/profile", profile_page),           # Профиль пользователя (user+)
web.get("/profile/locations", user_locations), # Локации пользователя
web.get("/profile/alerts", user_alerts),       # История уведомлений
# ... остальные маршруты панели (как сейчас)
```

### 2.2 Новые модули

| Файл | Назначение |
|---|---|
| `radar/web/landing.py` | Рендеринг лендинга, виджеты, публичные страницы |
| `radar/web/widgets.py` | Telegram Mini App виджеты (погода, новости, опасность) |
| `radar/web/public_pages.py` | Privacy, Terms, Support, Pricing страницы |

### 2.3 Telegram Mini App виджеты

Используем **Telegram Web App Platform** (доступна с Bot API 6.0+):

```html
<!-- Виджет погоды -->
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<div id="weather-widget" data-location="auto"></div>

<!-- Виджет новостей -->
<div id="news-widget" data-topics="alerts,utilities,weather"></div>

<!-- Виджет статуса опасности -->
<div id="danger-widget" data-city="auto"></div>
```

**Важно:** Для работы виджетов нужен `Web App` в настройках бота (@BotFather → Bot Settings → Menu Button → Configure Menu Button). Виджеты будут получать данные через наш API (`/api/widget/*`).

---

## 3. Структура лендинга (Landing Page)

### 3.1 Секции (в порядке отображения)

```
1. Hero Section
   ├─ Заголовок: «Радар — оповещения об угрозах и авариях ЖКХ по вашим адресам»
   ├─ Подзаголовок: ИИ-разбор источников, точная география, бесплатные тревоги
   ├─ CTA: «Запустить в Telegram» (кнопка с tg://resolve?domain=SecretHeroBot)
   └─ Индикатор версии: v5.9.10.1

2. Возможности (Feature Grid)
   ├─ 🛸 БПЛА/ракетная опасность — мгновенные оповещения всего города
   ├─ 🆘 МЧС: ЧС, штормовые предупреждения, эвакуация
   ├─ 🛠 ЖКХ: вода, свет, газ, отопление — адресно по улице и дому
   ├─ 🌤 Погода — почасовая, 3 дня, ветер, луна, картинкой
   ├─ 📰 Новостные подборки — 18 тематик, ИИ-сводки, Telegram Stars
   ├─ 🔗 Проверка ссылок на фишинг — 200 бесплатных в сутки
   ├─ 🎵 Музыка в облаке — rclone, кэш 256 Мб, пережатие в Opus
   ├─ 🔐 VPN (HydraSite) — 3x-ui, Marzban, Remnawave, продажа доступов
   ├─ 🤖 ИИ-ассистент — Gemini/DeepSeek, поиск в интернете
   └─ 👥 Модерация групп — антиспам, капча, лестница наказаний

3. Как это работает (3 шага)
   1. Добавьте бота → укажите адреса
   2. Бот мониторит каналы МЧС, админок, ЖКХ, RSS
   3. При совпадении с вашими локациями — приходит оповещение

4. Демо / Скриншоты
   ├─ Интерфейс бота (меню, локации, настройки)
   ├─ Веб-панель (overview, пользователи, источники, VPN)
   ├─ Погода картинкой (дневная/ночная тема, ветер, луна)
   └─ Оповещение о БПЛА (формат сообщения)

5. Документы (Platega compliance) — КНОПКИ, НЕ ССЫЛКИ
   ├─ 📄 Политика конфиденциальности → /privacy
   ├─ 📄 Пользовательское соглашение → /terms
   ├─ 🎫 Поддержка → /support (тикет-система / @username / email)
   ├─ 💰 Тарифы и цены → /pricing

6. Установка и развёртывание
   ├─ Одной командой: bash <(curl -fsSL .../install.sh)
   ├─ Docker Compose: git clone + docker compose up -d
   ├─ Поддержка ARM (RK3318) и x64
   └─ SQLite по умолчанию, PostgreSQL опционально

7. Telegram Login Widget (ВХОД ДЛЯ ПОЛЬЗОВАТЕЛЕЙ)
   ├─ Кнопка «Войти через Telegram» (data-size="large")
   ├─ После входа — редирект на /profile с ролевым доступом
   ├─ Подсказка: «Вход доступен модераторам и выше»
   └─ Альтернатива: код из бота (/panel → код)

8. Футер
   ├─ GitHub: github.com/Chistovik92/radar
   ├─ Лицензия: GPL-3.0
   ├─ Автор: SecretHero
   ├─ Кодовое слово для модерации: mekbuda (скрыто, на время согласования)
   └─ Контакты: @SecretHeroSupport (тикет-бот)
```

### 3.2 Адаптивность и темы
- 4 темы: Light, Dark, Matrix, Ark (как в панели)
- Mobile-first: breakpoint 640px, 1024px
- `prefers-reduced-motion` — отключение анимаций
- RTL-ready (для персидского/арабского в будущем)

---

## 4. Публичные страницы (Platega Compliance)

### 4.1 /privacy — Политика конфиденциальности
**Основа:** https://telegra.ph/Politika-konfidencialnosti-08-01-83  
**Обязательные дополнения:**
- Данные проекта: «Радар», @SecretHeroBot, github.com/Chistovik92/radar
- Актуальная дата: ноябрь 2026
- Какие данные собираются: Telegram ID, локации (город/улица/дом), настройки уведомлений, роль
- Куда передаются: только в Telegram (оповещения), в Google Gemini (анонимный разбор текстов)
- Хранение: SQLite/PostgreSQL на сервере пользователя, бэкапы в шифрованном виде
- Права пользователя: удаление аккаунта через бота (/menu → Профиль → Удалить)

### 4.2 /terms — Пользовательское соглашение
**Основа:** https://telegra.ph/Polzovatelskoe-soglashenie-08-01-39  
**Обязательные дополнения:**
- Бесплатные оповещения об угрозах (всегда)
- Платные: новостные подборки (Stars), VPN (отдельно)
- Отказ от ответственности: бот не заменяет официальные каналы оповещения
- Запрет на использование для обхода блокировок (VPN-раздел — только легальный доступ)
- Лимит транзакции 10 000 ₽ (для платежей через платежную систему)

### 4.3 /support — Контакты поддержки
**Требование Platega:** группа НЕ подходит. Варианты:
- Тикет-бот: @SecretHeroSupportBot (создать отдельного бота на базе `radar/platforms/`)
- Юзернейм: @SecretHeroSupport (пересылка в личку автора)
- Email: support@radar-project.ru (настроить пересылку)

**На странице:**
- Форма обращения (тема, текст, прикрепление файла)
- Автоответ с номером тикета
- SLA: ответ в рабочие часы (9:00–17:30 МСК)

### 4.4 /pricing — Тарифы и цены
| Продукт | Цена | Описание |
|---|---|---|
| Оповещения об угрозах | **Бесплатно** | БПЛА, ракетная опасность, МЧС, ЖКХ — всегда бесплатно |
| Новостные подборки | 50⭐/мес / 500⭐/год | 18 тематик, ИИ-сводки, доставка по расписанию |
| VPN доступ (HydraSite) | От 150₽/мес | 3x-ui, Marzban, Remnawave, до 25 устройств |
| Проверка ссылок | 200/сутки бесплатно | Подписчики — без лимита |

**Важно:** Все цены ≤ 10 000 ₽ за транзакцию (лимит платежной системы).

---

## 5. Telegram Mini App Виджеты

### 5.1 Архитектура виджетов

```
┌─────────────────────────────────────────────────────────────┐
│                    Landing Page (/)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Weather      │  │ News         │  │ Danger       │       │
│  │ Widget       │  │ Widget       │  │ Widget       │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │                │
│         └─────────────────┼─────────────────┘                │
│                           ▼                                  │
│              ┌────────────────────────┐                      │
│              │  Telegram Web App JS   │                      │
│              │  (telegram-web-app.js) │                      │
│              └───────────┬────────────┘                      │
│                           │                                  │
│         ┌─────────────────┼─────────────────┐                │
│         ▼                 ▼                 ▼                │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐           │
│  │ /api/w/    │   │ /api/n/    │   │ /api/d/    │           │
│  │ weather    │   │ news       │   │ danger     │           │
│  └────────────┘   └────────────┘   └────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 API эндпоинты для виджетов (новые маршруты)

```python
# Публичные API для виджетов (без авторизации, но с rate limit)
web.get("/api/widget/weather", widget_weather),      # Погода по координатам/городу
web.get("/api/widget/news", widget_news),            # Новостные подборки (публичные)
web.get("/api/widget/danger", widget_danger),        # Статус опасности по городу

# Параметры:
# /api/widget/weather?lat=51.53&lon=46.03&theme=dark
# /api/widget/news?topics=alerts,utilities&limit=5
# /api/widget/danger?city=Саратов
```

### 5.3 Формат ответа виджетов (JSON)

```json
// Weather Widget
{
  "current": { "temp": 12, "feels_like": 9, "condition": "cloudy", "wind": "м/с 5, порывы 9", "humidity": 78, "pressure": 752 },
  "hourly": [{ "time": "14:00", "temp": 12, "precip": 10 }, ...],
  "daily": [{ "date": "2026-11-17", "temp_min": 5, "temp_max": 14, "condition": "rain" }, ...],
  "sunrise": "07:42", "sunset": "16:18",
  "location": "Саратов, Россия",
  "theme": "dark"
}

// News Widget
{
  "items": [
    { "title": "В Саратове отключат горячую воду", "summary": "С 18 по 25 ноября...", "source": "Администрация Саратова", "url": "https://t.me/...", "topic": "utilities", "time": "2026-11-17T10:30:00Z" },
    ...
  ],
  "topics": ["alerts", "utilities", "weather"]
}

// Danger Widget
{
  "city": "Саратов",
  "active": true,
  "type": "uav",           // "uav" | "missile" | "air_raid" | "all_clear"
  "level": "red",          // "red" | "yellow" | "green"
  "message": "🛸 Внимание! В регионе объявлена опасность БПЛА. Укрывайтесь!",
  "started_at": "2026-11-17T14:22:00Z",
  "locations_matched": ["ул. Соколовая, 12", "пр. Кирова, 45"],
  "whitelist_info": "Связь может быть ограничена («белые списки»). Работают: SMS, голосовые звонки. Не работают: мобильный интернет, мессенджеры."
}
```

### 5.4 Инициализация виджетов на странице

```html
<!-- В <head> лендинга -->
<script src="https://telegram.org/js/telegram-web-app.js"></script>

<!-- Контейнеры виджетов -->
<div class="widget-row">
  <div id="widget-weather" class="widget" data-city="auto" data-theme="auto"></div>
  <div id="widget-news" class="widget" data-topics="alerts,utilities" data-limit="5"></div>
  <div id="widget-danger" class="widget" data-city="auto"></div>
</div>

<!-- Инициализация -->
<script>
  // Telegram Web App готов
  Telegram.WebApp.ready();
  Telegram.WebApp.expand(); // Раскрыть на весь экран если в Telegram
  
  // Инициализация наших виджетов
  RadarWidgets.init({
    apiBase: '/api/widget',
    theme: document.documentElement.getAttribute('data-theme') || 'dark'
  });
</script>
```

---

## 6. Ролевая авторизация после TG Login

### 6.1 Логика редиректа после `/auth`

```python
async def authenticate(request):
    # ... existing auth logic ...
    if session is not None:
        role = session.role
        # Ролевое перенаправление
        if roles.is_superadmin(role):
            target = "/settings"  # или /overview
        elif roles.is_admin(role):
            target = "/users"
        elif roles.is_moderator(role):
            target = "/sources"
        else:
            target = "/profile"   # Новый маршрут для обычных пользователей
        
        response = web.HTTPFound(target)
        # ... set cookie ...
        raise response
```

### 6.2 Новый маршрут `/profile` (для роли user+)

```python
async def profile_page(request):
    session = get_session(request)
    if not session:
        raise web.HTTPFound("/login")
    
    user = storage.get_user(session.user_key)
    locs = user.get("locs", [])
    
    # Данные для профиля
    return web.Response(
        text=render_profile_page(
            user=user,
            locations=locs,
            role=session.role,
            # Виджеты погоды/новостей/опасности для своих локаций
            weather_data=await get_weather_for_locations(locs),
            danger_status=await get_danger_for_locations(locs),
        ),
        content_type="text/html"
    )
```

### 6.3 Матрица доступа к разделам после входа

| Раздел | user | moderator | admin | superadmin |
|---|---|---|---|---|
| /profile | ✅ | ✅ | ✅ | ✅ |
| /profile/locations | ✅ | ✅ | ✅ | ✅ |
| /profile/alerts | ✅ | ✅ | ✅ | ✅ |
| /profile/subscription | ✅ | ✅ | ✅ | ✅ |
| /sources | — | ✅ | ✅ | ✅ |
| /users | — | ✅ (read) | ✅ | ✅ |
| /events | — | — | ✅ | ✅ |
| /vpn | — | — | — | ✅ |
| /settings | — | — | — | ✅ |
| /update | — | — | — | ✅ |
| /rustdesk | — | — | — | ✅ |

---

## 7. Интеграция с ботом (обратная связь)

### 7.1 Кнопки в боте для открытия веб-страниц

```python
# В главном меню бота (inline keyboard)
[
    [InlineKeyboardButton("🌐 Лендинг проекта", url="https://radar.example.com/")],
    [InlineKeyboardButton("👤 Мой профиль", url="https://radar.example.com/profile")],
    [InlineKeyboardButton("📄 Политика конфиденциальности", url="https://radar.example.com/privacy")],
    [InlineKeyboardButton("📄 Пользовательское соглашение", url="https://radar.example.com/terms")],
    [InlineKeyboardButton("🎫 Поддержка", url="https://radar.example.com/support")],
    [InlineKeyboardButton("💰 Тарифы", url="https://radar.example.com/pricing")],
]
```

### 7.2 Генерация кода входа для `/panel` (уже есть в 5.7)

```python
# В боте: раздел «Управление» → «Веб-панель» → «Код входа»
code = auth.issue_login_code(user_id)
await message.answer(f"Код для входа в панель: <code>{code}</code>\nДействует 5 минут.")
```

---

## 8. Техническая реализация — пошаговый план

### Этап 1: Базовая инфраструктура (1-2 дня)
- [ ] Создать `radar/web/landing.py` — базовый рендеринг лендинга
- [ ] Создать `radar/web/public_pages.py` — Privacy, Terms, Support, Pricing
- [ ] Добавить маршруты в `panel.py` (public + protected)
- [ ] Настроить CORS для виджетов (если будут на поддомене)

### Этап 2: Лендинг — контент и дизайн (2-3 дня)
- [ ] Hero секция с анимацией (GSAP / CSS)
- [ ] Feature Grid (8-10 карточек с иконками)
- [ ] How it works (3 шага)
- [ ] Демо-скриншоты (lightbox/gallery)
- [ ] Документы — кнопки (не ссылки!) в hero и футере
- [ ] Установка — табы: Bash / Docker / Ручная
- [ ] TG Login Widget внизу (large size)
- [ ] Футер с кодовым словом `mekbuda` (скрыто, `display:none` для модерации)

### Этап 3: Telegram Mini App виджеты (3-4 дня)
- [ ] Создать `radar/web/widgets.py` — API эндпоинты
- [ ] Реализовать `/api/widget/weather` (использовать существующий `weather.py`)
- [ ] Реализовать `/api/widget/news` (публичные подборки без авторизации)
- [ ] Реализовать `/api/widget/danger` (текущий статус опасности по городу)
- [ ] Фронтенд виджетов: Vanilla JS модуль `RadarWidgets`
- [ ] Интеграция в лендинг и профиль
- [ ] Темизация виджетов (light/dark/matrix/ark)
- [ ] `prefers-reduced-motion` поддержка

### Этап 4: Ролевая авторизация и профиль (1-2 дня)
- [ ] Добавить `/profile` маршрут с ролевым доступом
- [ ] Обновить `authenticate()` — редирект по роли
- [ ] Профиль пользователя: локации, настройки, история, виджеты
- [ ] Кнопки в боте для открытия профиля/лендинга

### Этап 5: Platega Compliance (1 день)
- [ ] Privacy Policy — адаптация шаблона + данные проекта
- [ ] Terms of Service — адаптация шаблона + лимиты/VPN
- [ ] Support — тикет-бот @SecretHeroSupportBot (или юзернейм/email)
- [ ] Pricing — таблица с ценами ≤ 10 000 ₽
- [ ] Убрать VPN/обход блокировок из публичных страниц
- [ ] Добавить `mekbuda` в футер (скрыто)

### Этап 6: Тестирование и полировка (2-3 дня)
- [ ] Мобильная вёрстка (Chrome DevTools device toolbar)
- [ ] Доступность (axe-core): контрасты, ARIA, фокус
- [ ] Производительность: Lighthouse > 90
- [ ] TG Login Widget: тест в Telegram Desktop, Mobile, Web
- [ ] Виджеты: тест в Telegram Mini App (через @BotFather)
- [ ] Ролевой доступ: user / moderator / admin / superadmin
- [ ] Rate limiting на API виджетов

### Этап 7: Документация и релиз (1 день)
- [ ] Обновить `README.md` / `README.en.md` — скриншоты лендинга
- [ ] Обновить `docs/ROADMAP.md` — пункт 5.10.0
- [ ] Обновить `docs/STATUS.md` — версия 5.10.0
- [ ] Создать `docs/releases/5.10.0.md` — текст релиза
- [ ] Поднять версию в `radar/__init__.py` → `5.10.0`
- [ ] Прогнать все линтеры и тесты
- [ ] Коммит, тег, пуш → GitHub Actions создаст релиз

---

## 9. Оценка трудоёмкости

| Этап | Дни | Риски |
|---|---|---|
| 1. Инфраструктура | 2 | Низкий |
| 2. Лендинг контент/дизайн | 3 | Средний (дизайн) |
| 3. Виджеты TG Mini App | 4 | Высокий (новая технология) |
| 4. Ролевой доступ/профиль | 2 | Низкий |
| 5. Platega Compliance | 1 | Низкий |
| 6. Тестирование | 3 | Средний |
| 7. Документация/Релиз | 1 | Низкий |
| **Итого** | **~16 дней** | |

**Резерв:** +30% = ~21 день (3 недели)

---

## 10. Зависимости и предварительные требования

### 10.1 В @BotFather (обязательно до старта)
- [ ] **Menu Button** → Configure Menu Button → Web App URL: `https://radar.example.com/`
- [ ] **Web App** → Включить, указать домен
- [ ] **Domain** → Добавить `radar.example.com` (через /setdomain)
- [ ] **Privacy Policy URL** → `https://radar.example.com/privacy`
- [ ] **Terms of Service URL** → `https://radar.example.com/terms`

### 10.2 На сервере
- [ ] SSL сертификат для `radar.example.com` (Caddy/Let's Encrypt)
- [ ] DNS A-запись на IP сервера
- [ ] Порт 80/443 проброшен на контейнер панели
- [ ] `WEB_PUBLIC_URL=https://radar.example.com` в `.env`

### 10.3 Кодовые зависимости
- `aiohttp` — уже есть
- `telegram-web-app.js` — подключается с CDN
- Существующие модули: `weather.py`, `digest.py`, `matching.py`, `storage.py`

---

## 11. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Telegram Mini App виджеты не работают на веб-странице (только в Telegram) | Высокая | Высокое | Fallback: собственные JS-виджеты, fetch с нашего API; в Telegram — полноценные Mini Apps |
| Platega откажет в модерации из-за VPN-тематики | Средняя | Критическое | Полностью убрать упоминания обхода блокировок с публичных страниц; оставить только в боте для авторизованных |
| TG Login Widget не работает на поддомене/в ифрейме | Низкая | Среднее | Использовать основной домен; `data-auth-url` на наш `/auth` |
| Ролевой доступ сломается при смене роли в боте | Низкая | Среднее | При каждом входе перечитывать роль из БД (уже реализовано в `auth.py`) |
| Виджеты погоды/опасности не обновляются в реальном времени | Средняя | Низкое | Polling каждые 5 мин для погоды, вебсокет/long-poll для опасности |

---

## 12. Критерии приёмки (Definition of Done)

### Лендинг
- [ ] Открывается на `/` без авторизации
- [ ] Все 8 секций рендерятся корректно
- [ ] 4 темы переключаются и запоминаются в localStorage
- [ ] Mobile-first: корректно на 375px, 768px, 1024px, 1440px
- [ ] Lighthouse Performance > 90, Accessibility > 95
- [ ] Кнопки «Политика», «Соглашение», «Поддержка», «Тарифы» ведут на соответсвующие страницы

### Публичные страницы
- [ ] `/privacy` — адаптированный шаблон с данными проекта, дата ноябрь 2026
- [ ] `/terms` — адаптированный шаблон, упоминание лимита 10 000 ₽
- [ ] `/support` — форма тикета / юзернейм / email, работает
- [ ] `/pricing` — таблица, все цены ≤ 10 000 ₽, нет VPN-рекламы

### TG Login + Роли
- [ ] Кнопка «Войти через Telegram» работает (Desktop, Mobile, Web)
- [ ] После входа редирект: user→/profile, moderator→/sources, admin→/users, superadmin→/settings
- [ ] В профиле видны: локации, настройки, история, виджеты погоды/опасности
- [ ] Код входа из бота (`/panel` → код) работает

### Виджеты
- [ ] Погода: текущая, почасовая (8ч), 3 дня, восход/закат, тема
- [ ] Новости: 5 последних публичных подборок, темы alerts/utilities
- [ ] Опасность: статус (активно/нет), тип (БПЛА/ракетная/отбой),.message, matched locations
- [ ] Виджеты работают на лендинге И в профиле
- [ ] Виджеты темизируются под тему страницы

### Platega Compliance
- [ ] Нет упоминаний: VPN, обход блокировок, цензура, DPI, ТСПУ, глушилки, белые списки, LTE
- [ ] Нет персональных данных: ИП, ООО, ИНН
- [ ] Кодовое слово `mekbuda` в футере (скрыто: `<!-- mekbuda -->` или `display:none`)
- [ ] Документы доступны отдельными кнопками в боте и на сайте

---

## 13. Дорожная карта (обновление ROADMAP.md)

Добавить в `docs/ROADMAP.md` после версии 5.9:

```markdown
## 5.10 — Лендинг, TG Login с ролями, виджеты, Platega compliance

1. **Публичный лендинг проекта** (`/`). Hero, фичи, как работает, демо, установка, документы (кнопки), TG Login Widget.
   Флаг: `landing_page` (включён по умолчанию).

2. **Публичные страницы для модерации платежной системы**:
   - `/privacy` — Политика конфиденциальности (адаптированный шаблон telegra.ph)
   - `/terms` — Пользовательское соглашение (адаптированный шаблон telegra.ph)
   - `/support` — Контакты поддержки: тикет-бот / юзернейм / email
   - `/pricing` — Тарифы: оповещения бесплатно, подборки Stars, VPN, проверка ссылок. Все ≤ 10 000 ₽.
   Флаг: `public_compliance_pages`.

3. **Telegram Mini App виджеты** на лендинге и в профиле:
   - Погода: текущая, почасовая, 3 дня, ветер, луна, тема
   - Новости: публичные подборки (alerts, utilities, weather)
   - Опасность: статус БПЛА/ракетная/отбой, matched locations, whitelist info
   API: `/api/widget/weather`, `/api/widget/news`, `/api/widget/danger`.
   Флаг: `tg_widgets`.

4. **Ролевой профиль пользователя** (`/profile`). После TG Login редирект по роли:
   user → /profile, moderator → /sources, admin → /users, superadmin → /settings.
   Профиль: локации, настройки уведомлений, история оповещений, подписка, виджеты.
   Флаг: `user_profile_web`.

5. **Кнопки в боте** для открытия лендинга, профиля, документов (Privacy, Terms, Support, Pricing).

6. **Platega compliance**: убрано VPN/обход, нет ПДН, лимит 10k, кодовое слово mekbuda, документы кнопками.

⚠️ **Требует проверки на живом сервере:** TG Login Widget, Mini App виджеты, прохождение модерации Platega.
```

---

## 14. Следующие шаги (Immediate Actions)

1. **Создать ветку:** `feat/landing-page-5-10`
2. **Настроить @BotFather:** Menu Button → Web App URL (заглушка), Domain
3. **Создать тикет-бота** @SecretHeroSupportBot (или определиться с юзернеймом/email)
4. **Начать Этап 1** — инфраструктура
5. **Еженедельные демо** автору для согласования дизайна

---

## Приложение А: Структура файлов (новые/изменённые)

```
radar/
├── web/
│   ├── __init__.py
│   ├── panel.py              # + маршруты /, /privacy, /terms, /support, /pricing, /profile, /api/widget/*
│   ├── auth.py               # без изменений (используется)
│   ├── landing.py            # НОВЫЙ — рендеринг лендинга
│   ├── public_pages.py       # НОВЫЙ — Privacy, Terms, Support, Pricing
│   ├── widgets.py            # НОВЫЙ — API виджетов + JS модуль
│   ├── adminpages.py         # без изменений
│   ├── settingspages.py      # без изменений
│   └── ...
├── templates/                # НОВАЯ ПАПКА (опционально, для Jinja2)
│   ├── landing.html
│   ├── privacy.html
│   ├── terms.html
│   ├── support.html
│   ├── pricing.html
│   ├── profile.html
│   └── widgets/
│       ├── weather.html
│       ├── news.html
│       └── danger.html
├── static/                   # НОВАЯ ПАПКА (опционально)
│   ├── css/
│   │   └── landing.css
│   └── js/
│       ├── landing.js
│       └── widgets.js
└── ...

docs/
├── ROADMAP.md                # + раздел 5.10
├── STATUS.md                 # + версия 5.10.0
├── releases/
│   └── 5.10.0.md            # НОВЫЙ — текст релиза
└── ...
```

---

## Приложение Б: Пример контента для лендинга (Hero)

```html
<section class="hero">
  <div class="hero-content">
    <span class="hero-badge">v5.9.10.1 · GPL-3.0 · ARM Ready</span>
    <h1>Радар — оповещения об угрозах и авариях ЖКХ по вашим адресам</h1>
    <p class="hero-subtitle">
      ИИ разбирает каналы МЧС, админок, ЖКХ и RSS-ленты. 
      Сопоставляет с вашими локациями. Присылает только то, что касается вас.
      <strong>Тревоги всегда бесплатно.</strong>
    </p>
    <div class="hero-cta">
      <a href="https://t.me/SecretHeroBot" class="btn btn-primary" target="_blank">
        <svg class="tg-icon">...</svg> Запустить в Telegram
      </a>
      <a href="#features" class="btn btn-ghost">Возможности</a>
    </div>
    <div class="hero-trust">
      <span>197 коммитов</span> · <span>105 тегов</span> · <span>Docker</span> · <span>SQLite/PostgreSQL</span>
    </div>
  </div>
  <!-- Виджеты под hero -->
  <div class="widget-row" id="hero-widgets">
    <div id="widget-weather" class="widget" data-city="auto"></div>
    <div id="widget-news" class="widget" data-topics="alerts,utilities"></div>
    <div id="widget-danger" class="widget" data-city="auto"></div>
  </div>
</section>
```

---

*Документ подготовлен для согласования. Версия 5.10.0 войдёт в дорожную карту после утверждения плана.*