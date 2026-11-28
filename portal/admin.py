from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import *
from .product_media import ProductImageForm,save_product_picture
from django.utils.html import format_html
from django.urls import reverse
from .services import BusinessError
from .admin_states import StateListMixin
from .admin_pricing import PriceToolsAdminMixin,SourceApprovalMixin
from .admin_fx import CurrencyRatesAdminMixin
from . import admin_operations

@admin.register(Campaign)
class CampaignAdmin(StateListMixin,admin.ModelAdmin):
    state_fields=('active',)
    list_display=['name','share_link','clicks','registrations','active']
    readonly_fields=['share_link','clicks','registrations']
    search_fields=['name','code']
    @admin.display(description='لینک قابل اشتراک')
    def share_link(self,obj):
        if not obj.code:return 'پس از ذخیره ساخته می‌شود.'
        url='https://dawnpanel.ir'+reverse('campaign',args=[obj.code])
        return format_html('<a href="{}" dir="ltr">{}</a>',url,url)
class AuditAdmin(admin.ModelAdmin):
    search_fields=['actor__username','action','object_ref']
    list_select_related=['actor']
    list_display=['created_at','actor','action','object_ref'];list_filter=['action','created_at'];readonly_fields=['actor','action','object_ref','details','created_at']
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False
admin.site.register(Audit,AuditAdmin)
class AuditedAdmin(admin.ModelAdmin):
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        Audit.objects.create(actor=request.user,action=self.model._meta.model_name+('.update' if change else '.create'),object_ref=str(obj.pk),details={'fields':list(form.changed_data)})

class WebsiteFlagFilter(admin.SimpleListFilter):
    title='نمایش در سایت'
    parameter_name='show_on_website__exact'

    def lookups(self,request,model_admin):
        return [('1','روشن'),('0','خاموش'),('blocked','غیرقابل انتشار در سایت')]

    def queryset(self,request,queryset):
        if self.value() in ('1','0'):
            return queryset.filter(Product.web_eligible(),show_on_website=self.value()=='1')
        if self.value()=='blocked':
            return queryset.exclude(Product.web_eligible())
        return queryset

@admin.register(Product)
class ProductAdmin(PriceToolsAdminMixin,StateListMixin,AuditedAdmin):
    actions=['set_profit','recheck_selected']
    state_fields=('is_active','show_on_website','show_on_telegram')
    state_labels={'is_active':'وضعیت فروش','show_on_telegram':'نمایش در ربات'}
    state_ordering={'show_on_website':'_web_enabled'}
    state_words={'show_on_website':('روشن','خاموش'), 'show_on_telegram':('روشن','خاموش')}
    list_hint='فروش محصول و نمایش آن در سایت و ربات را جداگانه تنظیم کن. هر تغییر همان لحظه ذخیره می‌شود.'
    form=ProductImageForm
    change_form_template='admin/portal/product/change_form.html'
    def get_changeform_initial_data(self,request):
        return {'platform':'rubika','show_on_website':True,**super().get_changeform_initial_data(request)}
    def render_change_form(self,request,context,add=False,change=False,form_url='',obj=None):
        from .catalog_aliases import PREMSTORE_EQUIVALENTS
        source_admin=self.admin_site.get_model_admin(SourceProduct)
        if obj and source_admin.has_view_or_change_permission(request):
            link=source_admin.get_queryset(request).filter(product_id=obj.pk).first()
            if link and source_admin.has_view_or_change_permission(request,link):
                context['pricing_source']=link
        if obj and obj.pk in (*PREMSTORE_EQUIVALENTS,31):
            from .store_catalog import families
            context['web_equivalent']=next((p for family in families() for p in family.plans
                if any(a.pk==obj.pk for a in p.web_aliases)),None)
        return super().render_change_form(request,context,add,change,form_url,obj)
    def get_fieldsets(self,request,obj=None):
        fieldsets=super().get_fieldsets(request,obj)
        if obj:return fieldsets
        return [(name,{**options,'fields':[field for field in options['fields'] if field not in ['current_picture','current_night_picture','remove_picture','remove_night_picture']]}) for name,options in fieldsets]
    readonly_fields=['current_picture','current_night_picture']
    @admin.display(description='عکس فعلی')
    def current_picture(self,obj):
        if obj and obj.visual and obj.visual.image:
            return format_html('<img src="{}" alt="{}" width="240">',obj.visual.image.url,obj.visual.alt_text or obj.name)
        if obj:
            from .templatetags.storefront import product_image
            return format_html('<img src="{}" alt="{}" width="240"><p>تصویر آمادهٔ این خانواده؛ با بارگذاری عکس دلخواه جایگزین می‌شود.</p>',product_image(obj,'light'),obj.name)
        return 'هنوز عکسی ثبت نشده است.'
    @admin.display(description='عکس شب فعلی')
    def current_night_picture(self,obj):
        if obj and obj.visual and obj.visual.night_image:
            return format_html('<img src="{}" alt="{}" width="240">',obj.visual.night_image.url,obj.visual.alt_text or obj.name)
        if obj:
            from .templatetags.storefront import product_image
            return format_html('<img src="{}" alt="{}" width="240"><p>تصویر آمادهٔ حالت شب</p>',product_image(obj,'dark'),obj.name)
        return 'تصویر شب دسته‌بندی نمایش داده می‌شود.'
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        if change and {'price','product_profit_percent','price_per','price_amount','price_currency'}.intersection(form.changed_data):
            ProductSaleOverride.objects.filter(product_id=obj.pk).delete()
        if 'picture' in form.cleaned_data: save_product_picture(obj,form)
        field='tax_percent'
        if field in form.cleaned_data and form.add_prefix(field) in form.data and field in form.changed_data:
            before=ProductTax.objects.filter(product_id=obj.pk).values_list('percent',flat=True).first() or 0
            after=form.cleaned_data[field] or 0
            if after!=before:
                if after:
                    ProductTax.objects.update_or_create(product_id=obj.pk,defaults={'percent':after})
                else:
                    ProductTax.objects.filter(product_id=obj.pk).delete()
                Audit.objects.create(actor=request.user,action='product.tax',object_ref=str(obj.pk),
                                     details={'old':str(before),'new':str(after)})
    @admin.display(description='محصول',ordering='name')
    def product_label(self,obj):
        return format_html('<strong class="catalog-row-name">{}</strong><small class="catalog-row-category">{}</small>',obj.name,obj.category.name if obj.category else 'بدون دسته‌بندی')
    @admin.display(description='قیمت پایه (تومان)',ordering='price')
    def base_price(self,obj):
        return format_html('<strong>{}</strong><small class="catalog-row-category">به‌ازای {} عدد</small>',format(obj.price,','),format(obj.price_per,','))
    @admin.display(description='مالیات',ordering='tax_policy__percent')
    def tax_label(self,obj):
        return f'{obj.tax_percent:g}٪' if obj.tax_percent else 'بدون مالیات'
    def get_queryset(self,request):
        from django.db.models import Exists,OuterRef,Q
        return super().get_queryset(request).select_related('category','tax_policy','sale_override').annotate(
            _has_source=Exists(SourceProduct.objects.filter(product_id=OuterRef('pk')))
        ).alias(_web_enabled=Q(show_on_website=True) & Product.web_eligible())
    def state_block(self,obj,field):
        if field=='show_on_website' and (reason:=obj.web_publication_error()):
            return ('فقط ربات' if obj.platform=='telegram' else 'نیازمند منبع',reason)
        return None
    def validate_activation(self,obj,field):
        if field!='show_on_website' and obj.show_on_website and obj.web_publication_error():
            # Some legacy bot SKUs have an ineffective web flag. Validate the sale
            # on its eligible channel; only the explicitly requested field is saved.
            from copy import copy
            obj=copy(obj)
            obj.show_on_website=False
        super().validate_activation(obj,field)
    list_display=['product_label','platform','base_price','profit_label','tax_label','is_active','show_on_website','show_on_telegram']
    list_filter=['platform','is_active',WebsiteFlagFilter,'show_on_telegram','category'];search_fields=['name'];list_per_page=30
    fieldsets=[('معرفی محصول',{'fields':['name','category','platform','plan_name','duration_months','description']}),('قیمت و تعداد',{'fields':['price','product_profit_percent','tax_percent',('price_per','min_order'),'max_order'],'description':'همه قیمت‌های پایه به تومان هستند. برای اشتراک تکی، تعداد مبنا و حداقل سفارش را روی ۱ قرار دهید.'}),('انتشار در سایت و تلگرام',{'fields':['is_active','show_on_website','show_on_telegram'],'description':'محل نمایش محصول را مستقل انتخاب کنید. محصولات غیرفعال قابل خرید نیستند.'}),('تصاویر روز و شب',{'fields':[('picture','night_picture'),'picture_alt','current_picture','current_night_picture','remove_night_picture','remove_picture']}),('اطلاعات تحویل و سئو',{'fields':['need_link','target_prompt','seo_description']}),('تنظیمات پیشرفته قیمت و ربات',{'fields':['price_currency','price_amount','target_type'],'classes':['collapse'],'description':'برای فروش معمولی با تومان نیازی به تغییر این بخش ندارید.'})]
    def has_delete_permission(self,request,obj=None): return False
@admin.register(Category)
class CategoryAdmin(StateListMixin,AuditedAdmin):
    state_fields=('is_active',)
    state_labels={'is_active':'وضعیت دسته'}
    list_hint='غیرفعال کردن دسته، محصولاتش را از فهرست سایت و ربات پنهان می‌کند. برای تغییر، روی وضعیت همان دسته بزن.'
    list_display=['name','product_count','sort_order','is_active'];fields=['name','emoji','sort_order','is_active']
    search_fields=['name'];list_filter=['is_active'];list_per_page=30
    def get_queryset(self,request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(_products=Count('product'))
    @admin.display(description='تعداد محصولات',ordering='_products')
    def product_count(self,obj):return obj._products
    def has_delete_permission(self,request,obj=None): return False
@admin.register(Post)
class PostAdmin(StateListMixin,AuditedAdmin):
    state_fields=('published',)
    state_words={'published':('منتشرشده','پیش‌نویس')}
    change_form_template='admin/portal/post/change_form.html'
    list_display=['title','published','author','updated_at'];list_filter=['published'];search_fields=['title'];prepopulated_fields={'slug':('title',)}
    readonly_fields=['author','created_at','updated_at']
    def save_model(self,request,obj,form,change):
        if not obj.pk: obj.author=request.user
        super().save_model(request,obj,form,change)
@admin.register(LegacyUser)
class WalletAdmin(admin.ModelAdmin):
    list_display=['user_id','full_name','phone_number','balance','is_verified','is_banned'];search_fields=['full_name','phone_number','=user_id'];list_filter=['is_banned','is_verified']
    readonly_fields=['user_id','full_name','username','phone_number','is_verified','balance','total_payments','total_purchases','income','subsets_count','subsets_commission','consumed_gift','referral_code']
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change);Audit.objects.create(actor=request.user,action='wallet.restriction',object_ref=str(obj.pk),details={'banned':obj.is_banned})
class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self,request,obj=None): return [f.name for f in self.model._meta.fields]
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False
    def has_change_permission(self,request,obj=None): return False
@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display=['tracking_code','product_name','quantity','total_price','status','created_at'];search_fields=['tracking_code','product_name'];list_filter=['status']
    def get_readonly_fields(self,request,obj=None): return [*super().get_readonly_fields(request,obj),'tax_breakdown']
    @admin.display(description='جزئیات مالیات هنگام خرید')
    def tax_breakdown(self,obj):
        amounts=getattr(obj,'amounts',None)
        if not amounts: return 'برای این سفارش قدیمی تفکیک مالیات ثبت نشده است.'
        return f'پیش از مالیات: {amounts.subtotal:,} تومان · مالیات ({amounts.tax_percent:g}٪): {amounts.tax_amount:,} تومان'
@admin.register(Ledger)
class LedgerAdmin(ReadOnlyAdmin):
    list_display=['user_id','amount','type','status','created_at'];list_filter=['type','status']
@admin.register(Account)
class AccountAdmin(ReadOnlyAdmin):
    list_display=['phone','profile_name','city','created_at']
    search_fields=['phone','user__first_name','user__last_name']
    fields=['phone','profile_name','legacy_id','birth_date','province','city','national_code_status','created_at']
    def get_readonly_fields(self,request,obj=None): return self.fields
    @admin.display(description='نام و نام خانوادگی')
    def profile_name(self,obj):return obj.user.get_full_name() or 'تکمیل نشده'
    @admin.display(description='وضعیت کد ملی')
    def national_code_status(self,obj):return 'ذخیره شده (خصوصی)' if obj.national_code_encrypted else 'ثبت نشده'
@admin.register(Ticket)
class TicketAdmin(AuditedAdmin):
    list_display=['id','subject','user','status','priority','assigned_to','updated_at'];list_filter=['status','priority'];search_fields=['subject'];readonly_fields=['user','subject','priority','order','created_at','updated_at']
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False

@admin.register(Currency)
class CurrencyAdmin(CurrencyRatesAdminMixin,StateListMixin,AuditedAdmin):
    state_fields=('is_active',)
    def validate_activation(self,obj,field):
        super().validate_activation(obj,field)
        from .exchange_rates import currency_rates,RateError
        from django.core.exceptions import ValidationError
        try:currency_rates(obj)
        except RateError as error:raise ValidationError(str(error)) from None
    def has_delete_permission(self,request,obj=None): return False
@admin.register(GiftCode)
class GiftAdmin(StateListMixin,AuditedAdmin):
    state_fields=('is_active',)
    list_display=['code','amount','is_active','used_count','max_uses','target_type'];readonly_fields=['used_count','created_by','created_at']
    def has_delete_permission(self,request,obj=None): return False
    def save_model(self,request,obj,form,change):
        if not obj.pk: obj.created_by=request.user.pk
        super().save_model(request,obj,form,change)
@admin.register(MemberRank)
class RankAdmin(AuditedAdmin): list_display=['name','min_spending']


@admin.register(SourceSyncSettings)
class SourceSyncSettingsAdmin(StateListMixin,AuditedAdmin):
    state_fields=('enabled',)
    list_hint='پایش، گزارش مقایسه می‌سازد. قیمت فروش فقط پس از تأیید مدیر تغییر می‌کند.'
    list_display=['source','enabled','interval_minutes','last_success','last_error']
    fields=['source','enabled','interval_minutes',
            'last_attempt','last_success','last_error']
    readonly_fields=['last_attempt','last_success','last_error']
    actions=['fetch_prices']

    def get_readonly_fields(self,request,obj=None):
        return self.readonly_fields + (['source'] if obj else [])

    def has_delete_permission(self,request,obj=None):
        return False

    def has_add_permission(self,request):
        return super().has_add_permission(request) and request.user.has_perm('portal.change_product')

    def has_change_permission(self,request,obj=None):
        return super().has_change_permission(request,obj) and request.user.has_perm('portal.change_product')

    @admin.action(description='دریافت گزارش مقایسهٔ قیمت‌ها',permissions=['change'])
    def fetch_prices(self,request,queryset):
        from .price_sync import sync_source,finish_batch
        from django.shortcuts import redirect
        from django.contrib import messages
        batch=PriceReviewBatch.objects.create(kind='manual')
        for config in queryset.order_by('pk'):
            try:
                sync_source(config.source,actor=request.user,batch=batch)
            except Exception:
                self.message_user(request,f'{config}: دریافت ناموفق بود؛ وضعیت منبع را بررسی کنید.',level=messages.ERROR)
        finish_batch(batch)
        if batch.items.exists():return redirect('admin:price_review',batch.pk)


@admin.register(SourceProduct)
class SourceProductAdmin(SourceApprovalMixin,PriceToolsAdminMixin,StateListMixin,AuditedAdmin):
    state_fields=('sync_enabled',)
    list_hint='برای ثبت قیمت، «تأیید و اعمال قیمت» همان محصول را بزن. لینک زیر قیمت منبع، صفحهٔ تأمین‌کننده را باز می‌کند. برای تأیید چند محصول، ردیف‌ها را انتخاب کن و از منوی اقدام «بررسی و تأیید قیمت‌های انتخاب‌شده» را بزن.'
    state_labels={'sync_enabled':'پایش خودکار'}
    list_display=['product_label','source_item','supplier_price','observation','profit_label','sync_enabled','check_time']
    list_display_links=('source_item',)  # product_label already links to the product editor.
    list_filter=['source','review_status','sync_enabled','available']
    search_fields=['product_name','family_name','external_id','=product_id']
    list_per_page=30
    fields=['source','external_id','product_id','source_page','family_name','family_summary','sync_enabled','last_price',
            'proposed_price','review_status','available','observed_at']
    readonly_fields=[field for field in fields if field not in {'sync_enabled','family_name','family_summary'}]
    actions=['recheck_selected','set_profit','approve_prices','reject_prices']

    @admin.display(description='نتیجهٔ بررسی',ordering='review_status')
    def observation(self,obj):
        from .templatetags.ui import fa_number
        label=obj.get_review_status_display()
        if obj.review_status in ('unavailable','missing'):
            return label
        detail='موجود در منبع' if obj.available else 'ناموجود در منبع'
        if obj.proposed_price:
            detail+=f' · پیشنهاد: {fa_number(obj.proposed_price)} تومان'
        return format_html('{}<small class="catalog-row-category">{}</small>',label,detail)

    @admin.display(description='آخرین بررسی',ordering='observed_at')
    def check_time(self,obj):
        if not obj.observed_at:return '—'
        from django.utils import formats, timezone
        value=timezone.localtime(obj.observed_at)
        return format_html('<time datetime="{}" title="{}">{}<small class="catalog-row-category">{}</small></time>',
                           value.isoformat(),formats.date_format(value,'DATETIME_FORMAT'),formats.date_format(value,'j F'),
                           formats.time_format(value,'H:i'))

    def has_add_permission(self,request):
        return False

    def has_delete_permission(self,request,obj=None):
        return False

    def has_change_permission(self,request,obj=None):
        return super().has_change_permission(request,obj) and request.user.has_perm('portal.change_product')

    @admin.display(description='منبع',ordering='source')
    def source_label(self,obj):
        return dict(SourceSyncSettings._meta.get_field('source').choices).get(obj.source,obj.source)

    @admin.display(description='منبع / شناسه',ordering='external_id')
    def source_item(self,obj):
        return format_html('{} <small dir="ltr">#{}</small>',self.source_label(obj),obj.external_id)

    @admin.display(description='صفحهٔ منبع')
    def source_page(self,obj):
        url=obj.evidence_url
        if not url: return 'لینک محصول ارائه نشده'
        return format_html('<a class="dp-source-page" href="{}" target="_blank" rel="noopener noreferrer">مشاهده در {}</a>',url,self.source_label(obj))

    @admin.display(description='آخرین قیمت منبع (تومان)',ordering='last_price')
    def supplier_price(self,obj):
        from .templatetags.ui import fa_number
        return format_html('<strong>{}</strong><small class="catalog-row-category">{}</small>',
                           fa_number(obj.last_price),self.source_page(obj))

    @admin.display(description='محصول')
    def product_label(self,obj):
        name=getattr(obj,'product_name',None)
        if not name:return str(obj.product_id)
        return format_html('<a href="{}">{}</a>',reverse('admin:portal_product_change',args=[obj.product_id]),name)

    def get_queryset(self,request):
        from django.db.models import OuterRef,Subquery
        return super().get_queryset(request).annotate(
            product_name=Subquery(Product.objects.filter(pk=OuterRef('product_id')).values('name')[:1]),
            fixed_amount=Subquery(ProductSaleOverride.objects.filter(product_id=OuterRef('product_id')).values('amount')[:1]),
            profit=Subquery(Product.objects.filter(pk=OuterRef('product_id')).values('product_profit_percent')[:1]))

    def review_prices(self,request,queryset,action):
        from django.contrib import messages
        from django.shortcuts import render
        from django.utils.dateparse import parse_datetime
        from .price_sync import reject_proposal
        rows=list(queryset.order_by('pk')[:51])
        if len(rows)>50:
            self.message_user(request,'هر بار حداکثر ۵۰ محصول انتخاب کنید.',level=messages.ERROR)
            return
        if request.POST.get('confirm')!='yes':
            return render(request,'admin/portal/sourceproduct/review.html',{
                **self.admin_site.each_context(request),'title':'بررسی تغییر قیمت‌ها',
                'rows':rows,'action_name':action,'opts':self.model._meta,
                'is_approval':action=='approve_prices'})
        count=0
        for row in rows:
            try:
                expected=parse_datetime(request.POST.get('observed_'+str(row.pk),''))
                if expected is None:raise ValueError()
                if action=='approve_prices':
                    item=next((i for i in row.pending_reviews if i.observed_at==expected),None)
                    if not item:raise ValueError()
                    count+=self.apply_review_item(request,item)
                else:
                    reject_proposal(row.pk,request.user,expected_observed_at=expected)
                    count+=1
            except (ValueError,BusinessError,Product.DoesNotExist,SourceProduct.DoesNotExist):
                self.message_user(request,f'محصول {row.product_id}: پیشنهاد معتبر نیست یا تغییر کرده است.',level=messages.WARNING)
        self.message_user(request,f'{count} مورد بررسی و ثبت شد؛ موارد متعارض اعمال نشدند.')

    @admin.action(description='بررسی و تأیید قیمت‌های انتخاب‌شده',permissions=['change'])
    def approve_prices(self,request,queryset):
        return self.review_prices(request,queryset,'approve_prices')

    @admin.action(description='رد قیمت‌های انتخاب‌شده',permissions=['change'])
    def reject_prices(self,request,queryset):
        return self.review_prices(request,queryset,'reject_prices')
