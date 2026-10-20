from django.conf import settings
def brand(request):
    return {'brand':'دان پنل','bot_username':settings.BOT_CONFIG.get('telegram',{}).get('bot_username','DawnPanelBot').lstrip('@'),'site_url':'https://dawnpanel.ir'}
