import secrets,uuid
from urllib.parse import quote
from django.shortcuts import render,redirect,get_object_or_404
from django.http import HttpResponse,HttpResponseForbidden,JsonResponse
from django.contrib.auth import login,logout
from django.contrib.auth.decorators import login_required,permission_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q,Sum
from django.db import transaction
from django.views.decorators.http import require_POST,require_GET
from django.utils import timezone
from .models import *
from .forms import *
from .services import *

def with_product_images(products):
    products=list(products)
    images={image.product_id:image for image in ProductVisual.objects.filter(product_id__in=[p.pk for p in products])}
    for product in products: product._visual_cache=images.get(product.pk)
    return products

def home(request):
    return render(request,'home.html',{'featured':with_product_images(public_products().exclude(platform='ai').order_by('id')[:6]),'ai_products':with_product_images(public_products().filter(platform='ai').order_by('id')[:3]),'posts':Post.objects.filter(published=True)[:3],'title':'دان پنل | اشتراک هوش مصنوعی و خدمات دیجیتال','description':'فروشگاه دان پنل؛ اشتراک ChatGPT، Gemini و Claude و خدمات روبیکا، ایتا و بله با قیمت روشن، حساب یکپارچه و پشتیبانی تیکتی.'})

def ai_catalog(request):
    return catalog(request,platform_override='ai')

def catalog(request,platform_override=None):
    products=public_products().select_related('category')
    platform=platform_override or request.GET.get('platform','')
    if platform in ['rubika','eitaa','bale','ai']: products=products.filter(platform=platform)
    q=request.GET.get('q','')[:100]
    if q:
        terms=[q]
        for aliases in [('ChatGPT','چت جی پی تی','چت‌جی‌پی‌تی'),('Gemini','جمینای'),('Claude','کلاد','کلود')]:
            if q.casefold() in [alias.casefold() for alias in aliases]: terms=list(aliases)
        search=Q()
        for term in terms: search |= Q(name__icontains=term)|Q(description__icontains=term)
        products=products.filter(search)
    page=Paginator(products.order_by('id'),12).get_page(request.GET.get('page'))
    page.object_list=with_product_images(page.object_list)
    return render(request,'catalog.html',{'page':page,'platform':platform,'q':q,'title':'اشتراک هوش مصنوعی؛ ChatGPT، Gemini و Claude | دان پنل' if platform=='ai' else 'خرید خدمات دیجیتال و پیام‌رسان | دان پنل','description':'خرید و بررسی اشتراک‌های هوش مصنوعی ChatGPT، Gemini و Claude؛ شرایط و مدت هر اشتراک را پیش از خرید بررسی کنید.' if platform=='ai' else 'مشاهده قیمت و شرایط خدمات روبیکا، ایتا و بله و اشتراک‌های هوش مصنوعی در فروشگاه دان پنل.'})

def product(request,pk):
    p=get_object_or_404(public_products(),pk=pk)
    form=OrderForm(request.POST or None,initial={'quantity':p.min_order})
    if p.platform=='ai':
        form.fields['target'].label='ایمیل یا توضیحات سفارش'
        form.fields['target'].help_text='اطلاعات لازم برای تحویل، مطابق توضیحات محصول.'
    total=None
    try: pack=price_for(p,p.price_per if p.price_per>=p.min_order and (not p.max_order or p.price_per<=p.max_order) else p.min_order)[1]
    except BusinessError: pack=None
    if request.method=='POST' and form.is_valid():
        if not request.user.is_authenticated: return redirect('login')
        try:
            total,_=price_for(p,form.cleaned_data['quantity'])
            if p.need_link and not form.cleaned_data['target'].strip(): raise BusinessError('اطلاعات مقصد را وارد کنید.')
            key=str(uuid.uuid4()); pending={'product_id':p.pk,'quantity':form.cleaned_data['quantity'],'target':form.cleaned_data['target'],'quoted_total':total,'key':key}
            request.session['checkout']=pending
            return render(request,'review.html',{'product':p,'pending':pending,'total':total,'title':'تایید سفارش'})
        except BusinessError as e: form.add_error(None,str(e))
    return render(request,'product.html',{'product':p,'form':form,'pack_price':pack,'title':p.name,'description':p.seo_description or (p.name+'؛ مشاهده قیمت، شرایط سفارش و پشتیبانی در دان پنل.')[:160]})

@require_POST
@login_required
def checkout(request):
    pending=request.session.get('checkout')
    if not pending or not secrets.compare_digest(str(request.POST.get('key','')),pending['key']):
        messages.error(request,'درخواست منقضی شده است. سفارش را دوباره بررسی کنید.');return redirect('catalog')
    try:
        order=place_order(request.user.account,**pending)
        request.session.pop('checkout',None)
        messages.success(request,'سفارش ثبت شد. کد پیگیری: '+order.tracking_code)
        return redirect('order',pk=order.pk)
    except (BusinessError,Account.DoesNotExist) as e:
        messages.error(request,str(e));return redirect('product',pk=pending['product_id'])

def sign_in(request):
    if request.user.is_authenticated: return redirect('dashboard')
    if not request.session.session_key: request.session.create()
    form=PhoneForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            otp=request_otp(form.cleaned_data['phone'],request.session.session_key,request.META.get('REMOTE_ADDR',''))
            request.session['otp_id']=str(otp.pk);request.session['otp_phone']=otp.phone
            return redirect('verify')
        except BusinessError as e: form.add_error(None,str(e))
    return render(request,'auth.html',{'form':form,'title':'ورود یا ثبت‌نام','subtitle':'با شماره موبایل خود وارد شوید. رمز یک‌بارمصرف برای شما پیامک می‌شود.','button':'دریافت کد ورود'})

def verify(request):
    if request.user.is_authenticated: return redirect('dashboard')
    otp_id=request.session.get('otp_id')
    if not otp_id: return redirect('login')
    form=CodeForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        code=form.cleaned_data['code']
        if not rate_limit('verify-ip:'+request.META.get('REMOTE_ADDR',''),30,900): form.add_error(None,'تعداد تلاش‌ها بیش از حد مجاز است.')
        else:
            phone=verify_otp(otp_id,code,request.session.session_key)
            if phone:
                try:
                    user=login_account(phone);login(request,user,backend='django.contrib.auth.backends.ModelBackend')
                    request.session.pop('otp_id',None);request.session.pop('otp_phone',None)
                    return redirect('staff' if user.is_staff else 'dashboard')
                except BusinessError as e: form.add_error(None,str(e))
            else: form.add_error(None,'کد اشتباه، منقضی یا مصرف شده است. پس از پنج تلاش، کد جدید بگیرید.')
    return render(request,'auth.html',{'form':form,'title':'تایید شماره موبایل','subtitle':'کد پیامک‌شده را وارد کنید. اعتبار کد پنج دقیقه است.','button':'تایید و ورود','verify':True})

@require_POST
def sign_out(request): logout(request);return redirect('home')

@login_required
def dashboard(request):
    a=request.user.account;wallet=get_object_or_404(LegacyUser,pk=a.legacy_id)
    return render(request,'dashboard.html',{'wallet':wallet,'orders':Order.objects.filter(user_id=a.legacy_id)[:5],'transactions':Ledger.objects.filter(user_id=a.legacy_id)[:8],'order_count':Order.objects.filter(user_id=a.legacy_id).count(),'ticket_count':Ticket.objects.filter(user=request.user).exclude(status='closed').count(),'rank':MemberRank.objects.filter(min_spending__lte=wallet.total_purchases).last(),'title':'حساب کاربری'})

@login_required
def orders(request):
    rows=Order.objects.filter(user_id=request.user.account.legacy_id)
    return render(request,'orders.html',{'page':Paginator(rows,20).get_page(request.GET.get('page')),'title':'سفارش‌های من'})

@login_required
def order_detail(request,pk):
    order=get_object_or_404(Order,pk=pk,user_id=request.user.account.legacy_id)
    return render(request,'order.html',{'order':order,'title':'سفارش '+order.tracking_code})

@login_required
def charge(request):
    form=ChargeForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            if not rate_limit('payment:'+str(request.user.pk),5,300): raise BusinessError('کمی بعد دوباره تلاش کنید.')
            return redirect(start_payment(request.user.account,form.cleaned_data['amount']))
        except BusinessError as e: form.add_error(None,str(e))
    return render(request,'simple_form.html',{'form':form,'title':'شارژ کیف پول','subtitle':'پرداخت از طریق درگاه زرین‌پال؛ مبالغ به تومان هستند.','button':'ادامه و پرداخت'})

@require_GET
def payment_callback(request):
    amount=None;ref=None;error=None
    try:
        if request.GET.get('Status')!='OK': raise BusinessError('پرداخت لغو شده است یا هنوز تایید نشده است.')
        amount,ref=verify_payment(request.GET.get('Authority'))
    except BusinessError as e: error=str(e)
    return render(request,'payment.html',{'amount':amount,'ref':ref,'error':error,'title':'نتیجه پرداخت'})

@login_required
def tickets(request):
    form=TicketForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if rate_limit('ticket:'+str(request.user.pk),5,3600):
            with transaction.atomic():
                ticket=form.save(commit=False);ticket.user=request.user;ticket.save()
                TicketMessage.objects.create(ticket=ticket,author=request.user,body=form.cleaned_data['body'])
            messages.success(request,'تیکت شما ثبت شد.');return redirect('ticket',pk=ticket.pk)
        form.add_error(None,'تعداد تیکت‌ها زیاد است. کمی بعد تلاش کنید.')
    return render(request,'tickets.html',{'tickets':Ticket.objects.filter(user=request.user)[:50],'form':form,'title':'پشتیبانی و تیکت‌ها'})

@login_required
def ticket_detail(request,pk):
    staff=request.user.has_perm('portal.change_ticket')
    rows=Ticket.objects.all() if staff else Ticket.objects.filter(user=request.user)
    ticket=get_object_or_404(rows,pk=pk)
    form=ReplyForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if ticket.status=='closed': form.add_error(None,'این تیکت بسته شده است.')
        elif not rate_limit('reply:'+str(request.user.pk),30,300): form.add_error(None,'کمی بعد تلاش کنید.')
        else:
            with transaction.atomic():
                TicketMessage.objects.create(ticket=ticket,author=request.user,body=form.cleaned_data['body'])
                ticket.status='answered' if staff else 'open';ticket.save()
                if staff: Audit.objects.create(actor=request.user,action='ticket.reply',object_ref=str(pk))
            return redirect('ticket',pk=pk)
    return render(request,'ticket.html',{'ticket':ticket,'thread':ticket.messages.select_related('author'),'form':form,'title':ticket.subject,'staff_reply':staff})

@require_POST
@login_required
def close_ticket(request,pk):
    ticket=get_object_or_404(Ticket,pk=pk)
    if ticket.user_id!=request.user.pk and not request.user.has_perm('portal.change_ticket'): return HttpResponseForbidden()
    ticket.status='closed';ticket.save();return redirect('ticket',pk=pk)

@login_required
def staff(request):
    if not request.user.is_staff: return HttpResponseForbidden()
    can_orders=request.user.has_perm('portal.change_order')
    can_tickets=request.user.has_perm('portal.change_ticket')
    return render(request,'staff.html',{'title':'میز مدیریت','pending_orders':Order.objects.filter(status__in=['pending','confirmed','approved'])[:30] if can_orders else [],'support_tickets':Ticket.objects.exclude(status='closed')[:30] if can_tickets else [],'can_orders':can_orders,'can_tickets':can_tickets,'revenue':Order.objects.filter(status='completed').aggregate(total=Sum('total_price'))['total'] or 0 if can_orders else None})

@require_POST
@permission_required('portal.change_order',raise_exception=True)
def staff_order(request,pk):
    try: change_order(request.user,pk,request.POST.get('status'),request.POST.get('note','')[:2000]);messages.success(request,'سفارش به‌روزرسانی شد.')
    except BusinessError as e: messages.error(request,str(e))
    return redirect('staff')

def blog(request): return render(request,'blog.html',{'page':Paginator(Post.objects.filter(published=True),9).get_page(request.GET.get('page')),'title':'وبلاگ دان پنل','description':'راهنماهای کاربردی مدیریت کانال، محتوای بهتر و استفاده از خدمات روبیکا، ایتا و بله.'})

def post(request,slug):
    p=get_object_or_404(Post,published=True,slug=slug)
    return render(request,'post.html',{'post':p,'title':p.title,'description':p.summary})

def legal(request,page):
    pages={'terms':('قوانین استفاده','پیش از سفارش، توضیحات، تعداد و مقصد را بررسی کنید. زمان انجام هر خدمت به شرایط همان محصول وابسته است. تضمینی درباره نتیجه تجاری یا رشد مخاطبان داده نمی‌شود. خدمات برای استفاده قانونی ارائه می‌شوند. در صورت لغو سفارش توسط پشتیبانی، وجه به کیف پول برمی‌گردد. برای اختلاف در پرداخت یا سفارش، از تیکت استفاده کنید.'),'privacy':('حریم خصوصی','شماره موبایل برای احراز هویت و اتصال حساب استفاده می‌شود. اطلاعات سفارش و پرداخت برای ارائه خدمات نگهداری می‌شوند. رمز یک‌بارمصرف سایت به‌صورت هش ذخیره می‌شود. دسترسی کارکنان براساس نقش محدود است. درخواست بررسی، اصلاح یا حذف اطلاعات را از طریق تیکت ثبت کنید.'),'about':('درباره دان پنل','دان پنل، فروشگاه اشتراک‌های هوش مصنوعی و خدمات روبیکا، ایتا و بله است. محصولات، موجودی و وضعیت سفارش‌ها در یک حساب مدیریت می‌شوند. پیش از ثبت سفارش، راهنمای محصول را بخوانید و در صورت نیاز با پشتیبانی تیکتی در ارتباط باشید.')}
    if page not in pages: return HttpResponse(status=404)
    title,body=pages[page];return render(request,'legal.html',{'title':title,'body':body})

def robots(request): return HttpResponse('User-agent: *\nDisallow: /manage/\nDisallow: /account/\nDisallow: /staff/\nDisallow: /login/\nDisallow: /payment/\nSitemap: https://dawnpanel.ir/sitemap.xml\n',content_type='text/plain')

def sitemap(request):
    from xml.sax.saxutils import escape
    from portal.templatetags.storefront import product_image
    entries=[(path,None,None) for path in ['/','/ai/','/services/','/blog/','/about/','/terms/','/privacy/']]
    entries += [(product.get_absolute_url(),None,product_image(product)) for product in with_product_images(public_products())]
    entries += [(post.get_absolute_url(),post.updated_at.date().isoformat(),None) for post in Post.objects.filter(published=True)]
    body=[]
    for path,modified,image in entries:
        entry='<url><loc>https://dawnpanel.ir'+escape(quote(path,safe='/'))+'</loc>'
        if modified:entry+='<lastmod>'+modified+'</lastmod>'
        if image:entry+='<image:image><image:loc>https://dawnpanel.ir'+escape(image)+'</image:loc></image:image>'
        body.append(entry+'</url>')
    data='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'+''.join(body)+'</urlset>'
    return HttpResponse(data,content_type='application/xml')

def health(request):
    with connection.cursor() as c: c.execute('SELECT 1');c.fetchone()
    return JsonResponse({'status':'ok'})


@login_required
def gift(request):
    form=GiftForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            if not rate_limit('gift:'+str(request.user.pk),8,900): raise BusinessError('کمی بعد دوباره تلاش کنید.')
            amount=redeem_gift(request.user.account,form.cleaned_data['code'])
            messages.success(request,f'کد هدیه مصرف شد؛ {amount:,} تومان به کیف پول اضافه شد.')
            return redirect('dashboard')
        except BusinessError as e: form.add_error(None,str(e))
    return render(request,'simple_form.html',{'form':form,'title':'کد هدیه','subtitle':'کدهای هدیه ربات و سایت از یک موجودی استفاده می‌کنند.','button':'ثبت کد هدیه'})

@login_required
def referrals(request):
    wallet=LegacyUser.objects.get(pk=request.user.account.legacy_id)
    return render(request,'referrals.html',{'wallet':wallet,'title':'دعوت دوستان و پورسانت'})
