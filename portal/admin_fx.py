from decimal import Decimal
import re

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.utils import formats, timezone
from django.utils.html import format_html

from .exchange_rates import RateError, resolve, spread, supported, source_link, refresh_rates
from .models import Currency, CurrencyPricing
from .templatetags.ui import fa_number
from .fx_review import FxReviewMixin
from django.http import HttpResponseRedirect
from django.urls import reverse


def normalized_number(value):
    value=value.strip().replace('٫','.').replace('٬',',')
    if ',' in value:
        if not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?',value):
            raise forms.ValidationError('اعشار را با «٫» یا «.» وارد کن. ویرگول فقط جداکنندهٔ هزارگان است.')
        value=value.replace(',','')
    return value


class AdjustmentField(forms.DecimalField):
    def __init__(self, **kwargs):
        super().__init__(min_value=0,max_digits=16,decimal_places=4,initial=0,
            widget=forms.TextInput(attrs={'inputmode':'decimal','dir':'ltr'}), **kwargs)

    def to_python(self,value):
        if isinstance(value,str):
            value=normalized_number(value)
        return super().to_python(value)


class CurrencyForm(forms.ModelForm):
    fx_source=forms.ChoiceField(label='مرجع نرخ',choices=CurrencyPricing.SOURCES,initial='manual',
        help_text='نوبیتکس برای بازار مستقیم رمزارز به ریال؛ نرخ‌آرا برای دلار نقدی و ارزهای پشتیبانی‌شده. دریافت خودکار هر دو دقیقه بررسی می‌شود.')
    spread_mode=forms.ChoiceField(label='نوع حاشیه',choices=CurrencyPricing.SPREADS,initial='fixed')
    sell_extra=AdjustmentField(label='افزودنیِ فروش به مشتری')
    buy_less=AdjustmentField(label='کسریِ خرید از مشتری',
        help_text='مثال مبلغ ثابت: اگر مرجع ۲۸۰٬۰۰۰ تومان باشد، با افزودنی ۵٬۰۰۰ و کسری ۱۰٬۰۰۰، فروش ۲۸۵٬۰۰۰ و خرید ۲۷۰٬۰۰۰ می‌شود.')

    class Meta:
        model=Currency
        fields='__all__'
        labels={'rate':'نرخ پایهٔ دستی (تومان)'}
        help_texts={'rate':'فقط در حالت «دستی» استفاده می‌شود.'}

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.policy=getattr(self.instance,'fx',None) if self.instance.pk else None
        if self.policy:
            self.initial.update(fx_source=self.policy.source,spread_mode=self.policy.spread_mode,
                                sell_extra=self.policy.sell_extra,buy_less=self.policy.buy_less)

    def clean(self):
        data=super().clean()
        if not {'code','type','rate','fx_source','spread_mode','sell_extra','buy_less'} <= data.keys():
            return data
        code=data['code']=data['code'].strip().upper()
        src,mode=data['fx_source'],data['spread_mode']
        extra,less=data['sell_extra'],data['buy_less']
        if not supported(code,data['type'],src):
            self.add_error('fx_source','این مرجع برای کد و نوع ارز انتخاب‌شده معتبر نیست.')
        if code=='TOMAN' and (data['rate']!=1 or extra or less):
            self.add_error(None,'تومان با نرخ ثابت ۱ و بدون حاشیه محاسبه می‌شود.')
        if mode=='percent' and less>=100:
            self.add_error('buy_less','درصد کسر خرید باید کمتر از ۱۰۰ باشد.')
        if mode=='fixed' and (extra!=extra.to_integral_value() or less!=less.to_integral_value()):
            self.add_error('spread_mode','مبلغ ثابت را به تومانِ صحیح وارد کن.')
        bid=ask=None
        if src=='manual':
            bid=ask=Decimal(data['rate'])
        elif self.policy and self.policy.quote_key==f'{src}:{code}':
            bid,ask=self.policy.market_bid,self.policy.market_ask
        if bid is not None and ask is not None:
            try:
                effective=spread(bid,ask,mode,extra,less)
                if code=='STAR' and data.get('is_active') and effective.buy>=bid:
                    self.add_error('buy_less','برای فعال کردن شارژ با استارز، کسری خرید مثبت لازم است.')
            except RateError as exc:self.add_error(None,str(exc))
        return data


class CurrencyRatesAdminMixin(FxReviewMixin):
    form=CurrencyForm
    list_hint='نرخ‌های این جدول مصوب‌اند. «به‌روزرسانی قیمت ارزها» پیشنهاد تازه را می‌گیرد تا آن را ویرایش و تأیید کنید.'
    list_display=['code','name','reference','buy_quote','sell_quote','quote_time','is_active']
    fieldsets=[
        ('مشخصات ارز',{'fields':['code','name','type','symbol','icon','is_active']}),
        ('نرخ مرجع و حاشیهٔ هر واحد',{'fields':['fx_source','rate','spread_mode','sell_extra','buy_less']}),
    ]
    actions=['refresh_quotes']

    def get_queryset(self,request):
        return super().get_queryset(request).select_related('fx')

    @transaction.atomic
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        current,_=CurrencyPricing.objects.select_for_update().get_or_create(currency=obj)
        src=form.cleaned_data['fx_source']
        if src!=current.source or current.quote_key!=f'{src}:{obj.code}':
            current.quote_key=current.last_error=''
            current.checked_at=current.observed_at=current.market_bid=current.market_ask=None
            if src!=current.source or current.candidate_key!=f'{src}:{obj.code}':
                current.candidate_key=''
                current.candidate_at=current.candidate_bid=current.candidate_ask=None
            current.published_at=None
        current.source=src
        current.spread_mode=form.cleaned_data['spread_mode']
        current.sell_extra=form.cleaned_data['sell_extra']
        current.buy_less=form.cleaned_data['buy_less']
        current.revision+=1
        current.save()

    @admin.display(description='مرجع')
    def reference(self,obj):
        p=getattr(obj,'fx',None)
        if not p or p.source=='manual':return f'دستی · {fa_number(obj.rate)}'
        label=p.get_source_display()
        last='دریافتی ثبت نشده'
        if p.quote_key==f'{p.source}:{obj.code}' and p.market_ask is not None:
            def localized(amount):
                text=format(amount,',f')
                if '.' in text:text=text.rstrip('0').rstrip('.')
                return text.translate(str.maketrans('0123456789,.','۰۱۲۳۴۵۶۷۸۹٬٫'))
            if p.source=='nerkhara':
                last=localized(p.market_ask)
            else:
                last=f'خرید {localized(p.market_bid)} · فروش {localized(p.market_ask)}'
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>'
                           '<small class="catalog-row-category">{}</small>',source_link(p.source,obj.code),label,last)

    def _quote(self,obj,side):
        try:
            rates=resolve(obj.code,obj.type,obj.rate,getattr(obj,'fx',None))
            return fa_number(getattr(rates,side))
        except RateError as exc:
            return format_html('<span title="{}">نرخ معتبر نیست</span>',str(exc))

    @admin.display(description='خرید از مشتری (تومان)')
    def buy_quote(self,obj):
        return self._quote(obj,'buy')

    @admin.display(description='فروش به مشتری (تومان)')
    def sell_quote(self,obj):
        return self._quote(obj,'sell')

    @admin.display(description='آخرین تأیید')
    def quote_time(self,obj):
        p=getattr(obj,'fx',None)
        if not p or p.source=='manual':return 'دستی'
        at=p.published_at
        stamp=formats.date_format(timezone.localtime(at),'j F، H:i') if at else 'در انتظار تأیید'
        if p.last_error:
            return format_html('{}<small class="catalog-row-category">{}</small>',stamp,p.last_error)
        return stamp

    @admin.action(description='دریافت نرخ ارزهای انتخاب‌شده اکنون',permissions=['change'])
    def refresh_quotes(self,request,queryset):
        from django.core.exceptions import PermissionDenied
        rows=list(queryset)
        if not self.has_change_permission(request) or not all(self.has_change_permission(request,row) for row in rows):
            raise PermissionDenied
        refresh_rates([r.pk for r in rows])
        url=reverse('admin:portal_currency_review')
        return HttpResponseRedirect(url+'?rows='+','.join(str(r.pk) for r in rows))
