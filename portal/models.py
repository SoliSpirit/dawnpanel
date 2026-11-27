import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator

PLATFORMS=[('rubika','روبیکا'),('eitaa','ایتا'),('bale','بله'),('ai','اشتراک هوش مصنوعی'),('telegram','تلگرام'),('other','سایر')]
WEB_PLATFORMS=('rubika','eitaa','bale','ai')
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
    @staticmethod
    def web_eligible():
        return models.Q(platform__in=WEB_PLATFORMS) | models.Q(
            platform='other',pk__in=SourceProduct.objects.values('product_id'))

    def web_publication_error(self):
        if self.platform=='telegram':
            return 'خدمات تلگرام در فروشگاه وب منتشر نمی‌شوند.'
        if self.platform not in WEB_PLATFORMS:
            linked=getattr(self,'_has_source',None)
            if self.platform=='other' and self.pk and linked is None:
                linked=SourceProduct.objects.filter(product_id=self.pk).exists()
            if self.platform!='other' or not linked:
                return 'این نوع محصول فقط با اتصال منبع معتبر در فروشگاه منتشر می‌شود.'
        return ''
    def clean(self):
        if self.max_order and self.max_order<self.min_order: raise ValidationError('حداکثر سفارش از حداقل کمتر است.')
        if self.show_on_website and (error:=self.web_publication_error()): raise ValidationError(error)
        if self.price_currency!='TOMAN' and self.price_amount is None: raise ValidationError('برای قیمت ارزی مبلغ لازم است.')
    @property
    def visual(self):
        if not hasattr(self,'_visual_cache'):
            self._visual_cache=ProductVisual.objects.filter(product_id=self.pk).first()
        return self._visual_cache
    @property
    def tax_percent(self):
        policy = getattr(self, 'tax_policy', None)
        return policy.percent if policy else 0
    def get_absolute_url(self):
        from django.urls import reverse
        from django.utils.text import slugify
        return reverse('product_named',kwargs={'pk':self.pk,'slug':slugify(self.name,allow_unicode=True)[:90].strip('-') or 'product'})
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
    national_code_encrypted=models.CharField('کد ملی رمز‌شده',max_length=255,blank=True,editable=False)
    birth_date=models.DateField('تاریخ تولد',null=True,blank=True)
    province=models.CharField('استان',max_length=80,blank=True)
    city=models.CharField('شهر',max_length=80,blank=True)
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


class OrderEvent(models.Model):
    """An order was actually placed and charged, not just previewed or topped up."""
    order=models.OneToOneField(Order,primary_key=True,on_delete=models.CASCADE,db_constraint=False)
    channel=models.CharField(max_length=8,choices=[('web','سایت'),('telegram','ربات')])
    prepared=models.BooleanField(default=False,db_index=True)


class NoticePreference(models.Model):
    recipient=models.PositiveBigIntegerField(primary_key=True)
    enabled=models.JSONField(default=list)
    revision=models.PositiveBigIntegerField(default=0)
    class Meta:
        verbose_name='تنظیم اعلان تلگرام';verbose_name_plural='تنظیمات اعلان تلگرام'


class OperationNotice(models.Model):
    topic=models.CharField(max_length=24)
    summary=models.CharField(max_length=160)
    origin=models.CharField(max_length=12)
    actor_key=models.PositiveBigIntegerField(null=True)
    reference=models.CharField(max_length=40,blank=True)
    prepared=models.BooleanField(default=False,db_index=True)
    created_at=models.DateTimeField(auto_now_add=True)


class SiteIssue(models.Model):
    fingerprint=models.CharField(max_length=64,unique=True,editable=False)
    kind=models.CharField('نوع خطا',max_length=96)
    status_code=models.PositiveSmallIntegerField('کد HTTP سایت',null=True,blank=True)
    route=models.CharField('مسیر برنامه',max_length=150)
    method=models.CharField('روش درخواست',max_length=12)
    trace=models.TextField('محل خطا در کد',blank=True)
    hint=models.CharField('راهنمای بررسی',max_length=240,blank=True)
    release=models.CharField('نسخهٔ برنامه',max_length=40,blank=True)
    occurrences=models.PositiveBigIntegerField('تعداد رخداد',default=1)
    first_seen=models.DateTimeField('اولین رخداد')
    last_seen=models.DateTimeField('آخرین رخداد',db_index=True)
    resolved=models.BooleanField('رفع‌شده',default=False,db_index=True)
    resolved_at=models.DateTimeField('آخرین زمان رفع',null=True,blank=True)
    class Meta:
        ordering=['-last_seen','-pk'];verbose_name='خطای سایت';verbose_name_plural='خطاهای سایت'
    def __str__(self):return f'{self.kind} · {self.route}'


class OrderDelivery(models.Model):
    event=models.ForeignKey(OrderEvent,null=True,on_delete=models.CASCADE)
    operation=models.ForeignKey(OperationNotice,null=True,on_delete=models.CASCADE)
    recipient=models.PositiveBigIntegerField()
    state=models.CharField(max_length=8,default='pending')
    due_at=models.DateTimeField()
    lease=models.UUIDField(null=True)
    attempts=models.PositiveIntegerField(default=0)
    last_error=models.CharField(max_length=40,blank=True)
    sent_at=models.DateTimeField(null=True)
    message_id=models.PositiveBigIntegerField(null=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['event','recipient'],name='unique_order_recipient'),
                     models.UniqueConstraint(fields=['operation','recipient'],name='unique_operation_recipient'),
                     models.CheckConstraint(condition=(models.Q(event__isnull=False,operation__isnull=True)|
                                                       models.Q(event__isnull=True,operation__isnull=False)),name='one_notice_source')]
        indexes=[models.Index(fields=['state','due_at'],name='order_delivery_due')]

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

class Campaign(models.Model):
    name=models.CharField('نام کمپین',max_length=120)
    code=models.SlugField('کد لینک',unique=True,max_length=60)
    clicks=models.PositiveBigIntegerField('باز شدن لینک',default=0,editable=False)
    registrations=models.PositiveBigIntegerField('ثبت‌نام منتسب',default=0,editable=False)
    active=models.BooleanField('فعال',default=True)
    class Meta:
        verbose_name='لینک تبلیغاتی'
        verbose_name_plural='لینک‌های تبلیغاتی'
    def __str__(self):return self.name
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


class CurrencyPricing(models.Model):
    """Merchant policy and last verified book. The legacy rate stays the manual base."""
    SOURCES=[('manual','نرخ پایهٔ دستی'),('nobitex','نوبیتکس · بازار رمزارز'),('nerkhara','نرخ‌آرا · بازار آزاد ارز'),
             ('denapanel','دناپنل · استارز تلگرام')]
    SPREADS=[('fixed','مبلغ ثابت به تومان'),('percent','درصد از نرخ مرجع')]
    currency=models.OneToOneField(Currency,primary_key=True,on_delete=models.CASCADE,
                                  db_constraint=False,related_name='fx')
    source=models.CharField(max_length=12,choices=SOURCES,default='manual')
    spread_mode=models.CharField(max_length=8,choices=SPREADS,default='fixed')
    sell_extra=models.DecimalField(max_digits=16,decimal_places=4,default=0,validators=[MinValueValidator(0)])
    buy_less=models.DecimalField(max_digits=16,decimal_places=4,default=0,validators=[MinValueValidator(0)])
    # Both sides are in TOMAN for exactly one unit. An observation belongs to
    # one specific source/symbol even when an operator changes the currency code.
    quote_key=models.CharField(max_length=40,blank=True,default='',editable=False)
    market_bid=models.DecimalField(max_digits=25,decimal_places=8,null=True,editable=False)
    market_ask=models.DecimalField(max_digits=25,decimal_places=8,null=True,editable=False)
    observed_at=models.DateTimeField(null=True,editable=False)
    checked_at=models.DateTimeField(null=True,editable=False)
    last_error=models.CharField(max_length=200,blank=True,default='',editable=False)
    # Polling updates only the candidate. The book above is the published one.
    candidate_key=models.CharField(max_length=40,blank=True,default='',editable=False)
    candidate_bid=models.DecimalField(max_digits=25,decimal_places=8,null=True,editable=False)
    candidate_ask=models.DecimalField(max_digits=25,decimal_places=8,null=True,editable=False)
    candidate_at=models.DateTimeField(null=True,editable=False)
    published_at=models.DateTimeField(null=True,editable=False)
    revision=models.PositiveBigIntegerField(default=0,editable=False)


class CryptoTopup(models.Model):
    ticket=models.OneToOneField(Ticket,primary_key=True,on_delete=models.PROTECT,related_name='crypto_topup')
    account=models.ForeignKey(Account,on_delete=models.PROTECT)
    request_key=models.UUIDField(unique=True)
    code=models.CharField(max_length=20)
    units=models.DecimalField(max_digits=28,decimal_places=12)
    requested_rate=models.PositiveBigIntegerField()
    # One verified transfer can credit exactly one ticket. Users never supply
    # a settlement reference through an endpoint that moves money.
    paid_ref=models.CharField(max_length=160,unique=True,null=True,editable=False)
    paid_units=models.DecimalField(max_digits=28,decimal_places=12,null=True,editable=False)
    paid_rate=models.PositiveBigIntegerField(null=True,editable=False)
    credited=models.PositiveBigIntegerField(null=True,editable=False)
    settled_at=models.DateTimeField(null=True,editable=False)

    class Meta:
        permissions=[('settle_crypto_topup','تأیید دریافت رمزارز و شارژ کیف پول')]

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
    plan_name=models.CharField('نام پلن',max_length=80,blank=True)
    duration_months=models.PositiveSmallIntegerField('مدت اعتبار به ماه',null=True,blank=True,validators=[MinValueValidator(1)])
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name='تصویر محصول'
        verbose_name_plural='تصاویر محصولات'


class ProductTax(models.Model):
    # Managed sidecar: the legacy bot's products table/column order is unchanged.
    product=models.OneToOneField(Product,primary_key=True,on_delete=models.CASCADE,
                                 db_constraint=False,related_name='tax_policy')
    percent=models.DecimalField('درصد مالیات',max_digits=5,decimal_places=2,default=0,
                                validators=[MinValueValidator(0),MaxValueValidator(100)])
    class Meta:
        constraints=[models.CheckConstraint(condition=models.Q(percent__gte=0,percent__lte=100),
                                            name='product_tax_in_range')]


class OrderAmounts(models.Model):
    """Immutable at purchase; pre-existing orders intentionally have no row."""
    order=models.OneToOneField(Order,primary_key=True,on_delete=models.DO_NOTHING,
                               db_constraint=False,related_name='amounts')
    subtotal=models.PositiveBigIntegerField('مبلغ پیش از مالیات')
    tax_percent=models.DecimalField('درصد مالیات هنگام خرید',max_digits=5,decimal_places=2)
    tax_amount=models.PositiveBigIntegerField('مبلغ مالیات')


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


class SourceProduct(models.Model):
    """Stable association between a supplier item and an imported product."""
    source=models.CharField(max_length=30)
    external_id=models.CharField(max_length=80)
    product_id=models.PositiveBigIntegerField(unique=True)
    source_url=models.URLField(max_length=1000,blank=True)
    item_url=models.URLField('صفحهٔ قیمت در منبع',max_length=2000,blank=True,default='')
    family_name=models.CharField('نام خانواده محصول',max_length=500,blank=True,default='')
    family_summary=models.TextField('معرفی خانواده محصول',blank=True,default='')
    last_price=models.PositiveBigIntegerField()
    sync_enabled=models.BooleanField('دریافت قیمت این محصول',default=True)
    proposed_price=models.PositiveBigIntegerField('قیمت پیشنهادی تومان',null=True,blank=True)
    price_baseline=models.JSONField(default=dict,editable=False)
    observed_at=models.DateTimeField('آخرین دریافت معتبر',null=True,blank=True)
    available=models.BooleanField('موجود در منبع',default=False)
    review_status=models.CharField('وضعیت قیمت',max_length=20,default='new',choices=[
        ('new','دریافت نشده'),('pending','منتظر تأیید'),('applied','اعمال شده'),
        ('unchanged','بدون تغییر'),('conflict','نیازمند بررسی'),('rejected','رد شده'),
        ('unavailable','ناموجود در منبع'),('missing','شناسه در فهرست منبع پیدا نشد')])
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['source','external_id'],name='unique_source_product')]
        verbose_name='قیمت منبع محصول'
        verbose_name_plural='بررسی قیمت محصولات'

    def __str__(self):
        return f'{self.source} / {self.external_id}'

    @property
    def evidence_url(self):
        from .source_links import product_page
        return (product_page(self.source,self.item_url,self.external_id)
                or product_page(self.source,self.source_url,self.external_id))


class SourceSyncSettings(models.Model):
    source=models.CharField('منبع',max_length=30,unique=True,choices=[
        ('denapanel','دناپنل'),('premstore','پریم‌استور')])
    enabled=models.BooleanField('دریافت زمان‌بندی‌شده',default=False)
    require_approval=models.BooleanField('نیاز به تأیید پیش از اعمال',default=True)
    interval_minutes=models.PositiveIntegerField('فاصله دریافت به دقیقه',default=60,
        validators=[MinValueValidator(15)])
    max_change_percent=models.PositiveIntegerField('حداکثر تغییر برای اعمال خودکار (%)',default=25,
        validators=[MinValueValidator(1)])
    last_attempt=models.DateTimeField('آخرین تلاش',null=True,blank=True,editable=False)
    last_success=models.DateTimeField('آخرین دریافت موفق',null=True,blank=True,editable=False)
    running_until=models.DateTimeField(null=True,blank=True,editable=False)
    last_error=models.CharField('خطای آخر',max_length=200,blank=True,editable=False)

    class Meta:
        verbose_name='تنظیم دریافت قیمت'
        verbose_name_plural='تنظیمات دریافت قیمت'

    def __str__(self):
        return self.get_source_display()
