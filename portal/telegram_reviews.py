"""Mobile Telegram review: one digest, a short index, then one price comparison."""
from html import escape
import re
from time import monotonic

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.urls import reverse

from .models import OrderDelivery, PriceReviewBatch
from .notice_topics import subscribers
from .pack_basis import pack_change
from .price_sync import sync_source
from .pricing import BusinessError
from .review_queue import NAMES, batch_url, decide, display_row, live_pending
from .supplier_clients import SupplierError
from .templatetags.ui import fa_datetime, fa_number

PER_PAGE = 5
CALLBACK = re.compile(r'pr:([1-9][0-9]{0,15}):([1-9][0-9]{0,7}):(home|pending|items|detail[pa]|(?:approve|reject|recheck)[hpa]|basis|u[1kf](?:_[a-f0-9]{20})?|ask|all|page|one):([0-9]{1,16})')


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


def item_controls(batch,i,view,page=1):
    """Always bind actions, including the digest's example, to its displayed observation."""
    keys=[]
    if i.status=='pending' and i.editable:
        keys.append([button(batch,'approve'+view,'✅ تأیید همین پیشنهاد',page=page,item=i.pk),
                     button(batch,'reject'+view,'❌ رد همین پیشنهاد',page=page,item=i.pk)])
    tools=[]
    if i.current_observation and i.source in NAMES:
        tools.append(button(batch,'recheck'+view,'🔄 بررسی مجدد قیمت',page=page,item=i.pk))
    if i.source_page:tools.append({'text':'صفحهٔ منبع','url':i.source_page})
    if tools:keys.append(tools)
    return keys


def digest(batch, notice=''):
    if batch.kind=='recheck':
        only=batch.items.values_list('pk',flat=True).first()
        if only:return detail_card(batch,only,1,False,notice=notice)
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
        lines+=['','<b>اولین پیشنهاد</b>',name(i,80),
                f'هر {money(i.units)} عدد · تومان، پیش از مالیات',
                f'فروش هنگام بررسی: {money(i.sale_before)}',f'فروش پیشنهادی: <b>{money(i.sale_after)}</b>']
        keys.extend(item_controls(batch,i,'h'))
    if notice:lines+=['',notice]
    nav=[button(batch,'items','همهٔ محصولات')]
    if n:nav.insert(0,button(batch,'pending',f'فهرست {fa_number(n)} پیشنهاد'))
    bottom=[web(batch)]
    if n:bottom.insert(0,button(batch,'ask','تأیید همه…'))
    if first:keys.append([button(batch,'basis','تنظیم مبنای همین محصول',item=first.pk)])
    return packet(lines,[*keys,nav,bottom])


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


def detail_card(batch,pk,page,pending,*,notice=''):
    item=batch.items.select_related('link').filter(pk=pk).first()
    if not item:raise BusinessError('محصول در این گزارش نیست.')
    i=display_row(item)
    lines=[f'<b>{name(i,110)}</b>',f'{escape(i.source_label)} · گزارش {fa_number(batch.pk)}']
    if batch.kind=='recheck':lines+=['بررسی مجدد · '+fa_datetime(i.observed_at)]
    if i.units:lines.append(f'مبنای قیمت: هر {money(i.units)} عدد')
    if i.feed_units and i.feed_units!=i.units:lines.append(f'تعداد اعلام‌شدهٔ منبع: {money(i.feed_units)}')
    lines+=[i.current_label]
    if notice:lines+=['',notice]
    before=f' · هر {money(i.before_units)} عدد' if i.before_units and i.before_units!=i.units else ''
    lines+=['','<b>فروش پیش از مالیات</b> · تومان',f'هنگام بررسی: {money(i.sale_before)}{before}']
    if i.sale_after is not None:
        label={'applied':'تأییدشده','rejected':'پیشنهاد ردشده'}.get(i.decision,'پیشنهادی')
        lines.append(f'{label}: <b>{money(i.sale_after)}</b>')
    lines+=['','<b>قیمت منبع</b> · تومان']
    prev=f' · هر {money(i.previous_units)} عدد' if i.previous_units and i.previous_units!=i.units else ''
    if i.previous==i.observed and i.observed is not None and not prev:lines.append(f'بدون تغییر: {money(i.observed)}')
    else:lines.extend([f'قبلی: {money(i.previous)}{prev}',f'تازه: {money(i.observed)}'])
    keys=item_controls(batch,i,'p' if pending else 'a',page)
    if not i.source_page:lines.append('لینک صفحهٔ منبع در دسترس نیست.')
    if notice and (i.decision or not i.current_observation):
        next_pk=live_pending(batch).exclude(pk=i.pk).values_list('pk',flat=True).first()
        if next_pk:keys.insert(0,[button(batch,'detailp','پیشنهاد بعدی ←',item=next_pk)])
    keys.append([button(batch,'basis','تنظیم مبنای قیمت',item=i.pk),web(batch,i,editable=i.editable)])
    if batch.kind!='recheck':
        keys.append([button(batch,'pending' if pending else 'items','فهرست محصولات',page=page),
                     button(batch,'home','خلاصهٔ گزارش')])
    return packet(lines,keys)


def recheck(batch,i,page,view,user_id):
    # sync_source does the bounded supplier I/O outside transactions. Its new
    # one-item report uses the ordinary durable outbox and its own message ID.
    error=''
    try:
        result=sync_source(i.source,link_ids=[i.link_id],recheck_item=i,telegram_admin_id=user_id,
                           deadline=monotonic()+35)
    except BusinessError as exc:error=escape(str(exc))
    except SupplierError:error='دریافت قیمت از منبع موفق نبود. دوباره تلاش کنید.'
    if user_id not in subscribers('price_review'):raise PermissionDenied
    if error:return detail_card(batch,i.pk,page,view!='a',notice=error)
    fresh=result['review_batch']
    return packet(['<b>بررسی مجدد انجام شد</b>',name(i,110),'',
                   f'نتیجه در گزارش جدید شمارهٔ {fa_number(fresh)} ارسال می‌شود. قیمت فروش تغییر نکرد.'],
                  [[{'text':'مشاهدهٔ نتیجه در سایت','url':batch_url(fresh)}],
                   [button(batch,'home','بازگشت به گزارش '+fa_number(batch.pk))]])


def telegram_digest(batch_pk):
    batch=PriceReviewBatch.objects.filter(pk=batch_pk,ready=True).first()
    if not batch:return {'text':'این گزارش دیگر در دسترس نیست.'}
    return digest(batch)


def pack_card(batch,pk,action,user):
    i=batch.items.filter(pk=pk).first()
    if not i:raise PermissionDenied
    code,_,proof=action.partition('_')
    choice={'basis':None,'u1':1,'uk':1000,'uf':'feed'}[code]
    back=[button(batch,'detaila','بازگشت به محصول',item=pk)]
    try:d=pack_change(i.product_id,choice,telegram_id=user,item=i,proof=proof or None)
    except BusinessError as exc:
        return packet([escape(str(exc))],[[button(batch,'basis','مشاهدهٔ مبنای فعلی',item=pk)],back])
    if proof:return packet([f'<b>{name(i,80)}</b>',f'مبنای فعلی: {money(d["pack"])} تومان برای هر {money(d["units"])} عدد.',
                            'برای دریافت پیشنهاد با این مبنا، قیمت منبع را دوباره بررسی کنید.'],[back])
    lines=[f'<b>{name(i,80)}</b>',f'فروش فعلی: {money(d["pack"])} تومان برای هر {money(d["old"])} عدد، پیش از مالیات.']
    if choice is not None:
        lines+=['',f'مبنای جدید: هر {money(d["units"])} عدد · مبلغ بسته ثابت می‌ماند.',
                f'سفارش {money(d["min_order"])} عددی با مالیات: از {money(d["before"])} به <b>{money(d["after"])} تومان</b>.']
        return packet(lines,[[button(batch,code+'_'+d['proof'],'ثبت مبنای قیمت',item=pk)],[button(batch,'basis','بازگشت',item=pk)]])
    keys=[[button(batch,'u1','تکی · ۱ عدد',item=pk),button(batch,'uk','بستهٔ ۱٬۰۰۰ عددی',item=pk)],
          [{'text':'تعداد دلخواه در سایت','url':'https://dawnpanel.ir'+reverse('admin:pack_editor',args=[i.product_id])}]]
    if d['feed']:keys[1].append(button(batch,'uf',f'مبنای منبع · {money(d["feed"])}',item=pk))
    return packet(lines+['','تعداد مبنای قیمت را برای پیش‌نمایش انتخاب کن:'],[*keys,back])


def telegram_action(user_id,chat_id,chat_type,message_id,data):
    match=CALLBACK.fullmatch(data or '')
    if not match or chat_type!='private' or user_id!=chat_id or user_id not in subscribers('price_review'):raise PermissionDenied
    raw_pk,raw_page,action,raw_target=match.groups()
    if not OrderDelivery.objects.filter(operation__topic='price_review',operation__reference=raw_pk,recipient=user_id,
                                       state='sent',message_id=message_id).exists():raise PermissionDenied
    batch=PriceReviewBatch.objects.filter(pk=int(raw_pk),ready=True).first()
    if not batch:raise BusinessError('مهلت گزارش تمام شده است.')
    page=int(raw_page);target=int(raw_target)
    item_action=action.startswith(('approve','reject','recheck','detail','u')) or action in ('one','basis')
    if item_action!=bool(target):raise PermissionDenied
    if action=='basis' or action.startswith('u'):return pack_card(batch,target,action,user_id)
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
    if action.startswith(('approve','reject','recheck')):
        i=batch.items.filter(pk=target).first()
        if not i:raise PermissionDenied
        if action.startswith('recheck'):return recheck(batch,i,page,action[-1],user_id)
        if i.status!='pending':raise PermissionDenied
        rejecting=action.startswith('reject')
        n,_=decide(batch.pk,item_pk=i.pk,telegram_id=user_id,reject=rejecting)
        notice='پیشنهاد رد شد. قیمت فروش تغییر نکرد.' if rejecting else 'قیمت پیشنهادی تأیید شد.'
        return detail_card(batch,i.pk,page,action[-1]!='a',notice=notice if n else 'این پیشنهاد قبلاً بررسی شده یا دیگر معتبر نیست.')
    if action=='home':return digest(batch)
    return index(batch,page,action=='pending')  # includes legacy 'page'
