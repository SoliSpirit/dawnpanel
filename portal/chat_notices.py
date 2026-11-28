"""Non-blocking chat notifications. Only an authorized staff destination receives a private desk link."""
from datetime import timedelta
import smtplib
from time import monotonic
from uuid import uuid4

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import ChatEmailDelivery,NoticePreference,OperationNotice,OrderDelivery,OrderEvent
from .notice_topics import TOPICS,mail_topics,recipients,subscribers


def address_key(address):
    return salted_hmac('portal.chat.email',address,algorithm='sha256').hexdigest()


def desk_link(thread):
    return 'https://dawnpanel.ir'+reverse('admin:chat_desk',query={'thread':str(thread)})


def enqueue_email(topic,*,using='default',**source):
    prefs=NoticePreference.objects.using(using).filter(pk__in=recipients()).exclude(chat_email='')
    now=timezone.now()
    ChatEmailDelivery.objects.using(using).bulk_create([ChatEmailDelivery(**source,topic=topic,recipient=p.pk,
        destination_key=address_key(p.chat_email),due_at=now) for p in prefs if topic in mail_topics(p)])


@receiver(post_save,sender=OrderEvent,dispatch_uid='mail.new.order')
def order_email(sender,instance,created,raw,using,**kw):
    if created and not raw:
        from .order_notices import order_topic
        enqueue_email(order_topic(instance.channel),event=instance,using=using)


@receiver(post_save,sender=OperationNotice,dispatch_uid='mail.new.operation')
def operation_email(sender,instance,created,raw,using,**kw):
    if created and not raw and instance.topic in TOPICS and instance.topic!='web_chat':
        enqueue_email(instance.topic,operation=instance,using=using)


def queue_message(message):
    # The caller already holds the conversation lock; duplicate nonces never reach here.
    # Snapshot the audience now. Enabling a channel later must not deliver old chat.
    event=OperationNotice.objects.create(topic='web_chat',summary='یک پیام تازه در گفتگوی آنلاین سایت ثبت شد.',
                                         origin='system',reference=str(message.conversation_id),prepared=True)
    now=timezone.now()
    OrderDelivery.objects.bulk_create([OrderDelivery(operation=event,recipient=r,due_at=now) for r in subscribers('web_chat')])
    enqueue_email('web_chat',message=message)


@transaction.atomic
def claim():
    now=timezone.now()
    row=ChatEmailDelivery.objects.select_for_update().filter(state__in=('pending','sending'),due_at__lte=now).order_by('due_at','pk').first()
    if row:
        row.lease=uuid4();row.state='sending';row.attempts+=1;row.due_at=now+timedelta(minutes=3)
        row.save(update_fields=['lease','state','attempts','due_at'])
    return row


def send_chat_email(address,body,*,subject='پیام جدید در گفتگوی آنلاین دان‌پنل',headers=None,url=None,button='ورود به پنل مدیریت',attachment=None):
    if settings.PRODUCTION and not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD and settings.EMAIL_USE_TLS):
        raise smtplib.SMTPException('SMTP not configured')
    url=url or 'https://dawnpanel.ir'+reverse('admin:index')
    msg=EmailMultiAlternatives(subject,body+'\n\n'+url,settings.DEFAULT_FROM_EMAIL,[address],headers=headers or {})
    msg.attach_alternative(render_to_string('mail/admin_notice.html',{'subject':subject,'lines':body.splitlines(),'url':url,'button':button}),'text/html')
    if attachment:msg.attach(*attachment)
    return msg.send()


def email_content(row):
    base='https://dawnpanel.ir'
    if row.message_id:
        return ('یک پیام جدید در گفتگوی آنلاین سایت منتظر بررسی است.',desk_link(row.message.conversation_id),'باز کردن گفتگو')
    if row.event_id:
        from .order_notices import order_message
        return (order_message(row.event)['text'],base+reverse('admin:portal_order_change',args=[row.event_id]),'مشاهدهٔ سفارش')
    op=row.operation
    if op.topic=='price_review':
        from .review_queue import batch_url
        return (op.summary+'\nفهرست مقایسهٔ قیمت‌ها را در پنل ببینید. نسخهٔ جدولی گزارش‌های موجود نیز به ایمیل پیوست می‌شود.',batch_url(op.reference),'مقایسهٔ قیمت‌ها')
    if op.topic in ('incoming_ticket','incoming_receipt','lottery_warning'):
        import re
        bot=settings.BOT_CONFIG.get('telegram',{}).get('bot_username','DawnPanel_Bot')
        url='https://t.me/'+bot.lstrip('@') if isinstance(bot,str) and re.fullmatch(r'@?[A-Za-z][A-Za-z0-9_]{4,31}',bot) else base+reverse('admin:index')
        return (op.summary+(f'\nشناسه: {op.reference}' if op.reference else ''),url,'بررسی در ربات مدیریت')
    from .order_notices import operation_message
    payload=operation_message(op)
    url=base+reverse('admin:index')
    if op.topic=='site_error':url=base+reverse('admin:portal_siteissue_change',args=[op.reference])
    elif op.topic=='order_status' and op.reference.isdecimal():url=base+reverse('admin:portal_order_change',args=[op.reference])
    return (payload['text'],url,'مشاهده در پنل مدیریت')


def dispatch_email(limit=20):
    stats={'accepted':0,'retry':0,'stopped':0,'muted':0};deadline=monotonic()+40
    for _ in range(limit):
        if monotonic()>=deadline:break
        row=claim()
        if not row:break
        live=ChatEmailDelivery.objects.filter(pk=row.pk,lease=row.lease,state='sending')
        pref=NoticePreference.objects.filter(pk=row.recipient).first()
        if (not pref or row.topic not in mail_topics(pref) or row.recipient not in recipients() or not pref.chat_email or address_key(pref.chat_email)!=row.destination_key):
            stats['muted']+=live.update(state='muted',lease=None,last_error='disabled')
            continue
        reason='';permanent=False
        try:
            body,url,button=email_content(row)
            attachment=None
            if row.topic=='price_review':
                from .review_queue import email_sheet
                attachment=email_sheet(row.operation.reference)
            ok=send_chat_email(pref.chat_email,body,subject=TOPICS[row.topic]+' | دان‌پنل',url=url,button=button,
                attachment=attachment,
                headers={'Message-ID':f'<chat-notice-{row.pk}@dawnpanel.ir>','Auto-Submitted':'auto-generated'})
            if ok!=1:reason='not_accepted'
        except smtplib.SMTPRecipientsRefused as exc:
            permanent=any(500<=r[0]<600 for r in exc.recipients.values());reason='recipient_refused'
        except (smtplib.SMTPException,OSError):
            reason='smtp_unavailable'
        if reason:
            permanent=permanent or row.attempts>=15
            stats['stopped' if permanent else 'retry']+=live.update(state='stopped' if permanent else 'pending',lease=None,
                last_error=reason,due_at=timezone.now()+timedelta(seconds=min(7200,30*2**min(row.attempts,8))))
        else:stats['accepted']+=live.update(state='sent',lease=None,last_error='',sent_at=timezone.now())
    return stats
