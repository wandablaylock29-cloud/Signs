#!/usr/bin/env python3
"""
Simple Telegram Python Hosting Bot
"""

import logging
import asyncio
import sys
from pathlib import Path
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = "8036843497:AAHJ7gznTcwJto3iMAOooI7dzZmzQHNJW3M"  # <-- PUT TOKEN HERE

# Store running processes: user_id -> info
running_processes: dict[int, dict] = {}

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_scripts = len(running_processes)
    status = (
        "📊 *Bot Status*\n"
        f"• Running scripts: {total_scripts}\n"
        "• Bot: Online ✅\n"
        "• Scripts stop if bot restarts"
    )
    await update.message.reply_text(status, parse_mode="Markdown")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not running_processes:
        await update.message.reply_text("📭 No scripts are currently running.")
        return

    message = "📋 *Running Scripts:*\n\n"
    for user_id, info in running_processes.items():
        filename = info["filename"]
        start_time = info["start_time"].strftime("%H:%M:%S")
        message += f"• `{filename}` (Started: {start_time})\n"

    await update.message.reply_text(message, parse_mode="Markdown")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    info = running_processes.get(user_id)
    if not info:
        await update.message.reply_text("❌ No script is currently running.")
        return

    process: asyncio.subprocess.Process = info["process"]

    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass

    running_processes.pop(user_id, None)
    await update.message.reply_text(f"🛑 Stopped: `{info['filename']}`", parse_mode="Markdown")


# ================= FILE HANDLER =================

async def handle_python_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id

        if user_id in running_processes:
            await update.message.reply_text("⚠️ Stop your current script first using /stop")
            return

        document = update.message.document
        tg_file = await document.get_file()

        # Safe filename
        filename = Path(document.file_name).name

        user_dir = Path("scripts") / f"user_{user_id}"
        user_dir.mkdir(parents=True, exist_ok=True)

        file_path = user_dir / filename

        await tg_file.download_to_drive(file_path)

        await update.message.reply_text(
            f"✅ File saved: `{filename}`\n🚀 Running your script...",
            parse_mode="Markdown",
        )

        asyncio.create_task(run_script(update, user_id, file_path))

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


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

        await update.message.reply_text(
            f"▶️ Script started: `{file_path.name}`",
            parse_mode="Markdown",
        )

        # Stream output live
        async def read_stream(stream, label):
            lines = []
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="ignore")
                lines.append(text)
                if len("".join(lines)) > 3500:
                    break
            return "".join(lines)

        stdout_task = asyncio.create_task(read_stream(process.stdout, "out"))
        stderr_task = asyncio.create_task(read_stream(process.stderr, "err"))

        await process.wait()

        stdout = await stdout_task
        stderr = await stderr_task

        if stdout.strip():
            await update.message.reply_text(
                f"📤 Output:\n```\n{stdout[-3500:]}\n```",
                parse_mode="Markdown",
            )

        if stderr.strip():
            await update.message.reply_text(
                f"⚠️ Errors:\n```\n{stderr[-3500:]}\n```",
                parse_mode="Markdown",
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Runtime error: {e}")

    finally:
        running_processes.pop(user_id, None)


# ================= MAIN =================

def main():
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Set your bot token in BOT_TOKEN")
        return

    Path("scripts").mkdir(exist_ok=True)

    try:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stop", stop_command))
        application.add_handler(CommandHandler("list", list_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(MessageHandler(filters.Document.FileExtension("py"), handle_python_file))

        print("🤖 Bot started")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
    except AttributeError as e:
        print(f"❌ Library version issue: {e}")
        print("\n🔥 FIX: Install compatible python-telegram-bot version:")
        print("Run: pip install python-telegram-bot==20.7")
        print("Or: pip install python-telegram-bot --upgrade")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
