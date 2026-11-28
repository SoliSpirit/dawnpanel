"""Durable, allowlisted private Telegram delivery. No network I/O inside checkout or row locks."""
from datetime import timedelta
from time import monotonic
from uuid import uuid4

import requests
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import OperationNotice, OrderDelivery, OrderEvent, SiteIssue
from .notice_topics import policies,recipients,subscribers,TOPICS


def order_topic(channel):
    return {'web':'web_order','telegram':'bot_order'}[channel]


def approval_buttons(order_id):
    return [[{'text':'✅ تایید سفارش','callback_data':f'confirmorder_{order_id}'},
             {'text':'❌ لغو سفارش','callback_data':f'rejectorder_{order_id}'}],
            [{'text':'🎉 تکمیل سفارش','callback_data':f'completeorder_{order_id}'}],
            [{'text':'🔙 بازگشت','callback_data':f'backorder_{order_id}'}]]


def order_message(event):
    o=event.order
    text=(f'📦 سفارش جدید از {event.get_channel_display()}\nکد پیگیری: {o.tracking_code}\n'
          f'محصول: {o.product_name}\nتعداد: {o.quantity:,}\nمبلغ پرداخت‌شده: {o.total_price:,} تومان')
    if o.status!='pending':text+=f'\nوضعیت فعلی: {o.status_label}'
    # Web-only wallet IDs aren't Telegram chats. Manage those orders on the website.
    rows=approval_buttons(o.pk) if event.channel=='telegram' and o.status=='pending' else []
    rows.append([{'text':'جزئیات سفارش در مدیریت','url':'https://dawnpanel.ir'+reverse('admin:portal_order_change',args=[o.pk])}])
    if event.channel=='web' and o.status=='pending':
        rows.append([{'text':'رسیدگی در میز سفارش‌ها','url':'https://dawnpanel.ir'+reverse('admin:requests_desk')}])
    return {'text':text,'reply_markup':{'inline_keyboard':rows},'link_preview_options':{'is_disabled':True}}


class DeliveryError(Exception):
    def __init__(self,reason,*,permanent=False,retry_after=0):
        super().__init__(reason)
        self.permanent,self.retry_after=permanent,retry_after


def operation_message(event):
    origin={'web':'پنل سایت','telegram':'ربات','system':'سایت'}[event.origin]
    text=f'{TOPICS[event.topic]}\n{event.summary}\nمبدأ: {origin}'
    if event.actor_key:text+=f'\nمدیر {"تلگرام" if event.origin=="telegram" else "سایت"}: #{event.actor_key}'
    if event.reference and event.topic!='web_chat':text+=f'\nشناسه: {event.reference}'
    payload={'text':text,'link_preview_options':{'is_disabled':True}}
    if event.topic=='site_error':
        route=SiteIssue.objects.filter(pk=event.reference).values_list('route',flat=True).first()
        if route:payload['text']+=f'\nمسیر برنامه: {route}'
        path=reverse('admin:portal_siteissue_change',args=[event.reference])
        payload['reply_markup']={'inline_keyboard':[[{'text':'بررسی خطا در پنل','url':'https://dawnpanel.ir'+path}]]}
    elif event.topic=='web_chat':
        from .chat_notices import desk_link
        payload['reply_markup']={'inline_keyboard':[[{'text':'پاسخ به گفتگو','url':desk_link(event.reference)}]]}
    return payload


def send_private(recipient, payload, *, topic=None):
    if recipient not in recipients():raise DeliveryError('recipient_removed',permanent=True)
    if topic is not None and recipient not in subscribers(topic):
        raise DeliveryError('muted',permanent=True)
    token=settings.BOT_CONFIG.get('telegram',{}).get('token')
    if not token:raise DeliveryError('missing_token')
    try:
        response=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                               json={**payload,'chat_id':recipient,'disable_notification':False},
                               allow_redirects=False,timeout=(4,8))
        try:data=response.json()
        except ValueError:data={}
    except requests.RequestException:
        # Requests exceptions may contain the token-bearing URL. Never persist/log them.
        raise DeliveryError('network') from None
    if not isinstance(data,dict):data={}
    if response.status_code==429:
        params=data.get('parameters');delay=params.get('retry_after') if isinstance(params,dict) else None
        raise DeliveryError('telegram_429',retry_after=delay if type(delay) is int and 0<delay<=86400 else 60)
    result=data.get('result')
    if (response.status_code==200 and data.get('ok') is True and isinstance(result,dict)
            and type(result.get('message_id')) is int and result['message_id']>0
            and isinstance(result.get('chat'),dict) and result['chat'].get('id')==recipient):
        return result['message_id']
    raise DeliveryError(f'telegram_{response.status_code}',permanent=response.status_code in (400,403))


@transaction.atomic
def prepare(limit):
    prefs=policies()
    if not prefs:return
    events=list(OrderEvent.objects.select_for_update().filter(prepared=False).order_by('pk')[:limit])
    ops=list(OperationNotice.objects.select_for_update().filter(prepared=False).order_by('pk')[:limit])
    now=timezone.now()
    deliveries=[OrderDelivery(event=e,recipient=r,due_at=now) for e in events for r,enabled in prefs.items()
                if order_topic(e.channel) in enabled]
    deliveries += [OrderDelivery(operation=e,recipient=r,due_at=now) for e in ops for r,enabled in prefs.items() if e.topic in enabled]
    OrderDelivery.objects.bulk_create(deliveries)
    OrderEvent.objects.filter(pk__in=[e.pk for e in events]).update(prepared=True)
    OperationNotice.objects.filter(pk__in=[e.pk for e in ops]).update(prepared=True)


@transaction.atomic
def claim():
    now=timezone.now()
    row=(OrderDelivery.objects.select_for_update().filter(state__in=('pending','sending'),due_at__lte=now)
         .order_by('due_at','pk').first())
    if row:
        row.lease=uuid4();row.state='sending';row.attempts+=1;row.due_at=now+timedelta(minutes=3)
        row.save(update_fields=['lease','state','attempts','due_at'])
    return row


def dispatch(limit=20):
    prepare(limit)
    counts={'sent':0,'retry':0,'stopped':0}
    until=monotonic()+40
    for _ in range(limit):
        if monotonic()>=until:break
        row=claim()
        if not row:break
        live=OrderDelivery.objects.filter(pk=row.pk,state='sending',lease=row.lease)
        try:
            if row.event_id:
                event=OrderEvent.objects.select_related('order').get(pk=row.event_id)
                topic,payload=order_topic(event.channel),order_message(event)
            else:
                event=row.operation
                topic,payload=event.topic,operation_message(event)
            message_id=send_private(row.recipient,payload,topic=topic)
        except (DeliveryError,OrderEvent.DoesNotExist,OperationNotice.DoesNotExist) as exc:
            error=exc if isinstance(exc,DeliveryError) else DeliveryError('event_missing',permanent=True)
            wait=max(error.retry_after,min(3600,15*2**min(row.attempts-1,8)))
            state='muted' if str(error)=='muted' else ('stopped' if error.permanent else 'pending')
            changed=live.update(state=state,lease=None,
                                last_error=str(error),due_at=timezone.now()+timedelta(seconds=wait))
            key='muted' if state=='muted' else ('stopped' if error.permanent else 'retry')
            counts[key]=counts.get(key,0)+changed
            if changed and error.retry_after:
                until_retry=timezone.now()+timedelta(seconds=wait)
                OrderDelivery.objects.filter(recipient=row.recipient,state='pending',due_at__lt=until_retry).update(due_at=until_retry)
                break
        else:
            counts['sent']+=live.update(state='sent',lease=None,last_error='',sent_at=timezone.now(),message_id=message_id)
    return counts
