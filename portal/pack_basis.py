"""One explicit pack denomination for live checkout and subsequent supplier reviews."""
from dataclasses import replace
import json
import re
from time import time

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils.crypto import constant_time_compare,salted_hmac
from django.views.decorators.http import require_http_methods

from .models import Audit,Product,ProductSaleOverride,SourceProduct
from .notice_topics import recipients,subscribers
from .price_sync import price_signature
from .pricing import BusinessError,MAX_QUANTITY,pricing_for
from .templatetags.ui import fa_number


def pack_input(text):
    value=str(text).strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٬،','01234567890123456789,,'))
    if re.fullmatch(r'(?:[0-9]{1,9}|[0-9]{1,3}(?:,[0-9]{3}){1,2})',value):
        n=int(value.replace(',',''))
        if 1<=n<=MAX_QUANTITY:return n
    raise BusinessError(f'تعداد مبنا باید عدد صحیح بین ۱ و {fa_number(MAX_QUANTITY)} باشد.')


@transaction.atomic
def pack_change(pk,choice=None,*,proof=None,request=None,site=None,telegram_id=None,item=None):
    """No write until a price preview for this actor, product and choice is confirmed."""
    web=request is not None
    if web:
        if telegram_id is not None or not request.user.is_staff:raise PermissionDenied
        actor=f'web:{request.user.pk}'
    else:
        if telegram_id not in (subscribers('price_review') if item else recipients()):raise PermissionDenied
        actor=f'tg:{telegram_id}:{item.pk if item else "catalog"}'
    saving=proof is not None
    links=SourceProduct.objects
    link=(links.select_for_update() if saving else links).filter(product_id=pk).first()
    products=Product.objects
    p=get_object_or_404(products.select_for_update() if saving else products,pk=pk)
    if item and (not link or item.link_id!=link.pk or item.product_id!=p.pk or item.source!=link.source):
        raise PermissionDenied
    if web:
        for obj in (p,link):
            if obj is None:continue
            adm=site.get_model_admin(type(obj))
            if not adm.has_change_permission(request,obj) or not adm.get_queryset(request).filter(pk=obj.pk).exists():
                raise PermissionDenied
    pricing=pricing_for(p)
    feed=link.feed_units if link else None
    result={'pk':p.pk,'name':p.name,'old':p.price_per,'fixed':p.fixed_sale is not None,'pack':pricing.pack,
            'min_order':p.min_order,'before':pricing.amounts(p.min_order).total,'feed':feed,
            'override':link.pack_override if link else None,'link':link,'changed':False}
    if choice is None and not saving:return result
    auto=choice=='feed'
    if auto and not feed:raise BusinessError('تعداد اعلام‌شدهٔ منبع مشخص نیست.')
    units=feed if auto else pack_input(choice)
    override=units if link and not auto else None
    after=replace(pricing,price_per=units).quote(p.min_order).total
    state=[actor,p.pk,price_signature(p),p.min_order,p.max_order,pricing.pack,pricing.tax_bps,
           [link.pk,link.source,link.external_id,feed,link.pack_override,link.last_price,str(link.observed_at),
            link.review_status,link.proposed_price] if link else None,units,override]
    # Short enough for a Telegram callback; raw state is recomputed under the same locks as the write.
    interval=int(time()//900)
    def sign(slot):
        return salted_hmac('portal.pack-basis.v1',json.dumps([state,slot],sort_keys=True),algorithm='sha256').hexdigest()[:20]
    stamp=sign(interval)
    result.update(units=units,choice='feed' if auto else str(units),after=after,proof=stamp)
    if not saving:return result
    if not any(constant_time_compare(s,str(proof)) for s in (stamp,sign(interval-1))):
        raise BusinessError('قیمت، مبنا یا مهلت فرم تغییر کرده است؛ پیش‌نمایش تازه را ببینید.')
    if p.price_per==units and (not link or link.pack_override==override):return result
    fixed=p.fixed_sale
    if p.price_per!=units:
        # The pack amount is kept, not rescaled or switched to percentage pricing.
        policy=ProductSaleOverride.objects.filter(product_id=p.pk)
        if fixed is not None:policy.update(units=units)
        else:policy.delete()  # An inactive override for an older unit must not become active again.
        p.price_per=units;p.save(update_fields=['price_per'])
    if link:
        link.pack_override=override
        link.proposed_price=None
        link.review_status='conflict'
        link.save(update_fields=['pack_override','proposed_price','review_status'])
    Audit.objects.create(actor=request.user if web else None,action='product.pack.change',object_ref=str(p.pk),
        details={'old':result['old'],'new':units,'override_before':result['override'],'override_after':override,
                 'pack_toman':pricing.pack,'telegram_admin_id':telegram_id})
    result['changed']=True
    return result


@require_http_methods(['GET','POST'])
def pack_editor(request,site,pk):
    kwargs={'request':request,'site':site}
    error='';preview=None;entered=''
    try:
        if request.method=='POST':
            mode=request.POST.get('mode')
            if mode not in ('preview','save'):raise PermissionDenied
            entered=request.POST.get('units','')
            choice='feed' if request.POST.get('basis')=='feed' else entered
            preview=pack_change(pk,choice,proof=request.POST.get('proof','') if mode=='save' else None,**kwargs)
            if mode=='save':
                messages.success(request,f'مبنای «{preview["name"]}»: قیمت برای هر {fa_number(preview["units"])} عدد.')
                return redirect('admin:pack_editor',pk)
        current=preview or pack_change(pk,**kwargs)
    except BusinessError as exc:
        error=str(exc);preview=None
        try:current=pack_change(pk,**kwargs)
        except BusinessError:current=None
    return render(request,'admin/portal/pack_editor.html',{**site.each_context(request),'title':'تنظیم مبنای قیمت',
                  'p':current,'preview':preview,'error':error,'entered':entered[:24],'product_id':pk})
