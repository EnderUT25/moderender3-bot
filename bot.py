import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

import google.generativeai as genai
from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_KEY = os.getenv("GEMINI_KEY", "")

MODS_FILE = "moderators.json"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

SYSTEM = """Ты — Модерэндер 3.0, умный и немного строгий помощник Telegram-чата.
Отвечай кратко, по делу, на русском языке. Можешь иногда пошутить."""

warns = {}

# ==================== ХРАНЕНИЕ МОДЕРАТОРОВ ====================

def load_mods():
    if os.path.exists(MODS_FILE):
        with open(MODS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_mods(mods):
    with open(MODS_FILE, "w") as f:
        json.dump(mods, f)

moderators = load_mods()

# ==================== ПРОВЕРКА ПРАВ ====================

async def is_creator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    if member.status != "creator":
        await update.message.reply_text("❌ Только создатель чата может это делать.")
        return False
    return True

async def is_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id

    member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
    if member.status == "creator":
        return True

    if chat_id in moderators and user_id in moderators[chat_id]:
        return True

    await update.message.reply_text(
        "❌ У тебя нет прав модератора.\n"
        "Попроси создателя чата выдать права — он должен ответить на твоё сообщение командой /addmod"
    )
    return False

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    await update.message.reply_text(
        "❌ Ответь (Reply) на сообщение пользователя, затем введи команду."
    )
    return None

# ==================== УПРАВЛЕНИЕ МОДЕРАТОРАМИ ====================

async def addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_creator(update, context):
        return
    user = await get_target(update, context)
    if not user:
        return

    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators:
        moderators[chat_id] = []

    if user.id in moderators[chat_id]:
        await update.message.reply_text(f"ℹ️ {user.first_name} уже является модератором.")
        return

    moderators[chat_id].append(user.id)
    save_mods(moderators)
    await update.message.reply_text(
        f"✅ {user.first_name} назначен модератором Модерэндера 3.0."
    )

async def removemod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_creator(update, context):
        return
    user = await get_target(update, context)
    if not user:
        return

    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators or user.id not in moderators[chat_id]:
        await update.message.reply_text(f"ℹ️ {user.first_name} не является модератором.")
        return

    moderators[chat_id].remove(user.id)
    save_mods(moderators)
    await update.message.reply_text(f"🗑 Статус модератора снят с {user.first_name}.")

async def modlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_creator(update, context):
        return

    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators or not moderators[chat_id]:
        await update.message.reply_text("📋 Модераторов пока нет. Ответь на чьё-то сообщение командой /addmod")
        return

    lines = ["📋 *Модераторы Модерэндера 3.0:*\n"]
    for uid in moderators[chat_id]:
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, uid)
            name = member.user.first_name
            username = f"@{member.user.username}" if member.user.username else ""
            lines.append(f"• {name} {username}")
        except:
            lines.append(f"• ID: {uid} (покинул чат)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ==================== КОМАНДЫ МОДЕРАЦИИ ====================

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"🔨 {user.first_name} заблокирован навсегда.")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"👢 {user.first_name} кикнут. Может вернуться.")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    minutes = 60
    if context.args:
        try:
            minutes = int(context.args[0])
        except:
            pass
    if user:
        until = datetime.now() + timedelta(minutes=minutes)
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(f"🔇 {user.first_name} замьючен на {minutes} мин.")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        try:
            await context.bot.restrict_chat_member(
                update.effective_chat.id, user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            await update.message.reply_text(f"🔊 {user.first_name} снова может писать.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        uid = user.id
        warns[uid] = warns.get(uid, 0) + 1
        count = warns[uid]
        if count >= 3:
            await context.bot.ban_chat_member(update.effective_chat.id, uid)
            await update.message.reply_text(f"🔨 {user.first_name} получил 3 предупреждения и заблокирован.")
            warns[uid] = 0
        else:
            await update.message.reply_text(f"⚠️ Предупреждение {count}/3 для {user.first_name}.")

async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        warns[user.id] = max(0, warns.get(user.id, 0) - 1)
        await update.message.reply_text(
            f"✅ Предупреждение снято с {user.first_name}. Сейчас: {warns[user.id]}/3"
        )

async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    if update.message.reply_to_message:
        try:
            await context.bot.pin_chat_message(
                update.effective_chat.id,
                update.message.reply_to_message.message_id
            )
            await update.message.reply_text("📌 Закреплено.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    else:
        await update.message.reply_text("❌ Ответь на сообщение которое хочешь закрепить.")

async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    await context.bot.unpin_all_chat_messages(update.effective_chat.id)
    await update.message.reply_text("📌 Все закреплённые сообщения откреплены.")

async def ro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    await context.bot.set_chat_permissions(
        update.effective_chat.id,
        ChatPermissions(can_send_messages=False)
    )
    await update.message.reply_text("🔒 Чат переведён в режим только чтения.")

async def rw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context):
        return
    await context.bot.set_chat_permissions(
        update.effective_chat.id,
        ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
    )
    await update.message.reply_text("🔓 Чат снова открыт для всех.")

# ==================== ИИ ====================

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    bot = context.bot
    text = update.message.text
    is_mentioned = f"@{bot.username}" in text
    is_reply_to_bot = (
        update.message.reply_to_message is not None and
        update.message.reply_to_message.from_user.id == bot.id
    )

    if not (is_mentioned or is_reply_to_bot):
        return

    user_text = text.replace(f"@{bot.username}", "").strip()
    if not user_text:
        user_text = "Прокомментируй это."

    try:
        response = model.generate_content(f"{SYSTEM}\n\nПользователь: {user_text}")
        await update.message.reply_text(response.text)
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        await update.message.reply_text("⚙️ Модерэндер временно думает... попробуй позже.")

# ==================== СТАРТ И ПОМОЩЬ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я *Модерэндер 3.0*\n\n"
        "👑 Создатель чата назначает модераторов через /addmod\n"
        "👮 Модераторы управляют чатом\n"
        "💬 Упомяни меня @бот или ответь на моё сообщение — отвечу как ИИ\n\n"
        "/help — список команд",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Модерэндер 3.0 — Команды:*\n\n"
        "👑 *Только создатель чата:*\n"
        "/addmod — назначить модератора (Reply)\n"
        "/removemod — снять модератора (Reply)\n"
        "/modlist — список модераторов\n\n"
        "👮 *Модераторы и создатель:*\n"
        "/ban — бан навсегда (Reply)\n"
        "/kick — кик (Reply)\n"
        "/mute [мин] — мут, по умолч. 60 мин (Reply)\n"
        "/unmute — снять мут (Reply)\n"
        "/warn — предупреждение, 3 = бан (Reply)\n"
        "/unwarn — снять предупреждение (Reply)\n"
        "/pin — закрепить (Reply)\n"
        "/unpin — открепить все\n"
        "/ro — чат только чтение\n"
        "/rw — открыть чат\n\n"
        "💬 *ИИ:*\n"
        "Упомяни @бот или ответь на моё сообщение"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== HTTP-СЕРВЕР ДЛЯ RENDER ====================

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Alive")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Отключаем спам в логах

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    print("🌐 HTTP-сервер запущен (для Render)")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("addmod", addmod))
    app.add_handler(CommandHandler("removemod", removemod))
    app.add_handler(CommandHandler("modlist", modlist))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("kick", kick))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("unwarn", unwarn))
    app.add_handler(CommandHandler("pin", pin))
    app.add_handler(CommandHandler("unpin", unpin))
    app.add_handler(CommandHandler("ro", ro))
    app.add_handler(CommandHandler("rw", rw))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply))

    print("✅ Модерэндер 3.0 успешно запущен!")
    app.run_polling()
