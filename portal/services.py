import hashlib,hmac,secrets,re,uuid
from datetime import timedelta
from decimal import Decimal,ROUND_CEILING
import requests
from django.conf import settings
from django.db import transaction,connection
from django.db.models import F
from django.utils import timezone
from django.contrib.auth.models import User
from .models import *

class BusinessError(ValueError): pass

def normalize_phone(value):
    value=str(value).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
    value=re.sub(r'[\s()\-]','',value)
    if value.startswith('+98'): value='0'+value[3:]
    elif value.startswith('0098'): value='0'+value[4:]
    elif value.startswith('98'): value='0'+value[2:]
    if not re.fullmatch(r'09[0-9]{9}',value): raise BusinessError('شماره موبایل معتبر وارد کنید.')
    return value

def digest(value): return hmac.new(settings.SECRET_KEY.encode(),str(value).encode(),hashlib.sha256).hexdigest()

def rate_limit(key,limit,seconds):
    now=timezone.now()
    with transaction.atomic():
        row,_=RateBucket.objects.get_or_create(key=digest(key),defaults={'expires_at':now+timedelta(seconds=seconds)})
        row=RateBucket.objects.select_for_update().get(pk=row.pk)
        if row.expires_at<=now: row.count=0;row.expires_at=now+timedelta(seconds=seconds)
        if row.count>=limit: return False
        row.count+=1;row.save();return True

def request_otp(phone,session,ip):
    phone=normalize_phone(phone)
    if not all([rate_limit('sms-minute:'+phone,1,60),rate_limit('sms-day:'+phone,6,86400),rate_limit('sms-ip:'+ip,15,3600)]): raise BusinessError('تعداد درخواست‌ها زیاد است. کمی بعد تلاش کنید.')
    code=str(secrets.randbelow(900000)+100000)
    otp=OTP.objects.create(phone=phone,code_hash=digest(code),session_hash=digest(session),expires_at=timezone.now()+timedelta(minutes=5))
    cfg=settings.BOT_CONFIG.get('sms_ir',{})
    try:
        r=requests.post('https://api.sms.ir/v1/send/verify',json={'mobile':phone,'templateId':cfg['verify_template_id'],'parameters':[{'name':'Code','value':code}]},headers={'x-api-key':cfg['api_key']},timeout=12)
        r.raise_for_status()
        if r.json().get('status')!=1: raise ValueError('SMS rejected')
    except (requests.RequestException,ValueError,KeyError):
        otp.consumed=True;otp.save(update_fields=['consumed'])
        raise BusinessError('ارسال پیامک انجام نشد. دوباره تلاش کنید.') from None
    return otp

def verify_otp(otp_id,code,session):
    with transaction.atomic():
        otp=OTP.objects.select_for_update().filter(pk=otp_id).first()
        if not otp or otp.consumed or otp.attempts>=5 or otp.expires_at<timezone.now() or not hmac.compare_digest(otp.session_hash,digest(session)): return None
        otp.attempts+=1
        valid=hmac.compare_digest(otp.code_hash,digest(code))
        if valid: otp.consumed=True
        otp.save(update_fields=['attempts','consumed'])
        return otp.phone if valid else None

@transaction.atomic
def login_account(phone):
    user,_=User.objects.get_or_create(username=phone,defaults={'first_name':'کاربر دان پنل'})
    user=User.objects.select_for_update().get(pk=user.pk)
    account=Account.objects.filter(user=user).first()
    if not account:
        matches=list(LegacyUser.objects.select_for_update().filter(phone_number=phone,is_verified=True)[:2])
        if len(matches)>1: raise BusinessError('این شماره به چند حساب متصل است؛ با پشتیبانی تماس بگیرید.')
        if matches: legacy=matches[0]
        else: legacy=LegacyUser.objects.create(user_id=-secrets.randbits(61)-1,full_name='کاربر سایت',phone_number=phone,is_verified=True,referral_code=secrets.token_hex(12))
        if legacy.is_banned: raise BusinessError('دسترسی حساب محدود شده است. با پشتیبانی تماس بگیرید.')
        account=Account.objects.create(user=user,phone=phone,legacy_id=legacy.pk)
        user.set_unusable_password()
    if LegacyUser.objects.get(pk=account.legacy_id).is_banned: raise BusinessError('دسترسی حساب محدود شده است.')
    if settings.OWNER_PHONE and phone==settings.OWNER_PHONE:
        user.is_staff=True;user.is_superuser=True
    if not user.is_active: raise BusinessError('حساب غیرفعال است.')
    user.save()
    return user

def public_products(): return Product.objects.filter(is_active=True,category__is_active=True,show_on_website=True,platform__in=['rubika','eitaa','bale'])

def price_for(product,quantity):
    if quantity<product.min_order or (product.max_order and quantity>product.max_order) or quantity>100000000: raise BusinessError('تعداد خارج از محدوده مجاز است.')
    if product.price_per<=0: raise BusinessError('قیمت محصول نیاز به بررسی دارد.')
    amount=product.price_amount if product.price_amount is not None else Decimal(product.price)
    if product.price_currency!='TOMAN':
        with connection.cursor() as c:
            c.execute('SELECT rate FROM currencies WHERE code=%s AND is_active=1',[product.price_currency]); row=c.fetchone()
        if not row or row[0]<=0: raise BusinessError('نرخ ارز در دسترس نیست.')
        amount*=Decimal(row[0])
    # The bot rounds the pack price upward before calculating the quantity total.
    pack=(amount*(Decimal(1)+product.product_profit_percent/100)).to_integral_value(rounding=ROUND_CEILING)
    total=int((pack*quantity/Decimal(product.price_per)).to_integral_value(rounding=ROUND_CEILING))
    if total<=0 or total>100000000000: raise BusinessError('مبلغ سفارش نامعتبر است.')
    return total,int(pack)

@transaction.atomic
def place_order(account,product_id,quantity,target,key,quoted_total):
    # Lock the wallet first: serializes retries, bot purchases and concurrent website purchases.
    wallet=LegacyUser.objects.select_for_update().get(pk=account.legacy_id)
    if wallet.is_banned or not wallet.is_verified: raise BusinessError('حساب مجاز به ثبت سفارش نیست.')
    checkout,created=Checkout.objects.get_or_create(key=key,defaults={'account':account})
    if checkout.account_id!=account.pk: raise BusinessError('درخواست سفارش نامعتبر است.')
    if checkout.order_id: return Order.objects.get(pk=checkout.order_id)
    p=public_products().select_for_update().filter(pk=product_id).first()
    if not p: raise BusinessError('محصول در دسترس نیست.')
    total,pack=price_for(p,quantity)
    if total!=quoted_total: raise BusinessError('قیمت تغییر کرده است؛ سفارش را دوباره بررسی کنید.')
    if p.need_link and not target.strip(): raise BusinessError('لینک یا شناسه سفارش را وارد کنید.')
    if len(target)>1500: raise BusinessError('اطلاعات سفارش بیش از حد طولانی است.')
    if wallet.balance<total: raise BusinessError('موجودی کافی نیست. ابتدا کیف پول را شارژ کنید.')
    wallet.balance-=total;wallet.save(update_fields=['balance'])
    order=Order.objects.create(tracking_code='DWN-'+secrets.token_hex(8).upper(),user=wallet,product_id=p.pk,product_name=p.name,target_link=target,quantity=quantity,unit_price=int((Decimal(pack)/p.price_per).to_integral_value(rounding=ROUND_CEILING)),total_price=total)
    Ledger.objects.create(user=wallet,amount=-total,type='withdraw',description=f'خرید سایت: {order.tracking_code}')
    checkout.order_id=order.pk;checkout.save(update_fields=['order_id'])
    return order

@transaction.atomic
def change_order(actor,order_id,status,note):
    order=Order.objects.select_for_update().get(pk=order_id)
    if order.status in ['completed','cancelled','rejected']: raise BusinessError('این سفارش قبلاً نهایی شده است.')
    if status not in ['confirmed','completed','cancelled']: raise BusinessError('وضعیت نامعتبر است.')
    if status=='cancelled':
        wallet=LegacyUser.objects.select_for_update().get(pk=order.user_id)
        wallet.balance+=order.total_price;wallet.save(update_fields=['balance'])
        Ledger.objects.create(user=wallet,amount=order.total_price,type='refund',description=f'بازگشت سفارش {order.tracking_code}')
        order.cancel_reason=note
    elif status=='completed':
        order.completed_at=timezone.now();order.completion_message=note
        LegacyUser.objects.filter(pk=order.user_id).update(total_purchases=F('total_purchases')+order.total_price)
    order.status=status;order.save()
    Audit.objects.create(actor=actor,action='order.status',object_ref=str(order.pk),details={'status':status,'note':note})

def zarin_config():
    c=settings.BOT_CONFIG['zarinpal']; base='https://sandbox.zarinpal.com' if c['sandbox'] else 'https://payment.zarinpal.com'
    return c,base

def start_payment(account,amount):
    if amount<1000 or amount>100000000: raise BusinessError('مبلغ شارژ باید بین ۱٬۰۰۰ و ۱۰۰٬۰۰۰٬۰۰۰ تومان باشد.')
    if LegacyUser.objects.get(pk=account.legacy_id).is_banned: raise BusinessError('حساب محدود شده است.')
    c,base=zarin_config();attempt=PaymentAttempt.objects.create(account=account,amount=amount)
    try:
        r=requests.post(base+'/pg/v4/payment/request.json',json={'merchant_id':c['merchant'],'amount':amount*10,'callback_url':'https://dawnpanel.ir/payment/verify/','description':'شارژ کیف پول دان پنل','metadata':{'mobile':account.phone}},timeout=20)
        r.raise_for_status();data=r.json()['data']
        if data.get('code')!=100 or not re.fullmatch(r'[A-Za-z0-9]{20,50}',data.get('authority','')): raise ValueError()
        authority=data['authority']
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("INSERT INTO zarinpal_transactions (user_id,amount,authority,status,payment_tracking_code) VALUES (%s,%s,%s,'pending',%s)",[account.legacy_id,amount,authority,secrets.token_hex(5)])
            attempt.authority=authority;attempt.status='pending';attempt.save()
        return base+'/pg/StartPay/'+authority
    except (requests.RequestException,KeyError,ValueError):
        attempt.status='failed';attempt.save(update_fields=['status'])
        raise BusinessError('درگاه پرداخت در دسترس نیست. کمی بعد تلاش کنید.') from None

@transaction.atomic
def verify_payment(authority):
    if not re.fullmatch(r'[A-Za-z0-9]{20,50}',authority or ''): raise BusinessError('شناسه پرداخت نامعتبر است.')
    with connection.cursor() as cur:
        cur.execute('SELECT id,user_id,amount,status,ref_id,payment_tracking_code FROM zarinpal_transactions WHERE authority=%s FOR UPDATE',[authority]); rows=cur.fetchall()
        if len(rows)!=1: raise BusinessError('پرداخت یافت نشد.')
        pk,uid,amount,status,ref,tracking=rows[0]
        if status in ['verified','completed']: return amount,ref
        if status not in ['pending','checking']: raise BusinessError('این پرداخت قابل تایید نیست.')
        c,base=zarin_config()
        try:
            r=requests.post(base+'/pg/v4/payment/verify.json',json={'merchant_id':c['merchant'],'authority':authority,'amount':amount*10},timeout=20);r.raise_for_status();data=r.json().get('data',{})
        except (requests.RequestException,ValueError): raise BusinessError('تایید درگاه موقتاً ممکن نیست؛ دوباره این صفحه را باز کنید.') from None
        if data.get('code') not in [100,101]: raise BusinessError('درگاه هنوز پرداخت را تایید نکرده است.')
        ref=str(data.get('ref_id',''))
        if not ref: raise BusinessError('شماره مرجع دریافت نشد.')
        cur.execute("UPDATE zarinpal_transactions SET status='verified',ref_id=%s,verified_at=NOW() WHERE id=%s",[ref,pk])
        cur.execute('UPDATE users SET balance=balance+%s,total_payments=total_payments+%s WHERE user_id=%s',[amount,amount,uid])
        cur.execute("INSERT INTO transactions (user_id,amount,type,description,payment_tracking_code) VALUES (%s,%s,'deposit',%s,%s)",[uid,amount,'شارژ درگاه؛ مرجع '+ref,tracking])
        cur.execute("UPDATE zarinpal_verification_queue SET status='completed' WHERE authority=%s",[authority])
        cur.execute('SELECT referrer_id FROM referrals WHERE referred_user_id=%s',[uid]);row=cur.fetchone()
        if row:
            cur.execute("SELECT setting_value FROM bot_settings WHERE setting_key='referral_percent'");setting=cur.fetchone()
            percent=Decimal(setting[0] if setting else str(settings.BOT_CONFIG['business']['commission_percent']))
            commission=int(Decimal(amount)*percent/100)
            if 0<commission<=amount:
                cur.execute('UPDATE users SET balance=balance+%s,income=income+%s,subsets_commission=subsets_commission+%s WHERE user_id=%s',[commission,commission,commission,row[0]])
                cur.execute('UPDATE referrals SET total_commission=total_commission+%s WHERE referred_user_id=%s',[commission,uid])
                cur.execute("INSERT INTO transactions (user_id,amount,type,description) VALUES (%s,%s,'commission',%s)",[row[0],commission,'پورسانت شارژ '+tracking])
        PaymentAttempt.objects.filter(authority=authority).update(status='verified')
        return amount,ref


@transaction.atomic
def place_bot_order(uid,product_id,quantity,target,quoted_total):
    wallet=LegacyUser.objects.select_for_update().get(pk=uid)
    if wallet.is_banned or not wallet.is_verified: raise BusinessError('حساب مجاز به ثبت سفارش نیست.')
    p=Product.objects.select_for_update().filter(pk=product_id,is_active=True,category__is_active=True,show_on_telegram=True).first()
    if not p: raise BusinessError('محصول در تلگرام در دسترس نیست.')
    total,pack=price_for(p,quantity)
    if total!=quoted_total: raise BusinessError('قیمت تغییر کرده؛ سفارش را دوباره بررسی کنید.')
    if p.need_link and not str(target).strip(): raise BusinessError('مقصد سفارش لازم است.')
    if wallet.balance<total: raise BusinessError('موجودی کافی نیست.')
    wallet.balance-=total;wallet.save(update_fields=['balance'])
    o=Order.objects.create(tracking_code='DWN-'+secrets.token_hex(8).upper(),user=wallet,product_id=p.pk,product_name=p.name,target_link=str(target)[:1500],quantity=quantity,unit_price=int((Decimal(pack)/p.price_per).to_integral_value(rounding=ROUND_CEILING)),total_price=total)
    Ledger.objects.create(user=wallet,amount=-total,type='withdraw',description='خرید ربات: '+o.tracking_code)
    return o.pk,o.tracking_code


@transaction.atomic
def redeem_gift(account,code):
    from .gift_targets import ELIGIBILITY
    code=str(code).strip().upper()
    if not re.fullmatch(r'[A-Z0-9_-]{1,50}',code): raise BusinessError('کد هدیه نامعتبر است.')
    gift=GiftCode.objects.select_for_update().filter(code=code,is_active=True).first()
    if not gift or gift.amount<=0: raise BusinessError('کد هدیه پیدا نشد یا غیرفعال است.')
    wallet=LegacyUser.objects.select_for_update().get(pk=account.legacy_id)
    if wallet.is_banned: raise BusinessError('حساب محدود شده است.')
    if gift.max_uses and gift.used_count>=gift.max_uses: raise BusinessError('ظرفیت کد هدیه تکمیل شده است.')
    conditions={'min_referrals':('subsets_count >= %s',[gift.target_value]),'min_purchases':('total_purchases >= %s',[gift.target_value]),'high_referrals':('subsets_count > %s',[gift.target_value]),'high_purchases':('total_purchases > %s',[gift.target_value])}
    if gift.target_type=='all': condition,params='1=1',[]
    elif gift.target_type in conditions: condition,params=conditions[gift.target_type]
    elif gift.target_type in ELIGIBILITY: condition,params=ELIGIBILITY[gift.target_type],[]
    else: raise BusinessError('شرایط کد هدیه قابل بررسی نیست؛ با پشتیبانی تماس بگیرید.')
    with connection.cursor() as cur:
        cur.execute('SELECT user_id FROM users WHERE user_id=%s AND ('+condition+')',[wallet.pk]+params)
        if not cur.fetchone(): raise BusinessError('شما در گروه مجاز این کد هدیه نیستید.')
        cur.execute('SELECT id FROM gift_code_uses WHERE gift_code_id=%s AND user_id=%s',[gift.pk,wallet.pk])
        if cur.fetchone(): raise BusinessError('قبلاً از این کد هدیه استفاده کرده‌اید.')
        cur.execute('INSERT INTO gift_code_uses (gift_code_id,user_id,amount) VALUES (%s,%s,%s)',[gift.pk,wallet.pk,gift.amount])
    wallet.balance+=gift.amount;wallet.consumed_gift+=gift.amount;wallet.save(update_fields=['balance','consumed_gift'])
    gift.used_count+=1;gift.save(update_fields=['used_count'])
    Ledger.objects.create(user=wallet,amount=gift.amount,type='gift',description='کد هدیه '+gift.code)
    return gift.amount
