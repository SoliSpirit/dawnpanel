from django.conf import settings
import re
def brand(request):
    username=str(settings.BOT_CONFIG.get('telegram',{}).get('bot_username') or 'DawnPanel_Bot').strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',username):username='DawnPanel_Bot'
    return {'brand':'دان پنل','bot_username':username,'site_url':'https://dawnpanel.ir'}
