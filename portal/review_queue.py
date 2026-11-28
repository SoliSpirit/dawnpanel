"""A report is a frozen set of observations. Both review desks use the same writer."""
from datetime import timedelta
from decimal import Decimal,ROUND_CEILING
import csv,io
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404,redirect,render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET,require_http_methods

from .models import Audit,OrderDelivery,PriceReviewBatch,PriceReviewItem,Product,SourceProduct
from .notice_topics import subscribers
from .price_sync import apply_proposal
from .pricing import BusinessError
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
    i.sale_before=sale(i.base,i.markup)
    i.sale_after=sale(i.observed,i.final_markup if i.final_markup is not None else i.markup) if i.status in ('pending','unchanged') else None
    i.editable=not i.decision and not stale and i.status in ('pending','unchanged')
    return i


def live_pending(batch):
    return batch.items.filter(status='pending',decision='',link__review_status='pending',observed_at=F('link__observed_at'),
                              observed_at__gte=timezone.now()-timedelta(days=1))


def sale(base,markup):
    if base is None or markup is None:return None
    return int((Decimal(base)*(100+markup)/100).to_integral_value(rounding=ROUND_CEILING))


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
def decide(batch_pk,*,item_pk=None,markup=None,actor=None,telegram_id=None,request=None,site=None):
    if telegram_id is not None:
        if telegram_id not in subscribers('price_review'):raise PermissionDenied
    elif request is None or actor!=request.user or not allowed(request,site,True):raise PermissionDenied
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
        if valid and i.status=='unchanged' and (markup is None or markup==i.markup):continue
        if valid:
            try:valid=apply_proposal(link.pk,actor,expected_observed_at=i.observed_at,markup=markup,review=True,telegram_admin_id=telegram_id)
            except BusinessError:valid=False
        i.decision='applied' if valid else 'stale'
        if valid:
            i.final_markup=markup if markup is not None else i.markup;count+=1
        else:stale+=1
        i.save(update_fields=['decision','final_markup'])
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
        if do not in ('all','one'):raise PermissionDenied
        item=None;markup=None
        if do=='one':
            value=request.POST.get('item','')
            if not re.fullmatch(r'[1-9][0-9]{0,17}',value):raise PermissionDenied
            item=get_object_or_404(batch.items,pk=int(value))
            try:markup=ProfitPercentField().clean(request.POST.get('markup'))
            except ValidationError:messages.error(request,'درصد سود معتبر وارد کنید.');return redirect(request.get_full_path())
        n,s=decide(pk,item_pk=item.pk if item else None,markup=markup,actor=request.user,request=request,site=site)
        messages.info(request,f'{fa_number(n)} تأیید شد · {fa_number(s)} قدیمی یا متعارض بود.');return redirect(request.get_full_path())
    mode=request.GET.get('show','all');rows=batch.items.all()
    if mode=='pending':rows=live_pending(batch)
    elif mode=='changed':rows=rows.exclude(observed=F('previous'))
    else:mode='all'
    page=Paginator(rows.select_related('link'),12).get_page(request.GET.get('page'))
    return render(request,'admin/portal/price_report.html',{**site.each_context(request),'title':'مقایسهٔ قیمت منابع','batch':batch,
        'pending':pending,'page':page,'items':[display_row(i) for i in page],'show':mode,'can_edit':write})


def telegram_page(batch_pk,page_number=1,*,confirm=False,notice=''):
    batch=PriceReviewBatch.objects.filter(pk=batch_pk,ready=True).first()
    if not batch:return {'text':'این گزارش دیگر در دسترس نیست.'}
    page=Paginator(batch.items.select_related('link'),5).get_page(page_number)
    pending=live_pending(batch).count()
    text=[f'گزارش قیمت #{batch.pk} · صفحهٔ {page.number} از {page.paginator.num_pages}',
          f'{fa_number(page.paginator.count)} محصول · {fa_number(pending)} پیشنهاد در انتظار تأیید',notice]
    keyboard=[]
    def button(label,action,pk=0):return {'text':label,'callback_data':f'pr:{batch.pk}:{page.number}:{action}:{pk}'}
    if confirm:
        text+=['همهٔ پیشنهادهای معتبر این گزارش، در تمام صفحه‌ها، با سود فعلی هر محصول اعمال شوند؟']
        keyboard.append([button('بله، تأیید همه','all'),button('بازگشت','page')])
    else:
        def money(v):return '—' if v is None else fa_number(v)
        for k,i in enumerate(page,1):
            display_row(i);label=' '.join(i.label.split())[:100]
            text.extend([f'{k}. {label} · {i.current_label}',f'{i.source_label} / {money(i.units)} عدد · منبع قبلی: {money(i.previous)} · تازه: {money(i.observed)}',
                         f'فروش قبل: {money(i.sale_before)} · پس از تأیید: {money(i.sale_after)} تومان'])
            if i.editable and i.status=='pending':keyboard.append([button(f'تأیید {k} · {label[:32]}','one',i.pk)])
        nav=[]
        if page.has_previous():nav.append({'text':'صفحهٔ قبل','callback_data':f'pr:{batch.pk}:{page.number-1}:page:0'})
        if page.has_next():nav.append({'text':'صفحهٔ بعد','callback_data':f'pr:{batch.pk}:{page.number+1}:page:0'})
        if nav:keyboard.append(nav)
        if pending:keyboard.append([button(f'تأیید همهٔ {fa_number(pending)} پیشنهاد…','ask')])
    keyboard.append([{'text':'تنظیم سود و مشاهده در سایت','url':batch_url(batch.pk)}])
    return {'text':'\n'.join(t for t in text if t),'reply_markup':{'inline_keyboard':keyboard}}


def telegram_action(user_id,chat_id,chat_type,message_id,data):
    match=re.fullmatch(r'pr:([1-9][0-9]{0,15}):([1-9][0-9]{0,7}):(page|one|ask|all):([0-9]{1,16})',data or '')
    if not match or chat_type!='private' or user_id!=chat_id or user_id not in subscribers('price_review'):raise PermissionDenied
    pk,page,action,target=match.groups()
    if not OrderDelivery.objects.filter(operation__topic='price_review',operation__reference=pk,recipient=user_id,
                                         state='sent',message_id=message_id).exists():raise PermissionDenied
    if not PriceReviewBatch.objects.filter(pk=int(pk),ready=True).exists():raise BusinessError('مهلت گزارش تمام شده است.')
    notice=''
    if action in ('one','all'):
        if action=='one' and not int(target):raise PermissionDenied
        n,s=decide(int(pk),item_pk=int(target) if action=='one' else None,telegram_id=user_id)
        notice=f'{fa_number(n)} تأیید شد · {fa_number(s)} قدیمی یا متعارض.'
    return telegram_page(int(pk),int(page),confirm=action=='ask',notice=notice)
