---
title: Telegram Course Batch Uploader Bot
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 🚀 Telegram Course Batch Uploader Bot

An ultra-fast, multi-threaded Telegram bot built with **Pyrofork**, **yt-dlp**, and **FFmpeg** to download, mirror, and upload course batches (Videos, M3U8 Streams, PDFs) directly to Telegram channels or private chats.

Includes a **Gradio dashboard** and **Docker** configuration optimized for 24/7 deployment on **Hugging Face Spaces**, **VPS**, or local environments.

---

## ✨ Features

- ⚡ **High-Speed Segmented Downloads**: Multi-threaded segmented downloader for rapid retrieval of large media files.
- 🎬 **HLS & Stream Processing**: Captures `.m3u8`, YouTube embeds, and video streams seamlessly via `yt-dlp`.
- 🖼️ **Auto-Thumbnail Generation**: Generates high-quality video thumbnails using `FFmpeg`.
- 📄 **TXT File Index Parsing**: Smart parser supporting Study-Mate formats, key-value blocks, and raw link text lists.
- 🎛️ **Interactive Range Selection**: Upload entire batches, pre-set ranges (`1-20`, `21-50`, `51-100`), or custom ranges (`/range 1-15`).
- 📢 **Target Channel Forwarding**: Route uploads directly to any custom Telegram channel where the bot is an admin.
- 🌐 **24/7 Cloud Ready**: Gradio health-check dashboard on port `7860` keeps free cloud containers (like Hugging Face Spaces) active.

---

## 📁 Project Structure

```text
telegram-course-uploader-bot/
├── app.py                # Gradio status dashboard + Bot launcher (Hugging Face / Cloud entry point)
├── bot.py                # Main Telegram bot logic, media handlers, and download engine
├── Dockerfile            # Container definition with ffmpeg, aria2c, and Python 3.10
├── requirements.txt      # Python package requirements
├── .env.example          # Environment variable template for GitHub
├── .env                  # Local secret keys (ignored by git for security)
├── .gitignore            # Git ignore configuration
└── README.md             # Project documentation
```

---

## 🛠️ Local Setup & Installation

### Prerequisites
- **Python 3.10+**
- **FFmpeg** installed and added to system PATH

### 1. Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/telegram-course-uploader-bot.git
cd telegram-course-uploader-bot
```

### 2. Create Virtual Environment & Install Dependencies
```bash
python -m venv venv

# On Windows:
venv\Scripts\activate

# On Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Credentials
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
```
> 💡 Obtain `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org), and `BOT_TOKEN` from [@BotFather](https://t.me/BotFather).

### 4. Run the Bot
- **For local bot only:**
  ```bash
  python bot.py
  ```
- **With Gradio Dashboard (recommended for cloud):**
  ```bash
  python app.py
  ```

---

## 🚀 Deployment

### Option 1: Hugging Face Spaces (Free 24/7)
1. Go to [Hugging Face Spaces](https://huggingface.co/new-space).
2. Create a new Space:
   - **SDK**: Select **Docker** (Blank).
   - Set visibility to **Public** or **Private**.
3. Push this repository to your Space or connect your GitHub repository.
4. Go to **Settings > Variables and secrets** in your Space:
   - Add `API_ID` (Secret)
   - Add `API_HASH` (Secret)
   - Add `BOT_TOKEN` (Secret)
5. The container will build and start automatically!

---

### Option 2: Docker / VPS
Run anywhere using Docker:
```bash
# Build the Docker image
docker build -t course-uploader-bot .

# Run container with environment variables
docker run -d --name uploader-bot \
  -e API_ID="your_api_id" \
  -e API_HASH="your_api_hash" \
  -e BOT_TOKEN="your_bot_token" \
  -p 7860:7860 course-uploader-bot
```

---

## 🤖 Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Open the main menu and instructions |
| `/channel` | Configure destination channel for uploads |
| `/settings` | View bot status and channel settings |
| `/range <start>-<end>` | Process specific items from uploaded TXT (e.g., `/range 1-25`) |
| `/cancel` | Stop currently running download/upload task |

---

## 🔒 Security Best Practices
- Never commit your `.env` file or session files to GitHub.
- Ensure `.gitignore` is present before pushing to any public repository.
