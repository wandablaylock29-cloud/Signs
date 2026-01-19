#!/usr/bin/env python3
"""
Simple Telegram Python Hosting Bot
Working with bot token: 8036843497:AAFscbpINVEMGt5GaOHnJ0deVcCASGqZe98
Compatible with python-telegram-bot v21+
"""

import logging
import asyncio
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = "8036843497:AAFscbpINVEMGt5GaOHnJ0deVcCASGqZe98"

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

    process: Optional[asyncio.subprocess.Process] = info.get("process")
    
    if process:
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except Exception as e:
            logger.error(f"Error stopping process: {e}")

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

        # Run script in background
        asyncio.create_task(run_script(update, user_id, file_path))

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Error handling file: {e}")


# ================= SCRIPT RUNNER =================

async def run_script(update: Update, user_id: int, file_path: Path):
    process = None
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

        # Get output
        stdout, stderr = await process.communicate()

        if stdout:
            output_text = stdout.decode('utf-8', errors='ignore')
            if output_text.strip():
                # Split long output into multiple messages if needed
                if len(output_text) > 3500:
                    chunks = [output_text[i:i+3500] for i in range(0, len(output_text), 3500)]
                    for i, chunk in enumerate(chunks[:3]):  # Limit to 3 chunks
                        await update.message.reply_text(
                            f"📤 Output (Part {i+1}):\n```\n{chunk}\n```",
                            parse_mode="Markdown",
                        )
                else:
                    await update.message.reply_text(
                        f"📤 Output:\n```\n{output_text}\n```",
                        parse_mode="Markdown",
                    )

        if stderr:
            error_text = stderr.decode('utf-8', errors='ignore')
            if error_text.strip():
                if len(error_text) > 3500:
                    chunks = [error_text[i:i+3500] for i in range(0, len(error_text), 3500)]
                    for i, chunk in enumerate(chunks[:3]):
                        await update.message.reply_text(
                            f"⚠️ Errors (Part {i+1}):\n```\n{chunk}\n```",
                            parse_mode="Markdown",
                        )
                else:
                    await update.message.reply_text(
                        f"⚠️ Errors:\n```\n{error_text}\n```",
                        parse_mode="Markdown",
                    )

    except Exception as e:
        logger.error(f"Runtime error: {e}")
        await update.message.reply_text(f"❌ Runtime error: {str(e)[:1000]}")

    finally:
        if user_id in running_processes:
            running_processes.pop(user_id, None)


# ================= ERROR HANDLER =================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ An error occurred. Please try again.")


# ================= MAIN =================

async def main():
    """Main async function for python-telegram-bot v21+"""
    # Create necessary directories
    Path("scripts").mkdir(exist_ok=True)
    
    print("🤖 Starting Python Hosting Bot...")
    print(f"📱 Bot Token: {BOT_TOKEN[:10]}...")
    
    try:
        # Create application with the bot token
        application = Application.builder().token(BOT_TOKEN).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stop", stop_command))
        application.add_handler(CommandHandler("list", list_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(MessageHandler(filters.Document.FileExtension("py"), handle_python_file))
        
        # Add error handler
        application.add_error_handler(error_handler)

        print("✅ Bot initialized successfully!")
        print("🚀 Starting polling...")
        print("📝 Send /start to your bot on Telegram")
        
        # Start polling
        await application.run_polling()
        
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        print("Possible issues:")
        print("1. Invalid bot token")
        print("2. Network connection issue")
        print("3. python-telegram-bot version mismatch")
        print(f"Error details: {type(e).__name__}: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
