from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from portal.models import OrderDelivery
from portal.order_notices import DeliveryError, dispatch, recipients, send_private


class Command(BaseCommand):
    help='Send queued purchase alerts to the private Telegram chats of configured bot admins.'

    def add_arguments(self, parser):
        group=parser.add_mutually_exclusive_group()
        group.add_argument('--test',action='store_true',help='Send a clearly identified test, without creating an order.')
        group.add_argument('--retry-stopped',action='store_true',help='Retry stopped deliveries to currently configured recipients.')

    def handle(self,*args,**opts):
        ids=recipients()
        if opts['test']:
            if not ids:raise CommandError('No private admin recipients configured.')
            try:
                for recipient in ids:
                    send_private(recipient,{'text':'🔔 تست اعلان خرید دان‌پنل\nاعلان سفارش‌های سایت و ربات در همین گفتگو می‌آید. این پیام آزمایشی است و سفارشی ثبت نشده.'})
            except DeliveryError as exc:raise CommandError(str(exc)) from None
            self.stdout.write(f'Telegram accepted a test for {len(ids)} private recipient(s).')
            return
        if opts['retry_stopped']:
            OrderDelivery.objects.filter(state='stopped',recipient__in=ids).update(state='pending',due_at=timezone.now(),last_error='')
        result=dispatch()
        if any(result.values()):self.stdout.write(str(result))
