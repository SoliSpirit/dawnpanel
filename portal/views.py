import secrets,uuid
from datetime import timedelta
from django.utils.encoding import iri_to_uri
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.conf import settings
from django.shortcuts import render,redirect,get_object_or_404
from django.http import Http404,HttpResponse,HttpResponseForbidden,JsonResponse
from django.contrib.auth import login,logout
from django.contrib.auth.decorators import login_required,permission_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import F,Q,Sum
from django.db import transaction
from django.views.decorators.http import require_POST,require_GET,require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.utils import timezone
from .models import *
from .forms import *
from .services import *
from .store_catalog import families, category_tiles, filter_families, TAXONOMY, MESSAGING
from .catalog_pages import SECTION_COPY, section_url
from .site_issues import report_dependency

ORDER_DRAFT_AGE = timedelta(minutes=20)

@never_cache
@require_http_methods(['GET','HEAD'])
def exchange_board(request):
    from .exchange_rates import SOURCES, currency_rates, RateError, source_link
    rows=[]
    now=timezone.now()
    for currency in Currency.objects.filter(is_active=True).exclude(code='TOMAN').select_related('fx').order_by('code'):
        policy=getattr(currency,'fx',None)
        src=policy.source if policy else 'manual'
        try:rates=currency_rates(currency,now=now)
        except RateError:rates=None
        rows.append({'code':currency.code,'name':currency.name,'rates':rates,
                     'source':SOURCES[src][0] if src in SOURCES else 'نرخ دستی فروشگاه',
                     'url':source_link(src,currency.code),
                     'at':policy.published_at if src in SOURCES else currency.updated_at})
    return render(request,'exchange_rates.html',{'rows':rows,'title':'نرخ خرید و فروش ارز | دان‌پنل',
        'description':'نرخ خرید از مشتری و نرخ فروش به مشتری به تومان، با مرجع و زمان ثبت نرخ.'})


def local_return_path(value):
    # Only local navigation; never use an arbitrary URL as a login redirect.
    if (isinstance(value,str) and len(value)<=1500 and value.startswith('/')
            and not value.startswith('//') and '\\' not in value
            and url_has_allowed_host_and_scheme(value,allowed_hosts=set())):
        return value
    return ''

def home(request):
    items=families()
    subscriptions=[f for f in items if f.section not in MESSAGING]
    # Lead with familiar products and include more than a single category.
    picks=[]
    for section in ('ai','music','design','business','development','education'):
        match=next((f for f in reversed(subscriptions) if f.section==section),None)
        if match: picks.append(match)
    return render(request,'home.html',{'families':picks,
        'categories':category_tiles(items),'posts':Post.objects.filter(published=True)[:3],
        'title':'دان‌پنل | خرید اشتراک هوش مصنوعی و خدمات روبیکا، ایتا و بله',
        'description':'در دان‌پنل پلن‌های اشتراک هوش مصنوعی و ابزارهای دیجیتال را مقایسه کنید یا خدمات کانال روبیکا، ایتا و بله را با قیمت مشخص و کد پیگیری سفارش دهید.',
        'google_verification':settings.GOOGLE_SITE_VERIFICATION})

@require_GET
def contact(request):
    return render(request,'contact.html',{'title':'ارتباط با ما | پشتیبانی دان‌پنل',
        'description':'راه‌های ارتباط با دان‌پنل: تماس تلفنی، ایمیل، گفتگوی آنلاین و پیگیری سفارش با تیکت.',
        'contact_phone':settings.CONTACT_PHONE,'contact_tel':'+98'+settings.CONTACT_PHONE.removeprefix('0'),
        'contact_email':settings.CONTACT_EMAIL})

def ai_catalog(request):
    return catalog(request,section_key='ai')

@require_http_methods(['GET','HEAD'])
def catalog_section(request,section_key):
    if section_key not in SECTION_COPY: raise Http404
    if section_key=='ai':
        return redirect(reverse('ai_catalog',query=request.GET),permanent=True)
    return catalog(request,section_key=section_key)

@require_http_methods(['GET','HEAD'])
def catalog(request,section_key=None):
    if not section_key and (request.GET.get('platform')=='telegram' or request.GET.get('section')=='telegram'):
        return redirect(reverse('catalog')+'?collection=messaging')
    old_section=request.GET.get('section','')
    if not section_key and old_section in SECTION_COPY and set(request.GET)<= {'section','page'}:
        params=request.GET.copy();del params['section']
        return redirect(section_url(old_section)+('?' + params.urlencode() if params else ''),permanent=True)
    items=families()
    platform='' if section_key else request.GET.get('platform','')
    if platform not in ['rubika','eitaa','bale','ai','telegram','other']: platform=''
    section=section_key or old_section
    if section not in {row[0] for row in TAXONOMY}: section=''
    collection=request.GET.get('collection','')
    if collection not in {'subscriptions','messaging'} or section or platform: collection=''
    category=request.GET.get('category','')
    q=request.GET.get('q','')[:100].strip()
    scope=filter_families(items,section=section,platform=platform,collection=collection)
    category_ids={p.category_id for f in scope for p in f.search_plans if not platform or p.platform==platform}
    if category not in {str(pk) for pk in category_ids}: category=''
    filtered=filter_families(scope,platform=platform,category=category,query=q)
    sort=request.GET.get('sort','')
    if sort not in {'price','-price'}: sort=''
    if sort in {'price','-price'}:
        filtered.sort(key=lambda f:(f.minimum is None, (f.minimum or 0)*(-1 if sort=='-price' else 1)))
    label=next((row[1] for row in TAXONOMY if row[0]==(section or platform)),
               {'subscriptions':'اشتراک‌ها و ابزارها','messaging':'خدمات پیام‌رسان‌ها'}.get(collection,'همه محصولات'))
    paginator=Paginator(filtered,12)
    if section_key and request.GET.get('page'):
        from django.core.paginator import InvalidPage
        try:page=paginator.page(request.GET['page'])
        except InvalidPage: raise Http404 from None
    else:page=paginator.get_page(request.GET.get('page'))
    heading,description=SECTION_COPY.get(section_key,('فروشگاه دان‌پنل','انتخاب اشتراک و خدمات دیجیتال بر اساس دسته‌بندی؛ مقایسه پلن‌ها و خرید از دان‌پنل.'))
    return render(request,'catalog.html',{'page':page,'platform':platform,'q':q,'category':category,
        'section':section,'sort':sort,'categories':category_tiles(scope if collection else items),'section_label':label,
        'collection':collection,'collection_tab':collection or ('messaging' if (section or platform) in MESSAGING else 'subscriptions' if section or platform else ''),
        'catalog_categories':Category.objects.filter(pk__in=category_ids),
        'landing':section_key,'catalog_heading':heading,'landing_empty':bool(section_key and not scope),
        'catalog_path':section_url(section) if section in SECTION_COPY else reverse('catalog'),
        'title':(heading if section_key else label)+' | فروشگاه دان‌پنل','description':description})

@require_http_methods(['GET','HEAD','POST'])
@sensitive_post_parameters('target')
def product(request,pk,slug=None):
    items=families()
    family,p=next(((f,plan) for f in items for plan in f.plans
                   if plan.pk==pk or any(alias.pk==pk for alias in plan.web_aliases)),(None,None))
    if p is None: raise Http404
    if request.method in ('GET','HEAD') and p.pk!=pk:
        return redirect(p)  # A preference between eligible SKUs is not permanent.
    if request.method in ('GET','HEAD') and iri_to_uri(request.path)!=p.get_absolute_url():
        return redirect(p,permanent=True)
    draft=request.session.get('order_draft')
    initial={'quantity':p.min_order}
    restored=False
    if draft:
        if timezone.now().timestamp()-draft['at']>ORDER_DRAFT_AGE.total_seconds():
            request.session.pop('order_draft',None)
        elif (request.method=='GET' and request.user.is_authenticated and
              draft['product_id'] in {p.pk, *(alias.pk for alias in p.web_aliases)}):
            initial['quantity']=draft['quantity']
            restored=True
    form=OrderForm(request.POST if request.method=='POST' else None,initial=initial)
    if p.min_order==p.max_order:
        from django.forms import HiddenInput
        form.fields['quantity'].widget=HiddenInput()
    else:
        form.fields['quantity'].widget.attrs.update(min=p.min_order,max=min(p.max_order or 100000000,100000000))
    if p.platform in ('ai','other'):
        form.fields['target'].label='ایمیل یا توضیحات سفارش'
        form.fields['target'].help_text='اطلاعات لازم برای تحویل، مطابق توضیحات محصول.'
        form.fields['target'].widget.attrs['placeholder']='ایمیل یا اطلاعات سفارش'
    pricing=quote=None
    try:
        pricing=pricing_for(p)
        quote=pricing.quote(p.min_order)
        if restored:
            quote=pricing.quote(initial['quantity'])
    except BusinessError: pass
    if request.method=='POST' and form.is_valid():
        try:
            if not pricing: raise BusinessError('قیمت محصول نیاز به بررسی دارد.')
            quote=pricing.quote(form.cleaned_data['quantity'])
            if p.need_link and not form.cleaned_data['target'].strip(): raise BusinessError('اطلاعات مقصد را وارد کنید.')
            selection={'product_id':p.pk,'quantity':form.cleaned_data['quantity'],'target':form.cleaned_data['target']}
            if not request.user.is_authenticated:
                # Keep the selected plan and quantity, not the guest's delivery data.
                request.session['order_draft']={'product_id':p.pk,'quantity':selection['quantity'],
                                               'at':timezone.now().timestamp()}
                request.session['login_return']=p.get_absolute_url()
                return redirect('login')
            request.session.pop('order_draft',None)
            key=str(uuid.uuid4()); pending={**selection,'quoted_total':quote.total,'quoted_breakdown':quote.breakdown,'key':key}
            request.session['checkout']=pending
            response=render(request,'review.html',{'product':p,'pending':pending,'total':quote.total,'quote':quote,'title':'تایید سفارش','private_page':True})
            response['Cache-Control']='private, no-store'
            return response
        except BusinessError as e: form.add_error(None,str(e))
    response=render(request,'product.html',{'product':p,'family':family,
        'related':[f for f in items if family and f.section==family.section and f is not family][:4],
        'form':form,'pricing':pricing,'quote':quote,'display_total':quote.total if quote else None,'restored':restored,
        'title':p.name+' | دان‌پنل','description':p.seo_description or (p.name+'؛ مشاهده قیمت، شرایط سفارش و پشتیبانی در دان پنل.')[:160]})
    if restored or request.method=='POST': response['Cache-Control']='private, no-store'
    return response


@require_GET
def product_cover(request,pk):
    from .product_art import artwork_key, gallery_jpeg
    product=get_object_or_404(public_products().only('name','platform'),pk=pk)
    response=HttpResponse(gallery_jpeg(artwork_key(pk,product.platform,product.name)),content_type='image/jpeg')
    response['Cache-Control']='public, max-age=300'
    return response

@require_POST
@login_required
def checkout(request):
    pending=request.session.get('checkout')
    expected=pending.get('key') if pending else None
    if not expected or not secrets.compare_digest(request.POST.get('key','').encode(),expected.encode()):
        messages.error(request,'درخواست منقضی شده است. سفارش را دوباره بررسی کنید.');return redirect('catalog')
    try:
        order=place_order(request.user.account,**pending)
        request.session.pop('checkout',None)
        messages.success(request,'سفارش ثبت شد. کد پیگیری: '+order.tracking_code)
        return redirect('order',pk=order.pk)
    except (BusinessError,Account.DoesNotExist) as e:
        messages.error(request,str(e));return redirect('product',pk=pending['product_id'])

@never_cache
@require_http_methods(['GET','HEAD','POST'])
def sign_in(request):
    destination=local_return_path(request.GET.get('next'))
    if request.user.is_authenticated: return redirect(destination or 'dashboard')
    if destination: request.session['login_return']=destination
    if not request.session.session_key: request.session.create()
    form=PhoneForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            otp=request_otp(form.cleaned_data['phone'],request.session.session_key,request.META.get('REMOTE_ADDR',''))
            request.session['otp_id']=str(otp.pk);request.session['otp_phone']=otp.phone
            return redirect('verify')
        except BusinessError as e:
            report_dependency(request,e);form.add_error(None,str(e))
    return render(request,'auth.html',{'form':form,'title':'ورود یا ثبت‌نام','subtitle':'با شماره موبایل خود وارد شوید. رمز یک‌بارمصرف برای شما پیامک می‌شود.','button':'دریافت کد ورود',
        'returning_to_order':bool(request.session.get('order_draft'))})

@require_GET
def campaign(request,code):
    link=get_object_or_404(Campaign,code=code,active=True)
    Campaign.objects.filter(pk=link.pk).update(clicks=F('clicks')+1)
    request.session['campaign']={'id':link.pk,'at':int(timezone.now().timestamp())}
    response=redirect('catalog')
    response['Cache-Control']='private, no-store'
    response['X-Robots-Tag']='noindex, nofollow'
    return response

@never_cache
@sensitive_post_parameters('code')
@require_http_methods(['GET','HEAD','POST'])
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
                    attribution=request.session.pop('campaign',None)
                    campaign_id=attribution['id'] if attribution and 0<=timezone.now().timestamp()-attribution['at']<=30*86400 else None
                    user=login_account(phone,campaign_id=campaign_id) if campaign_id else login_account(phone)
                    login(request,user,backend='django.contrib.auth.backends.ModelBackend')
                    Audit.objects.create(actor=user,action='account.login')
                    # Keep a fixed deadline even when checkout or chat updates the session.
                    request.session.set_expiry(timezone.now()+timedelta(seconds=settings.SESSION_COOKIE_AGE))
                    request.session.pop('otp_id',None);request.session.pop('otp_phone',None)
                    destination=local_return_path(request.session.pop('login_return',''))
                    return redirect(destination or ('staff' if user.is_staff else 'dashboard'))
                except BusinessError as e: form.add_error(None,str(e))
            else: form.add_error(None,'کد اشتباه، منقضی یا مصرف شده است. پس از پنج تلاش، کد جدید بگیرید.')
    return render(request,'auth.html',{'form':form,'title':'تایید شماره موبایل','subtitle':'کد پیامک‌شده را وارد کنید. اعتبار کد پنج دقیقه است.','button':'تایید و ورود','verify':True,
        'returning_to_order':bool(request.session.get('order_draft'))})

@require_POST
def sign_out(request):
    if request.user.is_authenticated:Audit.objects.create(actor=request.user,action='account.logout')
    logout(request)
    return redirect('home')

@login_required
def dashboard(request):
    a=request.user.account;wallet=get_object_or_404(LegacyUser,pk=a.legacy_id)
    orders=Order.objects.filter(user_id=a.legacy_id)
    return render(request,'dashboard.html',{'wallet':wallet,'orders':orders[:5],'transactions':Ledger.objects.filter(user_id=a.legacy_id)[:6],'order_count':orders.count(),'pending_count':orders.filter(status__in=['pending','confirmed','approved','processing']).count(),'ticket_count':Ticket.objects.filter(user=request.user).exclude(status='closed').count(),'rank':MemberRank.objects.filter(min_spending__lte=wallet.total_purchases).last(),'title':'حساب کاربری'})

@login_required
@sensitive_post_parameters('national_code','birth_date')
@require_http_methods(['GET','POST'])
def profile(request):
    from .profile import ProfileForm,profile_cipher
    import jdatetime
    account=request.user.account
    initial={name:getattr(request.user,name) for name in ['first_name','last_name','email']}
    if initial['first_name']=='کاربر دان پنل':initial['first_name']=''
    initial.update({'province':account.province,'city':account.city,'birth_date':jdatetime.date.fromgregorian(date=account.birth_date).strftime('%Y/%m/%d') if account.birth_date else ''})
    form=ProfileForm(request.POST if request.method=='POST' else None,initial=initial)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            account=Account.objects.select_for_update().get(user=request.user)
            for field in ['first_name','last_name','email']:setattr(request.user,field,form.cleaned_data[field])
            request.user.save(update_fields=['first_name','last_name','email'])
            for field in ['birth_date','province','city']:setattr(account,field,form.cleaned_data[field])
            if form.cleaned_data['clear_national_code']:account.national_code_encrypted=''
            elif form.cleaned_data['national_code']:account.national_code_encrypted=profile_cipher().encrypt(form.cleaned_data['national_code'].encode()).decode()
            account.save(update_fields=['national_code_encrypted','birth_date','province','city'])
            name=request.user.get_full_name().strip()
            LegacyUser.objects.filter(pk=account.legacy_id).update(full_name=name[:255] or 'کاربر سایت')
            Audit.objects.create(actor=request.user,action='profile.update',object_ref=str(account.pk),details={'fields':form.changed_data})
        messages.success(request,'اطلاعات پروفایل ذخیره شد.')
        return redirect('profile')
    return render(request,'profile.html',{'form':form,'has_national_code':bool(account.national_code_encrypted),'title':'اطلاعات پروفایل | دان‌پنل'})

@login_required
def orders(request):
    rows=Order.objects.filter(user_id=request.user.account.legacy_id)
    return render(request,'orders.html',{'page':Paginator(rows,20).get_page(request.GET.get('page')),'title':'سفارش‌های من'})

@login_required
def order_detail(request,pk):
    order=get_object_or_404(Order.objects.select_related('amounts'),pk=pk,user_id=request.user.account.legacy_id)
    return render(request,'order.html',{'order':order,'title':'سفارش '+order.tracking_code})

@login_required
def charge(request):
    from .crypto_topups import method_open
    from .exchange_rates import currency_rates,RateError
    form=ChargeForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            if not rate_limit('payment:'+str(request.user.pk),5,300): raise BusinessError('کمی بعد دوباره تلاش کنید.')
            return redirect(start_payment(request.user.account,form.cleaned_data['amount']))
        except BusinessError as e:
            report_dependency(request,e);form.add_error(None,str(e))
    star=Currency.objects.filter(code='STAR',type='telegram',is_active=True).select_related('fx').first()
    try:star_buy=currency_rates(star).buy if star and method_open('stars') else None
    except RateError:star_buy=None
    return render(request,'charge.html',{'form':form,'title':'شارژ کیف پول','crypto_open':method_open('crypto'),'star_buy':star_buy})

@require_GET
def payment_callback(request):
    amount=None;ref=None;error=None
    try:
        if request.GET.get('Status')!='OK': raise BusinessError('پرداخت لغو شده است یا هنوز تایید نشده است.')
        amount,ref=verify_payment(request.GET.get('Authority'))
    except BusinessError as e:
        report_dependency(request,e);error=str(e)
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
def ticket_detail(request,pk,*,site=None):
    staff=request.user.is_staff and request.user.has_perm('portal.change_ticket')
    route='admin:desk_ticket' if site else 'ticket'
    rows=Ticket.objects.all() if staff else Ticket.objects.filter(user=request.user)
    ticket=get_object_or_404(rows,pk=pk)
    form=ReplyForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if ticket.status=='closed': form.add_error(None,'این تیکت بسته شده است.')
        elif not rate_limit('reply:'+str(request.user.pk),30,300): form.add_error(None,'کمی بعد تلاش کنید.')
        else:
            with transaction.atomic():
                ticket=get_object_or_404(rows.select_for_update(),pk=pk)
                if ticket.status=='closed':
                    messages.error(request,'این تیکت بسته شده است.')
                    return redirect(route,pk=pk)
                TicketMessage.objects.create(ticket=ticket,author=request.user,body=form.cleaned_data['body'])
                ticket.status='answered' if staff else 'open';ticket.save()
                if staff: Audit.objects.create(actor=request.user,action='ticket.reply',object_ref=str(pk))
            return redirect(route,pk=pk)
    from .crypto_topups import can_settle,SettleForm,current_buy
    from .exchange_rates import RateError
    entry=getattr(ticket,'crypto_topup',None)
    settle_form=buy=None
    if entry and not entry.credited and ticket.status!='closed' and can_settle(request.user):
        try:
            buy=current_buy(entry.code)
            settle_form=SettleForm(initial={'units':format(entry.units.normalize(),'f'),'expected':buy})
        except RateError:pass
    return render(request,'admin/portal/desk_ticket.html' if site else 'ticket.html',{**(site.each_context(request) if site else {}),
        'close_route':'admin:desk_ticket_close' if site else 'close_ticket','settle_route':'admin:desk_ticket_settle' if site else 'settle_crypto',
        'ticket':ticket,'thread':ticket.messages.select_related('author'),'form':form,'title':ticket.subject,
        'staff_reply':staff,'topup':entry,'settle_form':settle_form,'settle_rate':buy})

@require_POST
@login_required
@transaction.atomic
def close_ticket(request,pk,*,return_route='ticket'):
    ticket=get_object_or_404(Ticket.objects.select_for_update(),pk=pk)
    if ticket.user_id!=request.user.pk and not (request.user.is_staff and request.user.has_perm('portal.change_ticket')): return HttpResponseForbidden()
    if ticket.status!='closed':
        ticket.status='closed';ticket.save()
        if request.user.is_staff and request.user.has_perm('portal.change_ticket'):
            Audit.objects.create(actor=request.user,action='ticket.close',object_ref=str(pk))
    return redirect(return_route,pk=pk)

@login_required
def staff(request):
    if not request.user.is_staff: return HttpResponseForbidden()
    if not any(request.user.has_perm('portal.'+p) for p in ['change_order','change_ticket']):
        return redirect('admin:chat_desk' if request.user.has_perm('portal.change_chatconversation') else 'admin:index')
    return redirect('admin:requests_desk')

@require_POST
@permission_required('portal.change_order',raise_exception=True)
def staff_order(request,pk):
    if not request.user.is_staff:return HttpResponseForbidden()
    try: change_order(request.user,pk,request.POST.get('status'),request.POST.get('note','')[:2000]);messages.success(request,'سفارش به‌روزرسانی شد.')
    except BusinessError as e: messages.error(request,str(e))
    return redirect('admin:requests_desk')

def blog(request): return render(request,'blog.html',{'page':Paginator(Post.objects.filter(published=True),9).get_page(request.GET.get('page')),'title':'وبلاگ دان پنل','description':'راهنماهای کاربردی مدیریت کانال، محتوای بهتر و استفاده از خدمات روبیکا، ایتا و بله.'})

def post(request,slug):
    p=get_object_or_404(Post,published=True,slug=slug)
    return render(request,'post.html',{'post':p,'title':p.title,'description':p.summary})

def legal(request,page):
    pages={'terms':('قوانین استفاده','پیش از سفارش، توضیحات، تعداد و مقصد را بررسی کنید. زمان انجام هر خدمت به شرایط همان محصول وابسته است. تضمینی درباره نتیجه تجاری یا رشد مخاطبان داده نمی‌شود. خدمات برای استفاده قانونی ارائه می‌شوند. در صورت لغو سفارش توسط پشتیبانی، وجه به کیف پول برمی‌گردد. برای اختلاف در پرداخت یا سفارش، از تیکت استفاده کنید.'),'privacy':('حریم خصوصی','شماره موبایل برای ورود و اتصال حساب استفاده می‌شود. نام، نام خانوادگی، ایمیل، تاریخ تولد، استان، شهر و کد ملی فقط در صورت تکمیل اختیاری پروفایل نگهداری می‌شوند. کد ملی رمز‌شده ذخیره می‌شود و ثبت آن به معنی احراز هویت رسمی نیست. می‌توانید کد ملی را از پروفایل حذف کنید. اطلاعات سفارش و پرداخت برای ارائه خدمات نگهداری می‌شوند. رمز یک‌بارمصرف سایت به‌صورت هش ذخیره می‌شود. دسترسی کارکنان براساس نقش محدود است. درخواست بررسی، اصلاح یا حذف اطلاعات را از طریق تیکت ثبت کنید.'),'about':('درباره دان پنل','دان پنل، فروشگاه اشتراک‌های هوش مصنوعی و خدمات روبیکا، ایتا و بله است. محصولات، موجودی و وضعیت سفارش‌ها در یک حساب مدیریت می‌شوند. پیش از ثبت سفارش، راهنمای محصول را بخوانید و در صورت نیاز با پشتیبانی تیکتی در ارتباط باشید.')}
    if page not in pages: return HttpResponse(status=404)
    title,body=pages[page];return render(request,'legal.html',{'title':title,'body':body})

def robots(request): return HttpResponse('User-agent: *\nDisallow: /admin\nDisallow: /manage/\nDisallow: /account/\nDisallow: /staff/\nDisallow: /login/\nDisallow: /logout/\nDisallow: /support/chat/\nDisallow: /payment/\nDisallow: /healthz/\nSitemap: https://dawnpanel.ir/sitemap.xml\n',content_type='text/plain')

def sitemap(request):
    from xml.sax.saxutils import escape
    from portal.templatetags.storefront import product_image,post_image
    items=families()
    entries=[(path,None,None) for path in ['/','/services/','/rates/','/blog/','/contact/','/faq/','/about/','/terms/','/privacy/']]
    entries += [(section_url(key),None,None) for key in sorted({f.section for f in items} & SECTION_COPY.keys())]
    entries += [(p.get_absolute_url(),None,product_image(p)) for family in items for p in family.plans]
    entries += [(post.get_absolute_url(),post.updated_at.date().isoformat(),post_image(post)) for post in Post.objects.filter(published=True)]
    body=[]
    for path,modified,image in entries:
        entry='<url><loc>https://dawnpanel.ir'+escape(iri_to_uri(path))+'</loc>'
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
