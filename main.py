import os
import asyncio
import yt_dlp
import uuid
import shutil
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
#          CONFIG (Apni Details Bharein)
# ==========================================
API_ID = 33675350
API_HASH = "2f97c845b067a750c9f36fec497acf97"
BOT_TOKEN = "8343193883:AAE738x9dK-c4SdMx0N3HeF8XzrTn3plq8A"
PORT = 8000

# ==========================================
#          SETUP
# ==========================================
TASK_QUEUE = []
IS_WORKING = False
URL_STORE = {}

app = Client("leech_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Web Server (Koyeb Health Check ke liye)
async def web_server():
    async def handle(request): return web.Response(text="Leech Bot Running!")
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

# ==========================================
#          WORKER (LEECH ENGINE)
# ==========================================
async def worker():
    global IS_WORKING
    if IS_WORKING: return
    IS_WORKING = True

    while TASK_QUEUE:
        task = TASK_QUEUE.pop(0)
        url, quality, msg, user_mention = task["link"], task["quality"], task["msg"], task["user_mention"]

        try:
            status_msg = await msg.reply_text(f"⚡ **Initializing Leech...**\n`{url}`")
            
            # --- LEECH BOT LOGIC ---
            # Ab hamare paas FFmpeg hai, to hum Best Video + Best Audio merge kar sakte hain
            if quality == "mp3":
                fmt = 'bestaudio/best'
            else:
                fmt = f'bestvideo[height<={quality}]+bestaudio/best/best[height<={quality}]/best'

            ydl_opts = {
                'format': fmt,
                'outtmpl': '%(title)s.%(ext)s',
                'noplaylist': True,
                'quiet': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'writethumbnail': True,
                
                # COOKIES (Most Important)
                'cookiefile': 'cookies.txt' if os.path.exists("cookies.txt") else None,

                # ARIA2C DOWNLOADER (Speed + Bypass)
                'external_downloader': 'aria2c',
                'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M'],

                # FFMPEG MERGING (Video + Audio jodne ke liye)
                'merge_output_format': 'mp4',

                # HEADERS FIX (NoneType Error Hatane ke liye)
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.5',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['dash', 'hls']
                    }
                }
            }

            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info.get("title", "Video")

            # Executing Download
            await status_msg.edit_text("📥 **Leeching with Aria2c...**\n*(High Speed)*")
            loop = asyncio.get_running_loop()
            file_path, title = await loop.run_in_executor(None, download)

            # Verification
            if not file_path or not os.path.exists(file_path):
                raise Exception("Download failed! Cookies might be expired.")

            await status_msg.edit_text("☁️ **Uploading to Telegram...**")
            
            # Thumbnail Logic
            thumb = f"{file_path}.jpg"
            if not os.path.exists(thumb): 
                thumb = file_path.rsplit(".", 1)[0] + ".webp"
            
            if not os.path.exists(thumb): thumb = None

            # Uploading
            if quality == "mp3":
                await app.send_audio(msg.chat.id, file_path, caption=f"🎵 **{title}**\n👤 {user_mention}", thumb=thumb)
            else:
                await app.send_video(msg.chat.id, file_path, caption=f"🎬 **{title}**\n👤 {user_mention}", thumb=thumb, supports_streaming=True)

            await status_msg.delete()
            
            # Cleanup
            if os.path.exists(file_path): os.remove(file_path)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        except Exception as e:
            print(f"Error: {e}")
            await msg.reply_text(f"❌ **Leech Error:** `{str(e)}`")
        
        await asyncio.sleep(2)

    IS_WORKING = False

# ==========================================
#          HANDLERS
# ==========================================
@app.on_message(filters.command("start"))
async def start(c, m):
    await m.reply_text("👋 **Leech Bot Ready!**\nSend me a YouTube link.")

@app.on_message(filters.regex(r"https?://.*youtube|youtu\.be"))
async def link_handler(c, m):
    uid = str(uuid.uuid4())[:8]
    URL_STORE[uid] = m.text
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 1080p", callback_data=f"dl|1080|{uid}"), 
         InlineKeyboardButton("🎬 720p", callback_data=f"dl|720|{uid}")],
        [InlineKeyboardButton("🎬 480p", callback_data=f"dl|480|{uid}"),
         InlineKeyboardButton("🎵 MP3", callback_data=f"dl|mp3|{uid}")]
    ])
    await m.reply_text("Select Quality:", reply_markup=btns)

@app.on_callback_query()
async def cb_handler(c, cb):
    data = cb.data.split("|")
    url = URL_STORE.get(data[2])
    if not url: return await cb.answer("Expired!")
    
    TASK_QUEUE.append({"link": url, "quality": data[1], "msg": cb.message, "user_mention": cb.from_user.mention})
    await cb.message.edit_text("✅ **Added to Queue!**")
    asyncio.create_task(worker())

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(app.start())
    asyncio.get_event_loop().run_until_complete(web_server())
    asyncio.get_event_loop().run_until_complete(idle())
