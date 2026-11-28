"""A report is a frozen set of observations. Both review desks use the same writer."""
from datetime import timedelta
from decimal import Decimal,ROUND_CEILING
import csv,io
import re

from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404,redirect,render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET,require_http_methods

from .models import Audit,PriceReviewBatch,PriceReviewItem,Product,ProductSaleOverride,SourceProduct
from .notice_topics import subscribers
from .price_sync import apply_proposal,price_signature
from .pricing import BusinessError,MAX_TOTAL
from .product_media import ProfitPercentField
from .templatetags.ui import fa_number

NAMES={'premstore':'پریم‌استور','denapanel':'دناپنل'}
LABEL=dict(SourceProduct._meta.get_field('review_status').choices)|{'stale':'گزارش قدیمی','applied':'تأیید شده'}


def batch_url(pk):
    return 'https://dawnpanel.ir'+reverse('admin:price_review',args=[int(pk)])


def display_row(i):
    stale=(not i.decision and i.status in ('pending','unchanged') and
           (i.link.observed_at!=i.observed_at or i.link.review_status!=i.status or i.observed_at<timezone.now()-timedelta(days=1)))
    i.current_label=LABEL.get(i.decision or ('stale' if stale else i.status),i.status)
    i.source_label=NAMES.get(i.source,i.source)
    i.sale_before=i.fixed_before if i.fixed_before is not None else sale(i.base,i.markup)
    i.percent_sale=sale(i.observed,i.markup)
    i.sale_after=None
    if i.status in ('pending','unchanged'):
        if i.final_sale is not None:i.sale_after=i.final_sale
        elif i.fixed_before is not None:i.sale_after=i.fixed_before
        else:i.sale_after=sale(i.observed,i.final_markup if i.final_markup is not None else i.markup)
    i.editable=not i.decision and not stale and i.status in ('pending','unchanged')
    return i


def live_pending(batch):
    return batch.items.filter(status='pending',decision='',link__review_status='pending',observed_at=F('link__observed_at'),
                              observed_at__gte=timezone.now()-timedelta(days=1))


def sale(base,markup):
    if base is None or markup is None:return None
    return int((Decimal(base)*(100+markup)/100).to_integral_value(rounding=ROUND_CEILING))


def current_pack(product):
    if not product or product.price_currency!='TOMAN' or product.price_per<=0:return None
    if product.fixed_sale is not None:return product.fixed_sale
    return sale(product.price if product.price_amount is None else product.price_amount,product.product_profit_percent)


def toman_input(value):
    value=(value or '').strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬،','01234567890123456789,,'))
    if re.fullmatch(r'(?:[0-9]{1,12}|[0-9]{1,3}(?:,[0-9]{3}){1,3})',value):
        amount=int(value.replace(',',''))
        if 0<amount<=MAX_TOTAL:return amount
    raise ValidationError(f'مبلغ فروش را به تومان، از ۱ تا {fa_number(MAX_TOTAL)} و بدون اعشار وارد کنید.')


def email_sheet(pk):
    data=io.StringIO();w=csv.writer(data)
    w.writerow(['محصول','منبع','تعداد مبنا','قیمت قبلی منبع','قیمت جدید منبع','فروش هنگام بررسی','فروش پیشنهادی پیش از مالیات','وضعیت'])
    rows=PriceReviewItem.objects.filter(batch_id=int(pk),batch__ready=True).select_related('link')
    if not rows.exists():return None
    for i in rows.iterator():
        display_row(i);label=' '.join(i.label.split())
        if label.startswith(('=','+','-','@')):label="'"+label
        w.writerow([label,i.source_label,i.units,i.previous,i.observed,i.sale_before,i.sale_after,i.current_label])
    return (f'prices-{int(pk)}.csv','\ufeff'+data.getvalue(),'text/csv')


def allowed(request,site,write=False):
    source=site.get_model_admin(SourceProduct);product=site.get_model_admin(Product)
    return (source.has_change_permission(request) and product.has_change_permission(request)) if write else (
        source.has_view_or_change_permission(request) and product.has_view_or_change_permission(request))


@transaction.atomic
def decide(batch_pk,*,item_pk=None,markup=None,fixed_sale=None,actor=None,telegram_id=None,request=None,site=None):
    if telegram_id is not None:
        if telegram_id not in subscribers('price_review'):raise PermissionDenied
    elif request is None or actor!=request.user or not allowed(request,site,True):raise PermissionDenied
    if (fixed_sale is not None or markup is not None) and (not item_pk or telegram_id is not None):raise PermissionDenied
    batch=PriceReviewBatch.objects.select_for_update().get(pk=batch_pk,ready=True)
    rows=batch.items.select_for_update().filter(decision='')
    rows=rows.filter(pk=item_pk,status__in=('pending','unchanged')) if item_pk else rows.filter(status='pending')
    items=list(rows.order_by('link_id'))
    links=SourceProduct.objects.select_for_update().order_by('pk').in_bulk([r.link_id for r in items])
    products=Product.objects.select_for_update().order_by('pk').in_bulk(sorted({r.product_id for r in items}))
    if request:
        for model,objects in ((SourceProduct,links),(Product,products)):
            adm=site.get_model_admin(model)
            if len(objects)!=adm.get_queryset(request).filter(pk__in=objects).count() or not all(adm.has_change_permission(request,o) for o in objects.values()):
                raise PermissionDenied
    count=stale=0
    for i in items:
        link=links.get(i.link_id)
        valid=(link and link.product_id==i.product_id and i.product_id in products and link.observed_at==i.observed_at
               and link.review_status==i.status and i.observed_at>=timezone.now()-timedelta(hours=24))
        if valid and i.status=='unchanged' and fixed_sale is None and (markup is None or markup==i.markup and i.fixed_before is None):continue
        if valid:
            try:valid=apply_proposal(link.pk,actor,expected_observed_at=i.observed_at,markup=markup,fixed_sale=fixed_sale,review=True,telegram_admin_id=telegram_id)
            except BusinessError:valid=False
        i.decision='applied' if valid else 'stale'
        if valid:
            fixed=fixed_sale if fixed_sale is not None else (i.fixed_before if markup is None else None)
            i.final_markup=None if fixed is not None else (markup if markup is not None else i.markup)
            i.final_sale=fixed if fixed is not None else sale(i.observed,i.final_markup)
            count+=1
        else:stale+=1
        i.save(update_fields=['decision','final_markup','final_sale'])
    if count:Audit.objects.create(actor=actor,action='source.review.decide',object_ref=str(batch.pk),details={'count':count,'telegram_admin_id':telegram_id})
    return count,stale


@require_GET
def reports(request,site):
    if not allowed(request,site):raise PermissionDenied
    page=Paginator(PriceReviewBatch.objects.filter(ready=True).order_by('-pk'),15).get_page(request.GET.get('page'))
    return render(request,'admin/portal/price_reports.html',{**site.each_context(request),'title':'گزارش‌های بررسی قیمت','page':page})


@require_http_methods(['GET','POST'])
def report(request,site,pk):
    if not allowed(request,site):raise PermissionDenied
    batch=get_object_or_404(PriceReviewBatch,pk=pk,ready=True);write=allowed(request,site,True)
    pending=live_pending(batch).count()
    if request.method=='POST':
        if not write:raise PermissionDenied
        do=request.POST.get('decision')
        if do=='confirm_all':
            return render(request,'admin/portal/price_confirm.html',{**site.each_context(request),'title':'تأیید همهٔ پیشنهادهای گزارش','batch':batch,'pending':pending})
        if do not in ('all','one','fixed'):raise PermissionDenied
        item=None;markup=fixed=None
        if do in ('one','fixed'):
            value=request.POST.get('item','')
            if not re.fullmatch(r'[1-9][0-9]{0,17}',value):raise PermissionDenied
            item=get_object_or_404(batch.items,pk=int(value))
            try:
                if do=='fixed':fixed=toman_input(request.POST.get('sale_price'))
                else:markup=ProfitPercentField().clean(request.POST.get('markup'))
            except ValidationError as exc:
                messages.error(request,exc.messages[0]);return redirect(request.get_full_path()+f'#item-{item.pk}')
        n,s=decide(pk,item_pk=item.pk if item else None,markup=markup,fixed_sale=fixed,actor=request.user,request=request,site=site)
        if item and n and fixed is not None:messages.success(request,f'فروش هر {fa_number(item.units)} عدد «{item.label}» روی {fa_number(fixed)} تومان ثبت شد.')
        elif item and not n:messages.info(request,'قیمت تازه‌ای ثبت نشد. وضعیت ردیف و قیمت فعلی محصول را ببینید.')
        else:messages.info(request,f'{fa_number(n)} تأیید شد · {fa_number(s)} قدیمی یا متعارض بود.')
        return redirect(request.get_full_path()+(f'#item-{item.pk}' if item else ''))
    mode=request.GET.get('show','all');rows=batch.items.all()
    if mode=='pending':rows=live_pending(batch)
    elif mode=='changed':rows=rows.exclude(observed=F('previous'))
    else:mode='all'
    if focus:=request.GET.get('item'):
        if not re.fullmatch('[1-9][0-9]{0,17}',focus):raise PermissionDenied
        rows=batch.items.filter(pk=int(focus));mode='item'
    page=Paginator(rows.select_related('link'),12).get_page(request.GET.get('page'))
    items=[display_row(i) for i in page]
    products=site.get_model_admin(Product).get_queryset(request).in_bulk([i.product_id for i in items])
    for i in items:
        p=products.get(i.product_id)
        if i.editable and (not p or any(i.link.price_baseline.get(k)!=v for k,v in price_signature(p).items())):
            i.editable=False;i.current_label=LABEL['stale']
        i.live_sale=current_pack(p);i.live_units=p.price_per if p else None
    return render(request,'admin/portal/price_report.html',{**site.each_context(request),'title':'مقایسهٔ قیمت منابع','batch':batch,
        'pending':pending,'page':page,'items':items,'show':mode,'can_edit':write})


@require_http_methods(['GET','POST'])
@transaction.atomic
def current_price(request,site,pk,item_pk):
    """From a closed/superseded review, edit today's selling price, not yesterday's observation."""
    if not allowed(request,site,True):raise PermissionDenied
    row=get_object_or_404(PriceReviewItem,pk=item_pk,batch_id=pk,batch__ready=True)
    locked=request.method=='POST'
    def scoped(model,pk):
        adm=site.get_model_admin(model)
        ids=adm.get_queryset(request).order_by().values('pk')
        qs=model.objects.filter(pk__in=ids)
        obj=get_object_or_404(qs.select_for_update() if locked else qs,pk=pk)
        if not adm.has_change_permission(request,obj):raise PermissionDenied
        return obj
    link=scoped(SourceProduct,row.link_id);p=scoped(Product,row.product_id)
    if p.pk!=link.product_id:raise PermissionDenied
    valid=p.price_currency=='TOMAN' and p.price_per>0
    sig=[request.user.pk,row.pk,p.pk,link.pk,price_signature(p)]
    salt='portal.current-sale-price'
    url=reverse('admin:price_review',args=[pk],query={'item':row.pk})
    old=current_pack(p)
    entered=str(old);error=''
    if locked and valid:
        entered=request.POST.get('sale_price','')[:32]
        try:
            if signing.loads(request.POST.get('stamp',''),salt=salt,max_age=1800)!=sig:raise signing.BadSignature
            amount=toman_input(request.POST.get('sale_price',''))
        except signing.BadSignature:error='قیمت فعلی یا مهلت فرم تغییر کرده است. مبلغ جدید را بررسی و دوباره ثبت کنید.'
        except ValidationError as exc:error=exc.messages[0]
        else:
            if p.fixed_sale!=amount:
                ProductSaleOverride.objects.update_or_create(product_id=p.pk,defaults={'amount':amount,'units':p.price_per})
                if link.review_status in ('pending','unchanged'):
                    link.review_status='conflict';link.proposed_price=None;link.save(update_fields=['review_status','proposed_price'])
                Audit.objects.create(actor=request.user,action='product.sale.fixed',object_ref=str(p.pk),
                                     details={'old':old,'new':amount,'units':p.price_per,'report':pk})
            messages.success(request,f'فروش فعلی «{p.name}»: {fa_number(amount)} تومان.');return redirect(url)
    return render(request,'admin/portal/current_sale.html',{**site.each_context(request),'title':'ویرایش قیمت فعلی محصول',
        'p':p,'old':old,'entered':entered,'valid':valid,'stamp':signing.dumps(sig,salt=salt),'report_url':url,'error':error})
