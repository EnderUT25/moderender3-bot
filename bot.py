import json
import os
import threading
import random
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta
from collections import deque

from google import genai
from telegram import Update, ChatPermissions, ReactionTypeEmoji
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_KEY = os.getenv("GEMINI_KEY", "")

MODS_FILE = "moderators.json"

ai_client = genai.Client(api_key=GEMINI_KEY)

SYSTEM = """Ты — Модерэндер 3.0, умный и немного строгий помощник Telegram-чата.
Отвечай кратко, по делу, на русском языке, можешь шутить. Ты прикольный такой, душа компании, шаришь за интернет мемы. Ты админ Эндер Крутого чата, твой создатель @EnderUT25 или Эндер или Тимур Чубов это всё он
Ты помнишь историю переписки и учитываешь контекст при ответе."""

warns = {}

# ==================== ИСТОРИЯ ЧАТА ====================
# Храним историю для каждого чата: последние 50 сообщений за последние 2 часа
HISTORY_LIMIT = 50       # максимум сообщений
HISTORY_TTL = 120        # минут (2 часа)

chat_history = {}  # {chat_id: deque([(datetime, username, text), ...])}

def add_to_history(chat_id: int, username: str, text: str):
    cid = str(chat_id)
    if cid not in chat_history:
        chat_history[cid] = deque(maxlen=HISTORY_LIMIT)

    # Чистим старые сообщения
    cutoff = datetime.now() - timedelta(minutes=HISTORY_TTL)
    while chat_history[cid] and chat_history[cid][0][0] < cutoff:
        chat_history[cid].popleft()

    chat_history[cid].append((datetime.now(), username, text))

def get_history_text(chat_id: int) -> str:
    cid = str(chat_id)
    if cid not in chat_history or not chat_history[cid]:
        return ""

    cutoff = datetime.now() - timedelta(minutes=HISTORY_TTL)
    lines = []
    for ts, uname, text in chat_history[cid]:
        if ts >= cutoff:
            lines.append(f"{uname}: {text}")

    if not lines:
        return ""

    return "История чата за последние 2 часа:\n" + "\n".join(lines) + "\n\n"

# ==================== РЕАКЦИИ ====================
# Все реакции которые поддерживает Telegram
REACTIONS = [
    "👍", "👎", "❤️", "🔥", "🥰", "👏", "😁", "🤔",
    "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩",
    "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳",
    "❤️‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆",
    "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈",
    "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈",
    "😇", "😨", "🤝", "✍️", "🤗", "🫡", "🎅", "🎄",
    "☃️", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄",
]

# Шанс поставить реакцию (1 = 100%, 0.3 = 30%)
REACTION_CHANCE = 0.3

async def maybe_react(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайно ставит реакцию на сообщение"""
    if random.random() > REACTION_CHANCE:
        return
    try:
        emoji = random.choice(REACTIONS)
        await context.bot.set_message_reaction(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)]
        )
    except Exception:
        pass  # Молча игнорируем если реакция не поддерживается

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
    await update.message.reply_text(f"✅ {user.first_name} назначен модератором Модерэндера 3.0.")

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

    lines = ["📋 *Модераторы Эндер Крутого Чата:*\n"]
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

# ==================== ИИ + ИСТОРИЯ + РЕАКЦИИ ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    username = update.effective_user.first_name or "Пользователь"
    text = update.message.text

    # Сохраняем каждое сообщение в историю
    add_to_history(update.effective_chat.id, username, text)

    # Ставим случайную реакцию на любое сообщение
    await maybe_react(update, context)

    # Отвечаем только если упомянули бота или ответили на его сообщение
    bot = context.bot
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

    # Формируем запрос с историей
    history = get_history_text(update.effective_chat.id)
    prompt = f"{SYSTEM}\n\n{history}Пользователь {username}: {user_text}"

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        reply = response.text
        # Сохраняем ответ бота в историю
        add_to_history(update.effective_chat.id, "Модерэндер 3.0", reply)
        await update.message.reply_text(reply)
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        await update.message.reply_text("⚙️ Модерэндер временно думает... попробуй позже.")

# ==================== СТАРТ И ПОМОЩЬ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я *Модерэндер 3.0*\n\n"
        "👑 Создатель чата назначает модераторов через /addmod\n"
        "👮 Модераторы управляют чатом\n"
        "💬 Упомяни меня @бот или ответь на моё сообщение — отвечу как ИИ\n"
        "😄 Иногда ставлю реакции на сообщения\n"
        "🧠 Помню историю чата за последние 2 часа\n\n"
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
        "Упомяни @бот или ответь на моё сообщение\n"
        "🧠 Помню историю чата за 2 часа\n"
        "😄 Ставлю реакции на сообщения (30% шанс)"
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
        pass

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    print("🌐 HTTP-сервер запущен")

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Модерэндер 3.0 успешно запущен!")
    app.run_polling()
