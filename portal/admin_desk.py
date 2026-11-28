from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,render
from django.views.decorators.http import require_GET

from . import chat
from .admin_overview import IN_PROGRESS
from .models import ChatMessage,Order,Ticket


def request_scope(request,site):
    u=request.user
    orders=(site.get_model_admin(Order).get_queryset(request).filter(status__in=IN_PROGRESS)
            if u.has_perm('portal.change_order') else None)
    tickets=(site.get_model_admin(Ticket).get_queryset(request).exclude(status='closed')
             if u.has_perm('portal.change_ticket') else None)
    return orders,tickets


@require_GET
def desk_counts(request,site):
    data={};orders,tickets=request_scope(request,site)
    if chat.can_support(request.user):
        data['chat']=chat.unread_messages().count()
        data['latest']=ChatMessage.objects.filter(from_staff=False).aggregate(n=Max('id'))['n'] or 0
    if orders is not None or tickets is not None:
        data['requests']=(orders.count() if orders is not None else 0)+(tickets.filter(status='open').count() if tickets is not None else 0)
    if not data:raise PermissionDenied
    return JsonResponse(data)


@require_GET
def chat_desk(request,site):
    if not chat.can_support(request.user):raise PermissionDenied
    try:thread=str(UUID(request.GET.get('thread','')))
    except ValueError:thread=''
    return render(request,'admin/portal/chat_desk.html',{**site.each_context(request),'title':'گفتگوی آنلاین','initial_thread':thread})


@require_GET
def requests_desk(request,site):
    orders,tickets=request_scope(request,site)
    if orders is None and tickets is None:raise PermissionDenied
    return render(request,'admin/portal/requests_desk.html',{**site.each_context(request),'title':'رسیدگی به درخواست‌ها',
        'orders':Paginator(orders.order_by('id'),25).get_page(request.GET.get('op')) if orders is not None else None,
        'tickets':Paginator(tickets.select_related('user').order_by('status','-updated_at'),25).get_page(request.GET.get('tp')) if tickets is not None else None})


def order_action(request,pk,site):
    from .views import staff_order
    if not request.user.has_perm('portal.change_order'):raise PermissionDenied
    get_object_or_404(site.get_model_admin(Order).get_queryset(request).only('pk'),pk=pk)
    return staff_order(request,pk)


def ticket_action(request,pk,site,action):
    from .views import ticket_detail,close_ticket
    from .crypto_topups import settle_view
    if not request.user.has_perm('portal.change_ticket'):raise PermissionDenied
    get_object_or_404(site.get_model_admin(Ticket).get_queryset(request).only('pk'),pk=pk)
    if action=='show':return ticket_detail(request,pk,site=site)
    if action=='close':return close_ticket(request,pk,return_route='admin:desk_ticket')
    return settle_view(request,pk,return_route='admin:desk_ticket')
