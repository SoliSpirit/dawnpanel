"""Private recipient policy; topics are closed choices, never chat IDs from a form."""
from django.conf import settings

TOPICS = {
    'web_order':'خرید مشتری از سایت',
    'bot_order':'خرید مشتری از ربات',
    'catalog':'تغییر محصولات، دسته‌ها و قیمت‌ها',
    'price_review':'گزارش مقایسه و تأیید قیمت منابع',
    'order_status':'تأیید، تکمیل یا لغو سفارش توسط مدیر',
    'finance':'عملیات مالی مدیر، رسید و ارز',
    'support':'اقدام مدیر در تیکت و گفتگو',
    'web_chat':'پیام جدید مشتری در چت آنلاین سایت',
    'management':'تنظیمات، دسترسی کاربران و محتوای فروشگاه',
    'staff_session':'ورود و خروج موفق مدیران سایت',
    'site_error':'خطای جدید یا بازگشتهٔ سایت',
    'incoming_ticket':'پیام پشتیبانی جدید در ربات',
    'incoming_receipt':'رسید کارت‌به‌کارت جدید در ربات',
    'lottery_warning':'هشدار قرعه‌کشی ربات',
}
DEFAULT_TOPICS=frozenset(TOPICS)-{'site_error','staff_session'}


def mail_topics(row):
    selected=set(row.email_topics or ()) & TOPICS.keys() if isinstance(row.email_topics,list) else set()
    selected.discard('web_chat')
    if row.chat_email_enabled:selected.add('web_chat')
    return selected


def recipients():
    values=settings.BOT_CONFIG.get('telegram',{}).get('admin_ids',[])
    if not isinstance(values,(list,tuple)):return []
    return sorted({int(v) for v in values if isinstance(v,(int,str)) and str(v).isascii()
                   and str(v).isdigit() and 0<len(str(v))<=16 and 0<int(v)<2**52})


def policies():
    from .models import NoticePreference
    ids=recipients()
    rows=NoticePreference.objects.filter(pk__in=ids).values_list('recipient','enabled')
    overrides={key:set(v)&TOPICS.keys() if isinstance(v,list) else set() for key,v in rows}
    return {i:overrides.get(i,DEFAULT_TOPICS) for i in ids}


def subscribers(topic):
    return [i for i,enabled in policies().items() if topic in enabled]
