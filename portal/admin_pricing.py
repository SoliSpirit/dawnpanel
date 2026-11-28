"""Staff actions for supplier observations and explicit per-product markups."""
from collections import defaultdict
from time import monotonic

from django import forms
from django.contrib import admin, messages
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_protect

from .models import Audit, Product, ProductSaleOverride, SourceProduct,PriceReviewBatch
from .price_sync import sync_source,finish_batch
from django.urls import reverse
from .pricing import BusinessError
from .product_media import ProfitPercentField
from .supplier_clients import SupplierError
from .templatetags.ui import fa_number


def profit_text(value):
    if value is None:
        return '—'
    if not value:
        return 'بدون سود'
    return format(value.normalize(),'f').translate(str.maketrans('0123456789.', '۰۱۲۳۴۵۶۷۸۹٫'))+'٪'


class ProfitForm(forms.Form):
    percent = ProfitPercentField()


class PriceToolsAdminMixin:
    """Shared by the two lists, not a general-purpose field update endpoint."""
    def has_recheck_permission(self, request):
        return (self.has_change_permission(request)
                and self.admin_site.get_model_admin(SourceProduct).has_change_permission(request))

    @admin.display(description='سود فروش')
    def profit_label(self, obj):
        fixed=obj.fixed_sale if self.model is Product else obj.fixed_amount
        if fixed is not None:return f'فروش ثابت: {fa_number(fixed)} تومان'
        value = obj.product_profit_percent if self.model is Product else obj.profit
        return profit_text(value)

    def get_list_display(self, request):
        cols = super().get_list_display(request)
        if '_popup' not in request.GET and self.has_change_permission(request):
            @admin.display(description='سود فروش',ordering='product_profit_percent' if self.model is Product else 'profit')
            def edit_profit(obj):
                if not self.has_change_permission(request,obj):
                    return self.profit_label(obj)
                return format_html('<button type="submit" class="dp-profit-value" name="_dp_profit" value="{}" '
                                   'formnovalidate aria-label="تنظیم سود: {}">{}</button>',str(obj.pk),str(obj),self.profit_label(obj))
            cols = [edit_profit if col=='profit_label' else col for col in cols]
        if '_popup' in request.GET or not self.has_recheck_permission(request):
            return cols

        @admin.display(description='بررسی قیمت')
        def recheck_row(obj):
            if self.model is Product and not obj._has_source:
                return 'بدون منبع'
            if not self.has_change_permission(request,obj):
                return '—'
            return format_html('<button type="submit" class="dp-price-button" name="_dp_recheck" '
                               'value="{}" formnovalidate aria-label="بررسی مجدد: {}">بررسی مجدد</button>',
                               str(obj.pk),str(obj))
        return [*cols,recheck_row]

    def _scoped_products(self, request, rows, *, lock=False):
        """Recheck both row scopes and permissions on confirmation. Lock in PK order."""
        selected = list(rows.order_by('pk'))
        if not all(self.has_change_permission(request,row) for row in selected):
            raise PermissionDenied
        product_admin = self.admin_site.get_model_admin(Product)
        if not product_admin.has_change_permission(request):
            raise PermissionDenied
        ids = [r.product_id if self.model is SourceProduct else r.pk for r in selected]
        scope = product_admin.get_queryset(request).filter(pk__in=ids).order_by().values('pk')
        products = Product.objects.filter(pk__in=scope).select_related('sale_override').order_by('pk')
        if lock:
            products = products.select_for_update()
        products = list(products)
        if len(products)!=len(ids) or not all(product_admin.has_change_permission(request,p)
                and 'product_profit_percent' not in product_admin.get_readonly_fields(request,p) for p in products):
            raise PermissionDenied
        return selected,products

    @admin.action(description='تنظیم درصد سود انتخاب‌ها',permissions=['change'])
    def set_profit(self, request, queryset):
        selected,products = self._scoped_products(request,queryset)
        if not products:
            self.message_user(request,'محصولی برای تنظیم سود انتخاب نشده است.',messages.WARNING)
            return
        # Freeze the selection, mapping and currently visible percentages (including
        # "select across"). A single form field works beyond a page of checkboxes.
        payload = {'user':request.user.pk,'ids':[r.pk for r in selected],
                   'before':[[p.pk,str(p.product_profit_percent),p.fixed_sale] for p in products]}
        ticket = signing.dumps(payload,salt=self.opts.label_lower+'.profit',compress=True)
        form = ProfitForm(initial={'percent':format(products[0].product_profit_percent.normalize(),'f')} if len(products)==1 else {})
        return self._profit_page(request,form,ticket,products)

    def _profit_page(self,request,form,ticket,products):
        return render(request,'admin/portal/profit_form.html',{
            **self.admin_site.each_context(request),'opts':self.opts,'title':'تنظیم درصد سود',
            'form':form,'selection':ticket,'count':len(products),
            'sample':[(p.name,profit_text(p.product_profit_percent)) for p in products[:8]],
            'return_url':request.get_full_path(),
        })

    @transaction.atomic
    def _save_profit(self, request):
        if not self.has_change_permission(request) or '_popup' in request.GET:
            raise PermissionDenied
        ticket = request.POST['_dp_profit_selection']
        try:
            token = signing.loads(ticket,salt=self.opts.label_lower+'.profit',max_age=1800)
        except signing.BadSignature:
            self.message_user(request,'انتخاب معتبر نیست یا مهلتش تمام شده؛ ردیف‌ها را دوباره انتخاب کن.',messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
        if token['user'] != request.user.pk:
            raise PermissionDenied
        rows = self.get_queryset(request).filter(pk__in=token['ids'])
        if self.model is SourceProduct:
            rows = rows.select_for_update()
        selected,products = self._scoped_products(request,rows,lock=True)
        if ([r.pk for r in selected] != token['ids']
                or [[p.pk,str(p.product_profit_percent),p.fixed_sale] for p in products] != token['before']):
            self.message_user(request,'انتخاب یا درصد سود تغییر کرده است؛ فهرست را بررسی و دوباره انتخاب کن.',messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
        form = ProfitForm(request.POST)
        if not form.is_valid():
            return self._profit_page(request,form,ticket,products)
        percent = form.cleaned_data['percent']
        changed = [p for p in products if p.product_profit_percent!=percent or p.fixed_sale is not None]
        ProductSaleOverride.objects.filter(product_id__in=[p.pk for p in changed]).delete()
        Product.objects.filter(pk__in=[p.pk for p in changed]).update(product_profit_percent=percent)
        Audit.objects.bulk_create([Audit(actor=request.user,action='product.profit',object_ref=str(p.pk),
            details={'old':str(p.product_profit_percent),'new':str(percent),'fixed_before':p.fixed_sale}) for p in changed],batch_size=100)
        if changed:
            Audit.objects.create(actor=request.user,action='catalog.profit.batch',details={'count':len(changed)})
            from django.contrib.admin.models import CHANGE, LogEntry
            LogEntry.objects.log_actions(user_id=request.user.pk,queryset=changed,action_flag=CHANGE,
                                        change_message=[{'changed':{'fields':['درصد سود']}}])
        self.message_user(request,f'سود فروش: {profit_text(percent)}. {fa_number(len(changed))} محصول تغییر کرد.')
        return HttpResponseRedirect(request.get_full_path())

    @admin.action(description='بررسی مجدد قیمت و موجودی انتخاب‌ها',permissions=['recheck'])
    def recheck_selected(self, request, queryset):
        if not self.has_recheck_permission(request) or '_popup' in request.GET:
            raise PermissionDenied
        link_admin = self.admin_site.get_model_admin(SourceProduct)
        if self.model is SourceProduct:
            links = list(queryset.order_by('pk'))
        else:
            selected = list(queryset)
            if not all(self.has_change_permission(request,row) for row in selected):
                raise PermissionDenied
            links = list(link_admin.get_queryset(request).filter(product_id__in=[p.pk for p in selected]))
        if not all(link_admin.has_change_permission(request,link) for link in links):
            raise PermissionDenied
        groups = defaultdict(list)
        for link in links:
            groups[link.source].append(link.pk)
        if not groups:
            self.message_user(request,'هیچ‌کدام از این محصولات به منبع قیمت متصل نیستند.',messages.WARNING)
            return
        batch=PriceReviewBatch.objects.create(kind='manual')
        deadline = monotonic()+35
        for source, ids in sorted(groups.items()):
            name = {'denapanel':'دناپنل','premstore':'پریم‌استور'}.get(source,source)
            try:
                result = sync_source(source,link_ids=ids,actor=request.user,deadline=deadline,batch=batch)
            except (BusinessError,SupplierError) as error:
                self.message_user(request,f'{name}: {error}',messages.ERROR)
            else:
                text = '، '.join(f'{fa_number(result[k])} {label}' for k,label in [
                    ('checked','بررسی'),('available','موجود'),('unavailable','ناموجود'),('missing','پیدا نشده'),('pending','پیشنهاد قیمت')])
                self.message_user(request,f'{name}: {text}.')
        finish_batch(batch)
        if batch.items.exists():return HttpResponseRedirect(reverse('admin:price_review',args=[batch.pk]))

    @method_decorator(csrf_protect)
    def changelist_view(self,request,extra_context=None):
        if request.method=='POST' and '_dp_profit_selection' in request.POST:
            return self._save_profit(request)
        if request.method=='POST' and ('_dp_recheck' in request.POST or '_dp_profit' in request.POST):
            profit = '_dp_profit' in request.POST
            if '_popup' in request.GET or not (self.has_change_permission(request) if profit else self.has_recheck_permission(request)):
                raise PermissionDenied
            value=request.POST['_dp_profit' if profit else '_dp_recheck']
            if value=='results' and not profit:
                rows=self.get_changelist_instance(request).queryset
            elif len(value)<=19 and value.isascii() and value.isdecimal() and 0<int(value)<2**63:
                rows=self.get_queryset(request).filter(pk=int(value))
                if not rows.exists(): raise Http404
            else:
                raise Http404
            if profit:
                return self.set_profit(request,rows)
            return self.recheck_selected(request,rows) or HttpResponseRedirect(request.get_full_path())
        return super().changelist_view(request,{'can_recheck_all':self.model is SourceProduct and self.has_recheck_permission(request),
                                                **(extra_context or {})})
