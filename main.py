#!/usr/bin/env python3
"""
Python Hosting Telegram Bot
Compatible with python-telegram-bot v21.0+
Runs scripts indefinitely until stopped or bot restarts
"""

import logging
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List
import signal

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== CONFIG ==========
BOT_TOKEN = "7897881067:AAGtctSuNLfu14sKGaaVmHUV4Nvz935nENc"

# Store running processes: user_id -> info
running_processes: dict[int, dict] = {}

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when /start is issued."""
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


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send bot status."""
    total_scripts = len(running_processes)
    status = (
        "📊 *Bot Status*\n"
        f"• Running scripts: {total_scripts}\n"
        "• Bot: Online ✅\n"
        "• Scripts run indefinitely until stopped"
    )
    await update.message.reply_text(status, parse_mode="Markdown")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all running scripts."""
    if not running_processes:
        await update.message.reply_text("📭 No scripts are currently running.")
        return

    message = "📋 *Running Scripts:*\n\n"
    for user_id, info in running_processes.items():
        filename = info["filename"]
        start_time = info["start_time"].strftime("%H:%M:%S")
        message += f"• `{filename}` (Started: {start_time})\n"

    await update.message.reply_text(message, parse_mode="Markdown")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop the user's running script."""
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
                if process.returncode is None:  # Process still running
                    process.kill()
                    await process.wait()
            except Exception as e:
                logger.error(f"Error stopping process: {e}")
        except Exception as e:
            logger.error(f"Error in process termination: {e}")

    running_processes.pop(user_id, None)
    await update.message.reply_text(f"🛑 Stopped: `{info['filename']}`", parse_mode="Markdown")


# ================= FILE HANDLER =================

async def handle_python_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming Python files."""
    try:
        user_id = update.effective_user.id

        if user_id in running_processes:
            await update.message.reply_text("⚠️ Stop your current script first using /stop")
            return

        document = update.message.document
        
        if not document.file_name.endswith('.py'):
            await update.message.reply_text("❌ Please send a .py file")
            return

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
        logger.error(f"Error handling file: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:500]}")


# ================= SCRIPT RUNNER =================

async def run_script(update: Update, user_id: int, file_path: Path) -> None:
    """Run the Python script and send output - NO TIME LIMIT."""
    process = None
    output_chunks: List[str] = []
    error_chunks: List[str] = []
    
    try:
        # Create subprocess with unbuffered output
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(file_path),  # -u for unbuffered output
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        running_processes[user_id] = {
            "process": process,
            "filename": file_path.name,
            "start_time": datetime.now(),
        }

        await update.message.reply_text(
            f"▶️ Script started: `{file_path.name}`\n"
            "⏳ Running indefinitely until stopped with /stop",
            parse_mode="Markdown",
        )

        # Function to read stream
        async def read_stream(stream, is_stderr=False):
            """Read from stream and collect output."""
            chunks = []
            try:
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    line = line_bytes.decode('utf-8', errors='ignore').rstrip()
                    if line:
                        chunks.append(line)
            except Exception as e:
                logger.error(f"Error reading {'stderr' if is_stderr else 'stdout'}: {e}")
            return chunks

        # Create tasks for reading stdout and stderr
        stdout_task = asyncio.create_task(read_stream(process.stdout, False))
        stderr_task = asyncio.create_task(read_stream(process.stderr, True))
        
        # Wait for process to complete or be stopped
        try:
            # Wait for process to complete
            await process.wait()
        except Exception as e:
            logger.error(f"Error waiting for process: {e}")
        
        # Get collected output
        output_chunks = await stdout_task
        error_chunks = await stderr_task
        
        # Send collected output
        if output_chunks:
            output_text = "\n".join(output_chunks)
            if output_text:
                if len(output_text) > 3500:
                    chunks = [output_text[i:i+3500] for i in range(0, len(output_text), 3500)]
                    for i, chunk in enumerate(chunks[:5]):  # Limit to 5 chunks
                        await update.message.reply_text(
                            f"📤 Output (Part {i+1}):\n```\n{chunk}\n```",
                            parse_mode="Markdown",
                        )
                else:
                    await update.message.reply_text(
                        f"📤 Output:\n```\n{output_text}\n```",
                        parse_mode="Markdown",
                    )

        if error_chunks:
            error_text = "\n".join(error_chunks)
            if error_text:
                if len(error_text) > 3500:
                    chunks = [error_text[i:i+3500] for i in range(0, len(error_text), 3500)]
                    for i, chunk in enumerate(chunks[:5]):  # Limit to 5 chunks
                        await update.message.reply_text(
                            f"⚠️ Errors (Part {i+1}):\n```\n{chunk}\n```",
                            parse_mode="Markdown",
                        )
                else:
                    await update.message.reply_text(
                        f"⚠️ Errors:\n```\n{error_text}\n```",
                        parse_mode="Markdown",
                    )

        # Check exit code
        if process and process.returncode == 0:
            await update.message.reply_text("✅ Script completed successfully")
        elif process and process.returncode != 0:
            await update.message.reply_text(f"❌ Script exited with code: {process.returncode}")

    except Exception as e:
        logger.error(f"Runtime error: {e}")
        try:
            await update.message.reply_text(f"❌ Runtime error: {str(e)[:500]}")
        except:
            pass

    finally:
        if user_id in running_processes:
            running_processes.pop(user_id, None)


# ================= ERROR HANDLER =================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Try to send error message to user
    try:
        if update and update.message:
            await update.message.reply_text("❌ An error occurred. Please try again.")
    except:
        pass


# ================= CLEANUP ON EXIT =================

def cleanup_all_processes():
    """Clean up all running processes on exit."""
    logger.info("Cleaning up all processes...")
    for user_id, info in list(running_processes.items()):
        process = info.get("process")
        if process and process.returncode is None:
            try:
                process.kill()
            except:
                pass
    running_processes.clear()


# ================= MAIN =================

def main() -> None:
    """Start the bot."""
    # Create necessary directories
    Path("scripts").mkdir(exist_ok=True)
    
    print("🤖 Starting Python Hosting Bot...")
    print(f"📱 Bot Token: {BOT_TOKEN[:10]}...")
    print("📦 Using python-telegram-bot v21+")
    print("⏳ Scripts run indefinitely until stopped")
    
    try:
        # Create application
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
        print("🔄 Bot is running...")
        
        # Set up cleanup on exit
        import atexit
        atexit.register(cleanup_all_processes)
        
        # Run the bot
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        print(f"❌ Fatal error: {type(e).__name__}: {e}")
        cleanup_all_processes()
        return 1
    
    return 0


if __name__ == "__main__":
    # Run the bot
    sys.exit(main())
