import logging
import sqlite3
import secrets
import string
import re
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8206275772:AAGGRf1u50iDCziHS0SCHSyijddw4Z8DAL8"
ADMIN_IDS = [6018936021, 8052728789]
# ================================

logging.basicConfig(level=logging.INFO)

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        link_code TEXT UNIQUE,
        name TEXT,
        username TEXT,
        registered_at TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER,
        to_user_id INTEGER,
        to_link_code TEXT,
        text TEXT,
        timestamp TEXT,
        is_read INTEGER DEFAULT 0,
        reply_to_id INTEGER DEFAULT NULL
    )
''')

try:
    cursor.execute("ALTER TABLE messages ADD COLUMN reply_to_id INTEGER DEFAULT NULL")
except:
    pass

conn.commit()

def generate_link_code():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        cursor.execute("SELECT 1 FROM users WHERE link_code = ?", (code,))
        if not cursor.fetchone():
            return code

def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📋 Моя ссылка"), KeyboardButton("📬 Полученные")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_user_info(telegram_id):
    cursor.execute("SELECT name, username FROM users WHERE telegram_id = ?", (telegram_id,))
    result = cursor.fetchone()
    if result:
        return result[0], result[1]
    return None, None

def extract_code_from_link(text):
    match = re.search(r'[?&]start=([A-Z0-9]+)', text)
    if match:
        return match.group(1)
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    target_code = args[0] if args else None
    user_id = update.effective_user.id

    cursor.execute("SELECT link_code FROM users WHERE telegram_id = ?", (user_id,))
    existing_user = cursor.fetchone()

    if target_code:
        cursor.execute("SELECT name, telegram_id FROM users WHERE link_code = ?", (target_code,))
        target_user = cursor.fetchone()

        if target_user:
            context.user_data['reply_to_code'] = target_code
            context.user_data['reply_to_user_id'] = target_user[1]
            await update.message.reply_text(
                "📝 Напиши сообщение. Оно будет отправлено анонимно.",
                reply_markup=None
            )
            return

    if not existing_user:
        link_code = generate_link_code()
        cursor.execute('''
            INSERT INTO users (telegram_id, link_code, name, username, registered_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, link_code, update.effective_user.first_name, update.effective_user.username, datetime.now().isoformat()))
        conn.commit()

        bot_username = (await context.bot.get_me()).username
        profile_link = f"https://t.me/{bot_username}?start={link_code}"

        await update.message.reply_text(
            f"🔐 Твоя ссылка для анонимных сообщений:\n`{profile_link}`\n\n"
            f"Вставь её в профиль. Любой, кто перейдёт, сможет написать тебе.\n"
            f"Или просто отправь ссылку другу в чат — бот сам предложит написать анонимку.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await main_menu(update, context)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT link_code FROM users WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()

    if user:
        bot_username = (await context.bot.get_me()).username
        profile_link = f"https://t.me/{bot_username}?start={user[0]}"
        await update.message.reply_text(
            f"📎 Твоя ссылка: `{profile_link}`\n\n"
            f"Вставь её в профиль, чтобы получать анонимные сообщения.\n\n"
            f"📌 Или отправь анонимку:\n"
            f"• по команде: `/send @username Текст`\n"
            f"• или просто скинь ссылку друга в этот чат",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "Нажми /start чтобы получить ссылку.",
            reply_markup=get_main_keyboard()
        )

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Использование: `/send @username Текст сообщения`\n\n"
            "Пример: `/send @petrov Привет! Это анонимка.`",
            parse_mode="Markdown"
        )
        return

    target_username = context.args[0]
    if target_username.startswith('@'):
        target_username = target_username[1:]

    message_text = ' '.join(context.args[1:])

    cursor.execute("SELECT telegram_id, link_code FROM users WHERE username = ?", (target_username,))
    target = cursor.fetchone()

    if not target:
        await update.message.reply_text(f"❌ Пользователь @{target_username} не найден.\n\nВозможно, он ещё не запускал бота.")
        return

    await send_anonymous_message(update, context, user.id, target[0], target[1], message_text)

async def send_anonymous_message(update, context, from_user_id, to_user_id, to_link_code, message_text):
    cursor.execute('''
        INSERT INTO messages (from_user_id, to_user_id, to_link_code, text, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (from_user_id, to_user_id, to_link_code, message_text, datetime.now().isoformat()))
    conn.commit()

    msg_id = cursor.lastrowid
    keyboard = [[InlineKeyboardButton("💬 Ответить", callback_data=f"reply_to_{msg_id}")]]

    try:
        await context.bot.send_message(
            chat_id=to_user_id,
            text=f"🔔 Новое анонимное сообщение\n\n{message_text}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        pass

    sender_name, sender_username = get_user_info(from_user_id)
    target_name, target_username = get_user_info(to_user_id)

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🔔 Анонимка\n"
                    f"От: {sender_name} (@{sender_username or 'нет'})\n"
                    f"Кому: {target_name} (@{target_username or 'нет'})\n"
                    f"Текст: {message_text}"
                )
            )
        except:
            pass

    if isinstance(update, Update):
        await update.message.reply_text("✅ Анонимка отправлена.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message_text = update.message.text

    if message_text == "📋 Моя ссылка":
        await my_link(update, context)
        return
    elif message_text == "📬 Полученные":
        await inbox_command(update, context)
        return
    elif message_text == "❓ Помощь":
        await help_command(update, context)
        return

    code = extract_code_from_link(message_text)
    if code:
        cursor.execute("SELECT name, telegram_id FROM users WHERE link_code = ?", (code,))
        target_user = cursor.fetchone()
        if target_user:
            context.user_data['reply_to_code'] = code
            context.user_data['reply_to_user_id'] = target_user[1]
            await update.message.reply_text(
                f"🔗 Ты хочешь написать анонимно пользователю *{target_user[0]}*.\n\n"
                f"📝 Напиши своё сообщение:",
                parse_mode="Markdown"
            )
            return
        else:
            await update.message.reply_text("❌ Ссылка недействительна. Попробуй другую.")
            return

    reply_to_user_id = context.user_data.get('reply_to_user_id')
    reply_to_msg_id = context.user_data.get('reply_to_msg_id')

    if reply_to_user_id and reply_to_msg_id:
        try:
            cursor.execute("SELECT from_user_id, text, to_link_code FROM messages WHERE id = ?", (reply_to_msg_id,))
            original = cursor.fetchone()

            if original:
                original_sender_id = original[0]
                original_text = original[1]

                keyboard = [[InlineKeyboardButton("💬 Ответить", callback_data=f"reply_to_{reply_to_msg_id}")]]

                await context.bot.send_message(
                    chat_id=reply_to_user_id,
                    text=f"🔔 Ответ\n\nТвой вопрос:\n{original_text[:100]}\n\nОтвет:\n{message_text}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

                cursor.execute('''
                    INSERT INTO messages (from_user_id, to_user_id, to_link_code, text, timestamp, reply_to_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user.id, original_sender_id, original[2], message_text, datetime.now().isoformat(), reply_to_msg_id))
                conn.commit()

                sender_name, sender_username = get_user_info(user.id)
                target_name, target_username = get_user_info(original_sender_id)

                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"🔄 Ответ\nОт: {sender_name} (@{sender_username or 'нет'})\nКому: {target_name} (@{target_username or 'нет'})\nТекст: {message_text}"
                        )
                    except:
                        pass

                await update.message.reply_text("✅ Ответ отправлен.")

                context.user_data.pop('reply_to_user_id', None)
                context.user_data.pop('reply_to_msg_id', None)
                return
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
            return

    target_code = context.user_data.get('reply_to_code')
    target_user_id = context.user_data.get('reply_to_user_id')

    if target_code and target_user_id:
        cursor.execute('''
            INSERT INTO messages (from_user_id, to_user_id, to_link_code, text, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, target_user_id, target_code, message_text, datetime.now().isoformat()))
        conn.commit()

        msg_id = cursor.lastrowid
        keyboard = [[InlineKeyboardButton("💬 Ответить", callback_data=f"reply_to_{msg_id}")]]

        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🔔 Новое сообщение\n\n{message_text}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            pass

        sender_name, sender_username = get_user_info(user.id)
        target_name, target_username = get_user_info(target_user_id)

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 Сообщение\nОт: {sender_name} (@{sender_username or 'нет'})\nКому: {target_name} (@{target_username or 'нет'})\nТекст: {message_text}"
                )
            except:
                pass

        await update.message.reply_text("✅ Отправлено.")
        context.user_data.pop('reply_to_code', None)
        context.user_data.pop('reply_to_user_id', None)
    else:
        await main_menu(update, context)

async def my_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT link_code FROM users WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()

    if user:
        bot_username = (await context.bot.get_me()).username
        profile_link = f"https://t.me/{bot_username}?start={user[0]}"
        await update.message.reply_text(
            f"📎 Твоя ссылка:\n`{profile_link}`\n\n"
            f"📌 Отправь её другу — бот сам предложит написать тебе анонимку.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Напиши /start чтобы получить ссылку.")

async def inbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT link_code FROM users WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        await update.message.reply_text("Напиши /start чтобы получить ссылку.")
        return

    user_code = user[0]

    cursor.execute('''
        SELECT id, text, timestamp 
        FROM messages 
        WHERE to_link_code = ? 
        ORDER BY timestamp DESC
    ''', (user_code,))

    messages = cursor.fetchall()

    if not messages:
        await update.message.reply_text("📭 Нет сообщений.")
        return

    for msg in messages:
        cursor.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (msg[0],))
    conn.commit()

    response = f"📬 Получено сообщений: {len(messages)}\n\n"
    for i, msg in enumerate(messages[:10], 1):
        response += f"{i}. {msg[2][:16]}\n   {msg[1][:150]}\n\n"

    await update.message.reply_text(response)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Как это работает\n\n"
        "1. Получи свою ссылку через /start\n"
        "2. Вставь ссылку в профиль — и тебе смогут писать анонимно\n"
        "3. Или отправь анонимку сам:\n"
        "   • по команде: `/send @username Текст`\n"
        "   • или просто скинь ссылку друга в этот чат\n"
        "4. На полученные сообщения можно ответить кнопкой «Ответить»\n"
        "5. Все ответы тоже анонимны",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("reply_to_"):
        original_msg_id = int(data.split("_")[2])
        context.user_data['reply_to_msg_id'] = original_msg_id

        cursor.execute("SELECT from_user_id FROM messages WHERE id = ?", (original_msg_id,))
        msg = cursor.fetchone()
        if msg:
            context.user_data['reply_to_user_id'] = msg[0]
            await query.edit_message_text("✏️ Напиши ответ:")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Недостаточно прав")
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM messages")
    messages = cursor.fetchone()[0]

    await update.message.reply_text(f"📊 Пользователей: {users}\nСообщений: {messages}")

def main():
    while True:
        try:
            app = (
                Application.builder()
                .token(BOT_TOKEN)
                .connect_timeout(30)
                .read_timeout(30)
                .write_timeout(30)
                .pool_timeout(30)
                .build()
            )
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("inbox", inbox_command))
            app.add_handler(CommandHandler("stats", admin_stats))
            app.add_handler(CommandHandler("help", help_command))
            app.add_handler(CommandHandler("send", send_command))
            app.add_handler(CallbackQueryHandler(button_handler))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

            print("🤖 Анонимный бот запущен!")
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            print("🔄 Перезапуск через 5 секунд...")
            time.sleep(5)

if __name__ == "__main__":
    main()