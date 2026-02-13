import os
import time
import asyncio
import yt_dlp
import shutil
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# ==========================================
#          CONFIG (Environment Variables)
# ==========================================
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Dump Channel ID (e.g., -100123456789)
DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", "0"))

# ==========================================
#          GLOBAL QUEUE SYSTEM
# ==========================================
# Format: {"link": url, "quality": "720", "user_id": 123, "msg": message_object}
TASK_QUEUE = []
IS_WORKING = False

app = Client("yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==========================================
#          HELPER FUNCTIONS
# ==========================================
def humanbytes(size):
    if not size: return "0B"
    power = 2**10
    n = 0
    dic = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power: 
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic[n] + 'B'

async def progress_bar(current, total, status_msg, start_time):
    try:
        now = time.time()
        # Update every 5 seconds only
        if (now - start_time) % 5 == 0 or current == total:
            percentage = current * 100 / total
            speed = current / (now - start_time) if (now - start_time) > 0 else 0
            eta = (total - current) / speed if speed > 0 else 0
            
            text = f"""
Downloading... 📥
📊 <b>Progress:</b> {round(percentage, 2)}%
💾 <b>Size:</b> {humanbytes(current)} / {humanbytes(total)}
🚀 <b>Speed:</b> {humanbytes(speed)}/s
⏳ <b>ETA:</b> {round(eta)} sec
"""
            await status_msg.edit_text(text)
    except:
        pass

# ==========================================
#          WORKER (PROCESSES QUEUE)
# ==========================================
async def worker():
    global IS_WORKING
    if IS_WORKING: return
    IS_WORKING = True

    while TASK_QUEUE:
        # 1. Get Task
        task = TASK_QUEUE.pop(0)
        url = task["link"]
        quality = task["quality"]
        msg = task["msg"]
        user_mention = task["user_mention"]

        try:
            status_msg = await msg.reply_text(f"⏳ <b>Starting Task...</b>\nQueue Left: {len(TASK_QUEUE)}")
            
            # 2. Download Logic
            await status_msg.edit_text("📥 <b>Downloading from YouTube...</b>")
            
            cookie_path = "cookies.txt" if os.path.exists("cookies.txt") else None
            
            # Format Selection
            if quality == "mp3":
                fmt = 'bestaudio/best'
            else:
                fmt = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best'

            ydl_opts = {
                'format': fmt,
                'outtmpl': '%(title)s.%(ext)s',
                'noplaylist': True,
                'cookiefile': cookie_path,
                'writethumbnail': True,
                # New Android Client to fix n-token errors
                'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            }

            loop = asyncio.get_running_loop()
            
            # Run Download in Executor to avoid blocking
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info), info.get("title")

            file_path, title = await loop.run_in_executor(None, download_video)

            # 3. Upload Logic
            await status_msg.edit_text("☁️ <b>Uploading to Telegram...</b>")
            
            thumb_path = f"{file_path}.jpg"
            thumb = thumb_path if os.path.exists(thumb_path) else None
            
            caption = f"🎬 <b>{title}</b>\nRequested by: {user_mention}"
            
            # Upload to Dump Channel or User
            target_id = DUMP_CHANNEL if DUMP_CHANNEL != 0 else msg.chat.id
            
            if quality == "mp3":
                 sent = await app.send_audio(target_id, file_path, caption=caption, thumb=thumb)
            else:
                 sent = await app.send_video(target_id, file_path, caption=caption, thumb=thumb, supports_streaming=True)
            
            # If uploaded to Dump, notify user
            if DUMP_CHANNEL != 0:
                await status_msg.edit_text(f"✅ <b>Done!</b>\nSent to Dump Channel.")
            else:
                await status_msg.delete()

            # Cleanup
            if os.path.exists(file_path): os.remove(file_path)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        except Exception as e:
            await msg.reply_text(f"❌ Error: {str(e)}")
        
        # 4. ONE MINUTE DELAY (Cool-down)
        if TASK_QUEUE:
            await msg.reply_text("💤 <b>Cooling down for 60 seconds...</b>")
            await asyncio.sleep(60)

    IS_WORKING = False

# ==========================================
#          HANDLERS
# ==========================================

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 <b>Send me a YouTube Link!</b>\nI support Playlists & Quality Selection.")

@app.on_message(filters.regex(r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=|embed\/|v\/|shorts\/|playlist\?list=)?([\w\-]+)"))
async def process_link(client, message):
    url = message.text.strip()
    
    # Check if Playlist
    if "playlist" in url:
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download Entire Playlist (Best Quality)", callback_data=f"plist|{url}")]
        ])
        await message.reply_text(f"📂 <b>Playlist Detected!</b>\nSelect action:", reply_markup=buttons)
    else:
        # Single Video
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("1080p", callback_data=f"add|1080|{url}"),
                InlineKeyboardButton("720p", callback_data=f"add|720|{url}")
            ],
            [
                InlineKeyboardButton("480p", callback_data=f"add|480|{url}"),
                InlineKeyboardButton("360p", callback_data=f"add|360|{url}")
            ],
            [
                InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"add|mp3|{url}")
            ]
        ])
        await message.reply_text("🎥 <b>Select Quality:</b>", reply_markup=buttons)

@app.on_callback_query()
async def callback(client, cb):
    data = cb.data.split("|")
    action = data[0]
    
    if action == "add":
        quality = data[1]
        url = data[2] # Note: Simple split might break if URL has |, but YT links usually don't.
        
        TASK_QUEUE.append({
            "link": url,
            "quality": quality,
            "msg": cb.message,
            "user_mention": cb.from_user.mention
        })
        
        await cb.answer(f"✅ Added to Queue! Position: {len(TASK_QUEUE)}")
        await cb.message.edit_text(f"✅ <b>Queued!</b>\nQuality: {quality}\nWaiting for turn...")
        
        # Trigger Worker
        asyncio.create_task(worker())

    elif action == "plist":
        url = data[1]
        await cb.message.edit_text("🔄 <b>Processing Playlist... This may take time.</b>")
        
        # Extract Playlist Links
        try:
            ydl_opts = {'extract_flat': True, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    count = 0
                    for entry in info['entries']:
                        vid_url = f"https://www.youtube.com/watch?v={entry['id']}"
                        TASK_QUEUE.append({
                            "link": vid_url,
                            "quality": "720", # Default for playlist
                            "msg": cb.message,
                            "user_mention": cb.from_user.mention
                        })
                        count += 1
                    
                    await cb.message.edit_text(f"✅ <b>{count} Videos Added to Queue!</b>")
                    asyncio.create_task(worker())
        except Exception as e:
            await cb.message.edit_text(f"❌ Playlist Error: {e}")

# ==========================================
#          RUN
# ==========================================
if __name__ == "__main__":
    print("🤖 YouTube Bot Started...")
    app.run()
      
