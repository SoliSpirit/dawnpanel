from functools import wraps
from django.apps import apps
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.db.models import Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from datetime import date, timedelta


class DawnAdminConfig(AdminConfig):
    default_site='portal.admin_site.DawnAdminSite'


class DawnAdminSite(AdminSite):
    site_header='مدیریت دان‌پنل'
    site_title='مدیریت دان‌پنل'
    index_title='نمای کلی فروشگاه'
    index_template='admin/dashboard.html'

    def each_context(self, request):
        context=super().each_context(request)
        groups=[('فروشگاه', {'Product','Category','Order','Ledger','Currency','GiftCode'}),
                ('مشتریان و دسترسی‌ها', {'Account','LegacyUser','MemberRank','User','Group'}),
                ('محتوا و پشتیبانی', {'Post','Ticket'}), ('تبلیغات', {'Campaign'}), ('فعالیت‌ها', {'Audit'})]
        models=[model for app in context['available_apps'] for model in app['models'] if model['admin_url']]
        context['workspace_groups']=[(label,[m for m in models if m['object_name'] in names]) for label,names in groups]
        return context

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
        icons={'Product':'grid','Order':'clock','Ticket':'headset','Account':'user'}
        for metric,model in zip(metrics,[m for m in ['Product','Order','Ticket','Account'] if request.user.has_perm('portal.view_'+m.lower())]):
            metric['icon']=icons[model]
        context={'dashboard_metrics':metrics,'dashboard_date':timezone.localdate()}
        if request.user.has_perm('portal.view_order'):
            orders=apps.get_model('portal','Order').objects.all()
            context.update(recent_orders=orders[:6],pending_orders_count=orders.filter(status__in=['pending','confirmed','approved','processing']).count(),completed_revenue=orders.filter(status='completed').aggregate(total=Sum('total_price'))['total'] or 0)
        if request.user.has_perm('portal.view_ticket'):
            context['recent_tickets']=apps.get_model('portal','Ticket').objects.select_related('user').exclude(status='closed')[:5]
        today=timezone.localdate()
        period=request.GET.get('period','week')
        days={'today':1,'week':7,'month':30,'year':365}
        start,end=today-timedelta(days=days.get(period,7)-1),today
        if period=='custom':
            try:
                start,end=(date.fromisoformat(request.GET.get(k,'')) for k in ('start','end'))
                if not date(2000,1,1)<=start<=end<=today or (end-start).days>365:raise ValueError
            except ValueError:
                start,end=today-timedelta(days=6),today
                context['report_error']='بازه معتبر تا ۳۶۶ روز و حداکثر تا امروز انتخاب کنید.'
        elif period not in days:period='week'
        context.update(report_start=start,report_end=end,report_period=period)
        if request.user.has_perm('portal.view_account'):
            context['new_customers_today']=apps.get_model('portal','Account').objects.filter(created_at__date=today).count()
        if request.user.has_perm('portal.view_order'):
            completed=orders.filter(status='completed')
            context['today_sales']=completed.filter(completed_at__date=today).aggregate(total=Sum('total_price'))['total'] or 0
            trunc=TruncMonth if (end-start).days>60 else TruncDate
            rows=list(completed.filter(completed_at__date__range=(start,end)).order_by().annotate(day=trunc('completed_at')).values('day').annotate(total=Sum('total_price')).order_by('day'))
            peak=max([1]+[row['total'] for row in rows])
            for row in rows:row['bar']=max(0,min(100,round(row['total']*100/peak)))
            # Fill the selected interval, including periods without completed sales.
            totals={row['day'].strftime('%Y-%m' if trunc is TruncMonth else '%Y-%m-%d'):row['total'] for row in rows}
            chart=[]
            cursor=start.replace(day=1) if trunc is TruncMonth else start
            while cursor<=end:
                key=cursor.strftime('%Y-%m' if trunc is TruncMonth else '%Y-%m-%d')
                chart.append({'label':key,'amount':totals.get(key,0)})
                cursor=(cursor.replace(year=cursor.year+1,month=1) if cursor.month==12 else cursor.replace(month=cursor.month+1)) if trunc is TruncMonth else cursor+timedelta(days=1)
            context.update(sales_rows=rows,range_sales=sum(row['total'] for row in rows),monthly_buckets=trunc is TruncMonth,sales_chart=chart)
        return super().index(request,{**context,**(extra_context or {})})
