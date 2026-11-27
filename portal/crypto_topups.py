"""Ticket-only crypto deposits. Opening a request never credits a wallet."""
import re
import secrets
import uuid
from decimal import Decimal, ROUND_FLOOR, localcontext

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .exchange_rates import currency_rates, resolve, RateError
from .models import Account, Audit, CryptoTopup, Currency, CurrencyPricing, Ledger, LegacyUser, Ticket, TicketMessage
from .services import BusinessError, rate_limit

LIMIT=100_000_000
SALT='portal.crypto-ticket.v1'


def method_open(key):
    # A missing or disabled payment method is not an available deposit route.
    try:
        with transaction.atomic(),connection.cursor() as c:
            c.execute('SELECT is_active FROM payment_methods WHERE method_key=%s',[key])
            return bool((c.fetchone() or (False,))[0])
    except DatabaseError:
        return False


def available_rates():
    rates={}
    for row in Currency.objects.filter(is_active=True,type='crypto').select_related('fx').order_by('code'):
        try:rates[row.code]=currency_rates(row).buy
        except RateError:pass
    return rates


class Units(forms.DecimalField):
    def __init__(self,**kwargs):
        super().__init__(min_value=Decimal('0.000000000001'),max_digits=28,decimal_places=12,
                         widget=forms.TextInput(attrs={'inputmode':'decimal','dir':'ltr'}),**kwargs)

    def to_python(self,value):
        if isinstance(value,str):value=value.strip().replace('٫','.')
        return super().to_python(value)


class RequestForm(forms.Form):
    code=forms.ChoiceField(label='رمزارز و نرخ خرید هر واحد')
    units=Units(label='مقدار ارز',help_text='مثلاً ۲٫۵ تتر')
    note=forms.CharField(label='توضیح یا شبکهٔ موردنظر (اختیاری)',max_length=1500,required=False,
                         widget=forms.Textarea(attrs={'rows':2}))
    quote=forms.CharField(widget=forms.HiddenInput)

    def __init__(self,*args,rates,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['code'].choices=[(k,f'{k} — {v:,} تومان') for k,v in rates.items()]


class SettleForm(forms.Form):
    units=Units(label='مقدار دریافت‌شده')
    reference=forms.CharField(label='شناسهٔ یکتای تراکنش روی شبکه',max_length=160,
                              widget=forms.TextInput(attrs={'dir':'ltr'}))
    verified=forms.BooleanField(label='دریافت وجه، مقدار و نرخ نهایی را بررسی کرده‌ام.')
    expected=forms.IntegerField(widget=forms.HiddenInput,min_value=1)

    def clean_reference(self):
        value=self.cleaned_data['reference'].strip()
        if re.fullmatch(r'(?:0[xX])?[a-fA-F0-9]{64}',value):
            return value[-64:].lower()
        if re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{80,90}',value):
            return value
        raise forms.ValidationError('هش کامل تراکنش (TxID) شبکه را وارد کنید.')


def can_settle(user):
    return user.is_staff and user.has_perms(['portal.change_ticket','portal.settle_crypto_topup'])


def credit_amount(units,rate):
    with localcontext() as ctx:
        ctx.prec=60
        amount=int((units*rate).to_integral_value(rounding=ROUND_FLOOR))
    if not 0<amount<=LIMIT:
        raise BusinessError('معادل واریز باید بین ۱ و ۱۰۰٬۰۰۰٬۰۰۰ تومان باشد.')
    return amount


def current_buy(code,*,locked=False):
    qs=Currency.objects.filter(code=code,type='crypto',is_active=True)
    row=(qs.select_for_update() if locked else qs.select_related('fx')).first()
    if not row:raise RateError('این رمزارز در حال حاضر فعال نیست.')
    if locked:
        policy=CurrencyPricing.objects.select_for_update().filter(currency=row).first()
        return resolve(row.code,row.type,row.rate,policy).buy
    return currency_rates(row).buy


@transaction.atomic
def open_request(user,data):
    try:uid,key,seen=signing.loads(data['quote'],salt=SALT,max_age=900)
    except signing.BadSignature:raise BusinessError('مهلت نرخ تمام شده است؛ نرخ جدید را بررسی کنید.') from None
    if uid!=user.pk:raise PermissionDenied
    acct=get_object_or_404(Account.objects.select_for_update(),user=user)
    old=CryptoTopup.objects.filter(request_key=key,account=acct).first()
    if old:return old.ticket
    if not method_open('crypto'):raise BusinessError('ثبت شارژ رمزارزی در حال حاضر بسته است.')
    wallet=get_object_or_404(LegacyUser,pk=acct.legacy_id)
    if wallet.is_banned:raise PermissionDenied
    code,units=data['code'],data['units']
    rate=current_buy(code)
    if seen.get(code)!=rate:raise BusinessError('نرخ خرید تغییر کرده؛ رقم جدید را بررسی و دوباره ثبت کنید.')
    amount=credit_amount(units,rate)
    if not rate_limit('ticket:'+str(user.pk),5,3600):raise BusinessError('تعداد تیکت‌ها زیاد است. کمی بعد تلاش کنید.')
    ticket=Ticket.objects.create(user=user,subject=f'شارژ دستی کیف پول با {code}')
    CryptoTopup.objects.create(ticket=ticket,account=acct,request_key=key,code=code,units=units,requested_rate=rate)
    TicketMessage.objects.create(ticket=ticket,author=user,body=(
        f'درخواست شارژ: {units:f} {code}\nنرخ خرید هنگام درخواست: {rate:,} تومان · برآورد: {amount:,} تومان\n'+data['note']).strip())
    return ticket


@never_cache
@login_required
@require_http_methods(['GET','POST'])
def crypto_request(request):
    rates=available_rates() if method_open('crypto') else {}
    def new_quote():
        return signing.dumps([request.user.pk,str(uuid.uuid4()),rates],salt=SALT,compress=True)
    form=RequestForm(request.POST if request.method=='POST' else None,rates=rates,initial={'quote':new_quote()})
    if request.method=='POST' and form.is_valid():
        try:ticket=open_request(request.user,form.cleaned_data)
        except (BusinessError,RateError) as exc:
            rates=available_rates() if method_open('crypto') else {}
            data=request.POST.copy();data['quote']=new_quote()
            form=RequestForm(data,rates=rates);form.is_valid();form.add_error(None,str(exc))
        else:
            messages.success(request,'تیکت ثبت شد. آدرس و شبکهٔ واریز را از پشتیبانی همین تیکت بگیرید.')
            return redirect('ticket',pk=ticket.pk)
    return render(request,'crypto_request.html',{'form':form,'has_rates':bool(rates),'title':'تیکت شارژ با رمزارز'})


@transaction.atomic
def settle(user,ticket_id,data):
    if not can_settle(user):raise PermissionDenied
    ticket=get_object_or_404(Ticket.objects.select_for_update(),pk=ticket_id)
    entry=get_object_or_404(CryptoTopup.objects.select_for_update(),ticket=ticket)
    if entry.credited is not None or ticket.status=='closed':
        raise BusinessError('این درخواست قبلاً رسیدگی یا بسته شده است.')
    if not method_open('crypto'):raise BusinessError('روش شارژ رمزارزی غیرفعال است.')
    rate=current_buy(entry.code,locked=True)
    if data['expected']!=rate:raise BusinessError('نرخ مصوب تغییر کرده؛ نرخ جدید را بررسی کنید.')
    amount=credit_amount(data['units'],rate)
    wallet=get_object_or_404(LegacyUser.objects.select_for_update(),pk=entry.account.legacy_id)
    if wallet.is_banned:raise BusinessError('این حساب محدود شده است.')
    entry.paid_ref=data['reference']
    entry.paid_rate=rate;entry.paid_units=data['units'];entry.credited=amount;entry.settled_at=timezone.now()
    try:
        with transaction.atomic():entry.save()
    except IntegrityError:
        if CryptoTopup.objects.filter(paid_ref=entry.paid_ref).exists():
            raise BusinessError('این تراکنش قبلاً برای یک شارژ ثبت شده است.') from None
        raise
    wallet.balance+=amount;wallet.total_payments+=amount
    wallet.save(update_fields=['balance','total_payments'])
    ledger=Ledger.objects.create(user=wallet,amount=amount,type='deposit',description=f'شارژ دستی رمزارزی · تیکت #{ticket.pk}',
                                 payment_tracking_code=secrets.token_hex(5))
    TicketMessage.objects.create(ticket=ticket,author=user,body=f'دریافت {entry.paid_units:f} {entry.code} تأیید شد. با نرخ هر واحد {rate:,} تومان، مبلغ {amount:,} تومان به کیف پول اضافه شد.')
    ticket.status='closed';ticket.save(update_fields=['status','updated_at'])
    Audit.objects.create(actor=user,action='wallet.crypto.credit',object_ref=str(ticket.pk),details={
        'ledger':ledger.pk,'rate':rate,'units':str(entry.paid_units),'credit':amount,'txid':entry.paid_ref})
    return amount


@login_required
@require_POST
def settle_view(request,pk):
    if not can_settle(request.user):raise PermissionDenied
    form=SettleForm(request.POST)
    if form.is_valid():
        try:settle(request.user,pk,form.cleaned_data)
        except (BusinessError,RateError) as exc:messages.error(request,str(exc))
        else:messages.success(request,'شارژ ثبت شد.')
    else:
        messages.error(request,' · '.join(text for errors in form.errors.values() for text in errors))
    return redirect('ticket',pk=pk)
