import hashlib,secrets,uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Q,OuterRef,Subquery,Case,When,Value,IntegerField
from django.http import JsonResponse,HttpResponseForbidden
from django.shortcuts import render,get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods,require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from django.middleware.csrf import get_token
from django.utils import timezone
from .models import ChatConversation,ChatMessage,SupportPresence,Audit
from .services import rate_limit

def can_support(user):
    return user.is_authenticated and user.is_staff and user.has_perm('portal.change_chatconversation')

def visitor_key(request):
    token=request.session.get('_support_chat')
    if not token:
        token=secrets.token_urlsafe(32);request.session['_support_chat']=token
    return hashlib.sha256(token.encode()).hexdigest()

def own_conversation(request,key):
    if request.user.is_authenticated:
        return ChatConversation.objects.filter(Q(user=request.user)|Q(visitor_key=key,user__isnull=True)).order_by('-updated_at').first()
    return ChatConversation.objects.filter(visitor_key=key,user__isnull=True).first()

def parameters(request):
    try:
        after=int(request.GET.get('after','0'))
        if not 0<=after<=2**63-1:raise ValueError
        return after
    except (ValueError,TypeError):return None

def message_values(conversation,after):
    return list(conversation.messages.filter(id__gt=after).values('id','body','from_staff','created_at')[:100]) if conversation else []

def parse_message(request):
    body=request.POST.get('body','').strip()
    if not body or len(body)>2000:return None,None
    try:nonce=uuid.UUID(request.POST.get('nonce',''))
    except (ValueError,TypeError,AttributeError):return None,None
    return body,nonce

@ensure_csrf_cookie
@require_http_methods(['GET','POST'])
def customer_chat(request):
    key=visitor_key(request)
    if request.user.is_authenticated:
        account=getattr(request.user,'account',None)
        if account:
            from .models import LegacyUser
            if LegacyUser.objects.filter(pk=account.legacy_id,is_banned=True).exists():return JsonResponse({'error':'امکان ارسال پیام برای این حساب فعال نیست.'},status=403)
    conversation=own_conversation(request,key)
    if request.method=='POST':
        body,nonce=parse_message(request)
        if body is None:return JsonResponse({'error':'پیام باید بین ۱ تا ۲۰۰۰ نویسه باشد.'},status=400)
        if not rate_limit('chat-ip:'+request.META.get('REMOTE_ADDR','unknown'),40,300) or not rate_limit('chat-session:'+key,20,60):
            return JsonResponse({'error':'تعداد پیام‌ها زیاد است؛ کمی بعد تلاش کنید.'},status=429)
        with transaction.atomic():
            if conversation:conversation=ChatConversation.objects.select_for_update().get(pk=conversation.pk)
            else:
                conversation,_=ChatConversation.objects.get_or_create(visitor_key=key,defaults={'user':request.user if request.user.is_authenticated else None})
                if conversation.user_id is not None and conversation.user_id!=getattr(request.user,'pk',None):return JsonResponse({'error':'گفتگو در دسترس نیست.'},status=403)
                conversation=ChatConversation.objects.select_for_update().get(pk=conversation.pk)
            message,created=ChatMessage.objects.get_or_create(conversation=conversation,nonce=nonce,defaults={'body':body,'from_staff':False,'author':request.user if request.user.is_authenticated else None})
            if created:
                if request.user.is_authenticated and conversation.user_id is None:conversation.user=request.user
                conversation.status='waiting';conversation.save()
        return JsonResponse({'id':message.pk,'conversation':str(conversation.pk),'status':conversation.status})
    after=parameters(request)
    if after is None:return JsonResponse({'error':'درخواست نامعتبر است.'},status=400)
    active=SupportPresence.objects.filter(seen_at__gte=timezone.now()-timedelta(seconds=75),user__is_active=True,user__is_staff=True).select_related('user')
    online=any(can_support(presence.user) for presence in active[:30])
    return JsonResponse({'csrf':get_token(request),'conversation':str(conversation.pk) if conversation else None,'status':conversation.status if conversation else 'new','online':online,'messages':message_values(conversation,after)})

@login_required
def chat_desk(request):
    if not can_support(request.user):return HttpResponseForbidden()
    return render(request,'chat_desk.html',{'title':'میز گفتگوی آنلاین'})

@require_http_methods(['GET','POST'])
def support_list(request):
    if not can_support(request.user):return JsonResponse({'error':'دسترسی مجاز نیست.'},status=403)
    if request.method=='POST':
        SupportPresence.objects.update_or_create(user=request.user)
        return JsonResponse({'ok':True})
    latest=ChatMessage.objects.filter(conversation_id=OuterRef('pk')).order_by('-id')
    rows=ChatConversation.objects.annotate(last_body=Subquery(latest.values('body')[:1]),queue_order=Case(When(status='waiting',then=Value(0)),When(status='open',then=Value(1)),default=Value(2),output_field=IntegerField())).select_related('user').order_by('queue_order','-updated_at')[:80]
    return JsonResponse({'conversations':[{'id':str(row.pk),'label':row.user.username if row.user_id else 'مهمان '+str(row.pk)[:6],'status':row.status,'preview':(row.last_body or '')[:90],'updated_at':row.updated_at} for row in rows]})

@require_http_methods(['GET','POST'])
def support_thread(request,pk):
    if not can_support(request.user):return JsonResponse({'error':'دسترسی مجاز نیست.'},status=403)
    conversation=get_object_or_404(ChatConversation,pk=pk)
    if request.method=='POST':
        if request.POST.get('action')=='close':
            conversation.status='closed';conversation.save()
            Audit.objects.create(actor=request.user,action='chat.close',object_ref=str(pk))
            return JsonResponse({'ok':True,'status':'closed'})
        body,nonce=parse_message(request)
        if body is None:return JsonResponse({'error':'پیام باید بین ۱ تا ۲۰۰۰ نویسه باشد.'},status=400)
        if not rate_limit('chat-staff:'+str(request.user.pk),60,60):return JsonResponse({'error':'کمی بعد تلاش کنید.'},status=429)
        with transaction.atomic():
            conversation=ChatConversation.objects.select_for_update().get(pk=pk)
            message,created=ChatMessage.objects.get_or_create(conversation=conversation,nonce=nonce,defaults={'body':body,'author':request.user,'from_staff':True})
            if created:
                conversation.status='open';conversation.save()
                Audit.objects.create(actor=request.user,action='chat.reply',object_ref=str(pk))
        return JsonResponse({'id':message.pk,'status':conversation.status})
    after=parameters(request)
    if after is None:return JsonResponse({'error':'درخواست نامعتبر است.'},status=400)
    return JsonResponse({'id':str(pk),'status':conversation.status,'messages':message_values(conversation,after)})
