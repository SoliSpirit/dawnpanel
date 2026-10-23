from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import *
from .product_media import ProductImageForm,save_product_picture
from django.utils.html import format_html
class AuditAdmin(admin.ModelAdmin):
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
    def get_fieldsets(self,request,obj=None):
        fieldsets=super().get_fieldsets(request,obj)
        if obj:return fieldsets
        return [(name,{**options,'fields':[field for field in options['fields'] if field not in ['current_picture','current_night_picture','remove_picture','remove_night_picture']]}) for name,options in fieldsets]
    readonly_fields=['current_picture','current_night_picture']
    @admin.display(description='عکس فعلی')
    def current_picture(self,obj):
        if obj and obj.visual and obj.visual.image:
            return format_html('<img src="{}" alt="{}" width="240">',obj.visual.image.url,obj.visual.alt_text or obj.name)
        return 'هنوز عکسی ثبت نشده است.'
    @admin.display(description='عکس شب فعلی')
    def current_night_picture(self,obj):
        if obj and obj.visual and obj.visual.night_image:
            return format_html('<img src="{}" alt="{}" width="240">',obj.visual.night_image.url,obj.visual.alt_text or obj.name)
        return 'تصویر شب دسته‌بندی نمایش داده می‌شود.'
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        save_product_picture(obj,form)
    @admin.display(description='محصول',ordering='name')
    def product_label(self,obj):
        return format_html('<strong class="catalog-row-name">{}</strong><small class="catalog-row-category">{}</small>',obj.name,obj.category.name if obj.category else 'بدون دسته‌بندی')
    @admin.display(description='قیمت پایه (تومان)',ordering='price')
    def base_price(self,obj):
        return format_html('<strong>{}</strong><small class="catalog-row-category">به‌ازای {} عدد</small>',format(obj.price,','),format(obj.price_per,','))
    def get_queryset(self,request):return super().get_queryset(request).select_related('category')
    list_display=['product_label','platform','base_price','is_active','show_on_website','show_on_telegram']
    list_filter=['platform','is_active','show_on_website','show_on_telegram','category'];search_fields=['name'];list_per_page=30
    fieldsets=[('معرفی محصول',{'fields':['name','category','platform','description']}),('قیمت و تعداد',{'fields':['price',('price_per','min_order'),'max_order'],'description':'همه قیمت‌های پایه به تومان هستند. برای اشتراک تکی، تعداد مبنا و حداقل سفارش را روی ۱ قرار دهید.'}),('انتشار در سایت و تلگرام',{'fields':['is_active','show_on_website','show_on_telegram'],'description':'محل نمایش محصول را مستقل انتخاب کنید. محصولات غیرفعال قابل خرید نیستند.'}),('تصاویر روز و شب',{'fields':[('picture','night_picture'),'picture_alt','current_picture','current_night_picture','remove_night_picture','remove_picture']}),('اطلاعات تحویل و سئو',{'fields':['need_link','target_prompt','seo_description']}),('تنظیمات پیشرفته قیمت و ربات',{'fields':['price_currency','price_amount','product_profit_percent','target_type'],'classes':['collapse'],'description':'برای فروش معمولی با تومان نیازی به تغییر این بخش ندارید.'})]
    def has_delete_permission(self,request,obj=None): return False
@admin.register(Category)
class CategoryAdmin(AuditedAdmin):
    list_display=['name','sort_order','is_active'];fields=['name','emoji','sort_order','is_active']
    def has_delete_permission(self,request,obj=None): return False
@admin.register(Post)
class PostAdmin(AuditedAdmin):
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
