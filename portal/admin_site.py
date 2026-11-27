from functools import wraps
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
    ('فعالیت‌ها', 'activity', 'slate', {'Audit':'history'}),
)


class DawnAdminConfig(AdminConfig):
    default_site='portal.admin_site.DawnAdminSite'


class DawnAdminSite(AdminSite):
    site_header='مدیریت دان‌پنل'
    site_title='مدیریت دان‌پنل'
    index_title='نمای کلی فروشگاه'
    index_template='admin/dashboard.html'

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
