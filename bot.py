import os
import re
import time
import json
import logging
import asyncio
import aiohttp
import subprocess
import sys
import urllib.request
import email.utils
import calendar
import requests
import urllib3
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------- Time Sync Monkeypatch -----------------
try:
    req = urllib.request.Request('https://www.google.com', method='HEAD')
    with urllib.request.urlopen(req, timeout=5) as res:
        date_str = res.headers['date']
        server_time = calendar.timegm(email.utils.parsedate(date_str))
        local_time = time.time()
        offset = int(server_time - local_time)
        if abs(offset) > 10:
            real_time = time.time
            time.time = lambda: real_time() + offset
            if 'time' in sys.modules:
                sys.modules['time'].time = lambda: real_time() + offset
            print(f"[Time Sync] Successfully synchronized system time offset: {offset}s")
except Exception as e:
    print(f"[Time Sync Warning] Clock synchronization skipped: {e}")
# ---------------------------------------------------------

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

API_ID = int(os.environ.get("API_ID", 26039838))
API_HASH = os.environ.get("API_HASH", "043c4fc28f7825c84bca454900645fba")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8801935577:AAGEehNQczG7pS9-3hejpFzphOFS2xz-L6o")

# Create unique session with ultra-fast multi-channel transmission
session_name = "classx_downloader_session"
app = Client(
    session_name,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50,
    max_concurrent_transmissions=20
)

# Progress Tracking & Task Cancellation State
running_tasks = {}
last_update_time = {}
user_sessions = {}

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def cleanup_stray_media():
    if os.path.exists(DOWNLOAD_DIR):
        for filename in os.listdir(DOWNLOAD_DIR):
            if not filename.endswith(".json"):
                file_p = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(file_p):
                    try:
                        os.remove(file_p)
                    except:
                        pass

# Run startup cleanup
cleanup_stray_media()

def get_readable_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0

def make_progress_bar(percent):
    filled = min(20, int(percent / 5))
    return "█" * filled + "░" * (20 - filled)

def format_size(bytes_val):
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.2f} KB"
    return f"{bytes_val / (1024 * 1024):.2f} MB"

def format_speed(bytes_per_sec):
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.2f} KiB/s"
    return f"{bytes_per_sec / (1024 * 1024):.2f} MiB/s"

def format_eta(seconds):
    if seconds <= 0 or seconds > 86400:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def build_mirror_progress_box(batch_name, topic_name, item_title, status_text, percent, downloaded_bytes, total_bytes, speed_bytes, eta_sec, is_downloading=True):
    bar = make_progress_bar(percent)
    done_str = format_size(downloaded_bytes)
    total_str = format_size(total_bytes) if total_bytes > 0 else "Unknown"
    speed_str = format_speed(speed_bytes)
    eta_str = format_eta(eta_sec)
    remaining_bytes = max(0, total_bytes - downloaded_bytes) if total_bytes > 0 else 0
    rem_str = format_size(remaining_bytes)

    header_icon = "📥 Mirroring Progress (Downloading) 📥" if is_downloading else "📤 Mirroring Progress (Uploading) 📤"

    text = (
        f"{header_icon}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎓 <b>Batch</b> : {batch_name}\n"
        f"📂 <b>Chapter</b> : {topic_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 <b>Active Item</b> : {item_title[:45]}\n"
        f"⚡ <b>Status</b> : {status_text}\n"
        f"📈 <b>Progress</b> : {percent:.1f}%\n\n"
        f"🌀 <b>प्रगति</b> : [{bar}] {percent:.1f}%\n"
        f"💾 <b>साइज</b> : {done_str} / {total_str}\n"
        f"⚡ <b>गति</b> : {speed_str} | ⏳ <b>ETA</b> : {eta_str}\n"
        f"📂 <b>बाकी साइज</b> : {rem_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    return text

class PyrogramUploadProgress:
    def __init__(self, status_msg: Message, title: str, batch: str, topic: str, item_id: str, loop):
        self.status_msg = status_msg
        self.title = title
        self.batch = batch
        self.topic = topic
        self.item_id = item_id
        self.loop = loop
        self.last_update = 0
        self.start_time = time.time()

    def __call__(self, current, total):
        user_id = str(self.status_msg.chat.id)
        if not running_tasks.get(user_id, True):
            raise Exception("Upload cancelled by user.")

        now = time.time()
        if now - self.last_update > 3 or current == total:
            self.last_update = now
            elapsed = now - self.start_time
            speed = current / elapsed if elapsed > 0 else 0
            percent = (current / total * 100) if total else 0
            remaining_bytes = max(0, total - current) if total else 0
            eta_sec = int(remaining_bytes / speed) if speed > 0 else 0

            box_text = build_mirror_progress_box(
                batch_name=self.batch,
                topic_name=self.topic,
                item_title=f"[{self.item_id}] {self.title}",
                status_text="📤 Uploading to Telegram...",
                percent=percent,
                downloaded_bytes=current,
                total_bytes=total,
                speed_bytes=speed,
                eta_sec=eta_sec,
                is_downloading=False
            )

            async def edit_msg():
                cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Cancel Process", callback_data="dl_cancel_active")]])
                try:
                    await self.status_msg.edit_text(box_text, parse_mode=enums.ParseMode.HTML, reply_markup=cancel_markup)
                except Exception:
                    pass

            asyncio.run_coroutine_threadsafe(edit_msg(), self.loop)

def parse_study_mate_format(text_content):
    topic_blocks = text_content.split("===================================================================================================================")
    if len(topic_blocks) <= 1:
        topic_blocks = text_content.split("==========================================================================================")
    
    items = []

    for block in topic_blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue

        topic_name = "General Module"
        for line in lines:
            if line.startswith("📁"):
                t_clean = re.sub(r"^📁\s*\[\d+\]\s*", "", line)
                topic_name = re.sub(r"\s*\(Topic ID:.*?\)", "", t_clean).strip()
                break
            elif "TOPIC " in line and ":" in line:
                t_clean = line.split(":", 1)[1].strip()
                topic_name = re.sub(r"\s*\(Topic ID:.*?\)", "", t_clean).strip()
                break

        mode = None
        i = 0
        while i < len(lines):
            line = lines[i]
            if "LECTURES / CLASSES" in line or "CLASSES / VIDEOS" in line:
                mode = "video"
                i += 1
                continue
            elif "STUDY NOTES / PDFs" in line or "STUDY NOTES" in line:
                mode = "pdf"
                i += 1
                continue

            m = re.match(r"^\[?\d+\]?\.?\s*(.+)", line)
            if m and mode:
                title = m.group(1).strip()
                item_date = ""
                item_url = ""

                j = i + 1
                while j < len(lines) and not re.match(r"^\[?\d+\]?\.?\s*", lines[j]) and not "STUDY NOTES" in lines[j] and not "CLASSES" in lines[j] and not "LECTURES" in lines[j]:
                    sub = lines[j]
                    if "📅 Date:" in sub or "Published Date:" in sub:
                        item_date = re.sub(r"^(?:📅 Date:|Published Date:)\s*", "", sub).strip()
                    elif "🎬 Video Stream Link:" in sub or "Video Link:" in sub:
                        item_url = re.sub(r"^(?:🎬 Video Stream Link:|Video Link:)\s*", "", sub).strip()
                    elif "📄 Lecture PDF:" in sub:
                        lec_pdf = sub.replace("📄 Lecture PDF:", "").strip()
                        if lec_pdf:
                            items.append({
                                "id": f"{len(items)+1:03d}",
                                "title": f"{title} (Lecture Notes)",
                                "full_title": f"{title} (Lecture Notes)",
                                "type": "pdf",
                                "url": lec_pdf,
                                "key": None,
                                "batch": "Study-Mate Batch",
                                "subject": topic_name,
                                "date": item_date,
                                "class_title": f"{title} (Lecture Notes)"
                            })
                    elif "📥 Direct PDF Download:" in sub or "📥 PDF Link:" in sub or "PDF Link:" in sub:
                        item_url = re.sub(r"^(?:📥\s*)?(?:Direct PDF Download|PDF Link):\s*", "", sub).strip()
                    j += 1

                i = j - 1
                if item_url:
                    items.append({
                        "id": f"{len(items)+1:03d}",
                        "title": title,
                        "full_title": title,
                        "type": mode,
                        "url": item_url,
                        "key": None,
                        "batch": "Study-Mate Batch",
                        "subject": topic_name,
                        "date": item_date,
                        "class_title": title
                    })
            i += 1

    return items

def parse_index_content(text_content):
    # 1. Check if Study-Mate format
    if ("📁" in text_content or "STUDY NOTES / PDFs" in text_content or "STUDY MATE - BATCH" in text_content) and ("--- CLASSES" in text_content or "--- STUDY NOTES" in text_content or "LECTURES / CLASSES" in text_content):
        res = parse_study_mate_format(text_content)
        if res:
            return res

    # 2. Check if Structured Block / Key-Value format (Index:, Name:, Topic:, M3U8:, Batch:, etc.)
    has_index = bool(re.search(r'^\s*Index\s*:\s*\d+', text_content, re.MULTILINE | re.IGNORECASE))
    has_m3u8_field = bool(re.search(r'^\s*(?:M3U8|Video|Stream|Link|URL|PDF)\s*:\s*https?://', text_content, re.MULTILINE | re.IGNORECASE))
    
    if has_index and has_m3u8_field:
        global_batch = None
        batch_m = re.search(r'^(?:Batch|Course|Course Name)\s*:\s*(.+)$', text_content, re.MULTILINE | re.IGNORECASE)
        if batch_m:
            global_batch = batch_m.group(1).strip()
            global_batch = re.sub(r'\(ID:\s*\d+\)', '', global_batch).strip()

        global_date = None
        date_m = re.search(r'^(?:Extracted on|Date)\s*:\s*(.+)$', text_content, re.MULTILINE | re.IGNORECASE)
        if date_m:
            global_date = date_m.group(1).strip()

        blocks = re.split(r'[━=─#-]{5,}', text_content)
        items = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            url_m = re.search(r'(https?://[^\s\n\r*]+)', block)
            if not url_m:
                continue

            raw_url = url_m.group(1).strip()
            key = None
            if "*" in raw_url:
                raw_url, key = raw_url.rsplit("*", 1)

            idx_m = re.search(r'^(?:Index|ID|No)\s*:\s*([^\n\r]+)', block, re.MULTILINE | re.IGNORECASE)
            name_m = re.search(r'^(?:Name|Title|Class|Lecture Name|Lecture)\s*:\s*([^\n\r]+)', block, re.MULTILINE | re.IGNORECASE)
            topic_m = re.search(r'^(?:Topic|Subject|Chapter|Module)\s*:\s*([^\n\r]+)', block, re.MULTILINE | re.IGNORECASE)
            batch_m_local = re.search(r'^(?:Batch|Course)\s*:\s*([^\n\r]+)', block, re.MULTILINE | re.IGNORECASE)

            item_id = idx_m.group(1).strip() if idx_m else f"{len(items)+1:03d}"
            
            item_topic = "General Module"
            if topic_m:
                item_topic = topic_m.group(1).strip()
            
            item_batch = global_batch or "Classx Consolidated Batch"
            if batch_m_local:
                item_batch = batch_m_local.group(1).strip()

            if name_m:
                item_name = name_m.group(1).strip()
            else:
                item_name = f"Class {item_id}"

            item_type = "pdf" if raw_url.lower().endswith(".pdf") or "PDF:" in block else "video"

            clean_display_title = item_name
            if item_topic and item_topic != "General Module":
                clean_display_title = f"{item_topic} - {item_name}"

            items.append({
                "id": item_id,
                "title": item_name,
                "full_title": clean_display_title,
                "url": raw_url,
                "key": key,
                "type": item_type,
                "batch": item_batch,
                "subject": item_topic,
                "date": global_date or "N/A",
                "class_title": item_name
            })

        if items:
            return items

    # 3. Line-by-line parser (handles Topic headings, Course:, Subject:, Title:, and simple 'Title: URL')
    resources = []
    date_match = re.search(r'Date:\s*([0-9\-\/]+)', text_content, re.IGNORECASE)
    date_str = date_match.group(1).strip() if date_match else ""

    lines = text_content.split("\n")
    current_course = ""
    current_subject = ""
    current_title = ""

    # Check top batch
    top_batch_m = re.search(r'^(?:Batch|Course|Course Name)\s*:\s*(.+)$', text_content, re.MULTILINE | re.IGNORECASE)
    if top_batch_m:
        current_course = top_batch_m.group(1).strip()
        current_course = re.sub(r'\(ID:\s*\d+\)', '', current_course).strip()

    for idx, line in enumerate(lines, 1):
        line_strip = line.strip()
        if not line_strip or line_strip.startswith("===") or line_strip.startswith("---") or line_strip.startswith("###") or line_strip.startswith("━"):
            continue

        if re.match(r'^(?:Course|Batch|Course Name)\s*:\s*', line_strip, re.IGNORECASE):
            parts = re.split(r'^(?:Course|Batch|Course Name)\s*:\s*', line_strip, flags=re.IGNORECASE)
            course_val = parts[1].strip()
            course_val = re.sub(r'\(ID:\s*\d+\)', '', course_val).strip()
            current_course = course_val
            continue

        if re.match(r'^(?:Subject|Topic|Chapter|Module)\s*:\s*', line_strip, re.IGNORECASE):
            parts = re.split(r'^(?:Subject|Topic|Chapter|Module)\s*:\s*', line_strip, flags=re.IGNORECASE)
            current_subject = parts[1].strip()
            continue

        if re.match(r'^(?:Title|Name|Lecture Name)\s*:\s*', line_strip, re.IGNORECASE):
            parts = re.split(r'^(?:Title|Name|Lecture Name)\s*:\s*', line_strip, flags=re.IGNORECASE)
            current_title = parts[1].strip()
            continue

        # If line does not have http, it might be a section topic heading
        if "http" not in line_strip and len(line_strip) < 100:
            if not line_strip.startswith("Index:") and not line_strip.startswith("Summary:"):
                current_subject = line_strip
            continue

        if "http" in line_strip:
            http_idx = line_strip.find("http")
            url_part = line_strip[http_idx:].strip()
            prefix = line_strip[:http_idx].strip(" :|-")

            key = None
            if "*" in url_part:
                url, key = url_part.rsplit("*", 1)
                url = url.strip()
                key = key.strip()
            else:
                url = url_part

            item_type = "pdf" if url.lower().endswith(".pdf") else "video"

            # Clean prefix if it's just a protocol or tag word
            if prefix.lower() in ["m3u8", "url", "link", "pdf", "video", "stream", "download", "direct pdf download", "pdf link"]:
                prefix = ""

            item_title = current_title or prefix
            if not item_title:
                item_title = f"Class {len(resources)+1}"

            # Clean title
            item_title = re.sub(r'^\d+[\.\s]*-*\s*', '', item_title).strip()
            if not item_title:
                item_title = f"Item {len(resources)+1}"

            display_title = item_title
            if len(display_title) > 120:
                display_title = display_title[:117] + "..."

            resources.append({
                "id": f"{len(resources)+1:03d}",
                "title": item_title,
                "full_title": f"{current_subject} - {item_title}" if current_subject else item_title,
                "url": url,
                "key": key,
                "type": item_type,
                "batch": current_course or "Classx Consolidated Batch",
                "subject": current_subject or "General Module",
                "date": date_str or "N/A",
                "class_title": item_title
            })

            current_title = ""

    return resources

def extract_from_txt_file(file_path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return parse_index_content(content)

async def download_file_direct(url, file_path, status_msg, title, batch, topic, item_id, user_id, loop):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
    }
    
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504]))
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Multi-Thread segmented download for speed
    def run_multi_thread():
        try:
            head_resp = session.head(url, headers=headers, timeout=15, allow_redirects=True, verify=False)
            total_size = int(head_resp.headers.get('content-length', 0))
            accept_ranges = head_resp.headers.get('accept-ranges', '') == 'bytes' or total_size > 5 * 1024 * 1024
        except Exception:
            total_size = 0
            accept_ranges = False

        if total_size <= 2 * 1024 * 1024 or not accept_ranges:
            with session.get(url, headers=headers, stream=True, timeout=60, verify=False) as r:
                r.raise_for_status()
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if not running_tasks.get(user_id, True):
                            raise Exception("Download cancelled by user.")
                        if chunk: f.write(chunk)
            return True

        with open(file_path, 'wb') as f:
            f.truncate(total_size)

        num_threads = 50
        part_size = total_size // num_threads
        ranges = []
        for i in range(num_threads):
            start = i * part_size
            end = total_size - 1 if i == num_threads - 1 else (start + part_size - 1)
            ranges.append((start, end))

        downloaded_chunks = [0] * num_threads
        start_time = time.time()
        last_edit = [0]

        def download_range(thread_idx, start_byte, end_byte):
            req_headers = headers.copy()
            req_headers['Range'] = f"bytes={start_byte}-{end_byte}"
            with session.get(url, headers=req_headers, stream=True, timeout=60, verify=False) as r:
                r.raise_for_status()
                with open(file_path, 'r+b') as f:
                    f.seek(start_byte)
                    for chunk in r.iter_content(chunk_size=512*1024):
                        if not running_tasks.get(user_id, True):
                            raise Exception("Download cancelled by user.")
                        if chunk:
                            f.write(chunk)
                            downloaded_chunks[thread_idx] += len(chunk)

                            now = time.time()
                            if now - last_edit[0] >= 3.0:
                                total_dl = sum(downloaded_chunks)
                                elapsed = now - start_time
                                speed = total_dl / elapsed if elapsed > 0 else 0
                                remaining = total_size - total_dl
                                eta = remaining / speed if speed > 0 else 0
                                percent = (total_dl / total_size * 100) if total_size > 0 else 0

                                box_text = build_mirror_progress_box(
                                    batch_name=batch,
                                    topic_name=topic,
                                    item_title=f"[{item_id}] {title}",
                                    status_text="📥 Downloading...",
                                    percent=percent,
                                    downloaded_bytes=total_dl,
                                    total_bytes=total_size,
                                    speed_bytes=speed,
                                    eta_sec=eta,
                                    is_downloading=True
                                )

                                async def edit_ui():
                                    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Cancel Process", callback_data="dl_cancel_active")]])
                                    try:
                                        await status_msg.edit_text(box_text, parse_mode=enums.ParseMode.HTML, reply_markup=cancel_markup)
                                    except Exception:
                                        pass

                                asyncio.run_coroutine_threadsafe(edit_ui(), loop)
                                last_edit[0] = now

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(download_range, i, r[0], r[1]) for i, r in enumerate(ranges)]
            for fut in as_completed(futures):
                fut.result()

        return os.path.exists(file_path) and os.path.getsize(file_path) == total_size

    await asyncio.to_thread(run_multi_thread)

async def download_hls_video(url, file_path, status_msg, title, batch, topic, item_id, user_id, loop):
    last_update = 0
    start_time = time.time()

    def hook(d):
        nonlocal last_update
        if not running_tasks.get(user_id, True):
            raise Exception("Download cancelled by user.")

        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update > 3 or d.get('status') == 'finished':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                speed = d.get('speed', 0) or 0
                eta = d.get('eta', 0) or 0
                percent = (downloaded / total * 100) if total else 0

                box_text = build_mirror_progress_box(
                    batch_name=batch,
                    topic_name=topic,
                    item_title=f"[{item_id}] {title}",
                    status_text="📥 Downloading video stream...",
                    percent=percent,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed_bytes=speed,
                    eta_sec=eta,
                    is_downloading=True
                )

                async def do_edit():
                    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Cancel Process", callback_data="dl_cancel_active")]])
                    try:
                        await status_msg.edit_text(box_text, parse_mode=enums.ParseMode.HTML, reply_markup=cancel_markup)
                    except:
                        pass

                asyncio.run_coroutine_threadsafe(do_edit(), loop)
                last_update = now

    clean_url = url.strip()
    if "youtube.com/embed/" in clean_url:
        vid_id = clean_url.split("youtube.com/embed/")[1].split("?")[0].split("&")[0].split("/")[0]
        clean_url = f"https://www.youtube.com/watch?v={vid_id}"
    elif "youtu.be/" in clean_url:
        vid_id = clean_url.split("youtu.be/")[1].split("?")[0].split("&")[0].split("/")[0]
        clean_url = f"https://www.youtube.com/watch?v={vid_id}"

    # Auto fallback list for stream resolution parameters (e.g. liveclasses.cloud-front.in)
    urls_to_try = [clean_url]
    if "txCodecTempName=" in clean_url:
        for res in ["720p", "480p", "360p"]:
            alt = re.sub(r'txCodecTempName=\w+', f'txCodecTempName={res}', clean_url)
            if alt not in urls_to_try:
                urls_to_try.append(alt)
        alt_no_res = re.sub(r'&?txCodecTempName=\w+', '', clean_url)
        if alt_no_res not in urls_to_try:
            urls_to_try.append(alt_no_res)

    base_target = file_path.rsplit('.', 1)[0]
    outtmpl_pattern = f"{base_target}.%(ext)s"

    ydl_opts = {
        'outtmpl': outtmpl_pattern,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'retries': 10,
        'fragment_retries': 10,
        'extractor_retries': 5,
        'socket_timeout': 30,
        'progress_hooks': [hook],
        'concurrent_fragment_downloads': 50,
        'buffersize': 16 * 1024 * 1024,
        'http_chunk_size': 10485760,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': clean_url,
        }
    }

    def run_ytdlp():
        import yt_dlp
        last_err = None
        for try_url in urls_to_try:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([try_url])

                if not os.path.exists(file_path):
                    for ext in ['.mp4', '.mkv', '.webm', '.ts']:
                        alt_path = base_target + ext
                        if os.path.exists(alt_path):
                            if alt_path != file_path:
                                try:
                                    os.rename(alt_path, file_path)
                                except Exception:
                                    pass
                            break

                if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
                    return
            except Exception as e:
                last_err = e
                logger.warning(f"Failed stream download for {try_url}: {e}")
                continue

        if last_err and not os.path.exists(file_path):
            raise last_err

    await asyncio.to_thread(run_ytdlp)

def get_video_metadata_and_thumb(video_path):
    duration = 0
    width = 320
    height = 180
    thumb_path = None

    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        val = res.stdout.strip()
        if val and val.lower() != "n/a":
            duration = int(float(val))
    except Exception:
        pass

    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width") or stream.get("coded_width") or 320)
                height = int(stream.get("height") or stream.get("coded_height") or 180)
                break
    except:
        pass

    try:
        base_name = video_path.rsplit(".", 1)[0]
        thumb_candidate = f"{base_name}_thumb.jpg"
        cmd = ["ffmpeg", "-ss", "00:00:02", "-i", video_path, "-vframes", "1", "-q:v", "2", thumb_candidate, "-y"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=True)
        if os.path.exists(thumb_candidate):
            thumb_path = thumb_candidate
    except:
        pass

    return duration, width, height, thumb_path

CONFIG_FILE = "config.json"

def load_user_config(user_id):
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                return config.get(str(user_id), {})
        except Exception:
            pass
    return {}

def save_user_config(user_id, user_config):
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
        except Exception:
            pass
    config[str(user_id)] = user_config
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def get_dest_chat_id(user_id, default_chat_id):
    user_config = load_user_config(user_id)
    target = user_config.get("target_channel", default_chat_id)
    if isinstance(target, str):
        target = target.strip()
        if target.startswith("-100") or (target.startswith("-") and target[1:].isdigit()) or target.isdigit():
            try:
                return int(target)
            except Exception:
                pass
    return target

async def process_batch_resources(client, chat_id, resources, status_msg, custom_batch_name=None):
    user_id = str(chat_id)
    running_tasks[user_id] = True
    total = len(resources)

    await status_msg.edit_text(f"🚀 **Batch setup complete!**\nProcessing **{total}** items...")
    await asyncio.sleep(1)

    cancel_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Cancel Process", callback_data="dl_cancel_active")]])
    loop = asyncio.get_running_loop()

    for idx, item in enumerate(resources, 1):
        if not running_tasks.get(user_id, True):
            await client.send_message(chat_id, "🛑 **Task Cancelled!** Batch process has been stopped by the user.")
            break

        title = item['title']
        url = item['url']
        item_id = item['id']
        batch = custom_batch_name or item.get('batch') or "Study-Mate Batch"
        topic = item.get('subject') or "General Module"
        item_type = item.get('type', 'video')

        # Check if YouTube link -> send link directly without downloading
        is_youtube = ("youtube.com" in url.lower() or "youtu.be" in url.lower())
        if is_youtube:
            dest_chat_id = get_dest_chat_id(user_id, chat_id)

            yt_watch_url = url.strip()
            if "youtube.com/embed/" in yt_watch_url:
                vid_id = yt_watch_url.split("youtube.com/embed/")[1].split("?")[0].split("&")[0].split("/")[0]
                yt_watch_url = f"https://www.youtube.com/watch?v={vid_id}"
            elif "youtu.be/" in yt_watch_url:
                vid_id = yt_watch_url.split("youtu.be/")[1].split("?")[0].split("&")[0].split("/")[0]
                yt_watch_url = f"https://www.youtube.com/watch?v={vid_id}"

            caption_text = (
                f"🎬 <b>Vid ID</b> : {item_id}\n"
                f"📌 <b>Video Title</b> : {title}\n"
                f"<blockquote>📚 Topic Name : {topic}</blockquote>\n"
                f"<blockquote>🎓 Batch Name : {batch}</blockquote>\n\n"
                f"🔗 <b>YouTube Link:</b> {yt_watch_url}"
            )

            yt_btn = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Watch On YouTube", url=yt_watch_url)]])

            try:
                await client.send_message(
                    chat_id=dest_chat_id,
                    text=caption_text,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=yt_btn,
                    disable_web_page_preview=False
                )
                await status_msg.edit_text(
                    f"⚡ <b>Item [{idx}/{total}] Processed</b>\n"
                    f"📌 <b>Title:</b> <code>{title[:40]}</code>\n"
                    f"🔗 <i>YouTube link directly sent!</i>",
                    parse_mode=enums.ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error sending YouTube link: {e}")
                await client.send_message(
                    chat_id=chat_id,
                    text=f"❌ **Failed to send YouTube link [{idx}/{total}]**\n📝 `{title}`\n⚠️ `{str(e)}`"
                )
            await asyncio.sleep(0.5)
            continue

        ext = ".pdf" if item_type == "pdf" else ".mp4"
        safe_file_path = os.path.join(DOWNLOAD_DIR, f"{user_id}_{item_id}{ext}")
        thumb_path = None
        file_path = None

        try:
            # 1. Download with multi-threading / HLS / yt-dlp
            is_stream_or_video = (
                item_type == "video" or
                ".m3u8" in url.lower() or
                ".mpd" in url.lower() or
                "youtube.com" in url.lower() or
                "youtu.be" in url.lower() or
                "vimeo.com" in url.lower() or
                not url.lower().endswith(".pdf")
            )
            if is_stream_or_video and item_type != "pdf":
                try:
                    await download_hls_video(url, safe_file_path, status_msg, title, batch, topic, item_id, user_id, loop)
                except Exception as e:
                    if not os.path.exists(safe_file_path):
                        logger.warning(f"yt-dlp stream download failed, attempting direct download fallback for {url}: {e}")
                        await download_file_direct(url, safe_file_path, status_msg, title, batch, topic, item_id, user_id, loop)
                    else:
                        raise e
            else:
                await download_file_direct(url, safe_file_path, status_msg, title, batch, topic, item_id, user_id, loop)

            if not os.path.exists(safe_file_path):
                raise Exception("Downloaded file not found on disk.")

            # 2. Metadata & Rename
            duration = 0
            width = 854
            height = 480

            if item_type == "video":
                duration, width, height, thumb_path = get_video_metadata_and_thumb(safe_file_path)

            clean_name = re.sub(r'[\\/*?:"<>|]', '', title)[:60]
            file_path = os.path.join(DOWNLOAD_DIR, f"{item_id}_{clean_name}{ext}")
            if os.path.exists(safe_file_path):
                os.rename(safe_file_path, file_path)

            # 3. Exact Screenshot Caption format
            id_prefix = "🎬 Vid ID" if item_type == 'video' else "📄 Doc ID"
            title_prefix = "📌 Video Title" if item_type == 'video' else "📌 Note Title"
            display_title = f"{title} [{width}x{height}p]{ext}" if item_type == 'video' else f"{title}{ext}"

            caption_text = (
                f"{id_prefix} : {item_id}\n"
                f"{title_prefix} : {display_title}\n"
                f"<blockquote>📚 Topic Name : {topic}</blockquote>\n"
                f"<blockquote>🎓 Batch Name : {batch}</blockquote>"
            )

            upload_progress = PyrogramUploadProgress(status_msg, title, batch, topic, item_id, loop)
            dest_chat_id = get_dest_chat_id(user_id, chat_id)

            if item_type == "pdf":
                await client.send_document(
                    chat_id=dest_chat_id,
                    document=file_path,
                    caption=caption_text,
                    parse_mode=enums.ParseMode.HTML,
                    progress=upload_progress
                )
            else:
                await client.send_video(
                    chat_id=dest_chat_id,
                    video=file_path,
                    caption=caption_text,
                    parse_mode=enums.ParseMode.HTML,
                    supports_streaming=True,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumb_path,
                    progress=upload_progress
                )

            # Cleanup
            if thumb_path and os.path.exists(thumb_path):
                try: os.remove(thumb_path)
                except: pass
            if file_path and os.path.exists(file_path):
                try: os.remove(file_path)
                except: pass

        except Exception as e:
            logger.error(f"Error on {title}: {e}")
            await client.send_message(
                chat_id=chat_id,
                text=f"❌ **Task Failed [{idx}/{total}]**\n"
                     f"📝 **Title:** `{title}`\n"
                     f"⚠️ **Error:** `{str(e)}`"
            )
            cleanup_stray_media()
            continue

    cleanup_stray_media()
    if running_tasks.get(user_id, True):
        await status_msg.edit_text(
            f"🎉 **Batch Complete!**\n\n"
            f"✅ **Total processed:** `{total}` items.\n"
            f"🧹 All files uploaded and storage cleaned!"
        )
    running_tasks[user_id] = False

# Commands & Handlers
# Keyboards & Commands
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 Start / Send TXT"), KeyboardButton("📢 Set Channel")],
        [KeyboardButton("🛑 Stop Task"), KeyboardButton("⚙️ Settings")]
    ],
    resize_keyboard=True
)

@app.on_message(filters.command("start") | filters.regex(r"^(🚀 Start|🔄 Refresh|🚀 Start / Send TXT)$"))
async def start_cmd(client, message):
    user_id = str(message.chat.id)
    user_config = load_user_config(user_id)
    ch_info = user_config.get("target_channel", "Direct Private Chat")
    
    await message.reply_text(
        "👋 **Welcome to Course Batch Downloader & Uploader Bot!**\n\n"
        "📥 **Kaise Use Karein:**\n"
        "1. Mujhe koi bhi Batch / Course ki `.txt` file bhejain.\n"
        "2. Main aapse **Batch Name** puchunga.\n"
        "3. Range choose karein (e.g. 1-20, 21-50, ya Custom).\n"
        "4. Auto-detected topics, custom thumbnails aur exact blockquote layout ke sath video/pdf upload ho jayegi!\n\n"
        f"📢 **Current Target Channel:** <code>{ch_info}</code>\n\n"
        "👉 **Kripya apni TXT file yahan send karein!**",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD
    )

@app.on_message(filters.command(["channel", "setchannel"]) | filters.regex(r"^📢 Set Channel$"))
async def set_channel_cmd(client, message):
    user_id = str(message.chat.id)
    args = message.text.split() if message.text else []

    # If argument provided like /setchannel @mychannel or /setchannel -100123...
    if len(args) >= 2:
        target = args[1].strip()
        if target.lower() == "reset":
            user_config = load_user_config(user_id)
            user_config.pop("target_channel", None)
            save_user_config(user_id, user_config)
            await message.reply_text("✅ Target channel reset. Videos will be sent directly to this chat.", reply_markup=MAIN_KEYBOARD)
            return

        status_msg = await message.reply_text("⏳ Verifying channel access...")
        try:
            target_id = int(target) if target.startswith("-100") or (target.startswith("-") and target[1:].isdigit()) else target
            chat = await client.get_chat(target_id)
            user_config = load_user_config(user_id)
            user_config["target_channel"] = chat.id
            save_user_config(user_id, user_config)

            await status_msg.edit_text(
                f"✅ **Target Channel Set Successfully!**\n\n"
                f"📢 **Name:** `{chat.title}`\n"
                f"🆔 **ID:** `{chat.id}`\n\n"
                f"🚀 Ab sabhi videos/PDFs is channel par automatically upload hongi!",
                reply_markup=MAIN_KEYBOARD
            )
        except Exception as e:
            await status_msg.edit_text(
                f"❌ **Verification Failed!**\nError: `{str(e)}`\n\n"
                f"⚠️ *Kripya check karein ki bot channel me Admin hai aur 'Post Messages' permission on hai.*"
            )
        return

    # If no argument or button clicked: show interactive menu
    user_config = load_user_config(user_id)
    current_target = user_config.get("target_channel")
    current_str = f"<code>{current_target}</code>" if current_target else "<i>Direct Private Chat (No channel set)</i>"

    user_sessions.setdefault(user_id, {})["awaiting_channel"] = True

    buttons = [
        [InlineKeyboardButton("🔄 Reset to Direct Chat", callback_data="ch_reset")],
        [InlineKeyboardButton("ℹ️ Admin Permissions Help", callback_data="ch_help")]
    ]

    prompt_text = (
        f"📢 <b>Uploader Target Channel Setup:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Current Target:</b> {current_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✍️ <b>Channel Set Karne Ke Tareeqe:</b>\n"
        f"1. Apne channel ka <b>@Username</b> (e.g. <code>@my_channel</code>) yahan reply karein.\n"
        f"2. Ya channel ki <b>ID</b> (e.g. <code>-1001234567890</code>) yahan bhejain.\n"
        f"3. Ya apne channel se koi bhi post yahan <b>Forward</b> karein!\n\n"
        f"⚠️ <i>Bot ko channel me Admin bana kar 'Post Messages' permission zaroor dein!</i>"
    )

    await message.reply_text(prompt_text, parse_mode=enums.ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))

@app.on_message(filters.command("settings") | filters.regex(r"^⚙️ Settings$"))
async def settings_cmd(client, message):
    user_id = str(message.chat.id)
    user_config = load_user_config(user_id)
    current_target = user_config.get("target_channel", "Direct Private Chat")

    await message.reply_text(
        f"⚙️ <b>Bot Settings & Status:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Uploader Channel:</b> <code>{current_target}</code>\n"
        f"⚡ <b>Engine Workers:</b> <code>50 Parallel Threads</code>\n"
        f"🚀 <b>Fragment Downloader:</b> <code>50 Multi-Fragments</code>\n"
        f"📤 <b>Upload Channels:</b> <code>20 Concurrent Streams</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Target channel badalne ke liye</i> <code>/channel</code> <i>command use karein.</i>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD
    )

@app.on_message(filters.command("cancel") | filters.regex(r"^🛑 Stop Task$|^🛑 Stop$"))
async def cancel_cmd(client, message):
    user_id = str(message.chat.id)
    if running_tasks.get(user_id, False):
        running_tasks[user_id] = False
        await message.reply_text("⏳ Stopping current task... Please wait.")
    else:
        await message.reply_text("❌ No task is currently running.")

@app.on_message(filters.document)
async def handle_document(client, message: Message):
    file_name = message.document.file_name.lower()
    user_id = str(message.chat.id)

    if not file_name.endswith(".txt"):
        await message.reply_text("❌ Please send a valid `.txt` index file.")
        return

    if running_tasks.get(user_id, False):
        await message.reply_text("⚠️ A task is already running. Use `🛑 Stop` to stop it.")
        return

    status_msg = await message.reply_text("📥 **Reading & Parsing TXT File...**")
    file_path = await message.download()

    resources = extract_from_txt_file(file_path)

    if os.path.exists(file_path):
        try: os.remove(file_path)
        except: pass

    if not resources:
        await status_msg.edit_text("❌ No valid links found in this text file.")
        return

    # Cache resources
    session_file = os.path.join(DOWNLOAD_DIR, f"{user_id}_resources.json")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(resources, f)

    detected_batch = resources[0].get("batch", "Classx Consolidated Batch")
    if detected_batch in ["Classx Consolidated Batch", "Study-Mate Batch"] and len(resources) > 1:
        for r in resources:
            if r.get("batch") and r.get("batch") not in ["Classx Consolidated Batch", "Study-Mate Batch"]:
                detected_batch = r.get("batch")
                break

    user_sessions[user_id] = {
        "status_msg_id": status_msg.id,
        "awaiting_batch_name": True,
        "custom_batch_name": detected_batch
    }

    v_count = sum(1 for x in resources if x.get("type") == "video")
    p_count = sum(1 for x in resources if x.get("type") == "pdf")

    prompt_text = (
        f"✅ <b>TXT File Parsed Successfully!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Total Items:</b> <code>{len(resources)}</code> (🎥 {v_count} Videos • 📄 {p_count} PDFs)\n"
        f"🎓 <b>Detected Batch:</b> <code>{detected_batch}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✍️ <b>Kripya is Batch ka Name reply me likh kar bhejain:</b>\n"
        f"<i>(Agar detected name hi rakhna hai toh <code>{detected_batch}</code> ya koi naya name reply karein)</i>"
    )

    await status_msg.edit_text(prompt_text, parse_mode=enums.ParseMode.HTML)

@app.on_message(filters.text & ~filters.regex(r"^/"))
async def handle_text_reply(client, message: Message):
    user_id = str(message.chat.id)
    session = user_sessions.setdefault(user_id, {})
    text_content = message.text.strip()

    # If user was setting channel
    if session.get("awaiting_channel") or (text_content.startswith("-100") and text_content[1:].replace("-","").isdigit()) or (text_content.startswith("@") and len(text_content) > 3 and " " not in text_content):
        session["awaiting_channel"] = False
        target = text_content
        if message.forward_from_chat:
            target = message.forward_from_chat.id
        elif target.startswith("-100") or (target.startswith("-") and target[1:].isdigit()):
            target = int(target)

        status_msg = await message.reply_text("⏳ Verifying channel access...")
        try:
            chat = await client.get_chat(target)
            user_config = load_user_config(user_id)
            user_config["target_channel"] = chat.id
            save_user_config(user_id, user_config)

            await status_msg.edit_text(
                f"✅ **Target Channel Set Successfully!**\n\n"
                f"📢 **Name:** `{chat.title}`\n"
                f"🆔 **ID:** `{chat.id}`\n\n"
                f"🚀 Ab sabhi videos/PDFs is channel par upload hongi!",
                reply_markup=MAIN_KEYBOARD
            )
            return
        except Exception as e:
            await status_msg.edit_text(
                f"❌ **Verification Failed!** Error: `{str(e)}`\n\n"
                f"⚠️ *Kripya check karein ki bot channel me Admin hai aur 'Post Messages' permission on hai.*",
                reply_markup=MAIN_KEYBOARD
            )
            return

    if session.get("awaiting_batch_name"):
        batch_name = message.text.strip()
        session["custom_batch_name"] = batch_name
        session["awaiting_batch_name"] = False

        session_file = os.path.join(DOWNLOAD_DIR, f"{user_id}_resources.json")
        if not os.path.exists(session_file):
            await message.reply_text("❌ Session expired. Please send txt file again.")
            return

        with open(session_file, "r", encoding="utf-8") as f:
            resources = json.load(f)

        v_count = sum(1 for x in resources if x.get("type") == "video")
        p_count = sum(1 for x in resources if x.get("type") == "pdf")

        buttons = [
            [
                InlineKeyboardButton("▶️ Start All (1 to End)", callback_data="dl_type_all"),
                InlineKeyboardButton("🔢 Range 1 to 20", callback_data="dl_range_1_20")
            ],
            [
                InlineKeyboardButton("🔢 Range 21 to 50", callback_data="dl_range_21_50"),
                InlineKeyboardButton("🔢 Range 51 to 100", callback_data="dl_range_51_100")
            ],
            [
                InlineKeyboardButton("✍️ Custom Range", callback_data="dl_type_range"),
                InlineKeyboardButton("🛑 Cancel", callback_data="dl_cancel")
            ]
        ]

        summary_text = (
            f"🎓 <b>Batch Name Set:</b> <code>{batch_name}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Total Items:</b> <code>{len(resources)}</code> ({v_count} Videos • {p_count} PDFs)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <b>Select Range / Action:</b>\n"
            f"Niche button dabayein ya <b>Custom Range</b> choose karein.\n\n"
            f"💡 <i>Range Command:</i> <code>/range 1-20</code>"
        )

        await message.reply_text(summary_text, parse_mode=enums.ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # Direct links text support
    if "http" in message.text:
        if running_tasks.get(user_id, False):
            await message.reply_text("⚠️ A task is already running. Use `🛑 Stop` to stop it.")
            return

        status_msg = await message.reply_text("🔍 **Parsing Links...**")
        resources = parse_index_content(message.text)
        if not resources:
            await status_msg.edit_text("❌ No valid links found.")
            return

        session_file = os.path.join(DOWNLOAD_DIR, f"{user_id}_resources.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(resources, f)

        buttons = [
            [InlineKeyboardButton("📥 Download All", callback_data="dl_type_all")],
            [InlineKeyboardButton("🔢 Download Range", callback_data="dl_type_range"), InlineKeyboardButton("🛑 Cancel", callback_data="dl_cancel")]
        ]
        await status_msg.edit_text(f"📋 **Found {len(resources)} items.** Choose action:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_message(filters.forwarded)
async def handle_forwarded_message(client, message: Message):
    user_id = str(message.chat.id)
    session = user_sessions.setdefault(user_id, {})
    if message.forward_from_chat and (session.get("awaiting_channel") or message.forward_from_chat.type == enums.ChatType.CHANNEL):
        session["awaiting_channel"] = False
        target_id = message.forward_from_chat.id
        status_msg = await message.reply_text("⏳ Verifying forwarded channel access...")
        try:
            chat = await client.get_chat(target_id)
            user_config = load_user_config(user_id)
            user_config["target_channel"] = chat.id
            save_user_config(user_id, user_config)

            await status_msg.edit_text(
                f"✅ **Target Channel Set Successfully from Forward!**\n\n"
                f"📢 **Name:** `{chat.title}`\n"
                f"🆔 **ID:** `{chat.id}`\n\n"
                f"🚀 Ab sabhi videos/PDFs is channel par automatically upload hongi!",
                reply_markup=MAIN_KEYBOARD
            )
        except Exception as e:
            await status_msg.edit_text(
                f"❌ **Verification Failed!**\nError: `{str(e)}`\n\n"
                f"⚠️ *Make sure bot is Admin in `{message.forward_from_chat.title}` with 'Post Messages' permission!*",
                reply_markup=MAIN_KEYBOARD
            )

@app.on_message(filters.command("range"))
async def handle_range_command(client, message):
    user_id = str(message.chat.id)
    session_file = os.path.join(DOWNLOAD_DIR, f"{user_id}_resources.json")

    if running_tasks.get(user_id, False):
        await message.reply_text("⚠️ A task is already running. Stop it first.")
        return

    if not os.path.exists(session_file):
        await message.reply_text("❌ Please send a `.txt` index file first.")
        return

    args = message.text.split()
    if len(args) != 2 or "-" not in args[1]:
        await message.reply_text("❌ Format: `/range <start>-<end>` (e.g. `/range 1-20`)")
        return

    try:
        start_val, end_val = map(int, args[1].split("-"))
    except ValueError:
        await message.reply_text("❌ Please enter valid numbers (e.g. `/range 1-20`).")
        return

    with open(session_file, "r", encoding="utf-8") as f:
        resources = json.load(f)

    total_resources = len(resources)
    start_val = max(1, min(start_val, total_resources))
    end_val = min(max(start_val, end_val), total_resources)

    selected = resources[start_val - 1 : end_val]
    custom_batch = user_sessions.get(user_id, {}).get("custom_batch_name", "Study-Mate Batch")

    status_msg = await message.reply_text(f"⏳ **Range {start_val}-{end_val} selected... Starting upload!**")
    await process_batch_resources(client, message.chat.id, selected, status_msg, custom_batch)

@app.on_callback_query(filters.regex("^(dl_|ch_)"))
async def on_callback(client, query: CallbackQuery):
    user_id = str(query.message.chat.id)
    data = query.data
    session_file = os.path.join(DOWNLOAD_DIR, f"{user_id}_resources.json")

    if data == "ch_reset":
        user_config = load_user_config(user_id)
        user_config.pop("target_channel", None)
        save_user_config(user_id, user_config)
        await query.answer("Target channel reset.")
        await query.message.edit_text("✅ Target channel reset. Files will now be sent directly to your private chat.")
        return

    if data == "ch_help":
        await query.answer()
        help_text = (
            "ℹ️ <b>How to Add Bot as Channel Admin:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Apne Telegram Channel ko open karein.\n"
            "2. Channel Info > <b>Administrators</b> me jayein.\n"
            "3. <b>Add Admin</b> par click karke is Bot ko search karein.\n"
            "4. <b>Post Messages</b> permission ko ON karein aur Save karein.\n"
            "5. Fir yahan aakar channel ka <code>@Username</code> ya ID bhejain!"
        )
        await query.message.reply_text(help_text, parse_mode=enums.ParseMode.HTML)
        return

    if data == "dl_cancel":
        await query.answer("Cancelled.")
        await query.message.edit_text("🛑 Process cancelled.")
        if os.path.exists(session_file):
            try: os.remove(session_file)
            except: pass
        return

    if data == "dl_cancel_active":
        running_tasks[user_id] = False
        await query.answer("🛑 Cancelling active process...", show_alert=True)
        return

    if not os.path.exists(session_file):
        await query.answer("❌ Session expired. Send the text file again.", show_alert=True)
        return

    with open(session_file, "r", encoding="utf-8") as f:
        resources = json.load(f)

    custom_batch = user_sessions.get(user_id, {}).get("custom_batch_name", "Study-Mate Batch")

    if data == "dl_type_range":
        await query.answer("Enter range command.")
        await query.message.edit_text(
            f"🔢 **Download Range Setup:**\n\n"
            f"Send range command in chat:\n\n"
            f"`/range <start>-<end>`\n\n"
            f"**Example:** `/range 1-20`\n"
            f"**Total Available:** `{len(resources)}`"
        )
        return

    selected = []
    if data == "dl_type_all":
        selected = resources
    elif data == "dl_range_1_20":
        selected = resources[:20]
    elif data == "dl_range_21_50":
        selected = resources[20:50]
    elif data == "dl_range_51_100":
        selected = resources[50:100]

    if not selected:
        await query.answer("⚠️ No items in this range.", show_alert=True)
        return

    status_msg = await query.message.edit_text("⏳ Initializing high-speed downloader...")
    await process_batch_resources(client, query.message.chat.id, selected, status_msg, custom_batch)

if __name__ == "__main__":
    print("--------------------------------------------------")
    print("Batch Video/PDF Decrypter & Uploader Bot Starting...")
    print("--------------------------------------------------")
    app.run()
