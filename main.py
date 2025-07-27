import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
from datetime import datetime
from collections import defaultdict
import yt_dlp

# ============ إعدادات البوت ============
TOKEN = '8341500604:AAEeOInjcnpmLQ1y3J3vZimBLXm1EokNzlw'  # ← ← ← استبدله هنا فقط
ADS = [
    "https://exe.io/Zx4p2hKv",  # إعلان 1
    "https://exe.io/BXQ6wFN4"   # إعلان 2
]
DAILY_LIMIT = 3
user_downloads = defaultdict(lambda: {"date": None, "count": 0})

# ============ الإعدادات العامة ============
logging.basicConfig(level=logging.INFO)

# ============ الأوامر ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 أهلاً بك!\nأرسل رابط فيديو من YouTube أو TikTok أو Instagram أو Facebook وسأقوم بتحميله لك بدون علامة مائية."
    )

# ============ التحكم في الحد اليومي ============
def reset_counter(user_id):
    today = datetime.now().date()
    if user_downloads[user_id]["date"] != today:
        user_downloads[user_id] = {"date": today, "count": 0}

def is_within_limit(user_id):
    reset_counter(user_id)
    return user_downloads[user_id]["count"] < DAILY_LIMIT

def increment_download(user_id):
    user_downloads[user_id]["count"] += 1

# ============ استخراج الجودات من YouTube ============
def get_youtube_formats(url):
    try:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            qualities = {}
            for fmt in formats:
                if fmt.get("vcodec") != "none" and fmt.get("acodec") != "none":
                    res = fmt.get("format_note") or f"{fmt.get('height')}p"
                    if res and "audio only" not in fmt.get("format", ""):
                        qualities[str(fmt['format_id'])] = res
            return qualities, info.get("title", "video")
    except Exception as e:
        logging.error(f"Error getting formats: {e}")
        return {}, None

# ============ تحميل الفيديو ============
def download_video(url, fmt_id=None):
    try:
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'quiet': True,
        }
        if fmt_id:
            ydl_opts['format'] = fmt_id
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logging.error(f"Download failed: {e}")
        return None

# ============ الرسائل العادية ============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    if not any(s in url for s in ["youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com"]):
        await update.message.reply_text("❌ الرابط غير مدعوم.")
        return

    reset_counter(user_id)
    remaining = DAILY_LIMIT - user_downloads[user_id]["count"]

    if not is_within_limit(user_id):
        buttons = [
            [InlineKeyboardButton("🔗 شاهد الإعلان 1", url=ADS[0])],
            [InlineKeyboardButton("🔗 شاهد الإعلان 2", url=ADS[1])],
            [InlineKeyboardButton("✅ فتحت الإعلانين، أكمل", callback_data="ads_done")]
        ]
        await update.message.reply_text(
            "🚫 لقد استخدمت الحد المجاني اليومي (3 فيديوهات).\n\n"
            "🎥 إذا أردت تحميل فيديو إضافي:\n"
            "1. اضغط على \"شاهد الإعلان 1\"\n"
            "2. ثم \"شاهد الإعلان 2\"\n"
            "3. بعد المشاهدة اضغط \"✅ فتحت الإعلانين، أكمل\".",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        context.user_data['pending_url'] = url
        return

    await update.message.reply_text(f"✅ عدد الفيديوهات المتبقية اليوم: {remaining}")

    if "youtube.com" in url or "youtu.be" in url:
        formats, title = get_youtube_formats(url)
        if not formats:
            await update.message.reply_text("❌ تعذر الحصول على الجودات المتاحة.")
            return
        buttons = [
            [InlineKeyboardButton(f"{label}", callback_data=f"quality|{fmt_id}|{url}")]
            for fmt_id, label in formats.items()
        ]
        await update.message.reply_text(
            f"🎬 اختر الجودة لتحميل الفيديو:\n📌 {title}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await process_download(update, context, url)

# ============ زر تحميل بعد الضغط على إعلانين ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ads_done":
        url = context.user_data.get("pending_url")
        if url:
            await query.edit_message_text("⏳ جاري تحميل الفيديو الآن...")
            await process_download(query, context, url)
            context.user_data['pending_url'] = None
        else:
            await query.edit_message_text("❌ لم يتم العثور على رابط محفوظ.")
    elif query.data.startswith("quality|"):
        _, fmt_id, url = query.data.split("|", 2)
        await query.edit_message_text("📥 جاري التحميل بالجودة المحددة...")
        await process_download(query, context, url, fmt_id)

# ============ تنفيذ التحميل ============
async def process_download(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, fmt_id=None):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    msg = await (update.message.reply_text("⏳ جاري تحميل الفيديو...") if hasattr(update, 'message') else context.bot.send_message(chat_id, "⏳ جار التحميل..."))

    filepath = download_video(url, fmt_id)
    if not filepath:
        await context.bot.send_message(chat_id=chat_id, text="❌ فشل في تحميل الفيديو.")
        return

    try:
        await context.bot.send_video(chat_id=chat_id, video=filepath, caption="✅ تم التحميل بنجاح.")
        increment_download(user_id)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠ حدث خطأ أثناء إرسال الفيديو: {e}")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

# ============ تشغيل البوت ============
if __name__ == "_main_":
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("✅ البوت يعمل الآن...")
    app.run_polling()  # ← ← ← هذا هو السطر الذي يُبقي البوت شغالاً في Rende