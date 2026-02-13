import os
import asyncio
import yt_dlp
import uuid
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# CONFIG
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", "0"))
PORT = int(os.environ.get("PORT", "8000"))

TASK_QUEUE = []
IS_WORKING = False
URL_STORE = {}

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# WEB SERVER
async def web_server():
    async def handle(request): return web.Response(text="Bot is Alive!")
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

# WORKER
async def worker():
    global IS_WORKING
    if IS_WORKING: return
    IS_WORKING = True

    while TASK_QUEUE:
        task = TASK_QUEUE.pop(0)
        url, quality, msg, user_mention = task["link"], task["quality"], task["msg"], task["user_mention"]

        try:
            status_msg = await msg.reply_text("📥 **Downloading...**")
            
            # Formats
            fmt = 'bestaudio/best' if quality == "mp3" else f'bestvideo[height<={quality}]+bestaudio/best/best'

            # YT-DLP OPTIONS (Fixed for NoneType and Signature Errors)
            ydl_opts = {
                'format': fmt,
                'outtmpl': '%(title)s.%(ext)s',
                'cookiefile': 'cookies.txt' if os.path.exists("cookies.txt") else None,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios'],
                        'player_skip': ['dash', 'hls']
                    }
                }
            }

            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info.get("title", "Video")

            loop = asyncio.get_running_loop()
            file_path, title = await loop.run_in_executor(None, download)

            await status_msg.edit_text("☁️ **Uploading...**")
            
            target_id = DUMP_CHANNEL if DUMP_CHANNEL != 0 else msg.chat.id
            if quality == "mp3":
                await app.send_audio(target_id, file_path, caption=f"🎵 **{title}**\n👤 {user_mention}")
            else:
                await app.send_video(target_id, file_path, caption=f"🎬 **{title}**\n👤 {user_mention}", supports_streaming=True)

            if DUMP_CHANNEL != 0: await status_msg.edit_text("✅ Sent to Dump!")
            else: await status_msg.delete()
            
            if os.path.exists(file_path): os.remove(file_path)

        except Exception as e:
            await msg.reply_text(f"❌ **Error:** `{str(e)}`")
        
        await asyncio.sleep(2)

    IS_WORKING = False

# HANDLERS
@app.on_message(filters.command("start"))
async def start(c, m): await m.reply_text("Send me a YouTube link!")

@app.on_message(filters.regex(r"https?://.*youtube|youtu\.be"))
async def link_handler(c, m):
    uid = str(uuid.uuid4())[:8]
    URL_STORE[uid] = m.text
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("720p", callback_data=f"add|720|{uid}"), InlineKeyboardButton("480p", callback_data=f"add|480|{uid}")],
        [InlineKeyboardButton("🎵 MP3", callback_data=f"add|mp3|{uid}")]
    ])
    await m.reply_text("Select Quality:", reply_markup=btns)

@app.on_callback_query()
async def cb_handler(c, cb):
    data = cb.data.split("|")
    url = URL_STORE.get(data[2])
    if not url: return await cb.answer("Link Expired!", show_alert=True)
    
    TASK_QUEUE.append({"link": url, "quality": data[1], "msg": cb.message, "user_mention": cb.from_user.mention})
    await cb.message.edit_text("✅ **Added to Queue!**")
    asyncio.create_task(worker())

async def main():
    await app.start()
    await web_server()
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
