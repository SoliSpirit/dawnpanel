"""Persist a bot submission and its private alert in the same database transaction."""
from django.db import connection,transaction
from django.utils import timezone
from .models import OperationNotice,OrderDelivery
from .notice_topics import subscribers
from .order_notices import DeliveryError


@transaction.atomic
def native_event(topic,ref,key,summary):
    op,created=OperationNotice.objects.get_or_create(notice_key=key,defaults={'topic':topic,'summary':summary,
        'reference':str(ref),'origin':'system','prepared':True})
    if created:OrderDelivery.objects.bulk_create([OrderDelivery(operation=op,recipient=r,due_at=timezone.now()) for r in subscribers(topic)])


@transaction.atomic
def save_submission(kind,uid,data,update_id):
    if type(update_id) is not int or update_id<0:raise ValueError('Missing Telegram update')
    topic={'ticket':'incoming_ticket','receipt':'incoming_receipt'}[kind]
    media=('photo' if data[-1] else 'document') if kind=='receipt' else 'text'
    summary=f'رسید تازه برای {data[0]:,} تومان در ربات ثبت شد.' if kind=='receipt' else 'درخواست پشتیبانی تازه در ربات ثبت شد.'
    # Reserve the Telegram update in the SAME transaction as the legacy insert.
    # No receipt, email or actionable notification is repeated after a reconnect.
    op,created=OperationNotice.objects.get_or_create(notice_key=f'{kind}-update:{update_id}:{media}',defaults={
        'topic':topic,'summary':summary,'origin':'telegram','prepared':True})
    if not created:return int(op.reference)
    with connection.cursor() as c:
        if kind=='ticket':
            subject,text=data
            c.execute('INSERT INTO support_messages (user_id,topic,message_text) VALUES (%s,%s,%s)',[uid,subject,text])
        elif kind=='receipt':
            amount,file_id,tracking,method,photo=data
            c.execute('INSERT INTO receipts (user_id,amount,photo_id,payment_method,payment_tracking_code) VALUES (%s,%s,%s,%s,%s)',[uid,amount,file_id,method,tracking])
        else:raise ValueError('Unknown submission')
        pk=c.lastrowid
    op.reference=str(pk);op.save(update_fields=['reference'])
    OrderDelivery.objects.bulk_create([OrderDelivery(operation=op,recipient=r,due_at=timezone.now()) for r in subscribers(topic)])
    return pk


def telegram_payload(op):
    with connection.cursor() as c:
        if op.topic=='incoming_ticket':
            c.execute('SELECT user_id,topic,message_text,answered FROM support_messages WHERE id=%s',[int(op.reference)])
            record=c.fetchone()
            if not record:raise DeliveryError('ticket_missing',permanent=True)
            uid,topic,body,answered=record
            msg={'text':f'پیام پشتیبانی #{op.reference} · کاربر {uid}\n{str(topic)[:150]}\n{str(body)[:1700]}'}
            if not answered:msg['reply_markup']={'inline_keyboard':[[{'text':'پاسخ به کاربر','callback_data':f'reply_support_{op.reference}_{uid}'}]]}
            return msg
        c.execute('SELECT user_id,amount,photo_id,payment_tracking_code,status FROM receipts WHERE id=%s',[int(op.reference)])
        record=c.fetchone()
        if not record:raise DeliveryError('receipt_missing',permanent=True)
        uid,amount,photo,tracking,status=record;pk=op.reference
        msg={('photo' if op.notice_key.endswith(':photo') else 'document'):photo,
             'caption':f'رسید #{pk} · کاربر {uid}\nمبلغ: {amount:,} تومان\nکد پیگیری: {tracking}'}
        if status=='pending':msg['reply_markup']={'inline_keyboard':[[{'text':'شارژ سریع','callback_data':f'quickcharge_{uid}_{amount}_{pk}_{tracking}'},
            {'text':'شارژ دستی','callback_data':f'approve_{uid}_{amount}_{pk}'}],[{'text':'رد رسید','callback_data':f'reject_{uid}_{amount}_{pk}'}]]}
        return msg
