from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton, LabeledPrice
from telegram.helpers import escape
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler, TypeHandler, PreCheckoutQueryHandler
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import random
import secrets
import asyncio
import integration
import re
import json
from pathlib import Path
import jdatetime
import string
import math
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import os
import html
import requests
import json
import threading
from time import sleep
import logging
from logging.handlers import RotatingFileHandler

# ==================== سیستم لاگ ====================
LOG_DIR = Path(os.environ.get("DAWN_LOG_DIR", str(Path(__file__).with_name("logs"))))
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("dawnpanel")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _fh = RotatingFileHandler(LOG_DIR / "bot.log", maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    _fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    logger.addHandler(_sh)

def log_exception(message, exc=None):
    if exc is not None:
        logger.exception(message)
    else:
        logger.error(message)

# مقادیر حساس را در config.json قرار دهید و آن فایل را در Git/عموم منتشر نکنید.
CONFIG_FILE = Path(os.environ.get("DAWN_CONFIG", Path(__file__).with_name("config.json")))
try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    raise RuntimeError(f"فایل config.json پیدا نشد: {CONFIG_FILE}")

TOKEN = CONFIG["telegram"]["token"]
SUPPORT_USERNAME = CONFIG["telegram"]["support_username"]
SUPPORT_USER_ID = CONFIG["telegram"]["support_user_id"]
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}"
BOT_USERNAME = CONFIG["telegram"]["bot_username"]
RULES_LINK = CONFIG["telegram"]["rules_link"]
ORDER_RULES_LINK = CONFIG["telegram"]["order_rules_link"]

# کانال گزارش خریدهای موفق فقط از config.json خوانده می‌شود.
# نمونه در config.json:
# "report_channel_id": -1003984929895
_raw_report_channel_id = CONFIG["telegram"].get("report_channel_id")
if _raw_report_channel_id is None:
    raise RuntimeError('کلید telegram.report_channel_id در config.json تنظیم نشده است.')
try:
    REPORT_CHANNEL_ID = int(_raw_report_channel_id)
except (TypeError, ValueError) as exc:
    raise RuntimeError('مقدار telegram.report_channel_id در config.json باید یک عدد معتبر باشد.') from exc
SELECT_PAYMENT_METHOD = 0
AMOUNT_INPUT = 1
RECEIPT_PHOTO = 3
ADMIN_AMOUNT_INPUT = 4
ADMIN_REJECT_REASON = 5
PHONE_NUMBER_INPUT = 9
VERIFICATION_CODE = 10
ADMIN_BAN_USER = 11
ADMIN_UNBAN_USER = 12
ADMIN_BROADCAST = 13
STARS_AMOUNT_INPUT = 17
SUPPORT_MESSAGE_INPUT = 18
ADMIN_ADD_CATEGORY_NAME = 20
ADMIN_ADD_CATEGORY_EMOJI = 21
ADMIN_ADD_PRODUCT_NAME = 23
ADMIN_ADD_PRODUCT_DESCRIPTION = 24
ADMIN_ADD_PRODUCT_PRICE = 25
ADMIN_ADD_PRODUCT_PRICE_PER = 26
ADMIN_ADD_PRODUCT_MIN_ORDER = 27
ADMIN_ADD_PRODUCT_MAX_ORDER = 28
ADMIN_ADD_PRODUCT_NEED_LINK = 29
ADMIN_EDIT_CATEGORY_NAME = 30
ADMIN_EDIT_PRODUCT_VALUE = 31
ADMIN_ADD_PRODUCT_CURRENCY = 52
ADMIN_ADD_PRODUCT_PROFIT = 53
ADMIN_SETTING_SELF_PROFIT = 32
ADMIN_SETTING_REFERRAL = 33
ADMIN_USER_SEARCH = 34
ADMIN_SETTING_MIN_CHARGE = 35
ADMIN_SETTING_MAX_CHARGE = 36
ADMIN_SETTING_MIN_STARS = 37
ADMIN_SETTING_MAX_STARS = 38
ADMIN_GIFT_CODE = 39
ADMIN_GIFT_AMOUNT = 40
ADMIN_GIFT_MAX_USES = 41
ADMIN_CURRENCY_ADD_CODE = 42
ADMIN_CURRENCY_ADD_NAME = 43
ADMIN_CURRENCY_ADD_SYMBOL = 44
ADMIN_CURRENCY_ADD_RATE = 45
ADMIN_USER_VERIFICATION_TEXT = 46
ADMIN_USER_VERIFICATION_PHOTO = 47

ADMIN_IDS = CONFIG["telegram"]["admin_ids"]
CARD_NUMBER = CONFIG["payment"]["card_number"]
CARD_HOLDER = CONFIG["payment"]["card_holder"]
REQUIRED_CHANNEL_ID = CONFIG["telegram"]["required_channel_id"]
REQUIRED_CHANNEL_LINK = CONFIG["telegram"]["required_channel_link"]
MIN_CHARGE_AMOUNT = 1000
MAX_CHARGE_AMOUNT = 100000000
COMMISSION_PERCENT = CONFIG["business"]["commission_percent"]
SELF_PROFIT_PERCENT = CONFIG["business"]["self_profit_percent"]
MAX_STARS = 2500
MIN_STARS = 1
ZARINPAL_MERCHANT = CONFIG["zarinpal"]["merchant"]
ZARINPAL_SANDBOX = CONFIG["zarinpal"]["sandbox"]
ZARINPAL_CALLBACK_URL = CONFIG["zarinpal"]["callback_url"]
SMS_IR_API_KEY = CONFIG["sms_ir"]["api_key"]
SMS_IR_VERIFY_TEMPLATE_ID = CONFIG["sms_ir"]["verify_template_id"]

DB_CONFIG = CONFIG["database"]

if ZARINPAL_SANDBOX:
    ZARINPAL_API_REQUEST = "https://sandbox.zarinpal.com/pg/v4/payment/request.json"
    ZARINPAL_API_VERIFY = "https://sandbox.zarinpal.com/pg/v4/payment/verify.json"
    ZARINPAL_START_PAY = "https://sandbox.zarinpal.com/pg/StartPay/"
else:
    ZARINPAL_API_REQUEST = "https://payment.zarinpal.com/pg/v4/payment/request.json"
    ZARINPAL_API_VERIFY = "https://payment.zarinpal.com/pg/v4/payment/verify.json"
    ZARINPAL_START_PAY = "https://payment.zarinpal.com/pg/StartPay/"

banned_users_notified = set()

# ==================== توابع کمکی ====================
def get_jalali_datetime():
    now = jdatetime.datetime.now()
    return now.strftime("%Y/%m/%d - %H:%M:%S")

def generate_tracking_code():
    chars = string.digits + string.ascii_uppercase
    return 'DWN-' + ''.join([secrets.choice(chars) for _ in range(16)])

def generate_payment_tracking():
    return ''.join([secrets.choice(string.hexdigits.lower()) for _ in range(10)])

def generate_referral_code(user_id):
    return str(user_id)

def format_amount(amount):
    """نمایش مبلغ به صورت عدد کامل و بدون scientific notation مثل 1e+08."""
    try:
        if amount is None:
            return "0"
        from decimal import Decimal, InvalidOperation
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        if value == value.to_integral_value():
            return f"{int(value):,}"
        return f"{value:,.2f}".rstrip('0').rstrip('.')
    except (TypeError, ValueError, InvalidOperation):
        return str(amount)

def validate_iranian_phone(phone):
    phone = re.sub(r'[\s\-\(\)\+]', '', phone)
    for pattern in [r'^09\d{9}$', r'^989\d{9}$', r'^\+989\d{9}$', r'^00989\d{9}$']:
        if re.match(pattern, phone):
            if phone.startswith('+98'): phone = '0' + phone[3:]
            elif phone.startswith('0098'): phone = '0' + phone[4:]
            elif phone.startswith('98'): phone = '0' + phone[2:]
            return True, phone
    return False, phone

def generate_verification_code():
    return str(secrets.randbelow(900000) + 100000)

def get_setting(key, default=None):
    connection = get_db_connection()
    if not connection: return default
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_key = %s", (key,))
        row = cursor.fetchone()
        cursor.close(); connection.close()
        if row is None: return default
        try: return float(row[0])
        except (TypeError, ValueError): return row[0]
    except Exception:
        try: cursor.close(); connection.close()
        except Exception: pass
        return default

def set_setting(key, value):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("INSERT INTO bot_settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)", (key, str(value)))
        connection.commit(); cursor.close(); connection.close()
        return True
    except Exception as e:
        print(f"❌ خطا در ذخیره تنظیمات: {e}")
        try: cursor.close(); connection.close()
        except Exception: pass
        return False

def setting_enabled(key, default=True):
    value = get_setting(key, 1 if default else 0)
    try:
        return bool(int(float(value)))
    except (TypeError, ValueError):
        return bool(value)


def get_self_profit_percent():
    return float(get_setting('self_profit_percent', SELF_PROFIT_PERCENT) or 0)

def get_product_profit_percent(product):
    """درصد سود اختصاصی محصول را با Decimal دقیق از دیتابیس می‌خواند."""
    try:
        product_id = int(product[0]) if product else 0
    except Exception:
        product_id = 0
    if not product_id:
        return Decimal('0')
    conn = get_db_connection()
    if not conn:
        return Decimal('0')
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT product_profit_percent FROM products WHERE id=%s LIMIT 1", (product_id,))
        row = cur.fetchone()
        return Decimal(str(row.get('product_profit_percent') if row and row.get('product_profit_percent') is not None else 0))
    except Exception:
        return Decimal('0')
    finally:
        try:
            if cur: cur.close()
            conn.close()
        except Exception:
            pass

def format_profit_percent(value):
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
        return format(d, 'f').rstrip('0').rstrip('.') or '0'
    except Exception:
        return '0'

def get_referral_percent():
    return float(get_setting('referral_percent', COMMISSION_PERCENT) or 0)

def apply_product_profit(price, profit_percent):
    """Apply product-specific profit using exact Decimal arithmetic."""
    try:
        base = price if isinstance(price, Decimal) else Decimal(str(price))
        percent = profit_percent if isinstance(profit_percent, Decimal) else Decimal(str(profit_percent or 0))
        if percent < 0:
            percent = Decimal('0')
        result = base * (Decimal('100') + percent) / Decimal('100')
        return int(result.to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, TypeError, ValueError):
        return 0

def apply_self_profit(price):
    """سازگاری با بخش‌های قدیمی؛ سود پیش‌فرض تنظیمات عمومی را اعمال می‌کند."""
    return apply_product_profit(price, Decimal(str(get_self_profit_percent() or 0)))

def format_product_admin_price_lines(product):
    code, currency, amount, rate = get_product_currency(product)
    if code == 'TOMAN':
        return (f"💰 قیمت پایه: {format_amount(amount)} تومان\n"
                f"📈 سود محصول: {format_profit_percent(get_product_profit_percent(product))}%\n"
                f"💵 قیمت فروش: {format_amount(apply_product_profit(amount, get_product_profit_percent(product)))} تومان\n")
    toman = calculate_product_base_toman(product)
    profit = get_product_profit_percent(product)
    sold = apply_product_profit(toman, profit)
    return (f"💰 قیمت پایه: {format_amount(amount)} {html.escape(str(currency.get('symbol') or code))} ({html.escape(code)})\n"
            f"💱 نرخ فعلی: {format_amount(rate)} تومان برای 1 {html.escape(code)}\n"
            f"💵 معادل قیمت: {format_amount(toman)} تومان\n"
            f"📈 سود محصول: {format_profit_percent(profit)}%\n"
            f"💵 قیمت فروش: {format_amount(sold)} تومان\n")

def get_product_currency(product):
    """Return product pricing currency and current Toman rate.

    Pricing columns are read by name so this works with both freshly-created
    and migrated products tables where ALTER TABLE may have appended columns.
    """
    code = 'TOMAN'
    amount = None
    product_id = None
    try:
        product_id = int(product[0]) if product else None
    except Exception:
        product_id = None

    if product_id:
        conn = get_db_connection()
        if conn:
            cur = None
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute("SELECT price, price_currency, price_amount FROM products WHERE id=%s LIMIT 1", (product_id,))
                row = cur.fetchone()
                if row:
                    code = str(row.get('price_currency') or 'TOMAN').upper()
                    amount = row.get('price_amount')
                    if amount is None:
                        amount = row.get('price', 0)
            except Exception:
                pass
            finally:
                try:
                    if cur: cur.close()
                    conn.close()
                except Exception:
                    pass

    if amount is None:
        try:
            amount = product[4] if product else 0
        except Exception:
            amount = 0
        code = 'TOMAN'

    currency = get_currency(code) if code != 'TOMAN' else {'code':'TOMAN','name':'تومان','symbol':'تومان','rate':1,'icon':'🇮🇷'}
    if not currency:
        code = 'TOMAN'
        currency = {'code':'TOMAN','name':'تومان','symbol':'تومان','rate':1,'icon':'🇮🇷'}
    try:
        rate = Decimal(str(currency.get('rate') or 1))
        if rate <= 0:
            rate = Decimal('1')
    except Exception:
        rate = Decimal('1')
    try:
        amount = Decimal(str(amount))
    except Exception:
        amount = Decimal('0')
    return code, currency, amount, rate

def calculate_product_base_toman(product):
    code, currency, amount, rate = get_product_currency(product)
    if code == 'TOMAN':
        return amount
    return amount * rate

def calculate_price_info(product):
    base_toman = calculate_product_base_toman(product)
    price_per = product[5] if len(product) > 5 and product[5] else 1
    min_order = product[6] if len(product) > 6 else 1
    max_order = product[7] if len(product) > 7 else None
    need_link = product[8] if len(product) > 8 else 0
    profit_percent = get_product_profit_percent(product)
    price = apply_product_profit(base_toman, profit_percent)
    price_per_unit = calculate_total_price(price, price_per, 1) if price_per > 0 else price
    code, currency, amount, rate = get_product_currency(product)
    return {
        'price': int(price), 'base_price': base_toman, 'profit_percent': float(profit_percent),
        'price_per': price_per, 'price_per_unit': price_per_unit, 'min_order': min_order or 1,
        'max_order': max_order, 'need_link': need_link, 'currency_code': code,
        'currency_symbol': currency.get('symbol') or code, 'currency_amount': amount, 'currency_rate': rate
    }

def calculate_total_price(base_price, price_per, quantity):
    """Calculate final payable Tomans with Decimal arithmetic, rounded upward once."""
    try:
        base = base_price if isinstance(base_price, Decimal) else Decimal(str(base_price))
        qty = Decimal(str(quantity))
        per = Decimal(str(price_per))
        if per <= 0:
            return 0
        total = (base * qty) / per
        return int(total.to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, TypeError, ValueError):
        return 0

def format_product_price(price_info):
    if price_info['price_per'] > 1:
        return f"💸 قیمت (به ازای {price_info['price_per']:,} عدد) : {price_info['price']:,} تومان - قیمت هر عدد : {price_info['price_per_unit']:,} تومان"
    else:
        return f"💸 قیمت (به ازای 1 عدد) : {price_info['price']:,} تومان"

# ==================== SMS OTP ====================
def send_verification_sms(phone_number, code):
    url = "https://api.sms.ir/v1/send/verify"

    if phone_number.startswith("0"):
        mobile = phone_number[1:]
    else:
        mobile = phone_number

    payload = json.dumps({
        "mobile": mobile,
        "templateId": SMS_IR_VERIFY_TEMPLATE_ID,
        "parameters": [
            {
                "name": "Code",
                "value": str(code)
            }
        ]
    })

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'text/plain',
        'x-api-key': SMS_IR_API_KEY
    }

    try:
        response = requests.post(url, headers=headers, data=payload, timeout=12)
        response.raise_for_status()
        result = response.json()
        print(f"✅ پیامک با موفقیت ارسال شد. Message ID: {result['data']['messageId']}")
        return True, result
    except requests.exceptions.RequestException as e:
        print(f"❌ خطا در ارسال پیامک: {e}")
        if e.response is not None:
            try:
                error_data = e.response.json()
                print(f"📝 پیغام خطای sms.ir: {error_data.get('message')}")
            except:
                pass
        return False, None

def send_telegram_message_sync(chat_id, text, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ خطا در ارسال پیام sync: {e}")
        return None

# ==================== توابع زرین‌پال ====================
def zarinpal_request_payment(amount, description, user_id, payment_tracking_code, mobile=None, email=None):
    try:
        metadata = {}
        if mobile:
            metadata["mobile"] = mobile
        if email:
            metadata["email"] = email

        data = {
            "merchant_id": ZARINPAL_MERCHANT,
            "amount": amount * 10,
            "callback_url": ZARINPAL_CALLBACK_URL,
            "description": description[:500],
        }

        if metadata:
            data["metadata"] = metadata

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        response = requests.post(ZARINPAL_API_REQUEST, json=data, headers=headers, timeout=30)

        result = response.json()

        if "data" in result and result["data"].get("code") == 100:
            authority = result["data"]["authority"]

            connection = get_db_connection()
            if connection:
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        "INSERT INTO zarinpal_transactions (user_id, amount, authority, payment_tracking_code) VALUES (%s, %s, %s, %s)",
                        (user_id, amount, authority, payment_tracking_code)
                    )
                    transaction_id = cursor.lastrowid

                    cursor.execute(
                        """INSERT INTO zarinpal_verification_queue 
                        (authority, amount, user_id, payment_tracking_code, scheduled_check_time, status) 
                        VALUES (%s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL 30 MINUTE), 'scheduled')""",
                        (authority, amount, user_id, payment_tracking_code)
                    )
                    queue_id = cursor.lastrowid

                    cursor.execute(
                        "UPDATE zarinpal_transactions SET queue_id = %s WHERE id = %s",
                        (queue_id, transaction_id)
                    )

                    connection.commit()
                    cursor.close()
                    connection.close()
                except Exception as e:
                    print(f"❌ خطا در ذخیره تراکنش زرین‌پال: {e}")

            return {
                "success": True,
                "authority": authority,
                "payment_url": f"{ZARINPAL_START_PAY}{authority}"
            }
        else:
            error_msg = "خطا در اتصال به درگاه پرداخت"
            if "errors" in result and len(result["errors"]) > 0:
                errors = result["errors"]
                if isinstance(errors, list):
                    error_msg = f"خطای درگاه: {errors[0] if isinstance(errors[0], str) else errors[0].get('message', errors[0])}"

            return {
                "success": False,
                "error": error_msg
            }
    except json.JSONDecodeError as e:
        print(f"❌ خطا در پردازش JSON: {e}")
        return {"success": False, "error": "خطا در پردازش پاسخ درگاه"}
    except Exception as e:
        print(f"❌ خطا در زرین‌پال: {e}")
        return {"success": False, "error": "خطا در اتصال به درگاه پرداخت"}

def zarinpal_verify_payment(authority, amount):
    return integration.verify(authority,amount)


def get_active_zarinpal_transaction(user_id):
    connection = get_db_connection()
    if not connection:
        return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT zt.*, zvq.status as queue_status, zvq.scheduled_check_time 
            FROM zarinpal_transactions zt 
            LEFT JOIN zarinpal_verification_queue zvq ON zt.queue_id = zvq.id 
            WHERE zt.user_id = %s AND zt.status = 'pending' 
            AND zvq.status IN ('scheduled', 'checking')
            ORDER BY zt.created_at DESC LIMIT 1""",
            (user_id,)
        )
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result
    except Exception as e:
        print(f"❌ خطا در بررسی تراکنش فعال: {e}")
        return None

def cancel_zarinpal_transaction(user_id):
    connection = get_db_connection()
    if not connection:
        return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT zt.*, zvq.id as queue_id 
            FROM zarinpal_transactions zt 
            LEFT JOIN zarinpal_verification_queue zvq ON zt.queue_id = zvq.id 
            WHERE zt.user_id = %s AND zt.status = 'pending' 
            AND zvq.status IN ('scheduled', 'checking')
            ORDER BY zt.created_at DESC LIMIT 1""",
            (user_id,)
        )
        transaction = cursor.fetchone()

        if transaction:
            cursor.execute(
                "UPDATE zarinpal_transactions SET status = 'cancelled' WHERE id = %s",
                (transaction['id'],)
            )
            if transaction.get('queue_id'):
                cursor.execute(
                    "UPDATE zarinpal_verification_queue SET status = 'expired' WHERE id = %s",
                    (transaction['queue_id'],)
                )
            connection.commit()
            cursor.close()
            connection.close()
            return transaction
        cursor.close()
        connection.close()
        return None
    except Exception as e:
        print(f"❌ خطا در لغو تراکنش: {e}")
        return None

def run_verification_queue():
    sleep(5)
    while True:
        conn=None
        try:
            conn=get_db_connection()
            if not conn:
                sleep(30);continue
            cur=conn.cursor(dictionary=True)
            cur.execute("SELECT authority FROM zarinpal_verification_queue WHERE status IN ('scheduled','checking') AND scheduled_check_time<=NOW() AND retry_count<12 LIMIT 10")
            checks=cur.fetchall();cur.close();conn.close();conn=None
            for check in checks:
                result=integration.verify(check['authority'])
                if not result['success']:
                    conn=get_db_connection();cur=conn.cursor()
                    cur.execute("UPDATE zarinpal_verification_queue SET status='scheduled',retry_count=retry_count+1,scheduled_check_time=DATE_ADD(NOW(),INTERVAL 10 MINUTE),last_error=%s WHERE authority=%s AND status!='completed'",(result.get('error','Verification pending'),check['authority']))
                    conn.commit();cur.close();conn.close();conn=None
        except Exception:
            logger.exception('Gateway verification queue failed')
        finally:
            if conn: conn.close()
        sleep(30)


# ==================== مدیریت دیتابیس ====================
def get_db_connection():
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"❌ خطا در اتصال به دیتابیس: {e}")
        return None

def init_database():
    connection = get_db_connection()
    if not connection:
        return False

    try:
        cursor = connection.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name VARCHAR(255),
                username VARCHAR(255),
                phone_number VARCHAR(20),
                is_verified TINYINT(1) DEFAULT 0,
                is_banned TINYINT(1) DEFAULT 0,
                ban_reason TEXT,
                banned_at TIMESTAMP NULL,
                balance BIGINT DEFAULT 0,
                total_payments BIGINT DEFAULT 0,
                total_purchases BIGINT DEFAULT 0,
                income BIGINT DEFAULT 0,
                subsets_count INT DEFAULT 0,
                subsets_commission BIGINT DEFAULT 0,
                consumed_gift BIGINT DEFAULT 0,
                referrer_id BIGINT,
                referral_code VARCHAR(50) UNIQUE,
                join_date VARCHAR(25),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        for col, col_type in [
            ("is_banned", "TINYINT(1) DEFAULT 0"),
            ("ban_reason", "TEXT"),
            ("banned_at", "TIMESTAMP NULL"),
            ("consumed_gift", "BIGINT DEFAULT 0"),
            ("is_blocked", "TINYINT(1) DEFAULT 0"),
            ("rules_accepted", "TINYINT(1) DEFAULT 0"),
            ("pending_referrer_id", "BIGINT NULL"),
            ("last_activity_at", "TIMESTAMP NULL")
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except:
                pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_verification (
                user_id BIGINT PRIMARY KEY,
                national_id VARCHAR(20) NULL,
                birth_certificate_number VARCHAR(50) NULL,
                birth_date VARCHAR(30) NULL,
                father_name VARCHAR(255) NULL,
                bank_card_number VARCHAR(32) NULL,
                identity_document_type VARCHAR(50) NULL,
                identity_document_file_id VARCHAR(500) NULL,
                notes TEXT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # Persistent SMS verification state. This keeps the 5-minute code validity
        # and the daily send limit even if the bot restarts or the conversation is reset.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phone_verification_codes (
                user_id BIGINT PRIMARY KEY,
                phone_number VARCHAR(20) NOT NULL,
                verification_code VARCHAR(10) NULL,
                expires_at DATETIME NULL,
                sent_date DATE NULL,
                sent_count INT NOT NULL DEFAULT 0,
                total_sent_count BIGINT NOT NULL DEFAULT 0,
                request_count BIGINT NOT NULL DEFAULT 0,
                last_code VARCHAR(10) NULL,
                first_request_at DATETIME NULL,
                last_request_at DATETIME NULL,
                last_sent_at DATETIME NULL,
                verification_attempts INT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        for col, col_type in [
            ("total_sent_count", "BIGINT NOT NULL DEFAULT 0"),
            ("request_count", "BIGINT NOT NULL DEFAULT 0"),
            ("last_code", "VARCHAR(10) NULL"),
            ("first_request_at", "DATETIME NULL"),
            ("last_request_at", "DATETIME NULL"),
            ("verification_attempts", "INT NOT NULL DEFAULT 0")
        ]:
            try:
                cursor.execute(f"ALTER TABLE phone_verification_codes ADD COLUMN {col} {col_type}")
            except:
                pass

        # Detailed SMS verification request history for admin analytics/search.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phone_verification_request_logs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                phone_number VARCHAR(20) NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'requested',
                sms_sent TINYINT(1) NOT NULL DEFAULT 0,
                details VARCHAR(255) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pvrl_created_at (created_at),
                INDEX idx_pvrl_user_created (user_id, created_at),
                INDEX idx_pvrl_phone (phone_number),
                INDEX idx_pvrl_status (status),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INT AUTO_INCREMENT PRIMARY KEY,
                referrer_id BIGINT,
                referred_user_id BIGINT UNIQUE,
                referral_code VARCHAR(50),
                join_date VARCHAR(25),
                total_commission BIGINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (referred_user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS support_messages (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                topic VARCHAR(255) NOT NULL,
                message_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                answered TINYINT(1) DEFAULT 0,
                answered_by BIGINT NULL,
                answered_at TIMESTAMP NULL,
                INDEX idx_support_answered (answered),
                INDEX idx_support_topic (topic),
                INDEX idx_support_user (user_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                setting_key VARCHAR(100) PRIMARY KEY,
                setting_value VARCHAR(100) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        cursor.execute("INSERT IGNORE INTO bot_settings (setting_key, setting_value) VALUES (%s, %s), (%s, %s)", ('self_profit_percent', str(SELF_PROFIT_PERCENT), 'referral_percent', str(COMMISSION_PERCENT)))
        cursor.execute("INSERT IGNORE INTO bot_settings (setting_key, setting_value) VALUES (%s,%s),(%s,%s),(%s,%s)", ('require_rules','1','require_channel_membership','1','require_verification','1'))
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gift_codes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(50) NOT NULL UNIQUE,
                amount BIGINT NOT NULL,
                is_active TINYINT(1) DEFAULT 1,
                max_uses INT DEFAULT 0,
                used_count INT DEFAULT 0,
                created_by BIGINT,
                target_type VARCHAR(50) DEFAULT 'all',
                target_value INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        for _col, _definition in [
            ('target_type', "VARCHAR(50) DEFAULT 'all'"),
            ('target_value', 'INT DEFAULT 0'),
            ('channel_message_id', 'BIGINT NULL'),
            ('channel_chat_id', 'BIGINT NULL')
        ]:
            try:
                cursor.execute(f"ALTER TABLE gift_codes ADD COLUMN {_col} {_definition}")
            except Exception:
                pass
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lottery_runs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                amount BIGINT NOT NULL,
                target_type VARCHAR(50) NOT NULL DEFAULT 'all',
                target_value INT DEFAULT 0,
                winner_id BIGINT NOT NULL,
                created_by BIGINT,
                channel_chat_id BIGINT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS gift_code_uses (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                gift_code_id INT NOT NULL,
                user_id BIGINT NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_gift_user (gift_code_id, user_id),
                FOREIGN KEY (gift_code_id) REFERENCES gift_codes(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        # Migration for older databases where gift_code_uses.amount is required or missing.
        try:
            cursor.execute("ALTER TABLE gift_code_uses ADD COLUMN amount BIGINT NOT NULL DEFAULT 0")
        except Exception:
            pass
        cursor.execute("INSERT IGNORE INTO bot_settings (setting_key, setting_value) VALUES (%s,%s),(%s,%s),(%s,%s),(%s,%s)",
                       ('min_charge_amount', str(MIN_CHARGE_AMOUNT), 'max_charge_amount', str(MAX_CHARGE_AMOUNT), 'min_stars', str(MIN_STARS), 'max_stars', str(MAX_STARS)))

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INT AUTO_INCREMENT PRIMARY KEY,
                method_key VARCHAR(50) NOT NULL UNIQUE,
                method_name VARCHAR(100) NOT NULL,
                is_active TINYINT(1) DEFAULT 1,
                disable_reason TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute("SELECT COUNT(*) FROM payment_methods")
        if cursor.fetchone()[0] == 0:
            default_methods = [
                ('online', '💸 پرداخت آنلاین', 1, ''),
                ('card', '💳 کارت به کارت', 1, ''),
                ('stars', '⭐️ پرداخت با استارز', 1, ''),
                ('crypto', '💰 پرداخت با ارز دیجیتال', 1, ''),
            ]
            cursor.executemany(
                "INSERT INTO payment_methods (method_key, method_name, is_active, disable_reason) VALUES (%s, %s, %s, %s)",
                default_methods
            )

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(500) NOT NULL,
                emoji VARCHAR(50),
                sort_order INT DEFAULT 0,
                is_active TINYINT(1) DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                category_id INT,
                name VARCHAR(500) NOT NULL,
                description TEXT,
                price BIGINT NOT NULL,
                price_per INT DEFAULT 1,
                min_order INT DEFAULT 1,
                max_order INT DEFAULT NULL,
                need_link TINYINT(1) DEFAULT 0,
                target_type VARCHAR(30) DEFAULT 'channel_group',
                target_prompt TEXT NULL,
                price_currency VARCHAR(20) DEFAULT 'TOMAN',
                price_amount DECIMAL(36,18) NULL,
                product_profit_percent DECIMAL(10,4) NOT NULL DEFAULT 0,
                is_active TINYINT(1) DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tracking_code VARCHAR(20),
                user_id BIGINT,
                product_id INT,
                product_name VARCHAR(500),
                target_link TEXT,
                quantity INT,
                unit_price BIGINT,
                total_price BIGINT,
                status VARCHAR(50) DEFAULT 'pending',
                completed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cancel_reason TEXT NULL,
                completion_message TEXT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        # Product order-input migration: channel/group link, numeric ID, email, or custom prompt.
        for col, col_type in [("target_type", "VARCHAR(30) DEFAULT 'channel_group'"), ("target_prompt", "TEXT NULL"), ("price_currency", "VARCHAR(20) DEFAULT 'TOMAN'"), ("price_amount", "DECIMAL(36,18) NULL"), ("product_profit_percent", "DECIMAL(10,4) NOT NULL DEFAULT 0")]:
            try:
                cursor.execute(f"ALTER TABLE products ADD COLUMN {col} {col_type}")
            except:
                pass
        # Ensure older databases also gain enough decimal precision for crypto prices.
        # DECIMAL(36,18) supports values such as 0.000000000000000001 without float loss.
        try:
            cursor.execute("ALTER TABLE products MODIFY COLUMN price_amount DECIMAL(36,18) NULL")
        except Exception:
            pass
        # برای محصولات قدیمی، سود پیش‌فرض قبلی را فقط در اولین مهاجرت قرار بده تا رفتار قبلی حفظ شود.
        try:
            cursor.execute("SELECT setting_value FROM bot_settings WHERE setting_key='product_profit_migrated_v30' LIMIT 1")
            migrated = cursor.fetchone()
            if not migrated:
                default_profit = str(SELF_PROFIT_PERCENT or 0)
                cursor.execute("UPDATE products SET product_profit_percent=%s WHERE product_profit_percent IS NULL OR product_profit_percent=0", (default_profit,))
                cursor.execute("INSERT INTO bot_settings (setting_key, setting_value) VALUES ('product_profit_migrated_v30','1') ON DUPLICATE KEY UPDATE setting_value='1'")
                connection.commit()
        except Exception:
            pass
        try:
            cursor.execute("UPDATE products SET target_type='none' WHERE COALESCE(need_link,0)=0 AND (target_type IS NULL OR target_type='channel_group')")
            connection.commit()
        except:
            pass

        for col, col_type in [("cancel_reason", "TEXT NULL"), ("completion_message", "TEXT NULL")]:
            try:
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
            except:
                pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                amount BIGINT,
                type VARCHAR(50),
                description TEXT,
                payment_tracking_code VARCHAR(10),
                status VARCHAR(50) DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS star_payments (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                stars_count INT NOT NULL,
                star_rate BIGINT NOT NULL,
                amount_toman BIGINT NOT NULL,
                payment_tracking_code VARCHAR(10) NOT NULL UNIQUE,
                telegram_payment_charge_id VARCHAR(255) NULL UNIQUE,
                provider_payment_charge_id VARCHAR(255),
                status VARCHAR(30) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS receipts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                amount BIGINT,
                photo_id VARCHAR(500),
                payment_method VARCHAR(50) DEFAULT 'card',
                payment_tracking_code VARCHAR(10),
                status VARCHAR(50) DEFAULT 'pending',
                admin_id BIGINT,
                charge_amount BIGINT,
                reject_reason TEXT,
                processed_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        # Migration for existing receipts tables.
        try:
            cursor.execute("ALTER TABLE receipts ADD COLUMN payment_method VARCHAR(50) DEFAULT 'card'")
        except Exception:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS currencies (
                id INT AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(20) NOT NULL UNIQUE,
                name VARCHAR(100) NOT NULL,
                symbol VARCHAR(20),
                rate BIGINT NOT NULL,
                type VARCHAR(50) DEFAULT 'crypto',
                icon VARCHAR(10),
                is_active TINYINT(1) DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute("SELECT COUNT(*) FROM currencies")
        if cursor.fetchone()[0] == 0:
            default_currencies = [
                ('STAR', 'استارز تلگرام', '⭐', 2900, 'telegram', '⭐️'),
                ('USD', 'دلار آمریکا', '$', 85000, 'fiat', '💵'),
                ('USDT', 'تتر', '₮', 88000, 'crypto', '₮'),
                ('BTC', 'بیتکوین', '₿', 5800000000, 'crypto', '₿'),
                ('ETH', 'اتریوم', 'Ξ', 280000000, 'crypto', 'Ξ'),
                ('TON', 'تون کوین', '💎', 550000, 'crypto', '💎'),
                ('TOMAN', 'تومان', 'تومان', 1, 'fiat', '🇮🇷'),
            ]
            cursor.executemany(
                "INSERT INTO currencies (code, name, symbol, rate, type, icon) VALUES (%s, %s, %s, %s, %s, %s)",
                default_currencies
            )

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zarinpal_transactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                amount BIGINT,
                authority VARCHAR(50),
                ref_id VARCHAR(50),
                status VARCHAR(50) DEFAULT 'pending',
                payment_tracking_code VARCHAR(10),
                queue_id INT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zarinpal_verification_queue (
                id INT AUTO_INCREMENT PRIMARY KEY,
                authority VARCHAR(50) UNIQUE NOT NULL,
                amount BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                payment_tracking_code VARCHAR(10),
                scheduled_check_time TIMESTAMP NOT NULL,
                status ENUM('scheduled', 'checking', 'completed', 'expired') DEFAULT 'scheduled',
                retry_count INT DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')

        try:
            cursor.execute("ALTER TABLE zarinpal_transactions ADD COLUMN queue_id INT NULL")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE zarinpal_transactions MODIFY COLUMN status VARCHAR(50) DEFAULT 'pending'")
        except:
            pass

        connection.commit()
        cursor.close()
        connection.close()
        print("✅ جداول با موفقیت ساخته شدند")
        return True
    except Error as e:
        print(f"❌ خطا در ساخت جداول: {e}")
        return False

# ==================== توابع عملیات دیتابیس ====================
def get_or_create_user(user_id, full_name, username, referrer_id=None):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            join_date = get_jalali_datetime()
            referral_code = generate_referral_code(user_id)
            cursor.execute(
                "INSERT INTO users (user_id, full_name, username, referrer_id, referral_code, join_date, last_activity_at) VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (user_id, full_name, username, referrer_id, referral_code, join_date)
            )
            if referrer_id:
                cursor.execute(
                    "INSERT INTO referrals (referrer_id, referred_user_id, referral_code, join_date) VALUES (%s, %s, %s, %s)",
                    (referrer_id, user_id, referral_code, join_date)
                )
                cursor.execute("UPDATE users SET subsets_count = subsets_count + 1 WHERE user_id = %s", (referrer_id,))
            connection.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()
        else:
            # هر بار که get_or_create_user در اثر /start یا ورود کاربر اجرا می‌شود،
            # آخرین فعالیت واقعی کاربر را هم ثبت می‌کنیم. این بخش برای کاربران قدیمی
            # مهم است چون TypeHandler ممکن است قبل از ساخته‌شدن رکورد اجرا شده باشد.
            cursor.execute(
                "UPDATE users SET last_activity_at=NOW(), full_name=%s, username=%s WHERE user_id=%s",
                (full_name, username or '', user_id)
            )
            user['last_activity_at'] = None  # مقدار از دیتابیس دوباره خوانده می‌شود
            cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            user = cursor.fetchone()
            if referrer_id and referrer_id != user_id and not user.get('referrer_id'):
                cursor.execute("UPDATE users SET referrer_id = %s WHERE user_id = %s AND referrer_id IS NULL", (referrer_id, user_id))
                if cursor.rowcount > 0:
                    cursor.execute(
                        "INSERT INTO referrals (referrer_id, referred_user_id, referral_code, join_date) VALUES (%s, %s, %s, %s)",
                        (referrer_id, user_id, user.get('referral_code', ''), get_jalali_datetime())
                    )
                    cursor.execute("UPDATE users SET subsets_count = subsets_count + 1 WHERE user_id = %s", (referrer_id,))
                    connection.commit()
                    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                    user = cursor.fetchone()
        cursor.close()
        connection.close()
        return user
    except Error as e:
        print(f"❌ خطا: {e}")
        return None

def set_pending_referrer(user_id, referrer_id):
    """Persist the referral source until the user completes channel/rules requirements."""
    if not referrer_id or int(referrer_id) == int(user_id):
        return False
    connection = get_db_connection()
    if not connection:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE users SET pending_referrer_id=%s WHERE user_id=%s AND referrer_id IS NULL AND (pending_referrer_id IS NULL OR pending_referrer_id=0)",
            (int(referrer_id), int(user_id))
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception:
        try: connection.rollback()
        except: pass
        logger.exception("failed setting pending referral user=%s referrer=%s", user_id, referrer_id)
        return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_pending_referrer(user_id):
    connection = get_db_connection()
    if not connection:
        return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT pending_referrer_id FROM users WHERE user_id=%s", (int(user_id),))
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] else None
    except Exception:
        logger.exception("failed reading pending referral user=%s", user_id)
        return None
    finally:
        try: cursor.close(); connection.close()
        except: pass

def clear_pending_referrer(user_id):
    connection = get_db_connection()
    if not connection:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET pending_referrer_id=NULL WHERE user_id=%s", (int(user_id),))
        connection.commit()
        return True
    except Exception:
        try: connection.rollback()
        except: pass
        return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def finalize_referral(user_id, referrer_id):
    """ثبت نهایی رفرال فقط بعد از تکمیل عضویت کانال و پذیرش قوانین."""
    if not referrer_id or int(referrer_id) == int(user_id):
        return False
    connection = get_db_connection()
    if not connection:
        return False
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT referrer_id, referral_code FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
        user = cursor.fetchone()
        if not user:
            connection.rollback()
            return False
        # اگر قبلاً رفرال ثبت شده، دوباره ثبت نکن.
        if user.get('referrer_id'):
            connection.rollback()
            return False
        cursor.execute("SELECT user_id, full_name FROM users WHERE user_id=%s LIMIT 1", (referrer_id,))
        referrer = cursor.fetchone()
        if not referrer:
            connection.rollback()
            return False
        cursor.execute("SELECT id FROM referrals WHERE referred_user_id=%s LIMIT 1", (user_id,))
        if cursor.fetchone():
            connection.rollback()
            return False
        join_date = get_jalali_datetime()
        cursor.execute("UPDATE users SET referrer_id=%s WHERE user_id=%s AND referrer_id IS NULL", (referrer_id, user_id))
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        cursor.execute(
            "INSERT INTO referrals (referrer_id, referred_user_id, referral_code, join_date) VALUES (%s,%s,%s,%s)",
            (referrer_id, user_id, str(referrer_id), join_date)
        )
        cursor.execute("UPDATE users SET subsets_count=COALESCE(subsets_count,0)+1 WHERE user_id=%s", (referrer_id,))
        cursor.execute("UPDATE users SET pending_referrer_id=NULL WHERE user_id=%s", (user_id,))
        connection.commit()
        logger.info("referral finalized referrer=%s referred=%s", referrer_id, user_id)
        return True
    except Exception:
        try: connection.rollback()
        except: pass
        logger.exception("failed finalizing referral referrer=%s referred=%s", referrer_id, user_id)
        return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_user_data(user_id):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""SELECT u.*, v.national_id, v.birth_certificate_number, v.birth_date, v.father_name,
               v.bank_card_number, v.identity_document_type, v.identity_document_file_id, v.notes AS verification_notes,
               COUNT(o.id) as orders_count, COALESCE(SUM(o.total_price), 0) as total_orders_amount
               FROM users u
               LEFT JOIN user_verification v ON v.user_id = u.user_id
               LEFT JOIN orders o ON u.user_id = o.user_id AND o.status = 'completed'
               WHERE u.user_id = %s GROUP BY u.user_id""", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        connection.close()
        if row:
            return {
                "user_id": row['user_id'], "full_name": row['full_name'], "username": row['username'],
                "phone_number": row['phone_number'], "is_verified": row['is_verified'],
                "is_banned": row.get('is_banned', 0), "ban_reason": row.get('ban_reason', ''),
                "balance": row['balance'], "total_payments": row['total_payments'],
                "total_purchases": row['total_purchases'], "income": row['income'],
                "subsets_count": row['subsets_count'], "subsets_commission": row['subsets_commission'],
                "consumed_gift": row.get('consumed_gift', 0),
                "referrer_id": row['referrer_id'], "referral_code": row['referral_code'],
                "join_date": row['join_date'], "orders_count": row['orders_count'],
                "national_id": row.get('national_id'), "birth_certificate_number": row.get('birth_certificate_number'),
                "birth_date": row.get('birth_date'), "father_name": row.get('father_name'),
                "bank_card_number": row.get('bank_card_number'), "identity_document_type": row.get('identity_document_type'),
                "identity_document_file_id": row.get('identity_document_file_id'), "verification_notes": row.get('verification_notes')
            }
        return None
    except Error as e:
        print(f"❌ خطا: {e}")
        return None

def save_phone_number(user_id, phone_number):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET phone_number = %s WHERE user_id = %s", (phone_number, user_id))
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e: return False

def verify_user(user_id):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_verified = 1 WHERE user_id = %s", (user_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e: return False

SMS_DAILY_LIMIT = 3
SMS_CODE_VALID_MINUTES = 5
SMS_MAX_ATTEMPTS = 5
SMS_RESEND_COOLDOWN_SECONDS = 30

def get_phone_verification_state(user_id):
    connection = get_db_connection()
    if not connection:
        return None
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, phone_number, verification_code, expires_at, sent_date, sent_count, "
            "total_sent_count, request_count, last_code, first_request_at, last_request_at, last_sent_at, verification_attempts, "
            "(expires_at IS NOT NULL AND expires_at > NOW()) AS is_active, "
            "(sent_date IS NOT NULL AND sent_date = CURDATE()) AS sent_today "
            "FROM phone_verification_codes WHERE user_id = %s LIMIT 1",
            (int(user_id),)
        )
        return cursor.fetchone()
    except Error as e:
        logger.error("phone verification state read failed user=%s: %s", user_id, e)
        return None
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def _record_phone_verification_request(user_id, phone_number):
    """Count every attempt, even when no new SMS is sent."""
    connection = get_db_connection()
    if not connection:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO phone_verification_codes
                (user_id, phone_number, request_count, first_request_at, last_request_at)
            VALUES (%s, %s, 1, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                request_count = request_count + 1,
                first_request_at = COALESCE(first_request_at, NOW()),
                last_request_at = NOW()
            """,
            (int(user_id), str(phone_number))
        )
        connection.commit()
        return True
    except Error as e:
        logger.error("phone verification request counter failed user=%s: %s", user_id, e)
        return False
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def log_phone_verification_event(user_id, phone_number, status, sms_sent=False, details=None):
    connection = get_db_connection()
    if not connection:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO phone_verification_request_logs (user_id, phone_number, status, sms_sent, details) VALUES (%s,%s,%s,%s,%s)",
            (int(user_id), str(phone_number), str(status)[:30], 1 if sms_sent else 0, str(details)[:255] if details else None)
        )
        connection.commit()
        return True
    except Error as e:
        logger.error("phone verification event log failed user=%s: %s", user_id, e)
        return False
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def request_phone_verification_code(user_id, phone_number, force_new=False):
    """Request an OTP. Active codes are reused normally; force_new is used by the resend button.
    Every request is logged and only successfully sent SMS messages consume the daily quota."""
    state = get_phone_verification_state(user_id)
    _record_phone_verification_request(user_id, phone_number)

    if state:
        expires_at = state.get('expires_at')
        same_phone = str(state.get('phone_number') or '') == str(phone_number)
        active_code = str(state.get('verification_code') or '').strip()
        if same_phone and active_code and bool(state.get('is_active')) and not force_new:
            log_phone_verification_event(user_id, phone_number, 'existing', False, 'active code reused')
            return {'status': 'existing', 'code': active_code, 'expires_at': expires_at,
                    'sent_count': int(state.get('sent_count') or 0)}

        sent_count = int(state.get('sent_count') or 0) if bool(state.get('sent_today')) else 0
        if sent_count >= SMS_DAILY_LIMIT:
            log_phone_verification_event(user_id, phone_number, 'limit', False, 'daily sms limit reached')
            return {'status': 'limit', 'sent_count': sent_count}

    if force_new and state:
        last_sent_at = state.get('last_sent_at')
        if last_sent_at:
            try:
                import datetime as _dt
                elapsed = (_dt.datetime.now() - last_sent_at).total_seconds()
                if elapsed < SMS_RESEND_COOLDOWN_SECONDS:
                    remaining = max(1, int(SMS_RESEND_COOLDOWN_SECONDS - elapsed))
                    log_phone_verification_event(user_id, phone_number, 'cooldown', False, f'resend cooldown {remaining}s')
                    return {'status': 'cooldown', 'remaining': remaining, 'sent_count': sent_count}
            except Exception:
                pass

    code = generate_verification_code()
    success, sms_result = send_verification_sms(phone_number, code)
    if not success:
        logger.warning("verification SMS send failed user=%s phone=%s result=%s", user_id, phone_number, sms_result)
        log_phone_verification_event(user_id, phone_number, 'error', False, sms_result)
        return {'status': 'error'}

    connection = get_db_connection()
    if not connection:
        return {'status': 'error'}
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO phone_verification_codes
                (user_id, phone_number, verification_code, expires_at, sent_date, sent_count,
                 total_sent_count, last_code, first_request_at, last_request_at, last_sent_at, verification_attempts)
            VALUES
                (%s, %s, %s, DATE_ADD(NOW(), INTERVAL 5 MINUTE), CURDATE(), 1,
                 1, %s, NOW(), NOW(), NOW(), 0)
            ON DUPLICATE KEY UPDATE
                phone_number = VALUES(phone_number),
                verification_code = VALUES(verification_code),
                expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE),
                sent_count = IF(sent_date = CURDATE(), sent_count + 1, 1),
                total_sent_count = total_sent_count + 1,
                last_code = VALUES(last_code),
                sent_date = CURDATE(),
                last_sent_at = NOW(),
                verification_attempts = 0
            """,
            (int(user_id), str(phone_number), str(code), str(code))
        )
        connection.commit()
        log_phone_verification_event(user_id, phone_number, 'sent', True, 'new sms sent')
        return {'status': 'sent', 'code': str(code)}
    except Error as e:
        logger.error("phone verification state save failed user=%s: %s", user_id, e)
        log_phone_verification_event(user_id, phone_number, 'error', False, e)
        return {'status': 'error'}
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def increment_phone_verification_attempt(user_id):
    """Atomically count an OTP attempt and return the new count."""
    connection = get_db_connection()
    if not connection:
        return None
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE phone_verification_codes SET verification_attempts = verification_attempts + 1 WHERE user_id=%s AND verification_code IS NOT NULL AND expires_at > NOW()",
            (int(user_id),)
        )
        connection.commit()
        if cursor.rowcount != 1:
            return None
        cursor.execute("SELECT verification_attempts FROM phone_verification_codes WHERE user_id=%s", (int(user_id),))
        row = cursor.fetchone()
        return int(row[0]) if row else None
    except Error as e:
        logger.error("phone verification attempt counter failed user=%s: %s", user_id, e)
        return None
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def get_verification_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 درخواست مجدد کد", callback_data="resend_verification_code")]
    ])

def invalidate_phone_verification_code(user_id):
    connection = get_db_connection()
    if not connection:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE phone_verification_codes SET verification_code=NULL, expires_at=NULL, verification_attempts=0 WHERE user_id=%s",
            (int(user_id),)
        )
        connection.commit()
        return True
    except Error as e:
        logger.error("phone verification invalidate failed user=%s: %s", user_id, e)
        return False
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def consume_phone_verification_code(user_id):
    connection = get_db_connection()
    if not connection:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE phone_verification_codes SET verification_code=NULL, expires_at=NULL, verification_attempts=0 WHERE user_id=%s",
            (int(user_id),)
        )
        connection.commit()
        return True
    except Error:
        return False
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def update_user_balance(user_id, amount):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
        if amount > 0: cursor.execute("UPDATE users SET total_payments = total_payments + %s WHERE user_id = %s", (amount, user_id))
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e: return False

def deduct_user_balance(user_id, amount):
    """Atomically deduct balance only when the user has enough credit."""
    try:
        amount = int(amount)
    except Exception:
        return False
    if amount <= 0:
        return False
    connection = get_db_connection()
    if not connection:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s AND balance >= %s",
            (amount, user_id, amount)
        )
        ok = cursor.rowcount == 1
        connection.commit()
        cursor.close()
        connection.close()
        return ok
    except Error:
        try:
            connection.rollback()
            connection.close()
        except Exception:
            pass
        return False

def save_transaction(user_id, amount, type, description, payment_tracking_code=None):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO transactions (user_id, amount, type, description, payment_tracking_code) VALUES (%s, %s, %s, %s, %s)",
            (user_id, amount, type, description, payment_tracking_code)
        )
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e: return False

def get_all_categories():
    connection = get_db_connection()
    if not connection: return []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY sort_order ASC")
        return cursor.fetchall()
    except Error as e: return []
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_all_category_products_for_admin(category_id):
    """همه محصولات یک دسته برای پنل مدیریت؛ فعال و غیرفعال هر دو نمایش داده می‌شوند."""
    connection = get_db_connection()
    if not connection:
        return []
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT id, category_id, name, description, price, price_per, min_order, max_order, need_link, is_active, created_at
            FROM products
            WHERE category_id = %s
            ORDER BY id DESC
        """, (int(category_id),))
        return cursor.fetchall()
    except Exception:
        logger.exception("failed loading admin category products: category_id=%s", category_id)
        return []
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def get_category_products(category_id):
    """دریافت محصولات یک دسته برای کاربر؛ دقیقاً با همان منطق محصولات فعال پنل ادمین."""
    connection = get_db_connection()
    if not connection:
        logger.error("get_category_products: database connection unavailable category_id=%s", category_id)
        return []
    cursor = None
    try:
        cursor = connection.cursor()
        # دسته باید فعال باشد و محصول نیز فعال؛ JOIN جلوی mismatch بین شناسه دسته و محصول را می‌گیرد.
        cursor.execute("""
            SELECT p.*
            FROM products p
            INNER JOIN categories c ON c.id = p.category_id
            WHERE p.category_id = %s
              AND p.is_active = 1
              AND p.show_on_telegram = 1
              AND c.is_active = 1
            ORDER BY p.price ASC, p.id ASC
        """, (int(category_id),))
        rows = cursor.fetchall() or []
        if not rows:
            cursor.execute("SELECT COUNT(*) FROM products WHERE category_id=%s", (int(category_id),))
            total = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) FROM products WHERE category_id=%s AND is_active=1", (int(category_id),))
            active = int(cursor.fetchone()[0] or 0)
            logger.info("get_category_products: category_id=%s active_products=%s total_products=%s", category_id, active, total)
        else:
            logger.info("get_category_products: category_id=%s products=%s", category_id, len(rows))
        return rows
    except Error as e:
        logger.exception("get_category_products failed category_id=%s", category_id)
        return []
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def get_product_admin(product_id):
    """Load a product for the admin panel, including inactive products."""
    connection = get_db_connection()
    if not connection:
        return None
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        return cursor.fetchone()
    except Error:
        return None
    finally:
        try:
            if cursor:
                cursor.close()
            connection.close()
        except Exception:
            pass

def get_product(product_id):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM products WHERE id = %s AND is_active = 1 AND show_on_telegram = 1", (product_id,))
        return cursor.fetchone()
    except Error as e: return None
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_product_input_config(product):
    """Return product input config without relying on fragile SELECT * column positions."""
    if not product:
        return {"type": "none", "prompt": "", "label": ""}

    # id and legacy need_link are stable early columns; newer columns may have been
    # appended in a different order on upgraded databases, so fetch them by name.
    product_id = product[0]
    need_link = int(product[8] or 0) if len(product) > 8 else 0
    target_type = 'channel_group' if need_link else 'none'
    target_prompt = ''

    connection = get_db_connection()
    cursor = None
    if connection:
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT need_link, target_type, target_prompt FROM products WHERE id=%s LIMIT 1",
                (int(product_id),)
            )
            row = cursor.fetchone() or {}
            need_link = int(row.get('need_link') or 0)
            target_type = str(row.get('target_type') or ('channel_group' if need_link else 'none'))
            target_prompt = str(row.get('target_prompt') or '')
        except Error as e:
            logger.warning("failed reading product input config product=%s: %s", product_id, e)
        finally:
            try:
                if cursor: cursor.close()
                connection.close()
            except Exception:
                pass

    if not need_link and target_type == 'channel_group':
        target_type = 'none'

    labels = {
        'channel_group': 'لینک کانال/گروه',
        'numeric_id': 'آیدی عددی',
        'email': 'ایمیل',
        'username': 'یوزرنیم تلگرام',
        'custom': 'اطلاعات دلخواه',
        'none': 'بدون دریافت اطلاعات'
    }
    defaults = {
        'channel_group': '🔗 لینک کانال/گروه خود را ارسال کنید:',
        'numeric_id': '🆔 آیدی عددی خود را ارسال کنید:',
        'email': '📧 ایمیل خود را ارسال کنید:',
        'username': '👤 یوزرنیم تلگرام موردنظر را ارسال کنید تا استارز برای همان یوزرنیم ارسال شود.\n\nمثال: @username',
        'custom': '📝 اطلاعات موردنیاز سفارش را ارسال کنید:',
        'none': ''
    }
    return {
        "type": target_type,
        "prompt": target_prompt or defaults.get(target_type, defaults['custom']),
        "label": labels.get(target_type, target_type)
    }

def mask_phone(phone):
    phone = re.sub(r'\D', '', str(phone or ''))
    if len(phone) >= 6:
        return phone[:2] + '***' + phone[-3:]
    return phone or 'ثبت نشده'

async def send_successful_order_report(context, order):
    """Publish the exact-style successful purchase report to the configured report channel."""
    report_channel_id = REPORT_CHANNEL_ID
    try:
        user_data = get_user_data(order[2]) or {}
        buyer = mask_phone(user_data.get('phone_number'))
        product_name = html.escape(str(order[4] or '-'))
        quantity = int(order[6] or 0)
        total = format_amount(order[8] or 0)
        now_text = jdatetime.datetime.now().strftime('%Y/%m/%d - %H:%M')
        bot_username = str(BOT_USERNAME or '').strip()
        if bot_username and not bot_username.startswith('@'):
            bot_username = '@' + bot_username
        report = (
            '🛍 گزارش #خرید موفق\n\n'
            f'👤 خریدار: {html.escape(buyer)}\n'
            f'🛒 سفارش : {quantity:,} {product_name} 🎁\n'
            f'💳 مبلغ پرداخت شده: {total} تومان\n\n'
            f'⌛️{now_text}\n\n'
            f'🤖 {html.escape(bot_username)}'
        )
        report_keyboard = InlineKeyboardMarkup([[make_primary_inline_button('🛒 ثبت سفارش', f'order_{order[3]}')]])
        await context.bot.send_message(chat_id=report_channel_id, text=report, parse_mode='HTML', reply_markup=report_keyboard)
        logger.info('successful order report sent order=%s channel=%s', order[0], report_channel_id)
        return True
    except Exception:
        logger.exception('failed sending successful order report order=%s', order[0] if order else None)
        return False

def create_order(user_id, product_id, product_name, target_link, quantity, unit_price, total_price):
    connection = get_db_connection()
    if not connection: return None, None
    try:
        cursor = connection.cursor()
        tracking_code = generate_tracking_code()
        cursor.execute("INSERT INTO orders (tracking_code, user_id, product_id, product_name, target_link, quantity, unit_price, total_price) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                       (tracking_code, user_id, product_id, product_name, target_link, quantity, unit_price, total_price))
        order_id = cursor.lastrowid
        connection.commit()
        return order_id, tracking_code
    except Error as e: return None, None
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_order(order_id):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        return cursor.fetchone()
    except Error as e: return None
    finally:
        try: cursor.close(); connection.close()
        except: pass

def update_order_status(order_id, status):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        if status == 'completed': cursor.execute("UPDATE orders SET status = %s, completed_at = NOW() WHERE id = %s", (status, order_id))
        else: cursor.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
        connection.commit()
        return True
    except Error as e: return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def save_receipt(user_id, amount, photo_id, payment_tracking_code=None, payment_method='card'):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor()
        cursor.execute("INSERT INTO receipts (user_id, amount, photo_id, payment_method, payment_tracking_code) VALUES (%s, %s, %s, %s, %s)",
                       (user_id, amount, photo_id, payment_method or 'card', payment_tracking_code))
        receipt_id = cursor.lastrowid
        connection.commit()
        return receipt_id
    except Error as e: return None
    finally:
        try: cursor.close(); connection.close()
        except: pass

def update_receipt_status(receipt_id, status, admin_id=None, charge_amount=None, reject_reason=None):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE receipts SET status = %s, admin_id = %s, charge_amount = %s, reject_reason = %s, processed_at = NOW() WHERE id = %s",
                       (status, admin_id, charge_amount, reject_reason, receipt_id))
        connection.commit()
        return True
    except Error as e: return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_receipt_by_id(receipt_id):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM receipts WHERE id = %s", (receipt_id,))
        return cursor.fetchone()
    except Error as e: return None
    finally:
        try: cursor.close(); connection.close()
        except: pass


def claim_receipt(receipt_id, status, admin_id):
    """Atomically claim a pending receipt so an admin cannot process it twice."""
    connection = get_db_connection()
    if not connection:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE receipts SET status=%s, admin_id=%s, processed_at=NOW() WHERE id=%s AND status='pending'",
            (status, admin_id, int(receipt_id))
        )
        connection.commit()
        return cursor.rowcount == 1
    except Error:
        try: connection.rollback()
        except Exception: pass
        return False
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception: pass


async def admin_receipt_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restore the action buttons of a still-pending receipt."""
    query = update.callback_query
    await query.answer("🔙 برگشت")
    parts = query.data.split("_")
    if len(parts) != 4:
        return
    receipt_id = int(parts[3])
    receipt = get_receipt_by_id(receipt_id)
    if not receipt or str(receipt.get('status') or '').lower() != 'pending':
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await query.message.reply_text("⚠️ این رسید قبلاً پردازش شده است.", reply_markup=get_admin_panel_keyboard())
        return
    uid = int(receipt.get('user_id') or 0)
    amount = int(receipt.get('amount') or 0)
    pt = receipt.get('payment_tracking_code') or generate_payment_tracking()
    try:
        await query.edit_message_reply_markup(reply_markup=get_admin_action_keyboard(uid, amount, receipt_id, pt))
    except Exception:
        pass
    await reset_user_state(update, context)
    return ConversationHandler.END



def format_datetime_fa(value):
    """Format Gregorian DB datetimes as Jalali/Persian dates."""
    if not value:
        return "-"
    try:
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
                try:
                    value = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
        if isinstance(value, datetime):
            jdt = jdatetime.datetime.fromgregorian(datetime=value)
            return jdt.strftime("%Y/%m/%d - %H:%M:%S")
        return str(value)
    except Exception:
        return str(value)

def make_primary_inline_button(text, callback_data):
    """Create Telegram's new blue primary button when the installed PTB supports it.
    Older python-telegram-bot versions do not accept `style`; in that case we
    gracefully fall back to a normal inline button instead of crashing the bot.
    """
    try:
        return InlineKeyboardButton(text, callback_data=callback_data, style='primary')
    except TypeError:
        logger.warning("python-telegram-bot does not support InlineKeyboardButton.style; using normal button")
        return InlineKeyboardButton(text, callback_data=callback_data)

def get_transaction_type_fa(tx_type):
    labels = {
        "commission": "💎 پورسانت رفرال",
        "deposit": "💰 شارژ حساب",
        "withdraw": "💸 برداشت",
        "purchase": "🛒 خرید",
        "refund": "↩️ بازگشت وجه",
        "gift": "🎁 هدیه",
    }
    return labels.get(str(tx_type or "").lower(), "💳 تراکنش")

def get_transaction_status_fa(status):
    labels = {
        "completed": "✅ تکمیل شده",
        "success": "✅ موفق",
        "successful": "✅ موفق",
        "pending": "⏳ در انتظار",
        "failed": "❌ ناموفق",
        "cancelled": "❌ لغو شده",
    }
    return labels.get(str(status or "").lower(), "")

def format_transaction_text(t):
    amount = t[2] or 0
    emoji = "🟢" if amount > 0 else "🔴"
    sign = "+" if amount > 0 else "-"
    text = f"{emoji} <b>{sign}{abs(amount):,} تومان</b>\n"
    text += f"📝 {get_transaction_type_fa(t[3])}\n"
    if t[4]:
        text += f"💬 {t[4]}\n"
    status = get_transaction_status_fa(t[6] if len(t) > 6 else None)
    if status:
        text += f"📊 وضعیت: {status}\n"
    text += f"📅 تاریخ: {format_datetime_fa(t[7] if len(t) > 7 else None)}\n"
    return text

def format_order_text(o):
    status_map = {'pending':'⏳ در انتظار', 'confirmed':'🔄 تأیید شده', 'completed':'🎉 تکمیل شده', 'cancelled':'❌ لغو شده'}
    status = status_map.get(o[9], f"❓ {o[9]}")
    product_name = html.escape(str(o[4] or '-'))
    return (f"{status} <b>{product_name}</b>\n"
            f"💰 مبلغ: <b>{format_amount(o[8])} تومان</b>\n"
            f"📅 تاریخ: {format_datetime_fa(o[11])}\n")

def get_user_transactions_page(user_id, page=1, per_page=10):
    connection = get_db_connection()
    if not connection: return [], 0
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()[0]
        offset = (page - 1) * per_page
        cursor.execute(
            "SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (user_id, per_page, offset)
        )
        transactions = cursor.fetchall()
        cursor.close()
        connection.close()
        return transactions, total
    except Error as e:
        print(f"❌ خطا: {e}")
        return [], 0

def get_user_orders_page(user_id, page=1, per_page=10):
    connection = get_db_connection()
    if not connection: return [], 0
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = %s", (user_id,))
        total = cursor.fetchone()[0]
        offset = (page - 1) * per_page
        cursor.execute(
            "SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (user_id, per_page, offset)
        )
        orders = cursor.fetchall()
        cursor.close()
        connection.close()
        return orders, total
    except Error as e:
        print(f"❌ خطا: {e}")
        return [], 0

def get_user_transactions(user_id, limit=10):
    connection = get_db_connection()
    if not connection: return []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM transactions WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user_id, limit))
        return cursor.fetchall()
    except Error as e: return []
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_user_orders_list(user_id, limit=10):
    connection = get_db_connection()
    if not connection: return []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user_id, limit))
        return cursor.fetchall()
    except Error as e: return []
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_order_by_tracking(tracking_code):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM orders WHERE tracking_code = %s", (tracking_code,))
        return cursor.fetchone()
    except Error as e: return None
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_currency(code):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM currencies WHERE code = %s AND is_active = 1", (code,))
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result
    except Error as e:
        print(f"❌ خطا در get_currency: {e}")
        return None

def get_currency_rate(code):
    currency = get_currency(code)
    if currency:
        return currency['rate']
    return 0

def get_star_rate_toman():
    """نرخ دقیق هر STAR به تومان را فقط از جدول currencies می‌خواند.

    هیچ نرخ پیش‌فرض/fallback استفاده نمی‌شود تا در صورت حذف یا خراب بودن نرخ،
    حساب کاربر اشتباه شارژ نشود. چون موجودی حساب به تومانِ صحیح نگهداری می‌شود،
    نرخ STAR نیز باید عدد صحیح مثبت باشد.
    """
    currency = get_currency('STAR')
    if not currency:
        return None
    try:
        rate = Decimal(str(currency.get('rate')))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if rate <= 0 or rate != rate.to_integral_value():
        return None
    return rate

def get_all_currencies():
    connection = get_db_connection()
    if not connection: return []
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM currencies WHERE is_active = 1 ORDER BY type, code")
        result = cursor.fetchall()
        cursor.close()
        connection.close()
        return result
    except Error as e: return []
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_gift_code(code):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM gift_codes WHERE code=%s AND is_active=1", (code.upper(),))
        row = cursor.fetchone()
        cursor.close(); connection.close()
        return row
    except Error:
        logger.exception("get_gift_code failed code=%s", code)
        return None

async def update_published_gift_message(bot, gift_id):
    """Update the already-published gift post immediately after a redemption."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM gift_codes WHERE id=%s", (gift_id,))
        gift = cur.fetchone()
        if not gift or not gift.get("channel_message_id") or not gift.get("channel_chat_id"):
            return
        max_uses = int(gift.get("max_uses") or 0)
        used_count = int(gift.get("used_count") or 0)
        if max_uses > 0 and used_count >= max_uses:
            capacity_text = f"❌ <b>تکمیل شد — {used_count} نفر از {max_uses} نفر استفاده کردند</b>"
            urgency_text = "🔴 <b>این کد هدیه تمام شده است و دیگر قابل استفاده نیست.</b>"
        elif max_uses > 0:
            remaining = max(0, max_uses - used_count)
            capacity_text = f"{remaining} نفر باقی‌مانده از {max_uses} نفر"
            urgency_text = "⚠️ <b>ظرفیت استفاده از این کد محدود است؛ بهتر است هرچه سریع‌تر از این کد استفاده کنید.</b>"
        else:
            capacity_text = "نامحدود"
            urgency_text = "⚠️ <b>هر کاربر فقط یک‌بار می‌تواند از این کد استفاده کند.</b>"
        bot_url = f"https://t.me/{str(BOT_USERNAME).lstrip('@')}"
        channel_text = (f"🎁 <b>کد هدیه ویژه</b>\n\n"
                        f"🎟 کد: <code>{gift['code']}</code>\n"
                        f"💰 مبلغ هدیه: <b>{int(gift['amount']):,}</b> تومان\n"
                        f"👥 ظرفیت استفاده: <b>{capacity_text}</b>\n"
                        f"🎯 مجاز برای: <b>{gift_target_label(gift.get('target_type','all'), int(gift.get('target_value') or 0))}</b>\n\n"
                        f"{urgency_text}\n\n"
                        f"📌 <b>نحوه استفاده از کد:</b>\n"
                        f"وارد ربات شوید → <b>🎁 شارژ رایگان</b> → <b>🎟 کد هدیه</b> → کد را ارسال کنید.")
        channel_kb = InlineKeyboardMarkup([[InlineKeyboardButton('🤖 ورود به ربات', url=bot_url)]])
        await bot.edit_message_text(chat_id=int(gift['channel_chat_id']), message_id=int(gift['channel_message_id']), text=channel_text, parse_mode='HTML', reply_markup=channel_kb)
        logger.info("gift channel post updated gift_id=%s used=%s max=%s", gift_id, used_count, max_uses)
    except Exception:
        logger.exception("failed updating gift channel post gift_id=%s", gift_id)
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

def redeem_gift_code(user_id, code):
    connection = get_db_connection()
    if not connection: return (False, "❌ خطا در اتصال به دیتابیس.")
    try:
        connection.start_transaction()
        cur = connection.cursor(dictionary=True)
        cur.execute("SELECT * FROM gift_codes WHERE code=%s AND is_active=1 FOR UPDATE", (code.upper(),))
        gift = cur.fetchone()
        if not gift:
            connection.rollback(); return (False, "❌ کد هدیه پیدا نشد یا غیرفعال است.")
        # بررسی دسته‌بندی مجاز استفاده از کد هدیه
        target_type = gift.get('target_type') or 'all'
        target_value = int(gift.get('target_value') or 0)
        eligibility = {
            'verified': 'is_verified = 1',
            'unverified': 'is_verified = 0',
            'rules_pending': 'rules_accepted = 0',
            'buyers': 'total_purchases > 0',
            'no_buyers': 'COALESCE(total_purchases,0) = 0',
            'referrers': 'subsets_count > 0',
            'no_referrals': 'COALESCE(subsets_count,0) = 0',
            'new_today': 'created_at >= CURDATE()',
            'new_week': 'created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)',
            'new_month': 'created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)',
            'active': 'is_blocked = 0 AND is_banned = 0 AND last_activity_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)',
            'banned': 'is_banned = 1',
            'blocked': 'is_blocked = 1',
            'paid': 'COALESCE(total_payments,0) > 0',
            'no_payments': 'COALESCE(total_payments,0) = 0',
            'positive_balance': 'COALESCE(balance,0) > 0',
            'zero_balance': 'COALESCE(balance,0) = 0',
            'inactive_7': 'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 7 DAY)',
            'inactive_30': 'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 30 DAY)',
            'inactive_60': 'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 60 DAY)',
            'inactive_90': 'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 90 DAY)',
            'inactive_180': 'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 180 DAY)',
            'inactive_365': 'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 365 DAY)',
            'never_active': 'last_activity_at IS NULL',
            'new_3_month': 'created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)',
            'new_6_month': 'created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)',
            'new_year': 'created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)',
            'top_purchases': 'COALESCE(total_purchases,0) > 0',
            'top_referrals': 'COALESCE(subsets_count,0) > 0',
            'top_income': 'COALESCE(income,0) > 0',
            'top_balance': 'COALESCE(balance,0) > 0',
            'lottery_winners': 'EXISTS (SELECT 1 FROM lottery_runs lr WHERE lr.winner_id = users.user_id)',
            'gift_users': 'EXISTS (SELECT 1 FROM gift_code_uses gcu WHERE gcu.user_id = users.user_id)',
        }
        if target_type == 'min_referrals':
            condition, params = 'subsets_count >= %s', [target_value]
        elif target_type == 'min_purchases':
            condition, params = 'total_purchases >= %s', [target_value]
        elif target_type == 'high_referrals':
            condition, params = 'subsets_count > %s', [target_value]
        elif target_type == 'high_purchases':
            condition, params = 'total_purchases > %s', [target_value]
        else:
            condition, params = eligibility.get(target_type, '1=1'), []
        cur.execute(f"SELECT user_id FROM users WHERE user_id=%s AND {condition} LIMIT 1", tuple([user_id] + params))
        if not cur.fetchone():
            connection.rollback(); return (False, "❌ شما در گروه مجاز استفاده از این کد هدیه نیستید.")
        cur.execute("SELECT id FROM gift_code_uses WHERE gift_code_id=%s AND user_id=%s LIMIT 1", (gift['id'], user_id))
        if cur.fetchone():
            connection.rollback(); return (False, "❌ شما قبلاً از این کد هدیه استفاده کرده‌اید.")
        if int(gift['max_uses'] or 0) > 0 and int(gift['used_count'] or 0) >= int(gift['max_uses']):
            connection.rollback(); return (False, f"❌ ظرفیت استفاده از این کد هدیه تکمیل شده است.\n\n👥 تعداد استفاده: <b>{int(gift['used_count'] or 0)}</b> نفر از <b>{int(gift['max_uses'] or 0)}</b> نفر.\n🎁 اگر هدیه دیگری می‌خواهید، از یک کد جدید استفاده کنید.")
        cur.execute("INSERT INTO gift_code_uses (gift_code_id,user_id,amount) VALUES (%s,%s,%s)", (gift['id'], user_id, int(gift['amount'] or 0)))
        cur.execute("UPDATE gift_codes SET used_count=used_count+1 WHERE id=%s", (gift['id'],))
        cur.execute("UPDATE users SET balance=balance+%s, consumed_gift=consumed_gift+%s WHERE user_id=%s", (gift['amount'], gift['amount'], user_id))
        connection.commit()
        logger.info("gift redeemed code=%s user=%s amount=%s", code, user_id, gift['amount'])
        return (True, f"🎉 کد هدیه با موفقیت مصرف شد.\n\n💰 مبلغ هدیه: <b>{format_amount(int(gift['amount']))}</b> تومان")
    except Error:
        connection.rollback()
        logger.exception("gift redeem failed code=%s user=%s", code, user_id)
        return (False, "❌ هنگام مصرف کد هدیه خطایی رخ داد.")
    finally:
        try: cur.close(); connection.close()
        except: pass

def add_commission_to_referrer(referred_user_id, charge_amount):
    """پرداخت پورسانت رفرال از درصد ذخیره‌شده در bot_settings.
    برای سازگاری با داده‌های قدیمی، اگر رکورد referrals موجود نباشد از users.referrer_id هم استفاده می‌کند.
    """
    connection = get_db_connection()
    if not connection:
        logger.error("referral commission: database connection failed referred=%s", referred_user_id)
        return None
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT u.user_id AS referred_id, u.full_name AS referred_name,
                      COALESCE(r.referrer_id, u.referrer_id) AS referrer_id
               FROM users u
               LEFT JOIN referrals r ON r.referred_user_id = u.user_id
               WHERE u.user_id = %s
               LIMIT 1""",
            (referred_user_id,)
        )
        referral = cursor.fetchone()
        if not referral or not referral.get('referrer_id'):
            logger.warning("referral commission skipped: no referrer referred=%s", referred_user_id)
            return None

        referral_percent = get_referral_percent()
        try:
            charge_amount = int(charge_amount)
        except (TypeError, ValueError):
            charge_amount = 0
        commission = int(charge_amount * referral_percent / 100)
        logger.info(
            "referral commission calculated referred=%s referrer=%s charge=%s percent=%s commission=%s",
            referred_user_id, referral['referrer_id'], charge_amount, referral_percent, commission
        )
        if referral_percent <= 0 or commission <= 0:
            logger.warning(
                "referral commission is zero referred=%s referrer=%s charge=%s percent=%s",
                referred_user_id, referral['referrer_id'], charge_amount, referral_percent
            )
            return None

        # پورسانت رفرال فقط به «درآمد» اضافه می‌شود، نه موجودی قابل خرج.
        # همچنین این پورسانت نباید به عنوان تراکنش عادی کاربر ثبت شود.
        cursor.execute(
            """UPDATE users
               SET income = COALESCE(income,0) + %s,
                   subsets_commission = COALESCE(subsets_commission,0) + %s
               WHERE user_id = %s""",
            (commission, commission, referral['referrer_id'])
        )
        if cursor.rowcount != 1:
            connection.rollback()
            logger.error("referrer user not found referrer=%s referred=%s", referral['referrer_id'], referred_user_id)
            return None

        # اگر رکورد referrals وجود دارد، مجموع پورسانت را هم افزایش بده
        cursor.execute(
            "UPDATE referrals SET total_commission = COALESCE(total_commission,0) + %s WHERE referrer_id=%s AND referred_user_id=%s",
            (commission, referral['referrer_id'], referred_user_id)
        )
        connection.commit()

        # پورسانت رفرال عمداً در جدول transactions ثبت نمی‌شود
        # تا در «تراکنش‌های اخیر» کاربر نمایش داده نشود.
        logger.info(
            "referral commission paid referred=%s referrer=%s amount=%s percent=%s",
            referred_user_id, referral['referrer_id'], commission, referral_percent
        )
        return {
            'referrer_id': referral['referrer_id'],
            'referred_name': referral['referred_name'],
            'commission': commission,
            'charge_amount': charge_amount,
            'percent': referral_percent
        }
    except Exception:
        try: connection.rollback()
        except Exception: pass
        logger.exception("referral commission failed referred=%s charge=%s", referred_user_id, charge_amount)
        return None
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception: pass

def get_referrer_info_by_code(referral_code):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT user_id, full_name FROM users WHERE referral_code = %s OR user_id = %s", (referral_code, referral_code))
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result
    except Error as e: return None

def get_user_referral_code(user_id):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT referral_code FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        cursor.close()
        connection.close()
        return result[0] if result else None
    except Error as e: return None

# ==================== توابع مدیریت بن ====================
def ban_user(user_id, reason=""):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_banned = 1, ban_reason = %s, banned_at = NOW() WHERE user_id = %s", (reason, user_id))
        connection.commit()
        banned_users_notified.discard(user_id)
        return True
    except Error as e: return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def unban_user(user_id):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_banned = 0, ban_reason = NULL, banned_at = NULL WHERE user_id = %s", (user_id,))
        connection.commit()
        banned_users_notified.discard(user_id)
        return True
    except Error as e: return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

def is_user_banned(user_id):
    connection = get_db_connection()
    if not connection: return False, ""
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT is_banned, ban_reason FROM users WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        return (True, result[1] or "") if result and result[0] == 1 else (False, "")
    except Error as e: return False, ""
    finally:
        try: cursor.close(); connection.close()
        except: pass

# ==================== توابع مدیریت روش‌های پرداخت ====================
def get_payment_method_status(method_key):
    connection = get_db_connection()
    if not connection: return True, ""
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT is_active, disable_reason FROM payment_methods WHERE method_key = %s", (method_key,))
        result = cursor.fetchone()
        return (bool(result[0]), result[1] or "") if result else (True, "")
    except Error as e: return True, ""
    finally:
        try: cursor.close(); connection.close()
        except: pass

def get_all_payment_methods():
    connection = get_db_connection()
    if not connection: return []
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM payment_methods ORDER BY id")
        return cursor.fetchall()
    except Error as e: return []
    finally:
        try: cursor.close(); connection.close()
        except: pass

def toggle_payment_method(method_key, is_active, reason=""):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        if is_active:
            cursor.execute("UPDATE payment_methods SET is_active = 1, disable_reason = '' WHERE method_key = %s", (method_key,))
        else:
            cursor.execute("UPDATE payment_methods SET is_active = 0, disable_reason = %s WHERE method_key = %s", (reason, method_key))
        connection.commit()
        return True
    except Error as e: return False
    finally:
        try: cursor.close(); connection.close()
        except: pass

# ==================== توابع مدیریت دسته‌بندی و محصولات ====================
def add_category(name, emoji="", sort_order=0):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("INSERT INTO categories (name, emoji, sort_order, is_active) VALUES (%s, %s, %s, 1)", 
                       (name, emoji, sort_order))
        connection.commit()
        category_id = cursor.lastrowid
        cursor.close()
        connection.close()
        return category_id
    except Error as e:
        print(f"❌ خطا در افزودن دسته‌بندی: {e}")
        return False

def update_category(category_id, name=None, emoji=None):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        if name is not None and emoji is not None:
            cursor.execute("UPDATE categories SET name = %s, emoji = %s WHERE id = %s", (name, emoji, category_id))
        elif name is not None:
            cursor.execute("UPDATE categories SET name = %s WHERE id = %s", (name, category_id))
        elif emoji is not None:
            cursor.execute("UPDATE categories SET emoji = %s WHERE id = %s", (emoji, category_id))
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e:
        print(f"❌ خطا در ویرایش دسته‌بندی: {e}")
        return False

def delete_category(category_id):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE categories SET is_active = 0 WHERE id = %s", (category_id,))
        cursor.execute("UPDATE products SET is_active = 0 WHERE category_id = %s", (category_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e:
        print(f"❌ خطا در حذف دسته‌بندی: {e}")
        return False

def add_product(category_id, name, description, price, price_per=1, min_order=1, max_order=None, need_link=0, price_currency='TOMAN', price_amount=None, product_profit_percent=0):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO products (category_id, name, description, price, price_per, min_order, max_order, need_link, target_type, price_currency, price_amount, product_profit_percent, is_active) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        """, (category_id, name, description, price, price_per, min_order, max_order, need_link, 'channel_group' if need_link else 'none', price_currency, price_amount if price_amount is not None else price, product_profit_percent))
        connection.commit()
        product_id = cursor.lastrowid
        cursor.close()
        connection.close()
        return product_id
    except Error as e:
        print(f"❌ خطا در افزودن محصول: {e}")
        return False

def update_product(product_id, field, value):
    connection = get_db_connection()
    if not connection: return False
    try:
        cursor = connection.cursor()
        valid_fields = ['name', 'description', 'price', 'price_per', 'min_order', 'max_order', 'need_link', 'category_id', 'target_type', 'target_prompt', 'price_currency', 'price_amount', 'product_profit_percent']
        if field not in valid_fields:
            return False
        cursor.execute(f"UPDATE products SET {field} = %s WHERE id = %s", (value, product_id))
        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Error as e:
        print(f"❌ خطا در ویرایش محصول: {e}")
        return False

def delete_product(product_id):
    """حذف واقعی محصول از دیتابیس؛ فعال یا غیرفعال بودن مهم نیست."""
    connection = get_db_connection()
    if not connection:
        return False
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM products WHERE id = %s LIMIT 1", (int(product_id),))
        if not cursor.fetchone():
            return False
        cursor.execute("DELETE FROM products WHERE id = %s", (int(product_id),))
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        connection.commit()
        return True
    except Error as e:
        try: connection.rollback()
        except Exception: pass
        logger.exception("خطا در حذف محصول %s: %s", product_id, e)
        return False
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception: pass

def get_all_products_for_admin():
    connection = get_db_connection()
    if not connection: return []
    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT p.*, c.name as category_name 
            FROM products p 
            LEFT JOIN categories c ON p.category_id = c.id 
            WHERE p.is_active = 1 
            ORDER BY p.id DESC
        """)
        products = cursor.fetchall()
        cursor.close()
        connection.close()
        return products
    except Error as e:
        print(f"❌ خطا در دریافت محصولات: {e}")
        return []

def get_category_by_id(category_id):
    connection = get_db_connection()
    if not connection: return None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM categories WHERE id = %s AND is_active = 1", (category_id,))
        category = cursor.fetchone()
        cursor.close()
        connection.close()
        return category
    except Error as e:
        print(f"❌ خطا در دریافت دسته‌بندی: {e}")
        return None

# ==================== توابع مدیریت سفارشات ====================
def get_orders_by_status(status=None, page=1, per_page=10):
    connection = get_db_connection()
    if not connection: return [], 0
    try:
        cursor = connection.cursor()
        if status:
            cursor.execute("SELECT COUNT(*) FROM orders WHERE status = %s", (status,))
            total = cursor.fetchone()[0]
            offset = (page - 1) * per_page
            cursor.execute("""
                SELECT o.*, u.full_name, u.username 
                FROM orders o 
                JOIN users u ON o.user_id = u.user_id 
                WHERE o.status = %s 
                ORDER BY o.created_at DESC 
                LIMIT %s OFFSET %s
            """, (status, per_page, offset))
        else:
            cursor.execute("SELECT COUNT(*) FROM orders")
            total = cursor.fetchone()[0]
            offset = (page - 1) * per_page
            cursor.execute("""
                SELECT o.*, u.full_name, u.username 
                FROM orders o 
                JOIN users u ON o.user_id = u.user_id 
                ORDER BY o.created_at DESC 
                LIMIT %s OFFSET %s
            """, (per_page, offset))

        orders = cursor.fetchall()
        cursor.close()
        connection.close()
        return orders, total
    except Error as e:
        print(f"❌ خطا در دریافت سفارشات: {e}")
        return [], 0

# ==================== توابع آمار ====================
def get_total_stats():
    """آمار اصلی پنل مدیریت؛ هر شاخص مستقیماً از جدول مربوط به خودش محاسبه می‌شود."""
    conn = get_db_connection()
    if not conn: return {}
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        def scalar(sql, params=()):
            try:
                cur.execute(sql, params); row=cur.fetchone()
                if not row: return 0
                value=next(iter(row.values())); return value if value is not None else 0
            except Exception:
                logger.exception("stats query failed: %s", sql)
                try: conn.rollback()
                except Exception: pass
                return 0
        stats={}
        stats['total_users']=scalar("SELECT COUNT(*) FROM users")
        stats['banned_users']=scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=1")
        stats['blocked_users']=scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_blocked,0)=1")
        stats['verified_users']=scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_verified,0)=1")
        stats['unverified_users']=scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_verified,0)=0")
        stats['active_users']=scalar("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=0 AND COALESCE(is_blocked,0)=0 AND last_activity_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
        stats['new_users_today']=scalar("SELECT COUNT(*) FROM users WHERE created_at >= CURDATE() AND created_at < DATE_ADD(CURDATE(), INTERVAL 1 DAY)")
        stats['new_users_week']=scalar("SELECT COUNT(*) FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)")
        stats['new_users_month']=scalar("SELECT COUNT(*) FROM users WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
        stats['total_balance']=scalar("SELECT COALESCE(SUM(balance),0) FROM users")
        stats['total_orders']=scalar("SELECT COUNT(*) FROM orders")
        stats['pending_orders']=scalar("SELECT COUNT(*) FROM orders WHERE status='pending'")
        stats['confirmed_orders']=scalar("SELECT COUNT(*) FROM orders WHERE status='confirmed'")
        stats['completed_orders']=scalar("SELECT COUNT(*) FROM orders WHERE status='completed'")
        stats['cancelled_orders']=scalar("SELECT COUNT(*) FROM orders WHERE status='cancelled'")
        stats['sales_total']=scalar("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed'")
        stats['total_deposits']=scalar("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount > 0")
        stats['deposit_count_total']=scalar("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND amount > 0")
        stats['pending_receipts']=scalar("SELECT COUNT(*) FROM receipts WHERE status='pending'")
        profit_percent=float(get_self_profit_percent() or 0); stats['profit_percent']=profit_percent
        stats['profit_total']=int(float(stats['sales_total'] or 0)*profit_percent/(100.0+profit_percent)) if profit_percent>0 else 0
        stats['tickets_total']=scalar("SELECT COUNT(*) FROM support_messages")
        stats['tickets_unanswered']=scalar("SELECT COUNT(*) FROM support_messages WHERE answered=0")
        stats['tickets_answered']=scalar("SELECT COUNT(*) FROM support_messages WHERE answered=1")
        stats['total_products']=scalar("SELECT COUNT(*) FROM products WHERE is_active=1")
        stats['total_categories']=scalar("SELECT COUNT(*) FROM categories WHERE is_active=1")
        periods={
            'today':("created_at >= CURDATE() AND created_at < DATE_ADD(CURDATE(), INTERVAL 1 DAY)","created_at >= DATE_SUB(CURDATE(), INTERVAL 1 DAY) AND created_at < CURDATE()"),
            '7d':("created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)","created_at >= DATE_SUB(NOW(), INTERVAL 14 DAY) AND created_at < DATE_SUB(NOW(), INTERVAL 7 DAY)"),
            '30d':("created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)","created_at >= DATE_SUB(NOW(), INTERVAL 60 DAY) AND created_at < DATE_SUB(NOW(), INTERVAL 30 DAY)"),
            '3m':("created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)","created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH) AND created_at < DATE_SUB(NOW(), INTERVAL 3 MONTH)"),
            '6m':("created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)","created_at >= DATE_SUB(NOW(), INTERVAL 12 MONTH) AND created_at < DATE_SUB(NOW(), INTERVAL 6 MONTH)"),
            '1y':("created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)","created_at >= DATE_SUB(NOW(), INTERVAL 2 YEAR) AND created_at < DATE_SUB(NOW(), INTERVAL 1 YEAR)")}
        for key,(cond,prev) in periods.items():
            stats[f'orders_{key}']=scalar(f"SELECT COUNT(*) FROM orders WHERE {cond}")
            stats[f'completed_orders_{key}']=scalar(f"SELECT COUNT(*) FROM orders WHERE status='completed' AND {cond}")
            stats[f'pending_orders_{key}']=scalar(f"SELECT COUNT(*) FROM orders WHERE status='pending' AND {cond}")
            stats[f'cancelled_orders_{key}']=scalar(f"SELECT COUNT(*) FROM orders WHERE status='cancelled' AND {cond}")
            stats[f'sales_{key}']=scalar(f"SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed' AND {cond}")
            stats[f'orders_prev_{key}']=scalar(f"SELECT COUNT(*) FROM orders WHERE {prev}")
            stats[f'completed_orders_prev_{key}']=scalar(f"SELECT COUNT(*) FROM orders WHERE status='completed' AND {prev}")
            stats[f'sales_prev_{key}']=scalar(f"SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed' AND {prev}")
            stats[f'deposits_{key}']=scalar(f"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount > 0 AND {cond}")
            stats[f'deposit_count_{key}']=scalar(f"SELECT COUNT(*) FROM transactions WHERE type='deposit' AND amount > 0 AND {cond}")
            stats[f'deposits_prev_{key}']=scalar(f"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount > 0 AND {prev}")
            stats[f'deposit_count_prev_{key}']=scalar(f"SELECT COUNT(*) FROM transactions WHERE type='deposit' AND amount > 0 AND {prev}")
            stats[f'tickets_{key}']=scalar(f"SELECT COUNT(*) FROM support_messages WHERE {cond}")
            stats[f'tickets_answered_{key}']=scalar(f"SELECT COUNT(*) FROM support_messages WHERE answered=1 AND {cond}")
            stats[f'tickets_unanswered_{key}']=scalar(f"SELECT COUNT(*) FROM support_messages WHERE answered=0 AND {cond}")
            stats[f'tickets_prev_{key}']=scalar(f"SELECT COUNT(*) FROM support_messages WHERE {prev}")
            stats[f'new_users_{key}']=scalar(f"SELECT COUNT(*) FROM users WHERE {cond}")
            stats[f'new_users_prev_{key}']=scalar(f"SELECT COUNT(*) FROM users WHERE {prev}")
            stats[f'receipts_{key}']=scalar(f"SELECT COUNT(*) FROM receipts WHERE {cond}")
            stats[f'receipt_amount_{key}']=scalar(f"SELECT COALESCE(SUM(amount),0) FROM receipts WHERE {cond}")
            stats[f'receipts_prev_{key}']=scalar(f"SELECT COUNT(*) FROM receipts WHERE {prev}")
            stats[f'receipt_amount_prev_{key}']=scalar(f"SELECT COALESCE(SUM(amount),0) FROM receipts WHERE {prev}")
            stats[f'new_products_{key}']=scalar(f"SELECT COUNT(*) FROM products WHERE {cond}")
            stats[f'new_categories_{key}']=scalar(f"SELECT COUNT(*) FROM categories WHERE {cond}")
            stats[f'new_products_prev_{key}']=scalar(f"SELECT COUNT(*) FROM products WHERE {prev}")
            stats[f'new_categories_prev_{key}']=scalar(f"SELECT COUNT(*) FROM categories WHERE {prev}")
            stats[f'profit_{key}']=int(float(stats[f'sales_{key}'] or 0)*profit_percent/(100.0+profit_percent)) if profit_percent>0 else 0
            stats[f'profit_prev_{key}']=int(float(stats[f'sales_prev_{key}'] or 0)*profit_percent/(100.0+profit_percent)) if profit_percent>0 else 0
            stats[f'referral_commission_{key}']=scalar(f"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='commission' AND amount > 0 AND {cond}")
            stats[f'referral_commission_prev_{key}']=scalar(f"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='commission' AND amount > 0 AND {prev}")
            count=int(stats[f'completed_orders_{key}'] or 0); stats[f'avg_order_{key}']=float(stats[f'sales_{key}'] or 0)/count if count else 0
        for dst,src in {'orders_today':'orders_today','orders_week':'orders_7d','orders_month':'orders_30d','sales_today':'sales_today','sales_week':'sales_7d','sales_month':'sales_30d','deposits_today':'deposits_today','deposits_week':'deposits_7d','deposits_month':'deposits_30d','deposit_count_today':'deposit_count_today','deposit_count_week':'deposit_count_7d','deposit_count_month':'deposit_count_30d','tickets_today':'tickets_today','tickets_week':'tickets_7d','tickets_month':'tickets_30d','new_users_today':'new_users_today','new_users_week':'new_users_7d','new_users_month':'new_users_30d','receipts_today':'receipts_today','receipts_week':'receipts_7d','receipts_month':'receipts_30d','profit_today':'profit_today','profit_week':'profit_7d','profit_month':'profit_30d'}.items(): stats[dst]=stats.get(src,0)
        return stats
    except Exception:
        logger.exception("overall statistics failed"); return {}
    finally:
        try:
            if cur: cur.close()
            conn.close()
        except Exception: pass

async def track_user_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت آخرین فعالیت واقعی کاربر در ربات.

    هر پیام، /start، دکمه‌های Reply Keyboard و تمام کلیک‌های
    Inline Keyboard به‌عنوان فعالیت ثبت می‌شوند. ادمین‌ها از آمار کاربران حذف هستند.
    اگر رکورد کاربر هنوز ساخته نشده باشد، یک رکورد پایه ساخته می‌شود تا کلیک
    روی دکمه هم از همان لحظه اول در last_activity_at ثبت شود.
    """
    conn = None
    cur = None
    try:
        user = update.effective_user
        if not user or user.id in ADMIN_IDS:
            return
        conn = get_db_connection()
        if not conn:
            return
        cur = conn.cursor()
        # برای هر نوع Update (پیام، /start، Reply Keyboard، Inline Keyboard و Callback Query)
        # زمان فعالیت را مستقل از rowcount و بدون cache ثبت می‌کنیم.
        cur.execute(
            """INSERT INTO users (user_id, full_name, username, referral_code, join_date, last_activity_at)
               VALUES (%s, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                 last_activity_at=NOW(),
                 full_name=VALUES(full_name),
                 username=VALUES(username)""",
            (user.id, user.full_name or '', user.username or '',
             generate_referral_code(user.id), get_jalali_datetime())
        )
        conn.commit()
    except Exception:
        logger.exception("failed tracking user activity user=%s", getattr(update.effective_user, 'id', None))
    finally:
        try:
            if cur: cur.close()
        except Exception: pass
        try:
            if conn: conn.close()
        except Exception: pass


def get_users_page(page=1, per_page=10, search=None, category='all', threshold=None, search_mode='all'):
    conn=get_db_connection()
    if not conn: return [],0
    cur=None
    try:
        cur=conn.cursor(dictionary=True); where=[]; params=[]; q=(search or '').strip().lstrip('@')
        if q:
            like=f"%{q}%"
            if search_mode=='id':
                if not q.isdigit(): return [],0
                where.append('user_id=%s'); params.append(int(q))
            elif search_mode=='phone': where.append('phone_number LIKE %s'); params.append(like)
            elif search_mode=='username': where.append('username LIKE %s'); params.append(like)
            elif search_mode=='name': where.append('full_name LIKE %s'); params.append(like)
            else:
                if q.isdigit(): where.append('(user_id=%s OR phone_number LIKE %s OR username LIKE %s OR full_name LIKE %s)'); params += [int(q),like,like,like]
                else: where.append('(phone_number LIKE %s OR username LIKE %s OR full_name LIKE %s)'); params += [like,like,like]
        conditions={'banned':'COALESCE(is_banned,0)=1','verified':'COALESCE(is_verified,0)=1','unverified':'COALESCE(is_verified,0)=0','rules_pending':'COALESCE(rules_accepted,0)=0','blocked':'COALESCE(is_blocked,0)=1','new_today':'created_at >= CURDATE()','new_week':'created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)','new_month':'created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)','new_3_month':'created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)','new_6_month':'created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)','new_year':'created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)','inactive_7':'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 7 DAY)','inactive_30':'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 30 DAY)','inactive_60':'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 60 DAY)','inactive_90':'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 90 DAY)','inactive_180':'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 180 DAY)','inactive_365':'last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 365 DAY)','never_active':'last_activity_at IS NULL','top_purchases':'COALESCE(total_purchases,0)>0','top_referrals':'COALESCE(subsets_count,0)>0','top_income':'COALESCE(income,0)>0','top_balance':'COALESCE(balance,0)>0','lottery_winners':'EXISTS (SELECT 1 FROM lottery_runs lr WHERE lr.winner_id=users.user_id)','gift_users':'EXISTS (SELECT 1 FROM gift_code_uses gcu WHERE gcu.user_id=users.user_id)','buyers':'COALESCE(total_purchases,0)>0','no_buyers':'COALESCE(total_purchases,0)=0','referrers':'COALESCE(subsets_count,0)>0','no_referrals':'COALESCE(subsets_count,0)=0','paid':'COALESCE(total_payments,0)>0','no_payments':'COALESCE(total_payments,0)=0','positive_balance':'COALESCE(balance,0)>0','zero_balance':'COALESCE(balance,0)=0','active':'COALESCE(is_banned,0)=0 AND COALESCE(is_blocked,0)=0 AND last_activity_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)'}
        if category in ('high_referrals','high_purchases','min_referrals','min_purchases'):
            n=max(1,int(threshold or 1)); field='subsets_count' if category.endswith('referrals') else 'total_purchases'; op='>' if category.startswith('high_') else '>='; where.append(f'COALESCE({field},0) {op} %s'); params.append(n)
        elif category in conditions: where.append(conditions[category])
        clause=' WHERE '+' AND '.join(where) if where else ''
        cur.execute(f'SELECT COUNT(*) AS cnt FROM users{clause}',tuple(params)); total=int(cur.fetchone()['cnt'] or 0)
        order={'top_purchases':'COALESCE(total_purchases,0) DESC, created_at DESC','top_referrals':'COALESCE(subsets_count,0) DESC, COALESCE(subsets_commission,0) DESC, created_at DESC','top_income':'COALESCE(income,0) DESC, created_at DESC','top_balance':'COALESCE(balance,0) DESC, created_at DESC','lottery_winners':'COALESCE((SELECT MAX(lr.created_at) FROM lottery_runs lr WHERE lr.winner_id=users.user_id),created_at) DESC','gift_users':'COALESCE((SELECT MAX(gcu.used_at) FROM gift_code_uses gcu WHERE gcu.user_id=users.user_id),created_at) DESC'}.get(category,'created_at DESC')
        offset=max(0,(page-1)*per_page)
        cur.execute(f"""SELECT user_id,full_name,username,balance,is_banned,is_verified,subsets_count,total_purchases,income,subsets_commission,join_date,phone_number FROM users{clause} ORDER BY {order} LIMIT %s OFFSET %s""",tuple(params+[per_page,offset]))
        rows=cur.fetchall() or []; return [tuple(r.values()) for r in rows],total
    except Exception:
        logger.exception('get_users_page failed search=%s mode=%s category=%s',search,search_mode,category); return [],0
    finally:
        try:
            if cur: cur.close()
            conn.close()
        except Exception: pass

def get_receipts_page(page=1, per_page=5):
    connection = get_db_connection()
    if not connection: return [], 0
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM receipts WHERE status = 'pending'")
        total = cursor.fetchone()[0]
        offset = (page - 1) * per_page
        # payment_method is intentionally omitted here so the returned row
        # matches the 13 fields expected by the admin receipt list.
        cursor.execute(
            """SELECT
                    r.id,
                    r.user_id,
                    r.amount,
                    r.photo_id,
                    r.payment_tracking_code,
                    r.status,
                    r.admin_id,
                    r.charge_amount,
                    r.reject_reason,
                    r.processed_at,
                    r.created_at,
                    u.full_name,
                    u.username
                FROM receipts r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.status = 'pending'
                ORDER BY r.created_at DESC
                LIMIT %s OFFSET %s""",
            (per_page, offset)
        )
        receipts = cursor.fetchall()
        return receipts, total
    except Error as e: return [], 0
    finally:
        try: cursor.close(); connection.close()
        except: pass

# ==================== کیبوردها ====================
def get_main_menu():
    keyboard = [
        [KeyboardButton("💰 قیمت خدمات"), KeyboardButton("📝 ثبت سفارش")],
        [KeyboardButton("👤 اطلاعات حساب"), KeyboardButton("💳 شارژ حساب")],
        [KeyboardButton("🛡 پشتیبانی"), KeyboardButton("🎁 شارژ رایگان"), KeyboardButton("📞 پیگیری")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 منوی قبلی"), KeyboardButton("🔙 منوی اصلی")]], resize_keyboard=True)

def get_main_only_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 منوی اصلی")]], resize_keyboard=True)

def get_share_contact_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📱 اشتراک‌گذاری شماره", request_contact=True)],
            [KeyboardButton("🔙 منوی اصلی")]
        ], 
        resize_keyboard=True, 
        one_time_keyboard=True
    )

def get_payment_methods_keyboard():
    keyboard = []

    online_active, _ = get_payment_method_status('online')
    card_active, _ = get_payment_method_status('card')
    stars_active, _ = get_payment_method_status('stars')
    crypto_active, _ = get_payment_method_status('crypto')

    row1 = []
    if online_active: row1.append(KeyboardButton("💸 پرداخت آنلاین"))
    if card_active: row1.append(KeyboardButton("💳 کارت به کارت"))
    if len(row1) > 0: keyboard.append(row1)

    row2 = []
    if stars_active: row2.append(KeyboardButton("⭐️ پرداخت با استارز"))
    if crypto_active: row2.append(KeyboardButton("💰 پرداخت با ارز دیجیتال"))
    if len(row2) > 0: keyboard.append(row2)

    if not keyboard:
        keyboard.append([KeyboardButton("❌ روش پرداختی موجود نیست")])

    keyboard.append([KeyboardButton("🔙 منوی اصلی")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_support_keyboard():
    keyboard = [
        [KeyboardButton("💸 پیگیری تراکنش ها"), KeyboardButton("🔍 پیگیری سفارشات")],
        [KeyboardButton("✳️ سایر موارد"), KeyboardButton("👨‍💻 ارتباط با مدیریت")],
        [KeyboardButton("⭕️ پیشنهاد،انتقاد و شکایت")],
        [KeyboardButton("🔙 بازگشت به منوی اصلی")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_categories_inline_keyboard():
    categories = get_all_categories()
    keyboard = []
    row = []
    for cat in categories:
        emoji = cat[2] if cat[2] else "📦"
        row.append(InlineKeyboardButton(f"{emoji} {cat[1]}", callback_data=f"cat_{cat[0]}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 بستن لیست", callback_data="close_list")])
    return InlineKeyboardMarkup(keyboard)

def get_products_inline_keyboard(category_id):
    products = get_category_products(category_id)
    keyboard = []
    for product in products:
        name = str(product[2] or "محصول")
        short_name = name[:40] + "..." if len(name) > 40 else name
        keyboard.append([InlineKeyboardButton(f"💰 {short_name}", callback_data=f"prod_{product[0]}")])
    if not products:
        keyboard.append([InlineKeyboardButton("❌ محصول فعالی در این دسته نیست", callback_data="no_product")])
    keyboard.append([
        InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_categories"),
        InlineKeyboardButton("🔙 بستن لیست", callback_data="close_list")
    ])
    return InlineKeyboardMarkup(keyboard)

def get_product_detail_keyboard(product_id, category_id):
    cat_id = category_id if category_id else 0
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 ثبت سفارش این محصول", callback_data=f"order_{product_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"backprod_{cat_id}"), InlineKeyboardButton("🔙 بستن لیست", callback_data="close_list")]
    ])

def get_product_no_balance_keyboard(category_id):
    cat_id = category_id if category_id else 0
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"backprod_{cat_id}"), InlineKeyboardButton("🔙 بستن لیست", callback_data="close_list")]])

def get_order_approval_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید سفارش", callback_data=f"confirmorder_{order_id}"),
         InlineKeyboardButton("❌ لغو سفارش", callback_data=f"rejectorder_{order_id}")],
        [InlineKeyboardButton("🎉 تکمیل سفارش", callback_data=f"completeorder_{order_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"backorder_{order_id}")]
    ])

def get_order_completion_confirm_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، تکمیل شود", callback_data=f"confirmcomplete_{order_id}"),
         InlineKeyboardButton("❌ انصراف", callback_data=f"backorder_{order_id}")]
    ])

def get_order_completion_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎉 تکمیل سفارش", callback_data=f"completeorder_{order_id}")],
        [InlineKeyboardButton("📨 تکمیل سفارش + ارسال مشخصات", callback_data=f"completeorder_info_{order_id}")]
    ])

def get_card_payment_keyboard(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(CARD_NUMBER)), InlineKeyboardButton("💰 کپی مبلغ", copy_text=CopyTextButton(f"{amount}"))],
        [InlineKeyboardButton("✅ پرداخت کردم | ارسال رسید", callback_data=f"sr_{amount}")]
    ])

def get_admin_action_keyboard(user_id, amount, receipt_id, payment_tracking):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ شارژ سریع", callback_data=f"quickcharge_{user_id}_{amount}_{receipt_id}_{payment_tracking}"),
         InlineKeyboardButton("✏️ شارژ دستی", callback_data=f"approve_{user_id}_{amount}_{receipt_id}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"reject_{user_id}_{amount}_{receipt_id}")]
    ])

def get_cancel_transaction_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو تراکنش آنلاین", callback_data="cancel_online_transaction")]
    ])

def get_pagination_keyboard(prefix, page, total, per_page=10):
    total_pages = max(1, math.ceil(total / per_page))
    keyboard = []

    if total > 0:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"{prefix}_{page-1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"{prefix}_{page+1}"))
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🔙 بستن", callback_data="close_list")])
    return InlineKeyboardMarkup(keyboard)

def get_tracking_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 پیگیری سفارش")],
        [KeyboardButton("💸 تراکنش های اخیر"), KeyboardButton("🛒 سفارشات اخیر")],
        [KeyboardButton("🔙 بازگشت به منوی اصلی")]
    ], resize_keyboard=True)

def get_receipt_waiting_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 منوی اصلی")]], resize_keyboard=True)

# ==================== کیبورد پنل ادمین ====================
def get_direct_message_input_keyboard(recipient_selected=False):
    """دکمه‌های لغو/بازگشت برای ارسال پیام مستقیم به کاربر."""
    back_text = "🔙 تغییر کاربر" if recipient_selected else "🔙 بازگشت"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ لغو", callback_data="adirect_cancel"),
            InlineKeyboardButton(back_text, callback_data="adirect_back"),
        ]
    ])


def get_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 آمار کلی", callback_data="apanel_stats"),
         InlineKeyboardButton("👥 مدیریت کاربران", callback_data="apanel_users_menu")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="apanel_settings")],
        [InlineKeyboardButton("📸 رسیدهای در انتظار", callback_data="apanel_receipts_1"),
         InlineKeyboardButton("💳 مدیریت روش‌های پرداخت", callback_data="apanel_payments")],
        [InlineKeyboardButton("🛡 مدیریت پشتیبانی", callback_data="apanel_support"),
         InlineKeyboardButton("📨 پیام به کاربر", callback_data="apanel_direct_message")],
        [InlineKeyboardButton("📦 مدیریت محصولات", callback_data="apanel_products"),
         InlineKeyboardButton("📋 مدیریت سفارشات", callback_data="apanel_orders_menu")],
        [InlineKeyboardButton("🎁 کدهای هدیه", callback_data="aset_gift_management"),
         InlineKeyboardButton("🎲 قرعه‌کشی", callback_data="agift_lottery")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="apanel_broadcast"),
         InlineKeyboardButton("📩 درخواست‌های کد", callback_data="apanel_sms_requests_1")],
        [InlineKeyboardButton("❌ بستن پنل", callback_data="apanel_close")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_sms_verification_dashboard_stats():
    connection = get_db_connection()
    if not connection:
        return {}
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                COUNT(*) AS total_users,
                COALESCE(SUM(request_count),0) AS total_requests,
                COALESCE(SUM(total_sent_count),0) AS total_sms,
                SUM(CASE WHEN DATE(last_request_at)=CURDATE() THEN 1 ELSE 0 END) AS users_today,
                SUM(CASE WHEN last_request_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS users_week,
                SUM(CASE WHEN last_request_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS users_month,
                SUM(CASE WHEN verification_code IS NOT NULL AND expires_at > NOW() THEN 1 ELSE 0 END) AS active_codes
            FROM phone_verification_codes WHERE request_count > 0
        """)
        base = cursor.fetchone() or {}
        cursor.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN DATE(created_at)=CURDATE() THEN 1 ELSE 0 END),0) AS requests_today,
                COALESCE(SUM(CASE WHEN created_at>=DATE_SUB(NOW(),INTERVAL 7 DAY) THEN 1 ELSE 0 END),0) AS requests_week,
                COALESCE(SUM(CASE WHEN created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY) THEN 1 ELSE 0 END),0) AS requests_month,
                COALESCE(SUM(CASE WHEN DATE(created_at)=CURDATE() AND sms_sent=1 THEN 1 ELSE 0 END),0) AS sms_today,
                COALESCE(SUM(CASE WHEN status='error' AND created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY) THEN 1 ELSE 0 END),0) AS errors_month,
                COALESCE(SUM(CASE WHEN status='limit' AND created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY) THEN 1 ELSE 0 END),0) AS limits_month,
                COALESCE(SUM(CASE WHEN status='existing' AND created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY) THEN 1 ELSE 0 END),0) AS reused_month
            FROM phone_verification_request_logs
        """)
        base.update(cursor.fetchone() or {})
        return base
    except Error as e:
        logger.error("sms verification dashboard stats failed: %s", e)
        return {}
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass

def get_sms_verification_requests_page(page=1, per_page=10, period='all', sort='latest', search=None):
    connection = get_db_connection()
    if not connection:
        return [], 0
    cursor = None
    try:
        page=max(1,int(page or 1)); per_page=max(1,min(20,int(per_page or 10))); offset=(page-1)*per_page
        where=["p.request_count > 0"]; params=[]
        if period == 'today': where.append("DATE(p.last_request_at)=CURDATE()")
        elif period == 'week': where.append("p.last_request_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)")
        elif period == 'month': where.append("p.last_request_at>=DATE_SUB(NOW(),INTERVAL 30 DAY)")
        if search:
            q=str(search).strip(); q_no_at=q.lstrip('@')
            where.append("(CAST(p.user_id AS CHAR)=%s OR p.phone_number LIKE %s OR LOWER(COALESCE(u.username,'')) LIKE LOWER(%s) OR LOWER(COALESCE(u.full_name,'')) LIKE LOWER(%s))")
            params.extend([q, f"%{q}%", f"%{q_no_at}%", f"%{q}%"])
        where_sql=' AND '.join(where)
        order_sql = "p.request_count DESC, p.last_request_at DESC" if sort == 'top' else "p.last_request_at DESC, p.user_id DESC"
        cursor=connection.cursor(dictionary=True)
        cursor.execute(f"SELECT COUNT(*) AS c FROM phone_verification_codes p LEFT JOIN users u ON u.user_id=p.user_id WHERE {where_sql}", tuple(params))
        total=int((cursor.fetchone() or {}).get('c') or 0)
        cursor.execute(f"""
            SELECT p.user_id,p.phone_number,p.request_count,p.sent_count,p.total_sent_count,p.last_code,p.verification_code,p.expires_at,
                   p.first_request_at,p.last_request_at,p.last_sent_at,p.sent_date,u.full_name,u.username
            FROM phone_verification_codes p LEFT JOIN users u ON u.user_id=p.user_id
            WHERE {where_sql} ORDER BY {order_sql} LIMIT %s OFFSET %s
        """, tuple(params+[per_page,offset]))
        return cursor.fetchall() or [], total
    except Error as e:
        logger.error("sms verification admin list failed: %s", e); return [],0
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception: pass

def get_sms_verification_request_detail(user_id):
    connection=get_db_connection()
    if not connection: return None
    cursor=None
    try:
        cursor=connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.*, (p.expires_at IS NOT NULL AND p.expires_at > NOW()) AS is_active, u.full_name,u.username,u.is_verified,
                   (SELECT COUNT(*) FROM phone_verification_request_logs l WHERE l.user_id=p.user_id AND DATE(l.created_at)=CURDATE()) AS requests_today,
                   (SELECT COUNT(*) FROM phone_verification_request_logs l WHERE l.user_id=p.user_id AND l.created_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)) AS requests_week,
                   (SELECT COUNT(*) FROM phone_verification_request_logs l WHERE l.user_id=p.user_id AND l.created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY)) AS requests_month,
                   (SELECT COUNT(*) FROM phone_verification_request_logs l WHERE l.user_id=p.user_id AND l.status='error') AS error_count,
                   (SELECT COUNT(*) FROM phone_verification_request_logs l WHERE l.user_id=p.user_id AND l.status='limit') AS limit_count,
                   (SELECT COUNT(*) FROM phone_verification_request_logs l WHERE l.user_id=p.user_id AND l.status='existing') AS reused_count
            FROM phone_verification_codes p LEFT JOIN users u ON u.user_id=p.user_id WHERE p.user_id=%s LIMIT 1
        """,(int(user_id),)); return cursor.fetchone()
    except Error as e:
        logger.error("sms verification admin detail failed user=%s: %s",user_id,e); return None
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception: pass

def get_sms_verification_recent_logs(user_id, limit=8):
    connection=get_db_connection()
    if not connection:return []
    cursor=None
    try:
        cursor=connection.cursor(dictionary=True)
        cursor.execute("SELECT status,sms_sent,details,created_at FROM phone_verification_request_logs WHERE user_id=%s ORDER BY id DESC LIMIT %s",(int(user_id),max(1,min(20,int(limit)))))
        return cursor.fetchall() or []
    except Error as e:
        logger.error("sms verification recent logs failed: %s",e); return []
    finally:
        try:
            if cursor:cursor.close()
            connection.close()
        except Exception:pass

def _fmt_admin_datetime(value):
    if not value:return '-'
    try:return value.strftime("%Y-%m-%d - %H:%M:%S")
    except Exception:return str(value)

def get_sms_dashboard_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 امروز",callback_data="apanel_sms_list_today_1"),InlineKeyboardButton("🗓 ۷ روز اخیر",callback_data="apanel_sms_list_week_1")],
        [InlineKeyboardButton("📆 ۳۰ روز اخیر",callback_data="apanel_sms_list_month_1"),InlineKeyboardButton("📚 همه درخواست‌دهنده‌ها",callback_data="apanel_sms_list_all_1")],
        [InlineKeyboardButton("🏆 بیشترین درخواست",callback_data="apanel_sms_top_1"),InlineKeyboardButton("🔎 جستجو",callback_data="apanel_sms_search")],
        [InlineKeyboardButton("🔄 بروزرسانی",callback_data="apanel_sms_requests_1")],
        [InlineKeyboardButton("🔙 پنل اصلی",callback_data="apanel_main")]
    ])

def get_sms_verification_admin_keyboard(rows,page,total,per_page=10,period='all',sort='latest'):
    keyboard=[]
    for row in rows:
        uid=int(row.get('user_id') or 0); name=str(row.get('full_name') or row.get('username') or f"کاربر {uid}")
        if len(name)>20:name=name[:17]+'...'
        keyboard.append([InlineKeyboardButton(f"👤 {name} • {int(row.get('request_count') or 0):,} درخواست",callback_data=f"apanel_sms_user_{uid}_1")])
    total_pages=max(1,(int(total)+per_page-1)//per_page); nav=[]
    prefix = 'apanel_sms_top' if sort=='top' else f'apanel_sms_list_{period}'
    if page>1:nav.append(InlineKeyboardButton("⬅️ قبلی",callback_data=f"{prefix}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}",callback_data="noop"))
    if page<total_pages:nav.append(InlineKeyboardButton("بعدی ➡️",callback_data=f"{prefix}_{page+1}"))
    if nav:keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 گزارش درخواست‌های کد",callback_data="apanel_sms_requests_1")])
    return InlineKeyboardMarkup(keyboard)

def get_orders_search_page(search, page=1, per_page=10):
    connection = get_db_connection()
    if not connection:
        return [], 0
    try:
        cursor = connection.cursor()
        q = (search or '').strip()
        like = f"%{q}%"
        if q.isdigit():
            cursor.execute(
                "SELECT COUNT(*) FROM orders WHERE id=%s OR user_id=%s OR tracking_code LIKE %s OR product_name LIKE %s",
                (int(q), int(q), like, like)
            )
            total = cursor.fetchone()[0]
            offset = (page - 1) * per_page
            cursor.execute(
                "SELECT o.*, u.full_name, u.username FROM orders o LEFT JOIN users u ON u.user_id=o.user_id "
                "WHERE o.id=%s OR o.user_id=%s OR o.tracking_code LIKE %s OR o.product_name LIKE %s "
                "ORDER BY o.created_at DESC LIMIT %s OFFSET %s",
                (int(q), int(q), like, like, per_page, offset)
            )
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM orders WHERE tracking_code LIKE %s OR product_name LIKE %s",
                (like, like)
            )
            total = cursor.fetchone()[0]
            offset = (page - 1) * per_page
            cursor.execute(
                "SELECT o.*, u.full_name, u.username FROM orders o LEFT JOIN users u ON u.user_id=o.user_id "
                "WHERE o.tracking_code LIKE %s OR o.product_name LIKE %s "
                "ORDER BY o.created_at DESC LIMIT %s OFFSET %s",
                (like, like, per_page, offset)
            )
        return cursor.fetchall(), total
    except Exception:
        logger.exception("failed searching orders search=%s", search)
        return [], 0
    finally:
        try:
            cursor.close(); connection.close()
        except Exception:
            pass

def get_admin_orders_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("⏳ سفارشات در انتظار", callback_data="aorders_pending_1"),
         InlineKeyboardButton("✅ سفارشات تایید شده", callback_data="aorders_confirmed_1")],
        [InlineKeyboardButton("🎉 سفارشات تکمیل شده", callback_data="aorders_completed_1"),
         InlineKeyboardButton("❌ سفارشات لغو شده", callback_data="aorders_cancelled_1")],
        [InlineKeyboardButton("📋 همه سفارشات", callback_data="aorders_all_1")],
        [InlineKeyboardButton("🔎 جستجوی سفارش", callback_data="aorders_search")],
        [InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_orders_keyboard(status, page, total, per_page=10):
    total_pages = max(1, math.ceil(total / per_page))
    orders, _ = get_orders_by_status(status if status != 'all' else None, page, per_page)

    keyboard = []
    keyboard.append([InlineKeyboardButton(f"📄 صفحه {page} از {total_pages} - {total} سفارش", callback_data="noop")])

    for order in orders:
        oid = order[0]
        tracking = str(order[1] or oid)
        status_emoji = "🎉" if order[9] == 'completed' else ("⏳" if order[9] == 'pending' else ("✅" if order[9] == 'confirmed' else "❌"))
        keyboard.append([InlineKeyboardButton(f"{status_emoji} {tracking}", callback_data=f"aorderdetail_{oid}")])

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"aorders_{status}_{page-1}"))
    nav_row.append(InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_orders_menu"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"aorders_{status}_{page+1}"))
    keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)

def get_admin_user_category_counts():
    """تعداد واقعی هر دسته برای نمایش روی دکمه‌های مدیریت کاربران."""
    connection = get_db_connection()
    counts = {
        'all': 0, 'banned': 0, 'verified': 0, 'unverified': 0,
        'rules_pending': 0, 'blocked': 0, 'new_today': 0,
        'new_week': 0, 'new_month': 0, 'new_3_month': 0, 'new_6_month': 0, 'new_year': 0, 'top_purchases': 0,
        'top_referrals': 0, 'top_income': 0, 'top_balance': 0,
        'lottery_winners': 0, 'gift_users': 0
    }
    if not connection:
        return counts
    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                COUNT(*) AS all_count,
                SUM(CASE WHEN COALESCE(is_banned,0)=1 THEN 1 ELSE 0 END) AS banned_count,
                SUM(CASE WHEN COALESCE(is_verified,0)=1 THEN 1 ELSE 0 END) AS verified_count,
                SUM(CASE WHEN COALESCE(is_verified,0)=0 THEN 1 ELSE 0 END) AS unverified_count,
                SUM(CASE WHEN COALESCE(rules_accepted,0)=0 THEN 1 ELSE 0 END) AS rules_pending_count,
                SUM(CASE WHEN COALESCE(is_blocked,0)=1 THEN 1 ELSE 0 END) AS blocked_count,
                SUM(CASE WHEN created_at >= CURDATE() THEN 1 ELSE 0 END) AS new_today_count,
                SUM(CASE WHEN created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS new_week_count,
                SUM(CASE WHEN created_at >= DATE_SUB(NOW(), INTERVAL 1 MONTH) THEN 1 ELSE 0 END) AS new_month_count,
                SUM(CASE WHEN created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH) THEN 1 ELSE 0 END) AS new_3_month_count,
                SUM(CASE WHEN created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH) THEN 1 ELSE 0 END) AS new_6_month_count,
                SUM(CASE WHEN created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR) THEN 1 ELSE 0 END) AS new_year_count,
                SUM(CASE WHEN last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS inactive_7_count,
                SUM(CASE WHEN last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS inactive_30_count,
                SUM(CASE WHEN last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 60 DAY) THEN 1 ELSE 0 END) AS inactive_60_count,
                SUM(CASE WHEN last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 90 DAY) THEN 1 ELSE 0 END) AS inactive_90_count,
                SUM(CASE WHEN last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 180 DAY) THEN 1 ELSE 0 END) AS inactive_180_count,
                SUM(CASE WHEN last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 365 DAY) THEN 1 ELSE 0 END) AS inactive_365_count,
                SUM(CASE WHEN COALESCE(total_purchases,0) > 0 THEN 1 ELSE 0 END) AS top_purchases_count,
                SUM(CASE WHEN COALESCE(subsets_count,0) > 0 THEN 1 ELSE 0 END) AS top_referrals_count,
                SUM(CASE WHEN COALESCE(income,0) > 0 THEN 1 ELSE 0 END) AS top_income_count,
                SUM(CASE WHEN COALESCE(balance,0) > 0 THEN 1 ELSE 0 END) AS top_balance_count,
                SUM(CASE WHEN EXISTS (SELECT 1 FROM lottery_runs lr WHERE lr.winner_id = users.user_id) THEN 1 ELSE 0 END) AS lottery_winners_count,
                SUM(CASE WHEN EXISTS (SELECT 1 FROM gift_code_uses gcu WHERE gcu.user_id = users.user_id) THEN 1 ELSE 0 END) AS gift_users_count
            FROM users
        """)
        row = cursor.fetchone() or {}
        mapping = {
            'all': 'all_count', 'banned': 'banned_count', 'verified': 'verified_count',
            'unverified': 'unverified_count', 'rules_pending': 'rules_pending_count',
            'blocked': 'blocked_count', 'new_today': 'new_today_count',
            'new_week': 'new_week_count', 'new_month': 'new_month_count', 'new_3_month': 'new_3_month_count',
            'new_6_month': 'new_6_month_count', 'new_year': 'new_year_count',
            'inactive_7': 'inactive_7_count', 'inactive_30': 'inactive_30_count',
            'inactive_60': 'inactive_60_count', 'inactive_90': 'inactive_90_count',
            'inactive_180': 'inactive_180_count', 'inactive_365': 'inactive_365_count',
            'top_purchases': 'top_purchases_count', 'top_referrals': 'top_referrals_count',
            'top_income': 'top_income_count', 'top_balance': 'top_balance_count',
            'lottery_winners': 'lottery_winners_count', 'gift_users': 'gift_users_count'
        }
        for key, db_key in mapping.items():
            counts[key] = int(row.get(db_key) or 0)
    except Error as e:
        logger.exception("failed getting admin user category counts: %s", e)
    finally:
        try:
            if cursor: cursor.close()
            connection.close()
        except Exception:
            pass
    return counts

# ==================== گروه‌های مشترک انتخاب کاربران ====================
# همه بخش‌های «مدیریت کاربران»، «ساخت کد هدیه»، «قرعه‌کشی» و «ارسال پیام همگانی»
# از همین لیست استفاده می‌کنند تا دسته‌بندی‌ها همیشه یکسان بمانند.
UNIFIED_USER_TARGET_GROUPS = [
    ('all', '👥 همه کاربران', [('all', '👥 همه کاربران')]),
    ('status', '🛡️ وضعیت کاربران', [('banned','⛔️ کاربران بن‌شده'),('blocked','🚫 کاربران بلاک‌کننده'),('verified','✅ احراز شده‌ها'),('unverified','⚠️ احراز نشده‌ها'),('rules_pending','📜 قوانین تأییدنشده‌ها')]),
    ('new', '🆕 کاربران جدید', [('new_today','🆕 امروز'),('new_week','📅 ۷ روز اخیر'),('new_month','🗓️ ۳۰ روز اخیر'),('new_3_month','📆 ۳ ماه اخیر'),('new_6_month','📆 ۶ ماه اخیر'),('new_year','🗓️ ۱ سال اخیر')]),
    ('inactive', '😴 کاربران کم‌فعالیت', [('inactive_7','😴 بیش از ۷ روز'),('inactive_30','💤 بیش از ۳۰ روز'),('inactive_60','💤 بیش از ۶۰ روز'),('inactive_90','💤 بیش از ۹۰ روز'),('inactive_180','🪦 بیش از ۶ ماه'),('inactive_365','🪦 بیش از ۱ سال'),('never_active','👻 بدون فعالیت')]),
    ('purchase_referral', '🛒 خرید و رفرال', [('buyers','🛍️ دارای خرید'),('no_buyers','🚫 بدون خرید'),('referrers','👥 دارای رفرال'),('no_referrals','🚫 بدون رفرال')]),
    ('financial', '💰 پرداخت و موجودی', [('paid','💳 دارای پرداخت'),('no_payments','🚫 بدون پرداخت'),('positive_balance','💵 موجودی بیشتر از صفر'),('zero_balance','0️⃣ موجودی صفر')]),
    ('top', '🏅 بیشترین‌ها و برندگان', [('top_purchases','🏆 بیشترین خرید'),('top_referrals','🥇 بیشترین رفرال'),('top_income','💸 بیشترین درآمد'),('top_balance','💰 بیشترین موجودی'),('lottery_winners','🎉 برندگان قرعه‌کشی'),('gift_users','🎁 دریافت‌کنندگان کد هدیه')]),
    ('threshold', '🎯 بیشتر از / حداقل مقدار', [('high_referrals','📈 رفرال بیشتر از مقدار'),('high_purchases','📈 خرید بیشتر از مقدار'),('min_referrals','🔢 حداقل تعداد رفرال'),('min_purchases','💰 حداقل مبلغ خرید')]),
    ('active', '🟢 کاربران فعال', [('active','🟢 کاربران فعال')]),
]
UNIFIED_USER_TARGET_GROUP_MAP = {k:(label,items) for k,label,items in UNIFIED_USER_TARGET_GROUPS}
UNIFIED_USER_TARGET_LABELS = {key:label for _,_,items in UNIFIED_USER_TARGET_GROUPS for key,label in items}
# Flattened target rows used by legacy/admin menu helpers. Keep this derived from the shared groups.
UNIFIED_USER_TARGET_ROWS = [items for _, _, items in UNIFIED_USER_TARGET_GROUPS]

def _chunk_keyboard_buttons(buttons, size=2):
    """چند دکمه را به ردیف‌های ثابت تقسیم می‌کند؛ منوهای مشترک همیشه دو ستونه هستند."""
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]

def get_unified_group_keyboard(prefix, purpose='admin', context=None, back_callback='apanel_main'):
    # «همه کاربران» یک ردیف مستقل دارد؛ سایر گروه‌ها دو ستونه هستند.
    rows = []
    all_group = UNIFIED_USER_TARGET_GROUP_MAP.get('all')
    if all_group:
        _, items = all_group
        key, label = items[0]
        count = get_unified_target_count(key, purpose, context)
        rows.append([InlineKeyboardButton(f'{label} ({count:,})', callback_data=f'{prefix}{key}')])

    group_buttons = []
    for group_key, label, _items in UNIFIED_USER_TARGET_GROUPS:
        if group_key == 'all':
            continue
        group_buttons.append(InlineKeyboardButton(label, callback_data=f'{prefix}group_{group_key}'))
    rows.extend(_chunk_keyboard_buttons(group_buttons, 2))

    if back_callback:
        rows.append([InlineKeyboardButton('🏠 پنل اصلی', callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)

def get_unified_group_items_keyboard(prefix, group_key, purpose='admin', context=None, back_callback=None):
    group = UNIFIED_USER_TARGET_GROUP_MAP.get(group_key)
    if not group:
        return get_unified_group_keyboard(prefix, purpose, context, back_callback or 'apanel_main')

    _, items = group
    buttons = []
    for key, label in items:
        count = get_unified_target_count(key, purpose, context)
        buttons.append(InlineKeyboardButton(f'{label} ({count:,})', callback_data=f'{prefix}{key}'))

    rows = _chunk_keyboard_buttons(buttons, 2)
    rows.append([InlineKeyboardButton('🔙 بازگشت', callback_data=back_callback or f'{prefix}menu')])
    return InlineKeyboardMarkup(rows)

def get_unified_user_target_keyboard(prefix,purpose='admin',context=None,back_callback=None):
    return get_unified_group_keyboard(prefix,purpose,context,back_callback or 'apanel_main')

def get_unified_target_count(target, purpose='admin', context=None):
    """تعداد هر گروه را برای هر چهار بخش از منبع مناسب می‌گیرد."""
    if target in ('min_referrals', 'min_purchases', 'high_referrals', 'high_purchases'):
        threshold = 1
        if context:
            threshold = context.user_data.get('broadcast_threshold', 1) or context.user_data.get('gift_target_value', 1) or context.user_data.get('lottery_target_value', 1) or 1
        if purpose == 'broadcast':
            return get_broadcast_target_count(target, threshold)
        # برای هدیه/قرعه‌کشی هم از شرایط واقعی همان بخش استفاده می‌کنیم.
        if target.endswith('referrals'):
            condition = 'COALESCE(subsets_count,0) > %s' if target == 'high_referrals' else 'COALESCE(subsets_count,0) >= %s'
        else:
            condition = 'COALESCE(total_purchases,0) > %s' if target == 'high_purchases' else 'COALESCE(total_purchases,0) >= %s'
        conn = get_db_connection()
        if not conn: return 0
        try:
            cur = conn.cursor(); cur.execute(f'SELECT COUNT(*) FROM users WHERE {condition}', (int(threshold),))
            return int(cur.fetchone()[0] or 0)
        except Exception:
            return 0
        finally:
            try: cur.close(); conn.close()
            except Exception: pass

    counts = get_admin_user_category_counts()
    if target in counts:
        return int(counts.get(target, 0) or 0)
    if purpose == 'broadcast':
        return get_broadcast_target_count(target)
    if purpose == 'lottery':
        try: return int(get_lottery_target_count(target, 0) or 0)
        except Exception: return 0
    # برای هدیه همان شرایط broadcast قابل استفاده است.
    try: return int(get_broadcast_target_count(target) or 0)
    except Exception: return 0


def get_unified_user_target_keyboard(prefix, purpose='admin', context=None, back_callback=None):
    """منوی مشترک انتخاب کاربران به‌صورت دسته‌بندی‌شده؛ هر ردیف حداکثر ۲ دکمه."""
    return get_unified_group_keyboard(prefix, purpose, context, back_callback or 'apanel_main')

def get_admin_users_menu_keyboard():
    """منوی مدیریت کاربران؛ جستجوی مستقیم + دسته‌بندی‌ها."""
    kb = get_unified_user_target_keyboard(
        'apanel_users_',
        'admin',
        None,
        None
    )

    # PTB may expose inline_keyboard as a tuple.
    # Convert it to a mutable list before inserting the search row.
    rows = list(kb.inline_keyboard)

    rows.insert(
        0,
        [
            InlineKeyboardButton(
                "🔎 جستجوی کاربر",
                callback_data="apanel_users_search"
            )
        ]
    )

    return InlineKeyboardMarkup(rows)

def get_admin_users_keyboard(page, total, per_page=10, search=None, category='all', users=None):
    """کیبورد مدیریت کاربران؛ هر ردیف دقیقاً حداکثر ۲ کاربر دارد."""
    total_pages = max(1, math.ceil(total / per_page))
    base = "apanel_users_search_" if category == "search" else f"apanel_users_{category}_"
    keyboard = []
    if users:
        row = []
        for user in users:
            uid = int(user[0])
            name = str(user[1] or uid).replace('\n',' ').strip()
            if len(name) > 24:
                name = name[:23] + '…'
            row.append(InlineKeyboardButton(f"👤 {name}", callback_data=f"auser_{uid}"))
            if len(row) == 2:
                keyboard.append(row); row = []
        if row:
            keyboard.append(row)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"{base}{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"{base}{page+1}"))
    keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 دسته‌بندی‌ها", callback_data="apanel_users_menu")])
    return InlineKeyboardMarkup(keyboard)


def format_admin_users_list(users, category, page, total, per_page=10):
    labels = {
        'all': '👥 همه کاربران', 'banned': '🚫 کاربران بن‌شده',
        'verified': '✅ کاربران احراز هویت‌شده', 'unverified': '⚠️ کاربران احراز نشده',
        'rules_pending': '📜 کاربران تأییدنشده قوانین', 'blocked': '🚫 کاربرانی که ربات را بلاک کرده‌اند',
        'new_today': '🆕 کاربران جدید امروز', 'new_week': '📅 کاربران جدید ۷ روز اخیر',
        'new_month': '🗓 کاربران جدید ۳۰ روز اخیر',
        'new_3_month': '📆 کاربران جدید ۳ ماه اخیر', 'new_6_month': '📆 کاربران جدید ۶ ماه اخیر',
        'new_year': '🗓 کاربران جدید ۱ سال اخیر',
        'inactive_7': '😴 بدون فعالیت بیش از ۷ روز', 'inactive_30': '😴 بدون فعالیت بیش از ۳۰ روز',
        'inactive_60': '😴 بدون فعالیت بیش از ۶۰ روز', 'inactive_90': '😴 بدون فعالیت بیش از ۹۰ روز',
        'inactive_180': '💤 بدون فعالیت بیش از ۶ ماه', 'inactive_365': '💤 بدون فعالیت بیش از ۱ سال',
        'never_active': '⚪️ بدون فعالیت ثبت‌شده', 'top_purchases': '🛒 بیشترین خرید',
        'top_referrals': '👥 بیشترین رفرال', 'top_income': '💰 بیشترین کسب درآمد',
        'top_balance': '💳 بیشترین موجودی', 'lottery_winners': '🏆 برندگان قرعه‌کشی',
        'gift_users': '🎁 دریافت‌کنندگان کد هدیه',
        'high_referrals': '📈 رفرال بیشتر از مقدار',
        'high_purchases': '📈 خرید بیشتر از مقدار',
        'min_referrals': '🎯 حداقل تعداد رفرال',
        'min_purchases': '🎯 حداقل مبلغ خرید',
        'search': '🔎 نتیجه جستجو', 'buyers':'🛍️ کاربران دارای خرید', 'no_buyers':'🚫 کاربران بدون خرید', 'referrers':'👥 کاربران دارای رفرال', 'no_referrals':'🚫 کاربران بدون رفرال', 'paid':'💳 کاربران دارای پرداخت', 'no_payments':'🚫 کاربران بدون پرداخت', 'positive_balance':'💵 کاربران با موجودی مثبت', 'zero_balance':'0️⃣ کاربران با موجودی صفر', 'active':'🟢 کاربران فعال'
    }
    title = labels.get(category, '👥 کاربران')
    total_pages = max(1, math.ceil(total / per_page))
    lines = [
        f"<b>{title}</b>",
        f"📄 صفحه <b>{page}</b> از <b>{total_pages}</b>  •  👥 <b>{total:,}</b> نفر",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not users:
        lines.append("📭 این لیست در حال حاضر خالی است.")
    else:
        start_index = (page - 1) * per_page
        for idx, user in enumerate(users, start=1):
            uid = int(user[0])
            raw_name = str(user[1] or '').replace('\n', ' ').strip()
            username = str(user[2] or '').strip().lstrip('@')
            # اگر یوزرنیم وجود داشته باشد، خود نام به لینک تلگرام تبدیل می‌شود؛
            # در غیر این صورت نام به آیدی عددی لینک می‌شود.
            display_name = raw_name or str(uid)
            if len(display_name) > 38:
                display_name = display_name[:37] + '…'
            display_name = html.escape(display_name)
            if username:
                name_link = f'<a href="https://t.me/{html.escape(username, quote=True)}">{display_name}</a>'
            else:
                name_link = f'<a href="tg://user?id={uid}">{display_name}</a>'

            balance = int(float(user[3] or 0))
            purchases = int(user[7] or 0)
            number = start_index + idx
            lines.append(
                f"{number}. {name_link} | <code>{uid}</code> | 💰 {format_amount(balance)} | 🛒 {purchases:,}"
            )

    lines.append("\nبرای مشاهده جزئیات، روی نام کاربر در متن بالا بزنید 👆")
    return "\n".join(lines)

def get_user_verification(user_id):
    conn=get_db_connection()
    if not conn:return {}
    cur=None
    try:
        cur=conn.cursor(dictionary=True);cur.execute("SELECT * FROM user_verification WHERE user_id=%s",(int(user_id),));return cur.fetchone() or {}
    except Exception:return {}
    finally:
        try:
            if cur:cur.close()
            conn.close()
        except Exception:pass

def save_user_verification_field(user_id,field,value):
    allowed={'national_id','birth_certificate_number','birth_date','father_name','bank_card_number','identity_document_type','notes'}
    if field not in allowed:return False
    conn=get_db_connection()
    if not conn:return False
    cur=None
    try:
        cur=conn.cursor();cur.execute("INSERT INTO user_verification(user_id) VALUES(%s) ON DUPLICATE KEY UPDATE user_id=user_id",(int(user_id),));cur.execute(f"UPDATE user_verification SET {field}=%s WHERE user_id=%s",(value,int(user_id)));conn.commit();return True
    except Exception:
        try:conn.rollback()
        except Exception:pass
        return False
    finally:
        try:
            if cur:cur.close()
            conn.close()
        except Exception:pass

def save_user_verification_photo(user_id,file_id,doc_type=None):
    conn=get_db_connection()
    if not conn:return False
    cur=None
    try:
        cur=conn.cursor();cur.execute("INSERT INTO user_verification(user_id,identity_document_file_id,identity_document_type) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE identity_document_file_id=VALUES(identity_document_file_id), identity_document_type=COALESCE(VALUES(identity_document_type),identity_document_type)",(int(user_id),file_id,doc_type));conn.commit();return True
    except Exception:
        try:conn.rollback()
        except Exception:pass
        return False
    finally:
        try:
            if cur:cur.close()
            conn.close()
        except Exception:pass

def clear_user_verification(user_id):
    conn=get_db_connection()
    if not conn:return False
    cur=None
    try:cur=conn.cursor();cur.execute("DELETE FROM user_verification WHERE user_id=%s",(int(user_id),));conn.commit();return True
    except Exception:return False
    finally:
        try:
            if cur:cur.close()
            conn.close()
        except Exception:pass

def verification_label(field):
    return {'national_id':'کد ملی','birth_certificate_number':'شماره شناسنامه','birth_date':'تاریخ تولد','father_name':'نام پدر','bank_card_number':'شماره کارت بانکی','identity_document_type':'نوع مدرک','notes':'یادداشت تکمیلی','identity_document_file_id':'عکس کارت ملی/شناسنامه'}.get(field,field)

def get_admin_verification_keyboard(user_id,data):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"🪪 کد ملی: {'✅' if data.get('national_id') else '➕'}",callback_data=f"averify_edit_{user_id}_national_id"),InlineKeyboardButton(f"📄 شناسنامه: {'✅' if data.get('birth_certificate_number') else '➕'}",callback_data=f"averify_edit_{user_id}_birth_certificate_number")],[InlineKeyboardButton(f"👨 نام پدر: {'✅' if data.get('father_name') else '➕'}",callback_data=f"averify_edit_{user_id}_father_name"),InlineKeyboardButton(f"🎂 تولد: {'✅' if data.get('birth_date') else '➕'}",callback_data=f"averify_edit_{user_id}_birth_date")],[InlineKeyboardButton(f"💳 شماره کارت: {'✅' if data.get('bank_card_number') else '➕'}",callback_data=f"averify_edit_{user_id}_bank_card_number"),InlineKeyboardButton(f"🗂 نوع مدرک: {'✅' if data.get('identity_document_type') else '➕'}",callback_data=f"averify_edit_{user_id}_identity_document_type")],[InlineKeyboardButton(f"📸 عکس مدرک: {'✅ ثبت شده' if data.get('identity_document_file_id') else '❌ ثبت نشده'}",callback_data=f"averify_edit_{user_id}_identity_document_file_id")],[InlineKeyboardButton("📝 یادداشت تکمیلی",callback_data=f"averify_edit_{user_id}_notes")],[InlineKeyboardButton("✅ تایید احراز هویت",callback_data=f"averify_status_{user_id}_1"),InlineKeyboardButton("⚠️ لغو تایید",callback_data=f"averify_status_{user_id}_0")],[InlineKeyboardButton("🗑 پاک کردن اطلاعات احراز",callback_data=f"averify_clear_{user_id}")],[InlineKeyboardButton("🔙 اطلاعات کاربر",callback_data=f"auser_{user_id}")]])

def format_admin_verification(user_id,user,data):
    def v(k): return html.escape(str(data.get(k) or 'ثبت نشده'))
    return (f"🪪 <b>احراز هویت دستی کاربر</b>\n\n"
            f"👤 {html.escape(str(user.get('full_name') or user_id))} | <code>{user_id}</code>\n"
            f"📊 وضعیت احراز: <b>{'✅ تایید شده' if user.get('is_verified') else '⚠️ تایید نشده'}</b>\n\n"
            f"🪪 کد ملی: <tg-spoiler>{v('national_id')}</tg-spoiler>\n"
            f"📄 شماره شناسنامه: <tg-spoiler>{v('birth_certificate_number')}</tg-spoiler>\n"
            f"👨 نام پدر: {v('father_name')}\n"
            f"🎂 تاریخ تولد: {v('birth_date')}\n"
            f"💳 شماره کارت بانکی: <tg-spoiler>{v('bank_card_number')}</tg-spoiler>\n"
            f"🗂 نوع مدرک: {v('identity_document_type')}\n"
            f"📸 عکس مدرک: <b>{'✅ ثبت شده' if data.get('identity_document_file_id') else '❌ ثبت نشده'}</b>\n"
            f"📝 یادداشت: {v('notes')}")

def get_admin_user_detail_keyboard(user_id, is_banned=False):
    ban_row=([InlineKeyboardButton("✅ آنبن کاربر",callback_data=f"aunban_{user_id}")] if is_banned else [InlineKeyboardButton("🚫 بن کاربر",callback_data=f"aban_{user_id}")])
    return InlineKeyboardMarkup([ban_row,[InlineKeyboardButton("🪪 اطلاعات احراز هویت",callback_data=f"auser_verification_{user_id}")],[InlineKeyboardButton("💰 تغییر موجودی",callback_data=f"abalance_{user_id}")],[InlineKeyboardButton("💸 تراکنش‌های کاربر",callback_data=f"auser_txns_{user_id}_1"),InlineKeyboardButton("💳 پرداخت‌های کاربر",callback_data=f"auser_payments_{user_id}_1")],[InlineKeyboardButton("🛒 سفارشات کاربر",callback_data=f"auser_orders_{user_id}_1"),InlineKeyboardButton("🎟 کدهای هدیه",callback_data=f"auser_gifts_{user_id}_1")],[InlineKeyboardButton("🎲 قرعه‌کشی‌های برنده",callback_data=f"auser_lottery_{user_id}_1")],[InlineKeyboardButton("🔙 بازگشت به مدیریت کاربران",callback_data="apanel_users_menu"),InlineKeyboardButton("🏠 پنل اصلی",callback_data="apanel_main")]])

def get_admin_currencies_keyboard():
    currencies = get_all_currencies()
    keyboard = []
    for c in currencies:
        code = c.get('code')
        name = c.get('name') or code
        rate = int(c.get('rate') or 0)
        status = "✅" if c.get('is_active') else "⛔️"
        keyboard.append([InlineKeyboardButton(f"{status} {code} — {format_amount(rate)} تومان", callback_data=f"acur_edit_{code}"),
                         InlineKeyboardButton("🗑 حذف", callback_data=f"acur_delete_{code}")])
    keyboard.append([InlineKeyboardButton("➕ افزودن ارز", callback_data="acur_add")])
    keyboard.append([InlineKeyboardButton("🔙 تنظیمات", callback_data="apanel_settings")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_gift_codes_keyboard(page=1, per_page=8):
    conn = get_db_connection()
    rows=[]; total=0
    if conn:
        try:
            cur=conn.cursor(dictionary=True)
            cur.execute("SELECT COUNT(*) AS c FROM gift_codes")
            total=int(cur.fetchone()["c"] or 0)
            offset=max(0,(page-1)*per_page)
            cur.execute("SELECT * FROM gift_codes ORDER BY id DESC LIMIT %s OFFSET %s", (per_page,offset))
            rows=cur.fetchall()
        except Exception:
            logger.exception("failed loading gift code list")
        finally:
            try: cur.close(); conn.close()
            except: pass
    pages=max(1, math.ceil(total/per_page))
    kb=[]
    if not rows:
        kb.append([InlineKeyboardButton("📭 لیست کدهای هدیه خالی است", callback_data="noop")])
    for g in rows:
        maxu=int(g.get('max_uses') or 0); used=int(g.get('used_count') or 0)
        status='🟢' if g.get('is_active') and (maxu==0 or used<maxu) else '🔴'
        rem='∞' if maxu==0 else str(max(0,maxu-used))
        kb.append([InlineKeyboardButton(f"{status} {g.get('code')} | {used}/{maxu if maxu else '∞'}", callback_data=f"agift_detail_{g['id']}_1")])
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("⬅️ قبلی",callback_data=f"agiftlist_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page}/{pages}",callback_data="noop"))
    if page<pages: nav.append(InlineKeyboardButton("بعدی ➡️",callback_data=f"agiftlist_page_{page+1}"))
    kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 تنظیمات", callback_data="apanel_settings")])
    return InlineKeyboardMarkup(kb)

def get_gift_code_detail(gift_id):
    conn=get_db_connection()
    if not conn: return None
    try:
        cur=conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM gift_codes WHERE id=%s",(gift_id,))
        return cur.fetchone()
    except Exception:
        logger.exception("failed loading gift detail id=%s",gift_id); return None
    finally:
        try: cur.close(); conn.close()
        except: pass

def get_gift_code_users(gift_id,page=1,per_page=8):
    conn=get_db_connection()
    if not conn: return [],0
    try:
        cur=conn.cursor(dictionary=True); cur.execute("SELECT COUNT(*) c FROM gift_code_uses WHERE gift_code_id=%s",(gift_id,)); total=int(cur.fetchone()['c'] or 0)
        cur.execute("SELECT u.user_id,u.full_name,u.username,g.used_at FROM gift_code_uses g JOIN users u ON u.user_id=g.user_id WHERE g.gift_code_id=%s ORDER BY g.used_at DESC LIMIT %s OFFSET %s",(gift_id,per_page,(page-1)*per_page))
        return cur.fetchall(),total
    except Exception:
        logger.exception("failed loading gift users id=%s",gift_id); return [],0
    finally:
        try: cur.close(); conn.close()
        except: pass

def get_admin_gift_management_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ساخت کد هدیه", callback_data="aset_gift_create")],
        [InlineKeyboardButton("🎲 قرعه‌کشی", callback_data="agift_lottery")],
        [InlineKeyboardButton("📋 لیست و مدیریت کدهای هدیه", callback_data="aset_gift_list")],
        [InlineKeyboardButton("🔙 پنل اصلی", callback_data="apanel_main")]
    ])

def get_admin_settings_keyboard():
    rules = setting_enabled('require_rules', True)
    channel = setting_enabled('require_channel_membership', True)
    verification = setting_enabled('require_verification', True)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 درصد سود", callback_data="aset_self_profit"),
         InlineKeyboardButton("👥 درصد رفرال", callback_data="aset_referral")],
        [InlineKeyboardButton("💳 حداقل شارژ", callback_data="aset_min_charge"),
         InlineKeyboardButton("💳 حداکثر شارژ", callback_data="aset_max_charge")],
        [InlineKeyboardButton("⭐️ حداقل استارز", callback_data="aset_min_stars"),
         InlineKeyboardButton("⭐️ حداکثر استارز", callback_data="aset_max_stars")],
        [InlineKeyboardButton("💱 مدیریت ارزها", callback_data="aset_currencies")],
        [InlineKeyboardButton(("🟢" if rules else "🔴") + " تأیید قوانین", callback_data="aset_toggle_rules"),
         InlineKeyboardButton(("🟢" if channel else "🔴") + " عضویت کانال", callback_data="aset_toggle_channel")],
        [InlineKeyboardButton(("🟢" if verification else "🔴") + " احراز هویت", callback_data="aset_toggle_verification")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="apanel_settings"),
         InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")]
    ])

def get_admin_payments_keyboard():
    methods = get_all_payment_methods()
    keyboard = []
    for method in methods:
        status = "✅" if method[3] else "⛔️"
        keyboard.append([InlineKeyboardButton(f"{status} {method[2]}", callback_data=f"apaytoggle_{method[1]}")])
    keyboard.append([InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_products_management_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ افزودن دسته‌بندی", callback_data="aaddcategory"),
         InlineKeyboardButton("➕ افزودن محصول", callback_data="aaddproduct")],
        [InlineKeyboardButton("📋 لیست دسته‌بندی‌ها", callback_data="alistcategories"),
         InlineKeyboardButton("📋 لیست محصولات", callback_data="alistproducts")],
        [InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_categories_list_keyboard():
    categories = get_all_categories()
    keyboard = []
    for cat in categories:
        emoji = cat[2] if cat[2] else "📦"
        keyboard.append([InlineKeyboardButton(f"{emoji} {cat[1]} (ID: {cat[0]})", callback_data=f"acatdetail_{cat[0]}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_products")])
    return InlineKeyboardMarkup(keyboard)

def get_category_detail_keyboard(category_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"aeditcatname_{category_id}"),
         InlineKeyboardButton("🗑 حذف دسته‌بندی", callback_data=f"adeletecat_{category_id}")],
        [InlineKeyboardButton("➕ افزودن محصول به این دسته", callback_data=f"aaddproducttocat_{category_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="alistcategories")],
    ])

def format_admin_product_details(product):
    """نمایش کامل و یکدست تمام اطلاعات محصول در پنل ادمین."""
    if not product:
        return "❌ محصول پیدا نشد."
    categories = get_all_categories()
    cat_name = next((cat[1] for cat in categories if cat[0] == product[1]), "نامشخص")
    cfg = get_product_input_config(product)
    status = "🟢 فعال" if int(product[9] or 0) else "🔴 غیرفعال" if len(product) > 9 else "نامشخص"
    currency_code, currency, amount, rate = get_product_currency(product)
    currency_name = currency.get('name') or currency_code
    currency_symbol = currency.get('symbol') or currency_code
    prompt = cfg.get('prompt') or 'ندارد'
    max_text = product[7] if product[7] else 'نامحدود'
    target_type = cfg.get('label') or 'بدون دریافت اطلاعات'
    return (
        "💰 <b>اطلاعات کامل محصول</b>\n\n"
        f"🆔 <b>شناسه محصول:</b> {product[0]}\n"
        f"📦 <b>نام محصول:</b> {html.escape(str(product[2]))}\n"
        f"📁 <b>دسته‌بندی:</b> {html.escape(str(cat_name))}\n"
        f"📊 <b>وضعیت:</b> {status}\n\n"
        f"📝 <b>توضیحات:</b> {html.escape(str(product[3] or 'ندارد'))}\n\n"
        f"💱 <b>ارز قیمت:</b> {html.escape(str(currency_symbol))} {html.escape(str(currency_code))} — {html.escape(str(currency_name))}\n"
        f"💵 <b>مبلغ اصلی:</b> {html.escape(format_amount(amount))} {html.escape(str(currency_symbol))}\n"
        f"📈 <b>نرخ ارز:</b> {html.escape(format_amount(rate))} تومان\n"
        f"💰 <b>معادل قیمت پایه:</b> {format_amount(calculate_product_base_toman(product))} تومان\n"
        f"📈 <b>سود اختصاصی محصول:</b> {format_profit_percent(get_product_profit_percent(product))}%\n"
        f"💸 <b>قیمت فروش:</b> {format_amount(apply_product_profit(calculate_product_base_toman(product), get_product_profit_percent(product)))} تومان\n\n"
        f"🔢 <b>قیمت به ازای:</b> {product[5]} عدد\n"
        f"⬇️ <b>حداقل سفارش:</b> {product[6]}\n"
        f"⬆️ <b>حداکثر سفارش:</b> {max_text}\n\n"
        f"📨 <b>نوع اطلاعات سفارش:</b> {html.escape(str(target_type))}\n"
        f"📝 <b>متن درخواست:</b> {html.escape(str(prompt))}\n"
        f"🔗 <b>دریافت اطلاعات مشتری:</b> {'بله' if int(product[8] or 0) else 'خیر'}\n"
    )

def get_product_currency_keyboard(product_id):
    currencies = get_all_currencies() or []
    rows = []
    for c in currencies:
        code = str(c.get('code') or '').upper()
        if not code:
            continue
        symbol = c.get('symbol') or code
        button = InlineKeyboardButton(f"{symbol} {code}", callback_data=f"asetprodcurrency_{code}_{product_id}")
        if rows and len(rows[-1]) == 1:
            rows[-1].append(button)
        else:
            rows.append([button])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"aproductdetail_{product_id}")])
    return InlineKeyboardMarkup(rows)

def get_product_detail_admin_keyboard(product_id):
    conn=get_db_connection();cur=conn.cursor();cur.execute('SELECT show_on_website,show_on_telegram,platform FROM products WHERE id=%s',(product_id,));web,tg,platform=cur.fetchone();cur.close();conn.close()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(('✅' if web else '❌')+' سایت',callback_data=f'achannel_web_{product_id}'),InlineKeyboardButton(('✅' if tg else '❌')+' تلگرام',callback_data=f'achannel_tg_{product_id}')],
        [InlineKeyboardButton('روبیکا',callback_data=f'achannel_rubika_{product_id}'),InlineKeyboardButton('ایتا',callback_data=f'achannel_eitaa_{product_id}'),InlineKeyboardButton('بله',callback_data=f'achannel_bale_{product_id}')],
        [InlineKeyboardButton('محصول تلگرام',callback_data=f'achannel_telegram_{product_id}')],
        [InlineKeyboardButton("✏️ نام", callback_data=f"aeditprod_name_{product_id}"),
         InlineKeyboardButton("✏️ توضیحات", callback_data=f"aeditprod_desc_{product_id}")],
        [InlineKeyboardButton("💰 مبلغ قیمت", callback_data=f"aeditprod_price_{product_id}"),
         InlineKeyboardButton("💱 ارز قیمت", callback_data=f"aeditprod_currency_{product_id}")],
        [InlineKeyboardButton("📈 سود محصول", callback_data=f"aeditprod_profit_{product_id}"),
         InlineKeyboardButton("🔢 قیمت به ازای", callback_data=f"aeditprod_priceper_{product_id}")],
        [InlineKeyboardButton("⬇️ حداقل سفارش", callback_data=f"aeditprod_min_{product_id}"),
         InlineKeyboardButton("⬆️ حداکثر سفارش", callback_data=f"aeditprod_max_{product_id}")],
        [InlineKeyboardButton("📁 تغییر دسته", callback_data=f"aeditprod_category_{product_id}"),
         InlineKeyboardButton("🔗 نوع اطلاعات سفارش", callback_data=f"aeditprod_target_{product_id}")],
        [InlineKeyboardButton("📝 متن درخواست اطلاعات", callback_data=f"aeditprod_prompt_{product_id}")],
        [InlineKeyboardButton("🟢 فعال کردن / 🔴 غیرفعال کردن", callback_data=f"atoggleprod_{product_id}")],
        [InlineKeyboardButton("🗑 حذف محصول", callback_data=f"adeleteprod_{product_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="alistproducts")],
    ])



def get_product_delete_confirm_keyboard(product_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، حذفش کن", callback_data=f"aconfirmdeleteprod_{product_id}"),
         InlineKeyboardButton("❌ نه، برگرد", callback_data=f"acanceldeleteprod_{product_id}")]
    ])


def get_product_category_edit_keyboard(product_id):
    categories = get_all_categories()
    keyboard = []
    for cat in categories:
        emoji = cat[2] if cat[2] else "📦"
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {cat[1]}",
                callback_data=f"asetprodcat_{product_id}_{cat[0]}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton("🔙 بازگشت", callback_data=f"aproductdetail_{product_id}")
    ])
    return InlineKeyboardMarkup(keyboard)


def get_products_list_keyboard(page=1, per_page=10):
    """صفحه اول فقط دسته‌بندی‌ها را نشان می‌دهد؛ با انتخاب دسته محصولات همان دسته باز می‌شوند."""
    categories = get_all_categories()
    keyboard = []
    if not categories:
        keyboard.append([InlineKeyboardButton("❌ هیچ دسته‌بندی فعالی وجود ندارد", callback_data="noop")])
    else:
        for cat in categories:
            emoji = cat[2] if cat[2] else "📦"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {cat[1]}",
                callback_data=f"acatproducts_{cat[0]}_1"
            )])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_products")])
    return InlineKeyboardMarkup(keyboard)

def get_category_products_keyboard(category_id, page=1, per_page=10):
    category = get_category_by_id(category_id)
    products = get_all_category_products_for_admin(category_id)

    if not category:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت به لیست محصولات", callback_data="alistproducts")]
        ])

    total = len(products)
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    page_products = products[start_idx:start_idx + per_page]
    keyboard = []

    if page_products:
        for product in page_products:
            short_name = product[2][:30] + "..." if len(product[2]) > 30 else product[2]
            keyboard.append([
                InlineKeyboardButton(
                    f"📦 {short_name}",
                    callback_data=f"aproductdetail_{product[0]}"
                )
            ])
    else:
        keyboard.append([InlineKeyboardButton("❌ محصولی در این دسته نیست", callback_data="noop")])

    # بازگشت یک ردیف مستقل است؛ ردیف آخر همیشه مخصوص صفحه‌بندی است.
    keyboard.append([InlineKeyboardButton("🔙 لیست دسته‌بندی‌ها", callback_data="alistproducts")])
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"acatproducts_{category_id}_{page-1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"acatproducts_{category_id}_{page+1}"))
    keyboard.append(nav_row)
    return InlineKeyboardMarkup(keyboard)


def get_categories_for_selection_keyboard():
    categories = get_all_categories()
    keyboard = []
    for cat in categories:
        emoji = cat[2] if cat[2] else "📦"
        keyboard.append([InlineKeyboardButton(f"{emoji} {cat[1]}", callback_data=f"selectcat_{cat[0]}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_products")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_receipts_keyboard(page, total, per_page=5):
    total_pages = max(1, math.ceil(total / per_page))
    receipts, _ = get_receipts_page(page, per_page)

    keyboard = []
    keyboard.append([InlineKeyboardButton(f"📄 صفحه {page} از {total_pages} - {total} رسید", callback_data="noop")])

    for receipt in receipts:
        rid, uid, amount, photo_id, ptc, status, aid, ca, rr, pat, cat, full_name, username = receipt
        keyboard.append([InlineKeyboardButton(f"📸 #{rid} - {format_amount(amount)}T - {full_name[:15]}", callback_data=f"areceipt_{rid}")])

    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"apanel_receipts_{page-1}"))
    nav_row.append(InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"apanel_receipts_{page+1}"))
    keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)

# ==================== توابع مدیریت state ====================
async def reset_user_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاک کردن تمام state های کاربر"""
    context.user_data.clear()

    keys_to_clear = [
        'payment_method', 'amount', 'waiting_for_receipt_photo', 
        'product_id', 'product_name', 'product_price', 'min_order', 
        'max_order', 'need_link', 'price_per', 'base_price',
        'order_quantity', 'order_total_price', 'waiting_for_link',
        'waiting_for_tracking_code', 'zarinpal_authority',
        'verification_code', 'verification_in_progress', 'verification_message_id', 'verification_chat_id', 'stars_count', 'star_rate', 'payment_tracking',
        'admin_state', 'ban_user_id', 'toggle_method_key',
        'target_user_id', 'declared_amount', 'receipt_id',
        'waiting_for_support_message', 'support_topic', 'referrer_id',
        'reply_to_user_id', 'waiting_for_reply', 'support_ticket_id',
        'new_category_name', 'new_product_category', 'new_product_name',
        'new_product_description', 'new_product_price', 'new_product_price_amount', 'new_product_currency', 'new_product_price_per',
        'new_product_min_order', 'new_product_max_order',
        'edit_product_id', 'edit_field', 'edit_category_id', 'admin_setting_key', 'admin_user_search',
        'broadcast_target', 'broadcast_targets', 'broadcast_threshold', 'broadcast_ref_threshold', 'broadcast_threshold_target',
        'direct_message_mode', 'cancel_order_id', 'complete_order_id'
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)

async def cancel_and_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو عملیات فعلی و اجرای مجدد /start"""
    await reset_user_state(update, context)
    await start(update, context)
    return ConversationHandler.END

async def _restore_admin_user_detail(context, user_id, chat_id, message_id):
    """بازگرداندن همان پیام اطلاعات کاربر بعد از لغو/اتمام ورودی ادمین."""
    if not user_id or not chat_id or not message_id:
        return False
    user_data = get_user_data(int(user_id))
    if not user_data:
        return False
    status = "⛔️ مسدود" if user_data.get('is_banned') else ("✅ تایید شده" if user_data.get('is_verified') else "⚠️ تایید نشده")
    message = (
        f"👤 <b>اطلاعات کاربر</b>\n\n"
        f"🆔 آیدی: <code>{user_data['user_id']}</code>\n"
        f"👤 نام: {html.escape(str(user_data.get('full_name') or 'ندارد'))}\n"
        f"📱 یوزرنیم: @{html.escape(str(user_data.get('username') or 'ندارد'))}\n"
        f"☎️ شماره تلفن: <tg-spoiler>{html.escape(str(user_data.get('phone_number') or 'ثبت نشده'))}</tg-spoiler>\n"
        f"📊 وضعیت: {status}\n"
        f"💰 موجودی: {format_amount(user_data.get('balance', 0))} تومان\n"
        f"💸 مجموع شارژ/پرداخت: {format_amount(user_data.get('total_payments', 0))} تومان\n"
        f"🛒 مجموع خرید: {format_amount(user_data.get('total_purchases', 0))} تومان\n"
        f"📦 سفارش‌های تکمیل‌شده: {user_data.get('orders_count', 0)}\n"
        f"💰 درآمد کسب‌شده: {format_amount(user_data.get('income', 0))} تومان\n"
        f"👥 تعداد رفرال: {user_data.get('subsets_count', 0)} نفر\n"
        f"🤑 درآمد رفرال: {format_amount(user_data.get('subsets_commission', 0))} تومان\n"
        f"🎁 هدیه مصرف‌شده: {format_amount(user_data.get('consumed_gift', 0))} تومان\n"
        f"🔗 کد رفرال: <code>{user_data.get('referral_code') or 'ندارد'}</code>\n"
        f"👤 معرف: <code>{user_data.get('referrer_id') or 'ندارد'}</code>\n"
        f"📅 تاریخ عضویت: {user_data.get('join_date') or 'نامشخص'}"
    )
    if user_data.get('is_banned'):
        message += f"\n🚫 دلیل بن: {html.escape(str(user_data.get('ban_reason') or 'ثبت نشده'))}"
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=message,
            reply_markup=get_admin_user_detail_keyboard(int(user_id), bool(user_data.get('is_banned'))),
            parse_mode="HTML"
        )
        return True
    except Exception:
        logger.exception("failed restoring admin user detail user=%s", user_id)
        return False

async def cancel_admin_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو همه ورودی‌های ادمین و برگشت به پنل اصلی روی همان پیام."""
    query = update.callback_query
    await query.answer("لغو شد")
    chat_id = context.user_data.get('admin_input_chat_id', query.message.chat_id if query.message else None)
    message_id = context.user_data.get('admin_input_message_id', query.message.message_id if query.message else None)
    await reset_user_state(update, context)
    await _show_admin_main_in_same_message(context, chat_id, message_id)
    return ConversationHandler.END


async def _edit_admin_input_prompt(context, text, reply_markup=None, parse_mode="HTML"):
    """ادیت همان پیام پنل که ادمین در حال وارد کردن اطلاعات آن است."""
    chat_id = context.user_data.get('admin_input_chat_id')
    message_id = context.user_data.get('admin_input_message_id')
    if not chat_id or not message_id:
        return False
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception:
        logger.exception("failed editing admin input prompt")
        return False


async def _show_admin_main_in_same_message(context, chat_id, message_id):
    """نمایش پنل اصلی مدیریت روی همان پیام؛ بدون ارسال پیام جدید."""
    if not chat_id or not message_id:
        return False
    stats = get_total_stats() or {}
    message = (
        "🎛 <b>پنل مدیریت دان پنل</b>\n"
        "━━━━━━━━━━━━━━\n"
        "👥 <b>کاربران</b>\n"
        f"▫️ کل: <b>{stats.get('total_users', 0):,}</b>  •  🚫 بن: <b>{stats.get('banned_users', 0):,}</b>  •  🚫 بلاک: <b>{stats.get('blocked_users', 0):,}</b>\n"
        f"💰 موجودی کل: <b>{format_amount(stats.get('total_balance', 0))} تومان</b>\n"
        "━━━━━━━━━━━━━━\n"
        "📦 <b>سفارش‌ها</b>\n"
        f"▫️ کل: <b>{stats.get('total_orders', 0):,}</b>  •  ⏳ <b>{stats.get('pending_orders', 0):,}</b>  •  🎉 <b>{stats.get('completed_orders', 0):,}</b>  •  ❌ <b>{stats.get('cancelled_orders', 0):,}</b>\n"
        f"📅 امروز: <b>{stats.get('orders_today', 0):,}</b> سفارش | {format_amount(stats.get('sales_today', 0))} تومان\n"
        f"📆 هفته: <b>{stats.get('orders_week', 0):,}</b> سفارش | {format_amount(stats.get('sales_week', 0))} تومان\n"
        f"🗓 ماه: <b>{stats.get('orders_month', 0):,}</b> سفارش | {format_amount(stats.get('sales_month', 0))} تومان\n"
        "━━━━━━━━━━━━━━\n"
        "💎 <b>واریزی‌ها</b>\n"
        f"▫️ کل: <b>{format_amount(stats.get('total_deposits', 0))} تومان</b>\n"
        f"▫️ امروز: <b>{format_amount(stats.get('deposits_today', 0))} تومان</b> ({stats.get('deposit_count_today', 0):,})\n"
        f"▫️ هفته: <b>{format_amount(stats.get('deposits_week', 0))} تومان</b> ({stats.get('deposit_count_week', 0):,})\n"
        f"▫️ ماه: <b>{format_amount(stats.get('deposits_month', 0))} تومان</b> ({stats.get('deposit_count_month', 0):,})\n"
        "━━━━━━━━━━━━━━\n"
        "📸 <b>رسیدهای در انتظار</b>\n"
        f"▫️ <b>{stats.get('pending_receipts', 0):,}</b>\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>سود</b>\n"
        f"▫️ امروز: <b>{format_amount(stats.get('profit_today', 0))} تومان</b>\n"
        f"▫️ هفته: <b>{format_amount(stats.get('profit_week', 0))} تومان</b>\n"
        f"▫️ ماه: <b>{format_amount(stats.get('profit_month', 0))} تومان</b>\n"
        "👇 <b>یک بخش را برای مدیریت انتخاب کنید:</b>"
    )
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=message,
            reply_markup=get_admin_panel_keyboard(), parse_mode='HTML'
        )
        return True
    except Exception as exc:
        logger.warning('failed returning admin main panel chat=%s message=%s: %s', chat_id, message_id, exc)
        return False

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو عملیات؛ برای ورودی‌های ادمین مستقیماً به پنل اصلی برمی‌گردد."""
    # ویرایش نرخ ارز: همان پیام ورودی را به لیست ارزها برگردان.
    if (update.effective_user and update.effective_user.id in ADMIN_IDS
            and context.user_data.get('admin_state') == 'currency_edit_rate'
            and context.user_data.get('currency_code')):
        message_id = context.user_data.get('admin_input_message_id')
        chat_id = context.user_data.get('admin_input_chat_id') or (update.effective_chat.id if update.effective_chat else None)
        for k in ('currency_code', 'admin_state', 'admin_input_message_id', 'admin_input_chat_id'):
            context.user_data.pop(k, None)
        if message_id and chat_id:
            currencies = get_all_currencies() or []
            lines = ["💱 <b>مدیریت ارزها</b>", ""]
            for c in currencies:
                lines.append(
                    f"{c.get('icon') or '💱'} <b>{html.escape(str(c.get('code') or ''))}</b> — "
                    f"{html.escape(str(c.get('name') or c.get('code') or ''))}\n"
                    f"💰 نرخ: {format_amount(int(c.get('rate') or 0))} تومان"
                )
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text="\n".join(lines), reply_markup=get_admin_currencies_keyboard(), parse_mode="HTML"
                )
                return ConversationHandler.END
            except Exception:
                logger.exception("failed returning to currencies after cancel")
        return ConversationHandler.END

    # ویرایش قیمت محصول با ارز: همان پیام را به جزئیات محصول برگردان.
    if (update.effective_user and update.effective_user.id in ADMIN_IDS
            and context.user_data.get('admin_state') == 'edit_product_value'
            and context.user_data.get('edit_field') == 'price_amount'
            and context.user_data.get('edit_product_id')):
        product_id = context.user_data.get('edit_product_id')
        message_id = context.user_data.get('edit_product_prompt_message_id')
        chat_id = context.user_data.get('edit_product_prompt_chat_id') or (update.effective_chat.id if update.effective_chat else None)
        for k in ('edit_product_id', 'edit_field', 'edit_currency_code', 'admin_state', 'edit_product_prompt_message_id', 'edit_product_prompt_chat_id'):
            context.user_data.pop(k, None)
        product = get_product_admin(product_id)
        if product and message_id and chat_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text="❌ <b>عملیات لغو شد.</b>\n\n" + format_admin_product_details(product),
                    reply_markup=get_product_detail_admin_keyboard(product_id), parse_mode="HTML"
                )
                return ConversationHandler.END
            except Exception:
                logger.exception("failed returning to product after currency price cancel")
        return ConversationHandler.END
    input_message_id = context.user_data.get('admin_input_message_id')
    input_chat_id = context.user_data.get('admin_input_chat_id', update.effective_chat.id if update.effective_chat else None)
    if update.effective_user and update.effective_user.id in ADMIN_IDS and input_message_id and input_chat_id:
        await reset_user_state(update, context)
        await _show_admin_main_in_same_message(context, input_chat_id, input_message_id)
        return ConversationHandler.END

    if (update.effective_user and update.effective_user.id in ADMIN_IDS
            and context.user_data.get('admin_state') == 'edit_product_value'
            and context.user_data.get('edit_product_id')):
        product_id = context.user_data.get('edit_product_id')
        await reset_user_state(update, context)
        product = get_product_admin(product_id)
        if product:
            await update.effective_message.reply_text(
                "❌ <b>عملیات لغو شد.</b>\n\n" + format_admin_product_details(product),
                reply_markup=get_product_detail_admin_keyboard(product_id),
                parse_mode='HTML'
            )
        else:
            await update.effective_message.reply_text("❌ <b>عملیات لغو شد.</b>", parse_mode='HTML')
        return ConversationHandler.END

    old_message_id = context.user_data.get('admin_setting_message_id')
    old_chat_id = context.user_data.get('admin_setting_chat_id', update.effective_chat.id)
    was_setting = bool(old_message_id and context.user_data.get('admin_state') == 'setting')

    input_message_id = context.user_data.get('admin_input_message_id')
    input_chat_id = context.user_data.get('admin_input_chat_id', update.effective_chat.id)
    input_user_id = context.user_data.get('admin_input_user_id')

    # مقادیر لازم برای بازگردانی را نگه می‌داریم و بعد state را پاک می‌کنیم.
    await reset_user_state(update, context)

    if was_setting:
        try:
            min_charge = get_setting('min_charge_amount', MIN_CHARGE_AMOUNT)
            max_charge = get_setting('max_charge_amount', MAX_CHARGE_AMOUNT)
            min_stars = get_setting('min_stars', MIN_STARS)
            max_stars = get_setting('max_stars', MAX_STARS)
            message = (
                "⚙️ <b>تنظیمات</b>\n\n"
                f"💰 درصد سود: <b>{get_self_profit_percent():g}%</b>\n"
                f"👥 درصد رفرال: <b>{get_referral_percent():g}%</b>\n"
                f"💳 حداقل شارژ: <b>{float(min_charge):g}</b> تومان\n"
                f"💳 حداکثر شارژ: <b>{float(max_charge):g}</b> تومان\n"
                f"⭐️ حداقل استارز: <b>{float(min_stars):g}</b>\n"
                f"⭐️ حداکثر استارز: <b>{float(max_stars):g}</b>\n\n"
                f"📜 تأیید قوانین: {'فعال' if setting_enabled('require_rules', True) else 'غیرفعال'}\n"
                f"📢 عضویت کانال: {'فعال' if setting_enabled('require_channel_membership', True) else 'غیرفعال'}\n"
                f"🪪 احراز هویت: {'فعال' if setting_enabled('require_verification', True) else 'غیرفعال'}"
            )
            await context.bot.edit_message_text(
                chat_id=old_chat_id, message_id=old_message_id, text=message,
                reply_markup=get_admin_settings_keyboard(), parse_mode="HTML"
            )
        except Exception:
            logger.exception("failed restoring settings panel on cancel")
        return ConversationHandler.END

    if await _restore_admin_user_detail(context, input_user_id, input_chat_id, input_message_id):
        # جلوگیری از باقی ماندن شناسه عملیات قبلی و تداخل با عملیات بعدی.
        for key in ('admin_input_user_id', 'admin_input_chat_id', 'admin_input_message_id',
                    'ban_user_id', 'balance_user_id'):
            context.user_data.pop(key, None)
        return ConversationHandler.END

    # اگر عملیات از پیام دیگری شروع شده بود، همان پیام را ادیت کن؛ reply جدید نساز.
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                "❌ عملیات لغو شد.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")]]),
                parse_mode="HTML"
            )
        except Exception:
            pass
    elif update.effective_message:
        try:
            await update.effective_message.edit_text("❌ عملیات لغو شد.", parse_mode="HTML")
        except Exception:
            pass
    return ConversationHandler.END

# ==================== بررسی عضویت در کانال ====================
def get_rules_accepted(user_id):
    connection = get_db_connection()
    if not connection: return False
    try:
        cur=connection.cursor()
        cur.execute("SELECT COALESCE(rules_accepted,0) FROM users WHERE user_id=%s", (user_id,))
        row=cur.fetchone()
        return bool(row and row[0])
    except Error:
        logger.exception("failed reading rules_accepted user=%s", user_id)
        return False
    finally:
        try: cur.close(); connection.close()
        except: pass

def set_rules_accepted(user_id):
    connection=get_db_connection()
    if not connection: return False
    try:
        cur=connection.cursor()
        cur.execute("UPDATE users SET rules_accepted=1 WHERE user_id=%s", (user_id,))
        connection.commit()
        logger.info("rules accepted user=%s", user_id)
        return True
    except Error:
        logger.exception("failed setting rules_accepted user=%s", user_id)
        return False
    finally:
        try: cur.close(); connection.close()
        except: pass

def get_welcome_text(user):
    return (
        f"✨ سلام <a href='tg://user?id={user.id}'>{user.full_name}</a> عزیز!\n\n"
        f"🎯 به دان پنل خوش آمدید\n\n"
        f"🌟 خدمات ما:\n"
        f"• 📊 انواع خدمات تلگرام با بهترین کیفیت\n"
        f"• ⚡️ تحویل فوری و تضمینی\n"
        f"• 💰 قیمت‌های رقابتی و منصفانه\n"
        f"• 🔐 امنیت و پشتیبانی ۲۴ ساعته\n\n"
        f"📋 برای شروع یکی از گزینه‌های زیر را انتخاب کنید:"
    )

def rules_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 قوانین استفاده از ربات", url=RULES_LINK)],
        [InlineKeyboardButton("📋 قوانین ثبت سفارش", url=ORDER_RULES_LINK)],
        [InlineKeyboardButton("✅ قوانین را خواندم و می‌پذیرم", callback_data="accept_rules")]
    ])

async def show_rules_message(update, context):
    text=(
        "📜 <b>قوانین استفاده از ربات</b>\n\n"
        "برای استفاده از ربات باید قوانین استفاده و قوانین ثبت سفارش را مطالعه کرده و تأیید کنید.\n\n"
        "⚠️ تا زمانی که قوانین را تأیید نکنید، امکان استفاده از ربات را ندارید."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=rules_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=rules_keyboard(), parse_mode="HTML")

async def accept_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    await query.answer()
    user=query.from_user
    if is_user_banned(user.id)[0]:
        await query.answer("⛔️ حساب شما مسدود است.", show_alert=True); return
    # عضویت کانال را فقط اگر کانال تنظیم شده بررسی کن
    if REQUIRED_CHANNEL_ID:
        try:
            member=await context.bot.get_chat_member(REQUIRED_CHANNEL_ID,user.id)
            if member.status not in ['member','administrator','creator']:
                await query.answer("❌ ابتدا عضو کانال شوید.", show_alert=True)
                return
        except Exception:
            await query.answer("❌ عضویت کانال قابل بررسی نیست.", show_alert=True)
            logger.exception("channel membership check failed on rule accept user=%s", user.id)
            return
    if not set_rules_accepted(user.id):
        await query.answer("❌ ذخیره تأیید قوانین انجام نشد.", show_alert=True); return
    referrer_id = get_pending_referrer(user.id) or context.user_data.get('referrer_id')
    if referrer_id and finalize_referral(user.id, referrer_id):
        try:
            await context.bot.send_message(
                referrer_id,
                "🌟 تبریک! یک کاربر با لینک دعوت شما وارد ربات شد.\n\n💰 با هر شارژ، پورسانت رفرال به شما تعلق می‌گیرد.",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("failed notifying referrer=%s referred=%s", referrer_id, user.id)
    context.user_data.pop('referrer_id', None)
    await query.message.delete()
    await context.bot.send_message(user.id, get_welcome_text(user), reply_markup=get_main_menu(), parse_mode="HTML")

async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if not setting_enabled('require_channel_membership', True) or not REQUIRED_CHANNEL_ID:
        return True
    try:
        chat_member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL_ID, user_id=user_id)
        if chat_member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            await send_join_channel_message(update, context)
            return False
    except Exception as e:
        await send_join_channel_message(update, context)
        return False

async def send_join_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = "🔐 **برای استفاده از ربات، ابتدا باید عضو کانال ما شوید!**\n\n✨ با عضویت در کانال، از جدیدترین اخبار و خدمات ما باخبر شوید."
    keyboard = [
        [InlineKeyboardButton("📢 عضویت در کانال", url=REQUIRED_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]
    ]
    if update.message:
        await update.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    is_banned, ban_reason = is_user_banned(user.id)
    if is_banned:
        if user.id not in banned_users_notified:
            banned_users_notified.add(user.id)
            await query.answer("⛔️ حساب شما مسدود شده است!", show_alert=True)
            await query.message.delete()
            await context.bot.send_message(chat_id=user.id, text=f"⛔️ اکانت شما مسدود شد ❌\n\n📝 دلیل: {ban_reason or 'نقض قوانین'}\n\n🆔 {SUPPORT_USERNAME}")
        else:
            await query.answer("⛔️ حساب شما مسدود است.", show_alert=True)
        return

    if await check_channel_membership(update, context):
        referrer_id = get_pending_referrer(user.id) or context.user_data.get('referrer_id')
        user_data = get_or_create_user(user.id, user.full_name, user.username, None)
        if not user_data:
            await query.answer("❌ خطا در ثبت اطلاعات کاربر.", show_alert=True)
            return

        # رفرال عمداً تا پایان قوانین ثبت نمی‌شود.
        if setting_enabled('require_rules', True) and not get_rules_accepted(user.id):
            await show_rules_message(update, context)
            return

        # اگر قوانین خاموش باشند، همین‌جا پس از عضویت کانال رفرال نهایی می‌شود.
        if referrer_id and finalize_referral(user.id, referrer_id):
            try:
                await context.bot.send_message(
                    referrer_id,
                    "🌟 تبریک! یک کاربر با لینک دعوت شما وارد ربات شد.\n\n💰 با هر شارژ، پورسانت رفرال به شما تعلق می‌گیرد.",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("failed notifying referrer=%s referred=%s", referrer_id, user.id)
        context.user_data.pop('referrer_id', None)
        await query.message.delete()
        await context.bot.send_message(chat_id=query.message.chat_id, text=get_welcome_text(user), reply_markup=get_main_menu(), parse_mode="HTML")
    else:
        await query.answer("❌ هنوز عضو نشده‌اید!", show_alert=True)

# ==================== اطلاعات حساب ====================
async def show_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_membership(update, context): return
    user = update.effective_user

    is_banned, ban_reason = is_user_banned(user.id)
    if is_banned:
        if user.id not in banned_users_notified:
            banned_users_notified.add(user.id)
            await update.message.reply_text(f"⛔️ اکانت شما مسدود شد ❌\n\n📝 دلیل: {ban_reason or 'نقض قوانین'}\n\n🆔 {SUPPORT_USERNAME}")
        return

    get_or_create_user(user.id, user.full_name, user.username)
    user_data = get_user_data(user.id)

    if user_data:
        if user_data.get('is_banned'): account_status = "⛔️ مسدود شده"
        elif user_data['is_verified']: account_status = "✅ تایید شده"
        else: account_status = "⚠️ تایید نشده"

        message = (
            f"👤 اطلاعات حساب شما\n\n"
            f"📝 نام: {user_data['full_name']}\n"
            f"🔢 آیدی: <code>{user_data['user_id']}</code>\n"
            f"📊 وضعیت: {account_status}\n\n"
            f"🛒 سفارشات: {user_data['orders_count']}\n"
            f"💸 مجموع پرداختی: {user_data['total_payments']:,}\n"
            f"🛍 مجموع خرید: {user_data['total_purchases']:,}\n\n"
            f"💰 درآمد: {user_data['income']:,}\n"
            f"🫂 زیرمجموعه: {user_data['subsets_count']} نفر\n"
            f"🤑 پورسانت: {user_data['subsets_commission']:,}\n\n"
            f"💰 موجودی: {user_data['balance']:,} تومان\n\n"
            f"⏰ عضویت: {user_data['join_date']}"
        )
    else:
        message = "❌ اطلاعات شما یافت نشد."

    await update.message.reply_text(message, reply_markup=get_main_menu(), parse_mode="HTML")

# ==================== نمایش دسته‌بندی‌ها ====================
async def show_categories_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_membership(update, context): return
    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned: return

    categories = get_all_categories()
    if categories:
        await update.message.reply_text("👈 لطفا دسته بندی مورد نظر خود را انتخاب کنید.", reply_markup=get_categories_inline_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ هیچ دسته‌بندی فعالی وجود ندارد.", reply_markup=get_main_menu())

# ==================== مدیریت callback ها ====================
async def handle_all_inline_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned:
        await query.answer("⛔️ حساب شما مسدود است.", show_alert=True)
        return

    if data == "cancel_online_transaction":
        await query.answer()
        user = update.effective_user
        active_transaction = get_active_zarinpal_transaction(user.id)

        if active_transaction:
            cancelled = cancel_zarinpal_transaction(user.id)
            if cancelled:
                cancel_message = (
                    f"✅ <b>تراکنش آنلاین با موفقیت لغو شد</b>\n\n"
                    f"💰 مبلغ: {format_amount(cancelled['amount'])} تومان\n"
                    f"🔢 کد پیگیری: <code>{cancelled['payment_tracking_code']}</code>\n"
                    f"📅 تاریخ: {get_jalali_datetime()}\n\n"
                    f"📋 برای ادامه، از دکمه‌های زیر استفاده کنید."
                )
                await query.edit_message_text(cancel_message, parse_mode="HTML")
                await context.bot.send_message(
                    chat_id=user.id,
                    text="📋 یکی از گزینه‌های زیر را انتخاب کنید:",
                    reply_markup=get_main_menu()
                )
            else:
                await query.answer("❌ خطا در لغو تراکنش!", show_alert=True)
        else:
            await query.answer("❌ تراکنش فعالی یافت نشد!", show_alert=True)
        return

    if data == "no_product":
        await query.answer(text="❌ محصولی یافت نشد!", show_alert=True)
        return

    if data == "close_list":
        await query.message.delete()
        user = update.effective_user
        context.user_data.clear()
        welcome_text = f"✨ سلام <a href='tg://user?id={user.id}'>{user.full_name}</a> عزیز!\n\n🎯 به دان پنل خوش آمدید\n\n📋 برای شروع یکی از گزینه‌های زیر را انتخاب کنید:"
        await context.bot.send_message(chat_id=user.id, text=welcome_text, reply_markup=get_main_menu(), parse_mode="HTML")
        return

    if data == "back_to_categories":
        context.user_data.pop('product_id', None)
        categories = get_all_categories()
        if categories:
            await query.edit_message_text("👈 لطفا دسته بندی مورد نظر خود را انتخاب کنید.", reply_markup=get_categories_inline_keyboard(), parse_mode="HTML")
        return

    if data.startswith("backprod_"):
        await query.answer()
        category_id = int(data.split("_")[1])
        context.user_data.pop('product_id', None)
        category = get_category_by_id(category_id)
        if not category:
            await query.answer("❌ دسته‌بندی پیدا نشد یا غیرفعال است.", show_alert=True)
            return
        cat_name, cat_emoji = category[1], (category[2] if category[2] else "📦")
        await query.edit_message_text(f"{cat_emoji} {html.escape(str(cat_name))}\n\n👈 لطفا محصول مورد نظر خود را انتخاب کنید.", reply_markup=get_products_inline_keyboard(category_id), parse_mode="HTML")
        return

    if data.startswith("cat_"):
        await query.answer()
        category_id = int(data.split("_")[1])
        context.user_data.pop('product_id', None)
        category = get_category_by_id(category_id)
        if not category:
            await query.answer("❌ دسته‌بندی پیدا نشد یا غیرفعال است.", show_alert=True)
            return
        cat_name, cat_emoji = category[1], (category[2] if category[2] else "📦")
        products = get_category_products(category_id)
        if not products:
            logger.warning("User category selected but no active products found: category_id=%s", category_id)
        await query.edit_message_text(f"{cat_emoji} {html.escape(str(cat_name))}\n\n👈 لطفا محصول مورد نظر خود را انتخاب کنید.", reply_markup=get_products_inline_keyboard(category_id), parse_mode="HTML")
        return

    if data.startswith("prod_"):
        product_id = int(data.rsplit("_", 1)[1])
        product = get_product(product_id)
        if product:
            price_info = calculate_price_info(product)
            description = product[3] or ""
            category_id = product[1]

            context.user_data.update({
                'product_id': product[0], 'product_name': product[2], 'product_price': price_info['price_per_unit'],
                'min_order': price_info['min_order'], 'max_order': price_info['max_order'],
                'need_link': price_info['need_link'], 'price_per': price_info['price_per'], 'base_price': price_info['price']
            })

            categories = get_all_categories()
            cat_name = next((cat[1] for cat in categories if cat[0] == category_id), "")

            message = f"✅ سرویس: {product[2]}\n"
            if cat_name: message += f"📱 دسته: {cat_name}\n"
            if description: message += f"ــ ـ ــ  ــ ــ ـ ــ ـ\n📝 {description}\nــ ـ ــ  ــ ــ ـ ــ ـ\n"
            message += f"{format_product_price(price_info)}\n"
            if price_info['min_order'] and price_info['max_order']:
                message += f"⬇️ حداقل: {price_info['min_order']:,} - ⬆️ حداکثر: {price_info['max_order']:,}\n"
            elif price_info['min_order'] and price_info['min_order'] > 1:
                message += f"⬇️ حداقل: {price_info['min_order']:,} عدد\n"
            elif price_info['max_order']:
                message += f"⬆️ حداکثر: {price_info['max_order']:,} عدد\n"

            user = update.effective_user
            user_data = get_user_data(user.id)
            user_balance = user_data['balance'] if user_data else 0
            max_affordable = user_balance // price_info['price_per_unit'] if price_info['price_per_unit'] > 0 else 0

            if user_balance > 0 and max_affordable > 0:
                affordable = min(max_affordable, price_info['max_order']) if price_info['max_order'] else max_affordable
                message += f"\n✔️ میتوانید {affordable:,} عدد سفارش دهید.\n"
                await query.edit_message_text(message, reply_markup=get_product_detail_keyboard(product_id, category_id), parse_mode="HTML")
            else:
                message += "\n⚠️ موجودی کافی نیست.\n"
                await query.edit_message_text(message, reply_markup=get_product_no_balance_keyboard(category_id), parse_mode="HTML")
        return

    if data.startswith("sr_"):
        amount = data[3:]
        await query.answer()
        context.user_data['waiting_for_receipt_photo'] = True

        # بعد از زدن «پرداخت کردم»، دکمه قبلی باید حذف شود تا کاربر نتواند
        # چند بار روی آن بزند و چند بار وارد مرحله ارسال رسید شود.
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.exception("failed removing card payment keyboard user=%s", update.effective_user.id)

        await query.message.reply_text(
            "🖼 تصویر رسید خود را ارسال نمایید\n\n"
            "⚠️ نکات مهم:\n"
            "• تصویر باید واضح و خوانا باشد\n"
            "• شماره کارت و مبلغ مشخص باشد\n"
            "• فقط عکس (jpg یا png)",
            reply_markup=get_receipt_waiting_keyboard()
        )
        return

async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("txn_"):
        page = int(data.split("_")[1])
        transactions, total = get_user_transactions_page(update.effective_user.id, page, 10)
        if transactions:
            message = f"💸 <b>تراکنش‌های اخیر</b>\n📄 صفحه {page} از {max(1, (total + 9) // 10)}\n\n"
            keyboard_rows = []
            for t in transactions:
                tracking = t[5] if len(t) > 5 and t[5] else str(t[0])
                keyboard_rows.append([InlineKeyboardButton(f"🔎 {tracking}", callback_data=f"usertransaction_{t[0]}")])
            nav_markup = get_pagination_keyboard("txn", page, total, 10)
            if nav_markup.inline_keyboard:
                keyboard_rows.extend(nav_markup.inline_keyboard)
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard_rows),
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text("❌ تراکنشی نیست.", parse_mode="HTML")

    elif data.startswith("ord_"):
        page = int(data.split("_")[1])
        orders, total = get_user_orders_page(update.effective_user.id, page, 10)
        if orders:
            message = f"🛒 <b>سفارشات اخیر</b>\n📄 صفحه {page} از {(total + 9) // 10}\n\n"
            keyboard_rows = []
            for o in orders:
                status_emoji = "🎉" if o[9] == 'completed' else ("⏳" if o[9] == 'pending' else ("✅" if o[9] == 'confirmed' else "❌"))
                keyboard_rows.append([InlineKeyboardButton(f"{status_emoji} {o[1]}", callback_data=f"userorder_{o[0]}")])
            # صفحه‌بندی پایین لیست
            total_pages = max(1, math.ceil(total / 10))
            nav = []
            if page > 1:
                nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"ord_{page-1}"))
            nav.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"ord_{page+1}"))
            keyboard_rows.append(nav)
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
        else:
            await query.edit_message_text("❌ سفارشی نیست.", parse_mode="HTML")

async def user_transaction_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        transaction_id = int(query.data.split("_")[1])
    except (ValueError, IndexError):
        await query.answer("❌ تراکنش نامعتبر است.", show_alert=True)
        return
    connection = get_db_connection()
    transaction = None
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM transactions WHERE id = %s AND user_id = %s LIMIT 1", (transaction_id, update.effective_user.id))
            transaction = cursor.fetchone()
            cursor.close(); connection.close()
        except Exception as e:
            try: connection.close()
            except: pass
            logger.exception("transaction detail failed id=%s user=%s", transaction_id, update.effective_user.id)
    if not transaction:
        await query.answer("❌ این تراکنش پیدا نشد.", show_alert=True)
        return
    amount = transaction[2] or 0
    sign = "+" if amount > 0 else "-"
    tracking = transaction[5] if len(transaction) > 5 and transaction[5] else "-"
    status = get_transaction_status_fa(transaction[6] if len(transaction) > 6 else None) or "—"
    message = (
        "💸 <b>جزئیات تراکنش</b>\n\n"
        f"💰 مبلغ: <b>{sign}{abs(amount):,} تومان</b>\n"
        f"📝 نوع: {get_transaction_type_fa(transaction[3])}\n"
        f"💬 توضیحات: {transaction[4] or '—'}\n"
        f"📊 وضعیت: {status}\n"
        f"🔢 کد پیگیری: <code>{tracking}</code>\n"
        f"📅 تاریخ: {format_datetime_fa(transaction[7] if len(transaction) > 7 else None)}"
    )
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به تراکنش‌ها", callback_data="txn_1")]]), parse_mode="HTML")


async def user_order_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        order_id = int(query.data.split("_")[1])
    except (ValueError, IndexError):
        return
    order = get_order(order_id)
    if not order or int(order[2]) != int(update.effective_user.id):
        await query.answer("❌ این سفارش برای شما نیست.", show_alert=True)
        return
    status_map = {'pending':'⏳ در انتظار', 'confirmed':'🔄 تأیید شده', 'completed':'🎉 تکمیل شده', 'cancelled':'❌ لغو شده'}
    status = status_map.get(order[9], f"❓ {order[9]}")
    product_name = html.escape(str(order[4] or '-'))
    message = (
        f"🛒 <b>جزئیات سفارش</b>\n\n"
        f"📦 محصول: <b>{product_name}</b>\n"
        f"🔢 کد پیگیری: <code>{html.escape(str(order[1]))}</code>\n"
        f"💰 مبلغ: <b>{format_amount(order[8])} تومان</b>\n"
        f"📊 وضعیت: <b>{status}</b>\n"
        f"📅 تاریخ: {format_datetime_fa(order[11])}\n"
    )
    if order[5]:
        message += f"🔗 لینک: {html.escape(str(order[5]))}\n"
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به سفارشات", callback_data="ord_1")]]),
        parse_mode="HTML"
    )

async def order_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned: await query.answer("⛔️ حساب شما مسدود است.", show_alert=True); return

    await query.answer()
    await query.message.delete()

    product_id = int(query.data.split("_")[1])
    product = get_product(product_id)
    if not product: await query.message.reply_text("❌ محصول یافت نشد.", reply_markup=get_main_menu()); return

    price_info = calculate_price_info(product)
    context.user_data.update({
        'product_id': product[0], 'product_name': product[2], 'product_price': price_info['price_per_unit'],
        'min_order': price_info['min_order'], 'max_order': price_info['max_order'],
        'need_link': price_info['need_link'], 'price_per': price_info['price_per'], 'base_price': price_info['price']
    })

    user = update.effective_user
    user_data = get_user_data(user.id)
    user_balance = user_data['balance'] if user_data else 0
    max_affordable = user_balance // price_info['price_per_unit'] if price_info['price_per_unit'] > 0 else 0

    message = f"{product[3]}\n\n" if product[3] else ""
    message += f"{format_product_price(price_info)}\n"
    if price_info['min_order'] and price_info['max_order']:
        message += f"⬇️ حداقل: {price_info['min_order']:,} - ⬆️ حداکثر: {price_info['max_order']:,}\n"
    elif price_info['min_order'] and price_info['min_order'] > 1: message += f"⬇️ حداقل: {price_info['min_order']:,}\n"
    elif price_info['max_order']: message += f"⬆️ حداکثر: {price_info['max_order']:,}\n"

    if user_balance > 0 and max_affordable > 0:
        affordable = min(max_affordable, price_info['max_order']) if price_info['max_order'] else max_affordable
        message += f"\n✔️ میتوانید {affordable:,} عدد سفارش دهید.\n"
    else: message += "\n⚠️ موجودی کافی نیست.\n"

    message += "\n👈 تعداد مورد نظر را ارسال کنید:"
    await query.message.reply_text(message, reply_markup=get_back_keyboard(), parse_mode="HTML")

# ==================== پیگیری ====================
async def show_tracking_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_membership(update, context): return
    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned: return
    await update.message.reply_text("📞 بخش پیگیری\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=get_tracking_menu_keyboard(), parse_mode="HTML")

# ==================== مدیریت تیکت‌های پشتیبانی ====================
def create_support_ticket(user_id, topic, message_text):
    conn=get_db_connection()
    if not conn: return None
    try:
        cur=conn.cursor(); cur.execute("INSERT INTO support_messages (user_id,topic,message_text) VALUES (%s,%s,%s)",(user_id,topic,message_text)); conn.commit(); tid=cur.lastrowid; cur.close(); conn.close(); return tid
    except Exception as e:
        logger.exception("create_support_ticket failed: %s",e)
        try: conn.close()
        except: pass
        return None

def mark_support_answered(ticket_id, admin_id):
    conn=get_db_connection()
    if not conn: return False
    try:
        cur=conn.cursor(); cur.execute("UPDATE support_messages SET answered=1,answered_by=%s,answered_at=CURRENT_TIMESTAMP WHERE id=%s AND answered=0",(admin_id,ticket_id)); conn.commit(); ok=cur.rowcount>0; cur.close(); conn.close(); return ok
    except Exception as e:
        logger.exception("mark_support_answered failed: %s",e)
        try: conn.close()
        except: pass
        return False

def get_support_ticket(ticket_id):
    conn=get_db_connection()
    if not conn: return None
    try:
        cur=conn.cursor(dictionary=True); cur.execute("SELECT * FROM support_messages WHERE id=%s",(ticket_id,)); row=cur.fetchone(); cur.close(); conn.close(); return row
    except Exception:
        try: conn.close()
        except: pass
        return None

def get_support_list(answered=None, topic=None, page=1, per_page=10):
    conn=get_db_connection()
    if not conn: return [],0
    try:
        cur=conn.cursor(dictionary=True); where=[]; params=[]
        if answered is not None: where.append("answered=%s"); params.append(int(answered))
        if topic is not None: where.append("topic=%s"); params.append(topic)
        clause=(" WHERE "+" AND ".join(where)) if where else ""
        cur.execute(f"SELECT COUNT(*) AS total FROM support_messages{clause}",tuple(params)); total=int(cur.fetchone()['total'] or 0)
        cur.execute(f"SELECT id,user_id,topic,message_text,created_at,answered,answered_by,answered_at FROM support_messages{clause} ORDER BY id DESC LIMIT %s OFFSET %s",tuple(params+[per_page,(page-1)*per_page]))
        rows=cur.fetchall(); cur.close(); conn.close(); return rows,total
    except Exception as e:
        logger.exception("get_support_list failed: %s",e)
        try: conn.close()
        except: pass
        return [],0

def get_support_topics():
    conn=get_db_connection()
    if not conn: return []
    try:
        cur=conn.cursor(); cur.execute("SELECT topic,COUNT(*) total,SUM(answered=0) unanswered FROM support_messages GROUP BY topic ORDER BY total DESC"); rows=cur.fetchall(); cur.close(); conn.close(); return rows
    except Exception:
        try: conn.close()
        except: pass
        return []

def get_support_counts():
    conn=get_db_connection()
    if not conn: return 0,0
    try:
        cur=conn.cursor(); cur.execute("SELECT SUM(answered=0),SUM(answered=1) FROM support_messages"); a,b=cur.fetchone(); cur.close(); conn.close(); return int(a or 0),int(b or 0)
    except Exception:
        try: conn.close()
        except: pass
        return 0,0

def get_admin_support_keyboard():
    unanswered, answered = get_support_counts()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏳ بدون پاسخ  •  {unanswered}", callback_data="asupport_unanswered_1")],
        [InlineKeyboardButton(f"✅ پاسخ داده شده  •  {answered}", callback_data="asupport_answered_1")],
        [InlineKeyboardButton("📂 دسته‌بندی موضوعات", callback_data="asupport_topics")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="apanel_support"),
         InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")]
    ])

def get_support_list_keyboard(rows,page,total,mode):
    kb=[]
    for r in rows:
        status="⏳" if not r['answered'] else "✅"
        title=(r['topic'] or 'بدون موضوع')[:18]
        kb.append([InlineKeyboardButton(f"{status} #{r['id']} — {title} — {r['user_id']}",callback_data=f"asupport_ticket_{r['id']}")])
    pages=max(1,(total+9)//10); nav=[]
    if page>1:
        cb=f"asupport_topic_{mode.split('_')[1]}_{page-1}" if mode.startswith('topic_') else f"asupport_{mode}_{page-1}"
        nav.append(InlineKeyboardButton("⬅️ قبلی",callback_data=cb))
    nav.append(InlineKeyboardButton(f"{page}/{pages}",callback_data="asupport_noop"))
    if page<pages:
        cb=f"asupport_topic_{mode.split('_')[1]}_{page+1}" if mode.startswith('topic_') else f"asupport_{mode}_{page+1}"
        nav.append(InlineKeyboardButton("بعدی ➡️",callback_data=cb))
    kb.append(nav); kb.append([InlineKeyboardButton("🔙 مدیریت پشتیبانی",callback_data="apanel_support")])
    return InlineKeyboardMarkup(kb)

# ==================== پشتیبانی ====================
async def show_support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_membership(update, context): return
    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned: return

    await update.message.reply_text(
        "🛡 <b>بخش پشتیبانی</b>\n\n"
        "لطفاً موضوع مورد نظر خود را انتخاب کنید:",
        reply_markup=get_support_keyboard(),
        parse_mode="HTML"
    )

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    topic = context.user_data.get('support_topic', 'مشخص نشده')
    ticket_id = create_support_ticket(user.id, topic, text)

    support_message = (
        f"📨 <b>پیام پشتیبانی جدید</b>\n\n"
        f"👤 کاربر: {user.full_name}\n"
        f"🆔 آیدی: <code>{user.id}</code>\n"
        f"📱 یوزرنیم: @{user.username or 'ندارد'}\n"
        f"📝 موضوع: {topic}\n"
        f"💬 پیام: {text}\n"
        f"📅 تاریخ: {get_jalali_datetime()}\n\n"
        f"💡 <b>برای پاسخ به کاربر، روی دکمه زیر کلیک کنید.</b>"
    )

    reply_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"reply_support_{ticket_id}_{user.id}")]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id, 
                text=support_message, 
                parse_mode="HTML",
                reply_markup=reply_keyboard
            )
        except:
            pass

    await update.message.reply_text(
        "✅ پیام شما با موفقیت ارسال شد.\n\n"
        "📩 تیم پشتیبانی در اسرع وقت به پیام شما رسیدگی خواهد کرد.",
        reply_markup=get_main_menu()
    )

    context.user_data.pop('waiting_for_support_message', None)
    context.user_data.pop('support_topic', None)

# ==================== پاسخ ادمین به کاربر ====================
async def admin_reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if query.data.startswith('reply_support_'):
        ticket_id=int(parts[2]); user_id=int(parts[3]); context.user_data['support_ticket_id']=ticket_id
    else:
        user_id=int(parts[2]); context.user_data.pop('support_ticket_id',None)
    context.user_data['reply_to_user_id']=user_id
    context.user_data['waiting_for_reply'] = True

    await query.message.reply_text(
        f"💬 لطفاً پیام پاسخ خود را برای کاربر {user_id} بنویسید:\n\n"
        f"برای لغو /cancel را بزنید."
    )

    return SUPPORT_MESSAGE_INPUT

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = msg.text or ""

    if text in ["/start", "/cancel"]:
        context.user_data.pop('reply_to_user_id', None)
        context.user_data.pop('waiting_for_reply', None)
        context.user_data.pop('support_ticket_id', None)
        await update.message.reply_text("❌ عملیات لغو شد.")
        return ConversationHandler.END

    user_id = context.user_data.get('reply_to_user_id')
    ticket_id = context.user_data.get('support_ticket_id')

    if user_id:
        try:
            # پیام‌های ادمین باید برای کاربر مشخص کنند که پیام از طرف پشتیبانی است.
            # برای متن، همان یک پیام با هدر پشتیبانی ارسال می‌شود.
            # برای رسانه‌هایی که caption دارند نیز هدر داخل caption قرار می‌گیرد.
            # برای پیام‌هایی که caption ندارند، در صورت نیاز fallback به دو پیام انجام می‌شود.
            support_header = "📨 پیام از طرف پشتیبانی\n\n"

            if msg.text is not None:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=support_header + msg.text
                )
            elif msg.caption is not None:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=msg.message_id,
                    caption=support_header + msg.caption
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="📨 پیام از طرف پشتیبانی"
                )
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=msg.message_id
                )
            if ticket_id:
                mark_support_answered(ticket_id, update.effective_user.id)
            await update.message.reply_text(f"✅ پاسخ شما به کاربر {user_id} ارسال شد.", parse_mode="HTML")
        except Exception as e:
            logger.exception("support reply failed admin=%s user=%s ticket=%s", update.effective_user.id, user_id, ticket_id)
            await update.message.reply_text(f"❌ خطا در ارسال پاسخ: {e}")
    else:
        await update.message.reply_text("❌ کاربر مورد نظر یافت نشد.")

    context.user_data.pop('reply_to_user_id', None)
    context.user_data.pop('waiting_for_reply', None)
    context.user_data.pop('support_ticket_id', None)
    return ConversationHandler.END

# ==================== مدیریت سفارش ====================
async def handle_inline_order_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned: return

    if text in ["🔙 منوی اصلی", "🔙 منوی قبلی"]:
        context.user_data.clear()
        await update.message.reply_text("👈 به منوی اصلی بازگشتید.\n📋 یکی از گزینه‌ها را انتخاب کنید:", reply_markup=get_main_menu(), parse_mode="HTML")
        return

    try: quantity = int(text.replace(",", "").strip())
    except: await update.message.reply_text("❌ عدد معتبر وارد کنید.", reply_markup=get_back_keyboard()); return

    if quantity <= 0: await update.message.reply_text("❌ تعداد باید > 0 باشد.", reply_markup=get_back_keyboard()); return

    product_id = context.user_data.get('product_id')
    product = get_product(product_id)
    if not product: context.user_data.clear(); await update.message.reply_text("❌ محصول در دسترس نیست.", reply_markup=get_main_menu()); return

    price_info = calculate_price_info(product)
    context.user_data.update({'product_price': price_info['price_per_unit'], 'min_order': price_info['min_order'],
                              'max_order': price_info['max_order'], 'price_per': price_info['price_per'], 'base_price': price_info['price']})

    min_order, max_order, need_link = price_info['min_order'], price_info['max_order'], price_info['need_link']
    user = update.effective_user
    user_data = get_user_data(user.id)
    user_balance = user_data['balance'] if user_data else 0

    if quantity < min_order: await update.message.reply_text(f"❌ حداقل خرید {min_order:,} عدد.", reply_markup=get_back_keyboard()); return
    if max_order and quantity > max_order: await update.message.reply_text(f"❌ حداکثر خرید {max_order:,} عدد.", reply_markup=get_back_keyboard()); return

    total_price = calculate_total_price(price_info['price'], price_info['price_per'], quantity)
    if total_price > user_balance:
        shortage = total_price - user_balance
        context.user_data.clear()
        await update.message.reply_text(f"❌ موجودی کافی نیست!\n\n💰 موجودی: {user_balance:,} تومان\n💎 قیمت کل: {total_price:,} تومان\n⚠️ کمبود: {shortage:,} تومان", reply_markup=get_main_menu())
        return

    context.user_data['order_quantity'] = quantity
    context.user_data['order_total_price'] = total_price

    input_cfg = get_product_input_config(product)
    if input_cfg['type'] != 'none':
        # متن دلخواه باید دقیقاً با همان فاصله‌ها و خط‌های جدیدی که پشتیبانی ثبت کرده ارسال شود.
        if input_cfg['type'] == 'username':
            username_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 یوزرنیم خودم", callback_data="order_username_self")],
                [InlineKeyboardButton("❌ لغو سفارش", callback_data="cancel_order_input")]
            ])
            await update.message.reply_text(input_cfg['prompt'], reply_markup=username_keyboard, parse_mode="HTML")
        elif input_cfg['type'] == 'custom':
            await update.message.reply_text(input_cfg['prompt'], reply_markup=get_back_keyboard())
        else:
            await update.message.reply_text(input_cfg['prompt'], reply_markup=get_back_keyboard(), parse_mode="HTML")
        context.user_data['waiting_for_link'] = True
        return

    return await finalize_order(update, context, "")

def get_order_reorder_keyboard(product_id):
    """Keyboard shown after a successful order so the user can order the same product again."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 ثبت سفارش مجدد", callback_data=f"reorder_{int(product_id)}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_categories")]
    ])


async def username_self_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use the Telegram username of the current user as order information."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    username = (user.username or '').strip()
    if not username:
        await query.message.reply_text(
            "❌ <b>یوزرنیم تلگرام ندارید.</b>\n\n"
            "برای ثبت این سفارش باید حتماً برای حساب تلگرام خود یک یوزرنیم تنظیم کنید.\n"
            "بعد از تنظیم یوزرنیم، دوباره روی «👤 یوزرنیم خودم» بزنید.",
            parse_mode="HTML"
        )
        return
    value = '@' + username.lstrip('@')
    context.user_data['waiting_for_link'] = False
    await finalize_order(update, context, value)


async def finalize_order(update: Update, context: ContextTypes.DEFAULT_TYPE, target_link):
    """Show the final order review. Money is NOT deducted until the user confirms."""
    user = update.effective_user
    is_banned, _ = is_user_banned(user.id)
    if is_banned:
        return

    product_id = context.user_data.get('product_id')
    product = get_product(product_id)
    if not product:
        context.user_data.clear()
        await update.effective_message.reply_text("❌ محصول در دسترس نیست.", reply_markup=get_main_menu())
        return

    price_info = calculate_price_info(product)
    product_name = context.user_data.get('product_name', product[2])
    quantity = int(context.user_data.get('order_quantity', 0) or 0)
    total_price = calculate_total_price(price_info['price'], price_info['price_per'], quantity)

    user_data = get_user_data(user.id)
    user_balance = user_data['balance'] if user_data else 0
    if total_price > user_balance:
        shortage = total_price - user_balance
        context.user_data.clear()
        await update.effective_message.reply_text(
            f"❌ موجودی کافی نیست!\n\n"
            f"💰 موجودی: {format_amount(user_balance)} تومان\n"
            f"💎 قیمت کل: {format_amount(total_price)} تومان\n"
            f"⚠️ کمبود: {format_amount(shortage)} تومان",
            reply_markup=get_main_menu(), parse_mode="HTML"
        )
        return

    # Keep everything required for the confirmation callback.
    context.user_data.update({
        'pending_order_target': str(target_link or ''),
        'pending_order_quantity': quantity,
        'pending_order_total_price': total_price,
        'pending_order_product_id': product_id,
        'pending_order_product_name': product_name,
    })

    safe_product_name = html.escape(str(product_name or '-'))
    safe_target = html.escape(str(target_link or '-'))
    review = (
        "✅ <b>اطلاعات زیر را بررسی کرده و درصورت صحیح بودن تایید کنید.</b>\n\n"
        f"🔰 <b>نوع سفارش :</b> 🌟 {safe_product_name} 🌟\n"
        f"💠 <b>تعداد :</b> {quantity:,}\n"
        f"🔗 <b>اطلاعات سفارش :</b> {safe_target}\n"
        f"💸 <b>قیمت فاکتور :</b> {format_amount(total_price)} تومان\n\n"
        "👈 درصورت تایید کردن سفارش امکان لغو سفارش وجود ندارد."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید سفارش", callback_data="user_confirm_order"),
         InlineKeyboardButton("❌ لغو سفارش", callback_data="cancel_order_input")]
    ])
    await update.effective_message.reply_text(review, reply_markup=keyboard, parse_mode="HTML")


async def user_confirm_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deduct balance and create the order only after the user confirms the review."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    product_id = context.user_data.get('pending_order_product_id')
    product = get_product(product_id)
    if not product:
        context.user_data.clear()
        await query.message.reply_text("❌ این محصول دیگر در دسترس نیست.", reply_markup=get_main_menu())
        return

    quantity = int(context.user_data.get('pending_order_quantity', 0) or 0)
    total_price = int(context.user_data.get('pending_order_total_price', 0) or 0)
    target_link = str(context.user_data.get('pending_order_target') or '')
    product_name = context.user_data.get('pending_order_product_name', product[2])

    if quantity <= 0 or total_price <= 0:
        context.user_data.clear()
        await query.message.reply_text("❌ اطلاعات سفارش نامعتبر است.", reply_markup=get_main_menu())
        return

    # Re-check balance at the exact moment of confirmation.
    user_data = get_user_data(user.id)
    user_balance = int(user_data['balance'] if user_data else 0)
    if total_price > user_balance:
        context.user_data.clear()
        await query.message.reply_text(
            f"❌ موجودی شما برای این سفارش کافی نیست.\n\n"
            f"💰 موجودی فعلی: {format_amount(user_balance)} تومان\n"
            f"💸 مبلغ سفارش: {format_amount(total_price)} تومان",
            reply_markup=get_main_menu(), parse_mode="HTML"
        )
        return

    # Prevent double-clicks on the confirmation button.
    if context.user_data.get('creating_order'):
        return
    context.user_data['creating_order'] = True

    order_id = None
    tracking_code = None
    try:
        order_id, tracking_code = await asyncio.to_thread(
            integration.purchase, user.id, product_id, quantity, target_link, total_price
        )

        order_row = get_order(order_id)
        created_at = order_row[11] if order_row and len(order_row) > 11 else None
        created_text = format_datetime_fa(created_at) if created_at else get_jalali_datetime()
        safe_product_name = html.escape(str(product_name or '-'))
        safe_target = html.escape(str(target_link or '-'))
        user_message = (
            "✅ <b>سفارش شما با موفقیت ثبت شد !</b>\n\n"
            f"🔰 <b>نوع سفارش :</b> 🌟 {safe_product_name} 🌟\n"
            f"💠 <b>تعداد :</b> {quantity:,}\n"
            f"🔗 <b>اطلاعات سفارش :</b> {safe_target}\n"
            f"💸 <b>مبلغ سفارش :</b> {format_amount(total_price)} تومان\n"
            f"🔍 <b>کد پیگیری شما :</b> <code>{html.escape(str(tracking_code))}</code>\n"
            f"⏳ <b>زمان ثبت :</b> {html.escape(created_text)}\n\n"
            "✳️ انجام سفارشات زمان بر میباشد، پس لطفاً تا انجام سفارش صبور باشید."
        )

        await query.message.edit_text(user_message, parse_mode="HTML", reply_markup=get_order_reorder_keyboard(product_id))

        for admin_id in ADMIN_IDS:
            try:
                admin_msg = (
                    "📦 <b>سفارش جدید</b>\n\n"
                    f"🆔 #{order_id}\n"
                    f"🔍 <b>کد پیگیری:</b> <code>{html.escape(str(tracking_code))}</code>\n"
                    f"👤 {html.escape(str(user.full_name or '-'))}\n"
                    f"🔹 یوزرنیم: {html.escape('@' + user.username if user.username else 'ندارد')}\n"
                    f"🆔 آیدی عددی: <code>{user.id}</code>\n"
                    f"📦 {safe_product_name}\n"
                    f"🔢 {quantity:,}\n"
                    f"💰 {format_amount(total_price)} تومان"
                )
                if target_link:
                    admin_msg += f"\n🔗 اطلاعات سفارش: {safe_target}"
                await context.bot.send_message(
                    chat_id=admin_id, text=admin_msg,
                    reply_markup=get_order_approval_keyboard(order_id), parse_mode="HTML"
                )
            except Exception:
                logger.exception("failed sending new order to admin order=%s admin=%s", order_id, admin_id)

    except Exception:
        logger.exception("failed creating confirmed user order user=%s product=%s", user.id, product_id)
        try:
            await query.message.reply_text((f"✅ سفارش ثبت شد. کد پیگیری: {tracking_code}" if order_id else "❌ ثبت سفارش انجام نشد؛ موجودی تغییری نکرده است."), reply_markup=get_main_menu())
        except Exception:
            pass
    finally:
        context.user_data.clear()


async def cancel_order_input_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("لغو شد.")
    await reset_user_state(update, context)
    try:
        await query.message.reply_text(
            "❌ <b>ثبت سفارش لغو شد.</b>\n\nبه منوی اصلی بازگشتید.",
            reply_markup=get_main_menu(), parse_mode="HTML"
        )
    except Exception:
        pass


async def reorder_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    product_id = int(query.data.split("_")[1])
    product = get_product(product_id)
    if not product:
        await query.edit_message_text("❌ این محصول دیگر در دسترس نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منوی اصلی", callback_data="apanel_close")]]), parse_mode="HTML")
        return

    price_info = calculate_price_info(product)
    context.user_data.update({
        'product_id': product[0], 'product_name': product[2], 'product_price': price_info['price_per_unit'],
        'min_order': price_info['min_order'], 'max_order': price_info['max_order'],
        'need_link': price_info['need_link'], 'price_per': price_info['price_per'], 'base_price': price_info['price']
    })
    user_data = get_user_data(user_id)
    balance = user_data['balance'] if user_data else 0
    max_affordable = balance // price_info['price_per_unit'] if price_info['price_per_unit'] > 0 else 0
    prompt = f"🔁 <b>سفارش مجدد</b>\n\n📦 <b>{html.escape(str(product[2]))}</b>\n"
    if price_info['min_order']: prompt += f"⬇️ حداقل: <b>{price_info['min_order']:,}</b>\n"
    if price_info['max_order']: prompt += f"⬆️ حداکثر: <b>{price_info['max_order']:,}</b>\n"
    prompt += f"💰 موجودی شما: <b>{format_amount(balance)} تومان</b>\n\n🔢 <b>تعداد موردنظر را ارسال کنید:</b>"
    await query.edit_message_text(prompt, parse_mode="HTML")

async def confirm_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True); return
    await query.answer()
    order_id = int(query.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order[9] != 'pending':
        await query.answer("⚠️ این سفارش قبلاً تعیین تکلیف شده است.", show_alert=True); return
    if not await asyncio.to_thread(integration.transition, order_id, 'confirmed'):
        return
    try:
        now_text = get_jalali_datetime()
        date_part, time_part = now_text.split(" - ", 1)
        await context.bot.send_message(
            chat_id=order[2],
            text=(f"♻️ سفارش شما با کد پیگیری <code>{html.escape(str(order[1]))}</code> "
                  f"در تاریخ {html.escape(date_part)} و ساعت {html.escape(time_part)} تایید شد و به زودی انجام میشود !\n\n"
                  "👈 لطفا تا زمان انجام سفارش خود صبور باشید."),
            parse_mode="HTML"
        )
        # The report channel receives the successful-purchase report immediately after admin confirmation.
        await send_successful_order_report(context, order)
        await query.edit_message_text(
            query.message.text + "\n\n✅ تایید شد - در حال انجام",
            reply_markup=get_order_completion_keyboard(order_id),
            parse_mode="HTML"
        )
    except Exception:
        logger.exception('failed confirming order=%s', order_id)

async def complete_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True); return
    order_id = int(query.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order[9] == 'cancelled':
        await query.answer("❌ سفارش لغو شده است.", show_alert=True); return
    if order[9] == 'completed':
        await query.answer("⚠️ سفارش قبلاً تکمیل شده است.", show_alert=True); return
    if order[9] != 'confirmed':
        await query.answer("⚠️ ابتدا سفارش را تایید کنید، سپس آن را تکمیل کنید.", show_alert=True)
        return

    # First click only asks for confirmation; no status change or user notification yet.
    await query.answer("⚠️ آیا مطمئن هستید که می‌خواهید این سفارش را تکمیل کنید؟", show_alert=True)
    try:
        await query.message.edit_reply_markup(reply_markup=get_order_completion_confirm_keyboard(order_id))
    except Exception:
        logger.exception('failed showing completion confirmation for order=%s', order_id)
    return

async def confirm_complete_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True); return
    await query.answer()
    order_id = int(query.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order[9] == 'cancelled':
        await query.answer("❌ سفارش لغو شده است.", show_alert=True); return
    if order[9] == 'completed':
        await query.answer("⚠️ سفارش قبلاً تکمیل شده است.", show_alert=True); return
    if order[9] != 'confirmed':
        await query.answer("⚠️ این سفارش هنوز تایید نشده است.", show_alert=True); return
    if not await asyncio.to_thread(integration.transition, order_id, 'completed'):
        return
    try:
        now_text = get_jalali_datetime()
        date_part, time_part = now_text.split(" - ", 1)
        await context.bot.send_message(
            chat_id=order[2],
            text=(f"✅ سفارش شما با کد پیگیری <code>{html.escape(str(order[1]))}</code> "
                  f"در تاریخ {html.escape(date_part)} و ساعت {html.escape(time_part)} با موفقیت تکمیل شد !"),
            parse_mode="HTML"
        )
        await query.edit_message_text(query.message.text + "\n\n🎉 تکمیل شد", reply_markup=None, parse_mode="HTML")
    except Exception:
        logger.exception('failed completing order=%s', order_id)

async def complete_order_with_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True); return
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    order = get_order(order_id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order[9] in ('cancelled', 'completed'):
        await query.answer("⚠️ این سفارش قبلاً نهایی شده است.", show_alert=True); return
    context.user_data['admin_state'] = 'order_complete_message'
    context.user_data['complete_order_id'] = order_id
    await query.edit_message_text(
        query.message.text + "\n\n📨 <b>مشخصات یا پیام موردنظر را ارسال کن.</b>\n"
        "می‌توانی متن، عکس، فایل یا هر محتوای دیگری بفرستی.\n\nبرای لغو /cancel را بزن.",
        reply_markup=None, parse_mode='HTML')

async def reject_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True); return
    await query.answer()
    order_id = int(query.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order[9] in ('cancelled', 'completed'):
        await query.answer("⚠️ این سفارش قبلاً نهایی شده است.", show_alert=True); return
    context.user_data['admin_state'] = 'order_cancel_reason'
    context.user_data['cancel_order_id'] = order_id
    await query.edit_message_text(
        query.message.text + "\n\n❌ <b>دلیل لغو سفارش را وارد کن:</b>\n"
        "این دلیل برای کاربر ارسال می‌شود و مبلغ سفارش بعد از ثبت دلیل به موجودی او برمی‌گردد.\n\nبرای لغو عملیات /cancel را بزن.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"backorder_{order_id}")]]),
        parse_mode='HTML')

async def back_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True); return
    await query.answer()
    order_id = int(query.data.split("_")[1])
    order = get_order(order_id)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True); return
    if order[9] == 'pending':
        keyboard = get_order_approval_keyboard(order_id)
    elif order[9] == 'confirmed':
        keyboard = get_order_completion_keyboard(order_id)
    else:
        keyboard = None
    # Remove any temporary admin prompt from the current message.
    text = query.message.text or query.message.caption or ''
    markers = ["\n\n❌ <b>دلیل لغو سفارش را وارد کن:</b>", "\n\n📨 <b>مشخصات یا پیام موردنظر را ارسال کن.</b>"]
    for marker in markers:
        if marker in text:
            text = text.split(marker, 1)[0]
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

# ==================== بخش شارژ حساب ====================
def create_charge_handler():
    async def start_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await check_channel_membership(update, context): 
            return ConversationHandler.END

        is_banned, _ = is_user_banned(update.effective_user.id)
        if is_banned: 
            return ConversationHandler.END

        await reset_user_state(update, context)

        user_data = get_user_data(update.effective_user.id)
        if setting_enabled('require_verification', True) and (not user_data or not user_data.get('phone_number') or not user_data.get('is_verified')):
            await update.message.reply_text(
                "📱 لطفاً شماره موبایل خود را به اشتراک بگذارید:", 
                reply_markup=get_share_contact_reply_keyboard(), 
                parse_mode="HTML"
            )
            return PHONE_NUMBER_INPUT

        await update.message.reply_text(
            f"💎 <b>شارژ حساب</b>\n\n✅ لطفاً روش پرداخت خود را انتخاب کنید:",
            reply_markup=get_payment_methods_keyboard(),
            parse_mode="HTML"
        )
        return SELECT_PAYMENT_METHOD

    async def receive_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text if update.message.text else ""

        if text == "/start":
            return await cancel_and_restart(update, context)

        if text == "🔙 منوی اصلی":
            await update.message.reply_text(
                "👈 به منوی اصلی بازگشتید.\n📋 یکی از گزینه‌ها را انتخاب کنید:", 
                reply_markup=get_main_menu(), 
                parse_mode="HTML"
            )
            return ConversationHandler.END

        if not update.message.contact:
            await update.message.reply_text(
                "❌ لطفاً از دکمه اشتراک‌گذاری استفاده کنید.", 
                reply_markup=get_share_contact_reply_keyboard()
            )
            return PHONE_NUMBER_INPUT

        phone = update.message.contact.phone_number
        is_valid, formatted_phone = validate_iranian_phone(phone)
        if not is_valid:
            await update.message.reply_text(
                "❌ شماره ایران نیست.", 
                reply_markup=get_share_contact_reply_keyboard()
            )
            return PHONE_NUMBER_INPUT

        verification = request_phone_verification_code(update.effective_user.id, formatted_phone)
        status = verification.get('status') if verification else 'error'

        if status == 'limit':
            context.user_data.pop('verification_code', None)
            await update.message.reply_text(
                "🚫 سقف ارسال کد تأیید امروز برای شما پر شده است.\n\n"
                f"📩 حداکثر <b>{SMS_DAILY_LIMIT}</b> پیامک در روز ارسال می‌شود.\n"
                "👈 لطفاً روز بعد دوباره تلاش کنید.",
                reply_markup=get_main_menu(),
                parse_mode="HTML"
            )
            return ConversationHandler.END

        if status == 'error':
            context.user_data.pop('verification_code', None)
            await update.message.reply_text(
                "❌ ارسال کد تأیید انجام نشد. لطفاً دوباره تلاش کنید.",
                reply_markup=get_main_menu()
            )
            return ConversationHandler.END

        save_phone_number(update.effective_user.id, formatted_phone)
        context.user_data['verification_code'] = verification.get('code', '')

        message = (
            "📩 یک کد تأیید ۶ رقمی به شماره شما ارسال شد.\n\n"
            "👈 لطفاً کد ۶ رقمی را وارد کنید:"
        )

        sent_message = await update.message.reply_text(
            message,
            reply_markup=get_verification_keyboard(),
            parse_mode="HTML"
        )
        context.user_data['verification_in_progress'] = True
        context.user_data['verification_message_id'] = sent_message.message_id
        context.user_data['verification_chat_id'] = sent_message.chat_id
        return VERIFICATION_CODE

    async def verify_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text

        if text == "/start":
            return await cancel_and_restart(update, context)

        if text == "🔙 منوی اصلی":
            await update.message.reply_text(
                "👈 به منوی اصلی بازگشتید.\n📋 یکی از گزینه‌ها را انتخاب کنید:", 
                reply_markup=get_main_menu(), 
                parse_mode="HTML"
            )
            return ConversationHandler.END

        if text == "🔙 منوی قبلی":
            await update.message.reply_text(
                "📱 شماره خود را به اشتراک بگذارید:", 
                reply_markup=get_share_contact_reply_keyboard()
            )
            return PHONE_NUMBER_INPUT

        state = get_phone_verification_state(update.effective_user.id)
        active_code = str((state or {}).get('verification_code') or '').strip()

        if not state or not active_code or not bool(state.get('is_active')):
            context.user_data.pop('verification_code', None)
            context.user_data.pop('verification_in_progress', None)
            context.user_data.pop('verification_message_id', None)
            context.user_data.pop('verification_chat_id', None)
            consume_phone_verification_code(update.effective_user.id)
            await update.message.reply_text(
                "⌛️ کد تأیید منقضی شده است.\n\n"
                "فرایند تأیید شماره لغو شد؛ برای تلاش دوباره از منوی اصلی وارد «💳 شارژ حساب» شوید.",
                reply_markup=get_main_menu(),
                parse_mode="HTML"
            )
            return ConversationHandler.END

        if text.strip() == active_code:
            verify_user(update.effective_user.id)
            consume_phone_verification_code(update.effective_user.id)
            context.user_data.pop('verification_code', None)
            context.user_data.pop('verification_in_progress', None)
            verification_message_id = context.user_data.pop('verification_message_id', None)
            verification_chat_id = context.user_data.pop('verification_chat_id', None)
            if verification_message_id and verification_chat_id:
                try:
                    await context.bot.edit_message_reply_markup(chat_id=verification_chat_id, message_id=verification_message_id, reply_markup=None)
                except Exception:
                    pass
            await update.message.reply_text(
                f"🎉 احراز هویت با موفقیت انجام شد!\n\n"
                f"💎 <b>شارژ حساب</b>\n"
                f"✅ لطفاً روش پرداخت خود را انتخاب کنید:",
                reply_markup=get_payment_methods_keyboard(),
                parse_mode="HTML"
            )
            return SELECT_PAYMENT_METHOD

        attempt_count = increment_phone_verification_attempt(update.effective_user.id)
        if attempt_count is not None and attempt_count >= SMS_MAX_ATTEMPTS:
            invalidate_phone_verification_code(update.effective_user.id)
            context.user_data.pop('verification_code', None)
            await update.message.reply_text(
                "❌ کد وارد شده اشتباه است.\n\n"
                f"🚫 حداکثر {SMS_MAX_ATTEMPTS} بار امکان وارد کردن کد وجود دارد و این کد باطل شد.\n"
                "👈 برای دریافت کد جدید، روی دکمه «📩 درخواست مجدد کد» بزنید.",
                reply_markup=get_verification_keyboard(),
                parse_mode="HTML"
            )
            return VERIFICATION_CODE

        await update.message.reply_text(
            "❌ کد وارد شده اشتباه است.",
            reply_markup=get_verification_keyboard()
        )
        return VERIFICATION_CODE

    async def resend_verification_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        state = get_phone_verification_state(user_id)
        phone = str((state or {}).get('phone_number') or '').strip()
        if not phone:
            await query.answer("❌ شماره‌ای برای ارسال مجدد پیدا نشد.", show_alert=True)
            return

        verification = request_phone_verification_code(user_id, phone, force_new=True)
        status = verification.get('status') if verification else 'error'
        if status == 'limit':
            await query.answer(
                f"🚫 سقف ارسال روزانه ({SMS_DAILY_LIMIT} پیامک) تکمیل شده است.",
                show_alert=True
            )
            return
        if status == 'cooldown':
            await query.answer(
                f"⏳ لطفاً {verification.get('remaining', SMS_RESEND_COOLDOWN_SECONDS)} ثانیه دیگر دوباره درخواست کنید.",
                show_alert=True
            )
            return
        if status in ('sent', 'existing'):
            context.user_data['verification_code'] = verification.get('code', '')
            try:
                await query.edit_message_text(
                    "📩 یک کد تأیید ۶ رقمی به شماره شما ارسال شد.\n\n"
                    "👈 لطفاً کد ۶ رقمی را وارد کنید:",
                    reply_markup=get_verification_keyboard(),
                    parse_mode="HTML"
                )
            except Exception:
                await query.message.reply_text(
                    "📩 یک کد تأیید ۶ رقمی به شماره شما ارسال شد.\n\n"
                    "👈 لطفاً کد ۶ رقمی را وارد کنید:",
                    reply_markup=get_verification_keyboard(),
                    parse_mode="HTML"
                )
            return

        await query.answer("❌ ارسال کد جدید انجام نشد. دوباره تلاش کنید.", show_alert=True)

    async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text

        if text == "/start":
            return await cancel_and_restart(update, context)

        if text == "🔙 منوی اصلی":
            await update.message.reply_text(
                "👈 به منوی اصلی بازگشتید.\n📋 یکی از گزینه‌ها را انتخاب کنید:", 
                reply_markup=get_main_menu(), 
                parse_mode="HTML"
            )
            return ConversationHandler.END

        if text == "💸 پرداخت آنلاین":
            active_transaction = get_active_zarinpal_transaction(update.effective_user.id)
            if active_transaction:
                cancel_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ لغو تراکنش آنلاین", callback_data="cancel_online_transaction")]
                ])
                await update.message.reply_text(
                    f"⚠️ <b>شما یک تراکنش آنلاین در انتظار دارید!</b>\n\n"
                    f"💰 مبلغ: {format_amount(active_transaction['amount'])} تومان\n"
                    f"🔢 کد پیگیری: <code>{active_transaction['payment_tracking_code']}</code>\n"
                    f"📅 تاریخ: {get_jalali_datetime()}\n\n"
                    f"❌ تا زمان اتمام این تراکنش، امکان ایجاد تراکنش جدید وجود ندارد.\n"
                    f"برای ایجاد تراکنش جدید، ابتدا تراکنش فعلی را لغو کنید.",
                    reply_markup=cancel_keyboard,
                    parse_mode="HTML"
                )
                await update.message.reply_text(
                    "💎 <b>شارژ حساب</b>\n\n✅ لطفاً روش پرداخت خود را انتخاب کنید:",
                    reply_markup=get_payment_methods_keyboard(),
                    parse_mode="HTML"
                )
                return SELECT_PAYMENT_METHOD

            is_active, reason = get_payment_method_status('online')
            if not is_active:
                await update.message.reply_text(
                    f"⛔️ این روش پرداخت غیرفعال است.\n📝 {reason}", 
                    reply_markup=get_payment_methods_keyboard()
                )
                return SELECT_PAYMENT_METHOD

            context.user_data['payment_method'] = 'online'
            await update.message.reply_text(
                f"💸 مبلغ مورد نظر خود را بین {format_amount(get_setting('min_charge_amount', MIN_CHARGE_AMOUNT))} تومان تا {format_amount(get_setting('max_charge_amount', MAX_CHARGE_AMOUNT))} تومان وارد کنید:",
                reply_markup=get_back_keyboard(),
                parse_mode="HTML"
            )
            return AMOUNT_INPUT

        if text == "⭐️ پرداخت با استارز":
            is_active, reason = get_payment_method_status('stars')
            if not is_active:
                await update.message.reply_text(
                    f"⛔️ این روش پرداخت غیرفعال است.\n📝 {reason}", 
                    reply_markup=get_payment_methods_keyboard()
                )
                return SELECT_PAYMENT_METHOD

            context.user_data['payment_method'] = 'stars'
            star_rate = get_star_rate_toman()
            if star_rate is None:
                logger.error("STAR payment blocked: active STAR currency/rate is missing or invalid")
                await update.message.reply_text(
                    "❌ نرخ استارز در بخش «مدیریت ارزها» معتبر نیست یا ارز STAR غیرفعال است.\n\n"
                    "برای جلوگیری از شارژ اشتباه حساب، پرداخت با استارز متوقف شد.",
                    reply_markup=get_payment_methods_keyboard()
                )
                return SELECT_PAYMENT_METHOD

            # Snapshot فقط برای نمایش/کنترل؛ هنگام ثبت مقدار دوباره نرخ جاری از DB خوانده می‌شود.
            context.user_data['star_rate'] = str(star_rate)
            min_stars = int(Decimal(str(get_setting('min_stars', MIN_STARS))))
            max_stars = int(Decimal(str(get_setting('max_stars', MAX_STARS))))

            await update.message.reply_text(
                f"⭐️ <b>پرداخت با استارز</b>\n\n"
                f"⭐️ لطفا تعداد استارز مورد نظر خود را وارد کنید:\n\n"
                f"📊 محدوده مجاز: {min_stars:,} تا {max_stars:,} استارز\n"
                f"💰 نرخ تبدیل: هر استارز = {format_amount(star_rate)} تومان\n\n"
                f"💡 مثال: اگر 1 استارز وارد کنید، {format_amount(star_rate)} تومان به حساب شما اضافه می‌شود.",
                reply_markup=get_back_keyboard(),
                parse_mode="HTML"
            )
            return STARS_AMOUNT_INPUT

        elif text == "💳 کارت به کارت":
            is_active, reason = get_payment_method_status('card')
            if not is_active:
                await update.message.reply_text(
                    f"⛔️ این روش پرداخت غیرفعال است.\n📝 {reason}", 
                    reply_markup=get_payment_methods_keyboard()
                )
                return SELECT_PAYMENT_METHOD

            context.user_data['payment_method'] = 'card'
            await update.message.reply_text(
                f"💸 مبلغ مورد نظر خود را بین {format_amount(get_setting('min_charge_amount', MIN_CHARGE_AMOUNT))} تومان تا {format_amount(get_setting('max_charge_amount', MAX_CHARGE_AMOUNT))} تومان وارد کنید:",
                reply_markup=get_back_keyboard(),
                parse_mode="HTML"
            )
            return AMOUNT_INPUT

        elif text == "💰 پرداخت با ارز دیجیتال":
            is_active, reason = get_payment_method_status('crypto')
            if not is_active:
                await update.message.reply_text(
                    f"⛔️ این روش پرداخت غیرفعال است.\n📝 {reason}", 
                    reply_markup=get_payment_methods_keyboard()
                )
                return SELECT_PAYMENT_METHOD

            currencies = get_all_currencies()
            crypto_list = [c for c in currencies if c['type'] == 'crypto']
            message = f"💰 <b>پرداخت با ارز دیجیتال</b>\n\n🔸 جهت شارژ به {SUPPORT_USERNAME} پیام دهید.\n\n💎 ارزهای قابل قبول:\n"
            for c in crypto_list:
                message += f"{c['icon'] or '•'} {c['name']}: {format_amount(c['rate'])} تومان\n"
            await update.message.reply_text(message, reply_markup=get_main_menu(), parse_mode="HTML")
            return ConversationHandler.END

        else:
            await update.message.reply_text(
                "❌ لطفاً یکی از روش‌های پرداخت را انتخاب کنید:", 
                reply_markup=get_payment_methods_keyboard()
            )
            return SELECT_PAYMENT_METHOD

    async def precheckout_star_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """اعتبارسنجی فاکتور قبل از نهایی شدن پرداخت Telegram Stars."""
        query = update.pre_checkout_query
        try:
            parts = (query.invoice_payload or '').split(':')
            if len(parts) != 5 or parts[0] != 'STAR':
                await query.answer(ok=False, error_message="❌ اطلاعات فاکتور معتبر نیست.")
                return
            user_id = int(parts[1])
            stars = int(parts[2])
            rate = int(parts[3])
            tracking = parts[4]
            if user_id != query.from_user.id or stars <= 0 or rate <= 0 or not re.fullmatch(r'[0-9a-f]{10}', tracking):
                await query.answer(ok=False, error_message="❌ اطلاعات پرداخت معتبر نیست.")
                return
            if query.currency != 'XTR' or int(query.total_amount) != stars:
                await query.answer(ok=False, error_message="❌ مبلغ فاکتور با درخواست شما مطابقت ندارد.")
                return

            conn = get_db_connection()
            if not conn:
                await query.answer(ok=False, error_message="❌ خطای موقت سرور. لطفاً دوباره تلاش کنید.")
                return
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute("SELECT status, user_id, stars_count, star_rate, amount_toman FROM star_payments WHERE payment_tracking_code=%s LIMIT 1", (tracking,))
                row = cur.fetchone()
                if not row or int(row['user_id']) != user_id or row['status'] != 'pending':
                    await query.answer(ok=False, error_message="❌ این تراکنش دیگر معتبر نیست.")
                    return
                if int(row['stars_count']) != stars or int(row['star_rate']) != rate:
                    await query.answer(ok=False, error_message="❌ اطلاعات نرخ این تراکنش تغییر کرده است.")
                    return
                expected_amount = stars * rate
                if int(row['amount_toman']) != expected_amount:
                    await query.answer(ok=False, error_message="❌ مبلغ شارژ معتبر نیست.")
                    return
            finally:
                try: cur.close(); conn.close()
                except Exception: pass

            await query.answer(ok=True)
        except Exception:
            logger.exception("STAR pre-checkout validation failed")
            try:
                await query.answer(ok=False, error_message="❌ خطا در بررسی پرداخت. لطفاً دوباره تلاش کنید.")
            except Exception:
                pass

    async def successful_star_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بعد از پرداخت موفق Telegram Stars، مبلغ دقیق محاسبه‌شده را فقط یک‌بار واریز می‌کند."""
        payment = update.message.successful_payment
        if not payment:
            return
        try:
            parts = (payment.invoice_payload or '').split(':')
            if len(parts) != 5 or parts[0] != 'STAR':
                logger.error("invalid STAR successful payment payload")
                return
            user_id = int(parts[1])
            stars = int(parts[2])
            rate = int(parts[3])
            tracking = parts[4]
            if user_id != update.effective_user.id or payment.currency != 'XTR' or int(payment.total_amount) != stars:
                logger.error("invalid STAR payment values user=%s tracking=%s", user_id, tracking)
                await update.message.reply_text("❌ پرداخت دریافت شد اما اطلاعات آن معتبر نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                return

            conn = get_db_connection()
            if not conn:
                await update.message.reply_text("❌ پرداخت دریافت شد، اما اتصال به دیتابیس برقرار نشد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                return

            amount = 0
            already_paid = False
            try:
                conn.start_transaction()
                cur = conn.cursor(dictionary=True)
                cur.execute("SELECT * FROM star_payments WHERE payment_tracking_code=%s FOR UPDATE", (tracking,))
                row = cur.fetchone()
                if not row or int(row['user_id']) != user_id:
                    conn.rollback()
                    await update.message.reply_text("❌ تراکنش پیدا نشد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                    return

                if row['status'] == 'credited':
                    already_paid = True
                    amount = int(row['amount_toman'])
                    conn.commit()
                elif row['status'] != 'pending':
                    conn.rollback()
                    await update.message.reply_text("❌ وضعیت این تراکنش قابل پردازش نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                    return
                else:
                    if int(row['stars_count']) != stars or int(row['star_rate']) != rate:
                        conn.rollback()
                        await update.message.reply_text("❌ اطلاعات پرداخت با فاکتور مطابقت ندارد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                        return
                    amount = stars * rate
                    if amount != int(row['amount_toman']):
                        conn.rollback()
                        await update.message.reply_text("❌ مبلغ پرداختی قابل تأیید نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                        return

                    cur.execute("""UPDATE users SET balance=balance+%s, total_payments=total_payments+%s WHERE user_id=%s""", (amount, amount, user_id))
                    if cur.rowcount != 1:
                        raise RuntimeError("user balance row not found")
                    cur.execute("""INSERT INTO transactions (user_id, amount, type, description, payment_tracking_code, status) VALUES (%s,%s,'deposit',%s,%s,'completed')""", (user_id, amount, f'شارژ با Telegram Stars - {stars} استارز معادل {format_amount(amount)} تومان (نرخ: {format_amount(rate)})', tracking))
                    cur.execute("""UPDATE star_payments SET status='credited', telegram_payment_charge_id=%s, provider_payment_charge_id=%s, paid_at=NOW() WHERE id=%s""", (payment.telegram_payment_charge_id, payment.provider_payment_charge_id, row['id']))
                    conn.commit()
            except Exception:
                try: conn.rollback()
                except Exception: pass
                logger.exception("failed crediting Telegram STAR payment user=%s tracking=%s", user_id, tracking)
                await update.message.reply_text("❌ پرداخت شما دریافت شد اما واریز موجودی با خطا مواجه شد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                return
            finally:
                try: cur.close(); conn.close()
                except Exception: pass

            if already_paid:
                await update.message.reply_text(f"ℹ️ این پرداخت قبلاً ثبت شده است.\n\n💠 موجودی ثبت‌شده: {format_amount(amount)} تومان", reply_markup=get_main_menu())
                return

            commission_info = add_commission_to_referrer(user_id, amount)
            if commission_info:
                try:
                    await context.bot.send_message(
                        commission_info['referrer_id'],
                        f"🥳 تبریک!\n👥 {commission_info['referred_name']} مقدار {format_amount(commission_info['charge_amount'])} تومان با استارز شارژ کرد و {format_amount(commission_info['commission'])} پورسانت واریز شد.",
                        parse_mode="HTML"
                    )
                except Exception:
                    logger.exception("failed notifying STAR referrer user=%s", user_id)

            paid_at = jdatetime.datetime.now().strftime("%Y/%m/%d - %H:%M")
            await update.message.reply_text(
                f"🎉 <b>پرداخت با موفقیت انجام شد</b>\n\n"
                f"⭐️ تعداد استارز: <b>{stars:,}</b>\n"
                f"💠 مبلغ شارژ حساب: <b>{format_amount(amount)} تومان</b>\n"
                f"🔢 کد پیگیری: <code>{tracking}</code>\n"
                f"📅 تاریخ پرداخت: <code>{paid_at}</code>",
                reply_markup=get_main_menu(), parse_mode="HTML"
            )
        except Exception:
            logger.exception("unexpected successful Telegram STAR payment error")
            await update.message.reply_text("❌ پرداخت دریافت شد، اما پردازش آن با خطا مواجه شد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())

    async def cancel_star_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        tracking = (query.data or '').rsplit('_', 1)[-1]
        if not re.fullmatch(r'[0-9a-f]{10}', tracking):
            return
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("UPDATE star_payments SET status='cancelled' WHERE user_id=%s AND payment_tracking_code=%s AND status='pending'", (update.effective_user.id, tracking))
                conn.commit(); cur.close(); conn.close()
            except Exception:
                try: cur.close(); conn.close()
                except Exception: pass
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text("❌ تراکنش استارز لغو شد.", reply_markup=get_main_menu())
        context.user_data.pop('star_payment_tracking', None)
        return ConversationHandler.END

    async def receive_stars_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if text == "/start":
            return await cancel_and_restart(update, context)
        if text in ["🔙 منوی اصلی", "🔙 منوی قبلی"]:
            await update.message.reply_text("💎 <b>شارژ حساب</b>\n\n✅ لطفاً روش پرداخت خود را انتخاب کنید:", reply_markup=get_payment_methods_keyboard(), parse_mode="HTML")
            return SELECT_PAYMENT_METHOD
        try:
            stars = int((text or '').replace(",", "").replace('٬', '').strip())
        except (TypeError, ValueError):
            await update.message.reply_text("❌ لطفاً فقط تعداد صحیح استارز را به صورت عدد وارد کنید.", reply_markup=get_back_keyboard())
            return STARS_AMOUNT_INPUT
        try:
            min_stars = int(Decimal(str(get_setting('min_stars', MIN_STARS))))
            max_stars = int(Decimal(str(get_setting('max_stars', MAX_STARS))))
        except (InvalidOperation, TypeError, ValueError):
            await update.message.reply_text("❌ تنظیمات استارز معتبر نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
            return ConversationHandler.END
        if stars < min_stars or stars > max_stars:
            await update.message.reply_text(f"❌ تعداد استارز معتبر نیست.\n\n📊 محدوده مجاز: {min_stars:,} تا {max_stars:,} استارز\n\n🔄 لطفاً مجدداً وارد کنید:", reply_markup=get_back_keyboard())
            return STARS_AMOUNT_INPUT

        star_rate = get_star_rate_toman()
        if star_rate is None:
            await update.message.reply_text("❌ نرخ استارز در بخش «مدیریت ارزها» معتبر نیست یا ارز STAR غیرفعال است.\n\nبرای جلوگیری از اختلاف مالی، پرداخت متوقف شد.", reply_markup=get_main_menu())
            return ConversationHandler.END
        amount_decimal = Decimal(stars) * star_rate
        if amount_decimal != amount_decimal.to_integral_value():
            await update.message.reply_text("❌ مبلغ قابل واریز به تومان صحیح نیست؛ تراکنش انجام نشد.", reply_markup=get_main_menu())
            return ConversationHandler.END
        amount = int(amount_decimal)
        tracking = generate_payment_tracking()
        payload = f"STAR:{update.effective_user.id}:{stars}:{int(star_rate)}:{tracking}"
        context.user_data['star_payment_tracking'] = tracking

        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ خطا در اتصال به دیتابیس. لطفاً دوباره تلاش کنید.", reply_markup=get_main_menu())
            return ConversationHandler.END
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO star_payments (user_id, stars_count, star_rate, amount_toman, payment_tracking_code, status) VALUES (%s,%s,%s,%s,%s,'pending')", (update.effective_user.id, stars, int(star_rate), amount, tracking))
            conn.commit(); cur.close(); conn.close()
        except Exception:
            try: cur.close(); conn.close()
            except Exception: pass
            logger.exception("failed creating STAR payment user=%s", update.effective_user.id)
            await update.message.reply_text("❌ ایجاد تراکنش انجام نشد. لطفاً دوباره تلاش کنید.", reply_markup=get_main_menu())
            return ConversationHandler.END

        try:
            await context.bot.send_invoice(
                chat_id=update.effective_user.id,
                title="⭐️ شارژ حساب با استارز",
                description=f"💠 مقدار شارژ حساب: {format_amount(amount)} تومان",
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice("شارژ حساب", stars)],
                provider_token="",
                start_parameter=f"star_{tracking}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐️ پرداخت با استارز", pay=True)],
                    [InlineKeyboardButton("❌ لغو تراکنش", callback_data=f"cancel_star_payment_{tracking}")]
                ])
            )
        except Exception:
            logger.exception("failed sending Telegram Stars invoice user=%s tracking=%s", update.effective_user.id, tracking)
            try:
                conn = get_db_connection(); cur = conn.cursor()
                cur.execute("UPDATE star_payments SET status='failed' WHERE payment_tracking_code=%s", (tracking,))
                conn.commit(); cur.close(); conn.close()
            except Exception:
                logger.exception("failed marking STAR invoice failed tracking=%s", tracking)
            await update.message.reply_text("❌ فاکتور استارز ارسال نشد. لطفاً دوباره تلاش کنید.", reply_markup=get_main_menu())
        return ConversationHandler.END

    async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text

        if text == "/start":
            return await cancel_and_restart(update, context)

        if text in ["🔙 منوی اصلی", "🔙 منوی قبلی"]:
            await update.message.reply_text(
                "💎 <b>شارژ حساب</b>\n\n✅ لطفاً روش پرداخت خود را انتخاب کنید:",
                reply_markup=get_payment_methods_keyboard(),
                parse_mode="HTML"
            )
            return SELECT_PAYMENT_METHOD

        try:
            amount = int(text.replace(",", "").strip())
            if get_setting('min_charge_amount', MIN_CHARGE_AMOUNT) <= amount <= get_setting('max_charge_amount', MAX_CHARGE_AMOUNT):
                context.user_data['amount'] = amount
                context.user_data['payment_tracking'] = generate_payment_tracking()
                payment_method = context.user_data.get('payment_method', '')

                if payment_method == 'card':
                    message = (
                        f"💳 مبلغ <b>{format_amount(amount)} تومان</b> به حساب زیر واریز کنید:\n\n"
                        f"<code>{CARD_NUMBER}</code>\n"
                        f"{CARD_HOLDER}\n\n"
                        f"❌ این تراکنش به مدت یک ساعت اعتبار دارد.\n\n"
                        f"‼️ مبلغ باید دقیقاً مطابق مبلغ ذکر شده باشد.\n"
                        f"‼️ مسئولیت واریز اشتباهی با شماست.\n"
                        f"🔝 بعد از پرداخت دکمه «پرداخت کردم» را زده سپس تصویر رسید را ارسال نمایید."
                    )
                    await update.message.reply_text(
                        message, 
                        reply_markup=get_card_payment_keyboard(amount), 
                        parse_mode="HTML"
                    )
                    return RECEIPT_PHOTO

                elif payment_method == 'online':
                    user = update.effective_user
                    payment_tracking = context.user_data.get('payment_tracking', '')

                    user_data = get_user_data(user.id)
                    phone_number = user_data.get('phone_number') if user_data else None

                    loading_msg = await update.message.reply_text("🔄 در حال اتصال به درگاه پرداخت...")

                    payment_result = zarinpal_request_payment(
                        amount=amount,
                        description=f"🔍 ({payment_tracking}) | 👤 ({user.id})",
                        user_id=user.id,
                        payment_tracking_code=payment_tracking,
                        mobile=phone_number
                    )

                    try:
                        await loading_msg.delete()
                    except:
                        pass

                    if payment_result["success"]:
                        context.user_data['zarinpal_authority'] = payment_result["authority"]

                        authority = payment_result['authority']
                        redirect_url = f"https://dawnpanel.ir/pay.html?authority={authority}"

                        cancel_keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("💳 رفتن به درگاه پرداخت", url=redirect_url)],
                            [InlineKeyboardButton("❌ لغو تراکنش آنلاین", callback_data="cancel_online_transaction")]
                        ])

                        await update.message.reply_text(
                            f"💸 <b>پرداخت آنلاین</b>\n\n"
                            f"💰 مبلغ: {format_amount(amount)} تومان\n"
                            f"🔢 کد پیگیری: <code>{payment_tracking}</code>\n\n"
                            f"🔗 برای پرداخت روی دکمه زیر کلیک کنید 👇\n\n"
                            f"━━━━━━━━━━━━━━━━\n"
                            f"🚫 <b>هشدار مهم:</b>\n"
                            f"• اگر با <b>فیلترشکن</b> متصل هستید، لطفاً آن را <b>خاموش</b> کنید\n"
                            f"• سپس وارد درگاه بانکی شوید\n"
                            f"• یا از <b>پروکسی تلگرام</b> استفاده نمایید\n"
                            f"━━━━━━━━━━━━━━━━\n\n"
                            f"⚠️ <b>برای لغو این تراکنش، روی دکمه «❌ لغو تراکنش آنلاین» کلیک کنید.</b>\n\n"
                            f"✅ پس از پرداخت موفق، موجودی شما به صورت خودکار شارژ خواهد شد.\n\n"
                            f"⚠️ در صورتی که موجودی شما به‌صورت خودکار شارژ نشد، با پشتیبانی تماس بگیرید:\n"
                            f"🆔 {SUPPORT_USERNAME}",
                            reply_markup=cancel_keyboard,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )

                        rules_text = (
                            f"⚠️ <b>#مهم</b> (این نکات رعایت نشود بلافاصله مسدود می‌شوید) ❗️\n\n"
                            f"1️⃣ بعد از شارژ حساب در صورت نیاز احراز هویت گرفته می‌شود. پس پول هک شده و فیشینگ نزنید.\n\n"
                            f"2️⃣ شارژ حساب با ارز دیجیتال نیاز به احراز هویت ندارد. جهت دریافت ولت به پشتیبانی مراجعه کنید.\n\n"
                            f"3️⃣ از کارت‌های هدیه جهت شارژ حساب استفاده نکنید.\n\n"
                            f"4️⃣ اتباع خارجی اجازه پرداخت با ریال را ندارند.\n\n"
                            f"5️⃣ فقط با یک کارت ثابت خرید بزنید و از چند کارت استفاده نکنید چون بلافاصله مسدود می‌شوید. کارت فقط برای خودتان یا یکی از فامیل درجه یک باشد به صورتی که کارت در اختیارتان باشد.\n\n"
                            f"💰 واریزها و مبالغ در ربات به صورت <b>تومان</b> می‌باشد ❗️\n\n"
                            f"⚠️ جهت شارژ حساب در ربات به <b>پروکسی</b> متصل شوید یا هنگام ورود به درگاه فیلترشکن را خاموش کنید ❗️\n"
                            f"فیلترشکن باعث می‌شود تراکنش ناموفق شود و پنل شارژ نشود ❌\n\n"
                            f"📮 <a href='{RULES_LINK}'>قوانین استفاده از ربات</a>\n"
                            f"📋 <a href='{ORDER_RULES_LINK}'>قوانین ثبت سفارش</a>"
                        )

                        await update.message.reply_text(
                            rules_text,
                            reply_markup=get_main_menu(),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )

                        context.user_data.pop('payment_method', None)
                        context.user_data.pop('amount', None)
                        return ConversationHandler.END
                    else:
                        await update.message.reply_text(
                            f"❌ {payment_result['error']}\n\n"
                            f"🔄 لطفاً مجدداً تلاش کنید یا از روش پرداخت دیگری استفاده کنید.",
                            reply_markup=get_payment_methods_keyboard()
                        )
                        return SELECT_PAYMENT_METHOD

            await update.message.reply_text(
                f"❌ مبلغ وارد شده معتبر نیست.\n\n"
                f"💰 حداقل: {format_amount(get_setting('min_charge_amount', MIN_CHARGE_AMOUNT))} تومان\n"
                f"💰 حداکثر: {format_amount(get_setting('max_charge_amount', MAX_CHARGE_AMOUNT))} تومان\n\n"
                f"🔄 لطفاً مجدداً وارد کنید:",
                reply_markup=get_back_keyboard(),
                parse_mode="HTML"
            )
            return AMOUNT_INPUT
        except:
            await update.message.reply_text(
                "❌ لطفاً فقط عدد وارد کنید.", 
                reply_markup=get_back_keyboard()
            )
            return AMOUNT_INPUT

    async def receive_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text if update.message.text else ""

        if text == "/start":
            return await cancel_and_restart(update, context)

        if text == "🔙 منوی اصلی":
            context.user_data.pop('waiting_for_receipt_photo', None)
            await update.message.reply_text(
                "👈 به منوی اصلی بازگشتید.\n📋 یکی از گزینه‌ها را انتخاب کنید:", 
                reply_markup=get_main_menu(), 
                parse_mode="HTML"
            )
            return ConversationHandler.END

        if text == "🔙 منوی قبلی":
            amount = context.user_data.get('amount', 0)
            await update.message.reply_text(
                f"💳 مبلغ <b>{format_amount(amount)} تومان</b>\n\n<code>{CARD_NUMBER}</code>\n{CARD_HOLDER}",
                reply_markup=get_card_payment_keyboard(amount),
                parse_mode="HTML"
            )
            return RECEIPT_PHOTO

        if not context.user_data.get('waiting_for_receipt_photo'):
            await update.message.reply_text(
                "❌ ابتدا دکمه «پرداخت کردم» را بزنید.", 
                reply_markup=get_receipt_waiting_keyboard(), 
                parse_mode="HTML"
            )
            return RECEIPT_PHOTO

        photo_id, is_valid, is_photo = None, False, False
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
            is_valid = True
            is_photo = True
        elif update.message.document:
            doc = update.message.document
            mime_type = doc.mime_type or ""
            file_name = doc.file_name.lower() if doc.file_name else ""
            if mime_type in ['image/jpeg', 'image/png', 'image/jpg', 'image/webp', 'image/bmp'] or any(file_name.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']):
                photo_id = doc.file_id
                is_valid = True
                is_photo = False

        if not is_valid:
            await update.message.reply_text(
                "❌ فقط عکس (JPG, PNG).", 
                reply_markup=get_receipt_waiting_keyboard()
            )
            return RECEIPT_PHOTO

        user = update.effective_user
        amount = context.user_data.get('amount', 0)
        payment_tracking = context.user_data.get('payment_tracking', '')
        receipt_id = save_receipt(user.id, amount, photo_id, payment_tracking, context.user_data.get('payment_method', 'card'))
        context.user_data.pop('waiting_for_receipt_photo', None)

        for admin_id in ADMIN_IDS:
            try:
                safe_name = html.escape(str(user.full_name or '-'))
                safe_username = '@' + html.escape(str(user.username).lstrip('@')) if user.username else 'ندارد'
                caption = (
                    f"📸 رسید جدید\n\n"
                    f"🆔 #{receipt_id}\n"
                    f"👤 {safe_name}\n"
                    f"🔹 یوزرنیم: {safe_username}\n"
                    f"🔢 آیدی عددی: <code>{user.id}</code>\n"
                    f"💰 {format_amount(amount)} تومان\n"
                    f"🛒 <code>{payment_tracking}</code>"
                )
                if is_photo:
                    await context.bot.send_photo(
                        admin_id, photo=photo_id, caption=caption, 
                        reply_markup=get_admin_action_keyboard(user.id, amount, receipt_id, payment_tracking), 
                        parse_mode="HTML"
                    )
                else:
                    await context.bot.send_document(
                        admin_id, document=photo_id, caption=caption, 
                        reply_markup=get_admin_action_keyboard(user.id, amount, receipt_id, payment_tracking), 
                        parse_mode="HTML"
                    )
            except: pass

        await update.message.reply_text(
            "✅ رسید با موفقیت ارسال شد.\n\n📝 پس از بررسی توسط ادمین، موجودی شما شارژ خواهد شد.", 
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END

    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💳 شارژ حساب$"), start_charge)],
        states={
            PHONE_NUMBER_INPUT: [
                MessageHandler(filters.CONTACT, receive_phone_number),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone_number)
            ],
            VERIFICATION_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, verify_code)
            ],
            SELECT_PAYMENT_METHOD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_payment_method)
            ],
            STARS_AMOUNT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_stars_amount)
            ],
            AMOUNT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)
            ],
            RECEIPT_PHOTO: [
                MessageHandler(filters.PHOTO, receive_receipt_photo),
                MessageHandler(filters.Document.ALL, receive_receipt_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_receipt_photo)
            ],
        },
        fallbacks=[
            CommandHandler("start", cancel_and_restart),
            CommandHandler("cancel", cancel_operation),
            CallbackQueryHandler(cancel_admin_input_callback, pattern="^acancel_input$"),
            CallbackQueryHandler(handle_admin_panel, pattern="^adirect_(cancel|back)$")
        ],
        per_message=False
    )

async def resend_verification_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال مجدد کد فقط در صورت فعال بودن واقعی فرایند احراز هویت."""
    query = update.callback_query
    user_id = query.from_user.id

    user_data = get_user_data(user_id)
    if user_data and user_data.get('is_verified'):
        context.user_data.pop('verification_in_progress', None)
        try: await query.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await query.answer("✅ شماره شما قبلاً احراز شده است.", show_alert=True)
        return

    if not context.user_data.get('verification_in_progress'):
        try: await query.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await query.answer("⌛️ این درخواست دیگر معتبر نیست. لطفاً از «💳 شارژ حساب» دوباره فرایند احراز را شروع کنید.", show_alert=True)
        return

    state = get_phone_verification_state(user_id)
    phone = str((state or {}).get('phone_number') or '').strip()
    if not phone:
        context.user_data.pop('verification_in_progress', None)
        try: await query.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        await query.answer("❌ شماره‌ای برای ارسال مجدد پیدا نشد.", show_alert=True)
        return

    verification = request_phone_verification_code(user_id, phone, force_new=True)
    status = verification.get('status') if verification else 'error'
    if status == 'limit':
        await query.answer(f"🚫 سقف ارسال روزانه ({SMS_DAILY_LIMIT} پیامک) تکمیل شده است.", show_alert=True); return
    if status == 'cooldown':
        remaining=max(1,int(verification.get('remaining',SMS_RESEND_COOLDOWN_SECONDS))); minutes,seconds=divmod(remaining,60)
        time_text=f"{minutes} دقیقه و {seconds} ثانیه" if minutes else f"{seconds} ثانیه"
        await query.answer(f"⏳ لطفاً {time_text} دیگر صبر کنید و سپس دوباره درخواست کد بدهید.", show_alert=True); return
    if status == 'sent':
        context.user_data['verification_code']=verification.get('code','')
        context.user_data['verification_in_progress']=True
        context.user_data['verification_message_id']=query.message.message_id
        context.user_data['verification_chat_id']=query.message.chat_id
        msg="📩 یک کد تأیید ۶ رقمی به شماره شما ارسال شد.\n\n👈 لطفاً کد ۶ رقمی را وارد کنید:"
        try: await query.edit_message_text(msg, parse_mode="HTML", reply_markup=None)
        except Exception: pass
        await query.answer("✅ کد جدید ارسال شد."); return
    await query.answer("❌ ارسال کد جدید انجام نشد. دوباره تلاش کنید.", show_alert=True)

async def precheckout_star_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اعتبارسنجی فاکتور قبل از نهایی شدن پرداخت Telegram Stars."""
    query = update.pre_checkout_query
    try:
        parts = (query.invoice_payload or '').split(':')
        if len(parts) != 5 or parts[0] != 'STAR':
            await query.answer(ok=False, error_message="❌ اطلاعات فاکتور معتبر نیست.")
            return
        user_id = int(parts[1])
        stars = int(parts[2])
        rate = int(parts[3])
        tracking = parts[4]
        if user_id != query.from_user.id or stars <= 0 or rate <= 0 or not re.fullmatch(r'[0-9a-f]{10}', tracking):
            await query.answer(ok=False, error_message="❌ اطلاعات پرداخت معتبر نیست.")
            return
        if query.currency != 'XTR' or int(query.total_amount) != stars:
            await query.answer(ok=False, error_message="❌ مبلغ فاکتور با درخواست شما مطابقت ندارد.")
            return

        conn = get_db_connection()
        if not conn:
            await query.answer(ok=False, error_message="❌ خطای موقت سرور. لطفاً دوباره تلاش کنید.")
            return
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT status, user_id, stars_count, star_rate, amount_toman FROM star_payments WHERE payment_tracking_code=%s LIMIT 1", (tracking,))
            row = cur.fetchone()
            if not row or int(row['user_id']) != user_id or row['status'] != 'pending':
                await query.answer(ok=False, error_message="❌ این تراکنش دیگر معتبر نیست.")
                return
            if int(row['stars_count']) != stars or int(row['star_rate']) != rate:
                await query.answer(ok=False, error_message="❌ اطلاعات نرخ این تراکنش تغییر کرده است.")
                return
            expected_amount = stars * rate
            if int(row['amount_toman']) != expected_amount:
                await query.answer(ok=False, error_message="❌ مبلغ شارژ معتبر نیست.")
                return
        finally:
            try: cur.close(); conn.close()
            except Exception: pass

        await query.answer(ok=True)
    except Exception:
        logger.exception("STAR pre-checkout validation failed")
        try:
            await query.answer(ok=False, error_message="❌ خطا در بررسی پرداخت. لطفاً دوباره تلاش کنید.")
        except Exception:
            pass

async def successful_star_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بعد از پرداخت موفق Telegram Stars، مبلغ دقیق محاسبه‌شده را فقط یک‌بار واریز می‌کند."""
    payment = update.message.successful_payment
    if not payment:
        return
    try:
        parts = (payment.invoice_payload or '').split(':')
        if len(parts) != 5 or parts[0] != 'STAR':
            logger.error("invalid STAR successful payment payload")
            return
        user_id = int(parts[1])
        stars = int(parts[2])
        rate = int(parts[3])
        tracking = parts[4]
        if user_id != update.effective_user.id or payment.currency != 'XTR' or int(payment.total_amount) != stars:
            logger.error("invalid STAR payment values user=%s tracking=%s", user_id, tracking)
            await update.message.reply_text("❌ پرداخت دریافت شد اما اطلاعات آن معتبر نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
            return

        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ پرداخت دریافت شد، اما اتصال به دیتابیس برقرار نشد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
            return

        amount = 0
        already_paid = False
        try:
            conn.start_transaction()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM star_payments WHERE payment_tracking_code=%s FOR UPDATE", (tracking,))
            row = cur.fetchone()
            if not row or int(row['user_id']) != user_id:
                conn.rollback()
                await update.message.reply_text("❌ تراکنش پیدا نشد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                return

            if row['status'] == 'credited':
                already_paid = True
                amount = int(row['amount_toman'])
                conn.commit()
            elif row['status'] != 'pending':
                conn.rollback()
                await update.message.reply_text("❌ وضعیت این تراکنش قابل پردازش نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                return
            else:
                if int(row['stars_count']) != stars or int(row['star_rate']) != rate:
                    conn.rollback()
                    await update.message.reply_text("❌ اطلاعات پرداخت با فاکتور مطابقت ندارد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                    return
                amount = stars * rate
                if amount != int(row['amount_toman']):
                    conn.rollback()
                    await update.message.reply_text("❌ مبلغ پرداختی قابل تأیید نیست. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
                    return

                cur.execute("""UPDATE users SET balance=balance+%s, total_payments=total_payments+%s WHERE user_id=%s""", (amount, amount, user_id))
                if cur.rowcount != 1:
                    raise RuntimeError("user balance row not found")
                cur.execute("""INSERT INTO transactions (user_id, amount, type, description, payment_tracking_code, status) VALUES (%s,%s,'deposit',%s,%s,'completed')""", (user_id, amount, f'شارژ با Telegram Stars - {stars} استارز معادل {format_amount(amount)} تومان (نرخ: {format_amount(rate)})', tracking))
                cur.execute("""UPDATE star_payments SET status='credited', telegram_payment_charge_id=%s, provider_payment_charge_id=%s, paid_at=NOW() WHERE id=%s""", (payment.telegram_payment_charge_id, payment.provider_payment_charge_id, row['id']))
                conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
            logger.exception("failed crediting Telegram STAR payment user=%s tracking=%s", user_id, tracking)
            await update.message.reply_text("❌ پرداخت شما دریافت شد اما واریز موجودی با خطا مواجه شد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())
            return
        finally:
            try: cur.close(); conn.close()
            except Exception: pass

        if already_paid:
            await update.message.reply_text(f"ℹ️ این پرداخت قبلاً ثبت شده است.\n\n💠 موجودی ثبت‌شده: {format_amount(amount)} تومان", reply_markup=get_main_menu())
            return

        commission_info = add_commission_to_referrer(user_id, amount)
        if commission_info:
            try:
                await context.bot.send_message(
                    commission_info['referrer_id'],
                    f"🥳 تبریک!\n👥 {commission_info['referred_name']} مقدار {format_amount(commission_info['charge_amount'])} تومان با استارز شارژ کرد و {format_amount(commission_info['commission'])} پورسانت واریز شد.",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("failed notifying STAR referrer user=%s", user_id)

        await update.message.reply_text(
            f"🎉 <b>پرداخت با موفقیت انجام شد</b>\n\n"
            f"⭐️ استارز پرداخت‌شده: {stars:,}\n"
            f"💠 موجودی اضافه‌شده: <b>{format_amount(amount)} تومان</b>\n"
            f"📊 نرخ: هر استارز = {format_amount(rate)} تومان\n"
            f"🔢 کد پیگیری: <code>{tracking}</code>",
            reply_markup=get_main_menu(), parse_mode="HTML"
        )
    except Exception:
        logger.exception("unexpected successful Telegram STAR payment error")
        await update.message.reply_text("❌ پرداخت دریافت شد، اما پردازش آن با خطا مواجه شد. لطفاً با پشتیبانی تماس بگیرید.", reply_markup=get_main_menu())

async def cancel_star_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tracking = context.user_data.get('star_payment_tracking')
    # در حالت عادی tracking داخل callback نیست؛ از پیام invoice استخراج نمی‌شود.
    # بنابراین فقط وضعیت تمام تراکنش‌های pending کاربر را لغو می‌کنیم.
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("UPDATE star_payments SET status='cancelled' WHERE user_id=%s AND status='pending'", (update.effective_user.id,))
            conn.commit(); cur.close(); conn.close()
        except Exception:
            try: cur.close(); conn.close()
            except Exception: pass
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await query.message.reply_text("❌ تراکنش استارز لغو شد.", reply_markup=get_main_menu())
    context.user_data.pop('star_payment_tracking', None)
    return ConversationHandler.END


# ==================== افزایش موجودی ====================
async def increase_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    is_banned, _ = is_user_banned(update.effective_user.id)
    if is_banned: return

    active_transaction = get_active_zarinpal_transaction(update.effective_user.id)
    if active_transaction:
        message = (
            f"⚠️ <b>شما یک تراکنش آنلاین در انتظار دارید!</b>\n\n"
            f"💰 مبلغ: {format_amount(active_transaction['amount'])} تومان\n"
            f"🔢 کد پیگیری: <code>{active_transaction['payment_tracking_code']}</code>\n\n"
            f"❌ تا زمان اتمام این تراکنش، امکان ایجاد تراکنش جدید وجود ندارد."
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=message,
            reply_markup=get_cancel_transaction_keyboard(),
            parse_mode="HTML"
        )
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="📋 منوی اصلی:",
            reply_markup=get_main_menu()
        )
        return

    user_data = get_user_data(update.effective_user.id)
    if user_data and (not setting_enabled('require_verification', True) or (user_data['phone_number'] and user_data['is_verified'])):
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="💸 مبلغ را وارد کنید:",
            reply_markup=get_back_keyboard()
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="📱 شماره خود را به اشتراک بگذارید:",
            reply_markup=get_share_contact_reply_keyboard(),
            parse_mode="HTML"
        )

# ==================== مدیریت ادمین (شارژ) ====================
def format_admin_charge_success(user_id, amount, tracking_code):
    user_data = get_user_data(user_id) or {}
    name = html.escape(str(user_data.get('full_name') or '-'))
    username = ('@' + html.escape(str(user_data.get('username')).lstrip('@'))) if user_data.get('username') else 'ندارد'
    new_balance = int(user_data.get('balance') or 0)
    paid_at = datetime.now().strftime("%Y-%m-%d - %H:%M")
    return (
        "✅ <b>شارژ انجام شد</b>\n\n"
        f"💰 مبلغ اضافه‌شده: <b>{format_amount(amount)} تومان</b>\n"
        f"👤 کاربر: {name}\n"
        f"🔹 یوزرنیم: {username}\n"
        f"🆔 آیدی عددی: <code>{int(user_id)}</code>\n"
        f"💎 موجودی جدید: <b>{format_amount(new_balance)} تومان</b>\n"
        f"🛒 کد پیگیری: <code>{html.escape(str(tracking_code or '-'))}</code>\n"
        f"📅 تاریخ: <code>{paid_at}</code>"
    )

def create_admin_handler():
    async def admin_quick_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        parts = query.data.split("_")
        uid, amount, rid, pt = int(parts[1]), int(parts[2]), int(parts[3]), parts[4]

        # Claim the receipt first. This makes repeated/double clicks harmless.
        if not claim_receipt(rid, 'processing', update.effective_user.id):
            try: await query.edit_message_reply_markup(reply_markup=None)
            except Exception: pass
            await query.message.reply_text("⚠️ این رسید قبلاً پردازش شده و امکان شارژ مجدد ندارد.")
            return ConversationHandler.END

        # Remove the action buttons immediately so the admin cannot click again.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        try:
            if not update_user_balance(uid, amount):
                update_receipt_status(rid, 'pending', None, None, None)
                await query.message.reply_text("❌ شارژ انجام نشد؛ لطفاً دوباره بررسی کنید.")
                return ConversationHandler.END
            update_receipt_status(rid, 'approved', update.effective_user.id, amount)
            save_transaction(uid, amount, 'deposit', f'شارژ سریع - {format_amount(amount)} تومان', pt)
            commission_info = add_commission_to_referrer(uid, amount)

            try:
                await context.bot.send_message(uid, f"🎉 شارژ موفق\n\n💎 {format_amount(amount)} تومان واریز شد.\n🛒 <code>{pt}</code>", parse_mode="HTML")
            except Exception: pass
            if commission_info:
                try:
                    await context.bot.send_message(
                        commission_info['referrer_id'],
                        f"🥳 تبریک!\n👥 {commission_info['referred_name']} مقدار {format_amount(commission_info['charge_amount'])} تومان شارژ کرد و {format_amount(commission_info['commission'])} پورسانت واریز شد.",
                        parse_mode="HTML"
                    )
                except Exception: pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=format_admin_charge_success(uid, amount, pt),
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("quick charge failed receipt=%s", rid)
        return ConversationHandler.END

    async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        parts = query.data.split("_")
        receipt_id = int(parts[3])
        receipt = get_receipt_by_id(receipt_id)
        if not receipt or str(receipt.get('status') or '').lower() != 'pending':
            await query.answer("⚠️ این رسید قبلاً پردازش شده است.", show_alert=True)
            try: await query.edit_message_reply_markup(reply_markup=None)
            except Exception: pass
            return ConversationHandler.END
        context.user_data.update({
            'target_user_id': int(parts[1]),
            'declared_amount': int(parts[2]),
            'receipt_id': receipt_id,
            'admin_input_chat_id': query.message.chat_id,
            'admin_input_message_id': query.message.message_id
        })
        prompt_text = f"💰 مبلغ اعلامی: {format_amount(int(parts[2]))} تومان\n\n👈 مبلغ شارژ را وارد کنید:"
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_receipt_back_{receipt_id}")]])
        try: await query.edit_message_reply_markup(reply_markup=back_markup)
        except Exception: pass
        await query.message.reply_text(prompt_text, reply_markup=back_markup)
        return ADMIN_AMOUNT_INPUT

    async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        parts = query.data.split("_")
        receipt_id = int(parts[3])
        receipt = get_receipt_by_id(receipt_id)
        if not receipt or str(receipt.get('status') or '').lower() != 'pending':
            await query.answer("⚠️ این رسید قبلاً پردازش شده است.", show_alert=True)
            try: await query.edit_message_reply_markup(reply_markup=None)
            except Exception: pass
            return ConversationHandler.END
        context.user_data.update({
            'target_user_id': int(parts[1]),
            'declared_amount': int(parts[2]),
            'receipt_id': receipt_id,
            'admin_input_chat_id': query.message.chat_id,
            'admin_input_message_id': query.message.message_id
        })
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_receipt_back_{receipt_id}")]])
        try: await query.edit_message_reply_markup(reply_markup=back_markup)
        except Exception: pass
        await query.message.reply_text(
            f"❌ لغو شارژ\n💰 {format_amount(int(parts[2]))} تومان\n\n👈 دلیل را وارد کنید:",
            reply_markup=back_markup
        )
        return ADMIN_REJECT_REASON

    async def receive_admin_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text

        if text in ["/start", "/cancel"]:
            return await cancel_operation(update, context)

        try:
            amount = int(text.replace(",", "").strip())
            uid = context.user_data.get('target_user_id')
            rid = context.user_data.get('receipt_id')
            if amount <= 0:
                await update.message.reply_text("❌ > 0")
                return ADMIN_AMOUNT_INPUT

            update_user_balance(uid, amount)
            receipt = get_receipt_by_id(rid)
            pt = receipt['payment_tracking_code'] if receipt else generate_payment_tracking()
            update_receipt_status(rid, 'approved', update.effective_user.id, amount)
            save_transaction(uid, amount, 'deposit', f'شارژ دستی - {format_amount(amount)} تومان', pt)
            commission_info = add_commission_to_referrer(uid, amount)

            try:
                await context.bot.send_message(
                    uid, 
                    f"🎉 شارژ موفق\n\n💎 {format_amount(amount)} تومان واریز شد.\n🛒 <code>{pt}</code>", 
                    parse_mode="HTML"
                )
                if commission_info:
                    try: 
                        await context.bot.send_message(
                            commission_info['referrer_id'], 
                            f"🥳 تبریک!\n👥 {commission_info['referred_name']} مقدار {format_amount(commission_info['charge_amount'])} تومان شارژ کرد و {format_amount(commission_info['commission'])} پورسانت واریز شد.", 
                            parse_mode="HTML"
                        )
                    except: pass
                await update.message.reply_text(
                    format_admin_charge_success(uid, amount, pt),
                    parse_mode="HTML"
                )
            except: pass
            return ConversationHandler.END
        except:
            await update.message.reply_text("❌ عدد وارد کنید:")
            return ADMIN_AMOUNT_INPUT

    async def receive_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text

        if text in ["/start", "/cancel"]:
            return await cancel_operation(update, context)

        reason = text
        uid = context.user_data.get('target_user_id')
        rid = context.user_data.get('receipt_id')
        receipt = get_receipt_by_id(rid)
        pt = receipt['payment_tracking_code'] if receipt else ''
        update_receipt_status(rid, 'rejected', update.effective_user.id, reject_reason=reason)
        try: 
            await context.bot.send_message(
                uid, 
                f"❌ پرداخت رد شد.\n\n"
                f"✍️ دلیل: {reason}\n"
                f"🛒 <code>{pt}</code>\n"
                f"🆔 {SUPPORT_USERNAME}\n\n"
                f"📞 در صورت مشکل با پشتیبانی تماس بگیرید.", 
                parse_mode="HTML"
            )
        except: pass
        await update.message.reply_text(f"❌ لغو شد\n📝 {reason}")
        return ConversationHandler.END

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_quick_charge, pattern="^quickcharge_"),
            CallbackQueryHandler(admin_approve, pattern="^approve_"),
            CallbackQueryHandler(admin_reject, pattern="^reject_")
        ],
        states={
            ADMIN_AMOUNT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_amount)
            ],
            ADMIN_REJECT_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_reject_reason)
            ]
        },
        fallbacks=[
            CommandHandler("start", cancel_and_restart),
            CommandHandler("cancel", cancel_operation),
            CallbackQueryHandler(cancel_admin_input_callback, pattern="^acancel_input$"),
            CallbackQueryHandler(admin_receipt_back, pattern="^admin_receipt_back_[0-9]+$")
        ],
        per_message=False
    )

async def _edit_support_prompt(query, text):
    """ویرایش همان پیام درخواست پاسخ به‌جای ارسال پیام جدید."""
    try:
        await query.edit_message_text(text, parse_mode="HTML")
        return True
    except Exception as exc:
        logger.warning("Could not edit support prompt: %s", exc)
        return False


# ==================== پنل ادمین ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /panel فقط برای ADMIN_IDS است؛ برای سایر کاربران کاملاً بی‌پاسخ باشد.
    if update.effective_user.id not in ADMIN_IDS:
        logger.warning("unauthorized /panel attempt user=%s", update.effective_user.id)
        return

    # پاک کردن تمام state های قبلی
    await reset_user_state(update, context)

    stats = get_total_stats()
    message = (
        "🎛 <b>پنل مدیریت دان پنل</b>\n"
        "━━━━━━━━━━━━━━\n"
        "👥 <b>کاربران</b>\n"
        f"▫️ کل: <b>{stats.get('total_users', 0):,}</b>  •  🚫 بن: <b>{stats.get('banned_users', 0):,}</b>  •  🚫 بلاک: <b>{stats.get('blocked_users', 0):,}</b>\n"
        f"💰 موجودی کل: <b>{format_amount(stats.get('total_balance', 0))} تومان</b>\n"
        "━━━━━━━━━━━━━━\n"
        "📦 <b>سفارش‌ها</b>\n"
        f"▫️ کل: <b>{stats.get('total_orders', 0):,}</b>  •  ⏳ <b>{stats.get('pending_orders', 0):,}</b>  •  🎉 <b>{stats.get('completed_orders', 0):,}</b>  •  ❌ <b>{stats.get('cancelled_orders', 0):,}</b>\n"
        f"📅 امروز: <b>{stats.get('orders_today', 0):,}</b> سفارش | {format_amount(stats.get('sales_today', 0))} تومان\n"
        f"📆 هفته: <b>{stats.get('orders_week', 0):,}</b> سفارش | {format_amount(stats.get('sales_week', 0))} تومان\n"
        f"🗓 ماه: <b>{stats.get('orders_month', 0):,}</b> سفارش | {format_amount(stats.get('sales_month', 0))} تومان\n"
        "━━━━━━━━━━━━━━\n"
        "💎 <b>واریزی‌ها</b>\n"
        f"▫️ کل: <b>{format_amount(stats.get('total_deposits', 0))} تومان</b>\n"
        f"▫️ امروز: <b>{format_amount(stats.get('deposits_today', 0))} تومان</b> ({stats.get('deposit_count_today', 0):,})\n"
        f"▫️ هفته: <b>{format_amount(stats.get('deposits_week', 0))} تومان</b> ({stats.get('deposit_count_week', 0):,})\n"
        f"▫️ ماه: <b>{format_amount(stats.get('deposits_month', 0))} تومان</b> ({stats.get('deposit_count_month', 0):,})\n"
        "━━━━━━━━━━━━━━\n"
        "📸 <b>رسیدهای در انتظار</b>\n"
        f"▫️ <b>{stats.get('pending_receipts', 0):,}</b>\n"
        "━━━━━━━━━━━━━━\n"
        "📈 <b>سود</b>\n"
        f"▫️ امروز: <b>{format_amount(stats.get('profit_today', 0))} تومان</b>\n"
        f"▫️ هفته: <b>{format_amount(stats.get('profit_week', 0))} تومان</b>\n"
        f"▫️ ماه: <b>{format_amount(stats.get('profit_month', 0))} تومان</b>\n"
        "👇 <b>یک بخش را برای مدیریت انتخاب کنید:</b>"
    )
    await update.message.reply_text(
        message,
        reply_markup=get_admin_panel_keyboard(),
        parse_mode="HTML"
    )


def _get_category_products_add_keyboard(category_id):
    products = get_category_products(category_id) or []
    keyboard = []
    row = []

    for product in products:
        if isinstance(product, dict):
            product_id = product.get("id")
            name = product.get("name", "")
        else:
            product_id = product[0]
            name = product[2] if len(product) > 2 else product[1]

        if product_id is None:
            continue

        row.append(
            InlineKeyboardButton(
                str(name),
                callback_data=f"show_add_product_{int(product_id)}"
            )
        )

        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    return InlineKeyboardMarkup(keyboard) if keyboard else None


def _get_add_product_category_keyboard(category_id):
    product_kb = _get_category_products_add_keyboard(category_id)
    rows = []

    if product_kb and getattr(product_kb, "inline_keyboard", None):
        rows.extend(product_kb.inline_keyboard)

    rows.append([
        InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_products")
    ])
    return InlineKeyboardMarkup(rows)


def _get_product_add_alert_text(product):
    if isinstance(product, dict):
        name = product.get("name", "")
        price = product.get("price", 0)
        min_order = product.get("min_order", 1)
        max_order = product.get("max_order")
    else:
        name = product[2] if len(product) > 2 else ""
        price = int(calculate_price_info(product)['price']) if product else 0
        min_order = product[6] if len(product) > 6 else 1
        max_order = product[7] if len(product) > 7 else None

    def fmt(value):
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    max_text = "نامحدود" if max_order in (None, "", 0) else fmt(max_order)

    return (
        f"📦 {name}\n\n"
        f"💰 قیمت: {fmt(price)} تومان\n"
        f"⬇️ حداقل خرید: {fmt(min_order)}\n"
        f"⬆️ حداکثر خرید: {max_text}"
    )


def find_user_for_direct_message(value):
    """یافتن کاربر برای پیام مستقیم با آیدی عددی یا username."""
    value = (value or '').strip().lstrip('@')
    if not value:
        return None
    conn = get_db_connection()
    if not conn:
        return None
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        if value.isdigit():
            cur.execute("SELECT user_id, full_name, username FROM users WHERE user_id=%s LIMIT 1", (int(value),))
        else:
            cur.execute("SELECT user_id, full_name, username FROM users WHERE LOWER(username)=LOWER(%s) LIMIT 1", (value,))
        return cur.fetchone()
    except Exception:
        logger.exception("failed finding direct-message user value=%s", value)
        return None
    finally:
        try:
            if cur: cur.close()
            conn.close()
        except Exception:
            pass

async def handle_direct_message_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or '').strip()
    if value in ('/cancel', '/start'):
        return await cancel_operation(update, context)

    user = find_user_for_direct_message(value)
    if not user:
        await update.message.reply_text(
            "❌ کاربر پیدا نشد. آیدی عددی یا username معتبر وارد کن."
        )
        return

    context.user_data['reply_to_user_id'] = int(user['user_id'])
    context.user_data['waiting_for_reply'] = True
    context.user_data['direct_message_mode'] = True

    name = html.escape(str(user.get('full_name') or '-'))
    username = ('@' + str(user.get('username')).lstrip('@')) if user.get('username') else 'بدون یوزرنیم'

    prompt = (
        f"📨 <b>پیام مستقیم به کاربر</b>\n\n"
        f"👤 {name}\n"
        f"🆔 <code>{int(user['user_id'])}</code>\n"
        f"🔹 {html.escape(username)}\n\n"
        "حالا پیام، عکس، فایل یا هر محتوایی که می‌خواهی برای همین کاربر ارسال شود را بفرست."
    )

    edited = await _edit_admin_input_prompt(
        context,
        prompt,
        reply_markup=get_direct_message_input_keyboard(True),
        parse_mode="HTML"
    )
    if not edited:
        await update.message.reply_text(
            prompt,
            reply_markup=get_direct_message_input_keyboard(True),
            parse_mode="HTML"
        )

    context.user_data.pop('admin_state', None)
    return ConversationHandler.END


async def handle_admin_order_cancel_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return ConversationHandler.END
    reason = (update.effective_message.text or '').strip()
    if reason in ('/cancel', '/start'):
        return await cancel_operation(update, context)
    order_id = context.user_data.get('cancel_order_id')
    if not order_id:
        await update.message.reply_text('❌ سفارش برای لغو پیدا نشد.')
        context.user_data.pop('admin_state', None)
        return ConversationHandler.END
    order = get_order(int(order_id))
    if not order:
        await update.message.reply_text('❌ سفارش پیدا نشد.')
        context.user_data.pop('admin_state', None)
        return ConversationHandler.END
    if order[9] in ('cancelled', 'completed'):
        await update.message.reply_text('⚠️ این سفارش قبلاً نهایی شده است.')
        context.user_data.pop('admin_state', None)
        context.user_data.pop('cancel_order_id', None)
        return ConversationHandler.END
    try:
        amount = int(order[8] or 0)
        if not await asyncio.to_thread(integration.transition,int(order_id),'cancelled',reason):
            await update.message.reply_text('این سفارش قبلاً نهایی شده است.')
            return ConversationHandler.END
        user_text = (
            f"❌ <b>سفارش شما لغو شد.</b>\n\n"
            f"🆔 <b>#{order_id}</b>\n"
            f"📦 {html.escape(str(order[4] or '-'))}\n"
            f"💰 مبلغ برگشتی: <b>{format_amount(amount)} تومان</b>\n\n"
            f"📝 <b>دلیل لغو:</b>\n{html.escape(reason)}"
        )
        if int(order[2])>0:
            await context.bot.send_message(chat_id=order[2], text=user_text, parse_mode='HTML')
        await update.message.reply_text(f"✅ سفارش #{order_id} لغو شد و {format_amount(amount)} تومان به موجودی کاربر برگشت.")
    except Exception:
        logger.exception('failed cancelling order with reason order=%s admin=%s', order_id, update.effective_user.id)
        await update.message.reply_text('❌ لغو سفارش انجام نشد؛ موجودی کاربر را دوباره بررسی کن.')
    finally:
        context.user_data.pop('admin_state', None)
        context.user_data.pop('cancel_order_id', None)
    return ConversationHandler.END


async def handle_admin_order_completion_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return ConversationHandler.END
    order_id = context.user_data.get('complete_order_id')
    if not order_id:
        await update.message.reply_text('❌ سفارش برای تکمیل پیدا نشد.')
        return ConversationHandler.END
    order = get_order(int(order_id))
    if not order:
        await update.message.reply_text('❌ سفارش پیدا نشد.')
        return ConversationHandler.END
    if order[9] in ('cancelled', 'completed'):
        await update.message.reply_text('⚠️ این سفارش قبلاً نهایی شده است.')
        context.user_data.pop('admin_state', None)
        context.user_data.pop('complete_order_id', None)
        return ConversationHandler.END
    try:
        msg = update.effective_message
        note=(msg.text or msg.caption or 'مشخصات در تلگرام ارسال شد.').strip()
        if not await asyncio.to_thread(integration.transition,int(order_id),'completed',note):
            await update.message.reply_text('این سفارش قبلاً نهایی شده است.')
            return ConversationHandler.END
        if int(order[2])<0:
            await update.message.reply_text('سفارش تکمیل شد؛ توضیحات در پنل کاربر ثبت شد.')
            return ConversationHandler.END
        if msg.text is not None:
            extra_text = msg.text.strip()
            if not extra_text:
                await update.message.reply_text('❌ متن خالی است. مشخصات یا پیام موردنظر را ارسال کن.')
                return
            now_text = get_jalali_datetime()
            date_part, time_part = now_text.split(" - ", 1)
            await context.bot.send_message(
                chat_id=order[2],
                text=(f"✅ سفارش شما با کد پیگیری <code>{html.escape(str(order[1]))}</code> "
                      f"در تاریخ {html.escape(date_part)} و ساعت {html.escape(time_part)} با موفقیت تکمیل شد !\n\n"
                      f"📨 <b>پیام / مشخصات سفارش:</b>\n{html.escape(extra_text)}"),
                parse_mode='HTML')
            stored_message = extra_text
        else:
            sent = await context.bot.copy_message(chat_id=order[2], from_chat_id=update.effective_chat.id, message_id=msg.message_id)
            await context.bot.send_message(chat_id=order[2], text=(f"🎉 <b>سفارش #{order_id} با موفقیت تکمیل شد.</b>\n🔍 <b>کد پیگیری:</b> <code>{html.escape(str(order[1]))}</code>"), parse_mode='HTML')
            stored_message = msg.caption or ''
        await update.message.reply_text(f"✅ سفارش #{order_id} تکمیل شد و مشخصات برای کاربر ارسال شد.")
    except Exception:
        logger.exception('failed completing order with message order=%s admin=%s', order_id, update.effective_user.id)
        await update.message.reply_text('❌ ارسال مشخصات یا تکمیل سفارش انجام نشد.')
    finally:
        context.user_data.pop('admin_state', None)
        context.user_data.pop('complete_order_id', None)
    return ConversationHandler.END


def get_user_payments_page(user_id, page=1, per_page=10):
    conn = get_db_connection()
    if not conn: return [], 0
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) AS c FROM receipts WHERE user_id=%s", (user_id,)); card_count=int(cur.fetchone()['c'] or 0)
        cur.execute("SELECT COUNT(*) AS c FROM zarinpal_transactions WHERE user_id=%s", (user_id,)); online_count=int(cur.fetchone()['c'] or 0)
        total=card_count+online_count; offset=max(0,(page-1)*per_page)
        cur.execute("""
            SELECT id AS payment_id, 'card' AS method, amount, payment_tracking_code AS tracking,
                   status, created_at, NULL AS authority, NULL AS ref_id, photo_id
            FROM receipts WHERE user_id=%s
            UNION ALL
            SELECT id AS payment_id, 'online' AS method, amount, payment_tracking_code AS tracking,
                   status, created_at, authority, ref_id, NULL AS photo_id
            FROM zarinpal_transactions WHERE user_id=%s
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (user_id,user_id,per_page,offset))
        return cur.fetchall(), total
    except Exception:
        logger.exception("failed loading user payments user=%s", user_id); return [],0
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

def get_user_gift_uses_page(user_id, page=1, per_page=10):
    conn=get_db_connection()
    if not conn:return [],0
    try:
        cur=conn.cursor(dictionary=True); cur.execute("SELECT COUNT(*) AS c FROM gift_code_uses WHERE user_id=%s",(user_id,)); total=int(cur.fetchone()['c'] or 0)
        cur.execute("""SELECT g.code,g.amount,gcu.amount AS used_amount,gcu.used_at FROM gift_code_uses gcu JOIN gift_codes g ON g.id=gcu.gift_code_id WHERE gcu.user_id=%s ORDER BY gcu.used_at DESC LIMIT %s OFFSET %s""",(user_id,per_page,max(0,(page-1)*per_page)))
        return cur.fetchall(),total
    except Exception: logger.exception("failed loading user gift uses user=%s",user_id); return [],0
    finally:
        try:cur.close();conn.close()
        except Exception:pass

def get_user_lottery_wins_page(user_id, page=1, per_page=10):
    conn=get_db_connection()
    if not conn:return [],0
    try:
        cur=conn.cursor(dictionary=True); cur.execute("SELECT COUNT(*) AS c FROM lottery_runs WHERE winner_id=%s",(user_id,)); total=int(cur.fetchone()['c'] or 0)
        cur.execute("SELECT id,amount,target_type,target_value,created_at FROM lottery_runs WHERE winner_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",(user_id,per_page,max(0,(page-1)*per_page)))
        return cur.fetchall(),total
    except Exception: logger.exception("failed loading user lottery wins user=%s",user_id); return [],0
    finally:
        try:cur.close();conn.close()
        except Exception:pass

def payment_method_label(method):
    return {'card':'💳 کارت‌به‌کارت','online':'💸 درگاه آنلاین زرین‌پال'}.get(str(method),'💳 پرداخت')

def lottery_target_label_admin(target_type):
    return {'all':'همه کاربران','active':'کاربران فعال','verified':'احراز‌شده','unverified':'احراز‌نشده','buyers':'خریداران','referrers':'دارای رفرال','new_today':'امروز','new_week':'۷ روز اخیر','new_month':'۳۰ روز اخیر'}.get(str(target_type),str(target_type or 'همه کاربران'))

async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
        return

    await query.answer()

    # دکمه‌های صرفاً نمایشی نباید حالت لودینگ تلگرام را نگه دارند.
    if data == "noop":
        return

    if data.startswith("apanel_sms_requests_"):
        stats=get_sms_verification_dashboard_stats()
        text=(
            "📩 <b>مدیریت درخواست‌های کد تأیید</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👥 کل درخواست‌دهنده‌ها: <b>{int(stats.get('total_users') or 0):,}</b>\n"
            f"🔁 کل درخواست‌ها: <b>{int(stats.get('total_requests') or 0):,}</b>\n"
            f"📨 کل پیامک‌های موفق: <b>{int(stats.get('total_sms') or 0):,}</b>\n"
            f"🔐 کدهای فعال: <b>{int(stats.get('active_codes') or 0):,}</b>\n\n"
            f"📅 کاربران فعال امروز: <b>{int(stats.get('users_today') or 0):,}</b>\n"
            f"🗓 کاربران فعال ۷ روز اخیر: <b>{int(stats.get('users_week') or 0):,}</b>\n"
            f"📆 کاربران فعال ۳۰ روز اخیر: <b>{int(stats.get('users_month') or 0):,}</b>\n\n"
            "📊 <b>تاریخچه دقیق از نسخه جدید</b>\n"
            f"• درخواست امروز: <b>{int(stats.get('requests_today') or 0):,}</b>\n"
            f"• درخواست ۷ روز اخیر: <b>{int(stats.get('requests_week') or 0):,}</b>\n"
            f"• درخواست ۳۰ روز اخیر: <b>{int(stats.get('requests_month') or 0):,}</b>\n"
            f"• پیامک موفق امروز: <b>{int(stats.get('sms_today') or 0):,}</b>\n"
            f"• خطاهای ۳۰ روز اخیر: <b>{int(stats.get('errors_month') or 0):,}</b>\n"
            f"• برخورد با محدودیت: <b>{int(stats.get('limits_month') or 0):,}</b>\n"
            f"• استفاده مجدد از کد فعال: <b>{int(stats.get('reused_month') or 0):,}</b>"
        )
        await query.edit_message_text(text,reply_markup=get_sms_dashboard_keyboard(),parse_mode="HTML")
        return

    if data.startswith("apanel_sms_list_") or data.startswith("apanel_sms_top_"):
        sort='top' if data.startswith('apanel_sms_top_') else 'latest'
        if sort=='top': period='all'; page=int(data.rsplit('_',1)[1])
        else:
            parts=data.split('_'); period=parts[3] if len(parts)>3 else 'all'; page=int(parts[4]) if len(parts)>4 else 1
        rows,total=get_sms_verification_requests_page(page,10,period,sort)
        titles={'today':'📅 درخواست‌دهنده‌های امروز','week':'🗓 درخواست‌دهنده‌های ۷ روز اخیر','month':'📆 درخواست‌دهنده‌های ۳۰ روز اخیر','all':'📚 همه درخواست‌دهنده‌ها'}
        title='🏆 بیشترین درخواست‌دهنده‌ها' if sort=='top' else titles.get(period,titles['all'])
        text=f"{title}\n━━━━━━━━━━━━━━━━━━\n👥 تعداد کاربران: <b>{int(total):,}</b>\n\nروی هر کاربر بزنید تا جزئیات کامل نمایش داده شود."
        if not rows:text += "\n\n📭 موردی پیدا نشد."
        await query.edit_message_text(text,reply_markup=get_sms_verification_admin_keyboard(rows,page,total,10,period,sort),parse_mode='HTML')
        return

    if data == "apanel_sms_search":
        context.user_data['admin_state']='sms_request_search'
        context.user_data['admin_input_chat_id']=query.message.chat_id
        context.user_data['admin_input_message_id']=query.message.message_id
        await query.edit_message_text(
            "🔎 <b>جستجو در درخواست‌های کد</b>\n\nیوزرنیم، شماره موبایل یا آیدی عددی کاربر را ارسال کنید.\n\nمثال‌ها:\n<code>@Solispirit</code>\n<code>09123456789</code>\n<code>6478152414</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت",callback_data="apanel_sms_requests_1")]]),parse_mode='HTML')
        return

    if data.startswith("apanel_sms_user_"):
        parts=data.split('_')
        try:user_id=int(parts[3])
        except Exception:
            await query.answer("اطلاعات نامعتبر است.",show_alert=True);return
        row=get_sms_verification_request_detail(user_id)
        if not row:
            await query.answer("گزارش این کاربر پیدا نشد.",show_alert=True);return
        username=str(row.get('username') or '').strip().lstrip('@'); username_text=f"@{html.escape(username)}" if username else '-'
        full_name=html.escape(str(row.get('full_name') or '-')); phone=html.escape(str(row.get('phone_number') or '-'))
        last_code=html.escape(str(row.get('last_code') or '-')); active_code=html.escape(str(row.get('verification_code') or '-'))
        active_status="🟢 معتبر" if bool(row.get('is_active')) and row.get('verification_code') else "⚪️ منقضی/مصرف‌شده"
        sent_today=int(row.get('sent_count') or 0) if str(row.get('sent_date') or '')==datetime.now().strftime('%Y-%m-%d') else 0
        logs=get_sms_verification_recent_logs(user_id,8); status_names={'sent':'📨 ارسال شد','existing':'♻️ کد قبلی','limit':'⛔️ محدودیت','error':'❌ خطا','requested':'🔁 درخواست'}
        history=''
        if logs:
            history='\n\n🧾 <b>آخرین رویدادها</b>\n'+"\n".join(f"• {status_names.get(str(x.get('status')),str(x.get('status')))} — <code>{html.escape(_fmt_admin_datetime(x.get('created_at')))}</code>" for x in logs)
        text=(
            "📩 <b>گزارش کامل درخواست کد</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"👤 نام: <b>{full_name}</b>\n🔗 یوزرنیم: {username_text}\n🆔 آیدی عددی: <code>{int(row.get('user_id') or 0)}</code>\n📱 شماره: <code>{phone}</code>\n"
            f"✅ احراز هویت: <b>{'انجام شده' if row.get('is_verified') else 'انجام نشده'}</b>\n\n"
            f"🔁 کل درخواست‌ها: <b>{int(row.get('request_count') or 0):,}</b>\n📨 کل SMS موفق: <b>{int(row.get('total_sent_count') or 0):,}</b>\n"
            f"📅 درخواست امروز: <b>{int(row.get('requests_today') or 0):,}</b>\n🗓 ۷ روز اخیر: <b>{int(row.get('requests_week') or 0):,}</b>\n📆 ۳۰ روز اخیر: <b>{int(row.get('requests_month') or 0):,}</b>\n"
            f"📤 SMS امروز: <b>{sent_today:,}/{SMS_DAILY_LIMIT}</b>\n❌ خطاها: <b>{int(row.get('error_count') or 0):,}</b>\n⛔️ محدودیت‌ها: <b>{int(row.get('limit_count') or 0):,}</b>\n♻️ استفاده از کد قبلی: <b>{int(row.get('reused_count') or 0):,}</b>\n\n"
            f"🔢 آخرین کد: <code>{last_code}</code>\n🔐 کد فعال: <code>{active_code}</code>\n⏳ وضعیت کد: <b>{active_status}</b>\n"
            f"🕐 اولین درخواست: <code>{html.escape(_fmt_admin_datetime(row.get('first_request_at')))}</code>\n🕓 آخرین درخواست: <code>{html.escape(_fmt_admin_datetime(row.get('last_request_at')))}</code>\n📤 آخرین SMS: <code>{html.escape(_fmt_admin_datetime(row.get('last_sent_at')))}</code>"+history
        )
        await query.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔎 جستجوی جدید",callback_data="apanel_sms_search")],[InlineKeyboardButton("🔙 گزارش درخواست‌های کد",callback_data="apanel_sms_requests_1")],[InlineKeyboardButton("🏠 پنل اصلی",callback_data="apanel_main")]]),parse_mode='HTML')
        return

    for _prefix, _purpose, _back in (("apanel_users_","admin","apanel_users_menu"),("agift_target_","gift","apanel_main"),("alottery_target_","lottery","apanel_main"),("abcast_target_","broadcast","apanel_main")):
        if data.startswith(_prefix + "group_"):
            _group=data[len(_prefix)+6:]
            _title=UNIFIED_USER_TARGET_GROUP_MAP.get(_group,("دسته",[]))[0]
            _kb=get_unified_group_items_keyboard(_prefix,_group,_purpose,context,_back)
            await query.edit_message_text(f"👥 <b>{html.escape(_title)}</b>\n\nگزینه موردنظر را انتخاب کنید:",reply_markup=_kb,parse_mode="HTML")
            return

    if data == "adirect_cancel":
        chat_id = context.user_data.get('admin_input_chat_id', query.message.chat_id if query.message else None)
        message_id = context.user_data.get('admin_input_message_id', query.message.message_id if query.message else None)
        await query.answer("لغو شد")
        await reset_user_state(update, context)
        await _show_admin_main_in_same_message(context, chat_id, message_id)
        return ConversationHandler.END

    if data == "adirect_back":
        await query.answer()
        if context.user_data.get('reply_to_user_id'):
            # فقط گیرنده را پاک کن و همان پیام را دوباره به مرحله انتخاب کاربر برگردان.
            context.user_data.pop('reply_to_user_id', None)
            context.user_data.pop('waiting_for_reply', None)
            context.user_data['admin_state'] = 'direct_message_user'
            await query.edit_message_text(
                "📨 <b>ارسال پیام به یک کاربر</b>\n\n"
                "آیدی عددی یا username کاربر را بفرست.\n"
                "مثال: <code>123456789</code> یا <code>@username</code>\n\n"
                "برای لغو، دکمه «❌ لغو» را بزن.",
                reply_markup=get_direct_message_input_keyboard(False),
                parse_mode='HTML'
            )
        else:
            chat_id = query.message.chat_id if query.message else None
            message_id = query.message.message_id if query.message else None
            await reset_user_state(update, context)
            await _show_admin_main_in_same_message(context, chat_id, message_id)
        return ConversationHandler.END

    if data == "apanel_direct_message":
        context.user_data['admin_state'] = 'direct_message_user'
        context.user_data['admin_input_chat_id'] = query.message.chat_id
        context.user_data['admin_input_message_id'] = query.message.message_id
        await query.edit_message_text(
            "📨 <b>ارسال پیام به یک کاربر</b>\n\n"
            "آیدی عددی یا username کاربر را بفرست.\n"
            "مثال: <code>123456789</code> یا <code>@username</code>\n\n"
            "برای لغو، دکمه «❌ لغو» را بزن.",
            reply_markup=get_direct_message_input_keyboard(False),
            parse_mode='HTML')
        return

    if data == "asupport_noop":
        return
    if data == "apanel_support":
        await query.edit_message_text(
            "🛡 <b>مدیریت پشتیبانی</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "تیکت‌ها را بر اساس وضعیت یا موضوع مدیریت کنید.\n\n"
            "⏳ بدون پاسخ = نیازمند رسیدگی\n"
            "✅ پاسخ داده شده = رسیدگی شده",
            reply_markup=get_admin_support_keyboard(), parse_mode="HTML"
        )
        return
    if data.startswith("asupport_unanswered_") or data.startswith("asupport_answered_"):
        parts=data.split('_'); mode=parts[1]; page=int(parts[2]); answered=0 if mode=='unanswered' else 1
        rows,total=get_support_list(answered=answered,page=page); title="⏳ پیام‌های بدون پاسخ" if not answered else "✅ پیام‌های پاسخ داده شده"
        if not rows:
            await query.edit_message_text(f"{title} — <b>0 پیام</b>\n\n📭 این لیست خالی است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📭 لیست خالی است",callback_data="asupport_noop")],[InlineKeyboardButton("🔙 مدیریت پشتیبانی",callback_data="apanel_support")]]), parse_mode="HTML")
        else:
            await query.edit_message_text(f"{title} — <b>{total} پیام</b>", reply_markup=get_support_list_keyboard(rows,page,total,mode), parse_mode="HTML")
        return
    if data == "asupport_topics":
        topics=get_support_topics(); kb=[]
        for i,(topic,total,unanswered) in enumerate(topics):
            kb.append([InlineKeyboardButton(f"📂 {topic} — {total} پیام / {int(unanswered or 0)} بدون پاسخ",callback_data=f"asupport_topic_{i}_1")])
        if not kb: kb=[[InlineKeyboardButton("📭 لیست موضوعات خالی است",callback_data="asupport_noop")]]
        kb.append([InlineKeyboardButton("🔙 مدیریت پشتیبانی",callback_data="apanel_support")])
        await query.edit_message_text("📂 <b>دسته‌بندی پیام‌ها بر اساس موضوع</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return
    if data.startswith("asupport_topic_"):
        parts=data.split('_'); idx=int(parts[2]); page=int(parts[3]); topics=get_support_topics()
        if idx<0 or idx>=len(topics): await query.answer("موضوع پیدا نشد.",show_alert=True); return
        topic=topics[idx][0]; rows,total=get_support_list(topic=topic,page=page)
        if not rows:
            await query.edit_message_text(f"📂 <b>{topic}</b>\n\n📭 این دسته خالی است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📭 لیست خالی است",callback_data="asupport_noop")],[InlineKeyboardButton("🔙 دسته‌بندی موضوعات",callback_data="asupport_topics")]]), parse_mode="HTML")
        else:
            await query.edit_message_text(f"📂 <b>{topic}</b> — <b>{total} پیام</b>", reply_markup=get_support_list_keyboard(rows,page,total,f"topic_{idx}"), parse_mode="HTML")
        return
    if data.startswith("asupport_ticket_"):
        ticket=get_support_ticket(int(data.split('_')[2]))
        if not ticket: await query.answer("پیام پیدا نشد.",show_alert=True); return
        u=get_user_data(ticket['user_id']) or {}; status='✅ پاسخ داده شده' if ticket['answered'] else '⏳ بدون پاسخ'
        msg=(f"📨 <b>پیام پشتیبانی #{ticket['id']}</b>\n\n👤 {u.get('full_name','-')}\n🆔 <code>{ticket['user_id']}</code>\n📂 موضوع: <b>{ticket['topic']}</b>\n📅 {ticket['created_at']}\n📊 وضعیت: {status}\n\n💬 {ticket['message_text'] or '-'}")
        kb=[]
        if not ticket['answered']: kb.append([InlineKeyboardButton("💬 پاسخ به کاربر",callback_data=f"reply_support_{ticket['id']}_{ticket['user_id']}")])
        kb.append([InlineKeyboardButton("🔙 مدیریت پشتیبانی",callback_data="apanel_support")])
        await query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup(kb),parse_mode="HTML")
        return

    if data == "apanel_close":
        await query.message.delete()
        return

    if data == "apanel_main":
        stats = get_total_stats()
        message = (
            "🎛 <b>پنل مدیریت دان پنل</b>\n"
            "━━━━━━━━━━━━━━\n"
            "👥 <b>کاربران</b>\n"
            f"▫️ کل: <b>{stats.get('total_users', 0):,}</b>  •  🚫 بن: <b>{stats.get('banned_users', 0):,}</b>  •  🚫 بلاک: <b>{stats.get('blocked_users', 0):,}</b>\n"
            f"💰 موجودی کل: <b>{format_amount(stats.get('total_balance', 0))} تومان</b>\n"
            "━━━━━━━━━━━━━━\n"
            "📦 <b>سفارش‌ها</b>\n"
            f"▫️ کل: <b>{stats.get('total_orders', 0):,}</b>  •  ⏳ <b>{stats.get('pending_orders', 0):,}</b>  •  🎉 <b>{stats.get('completed_orders', 0):,}</b>  •  ❌ <b>{stats.get('cancelled_orders', 0):,}</b>\n"
            f"📅 امروز: <b>{stats.get('orders_today', 0):,}</b> سفارش | {format_amount(stats.get('sales_today', 0))} تومان\n"
            f"📆 هفته: <b>{stats.get('orders_week', 0):,}</b> سفارش | {format_amount(stats.get('sales_week', 0))} تومان\n"
            f"🗓 ماه: <b>{stats.get('orders_month', 0):,}</b> سفارش | {format_amount(stats.get('sales_month', 0))} تومان\n"
            "━━━━━━━━━━━━━━\n"
            "💎 <b>واریزی‌ها</b>\n"
            f"▫️ کل: <b>{format_amount(stats.get('total_deposits', 0))} تومان</b>\n"
            f"▫️ امروز: <b>{format_amount(stats.get('deposits_today', 0))} تومان</b> ({stats.get('deposit_count_today', 0):,})\n"
            f"▫️ هفته: <b>{format_amount(stats.get('deposits_week', 0))} تومان</b> ({stats.get('deposit_count_week', 0):,})\n"
            f"▫️ ماه: <b>{format_amount(stats.get('deposits_month', 0))} تومان</b> ({stats.get('deposit_count_month', 0):,})\n"
            "━━━━━━━━━━━━━━\n"
            "📸 <b>رسیدهای در انتظار</b>\n"
            f"▫️ <b>{stats.get('pending_receipts', 0):,}</b>\n"
            "━━━━━━━━━━━━━━\n"
            "📈 <b>سود</b>\n"
            f"▫️ امروز: <b>{format_amount(stats.get('profit_today', 0))} تومان</b>\n"
            f"▫️ هفته: <b>{format_amount(stats.get('profit_week', 0))} تومان</b>\n"
            f"▫️ ماه: <b>{format_amount(stats.get('profit_month', 0))} تومان</b>\n"
            "👇 <b>یک بخش را برای مدیریت انتخاب کنید:</b>"
        )
        await query.edit_message_text(message, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")
        return

    if data == "apanel_stats":
        stats = get_total_stats() or {}
        def n(k): return f"{int(stats.get(k, 0) or 0):,}"
        def m(k): return format_amount(stats.get(k, 0) or 0)
        message = (
            "📊 <b>آمار کلی سیستم</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "👥 <b>کاربران</b>\n"
            f"کل کاربران: <b>{n('total_users')}</b>   |   فعال ۳۰ روزه: <b>{n('active_users')}</b>\n"
            f"احراز شده: <b>{n('verified_users')}</b>   |   بن: <b>{n('banned_users')}</b>\n"
            f"💳 موجودی کل کاربران: <b>{m('total_balance')}</b> تومان\n\n"
            "🛒 <b>سفارش‌ها</b>\n"
            f"کل: <b>{n('total_orders')}</b>   |   در انتظار: <b>{n('pending_orders')}</b>   |   تکمیل: <b>{n('completed_orders')}</b>\n"
            f"💰 فروش قطعی: <b>{m('sales_total')}</b> تومان\n\n"
            "💵 <b>مالی</b>\n"
            f"واریزی واقعی: <b>{m('total_deposits')}</b> تومان\n"
            f"سود برآوردی: <b>{m('profit_total')}</b> تومان\n"
            f"📸 رسیدهای در انتظار: <b>{n('pending_receipts')}</b>\n\n"
            "🎫 <b>پشتیبانی</b>\n"
            f"کل تیکت‌ها: <b>{n('tickets_total')}</b>   |   بدون پاسخ: <b>{n('tickets_unanswered')}</b>\n\n"
            "👇 <b>برای دیدن جزئیات، بخش موردنظر را انتخاب کنید.</b>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 کاربران", callback_data="astat_users"),
             InlineKeyboardButton("🛒 سفارشات", callback_data="astat_orders")],
            [InlineKeyboardButton("💰 واریزی‌ها", callback_data="astat_deposits"),
             InlineKeyboardButton("📈 سود", callback_data="astat_profit")],
            [InlineKeyboardButton("🎫 پشتیبانی", callback_data="astat_tickets"),
             InlineKeyboardButton("📸 رسیدها", callback_data="astat_receipts")],
            [InlineKeyboardButton("📦 فروشگاه", callback_data="astat_store"),
             InlineKeyboardButton("👥 رفرال", callback_data="astat_referral")],
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data="apanel_stats"),
             InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")]
        ])
        try:
            await query.edit_message_text(message, reply_markup=keyboard, parse_mode="HTML")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.exception("failed updating admin stats")
        return

    # ==================== جزئیات دکمه‌های آمار کلی ====================
    if data.startswith("astat_") and data not in ("astat_period_", "astat_noop"):
        section = data[len("astat_"):]
        conn = get_db_connection()
        try:
            cur = conn.cursor(dictionary=True) if conn else None
            def one(sql, params=()):
                if not cur:
                    return 0
                try:
                    cur.execute(sql, params)
                    row = cur.fetchone() or {}
                    return next(iter(row.values())) if row else 0
                except Exception:
                    logger.exception("stats detail query failed: %s", sql)
                    try: conn.rollback()
                    except Exception: pass
                    return 0

            if section == "users":
                total=one("SELECT COUNT(*) FROM users")
                today=one("SELECT COUNT(*) FROM users WHERE created_at >= CURDATE()")
                week=one("SELECT COUNT(*) FROM users WHERE created_at >= DATE_SUB(NOW(),INTERVAL 7 DAY)")
                month=one("SELECT COUNT(*) FROM users WHERE created_at >= DATE_SUB(NOW(),INTERVAL 30 DAY)")
                active=one("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=0 AND COALESCE(is_blocked,0)=0 AND last_activity_at >= DATE_SUB(NOW(),INTERVAL 30 DAY)")
                verified=one("SELECT COUNT(*) FROM users WHERE COALESCE(is_verified,0)=1")
                banned=one("SELECT COUNT(*) FROM users WHERE COALESCE(is_banned,0)=1")
                blocked=one("SELECT COUNT(*) FROM users WHERE COALESCE(is_blocked,0)=1")
                text=(f"👥 <b>جزئیات کاربران</b>\n━━━━━━━━━━━━━━━━━━\n"
                      f"👤 کل کاربران: <b>{int(total):,}</b>\n🆕 امروز: <b>{int(today):,}</b>\n📆 ۷ روز اخیر: <b>{int(week):,}</b>\n🗓 ۳۰ روز اخیر: <b>{int(month):,}</b>\n\n"
                      f"🟢 فعال ۳۰ روزه: <b>{int(active):,}</b>\n✅ احراز شده: <b>{int(verified):,}</b>\n🚫 بن: <b>{int(banned):,}</b>\n⛔️ بلاک: <b>{int(blocked):,}</b>")
            elif section == "orders":
                total=one("SELECT COUNT(*) FROM orders")
                pending=one("SELECT COUNT(*) FROM orders WHERE status='pending'")
                confirmed=one("SELECT COUNT(*) FROM orders WHERE status='confirmed'")
                completed=one("SELECT COUNT(*) FROM orders WHERE status='completed'")
                cancelled=one("SELECT COUNT(*) FROM orders WHERE status='cancelled'")
                today=one("SELECT COUNT(*) FROM orders WHERE created_at >= CURDATE()")
                week=one("SELECT COUNT(*) FROM orders WHERE created_at >= DATE_SUB(NOW(),INTERVAL 7 DAY)")
                month=one("SELECT COUNT(*) FROM orders WHERE created_at >= DATE_SUB(NOW(),INTERVAL 30 DAY)")
                sales=one("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed'")
                text=(f"🛒 <b>جزئیات سفارشات</b>\n━━━━━━━━━━━━━━━━━━\nکل: <b>{int(total):,}</b>\n📅 امروز: <b>{int(today):,}</b>\n📆 ۷ روز اخیر: <b>{int(week):,}</b>\n🗓 ۳۰ روز اخیر: <b>{int(month):,}</b>\n\n⏳ در انتظار: <b>{int(pending):,}</b>\n🔄 تایید شده: <b>{int(confirmed):,}</b>\n🎉 تکمیل شده: <b>{int(completed):,}</b>\n❌ لغو شده: <b>{int(cancelled):,}</b>\n\n💰 فروش قطعی: <b>{format_amount(sales)} تومان</b>")
            elif section == "deposits":
                total=one("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount>0")
                cnt=one("SELECT COUNT(*) FROM transactions WHERE type='deposit' AND amount>0")
                today=one("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount>0 AND created_at>=CURDATE()")
                week=one("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount>0 AND created_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)")
                month=one("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND amount>0 AND created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY)")
                text=(f"💰 <b>جزئیات واریزی‌ها</b>\n━━━━━━━━━━━━━━━━━━\n💵 کل واریزی: <b>{format_amount(total)} تومان</b>\n🔢 تعداد تراکنش: <b>{int(cnt):,}</b>\n\n📅 امروز: <b>{format_amount(today)} تومان</b>\n📆 ۷ روز اخیر: <b>{format_amount(week)} تومان</b>\n🗓 ۳۰ روز اخیر: <b>{format_amount(month)} تومان</b>")
            elif section == "profit":
                pct=float(get_self_profit_percent() or 0)
                sales=one("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed'")
                today=one("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed' AND created_at>=CURDATE()")
                week=one("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed' AND created_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)")
                month=one("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='completed' AND created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY)")
                calc=lambda x: int(float(x or 0)*pct/(100+pct)) if pct>0 else 0
                text=(f"📈 <b>جزئیات سود</b>\n━━━━━━━━━━━━━━━━━━\n💹 درصد سود: <b>{pct:g}%</b>\n\n📅 امروز: <b>{format_amount(calc(today))} تومان</b>\n📆 ۷ روز اخیر: <b>{format_amount(calc(week))} تومان</b>\n🗓 ۳۰ روز اخیر: <b>{format_amount(calc(month))} تومان</b>\n💰 سود کل برآوردی: <b>{format_amount(calc(sales))} تومان</b>")
            elif section == "tickets":
                total=one("SELECT COUNT(*) FROM support_messages")
                unanswered=one("SELECT COUNT(*) FROM support_messages WHERE answered=0")
                answered=one("SELECT COUNT(*) FROM support_messages WHERE answered=1")
                today=one("SELECT COUNT(*) FROM support_messages WHERE created_at>=CURDATE()")
                week=one("SELECT COUNT(*) FROM support_messages WHERE created_at>=DATE_SUB(NOW(),INTERVAL 7 DAY)")
                text=(f"🎫 <b>جزئیات پشتیبانی</b>\n━━━━━━━━━━━━━━━━━━\nکل تیکت‌ها: <b>{int(total):,}</b>\n⏳ بدون پاسخ: <b>{int(unanswered):,}</b>\n✅ پاسخ داده شده: <b>{int(answered):,}</b>\n\n📅 امروز: <b>{int(today):,}</b>\n📆 ۷ روز اخیر: <b>{int(week):,}</b>")
            elif section == "receipts":
                pending=one("SELECT COUNT(*) FROM receipts WHERE status='pending'")
                total=one("SELECT COUNT(*) FROM receipts")
                approved=one("SELECT COUNT(*) FROM receipts WHERE status IN ('approved','completed','processing')")
                rejected=one("SELECT COUNT(*) FROM receipts WHERE status='rejected'")
                text=(f"📸 <b>جزئیات رسیدها</b>\n━━━━━━━━━━━━━━━━━━\n📋 کل رسیدها: <b>{int(total):,}</b>\n⏳ در انتظار بررسی: <b>{int(pending):,}</b>\n✅ تایید/پردازش شده: <b>{int(approved):,}</b>\n❌ رد شده: <b>{int(rejected):,}</b>")
            elif section == "store":
                products=one("SELECT COUNT(*) FROM products WHERE is_active=1")
                categories=one("SELECT COUNT(*) FROM categories WHERE is_active=1")
                orders=one("SELECT COUNT(*) FROM orders")
                completed=one("SELECT COUNT(*) FROM orders WHERE status='completed'")
                text=(f"📦 <b>جزئیات فروشگاه</b>\n━━━━━━━━━━━━━━━━━━\n📂 دسته‌بندی فعال: <b>{int(categories):,}</b>\n📦 محصول فعال: <b>{int(products):,}</b>\n🛒 کل سفارش‌ها: <b>{int(orders):,}</b>\n🎉 سفارش تکمیل شده: <b>{int(completed):,}</b>")
            elif section == "referral":
                # محاسبه عمومی رفرال بدون فرض ستون‌های اختیاری؛ اگر ستون وجود نداشته باشد صفر نمایش داده می‌شود.
                try:
                    referrals=one("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL AND referred_by != 0")
                except Exception:
                    referrals=0
                text=(f"👥 <b>جزئیات رفرال</b>\n━━━━━━━━━━━━━━━━━━\n🔗 کاربران دارای رفرال: <b>{int(referrals):,}</b>\n\nℹ️ آمار دقیق کمیسیون رفرال به ساختار جدول رفرال وابسته است.")
            else:
                await query.answer("این بخش هنوز تعریف نشده است.",show_alert=True)
                return

            kb=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"astat_{section}"), InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_stats")],
                [InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")]
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            return
        finally:
            try:
                if cur: cur.close()
            except Exception: pass
            try:
                if conn: conn.close()
            except Exception: pass

    if data.startswith("astat_period_"):
        # دکمه بازه فقط نمایشی است؛ صفحه جزئیات همان بخش را عوض نمی‌کند.
        await query.answer("📅 این بازه در ردیف آمار نمایش داده شده است.")
        return

    if data == "astat_noop":
        await query.answer("📊 این مقدار فقط برای نمایش آمار است.")
        return

    if data == "apanel_settings":
        for k in ('admin_state','admin_setting_key','admin_setting_min','admin_setting_max',
                  'admin_setting_message_id','admin_setting_chat_id'):
            context.user_data.pop(k, None)
        min_charge = get_setting('min_charge_amount', MIN_CHARGE_AMOUNT)
        max_charge = get_setting('max_charge_amount', MAX_CHARGE_AMOUNT)
        min_stars = get_setting('min_stars', MIN_STARS)
        max_stars = get_setting('max_stars', MAX_STARS)
        message = ("⚙️ <b>تنظیمات</b>\n\n"
                   f"💰 درصد سود: <b>{get_self_profit_percent():g}%</b>\n"
                   f"👥 درصد رفرال: <b>{get_referral_percent():g}%</b>\n"
                   f"💳 حداقل شارژ: <b>{float(min_charge):g}</b> تومان\n"
                   f"💳 حداکثر شارژ: <b>{float(max_charge):g}</b> تومان\n"
                   f"⭐️ حداقل استارز: <b>{float(min_stars):g}</b>\n"
                   f"⭐️ حداکثر استارز: <b>{float(max_stars):g}</b>\n\n"
                   f"📜 تأیید قوانین: <b>{'فعال' if setting_enabled('require_rules', True) else 'خاموش'}</b>\n"
                   f"📢 عضویت کانال: <b>{'فعال' if setting_enabled('require_channel_membership', True) else 'خاموش'}</b>\n"
                   f"🪪 احراز هویت: <b>{'فعال' if setting_enabled('require_verification', True) else 'خاموش'}</b>\n\n"
                   "📌 تنظیمات از دیتابیس خوانده و ذخیره می‌شوند.")
        await query.edit_message_text(message, reply_markup=get_admin_settings_keyboard(), parse_mode="HTML")
        return

    if data in {"aset_toggle_rules", "aset_toggle_channel", "aset_toggle_verification"}:
        mapping = {
            "aset_toggle_rules": ("require_rules", "تأیید قوانین"),
            "aset_toggle_channel": ("require_channel_membership", "عضویت در کانال"),
            "aset_toggle_verification": ("require_verification", "احراز هویت"),
        }
        key, label = mapping[data]
        new_value = 0 if setting_enabled(key, True) else 1
        if set_setting(key, new_value):
            logger.info("setting toggled key=%s value=%s admin=%s", key, new_value, update.effective_user.id)
            await query.answer(f"{label}: {'فعال' if new_value else 'خاموش'}")
        else:
            await query.answer("❌ ذخیره تنظیمات ناموفق بود.", show_alert=True)
        # نمایش مجدد صفحه تنظیمات
        min_charge = get_setting('min_charge_amount', MIN_CHARGE_AMOUNT)
        max_charge = get_setting('max_charge_amount', MAX_CHARGE_AMOUNT)
        min_stars = get_setting('min_stars', MIN_STARS)
        max_stars = get_setting('max_stars', MAX_STARS)
        message = ("⚙️ <b>تنظیمات</b>\n\n"
                   f"💰 درصد سود: <b>{get_self_profit_percent():g}%</b>\n"
                   f"👥 درصد رفرال: <b>{get_referral_percent():g}%</b>\n"
                   f"💳 حداقل شارژ: <b>{float(min_charge):g}</b> تومان\n"
                   f"💳 حداکثر شارژ: <b>{float(max_charge):g}</b> تومان\n"
                   f"⭐️ حداقل استارز: <b>{float(min_stars):g}</b>\n"
                   f"⭐️ حداکثر استارز: <b>{float(max_stars):g}</b>\n\n"
                   f"📜 تأیید قوانین: <b>{'فعال' if setting_enabled('require_rules', True) else 'خاموش'}</b>\n"
                   f"📢 عضویت کانال: <b>{'فعال' if setting_enabled('require_channel_membership', True) else 'خاموش'}</b>\n"
                   f"🪪 احراز هویت: <b>{'فعال' if setting_enabled('require_verification', True) else 'خاموش'}</b>")
        await query.edit_message_text(message, reply_markup=get_admin_settings_keyboard(), parse_mode="HTML")
        return

    if data == "aset_currencies":
        currencies = get_all_currencies()
        lines = ["💱 <b>مدیریت ارزها</b>", ""]
        for c in currencies:
            lines.append(f"{c.get('icon') or '💱'} <b>{c.get('code')}</b> — {c.get('name')}\n💰 نرخ: {format_amount(int(c.get('rate') or 0))} تومان")
        if not currencies:
            lines.append("هیچ ارزی ثبت نشده است.")
        await query.edit_message_text("\n".join(lines), reply_markup=get_admin_currencies_keyboard(), parse_mode="HTML")
        return

    if data.startswith("acur_edit_"):
        code = data[len("acur_edit_"):].upper()
        currency = get_currency(code)
        if not currency:
            await query.answer("ارز پیدا نشد.", show_alert=True)
            return
        context.user_data['currency_code'] = code
        context.user_data['admin_state'] = 'currency_edit_rate'
        context.user_data['admin_input_message_id'] = query.message.message_id
        context.user_data['admin_input_chat_id'] = query.message.chat_id
        await query.edit_message_text(
            f"💱 <b>{code} — {html.escape(str(currency.get('name') or code))}</b>\n\n"
            f"نرخ فعلی: <b>{format_amount(int(currency.get('rate') or 0))}</b> تومان\n\n"
            "نرخ جدید را به تومان وارد کن.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت و لغو", callback_data=f"acur_rate_back_{code}")]]),
            parse_mode="HTML")
        return ADMIN_CURRENCY_ADD_RATE

    if data.startswith("acur_rate_back_"):
        code = data[len("acur_rate_back_"):].upper()
        for k in ('currency_code','currency_new_code','currency_new_name','currency_new_symbol','admin_state','admin_input_message_id','admin_input_chat_id'):
            context.user_data.pop(k, None)
        currencies = get_all_currencies() or []
        lines=["💱 <b>مدیریت ارزها</b>", ""]
        for c in currencies:
            lines.append(f"{c.get('icon') or '💱'} <b>{html.escape(str(c.get('code') or ''))}</b> — {html.escape(str(c.get('name') or c.get('code') or ''))}\n💰 نرخ: {format_amount(int(c.get('rate') or 0))} تومان")
        await query.edit_message_text("\n".join(lines), reply_markup=get_admin_currencies_keyboard(), parse_mode="HTML")
        await query.answer("↩️ عملیات لغو شد.")
        return

    if data == "acur_add":
        context.user_data['admin_state'] = 'currency_add_code'
        await query.message.reply_text("➕ <b>افزودن ارز</b>\n\nکد ارز را وارد کن. مثال: <code>TRX</code>\nبرای لغو /cancel", parse_mode="HTML")
        return ADMIN_CURRENCY_ADD_CODE

    if data.startswith("acur_delete_"):
        code = data[len("acur_delete_"):].upper()
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE currencies SET is_active=0 WHERE code=%s", (code,))
            conn.commit()
            logger.info("currency disabled code=%s admin=%s", code, update.effective_user.id)
            await query.answer("ارز حذف شد.")
        except Error:
            logger.exception("failed disabling currency code=%s", code)
            await query.answer("خطا در حذف ارز", show_alert=True)
        finally:
            try: cur.close(); conn.close()
            except: pass
        currencies = get_all_currencies()
        lines=["💱 <b>مدیریت ارزها</b>", ""]
        for c in currencies:
            lines.append(f"{c.get('icon') or '💱'} <b>{c.get('code')}</b> — {c.get('name')}\n💰 نرخ: {format_amount(int(c.get('rate') or 0))} تومان")
        await query.edit_message_text("\n".join(lines), reply_markup=get_admin_currencies_keyboard(), parse_mode="HTML")
        return


    if data == "aset_gift_management":
        await query.edit_message_text(
            "🎁 <b>مدیریت هدایا</b>\n\nیکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=get_admin_gift_management_keyboard(),
            parse_mode="HTML",
        )
        return

    if data.startswith("agiftlist_page_"):
        page=int(data.rsplit("_",1)[1]); await query.edit_message_text("🎁 <b>مدیریت کدهای هدیه</b>", reply_markup=get_admin_gift_codes_keyboard(page), parse_mode="HTML"); return

    if data.startswith("agift_detail_"):
        parts=data.split("_"); gift_id=int(parts[2]); page=int(parts[3]) if len(parts)>3 else 1
        gift=get_gift_code_detail(gift_id)
        if not gift: await query.answer("❌ کد پیدا نشد.",show_alert=True); return
        maxu=int(gift.get('max_uses') or 0); used=int(gift.get('used_count') or 0); rem="نامحدود" if maxu==0 else str(max(0,maxu-used))
        status="فعال" if gift.get('is_active') and (maxu==0 or used<maxu) else ("تمام‌شده" if maxu>0 and used>=maxu else "غیرفعال")
        text=(f"🎁 <b>جزئیات کد هدیه</b>\n\n🎟 کد: <code>{gift['code']}</code>\n💰 مبلغ هر استفاده: <b>{format_amount(int(gift['amount']))}</b> تومان\n👥 تعداد استفاده: <b>{used}</b> نفر\n📦 ظرفیت: <b>{'نامحدود' if maxu==0 else maxu}</b>\n♻️ باقی‌مانده: <b>{rem}</b>\n🎯 مجاز برای: <b>{gift_target_label(gift.get('target_type','all'),int(gift.get('target_value') or 0))}</b>\n📊 وضعیت: <b>{status}</b>\n🕐 ایجاد: <b>{gift.get('created_at')}</b>")
        users,total=get_gift_code_users(gift_id,page)
        if users:
            text += "\n\n👤 <b>استفاده‌کنندگان:</b>\n"
            for u in users: text += f"• {u.get('full_name') or 'بدون نام'} — <code>{u['user_id']}</code> — {u.get('used_at')}\n"
        else: text += "\n\n📭 هنوز کسی از این کد استفاده نکرده است."
        pages=max(1,math.ceil(total/8)); kb=[]
        nav=[]
        if page>1: nav.append(InlineKeyboardButton("⬅️ قبلی",callback_data=f"agift_detail_{gift_id}_{page-1}"))
        if total: nav.append(InlineKeyboardButton(f"👥 {total} استفاده‌کننده | {page}/{pages}",callback_data="noop"))
        if page<pages: nav.append(InlineKeyboardButton("بعدی ➡️",callback_data=f"agift_detail_{gift_id}_{page+1}"))
        if nav: kb.append(nav)
        kb.append([InlineKeyboardButton("🗑 حذف کد",callback_data=f"agift_delete_{gift_id}"), InlineKeyboardButton("🔙 لیست کدها",callback_data="aset_gift_list")])
        await query.edit_message_text(text,reply_markup=InlineKeyboardMarkup(kb),parse_mode="HTML"); return

    if data.startswith("agift_delete_"):
        gift_id=int(data[len("agift_delete_"):]); conn=get_db_connection()
        try:
            cur=conn.cursor(); cur.execute("DELETE FROM gift_codes WHERE id=%s",(gift_id,)); conn.commit(); ok=cur.rowcount>0; logger.info("gift deleted id=%s admin=%s",gift_id,update.effective_user.id)
        except Exception: conn.rollback(); ok=False; logger.exception("gift delete failed id=%s",gift_id)
        finally:
            try: cur.close(); conn.close()
            except: pass
        await query.answer("✅ کد حذف شد." if ok else "❌ کد پیدا نشد.",show_alert=True)
        await query.edit_message_text("🎁 <b>مدیریت کدهای هدیه</b>",reply_markup=get_admin_gift_codes_keyboard(1),parse_mode="HTML"); return

    setting_prompts = {
        "aset_min_charge": ("min_charge_amount", "حداقل مبلغ شارژ", ADMIN_SETTING_MIN_CHARGE, MIN_CHARGE_AMOUNT, 0, 100000000000),
        "aset_max_charge": ("max_charge_amount", "حداکثر مبلغ شارژ", ADMIN_SETTING_MAX_CHARGE, MAX_CHARGE_AMOUNT, 0, 1000000000000),
        "aset_min_stars": ("min_stars", "حداقل استارز", ADMIN_SETTING_MIN_STARS, MIN_STARS, 1, 100000000),
        "aset_max_stars": ("max_stars", "حداکثر استارز", ADMIN_SETTING_MAX_STARS, MAX_STARS, 1, 100000000),
    }
    if data in setting_prompts:
        key,label,state,default,mn,mx = setting_prompts[data]
        current = get_setting(key, default)
        context.user_data['admin_setting_key'] = key
        context.user_data['admin_setting_min'] = mn
        context.user_data['admin_setting_max'] = mx
        context.user_data['admin_state'] = 'setting'
        context.user_data['admin_setting_message_id'] = query.message.message_id
        context.user_data['admin_setting_chat_id'] = query.message.chat_id
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="apanel_settings")]
        ])
        await query.edit_message_text(
            f"⚙️ <b>{label}</b>\n\nمقدار فعلی: <b>{float(current):g}</b>\nمقدار جدید را وارد کن.\n\nبرای لغو <code>/cancel</code>",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return state



    if data == "agift_lottery":
        await query.answer()
        context.user_data['admin_state'] = 'lottery_amount'
        await query.edit_message_text(
            "🎲 <b>قرعه‌کشی</b>\n\n"
            "💰 مبلغ جایزه را به تومان وارد کن.\n"
            "مثال: <code>500000</code>\n\n"
            "برای لغو /cancel",
            parse_mode="HTML",
        )
        return

    if data.startswith("alottery_target_"):
        target = data[len("alottery_target_"):]
        await query.answer()

        if target in ('min_referrals', 'min_purchases', 'high_referrals', 'high_purchases'):
            context.user_data['lottery_target_pending'] = target
            context.user_data['admin_state'] = 'lottery_target_value'
            is_high = target.startswith('high_')
            if target.endswith('referrals'):
                label, example = 'تعداد رفرال', '10'
            else:
                label, example = 'مبلغ خرید به تومان', '100000'
            prefix = 'بیشتر از' if is_high else 'حداقل'
            await query.message.reply_text(
                f"🎯 {prefix} {label} را وارد کن.\n\n"
                f"مثال: <code>{example}</code>\n"
                "برای لغو /cancel",
                parse_mode="HTML",
            )
            return

        context.user_data['lottery_target_type'] = target
        context.user_data['lottery_target_value'] = 0

        try:
            await query.edit_message_text(
                "🎲 <b>در حال انجام قرعه‌کشی...</b>\n\n"
                f"🎯 گروه: <b>{escape(gift_target_label(target, 0))}</b>\n"
                f"👥 تعداد واجدین شرایط: <b>{get_lottery_target_count(target, 0)} نفر</b>\n"
                "⏳ در حال انتخاب کاملاً تصادفی برنده...",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("failed editing lottery running message")

        await run_lottery(update, context, target, 0)
        return

    if data == "aset_gift_create":
        context.user_data['admin_state'] = 'gift_code'
        await query.edit_message_text(
            "🎁 <b>ساخت کد هدیه</b>\n\n"
            "کد هدیه را وارد کن.\n"
            "مثال: <code>WELCOME100</code>\n\n"
            "برای لغو /cancel",
            parse_mode="HTML",
        )
        return ADMIN_GIFT_CODE

    if data in ("aset_self_profit", "aset_referral"):
        if data == "aset_self_profit":
            key, label, current, mx = "self_profit_percent", "درصد سود خودت", get_self_profit_percent(), 1000
        else:
            key, label, current, mx = "referral_percent", "درصد سود رفرال", get_referral_percent(), 100

        context.user_data['admin_setting_key'] = key
        context.user_data['admin_setting_min'] = 0
        context.user_data['admin_setting_max'] = mx
        context.user_data['admin_state'] = 'setting'
        context.user_data['admin_setting_message_id'] = query.message.message_id
        context.user_data['admin_setting_chat_id'] = query.message.chat_id

        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="apanel_settings")]
        ])
        await query.edit_message_text(
            f"⚙️ <b>{label}</b> را وارد کن.\n\n"
            f"مقدار فعلی: <b>{current:g}%</b>\n"
            f"مثال: <code>10</code>\n"
            f"حد مجاز: 0 تا {mx:g}\n\n"
            f"برای لغو <code>/cancel</code>",
            reply_markup=back_kb,
            parse_mode="HTML"
        )
        return

    if data == "apanel_users_menu":
        context.user_data.pop('admin_user_search', None)
        context.user_data.pop('admin_user_threshold', None)
        context.user_data.pop('admin_user_threshold_target', None)
        await query.edit_message_text("👥 <b>مدیریت کاربران</b>\n\nیکی از بخش‌های زیر را انتخاب کنید:",
                                      reply_markup=get_admin_users_menu_keyboard(), parse_mode="HTML")
        return

    if data == "apanel_users_new_menu":
        c = get_admin_user_category_counts()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🆕 امروز ({c['new_today']:,})", callback_data="apanel_users_new_today_1"),
             InlineKeyboardButton(f"📅 ۱ هفته اخیر ({c['new_week']:,})", callback_data="apanel_users_new_week_1")],
            [InlineKeyboardButton(f"🗓 ۱ ماه اخیر ({c['new_month']:,})", callback_data="apanel_users_new_month_1"),
             InlineKeyboardButton(f"📆 ۳ ماه اخیر ({c['new_3_month']:,})", callback_data="apanel_users_new_3_month_1")],
            [InlineKeyboardButton(f"📆 ۶ ماه اخیر ({c['new_6_month']:,})", callback_data="apanel_users_new_6_month_1"),
             InlineKeyboardButton(f"🗓 ۱ سال اخیر ({c['new_year']:,})", callback_data="apanel_users_new_year_1")],
            [InlineKeyboardButton("🔙 بازگشت به مدیریت کاربران", callback_data="apanel_users_menu")]
        ])
        await query.edit_message_text(
            "🆕 <b>کاربران جدید</b>\n\nبازه زمانی موردنظر را انتخاب کنید:",
            reply_markup=kb, parse_mode="HTML"
        )
        return

    if data == "apanel_users_inactive_menu":
        c = get_admin_user_category_counts()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"😴 بیش از ۷ روز ({c['inactive_7']:,})", callback_data="apanel_users_inactive_7_1"),
             InlineKeyboardButton(f"😴 بیش از ۳۰ روز ({c['inactive_30']:,})", callback_data="apanel_users_inactive_30_1")],
            [InlineKeyboardButton(f"💤 بیش از ۶۰ روز ({c['inactive_60']:,})", callback_data="apanel_users_inactive_60_1"),
             InlineKeyboardButton(f"💤 بیش از ۹۰ روز ({c['inactive_90']:,})", callback_data="apanel_users_inactive_90_1")],
            [InlineKeyboardButton(f"💤 بیش از ۶ ماه ({c['inactive_180']:,})", callback_data="apanel_users_inactive_180_1")],
            [InlineKeyboardButton(f"🪦 بیش از ۱ سال ({c['inactive_365']:,})", callback_data="apanel_users_inactive_365_1")],
            [InlineKeyboardButton("🔙 بازگشت به مدیریت کاربران", callback_data="apanel_users_menu")]
        ])
        await query.edit_message_text(
            "😴 <b>کاربران کم‌فعالیت</b>\n\n"
            "ملاک این لیست «آخرین فعالیت واقعی در ربات» است؛ یعنی /start، پیام یا کلیک روی دکمه‌ها.\n"
            "کاربری که بیشتر از بازه انتخابی هیچ‌کدام را انجام نداده باشد اینجا قرار می‌گیرد:",
            reply_markup=kb, parse_mode="HTML"
        )
        return

    if data == "apanel_users_search":
        await query.edit_message_text("🔎 <b>جستجوی کاربر</b>\n\nروش جستجو را انتخاب کن:",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆔 آیدی عددی",callback_data="apanel_users_search_mode_id"),InlineKeyboardButton("📱 شماره تلفن",callback_data="apanel_users_search_mode_phone")],[InlineKeyboardButton("👤 یوزرنیم",callback_data="apanel_users_search_mode_username"),InlineKeyboardButton("📝 نام و نام خانوادگی",callback_data="apanel_users_search_mode_name")],[InlineKeyboardButton("🔎 جستجو در همه",callback_data="apanel_users_search_mode_all")],[InlineKeyboardButton("🔙 مدیریت کاربران",callback_data="apanel_users_menu")]]),parse_mode='HTML');return

    if data.startswith("apanel_users_search_mode_"):
        mode=data[len("apanel_users_search_mode_"):]
        if mode not in {'id','phone','username','name','all'}: await query.answer("❌ روش جستجو نامعتبر است.",show_alert=True);return
        context.user_data['admin_user_search_mode']=mode;context.user_data['admin_state']='user_search'
        labels={'id':('🆔 آیدی عددی','مثال: <code>123456789</code>'),'phone':('📱 شماره تلفن','مثال: <code>09123456789</code>'),'username':('👤 یوزرنیم','مثال: <code>username</code>'),'name':('📝 نام و نام خانوادگی','مثال: <code>علی رضایی</code>'),'all':('🔎 همه اطلاعات','آیدی، شماره تلفن، یوزرنیم یا نام')}
        title,example=labels[mode]
        await query.edit_message_text(f"🔎 <b>{title}</b>\n\n{example} را ارسال کن.\n\nبرای لغو /cancel",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو",callback_data="acancel_input")]]),parse_mode='HTML');return ADMIN_USER_SEARCH

    if data.startswith("apanel_users_action_gift_"):
        category = data[len("apanel_users_action_gift_"):]
        allowed = {'banned','verified','unverified','rules_pending','blocked','new_today','new_week','new_month','new_3_month','new_6_month','new_year','inactive_7','inactive_30','inactive_90','inactive_180','inactive_365','top_purchases','top_referrals','top_income','top_balance','lottery_winners','gift_users','high_referrals','high_purchases','min_referrals','min_purchases'}
        if category not in allowed:
            await query.answer("❌ این گروه قابل استفاده نیست.", show_alert=True)
            return
        context.user_data['gift_target_type'] = category
        context.user_data['gift_target_value'] = 0
        context.user_data['gift_preset_from_users'] = True
        context.user_data['admin_state'] = 'gift_code'
        await query.answer("🎁 گروه انتخاب شد")
        await query.edit_message_text(
            f"🎁 <b>ساخت کد هدیه برای «{html.escape(gift_target_label(category, 0))}»</b>\n\n"
            "کد هدیه را وارد کن.\nمثال: <code>INACTIVE100</code>\n\nبرای لغو /cancel",
            parse_mode="HTML"
        )
        return ADMIN_GIFT_CODE

    if data.startswith("apanel_users_action_lottery_"):
        category = data[len("apanel_users_action_lottery_"):]
        allowed = {'banned','verified','unverified','rules_pending','blocked','new_today','new_week','new_month','new_3_month','new_6_month','new_year','inactive_7','inactive_30','inactive_90','inactive_180','inactive_365','top_purchases','top_referrals','top_income','top_balance','lottery_winners','gift_users','high_referrals','high_purchases','min_referrals','min_purchases'}
        if category not in allowed:
            await query.answer("❌ این گروه قابل استفاده نیست.", show_alert=True)
            return
        context.user_data['lottery_target_type'] = category
        context.user_data['lottery_target_value'] = 0
        context.user_data['lottery_preset_from_users'] = True
        context.user_data['admin_state'] = 'lottery_amount'
        await query.answer("🎲 گروه انتخاب شد")
        await query.edit_message_text(
            f"🎲 <b>قرعه‌کشی برای «{html.escape(gift_target_label(category, 0))}»</b>\n\n"
            "💰 مبلغ جایزه را به تومان وارد کن.\nمثال: <code>500000</code>\n\nبرای لغو /cancel",
            parse_mode="HTML"
        )
        return

    if data.startswith("apanel_users_action_broadcast_"):
        category = data[len("apanel_users_action_broadcast_"):]
        allowed = {'banned','verified','unverified','rules_pending','blocked','new_today','new_week','new_month','inactive_7','inactive_30','inactive_90','inactive_180','inactive_365','top_purchases','top_referrals','top_income','top_balance','lottery_winners','gift_users'}
        if category not in allowed:
            await query.answer("❌ این گروه قابل استفاده نیست.", show_alert=True)
            return
        # برای broadcast همان دسته را به عنوان مخاطب قرار می‌دهیم.
        context.user_data['broadcast_targets'] = [category]
        context.user_data['broadcast_target'] = category
        context.user_data['broadcast_mode'] = 'copy'
        context.user_data['broadcast_pin'] = False
        context.user_data['broadcast_threshold'] = None
        count = get_broadcast_target_count(category)
        await query.answer("📢 گروه انتخاب شد")
        await show_broadcast_mode_menu(query, context, count)
        return ADMIN_BROADCAST

    if data.startswith("apanel_users_") and data[len("apanel_users_"):] in {
        'high_referrals', 'high_purchases', 'min_referrals', 'min_purchases'
    }:
        target = data[len("apanel_users_"):]
        context.user_data['admin_user_threshold_target'] = target
        context.user_data['admin_state'] = 'user_threshold'
        if target.endswith('referrals'):
            label, example = 'تعداد رفرال', '10'
        else:
            label, example = 'مبلغ خرید به تومان', '100000'
        prefix = 'بیشتر از' if target.startswith('high_') else 'حداقل'
        await query.edit_message_text(
            f"🎯 <b>{prefix} {label}</b> را وارد کن.\n\n"
            f"مثال: <code>{example}</code>\n"
            "برای لغو /cancel",
            parse_mode="HTML",
        )
        return ADMIN_USER_SEARCH

    # انتخاب مستقیم یک دسته (مثل «همه کاربران» یا گزینه‌های داخل گروه‌ها)
    # از کیبورد مشترک بدون شماره صفحه می‌آید؛ صفحه اول را باز کن.
    if data.startswith("apanel_users_"):
        _direct_category = data[len("apanel_users_"):]
        _direct_allowed = {
            'all','banned','verified','rules_pending','blocked','new_today','new_week','new_month',
            'new_3_month','new_6_month','new_year','inactive_7','inactive_30','inactive_60','inactive_90',
            'inactive_180','inactive_365','never_active','top_purchases','top_referrals','top_income',
            'top_balance','lottery_winners','gift_users','unverified','buyers','no_buyers','referrers',
            'no_referrals','paid','no_payments','positive_balance','zero_balance','active'
        }
        if _direct_category in _direct_allowed:
            page = 1
            category = _direct_category
            context.user_data['admin_user_category'] = category
            users, total = get_users_page(page, 10, None, category, None)
            message = format_admin_users_list(users, category, page, total, 10)
            await query.edit_message_text(
                message,
                reply_markup=get_admin_users_keyboard(page, total, category=category, users=users),
                parse_mode="HTML"
            )
            return

    if data.startswith("apanel_users_"):
        parts=data.split("_")
        if parts[-1].isdigit():
            page=int(parts[-1])
            # جستجو: apanel_users_search_2
            if len(parts) == 4 and parts[2] == "search":
                search=context.user_data.get('admin_user_search','')
                search_mode=context.user_data.get('admin_user_search_mode','all')
                users,total=get_users_page(page,10,search,'all',None,search_mode)
                context.user_data['admin_user_category']='search'
                message = (
                    f"🔎 <b>نتیجه جستجو</b> برای <code>{search}</code>\n\n"
                    + format_admin_users_list(users, 'search', page, total, 10)
                )
                await query.edit_message_text(
                    message,
                    reply_markup=get_admin_users_keyboard(page, total, search=search, category='search', users=users),
                    parse_mode="HTML")
                return
            category="_".join(parts[2:-1])
            allowed={'all','banned','verified','rules_pending','blocked','new_today','new_week','new_month','new_3_month','new_6_month','new_year','inactive_7','inactive_30','inactive_60','inactive_90','inactive_180','inactive_365','never_active','top_purchases','top_referrals','top_income','top_balance','lottery_winners','gift_users','unverified','buyers','no_buyers','referrers','no_referrals','paid','no_payments','positive_balance','zero_balance','active','high_referrals','high_purchases','min_referrals','min_purchases'}
            if category in allowed:
                context.user_data['admin_user_category']=category
                threshold = context.user_data.get('admin_user_threshold') if category in {
                    'high_referrals','high_purchases','min_referrals','min_purchases'
                } else None
                users,total=get_users_page(page,10,None,category,threshold)
                category_titles = {
                    'all':'👥 همه کاربران', 'banned':'🚫 کاربران بن‌شده', 'verified':'✅ کاربران احراز هویت‌شده', 'unverified':'⚠️ کاربران احراز نشده',
                    'rules_pending':'📜 کاربران تأییدنشده قوانین', 'blocked':'🚫 کاربرانی که ربات را بلاک کرده‌اند',
                    'new_today':'🆕 کاربران جدید امروز', 'new_week':'📅 کاربران جدید ۱ هفته اخیر',
                    'new_month':'🗓 کاربران جدید ۱ ماه اخیر',
                    'new_3_month':'📆 کاربران جدید ۳ ماه اخیر', 'new_6_month':'📆 کاربران جدید ۶ ماه اخیر',
                    'new_year':'🗓 کاربران جدید ۱ سال اخیر',
                    'inactive_7':'😴 بدون فعالیت بیش از ۷ روز', 'inactive_30':'😴 بدون فعالیت بیش از ۳۰ روز',
                    'inactive_60':'💤 بدون فعالیت بیش از ۶۰ روز', 'inactive_90':'💤 بدون فعالیت بیش از ۹۰ روز',
                    'inactive_180':'💤 بدون فعالیت بیش از ۶ ماه', 'inactive_365':'🪦 بدون فعالیت بیش از ۱ سال',
                    'top_purchases':'🛒 کاربران با بیشترین خرید',
                    'top_referrals':'👥 کاربران با بیشترین رفرال', 'top_income':'💰 کاربران با بیشترین درآمد', 'top_balance':'💳 کاربران با بیشترین موجودی'
                }
                message = format_admin_users_list(users, category, page, total, 10)
                await query.edit_message_text(
                    message,
                    reply_markup=get_admin_users_keyboard(page, total, category=category, users=users),
                    parse_mode="HTML")
                return

    if data == "aorders_search":
        context.user_data['admin_state'] = 'order_search'
        await query.message.reply_text(
            "🔎 <b>جستجوی سفارش</b>\n\n"
            "کد پیگیری، آیدی عددی کاربر، شماره سفارش یا نام محصول را وارد کن.\n"
            "مثال: <code>DWN-ABC123</code> یا <code>90562681</code>\n\n"
            "برای لغو /cancel",
            parse_mode="HTML"
        )
        return

    if data.startswith("auser_txns_"):
        parts = data.split("_")
        user_id = int(parts[2]); page = int(parts[3]) if len(parts) > 3 else 1
        txs, total = get_user_transactions_page(user_id, page, 10)
        user_data = get_user_data(user_id)
        title_name = html.escape(str(user_data['full_name'])) if user_data else str(user_id)
        message = f"💸 <b>تراکنش‌های کاربر</b>\n👤 {title_name} | <code>{user_id}</code>\n📄 صفحه {page} از {max(1, math.ceil(total/10))}\n\n"
        keyboard=[]
        if txs:
            for t in txs:
                tracking = t[5] if len(t) > 5 and t[5] else str(t[0])
                keyboard.append([InlineKeyboardButton(f"🔎 {tracking}", callback_data=f"noop")])
        else:
            message += "❌ تراکنشی برای این کاربر ثبت نشده است.\n"
        nav=[]
        pages=max(1, math.ceil(total/10))
        if page>1: nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"auser_txns_{user_id}_{page-1}"))
        nav.append(InlineKeyboardButton(f"📄 {page}/{pages}", callback_data="noop"))
        if page<pages: nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"auser_txns_{user_id}_{page+1}"))
        keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 اطلاعات کاربر", callback_data=f"auser_{user_id}")])
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if data.startswith("auser_payments_"):
        parts=data.split('_'); uid=int(parts[2]); page=int(parts[3]) if len(parts)>3 else 1; rows,total=get_user_payments_page(uid,page,10); u=get_user_data(uid); name=html.escape(str(u['full_name'])) if u else str(uid); pages=max(1,math.ceil(total/10))
        msg=f"💳 <b>پرداخت‌های کاربر</b>\n👤 {name} | <code>{uid}</code>\n📄 صفحه {page} از {pages}\n\n"
        for x in rows:
            msg+=f"{payment_method_label(x['method'])}\n💰 مبلغ: <b>{format_amount(x.get('amount') or 0)} تومان</b>\n📊 وضعیت: {get_transaction_status_fa(x.get('status')) or x.get('status') or '-'}\n🔢 کد پیگیری: <code>{html.escape(str(x.get('tracking') or '-'))}</code>\n"
            if x['method']=='card': msg+=f"💳 کارت مقصد: <code>{html.escape(str(CARD_NUMBER))}</code>\n🧾 رسید: <code>#{x['payment_id']}</code>\n"
            else:
                if x.get('authority'): msg+=f"🔐 Authority: <code>{html.escape(str(x['authority']))}</code>\n"
                if x.get('ref_id'): msg+=f"🔗 شماره مرجع: <code>{html.escape(str(x['ref_id']))}</code>\n"
            msg+=f"📅 تاریخ: {format_datetime_fa(x.get('created_at'))}\n\n"
        if not rows: msg+='❌ پرداختی ثبت نشده است.\n'
        nav=[]
        if page>1:nav.append(InlineKeyboardButton('⬅️ قبلی',callback_data=f'auser_payments_{uid}_{page-1}'))
        nav.append(InlineKeyboardButton(f'📄 {page}/{pages}',callback_data='noop'))
        if page<pages:nav.append(InlineKeyboardButton('بعدی ➡️',callback_data=f'auser_payments_{uid}_{page+1}'))
        await query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup([nav,[InlineKeyboardButton('🔙 اطلاعات کاربر',callback_data=f'auser_{uid}')]]),parse_mode='HTML'); return

    if data.startswith("auser_gifts_"):
        parts=data.split('_'); uid=int(parts[2]); page=int(parts[3]) if len(parts)>3 else 1; rows,total=get_user_gift_uses_page(uid,page,10); u=get_user_data(uid); name=html.escape(str(u['full_name'])) if u else str(uid); pages=max(1,math.ceil(total/10))
        msg=f"🎟 <b>کدهای هدیه استفاده‌شده</b>\n👤 {name} | <code>{uid}</code>\n📄 صفحه {page} از {pages}\n\n"
        for x in rows: msg+=f"🎁 کد: <code>{html.escape(str(x.get('code') or '-'))}</code>\n💰 مبلغ: <b>{format_amount(x.get('used_amount') or x.get('amount') or 0)} تومان</b>\n📅 تاریخ: {format_datetime_fa(x.get('used_at'))}\n\n"
        if not rows:msg+='❌ کد هدیه‌ای استفاده نشده است.\n'
        nav=[]
        if page>1:nav.append(InlineKeyboardButton('⬅️ قبلی',callback_data=f'auser_gifts_{uid}_{page-1}'))
        nav.append(InlineKeyboardButton(f'📄 {page}/{pages}',callback_data='noop'))
        if page<pages:nav.append(InlineKeyboardButton('بعدی ➡️',callback_data=f'auser_gifts_{uid}_{page+1}'))
        await query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup([nav,[InlineKeyboardButton('🔙 اطلاعات کاربر',callback_data=f'auser_{uid}')]]),parse_mode='HTML'); return

    if data.startswith("auser_lottery_"):
        parts=data.split('_'); uid=int(parts[2]); page=int(parts[3]) if len(parts)>3 else 1; rows,total=get_user_lottery_wins_page(uid,page,10); u=get_user_data(uid); name=html.escape(str(u['full_name'])) if u else str(uid); pages=max(1,math.ceil(total/10))
        msg=f"🎲 <b>قرعه‌کشی‌های برنده‌شده</b>\n👤 {name} | <code>{uid}</code>\n📄 صفحه {page} از {pages}\n\n"
        for x in rows: msg+=f"🏆 قرعه‌کشی <b>#{x.get('id')}</b>\n💰 جایزه: <b>{format_amount(x.get('amount') or 0)} تومان</b>\n🎯 گروه: {html.escape(lottery_target_label_admin(x.get('target_type')))}\n📅 تاریخ: {format_datetime_fa(x.get('created_at'))}\n\n"
        if not rows:msg+='❌ برنده قرعه‌کشی نشده است.\n'
        nav=[]
        if page>1:nav.append(InlineKeyboardButton('⬅️ قبلی',callback_data=f'auser_lottery_{uid}_{page-1}'))
        nav.append(InlineKeyboardButton(f'📄 {page}/{pages}',callback_data='noop'))
        if page<pages:nav.append(InlineKeyboardButton('بعدی ➡️',callback_data=f'auser_lottery_{uid}_{page+1}'))
        await query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup([nav,[InlineKeyboardButton('🔙 اطلاعات کاربر',callback_data=f'auser_{uid}')]]),parse_mode='HTML'); return

    if data.startswith("auser_orders_"):
        parts = data.split("_")
        user_id = int(parts[2]); page = int(parts[3]) if len(parts) > 3 else 1
        orders, total = get_user_orders_page(user_id, page, 10)
        user_data = get_user_data(user_id)
        title_name = html.escape(str(user_data['full_name'])) if user_data else str(user_id)
        pages=max(1, math.ceil(total/10))
        message = f"🛒 <b>سفارشات کاربر</b>\n👤 {title_name} | <code>{user_id}</code>\n📄 صفحه {page} از {pages}\n\n"
        keyboard=[]
        if orders:
            for o in orders:
                status_emoji = "🎉" if o[9]=='completed' else ("⏳" if o[9]=='pending' else ("✅" if o[9]=='confirmed' else "❌"))
                keyboard.append([InlineKeyboardButton(f"{status_emoji} {o[1]}", callback_data=f"aorderdetail_{o[0]}")])
        else:
            message += "❌ سفارشی برای این کاربر ثبت نشده است.\n"
        nav=[]
        if page>1: nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"auser_orders_{user_id}_{page-1}"))
        nav.append(InlineKeyboardButton(f"📄 {page}/{pages}", callback_data="noop"))
        if page<pages: nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"auser_orders_{user_id}_{page+1}"))
        keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 اطلاعات کاربر", callback_data=f"auser_{user_id}")])
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if data.startswith("auser_verification_"):
        user_id=int(data.split("_")[-1]);u=get_user_data(user_id)
        if not u:
            await query.answer("❌ کاربر پیدا نشد.",show_alert=True);return
        vd=get_user_verification(user_id)
        await query.answer()
        await query.edit_message_text(format_admin_verification(user_id,u,vd),reply_markup=get_admin_verification_keyboard(user_id,vd),parse_mode='HTML')
        return

    if data.startswith("averify_status_"):
        parts=data.split('_');user_id=int(parts[2]);status=int(parts[3]);conn=get_db_connection();ok=False
        if conn:
            try:cur=conn.cursor();cur.execute("UPDATE users SET is_verified=%s WHERE user_id=%s",(status,user_id));conn.commit();ok=True
            except Exception:
                try:conn.rollback()
                except Exception:pass
            finally:
                try:cur.close();conn.close()
                except Exception:pass
        if not ok:await query.answer('❌ ذخیره وضعیت انجام نشد.',show_alert=True);return
        u=get_user_data(user_id);vd=get_user_verification(user_id);await query.answer('✅ وضعیت احراز تغییر کرد.');await query.edit_message_text(format_admin_verification(user_id,u,vd),reply_markup=get_admin_verification_keyboard(user_id,vd),parse_mode='HTML');return

    if data.startswith("averify_clear_"):
        user_id=int(data.split('_')[-1]);clear_user_verification(user_id);u=get_user_data(user_id);vd=get_user_verification(user_id);await query.answer('🗑 اطلاعات احراز پاک شد.',show_alert=True);await query.edit_message_text(format_admin_verification(user_id,u,vd),reply_markup=get_admin_verification_keyboard(user_id,vd),parse_mode='HTML');return

    if data.startswith("averify_edit_"):
        parts=data.split('_',3)
        if len(parts) < 4:
            await query.answer('❌ درخواست نامعتبر است.',show_alert=True);return
        user_id=int(parts[2]);field=parts[3]
        await query.answer()
        context.user_data.update({'verification_user_id':user_id,'verification_field':field,'admin_input_user_id':user_id,'admin_input_chat_id':query.message.chat_id,'admin_input_message_id':query.message.message_id})
        if field=='identity_document_file_id':
            context.user_data['admin_state']='verification_photo'
            await query.edit_message_text('📸 <b>عکس کارت ملی یا شناسنامه</b>\n\nعکس واضح مدرک را ارسال کن.\nبرای لغو /cancel',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ لغو',callback_data='acancel_input')]]),parse_mode='HTML')
            return ADMIN_USER_VERIFICATION_PHOTO
        if field not in {'national_id','birth_certificate_number','birth_date','father_name','bank_card_number','identity_document_type','notes'}:
            await query.answer('❌ فیلد نامعتبر است.',show_alert=True);return
        context.user_data['admin_state']='verification_text'
        await query.edit_message_text(f"✏️ <b>{verification_label(field)}</b>\n\nمقدار را ارسال کن.\nبرای لغو /cancel",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('❌ لغو',callback_data='acancel_input')]]),parse_mode='HTML')
        return ADMIN_USER_VERIFICATION_TEXT


    if data.startswith("auser_"):
        user_id = int(data.split("_")[1])
        user_data = get_user_data(user_id)
        if user_data:
            status = "⛔️ مسدود" if user_data['is_banned'] else ("✅ تایید شده" if user_data['is_verified'] else "⚠️ تایید نشده")
            message = (
                f"👤 <b>اطلاعات کاربر</b>\n\n"
                f"🆔 آیدی: <code>{user_data['user_id']}</code>\n"
                f"👤 نام: {user_data['full_name']}\n"
                f"📱 یوزرنیم: @{user_data['username'] or 'ندارد'}\n"
                f"☎️ شماره تلفن: <tg-spoiler>{user_data['phone_number'] or 'ثبت نشده'}</tg-spoiler>\n"
                f"📊 وضعیت: {status}\n"
                f"💰 موجودی: {format_amount(user_data['balance'])} تومان\n"
                f"💸 مجموع شارژ/پرداخت: {format_amount(user_data['total_payments'])} تومان\n"
                f"🛒 مجموع خرید: {format_amount(user_data['total_purchases'])} تومان\n"
                f"📦 سفارش‌های تکمیل‌شده: {user_data['orders_count']}\n"
                f"💰 درآمد کسب‌شده: {format_amount(user_data['income'])} تومان\n"
                f"👥 تعداد رفرال: {user_data['subsets_count']} نفر\n"
                f"🤑 درآمد رفرال: {format_amount(user_data['subsets_commission'])} تومان\n"
                f"🎁 هدیه مصرف‌شده: {format_amount(user_data['consumed_gift'])} تومان\n"
                f"🔗 کد رفرال: <code>{user_data['referral_code'] or 'ندارد'}</code>\n"
                f"👤 معرف: <code>{user_data['referrer_id'] or 'ندارد'}</code>\n"
                f"📅 تاریخ عضویت: {user_data['join_date']}\n"
            )
            if user_data['is_banned']:
                message += f"🚫 دلیل بن: {user_data['ban_reason']}"
            await query.edit_message_text(message, reply_markup=get_admin_user_detail_keyboard(user_id, user_data['is_banned']), parse_mode="HTML")
        return

    if data.startswith("abalance_"):
        user_id=int(data.split("_",1)[1]); user_data=get_user_data(user_id)
        if not user_data:
            await query.answer("❌ کاربر پیدا نشد.",show_alert=True); return
        context.user_data['balance_user_id']=user_id
        context.user_data['admin_input_user_id']=user_id
        context.user_data['admin_input_chat_id']=query.message.chat_id
        context.user_data['admin_input_message_id']=query.message.message_id
        await query.edit_message_text(
            f"💰 <b>تغییر موجودی کاربر</b>\n\n👤 {html.escape(str(user_data.get('full_name') or user_id))}\n🆔 <code>{user_id}</code>\n💳 موجودی فعلی: <b>{format_amount(user_data.get('balance',0))} تومان</b>\n\n➕ عدد مثبت = اضافه کردن\n➖ عدد منفی = کم کردن\n\nمثال: <code>50000</code> یا <code>-20000</code>\n\n👈 مبلغ را همینجا ارسال کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]]),
            parse_mode="HTML")
        return ADMIN_AMOUNT_INPUT

    if data.startswith("aban_"):
        user_id = int(data.split("_")[1])
        context.user_data['ban_user_id'] = user_id
        context.user_data['admin_input_user_id']=user_id
        context.user_data['admin_input_chat_id']=query.message.chat_id
        context.user_data['admin_input_message_id']=query.message.message_id
        await query.edit_message_text(
            f"🚫 <b>بن کاربر</b>\n\n🆔 کاربر: <code>{user_id}</code>\n\n📝 لطفاً دلیل بن را همینجا ارسال کنید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]]),
            parse_mode="HTML"
        )
        return ADMIN_BAN_USER

    if data.startswith("aunban_"):
        user_id = int(data.split("_")[1])
        if unban_user(user_id):
            await query.answer("✅ کاربر با موفقیت از بن خارج شد.", show_alert=True)
            user_data = get_user_data(user_id)
            if user_data:
                status = "✅ تایید شده" if user_data['is_verified'] else "⚠️ تایید نشده"
                message = (
                    f"👤 <b>اطلاعات کاربر</b>\n\n"
                    f"🆔 آیدی: <code>{user_data['user_id']}</code>\n"
                    f"👤 نام: {user_data['full_name']}\n"
                    f"📊 وضعیت: {status}\n"
                    f"💰 موجودی: {format_amount(user_data['balance'])} تومان\n"
                )
                await query.edit_message_text(message, reply_markup=get_admin_user_detail_keyboard(user_id, user_data['is_banned']), parse_mode="HTML")
        return

    if data == "apanel_payments":
        methods = get_all_payment_methods()
        message = "💳 <b>مدیریت روش‌های پرداخت</b>\n\nبرای فعال/غیرفعال کردن کلیک کنید:\n\n"
        for method in methods:
            status = "✅ فعال" if method[3] else "⛔️ غیرفعال"
            message += f"{method[2]}: <b>{status}</b>\n"
        await query.edit_message_text(message, reply_markup=get_admin_payments_keyboard(), parse_mode="HTML")
        return

    if data.startswith("apaytoggle_"):
        method_key = data.split("_")[1]
        is_active, reason = get_payment_method_status(method_key)

        if is_active:
            toggle_payment_method(method_key, False, "")
            await query.answer("⛔️ روش پرداخت غیرفعال شد.", show_alert=True)
        else:
            toggle_payment_method(method_key, True)
            await query.answer("✅ روش پرداخت فعال شد.", show_alert=True)

        methods = get_all_payment_methods()
        message = "💳 <b>مدیریت روش‌های پرداخت</b>\n\nبرای فعال/غیرفعال کردن کلیک کنید:\n\n"
        for method in methods:
            status = "✅ فعال" if method[3] else "⛔️ غیرفعال"
            message += f"{method[2]}: <b>{status}</b>\n"

        await query.edit_message_text(message, reply_markup=get_admin_payments_keyboard(), parse_mode="HTML")
        return

    if data.startswith('agift_publish_'):
        await query.answer()
        try:
            gift_id = int(data[len('agift_publish_'):])
            conn = get_db_connection(); cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM gift_codes WHERE id=%s", (gift_id,)); gift = cur.fetchone()
            cur.close(); conn.close()
            if not gift:
                await query.edit_message_text('❌ کد هدیه پیدا نشد.'); return
            if not REQUIRED_CHANNEL_ID:
                await query.edit_message_text('❌ شناسه کانال در تنظیمات ربات تعیین نشده است.'); return
            max_uses = int(gift.get('max_uses') or 0)
            used_count = int(gift.get('used_count') or 0)
            if max_uses > 0:
                remaining = max(0, max_uses - used_count)
                capacity_text = f"{remaining} نفر باقی‌مانده از {max_uses} نفر"
                urgency_text = "⚠️ <b>ظرفیت استفاده از این کد محدود است؛ بهتر است هرچه سریع‌تر از این کد استفاده کنید.</b>"
            else:
                capacity_text = "نامحدود"
                urgency_text = "⚠️ <b>هر کاربر فقط یک‌بار می‌تواند از این کد استفاده کند.</b>"
            bot_url = f"https://t.me/{str(BOT_USERNAME).lstrip('@')}"
            channel_text = (f"🎁 <b>کد هدیه ویژه</b>\n\n🎟 کد: <code>{gift['code']}</code>\n💰 مبلغ هدیه: <b>{int(gift['amount']):,}</b> تومان\n👥 ظرفیت استفاده: <b>{capacity_text}</b>\n🎯 مجاز برای: <b>{gift_target_label(gift.get('target_type','all'), int(gift.get('target_value') or 0))}</b>\n\n{urgency_text}\n\n📌 <b>نحوه استفاده از کد:</b>\nوارد ربات شوید → <b>🎁 شارژ رایگان</b> → <b>🎟 کد هدیه</b> → کد را ارسال کنید.")
            channel_kb = InlineKeyboardMarkup([[InlineKeyboardButton('🤖 ورود به ربات', url=bot_url)]])
            sent = await context.bot.send_message(chat_id=REQUIRED_CHANNEL_ID, text=channel_text, parse_mode='HTML', reply_markup=channel_kb)
            conn2 = get_db_connection()
            if conn2:
                try:
                    c2 = conn2.cursor()
                    c2.execute("UPDATE gift_codes SET channel_message_id=%s, channel_chat_id=%s WHERE id=%s", (sent.message_id, int(REQUIRED_CHANNEL_ID), gift_id))
                    conn2.commit()
                    c2.close()
                finally:
                    conn2.close()
            logger.info('gift published to channel gift_id=%s code=%s admin=%s channel=%s', gift_id, gift.get('code'), update.effective_user.id, REQUIRED_CHANNEL_ID)
            # کیبورد پیام انتخاب دسته را بعد از ارسال هم پاک می‌کنیم.
            target_chat_id = context.user_data.get('gift_target_prompt_chat_id')
            target_message_id = context.user_data.get('gift_target_prompt_message_id')
            if target_chat_id and target_message_id:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=target_chat_id, message_id=target_message_id, reply_markup=None
                    )
                except Exception:
                    logger.exception('failed clearing gift target keyboard after publish admin=%s', update.effective_user.id)
            await query.edit_message_text('✅ کد هدیه با موفقیت به کانال ارسال شد.')
        except Exception:
            logger.exception('gift publish failed admin=%s data=%s', update.effective_user.id, data)
            await query.edit_message_text('❌ ارسال کد هدیه به کانال انجام نشد. لاگ را بررسی کنید.')
        context.user_data.pop('gift_target_prompt_chat_id', None)
        context.user_data.pop('gift_target_prompt_message_id', None)
        return

    if data.startswith('agift_cancel_publish_'):
        await query.answer('ارسال به کانال لغو شد.')
        logger.info('gift channel publish cancelled admin=%s gift=%s', update.effective_user.id, data[len('agift_cancel_publish_'):])
        await query.edit_message_text('❌ ارسال کد هدیه به کانال لغو شد.\n\n🎁 کد هدیه ساخته شده و در دیتابیس باقی می‌ماند.')
        context.user_data.pop('gift_target_prompt_chat_id', None)
        context.user_data.pop('gift_target_prompt_message_id', None)
        return

    if data.startswith('agift_target_'):
        target = data[len('agift_target_'):]
        await query.answer()
        # کیبورد انتخاب دسته را همان لحظه غیرفعال می‌کنیم تا بعداً اشتباهی دوباره لمس نشود.
        context.user_data['gift_target_prompt_chat_id'] = query.message.chat_id
        context.user_data['gift_target_prompt_message_id'] = query.message.message_id
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.exception('failed removing gift target keyboard admin=%s', update.effective_user.id)
        if target in ('min_referrals','min_purchases','high_referrals','high_purchases'):
            context.user_data['gift_target_pending'] = target
            context.user_data['admin_state'] = 'gift_target_value'
            is_high = target.startswith('high_')
            if target.endswith('referrals'):
                label, example = 'تعداد رفرال', '10'
            else:
                label, example = 'مبلغ خرید به تومان', '100000'
            prefix = 'بیشتر از' if is_high else 'حداقل'
            await query.message.reply_text(
                f'🎯 {prefix} {label} را وارد کنید.\n\n'
                f'مثال: <code>{example}</code>\nبرای لغو /cancel',
                parse_mode='HTML'
            )
            return
        context.user_data['gift_target_type'] = target
        context.user_data['gift_target_value'] = 0
        await finalize_gift_code(update, context)
        return

    if data == "apanel_broadcast":
        context.user_data['broadcast_targets'] = []
        context.user_data.pop('broadcast_target', None)
        context.user_data.pop('broadcast_ref_threshold', None)
        context.user_data.pop('broadcast_threshold', None)
        context.user_data.pop('broadcast_threshold_target', None)
        context.user_data['broadcast_mode'] = 'copy'
        context.user_data['broadcast_pin'] = False
        await query.edit_message_text(
            "📢 <b>ارسال پیام همگانی</b>\n\n"
            "👥 ابتدا <b>یک گروه از مخاطبان</b> را انتخاب کنید:",
            reply_markup=get_broadcast_targets_keyboard(context), parse_mode="HTML"
        )
        return

    if data.startswith("abcast_target_"):
        target = data[len("abcast_target_"):]
        context.user_data['broadcast_targets'] = [target]
        context.user_data['broadcast_target'] = target
        context.user_data['broadcast_mode'] = 'copy'
        context.user_data['broadcast_pin'] = False
        await query.answer("✅ مخاطب انتخاب شد")

        if target in ('high_referrals', 'high_purchases', 'min_referrals', 'min_purchases'):
            context.user_data['admin_state'] = 'broadcast_threshold'
            context.user_data['broadcast_threshold_target'] = target
            is_high = target.startswith('high_')
            if target.endswith('referrals'):
                label, example = 'تعداد رفرال', '10'
            else:
                label, example = 'مبلغ خرید به تومان', '100000'
            prefix = 'بیشتر از' if is_high else 'حداقل'
            await query.edit_message_text(
                f"🎯 <b>{prefix} {label}</b> را وارد کنید.\n\n"
                f"مثال: <code>{example}</code>\n\n"
                "برای لغو /cancel",
                parse_mode='HTML'
            )
            return

        # بعد از انتخاب مخاطب، مستقیم وارد تنظیمات فوروارد و پین شو.
        await show_broadcast_mode_menu(query, context, get_broadcast_target_count(target))
        return ADMIN_BROADCAST

    if data == 'abcast_prepare':
        selected = context.user_data.get('broadcast_targets', [])
        if not selected:
            await query.answer("❌ ابتدا یک مخاطب را انتخاب کنید.", show_alert=True)
            return ADMIN_BROADCAST

        target = selected[0]
        context.user_data['broadcast_target'] = target
        context.user_data['admin_state'] = 'broadcast'

        count = get_broadcast_target_count(
            target,
            context.user_data.get('broadcast_threshold')
        )
        forward = context.user_data.get('broadcast_mode') == 'forward'
        pin = bool(context.user_data.get('broadcast_pin', False))

        await query.answer("✅ تنظیمات ذخیره شد")
        await query.edit_message_text(
            "📨 <b>ارسال پیام همگانی</b>\n\n"
            f"👥 مخاطب: <b>{html.escape(get_broadcast_target_label(target))}</b>\n"
            f"👤 تعداد مخاطبان: <b>{count:,}</b> نفر\n\n"
            f"↪️ فوروارد: <b>{'فعال' if forward else 'غیرفعال'}</b>\n"
            f"📌 پین: <b>{'فعال' if pin else 'غیرفعال'}</b>\n\n"
            "✉️ <b>حالا پیام موردنظر را بفرستید.</b>",
            parse_mode='HTML'
        )
        return ADMIN_BROADCAST

    if data == 'abcast_mode_copy':
        context.user_data['broadcast_mode'] = 'copy'
        await query.answer('📨 ارسال معمولی فعال شد')
        await show_broadcast_mode_menu(query, context)
        return ADMIN_BROADCAST

    if data == 'abcast_mode_forward':
        context.user_data['broadcast_mode'] = 'copy' if context.user_data.get('broadcast_mode') == 'forward' else 'forward'
        await query.answer("↪️ فوروارد فعال شد" if context.user_data['broadcast_mode'] == 'forward' else "📨 ارسال معمولی فعال شد")
        await show_broadcast_mode_menu(query, context)
        return ADMIN_BROADCAST

    if data == 'abcast_pin_toggle':
        context.user_data['broadcast_pin'] = not bool(context.user_data.get('broadcast_pin', False))
        await query.answer("📌 پین فعال شد" if context.user_data['broadcast_pin'] else "📌 پین غیرفعال شد")
        await show_broadcast_mode_menu(query, context)
        return ADMIN_BROADCAST

    if data.startswith("apanel_receipts_"):
        page = int(data.split("_")[2])
        receipts, total = get_receipts_page(page)
        message = f"📸 <b>رسیدهای در انتظار بررسی</b> - صفحه {page}\n\n"
        if receipts:
            for receipt in receipts:
                rid, uid, amount, photo_id, ptc, status, aid, ca, rr, pat, cat, full_name, username = receipt
                message += f"📸 #{rid} - {format_amount(amount)}T - {full_name[:15]}\n"
        else:
            message += "✅ هیچ رسید در انتظاری وجود ندارد."
        await query.edit_message_text(message, reply_markup=get_admin_receipts_keyboard(page, total), parse_mode="HTML")
        return

    if data.startswith("areceipt_"):
        receipt_id = int(data.split("_")[1])
        receipt = get_receipt_by_id(receipt_id)
        if receipt:
            message = (
                f"📸 <b>رسید #{receipt_id}</b>\n\n"
                f"👤 کاربر: {receipt.get('user_id')}\n"
                f"💰 مبلغ: {format_amount(receipt.get('amount', 0))} تومان\n"
                f"🛒 کد پیگیری: <code>{receipt.get('payment_tracking_code', '')}</code>\n"
                f"📊 وضعیت: {receipt.get('status')}\n"
            )
            await query.edit_message_text(
                message, 
                reply_markup=get_admin_action_keyboard(
                    receipt['user_id'], receipt['amount'], receipt_id, receipt.get('payment_tracking_code', '')
                ), 
                parse_mode="HTML"
            )
        return

    # مدیریت محصولات
    if data == "apanel_products":
        _clear_admin_product_state(context)
        message = "📦 <b>مدیریت محصولات و دسته‌بندی‌ها</b>\n\n"
        message += "👈 یکی از گزینه‌های زیر را انتخاب کنید:"
        await query.edit_message_text(message, reply_markup=get_admin_products_management_keyboard(), parse_mode="HTML")
        return ConversationHandler.END

    if data == "aaddcategory":
        _save_admin_product_message(query, context)
        context.user_data['admin_state'] = 'add_category_name'
        context.user_data.pop('new_category_name', None)
        await query.edit_message_text(
            "➕ <b>افزودن دسته‌بندی</b>\n\n"
            "📝 لطفاً نام دسته‌بندی جدید را وارد کنید:",
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_CATEGORY_NAME

    if data == "alistcategories":
        categories = get_all_categories()
        message = "📋 <b>لیست دسته‌بندی‌ها</b>\n\n"
        if categories:
            for cat in categories:
                emoji = cat[2] if cat[2] else "📦"
                message += f"{emoji} {cat[1]} (ID: {cat[0]})\n"
        else:
            message += "❌ دسته‌بندی وجود ندارد."
        await query.edit_message_text(message, reply_markup=get_categories_list_keyboard(), parse_mode="HTML")
        return
    if data.startswith("show_add_product_"):
        try:
            product_id = int(data.split("_")[-1])
            product = get_product(product_id)
            if not product:
                await query.answer("❌ محصول پیدا نشد.", show_alert=True)
                return

            await query.answer(
                _get_product_add_alert_text(product),
                show_alert=True
            )
        except Exception:
            logger.exception("failed showing product details alert")
            await query.answer("❌ خطا در نمایش مشخصات محصول.", show_alert=True)
        return


    if data == "aaddproduct":
        categories = get_all_categories()
        if not categories:
            await query.answer("❌ ابتدا یک دسته‌بندی اضافه کنید!", show_alert=True)
            return

        _save_admin_product_message(query, context)
        context.user_data['admin_state'] = 'select_product_category'
        await query.edit_message_text(
            "➕ <b>افزودن محصول</b>\n\n"
            "📂 لطفاً دسته‌بندی محصول را انتخاب کنید:",
            reply_markup=get_categories_for_selection_keyboard(),
            parse_mode="HTML"
        )
        return

    if data.startswith("selectcat_"):
        category_id = int(data.split("_")[1])
        context.user_data['new_product_category'] = category_id
        context.user_data['admin_state'] = 'add_product_name'

        category = get_category_by_id(category_id)
        category_name = category[1] if category else 'نامشخص'
        category_emoji = category[2] if category and category[2] else '📦'

        await query.edit_message_text(
            "➕ <b>افزودن محصول</b>\n\n"
            f"📂 دسته‌بندی: {category_emoji} <b>{html.escape(category_name)}</b>\n\n"
            "📦 <b>محصولات فعلی این دسته:</b>\n\n"
            "📝 لطفاً نام محصول جدید را وارد کنید:",
            reply_markup=_get_add_product_category_keyboard(category_id),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_NAME

    if data == "alistproducts":
        await query.edit_message_text(
            "📋 <b>لیست محصولات</b>\n\n",
            reply_markup=get_products_list_keyboard(1),
            parse_mode="HTML"
        )
        return

    if data.startswith("aproducts_"):
        page = int(data.split("_")[1])
        await query.edit_message_text(
            "📋 <b>لیست محصولات</b>\n\n",
            reply_markup=get_products_list_keyboard(page),
            parse_mode="HTML"
        )
        return

    if data.startswith("acatproducts_"):
        parts = data.split("_")
        category_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 1
        category = get_category_by_id(category_id)
        if not category:
            await query.answer("❌ دسته‌بندی پیدا نشد.", show_alert=True)
            return

        products = get_all_category_products_for_admin(category_id)
        emoji = category[2] if category[2] else "📦"
        message = (
            f"{emoji} <b>{html.escape(str(category[1]))}</b>\n\n"
            f"📦 <b>محصولات این دسته</b>\n"
            f"تعداد: <b>{len(products):,}</b>\n\n"
        )
        if products:
            for p in products:
                status = "🟢 فعال" if int(p[9] or 0) == 1 else "🔴 غیرفعال"
                message += f"• {html.escape(str(p[2]))} — {format_amount(p[4])} تومان — {status}\n"
        else:
            message += "❌ محصولی در این دسته وجود ندارد."

        await query.edit_message_text(
            message,
            reply_markup=get_category_products_keyboard(category_id, page),
            parse_mode="HTML"
        )
        return

    if data.startswith("acatdetail_"):
        category_id = int(data.split("_")[1])
        category = get_category_by_id(category_id)
        if category:
            products = get_all_category_products_for_admin(category_id)
            message = f"📦 <b>{category[2] or '📦'} {category[1]}</b> (ID: {category_id})\n\n"
            message += "💰 <b>محصولات این دسته:</b>\n"
            if products:
                for p in products:
                    message += f"• {p[2]} - {format_amount(p[4])} تومان\n"
            else:
                message += "❌ محصولی در این دسته نیست.\n"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"aeditcatname_{category_id}"),
                 InlineKeyboardButton("🗑 حذف دسته‌بندی", callback_data=f"adeletecat_{category_id}")],
                [InlineKeyboardButton("➕ افزودن محصول به این دسته", callback_data=f"aaddproducttocat_{category_id}")],
                [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="alistcategories")],
            ])
            await query.edit_message_text(message, reply_markup=keyboard, parse_mode="HTML")
        return

    if data.startswith("aeditcatname_"):
        category_id = int(data.split("_")[1])
        context.user_data['edit_category_id'] = category_id
        await query.message.reply_text(
            "✏️ لطفاً نام جدید دسته‌بندی را وارد کنید:\n\nبرای لغو /cancel را بزنید."
        )
        return ADMIN_EDIT_CATEGORY_NAME

    if data.startswith("adeletecat_"):
        category_id = int(data.split("_")[1])
        if delete_category(category_id):
            await query.answer("✅ دسته‌بندی حذف شد.", show_alert=True)
        else:
            await query.answer("❌ خطا در حذف.", show_alert=True)
        return

    if data.startswith('aaddprod_currency_'):
        if context.user_data.get('admin_state') != 'add_product_currency':
            await query.answer('❌ این مرحله منقضی شده است.', show_alert=True)
            return
        code = data[len('aaddprod_currency_'):].upper()
        currency = get_currency(code)
        if not currency:
            await query.answer('❌ ارز پیدا نشد.', show_alert=True)
            return
        await query.answer('✅ ارز انتخاب شد')
        context.user_data['admin_state'] = 'add_product_price'
        return await _start_add_product_price_input(query.message, context, code)

    if data in ('aaddprodlink_yes', 'aaddprodlink_no'):
        # این callback فقط وقتی معتبر است که ادمین در مرحله نیاز به لینک باشد.
        if context.user_data.get('admin_state') != 'add_product_need_link':
            await query.answer('❌ این مرحله منقضی شده است.', show_alert=True)
            return ConversationHandler.END

        need_link = data == 'aaddprodlink_yes'
        await query.answer('✅ بله' if need_link else '❌ خیر')

        # دکمه‌ها را از پیام سؤال حذف می‌کنیم تا دوباره قابل کلیک نباشند.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass

        return await _complete_admin_add_product(query.message, context, need_link)

    if data.startswith("aaddproducttocat_"):
        category_id = int(data.split("_")[1])
        context.user_data['new_product_category'] = category_id
        context.user_data['admin_state'] = 'add_product_name'
        _save_admin_product_message(query, context)

        category = get_category_by_id(category_id)
        category_name = category[1] if category else 'نامشخص'
        category_emoji = category[2] if category and category[2] else '📦'

        await query.edit_message_text(
            "➕ <b>افزودن محصول</b>\n\n"
            f"📂 دسته‌بندی: {category_emoji} <b>{html.escape(category_name)}</b>\n\n"
            "📦 <b>محصولات فعلی این دسته:</b>\n\n"
            "📝 لطفاً نام محصول جدید را وارد کنید:",
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_NAME

    if data.startswith("aproductdetail_"):
        product_id = int(data.rsplit("_", 1)[1])
        product = get_product_admin(product_id)
        if product:
            _save_admin_product_message(query, context)
            await query.edit_message_text(
                format_admin_product_details(product),
                reply_markup=get_product_detail_admin_keyboard(product_id),
                parse_mode="HTML"
            )
        return

    if data.startswith("aeditprod_profit_"):
        product_id = int(data.rsplit("_", 1)[1])
        product = get_product_admin(product_id)
        current_profit = get_product_profit_percent(product) if product else Decimal('0')
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'product_profit_percent'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            f"📈 <b>سود اختصاصی محصول</b>\n\n"
            f"مقدار فعلی: <b>{format_profit_percent(current_profit)}%</b>\n\n"
            "درصد سود جدید را وارد کنید.\n"
            "مثال: <code>5</code> = پنج درصد، <code>1</code> = یک درصد، <code>0.5</code> = نیم درصد، <code>0</code> = بدون سود\n\n"
            "مقدار را دقیق وارد کنید؛ اعداد اعشاری هم پشتیبانی می‌شوند.\n\nبرای لغو /cancel را بزنید.",
            parse_mode="HTML"
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_priceper_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'price_per'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            "✏️ لطفاً تعداد جدید «قیمت به ازای» را وارد کنید:\n\nبرای لغو /cancel را بزنید."
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_min_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'min_order'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            "✏️ لطفاً حداقل سفارش جدید را وارد کنید:\n\nبرای لغو /cancel را بزنید."
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_max_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'max_order'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            "✏️ لطفاً حداکثر سفارش جدید را وارد کنید. برای نامحدود بودن 0 بفرستید:\n\nبرای لغو /cancel را بزنید."
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_category_"):
        product_id = int(data.rsplit("_", 1)[1])
        await query.edit_message_text(
            "📁 <b>دسته‌بندی جدید محصول را انتخاب کنید:</b>",
            reply_markup=get_product_category_edit_keyboard(product_id),
            parse_mode="HTML"
        )
        return

    if data.startswith("aeditprod_target_"):
        product_id = int(data.rsplit("_", 1)[1])
        await query.edit_message_text(
            "📨 <b>نوع اطلاعات سفارش</b>\n\nنوع اطلاعاتی را که مشتری باید برای این محصول ارسال کند انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 لینک کانال/گروه", callback_data=f"asetprodtarget_channel_{product_id}"),
                 InlineKeyboardButton("🆔 آیدی عددی", callback_data=f"asetprodtarget_id_{product_id}")],
                [InlineKeyboardButton("📧 ایمیل", callback_data=f"asetprodtarget_email_{product_id}"),
                 InlineKeyboardButton("👤 یوزرنیم", callback_data=f"asetprodtarget_username_{product_id}")],
                [InlineKeyboardButton("📝 متن دلخواه", callback_data=f"asetprodtarget_custom_{product_id}"),
                 InlineKeyboardButton("🚫 بدون دریافت اطلاعات", callback_data=f"asetprodtarget_none_{product_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"aproductdetail_{product_id}")]
            ]),
            parse_mode="HTML"
        )
        return

    if data.startswith("asetprodtarget_"):
        parts = data.split("_")
        target_type = parts[1]
        product_id = int(parts[2])
        mapped = {'channel':'channel_group','id':'numeric_id','email':'email','username':'username','custom':'custom','none':'none'}
        target_type = mapped.get(target_type, 'custom')
        if update_product(product_id, 'need_link', 0 if target_type == 'none' else 1) and update_product(product_id, 'target_type', target_type):
            await query.answer("✅ نوع اطلاعات سفارش تغییر کرد.", show_alert=True)
            if target_type != 'none':
                context.user_data['edit_product_id'] = product_id
                context.user_data['edit_field'] = 'target_prompt'
                context.user_data['admin_state'] = 'edit_product_value'
                prompt_msg = await query.message.reply_text(
                    "📝 <b>متن جدیدی که مشتری هنگام ثبت سفارش می‌بیند را ارسال کنید:</b>\n\n"
                    "این متن برای نوع اطلاعات انتخاب‌شده نمایش داده می‌شود.\n"
                    "برای لغو /cancel را بزنید.",
                    parse_mode='HTML'
                )
                context.user_data['admin_input_message_id'] = prompt_msg.message_id
                context.user_data['admin_input_chat_id'] = prompt_msg.chat_id
                return ADMIN_EDIT_PRODUCT_VALUE
            product = get_product_admin(product_id)
            if product:
                msg = format_admin_product_details(product)
                await query.message.reply_text("✅ <b>نوع اطلاعات سفارش با موفقیت تغییر کرد.</b>\n\n" + msg, reply_markup=get_product_detail_admin_keyboard(product_id), parse_mode='HTML')
        return

    if data.startswith("aeditprod_prompt_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'target_prompt'
        context.user_data['admin_state'] = 'edit_product_value'
        prompt_msg = await query.message.reply_text("📝 <b>متن جدیدی که مشتری هنگام ثبت سفارش می‌بیند را ارسال کنید:</b>\n\nبرای لغو /cancel را بزنید.", parse_mode='HTML')
        context.user_data['admin_input_message_id'] = prompt_msg.message_id
        context.user_data['admin_input_chat_id'] = prompt_msg.chat_id
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_link_"):
        product_id = int(data.rsplit("_", 1)[1])
        product = get_product(product_id)
        if product:
            new_value = 0 if product[8] else 1
            if update_product(product_id, 'need_link', new_value):
                await query.answer(
                    f"✅ نیاز به لینک: {'بله' if new_value else 'خیر'}",
                    show_alert=True
                )
                # Refresh product details automatically.
                categories = get_all_categories()
                cat_name = next((cat[1] for cat in categories if cat[0] == product[1]), "")
                updated = get_product(product_id)
                message = (
                    f"💰 <b>اطلاعات محصول</b>\n\n"
                    f"🆔 ID: {updated[0]}\n"
                    f"📦 نام: {updated[2]}\n"
                    f"📁 دسته: {cat_name}\n"
                    f"📝 توضیحات: {updated[3] or 'ندارد'}\n"
                    f"💰 قیمت پایه: {format_amount(updated[4])} تومان\n"
                    f"💵 قیمت فروش با سود {get_self_profit_percent():g}%: {format_amount(apply_self_profit(updated[4]))} تومان\n"
                    f"🔢 قیمت به ازای: {updated[5]} عدد\n"
                    f"⬇️ حداقل سفارش: {updated[6]}\n"
                    f"⬆️ حداکثر سفارش: {updated[7] or 'نامحدود'}\n"
                    f"🔗 نیاز به لینک: {'بله' if updated[8] else 'خیر'}\n"
                )
                await query.message.reply_text(
                    "✅ <b>وضعیت نیاز به لینک با موفقیت تغییر کرد.</b>\\n\\n" + message,
                    reply_markup=get_product_detail_admin_keyboard(product_id),
                    parse_mode="HTML"
                )
        return

    if data.startswith("asetprodcat_"):
        parts = data.split("_")
        product_id = int(parts[1])
        category_id = int(parts[2])
        if update_product(product_id, 'category_id', category_id):
            await query.answer("✅ دسته‌بندی محصول تغییر کرد.")
            product = get_product(product_id)
            categories = get_all_categories()
            cat_name = next((cat[1] for cat in categories if cat[0] == product[1]), "")
            message = (
                f"💰 <b>اطلاعات محصول</b>\n\n"
                f"🆔 ID: {product[0]}\n"
                f"📦 نام: {product[2]}\n"
                f"📁 دسته: {cat_name}\n"
                f"📝 توضیحات: {product[3] or 'ندارد'}\n"
                + format_product_admin_price_lines(product) +
                f"🔢 قیمت به ازای: {product[5]} عدد\n"
                f"⬇️ حداقل سفارش: {product[6]}\n"
                f"⬆️ حداکثر سفارش: {product[7] or 'نامحدود'}\n"
                f"🔗 نیاز به لینک: {'بله' if product[8] else 'خیر'}\n"
            )
            await query.message.reply_text(
                "✅ <b>دسته‌بندی محصول با موفقیت تغییر کرد.</b>\\n\\n" + message,
                reply_markup=get_product_detail_admin_keyboard(product_id),
                parse_mode="HTML"
            )
        else:
            await query.answer("❌ خطا در تغییر دسته‌بندی.", show_alert=True)
        return

    if data.startswith("aeditprod_name_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'name'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            "✏️ لطفاً نام جدید محصول را وارد کنید:\n\nبرای لغو /cancel را بزنید."
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_currency_"):
        product_id = int(data.rsplit("_", 1)[1])
        await query.edit_message_text(
            "💱 <b>ارز قیمت محصول را انتخاب کنید:</b>\n\n"
            "نرخ ارز از بخش مدیریت ارزها خوانده می‌شود و مبلغ به تومان برای مشتری محاسبه خواهد شد.",
            reply_markup=get_product_currency_keyboard(product_id), parse_mode="HTML"
        )
        return

    if data.startswith("aproductcurrencyback_"):
        product_id = int(data.rsplit("_", 1)[1])
        for k in ('edit_product_id', 'edit_field', 'edit_currency_code', 'admin_state', 'admin_input_message_id', 'admin_input_chat_id', 'edit_product_prompt_message_id', 'edit_product_prompt_chat_id'):
            context.user_data.pop(k, None)
        product = get_product_admin(product_id)
        if product:
            await query.edit_message_text(
                format_admin_product_details(product),
                reply_markup=get_product_detail_admin_keyboard(product_id),
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text("❌ محصول پیدا نشد.", reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")
        await query.answer("↩️ عملیات لغو شد.")
        return

    if data.startswith("asetprodcurrency_"):
        parts = data.split("_")
        product_id = int(parts[-1])
        code = "_".join(parts[1:-1]).upper()
        currency = get_currency(code)
        if not currency:
            await query.answer("❌ ارز پیدا نشد.", show_alert=True)
            return
        # انتخاب ارز باید همان پیام انتخاب ارز را به فرم ورود مبلغ تبدیل کند.
        product = get_product_admin(product_id)
        current_code, current_currency, current_amount, current_rate = get_product_currency(product) if product else ('TOMAN', {'rate':1}, Decimal('0'), Decimal('1'))
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'price_amount'
        context.user_data['edit_currency_code'] = code
        context.user_data['admin_state'] = 'edit_product_value'
        context.user_data['edit_product_prompt_message_id'] = query.message.message_id
        context.user_data['edit_product_prompt_chat_id'] = query.message.chat_id
        symbol = str(currency.get('symbol') or code)
        rate = Decimal(str(currency.get('rate') or 0))
        preview = f"\n💱 نرخ فعلی: <b>{format_amount(rate)}</b> تومان برای 1 {html.escape(code)}" if rate > 0 else "\n⚠️ برای این ارز هنوز نرخ معتبری ثبت نشده است."
        await query.edit_message_text(
            f"💱 <b>ارز قیمت: {html.escape(str(currency.get('name') or code))}</b> ({html.escape(symbol)})\n\n"
            f"💰 مبلغ فعلی: <b>{format_amount(current_amount)}</b> {html.escape(str(current_currency.get('symbol') or current_code))}\n"
            f"✏️ مبلغ جدید را به <b>{html.escape(code)}</b> وارد کنید.\n"
            f"مثال: <code>1.5</code>{preview}\n\n"
            "بعد از ثبت مبلغ، معادل آن به تومان با نرخ فعلی ارز محاسبه و برای مشتری نمایش داده می‌شود.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت و لغو", callback_data=f"aproductcurrencyback_{product_id}")]]),
            parse_mode="HTML"
        )
        await query.answer("✅ ارز انتخاب شد.")
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_price_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'price'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            f"✏️ لطفاً قیمت پایه جدید محصول را وارد کنید (تومان):\n\n📈 سود اختصاصی محصول: <b>{format_profit_percent(get_product_profit_percent(get_product_admin(product_id)))}%</b> (روی قیمت اعمال می‌شود)\n\nبرای لغو /cancel را بزنید.",
            parse_mode="HTML"
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("aeditprod_desc_"):
        product_id = int(data.rsplit("_", 1)[1])
        context.user_data['edit_product_id'] = product_id
        context.user_data['edit_field'] = 'description'
        context.user_data['admin_state'] = 'edit_product_value'
        await query.message.reply_text(
            "✏️ لطفاً توضیحات جدید محصول را وارد کنید:\n\nبرای لغو /cancel را بزنید."
        )
        return ADMIN_EDIT_PRODUCT_VALUE

    if data.startswith("atoggleprod_"):
        product_id = int(data.rsplit("_", 1)[1])
        conn = get_db_connection()
        if not conn:
            await query.answer("❌ اتصال دیتابیس برقرار نشد.", show_alert=True)
            return
        try:
            cur = conn.cursor()
            cur.execute("SELECT is_active FROM products WHERE id=%s", (product_id,))
            row = cur.fetchone()
            if not row:
                await query.answer("❌ محصول پیدا نشد.", show_alert=True)
                return
            new_status = 0 if int(row[0] or 0) else 1
            cur.execute("UPDATE products SET is_active=%s WHERE id=%s", (new_status, product_id))
            conn.commit()
            await query.answer("✅ محصول فعال شد." if new_status else "⛔️ محصول غیرفعال شد.", show_alert=False)
            product = get_product(product_id) if new_status else None
            # برای محصول غیرفعال، مشخصات را مستقیم از DB بخوان تا صفحه ادمین باز بماند.
            cur.execute("SELECT * FROM products WHERE id=%s", (product_id,))
            product = cur.fetchone()
            if product:
                categories = get_all_categories()
                cat_name = next((cat[1] for cat in categories if cat[0] == product[1]), "")
                status_text = "🟢 فعال" if int(product[9] or 0) else "🔴 غیرفعال"
                message = (f"💰 <b>اطلاعات محصول</b>\n\n"
                           f"🆔 ID: {product[0]}\n📦 نام: {html.escape(str(product[2]))}\n"
                           f"📁 دسته: {html.escape(str(cat_name))}\n📊 وضعیت: <b>{status_text}</b>\n"
                           f"📝 توضیحات: {html.escape(str(product[3] or 'ندارد'))}\n"
                           + format_product_admin_price_lines(product) +
                           f"🔢 قیمت به ازای: {product[5]} عدد\n⬇️ حداقل سفارش: {product[6]}\n"
                           f"⬆️ حداکثر سفارش: {product[7] or 'نامحدود'}\n🔗 نیاز به لینک: {'بله' if product[8] else 'خیر'}")
                await query.message.reply_text(
                    f"✅ <b>وضعیت محصول با موفقیت تغییر کرد.</b>\\n\\n{message}",
                    reply_markup=get_product_detail_admin_keyboard(product_id),
                    parse_mode="HTML"
                )
        except Exception:
            try: conn.rollback()
            except: pass
            logger.exception("failed toggling product active state product_id=%s", product_id)
            await query.answer("❌ تغییر وضعیت محصول انجام نشد.", show_alert=True)
        finally:
            try: cur.close(); conn.close()
            except: pass
        return

    if data.startswith("adeleteprod_"):
        product_id = int(data.rsplit("_", 1)[1])
        product = get_product_admin(product_id)
        if not product:
            await query.answer("❌ محصول پیدا نشد یا قبلاً حذف شده است.", show_alert=True)
            return

        _save_admin_product_message(query, context)
        await query.edit_message_text(
            "⚠️ <b>تأیید حذف محصول</b>\n\n"
            f"📦 محصول: <b>{html.escape(str(product[2]))}</b>\n\n"
            "آیا مطمئنی می‌خواهی این محصول حذف شود؟\n"
            "⚠️ با تأیید، محصول به‌صورت کامل از دیتابیس حذف می‌شود و قابل برگشت نیست.",
            reply_markup=get_product_delete_confirm_keyboard(product_id),
            parse_mode="HTML"
        )
        return

    if data.startswith("aconfirmdeleteprod_"):
        product_id = int(data.rsplit("_", 1)[1])
        if not get_product_admin(product_id):
            await query.answer("❌ محصول پیدا نشد یا قبلاً حذف شده است.", show_alert=True)
            return

        if delete_product(product_id):
            await query.answer("✅ محصول حذف شد.")
            await query.edit_message_text(
                "🗑 <b>محصول با موفقیت حذف شد.</b>\n\n"
                "📋 به لیست محصولات برگشتی.",
                reply_markup=get_products_list_keyboard(1),
                parse_mode="HTML"
            )
        else:
            await query.answer("❌ خطا در حذف محصول.", show_alert=True)
        return

    if data.startswith("acanceldeleteprod_"):
        product_id = int(data.rsplit("_", 1)[1])
        product = get_product_admin(product_id)
        if not product:
            await query.answer("❌ محصول پیدا نشد.", show_alert=True)
            return

        _save_admin_product_message(query, context)
        categories = get_all_categories()
        cat_name = next((cat[1] for cat in categories if cat[0] == product[1]), "")
        message = (
            f"💰 <b>اطلاعات محصول</b>\n\n"
            f"🆔 ID: {product[0]}\n"
            f"📦 نام: {html.escape(str(product[2]))}\n"
            f"📁 دسته: {html.escape(str(cat_name))}\n"
            f"📝 توضیحات: {html.escape(str(product[3] or 'ندارد'))}\n"
            + format_product_admin_price_lines(product) +
            f"🔢 قیمت به ازای: {product[5]} عدد\n"
            f"⬇️ حداقل سفارش: {product[6]}\n"
            f"⬆️ حداکثر سفارش: {product[7] or 'نامحدود'}\n"
            f"🔗 نیاز به لینک: {'بله' if product[8] else 'خیر'}\n"
        )
        await query.edit_message_text(
            message,
            reply_markup=get_product_detail_admin_keyboard(product_id),
            parse_mode="HTML"
        )
        await query.answer("لغو شد.")
        return

    # مدیریت سفارشات
    if data == "apanel_orders_menu":
        await query.edit_message_text(
            "📋 <b>مدیریت سفارشات</b>\n\n"
            "👈 یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=get_admin_orders_menu_keyboard(),
            parse_mode="HTML"
        )
        return

    if data.startswith("aorders_"):
        parts = data.split("_")
        status = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 1

        status_map = {
            'pending': '⏳ سفارشات در انتظار',
            'confirmed': '✅ سفارشات تایید شده',
            'completed': '🎉 سفارشات تکمیل شده',
            'cancelled': '❌ سفارشات لغو شده',
            'all': '📋 همه سفارشات'
        }

        title = status_map.get(status, 'سفارشات')
        orders, total = get_orders_by_status(status if status != 'all' else None, page)

        message = f"📋 <b>{title}</b> - صفحه {page}\n\n"
        if orders:
            for order in orders:
                oid = order[0]
                pname = order[4][:25] + "..." if len(order[4]) > 25 else order[4]
                uname = order[12][:15] if order[12] else "Unknown"
                status_emoji = "⏳" if order[9] == 'pending' else ("✅" if order[9] == 'confirmed' else ("🎉" if order[9] == 'completed' else "❌"))
                message += f"{status_emoji} <code>{order[1]}</code> - {pname} - {uname} - 💰{format_amount(order[8])} تومان\n"
        else:
            message += "❌ سفارشی یافت نشد."

        await query.edit_message_text(
            message,
            reply_markup=get_admin_orders_keyboard(status, page, total),
            parse_mode="HTML"
        )
        return

    if data.startswith("aorderdetail_"):
        order_id = int(data.split("_")[1])
        order = get_order(order_id)
        if order:
            status_map = {
                'pending': '⏳ در انتظار',
                'confirmed': '✅ تایید شده',
                'completed': '🎉 تکمیل شده',
                'cancelled': '❌ لغو شده'
            }
            status = status_map.get(order[9], order[9])
            message = (
                f"📦 <b>جزئیات سفارش #{order_id}</b>\n\n"
                f"🔢 کد پیگیری: <code>{order[1]}</code>\n"
                f"👤 کاربر: <code>{order[2]}</code>\n"
                f"📦 محصول: {order[4]}\n"
                f"🔢 تعداد: {order[6]:,}\n"
                f"💰 قیمت واحد: {format_amount(order[7])} تومان\n"
                f"💎 قیمت کل: {format_amount(order[8])} تومان\n"
                f"📊 وضعیت: {status}\n"
                f"📅 تاریخ: {order[11]}\n"
            )
            if order[5]:
                message += f"🔗 لینک: {order[5]}\n"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_orders_menu")],
            ])
            if order[9] == 'pending':
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تایید سفارش", callback_data=f"confirmorder_{order_id}"),
                     InlineKeyboardButton("❌ لغو سفارش", callback_data=f"rejectorder_{order_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_orders_menu")],
                ])
            elif order[9] == 'confirmed':
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎉 تکمیل سفارش", callback_data=f"completeorder_{order_id}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="apanel_orders_menu")],
                ])

            await query.edit_message_text(message, reply_markup=keyboard, parse_mode="HTML")

    if data in ("aproduct_needlink_yes", "aproduct_needlink_no"):
        context.user_data["new_product_need_link"] = 1 if data.endswith("_yes") else 0
        # Finish product registration using the existing need-link handler logic.
        await query.answer()
        return await finalize_admin_product_registration(query, context)

    return

# ==================== هندلرهای مدیریت محصولات ====================

def _save_admin_product_message(query, context):
    """ذخیره همان پیام پنل که باید در تمام مراحل ادیت شود."""
    context.user_data['admin_product_message_id'] = query.message.message_id
    context.user_data['admin_product_chat_id'] = query.message.chat_id


def _clear_admin_product_state(context):
    for key in (
        'admin_product_message_id', 'admin_product_chat_id',
        'admin_state',
        'new_category_name',
        'new_product_category', 'new_product_name', 'new_product_description',
        'new_product_price', 'new_product_price_amount', 'new_product_currency', 'new_product_profit_percent', 'new_product_price_per',
        'new_product_min_order', 'new_product_max_order',
        'new_product_need_link',
    ):
        context.user_data.pop(key, None)


def _admin_product_back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔙 مدیریت محصولات', callback_data='apanel_products')]
    ])


def _admin_product_need_link_keyboard():
    """دکمه‌های بله/خیر برای مرحله نیاز داشتن محصول به لینک."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('✅ بله', callback_data='aaddprodlink_yes'),
            InlineKeyboardButton('❌ خیر', callback_data='aaddprodlink_no'),
        ],
        [InlineKeyboardButton('🔙 مدیریت محصولات', callback_data='apanel_products')],
    ])


async def _edit_admin_product_message(context, text, reply_markup=None):
    message_id = context.user_data.get('admin_product_message_id')
    chat_id = context.user_data.get('admin_product_chat_id')
    if not message_id or not chat_id:
        return False
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return True
    except BadRequest as e:
        # اگر متن و دکمه‌ها دقیقاً مثل قبل باشند، تلگرام خطای Message is not modified می‌دهد.
        # این خطا برای ما خطای واقعی نیست و نباید لاگ/پیام اضافی ایجاد کند.
        if 'Message is not modified' in str(e):
            return True
        logger.exception('failed editing admin product message')
        return False
    except Exception:
        logger.exception('failed editing admin product message')
        return False

async def handle_admin_add_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    if not text:
        await _edit_admin_product_message(
            context,
            '➕ <b>افزودن دسته‌بندی</b>\n\n'
            '❌ نام دسته‌بندی نمی‌تواند خالی باشد.\n\n'
            '📝 لطفاً نام دسته‌بندی جدید را وارد کنید:',
            _admin_product_back_keyboard()
        )
        return ADMIN_ADD_CATEGORY_NAME

    context.user_data['new_category_name'] = text


    await update.message.reply_text(
        '➕ <b>افزودن دسته‌بندی</b>\n\n'
        f'📁 نام: <b>{html.escape(text)}</b>\n\n'
        '📝 لطفاً ایموجی دسته‌بندی را وارد کنید:\n'
        'مثال: 📱\n\n'
        'برای رد شدن، /skip را بزنید.',
        reply_markup=_admin_product_back_keyboard(),
        parse_mode="HTML"
    )
    return ADMIN_ADD_CATEGORY_EMOJI


async def handle_admin_add_category_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    emoji = text if text != '/skip' else ''
    name = context.user_data.get('new_category_name', '')

    category_id = add_category(name, emoji)


    if category_id:
        message = (
            '✅ <b>دسته‌بندی با موفقیت اضافه شد</b>\n\n'
            f'📁 نام: <b>{html.escape(name)}</b>\n'
            f'🔹 ایموجی: {html.escape(emoji) if emoji else "📦"}\n'
            f'🆔 شناسه: <code>{category_id}</code>\n\n'
            '📦 <b>مدیریت محصولات و دسته‌بندی‌ها</b>'
        )
        await _edit_admin_product_message(
            context, message, get_admin_products_management_keyboard()
        )
    else:
        await _edit_admin_product_message(
            context,
            '❌ <b>خطا در افزودن دسته‌بندی</b>\n\nلطفاً دوباره تلاش کنید.',
            _admin_product_back_keyboard()
        )

    _clear_admin_product_state(context)
    return ConversationHandler.END


async def handle_admin_edit_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    category_id = context.user_data.get('edit_category_id')
    if category_id:
        if update_category(category_id, name=text):
            await update.message.reply_text(f'✅ نام دسته‌بندی به «{text}» تغییر کرد.')
        else:
            await update.message.reply_text('❌ خطا در ویرایش.')

    return ConversationHandler.END



async def finalize_admin_product_registration(query, context):
    category_id = context.user_data.get("new_product_category")
    name = context.user_data.get("new_product_name", "")
    description = context.user_data.get("new_product_description", "")
    price = context.user_data.get("new_product_price", 0)
    price_amount = context.user_data.get("new_product_price_amount", price)
    price_currency = str(context.user_data.get("new_product_currency") or "TOMAN").upper()
    price_per = context.user_data.get("new_product_price_per", 1)
    min_order = context.user_data.get("new_product_min_order", 1)
    max_order = context.user_data.get("new_product_max_order")
    need_link = context.user_data.get("new_product_need_link", 0)
    product_profit_percent = context.user_data.get("new_product_profit_percent", Decimal(str(get_self_profit_percent() or 0)))

    try:
        product_id = add_product(
            category_id, name, description, price, price_per,
            min_order, max_order, need_link, price_currency, price_amount, product_profit_percent
        )
        category = get_category(category_id)
        category_name = category["name"] if category else "نامشخص"

        text = (
            "✅ <b>محصول با موفقیت اضافه شد</b>\n\n"
            f"📂 دسته‌بندی: <b>{html.escape(category_name)}</b>\n"
            f"📦 نام: <b>{html.escape(name)}</b>\n"
            f"💰 قیمت پایه: <b>{format_amount(price_amount)}</b> {html.escape(price_currency)}\n"
            f"💵 معادل فعلی: <b>{format_amount(price)}</b> تومان\n"
            f"📈 سود محصول: <b>{format_profit_percent(product_profit_percent)}%</b>\n"
            f"🔢 به ازای: <b>{price_per:,.0f}</b> عدد\n"
            f"⬇️ حداقل سفارش: <b>{min_order:,}</b>\n"
            f"⬆️ حداکثر سفارش: <b>{max_order:,}</b>\n"
            f"🔗 نیاز به لینک: <b>{'بله' if need_link else 'خیر'}</b>"
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=get_admin_products_management_keyboard()
        )
        for key in [
            "new_product_category", "new_product_name", "new_product_description",
            "new_product_price", "new_product_price_per", "new_product_min_order",
            "new_product_max_order", "new_product_need_link", "admin_state"
        ]:
            context.user_data.pop(key, None)
    except Exception as e:
        logger.exception("failed registering product")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ خطا در ثبت محصول: {e}"
        )

async def handle_admin_add_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    if not text:
        await update.message.reply_text(

            '➕ <b>افزودن محصول</b>\n\n'
            '❌ نام محصول نمی‌تواند خالی باشد.\n\n'
            '📝 لطفاً نام محصول را وارد کنید:',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_NAME

    context.user_data['new_product_name'] = text


    await update.message.reply_text(

        '➕ <b>افزودن محصول</b>\n\n'
        f'📦 نام: <b>{html.escape(text)}</b>\n\n'
        '📝 لطفاً توضیحات محصول را وارد کنید:\n\n'
        'برای رد شدن، /skip را بزنید.',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
    return ADMIN_ADD_PRODUCT_DESCRIPTION


async def handle_admin_add_product_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    description = text if text != '/skip' else ''
    context.user_data['new_product_description'] = description


    await update.message.reply_text(

        '➕ <b>افزودن محصول</b>\n\n'
        f'📦 محصول: <b>{html.escape(context.user_data.get("new_product_name", ""))}</b>\n'
        f'📝 توضیحات: <b>{html.escape(description) if description else "ندارد"}</b>\n\n'
        '💱 لطفاً ارز قیمت محصول را انتخاب کنید:',
        reply_markup=get_product_currency_keyboard_for_add(),
        parse_mode="HTML"
    )
    return ADMIN_ADD_PRODUCT_CURRENCY


def get_product_currency_keyboard_for_add():
    currencies = get_all_currencies() or []
    rows = []
    for c in currencies:
        code = str(c.get('code') or '').upper()
        if not code:
            continue
        symbol = c.get('symbol') or code
        button = InlineKeyboardButton(f"{symbol} {code}", callback_data=f"aaddprod_currency_{code}")
        if rows and len(rows[-1]) == 1:
            rows[-1].append(button)
        else:
            rows.append([button])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="acancel_input")])
    return InlineKeyboardMarkup(rows)

async def handle_admin_add_product_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This stage is selected via inline buttons; text fallback accepts currency code.
    text = (update.message.text or '').strip().upper()
    if text in ['/START', '/CANCEL']:
        return await cancel_operation(update, context)
    currency = get_currency(text)
    if not currency:
        await update.message.reply_text('❌ ارز پیدا نشد. از دکمه‌های انتخاب ارز استفاده کنید.', reply_markup=get_product_currency_keyboard_for_add())
        return ADMIN_ADD_PRODUCT_CURRENCY
    return await _start_add_product_price_input(update.message, context, text)

async def _start_add_product_price_input(message, context, code):
    currency = get_currency(code)
    context.user_data['new_product_currency'] = code
    unit = 'تومان' if code == 'TOMAN' else (currency.get('symbol') or code)
    example = '2650000' if code == 'TOMAN' else '0.0052215'
    await message.reply_text(
        '➕ <b>افزودن محصول</b>\n\n'
        f'💱 ارز: <b>{html.escape(str(code))}</b>\n'
        f'💰 لطفاً مبلغ قیمت را به {html.escape(str(unit))} وارد کنید.\n'
        f'مثال: <code>{example}</code>\n\n'
        f'📈 سود فعلی شما: <b>{get_self_profit_percent():g}%</b> (روی قیمت اعمال می‌شود)',
        reply_markup=_admin_product_back_keyboard(), parse_mode='HTML'
    )
    return ADMIN_ADD_PRODUCT_PRICE

async def handle_admin_add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    code = str(context.user_data.get('new_product_currency') or 'TOMAN').upper()
    try:
        amount = Decimal(text.replace(',', '').replace('٬', '').strip())
        if amount <= 0:
            raise ValueError
        context.user_data['new_product_price_amount'] = amount
        currency = get_currency(code) if code != 'TOMAN' else {'rate':1,'symbol':'تومان','name':'تومان'}
        rate = Decimal(str(currency.get('rate') or 1))
        price = int((amount * rate).to_integral_value(rounding=ROUND_CEILING))
        context.user_data['new_product_price'] = price
    except Exception:
        await update.message.reply_text(

            '➕ <b>افزودن محصول</b>\n\n'
            '❌ لطفاً فقط یک عدد معتبر و بیشتر از صفر وارد کنید:\n\n'
            '💰 قیمت پایه محصول را به تومان وارد کنید:',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_PRICE


    await update.message.reply_text(

        '➕ <b>افزودن محصول</b>\n\n'
        f'💰 قیمت پایه: <b>{format_amount(context.user_data.get("new_product_price_amount", price))}</b> {html.escape(str(code))}\n'
        f'💵 معادل فعلی: <b>{format_amount(price)}</b> تومان\n\n'
        '🔢 لطفاً تعداد واحد برای این قیمت را وارد کنید:\n\n'
        'مثال: اگر قیمت برای 1000 عدد است، <code>1000</code> وارد کنید.\n'
        'برای 1 عدد، /skip را بزنید.',
        reply_markup=_admin_product_back_keyboard(),
        parse_mode="HTML"
    )
    return ADMIN_ADD_PRODUCT_PRICE_PER


async def handle_admin_add_product_price_per(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    try:
        price_per = int(text) if text != '/skip' else 1
        if price_per <= 0:
            raise ValueError
        context.user_data['new_product_price_per'] = price_per
    except Exception:
        await update.message.reply_text(

            '➕ <b>افزودن محصول</b>\n\n'
            '❌ لطفاً فقط عدد معتبر و بیشتر از صفر وارد کنید:\n\n'
            '🔢 تعداد واحد برای قیمت را وارد کنید:',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_PRICE_PER


    context.user_data['new_product_profit_percent'] = Decimal(str(get_self_profit_percent() or 0))
    await update.message.reply_text(
        '➕ <b>افزودن محصول</b>\n\n'
        f'💰 قیمت: <b>{context.user_data["new_product_price"]:,}</b> تومان\n'
        f'🔢 به ازای: <b>{price_per:,}</b> عدد\n\n'
        '📈 لطفاً درصد سود این محصول را وارد کنید.\n\n'
        'مثال: <code>5</code> = ۵٪، <code>1</code> = ۱٪، <code>0.5</code> = ۰.۵٪، <code>0</code> = بدون سود\n'
        f'سود پیش‌فرض: <b>{format_profit_percent(context.user_data["new_product_profit_percent"])}%</b>\n\n'
        'برای لغو /cancel را بزنید.',
        reply_markup=_admin_product_back_keyboard(),
        parse_mode="HTML"
    )
    context.user_data['admin_state'] = 'add_product_profit'
    return ADMIN_ADD_PRODUCT_PROFIT


async def handle_admin_add_product_profit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)
    try:
        profit = Decimal(text.replace(',', '.').replace('٬', '').replace('٪', '').strip())
        if profit < 0 or profit > Decimal('1000'):
            raise ValueError
        context.user_data['new_product_profit_percent'] = profit
    except Exception:
        await update.message.reply_text(
            '❌ درصد سود نامعتبر است. یک عدد بین 0 تا 1000 وارد کنید.\n\n'
            'مثال: <code>5</code>، <code>1</code>، <code>0.5</code> یا <code>0</code>',
            reply_markup=_admin_product_back_keyboard(), parse_mode='HTML'
        )
        return ADMIN_ADD_PRODUCT_PROFIT

    await update.message.reply_text(
        '➕ <b>افزودن محصول</b>\n\n'
        f'📈 سود محصول: <b>{format_profit_percent(profit)}%</b>\n\n'
        '⬇️ لطفاً حداقل تعداد سفارش را وارد کنید:',
        reply_markup=_admin_product_back_keyboard(), parse_mode='HTML'
    )
    context.user_data['admin_state'] = 'add_product_min_order'
    return ADMIN_ADD_PRODUCT_MIN_ORDER


async def handle_admin_add_product_min_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    try:
        min_order = int(text.replace(',', '').replace('٬', '').strip())
        if min_order <= 0:
            raise ValueError
        context.user_data['new_product_min_order'] = min_order
    except Exception:
        await update.message.reply_text(

            '➕ <b>افزودن محصول</b>\n\n'
            '❌ لطفاً فقط عدد معتبر و بیشتر از صفر وارد کنید:\n\n'
            '⬇️ حداقل تعداد سفارش را وارد کنید:',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_MIN_ORDER


    await update.message.reply_text(

        '➕ <b>افزودن محصول</b>\n\n'
        f'⬇️ حداقل سفارش: <b>{min_order:,}</b>\n\n'
        '⬆️ لطفاً حداکثر تعداد سفارش را وارد کنید:\n\n'
        'برای بدون محدودیت /skip را بزنید.',
        reply_markup=_admin_product_back_keyboard(),
        parse_mode="HTML"
    )
    return ADMIN_ADD_PRODUCT_MAX_ORDER


async def handle_admin_add_product_max_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    try:
        max_order = int(text.replace(',', '').replace('٬', '').strip()) if text != '/skip' else None
        if max_order is not None and max_order <= 0:
            raise ValueError

        min_order = context.user_data.get('new_product_min_order', 1)
        if max_order is not None and max_order < min_order:
            await _edit_admin_product_message(
                context,
                '➕ <b>افزودن محصول</b>\n\n'
                '❌ حداکثر سفارش نمی‌تواند کمتر از حداقل سفارش باشد.\n\n'
                f'⬇️ حداقل: <b>{min_order:,}</b>\n\n'
                '⬆️ لطفاً حداکثر تعداد سفارش را وارد کنید:',
                reply_markup=_admin_product_back_keyboard()
            )
            return ADMIN_ADD_PRODUCT_MAX_ORDER

        context.user_data['new_product_max_order'] = max_order
    except Exception:
        await update.message.reply_text(

            '➕ <b>افزودن محصول</b>\n\n'
            '❌ لطفاً عدد معتبر وارد کنید.\n\n'
            '⬆️ حداکثر تعداد سفارش را وارد کنید:\n\n'
            'برای بدون محدودیت /skip را بزنید.',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_MAX_ORDER


    max_text = 'نامحدود' if max_order is None else f'{max_order:,}'
    await update.message.reply_text(
        '➕ <b>افزودن محصول</b>\n\n'
        f'⬇️ حداقل سفارش: <b>{context.user_data["new_product_min_order"]:,}</b>\n'
        f'⬆️ حداکثر سفارش: <b>{max_text}</b>\n\n'
        '🔗 آیا محصول نیاز به لینک دارد؟\n\n'
        'یکی از دکمه‌های <b>بله</b> یا <b>خیر</b> را بزنید.',
        reply_markup=_admin_product_need_link_keyboard(),
        parse_mode="HTML"
    )
    context.user_data['admin_state'] = 'add_product_need_link'
    return ADMIN_ADD_PRODUCT_NEED_LINK


async def _complete_admin_add_product(message, context, need_link):
    """ثبت نهایی محصول؛ مشترک بین دکمه‌های اینلاین و ورودی متنی."""
    category_id = context.user_data.get('new_product_category')
    name = context.user_data.get('new_product_name', '')
    description = context.user_data.get('new_product_description', '')
    price = context.user_data.get('new_product_price', 0)
    price_amount = context.user_data.get('new_product_price_amount', price)
    price_currency = str(context.user_data.get('new_product_currency') or 'TOMAN').upper()
    price_per = context.user_data.get('new_product_price_per', 1)
    min_order = context.user_data.get('new_product_min_order', 1)
    max_order = context.user_data.get('new_product_max_order')

    product_id = add_product(
        category_id, name, description, price,
        price_per, min_order, max_order, int(bool(need_link)), price_currency, price_amount, context.user_data.get('new_product_profit_percent', Decimal(str(get_self_profit_percent() or 0)))
    )

    if product_id:
        max_text = 'نامحدود' if max_order is None else f'{max_order:,}'
        result_text = (
            '✅ <b>محصول با موفقیت اضافه شد</b>\n\n'
            f'📦 نام: <b>{html.escape(name)}</b>\n'
            f'💰 قیمت پایه: <b>{format_amount(price_amount)}</b> {html.escape(price_currency)}\n'
            f'💵 معادل فعلی: <b>{format_amount(price)}</b> تومان\n'
            f'📈 سود محصول: <b>{format_profit_percent(context.user_data.get("new_product_profit_percent", 0))}%</b>\n'
            f'🔢 به ازای: <b>{price_per:,}</b> عدد\n'
            f'⬇️ حداقل سفارش: <b>{min_order:,}</b>\n'
            f'⬆️ حداکثر سفارش: <b>{max_text}</b>\n'
            f'🔗 نیاز به لینک: <b>{"بله" if need_link else "خیر"}</b>\n\n'
            '📦 <b>مدیریت محصولات و دسته‌بندی‌ها</b>'
        )
        await message.reply_text(
            result_text,
            reply_markup=get_admin_products_management_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message.reply_text(
            '❌ <b>خطا در افزودن محصول</b>\n\nلطفاً دوباره تلاش کنید.',
            reply_markup=_admin_product_back_keyboard(),
            parse_mode="HTML"
        )

    _clear_admin_product_state(context)
    return ConversationHandler.END


async def handle_admin_add_product_need_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ورودی متنی را هم برای سازگاری نگه می‌داریم، ولی حالت اصلی دکمه‌ای است.
    text = (update.message.text or '').strip().lower()

    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    if text not in ['بله', 'خیر', 'yes', 'no', 'y', 'n', '1', '0']:
        await update.message.reply_text(
            '➕ <b>افزودن محصول</b>\n\n'
            '❌ لطفاً یکی از دکمه‌های <b>بله</b> یا <b>خیر</b> را بزنید.\n\n'
            '🔗 آیا محصول نیاز به لینک دارد؟',
            reply_markup=_admin_product_need_link_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_ADD_PRODUCT_NEED_LINK

    need_link = text in ['بله', 'yes', 'y', '1']
    return await _complete_admin_add_product(update.message, context, need_link)


async def handle_admin_edit_product_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_value = update.message.text

    if text_value in ["/start", "/cancel"]:
        return await cancel_operation(update, context)

    product_id = context.user_data.get('edit_product_id')
    field = context.user_data.get('edit_field')

    if not product_id or not field:
        return ConversationHandler.END

    numeric_fields = {'price', 'price_amount', 'price_per', 'min_order', 'max_order', 'product_profit_percent'}

    if field in numeric_fields:
        try:
            if field in ('price_amount', 'product_profit_percent'):
                value = Decimal(text_value.replace(',', '').replace('٬', '').strip())
                if value < 0:
                    raise ValueError
                if field == 'price_amount' and value == 0:
                    raise ValueError
                if field == 'product_profit_percent' and value > Decimal('1000'):
                    raise ValueError
            else:
                value = int(text_value.replace(",", "").replace('٬', '').strip())
                if value < 0:
                    raise ValueError
        except Exception:
            await update.message.reply_text("❌ لطفاً فقط یک عدد معتبر وارد کنید:")
            return ADMIN_EDIT_PRODUCT_VALUE

        if field == 'price_per' and value == 0:
            await update.message.reply_text("❌ «قیمت به ازای» نمی‌تواند صفر باشد:")
            return ADMIN_EDIT_PRODUCT_VALUE

        if field == 'min_order' and value == 0:
            await update.message.reply_text("❌ حداقل سفارش باید بیشتر از صفر باشد:")
            return ADMIN_EDIT_PRODUCT_VALUE

    else:
        # برای متن دلخواه، فاصله‌ها و خط‌های جدید دقیقاً همان‌طور که ادمین فرستاده حفظ شوند.
        value = text_value if field == 'target_prompt' else text_value.strip()
        if not value:
            await update.message.reply_text("❌ مقدار نمی‌تواند خالی باشد:")
            return ADMIN_EDIT_PRODUCT_VALUE

    if field == 'price_amount':
        product_before = get_product_admin(product_id)
        code = str(context.user_data.get('edit_currency_code') or (product_before[12] if product_before and len(product_before) > 12 else 'TOMAN')).upper()
        currency = get_currency(code) if code != 'TOMAN' else {'rate':1}
        rate = Decimal(str(currency.get('rate') or 1))
        toman_price = int((Decimal(str(value)) * rate).to_integral_value(rounding=ROUND_CEILING))
        ok = (update_product(product_id, 'price_currency', code) and update_product(product_id, 'price_amount', value) and update_product(product_id, 'price', toman_price))
    else:
        ok = update_product(product_id, field, value)

    if ok:
        product = get_product(product_id)
        categories = get_all_categories()
        cat_name = next((cat[1] for cat in categories if cat[0] == product[1]), "")

        field_names = {
            'name': 'نام',
            'description': 'توضیحات',
            'price': 'قیمت پایه',
            'price_amount': 'قیمت محصول',
            'product_profit_percent': 'سود اختصاصی',
            'price_per': 'قیمت به ازای',
            'min_order': 'حداقل سفارش',
            'max_order': 'حداکثر سفارش',
            'target_prompt': 'متن درخواست',
        }
        changed_name = field_names.get(field, 'اطلاعات محصول')

        message = (
            f"✅ <b>{html.escape(changed_name)} محصول با موفقیت تغییر کرد.</b>\n\n"
            + format_admin_product_details(product)
        )

        # اگر ویرایش قیمت ارزی از روی پیام محصول شروع شده، همان پیام را بروزرسانی کن.
        prompt_message_id = context.user_data.get('edit_product_prompt_message_id')
        prompt_chat_id = context.user_data.get('edit_product_prompt_chat_id') or update.effective_chat.id
        if field == 'price_amount' and prompt_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=prompt_chat_id,
                    message_id=prompt_message_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=get_product_detail_admin_keyboard(product_id)
                )
            except Exception:
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_product_detail_admin_keyboard(product_id))
        else:
            await update.message.reply_text(
                message,
                parse_mode="HTML",
                reply_markup=get_product_detail_admin_keyboard(product_id)
            )
    else:
        await update.message.reply_text("❌ خطا در ویرایش.")

    context.user_data.pop('edit_product_id', None)
    context.user_data.pop('edit_field', None)
    context.user_data.pop('edit_currency_code', None)
    context.user_data.pop('edit_product_prompt_message_id', None)
    context.user_data.pop('edit_product_prompt_chat_id', None)
    return ConversationHandler.END


async def handle_admin_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.message.text or '').strip()
    if text in ['/start','/cancel']: return await cancel_operation(update,context)
    try: amount=int(text.replace(',','').replace('٬','').replace(' ',''))
    except ValueError:
        await _edit_admin_input_prompt(
            context,
            "💰 <b>تغییر موجودی کاربر</b>\n\n❌ فقط عدد وارد کنید.\n\nمثال: <code>50000</code> یا <code>-20000</code>",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]])
        )
        return ADMIN_AMOUNT_INPUT
    if amount==0:
        await _edit_admin_input_prompt(
            context,
            "💰 <b>تغییر موجودی کاربر</b>\n\n❌ مبلغ نمی‌تواند صفر باشد.\n\nمثال: <code>50000</code> یا <code>-20000</code>",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]])
        )
        return ADMIN_AMOUNT_INPUT
    uid=context.user_data.get('balance_user_id')
    user_data=get_user_data(uid) if uid else None
    if not user_data:
        await _edit_admin_input_prompt(context, "❌ کاربر هدف مشخص نیست.", InlineKeyboardMarkup([[InlineKeyboardButton("🏠 پنل اصلی", callback_data="apanel_main")]]))
        return ConversationHandler.END
    old=int(user_data.get('balance') or 0); new=old+amount
    if new<0:
        await _edit_admin_input_prompt(
            context,
            f"💰 <b>تغییر موجودی کاربر</b>\n\n❌ موجودی منفی می‌شود.\n💳 موجودی فعلی: <b>{format_amount(old)} تومان</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]])
        )
        return ADMIN_AMOUNT_INPUT
    if not update_user_balance(uid,amount):
        await _edit_admin_input_prompt(context, "❌ خطا در تغییر موجودی.", InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]]))
        return ConversationHandler.END
    tx_type='deposit' if amount>0 else 'withdraw'; tracking=f"admin:{update.effective_user.id}:{generate_payment_tracking()}"
    save_transaction(uid,amount,tx_type,f"{'افزایش' if amount>0 else 'کاهش'} موجودی توسط مدیریت (ادمین: {update.effective_user.id})",tracking)
    fresh=get_user_data(uid); new=int(fresh.get('balance') or new) if fresh else new
    input_chat_id = context.user_data.get('admin_input_chat_id', update.effective_chat.id)
    input_message_id = context.user_data.get('admin_input_message_id')
    await _restore_admin_user_detail(context, uid, input_chat_id, input_message_id)
    try:
        await update.message.delete()
    except Exception:
        pass
    for key in ('balance_user_id', 'admin_input_user_id', 'admin_input_chat_id', 'admin_input_message_id'):
        context.user_data.pop(key, None)
    try:
        await context.bot.send_message(uid,f"💳 <b>تغییر موجودی حساب</b>\n\n{'➕' if amount>0 else '➖'} مبلغ: <b>{format_amount(abs(amount))} تومان</b>\n💰 موجودی جدید: <b>{format_amount(new)} تومان</b>",parse_mode='HTML')
    except Exception: logger.exception('failed notifying balance change user=%s',uid)
    return ConversationHandler.END


async def handle_admin_ban_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)

    user_id = context.user_data.get('ban_user_id')
    reason = (text or '').strip()
    if not reason:
        await _edit_admin_input_prompt(
            context,
            f"🚫 <b>بن کاربر</b>\n\n🆔 کاربر: <code>{user_id}</code>\n\n❌ دلیل بن نمی‌تواند خالی باشد.\n\n📝 دلیل را همینجا ارسال کنید:",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]])
        )
        return ADMIN_BAN_USER

    if ban_user(user_id, reason):
        await _restore_admin_user_detail(
            context,
            user_id,
            context.user_data.get('admin_input_chat_id', update.effective_chat.id),
            context.user_data.get('admin_input_message_id')
        )
        try:
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"⛔️ اکانت شما مسدود شد ❌\n\n📝 دلیل: {reason}\n\n🆔 {SUPPORT_USERNAME}"
            )
        except: pass
        try:
            await update.message.delete()
        except Exception:
            pass
        for key in ('ban_user_id', 'admin_input_user_id', 'admin_input_chat_id', 'admin_input_message_id'):
            context.user_data.pop(key, None)
    else:
        await _edit_admin_input_prompt(
            context,
            "❌ خطا در بن کاربر.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="acancel_input")]])
        )
        return ADMIN_BAN_USER

    return ConversationHandler.END

def get_lottery_target_count(target_type='all', target_value=0):
    conn = get_db_connection()
    if not conn:
        return 0

    try:
        cur = conn.cursor()
        conditions = ["is_banned = 0", "is_blocked = 0"]
        params = []

        conditions_map = {
            'verified': "is_verified = 1",
            'unverified': "is_verified = 0",
            'rules_pending': "rules_accepted = 0",
            'buyers': "total_purchases >= 1",
            'no_buyers': "total_purchases = 0",
            'referrers': "subsets_count >= 1",
            'no_referrals': "subsets_count = 0",
            'new_today': "created_at >= CURDATE()",
            'new_week': "created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)",
            'new_month': "created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)",
            'active': "is_blocked = 0 AND is_banned = 0 AND last_activity_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)",
            'banned': "is_banned = 1",
            'blocked': "is_blocked = 1",
            'paid': "COALESCE(total_payments,0) > 0",
            'no_payments': "COALESCE(total_payments,0) = 0",
            'positive_balance': "COALESCE(balance,0) > 0",
            'zero_balance': "COALESCE(balance,0) = 0",
            'inactive_7': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 7 DAY)",
            'inactive_30': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 30 DAY)",
            'inactive_90': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 90 DAY)",
            'inactive_180': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 180 DAY)",
            'inactive_365': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 365 DAY)",
            'inactive_60': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 60 DAY)",
            'never_active': "last_activity_at IS NULL",
            'new_3_month': "created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)",
            'new_6_month': "created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)",
            'new_year': "created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)",
            'top_purchases': "COALESCE(total_purchases,0) > 0",
            'top_referrals': "COALESCE(subsets_count,0) > 0",
            'top_income': "COALESCE(income,0) > 0",
            'top_balance': "COALESCE(balance,0) > 0",
            'lottery_winners': "EXISTS (SELECT 1 FROM lottery_runs lr WHERE lr.winner_id = users.user_id)",
            'gift_users': "EXISTS (SELECT 1 FROM gift_code_uses gcu WHERE gcu.user_id = users.user_id)",
        }

        if target_type == 'min_referrals':
            conditions.append("subsets_count >= %s")
            params.append(int(target_value))
        elif target_type == 'min_purchases':
            conditions.append("total_purchases >= %s")
            params.append(int(target_value))
        elif target_type == 'high_referrals':
            conditions.append("subsets_count > %s")
            params.append(int(target_value))
        elif target_type == 'high_purchases':
            conditions.append("total_purchases > %s")
            params.append(int(target_value))
        elif target_type in conditions_map:
            conditions.append(conditions_map[target_type])

        cur.execute(
            "SELECT COUNT(*) FROM users WHERE " + " AND ".join(conditions),
            tuple(params)
        )
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        logger.exception("get_lottery_target_count failed target=%s value=%s", target_type, target_value)
        return 0
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def lottery_eligibility_keyboard():
    return get_unified_user_target_keyboard('alottery_target_', 'lottery', None, None)

def get_lottery_candidates(target_type='all', target_value=0):
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        conditions = ["is_banned = 0", "is_blocked = 0"]
        params = []

        conditions_map = {
            'verified': "is_verified = 1",
            'unverified': "is_verified = 0",
            'rules_pending': "rules_accepted = 0",
            'buyers': "total_purchases >= 1",
            'no_buyers': "total_purchases = 0",
            'referrers': "subsets_count >= 1",
            'no_referrals': "subsets_count = 0",
            'new_today': "created_at >= CURDATE()",
            'new_week': "created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)",
            'new_month': "created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)",
            'active': "is_blocked = 0 AND is_banned = 0 AND last_activity_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)",
            'banned': "is_banned = 1",
            'blocked': "is_blocked = 1",
            'paid': "COALESCE(total_payments,0) > 0",
            'no_payments': "COALESCE(total_payments,0) = 0",
            'positive_balance': "COALESCE(balance,0) > 0",
            'zero_balance': "COALESCE(balance,0) = 0",
            'inactive_7': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 7 DAY)",
            'inactive_30': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 30 DAY)",
            'inactive_90': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 90 DAY)",
            'inactive_180': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 180 DAY)",
            'inactive_365': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 365 DAY)",
            'inactive_60': "last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 60 DAY)",
            'never_active': "last_activity_at IS NULL",
            'new_3_month': "created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)",
            'new_6_month': "created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)",
            'new_year': "created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)",
            'top_purchases': "COALESCE(total_purchases,0) > 0",
            'top_referrals': "COALESCE(subsets_count,0) > 0",
            'top_income': "COALESCE(income,0) > 0",
            'top_balance': "COALESCE(balance,0) > 0",
            'lottery_winners': "EXISTS (SELECT 1 FROM lottery_runs lr WHERE lr.winner_id = users.user_id)",
            'gift_users': "EXISTS (SELECT 1 FROM gift_code_uses gcu WHERE gcu.user_id = users.user_id)",
        }

        if target_type == 'min_referrals':
            conditions.append("subsets_count >= %s")
            params.append(int(target_value))
        elif target_type == 'min_purchases':
            conditions.append("total_purchases >= %s")
            params.append(int(target_value))
        elif target_type == 'high_referrals':
            conditions.append("subsets_count > %s")
            params.append(int(target_value))
        elif target_type == 'high_purchases':
            conditions.append("total_purchases > %s")
            params.append(int(target_value))
        elif target_type in conditions_map:
            conditions.append(conditions_map[target_type])

        sql = (
            "SELECT user_id FROM users WHERE "
            + " AND ".join(conditions)
            + " ORDER BY RAND() LIMIT 1"
        )
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        return [int(row[0])] if row else []
    except Exception:
        logger.exception("get_lottery_candidates failed")
        return []
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


async def run_lottery(update, context, target_type='all', target_value=0):
    amount = int(context.user_data.get('lottery_amount', 0))
    if amount <= 0:
        await update.effective_message.reply_text("❌ مبلغ قرعه‌کشی نامعتبر است.")
        return

    winner_list = get_lottery_candidates(target_type, target_value)
    if not winner_list:
        await update.effective_message.reply_text(
            "❌ هیچ کاربری با شرایط انتخاب‌شده پیدا نشد."
        )
        return

    winner_id = winner_list[0]
    group_label = gift_target_label(target_type, int(target_value))

    # Get the winner's display information from Telegram. Do not assume
    # first_name/username columns exist in the MySQL users table.
    winner_name = str(winner_id)
    winner_username = ""
    try:
        winner_chat = await context.bot.get_chat(winner_id)
        winner_name = (
            getattr(winner_chat, "full_name", None)
            or getattr(winner_chat, "first_name", None)
            or str(winner_id)
        )
        winner_username = getattr(winner_chat, "username", None) or ""
    except Exception:
        logger.exception("failed loading lottery winner profile from Telegram")

    winner_mention = f'<a href="tg://user?id={winner_id}">{escape(winner_name)}</a>'
    if winner_username:
        winner_mention += f" (@{escape(winner_username.lstrip('@'))})"

    # ابتدا مطمئن شویم برنده ربات را بلاک نکرده است.
    # اگر ارسال پیام خصوصی با خطای Forbidden انجام شود، هیچ مبلغی واریز نمی‌شود.
    try:
        await context.bot.send_message(
            chat_id=winner_id,
            text=(
                f"🎉 <b>تبریک! شما برنده قرعه‌کشی شدید.</b>\n\n"
                f"💰 جایزه: <b>{format_amount(amount)} تومان</b>\n"
                f"🎯 بخش: <b>{escape(group_label)}</b>\n\n"
                "⏳ جایزه در حال ثبت و واریز به حساب شماست..."
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        err = str(exc).lower()
        if "forbidden" in err or "bot was blocked" in err or "user is deactivated" in err or "chat not found" in err:
            mark_user_blocked(winner_id)
            admin_text = (
                "🚨 <b>برنده قرعه‌کشی ربات را بلاک کرده است</b>\n\n"
                f"🆔 آیدی عددی: <code>{winner_id}</code>\n"
                f"💰 مبلغ جایزه: <b>{format_amount(amount)} تومان</b>\n"
                f"🎯 بخش: {escape(group_label)}\n\n"
                "❌ هیچ مبلغی به این کاربر واریز نشد.\n"
                "⚠️ قرعه‌کشی به‌صورت خودکار ادامه داده نشد."
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML")
                except Exception:
                    logger.exception("failed notifying admin about blocked lottery winner=%s", winner_id)
            try:
                await update.effective_message.edit_text(
                    "🚨 <b>قرعه‌کشی متوقف شد</b>\n\n"
                    f"برنده انتخاب‌شده با آیدی <code>{winner_id}</code> ربات را بلاک کرده است.\n"
                    "❌ هیچ مبلغی واریز نشد.\n"
                    "📩 موضوع به ادمین گزارش شد.",
                    parse_mode="HTML",
                    reply_markup=get_admin_gift_management_keyboard(),
                )
            except Exception:
                logger.exception("failed editing blocked lottery admin message")
            return
        # خطاهای غیر از بلاک شدن را لاگ می‌کنیم و برای جلوگیری از پرداخت اشتباه، پرداخت را متوقف می‌کنیم.
        logger.exception("failed checking lottery winner availability user=%s", winner_id)
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "⚠️ <b>بررسی برنده قرعه‌کشی ناموفق بود</b>\n\n"
                        f"🆔 آیدی: <code>{winner_id}</code>\n"
                        f"💰 جایزه: <b>{format_amount(amount)} تومان</b>\n"
                        "❌ برای جلوگیری از واریز اشتباه، جایزه پرداخت نشد."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return

    # Record the lottery and credit the winner.
    conn = get_db_connection()
    if not conn:
        await update.effective_message.reply_text("❌ اتصال به دیتابیس برقرار نشد.")
        return

    lottery_id = None
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO lottery_runs
               (amount,target_type,target_value,winner_id,created_by,channel_chat_id)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (
                amount,
                target_type,
                int(target_value),
                winner_id,
                update.effective_user.id,
                REQUIRED_CHANNEL_ID,
            ),
        )
        lottery_id = cur.lastrowid

        update_ok = update_user_balance(winner_id, amount)
        if not update_ok:
            raise RuntimeError("failed updating winner balance")

        save_transaction(
            winner_id,
            amount,
            'gift',
            f'برنده قرعه‌کشی #{lottery_id} - {format_amount(amount)} تومان',
            f'lottery:{lottery_id}',
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception(
            "lottery failed amount=%s target=%s value=%s",
            amount, target_type, target_value
        )
        await update.effective_message.reply_text(
            "❌ قرعه‌کشی انجام نشد و مبلغی واریز نشد."
        )
        return
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

    # Edit the current admin lottery message instead of creating another
    # message. This is the message where the group button was selected.
    result_text = (
        "🎉 <b>قرعه‌کشی انجام شد</b>\n\n"
        f"🏆 <b>برنده:</b> {winner_mention}\n"
        f"🆔 <b>آیدی عددی:</b> <code>{winner_id}</code>\n"
        f"💰 <b>جایزه:</b> {format_amount(amount)} تومان\n"
        f"🎯 <b>گروه قرعه‌کشی:</b> {escape(group_label)}\n"
        f"🎟 <b>شماره قرعه‌کشی:</b> #{lottery_id}\n\n"
        "💳 مبلغ جایزه با موفقیت به موجودی برنده اضافه شد."
    )

    try:
        await update.effective_message.edit_text(
            result_text,
            parse_mode="HTML",
            reply_markup=get_admin_gift_management_keyboard(),
        )
    except Exception:
        logger.exception("failed editing admin lottery result message")
        await update.effective_message.reply_text(
            result_text,
            parse_mode="HTML",
            reply_markup=get_admin_gift_management_keyboard(),
        )

    # Channel announcement: keep the winner anonymous. Only show the prize,
    # lottery section and lottery number, with a button to enter the bot.
    try:
        bot_username = (await context.bot.get_me()).username
        bot_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me/"
        channel_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 ورود به ربات", url=bot_url)]
        ])

        await context.bot.send_message(
            chat_id=REQUIRED_CHANNEL_ID,
            text=(
                "🎉 <b>نتیجه قرعه‌کشی</b>\n\n"
                f"💰 <b>جایزه:</b> {format_amount(amount)} تومان\n"
                f"🎯 <b>بخش:</b> {escape(group_label)}\n"
                f"🎟 <b>شماره قرعه‌کشی:</b> #{lottery_id}\n\n"
                "🏆 <b>یک برنده به‌صورت کاملاً تصادفی انتخاب شد.</b>\n"
                "✅ مبلغ جایزه به موجودی برنده واریز شد."
            ),
            parse_mode="HTML",
            reply_markup=channel_keyboard,
        )
    except Exception:
        logger.exception("failed sending anonymous lottery announcement to channel")

    for key in (
        'lottery_amount',
        'lottery_target_type',
        'lottery_target_value',
        'lottery_target_pending',
        'lottery_preset_from_users',
        'admin_state',
    ):
        context.user_data.pop(key, None)


async def handle_admin_lottery_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or '').strip().replace(',', '').replace('٬', '')
    if value in ('/cancel', '/start'):
        return await cancel_operation(update, context)

    try:
        amount = int(value)
    except ValueError:
        await update.effective_message.reply_text("❌ مبلغ نامعتبر است. فقط عدد وارد کن.")
        return

    if amount <= 0:
        await update.effective_message.reply_text("❌ مبلغ باید بیشتر از صفر باشد.")
        return

    context.user_data['lottery_amount'] = amount
    if context.user_data.get('lottery_preset_from_users') and context.user_data.get('lottery_target_type'):
        return await run_lottery(update, context, context.user_data['lottery_target_type'], 0)
    context.user_data['admin_state'] = 'lottery_target'

    await update.effective_message.reply_text(
        "🎯 <b>گروه قرعه‌کشی را انتخاب کن</b>\n\n"
        "قرعه‌کشی فقط بین کاربرانی انجام می‌شود که شرایط انتخاب‌شده را داشته باشند.",
        reply_markup=lottery_eligibility_keyboard(),
        parse_mode="HTML",
    )
    return


async def handle_admin_lottery_target_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.effective_message.text or '').strip().replace(',', '').replace('٬', '')
    if value in ('/cancel', '/start'):
        return await cancel_operation(update, context)

    try:
        value = int(value)
    except ValueError:
        await update.effective_message.reply_text("❌ عدد معتبر وارد کن.")
        return

    if value < 1:
        await update.effective_message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
        return

    target = context.user_data.get('lottery_target_pending', 'all')
    context.user_data['lottery_target_type'] = target
    context.user_data['lottery_target_value'] = value
    return await run_lottery(update, context, target, value)


def gift_eligibility_keyboard():
    return get_unified_user_target_keyboard('agift_target_', 'gift', None, None)

def gift_target_label(target, value=0):
    names={'all':'همه کاربران','verified':'احراز شده‌ها','unverified':'احراز نشده‌ها','rules_pending':'قوانین تأییدنشده‌ها','buyers':'دارای خرید','no_buyers':'بدون خرید','referrers':'دارای رفرال','no_referrals':'بدون رفرال','new_today':'امروز','new_week':'۷ روز اخیر','new_month':'۳۰ روز اخیر','active':'کاربران فعال','inactive_7':'بیش از ۷ روز غیرفعال','inactive_30':'بیش از ۳۰ روز غیرفعال','inactive_90':'بیش از ۹۰ روز غیرفعال','inactive_180':'بیش از ۶ ماه غیرفعال','inactive_365':'بیش از ۱ سال غیرفعال','min_referrals':f'حداقل {value} رفرال','min_purchases':f'حداقل {value:,} تومان خرید','banned':'کاربران بن‌شده','blocked':'کاربران بلاک‌کننده','new_3_month':'۳ ماه اخیر','new_6_month':'۶ ماه اخیر','new_year':'۱ سال اخیر','never_active':'بدون فعالیت','top_purchases':'بیشترین خرید','top_referrals':'بیشترین رفرال','top_income':'بیشترین درآمد','top_balance':'بیشترین موجودی','lottery_winners':'برندگان قرعه‌کشی','gift_users':'دریافت‌کنندگان کد هدیه','paid':'دارای پرداخت','no_payments':'بدون پرداخت','positive_balance':'موجودی بیشتر از صفر','zero_balance':'موجودی صفر','high_referrals':'رفرال بیشتر از مقدار','high_purchases':'خرید بیشتر از مقدار','min_referrals':'حداقل تعداد رفرال','min_purchases':'حداقل مبلغ خرید'}
    return names.get(target,target)

async def handle_admin_gift_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    if code in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    if not re.fullmatch(r"[A-Z0-9_-]{3,50}", code):
        await update.message.reply_text("❌ کد نامعتبر است. فقط حروف انگلیسی، عدد، _ و - و حداقل ۳ کاراکتر.")
        return ADMIN_GIFT_CODE
    connection = get_db_connection()
    try:
        cur=connection.cursor()
        cur.execute("SELECT id FROM gift_codes WHERE code=%s", (code,))
        if cur.fetchone():
            await update.message.reply_text("❌ این کد هدیه قبلاً وجود دارد. یک کد دیگر وارد کن.")
            return ADMIN_GIFT_CODE
    finally:
        try: cur.close(); connection.close()
        except: pass
    context.user_data['gift_code'] = code
    logger.info("gift code entered code=%s admin=%s", code, update.effective_user.id)
    context.user_data['admin_state'] = 'gift_amount'
    await update.message.reply_text(f"🎁 کد <code>{code}</code> ثبت شد.\n\n💰 مبلغ هدیه را به تومان وارد کن:\nمثال: <code>100000</code>", parse_mode="HTML")
    return ADMIN_GIFT_AMOUNT

async def handle_admin_gift_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=update.message.text.strip().replace(',', '').replace('٬','')
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    try: amount=int(text)
    except ValueError:
        await update.message.reply_text("❌ مبلغ نامعتبر است. فقط عدد وارد کن.")
        return ADMIN_GIFT_AMOUNT
    if amount <= 0:
        await update.message.reply_text("❌ مبلغ باید بیشتر از صفر باشد.")
        return ADMIN_GIFT_AMOUNT
    code=context.user_data.get('gift_code')
    connection=get_db_connection()
    context.user_data['gift_amount'] = amount
    context.user_data['admin_state'] = 'gift_max_uses'
    await update.message.reply_text(
        "👥 <b>حداکثر تعداد نفرات</b>\n\n"
        "چند نفر می‌توانند از این کد استفاده کنند؟\n"
        "مثال: <code>10</code>\n"
        "عدد <code>0</code> = نامحدود\n\n"
        "برای لغو /cancel", parse_mode="HTML")
    return ADMIN_GIFT_MAX_USES

async def handle_admin_gift_max_uses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(',', '').replace('٬','')
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    try:
        max_uses = int(text)
    except ValueError:
        await update.message.reply_text("❌ تعداد نامعتبر است. فقط عدد صحیح وارد کن.")
        return ADMIN_GIFT_MAX_USES
    if max_uses < 0:
        await update.message.reply_text("❌ تعداد نمی‌تواند منفی باشد.")
        return ADMIN_GIFT_MAX_USES
    code = context.user_data.get('gift_code')
    amount = int(context.user_data.get('gift_amount', 0))
    if not code or amount <= 0:
        await update.message.reply_text("❌ اطلاعات ساخت کد ناقص است. دوباره تلاش کن.")
        return ConversationHandler.END
    context.user_data['gift_max_uses'] = max_uses
    if context.user_data.get('gift_preset_from_users') and context.user_data.get('gift_target_type'):
        await finalize_gift_code(update, context)
        return ConversationHandler.END
    context.user_data['admin_state'] = 'gift_target'
    await update.message.reply_text(
        "🎯 <b>چه کسانی بتوانند از این کد استفاده کنند؟</b>\n\n"
        "یک دسته را انتخاب کنید:", reply_markup=gift_eligibility_keyboard(), parse_mode="HTML")
    return ConversationHandler.END

async def finalize_gift_code(update, context):
    code=context.user_data.get('gift_code'); amount=int(context.user_data.get('gift_amount',0)); max_uses=int(context.user_data.get('gift_max_uses',0)); target=context.user_data.get('gift_target_type','all'); value=int(context.user_data.get('gift_target_value',0))
    conn=get_db_connection()
    if not conn:
        await update.effective_message.reply_text('❌ اتصال به دیتابیس برقرار نشد.')
        return
    try:
        cur=conn.cursor()
        cur.execute("INSERT INTO gift_codes (code,amount,is_active,max_uses,used_count,created_by,target_type,target_value) VALUES (%s,%s,1,%s,0,%s,%s,%s)",(code,amount,max_uses,update.effective_user.id,target,value))
        gift_id = cur.lastrowid
        conn.commit()
        logger.info('gift created code=%s amount=%s max_uses=%s target=%s value=%s admin=%s',code,amount,max_uses,target,value,update.effective_user.id)
    except Exception:
        conn.rollback(); logger.exception('failed creating gift code code=%s',code)
        await update.effective_message.reply_text('❌ ساخت کد هدیه انجام نشد؛ احتمالاً کد تکراری است.')
        return
    finally:
        try: cur.close(); conn.close()
        except: pass
    uses='نامحدود' if max_uses==0 else str(max_uses)
    publish_kb = InlineKeyboardMarkup([[InlineKeyboardButton('📢 ارسال به کانال', callback_data=f'agift_publish_{gift_id}'), InlineKeyboardButton('❌ لغو ارسال', callback_data=f'agift_cancel_publish_{gift_id}')]])
    await update.effective_message.reply_text(f'✅ <b>کد هدیه ساخته شد.</b>\n\n🎟 کد: <code>{code}</code>\n💰 مبلغ: <b>{amount:,}</b> تومان\n👥 حداکثر استفاده: <b>{uses}</b> نفر\n🎯 مجاز برای: <b>{gift_target_label(target,value)}</b>\n\n⚠️ هر کاربر فقط یک‌بار می‌تواند از این کد استفاده کند.\n\n📢 آیا این کد را به کانال ارسال کنم؟',parse_mode='HTML', reply_markup=publish_kb)
    for k in ('gift_code','gift_amount','gift_max_uses','gift_target_type','gift_target_value','gift_target_pending','gift_preset_from_users','admin_state'):
        context.user_data.pop(k,None)

async def handle_admin_gift_target_value(update, context):
    text=(update.effective_message.text or '').strip().replace(',','').replace('٬','')
    if text in ('/cancel','/start'):
        return await cancel_operation(update, context)
    try: value=int(text)
    except: await update.message.reply_text('❌ عدد معتبر وارد کنید.'); return
    if value<1: await update.message.reply_text('❌ مقدار باید بیشتر از صفر باشد.'); return
    context.user_data['gift_target_value']=value
    context.user_data['gift_target_type']=context.user_data.get('gift_target_pending','all')
    await finalize_gift_code(update,context)

async def handle_admin_user_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or '').strip().replace(',', '').replace('٬', '')
    if text in ('/cancel', '/start'):
        return await cancel_operation(update, context)
    try:
        value = int(text)
    except Exception:
        await update.message.reply_text("❌ عدد معتبر وارد کنید.")
        return
    if value < 1:
        await update.message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
        return

    target = context.user_data.get('admin_user_threshold_target')
    if target not in ('high_referrals', 'high_purchases', 'min_referrals', 'min_purchases'):
        await update.message.reply_text("❌ دسته‌بندی انتخاب‌شده معتبر نیست.")
        context.user_data.pop('admin_user_threshold_target', None)
        context.user_data.pop('admin_state', None)
        return ConversationHandler.END

    context.user_data['admin_user_threshold'] = value
    context.user_data['admin_user_category'] = target
    context.user_data.pop('admin_user_threshold_target', None)
    context.user_data.pop('admin_state', None)

    users, total = get_users_page(1, 10, None, target, value)
    message = format_admin_users_list(users, target, 1, total, 10)
    await update.effective_message.reply_text(
        message,
        reply_markup=get_admin_users_keyboard(1, total, category=target),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def handle_admin_currency_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    if not re.fullmatch(r"[A-Z0-9_\-]{2,20}", text):
        await update.message.reply_text("❌ کد نامعتبر است. فقط حروف انگلیسی و عدد و _ یا - و حداکثر ۲۰ کاراکتر.")
        return ADMIN_CURRENCY_ADD_CODE
    if get_currency(text):
        await update.message.reply_text("❌ این ارز از قبل وجود دارد. کد دیگری وارد کن.")
        return ADMIN_CURRENCY_ADD_CODE
    context.user_data['currency_new_code'] = text
    await update.message.reply_text("📝 نام ارز را وارد کن. مثال: <code>ترون</code>", parse_mode="HTML")
    return ADMIN_CURRENCY_ADD_NAME

async def handle_admin_currency_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    if not text:
        await update.message.reply_text("❌ نام ارز نمی‌تواند خالی باشد.")
        return ADMIN_CURRENCY_ADD_NAME
    context.user_data['currency_new_name'] = text
    await update.message.reply_text("🔣 نماد ارز را وارد کن. مثال: <code>TRX</code> یا <code>💎</code>", parse_mode="HTML")
    return ADMIN_CURRENCY_ADD_SYMBOL

async def handle_admin_currency_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    context.user_data['currency_new_symbol'] = text[:20]
    await update.message.reply_text("💰 قیمت ارز را به تومان وارد کن. مثال: <code>85000</code>", parse_mode="HTML")
    return ADMIN_CURRENCY_ADD_RATE

async def handle_admin_currency_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(',', '').replace('٬','')
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    try:
        rate = int(text)
    except ValueError:
        await update.message.reply_text("❌ قیمت نامعتبر است. فقط عدد وارد کن.")
        return ADMIN_CURRENCY_ADD_RATE
    if rate <= 0:
        await update.message.reply_text("❌ قیمت باید بیشتر از صفر باشد.")
        return ADMIN_CURRENCY_ADD_RATE
    code = context.user_data.get('currency_new_code')
    if code:
        name = context.user_data.get('currency_new_name', code)
        symbol = context.user_data.get('currency_new_symbol', code)
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ اتصال به دیتابیس برقرار نشد.")
            return ADMIN_CURRENCY_ADD_RATE
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO currencies (code,name,symbol,rate,type,icon,is_active) VALUES (%s,%s,%s,%s,'crypto',%s,1)", (code,name,symbol,rate,symbol))
            conn.commit()
            logger.info("currency added code=%s rate=%s admin=%s", code, rate, update.effective_user.id)
            await update.message.reply_text(f"✅ ارز <b>{code}</b> اضافه شد.\n💰 نرخ: <b>{format_amount(rate)}</b> تومان", parse_mode="HTML")
        except Error:
            logger.exception("failed adding currency code=%s", code)
            await update.message.reply_text("❌ افزودن ارز انجام نشد.")
        finally:
            try: cur.close(); conn.close()
            except: pass
        for k in ('currency_new_code','currency_new_name','currency_new_symbol','admin_state'):
            context.user_data.pop(k,None)
        return ConversationHandler.END
    code = context.user_data.get('currency_code')
    if not code:
        await update.message.reply_text("❌ ارز انتخاب‌شده مشخص نیست.")
        return ConversationHandler.END
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE currencies SET rate=%s WHERE code=%s", (rate,code))
        conn.commit()
        logger.info("currency updated code=%s rate=%s admin=%s", code, rate, update.effective_user.id)
        prompt_message_id = context.user_data.get('admin_input_message_id')
        prompt_chat_id = context.user_data.get('admin_input_chat_id') or update.effective_chat.id
        success_text = f"✅ نرخ <b>{html.escape(str(code))}</b> تغییر کرد: <b>{format_amount(rate)}</b> تومان"
        try:
            if prompt_message_id:
                await context.bot.edit_message_text(
                    chat_id=prompt_chat_id, message_id=prompt_message_id,
                    text=success_text, reply_markup=get_admin_currencies_keyboard(), parse_mode="HTML"
                )
            else:
                await update.message.reply_text(success_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(success_text, parse_mode="HTML")
    except Error:
        logger.exception("failed updating currency code=%s", code)
        await update.message.reply_text("❌ تغییر قیمت انجام نشد.")
    finally:
        try: cur.close(); conn.close()
        except: pass
    context.user_data.pop('currency_code',None); context.user_data.pop('admin_state',None)
    return ConversationHandler.END

def _get_admin_settings_text():
    min_charge = get_setting('min_charge_amount', MIN_CHARGE_AMOUNT)
    max_charge = get_setting('max_charge_amount', MAX_CHARGE_AMOUNT)
    min_stars = get_setting('min_stars', MIN_STARS)
    max_stars = get_setting('max_stars', MAX_STARS)
    return (
        "⚙️ <b>تنظیمات</b>\n\n"
        f"💰 درصد سود: <b>{get_self_profit_percent():g}%</b>\n"
        f"👥 درصد رفرال: <b>{get_referral_percent():g}%</b>\n"
        f"💳 حداقل شارژ: <b>{float(min_charge):g}</b> تومان\n"
        f"💳 حداکثر شارژ: <b>{float(max_charge):g}</b> تومان\n"
        f"⭐️ حداقل استارز: <b>{float(min_stars):g}</b>\n"
        f"⭐️ حداکثر استارز: <b>{float(max_stars):g}</b>\n\n"
        f"📜 تأیید قوانین: <b>{'فعال' if setting_enabled('require_rules', True) else 'خاموش'}</b>\n"
        f"📢 عضویت کانال: <b>{'فعال' if setting_enabled('require_channel_membership', True) else 'خاموش'}</b>\n"
        f"🪪 احراز هویت: <b>{'فعال' if setting_enabled('require_verification', True) else 'خاموش'}</b>\n\n"
        "📌 تنظیمات از دیتابیس خوانده و ذخیره می‌شوند."
    )


async def handle_admin_setting_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip().replace(',', '.').replace('٪', '')
    if text in ['/start', '/cancel']:
        return await cancel_operation(update, context)

    key = context.user_data.get('admin_setting_key')
    try:
        value = float(text)
    except ValueError:
        await update.message.reply_text("❌ فقط عدد وارد کن. مثال: 10")
        return

    max_value = 1000 if key == 'self_profit_percent' else 100
    min_value = context.user_data.get('admin_setting_min', 0)
    max_value = context.user_data.get('admin_setting_max', max_value)
    if value < min_value or value > max_value:
        await update.message.reply_text(f"❌ مقدار باید بین {min_value} تا {max_value} باشد.")
        return

    message_id = context.user_data.get('admin_setting_message_id')
    chat_id = context.user_data.get('admin_setting_chat_id', update.effective_chat.id)

    if not set_setting(key, value):
        await update.message.reply_text("❌ ذخیره تنظیمات انجام نشد.")
        return

    # همان پیام تنظیمات را با اطلاعات تازه از دیتابیس رفرش کن.
    settings_text = _get_admin_settings_text()
    try:
        if message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=settings_text,
                reply_markup=get_admin_settings_keyboard(),
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                settings_text,
                reply_markup=get_admin_settings_keyboard(),
                parse_mode='HTML'
            )
    except BadRequest as e:
        if 'Message is not modified' not in str(e):
            logger.exception('failed refreshing settings message after update')
    except Exception:
        logger.exception('failed refreshing settings message after update')

    for k in (
        'admin_state', 'admin_setting_key', 'admin_setting_min',
        'admin_setting_max', 'admin_setting_message_id', 'admin_setting_chat_id'
    ):
        context.user_data.pop(k, None)
    return ConversationHandler.END

async def handle_admin_order_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in ["/start", "/cancel"]:
        return await cancel_operation(update, context)
    search = text
    orders, total = get_orders_search_page(search, 1, 10)
    context.user_data['admin_order_search'] = search
    message = f"🔎 <b>نتیجه جستجوی سفارش</b> برای <code>{html.escape(search)}</code>\n📄 صفحه 1 از {max(1, math.ceil(total/10))}\n\n"
    keyboard=[]
    if orders:
        for order in orders:
            status_emoji = "🎉" if order[9]=='completed' else ("⏳" if order[9]=='pending' else ("✅" if order[9]=='confirmed' else "❌"))
            pname = html.escape(str(order[4] or '-'))
            message += f"{status_emoji} <code>{html.escape(str(order[1] or order[0]))}</code> - {pname} - 💰{format_amount(order[8])} تومان\n"
            keyboard.append([InlineKeyboardButton(f"{status_emoji} {order[1] or order[0]}", callback_data=f"aorderdetail_{order[0]}")])
    else:
        message += "❌ سفارشی با این مشخصات پیدا نشد."
    keyboard.append([InlineKeyboardButton("🔙 مدیریت سفارشات", callback_data="apanel_orders_menu")])
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    context.user_data.pop('admin_state', None)
    return ConversationHandler.END

async def _restore_admin_verification_detail(context,user_id,chat_id,message_id):
    if not user_id or not chat_id or not message_id:return False
    u=get_user_data(int(user_id));
    if not u:return False
    try:vd=get_user_verification(int(user_id));await context.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=format_admin_verification(int(user_id),u,vd),reply_markup=get_admin_verification_keyboard(int(user_id),vd),parse_mode='HTML');return True
    except Exception:return False

async def handle_admin_verification_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.message.text or '').strip()
    if text in ['/start','/cancel']:return await cancel_operation(update,context)
    uid=context.user_data.get('verification_user_id');field=context.user_data.get('verification_field')
    if not uid:return ConversationHandler.END
    if not save_user_verification_field(uid,field,text):await _edit_admin_input_prompt(context,'❌ ذخیره انجام نشد.',InlineKeyboardMarkup([[InlineKeyboardButton('❌ لغو',callback_data='acancel_input')]]));return ADMIN_USER_VERIFICATION_TEXT
    await _restore_admin_verification_detail(context,uid,context.user_data.get('admin_input_chat_id'),context.user_data.get('admin_input_message_id'))
    for k in ('verification_user_id','verification_field','admin_input_user_id','admin_input_chat_id','admin_input_message_id','admin_state'):context.user_data.pop(k,None)
    try:await update.message.delete()
    except Exception:pass
    return ConversationHandler.END

async def handle_admin_verification_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=context.user_data.get('verification_user_id')
    if not uid or not update.message.photo:
        await _edit_admin_input_prompt(context,'📸 لطفاً عکس مدرک را ارسال کن.',InlineKeyboardMarkup([[InlineKeyboardButton('❌ لغو',callback_data='acancel_input')]]));return ADMIN_USER_VERIFICATION_PHOTO
    if not save_user_verification_photo(uid,update.message.photo[-1].file_id):
        await _edit_admin_input_prompt(context,'❌ ذخیره عکس انجام نشد.',InlineKeyboardMarkup([[InlineKeyboardButton('❌ لغو',callback_data='acancel_input')]]));return ADMIN_USER_VERIFICATION_PHOTO
    await _restore_admin_verification_detail(context,uid,context.user_data.get('admin_input_chat_id'),context.user_data.get('admin_input_message_id'))
    for k in ('verification_user_id','verification_field','admin_input_user_id','admin_input_chat_id','admin_input_message_id','admin_state'):context.user_data.pop(k,None)
    try:await update.message.delete()
    except Exception:pass
    return ConversationHandler.END

async def handle_admin_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.message.text or '').strip()
    if text in ['/start','/cancel']: return await cancel_operation(update,context)
    mode=context.user_data.get('admin_user_search_mode','all'); search=text.lstrip('@')
    users,total=get_users_page(1,10,search,'all',None,mode)
    context.user_data['admin_user_search']=search; context.user_data['admin_user_category']='search'
    label={'id':'آیدی عددی','phone':'شماره تلفن','username':'یوزرنیم','name':'نام','all':'همه اطلاعات'}.get(mode,'همه اطلاعات')
    message=(f"🔎 <b>نتیجه جستجو</b>\n\n🎯 روش: <b>{label}</b>\n🔍 عبارت: <code>{html.escape(search)}</code>\n👥 نتیجه: <b>{total:,}</b> نفر\n\n"+format_admin_users_list(users,'search',1,total,10))
    await update.message.reply_text(message,reply_markup=get_admin_users_keyboard(1,total,search=search,category='search',users=users),parse_mode='HTML')
    return ConversationHandler.END

def mark_user_blocked(user_id):
    connection = get_db_connection()
    if not connection:
        return False
    try:
        cursor = connection.cursor()
        cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = %s", (user_id,))
        connection.commit()
        return True
    except Error:
        return False
    finally:
        try:
            cursor.close()
            connection.close()
        except:
            pass

def get_blocked_users_count():
    connection = get_db_connection()
    if not connection:
        return 0
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
        return cursor.fetchone()[0] or 0
    except Error:
        return 0
    finally:
        try:
            cursor.close()
            connection.close()
        except:
            pass


# ==================== فیلترهای پیام همگانی ====================
def get_broadcast_target_condition(target, threshold=None):
    conditions = {
        'all': ('1=1', []),
        'verified': ('is_verified = 1', []),
        'unverified': ('is_verified = 0', []),
        'rules_pending': ('rules_accepted = 0', []),
        'blocked': ('is_blocked = 1', []),
        'not_blocked': ('is_blocked = 0', []),
        'banned': ('is_banned = 1', []),
        'not_banned': ('is_banned = 0', []),
        'buyers': ('total_purchases > 0', []),
        'no_buyers': ('COALESCE(total_purchases,0) = 0', []),
        'referrers': ('subsets_count > 0', []),
        'no_referrals': ('COALESCE(subsets_count,0) = 0', []),
        'paid': ('total_payments > 0', []),
        'no_payments': ('COALESCE(total_payments,0) = 0', []),
        'positive_balance': ('balance > 0', []),
        'zero_balance': ('COALESCE(balance,0) = 0', []),
        'new_today': ('created_at >= CURDATE()', []),
        'new_week': ('created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)', []),
        'new_month': ('created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)', []),
        'active': ('is_blocked = 0 AND is_banned = 0', []),
    }
    if target in ('high_referrals', 'min_referrals', 'high_purchases', 'min_purchases'):
        try:
            n = max(1, int(threshold or 1))
        except Exception:
            n = 1
        if target.endswith('referrals'):
            return (
                'subsets_count > %s' if target == 'high_referrals' else 'subsets_count >= %s',
                [n],
            )
        return (
            'total_purchases > %s' if target == 'high_purchases' else 'total_purchases >= %s',
            [n],
        )
    return conditions.get(target, ('1=1', []))

def get_broadcast_target_count(target, threshold=None):
    conn = get_db_connection()
    if not conn: return 0
    cur = None
    try:
        cur = conn.cursor()
        condition, params = get_broadcast_target_condition(target, threshold)
        cur.execute(f"SELECT COUNT(*) FROM users WHERE {condition}", tuple(params))
        return int(cur.fetchone()[0] or 0)
    except Exception:
        logger.exception("broadcast target count failed target=%s", target)
        return 0
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

def get_broadcast_target_users(target, threshold=None):
    conn = get_db_connection()
    if not conn: return []
    cur = None
    try:
        cur = conn.cursor()
        condition, params = get_broadcast_target_condition(target, threshold)
        cur.execute(f"SELECT user_id FROM users WHERE {condition} ORDER BY user_id", tuple(params))
        return [int(r[0]) for r in cur.fetchall()]
    except Exception:
        logger.exception("broadcast target users failed target=%s", target)
        return []
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

def get_broadcast_mode_keyboard(context):
    forward = context.user_data.get('broadcast_mode') == 'forward'
    pin = bool(context.user_data.get('broadcast_pin', False))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ ↪️ فوروارد پیام' if forward else '⬜ ↪️ فوروارد پیام', callback_data='abcast_mode_forward')],
        [InlineKeyboardButton('✅ 📌 پین کردن پیام' if pin else '⬜ 📌 پین کردن پیام', callback_data='abcast_pin_toggle')],
        [InlineKeyboardButton('➡️ ادامه', callback_data='abcast_prepare')],
    ])


async def show_broadcast_mode_menu(query, context, count=None):
    selected = context.user_data.get('broadcast_targets', [])
    target = selected[0] if selected else context.user_data.get('broadcast_target', 'all')
    threshold = context.user_data.get('broadcast_threshold')
    if count is None: count = get_broadcast_target_count(target, threshold)
    forward = context.user_data.get('broadcast_mode') == 'forward'
    pin = bool(context.user_data.get('broadcast_pin', False))
    await query.edit_message_text(
        '📢 <b>تنظیمات ارسال پیام همگانی</b>\n\n'
        f'👥 مخاطب: <b>{html.escape(get_broadcast_target_label(target))}</b>\n'
        f'👤 تعداد مخاطبان: <b>{count:,}</b> نفر\n\n'
        f"↪️ فوروارد: <b>{'فعال' if forward else 'غیرفعال'}</b>\n"
        f"📌 پین: <b>{'فعال' if pin else 'غیرفعال'}</b>\n\n"
        'اگر تیک فوروارد را نزنید، پیام به‌صورت معمولی ارسال می‌شود.',
        reply_markup=get_broadcast_mode_keyboard(context), parse_mode='HTML')


def get_broadcast_target_label(target):
    return {
        'all':'همه کاربران','active':'کاربران فعال','verified':'کاربران احراز‌شده','unverified':'کاربران احراز‌نشده',
        'rules_pending':'کاربرانی که قوانین را تأیید نکرده‌اند','blocked':'کاربرانی که ربات را بلاک کرده‌اند','banned':'کاربران بن‌شده',
        'new_today':'کاربران امروز','new_week':'کاربران ۷ روز اخیر','new_month':'کاربران ۳۰ روز اخیر','buyers':'کاربران دارای خرید',
        'no_buyers':'کاربران بدون خرید','referrers':'کاربران دارای رفرال','no_referrals':'کاربران بدون رفرال','paid':'کاربران دارای پرداخت',
        'no_payments':'کاربران بدون پرداخت','positive_balance':'کاربران دارای موجودی','zero_balance':'کاربران با موجودی صفر',
        'high_referrals':'کاربران با رفرال زیاد','high_purchases':'کاربران با خرید زیاد','inactive_7':'کاربران بیش از ۷ روز غیرفعال','inactive_30':'کاربران بیش از ۳۰ روز غیرفعال','inactive_90':'کاربران بیش از ۹۰ روز غیرفعال','inactive_180':'کاربران بیش از ۶ ماه غیرفعال','inactive_365':'کاربران بیش از ۱ سال غیرفعال'
    }.get(target, target)


def get_broadcast_targets_keyboard(context=None):
    """انتخاب مخاطب پیام همگانی؛ دقیقاً همان دسته‌بندی‌های مدیریت کاربران."""
    return get_unified_user_target_keyboard('abcast_target_', 'broadcast', context, 'apanel_main')

def get_broadcast_target_condition(target, threshold=None):
    conditions = {
        'all': ('1=1', []),
        'active': ('is_banned = 0 AND is_blocked = 0 AND last_activity_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)', []),
        'verified': ('is_verified = 1', []),
        'unverified': ('is_verified = 0', []),
        'rules_pending': ('rules_accepted = 0', []),
        'blocked': ('is_blocked = 1', []),
        'banned': ('is_banned = 1', []),
        'new_today': ('DATE(created_at) = CURDATE()', []),
        'new_week': ('created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)', []),
        'new_month': ('created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)', []),
        'buyers': ('total_purchases >= 1', []),
        'no_buyers': ('total_purchases = 0 OR total_purchases IS NULL', []),
        'referrers': ('subsets_count >= 1', []),
        'no_referrals': ('subsets_count = 0 OR subsets_count IS NULL', []),
        'paid': ('total_payments >= 1', []),
        'no_payments': ('total_payments = 0 OR total_payments IS NULL', []),
        'positive_balance': ('balance > 0', []),
        'zero_balance': ('balance = 0 OR balance IS NULL', []),
        'inactive_7': ('last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 7 DAY)', []),
        'inactive_30': ('last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 30 DAY)', []),
        'inactive_60': ('last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 60 DAY)', []),
        'inactive_90': ('last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 90 DAY)', []),
        'inactive_180': ('last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 180 DAY)', []),
        'inactive_365': ('last_activity_at IS NULL OR last_activity_at < DATE_SUB(NOW(), INTERVAL 365 DAY)', []),
        'never_active': ('last_activity_at IS NULL', []),
        'new_3_month': ('created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)', []),
        'new_6_month': ('created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)', []),
        'new_year': ('created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)', []),
        'top_purchases': ('COALESCE(total_purchases,0) > 0', []),
        'top_referrals': ('COALESCE(subsets_count,0) > 0', []),
        'top_income': ('COALESCE(income,0) > 0', []),
        'top_balance': ('COALESCE(balance,0) > 0', []),
        'lottery_winners': ('EXISTS (SELECT 1 FROM lottery_runs lr WHERE lr.winner_id = users.user_id)', []),
        'gift_users': ('EXISTS (SELECT 1 FROM gift_code_uses gcu WHERE gcu.user_id = users.user_id)', []),
        'never_active': ('last_activity_at IS NULL', []),
        'new_3_month': ('created_at >= DATE_SUB(NOW(), INTERVAL 3 MONTH)', []),
        'new_6_month': ('created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)', []),
        'new_year': ('created_at >= DATE_SUB(NOW(), INTERVAL 1 YEAR)', []),
    }
    if target == 'high_referrals':
        try: n=max(1,int(threshold or 1))
        except Exception: n=1
        return ('subsets_count >= %s', [n])
    if target == 'high_purchases':
        try: n=max(1,int(threshold or 1))
        except Exception: n=1
        return ('total_purchases >= %s', [n])
    return conditions.get(target, ('1=1', []))


def get_broadcast_target_count(target, threshold=None):
    conn = get_db_connection()
    if not conn: return 0
    cur = None
    try:
        cur = conn.cursor()
        condition, params = get_broadcast_target_condition(target, threshold)
        cur.execute(f"SELECT COUNT(*) FROM users WHERE {condition}", tuple(params))
        return int(cur.fetchone()[0] or 0)
    except Exception:
        logger.exception("broadcast target count failed target=%s", target)
        return 0
    finally:
        try: cur.close(); conn.close()
        except Exception: pass


def get_broadcast_target_users_multi(targets):
    users = set()
    for target in targets or []:
        threshold = context_threshold = None
        # برای گروه‌های دارای حداقل، مقدار 1 پیش‌فرض است مگر اینکه همان گروه قبلاً مقدار گرفته باشد.
        users.update(get_broadcast_target_users(target, threshold))
    return list(users)


async def show_broadcast_mode_menu(query, context, count=None):
    # مرحله دوم: بعد از انتخاب مخاطب فقط تنظیمات فوروارد و پین نمایش داده می‌شود.
    selected = context.user_data.get('broadcast_targets', [])
    target = selected[0] if selected else context.user_data.get('broadcast_target', 'all')
    threshold = context.user_data.get('broadcast_threshold')
    if count is None:
        count = get_broadcast_target_count(target, threshold)

    forward = context.user_data.get('broadcast_mode') == 'forward'
    pin = bool(context.user_data.get('broadcast_pin', False))

    await query.edit_message_text(
        '📢 <b>تنظیمات پیام همگانی</b>\n\n'
        f'👥 مخاطب: <b>{html.escape(get_broadcast_target_label(target))}</b>\n'
        f'👤 تعداد مخاطبان: <b>{count:,}</b> نفر\n\n'
        f'↪️ فوروارد پیام: <b>{"فعال" if forward else "غیرفعال"}</b>\n'
        f'📌 پین پیام: <b>{"فعال" if pin else "غیرفعال"}</b>\n\n'
        '☑️ گزینه‌های موردنظر را انتخاب کنید.\n'
        'سپس روی «📨 ارسال پیام» بزنید تا پیام موردنظر را ارسال کنید.',
        reply_markup=get_broadcast_mode_keyboard(context),
        parse_mode='HTML'
    )


def get_broadcast_targets_keyboard(context=None):
    """Use the exact same shared grouped audience menu as the other three sections."""
    return get_unified_group_keyboard('abcast_target_', 'broadcast', context, 'apanel_main')


async def handle_broadcast_ref_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_broadcast_threshold(update, context)

async def handle_broadcast_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.effective_message.text or '').strip().replace(',','').replace('٬','')
    if text in ['/cancel','/start']:
        return await cancel_operation(update, context)
    try: n=int(text)
    except: await update.message.reply_text('❌ عدد معتبر وارد کنید.'); return
    if n<1: await update.message.reply_text('❌ مقدار باید بیشتر از صفر باشد.'); return
    target=context.user_data.get('broadcast_threshold_target','high_referrals')
    context.user_data['broadcast_target']=target
    context.user_data['broadcast_threshold']=n
    context.user_data['broadcast_targets'] = [target]
    context.user_data['admin_state']='broadcast'
    count=get_broadcast_target_count(target,n)
    label = 'رفرال' if target.endswith('referrals') else 'مبلغ خرید'
    context.user_data['broadcast_mode'] = 'copy'
    context.user_data['broadcast_pin'] = False
    await update.effective_chat.send_message(
        f'🎯 <b>مخاطب انتخاب شد</b>\n\n'
        f'👥 کاربران با حداقل <b>{n:,}</b> {label}\n'
        f'👤 تعداد: <b>{count:,}</b> نفر\n\n'
        '📢 <b>تنظیمات ارسال پیام همگانی</b>',
        reply_markup=get_broadcast_mode_keyboard(context), parse_mode='HTML')

async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        logger.warning("unauthorized broadcast attempt user=%s", update.effective_user.id)
        return ConversationHandler.END

    msg = update.effective_message
    text = msg.text if msg and msg.text is not None else None
    if text and text.split()[0].split('@')[0].lower() in ["/start", "/cancel"]:
        return await cancel_operation(update, context)

    targets = list(context.user_data.get('broadcast_targets', []))
    if not targets:
        old = context.user_data.get('broadcast_target')
        if old:
            targets = [old]
    if not targets:
        await update.message.reply_text('❌ هیچ گروهی برای ارسال انتخاب نشده است.')
        return ConversationHandler.END

    mode = context.user_data.get('broadcast_mode', 'copy')
    should_pin = bool(context.user_data.get('broadcast_pin', False))
    threshold = context.user_data.get('broadcast_threshold')

    # همه کاربران انتخاب‌شده از گروه‌ها با حذف موارد تکراری
    user_ids = set()
    for target in targets:
        target_threshold = threshold if target == context.user_data.get('broadcast_threshold_target') else (threshold if target in ('high_referrals','high_purchases') and len(targets) == 1 else None)
        try:
            user_ids.update(get_broadcast_target_users(target, target_threshold))
        except Exception:
            logger.exception('failed getting broadcast users target=%s', target)
    user_ids = list(user_ids)

    success = failed = blocked = 0
    for uid in user_ids:
        try:
            if mode == 'forward':
                sent_message = await context.bot.forward_message(
                    chat_id=uid, from_chat_id=update.effective_chat.id, message_id=msg.message_id
                )
            else:
                sent_message = await context.bot.copy_message(
                    chat_id=uid, from_chat_id=update.effective_chat.id, message_id=msg.message_id
                )

            if should_pin:
                try:
                    await context.bot.pin_chat_message(
                        chat_id=uid, message_id=sent_message.message_id, disable_notification=True
                    )
                except Exception as pin_error:
                    # پین در گفت‌وگوی خصوصی معمولاً توسط تلگرام مجاز نیست؛ ارسال پیام موفق محسوب می‌شود.
                    logger.info('broadcast pin skipped user=%s error=%s', uid, pin_error)
            success += 1
        except Exception as e:
            failed += 1
            err = str(e).lower()
            if 'forbidden' in err or 'bot was blocked' in err or 'user is deactivated' in err:
                blocked += 1
                try:
                    mark_user_blocked(uid)
                except Exception:
                    logger.exception('failed marking blocked user=%s', uid)
            logger.warning('broadcast failed user=%s error=%s', uid, e)

    mode_text = 'فوروارد' if mode == 'forward' else 'کپی'
    pin_text = 'فعال' if should_pin else 'غیرفعال'
    group_names = {
        'all':'همه کاربران','active':'کاربران فعال','verified':'کاربران احراز‌شده',
        'unverified':'کاربران احراز‌نشده','rules_pending':'تأیید نکرده‌های قوانین',
        'blocked':'کاربران مسدودکننده ربات','banned':'کاربران بن‌شده','new_today':'کاربران امروز',
        'new_week':'کاربران ۷ روز اخیر','new_month':'کاربران ۳۰ روز اخیر','buyers':'کاربران دارای خرید',
        'no_buyers':'کاربران بدون خرید','referrers':'کاربران دارای رفرال','no_referrals':'کاربران بدون رفرال',
        'paid':'کاربران دارای پرداخت','no_payments':'کاربران بدون پرداخت','positive_balance':'موجودی بیشتر از صفر',
        'zero_balance':'موجودی صفر','high_referrals':'رفرال زیاد','high_purchases':'خرید زیاد'
    }
    groups_text = '، '.join(group_names.get(t, t) for t in targets)
    report = (
        '📢 <b>گزارش ارسال پیام همگانی</b>\n\n'
        f'🎯 <b>گروه‌های مخاطب:</b> {html.escape(groups_text)}\n'
        f'👥 <b>تعداد هدف:</b> {len(user_ids):,}\n'
        f'📨 <b>نوع ارسال:</b> {mode_text}\n'
        f'📌 <b>پین پیام:</b> {pin_text}\n'
        f'✅ <b>موفق:</b> {success:,}\n'
        f'❌ <b>ناموفق:</b> {failed:,}\n'
        f'🚫 <b>بلاک‌کننده‌های شناسایی‌شده:</b> {blocked:,}'
    )

    # گزارش برای پشتیبانی/مدیریت
    try:
        await context.bot.send_message(chat_id=SUPPORT_USER_ID, text=report, parse_mode='HTML')
    except Exception:
        logger.exception('failed sending broadcast report to support=%s', SUPPORT_USER_ID)

    # گزارش به خود ادمین نیز نمایش داده شود
    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='HTML')
    except Exception:
        logger.exception('failed sending broadcast report to admin=%s', update.effective_user.id)

    for key in ('admin_state','broadcast_target','broadcast_targets','broadcast_threshold','broadcast_ref_threshold','broadcast_threshold_target','broadcast_mode','broadcast_pin'):
        context.user_data.pop(key, None)
    return ConversationHandler.END

def create_admin_panel_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("panel", admin_panel), CallbackQueryHandler(handle_admin_panel, pattern="^aban_|^abalance_")],
        allow_reentry=True,
        states={
            ADMIN_AMOUNT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_balance_amount)],
            ADMIN_BAN_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_ban_reason)
            ],
            ADMIN_BROADCAST: [
                MessageHandler(~filters.COMMAND, handle_admin_broadcast)
            ],
            # برای تعیین حداقل تعداد رفرال در فیلتر پیام همگانی
            'broadcast_ref_threshold': [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_ref_threshold)
            ],
            SUPPORT_MESSAGE_INPUT: [
                MessageHandler(~filters.COMMAND, handle_admin_reply)
            ],
            ADMIN_ADD_CATEGORY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_category_name)
            ],
            ADMIN_ADD_CATEGORY_EMOJI: [
                MessageHandler(filters.TEXT, handle_admin_add_category_emoji)
            ],
            ADMIN_EDIT_CATEGORY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_edit_category_name)
            ],
            ADMIN_ADD_PRODUCT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_product_name)
            ],
            ADMIN_ADD_PRODUCT_DESCRIPTION: [
                MessageHandler(filters.TEXT, handle_admin_add_product_description)
            ],
            ADMIN_ADD_PRODUCT_CURRENCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_product_currency)
            ],
            ADMIN_ADD_PRODUCT_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_product_price)
            ],
            ADMIN_ADD_PRODUCT_PRICE_PER: [
                MessageHandler(filters.TEXT, handle_admin_add_product_price_per)
            ],
            ADMIN_ADD_PRODUCT_PROFIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_product_profit)
            ],
            ADMIN_ADD_PRODUCT_MIN_ORDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_product_min_order)
            ],
            ADMIN_ADD_PRODUCT_MAX_ORDER: [
                MessageHandler(filters.TEXT, handle_admin_add_product_max_order)
            ],
            ADMIN_ADD_PRODUCT_NEED_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_add_product_need_link)
            ],
            ADMIN_EDIT_PRODUCT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_edit_product_value)
            ],
            ADMIN_SETTING_SELF_PROFIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setting_input)],
            ADMIN_SETTING_REFERRAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setting_input)],
            ADMIN_SETTING_MIN_CHARGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setting_input)],
            ADMIN_SETTING_MAX_CHARGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setting_input)],
            ADMIN_SETTING_MIN_STARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setting_input)],
            ADMIN_SETTING_MAX_STARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setting_input)],
            ADMIN_GIFT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_gift_code)],
            ADMIN_GIFT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_gift_amount)],
            ADMIN_GIFT_MAX_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_gift_max_uses)],
            ADMIN_CURRENCY_ADD_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_currency_code)],
            ADMIN_CURRENCY_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_currency_name)],
            ADMIN_CURRENCY_ADD_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_currency_symbol)],
            ADMIN_CURRENCY_ADD_RATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_currency_rate)],
            ADMIN_USER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_user_search)],
            ADMIN_USER_VERIFICATION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_verification_text)],
            ADMIN_USER_VERIFICATION_PHOTO: [MessageHandler(filters.PHOTO, handle_admin_verification_photo)],
        },
        fallbacks=[
            CommandHandler("start", cancel_and_restart),
            CommandHandler("cancel", cancel_operation),
            CallbackQueryHandler(cancel_admin_input_callback, pattern="^acancel_input$")
        ],
        per_message=False
    )

async def handle_admin_sms_request_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.effective_message.text or '').strip()
    if not text:
        await update.effective_message.reply_text("❌ مقدار جستجو را وارد کنید.")
        return
    rows,total=get_sms_verification_requests_page(1,10,'all','latest',text)
    context.user_data.pop('admin_state',None)
    if not rows:
        await update.effective_message.reply_text(
            "🔎 نتیجه‌ای برای این جستجو پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔎 جستجوی دوباره",callback_data="apanel_sms_search")],[InlineKeyboardButton("🔙 گزارش درخواست‌های کد",callback_data="apanel_sms_requests_1")]])
        )
        return
    await update.effective_message.reply_text(
        f"🔎 <b>نتایج جستجو</b>\n━━━━━━━━━━━━━━━━━━\n👥 {int(total):,} کاربر پیدا شد.\n\nروی کاربر موردنظر بزنید:",
        reply_markup=get_sms_verification_admin_keyboard(rows,1,total,10,'all','latest'),parse_mode='HTML'
    )

# ==================== مدیریت پیام‌ها ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    text = message.text if message and message.text is not None else ""

    # /cancel و /start باید قبل از حالت پیام همگانی بررسی شوند؛
    # در غیر این صورت /cancel به‌عنوان پیام همگانی برای کاربران کپی می‌شود.
    if text == "/cancel" and update.effective_user and update.effective_user.id in ADMIN_IDS:
        admin_state = context.user_data.get('admin_state')
        if admin_state:
            return await cancel_operation(update, context)

    if text == "/start":
        await reset_user_state(update, context)
        await start(update, context)
        return

    if text == "/panel":
        await reset_user_state(update, context)
        await admin_panel(update, context)
        return

    # پیام همگانی باید هر نوع پیام (متن، عکس، ویدیو، فایل، صدا و...) را دریافت کند.
    if update.effective_user and update.effective_user.id in ADMIN_IDS and context.user_data.get('admin_state') == 'broadcast':
        return await handle_admin_broadcast(update, context)

    is_banned, ban_reason = is_user_banned(update.effective_user.id)
    if is_banned:
        if update.effective_user.id not in banned_users_notified:
            banned_users_notified.add(update.effective_user.id)
            await update.message.reply_text(
                f"⛔️ اکانت شما مسدود شد ❌\n\n📝 دلیل: {ban_reason or 'نقض قوانین'}\n\n🆔 {SUPPORT_USERNAME}"
            )
        return

    # عملیات چندمرحله‌ای پنل ادمین که از CallbackQuery شروع شده‌اند.
    # این‌ها باید قبل از منطق عمومی پیام‌ها route شوند؛ چون CallbackQueryHandler
    # به‌تنهایی state ConversationHandler را فعال نمی‌کند.
    if update.effective_user.id in ADMIN_IDS:
        admin_state = context.user_data.get('admin_state')

        if text == '/cancel' and admin_state in {
            'setting', 'gift_code', 'gift_amount', 'gift_max_uses', 'gift_target_value', 'lottery_amount', 'lottery_target_value',
            'currency_edit_rate', 'currency_add_code', 'currency_add_name',
            'currency_add_symbol', 'currency_add_rate', 'user_threshold', 'user_search', 'order_search', 'broadcast', 'broadcast_ref_threshold',
            'direct_message_user', 'order_cancel_reason', 'order_complete_message', 'verification_text', 'verification_photo',
            'sms_request_search', 'edit_product_value'
        }:
            return await cancel_operation(update, context)

        admin_state_handlers = {
            'setting': handle_admin_setting_input,
            'lottery_amount': handle_admin_lottery_amount,
            'lottery_target_value': handle_admin_lottery_target_value,
            'gift_code': handle_admin_gift_code,
            'gift_amount': handle_admin_gift_amount,
            'gift_max_uses': handle_admin_gift_max_uses,
            'gift_target_value': handle_admin_gift_target_value,
            'currency_edit_rate': handle_admin_currency_rate,
            'currency_add_code': handle_admin_currency_code,
            'currency_add_name': handle_admin_currency_name,
            'currency_add_symbol': handle_admin_currency_symbol,
            'currency_add_rate': handle_admin_currency_rate,
            'user_search': handle_admin_user_search,
            'verification_text': handle_admin_verification_text,
            'verification_photo': handle_admin_verification_photo,
            'user_threshold': handle_admin_user_threshold,
            'order_search': handle_admin_order_search,
            'sms_request_search': handle_admin_sms_request_search,
            'broadcast': handle_admin_broadcast,
            'broadcast_ref_threshold': handle_broadcast_ref_threshold,
            'broadcast_threshold': handle_broadcast_threshold,
            'direct_message_user': handle_direct_message_user,
            'order_cancel_reason': handle_admin_order_cancel_reason,
            'order_complete_message': handle_admin_order_completion_message,
            'edit_product_value': handle_admin_edit_product_value,
            'add_category_name': handle_admin_add_category_name,
            'add_category_emoji': handle_admin_add_category_emoji,
            'add_product_name': handle_admin_add_product_name,
            'add_product_description': handle_admin_add_product_description,
            'add_product_currency': handle_admin_add_product_currency,
            'add_product_price': handle_admin_add_product_price,
            'add_product_price_per': handle_admin_add_product_price_per,
            'add_product_min_order': handle_admin_add_product_min_order,
            'add_product_max_order': handle_admin_add_product_max_order,
            'add_product_need_link': handle_admin_add_product_need_link,
        }
        handler = admin_state_handlers.get(admin_state)
        if handler:
            result = await handler(update, context)

            # مراحل افزودن محصول از CallbackQuery شروع می‌شوند و بنابراین
            # ConversationHandler به‌تنهایی state بعدی را برای handle_message
            # ثبت نمی‌کند. state را بر اساس مقدار برگشتی handler به‌روزرسانی می‌کنیم
            # تا هر پیام دقیقاً وارد مرحله بعد شود و دوباره مرحله قبلی اجرا نشود.
            product_state_map = {
                ADMIN_ADD_CATEGORY_NAME: 'add_category_name',
                ADMIN_ADD_CATEGORY_EMOJI: 'add_category_emoji',
                ADMIN_ADD_PRODUCT_NAME: 'add_product_name',
                ADMIN_ADD_PRODUCT_DESCRIPTION: 'add_product_description',
                ADMIN_ADD_PRODUCT_CURRENCY: 'add_product_currency',
                ADMIN_ADD_PRODUCT_PRICE: 'add_product_price',
                ADMIN_ADD_PRODUCT_PRICE_PER: 'add_product_price_per',
                ADMIN_ADD_PRODUCT_PROFIT: 'add_product_profit',
                ADMIN_ADD_PRODUCT_MIN_ORDER: 'add_product_min_order',
                ADMIN_ADD_PRODUCT_MAX_ORDER: 'add_product_max_order',
                ADMIN_ADD_PRODUCT_NEED_LINK: 'add_product_need_link',
            }
            if result in product_state_map:
                context.user_data['admin_state'] = product_state_map[result]
            elif result == ConversationHandler.END and (
                admin_state.startswith('add_product_') or
                admin_state.startswith('add_category_') or
                admin_state == 'edit_product_value'
            ):
                context.user_data.pop('admin_state', None)

            return result

    # چک برای پاسخ ادمین به کاربر
    if update.effective_user.id in ADMIN_IDS and context.user_data.get('waiting_for_reply'):
        return await handle_admin_reply(update, context)

    # اگر کاربر در مرحله نوشتن پیام پشتیبانی است و به‌جای متن، یکی از دکمه‌های
    # منو/ناوبری را بزند، نباید آن متن به‌عنوان تیکت برای پشتیبانی ثبت شود.
    # ابتدا حالت پشتیبانی لغو می‌شود و سپس همان دکمه توسط منطق عادی ربات پردازش می‌شود.
    navigation_buttons = {
        "🔙 منوی اصلی", "🔙 منوی قبلی", "🔙 بازگشت به منوی اصلی",
        "💰 قیمت خدمات", "📝 ثبت سفارش", "👤 اطلاعات حساب",
        "💳 شارژ حساب", "🛡 پشتیبانی", "🎁 شارژ رایگان", "📞 پیگیری",
        "📱 اشتراک‌گذاری شماره", "❌ روش پرداختی موجود نیست",
        "💸 پرداخت آنلاین", "💳 کارت به کارت", "⭐️ پرداخت با استارز",
        "💰 پرداخت با ارز دیجیتال",
        "💸 پیگیری تراکنش ها", "🔍 پیگیری سفارشات", "✳️ سایر موارد",
        "👨‍💻 ارتباط با مدیریت", "⭕️ پیشنهاد،انتقاد و شکایت"
    }
    if context.user_data.get('waiting_for_support_message') and text in navigation_buttons:
        context.user_data.pop('waiting_for_support_message', None)
        context.user_data.pop('support_topic', None)
        logger.info("support input cancelled by navigation button user=%s button=%s", update.effective_user.id, text)
        # ادامه می‌دهیم تا خود دکمه عادی پردازش شود؛ هیچ تیکتی ساخته نمی‌شود.

    # چک برای پیام پشتیبانی
    if context.user_data.get('waiting_for_support_message'):
        return await handle_support_message(update, context)

    # جلوگیری از استفاده قبل از تأیید قوانین
    if setting_enabled('require_rules', True) and not get_rules_accepted(update.effective_user.id):
        if text not in ["/start", "📜 قوانین استفاده از ربات", "📋 قوانین ثبت سفارش"]:
            await show_rules_message(update, context)
            return

    if text == "💳 شارژ حساب": return
    if text == "🎁 شارژ رایگان": 
        await show_free_charge(update, context)
        return

    if text == "👥 دعوت دوستان":
        user_id = update.effective_user.id
        bot_username = BOT_USERNAME.replace("@", "")
        invite_link = f"https://t.me/{bot_username}?start={user_id}"

        caption = (
            f"🎯 <b>دان پنل - خدمات شبکه‌های اجتماعی</b>\n\n"
            f"⚡️ <b>رایگان و پولی</b>\n\n"
            f"🔹 افزایش <b>فالوور، ممبر، لایک، کامنت، ویو</b>\n"
            f"🔹 <b>تلگرام، اینستاگرام، توییتر، یوتیوب</b> و...\n"
            f"🔹 کیفیت عالی - تحویل فوری - تضمینی\n"
            f"🔹 <b>شارژ رایگان</b> با دعوت دوستان\n\n"
            f"🔥 <b>همین حالا عضو شو 👇🏻</b>\n"
            f"{invite_link}"
        )

        try:
            if os.path.exists('photo.jpg'):
                with open('photo.jpg', 'rb') as photo:
                    await update.message.reply_photo(photo=photo, caption=caption, parse_mode="HTML")
            else:
                await update.message.reply_text(caption, parse_mode="HTML", disable_web_page_preview=False)
        except Exception as e:
            await update.message.reply_text(caption, parse_mode="HTML", disable_web_page_preview=False)

        user_data = get_user_data(user_id)
        if user_data:
            stats_text = (
                f"🔺 بنر بالا حاوی <b>لینک دعوت اختصاصی</b> شماست.\n"
                f"📤 با اشتراک بنر <b>موجودی جمع کنید!</b>\n\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"👥 زیرمجموعه: <b>{user_data['subsets_count']} نفر</b>\n"
                f"💰 پورسانت: <b>{format_amount(user_data['subsets_commission'])} تومان</b>\n"
                f"💎 موجودی: <b>{format_amount(user_data['balance'])} تومان</b>\n\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"💸 <b>{get_referral_percent():g}%</b> از هر شارژ زیرمجموعه\n"
                f"🔄 واریز <b>خودکار</b>\n\n"
                f"🔗 <b>لینک دعوت:</b>\n"
                f"{invite_link}"
            )
            await update.message.reply_text(stats_text, parse_mode="HTML", disable_web_page_preview=False)
        return

    if text == "💸 برداشت موجودی":
        user_data = get_user_data(update.effective_user.id)
        consumed_gift = user_data.get('consumed_gift', 0) if user_data else 0
        available_income = max(0, user_data['income'] - consumed_gift) if user_data else 0

        if available_income <= 0:
            await update.message.reply_text("❌ موجودی قابل برداشت ندارید!", reply_markup=get_main_menu())
            return

        withdraw_text = (
            f"💸 <b>برداشت موجودی</b>\n\n"
            f"💰 موجودی قابل برداشت: {format_amount(available_income)} تومان\n\n"
            f"⚠️ حداقل برداشت: {format_amount(get_setting('min_charge_amount', MIN_CHARGE_AMOUNT))} تومان\n\n"
            f"📝 برای برداشت، مبلغ مورد نظر را به همراه شماره کارت و نام صاحب حساب ارسال کنید.\n\n"
            f"👤 جهت هماهنگی به پشتیبانی پیام دهید:\n"
            f"{SUPPORT_LINK}"
        )
        await update.message.reply_text(withdraw_text, reply_markup=get_main_menu(), parse_mode="HTML", disable_web_page_preview=True)
        return

    if text == "🔄 تبدیل درآمد به موجودی":
        user_data = get_user_data(update.effective_user.id)
        if not user_data:
            await update.message.reply_text("❌ خطا!", reply_markup=get_main_menu())
            return
        consumed_gift = user_data.get('consumed_gift', 0) or 0
        available_income = max(0, (user_data.get('income', 0) or 0) - consumed_gift)
        min_convert = 5000
        if available_income < min_convert:
            await update.message.reply_text(
                f"❌ حداقل مبلغ برای تبدیل درآمد {format_amount(min_convert)} تومان است.",
                reply_markup=get_main_menu()
            )
            return
        context.user_data['waiting_for_income_conversion'] = True
        await update.message.reply_text(
            f"✅ مبلغ مورد نظر خود را از {format_amount(min_convert)} تومان الی {format_amount(available_income)} تومان وارد کنید.\n\n"
            "برای لغو /cancel را ارسال کنید.",
            reply_markup=get_main_menu()
        )
        return

    if context.user_data.get('waiting_for_income_conversion'):
        raw_amount = text.replace(',', '').replace('٬', '').replace(' ', '').replace('تومان', '')
        try:
            amount = int(raw_amount)
        except ValueError:
            await update.message.reply_text("❌ لطفاً مبلغ را فقط به صورت عدد وارد کنید.")
            return
        user_data = get_user_data(update.effective_user.id)
        consumed_gift = user_data.get('consumed_gift', 0) or 0 if user_data else 0
        available_income = max(0, (user_data.get('income', 0) or 0) - consumed_gift) if user_data else 0
        if amount < 5000 or amount > available_income:
            await update.message.reply_text(
                f"❌ مبلغ واردشده معتبر نیست.\n\n"
                f"مبلغ باید از 5,000 تومان الی {format_amount(available_income)} تومان باشد."
            )
            return
        connection = get_db_connection()
        if not connection:
            await update.message.reply_text("❌ خطا در اتصال به پایگاه داده!", reply_markup=get_main_menu())
            return
        try:
            cursor = connection.cursor()
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN consumed_gift BIGINT DEFAULT 0")
            except Exception:
                pass
            cursor.execute(
                "UPDATE users SET consumed_gift = COALESCE(consumed_gift, 0) + %s, balance = balance + %s WHERE user_id = %s",
                (amount, amount, update.effective_user.id)
            )
            save_transaction(
                update.effective_user.id, amount, 'convert',
                f'تبدیل درآمد به موجودی - {format_amount(amount)} تومان',
                generate_payment_tracking()
            )
            connection.commit()
            cursor.close()
            connection.close()
            context.user_data.pop('waiting_for_income_conversion', None)
            new_user_data = get_user_data(update.effective_user.id)
            new_balance = new_user_data['balance'] if new_user_data else 0
            await update.message.reply_text(
                f"✅ <b>تبدیل با موفقیت انجام شد!</b>\n\n"
                f"💰 مبلغ تبدیل شده: {format_amount(amount)} تومان\n"
                f"💎 موجودی جدید: {format_amount(new_balance)} تومان",
                reply_markup=get_main_menu(), parse_mode="HTML"
            )
        except Exception as e:
            try:
                connection.close()
            except Exception:
                pass
            print(f"❌ خطا در تبدیل: {e}")
            await update.message.reply_text("❌ خطا در انجام عملیات!", reply_markup=get_main_menu())
        return

    if text == "🎟 کد هدیه":
        context.user_data['redeem_gift'] = True
        await update.message.reply_text("🎟 <b>کد هدیه</b>\n\nکد هدیه را ارسال کن.\nمثال: <code>WELCOME100</code>\n\nبرای لغو /cancel", parse_mode="HTML")
        return

    if context.user_data.get('redeem_gift'):
        if text in ['/cancel','/start']:
            context.user_data.pop('redeem_gift', None)
            return await cancel_operation(update, context)
        code=text.strip().upper()
        ok,msg=redeem_gift_code(update.effective_user.id, code)
        context.user_data.pop('redeem_gift', None)
        if ok:
            try:
                conn_g = get_db_connection()
                gift_id = None
                if conn_g:
                    cg = conn_g.cursor(dictionary=True)
                    cg.execute("SELECT id FROM gift_codes WHERE code=%s LIMIT 1", (code,))
                    row_g = cg.fetchone()
                    gift_id = row_g.get('id') if row_g else None
                    cg.close(); conn_g.close()
                if gift_id:
                    await update_published_gift_message(context.bot, int(gift_id))
            except Exception:
                logger.exception("failed refreshing gift channel post after redemption code=%s user=%s", code, update.effective_user.id)
        await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="HTML")
        return

    # مدیریت دکمه‌های پشتیبانی
    if text in ["💸 پیگیری تراکنش ها", "🔍 پیگیری سفارشات", "✳️ سایر موارد", "👨‍💻 ارتباط با مدیریت", "⭕️ پیشنهاد،انتقاد و شکایت"]:
        topic_map = {
            "💸 پیگیری تراکنش ها": "پیگیری تراکنش",
            "🔍 پیگیری سفارشات": "پیگیری سفارش",
            "✳️ سایر موارد": "سایر موارد",
            "👨‍💻 ارتباط با مدیریت": "ارتباط با مدیریت",
            "⭕️ پیشنهاد،انتقاد و شکایت": "پیشنهاد،انتقاد و شکایت"
        }
        context.user_data['support_topic'] = topic_map.get(text, "مشخص نشده")
        context.user_data['waiting_for_support_message'] = True
        await update.message.reply_text(
            f"📝 <b>{text}</b>\n\n"
            "لطفاً پیام خود را ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 بازگشت به منوی اصلی")]], resize_keyboard=True),
            parse_mode="HTML"
        )
        return

    if text in ["🔙 منوی اصلی", "🔙 منوی قبلی", "🔙 بازگشت به منوی اصلی"]:
        context.user_data.clear()
        await update.message.reply_text(
            "👈 به منوی اصلی بازگشتید.\n📋 یکی از گزینه‌های زیر را انتخاب کنید:", 
            reply_markup=get_main_menu(), 
            parse_mode="HTML"
        )
        return

    if context.user_data.get('waiting_for_tracking_code'):
        context.user_data['waiting_for_tracking_code'] = False
        order = get_order_by_tracking(text.strip().upper())
        if order:
            status_map = {
                'pending': "⏳ در انتظار",
                'confirmed': "✅ تایید شده - در حال انجام",
                'completed': "🎉 تکمیل شده",
                'cancelled': "❌ لغو شده"
            }
            status = status_map.get(order[9], order[9])
            message = f"🔍 پیگیری\n\n🆔 #{order[0]}\n🔢 <code>{order[1]}</code>\n📦 {order[4]}\n🔢 {order[6]:,}\n💰 {order[8]:,} تومان\n📊 {status}"
        else:
            message = "❌ یافت نشد."
        await update.message.reply_text(message, reply_markup=get_main_menu(), parse_mode="HTML")
        return

    if text == "👤 اطلاعات حساب":
        await show_account_info(update, context)
        return

    if text in ["💰 قیمت خدمات", "📝 ثبت سفارش"]:
        context.user_data.clear()
        await show_categories_inline(update, context)
        return

    if text == "📞 پیگیری":
        await show_tracking_menu(update, context)
        return

    if text == "🔍 پیگیری سفارش":
        if not await check_channel_membership(update, context): return
        await update.message.reply_text(
            "🔍 کد پیگیری را وارد کنید:", 
            reply_markup=get_back_keyboard(), 
            parse_mode="HTML"
        )
        context.user_data['waiting_for_tracking_code'] = True
        return

    if text == "💸 تراکنش های اخیر":
        if not await check_channel_membership(update, context): return
        page = 1
        transactions, total = get_user_transactions_page(update.effective_user.id, 1, 10)
        # خلاصه کلی تراکنش‌های کاربر
        conn = get_db_connection()
        summary = {
            "total": 0,
            "completed": 0,
            "cancelled": 0,
            "pending": 0,
            "deposit_count": 0,
            "deposit_total": 0,
        }
        if conn:
            cur = conn.cursor(dictionary=True)
            try:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COALESCE(SUM(CASE WHEN status IN
                            ('completed','confirmed','success','successful','verified')
                            THEN 1 ELSE 0 END), 0) AS completed,
                        COALESCE(SUM(CASE WHEN status IN
                            ('cancelled','canceled','failed','rejected')
                            THEN 1 ELSE 0 END), 0) AS cancelled,
                        COALESCE(SUM(CASE WHEN status IN
                            ('pending','waiting','processing')
                            THEN 1 ELSE 0 END), 0) AS pending,
                        COALESCE(SUM(CASE WHEN type IN
                            ('deposit','charge','شارژ','واریز') AND amount > 0
                            THEN 1 ELSE 0 END), 0) AS deposit_count,
                        COALESCE(SUM(CASE WHEN type IN
                            ('deposit','charge','شارژ','واریز') AND amount > 0
                            THEN amount ELSE 0 END), 0) AS deposit_total
                    FROM transactions
                    WHERE user_id = %s
                    """,
                    (update.effective_user.id,)
                )
                row = cur.fetchone()
                if row:
                    summary.update(row)
            finally:
                cur.close()
                conn.close()

        message = (
            "💸 <b>تراکنش‌های اخیر</b>\n\n"
            "📊 <b>خلاصه تراکنش‌های شما</b>\n\n"
            f"🔢 تعداد کل تراکنش‌ها: {summary['total'] or 0}\n"
            f"✅ تایید شده: {summary['completed'] or 0}\n"
            f"❌ لغو شده: {summary['cancelled'] or 0}\n"
            f"⏳ در انتظار: {summary['pending'] or 0}\n\n"
            f"💰 تعداد واریزها: {summary['deposit_count'] or 0}\n"
            f"💵 مجموع مبلغ واریزی: {int(summary['deposit_total'] or 0):,} تومان\n\n"
            "━━━━━━━━━━━━━━\n\n"
        )
        if transactions:
            message = f"💸 <b>تراکنش‌های اخیر</b>\n📄 صفحه {page} از {max(1, (total + 9) // 10)}\n\n"
            keyboard_rows = []
            for t in transactions:
                message += format_transaction_text(t) + "\n"
                if len(t) > 0:
                    tracking = t[5] if len(t) > 5 and t[5] else str(t[0])
                    keyboard_rows.append([InlineKeyboardButton(f"🔎 {tracking}", callback_data=f"usertransaction_{t[0]}")])
            keyboard_rows.append(get_pagination_keyboard("txn", page, total, 10).inline_keyboard[-1] if get_pagination_keyboard("txn", page, total, 10).inline_keyboard else [])
            keyboard_rows = [r for r in keyboard_rows if r]
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard_rows),
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ تراکنشی نیست.", reply_markup=get_main_menu())
        return

    if text == "🛒 سفارشات اخیر":
        if not await check_channel_membership(update, context): return
        orders, total = get_user_orders_page(update.effective_user.id, 1, 10)
        if orders:
            message = f"🛒 <b>سفارشات اخیر</b>\n📄 صفحه 1 از {(total + 9) // 10}\n\n"
            keyboard_rows = []
            for o in orders:
                message += format_order_text(o) + "\n"
                status_emoji = "🎉" if o[9] == 'completed' else ("⏳" if o[9] == 'pending' else ("✅" if o[9] == 'confirmed' else "❌"))
                keyboard_rows.append([InlineKeyboardButton(f"{status_emoji} {o[1]}", callback_data=f"userorder_{o[0]}")])
            keyboard_rows.append([InlineKeyboardButton("📄 1/" + str(max(1, math.ceil(total / 10))), callback_data="noop")])
            if total > 10:
                keyboard_rows[-1] = [InlineKeyboardButton("📄 1/" + str(max(1, math.ceil(total / 10))), callback_data="noop"), InlineKeyboardButton("بعدی ➡️", callback_data="ord_2")]
            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard_rows), parse_mode="HTML")
        else:
            await update.message.reply_text("❌ سفارشی نیست.", reply_markup=get_main_menu())
        return

    if context.user_data.get('waiting_for_link'):
        product_id = context.user_data.get('product_id')
        product = get_product(product_id) if product_id else None
        input_cfg = get_product_input_config(product) if product else {'type': 'custom'}
        value = text.strip()
        if input_cfg['type'] == 'numeric_id' and not re.fullmatch(r'-?\d{3,30}', value):
            await update.message.reply_text("❌ لطفاً آیدی عددی معتبر ارسال کنید.", reply_markup=get_back_keyboard())
            return
        if input_cfg['type'] == 'email' and not re.fullmatch(r'[^\s@]+@(?:gmail\.com|[^\s@]+\.[^\s@]+)', value, re.IGNORECASE):
            await update.message.reply_text("❌ لطفاً یک ایمیل معتبر ارسال کنید.", reply_markup=get_back_keyboard())
            return
        if input_cfg['type'] == 'username' and not re.fullmatch(r'@?[A-Za-z0-9_]{5,32}', value):
            await update.message.reply_text("❌ لطفاً یک یوزرنیم تلگرام معتبر ارسال کنید.\nمثال: @username", reply_markup=get_back_keyboard())
            return
        context.user_data['waiting_for_link'] = False
        return await finalize_order(update, context, value)

    if context.user_data.get('product_id'):
        return await handle_inline_order_quantity(update, context)

    if text == "🛡 پشتیبانی":
        await show_support_menu(update, context)
        return

    else:
        await update.message.reply_text(
            "❌ دستور ناشناخته!\n\n"
            "👈 لطفاً از دکمه‌های زیر پیام یکی را انتخاب کنید:",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )

# ==================== شارژ رایگان ====================
async def show_free_charge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_membership(update, context): return
    user = update.effective_user
    is_banned, _ = is_user_banned(user.id)
    if is_banned: return

    user_data = get_user_data(user.id)
    if not user_data:
        get_or_create_user(user.id, user.full_name, user.username)
        user_data = get_user_data(user.id)

    if not user_data:
        await update.message.reply_text("❌ خطا در دریافت اطلاعات.", reply_markup=get_main_menu())
        return

    consumed_gift = user_data.get('consumed_gift', 0)
    available_income = max(0, user_data['income'] - consumed_gift)

    keyboard = [
        [KeyboardButton("👥 دعوت دوستان"), KeyboardButton("💸 برداشت موجودی")],
        [KeyboardButton("🔄 تبدیل درآمد به موجودی"), KeyboardButton("🎟 کد هدیه")],
        [KeyboardButton("🔙 منوی اصلی")]
    ]

    message = (
        f"🎁 <b>شارژ رایگان</b>\n\n"
        f"👤 نام : <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
        f"👤 شناسه : <code>{user.id}</code>\n\n"
        f"💰 درآمد شما : {format_amount(user_data['income'])}\n"
        f"💰 هدیه مصرف شده : {format_amount(consumed_gift)}\n"
        f"💎 تعداد زیر مجموعه : {user_data['subsets_count']}\n"
        f"🛍 پورسانت خرید زیرمجموعه : {format_amount(user_data['subsets_commission'])}\n\n"
        f"💎 <b>موجودی قابل برداشت : {format_amount(available_income)} تومان</b>\n\n"
        f"👇 یکی از گزینه‌های زیر را انتخاب کنید:"
    )

    await update.message.reply_text(
        message, 
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="HTML"
    )

# ==================== استارت ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_user_state(update, context)

    user = update.effective_user
    # اگر کاربر بعد از بلاک دوباره به ربات برگشت، وضعیت بلاک را پاک کن
    try:
        conn=get_db_connection()
        if conn:
            cur=conn.cursor(); cur.execute("UPDATE users SET is_blocked=0 WHERE user_id=%s", (user.id,)); conn.commit(); cur.close(); conn.close()
    except Exception:
        logger.exception("failed resetting is_blocked on /start user=%s", user.id)
    is_banned, ban_reason = is_user_banned(user.id)
    if is_banned:
        if user.id not in banned_users_notified:
            banned_users_notified.add(user.id)
            await update.message.reply_text(
                f"⛔️ اکانت شما مسدود شد ❌\n\n📝 دلیل: {ban_reason or 'نقض قوانین'}\n\n🆔 {SUPPORT_USERNAME}"
            )
        return

    if context.args:
        if context.args[0] == 'payment_success':
            await update.message.reply_text(
                "✅ <b>پرداخت شما با موفقیت انجام شد!</b>\n\n"
                "💰 موجودی حساب شما شارژ شد.\n\n"
                "📋 برای شروع یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=get_main_menu(),
                parse_mode="HTML"
            )
            return
        elif context.args[0] == 'payment_failed':
            await update.message.reply_text(
                "❌ <b>پرداخت ناموفق بود!</b>\n\n"
                "🔄 لطفاً مجدداً تلاش کنید یا از روش پرداخت دیگری استفاده کنید.\n\n"
                "📋 برای شروع یکی از گزینه‌های زیر را انتخاب کنید:",
                reply_markup=get_main_menu(),
                parse_mode="HTML"
            )
            return

    referrer_id = None
    if context.args and context.args[0].strip().isdigit():
        rid = int(context.args[0].strip())
        if rid != user.id and get_referrer_info_by_code(str(rid)):
            referrer_id = rid
            context.user_data['referrer_id'] = rid

    # ساخت/دریافت کاربر قبل از بررسی عضویت؛ منبع رفرال در دیتابیس ذخیره می‌شود
    # تا حتی اگر کاربر چند ماه بعد قوانین را قبول کند، رفرال از بین نرود.
    user_data = get_or_create_user(user.id, user.full_name, user.username, None)
    # /start همیشه یک فعالیت قطعی است؛ مستقل از ترتیب Handlerها آن را ثبت کن.
    if user_data:
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE users SET last_activity_at=NOW(), full_name=%s, username=%s WHERE user_id=%s",
                    (user.full_name, user.username or '', user.id)
                )
                conn.commit()
                cur.close(); conn.close()
        except Exception:
            logger.exception("failed recording /start activity user=%s", user.id)
    if referrer_id:
        set_pending_referrer(user.id, referrer_id)
    else:
        referrer_id = get_pending_referrer(user.id)

    existing_referrer = None
    if referrer_id:
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user.id,))
                result = cur.fetchone()
                if result and result[0]:
                    existing_referrer = result[0]
                cur.close()
                conn.close()
            except: pass

    if not user_data:
        await update.message.reply_text("❌ خطا در ثبت اطلاعات کاربر.")
        return
    if not await check_channel_membership(update, context):
        return
    if setting_enabled('require_rules', True) and not get_rules_accepted(user.id):
        await show_rules_message(update, context)
        return

    if referrer_id:
        if finalize_referral(user.id, referrer_id):
            try:
                await context.bot.send_message(
                    referrer_id,
                    "🌟 تبریک! یک کاربر با لینک دعوت شما وارد ربات شد.\n\n💰 با هر شارژ، پورسانت رفرال به شما تعلق می‌گیرد.",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("failed notifying referrer=%s referred=%s", referrer_id, user.id)
        context.user_data.pop('referrer_id', None)

    welcome_text = get_welcome_text(user)
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu(), 
        parse_mode="HTML"
    )

# ==================== اجرا ====================

async def publication_callback(update: Update,context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query
    if update.effective_user.id not in ADMIN_IDS:
        await query.answer('دسترسی غیرمجاز',show_alert=True);return
    _,channel,pk=query.data.split('_')
    try:
        await asyncio.to_thread(integration.channel_toggle,int(pk),channel)
        await query.answer('تنظیمات انتشار ذخیره شد.')
        await query.edit_message_reply_markup(reply_markup=get_product_detail_admin_keyboard(int(pk)))
    except Exception:
        await query.answer('پیام‌رسان محصول را انتخاب و دوباره تلاش کنید.',show_alert=True)

def main():
    logger.info("Bot starting")
    print("Connecting...")
    if init_database(): 
        print("Database ready.")
    else: 
        print("Warning: bot started without database.")

    app = Application.builder().token(TOKEN).build()

    # ترتیب handlerها خیلی مهمه!
    app.add_handler(TypeHandler(Update, track_user_activity), group=-1)
    # TypeHandler بالا همه Updateها را پوشش می‌دهد؛ بنابراین پیام‌های معمولی، /start،
    # Reply Keyboard و Inline/Callback همگی last_activity_at را به‌روزرسانی می‌کنند.
    app.add_handler(CallbackQueryHandler(publication_callback,pattern="^achannel_(web|tg|rubika|eitaa|bale|telegram)_[0-9]+$"))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", admin_panel))
    # /cancel باید یک Handler سراسری داشته باشد؛ مخصوصاً برای stateهایی که از CallbackQuery
    # شروع شده‌اند. این Handler قبل از ConversationHandler ثبت می‌شود تا هرگز /cancel
    # به‌عنوان پیام همگانی پردازش نشود.
    app.add_handler(CommandHandler("cancel", cancel_operation), group=0)

    # پنل ادمین باید قبل از ConversationHandler، Callbackها را بگیرد؛
    # چون بعد از /panel یک Conversation فعال است و در غیر این صورت
    # کلیک روی دسته‌بندی‌های مدیریت کاربران ممکن است اصلاً به handler نرسد.
    app.add_handler(CallbackQueryHandler(handle_admin_panel, pattern="^noop$|^apanel_|^astat_|^abcast_target_|^abcast_mode_|^abcast_pin_toggle$|^abcast_prepare$|^asupport_|^auser_|^averify_|^aunban_|^apaytoggle_|^areceipt_|^agift_(lottery$|publish_|cancel_publish_|target_|detail_|delete_)|^alottery_target_|^agiftlist_page_|^aaddcategory$|^aaddproduct$|^alistcategories$|^alistproducts$|^acatdetail_|^acatproducts_|^aproductdetail_|^aproducts_|^aorders_|^aorderdetail_|^aeditcatname_|^adeletecat_|^aaddproducttocat_|^aaddprodlink_(yes|no)$|^aeditprod_|^asetprodcurrency_|^aproductcurrencyback_|^asetprodtarget_|^adeleteprod_|^atoggleprod_|^aconfirmdeleteprod_|^acanceldeleteprod_|^asetprodcat_|^selectcat_|^aset_|^acur_|^adirect_(cancel|back)$"))

    app.add_handler(create_admin_panel_handler())
    app.add_handler(PreCheckoutQueryHandler(precheckout_star_payment))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_star_payment))
    app.add_handler(CallbackQueryHandler(resend_verification_code_callback, pattern="^resend_verification_code$"))
    app.add_handler(CallbackQueryHandler(cancel_star_payment_callback, pattern="^cancel_star_payment_[0-9a-f]{10}$"))
    app.add_handler(create_charge_handler())
    app.add_handler(create_admin_handler())
    app.add_handler(CallbackQueryHandler(admin_receipt_back, pattern="^admin_receipt_back_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(admin_reply_to_user, pattern="^reply_(user|support)_"))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    app.add_handler(CallbackQueryHandler(accept_rules_callback, pattern="^accept_rules$"))
    app.add_handler(CallbackQueryHandler(handle_all_inline_callbacks, pattern="^(cat_|prod_|back_to_categories|backprod_|close_list|no_product|sr_|cancel_online_transaction)"))
    app.add_handler(CallbackQueryHandler(user_transaction_detail_callback, pattern="^usertransaction_"))
    app.add_handler(CallbackQueryHandler(user_order_detail_callback, pattern="^userorder_"))
    app.add_handler(CallbackQueryHandler(handle_pagination, pattern="^(txn_|ord_)"))
    app.add_handler(CallbackQueryHandler(order_product_callback, pattern="^order_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(user_confirm_order_callback, pattern="^user_confirm_order$"))
    app.add_handler(CallbackQueryHandler(username_self_callback, pattern="^order_username_self$"))
    app.add_handler(CallbackQueryHandler(cancel_order_input_callback, pattern="^cancel_order_input$"))
    app.add_handler(CallbackQueryHandler(reorder_order_callback, pattern="^reorder_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(increase_balance_callback, pattern="^increase_balance$"))
    app.add_handler(CallbackQueryHandler(confirm_order_callback, pattern="^confirmorder_"))
    app.add_handler(CallbackQueryHandler(confirm_complete_order_callback, pattern="^confirmcomplete_"))
    app.add_handler(CallbackQueryHandler(back_order_callback, pattern="^backorder_"))
    app.add_handler(CallbackQueryHandler(complete_order_with_message_callback, pattern="^completeorder_info_"))
    app.add_handler(CallbackQueryHandler(complete_order_callback, pattern="^completeorder_"))
    app.add_handler(CallbackQueryHandler(reject_order_callback, pattern="^rejectorder_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def _global_error_handler(update, context):
        logger.exception("Unhandled Telegram update error", exc_info=context.error)

    app.add_error_handler(_global_error_handler)

    verification_thread = threading.Thread(target=run_verification_queue, daemon=True)
    verification_thread.start()
    print("Automatic transaction verification service started successfully.")

    print("Bot started successfully.")
    app.run_polling()

if __name__ == "__main__":
    main()
