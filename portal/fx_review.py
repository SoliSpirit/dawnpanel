"""Operator review of currency proposals. Observing a quote never publishes it."""
from datetime import datetime
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .exchange_rates import SOURCES, MAX_RATE, RateError, resolve, spread, supported, valid_age, refresh_rates, source_link
from .models import Audit, Currency, CurrencyPricing
from .source_catalog import DENA_PRICE_PER


def decimal_text(value):
    return format(Decimal(value).normalize(),'f') if value is not None else ''


def snapshot(row,policy):
    return [row.pk,row.code,row.type,row.rate,row.is_active,policy.source if policy else 'manual',
            policy.revision if policy else 0]


def candidate(row,policy,now):
    if not policy or policy.source=='manual':
        return Decimal(row.rate),Decimal(row.rate),None
    if (policy.last_error or not supported(row.code,row.type,policy.source)
            or policy.candidate_key!=f'{policy.source}:{row.code}'
            or not valid_age(policy.source,policy.candidate_at,now)
            or policy.candidate_bid is None or policy.candidate_ask is None):
        raise RateError(policy.last_error or 'پیشنهاد تازه‌ای در دسترس نیست؛ دوباره دریافت کنید.')
    return policy.candidate_bid,policy.candidate_ask,policy.candidate_at


class ReviewNumber(forms.DecimalField):
    def __init__(self,**kwargs):
        super().__init__(widget=forms.TextInput(attrs={'dir':'ltr','inputmode':'decimal'}),**kwargs)

    def to_python(self,value):
        if isinstance(value,str):
            from .admin_fx import normalized_number
            value=normalized_number(value)
        return super().to_python(value)


class RateReviewForm(forms.Form):
    basis_buy=ReviewNumber(label='پایهٔ خرید (تومان)',min_value=Decimal('0.00000001'),max_value=MAX_RATE,max_digits=25,decimal_places=8)
    basis_sell=ReviewNumber(label='پایهٔ فروش (تومان)',min_value=Decimal('0.00000001'),max_value=MAX_RATE,max_digits=25,decimal_places=8)
    mode=forms.ChoiceField(label='روش حاشیه',choices=CurrencyPricing.SPREADS)
    extra=ReviewNumber(label='سود فروش (+)',min_value=0,max_digits=16,decimal_places=4)
    less=ReviewNumber(label='کسریِ خرید / شارژ (−)',min_value=0,max_digits=16,decimal_places=4)
    active=forms.BooleanField(label='ارز برای مشتری فعال باشد',required=False)
    stamp=forms.CharField(widget=forms.HiddenInput)

    def __init__(self,*args,row,manual,**kwargs):
        super().__init__(*args,**kwargs)
        self.row,self.manual,self.preview=row,manual,None
        if manual:
            del self.fields['basis_sell']
            self.fields['basis_buy'].label='نرخ پایهٔ دستی (تومان)'

    def clean(self):
        data=super().clean()
        if self.errors:return data
        bid=data['basis_buy']
        ask=bid if self.manual else data['basis_sell']
        if self.manual and bid!=bid.to_integral_value():
            self.add_error('basis_buy','قیمت دستی را به تومان صحیح وارد کنید.')
        if data['mode']=='fixed' and any(data[f]!=data[f].to_integral_value() for f in ('extra','less')):
            self.add_error('mode','حاشیهٔ ثابت باید به تومان صحیح باشد.')
        if self.row.code=='TOMAN' and (bid!=1 or ask!=1 or data['extra'] or data['less']):
            raise forms.ValidationError('واحد تومان با نرخ یک و بدون حاشیه محاسبه می‌شود.')
        try:self.preview=spread(bid,ask,data['mode'],data['extra'],data['less'])
        except RateError as exc:raise forms.ValidationError(str(exc)) from None
        if self.row.code=='STAR' and (data['less']<=0 or self.preview.buy>=bid):
            self.add_error('less','برای استارز، کسریِ خرید مثبت وارد کنید تا نرخ شارژ از پایه کمتر باشد.')
        return data


class FxReviewMixin:
    change_list_template='admin/portal/fx_list.html'
    review_salt='portal.currency.review.v1'

    def get_urls(self):
        return [path('review/',self.admin_site.admin_view(self.review_view),name='portal_currency_review'),*super().get_urls()]

    def _review_rows(self,request):
        qs=self.get_queryset(request).order_by('code')
        raw=request.GET.get('rows')
        if raw:
            parts=raw.split(',')
            if any(not (s.isascii() and s.isdecimal() and len(s)<=19 and 0<int(s)<2**63) for s in parts):
                raise PermissionDenied
            qs=qs.filter(pk__in=[int(s) for s in parts])
        return [r for r in qs if self.has_change_permission(request,r)]

    def _review_card(self,request,row,data=None):
        p=getattr(row,'fx',None)
        src=p.source if p else 'manual'
        manual=src=='manual'
        current=proposed=None
        error=''
        try:current=resolve(row.code,row.type,row.rate,p)
        except RateError:pass
        try:bid,ask,at=candidate(row,p,timezone.now())
        except RateError as exc:
            bid=ask=at=None
            error=str(exc)
        # A suggested Stars discount is only a draft, never a live default.
        suggest=row.code=='STAR' and (not p or not p.buy_less)
        mode='percent' if suggest else (p.spread_mode if p else 'fixed')
        extra=Decimal(0) if suggest else (p.sell_extra if p else 0)
        less=Decimal(10) if suggest else (p.buy_less if p else 0)
        stamp=signing.dumps([request.user.pk,snapshot(row,p),decimal_text(bid),decimal_text(ask),
                             at.isoformat() if at else None],salt=self.review_salt)
        form=RateReviewForm(data,row=row,manual=manual,prefix=f'r{row.pk}',initial={
            'basis_buy':decimal_text(bid),'basis_sell':decimal_text(ask),'mode':mode,'extra':decimal_text(extra),
            'less':decimal_text(less),'active':row.is_active,'stamp':stamp})
        if data is not None:
            if form.is_valid():proposed=form.preview
        elif not error:
            try:proposed=spread(bid,ask,mode,extra,less)
            except RateError:pass
        return {'row':row,'form':form,'current':current,'preview':proposed,'bid':decimal_text(bid),'ask':decimal_text(ask),
                'source_url':source_link(src,row.code),'pack_size':DENA_PRICE_PER,
                'pack_price':bid*DENA_PRICE_PER if src=='denapanel' and bid is not None else None,
                'manual':manual,'at':at,'suggest':suggest,'error':error,'source':SOURCES[src][0] if src in SOURCES else 'دستی'}

    @transaction.atomic
    def _publish(self,request,cards):
        now=timezone.now()
        # Deterministic lock order, like the poller. Re-read the live policy and
        # the source evidence before applying any part of this selection.
        for card in sorted(cards,key=lambda c:c['row'].pk):
            form=card['form']; data=form.cleaned_data
            pk=card['row'].pk
            scope=self.get_queryset(request).filter(pk=pk).order_by().values('pk')
            row=Currency.objects.select_for_update().get(pk=pk,pk__in=scope)
            p=CurrencyPricing.objects.select_for_update().filter(currency=row).first()
            if not self.has_change_permission(request,row):raise PermissionDenied
            try:
                uid,before,bid0,ask0,stamp=signing.loads(data['stamp'],salt=self.review_salt,max_age=1800)
            except signing.BadSignature:
                raise RateError('مهلت پیش‌نمایش تمام شده یا معتبر نیست؛ فهرست را دوباره بررسی کنید.') from None
            if uid!=request.user.pk:raise PermissionDenied
            bid,ask,at=candidate(row,p,now)
            if (before!=snapshot(row,p) or bid0!=decimal_text(bid) or ask0!=decimal_text(ask)
                    or (at and (not stamp or not valid_age(p.source,datetime.fromisoformat(stamp),now)))):
                raise RateError(f'اطلاعات {row.code} از زمان مشاهده تغییر کرده؛ فهرست تازه را بررسی کنید.')
            p=p or CurrencyPricing(currency=row)
            old={'base':row.rate,'bid':decimal_text(p.market_bid),'ask':decimal_text(p.market_ask),
                 'mode':p.spread_mode,'extra':decimal_text(p.sell_extra),'less':decimal_text(p.buy_less),'active':row.is_active}
            row.is_active=data['active']
            final_ask=data.get('basis_sell',data['basis_buy'])
            if p.source=='manual':
                row.rate=int(data['basis_buy'])
            else:
                p.quote_key=f'{p.source}:{row.code}'
                p.market_bid,p.market_ask,p.observed_at=data['basis_buy'],final_ask,at
            row.save(update_fields=['rate','is_active','updated_at'])
            p.spread_mode,p.sell_extra,p.buy_less=data['mode'],data['extra'],data['less']
            p.revision+=1;p.published_at=now;p.save()
            Audit.objects.create(actor=request.user,action='currency.publish',object_ref=row.code,details={
                'old':old,'source':p.source,'source_bid':bid0,'source_ask':ask0,'observed_at':at.isoformat() if at else None,
                'bid':decimal_text(data['basis_buy']),'ask':decimal_text(final_ask),'mode':p.spread_mode,
                'less':decimal_text(p.buy_less),'extra':decimal_text(p.sell_extra),'active':row.is_active,
                'buy':form.preview.buy,'sell':form.preview.sell})
            self.log_change(request,row,'تأیید نرخ و حاشیهٔ خرید و فروش')

    @method_decorator(csrf_protect)
    @method_decorator(require_http_methods(['GET','HEAD','POST']))
    def review_view(self,request):
        if not self.has_change_permission(request) or '_popup' in request.GET:raise PermissionDenied
        rows=self._review_rows(request)
        if request.method=='POST' and '_fetch' in request.POST:
            result=refresh_rates([r.pk for r in rows])
            if any(result.values()):
                self.message_user(request,'برخی مراجع پاسخ معتبر ندادند؛ جزئیات در ردیف همان ارز آمده است.',messages.WARNING)
            else:
                self.message_user(request,'فهرست پیشنهادها آماده است. قیمت‌های جدید با تأیید شما منتشر می‌شوند.')
            return HttpResponseRedirect(request.get_full_path())
        page=Paginator(rows,10).get_page(request.GET.get('p'))
        selection=request.POST.getlist('selected') if request.method=='POST' else []
        if '_one' in request.POST:selection=[request.POST['_one']]
        if not set(selection)<=set(str(r.pk) for r in page):raise PermissionDenied
        cards=[self._review_card(request,r,request.POST if str(r.pk) in selection else None) for r in page]
        chosen=[c for c in cards if c['form'].is_bound]
        if request.method=='POST':
            if not chosen:self.message_user(request,'حداقل یک ارز را انتخاب کنید.',messages.WARNING)
            elif all(not c['error'] and c['form'].is_valid() for c in chosen):
                if '_publish' in request.POST or '_one' in request.POST:
                    try:self._publish(request,chosen)
                    except (RateError,Currency.DoesNotExist) as exc:
                        self.message_user(request,str(exc) or 'ارز دیگر موجود نیست.',messages.ERROR)
                        return HttpResponseRedirect(request.get_full_path())
                    self.message_user(request,f'نرخ {len(chosen)} ارز تأیید و ذخیره شد.')
                    return HttpResponseRedirect(reverse('admin:portal_currency_changelist'))
        return render(request,'admin/portal/fx_review.html',{**self.admin_site.each_context(request),
            'opts':self.opts,'title':'بررسی و تأیید قیمت ارزها','cards':cards,'page':page,'selection':request.GET.get('rows','')})
