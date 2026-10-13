import sys
import logging
import gradio as gr
import urllib.request
import shutil
import subprocess

# 1. Bypassing the time-sync monkeypatch in bot.py during import
original_urlopen = urllib.request.urlopen
urllib.request.urlopen = lambda *args, **kwargs: Exception("Bypassing time sync on Hugging Face")

try:
    from bot import app as bot_app
finally:
    # Restore the original urlopen function after import
    urllib.request.urlopen = original_urlopen

# Force unbuffered output for real-time Docker logs in Hugging Face
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# Enable DEBUG logging for Pyrogram
logging.getLogger("pyrogram").setLevel(logging.DEBUG)

# Create a simple dashboard to keep the Hugging Face Space active
with gr.Blocks(title="Telegram Bot Status") as demo:
    gr.Markdown("# 🤖 Classx Video Decrypter Bot is Running")
    gr.Markdown("This dashboard keeps the Hugging Face Space active and online.")

# Perform diagnostic check of system dependencies on startup
def run_diagnostics():
    print("================== SYSTEM DIAGNOSTICS ==================")
    
    # Check aria2c
    aria2c_path = shutil.which("aria2c")
    print(f"Diagnostic: aria2c path is {aria2c_path}")
    if aria2c_path:
        try:
            res = subprocess.run(["aria2c", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            first_line = res.stdout.split("\n")[0] if res.stdout else "No output"
            print(f"Diagnostic: aria2c version is '{first_line}'")
        except Exception as e:
            print(f"Diagnostic: Failed to run aria2c: {e}")
    else:
        print("Diagnostic: WARNING - aria2c is NOT found in PATH!")

    # Check ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    print(f"Diagnostic: ffmpeg path is {ffmpeg_path}")
    if ffmpeg_path:
        try:
            res = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            first_line = res.stdout.split("\n")[0] if res.stdout else "No output"
            print(f"Diagnostic: ffmpeg version is '{first_line}'")
        except Exception as e:
            print(f"Diagnostic: Failed to run ffmpeg: {e}")
    else:
        print("Diagnostic: WARNING - ffmpeg is NOT found in PATH!")
        
    print("========================================================")

if __name__ == '__main__':
    # Run diagnostics
    run_diagnostics()
    
    # Launch Gradio on port 7860 in the background
    demo.launch(server_name="0.0.0.0", server_port=7860, prevent_thread_lock=True)
    
    # Start and run the Pyrogram Telegram bot
    print("Starting Telegram Bot...")
    try:
        import asyncio
        from pyrogram.methods.utilities.idle import idle
        
        loop = bot_app.loop or asyncio.get_event_loop()
        
        async def start_and_identify():
            await bot_app.start()
            me = await bot_app.get_me()
            print("==================================================")
            print(f"SUCCESS: Logged in as bot @{me.username} (Name: {me.first_name})")
            print("==================================================")
            await idle()
            await bot_app.stop()

        loop.run_until_complete(start_and_identify())
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to run Telegram Bot: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        
        # Keep the container alive so the user can inspect logs in Hugging Face
        import time
        print("Keeping container alive for debugging. Check logs above for the error.")
        while True:
            time.sleep(10)
