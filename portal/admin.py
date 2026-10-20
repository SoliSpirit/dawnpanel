from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import *
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
    list_display=['name','platform','price','price_per','is_active','show_on_website','show_on_telegram']
    list_filter=['platform','is_active','show_on_website','show_on_telegram','category'];search_fields=['name'];list_per_page=30
    fields=['category','name','description','platform','is_active','show_on_website','show_on_telegram','price','price_currency','price_amount','price_per','product_profit_percent','min_order','max_order','need_link','target_type','target_prompt','seo_description']
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
class AccountAdmin(ReadOnlyAdmin): list_display=['phone','legacy_id','created_at']
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
