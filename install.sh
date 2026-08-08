#!/bin/bash

# 1. Останавливаем старый контейнер
cd ~/radar_bot || mkdir -p ~/radar_bot && cd ~/radar_bot
docker stop radar_container 2>/dev/null || true
docker rm radar_container 2>/dev/null || true

# 2. Устанавливаем зависимости
cat << 'EOF' > requirements.txt
aiogram
aiohttp
beautifulsoup4
google-genai
aiofiles
python-dotenv
EOF

# 2.1. Интерактивный ввод переменных окружения
echo "======================================"
echo "    НАСТРОЙКА СИСТЕМЫ РАДАР (v2.5.1)"
echo "======================================"

generate_env=true
if [ -f .env ]; then
    read -p "Файл .env уже существует. Использовать текущие настройки? (y/n): " use_existing < /dev/tty
    if [ "$use_existing" == "y" ] || [ "$use_existing" == "Y" ]; then
        generate_env=false
        echo "Используем существующий файл .env."
    fi
fi

if [ "$generate_env" = true ]; then
    read -p "Введите токен Telegram бота (BOT_TOKEN): " INPUT_BOT_TOKEN < /dev/tty
    read -p "Введите API ключ Gemini (GEMINI_API_KEY): " INPUT_GEMINI_API_KEY < /dev/tty
    read -p "Введите ваш Telegram ID (SUPERADMIN_ID): " INPUT_SUPERADMIN_ID < /dev/tty

    cat << EOF > .env
BOT_TOKEN=${INPUT_BOT_TOKEN}
GEMINI_API_KEY=${INPUT_GEMINI_API_KEY}
SUPERADMIN_ID=${INPUT_SUPERADMIN_ID}
EOF
    echo "Файл .env успешно создан."
fi

# 3. Полностью перезаписываем bot.py
cat << 'EOF' > bot.py
import asyncio, aiohttp, logging, json, os, time
from datetime import datetime
import aiofiles
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from google import genai

# --- ИНИЦИАЛИЗАЦИЯ И НАСТРОЙКИ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPERADMIN_ID = int(os.getenv("SUPERADMIN_ID", 0))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

BOT_VERSION = "2.5.1"
CHANGELOG = (
    f"🚀 **Обновление системы Радар v{BOT_VERSION}**\n\n"
    "✨ **Что нового в этой версии:**\n"
    "1. 📋 **Оптимизация интерфейса модератора/админа:** При удалении локаций, кике или изменении роли теперь автоматически выводится список всех пользователей для удобного копирования ID.\n"
)

ai_client = genai.Client(api_key=GEMINI_API_KEY)

DATA_FILE = "data/db.json"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
seen_texts = set()

db = {}

# --- СОСТОЯНИЯ (FSM) ---
class BotStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_user_id_kick = State()
    waiting_for_user_id_role = State()
    waiting_for_admin_loc_delete = State()
    waiting_for_ai_question = State()
    waiting_for_custom_weather_time = State()
    waiting_for_custom_weather_interval = State()

# --- АСИНХРОННАЯ БАЗА ДАННЫХ ---
async def load_data():
    global db
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        db = {
            "users": {str(SUPERADMIN_ID): {"role": "superadmin", "locs": [], "settings": {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}, "weather_mode": "interval", "weather_interval": 60, "weather_time": "08:00", "last_weather": 0, "last_fixed_date": ""}},
            "channels": ["saratov_24", "mchs_saratov", "saratovmeriya"],
            "pending": []
        }
        await save_data(db)
        return

    async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
        content = await f.read()
        data = json.loads(content)
        
        for uid, udata in data["users"].items():
            if "weather_mode" not in udata: udata["weather_mode"] = "interval"
            if "weather_interval" not in udata: udata["weather_interval"] = 0
            if "weather_time" not in udata: udata["weather_time"] = "08:00"
            if "last_weather" not in udata: udata["last_weather"] = 0
            if "last_fixed_date" not in udata: udata["last_fixed_date"] = ""
            new_locs = []
            for loc in udata.get("locs", []):
                if isinstance(loc, str): new_locs.append({"name": loc, "lat": 0.0, "lon": 0.0})
                else: new_locs.append(loc)
            udata["locs"] = new_locs
        db = data

async def save_data(data):
    async with aiofiles.open(DATA_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=4))

def get_role(uid): return db["users"].get(str(uid), {}).get("role", None)
def is_superadmin(uid): return get_role(uid) == "superadmin"
def is_admin(uid): return get_role(uid) in ["superadmin", "admin"]
def is_mod(uid): return get_role(uid) in ["superadmin", "admin", "moderator"]

def get_users_list_text():
    lines = ["👥 **Список пользователей:**\n"]
    for uid, udata in db["users"].items():
        role = udata.get("role", "user")
        locs_count = len(udata.get("locs", []))
        lines.append(f"ID: `{uid}` | Роль: {role} | Адресов: {locs_count}")
    
    text = "\n".join(lines)
    if len(text) > 3500: text = text[:3500] + "\n\n... (список обрезан)"
    return text

# --- MIDDLEWARE ---
class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            uid_str = str(user.id)
            text = getattr(event, "text", "")
            if text and text.startswith("/start join"):
                if uid_str not in db["users"]:
                    db["users"][uid_str] = {"role": "user", "locs": [], "settings": {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}, "weather_mode": "interval", "weather_interval": 0, "weather_time": "08:00", "last_weather": 0, "last_fixed_date": ""}
                    await save_data(db)
            if uid_str not in db["users"]: return 
        return await handler(event, data)

dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())

# --- КЛАВИАТУРЫ ---
def get_main_menu(uid):
    kb = [
        [InlineKeyboardButton(text="📍 Мои адреса", callback_data="menu_locs"),
         InlineKeyboardButton(text="⚙️ Угрозы и Погода", callback_data="menu_settings")],
        [InlineKeyboardButton(text="🔄 Обновить погоду", callback_data="user_refresh_weather"),
         InlineKeyboardButton(text="📢 Предложить канал", callback_data="menu_suggest")]
    ]
    if is_mod(uid):
        kb.append([InlineKeyboardButton(text="🛡 Модерация (Каналы/Локации)", callback_data="menu_mod")])
    if is_admin(uid):
        kb.append([InlineKeyboardButton(text="👥 Управление доступом", callback_data="menu_admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_settings_menu(uid):
    st = db["users"][str(uid)]["settings"]
    mode = db["users"][str(uid)].get("weather_mode", "interval")
    wi = db["users"][str(uid)].get("weather_interval", 0)
    wt = db["users"][str(uid)].get("weather_time", "08:00")
    
    if mode == "time":
        w_text = f"В {wt}"
    else:
        w_text = "Откл" if wi == 0 else (f"{wi // 60} ч" if wi >= 60 and wi % 60 == 0 else f"{wi} мин")
    
    kb = [
        [InlineKeyboardButton(text=("✅" if st.get("jkh") else "❌") + " ЖКХ", callback_data="tg_jkh"),
         InlineKeyboardButton(text=("✅" if st.get("bpla") else "❌") + " БПЛА", callback_data="tg_bpla")],
        [InlineKeyboardButton(text=("✅" if st.get("mchs") else "❌") + " МЧС", callback_data="tg_mchs"),
         InlineKeyboardButton(text=("✅" if st.get("whitelist") else "❌") + " Белые списки", callback_data="tg_whitelist")],
        [InlineKeyboardButton(text=f"🌤 Погода: {w_text} (Изменить)", callback_data="menu_weather")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_weather_menu():
    kb = [
        [InlineKeyboardButton(text="Отключить", callback_data="wth_off"), InlineKeyboardButton(text="Каждый 1 час", callback_data="wth_60")],
        [InlineKeyboardButton(text="Каждые 3 часа", callback_data="wth_180"), InlineKeyboardButton(text="Каждые 6 часов", callback_data="wth_360")],
        [InlineKeyboardButton(text="⏰ Задать точное время", callback_data="wth_custom_time"), InlineKeyboardButton(text="⏱ Свой интервал", callback_data="wth_custom_interval")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- ВИДЖЕТ ПОГОДЫ ---
async def get_weather(lat, lon):
    if not lat or not lon: return "Нет точных координат для локации."
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m,precipitation&hourly=temperature_2m,precipitation_probability&timezone=auto&forecast_hours=7"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    c = data.get("current", {})
                    temp = c.get("temperature_2m", "?")
                    wind = c.get("wind_speed_10m", "?")
                    prec = c.get("precipitation", 0)
                    rain_info = "🌧 Осадки" if prec > 0 else "☁️ Без осадков"
                    
                    res = f"🌡 **Сейчас:** {temp}°C | 💨 {wind} км/ч | {rain_info}\n"
                    res += "⏱ **Прогноз на 6 часов:**\n"
                    
                    hourly = data.get("hourly", {})
                    times = hourly.get("time", [])
                    temps = hourly.get("temperature_2m", [])
                    probs = hourly.get("precipitation_probability", [])
                    
                    hourly_str_list = []
                    for i in range(1, min(7, len(times))):
                        t_str = times[i].split("T")[1][:5] if "T" in times[i] else f"+{i}ч"
                        t_val = temps[i] if i < len(temps) else "?"
                        p_val = probs[i] if i < len(probs) else 0
                        hourly_str_list.append(f"`{t_str}`: {t_val}°C ({p_val}%)")
                    
                    res += " | ".join(hourly_str_list)
                    return res
    except Exception as e:
        logger.error(f"Ошибка получения погоды: {e}")
    return "Сбой получения погоды."

async def build_user_weather_summary(uid_str):
    udata = db["users"].get(uid_str, {})
    if not udata.get("locs"):
        return "📍 У вас пока нет сохраненных локаций."
    
    text_blocks = []
    for loc in udata["locs"]:
        w_info = await get_weather(loc.get("lat"), loc.get("lon"))
        text_blocks.append(f"🏢 **Объект:** {loc['name']}\n{w_info}")
    return "\n\n".join(text_blocks)

# --- ОПОВЕЩЕНИЯ ---
async def notify_startup_changes():
    current_time = int(time.time())
    for uid_str, udata in db["users"].items():
        try:
            uid = int(uid_str)
            if is_admin(uid):
                await bot.send_message(uid, CHANGELOG, parse_mode="Markdown")
            
            locs_list = udata.get("locs", [])
            locs_text = "\n".join([f"- {l['name']}" for l in locs_list]) if locs_list else "Локации не заданы"
            
            msg = (
                "🔄 **Система Радар успешно обновлена!**\n\n"
                f"📍 **Ваши отслеживаемые адреса:**\n{locs_text}\n\n"
                "🛡 **Статус угроз:** Опасности на данный момент не зафиксированы.\n\n"
                "🌤 **Актуальная сводка погоды:**\n"
            )
            if locs_list:
                w_summary = await build_user_weather_summary(uid_str)
                msg += w_summary
            else:
                msg += "Отправьте геопозицию в чат, чтобы получать погоду и сводки угроз."
                
            await bot.send_message(uid, msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось отправить стартовое уведомление {uid_str}: {e}")

# --- ФОНОВЫЙ ЦИКЛ ---
async def monitor_loop():
    async with aiohttp.ClientSession() as session:
        while True:
            current_time = int(time.time())
            now_dt = datetime.now()
            current_hhmm = now_dt.strftime("%H:%M")
            current_date_str = now_dt.strftime("%Y-%m-%d")
            
            news_buffer = []
            
            for channel in db["channels"]:
                try:
                    async with session.get(f"https://t.me/s/{channel}", timeout=10) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            msgs = BeautifulSoup(html, 'html.parser').find_all('div', class_='tgme_widget_message_text')
                            if msgs:
                                text = msgs[-1].get_text(separator='\n')
                                if text not in seen_texts:
                                    seen_texts.add(text)
                                    if len(seen_texts) > 200: seen_texts.pop()
                                    news_buffer.append((channel, text))
                        elif resp.status == 429:
                            logger.warning(f"Rate limit от Telegram для канала {channel}")
                except Exception as e:
                    logger.error(f"Ошибка парсинга канала {channel}: {e}")

            data_changed = False
            for uid_str, udata in db["users"].items():
                if not udata["locs"]: continue
                
                mode = udata.get("weather_mode", "interval")
                interval = udata.get("weather_interval", 0)
                target_time = udata.get("weather_time", "08:00")
                last_w = udata.get("last_weather", 0)
                last_f_date = udata.get("last_fixed_date", "")
                
                need_weather = False
                if mode == "interval" and interval > 0:
                    need_weather = (current_time - last_w >= interval * 60)
                elif mode == "time":
                    need_weather = (current_hhmm == target_time) and (last_f_date != current_date_str)
                
                if not news_buffer and not need_weather: continue

                st = udata["settings"]
                for loc in udata["locs"]:
                    consolidated_msg = f"🏢 **Сводка по объекту:** {loc['name']}\n"
                    has_data_to_send = False
                    
                    threats_found = []
                    if news_buffer:
                        for channel, text in news_buffer:
                            cond = []
                            if st.get("jkh"): cond.append(f"- ЖКХ/Аварии рядом с {loc['name']}")
                            if st.get("bpla"): cond.append("- Прилеты БПЛА, взрывы")
                            if st.get("mchs"): cond.append("- Экстренные оповещения")
                            if st.get("whitelist"): cond.append(f"- Белые списки связи по {loc['name']}")
                            
                            if cond:
                                prompt = f"Текст: '{text}'\nЕсть угрозы или события:\n{chr(10).join(cond)}\nДА (суть) / НЕТ."
                                try:
                                    resp_ai = await ai_client.aio.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                                    ans = resp_ai.text.strip()
                                    if ans.upper() != "НЕТ":
                                        threats_found.append(f"📍 **@{channel}:**\n{ans}")
                                except Exception as e:
                                    logger.error(f"Ошибка Gemini API: {e}")
                    
                    if threats_found:
                        consolidated_msg += "\n🚨 **ОБНАРУЖЕНЫ СОБЫТИЯ:**\n" + "\n\n".join(threats_found) + "\n"
                        has_data_to_send = True

                    if need_weather and loc.get("lat"):
                        weather_info = await get_weather(loc["lat"], loc["lon"])
                        consolidated_msg += f"\n🌤 **Текущая погода и прогноз:**\n{weather_info}"
                        has_data_to_send = True
                        db["users"][uid_str]["last_weather"] = current_time
                        if mode == "time":
                            db["users"][uid_str]["last_fixed_date"] = current_date_str
                        data_changed = True

                    if has_data_to_send:
                        try:
                            await bot.send_message(int(uid_str), consolidated_msg, parse_mode="Markdown")
                        except Exception as e:
                            logger.error(f"Не удалось отправить сообщение пользователю {uid_str}: {e}")
            
            if data_changed:
                await save_data(db)
                
            await asyncio.sleep(60)

# --- ОБРАБОТЧИКИ UI И FSM ---
@dp.message(Command("start", "menu"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(f"🎛 **Система Радар v{BOT_VERSION}**", reply_markup=get_main_menu(msg.from_user.id), parse_mode="Markdown")

def get_locs_ui(uid_str):
    locs = "\n".join([f"- {l['name']}" for l in db["users"][uid_str]["locs"]]) if db["users"][uid_str]["locs"] else "Пусто"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить погоду", callback_data="user_refresh_weather")],
        [InlineKeyboardButton(text="🗑 Очистить мои адреса", callback_data="locs_clear")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu_main")]
    ])
    return f"📍 **Ваши адреса:**\n{locs}\n\n*Для добавления просто отправьте геопозицию в чат (Скрепка -> Геопозиция).*", kb

@dp.callback_query(F.data.startswith("menu_"))
async def process_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    uid_str = str(call.from_user.id)
    action = call.data.split("_", 1)[1]
    
    if action == "main":
        await call.message.edit_text(f"🎛 **Система Радар v{BOT_VERSION}**", reply_markup=get_main_menu(call.from_user.id), parse_mode="Markdown")
    elif action == "settings":
        await call.message.edit_text("⚙️ **Угрозы и Погода:**", reply_markup=get_settings_menu(call.from_user.id), parse_mode="Markdown")
    elif action == "weather":
        await call.message.edit_text("⏱ **Выберите интервал или точное время отправки погоды:**", reply_markup=get_weather_menu())
    elif action == "locs":
        text, kb = get_locs_ui(uid_str)
        await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    elif action == "suggest":
        await call.message.edit_text("📝 Введите юзернейм канала (например: saratov_24):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_main")]]))
        await state.set_state(BotStates.waiting_for_channel)
    elif action == "mod":
        if not is_mod(call.from_user.id): return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛡 Очередь каналов", callback_data="mod_channels")],
            [InlineKeyboardButton(text="🗑 Удалить локацию пользователя", callback_data="mod_locs")],
            [InlineKeyboardButton(text="🏠 Назад", callback_data="menu_main")]
        ])
        await call.message.edit_text("🛡 **Панель Модератора**", reply_markup=kb)
    elif action == "admin":
        if not is_admin(call.from_user.id): return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 ИИ-Помощник (Задать вопрос)", callback_data="adm_ai")],
            [InlineKeyboardButton(text="📋 Список пользователей", callback_data="adm_users")],
            [InlineKeyboardButton(text="🔗 Сгенерировать инвайт", callback_data="adm_invite")],
            [InlineKeyboardButton(text="🔨 Удалить пользователя", callback_data="adm_kick")],
            [InlineKeyboardButton(text="👑 Изменить роль", callback_data="adm_role")],
            [InlineKeyboardButton(text="🏠 Назад", callback_data="menu_main")]
        ])
        await call.message.edit_text("👥 **Управление доступом & ИИ-Помощник**", reply_markup=kb)

# --- РУЧНОЕ ОБНОВЛЕНИЕ ПОГОДЫ ---
@dp.callback_query(F.data == "user_refresh_weather")
async def user_refresh_weather(call: CallbackQuery):
    uid_str = str(call.from_user.id)
    await call.answer("Получение актуального прогноза...")
    summary = await build_user_weather_summary(uid_str)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu_main")]])
    await call.message.answer(f"🌤 **Актуальная сводка погоды:**\n\n{summary}", reply_markup=kb, parse_mode="Markdown")

# --- НАСТРОЙКА ПОГОДЫ (НАСТРОЙКА ИНТЕРВАЛА И ВРЕМЕНИ) ---
@dp.callback_query(F.data.startswith("wth_"))
async def process_weather_select(call: CallbackQuery, state: FSMContext):
    uid_str = str(call.from_user.id)
    action = call.data.split("_", 1)[1]
    
    if action == "off":
        db["users"][uid_str]["weather_mode"] = "interval"
        db["users"][uid_str]["weather_interval"] = 0
        await save_data(db)
        await call.answer("Погода отключена")
        await call.message.edit_text("⚙️ **Угрозы и Погода:**", reply_markup=get_settings_menu(call.from_user.id))
    elif action == "custom_time":
        await call.message.edit_text("⏰ Введите точное время отправки погоды в формате HH:MM (например, 08:30 или 19:00):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_weather")]]))
        await state.set_state(BotStates.waiting_for_custom_weather_time)
    elif action == "custom_interval":
        await call.message.edit_text("⏱ Введите интервал вызова в минутах (например, 45) или часах (например, 2ч):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_weather")]]))
        await state.set_state(BotStates.waiting_for_custom_weather_interval)
    else:
        try:
            mins = int(action)
            db["users"][uid_str]["weather_mode"] = "interval"
            db["users"][uid_str]["weather_interval"] = mins
            db["users"][uid_str]["last_weather"] = 0
            await save_data(db)
            await call.answer(f"Интервал установлен: {mins} мин")
            await call.message.edit_text("⚙️ **Угрозы и Погода:**", reply_markup=get_settings_menu(call.from_user.id))
        except: pass

@dp.message(BotStates.waiting_for_custom_weather_time)
async def fsm_set_weather_time(msg: Message, state: FSMContext):
    val = msg.text.strip()
    try:
        time.strptime(val, "%H:%M")
        uid_str = str(msg.from_user.id)
        db["users"][uid_str]["weather_mode"] = "time"
        db["users"][uid_str]["weather_time"] = val
        db["users"][uid_str]["last_fixed_date"] = ""
        await save_data(db)
        await msg.answer(f"✅ Погода будет приходить ежедневно в **{val}**.", reply_markup=get_settings_menu(msg.from_user.id), parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await msg.answer("❌ Неверный формат времени. Введите время в формате HH:MM (например, 08:00):")

@dp.message(BotStates.waiting_for_custom_weather_interval)
async def fsm_set_weather_interval(msg: Message, state: FSMContext):
    val = msg.text.strip().lower()
    mins = 0
    try:
        if "ч" in val or "h" in val:
            hours = int(val.replace("ч", "").replace("h", "").strip())
            mins = hours * 60
        else:
            mins = int(val)
            
        if mins < 5:
            await msg.answer("❌ Минимальный интервал — 5 минут. Попробуйте еще раз:")
            return
            
        uid_str = str(msg.from_user.id)
        db["users"][uid_str]["weather_mode"] = "interval"
        db["users"][uid_str]["weather_interval"] = mins
        db["users"][uid_str]["last_weather"] = 0
        await save_data(db)
        await msg.answer(f"✅ Интервал отправки погоды установлен на **{mins} мин.**", reply_markup=get_settings_menu(msg.from_user.id), parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await msg.answer("❌ Некорректное значение. Введите число минут (например: 45) или часов (например: 2ч):")

@dp.callback_query(F.data.startswith("tg_"))
async def process_settings_toggle(call: CallbackQuery):
    uid_str = str(call.from_user.id)
    param = call.data.split("_", 1)[1]
    db["users"][uid_str]["settings"][param] = not db["users"][uid_str]["settings"][param]
    await save_data(db)
    await call.message.edit_reply_markup(reply_markup=get_settings_menu(call.from_user.id))

@dp.message(F.location)
async def handle_loc(msg: Message):
    lat, lon = msg.location.latitude, msg.location.longitude
    address = f"{lat}, {lon}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json", headers={"User-Agent": "RadarBot/10.0"}, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    addr_parts = data.get("address", {})
                    address = ", ".join(filter(None, [addr_parts.get("road", ""), addr_parts.get("house_number", "")])) or address
    except Exception as e:
        logger.error(f"Ошибка геокодирования: {e}")
    
    uid_str = str(msg.from_user.id)
    if not any(l["name"] == address for l in db["users"][uid_str]["locs"]):
        db["users"][uid_str]["locs"].append({"name": address, "lat": lat, "lon": lon})
        await save_data(db)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu_main")]])
    await msg.answer(f"🏠 Адрес **{address}** добавлен.", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "locs_clear")
async def clear_my_locs(call: CallbackQuery):
    uid_str = str(call.from_user.id)
    db["users"][uid_str]["locs"] = []
    await save_data(db)
    await call.answer("Локации очищены")
    text, kb = get_locs_ui(uid_str)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.message(BotStates.waiting_for_channel)
async def fsm_suggest(msg: Message, state: FSMContext):
    ch = msg.text.replace("@", "").replace("https://t.me/", "")
    if ch not in db["channels"] and ch not in db["pending"]:
        db["pending"].append(ch)
        await save_data(db)
        await msg.answer(f"✅ Канал @{ch} отправлен модераторам.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu_main")]]))
    else:
        await msg.answer("❌ Канал уже в базе.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu_main")]]))
    await state.clear()

@dp.callback_query(F.data == "mod_channels")
async def mod_channels_view(call: CallbackQuery):
    pend = db["pending"]
    if not pend: return await call.answer("Очередь пуста.", show_alert=True)
    ch = pend[0]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"aprv_{ch}"), InlineKeyboardButton(text="❌ Откл", callback_data=f"rjct_{ch}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mod")]
    ])
    await call.message.edit_text(f"Очередь: {len(pend)}. Проверка: @{ch}", reply_markup=kb)

@dp.callback_query(F.data.startswith("aprv_") | F.data.startswith("rjct_"))
async def mod_decision(call: CallbackQuery):
    action, ch = call.data.split("_", 1)
    if ch in db["pending"]:
        db["pending"].remove(ch)
        if action == "aprv" and ch not in db["channels"]: db["channels"].append(ch)
        await save_data(db)
    await mod_channels_view(call)

# --- МОДЕРАЦИЯ И УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ (С ВЫВОДОМ СПИСКА) ---

@dp.callback_query(F.data == "mod_locs")
async def ask_del_loc(call: CallbackQuery, state: FSMContext):
    list_text = get_users_list_text()
    prompt = f"{list_text}\n\n👇 **Отправьте ID пользователя, чью локацию нужно удалить (нажмите на ID, чтобы скопировать):**"
    await call.message.edit_text(prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_mod")]]), parse_mode="Markdown")
    await state.set_state(BotStates.waiting_for_admin_loc_delete)

@dp.message(BotStates.waiting_for_admin_loc_delete)
async def fsm_del_loc(msg: Message, state: FSMContext):
    target_id = msg.text.strip()
    if target_id in db["users"]:
        db["users"][target_id]["locs"] = []
        await save_data(db)
        await msg.answer(f"✅ Локации пользователя `{target_id}` удалены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mod")]]), parse_mode="Markdown")
    else:
        await msg.answer("❌ Пользователь не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mod")]]))
    await state.clear()

@dp.callback_query(F.data == "adm_ai")
async def ask_ai_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await call.message.edit_text("🤖 **ИИ-Помощник Администратора**\n\nВведите ваш вопрос к Gemini AI (например: *'Сформируй сводку безопасности'* или *'Как настроить маршрутизацию?'*):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_admin")]]), parse_mode="Markdown")
    await state.set_state(BotStates.waiting_for_ai_question)

@dp.message(BotStates.waiting_for_ai_question)
async def fsm_process_ai_question(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    prompt = msg.text.strip()
    loading_msg = await msg.answer("🧠 *ИИ генерирует ответ...*", parse_mode="Markdown")
    
    try:
        resp_ai = await ai_client.aio.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ans = resp_ai.text.strip()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Задать еще вопрос", callback_data="adm_ai")],
            [InlineKeyboardButton(text="◀️ В меню админа", callback_data="menu_admin")]
        ])
        await loading_msg.edit_text(f"🤖 **Ответ ИИ:**\n\n{ans}", reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка ИИ-помощника: {e}")
        await loading_msg.edit_text("❌ Ошибка обращения к ИИ. Проверьте API ключ.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В меню админа", callback_data="menu_admin")]]))
    
    await state.clear()

@dp.callback_query(F.data == "adm_users")
async def view_users(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    text = get_users_list_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "adm_invite")
async def gen_invite(call: CallbackQuery):
    bot_info = await bot.get_me()
    await call.message.edit_text(f"🔗 **Инвайт:**\nhttps://t.me/{bot_info.username}?start=join", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]]))

@dp.callback_query(F.data == "adm_kick")
async def ask_kick(call: CallbackQuery, state: FSMContext):
    list_text = get_users_list_text()
    prompt = f"{list_text}\n\n👇 **Отправьте ID пользователя для удаления (нажмите на ID, чтобы скопировать):**"
    await call.message.edit_text(prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_admin")]]), parse_mode="Markdown")
    await state.set_state(BotStates.waiting_for_user_id_kick)

@dp.message(BotStates.waiting_for_user_id_kick)
async def fsm_kick(msg: Message, state: FSMContext):
    tid = msg.text.strip()
    if tid == str(SUPERADMIN_ID): 
        await msg.answer("❌ Нельзя удалить создателя.")
    elif get_role(tid) == "admin" and not is_superadmin(msg.from_user.id): 
        await msg.answer("❌ Недостаточно прав для удаления администратора.")
    elif tid in db["users"]:
        del db["users"][tid]
        await save_data(db)
        await msg.answer(f"✅ Пользователь `{tid}` успешно удален.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В меню админа", callback_data="menu_admin")]]), parse_mode="Markdown")
    else: 
        await msg.answer("❌ Пользователь не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]]))
    await state.clear()

@dp.callback_query(F.data == "adm_role")
async def ask_role_id(call: CallbackQuery, state: FSMContext):
    list_text = get_users_list_text()
    prompt = f"{list_text}\n\n👇 **Отправьте ID пользователя для изменения роли (нажмите на ID, чтобы скопировать):**"
    await call.message.edit_text(prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_admin")]]), parse_mode="Markdown")
    await state.set_state(BotStates.waiting_for_user_id_role)

@dp.message(BotStates.waiting_for_user_id_role)
async def fsm_ask_role(msg: Message, state: FSMContext):
    tid = msg.text.strip()
    
    if tid not in db["users"]:
        await msg.answer("❌ Пользователь не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]]))
        await state.clear()
        return
        
    if tid == str(SUPERADMIN_ID):
        await msg.answer("❌ Нельзя изменить роль создателя.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]]))
        await state.clear()
        return
    
    await state.update_data(target_id=tid)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Пользователь (user)", callback_data="setrole_user")],
        [InlineKeyboardButton(text="🛡 Модератор (moderator)", callback_data="setrole_moderator")],
        [InlineKeyboardButton(text="👑 Админ (admin)", callback_data="setrole_admin")],
        [InlineKeyboardButton(text="Отмена", callback_data="menu_admin")]
    ])
    await msg.answer(f"Выберите новую роль для пользователя `{tid}`:", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("setrole_"))
async def set_new_role(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    
    new_role = call.data.split("_")[1]
    data = await state.get_data()
    tid = data.get("target_id")
    
    if tid and tid in db["users"]:
        db["users"][tid]["role"] = new_role
        await save_data(db)
        await call.message.edit_text(f"✅ Роль пользователя `{tid}` успешно изменена на **{new_role}**.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В меню админа", callback_data="menu_admin")]]))
    else:
        await call.message.edit_text("❌ Произошла ошибка. Пользователь не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]]))
        
    await state.clear()

async def main():
    await load_data()
    asyncio.create_task(monitor_loop())
    asyncio.create_task(notify_startup_changes())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
EOF

# 4. Создаем Dockerfile
cat << 'EOF' > Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
CMD ["python", "bot.py"]
EOF

# 5. Собираем и запускаем
echo "Сборка Docker-образа..."
docker build -t radar_image .
echo "Запуск контейнера..."
docker run -d --name radar_container --env-file .env --restart unless-stopped -v ~/radar_bot/data:/app/data radar_image
echo "Готово! Бот v2.5.1 успешно запущен."
