#!/usr/bin/env python3
"""
Simple Telegram Python Hosting Bot - Compatible with older python-telegram-bot
"""

import os
import logging
from pathlib import Path
from datetime import datetime
import subprocess
import threading
import signal

from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Bot token
BOT_TOKEN = "8036843497:AAHJ7gznTcwJto3iMAOooI7dzZmzQHNJW3M"

# Store running processes
running_processes = {}

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start(update: Update, context: CallbackContext):
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
    update.message.reply_text(welcome, parse_mode="Markdown")

def handle_python_file(update: Update, context: CallbackContext):
    """Handle incoming Python files"""
    # Get the file
    file = update.message.document.get_file()
    
    # Create user directory
    user_id = update.effective_user.id
    user_dir = Path(f"scripts/user_{user_id}")
    user_dir.mkdir(exist_ok=True)
    
    # Save file
    filename = update.message.document.file_name
    file_path = user_dir / filename
    
    # Download file
    file.download(str(file_path))
    
    # Make it executable
    file_path.chmod(0o755)
    
    update.message.reply_text(f"✅ File saved: `{filename}`\nRunning your script...", parse_mode="Markdown")
    
    # Run the script in background thread
    thread = threading.Thread(target=run_script, args=(update, context, user_id, file_path))
    thread.daemon = True
    thread.start()

def run_script(update: Update, context: CallbackContext, user_id: int, file_path: Path):
    """Run Python script in background"""
    try:
        # Start the process
        process = subprocess.Popen(
            ["python3", str(file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Store the process
        running_processes[user_id] = {
            'process': process,
            'filename': file_path.name,
            'start_time': datetime.now(),
            'file_path': str(file_path)
        }
        
        # Send confirmation
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🚀 Script is now running!\nFile: `{file_path.name}`",
            parse_mode="Markdown"
        )
        
        # Get output
        stdout, stderr = process.communicate()
        
        # Send output
        if stdout and stdout.strip():
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📤 Output:\n```\n{stdout[:4000]}\n```",
                parse_mode="Markdown"
            )
        
        if stderr and stderr.strip():
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Errors:\n```\n{stderr[:4000]}\n```",
                parse_mode="Markdown"
            )
        
        # Remove from running processes if it finished
        if user_id in running_processes:
            del running_processes[user_id]
            
    except Exception as e:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Error: {str(e)}"
        )

def stop_command(update: Update, context: CallbackContext):
    """Stop user's running script"""
    user_id = update.effective_user.id
    
    if user_id in running_processes:
        process_info = running_processes[user_id]
        process = process_info['process']
        
        try:
            process.terminate()
            process.wait(timeout=5)
        except:
            try:
                process.kill()
            except:
                pass
        
        del running_processes[user_id]
        update.message.reply_text(f"✅ Stopped: `{process_info['filename']}`", parse_mode="Markdown")
    else:
        update.message.reply_text("❌ No script running.")

def list_command(update: Update, context: CallbackContext):
    """List all running scripts"""
    if not running_processes:
        update.message.reply_text("📭 No scripts running.")
        return
    
    message = "📋 *Running Scripts:*\n\n"
    for user_id, info in running_processes.items():
        filename = info['filename']
        start_time = info['start_time'].strftime("%H:%M:%S")
        message += f"• `{filename}` (Started: {start_time})\n"
    
    update.message.reply_text(message, parse_mode="Markdown")

def status_command(update: Update, context: CallbackContext):
    """Show bot status"""
    total_scripts = len(running_processes)
    status = f"""
📊 *Bot Status*
• Running scripts: {total_scripts}
• Bot: Online ✅
• All scripts stop when bot restarts
    """
    update.message.reply_text(status, parse_mode="Markdown")

def error_handler(update: Update, context: CallbackContext):
    """Log errors"""
    logger.warning(f'Update {update} caused error {context.error}')

def cleanup():
    """Cleanup on shutdown"""
    for user_id, info in running_processes.items():
        try:
            info['process'].terminate()
        except:
            pass

def main():
    """Start the bot"""
    # Create updater
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Add handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop_command))
    dp.add_handler(CommandHandler("list", list_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(MessageHandler(Filters.document.file_extension("py"), handle_python_file))
    dp.add_error_handler(error_handler)
    
    # Create scripts directory
    Path("scripts").mkdir(exist_ok=True)
    
    print("Starting Python Hosting Bot...")
    print("Send .py files to run them!")
    
    # Start bot
    updater.start_polling()
    updater.idle()
    
    # Cleanup when bot stops
    cleanup()

if __name__ == '__main__':
    main()
