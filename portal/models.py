import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator

PLATFORMS=[('rubika','روبیکا'),('eitaa','ایتا'),('bale','بله'),('ai','اشتراک هوش مصنوعی'),('telegram','تلگرام'),('other','سایر')]
class LegacyUser(models.Model):
    user_id=models.BigIntegerField(primary_key=True)
    full_name=models.CharField(max_length=255,blank=True,null=True)
    username=models.CharField(max_length=255,blank=True,null=True)
    phone_number=models.CharField(max_length=20,blank=True,null=True)
    is_verified=models.BooleanField(default=False)
    is_banned=models.BooleanField(default=False)
    ban_reason=models.TextField(blank=True,null=True)
    balance=models.BigIntegerField(default=0)
    total_payments=models.BigIntegerField(default=0)
    total_purchases=models.BigIntegerField(default=0)
    income=models.BigIntegerField(default=0)
    subsets_count=models.IntegerField(default=0)
    subsets_commission=models.BigIntegerField(default=0)
    consumed_gift=models.BigIntegerField(default=0)
    referral_code=models.CharField(max_length=50,unique=True,null=True)
    class Meta: managed=False;db_table='users';verbose_name='حساب مشترک ربات و سایت';verbose_name_plural='حساب‌های مشترک'
    def __str__(self): return self.full_name or str(self.pk)
class Category(models.Model):
    name=models.CharField('نام',max_length=500)
    emoji=models.CharField('نشانه',max_length=50,blank=True,null=True)
    sort_order=models.IntegerField('ترتیب',default=0)
    is_active=models.BooleanField('فعال',default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: managed=False;db_table='categories';verbose_name='دسته‌بندی';verbose_name_plural='دسته‌بندی‌ها';ordering=['sort_order','id']
    def __str__(self): return self.name
class Product(models.Model):
    category=models.ForeignKey(Category,on_delete=models.SET_NULL,null=True,verbose_name='دسته‌بندی')
    name=models.CharField('نام محصول',max_length=500)
    description=models.TextField('توضیحات',blank=True,null=True)
    price=models.BigIntegerField('قیمت پایه تومان',validators=[MinValueValidator(1)])
    price_per=models.PositiveIntegerField('قیمت به‌ازای تعداد',default=1,validators=[MinValueValidator(1)])
    min_order=models.PositiveIntegerField('حداقل سفارش',default=1,validators=[MinValueValidator(1)])
    max_order=models.PositiveIntegerField('حداکثر سفارش',null=True,blank=True)
    need_link=models.BooleanField('نیازمند لینک یا شناسه',default=True)
    is_active=models.BooleanField('فعال',default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    target_type=models.CharField(max_length=30,default='channel_group')
    target_prompt=models.TextField('راهنمای اطلاعات سفارش',blank=True,null=True)
    price_currency=models.CharField('واحد قیمت',max_length=20,default='TOMAN')
    price_amount=models.DecimalField('مبلغ ارزی',max_digits=36,decimal_places=18,null=True,blank=True)
    product_profit_percent=models.DecimalField('درصد سود',max_digits=10,decimal_places=4,default=0,validators=[MinValueValidator(0)])
    show_on_website=models.BooleanField('نمایش در سایت',default=False)
    show_on_telegram=models.BooleanField('نمایش در تلگرام',default=True)
    platform=models.CharField('نوع محصول',max_length=20,choices=PLATFORMS,default='telegram')
    seo_description=models.CharField('توضیح سئو',max_length=160,blank=True,default='')
    class Meta: managed=False;db_table='products';verbose_name='محصول';verbose_name_plural='محصولات'
    def __str__(self): return self.name
    def clean(self):
        if self.max_order and self.max_order<self.min_order: raise ValidationError('حداکثر سفارش از حداقل کمتر است.')
        if self.show_on_website and self.platform not in ['rubika','eitaa','bale','ai']: raise ValidationError('نوع محصول برای نمایش در فروشگاه پشتیبانی نمی‌شود.')
        if self.price_currency!='TOMAN' and self.price_amount is None: raise ValidationError('برای قیمت ارزی مبلغ لازم است.')
    @property
    def visual(self):
        if not hasattr(self,'_visual_cache'):
            self._visual_cache=ProductVisual.objects.filter(product_id=self.pk).first()
        return self._visual_cache
    def get_absolute_url(self): return f'/services/{self.pk}/'
class Order(models.Model):
    tracking_code=models.CharField(max_length=20)
    user=models.ForeignKey(LegacyUser,on_delete=models.DO_NOTHING,db_column='user_id')
    product_id=models.IntegerField(null=True)
    product_name=models.CharField(max_length=500)
    target_link=models.TextField(blank=True,null=True)
    quantity=models.IntegerField()
    unit_price=models.BigIntegerField()
    total_price=models.BigIntegerField()
    status=models.CharField(max_length=50,default='pending')
    completed_at=models.DateTimeField(null=True)
    created_at=models.DateTimeField(auto_now_add=True)
    cancel_reason=models.TextField(blank=True,null=True)
    completion_message=models.TextField(blank=True,null=True)
    class Meta: managed=False;db_table='orders';verbose_name='سفارش';verbose_name_plural='سفارش‌ها';ordering=['-id']
    def __str__(self): return self.tracking_code
    @property
    def status_label(self): return {'pending':'در انتظار بررسی','confirmed':'در حال انجام','approved':'در حال انجام','processing':'در حال انجام','completed':'تکمیل شده','rejected':'رد شده','cancelled':'لغو شده'}.get(self.status,self.status)
class Ledger(models.Model):
    user=models.ForeignKey(LegacyUser,on_delete=models.DO_NOTHING,db_column='user_id')
    amount=models.BigIntegerField()
    type=models.CharField(max_length=50)
    description=models.TextField(blank=True,null=True)
    payment_tracking_code=models.CharField(max_length=10,blank=True,null=True)
    status=models.CharField(max_length=50,default='completed')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: managed=False;db_table='transactions';verbose_name='تراکنش';verbose_name_plural='تراکنش‌ها';ordering=['-id']
class Account(models.Model):
    user=models.OneToOneField(User,on_delete=models.CASCADE,related_name='account')
    phone=models.CharField('موبایل',max_length=11,unique=True)
    legacy_id=models.BigIntegerField('شناسه حساب مشترک',unique=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: verbose_name='حساب وب';verbose_name_plural='حساب‌های وب'
    def __str__(self): return self.phone
class OTP(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    phone=models.CharField(max_length=11)
    code_hash=models.CharField(max_length=128)
    session_hash=models.CharField(max_length=64)
    expires_at=models.DateTimeField()
    attempts=models.PositiveSmallIntegerField(default=0)
    consumed=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
class RateBucket(models.Model):
    key=models.CharField(max_length=100,primary_key=True)
    count=models.PositiveIntegerField(default=0)
    expires_at=models.DateTimeField()
class Checkout(models.Model):
    key=models.UUIDField(primary_key=True)
    account=models.ForeignKey(Account,on_delete=models.PROTECT)
    order_id=models.BigIntegerField(null=True)
    created_at=models.DateTimeField(auto_now_add=True)
class Ticket(models.Model):
    STATUS=[('open','باز'),('answered','پاسخ داده شده'),('closed','بسته')]
    user=models.ForeignKey(User,on_delete=models.PROTECT,verbose_name='کاربر')
    subject=models.CharField('موضوع',max_length=180)
    status=models.CharField('وضعیت',max_length=20,choices=STATUS,default='open')
    priority=models.CharField('اولویت',max_length=15,choices=[('normal','عادی'),('urgent','فوری')],default='normal')
    order=models.ForeignKey(Order,on_delete=models.DO_NOTHING,null=True,blank=True,db_constraint=False,verbose_name='سفارش مرتبط')
    assigned_to=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='assigned_tickets',verbose_name='مسئول پشتیبانی',limit_choices_to={'is_staff':True})
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=['-updated_at'];verbose_name='تیکت';verbose_name_plural='تیکت‌ها'
    def __str__(self): return f'#{self.pk} {self.subject}'
class TicketMessage(models.Model):
    ticket=models.ForeignKey(Ticket,on_delete=models.CASCADE,related_name='messages')
    author=models.ForeignKey(User,on_delete=models.PROTECT)
    body=models.TextField('متن')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['id'];verbose_name='پیام تیکت';verbose_name_plural='پیام‌ها'
class Post(models.Model):
    title=models.CharField('عنوان',max_length=180)
    slug=models.SlugField('نشانی',unique=True,allow_unicode=True,max_length=200)
    summary=models.CharField('خلاصه و توضیح سئو',max_length=160)
    body=models.TextField('متن مقاله')
    published=models.BooleanField('منتشر شده',default=False)
    author=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=['-created_at'];verbose_name='مقاله';verbose_name_plural='وبلاگ'
    def __str__(self): return self.title
    def get_absolute_url(self): return f'/blog/{self.slug}/'
class Audit(models.Model):
    actor=models.ForeignKey(User,on_delete=models.SET_NULL,null=True)
    action=models.CharField(max_length=80)
    object_ref=models.CharField(max_length=100,blank=True)
    details=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-id'];verbose_name='رویداد مدیریتی';verbose_name_plural='گزارش فعالیت'
class PaymentAttempt(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    account=models.ForeignKey(Account,on_delete=models.PROTECT)
    amount=models.PositiveBigIntegerField()
    authority=models.CharField(max_length=50,unique=True,null=True)
    status=models.CharField(max_length=20,default='new')
    created_at=models.DateTimeField(auto_now_add=True)

class Currency(models.Model):
    code=models.CharField('کد',max_length=20,unique=True)
    name=models.CharField('نام',max_length=100)
    symbol=models.CharField('نماد',max_length=20,blank=True,null=True)
    rate=models.PositiveBigIntegerField('نرخ به تومان',validators=[MinValueValidator(1)])
    type=models.CharField(max_length=50,default='crypto')
    icon=models.CharField(max_length=10,blank=True,null=True)
    is_active=models.BooleanField('فعال',default=True)
    updated_at=models.DateTimeField(auto_now=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: managed=False;db_table='currencies';verbose_name='نرخ ارز';verbose_name_plural='نرخ‌های ارز'
    def __str__(self): return self.name
class GiftCode(models.Model):
    code=models.CharField('کد',max_length=50,unique=True)
    amount=models.PositiveBigIntegerField('مبلغ هدیه',validators=[MinValueValidator(1)])
    is_active=models.BooleanField('فعال',default=True)
    max_uses=models.PositiveIntegerField('حداکثر استفاده؛ صفر نامحدود',default=0)
    used_count=models.PositiveIntegerField(default=0)
    created_by=models.BigIntegerField(null=True)
    target_type=models.CharField('گروه مجاز',max_length=50,default='all',choices=[('all','همه'),('verified','تایید شده'),('buyers','خریداران'),('no_buyers','بدون خرید'),('paid','دارای پرداخت'),('no_payments','بدون پرداخت'),('min_referrals','حداقل زیرمجموعه'),('min_purchases','حداقل خرید')])
    target_value=models.IntegerField('حد آستانه گروه',default=0)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: managed=False;db_table='gift_codes';verbose_name='کد هدیه';verbose_name_plural='کدهای هدیه'
    def clean(self):
        self.code=self.code.strip().upper()
        if not self.code or not self.code.isascii(): raise ValidationError('کد هدیه باید انگلیسی باشد.')
    def __str__(self): return self.code
class MemberRank(models.Model):
    name=models.CharField('نام رتبه',max_length=50,unique=True)
    min_spending=models.PositiveBigIntegerField('حداقل خرید تکمیل‌شده به تومان',default=0)
    class Meta: ordering=['min_spending'];verbose_name='رتبه کاربر';verbose_name_plural='رتبه‌های کاربران'
    def __str__(self): return self.name

class ReferralAlias(models.Model):
    code=models.CharField(max_length=50,unique=True)
    legacy_id=models.BigIntegerField()

class ProductVisual(models.Model):
    product_id=models.PositiveBigIntegerField('شناسه محصول',unique=True)
    image=models.FileField('عکس محصول',upload_to='products/%Y/%m/',max_length=255)
    night_image=models.FileField('عکس شب محصول',upload_to='products/%Y/%m/',max_length=255,blank=True)
    alt_text=models.CharField('توضیح تصویر',max_length=160,blank=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name='تصویر محصول'
        verbose_name_plural='تصاویر محصولات'


class ChatConversation(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    visitor_key=models.CharField(max_length=64,unique=True)
    user=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    status=models.CharField(max_length=12,choices=[('waiting','منتظر پاسخ'),('open','در گفتگو'),('closed','بسته')],default='waiting')
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True,db_index=True)
    class Meta:
        ordering=['-updated_at']
        verbose_name='گفتگوی آنلاین'
        verbose_name_plural='گفتگوهای آنلاین'

class ChatMessage(models.Model):
    conversation=models.ForeignKey(ChatConversation,on_delete=models.CASCADE,related_name='messages')
    author=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    from_staff=models.BooleanField(default=False)
    body=models.CharField(max_length=2000)
    nonce=models.UUIDField(default=uuid.uuid4)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['id']
        constraints=[models.UniqueConstraint(fields=['conversation','nonce'],name='unique_chat_message_nonce')]

class SupportPresence(models.Model):
    user=models.OneToOneField(User,on_delete=models.CASCADE)
    seen_at=models.DateTimeField(auto_now=True,db_index=True)
