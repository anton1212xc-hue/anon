import os
import time
import threading
import asyncio
import requests
import telebot
from telebot import apihelper, types
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = "1780243439:HzmpoX7Z3awrxPybzj6QhEGUlruv2AwfLsx"
PORT = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

# Перенаправляем запросы на Shuzagram API
apihelper.API_URL = "https://api.shuzagram.com/bot{0}/{1}"
bot = telebot.TeleBot(TOKEN)

# --- БАЗА ДАННЫХ В ПАМЯТИ ---
search_queue = []       # Очередь пользователей, ищущих собеседника
active_chats = {}       # Активные диалоги: {user_id: partner_id}
users_profiles = {}     # Профили: {user_id: {"ratings": [], "chats_count": 0}}

def get_user_profile(user_id):
    if user_id not in users_profiles:
        users_profiles[user_id] = {"ratings": [], "chats_count": 0}
    return users_profiles[user_id]

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔍 Найти собеседника"))
    markup.add(types.KeyboardButton("👤 Мой профиль"))
    return markup

def get_chat_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("⏭ Следующий собеседник"))
    markup.add(types.KeyboardButton("❌ Остановить диалог"))
    return markup

# --- КОМАНДА /START ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    if user_id in search_queue:
        search_queue.remove(user_id)
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        end_chat(partner_id, "Собеседник завершил сеанс.")
        if partner_id in active_chats:
            del active_chats[partner_id]
        del active_chats[user_id]

    bot.send_message(
        message.chat.id,
        "👋 <b>Добро пожаловать в Анонимный чат!</b>\n\n"
        "Нажмите кнопку ниже, чтобы найти случайного собеседника тет-а-тет.",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

# --- ОБРАБОТКА ТЕКСТА И КНОПОК ---
@bot.message_handler(func=lambda msg: True)
def handle_text(message):
    user_id = message.from_user.id
    text = message.text

    # 1. Поиск собеседника
    if text == "🔍 Найти собеседника":
        if user_id in active_chats:
            bot.send_message(user_id, "⚠️ Вы уже в диалоге! Сначала завершите текущий.")
            return
        if user_id in search_queue:
            bot.send_message(user_id, "⏳ Вы уже ищете собеседника, подождите немного...")
            return

        if search_queue:
            partner_id = search_queue.pop(0)
            
            # Связываем пользователей
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id

            # Обновляем статистику
            get_user_profile(user_id)["chats_count"] += 1
            get_user_profile(partner_id)["chats_count"] += 1

            bot.send_message(user_id, "🎉 Собеседник найден! Можете общаться.", reply_markup=get_chat_keyboard())
            bot.send_message(partner_id, "🎉 Собеседник найден! Можете общаться.", reply_markup=get_chat_keyboard())
        else:
            search_queue.append(user_id)
            cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            cancel_markup.add(types.KeyboardButton("❌ Отменить поиск"))
            bot.send_message(user_id, "🔍 Ищем свободного собеседника...", reply_markup=cancel_markup)

    # 2. Отмена поиска
    elif text == "❌ Отменить поиск":
        if user_id in search_queue:
            search_queue.remove(user_id)
        bot.send_message(user_id, "❌ Поиск отменен.", reply_markup=get_main_keyboard())

    # 3. Следующий собеседник / Остановить диалог
    elif text in ["⏭ Следующий собеседник", "❌ Остановить диалог"]:
        if user_id in active_chats:
            partner_id = active_chats[user_id]
            
            end_chat(user_id, "🛑 Диалог завершен.")
            end_chat(partner_id, "🛑 Собеседник покинул чат.")
            
            if text == "⏭ Следующий собеседник":
                message.text = "🔍 Найти собеседника"
                handle_text(message)
        else:
            bot.send_message(user_id, "Вы не находитесь в диалоге.", reply_markup=get_main_keyboard())

    # 4. Профиль
    elif text == "👤 Мой профиль":
        profile = get_user_profile(user_id)
        ratings = profile["ratings"]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0.0
        
        text_profile = (
            f"👤 <b>Ваш профиль:</b>\n\n"
            f"💬 Всего диалогов: <b>{profile['chats_count']}</b>\n"
            f"⭐ Средняя оценка: <b>{avg_rating:.1f} / 5.0</b> (оценок: {len(ratings)})"
        )
        bot.send_message(user_id, text_profile, parse_mode="HTML", reply_markup=get_main_keyboard())

    # 5. Пересылка сообщений в активном чате
    elif user_id in active_chats:
        partner_id = active_chats[user_id]
        try:
            bot.copy_message(chat_id=partner_id, from_chat_id=user_id, message_id=message.message_id)
        except Exception as e:
            print(f"Ошибка пересылки сообщения: {e}")
    else:
        bot.send_message(user_id, "Используйте кнопки меню 👇", reply_markup=get_main_keyboard())

# --- ЗАВЕРШЕНИЕ ДИАЛОГА И ОЦЕНКА ---
def end_chat(user_id, notification_text):
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        if partner_id in active_chats:
            del active_chats[partner_id]
        del active_chats[user_id]

    markup = types.InlineKeyboardMarkup(row_width=5)
    markup.add(
        types.InlineKeyboardButton("⭐ 1", callback_data="rate_1"),
        types.InlineKeyboardButton("⭐ 2", callback_data="rate_2"),
        types.InlineKeyboardButton("⭐ 3", callback_data="rate_3"),
        types.InlineKeyboardButton("⭐ 4", callback_data="rate_4"),
        types.InlineKeyboardButton("⭐ 5", callback_data="rate_5"),
    )

    try:
        bot.send_message(user_id, f"{notification_text}\n\nОцените прошедший диалог:", reply_markup=markup)
        bot.send_message(user_id, "Главное меню:", reply_markup=get_main_keyboard())
    except Exception:
        pass

# --- ОБРАБОТКА ОЦЕНКИ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def handle_rating(call):
    score = int(call.data.split("_")[1])
    user_id = call.from_user.id
    
    profile = get_user_profile(user_id)
    profile["ratings"].append(score)
    
    bot.answer_callback_query(call.id, f"Спасибо за оценку: {score} ⭐!")
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Спасибо за оценку! Вы поставили: {'⭐' * score}"
        )
    except Exception:
        pass

# --- ВЕБ-СЕРВЕР И САМОПИНГ ДЛЯ RENDER ---
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Веб-сервер запущен на порту {PORT}")

def run_web_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_web_server())
    loop.run_forever()

def self_ping_worker():
    time.sleep(10)
    while True:
        try:
            if RENDER_EXTERNAL_URL:
                requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except Exception:
            pass
        time.sleep(30)

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    ping_thread = threading.Thread(target=self_ping_worker, daemon=True)
    ping_thread.start()
    
    print("Анонимный чат-бот успешно запущен с новым токеном!")
    bot.infinity_polling(skip_pending=True)
