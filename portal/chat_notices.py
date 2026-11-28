"""Non-blocking chat notifications. Only an authorized staff destination receives a private desk link."""
from datetime import timedelta
import smtplib
from time import monotonic
from uuid import uuid4

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import ChatEmailDelivery,NoticePreference,OperationNotice,OrderDelivery
from .notice_topics import recipients,subscribers


def address_key(address):
    return salted_hmac('portal.chat.email',address,algorithm='sha256').hexdigest()


def desk_link(thread):
    return 'https://dawnpanel.ir'+reverse('admin:chat_desk',query={'thread':str(thread)})


def queue_message(message):
    # The caller already holds the conversation lock; duplicate nonces never reach here.
    # Snapshot the audience now. Enabling a channel later must not deliver old chat.
    event=OperationNotice.objects.create(topic='web_chat',summary='یک پیام تازه در گفتگوی آنلاین سایت ثبت شد.',
                                         origin='system',reference=str(message.conversation_id),prepared=True)
    now=timezone.now()
    OrderDelivery.objects.bulk_create([OrderDelivery(operation=event,recipient=r,due_at=now) for r in subscribers('web_chat')])
    prefs=NoticePreference.objects.filter(recipient__in=recipients(),chat_email_enabled=True).exclude(chat_email='')
    ChatEmailDelivery.objects.bulk_create([ChatEmailDelivery(message=message,recipient=p.pk,
        destination_key=address_key(p.chat_email),due_at=now) for p in prefs])


@transaction.atomic
def claim():
    now=timezone.now()
    row=ChatEmailDelivery.objects.select_for_update().filter(state__in=('pending','sending'),due_at__lte=now).order_by('due_at','pk').first()
    if row:
        row.lease=uuid4();row.state='sending';row.attempts+=1;row.due_at=now+timedelta(minutes=3)
        row.save(update_fields=['lease','state','attempts','due_at'])
    return row


def send_chat_email(address,body,*,subject='پیام جدید در گفتگوی آنلاین دان‌پنل',headers=None):
    if settings.PRODUCTION and not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD and settings.EMAIL_USE_TLS):
        raise smtplib.SMTPException('SMTP not configured')
    return EmailMessage(subject,body,settings.DEFAULT_FROM_EMAIL,[address],headers=headers or {}).send()


def dispatch_email(limit=20):
    stats={'accepted':0,'retry':0,'stopped':0,'muted':0};deadline=monotonic()+40
    for _ in range(limit):
        if monotonic()>=deadline:break
        row=claim()
        if not row:break
        live=ChatEmailDelivery.objects.filter(pk=row.pk,lease=row.lease,state='sending')
        pref=NoticePreference.objects.filter(pk=row.recipient,chat_email_enabled=True).first()
        if (not pref or row.recipient not in recipients() or not pref.chat_email or address_key(pref.chat_email)!=row.destination_key):
            stats['muted']+=live.update(state='muted',lease=None,last_error='disabled')
            continue
        reason='';permanent=False
        try:
            url=desk_link(row.message.conversation_id)
            ok=send_chat_email(pref.chat_email,'یک پیام جدید در چت سایت منتظر بررسی است.\nابتدا با حساب مدیریت وارد سایت شوید و سپس گفتگو را باز کنید:\n'+url,
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
