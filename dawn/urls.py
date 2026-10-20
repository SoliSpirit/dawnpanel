from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from portal import views as v
admin.site.site_header='مدیریت دان پنل'
admin.site.site_title='دان پنل'
admin.site.index_title='مدیریت محصولات، کاربران و محتوا'
def admin_login(request,extra_context=None): return redirect('staff' if request.user.is_authenticated and request.user.is_staff else 'login')
admin.site.login=admin_login
urlpatterns=[path('',v.home,name='home'),path('services/',v.catalog,name='catalog'),path('services/<int:pk>/',v.product,name='product'),path('login/',v.sign_in,name='login'),path('login/verify/',v.verify,name='verify'),path('logout/',v.sign_out,name='logout'),path('account/',v.dashboard,name='dashboard'),path('account/gift/',v.gift,name='gift'),path('account/referrals/',v.referrals,name='referrals'),path('account/orders/',v.orders,name='orders'),path('account/orders/<int:pk>/',v.order_detail,name='order'),path('account/checkout/',v.checkout,name='checkout'),path('account/charge/',v.charge,name='charge'),path('account/tickets/',v.tickets,name='tickets'),path('account/tickets/<int:pk>/',v.ticket_detail,name='ticket'),path('account/tickets/<int:pk>/close/',v.close_ticket,name='close_ticket'),path('payment/verify/',v.payment_callback,name='payment'),path('payment/verify',v.payment_callback),path('staff/',v.staff,name='staff'),path('staff/order/<int:pk>/',v.staff_order,name='staff_order'),path('manage/',admin.site.urls),path('blog/',v.blog,name='blog'),path('blog/<str:slug>/',v.post,name='post'),path('robots.txt',v.robots),path('sitemap.xml',v.sitemap),path('healthz/',v.health),path('<str:page>/',v.legal,name='legal')]
