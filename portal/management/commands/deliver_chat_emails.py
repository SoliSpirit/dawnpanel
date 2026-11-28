import smtplib
from django.core.management.base import BaseCommand,CommandError
from django.urls import reverse
from portal.chat_notices import dispatch_email,send_chat_email
from portal.models import NoticePreference
from portal.notice_topics import recipients


class Command(BaseCommand):
    help='Send due private live-chat emails; the web request and Telegram worker do not wait on SMTP.'
    def add_arguments(self,parser):
        parser.add_argument('--test',action='store_true',help='Send a labelled test only to opted-in destinations.')
    def handle(self,*args,**opts):
        if opts['test']:
            dest=NoticePreference.objects.filter(recipient__in=recipients(),chat_email_enabled=True).exclude(chat_email='').values_list('chat_email',flat=True).distinct()
            accepted=0
            for address in dest:
                try:
                    accepted+=send_chat_email(address,'این پیام آزمایشی است. میز گفتگوی آنلاین:\nhttps://dawnpanel.ir'+reverse('admin:chat_desk'),
                                              subject='تست اعلان ایمیلی چت دان‌پنل')
                except (smtplib.SMTPException,OSError):raise CommandError('SMTP did not accept the test.') from None
            if not accepted:raise CommandError('No test accepted. Check the enabled chat email destinations.')
            self.stdout.write(f'SMTP accepted {accepted} test message(s).')
            return
        result=dispatch_email()
        if any(result.values()):self.stdout.write(str(result))
