#!/usr/bin/env python3
"""
Simple Telegram Python Hosting Bot
Run Python files from Telegram
"""

import os
import logging
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Bot token (replace with your actual token)
BOT_TOKEN = "8036843497:AAHJ7gznTcwJto3iMAOooI7dzZmzQHNJW3M"

# Store running processes
running_processes = {}

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    welcome = """
🤖 *Python File Hosting Bot*

Send me a `.py` Python file and I'll run it for you!

*Commands:*
/start - Show this message
/stop - Stop your running script
/list - List all running scripts
/status - Check bot status

*Note:* Scripts will run until the bot is stopped.
    """
    await update.message.reply_text(welcome, parse_mode="Markdown")

async def handle_python_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Python files"""
    # Get the file
    file = await update.message.document.get_file()
    
    # Create user directory
    user_id = update.effective_user.id
    user_dir = Path(f"scripts/user_{user_id}")
    user_dir.mkdir(exist_ok=True)
    
    # Save file
    filename = update.message.document.file_name
    file_path = user_dir / filename
    
    # Download file
    await file.download_to_drive(file_path)
    
    # Make it executable
    file_path.chmod(0o755)
    
    await update.message.reply_text(f"✅ File saved: `{filename}`\nRunning your script...", parse_mode="Markdown")
    
    # Run the script in background
    await run_script(update, context, user_id, file_path)

async def run_script(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, file_path: Path):
    """Run Python script in background"""
    try:
        # Start the process
        process = await asyncio.create_subprocess_exec(
            "python3", str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Store the process
        running_processes[user_id] = {
            'process': process,
            'filename': file_path.name,
            'start_time': datetime.now(),
            'file_path': str(file_path)
        }
        
        # Send confirmation
        await update.message.reply_text(f"🚀 Script is now running!\nFile: `{file_path.name}`", parse_mode="Markdown")
        
        # Monitor output
        asyncio.create_task(monitor_output(update, context, user_id, process))
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error running script: {str(e)}")

async def monitor_output(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, process):
    """Monitor script output"""
    try:
        # Read stdout and stderr
        stdout, stderr = await process.communicate()
        
        if stdout:
            output = stdout.decode('utf-8', errors='ignore')[:4000]  # Limit length
            if output.strip():
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"📤 Output from your script:\n```\n{output}\n```",
                    parse_mode="Markdown"
                )
        
        if stderr:
            error = stderr.decode('utf-8', errors='ignore')[:4000]
            if error.strip():
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"⚠️ Errors from your script:\n```\n{error}\n```",
                    parse_mode="Markdown"
                )
                
    except Exception as e:
        logger.error(f"Error monitoring output: {e}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop user's running script"""
    user_id = update.effective_user.id
    
    if user_id in running_processes:
        process_info = running_processes[user_id]
        process = process_info['process']
        
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5)
        except:
            try:
                process.kill()
            except:
                pass
        
        del running_processes[user_id]
        await update.message.reply_text(f"✅ Stopped script: `{process_info['filename']}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No script is currently running.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all running scripts"""
    if not running_processes:
        await update.message.reply_text("📭 No scripts are currently running.")
        return
    
    message = "📋 *Running Scripts:*\n\n"
    for user_id, info in running_processes.items():
        filename = info['filename']
        start_time = info['start_time'].strftime("%H:%M:%S")
        message += f"• `{filename}` (Started: {start_time})\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    total_scripts = len(running_processes)
    status = f"""
📊 *Bot Status*
• Running scripts: {total_scripts}
• Bot: Online ✅
• All scripts will stop when bot restarts
    """
    await update.message.reply_text(status, parse_mode="Markdown")

async def cleanup():
    """Cleanup all running processes when bot stops"""
    for user_id, info in running_processes.items():
        try:
            info['process'].terminate()
        except:
            pass

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.Document.FileExtension("py"), handle_python_file))
    
    # Add cleanup on shutdown
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    # Cleanup when polling stops
    asyncio.run(cleanup())

if __name__ == '__main__':
    # Create scripts directory
    Path("scripts").mkdir(exist_ok=True)
    
    print("Starting Python Hosting Bot...")
    print("Send .py files to run them!")
    print("Bot will run until terminated with Ctrl+C")
    
    main()
