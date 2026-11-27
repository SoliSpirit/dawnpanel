import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','dawn.settings')
import django
django.setup()
from django.db import close_old_connections
from portal.services import bot_products,place_bot_order,change_order,verify_payment,BusinessError
from portal.pricing import pricing_for
from portal.models import Product
from portal.exchange_rates import RateError, resolve


def product_pricing(product_id):
    try:
        product = bot_products().select_related('tax_policy').filter(pk=product_id).first()
        if product is None:
            raise BusinessError('محصول در تلگرام در دسترس نیست.')
        pricing = pricing_for(product)
        pricing.quote(product.min_order)
        return pricing
    finally:
        close_old_connections()


def bot_currency_record(row):
    """Normalize one legacy connector result, without using ORM on the bot event loop."""
    from datetime import timezone
    from types import SimpleNamespace
    from portal.exchange_rates import source_link
    at=row.get('observed_at')
    if at is not None and at.tzinfo is None:
        at=at.replace(tzinfo=timezone.utc)  # Django's MySQL DATETIME in UTC
    policy=SimpleNamespace(source=row['fx_source'],spread_mode=row['spread_mode'],sell_extra=row['sell_extra'],
        buy_less=row['buy_less'],quote_key=row['quote_key'],market_bid=row['market_bid'],market_ask=row['market_ask'],
        observed_at=at) if row.get('fx_source') else None
    row['observed_at']=at
    row['fx_source']=policy.source if policy else 'manual'
    row['source_url']=source_link(row['fx_source'],row['code'])
    row['manual_rate']=row['rate']
    try:
        rates=resolve(row['code'],row['type'],row['manual_rate'],policy)
        row['rate'],row['buy_rate']=rates.sell,rates.buy
    except RateError:
        row['rate']=row['buy_rate']=None
    return row


def product_photo(product_id):
    """Serve approved catalogue images without fetching remote URLs."""
    from PIL import Image
    from portal.product_art import artwork_key, gallery_jpeg, write_jpeg
    from portal.models import SourceProduct
    try:
        product = Product.objects.filter(pk=product_id, is_active=True, show_on_telegram=True).first()
        if not product:
            return None
        visual = product.visual
        upload = (visual.image or visual.night_image) if visual else None
        if upload:
            try:
                with upload.open('rb') as file, Image.open(file) as image:
                    return write_jpeg(image)
            except (OSError, ValueError):
                pass
        link = SourceProduct.objects.filter(product_id=product_id, source='premstore').first()
        key = artwork_key(product.pk, product.platform, product.name, link.family_name if link else '')
        return gallery_jpeg(key)
    finally:
        close_old_connections()


def receipt_decision(receipt_id,admin_id,**kwargs):
    from portal.services import decide_bot_receipt
    try:
        return decide_bot_receipt(receipt_id,admin_id,**kwargs)
    finally:
        close_old_connections()

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
