import smtplib
from django.core.management.base import BaseCommand,CommandError
from portal.chat_notices import dispatch_email,send_chat_email
from portal.models import NoticePreference
from portal.notice_topics import TOPICS,mail_topics,recipients


class Command(BaseCommand):
    help='Deliver the independent admin email outbox. The deployed service name is kept for compatibility.'
    def add_arguments(self,parser):
        parser.add_argument('--test',action='store_true',help='Send a labelled test only to opted-in destinations.')
        parser.add_argument('--test-topic',choices=tuple(TOPICS),default='web_chat')
    def handle(self,*args,**opts):
        if opts['test']:
            topic=opts['test_topic']
            dest={p.chat_email for p in NoticePreference.objects.filter(pk__in=recipients()).exclude(chat_email='') if topic in mail_topics(p)}
            accepted=0
            for address in dest:
                try:
                    accepted+=send_chat_email(address,'این یک پیام آزمایشی برای دستهٔ «'+TOPICS[topic]+'» است.',subject='تست اعلان ایمیلی دان‌پنل')
                except (smtplib.SMTPException,OSError):raise CommandError('SMTP did not accept the test.') from None
            if not accepted:raise CommandError('No test accepted. Check the enabled chat email destinations.')
            self.stdout.write(f'SMTP accepted {accepted} test message(s).')
            return
        result=dispatch_email()
        if any(result.values()):self.stdout.write(str(result))
