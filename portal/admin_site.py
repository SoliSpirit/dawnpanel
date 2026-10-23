from functools import wraps
from django.apps import apps
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.db.models import Sum


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

    def get_app_list(self,request,app_label=None):
        app_list=super().get_app_list(request,app_label)
        priority=['Product','Category','Order','Ticket','Account','LegacyUser','Ledger','Post','GiftCode','Currency','MemberRank','Audit']
        for app in app_list:
            if app['app_label']=='portal':
                app['name']='فروشگاه و محتوا'
                app['models'].sort(key=lambda model:priority.index(model['object_name']) if model['object_name'] in priority else len(priority))
            elif app['app_label']=='auth':app['name']='کاربران و دسترسی‌ها'
        return sorted(app_list,key=lambda app:app['app_label']!='portal')

    def index(self,request,extra_context=None):
        metrics=[]
        for model,label,url in [('Product','محصول','admin:portal_product_changelist'),('Order','سفارش','admin:portal_order_changelist'),('Ticket','تیکت باز','admin:portal_ticket_changelist'),('Account','حساب کاربری','admin:portal_account_changelist')]:
            if request.user.has_perm('portal.view_'+model.lower()):
                rows=apps.get_model('portal',model).objects.all()
                if model=='Ticket': rows=rows.exclude(status='closed')
                metrics.append({'label':label,'count':rows.count(),'url':url})
        context={'dashboard_metrics':metrics}
        if request.user.has_perm('portal.view_order'):
            orders=apps.get_model('portal','Order').objects.all()
            context.update(recent_orders=orders[:6],pending_orders_count=orders.filter(status__in=['pending','confirmed','approved','processing']).count(),completed_revenue=orders.filter(status='completed').aggregate(total=Sum('total_price'))['total'] or 0)
        if request.user.has_perm('portal.view_ticket'):
            context['recent_tickets']=apps.get_model('portal','Ticket').objects.select_related('user').exclude(status='closed')[:5]
        return super().index(request,{**context,**(extra_context or {})})
