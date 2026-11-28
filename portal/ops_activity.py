"""Committed administrative actions, using fixed descriptions rather than submitted form data."""
from django.contrib.admin.models import ADDITION, CHANGE, DELETION
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Audit, OperationNotice
from .notice_topics import recipients


AUDITED = {
    'finance.cost':('finance','ثبت بهای واقعی تأمین سفارش'),
    'ticket.reply': ('support','پاسخ مدیر به تیکت'),
    'ticket.close': ('support','بستن تیکت توسط مدیر'),
    'chat.reply': ('support','پاسخ مدیر به گفتگوی پشتیبانی'),
    'chat.close': ('support','بستن گفتگوی پشتیبانی'),
    'order.status': ('order_status','تغییر وضعیت سفارش'),
    'receipt.approve': ('finance','تأیید رسید و شارژ کیف پول'),
    'receipt.reject': ('finance','رد رسید پرداخت'),
    'wallet.crypto.credit': ('finance','تأیید شارژ رمزارزی'),
    'source.price.apply': ('catalog','تأیید قیمت پیشنهادی منبع'),
    'source.price.reject': ('catalog','رد قیمت پیشنهادی منبع'),
    'source.price.recheck': ('catalog','بررسی مجدد قیمت‌های انتخاب‌شده'),
    'source.price.fetch': ('catalog','دریافت فهرست قیمت منبع'),
    'source.review.decide': ('catalog','تأیید قیمت‌های بررسی‌شده'),
    'catalog.profit.batch': ('catalog','تغییر گروهی سود محصولات'),
    'notice.settings': ('management','تغییر تنظیمات اعلان تلگرام'),
    'notice.email': ('management','تغییر تنظیمات ایمیل چت'),
    'issue.resolve': ('management','علامت‌گذاری خطا به‌عنوان رفع‌شده'),
    'issue.reopen': ('management','بازگشایی خطای سایت'),
    'account.login': ('staff_session','ورود مدیر به سایت'),
    'account.logout': ('staff_session','خروج مدیر از سایت'),
    'currency.refresh': ('finance','دریافت پیشنهاد قیمت ارزها توسط مدیر'),
}
BOT_ACTIONS = {
    'product.add':('catalog','افزودن محصول'), 'product.edit':('catalog','ویرایش محصول'),
    'product.publish':('catalog','تغییر انتشار یا وضعیت محصول'), 'product.delete':('catalog','حذف محصول'),
    'category.add':('catalog','افزودن دسته'), 'category.edit':('catalog','ویرایش دسته'),
    'category.disable':('catalog','غیرفعال‌کردن دسته'), 'currency.edit':('finance','تغییر تنظیمات ارز'),
    'balance.adjust':('finance','تغییر دستی موجودی'), 'payment.toggle':('finance','تغییر وضعیت روش پرداخت'),
    'gift.edit':('finance','مدیریت کد هدیه'), 'lottery.credit':('finance','ثبت جایزهٔ قرعه‌کشی'),
    'user.ban':('management','مسدودکردن حساب'), 'user.unban':('management','رفع مسدودی حساب'),
    'user.verify':('management','تغییر احراز هویت کاربر'), 'settings.edit':('management','تغییر تنظیمات ربات'),
    'broadcast':('management','پایان ارسال پیام همگانی'), 'support.reply':('support','ارسال پاسخ پشتیبانی ربات'),
}


def numeric_ref(value):
    s=str(value)
    return s if s.isascii() and s.isdecimal() and len(s)<=20 else ''


@receiver(post_save,sender=Audit,dispatch_uid='portal.ops.audit')
def audit_notice(sender,instance,created,raw,using,**kwargs):
    if not created or raw:return
    key=instance.action
    bot=instance.actor_id is None
    if key.startswith('bot.') and bot:
        info=BOT_ACTIONS.get(key[4:])
    else:info=AUDITED.get(key)
    if not info:return
    if bot:
        actor=instance.details.get('telegram_admin_id')
        if type(actor) is not int or actor not in recipients():return
    else:
        if not instance.actor.is_staff:return
        actor=instance.actor_id
    topic,summary=info
    if key=='order.status':
        label={'completed':'تکمیل سفارش','confirmed':'تأیید سفارش','cancelled':'لغو سفارش'}.get(instance.details.get('status'))
        summary=label or summary
    if key=='catalog.profit.batch':summary+=f" ({int(instance.details['count'])} محصول)"
    if key=='source.price.apply' and (instance.details.get('automatic') or instance.details.get('batch_item')):return
    if key in ('source.price.fetch','source.price.recheck') and instance.details.get('review_batch'):return
    OperationNotice.objects.using(using).create(topic=topic,summary=summary,origin='telegram' if bot else 'web',
        actor_key=actor,reference=numeric_ref(instance.object_ref))


class AdminNoticeMixin:
    """Use the actual ModelAdmin write hooks (also for auth.User/Group).

    Those writes often ALSO emit domain Audits; only the custom services above
    consume Audit, so editing e.g. a product and its tax gives one notification.
    """
    def _admin_notice(self,request,flag,obj=None,count=None):
        model=self.opts.model_name
        if model in ('audit','noticepreference','siteissue'):return
        topic=({'product':'catalog','category':'catalog','sourceproduct':'catalog','sourcesyncsettings':'catalog',
                'currency':'finance','giftcode':'finance','legacyuser':'management',
                'ticket':'support','order':'order_status'}).get(model,'management')
        verb={ADDITION:'افزودن',CHANGE:'ویرایش',DELETION:'حذف'}[flag]
        summary=f'{verb} {self.opts.verbose_name}'
        if count is not None:summary+=f' ({count} مورد)'
        OperationNotice.objects.create(topic=topic,summary=summary[:160],origin='web',
            actor_key=request.user.pk,reference=numeric_ref(obj.pk) if obj else '')

    def log_addition(self,request,obj,message):
        result=super().log_addition(request,obj,message)
        self._admin_notice(request,ADDITION,obj)
        return result

    def log_change(self,request,obj,message):
        result=super().log_change(request,obj,message)
        if message:self._admin_notice(request,CHANGE,obj)
        return result

    @transaction.atomic
    def delete_model(self,request,obj):
        self._admin_notice(request,DELETION,obj)
        return super().delete_model(request,obj)

    @transaction.atomic
    def delete_queryset(self,request,queryset):
        count=queryset.count()
        result=super().delete_queryset(request,queryset)
        if count:self._admin_notice(request,DELETION,count=count)
        return result
