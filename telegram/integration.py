import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','dawn.settings')
import django
django.setup()
from django.db import close_old_connections
from portal.services import place_bot_order,change_order,verify_payment,BusinessError
from portal.models import Product

def purchase(*args):
    try: return place_bot_order(*args)
    finally: close_old_connections()

def transition(order_id,status,note=''):
    try:
        change_order(None,order_id,status,note)
        return True
    except BusinessError: return False
    finally: close_old_connections()

def verify(authority,amount=None):
    try:
        paid,ref=verify_payment(authority)
        return {'success':True,'ref_id':ref,'amount':paid}
    except BusinessError as e: return {'success':False,'error':str(e)}
    finally: close_old_connections()

def channel_state(product_id):
    try:
        p=Product.objects.get(pk=product_id)
        return p.show_on_website,p.show_on_telegram,p.platform
    finally: close_old_connections()

def channel_toggle(product_id,channel):
    from django.db import transaction
    try:
        with transaction.atomic():
            p=Product.objects.select_for_update().get(pk=product_id)
            if channel=='web':
                if p.platform not in ['rubika','eitaa','bale','ai']: raise BusinessError('ابتدا نوع محصول قابل نمایش در سایت را انتخاب کنید.')
                p.show_on_website=not p.show_on_website;p.save(update_fields=['show_on_website'])
            elif channel=='tg': p.show_on_telegram=not p.show_on_telegram;p.save(update_fields=['show_on_telegram'])
            elif channel in ['rubika','eitaa','bale','ai','telegram']:
                p.platform=channel
                if channel=='telegram': p.show_on_website=False
                p.save(update_fields=['platform','show_on_website'])
    finally: close_old_connections()


def code_digest(code):
    from portal.services import digest
    return digest(code)

def code_matches(code,hashed):
    import hmac
    return hmac.compare_digest(code_digest(code),hashed)

def verify_identity(uid,code):
    from portal.services import verify_bot_phone
    try: return verify_bot_phone(uid,code)
    finally: close_old_connections()
