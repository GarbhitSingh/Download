import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yt_dlp

# --- CONFIGURATION ---
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
DOWNLOAD_DIR = "downloads"

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a YouTube link (Video or Short) and I'll download it to storage!")

def download_youtube_video(url, output_path):
    """
    Downloads video using yt-dlp.
    Returns the filename of the downloaded video.
    """
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{output_path}/%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename
    except Exception as e:
        print(f"Error downloading: {e}")
        return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    
    # Basic validation to check if it's a YouTube link
    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text("❌ That doesn't look like a YouTube link.")
        return

    status_msg = await update.message.reply_text(f"⏳ Downloading... Please wait.")

    # Create download directory if it doesn't exist
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    # Run the blocking download in a separate thread so the bot doesn't freeze
    # (Note: For heavy production use, use a proper task queue like Celery)
    loop = asyncio.get_event_loop()
    # We use a lambda or partial to pass arguments to the synchronous function
    file_path = await loop.run_in_executor(None, download_youtube_video, url, DOWNLOAD_DIR)

    if file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path) / (1024 * 1024) # Size in MB
        
        await status_msg.edit_text(f"✅ Downloaded to storage: `{file_path}`\nSIZE: {file_size:.2f} MB")

        # Attempt to upload if under 50MB (Telegram Bot API limit)
        if file_size < 50:
            await update.message.reply_text("🚀 Uploading to Telegram...")
            try:
                await update.message.reply_video(video=open(file_path, 'rb'))
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error uploading: {e}")
        else:
            await update.message.reply_text(
                f"⚠️ File is too large ({file_size:.2f} MB) to send via Telegram Bot API (Limit is 50MB).\n"
                "It has been saved safely to your local storage."
            )
    else:
        await status_msg.edit_text("❌ Download failed. Please check the log or the link.")

if __name__ == '__main__':
    import asyncio # Needed for the run_in_executor part above
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    start_handler = CommandHandler('start', start)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)

    application.add_handler(start_handler)
    application.add_handler(message_handler)

    print("Bot is running...")
    application.run_polling()
