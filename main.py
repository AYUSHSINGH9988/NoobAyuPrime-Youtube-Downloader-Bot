import os
import time
import asyncio
import yt_dlp
import shutil
import uuid
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
#          CONFIG
# ==========================================
# Make sure ye environment variables set hon
API_ID = int(os.environ.get("API_ID", "12345")) # Example default, replace properly
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_token")
DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", "0"))
PORT = int(os.environ.get("PORT", "8000"))

# ==========================================
#          STORAGE
# ==========================================
TASK_QUEUE = []
IS_WORKING = False
URL_STORE = {}

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==========================================
#          WEB SERVER
# ==========================================
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is Alive!")

    server = web.Application()
    server.router.add_get("/", handle)
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"✅ Web Server running on Port {PORT}")

# ==========================================
#          WORKER
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
            status_msg = await msg.reply_text(f"⏳ <b>Starting...</b>\nQueue: {len(TASK_QUEUE)}")
            await status_msg.edit_text("📥 <b>Downloading...</b>")
            
            # Cookies Check
            if not os.path.exists("cookies.txt"):
                await status_msg.edit_text("❌ <b>Error:</b> cookies.txt not found!\nUpload cookies.txt to root folder.")
                IS_WORKING = False
                return

            # Format Logic
            if quality == "mp3":
                fmt = 'bestaudio/best'
            else:
                fmt = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best'

            # --- FIX APPLIED HERE ---
            ydl_opts = {
                'format': fmt,
                'outtmpl': '%(title)s.%(ext)s',
                'noplaylist': True,
                'cookiefile': 'cookies.txt',
                'writethumbnail': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'quiet': True,
                # Error Fix 1: User-Agent add kiya
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                },
                # Error Fix 2: 'ios' string format mein (not list)
                'extractor_args': {
                    'youtube': {
                        'player_client': 'ios',
                        'player_skip': 'dash,hls' 
                    }
                }
            }

            loop = asyncio.get_running_loop()
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info.get("title", "Unknown")

            file_path, title = await loop.run_in_executor(None, download_video)

            if not file_path or not os.path.exists(file_path):
                raise Exception("Download Failed! Check Cookies or Link.")

            # Upload
            await status_msg.edit_text("☁️ <b>Uploading...</b>")
            
            # Thumbnail handling
            thumb_path = f"{file_path}.jpg"
            # Kabhi kabhi webp format aata hai, check kar lete hain
            if not os.path.exists(thumb_path):
                thumb_path = file_path.rsplit(".", 1)[0] + ".webp"
            
            thumb = thumb_path if os.path.exists(thumb_path) else None
            caption = f"🎬 <b>{title}</b>\n👤 {user_mention}"
            
            target_id = DUMP_CHANNEL if DUMP_CHANNEL != 0 else msg.chat.id
            
            if quality == "mp3":
                 await app.send_audio(target_id, file_path, caption=caption, thumb=thumb)
            else:
                 await app.send_video(target_id, file_path, caption=caption, thumb=thumb, supports_streaming=True)
            
            if DUMP_CHANNEL != 0:
                await status_msg.edit_text(f"✅ <b>Sent to Dump!</b>")
            else:
                await status_msg.delete()

            # Cleanup
            if os.path.exists(file_path): os.remove(file_path)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        except Exception as e:
            print(f"Error: {e}")
            try: await msg.reply_text(f"❌ Error: {str(e)}")
            except: pass
        
        # Thoda delay taaki server spam na ho
        if TASK_QUEUE:
            await asyncio.sleep(2)

    IS_WORKING = False

# ==========================================
#          HANDLERS
# ==========================================
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("👋 <b>Send YouTube Link!</b>\nMake sure cookies.txt is present.")

@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=|embed\/|v\/|shorts\/|playlist\?list=)?([\w\-]+)"))
async def process_link(client, message):
    url = message.text.strip()
    url_id = str(uuid.uuid4())[:8]
    URL_STORE[url_id] = url
    
    if "playlist" in url:
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download Playlist", callback_data=f"plist|{url_id}")]])
        await message.reply_text(f"📂 <b>Playlist Detected!</b>", reply_markup=btn)
    else:
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("1080p", callback_data=f"add|1080|{url_id}"), InlineKeyboardButton("720p", callback_data=f"add|720|{url_id}")],
            [InlineKeyboardButton("480p", callback_data=f"add|480|{url_id}"), InlineKeyboardButton("🎵 MP3", callback_data=f"add|mp3|{url_id}")]
        ])
        await message.reply_text("🎥 <b>Select Quality:</b>", reply_markup=btn)

@app.on_callback_query()
async def callback(client, cb):
    data = cb.data.split("|")
    action = data[0]
    url_id = data[2]
    url = URL_STORE.get(url_id)
    
    if not url: return await cb.answer("Link Expired!", show_alert=True)

    if action == "add":
        quality = data[1]
        TASK_QUEUE.append({"link": url, "quality": quality, "msg": cb.message, "user_mention": cb.from_user.mention})
        await cb.answer("Added to Queue!")
        await cb.message.edit_text(f"✅ <b>Queued!</b> Quality: {quality}")
        asyncio.create_task(worker())
    
    elif action == "plist":
        await cb.message.edit_text("🔄 <b>Fetching Playlist...</b>")
        try:
            ydl_opts = {'extract_flat': True, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    count = 0
                    for entry in info['entries']:
                        if entry: # Entry check
                            TASK_QUEUE.append({
                                "link": f"https://www.youtube.com/watch?v={entry['id']}",
                                "quality": "720",
                                "msg": cb.message,
                                "user_mention": cb.from_user.mention
                            })
                            count += 1
                    await cb.message.edit_text(f"✅ <b>Added {count} Videos to Queue!</b>")
                    asyncio.create_task(worker())
        except Exception as e:
            await cb.message.edit_text(f"❌ Error: {e}")

# ==========================================
#          MAIN
# ==========================================
async def main():
    print("🤖 Bot Starting...")
    await app.start()
    print("✅ Bot Started!")
    await web_server()
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
