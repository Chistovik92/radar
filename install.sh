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
echo "    НАСТРОЙКА СИСТЕМЫ РАДАР"
echo "======================================"

generate_env=true
if [ -f .env ]; then
    # Читаем из /dev/tty, чтобы не сломать ввод при запуске через curl | bash
    read -p "Файл .env уже существует. Использовать текущие настройки? (y/n): " use_existing < /dev/tty
    if [ "$use_existing" == "y" ] || [ "$use_existing" == "Y" ]; then
        generate_env=false
        echo "Используем существующий файл .env."
    fi
fi

if [ "$generate_env" = true ]; then
    # Читаем из /dev/tty
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
    waiting_for_role_assignment = State()
    waiting_for_admin_loc_delete = State()

# --- АСИНХРОННАЯ БАЗА ДАННЫХ ---
async def load_data():
    global db
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        db = {
            "users": {str(SUPERADMIN_ID): {"role": "superadmin", "locs": [], "settings": {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}, "weather_interval": 60, "last_weather": 0}},
            "channels": ["saratov_24", "mchs_saratov", "saratovmeriya"],
            "pending": []
        }
        await save_data(db)
        return

    async with aiofiles.open(DATA_FILE, "r", encoding="utf-8") as f:
        content = await f.read()
        data = json.loads(content)
        
        for uid, udata in data["users"].items():
            if "weather_interval" not in udata: udata["weather_interval"] = 0
            if "last_weather" not in udata: udata["last_weather"] = 0
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

# --- MIDDLEWARE ---
class AccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            uid_str = str(user.id)
            text = getattr(event, "text", "")
            if text and text.startswith("/start join"):
                if uid_str not in db["users"]:
                    db["users"][uid_str] = {"role": "user", "locs": [], "settings": {"jkh": True, "bpla": True, "mchs": True, "whitelist": True}, "weather_interval": 0, "last_weather": 0}
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
        [InlineKeyboardButton(text="📢 Предложить канал", callback_data="menu_suggest")]
    ]
    if is_mod(uid):
        kb.append([InlineKeyboardButton(text="🛡 Модерация (Каналы/Локации)", callback_data="menu_mod")])
    if is_admin(uid):
        kb.append([InlineKeyboardButton(text="👥 Управление доступом", callback_data="menu_admin")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_settings_menu(uid):
    st = db["users"][str(uid)]["settings"]
    wi = db["users"][str(uid)].get("weather_interval", 0)
    w_text = "Откл" if wi == 0 else f"{wi} мин"
    
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
        [InlineKeyboardButton(text="Отключить", callback_data="wth_0"), InlineKeyboardButton(text="5 мин", callback_data="wth_5")],
        [InlineKeyboardButton(text="15 мин", callback_data="wth_15"), InlineKeyboardButton(text="30 мин", callback_data="wth_30")],
        [InlineKeyboardButton(text="60 мин", callback_data="wth_60"), InlineKeyboardButton(text="◀️ Назад", callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- OPEN-METEO API ---
async def get_weather(lat, lon):
    if not lat or not lon: return "Нет точных координат."
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m,precipitation&timezone=auto"
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
                    return f"🌡 {temp}°C | 💨 {wind} км/ч | {rain_info}"
    except Exception as e:
        logger.error(f"Ошибка получения погоды: {e}")
    return "Сбой получения погоды."

# --- ФОНОВЫЙ ЦИКЛ ---
async def monitor_loop():
    async with aiohttp.ClientSession() as session:
        while True:
            current_time = int(time.time())
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
                
                interval = udata.get("weather_interval", 0)
                last_w = udata.get("last_weather", 0)
                need_weather = (interval > 0) and (current_time - last_w >= interval * 60)
                
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
                                    resp_ai = await ai_client.aio.models.generate_content(model='gemini-flash-latest', contents=prompt)
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
                        consolidated_msg += f"\n🌤 **Текущая погода:** {weather_info}"
                        has_data_to_send = True
                        db["users"][uid_str]["last_weather"] = current_time
                        data_changed = True

                    if has_data_to_send:
                        try:
                            await bot.send_message(int(uid_str), consolidated_msg)
                        except Exception as e:
                            logger.error(f"Не удалось отправить сообщение пользователю {uid_str}: {e}")
            
            if data_changed:
                await save_data(db)
                
            await asyncio.sleep(60)

# --- ОБРАБОТЧИКИ UI И FSM ---
@dp.message(Command("start", "menu"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🎛 **Система Радар**", reply_markup=get_main_menu(msg.from_user.id))

def get_locs_ui(uid_str):
    locs = "\n".join([f"- {l['name']}" for l in db["users"][uid_str]["locs"]]) if db["users"][uid_str]["locs"] else "Пусто"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить мои адреса", callback_data="locs_clear")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu_main")]
    ])
    return f"📍 **Ваши адреса:**\n{locs}\n\n*Для добавления просто отправьте геопозицию в чат (Скрепка -> Геопозиция).*.", kb

@dp.callback_query(F.data.startswith("menu_"))
async def process_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    uid_str = str(call.from_user.id)
    action = call.data.split("_", 1)[1]
    
    if action == "main":
        await call.message.edit_text("🎛 **Система Радар**", reply_markup=get_main_menu(call.from_user.id))
    elif action == "settings":
        await call.message.edit_text("⚙️ **Угрозы и Погода:**", reply_markup=get_settings_menu(call.from_user.id))
    elif action == "weather":
        await call.message.edit_text("⏱ **Выберите интервал проверки погоды:**", reply_markup=get_weather_menu())
    elif action == "locs":
        text, kb = get_locs_ui(uid_str)
        await call.message.edit_text(text, reply_markup=kb)
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
            [InlineKeyboardButton(text="🔗 Сгенерировать инвайт", callback_data="adm_invite")],
            [InlineKeyboardButton(text="🔨 Удалить пользователя", callback_data="adm_kick")],
            [InlineKeyboardButton(text="👑 Изменить роль", callback_data="adm_role")],
            [InlineKeyboardButton(text="🏠 Назад", callback_data="menu_main")]
        ])
        await call.message.edit_text("👥 **Управление доступом**", reply_markup=kb)

@dp.callback_query(F.data.startswith("tg_") | F.data.startswith("wth_"))
async def process_settings(call: CallbackQuery):
    uid_str = str(call.from_user.id)
    prefix, param = call.data.split("_", 1)
    
    if prefix == "tg":
        db["users"][uid_str]["settings"][param] = not db["users"][uid_str]["settings"][param]
    elif prefix == "wth":
        db["users"][uid_str]["weather_interval"] = int(param)
        db["users"][uid_str]["last_weather"] = 0
        
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
    await msg.answer(f"🏠 Адрес **{address}** добавлен.", reply_markup=kb)

@dp.callback_query(F.data == "locs_clear")
async def clear_my_locs(call: CallbackQuery):
    uid_str = str(call.from_user.id)
    db["users"][uid_str]["locs"] = []
    await save_data(db)
    await call.answer("Локации очищены")
    text, kb = get_locs_ui(uid_str)
    await call.message.edit_text(text, reply_markup=kb)

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

@dp.callback_query(F.data == "mod_locs")
async def ask_del_loc(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте ID пользователя, чью локацию нужно удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_mod")]]))
    await state.set_state(BotStates.waiting_for_admin_loc_delete)

@dp.message(BotStates.waiting_for_admin_loc_delete)
async def fsm_del_loc(msg: Message, state: FSMContext):
    target_id = msg.text.strip()
    if target_id in db["users"]:
        db["users"][target_id]["locs"] = []
        await save_data(db)
        await msg.answer(f"✅ Локации пользователя {target_id} удалены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mod")]]))
    else:
        await msg.answer("❌ Пользователь не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_mod")]]))
    await state.clear()

@dp.callback_query(F.data == "adm_invite")
async def gen_invite(call: CallbackQuery):
    bot_info = await bot.get_me()
    await call.message.edit_text(f"🔗 **Инвайт:**\nhttps://t.me/{bot_info.username}?start=join", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="menu_admin")]]))

@dp.callback_query(F.data == "adm_kick")
async def ask_kick(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте ID пользователя для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="menu_admin")]]))
    await state.set_state(BotStates.waiting_for_user_id_kick)

@dp.message(BotStates.waiting_for_user_id_kick)
async def fsm_kick(msg: Message, state: FSMContext):
    tid = msg.text.strip()
    if tid == str(SUPERADMIN_ID): await msg.answer("Нельзя кикнуть создателя.")
    elif get_role(tid) == "admin" and not is_superadmin(msg.from_user.id): await msg.answer("Недостаточно прав.")
    elif tid in db["users"]:
        del db["users"][tid]
        await save_data(db)
        await msg.answer("✅ Пользователь удален.")
    else: await msg.answer("❌ Не найден.")
    await state.clear()

async def main():
    await load_data()
    asyncio.create_task(monitor_loop())
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
echo "Готово! Бот запущен."
