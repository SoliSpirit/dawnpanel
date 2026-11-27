"""Group real Django 5xx responses without storing request data or traceback values."""
from hashlib import sha256
import logging
from pathlib import Path
import re
from threading import local

from django.conf import settings
from django.utils import timezone


_local=local()
METHODS={'GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'}
HINTS={
    'OperationalError':'اتصال و دسترسی پایگاه داده و وضعیت سرویس را در زمان رخداد بررسی کنید.',
    'IntegrityError':'قیدهای یکتایی، ارتباط رکوردها و تراکنش محل خطا را بررسی کنید.',
    'ProgrammingError':'نسخهٔ migrationهای پایگاه داده را با نسخهٔ برنامه تطبیق دهید.',
    'TemplateDoesNotExist':'نام و انتشار قالب در نسخهٔ ثبت‌شده را بررسی کنید.',
    'NoReverseMatch':'نام مسیر و آرگومان‌های ساخت پیوند را بررسی کنید.',
    'ValueError':'نوع و محدودهٔ مقدار مورد انتظار در محل خطا را بررسی کنید.',
    'KeyError':'وجود کلید مورد انتظار را در محل خطا بررسی کنید.',
}
TZ_HINT='تبدیل تاریخ MariaDB نامعتبر بود؛ تنظیم منطقهٔ زمانی یا وابستگی صفحه به تجمیع تاریخ را بررسی کنید.'


def identifier(value,default='unknown'):
    return value if isinstance(value,str) and re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.:<>-]{0,145}',value) else default


def record_issue(method,route,status,kind,frames=(),hint='',*,when=None,release=None,notify=True):
    from django.db import transaction
    from .models import OperationNotice,SiteIssue
    route=identifier(route,'unresolved')
    kind=identifier(kind,'Exception')[:96]
    method=method if method in METHODS else 'OTHER'
    # No formatted traceback, exception message, URL/path parameter, SQL, locals or client identity.
    frames=list(frames)[-10:]
    point=next((f for f in reversed(frames) if f.startswith(('portal.','dawn.'))),frames[-1] if frames else '')
    fingerprint=sha256(f'{method}|{route}|{status}|{kind}|{point.rsplit(":",1)[0]}'.encode()).hexdigest()
    at=when or timezone.now()
    release=Path(settings.BASE_DIR).name if release is None else release
    release=release if re.fullmatch(r'[a-f0-9]{40}',release) else ''
    with transaction.atomic():
        issue,created=SiteIssue.objects.select_for_update().get_or_create(fingerprint=fingerprint,defaults={
            'method':method,'route':route,'status_code':status,'kind':kind,'trace':'\n'.join(frames),
            'hint':hint or HINTS.get(kind,'مسیر، زمان و نسخه را با محل خطا در کد و گزارش سرویس تطبیق دهید.'),
            'first_seen':at,'last_seen':at,'release':release})
        reopened=False
        if not created:
            issue.occurrences+=1;issue.first_seen=min(at,issue.first_seen)
            if at>=issue.last_seen:
                issue.last_seen=at;issue.trace='\n'.join(frames);issue.release=release
                reopened=issue.resolved and (not issue.resolved_at or at>issue.resolved_at)
                if reopened:issue.resolved=False
            issue.save(update_fields=['occurrences','first_seen','last_seen','trace','release','resolved'])
        if notify and (created or reopened):
            label=f'HTTP {status} · {kind}' if status else kind
            OperationNotice.objects.create(topic='site_error',summary=f'{"بازگشت خطا" if reopened else "خطای جدید"}: {label}',
                origin='system',reference=str(issue.pk))
        return issue


DEPENDENCIES={
    'sms':('SMSDeliveryError','portal.services.request_otp','ارسال کد توسط سرویس پیامکی ناموفق بود. اتصال، اعتبار حساب و الگوی پیامک را بررسی کنید.'),
    'gateway_start':('PaymentStartError','portal.services.start_payment','ایجاد پرداخت در درگاه ناموفق بود. اتصال، تنظیمات پذیرنده و وضعیت درگاه را بررسی کنید.'),
    'gateway_verify':('PaymentVerifyError','portal.services.verify_payment','دریافت پاسخ معتبر برای تأیید پرداخت ناموفق بود. اتصال و وضعیت درگاه را بررسی کنید.'),
}


def report_dependency(request,error):
    info=DEPENDENCIES.get(getattr(error,'dependency',''))
    if info:
        try:record_issue(request.method,request.resolver_match.view_name,None,info[0],[info[1]],info[2])
        except Exception:pass  # retain the customer-facing response if the issue store itself is unavailable


class RequestIssueHandler(logging.Handler):
    def emit(self,record):
        code=getattr(record,'status_code',0)
        if type(code) is not int or not 500<=code<600 or getattr(_local,'writing',False):return
        _local.writing=True
        try:
            request=getattr(record,'request',None);match=getattr(request,'resolver_match',None)
            info=record.exc_info
            kind='HTTPError';frames=[];hint=''
            if isinstance(info,tuple) and len(info)==3 and info[0]:
                exc=info[1];kind=info[0].__name__
                if (kind=='ValueError' and exc.args and isinstance(exc.args[0],str)
                        and exc.args[0].startswith('Database returned an invalid datetime value')):hint=TZ_HINT
                tb=info[2];app=[];library=[]
                while tb:
                    module=identifier(tb.tb_frame.f_globals.get('__name__'))
                    func=identifier(tb.tb_frame.f_code.co_name)
                    frame=f'{module}.{func}:{tb.tb_lineno}'
                    if module.startswith(('portal.','dawn.')):app.append(frame)
                    elif module.startswith('django.'):library.append(frame)
                    tb=tb.tb_next
                frames=app[-6:]+library[-3:]
            record_issue(getattr(request,'method',None),getattr(match,'view_name',None),code,kind,frames,hint)
        except Exception:
            # A database outage must never recurse through logging or mask the original 500.
            pass
        finally:_local.writing=False
