"""
============================================
TELEGRAM BOT - FULL FEATURED
Admin + User Panel | Supabase Backend
============================================
"""

import os
import random
import string
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
    ConversationHandler
)
from supabase import create_client, Client

# ============================================
# LOGGING
# ============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================
# ENV VARIABLES (Render me set karna)
# ============================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")  # service_role key use karo
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")    # comma separated: 123456,789012
CHANNEL_1 = os.environ.get("CHANNEL_1", "@your_channel1")
CHANNEL_2 = os.environ.get("CHANNEL_2", "@your_channel2")

ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]
REFERRAL_REWARD = 2.0   # ₹2 per referral
MIN_REDEEM = 10.0       # ₹10 minimum redeem

# ============================================
# SUPABASE CLIENT
# ============================================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# CONVERSATION STATES
# ============================================
(
    ADMIN_ADD_LINK_TITLE, ADMIN_ADD_LINK_URL,
    ADMIN_DELETE_LINK,
    ADMIN_ADD_BALANCE_CHATID, ADMIN_ADD_BALANCE_AMOUNT,
    ADMIN_USER_INFO_ID,
    USER_REDEEM_AMOUNT,
    ADMIN_REPLY_REDEEM,
) = range(8)


# ============================================
# HELPER FUNCTIONS
# ============================================

def generate_referral_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_IDS

async def check_channel_membership(bot, user_id: int) -> bool:
    """Check if user joined both channels"""
    try:
        for channel in [CHANNEL_1, CHANNEL_2]:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ["left", "kicked", "banned"]:
                return False
        return True
    except Exception as e:
        logger.error(f"Channel check error: {e}")
        return False

def get_user(chat_id: int):
    try:
        res = supabase.table("users").select("*").eq("chat_id", chat_id).single().execute()
        return res.data
    except:
        return None

def create_user(chat_id: int, username: str, full_name: str, referred_by=None):
    code = generate_referral_code()
    # Unique code check
    while True:
        existing = supabase.table("users").select("id").eq("referral_code", code).execute()
        if not existing.data:
            break
        code = generate_referral_code()

    data = {
        "chat_id": chat_id,
        "username": username or "",
        "full_name": full_name or "Unknown",
        "referred_by": referred_by,
        "referral_code": code,
        "balance": 0.0,
    }
    supabase.table("users").insert(data).execute()
    return get_user(chat_id)

def update_balance(chat_id: int, amount: float):
    user = get_user(chat_id)
    if user:
        new_bal = float(user["balance"]) + amount
        supabase.table("users").update({"balance": round(new_bal, 2)}).eq("chat_id", chat_id).execute()
        return new_bal
    return 0

def get_all_links():
    res = supabase.table("links").select("*").order("created_at", desc=True).execute()
    return res.data or []

def get_pending_redeems():
    res = supabase.table("redeem_requests").select("*, users(full_name, username)").eq("status", "pending").order("requested_at").execute()
    return res.data or []

def get_referral_stats(chat_id: int):
    res = supabase.table("referrals").select("*").eq("referrer_chat_id", chat_id).execute()
    return res.data or []

# ============================================
# KEYBOARDS
# ============================================

def admin_main_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Add Link", "🗑 Delete Link"],
        ["👥 User Refer Details", "💰 User Balance Add"],
        ["🎁 Redeem Requests", "👤 User Info"],
    ], resize_keyboard=True)

def user_main_keyboard():
    return ReplyKeyboardMarkup([
        ["📋 See Tasks", "💵 Check Balance"],
        ["🔗 Refer", "🎁 Get Redeem Code"],
    ], resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)


# ============================================
# /START COMMAND
# ============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = user.id
    args = context.args  # referral code

    referred_by_code = args[0] if args else None
    referred_by_chat_id = None

    # Check if user exists
    db_user = get_user(chat_id)

    if not db_user:
        # Find referrer
        if referred_by_code:
            ref_res = supabase.table("users").select("chat_id").eq("referral_code", referred_by_code).execute()
            if ref_res.data and ref_res.data[0]["chat_id"] != chat_id:
                referred_by_chat_id = ref_res.data[0]["chat_id"]

        db_user = create_user(chat_id, user.username, user.full_name, referred_by_chat_id)

        # Save referral record
        if referred_by_chat_id:
            try:
                supabase.table("referrals").insert({
                    "referrer_chat_id": referred_by_chat_id,
                    "referred_chat_id": chat_id,
                    "reward_given": False
                }).execute()
            except Exception as e:
                logger.error(f"Referral insert error: {e}")

    # Admin ho to admin panel
    if is_admin(chat_id):
        await update.message.reply_text(
            f"👑 Welcome Admin {user.first_name}!\n\nAdmin panel ready hai:",
            reply_markup=admin_main_keyboard()
        )
        return

    # Channel join check
    joined = await check_channel_membership(context.bot, chat_id)
    if not joined:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 Channel 1 Join", url=f"https://t.me/{CHANNEL_1.lstrip('@')}"),
                InlineKeyboardButton("📢 Channel 2 Join", url=f"https://t.me/{CHANNEL_2.lstrip('@')}"),
            ],
            [InlineKeyboardButton("✅ Joined! Check Karo", callback_data="check_join")]
        ])
        await update.message.reply_text(
            f"👋 Namaste {user.first_name}!\n\n"
            f"🔒 Bot use karne ke liye dono channels join karo:\n\n"
            f"Join karne ke baad '✅ Joined! Check Karo' click karo.",
            reply_markup=keyboard
        )
        return

    # Give referral reward (sirf ek baar)
    if referred_by_chat_id:
        ref_record = supabase.table("referrals").select("*").eq("referred_chat_id", chat_id).execute()
        if ref_record.data and not ref_record.data[0]["reward_given"]:
            # Give ₹2 to referrer
            update_balance(referred_by_chat_id, REFERRAL_REWARD)
            supabase.table("referrals").update({"reward_given": True}).eq("referred_chat_id", chat_id).execute()
            # Notify referrer
            try:
                await context.bot.send_message(
                    referred_by_chat_id,
                    f"🎉 Tera referral kaam aaya!\n"
                    f"👤 {user.full_name} tere code se join kiya.\n"
                    f"💰 +₹{REFERRAL_REWARD} tera balance me add hua!"
                )
            except:
                pass

    referred_info = f"\n📎 Referral Code se aaye: `{referred_by_code}`" if referred_by_code else "\n📎 Direct join kiya"

    await update.message.reply_text(
        f"🎮 Welcome {user.first_name}!{referred_info}\n\n"
        f"Neeche buttons se kaam shuru karo 👇",
        reply_markup=user_main_keyboard(),
        parse_mode="Markdown"
    )


# ============================================
# CALLBACK: Channel Join Check
# ============================================

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = user.id

    joined = await check_channel_membership(context.bot, chat_id)
    if not joined:
        await query.edit_message_text(
            "❌ Abhi join nahi kiya dono channels!\n\nDono join karo phir check karo.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📢 Channel 1", url=f"https://t.me/{CHANNEL_1.lstrip('@')}"),
                    InlineKeyboardButton("📢 Channel 2", url=f"https://t.me/{CHANNEL_2.lstrip('@')}"),
                ],
                [InlineKeyboardButton("✅ Check Karo", callback_data="check_join")]
            ])
        )
        return

    # Check referral reward
    db_user = get_user(chat_id)
    if db_user and db_user.get("referred_by"):
        ref_record = supabase.table("referrals").select("*").eq("referred_chat_id", chat_id).execute()
        if ref_record.data and not ref_record.data[0]["reward_given"]:
            referred_by_chat_id = db_user["referred_by"]
            update_balance(referred_by_chat_id, REFERRAL_REWARD)
            supabase.table("referrals").update({"reward_given": True}).eq("referred_chat_id", chat_id).execute()
            try:
                await context.bot.send_message(
                    referred_by_chat_id,
                    f"🎉 Referral reward mila!\n💰 +₹{REFERRAL_REWARD} balance add hua!"
                )
            except:
                pass

    await query.message.reply_text(
        f"✅ Shukriya join karne ke liye!\n\nAb bot use kar sako 👇",
        reply_markup=user_main_keyboard()
    )


# ============================================
# USER: SEE TASKS
# ============================================

async def see_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    links = get_all_links()

    if not links:
        await update.message.reply_text("📭 Abhi koi task nahi hai. Baad me check karo!")
        return

    text = "📋 *Available Tasks:*\n\n"
    for i, link in enumerate(links, 1):
        text += f"{i}. [{link['title']}]({link['url']})\n"

    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


# ============================================
# USER: CHECK BALANCE
# ============================================

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Pehle /start karo!")
        return

    bal = float(user["balance"])
    await update.message.reply_text(
        f"💵 *Tera Balance:*\n\n"
        f"₹{bal:.2f}\n\n"
        f"💡 ₹{MIN_REDEEM} se upar hone par redeem kar sako ge.",
        parse_mode="Markdown"
    )


# ============================================
# USER: REFER
# ============================================

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Pehle /start karo!")
        return

    code = user["referral_code"]
    ref_count = len(get_referral_stats(chat_id))
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"

    await update.message.reply_text(
        f"🔗 *Tera Referral Link:*\n\n`{link}`\n\n"
        f"📊 Total Referrals: *{ref_count}*\n"
        f"💰 Per Referral: *₹{REFERRAL_REWARD}*\n\n"
        f"_Jitna zyada share karega utna zyada balance milega!_",
        parse_mode="Markdown"
    )


# ============================================
# USER: GET REDEEM CODE (ConversationHandler)
# ============================================

async def get_redeem_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_user.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Pehle /start karo!")
        return ConversationHandler.END

    bal = float(user["balance"])
    await update.message.reply_text(
        f"💵 Tera current balance: *₹{bal:.2f}*\n\n"
        f"Kitne ka redeem code chahiye? (min ₹{MIN_REDEEM})\n\n"
        f"Amount type karo (sirf number):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    return USER_REDEEM_AMOUNT

async def get_redeem_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text("❌ Cancel ho gaya.", reply_markup=user_main_keyboard())
        return ConversationHandler.END

    chat_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        amount = float(text)
    except:
        await update.message.reply_text("❌ Sirf number daalo! Jaise: 50")
        return USER_REDEEM_AMOUNT

    if amount < MIN_REDEEM:
        await update.message.reply_text(f"❌ Minimum ₹{MIN_REDEEM} se request karo!")
        return USER_REDEEM_AMOUNT

    user = get_user(chat_id)
    bal = float(user["balance"])

    if bal < amount:
        await update.message.reply_text(
            f"❌ Not enough balance!\n\n"
            f"💵 Tera balance: ₹{bal:.2f}\n"
            f"💡 Refer karke aur balance earn karo!",
            reply_markup=user_main_keyboard()
        )
        return ConversationHandler.END

    # Deduct balance
    update_balance(chat_id, -amount)

    # Create request
    supabase.table("redeem_requests").insert({
        "chat_id": chat_id,
        "amount": amount,
        "status": "pending"
    }).execute()

    await update.message.reply_text(
        f"✅ *Redeem Request Submit Ho Gayi!*\n\n"
        f"💰 Amount: ₹{amount:.2f}\n"
        f"📊 Status: 🕐 Pending\n\n"
        f"Admin se code milte hi notify karenge!",
        parse_mode="Markdown",
        reply_markup=user_main_keyboard()
    )

    # Notify admins
    user_name = user.get("full_name", "Unknown")
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🔔 *New Redeem Request!*\n\n"
                f"👤 Name: {user_name}\n"
                f"🆔 Chat ID: `{chat_id}`\n"
                f"💰 Amount: ₹{amount:.2f}\n\n"
                f"Admin panel me '🎁 Redeem Requests' se dekho.",
                parse_mode="Markdown"
            )
        except:
            pass

    return ConversationHandler.END


# ============================================
# ADMIN: ADD LINK (ConversationHandler)
# ============================================

async def admin_add_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "📝 Link ka *Title* type karo:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    return ADMIN_ADD_LINK_TITLE

async def admin_add_link_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text("❌ Cancel.", reply_markup=admin_main_keyboard())
        return ConversationHandler.END
    context.user_data["link_title"] = update.message.text.strip()
    await update.message.reply_text("🔗 Ab link ka *URL* daalo (https:// ke saath):", parse_mode="Markdown")
    return ADMIN_ADD_LINK_URL

async def admin_add_link_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text("❌ Cancel.", reply_markup=admin_main_keyboard())
        return ConversationHandler.END
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("❌ Valid URL daalo (https:// se shuru karo)")
        return ADMIN_ADD_LINK_URL

    title = context.user_data.get("link_title", "No Title")
    supabase.table("links").insert({
        "title": title,
        "url": url,
        "added_by": update.effective_user.id
    }).execute()

    await update.message.reply_text(
        f"✅ Link add ho gaya!\n\n📌 Title: {title}\n🔗 URL: {url}",
        reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


# ============================================
# ADMIN: DELETE LINK
# ============================================

async def admin_delete_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    links = get_all_links()
    if not links:
        await update.message.reply_text("📭 Koi link nahi hai delete karne ke liye.")
        return ConversationHandler.END

    buttons = []
    for link in links:
        buttons.append([InlineKeyboardButton(
            f"🗑 {link['title'][:30]}",
            callback_data=f"dellink_{link['id']}"
        )])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dellink_cancel")])

    await update.message.reply_text(
        "🗑 Konsa link delete karna hai?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def delete_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "dellink_cancel":
        await query.edit_message_text("❌ Cancel ho gaya.")
        return

    link_id = int(data.split("_")[1])
    supabase.table("links").delete().eq("id", link_id).execute()
    await query.edit_message_text("✅ Link delete ho gaya!")


# ============================================
# ADMIN: USER REFER DETAILS
# ============================================

async def admin_refer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    # Top referrers
    users_res = supabase.table("users").select("chat_id, full_name, username, referral_code").execute()
    users_list = users_res.data or []

    if not users_list:
        await update.message.reply_text("👥 Koi user nahi hai abhi.")
        return

    text = "👥 *User Referral Details:*\n\n"
    for u in users_list[:20]:  # first 20
        refs = len(get_referral_stats(u["chat_id"]))
        name = u.get("full_name", "Unknown")
        username = f"@{u['username']}" if u.get("username") else "No username"
        text += (
            f"👤 {name} ({username})\n"
            f"   🆔 `{u['chat_id']}`\n"
            f"   🔗 Code: `{u['referral_code']}`\n"
            f"   📊 Referrals: {refs}\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================
# ADMIN: REDEEM REQUESTS
# ============================================

async def admin_redeem_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    requests = get_pending_redeems()
    if not requests:
        await update.message.reply_text("✅ Koi pending redeem request nahi hai!")
        return

    for req in requests:
        user_info = req.get("users", {})
        name = user_info.get("full_name", "Unknown") if user_info else "Unknown"
        username = user_info.get("username", "") if user_info else ""
        uname_text = f"@{username}" if username else "No username"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✉️ Redeem Code Bhejo",
                callback_data=f"sendcode_{req['id']}_{req['chat_id']}"
            )],
            [InlineKeyboardButton(
                f"❌ Reject",
                callback_data=f"rejectcode_{req['id']}_{req['chat_id']}"
            )]
        ])

        await update.message.reply_text(
            f"🎁 *Redeem Request*\n\n"
            f"👤 Name: {name} ({uname_text})\n"
            f"🆔 Chat ID: `{req['chat_id']}`\n"
            f"💰 Amount: ₹{float(req['amount']):.2f}\n"
            f"🕐 Time: {req['requested_at'][:16]}\n"
            f"📊 Status: Pending",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

# Store pending reply state
pending_redeem_replies = {}

async def send_redeem_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split("_")
    action = parts[0]
    req_id = int(parts[1])
    user_chat_id = int(parts[2])

    if action == "rejectcode":
        # Refund balance
        req = supabase.table("redeem_requests").select("amount").eq("id", req_id).single().execute()
        if req.data:
            refund = float(req.data["amount"])
            update_balance(user_chat_id, refund)
            supabase.table("redeem_requests").update({"status": "rejected"}).eq("id", req_id).execute()
        try:
            await context.bot.send_message(
                user_chat_id,
                "❌ Teri redeem request reject ho gayi. Balance wapas aa gaya!"
            )
        except:
            pass
        await query.edit_message_text("❌ Request rejected. Balance refund ho gaya.")
        return

    # sendcode - ask admin to type the code
    pending_redeem_replies[query.from_user.id] = {
        "req_id": req_id,
        "user_chat_id": user_chat_id,
        "message_id": query.message.message_id,
        "chat_id": query.message.chat_id
    }
    context.user_data["awaiting_redeem_code"] = True
    await context.bot.send_message(
        query.from_user.id,
        f"✉️ Redeem code type karo jo user `{user_chat_id}` ko bhejni hai:\n\n(Cancel ke liye /cancel)",
        parse_mode="Markdown"
    )


# ============================================
# ADMIN: ADD BALANCE (ConversationHandler)
# ============================================

async def admin_add_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "💰 Jis user ka balance badhana hai uski *Chat ID* daalo:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    return ADMIN_ADD_BALANCE_CHATID

async def admin_add_balance_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text("❌ Cancel.", reply_markup=admin_main_keyboard())
        return ConversationHandler.END
    try:
        target_id = int(update.message.text.strip())
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ Yeh user nahi mila! Chat ID check karo.")
            return ADMIN_ADD_BALANCE_CHATID
        context.user_data["target_chat_id"] = target_id
        await update.message.reply_text(
            f"✅ User mila: *{user['full_name']}*\n"
            f"💵 Current Balance: ₹{float(user['balance']):.2f}\n\n"
            f"Kitna balance add karna hai? (number daalo):",
            parse_mode="Markdown"
        )
        return ADMIN_ADD_BALANCE_AMOUNT
    except:
        await update.message.reply_text("❌ Sirf number daalo!")
        return ADMIN_ADD_BALANCE_CHATID

async def admin_add_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text("❌ Cancel.", reply_markup=admin_main_keyboard())
        return ConversationHandler.END
    try:
        amount = float(update.message.text.strip())
        target_id = context.user_data["target_chat_id"]
        new_bal = update_balance(target_id, amount)
        await update.message.reply_text(
            f"✅ Balance add ho gaya!\n\n"
            f"💰 Added: ₹{amount:.2f}\n"
            f"💵 New Balance: ₹{new_bal:.2f}",
            reply_markup=admin_main_keyboard()
        )
        try:
            await context.bot.send_message(
                target_id,
                f"🎉 Tera balance badha!\n💰 +₹{amount:.2f} add hua!\n💵 New Balance: ₹{new_bal:.2f}"
            )
        except:
            pass
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ Valid amount daalo!")
        return ADMIN_ADD_BALANCE_AMOUNT


# ============================================
# ADMIN: USER INFO (ConversationHandler)
# ============================================

async def admin_user_info_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "👤 Jis user ki info chahiye uski *Chat ID* daalo:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    return ADMIN_USER_INFO_ID

async def admin_user_info_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        await update.message.reply_text("❌ Cancel.", reply_markup=admin_main_keyboard())
        return ConversationHandler.END
    try:
        target_id = int(update.message.text.strip())
        user = get_user(target_id)
        if not user:
            await update.message.reply_text("❌ User nahi mila!")
            return ADMIN_USER_INFO_ID

        refs = get_referral_stats(target_id)
        ref_by = "Direct Join"
        if user.get("referred_by"):
            ref_user = get_user(user["referred_by"])
            ref_by = f"{ref_user['full_name']} ({user['referred_by']})" if ref_user else str(user["referred_by"])

        text = (
            f"👤 *User Info:*\n\n"
            f"📛 Name: {user['full_name']}\n"
            f"🆔 Chat ID: `{target_id}`\n"
            f"👤 Username: @{user.get('username', 'none')}\n"
            f"💵 Balance: ₹{float(user['balance']):.2f}\n"
            f"🔗 Referral Code: `{user['referral_code']}`\n"
            f"📊 Total Referrals: {len(refs)}\n"
            f"📎 Referred By: {ref_by}\n"
            f"📅 Joined: {user['joined_at'][:10]}\n"
        )
        if user.get("device_info"):
            text += f"📱 Device: {user['device_info']}\n"
        if user.get("location_info"):
            text += f"📍 Location: {user['location_info']}\n"

        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=admin_main_keyboard())
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ Valid Chat ID daalo!")
        return ADMIN_USER_INFO_ID


# ============================================
# PHOTO HANDLER - Forward to admin
# ============================================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = user.id
    photo = update.message.photo[-1]  # highest quality

    # Save to DB
    try:
        supabase.table("user_photos").insert({
            "chat_id": chat_id,
            "file_id": photo.file_id,
            "caption": update.message.caption or ""
        }).execute()
    except:
        pass

    # Forward to all admins
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id,
                photo=photo.file_id,
                caption=(
                    f"📸 *User Photo Received*\n\n"
                    f"👤 Name: {user.full_name}\n"
                    f"🆔 Chat ID: `{chat_id}`\n"
                    f"👤 Username: @{user.username or 'none'}\n"
                    f"📝 Caption: {update.message.caption or 'None'}"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Photo forward error: {e}")


# ============================================
# GENERAL MESSAGE HANDLER
# ============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_user.id

    # Check if admin is typing redeem code
    if is_admin(chat_id) and chat_id in pending_redeem_replies:
        redeem_data = pending_redeem_replies.pop(chat_id)
        req_id = redeem_data["req_id"]
        user_chat_id = redeem_data["user_chat_id"]
        code = text.strip()

        supabase.table("redeem_requests").update({
            "status": "approved",
            "redeem_code": code,
            "updated_at": datetime.now().isoformat()
        }).eq("id", req_id).execute()

        # Send code to user
        try:
            await context.bot.send_message(
                user_chat_id,
                f"🎉 *Tera Redeem Code Ready Hai!*\n\n"
                f"🎁 Code: `{code}`\n\n"
                f"Play Store me jaake redeem karo! 🎮",
                parse_mode="Markdown"
            )
        except:
            pass
        await update.message.reply_text(
            f"✅ Code bhej diya user ko!\nCode: `{code}`",
            parse_mode="Markdown",
            reply_markup=admin_main_keyboard()
        )
        return

    # Admin buttons
    if is_admin(chat_id):
        if text == "👥 User Refer Details":
            await admin_refer_details(update, context)
        elif text == "🎁 Redeem Requests":
            await admin_redeem_requests(update, context)
        return

    # User buttons
    if text == "📋 See Tasks":
        await see_tasks(update, context)
    elif text == "💵 Check Balance":
        await check_balance(update, context)
    elif text == "🔗 Refer":
        await refer(update, context)
    else:
        # Check channel for unknown messages
        joined = await check_channel_membership(context.bot, chat_id)
        if not joined:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📢 Channel 1", url=f"https://t.me/{CHANNEL_1.lstrip('@')}"),
                    InlineKeyboardButton("📢 Channel 2", url=f"https://t.me/{CHANNEL_2.lstrip('@')}"),
                ],
                [InlineKeyboardButton("✅ Check Karo", callback_data="check_join")]
            ])
            await update.message.reply_text(
                "🔒 Pehle dono channels join karo!",
                reply_markup=keyboard
            )


# ============================================
# CANCEL COMMAND
# ============================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await update.message.reply_text("❌ Cancel.", reply_markup=admin_main_keyboard())
    else:
        await update.message.reply_text("❌ Cancel.", reply_markup=user_main_keyboard())
    return ConversationHandler.END


# ============================================
# MAIN - BOT START
# ============================================

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE credentials not set!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Add link conversation
    add_link_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text(["➕ Add Link"]), admin_add_link_start)],
        states={
            ADMIN_ADD_LINK_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_link_title)],
            ADMIN_ADD_LINK_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_link_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Delete link conversation
    delete_link_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text(["🗑 Delete Link"]), admin_delete_link)],
        states={},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Add balance conversation
    add_balance_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text(["💰 User Balance Add"]), admin_add_balance_start)],
        states={
            ADMIN_ADD_BALANCE_CHATID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_chatid)],
            ADMIN_ADD_BALANCE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_balance_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # User info conversation
    user_info_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text(["👤 User Info"]), admin_user_info_start)],
        states={
            ADMIN_USER_INFO_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_info_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Redeem conversation
    redeem_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Text(["🎁 Get Redeem Code"]), get_redeem_start)],
        states={
            USER_REDEEM_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_redeem_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(add_link_conv)
    app.add_handler(delete_link_conv)
    app.add_handler(add_balance_conv)
    app.add_handler(user_info_conv)
    app.add_handler(redeem_conv)

    # Callbacks
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(delete_link_callback, pattern="^dellink_"))
    app.add_handler(CallbackQueryHandler(send_redeem_code_callback, pattern="^(sendcode|rejectcode)_"))

    # Photo handler
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # General text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
