import os
import asyncio
import yt_dlp
import uuid
import shutil
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
#          CONFIG (Environment Variables)
# ==========================================
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", "0"))
PORT = int(os.environ.get("PORT", "8000"))

# Storage
TASK_QUEUE = []
IS_WORKING = False
URL_STORE = {}

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==========================================
#          WEB SERVER (For Health Checks)
# ==========================================
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is running perfectly!")

    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"🚀 Web Server started on port {PORT}")

# ==========================================
#          CORE DOWNLOADER (Worker)
# ==========================================
async def worker():
    global IS_WORKING
    if IS_WORKING: return
    IS_WORKING = True

    while TASK_QUEUE:
        task = TASK_QUEUE.pop(0)
        url = task["link"]
        quality = task["quality"]
        msg = task["msg"]
        user_mention = task["user_mention"]

        try:
            status_msg = await msg.reply_text("📥 **Processing your request...**")
            
            # Format Selection with Fallback logic
            if quality == "mp3":
                fmt = 'bestaudio/best'
            else:
                # Agar requested quality nahi mili toh auto best select karega
                fmt = f'bestvideo[height<={quality}]+bestaudio/best/best'

            # YT-DLP Options Fixed for Koyeb & YouTube's new rules
            ydl_opts = {
                'format': fmt,
                'outtmpl': '%(title)s.%(ext)s',
                'cookiefile': 'cookies.txt' if os.path.exists("cookies.txt") else None,
                'noplaylist': True,
                'writethumbnail': True,
                'nocheckcertificate': True,
                'quiet': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'web'],
                        'player_skip': ['dash', 'hls']
                    }
                }
            }

            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info.get("title", "Video")

            await status_msg.edit_text("📥 **Downloading...**\n*(This might take a minute)*")
            loop = asyncio.get_running_loop()
            file_path, title = await loop.run_in_executor(None, download_video)

            if not os.path.exists(file_path):
                raise Exception("File not found after download.")

            await status_msg.edit_text("☁️ **Uploading to Telegram...**")
            
            # Thumbnail handling
            thumb_path = file_path.rsplit(".", 1)[0] + ".jpg"
            thumb = thumb_path if os.path.exists(thumb_path) else None
            
            caption = f"🎬 **{title}**\n👤 Requested by: {user_mention}"
            target_id = DUMP_CHANNEL if DUMP_CHANNEL != 0 else msg.chat.id

            if quality == "mp3":
                await app.send_audio(target_id, file_path, caption=caption, thumb=thumb)
            else:
                await app.send_video(target_id, file_path, caption=caption, thumb=thumb, supports_streaming=True)

            if DUMP_CHANNEL != 0:
                await status_msg.edit_text("✅ **Uploaded to Dump Channel!**")
            else:
                await status_msg.delete()

            # Clean up files
            if os.path.exists(file_path): os.remove(file_path)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        except Exception as e:
            error_text = str(e)
            if "Requested format is not available" in error_text:
                await msg.reply_text("❌ **Error:** Selected quality not available for this video.")
            else:
                await msg.reply_text(f"❌ **Error:** `{error_text}`")
            print(f"Worker Error: {e}")
        
        await asyncio.sleep(2) # Small delay to prevent spam

    IS_WORKING = False

# ==========================================
#          TELEGRAM HANDLERS
# ==========================================
@app.on_message(filters.command("start"))
async def start_handler(c, m):
    await m.reply_text("👋 **Welcome!**\nSend me a YouTube link to download video or audio.")

@app.on_message(filters.regex(r"(https?://.*youtube|youtu\.be)"))
async def process_link(c, m):
    url = m.text.strip()
    url_id = str(uuid.uuid4())[:8]
    URL_STORE[url_id] = url
    
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 1080p", callback_data=f"dl|1080|{url_id}"), InlineKeyboardButton("🎬 720p", callback_data=f"dl|720|{url_id}")],
        [InlineKeyboardButton("🎬 480p", callback_data=f"dl|480|{url_id}"), InlineKeyboardButton("🎵 MP3", callback_data=f"dl|mp3|{url_id}")]
    ])
    await m.reply_text("🎥 **Choose Quality:**", reply_markup=btns)

@app.on_callback_query()
async def cb_handler(c, cb):
    data = cb.data.split("|")
    action = data[0]
    quality = data[1]
    url_id = data[2]
    
    url = URL_STORE.get(url_id)
    if not url:
        return await cb.answer("Link Expired! Send the link again.", show_alert=True)

    if action == "dl":
        TASK_QUEUE.append({
            "link": url, 
            "quality": quality, 
            "msg": cb.message, 
            "user_mention": cb.from_user.mention
        })
        await cb.answer("Added to queue!")
        await cb.message.edit_text(f"✅ **Queued!**\nQuality: `{quality}`\n\nWait for your turn...")
        asyncio.create_task(worker())

# ==========================================
#          STARTUP
# ==========================================
async def start_bot():
    print("🤖 Starting Bot...")
    await app.start()
    await web_server()
    print("✅ Bot is Online!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(start_bot())
