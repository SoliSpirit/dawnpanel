"""Reporting never recomputes historical cost from today's catalogue, FX or markup."""
from datetime import date,timedelta
from decimal import ROUND_CEILING,localcontext

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count,Q,Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404,redirect,render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET,require_POST

from .admin_overview import date_label,midnight
from .models import Account,Audit,Order,OrderCost,SourceProduct
from .pricing import ceil_div
from .source_catalog import DENA_PRICE_PER

PERIODS=(('today','امروز',1),('yesterday','دیروز',1),('week','۷ روز اخیر',7),('month','۳۰ روز اخیر',30),('year','۳۶۵ روز اخیر',365))
STATUSES={'pending':'منتظر بررسی','confirmed':'در حال انجام','approved':'تأییدشده','processing':'در حال پردازش',
          'completed':'تکمیل‌شده','cancelled':'لغوشده','rejected':'ردشده'}


def snapshot_cost(order,p,pricing):
    source='';estimate=at=None
    link=SourceProduct.objects.filter(product_id=p.pk).first()
    now=timezone.now()
    units={'denapanel':DENA_PRICE_PER,'premstore':1}.get(link.source) if link else None
    if (units and p.price_per==units and link.available and link.last_price>0 and link.observed_at
            and now-timedelta(hours=24)<=link.observed_at<=now and link.review_status in ('pending','applied','unchanged')):
        estimate=ceil_div(link.last_price*order.quantity,units);source=link.source;at=link.observed_at
    elif p.product_profit_percent>0 and pricing.base_pack is not None:
        with localcontext() as ctx:
            ctx.prec=80
            estimate=int((pricing.base_pack*order.quantity/pricing.price_per).to_integral_value(rounding=ROUND_CEILING))
        source='base';at=now
    if estimate is not None and 0<=estimate<2**63:
        OrderCost.objects.create(order=order,estimated=estimate,source=source,basis_at=at)


def can_view(user):
    return user.is_active and user.is_staff and user.has_perms(['portal.view_order','portal.view_financial_report'])


def period_bounds(params,today):
    period=params.get('period','today');end=today;error=''
    if period=='custom':
        try:
            start=date.fromisoformat(params.get('start',''));end=date.fromisoformat(params.get('end',''))
            if not date(2000,1,1)<=start<=end<=today or (end-start).days>365:raise ValueError
        except ValueError:
            start=end=today;period='today';error='بازه معتبر نیست. گزارش امروز نمایش داده شد.'
    else:
        lengths={k:n for k,_,n in PERIODS}
        if period not in lengths:period='today'
        if period=='yesterday':end-=timedelta(days=1)
        start=end-timedelta(days=lengths[period]-1)
    return period,start,end,error


@require_GET
def finance_report(request,site):
    if not can_view(request.user):raise PermissionDenied
    today=timezone.localdate();period,start,end,error=period_bounds(request.GET,today)
    basis='completed' if request.GET.get('basis')=='completed' else 'placed'
    field='completed_at' if basis=='completed' else 'created_at'
    orders=site.get_model_admin(Order).get_queryset(request).filter(**{
        field+'__gte':midnight(start),field+'__lt':midnight(end+timedelta(days=1))})
    if basis=='completed':orders=orders.filter(status='completed')
    channel=request.GET.get('channel','')
    if channel in ('web','telegram'):orders=orders.filter(orderevent__channel=channel)
    elif channel=='unknown':orders=orders.filter(orderevent__isnull=True)
    else:channel=''
    status=request.GET.get('status','')
    if status in STATUSES:orders=orders.filter(status=status)
    else:status=''
    q=request.GET.get('q','').strip()[:100]
    if q:
        people=Account.objects.filter(Q(user__first_name__icontains=q)|Q(user__last_name__icontains=q)).values('legacy_id')
        match=(Q(tracking_code__icontains=q)|Q(product_name__icontains=q)|Q(user__full_name__icontains=q)|
               Q(user__username__icontains=q)|Q(user_id__in=people))
        if q.removeprefix('-').isdecimal() and len(q)<=19 and abs(int(q))<2**63:match|=Q(user_id=int(q))
        orders=orders.filter(match)
    done=Q(status='completed');known=done&Q(amounts__isnull=False,cost_record__actual__isnull=False)
    estimate=done&Q(amounts__isnull=False,cost_record__actual__isnull=True,cost_record__estimated__isnull=False)
    refund=Q(status__in=('rejected','cancelled'))
    metrics=orders.aggregate(count=Count('pk'),buyers=Count('user_id',distinct=True),placed=Sum('total_price',default=0),
        done=Count('pk',filter=done),completed=Sum('total_price',filter=done,default=0),
        cancelled=Sum('total_price',filter=refund,default=0),tax=Sum('amounts__tax_amount',filter=done,default=0),
        before_tax=Sum('amounts__subtotal',filter=done,default=0),
        tax_missing=Count('pk',filter=done&Q(amounts__isnull=True)),
        known=Count('pk',filter=known),net=Sum('amounts__subtotal',filter=known,default=0),
        cost=Sum('cost_record__actual',filter=known,default=0),
        estimates=Count('pk',filter=estimate),estimated_net=Sum('amounts__subtotal',filter=estimate,default=0),
        estimated_cost=Sum('cost_record__estimated',filter=estimate,default=0))
    metrics['profit']=metrics['net']-metrics['cost'];metrics['est_profit']=metrics['estimated_net']-metrics['estimated_cost']
    metrics['missing']=metrics['done']-metrics['known']-metrics['estimates']
    rows=orders.select_related('user','amounts','cost_record','orderevent').order_by('-'+field,'-pk')
    page=Paginator(rows,25).get_page(request.GET.get('page'));items=list(page)
    accounts={a.legacy_id:a for a in Account.objects.filter(legacy_id__in=[o.user_id for o in items]).select_related('user')}
    for o in items:
        account=accounts.get(o.user_id)
        o.buyer=(account.user.get_full_name() if account else '') or o.user.full_name or (('@'+o.user.username) if o.user.username else 'خریدار')
        if account and request.user.has_perm('portal.view_account'):
            o.buyer_url=reverse('admin:portal_account_change',args=[account.pk])
        cost=getattr(o,'cost_record',None);amounts=getattr(o,'amounts',None);o.report_profit=None
        o.report_cost=cost.actual if cost and cost.actual is not None else (cost.estimated if cost else None)
        o.cost_label='قطعی' if cost and cost.actual is not None else {'denapanel':'برآورد دناپنل','premstore':'برآورد پریم‌استور','base':'برآورد از پایهٔ قیمت'}.get(cost.source if cost else '','نامشخص')
        if o.status=='completed' and amounts and o.report_cost is not None:o.report_profit=amounts.subtotal-o.report_cost
    return render(request,'admin/portal/finance_report.html',{**site.each_context(request),'title':'گزارش مالی خریدها',
        'items':items,'page':page,'metrics':metrics,'period':period,'periods':PERIODS,'basis':basis,'channel':channel,
        'status':status,'statuses':STATUSES,'q':q,'start':start,'end':end,'today':today,'error':error,
        'caption':date_label(start) if start==end else f'{date_label(start)} تا {date_label(end)}',
        'can_cost':request.user.has_perm('portal.record_order_cost')})


@require_POST
@transaction.atomic
def record_cost(request,pk,site):
    if not can_view(request.user) or not request.user.has_perm('portal.record_order_cost'):raise PermissionDenied
    raw=request.POST.get('cost','').strip()
    if not raw.isdecimal() or len(raw)>15:return HttpResponseBadRequest('بهای کل سفارش را به تومان صحیح و بدون جداکننده وارد کنید.')
    o=get_object_or_404(site.get_model_admin(Order).get_queryset(request).select_for_update(),pk=pk)
    if not site.get_model_admin(Order).has_view_permission(request,o):raise PermissionDenied
    row,_=OrderCost.objects.select_for_update().get_or_create(order=o)
    if request.POST.get('revision')!=str(row.revision):messages.error(request,'بهای تأمین تغییر کرده؛ مقدار جدید را بررسی کنید.')
    elif row.actual!=int(raw):
        before=row.actual;row.actual=int(raw);row.revision+=1;row.updated_at=timezone.now()
        row.save(update_fields=['actual','revision','updated_at'])
        Audit.objects.create(actor=request.user,action='finance.cost',object_ref=str(o.pk),details={'previous':before,'actual':row.actual})
        messages.success(request,'بهای واقعی تأمین برای همین سفارش ثبت شد.')
    return redirect(reverse('admin:finance_report',query=request.GET))
