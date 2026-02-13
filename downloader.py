import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
import yt_dlp

# --- CONFIGURATION (EDIT THESE) ---
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHANNEL_ID = "@YourChannelUsername"  # Must start with @, e.g., @MyCoolChannel
CHANNEL_URL = "https://t.me/YourChannelUsername"
ADMIN_ID = 123456789  # Your personal Telegram User ID (get it from @userinfobot)
DOWNLOAD_DIR = "downloads"

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- IN-MEMORY DATABASE (Replace with SQLite/Postgres for production) ---
valid_users = set()  # Caches users who have joined so we don't spam API
user_stats = set()   # Tracks unique users for the admin panel

# --- HELPER: FORCE SUB CHECK ---
async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the user is a member of the required channel."""
    if user_id in valid_users:
        return True
    
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            valid_users.add(user_id)
            return True
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        # If bot is not admin in channel, it crashes here.
        # Fallback: Assume true to not break bot, but log error.
        return False
    
    return False

# --- MENUS (INLINE KEYBOARDS) ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📺 Download YouTube", callback_data='help_yt'),
         InlineKeyboardButton("📸 Download Instagram", callback_data='help_ig')],
        [InlineKeyboardButton("🆘 Help", callback_data='help_general')],
    ]
    return InlineKeyboardMarkup(keyboard)

def force_join_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I Have Joined", callback_data='check_join')]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 User Stats", callback_data='admin_stats')],
        [InlineKeyboardButton("📢 Broadcast (Coming Soon)", callback_data='admin_broadcast')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_stats.add(user.id)
    
    # Check Membership
    is_member = await check_membership(user.id, context)
    if not is_member:
        await update.message.reply_text(
            f"🚫 **Access Denied**\n\nYou must join our channel {CHANNEL_ID} to use this bot.",
            reply_markup=force_join_keyboard(),
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\nI can download videos from **YouTube** and **Instagram**.\nSend me a link or choose an option below:",
        reply_markup=main_menu_keyboard(),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses button clicks."""
    query = update.callback_query
    await query.answer() # Acknowledge click to stop loading animation
    
    data = query.data
    
    if data == 'check_join':
        # Re-check membership
        if await check_membership(query.from_user.id, context):
            await query.edit_message_text(
                "✅ **Verified!** Welcome aboard.",
                reply_markup=main_menu_keyboard(),
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "❌ **Still not found.** Please join the channel first.",
                reply_markup=force_join_keyboard(),
                parse_mode='Markdown'
            )

    elif data == 'help_yt':
        await query.edit_message_text(
            "📺 **YouTube Mode**\nJust send me any YouTube video, Short, or Livestream link.\n\nExample:\n`https://youtu.be/xxxxx`",
            reply_markup=main_menu_keyboard(),
            parse_mode='Markdown'
        )
        
    elif data == 'help_ig':
        await query.edit_message_text(
            "📸 **Instagram Mode**\nSend me a Reel or Post link.\n\n⚠️ *Note: Private accounts are not supported.*",
            reply_markup=main_menu_keyboard(),
            parse_mode='Markdown'
        )

    elif data == 'admin_stats':
        if query.from_user.id != ADMIN_ID:
            return
        await query.edit_message_text(
            f"📊 **Bot Statistics**\n\nUnique Users: {len(user_stats)}\nValid Members: {len(valid_users)}",
            reply_markup=admin_keyboard(),
            parse_mode='Markdown'
        )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return # Ignore non-admins silently
    
    await update.message.reply_text(
        "🛠 **Admin Panel**",
        reply_markup=admin_keyboard(),
        parse_mode='Markdown'
    )

# --- DOWNLOAD LOGIC ---

def download_media(url, output_path):
    """
    Universal downloader for YT and Insta using yt-dlp.
    """
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        # Fake User-Agent to avoid some blocks (especially for Instagram)
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info.get('title', 'Video')
    except Exception as e:
        print(f"DL Error: {e}")
        return None, None

async def handle_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text
    
    # 1. Force Join Check
    if not await check_membership(user_id, context):
        await update.message.reply_text("🚫 Please join the channel first.", reply_markup=force_join_keyboard())
        return

    # 2. Link Detection
    if not any(x in url for x in ['youtube.com', 'youtu.be', 'instagram.com']):
        await update.message.reply_text("❌ I only support YouTube and Instagram links.")
        return

    msg = await update.message.reply_text("⏳ **Processing...**\nChecking link metadata...", parse_mode='Markdown')

    # 3. Download (in separate thread)
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    loop = asyncio.get_event_loop()
    
    # Run synchronous yt-dlp code in executor to prevent blocking
    file_path, title = await loop.run_in_executor(None, download_media, url, DOWNLOAD_DIR)

    if file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        
        await msg.edit_text(f"✅ **Downloaded**\nUploading {file_size:.2f} MB...", parse_mode='Markdown')

        if file_size < 49: # Keep safe margin below 50MB
            try:
                await update.message.reply_video(
                    video=open(file_path, 'rb'),
                    caption=f"🎥 **{title}**\n💾 Saved to Storage",
                    parse_mode='Markdown'
                )
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"⚠️ Error uploading to Telegram: {e}")
        else:
            await msg.edit_text(f"⚠️ **File too large for Telegram** ({file_size:.2f} MB).\nSaved locally: `{file_path}`", parse_mode='Markdown')
    else:
        await msg.edit_text("❌ **Download Failed.**\nLink might be private or invalid.", parse_mode='Markdown')

# --- MAIN EXECUTION ---
if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Message handler for links (filters out commands)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_links))

    print(f"🤖 Bot Started. Admin ID: {ADMIN_ID}")
    application.run_polling()
        
