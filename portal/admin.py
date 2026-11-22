from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import *
from .product_media import ProductImageForm,save_product_picture
from django.utils.html import format_html
from django.urls import reverse
from .services import BusinessError

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display=['name','share_link','clicks','registrations','active']
    readonly_fields=['share_link','clicks','registrations']
    search_fields=['name','code']
    @admin.display(description='لینک قابل اشتراک')
    def share_link(self,obj):
        if not obj.code:return 'پس از ذخیره ساخته می‌شود.'
        url='https://dawnpanel.ir'+reverse('campaign',args=[obj.code])
        return format_html('<a href="{}" dir="ltr">{}</a>',url,url)
class AuditAdmin(admin.ModelAdmin):
    date_hierarchy='created_at'
    search_fields=['actor__username','action','object_ref']
    list_select_related=['actor']
    list_display=['created_at','actor','action','object_ref'];list_filter=['action'];readonly_fields=['actor','action','object_ref','details','created_at']
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False
admin.site.register(Audit,AuditAdmin)
class AuditedAdmin(admin.ModelAdmin):
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        Audit.objects.create(actor=request.user,action=self.model._meta.model_name+('.update' if change else '.create'),object_ref=str(obj.pk),details={'fields':list(form.changed_data)})
@admin.register(Product)
class ProductAdmin(AuditedAdmin):
    form=ProductImageForm
    change_form_template='admin/portal/product/change_form.html'
    def get_changeform_initial_data(self,request):
        return {'platform':'rubika','show_on_website':True,**super().get_changeform_initial_data(request)}
    def render_change_form(self,request,context,add=False,change=False,form_url='',obj=None):
        from .catalog_aliases import PREMSTORE_EQUIVALENTS
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
    def get_queryset(self,request):return super().get_queryset(request).select_related('category','tax_policy')
    list_display=['product_label','platform','base_price','tax_label','is_active','show_on_website','show_on_telegram']
    list_editable=['is_active','show_on_website','show_on_telegram']
    list_filter=['platform','is_active','show_on_website','show_on_telegram','category'];search_fields=['name'];list_per_page=30
    fieldsets=[('معرفی محصول',{'fields':['name','category','platform','plan_name','duration_months','description']}),('قیمت و تعداد',{'fields':['price','tax_percent',('price_per','min_order'),'max_order'],'description':'همه قیمت‌های پایه به تومان هستند. برای اشتراک تکی، تعداد مبنا و حداقل سفارش را روی ۱ قرار دهید.'}),('انتشار در سایت و تلگرام',{'fields':['is_active','show_on_website','show_on_telegram'],'description':'محل نمایش محصول را مستقل انتخاب کنید. محصولات غیرفعال قابل خرید نیستند.'}),('تصاویر روز و شب',{'fields':[('picture','night_picture'),'picture_alt','current_picture','current_night_picture','remove_night_picture','remove_picture']}),('اطلاعات تحویل و سئو',{'fields':['need_link','target_prompt','seo_description']}),('تنظیمات پیشرفته قیمت و ربات',{'fields':['price_currency','price_amount','product_profit_percent','target_type'],'classes':['collapse'],'description':'برای فروش معمولی با تومان نیازی به تغییر این بخش ندارید.'})]
    def has_delete_permission(self,request,obj=None): return False
@admin.register(Category)
class CategoryAdmin(AuditedAdmin):
    list_display=['name','sort_order','is_active'];fields=['name','emoji','sort_order','is_active']
    def has_delete_permission(self,request,obj=None): return False
@admin.register(Post)
class PostAdmin(AuditedAdmin):
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
class CurrencyAdmin(AuditedAdmin):
    list_display=['code','name','rate','is_active','updated_at'];fields=['code','name','symbol','rate','type','icon','is_active']
    def has_delete_permission(self,request,obj=None): return False
@admin.register(GiftCode)
class GiftAdmin(AuditedAdmin):
    list_display=['code','amount','is_active','used_count','max_uses','target_type'];readonly_fields=['used_count','created_by','created_at']
    def has_delete_permission(self,request,obj=None): return False
    def save_model(self,request,obj,form,change):
        if not obj.pk: obj.created_by=request.user.pk
        super().save_model(request,obj,form,change)
@admin.register(MemberRank)
class RankAdmin(AuditedAdmin): list_display=['name','min_spending']


@admin.register(SourceSyncSettings)
class SourceSyncSettingsAdmin(AuditedAdmin):
    list_display=['source','enabled','require_approval','interval_minutes','last_success','last_error']
    fields=['source','enabled','require_approval','interval_minutes','max_change_percent',
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

    @admin.action(description='دریافت قیمت‌ها اکنون (مطابق حالت تأیید/خودکار)',permissions=['change'])
    def fetch_prices(self,request,queryset):
        from .price_sync import sync_source
        from django.contrib import messages
        for config in queryset:
            try:
                result=sync_source(config.source,actor=request.user)
                self.message_user(request,f'{config}: {result}')
            except Exception:
                self.message_user(request,f'{config}: دریافت ناموفق بود؛ وضعیت منبع را بررسی کنید.',level=messages.ERROR)


@admin.register(SourceProduct)
class SourceProductAdmin(AuditedAdmin):
    list_display=['product_label','source','external_id','last_price','proposed_price',
                  'review_status','available','sync_enabled','observed_at']
    list_filter=['source','review_status','sync_enabled','available']
    search_fields=['external_id','=product_id']
    list_per_page=30
    fields=['source','external_id','product_id','source_url','family_name','family_summary','sync_enabled','last_price',
            'proposed_price','review_status','available','observed_at']
    readonly_fields=[field for field in fields if field not in {'sync_enabled','family_name','family_summary'}]
    actions=['approve_prices','reject_prices']

    def has_add_permission(self,request):
        return False

    def has_delete_permission(self,request,obj=None):
        return False

    def has_change_permission(self,request,obj=None):
        return super().has_change_permission(request,obj) and request.user.has_perm('portal.change_product')

    @admin.display(description='محصول')
    def product_label(self,obj):
        name=getattr(obj,'product_name',None)
        if not name:return str(obj.product_id)
        return format_html('<a href="{}">{}</a>',reverse('admin:portal_product_change',args=[obj.product_id]),name)

    def get_queryset(self,request):
        from django.db.models import OuterRef,Subquery
        return super().get_queryset(request).annotate(
            product_name=Subquery(Product.objects.filter(pk=OuterRef('product_id')).values('name')[:1]))

    def review_prices(self,request,queryset,action):
        from django.contrib import messages
        from django.shortcuts import render
        from django.utils.dateparse import parse_datetime
        from .price_sync import apply_proposal,reject_proposal
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
                    count+=bool(apply_proposal(row.pk,request.user,expected_observed_at=expected))
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
