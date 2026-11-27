from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from portal.models import OrderDelivery
from portal.order_notices import DeliveryError, dispatch, recipients, send_private
from portal.notice_topics import TOPICS,subscribers


class Command(BaseCommand):
    help='Send subscribed purchase, staff and incident alerts to configured private Telegram recipients.'

    def add_arguments(self, parser):
        group=parser.add_mutually_exclusive_group()
        group.add_argument('--test',action='store_true',help='Send a clearly identified test, without creating an order.')
        group.add_argument('--retry-stopped',action='store_true',help='Retry stopped deliveries to currently configured recipients.')
        parser.add_argument('--test-topic',choices=tuple(TOPICS),help='Category for the explicit test (default: web_order).')

    def handle(self,*args,**opts):
        ids=recipients()
        if opts['test_topic'] and not opts['test']:raise CommandError('--test-topic requires --test.')
        if opts['test']:
            if not ids:raise CommandError('No private admin recipients configured.')
            topic=opts['test_topic'] or 'web_order'
            ids=subscribers(topic)
            try:
                for recipient in ids:
                    send_private(recipient,{'text':f'🔔 تست تنظیمات اعلان دان‌پنل\nنوع پیام: {TOPICS[topic]}\nتنظیمات این مدیر ارسال این نوع پیام را مجاز می‌داند. این پیام آزمایشی است.'},topic=topic)
            except DeliveryError as exc:raise CommandError(str(exc)) from None
            self.stdout.write(f'Telegram accepted a test for {len(ids)} private recipient(s).')
            return
        if opts['retry_stopped']:
            OrderDelivery.objects.filter(state='stopped',recipient__in=ids).update(state='pending',due_at=timezone.now(),last_error='')
        result=dispatch()
        if any(result.values()):self.stdout.write(str(result))
