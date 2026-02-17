import os
import asyncio
import yt_dlp
import uuid
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
#          CONFIG (HARDCODED)
# ==========================================
API_ID = 33675350
API_HASH = "2f97c845b067a750c9f36fec497acf97"
BOT_TOKEN = "8343193883:AAE738x9dK-c4SdMx0N3HeF8XzrTn3plq8A"
PORT = 8000

# Storage
TASK_QUEUE = []
IS_WORKING = False
URL_STORE = {}

app = Client("leech_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# WEB SERVER (Platform health check ke liye)
async def web_server():
    async def handle(request): return web.Response(text="Bot is Alive!")
    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
    except:
        pass

# ==========================================
#          CORE DOWNLOADER (Worker)
# ==========================================
async def worker():
    global IS_WORKING
    if IS_WORKING: return
    IS_WORKING = True

    while TASK_QUEUE:
        task = TASK_QUEUE.pop(0)
        url, quality, msg, user_mention = task["link"], task["quality"], task["msg"], task["user_mention"]

        try:
            status_msg = await msg.reply_text("📥 **Downloading...**\n*(Wait for processing)*")
            
            # --- SMART FORMAT LOGIC ---
            # Isse 'Format not available' error nahi aayega
            if quality == "mp3":
                fmt = 'bestaudio/best'
            else:
                # requested quality try karega, agar na mile toh automatic best lega
                fmt = f'bestvideo[height<={quality}]+bestaudio/best/best[height<={quality}]/best'

            ydl_opts = {
                'format': fmt,
                'outtmpl': '%(title)s.%(ext)s',
                'cookiefile': 'cookies.txt' if os.path.exists("cookies.txt") else None,
                'noplaylist': True,
                'quiet': True,
                'nocheckcertificate': True,
                'ignoreerrors': True, # Important to bypass small errors
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['dash', 'hls']
                    }
                }
            }

            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info.get("title", "Video")

            # Running blocking download in executor
            file_path, title = await asyncio.get_running_loop().run_in_executor(None, download)

            if not file_path or not os.path.exists(file_path):
                raise Exception("Download failed or format unsupported.")

            await status_msg.edit_text("☁️ **Uploading...**")
            
            if quality == "mp3":
                await app.send_audio(msg.chat.id, file_path, caption=f"🎵 **{title}**\n👤 {user_mention}")
            else:
                await app.send_video(msg.chat.id, file_path, caption=f"🎬 **{title}**\n👤 {user_mention}", supports_streaming=True)

            await status_msg.delete()
            if os.path.exists(file_path): os.remove(file_path)

        except Exception as e:
            print(f"Error: {e}")
            await msg.reply_text(f"❌ **Error:** `{str(e)}`")
        
        await asyncio.sleep(2)

    IS_WORKING = False

# ==========================================
#          HANDLERS
# ==========================================
@app.on_message(filters.command("start"))
async def start(c, m):
    await m.reply_text("👋 **Bot Online!**\nSend me a YouTube link to download.")

@app.on_message(filters.regex(r"https?://.*youtube|youtu\.be"))
async def link_handler(c, m):
    url = m.text.strip()
    uid = str(uuid.uuid4())[:8]
    URL_STORE[uid] = url
    
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 720p", callback_data=f"dl|720|{uid}"), 
         InlineKeyboardButton("🎬 480p", callback_data=f"dl|480|{uid}")],
        [InlineKeyboardButton("🎵 MP3", callback_data=f"dl|mp3|{uid}")]
    ])
    await m.reply_text("🎥 **Select Quality:**", reply_markup=btns)

@app.on_callback_query()
async def cb_handler(c, cb):
    data = cb.data.split("|")
    action, quality, uid = data[0], data[1], data[2]
    
    url = URL_STORE.get(uid)
    if not url:
        return await cb.answer("Link Expired! Send again.", show_alert=True)
    
    TASK_QUEUE.append({"link": url, "quality": quality, "msg": cb.message, "user_mention": cb.from_user.mention})
    await cb.message.edit_text("✅ **Added to Queue!**\nPlease wait...")
    asyncio.create_task(worker())

async def main():
    print("🤖 Bot is starting...")
    await app.start()
    await web_server()
    print("✅ Bot is Online!")
    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
