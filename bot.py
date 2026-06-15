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
DATA_FILE = "data.json"

ai_client = genai.Client(api_key=GEMINI_KEY)

SYSTEM = """Ты — Модерэндер 3.0, умный и немного строгий помощник Telegram-чата.
Отвечай кратко, по делу, на русском языке, можешь шутить. Ты прикольный такой, душа компании, шаришь за интернет мемы. Ты админ Эндер Крутого чата, твой создатель @EnderUT25 или Эндер или Тимур Чубов это всё он
Ты помнишь историю переписки и учитываешь контекст при ответе."""

SYSTEM_RP = """Ты — мастер ролевых игр Модерэндер 3.0. Ты описываешь действия между персонажами
красочно и атмосферно. Пиши в третьем лице, от 2 до 4 предложений. На русском языке."""

SYSTEM_RP_18 = """Ты — мастер ролевых игр Модерэндер 3.0 для взрослой аудитории.
Описывай действия между персонажами откровенно и красочно, без цензуры.
Пиши в третьем лице, от 2 до 4 предложений. На русском языке."""

warns = {}

# ==================== ПРАВИЛА ЧАТА ====================
RULES = """
📋 *Правила Эндер Крутого Чата*

1️⃣ Надо хуесосить Лоялети
2️⃣ Если не хотите хуесосить Лоялети, то читайте п. 1
3️⃣ Реклама и ссылки только с разрешением
4️⃣ Соблюдаем законодательство РФ, не публикуем экстремизм
5️⃣ Слушаемся модераторов с первого раза

_Владелец: @EnderUT25_
"""

# ==================== ЗВАНИЯ ====================
# Звание Эндердракона выдаётся только конкретному человеку (владелец чата)
OWNER_USERNAME = "EnderUT25"
RANK_OWNER = "Эндердракон"
RANK_DEPUTY = "Депутат ЭНР"
RANK_MEMBER = "Энровец"

# ==================== ИСТОРИЯ ЧАТА ====================
HISTORY_LIMIT = 50
HISTORY_TTL = 120

chat_history = {}

def add_to_history(chat_id: int, username: str, text: str):
    cid = str(chat_id)
    if cid not in chat_history:
        chat_history[cid] = deque(maxlen=HISTORY_LIMIT)
    cutoff = datetime.now() - timedelta(minutes=HISTORY_TTL)
    while chat_history[cid] and chat_history[cid][0][0] < cutoff:
        chat_history[cid].popleft()
    chat_history[cid].append((datetime.now(), username, text))

def get_history_text(chat_id: int) -> str:
    cid = str(chat_id)
    if cid not in chat_history or not chat_history[cid]:
        return ""
    cutoff = datetime.now() - timedelta(minutes=HISTORY_TTL)
    lines = [f"{u}: {t}" for ts, u, t in chat_history[cid] if ts >= cutoff]
    return ("История чата за последние 2 часа:\n" + "\n".join(lines) + "\n\n") if lines else ""

# ==================== РЕАКЦИИ ====================
REACTIONS = [
    "👍","👎","❤️","🔥","🥰","👏","😁","🤔","🤯","😱",
    "🤬","😢","🎉","🤩","🤮","💩","🙏","👌","🕊","🤡",
    "🥱","🥴","😍","🐳","❤️‍🔥","🌚","🌭","💯","🤣","⚡",
    "🍌","🏆","💔","🤨","😐","🍓","🍾","💋","😈","😴",
    "😭","🤓","👻","👀","🎃","🙈","😇","😨","🤝","✍️",
    "🤗","🫡","🎅","💅","🤪","🗿","🆒","💘","🙉","🦄",
]
REACTION_CHANCE = 0.3

async def maybe_react(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        pass

# ==================== ХРАНЕНИЕ ДАННЫХ ====================

def load_mods():
    if os.path.exists(MODS_FILE):
        with open(MODS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_mods(mods):
    with open(MODS_FILE, "w") as f:
        json.dump(mods, f)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}
    # Структура: {chat_id: {user_id: {warns, msg_count, custom_rank, awards: []}}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

moderators = load_mods()
data = load_data()

def get_user_data(chat_id, user_id):
    cid, uid = str(chat_id), str(user_id)
    if cid not in data:
        data[cid] = {}
    if uid not in data[cid]:
        data[cid][uid] = {"warns": 0, "msg_count": 0, "custom_rank": None, "awards": []}
    if "awards" not in data[cid][uid]:
        data[cid][uid]["awards"] = []
    return data[cid][uid]

def get_display_rank(chat_id, user, ud):
    """Определяет звание: Эндердракон > кастомное > Депутат/Энровец"""
    if user.username and user.username.lower() == OWNER_USERNAME.lower():
        return RANK_OWNER
    if ud.get("custom_rank"):
        return ud["custom_rank"]
    chat_id_str = str(chat_id)
    if chat_id_str in moderators and user.id in moderators[chat_id_str]:
        return RANK_DEPUTY
    return RANK_MEMBER

# ==================== ПОЛУЧЕНИЕ ЦЕЛИ (тег или реплай) ====================

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await update.message.reply_text("❌ Пользователь не найден. Проверь @username.")
            return None
    await update.message.reply_text(
        "❌ Укажи цель: ответь (Reply) на сообщение или напиши /команда @username"
    )
    return None

# ==================== ПРОВЕРКА ПРАВ ====================

async def is_creator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    if member.status != "creator":
        await update.message.reply_text("❌ Только Эндердракон может это делать.")
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
    )
    return False

# ==================== УПРАВЛЕНИЕ МОДЕРАТОРАМИ ====================

async def addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_creator(update, context): return
    user = await get_target(update, context)
    if not user: return
    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators:
        moderators[chat_id] = []
    if user.id in moderators[chat_id]:
        await update.message.reply_text(f"ℹ️ {user.first_name} уже {RANK_DEPUTY}.")
        return
    moderators[chat_id].append(user.id)
    save_mods(moderators)
    await update.message.reply_text(f"✅ {user.first_name} назначен {RANK_DEPUTY}!")

async def removemod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_creator(update, context): return
    user = await get_target(update, context)
    if not user: return
    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators or user.id not in moderators[chat_id]:
        await update.message.reply_text(f"ℹ️ {user.first_name} не является {RANK_DEPUTY}.")
        return
    moderators[chat_id].remove(user.id)
    save_mods(moderators)
    await update.message.reply_text(f"🗑 Звание {RANK_DEPUTY} снято с {user.first_name}.")

async def modlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_creator(update, context): return
    chat_id = str(update.effective_chat.id)
    if chat_id not in moderators or not moderators[chat_id]:
        await update.message.reply_text("📋 Депутатов ЭНР пока нет. Назначь через /addmod")
        return
    lines = ["📋 *Депутаты ЭНР:*\n"]
    for uid in moderators[chat_id]:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, uid)
            uname = f"@{m.user.username}" if m.user.username else ""
            lines.append(f"• {m.user.first_name} {uname}")
        except:
            lines.append(f"• ID: {uid} (покинул чат)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ==================== КОМАНДЫ МОДЕРАЦИИ ====================

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    if user:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"🔨 {user.first_name} заблокирован навсегда.")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    if user:
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"👢 {user.first_name} кикнут. Может вернуться.")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    minutes = 60
    args = context.args or []
    for a in args:
        try:
            minutes = int(a)
            break
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
    if not await is_moderator(update, context): return
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
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    if user:
        ud = get_user_data(update.effective_chat.id, user.id)
        ud["warns"] += 1
        count = ud["warns"]
        save_data(data)
        if count >= 3:
            await context.bot.ban_chat_member(update.effective_chat.id, user.id)
            await update.message.reply_text(f"🔨 {user.first_name} получил 3 предупреждения и заблокирован.")
            ud["warns"] = 0
            save_data(data)
        else:
            await update.message.reply_text(f"⚠️ Предупреждение {count}/3 для {user.first_name}.")

async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    if user:
        ud = get_user_data(update.effective_chat.id, user.id)
        ud["warns"] = max(0, ud["warns"] - 1)
        save_data(data)
        await update.message.reply_text(f"✅ Предупреждение снято с {user.first_name}. Сейчас: {ud['warns']}/3")

async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
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
    if not await is_moderator(update, context): return
    await context.bot.unpin_all_chat_messages(update.effective_chat.id)
    await update.message.reply_text("📌 Все закреплённые сообщения откреплены.")

async def ro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
    await context.bot.set_chat_permissions(update.effective_chat.id, ChatPermissions(can_send_messages=False))
    await update.message.reply_text("🔒 Чат переведён в режим только чтения.")

async def rw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_moderator(update, context): return
    await context.bot.set_chat_permissions(
        update.effective_chat.id,
        ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                        can_send_other_messages=True, can_add_web_page_previews=True)
    )
    await update.message.reply_text("🔓 Чат снова открыт для всех.")

# ==================== ЗВАНИЯ (кастомные) ====================

async def setrank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setrank @user Звание — выдать кастомное звание"""
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    if not user: return

    args = context.args or []
    rank_parts = [a for a in args if not a.startswith("@")]
    if not rank_parts:
        await update.message.reply_text("❌ Укажи звание: /setrank @user Моё Звание")
        return

    custom_rank = " ".join(rank_parts)
    ud = get_user_data(update.effective_chat.id, user.id)
    ud["custom_rank"] = custom_rank
    save_data(data)
    await update.message.reply_text(f"🏅 {user.first_name} получил звание: *{custom_rank}*", parse_mode="Markdown")

async def removerank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/removerank @user — убрать кастомное звание"""
    if not await is_moderator(update, context): return
    user = await get_target(update, context)
    if not user: return
    ud = get_user_data(update.effective_chat.id, user.id)
    ud["custom_rank"] = None
    save_data(data)
    new_rank = get_display_rank(update.effective_chat.id, user, ud)
    await update.message.reply_text(f"🗑 Звание снято. Текущее звание: *{new_rank}*", parse_mode="Markdown")

# ==================== НАГРАДЫ ====================

async def award_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реплай 'Наградить <текст>' — выдать награду пользователю"""
    if not await is_moderator(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответь на сообщение того, кого хочешь наградить.")
        return

    text = update.message.text
    # Убираем слово "Наградить" (с любым регистром) из начала
    award_text = text.split(None, 1)
    award_text = award_text[1].strip() if len(award_text) > 1 else ""

    if not award_text:
        await update.message.reply_text("❌ Укажи текст награды: ответь на сообщение и напиши 'Наградить <текст>'")
        return

    target = update.message.reply_to_message.from_user
    ud = get_user_data(update.effective_chat.id, target.id)
    ud["awards"].append(award_text)
    save_data(data)

    await update.message.reply_text(
        f"🏆 {target.first_name} получает награду: *{award_text}*!",
        parse_mode="Markdown"
    )

# ==================== ПРОФИЛЬ / КТО Я / КТО ТЫ ====================

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user):
    chat_id = update.effective_chat.id
    ud = get_user_data(chat_id, target_user.id)
    rank = get_display_rank(chat_id, target_user, ud)
    msg_count = ud.get("msg_count", 0)
    warns_count = ud.get("warns", 0)
    awards = ud.get("awards", [])

    uname = f"@{target_user.username}" if target_user.username else "—"

    text = (
        f"👤 *{target_user.first_name}*\n"
        f"🔖 Username: {uname}\n"
        f"🏅 Звание: {rank}\n"
        f"💬 Сообщений: {msg_count}\n"
        f"⚠️ Предупреждения: {warns_count}/3\n"
    )

    if awards:
        text += "\n🏆 *Награды:*\n"
        for a in awards:
            text += f"• {a}\n"
    else:
        text += "\n🏆 Наград пока нет\n"

    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== ПРАВИЛА ====================

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES, parse_mode="Markdown")

# ==================== РОЛЕВЫЕ КОМАНДЫ ====================

async def rp_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, is_18: bool = False):
    user1 = update.effective_user.first_name

    user2 = None
    if update.message.reply_to_message:
        user2 = update.message.reply_to_message.from_user.first_name
    elif context.args:
        username = context.args[0].replace("@", "")
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, f"@{username}")
            user2 = m.user.first_name
        except:
            user2 = context.args[0]

    if not user2:
        await update.message.reply_text("❌ Укажи цель: ответь на сообщение или /команда @username")
        return

    prompt = f"{'Эротическая р' if is_18 else 'Р'}олевая сцена: {user1} {action} {user2}. Опиши это."
    system = SYSTEM_RP_18 if is_18 else SYSTEM_RP

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=f"{system}\n\n{prompt}"
        )
        await update.message.reply_text(f"🎭 {response.text}")
    except Exception as e:
        print(f"Ошибка RP: {e}")
        await update.message.reply_text("⚙️ Не удалось создать сцену, попробуй позже.")

async def rp_hug(update, context): await rp_command(update, context, "нежно обнимает")
async def rp_kiss(update, context): await rp_command(update, context, "целует")
async def rp_slap(update, context): await rp_command(update, context, "даёт пощёчину")
async def rp_pat(update, context): await rp_command(update, context, "гладит по голове")
async def rp_poke(update, context): await rp_command(update, context, "тычет пальцем в")
async def rp_bite(update, context): await rp_command(update, context, "кусает")
async def rp_kill(update, context): await rp_command(update, context, "драматично убивает")
async def rp_marry(update, context): await rp_command(update, context, "делает предложение руки и сердца")
async def rp_fight(update, context): await rp_command(update, context, "вступает в эпическую битву с")
async def rp_cuddle(update, context): await rp_command(update, context, "уютно обнимается с")

async def rp_sex(update, context): await rp_command(update, context, "занимается любовью с", is_18=True)
async def rp_flirt(update, context): await rp_command(update, context, "откровенно флиртует с", is_18=True)
async def rp_spank(update, context): await rp_command(update, context, "шлёпает", is_18=True)

# ==================== ИИ + ИСТОРИЯ + РЕАКЦИИ + ТЕКСТОВЫЕ КОМАНДЫ ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    username = update.effective_user.first_name or "Пользователь"
    text = update.message.text
    text_lower = text.strip().lower()

    # ---------- Считаем сообщения ----------
    ud = get_user_data(update.effective_chat.id, update.effective_user.id)
    ud["msg_count"] = ud.get("msg_count", 0) + 1
    save_data(data)

    # ---------- История и реакция ----------
    add_to_history(update.effective_chat.id, username, text)
    await maybe_react(update, context)

    # ---------- "Правила" ----------
    if text_lower in ("правила", "правила!", "/правила"):
        await rules_command(update, context)
        return

    # ---------- "Наградить <текст>" (реплай) ----------
    if text_lower.startswith("наградить") and update.message.reply_to_message:
        await award_command(update, context)
        return

    # ---------- "Кто я" ----------
    if text_lower in ("кто я", "кто я?", "обо мне", "обо мне?"):
        await show_profile(update, context, update.effective_user)
        return

    # ---------- "Кто ты" (реплай на чьё-то сообщение) ----------
    if text_lower in ("кто ты", "кто ты?") and update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        await show_profile(update, context, target)
        return

    # ---------- ИИ ----------
    bot = context.bot
    is_mentioned = f"@{bot.username}" in text
    is_reply_to_bot = (
        update.message.reply_to_message is not None and
        update.message.reply_to_message.from_user.id == bot.id
    )
    is_mod_prefix = text_lower.startswith("мод")

    if not (is_mentioned or is_reply_to_bot or is_mod_prefix):
        return

    user_text = text.replace(f"@{bot.username}", "").strip()
    if is_mod_prefix and not is_mentioned:
        # Убираем слово "Мод" из начала
        parts = text.split(None, 1)
        user_text = parts[1].strip() if len(parts) > 1 else ""

    if not user_text:
        user_text = "Прокомментируй это."

    history = get_history_text(update.effective_chat.id)
    prompt = f"{SYSTEM}\n\n{history}Пользователь {username}: {user_text}"

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt
        )
        reply = response.text
        add_to_history(update.effective_chat.id, "Модерэндер 3.0", reply)
        await update.message.reply_text(reply)
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        await update.message.reply_text("⚙️ ВАШ МОДЕРЭНДЕР ПОМЕР")

# ==================== СТАРТ И ПОМОЩЬ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я *Модерэндер 3.0*\n\n"
        "👑 Эндердракон назначает депутатов через /addmod\n"
        "🎖 Депутаты ЭНР управляют чатом\n"
        "🎭 Ролевые команды для всех\n"
        "🏅 Звания и награды\n"
        "💬 Напиши «Мод ...», упомяни @бот или ответь мне\n\n"
        "/help — все команды",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Модерэндер 3.0*\n\n"
        "*@enderdrakon5*\n"
        "*@TimurChubov*\n\n"

        "📋 *Общее:*\n"
        "«Правила» — показать правила чата\n"
        "«Кто я» — твой профиль и звание\n"
        "«Кто ты» (Reply) — профиль другого участника\n\n"

        "👑 *ТОЛЬКО ЭНДЕРДРАКОН:*\n"
        "/addmod @user — назначить Депутата\n"
        "/removemod @user — снять звание\n"
        "/modlist — список депутатов\n\n"

        "🎖 *Команды для эндеровцев (депутаты + Эндердракон):*\n"
        "/ban @user — бан навсегда\n"
        "/kick @user — кик\n"
        "/mute @user [мин] — мут (60 мин по умолч.)\n"
        "/unmute @user — снять мут\n"
        "/warn @user — предупреждение (3=бан)\n"
        "/unwarn @user — снять предупреждение\n"
        "/pin — закрепить (Reply)\n"
        "/unpin — открепить все\n"
        "/ro — чат только чтение\n"
        "/rw — открыть чат\n"
        "/setrank @user Звание — выдать кастомное звание\n"
        "/removerank @user — убрать звание\n"
        "«Наградить <текст>» (Reply) — выдать награду\n\n"

        "🎭 *Ролевые (для всех):*\n"
        "/hug /kiss /slap /pat /poke /bite /kill /marry /fight /cuddle @user\n\n"

        "🔞 *18+ ролевые:*\n"
        "/sex /flirt /spank @user\n\n"

        "💬 *С Модерэндером можно попиздеть*\n"
        "Напиши «Мод ...», упомяни @бот или ответь на моё сообщение\n"
        "🧠 Помню историю чата за 2 часа\n"
        "😎 Ставлю реакции на сообщения"
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
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    print("🌐 HTTP-сервер запущен")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Управление модераторами
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

    # Звания
    app.add_handler(CommandHandler("setrank", setrank))
    app.add_handler(CommandHandler("removerank", removerank))

    # Ролевые
    app.add_handler(CommandHandler("hug", rp_hug))
    app.add_handler(CommandHandler("kiss", rp_kiss))
    app.add_handler(CommandHandler("slap", rp_slap))
    app.add_handler(CommandHandler("pat", rp_pat))
    app.add_handler(CommandHandler("poke", rp_poke))
    app.add_handler(CommandHandler("bite", rp_bite))
    app.add_handler(CommandHandler("kill", rp_kill))
    app.add_handler(CommandHandler("marry", rp_marry))
    app.add_handler(CommandHandler("fight", rp_fight))
    app.add_handler(CommandHandler("cuddle", rp_cuddle))
    app.add_handler(CommandHandler("sex", rp_sex))
    app.add_handler(CommandHandler("flirt", rp_flirt))
    app.add_handler(CommandHandler("spank", rp_spank))

    # Общее
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Модерэндер 3.0 успешно запущен!")
    app.run_polling()
