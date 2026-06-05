import json
import os
import google.generativeai as genai
from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from datetime import datetime, timedelta

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "6783929725:AAGwXMTRMvsJQG1Lw1MT9J_iWwm5z2ZK8Os"
GEMINI_KEY = "AQ.Ab8RN6K9MHvmBOfjr7T-1LIidvaSD1ZWi8qFxZ7VnzhzMOXtnw"

# Файл где хранятся модераторы (сохраняется на диске)
MODS_FILE = "moderators.json"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

SYSTEM = """Ты — Модерэндер 3.0, умный и немного строгий помощник Telegram-чата.
Отвечай кратко, по делу, на русском языке. Можешь иногда пошутить."""


# ==================== ХРАНЕНИЕ МОДЕРАТОРОВ ====================

def load_mods():
    """Загружаем список модераторов из файла"""
    if os.path.exists(MODS_FILE):
        with open(MODS_FILE, "r") as f:
            return json.load(f)
    return {}  # {chat_id: [user_id, user_id, ...]}

def save_mods(mods):
    """Сохраняем список модераторов в файл"""
    with open(MODS_FILE, "w") as f:
        json.dump(mods, f)

moderators = load_mods()


# ==================== ПРОВЕРКА ПРАВ ====================

async def is_creator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Только создатель чата (owner)"""
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    if member.status != "creator":
        await update.message.reply_text("❌ Только создатель чата может это делать.")
        return False
    return True

async def is_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Модератор назначенный через бота ИЛИ создатель чата"""
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id

    # Создатель всегда может всё
    member = await context.bot.get_chat_member(
        update.effective_chat.id, user_id
    )
    if member.status == "creator":
        return True

    # Проверяем список модераторов бота
    if chat_id in moderators and user_id in moderators[chat_id]:
        return True

    await update.message.reply_text(
        "❌ У тебя нет прав модератора.\n"
        "Попроси создателя чата выдать их командой /addmod @username"
    )
    return False

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем цель команды — по ответу или по @username"""
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        username = context.args[0].replace("@", "")
        try:
            member = await context.bot.get_chat_member(
                update.effective_chat.id, f"@{username}"
            )
            return member.user
        except:
            await update.message.reply_text("❌ Пользователь не найден")
    else:
        await update.message.reply_text(
            "❌ Укажи @username или ответь на сообщение пользователя"
        )
    return None


# ==================== УПРАВЛЕНИЕ МОДЕРАТОРАМИ (только создатель) ====================

async def addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addmod @username — выдать статус модератора"""
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
        f"✅ {user.first_name} назначен модератором Модерэндера 3.0.\n"
        f"Теперь он может использовать команды модерации."
    )

async def removemod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/removemod @username — снять статус модератора"""
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
    """/modlist — список всех модераторов чата"""
    if not await is_creator(update, context):
        return

    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators or not moderators[chat_id]:
        await update.message.reply_text("📋 Модераторов пока нет. Назначь через /addmod @username")
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
    """/ban @username — бан навсегда"""
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(
            f"🔨 Модерэндер 3.0 заблокировал {user.first_name} навсегда."
        )

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/kick @username — кик (может вернуться)"""
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"👢 {user.first_name} кикнут. Может вернуться по ссылке.")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mute @username [минуты] — мут (по умолч. 60 мин)"""
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    minutes = 60
    if context.args and len(context.args) > 1:
        try:
            minutes = int(context.args[1])
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
    """/unmute @username — снять мут"""
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
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

warns = {}

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/warn @username — предупреждение (3 = бан)"""
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        uid = user.id
        warns[uid] = warns.get(uid, 0) + 1
        count = warns[uid]
        if count >= 3:
            await context.bot.ban_chat_member(update.effective_chat.id, uid)
            await update.message.reply_text(
                f"🔨 {user.first_name} получил 3-е предупреждение и заблокирован Модерэндером 3.0."
            )
            warns[uid] = 0
        else:
            await update.message.reply_text(
                f"⚠️ Предупреждение {count}/3 для {user.first_name}."
            )

async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unwarn @username — снять предупреждение"""
    if not await is_moderator(update, context):
        return
    user = await get_target(update, context)
    if user:
        warns[user.id] = max(0, warns.get(user.id, 0) - 1)
        await update.message.reply_text(
            f"✅ Предупреждение снято с {user.first_name}. Сейчас: {warns[user.id]}/3"
        )

async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pin — закрепить (ответь на сообщение)"""
    if not await is_moderator(update, context):
        return
    if update.message.reply_to_message:
        await context.bot.pin_chat_message(
            update.effective_chat.id,
            update.message.reply_to_message.message_id
        )
        await update.message.reply_text("📌 Закреплено Модерэндером 3.0.")
    else:
        await update.message.reply_text("❌ Ответь на сообщение которое хочешь закрепить.")

async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unpin — открепить все сообщения"""
    if not await is_moderator(update, context):
        return
    await context.bot.unpin_all_chat_messages(update.effective_chat.id)
    await update.message.reply_text("📌 Все закреплённые сообщения откреплены.")

async def ro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ro — чат только для чтения"""
    if not await is_moderator(update, context):
        return
    await context.bot.set_chat_permissions(
        update.effective_chat.id,
        ChatPermissions(can_send_messages=False)
    )
    await update.message.reply_text("🔒 Чат переведён в режим только чтения.")

async def rw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rw — открыть чат для всех"""
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
    user_text = update.message.text
    try:
        response = model.generate_content(f"{SYSTEM}\n\nПользователь: {user_text}")
        await update.message.reply_text(response.text)
    except Exception:
        await update.message.reply_text("⚙️ Модерэндер временно думает... попробуй позже.")


# ==================== СТАРТ И ПОМОЩЬ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я *Модерэндер 3.0*\n\n"
        "🔑 *Создатель чата* может назначать модераторов через /addmod\n"
        "👮 *Модераторы* могут банить, мутить и управлять чатом\n"
        "💬 *Все остальные* могут общаться со мной как с ИИ\n\n"
        "Напиши /help для списка команд.",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Модерэндер 3.0 — Команды:*\n\n"

        "👑 *Только создатель чата:*\n"
        "/addmod @user — назначить модератора\n"
        "/removemod @user — снять модератора\n"
        "/modlist — список модераторов\n\n"

        "👮 *Модераторы и создатель:*\n"
        "/ban @user — бан навсегда\n"
        "/kick @user — кик (может вернуться)\n"
        "/mute @user [мин] — мут (по умолч. 60 мин)\n"
        "/unmute @user — снять мут\n"
        "/warn @user — предупреждение (3 = бан)\n"
        "/unwarn @user — снять предупреждение\n"
        "/pin — закрепить (ответь на сообщение)\n"
        "/unpin — открепить все\n"
        "/ro — чат только чтение\n"
        "/rw — открыть чат\n\n"

        "💬 *Для всех:*\n"
        "Просто напиши сообщение — Модерэндер ответит как ИИ!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ==================== ЗАПУСК ====================

app = ApplicationBuilder().token(BOT_TOKEN).build()

# Создатель
app.add_handler(CommandHandler("addmod", addmod))
app.add_handler(CommandHandler("removemod", removemod))
app.add_handler(CommandHandler("modlist", modlist))

# Модерация
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

# Общее
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply))

print("✅ Модерэндер 3.0 запущен!")
app.run_polling()
