import os
import re
import time
import math
import uuid
import logging
import asyncio
import requests
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("PyrogramBot")

# --- CONFIG ---
API_ID = 33675350
API_HASH = "2f97c845b067a750c9f36fec497acf97"
BOT_TOKEN = "8489527645:AAGokjooAXkg2L6qXhr0ThG1rPahxjEUQ5Q"
DOWNLOADS_DIR = "downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

app = Client("my_yt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- SESSIONS MEMORY ---
# Yahan hum short IDs mein URL save karenge taaki 64-byte ki Telegram limit cross na ho
URL_SESSIONS = {}

# --- COOKIES FINDER ---
_base = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = None
for _path in [os.path.join(_base, "cookies.txt"), os.path.expanduser("~/cookies.txt")]:
    if os.path.exists(_path):
        COOKIES_FILE = _path
        break

logger.info(f"Cookies: {COOKIES_FILE or 'NOT FOUND'}")

# --- PROGRESS BAR HELPERS ---
def humanbytes(size):
    if not size: return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0

def time_formatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    tmp = (f"{hours}h, " if hours else "") + (f"{minutes}m, " if minutes else "") + f"{seconds}s"
    return tmp.strip(", ") if tmp else "0s"

async def progress_for_pyrogram(current, total, ud_type, message, start_time):
    now = time.time()
    diff = now - start_time
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        time_to_completion = round((total - current) / speed) * 1000 if speed > 0 else 0
        
        prog = "[{0}{1}]".format('█' * math.floor(percentage / 10), '░' * (10 - math.floor(percentage / 10)))
        text = f"📤 **{ud_type}**\n\n{prog} {round(percentage, 2)}%\n"
        text += f"📦 {humanbytes(current)} of {humanbytes(total)}\n⚡ Speed: {humanbytes(speed)}/s\n⏳ ETA: {time_formatter(time_to_completion)}"
        
        try:
            await message.edit_text(text)
        except Exception:
            pass

class YtDlpProgress:
    def __init__(self, message, loop):
        self.message = message
        self.loop = loop
        self.last_edit = 0
        self.start_time = time.time()

    def hook(self, d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - self.last_edit > 5:
                self.last_edit = now
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                if total > 0:
                    percent = downloaded * 100 / total
                    speed = d.get('speed', 0)
                    eta = d.get('eta', 0)
                    
                    prog = "[{0}{1}]".format('█' * math.floor(percent / 10), '░' * (10 - math.floor(percent / 10)))
                    text = f"⬇️ **Downloading...**\n\n{prog} {percent:.2f}%\n"
                    text += f"📦 {humanbytes(downloaded)} of {humanbytes(total)}\n⚡ Speed: {humanbytes(speed)}/s\n⏳ ETA: {time_formatter(eta * 1000 if eta else 0)}"
                    
                    async def edit():
                        try: await self.message.edit_text(text)
                        except: pass
                    asyncio.run_coroutine_threadsafe(edit(), self.loop)

# --- YT-DLP OPTIONS ---
def get_ydl_opts(fmt: str, output_path: str, progress_tracker=None) -> dict:
    base_opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["web", "tv"]}},
        "remote_components": ["ejs:github"],
    }
    
    if progress_tracker:
        base_opts["progress_hooks"] = [progress_tracker.hook]
        
    if COOKIES_FILE:
        base_opts["cookiefile"] = str(COOKIES_FILE)

    if fmt == "mp3":
        base_opts.update({
            "format": "ba/b",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        })
    elif fmt == "mp4_360":
        base_opts["format"] = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/b"
    elif fmt == "mp4_720":
        base_opts["format"] = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/b"
    elif fmt == "mp4_1080":
        base_opts["format"] = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/b"
    else:
        base_opts["format"] = "bv*+ba/b"
        
    return base_opts

def _blocking_get_info(url: str) -> dict | None:
    try:
        opts = get_ydl_opts("best", None)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error(f"Info extract failed: {e}")
        return None

def download_thumbnail(thumb_url, vid_id):
    if not thumb_url:
        return None
    thumb_path = os.path.join(DOWNLOADS_DIR, f"{vid_id}_thumb.jpg")
    try:
        r = requests.get(thumb_url, stream=True, timeout=10)
        if r.status_code == 200:
            with open(thumb_path, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return thumb_path
    except Exception as e:
        logger.error(f"Failed to download thumbnail: {e}")
    return None

def _blocking_download(url: str, fmt: str, out_path: str, message, loop) -> dict:
    try:
        tracker = YtDlpProgress(message, loop)
        opts = get_ydl_opts(fmt, out_path, tracker)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            actual_file = ydl.prepare_filename(info)
            if fmt == "mp3":
                actual_file = actual_file.rsplit('.', 1)[0] + '.mp3'
                
            if os.path.exists(actual_file) and os.path.getsize(actual_file) > 0:
                duration = info.get("duration", 0)
                thumb_url = info.get("thumbnail")
                vid_id = info.get("id", "video")
                thumb_path = download_thumbnail(thumb_url, vid_id)
                
                return {
                    "filepath": actual_file,
                    "duration": duration,
                    "thumb_path": thumb_path
                }
        return None
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None

# --- BOT HANDLERS ---
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text("👋 Pyrogram Engine Ready! Send me a YouTube link.")

@app.on_message(filters.text & ~filters.command("start"))
async def handle_url(client, message):
    url = message.text.strip()
    if not re.match(r"https?://", url):
        return
    
    status_msg = await message.reply_text("🔍 **Fetching video details...**")
    
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _blocking_get_info, url)
    
    if not info:
        await status_msg.edit_text("❌ Failed to fetch video info. It might be age-restricted or invalid.")
        return
        
    title = info.get("title", "Unknown Video")
    duration = time_formatter(info.get("duration", 0) * 1000)
    
    # Generate a short unique ID (8 chars) and save URL in memory
    uid = uuid.uuid4().hex[:8]
    URL_SESSIONS[uid] = url
    
    # Pass ONLY the short UID in the callback data (Well below 64 bytes)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 MP3 Audio", callback_data=f"dl|mp3|{uid}")],
        [
            InlineKeyboardButton("📺 360p", callback_data=f"dl|mp4_360|{uid}"),
            InlineKeyboardButton("📺 720p", callback_data=f"dl|mp4_720|{uid}"),
            InlineKeyboardButton("🔥 1080p", callback_data=f"dl|mp4_1080|{uid}")
        ]
    ])
    
    await status_msg.edit_text(f"🎬 **{title}**\n⏱ **Duration:** {duration}\n\n🎯 **Select format to download:**", reply_markup=keyboard)

@app.on_callback_query(filters.regex(r"^dl\|"))
async def button_callback(client, query: CallbackQuery):
    data = query.data.split("|")
    fmt = data[1]
    uid = data[2] 
    
    # Retrieve the URL from our memory session
    url = URL_SESSIONS.get(uid)
    if not url:
        await query.answer("❌ Session expired! Please send the link again.", show_alert=True)
        return
    
    prog_msg = await query.message.edit_text(f"⏳ **Initializing Download...**\nFormat: `{fmt}`")
    
    loop = asyncio.get_event_loop()
    video_id = re.search(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})", url)
    vid = video_id.group(1) if video_id else "video"
    out_path = os.path.join(DOWNLOADS_DIR, f"{vid}_%(title)s.%(ext)s")
    
    result = await loop.run_in_executor(None, _blocking_download, url, fmt, out_path, prog_msg, loop)
    
    if not result:
        await prog_msg.edit_text("❌ Download failed! (Format unavailable or IP Blocked)")
        return
        
    final_file = result["filepath"]
    duration = result["duration"]
    thumb_path = result["thumb_path"]
    
    await prog_msg.edit_text("📤 **Preparing to Upload...**")
    
    try:
        file_size = os.path.getsize(final_file)
        if file_size > 2000 * 1024 * 1024:
            await prog_msg.edit_text("❌ File is larger than 2GB!")
        else:
            if fmt == "mp3":
                await client.send_audio(
                    chat_id=query.message.chat.id, 
                    audio=final_file,
                    duration=duration,
                    thumb=thumb_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Uploading Audio...", prog_msg, time.time())
                )
            else:
                await client.send_video(
                    chat_id=query.message.chat.id, 
                    video=final_file, 
                    duration=duration,
                    thumb=thumb_path,
                    supports_streaming=True,
                    progress=progress_for_pyrogram,
                    progress_args=("Uploading Video...", prog_msg, time.time())
                )
            await prog_msg.delete()
    except Exception as e:
        await prog_msg.edit_text(f"❌ Upload error: {str(e)[:100]}")
    finally:
        # Cleanup video, thumbnail, and memory session
        if final_file and os.path.exists(final_file):
            os.remove(final_file)
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
        if uid in URL_SESSIONS:
            del URL_SESSIONS[uid]

if __name__ == "__main__":
    logger.info("✅ Pyrogram Bot is running...")
    app.run()
