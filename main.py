#!/usr/bin/env python3
"""
Simple Telegram Python Hosting Bot - Fixed imports for v20+
"""

import logging
import asyncio
import sys
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext

# ========== CONFIG ==========
BOT_TOKEN = "8036843497:AAHJ7gznTcwJto3iMAOooI7dzZmzQHNJW3M"  # <-- PUT TOKEN HERE (GET FROM @BotFather)

# Store running processes: user_id -> info
running_processes: dict[int, dict] = {}

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ================= COMMANDS =================

def start(update: Update, context: CallbackContext):
    welcome = (
        "🤖 *Python File Hosting Bot*\n\n"
        "Send me a `.py` file and I'll run it for you!\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/stop - Stop your running script\n"
        "/list - List all running scripts\n"
        "/status - Check bot status\n\n"
        "*Note:* Scripts run until finished or stopped."
    )
    update.message.reply_text(welcome, parse_mode="Markdown")


def status_command(update: Update, context: CallbackContext):
    total_scripts = len(running_processes)
    status = (
        "📊 *Bot Status*\n"
        f"• Running scripts: {total_scripts}\n"
        "• Bot: Online ✅\n"
        "• Scripts stop if bot restarts"
    )
    update.message.reply_text(status, parse_mode="Markdown")


def list_command(update: Update, context: CallbackContext):
    if not running_processes:
        update.message.reply_text("📭 No scripts are currently running.")
        return

    message = "📋 *Running Scripts:*\n\n"
    for user_id, info in running_processes.items():
        filename = info["filename"]
        start_time = info["start_time"].strftime("%H:%M:%S")
        message += f"• `{filename}` (Started: {start_time})\n"

    update.message.reply_text(message, parse_mode="Markdown")


def stop_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    info = running_processes.get(user_id)
    if not info:
        update.message.reply_text("❌ No script is currently running.")
        return

    process = info["process"]
    
    try:
        process.terminate()
        process.wait(timeout=5)
    except:
        try:
            process.kill()
        except:
            pass

    running_processes.pop(user_id, None)
    update.message.reply_text(f"🛑 Stopped: `{info['filename']}`", parse_mode="Markdown")


# ================= FILE HANDLER =================

def handle_python_file(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id

        if user_id in running_processes:
            update.message.reply_text("⚠️ Stop your current script first using /stop")
            return

        document = update.message.document
        tg_file = document.get_file()

        # Safe filename
        filename = Path(document.file_name).name

        user_dir = Path("scripts") / f"user_{user_id}"
        user_dir.mkdir(parents=True, exist_ok=True)

        file_path = user_dir / filename

        tg_file.download(str(file_path))

        update.message.reply_text(
            f"✅ File saved: `{filename}`\n🚀 Running your script...",
            parse_mode="Markdown",
        )

        # Run script in background
        asyncio.run(run_script(update, user_id, file_path))

    except Exception as e:
        update.message.reply_text(f"❌ Error: {e}")


# ================= SCRIPT RUNNER =================

async def run_script(update: Update, user_id: int, file_path: Path):
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        running_processes[user_id] = {
            "process": process,
            "filename": file_path.name,
            "start_time": datetime.now(),
        }

        update.message.reply_text(
            f"▶️ Script started: `{file_path.name}`",
            parse_mode="Markdown",
        )

        # Get output
        stdout, stderr = await process.communicate()

        if stdout:
            output_text = stdout.decode('utf-8', errors='ignore')
            if output_text.strip():
                update.message.reply_text(
                    f"📤 Output:\n```\n{output_text[:3500]}\n```",
                    parse_mode="Markdown",
                )

        if stderr:
            error_text = stderr.decode('utf-8', errors='ignore')
            if error_text.strip():
                update.message.reply_text(
                    f"⚠️ Errors:\n```\n{error_text[:3500]}\n```",
                    parse_mode="Markdown",
                )

    except Exception as e:
        update.message.reply_text(f"❌ Runtime error: {e}")

    finally:
        running_processes.pop(user_id, None)


# ================= MAIN =================

def main():
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Set your bot token in BOT_TOKEN")
        print("Get your token from @BotFather on Telegram")
        print("Then replace 'PASTE_YOUR_BOT_TOKEN_HERE' with your actual token")
        return

    Path("scripts").mkdir(exist_ok=True)

    try:
        # Create updater and dispatcher
        updater = Updater(BOT_TOKEN, use_context=True)
        dispatcher = updater.dispatcher

        # Add handlers
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("stop", stop_command))
        dispatcher.add_handler(CommandHandler("list", list_command))
        dispatcher.add_handler(CommandHandler("status", status_command))
        dispatcher.add_handler(MessageHandler(filters.Document.FileExtension("py"), handle_python_file))

        print("🤖 Bot started successfully!")
        print("✅ Your bot is now live on Render!")
        print("📱 Go to Telegram and send /start to your bot")
        
        # Start polling
        updater.start_polling()
        updater.idle()
        
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        print("Make sure your BOT_TOKEN is correct!")


if __name__ == "__main__":
    main()
