from functools import wraps
from django.apps import apps
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect


class DawnAdminConfig(AdminConfig):
    default_site='portal.admin_site.DawnAdminSite'


class DawnAdminSite(AdminSite):
    site_header='مدیریت دان‌پنل'
    site_title='مدیریت دان‌پنل'
    index_title='نمای کلی فروشگاه'
    index_template='admin/dashboard.html'

    def has_permission(self,request):
        return super().has_permission(request) and bool(request.user.get_all_permissions())

    def admin_view(self,view,cacheable=False):
        secured=super().admin_view(view,cacheable)
        @wraps(view)
        def private_view(request,*args,**kwargs):
            if not self.has_permission(request): raise Http404
            try: return secured(request,*args,**kwargs)
            except PermissionDenied: raise Http404 from None
        return private_view

    def login(self,request,extra_context=None):
        if not self.has_permission(request): raise Http404
        return redirect('admin:index')

    def index(self,request,extra_context=None):
        metrics=[]
        for model,label,url in [('Product','محصول','admin:portal_product_changelist'),('Order','سفارش','admin:portal_order_changelist'),('Ticket','تیکت باز','admin:portal_ticket_changelist'),('Account','حساب کاربری','admin:portal_account_changelist')]:
            if request.user.has_perm('portal.view_'+model.lower()):
                rows=apps.get_model('portal',model).objects.all()
                if model=='Ticket': rows=rows.exclude(status='closed')
                metrics.append({'label':label,'count':rows.count(),'url':url})
        return super().index(request,{'dashboard_metrics':metrics,**(extra_context or {})})
