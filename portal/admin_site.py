from functools import partial,wraps
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect


# Shared by the desktop rail, mobile menu and dashboard's management tools.
WORKSPACE_GROUPS = (
    ('فروشگاه', 'store', 'green', {
        'Product':'box', 'Category':'folders', 'Order':'receipt', 'Ledger':'transfer',
        'Currency':'coins', 'GiftCode':'gift',
    }),
    ('مشتریان و دسترسی‌ها', 'shield', 'indigo', {
        'Account':'id-card', 'LegacyUser':'wallet', 'MemberRank':'award', 'User':'user', 'Group':'users',
    }),
    ('محتوا و پشتیبانی', 'headset', 'blue', {'Post':'pen', 'Ticket':'ticket'}),
    ('قیمت منابع', 'tags', 'amber', {'SourceProduct':'tag', 'SourceSyncSettings':'sliders'}),
    ('تبلیغات', 'megaphone', 'rose', {'Campaign':'target'}),
    ('فعالیت‌ها', 'activity', 'slate', {'Audit':'history','NoticePreference':'sliders','SiteIssue':'alert'}),
)


class DawnAdminConfig(AdminConfig):
    default_site='portal.admin_site.DawnAdminSite'


class DawnAdminSite(AdminSite):
    site_header='مدیریت دان‌پنل'
    site_title='مدیریت دان‌پنل'
    index_title='نمای کلی فروشگاه'
    index_template='admin/dashboard.html'

    def register(self,model_or_iterable,admin_class=None,**options):
        from django.contrib.admin import ModelAdmin
        from .ops_activity import AdminNoticeMixin
        cls=admin_class or ModelAdmin
        wrapped=type(cls.__name__,(AdminNoticeMixin,cls),{'__module__':cls.__module__})
        return super().register(model_or_iterable,wrapped,**options)

    def get_urls(self):
        from django.urls import path
        from . import admin_desk as desk, chat, finance, review_queue,pack_basis
        def workspace(fn,**kwargs):return self.admin_view(partial(fn,site=self,**kwargs))
        return [path('order-alerts/',self.admin_view(self.order_alerts),name='order_alerts'),
            path('prices/reviews/',workspace(review_queue.reports),name='price_reports'),
            path('prices/packs/<int:pk>/',workspace(pack_basis.pack_editor),name='pack_editor'),
            path('prices/reviews/<int:pk>/',workspace(review_queue.report),name='price_review'),
            path('prices/reviews/<int:pk>/items/<int:item_pk>/price/',workspace(review_queue.current_price),name='current_sale_price'),
            path('support/counts/',workspace(desk.desk_counts),name='desk_counts'),
            path('support/chat/',workspace(desk.chat_desk),name='chat_desk'),
            path('support/chat/api/',self.admin_view(chat.support_list),name='desk_chat_api'),
            path('support/chat/api/<uuid:pk>/',self.admin_view(chat.support_thread),name='desk_chat_thread'),
            path('support/requests/',workspace(desk.requests_desk),name='requests_desk'),
            path('support/requests/order/<int:pk>/',workspace(desk.order_action),name='desk_order'),
            path('support/requests/ticket/<int:pk>/',workspace(desk.ticket_action,action='show'),name='desk_ticket'),
            path('support/requests/ticket/<int:pk>/close/',workspace(desk.ticket_action,action='close'),name='desk_ticket_close'),
            path('support/requests/ticket/<int:pk>/settle/',workspace(desk.ticket_action,action='settle'),name='desk_ticket_settle'),
            path('finance/',workspace(finance.finance_report),name='finance_report'),
            path('finance/orders/<int:pk>/cost/',workspace(finance.record_cost),name='finance_cost'),*super().get_urls()]

    def order_alerts(self,request):
        from django.http import HttpResponseNotAllowed,JsonResponse
        from django.urls import reverse
        from .models import Order, OrderEvent
        if request.method!='GET':return HttpResponseNotAllowed(['GET'])
        manager=self.get_model_admin(Order)
        if not manager.has_view_permission(request):raise PermissionDenied
        events=(OrderEvent.objects.filter(order_id__in=manager.get_queryset(request).order_by().values('pk'))
                .select_related('order').order_by('-pk')[:20])
        return JsonResponse({'orders':[
            {'id':e.pk,'channel':e.get_channel_display(),'tracking':e.order.tracking_code,
             'product':e.order.product_name,'amount':e.order.total_price,
             'url':reverse('admin:portal_order_change',args=[e.pk])}
            for e in events if manager.has_view_permission(request,e.order)]})

    def each_context(self, request):
        context=super().each_context(request)
        models=[model for app in context['available_apps'] for model in app['models'] if model['admin_url']]
        groups=[]
        for label, icon, tone, icons in WORKSPACE_GROUPS:
            entries=[{**m, 'icon':icons[m['object_name']]} for m in models if m['object_name'] in icons]
            if entries:
                groups.append({'label':label, 'icon':icon, 'tone':tone, 'models':entries})
                for entry in entries:
                    if request.path.startswith(entry['admin_url']):
                        context['workspace_page']={'icon':entry['icon'], 'tone':tone}
        context['workspace_groups']=groups
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
        from .admin_overview import dashboard_context
        return super().index(request,{**dashboard_context(request),**(extra_context or {})})
