"""Mobile Telegram review: one digest, a short index, then one price comparison."""
from html import escape
import re

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.urls import reverse

from .models import OrderDelivery, PriceReviewBatch
from .notice_topics import subscribers
from .pricing import BusinessError
from .review_queue import NAMES, batch_url, decide, display_row, live_pending
from .templatetags.ui import fa_datetime, fa_number

PER_PAGE = 5
CALLBACK = re.compile(r'pr:([1-9][0-9]{0,15}):([1-9][0-9]{0,7}):(home|pending|items|detailp|detaila|approvep|approvea|ask|all|page|one):([0-9]{1,16})')


def button(batch, action, title, *, page=1, item=0):
    return {'text':title, 'callback_data':f'pr:{batch.pk}:{page}:{action}:{item}'}


def name(item, limit):
    # Keep Persian half spaces, but don't let pasted direction controls reorder prices.
    text=' '.join(re.sub(r'[\x00-\x1f\x7f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]', ' ', item.label).split())
    return escape(text if len(text)<=limit else text[:limit-1].rstrip()+'…', quote=False)


def packet(lines, keyboard):
    return {'text':'\n'.join(lines), 'parse_mode':'HTML', 'reply_markup':{'inline_keyboard':keyboard}}


def money(v):
    return 'ثبت نشده' if v is None else fa_number(v)


def web(batch, item=None, *, editable=False):
    url=batch_url(batch.pk)
    if item:
        if editable:url+=f'?item={item.pk}#item-{item.pk}'
        else:url='https://dawnpanel.ir'+reverse('admin:current_sale_price',args=[batch.pk,item.pk])
    return {'text':'ویرایش قیمت در سایت' if item else 'باز کردن گزارش در سایت','url':url}


def digest(batch, notice=''):
    qs=live_pending(batch)
    counts=list(qs.order_by('source').values('source').annotate(n=Count('pk')))
    n=sum(r['n'] for r in counts)
    lines=[f'<b>گزارش قیمت {fa_number(batch.pk)}</b>', fa_datetime(batch.created_at), '',
           f'<b>{fa_number(n)} پیشنهاد منتظر تأیید</b>' if n else '<b>پیشنهاد فعالی برای تأیید نمانده است.</b>',
           f'از {fa_number(batch.items.count())} محصول بررسی‌شده']
    if counts:lines.append('  ·  '.join(f'{escape(NAMES.get(r["source"],r["source"]))}: {fa_number(r["n"])}' for r in counts))
    first=qs.select_related('link').first() if n else None
    keys=[]
    if first:
        i=display_row(first)
        lines+=['','<b>اولین پیشنهاد</b>',name(i,64),
                f'هر {money(i.units)} عدد · تومان، پیش از مالیات',
                f'فروش هنگام بررسی: {money(i.sale_before)}',f'فروش پیشنهادی: <b>{money(i.sale_after)}</b>']
        keys.append([button(batch,'pending',f'بررسی {fa_number(n)} پیشنهاد')])
    if notice:lines+=['',notice]
    nav=[button(batch,'items','همهٔ محصولات')]
    if n:nav.append(button(batch,'ask','تأیید همه…'))
    return packet(lines,[*keys,nav,[web(batch)]])


def index(batch,number,pending,notice=''):
    rows=live_pending(batch) if pending else batch.items.all()
    page=Paginator(rows,PER_PAGE).get_page(number)
    view='pending' if pending else 'items';detail='detailp' if pending else 'detaila'
    lines=['<b>پیشنهادهای منتظر تأیید</b>' if pending else '<b>همهٔ محصولات گزارش</b>',
           f'گزارش {fa_number(batch.pk)} · صفحهٔ {fa_number(page.number)} از {fa_number(page.paginator.num_pages)}']
    if notice:lines+=['',notice]
    keys=[];choices=[]
    if page.paginator.count:
        lines+=['','برای دیدن قیمت‌ها، شمارهٔ محصول را بزنید.']
        for n,i in enumerate(page,page.start_index()):
            lines.append(f'{fa_number(n)}. {name(i,64)}')
            choices.append(button(batch,detail,fa_number(n),page=page.number,item=i.pk))
        keys.append(choices)
    else:lines+=['','موردی برای نمایش نمانده است.']
    nav=[]
    if page.has_previous():nav.append(button(batch,view,'صفحهٔ قبل',page=page.number-1))
    if page.has_next():nav.append(button(batch,view,'صفحهٔ بعد',page=page.number+1))
    if nav:keys.append(nav)
    keys.append([button(batch,'home','خلاصهٔ گزارش')])
    return packet(lines,keys)


def detail_card(batch,pk,page,pending):
    item=batch.items.select_related('link').filter(pk=pk).first()
    if not item:raise BusinessError('محصول در این گزارش نیست.')
    i=display_row(item)
    lines=[f'<b>{name(i,110)}</b>',f'{escape(i.source_label)} · هر {money(i.units)} عدد',
           i.current_label,'','<b>فروش پیش از مالیات</b> · تومان',
           f'هنگام بررسی: {money(i.sale_before)}',
           ('تأییدشده' if i.decision=='applied' else 'پیشنهادی')+f': <b>{money(i.sale_after)}</b>',
           '','<b>قیمت منبع</b> · تومان']
    if i.previous==i.observed and i.observed is not None:lines.append(f'بدون تغییر: {money(i.observed)}')
    else:lines.extend([f'قبلی: {money(i.previous)}',f'تازه: {money(i.observed)}'])
    keys=[]
    if i.status=='pending' and i.editable:
        keys.append([button(batch,'approvep' if pending else 'approvea','تأیید همین پیشنهاد',page=page,item=i.pk)])
    keys.extend([[web(batch,i,editable=i.editable)],[button(batch,'pending' if pending else 'items','فهرست محصولات',page=page),
                                                        button(batch,'home','خلاصهٔ گزارش')]])
    return packet(lines,keys)


def telegram_digest(batch_pk):
    batch=PriceReviewBatch.objects.filter(pk=batch_pk,ready=True).first()
    if not batch:return {'text':'این گزارش دیگر در دسترس نیست.'}
    return digest(batch)


def telegram_action(user_id,chat_id,chat_type,message_id,data):
    match=CALLBACK.fullmatch(data or '')
    if not match or chat_type!='private' or user_id!=chat_id or user_id not in subscribers('price_review'):raise PermissionDenied
    raw_pk,raw_page,action,raw_target=match.groups()
    if not OrderDelivery.objects.filter(operation__topic='price_review',operation__reference=raw_pk,recipient=user_id,
                                       state='sent',message_id=message_id).exists():raise PermissionDenied
    batch=PriceReviewBatch.objects.filter(pk=int(raw_pk),ready=True).first()
    if not batch:raise BusinessError('مهلت گزارش تمام شده است.')
    page=int(raw_page);target=int(raw_target)
    if action in ('detailp','detaila','one'):
        # Old messages' «تأیید ۱ · نام محصول» now open its comparison first.
        return detail_card(batch,target,page,action=='detailp')
    if action=='ask':
        n=live_pending(batch).count()
        if not n:return digest(batch)
        return packet(['<b>تأیید گروهی قیمت‌ها</b>','',
                       f'{fa_number(n)} پیشنهاد معتبر در تمام صفحه‌های گزارش {fa_number(batch.pk)} تأیید شود؟',
                       'روش قیمت‌گذاری هر محصول حفظ می‌شود.'],
                      [[button(batch,'all','بله، تأیید همه')],[button(batch,'home','بازگشت')]])
    if action=='all':
        n,s=decide(batch.pk,telegram_id=user_id)
        return digest(batch, f'تأیید شد: {fa_number(n)} · قدیمی یا متعارض: {fa_number(s)}')
    if action in ('approvep','approvea'):
        if not target:raise PermissionDenied
        n,_=decide(batch.pk,item_pk=target,telegram_id=user_id)
        return index(batch,page,action=='approvep','پیشنهاد تأیید شد.' if n else 'این پیشنهاد قبلاً بررسی شده یا اعتبارش تمام شده است.')
    if action=='home':return digest(batch)
    return index(batch,page,action=='pending')  # includes legacy 'page'
