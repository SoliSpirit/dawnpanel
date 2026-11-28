from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count,Max,Q
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path,reverse
from django.utils import timezone

from .models import Audit,ChatEmailDelivery,NoticePreference,OrderDelivery,SiteIssue
from .notice_topics import DEFAULT_TOPICS,TOPICS,recipients,mail_topics


class TopicForm(forms.Form):
    recipient=forms.IntegerField(widget=forms.HiddenInput,min_value=1,max_value=2**52-1)
    revision=forms.IntegerField(widget=forms.HiddenInput,min_value=0)
    topics=forms.MultipleChoiceField(label='پیام‌های دریافتی',choices=tuple(TOPICS.items()),required=False,
                                     widget=forms.CheckboxSelectMultiple)


class ChatEmailForm(forms.Form):
    recipient=forms.IntegerField(widget=forms.HiddenInput,min_value=1,max_value=2**52-1)
    revision=forms.IntegerField(widget=forms.HiddenInput,min_value=0)
    chat_email=forms.EmailField(label='آدرس Gmail یا ایمیل مقصد',required=False,max_length=254,widget=forms.EmailInput(attrs={'dir':'ltr','autocomplete':'off'}))
    chat_email_enabled=forms.BooleanField(label='ارسال ایمیل برای پیام جدید چت',required=False)
    def clean(self):
        d=super().clean()
        if d.get('chat_email_enabled') and not d.get('chat_email'):self.add_error('chat_email','ایمیل مقصد را وارد کنید.')
        return d


@admin.register(NoticePreference)
class PreferenceAdmin(admin.ModelAdmin):
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

    def get_urls(self):
        return [path('',self.admin_site.admin_view(self.changelist_view),name='portal_noticepreference_changelist')]

    def changelist_view(self,request,extra_context=None):
        if not self.has_view_or_change_permission(request):raise PermissionDenied
        if request.method not in ('GET','HEAD','POST'):return HttpResponseNotAllowed(['GET','HEAD','POST'])
        ids=recipients();edit=self.has_change_permission(request)
        can_email=edit and request.user.has_perm('portal.manage_chat_email')
        if request.method=='POST':
            if not edit:raise PermissionDenied
            if 'matrix' in request.POST:
                form=TopicForm(request.POST)
                if not form.is_valid() or len(request.POST.getlist('recipient'))!=1 or form.cleaned_data['recipient'] not in ids:raise PermissionDenied
                data=form.cleaned_data;tg=set(data['topics'])
                if not can_email and ('email_topics' in request.POST or 'chat_email' in request.POST):raise PermissionDenied
                emails=set(request.POST.getlist('email_topics'))
                if emails-TOPICS.keys():raise PermissionDenied
                try:
                    address=forms.EmailField(required=bool(emails),max_length=254).clean(request.POST.get('chat_email','')) if can_email else ''
                except forms.ValidationError:
                    self.message_user(request,'برای اعلان ایمیلی یک آدرس معتبر وارد کنید. تغییرات ذخیره نشد.',messages.ERROR)
                    return HttpResponseRedirect(request.path)
                with transaction.atomic():
                    row,_=NoticePreference.objects.select_for_update().get_or_create(pk=data['recipient'],defaults={'enabled':sorted(DEFAULT_TOPICS)})
                    if row.revision!=data['revision']:
                        self.message_user(request,'تنظیمات تغییر کرده؛ دوباره بررسی کنید.',messages.WARNING)
                        return HttpResponseRedirect(request.path)
                    removed=set(row.enabled)-tg
                    OrderDelivery.objects.filter(recipient=row.pk,state__in=('pending','stopped')).filter(
                        Q(operation__topic__in=removed)|Q(event__channel__in=[c for c,t in [('web','web_order'),('telegram','bot_order')] if t in removed])).update(state='muted',last_error='muted')
                    if can_email:
                        jobs=ChatEmailDelivery.objects.filter(recipient=row.pk,state__in=('pending','stopped'))
                        if address==row.chat_email:jobs=jobs.exclude(topic__in=emails)
                        jobs.update(state='muted',lease=None,last_error='changed')
                        row.chat_email=address;row.chat_email_enabled='web_chat' in emails;row.email_topics=sorted(emails-{'web_chat'})
                    row.enabled=sorted(tg);row.revision+=1;row.save()
                    Audit.objects.create(actor=request.user,action='notice.settings',object_ref=str(row.pk))
                self.message_user(request,'انتخاب‌های این مدیر ذخیره شد.');return HttpResponseRedirect(request.path)
            if 'email_settings' in request.POST:
                if not can_email:raise PermissionDenied
                if len(request.POST.getlist('recipient'))!=1:raise PermissionDenied
                form=ChatEmailForm(request.POST)
                if not form.is_valid():
                    self.message_user(request,'آدرس ایمیل و تنظیمات فرم را بررسی کنید.',messages.ERROR)
                elif form.cleaned_data['recipient'] not in ids:raise PermissionDenied
                else:
                    d=form.cleaned_data
                    with transaction.atomic():
                        row,_=NoticePreference.objects.select_for_update().get_or_create(pk=d['recipient'],defaults={'enabled':sorted(DEFAULT_TOPICS)})
                        if row.revision!=d['revision']:self.message_user(request,'صفحه قدیمی است؛ تنظیمات را دوباره بررسی کنید.',messages.WARNING)
                        elif (row.chat_email,row.chat_email_enabled)!=(d['chat_email'],d['chat_email_enabled']):
                            row.chat_email,row.chat_email_enabled=d['chat_email'],d['chat_email_enabled'];row.revision+=1;row.save()
                            ChatEmailDelivery.objects.filter(recipient=row.pk,state__in=('pending','stopped')).update(state='muted',last_error='changed')
                            Audit.objects.create(actor=request.user,action='notice.email',object_ref=str(row.pk))
                            self.message_user(request,'تنظیمات ایمیل چت ذخیره شد.')
                return HttpResponseRedirect(reverse('admin:portal_noticepreference_changelist'))
            form=TopicForm(request.POST)
            if not form.is_valid() or len(request.POST.getlist('recipient'))!=1 or form.cleaned_data['recipient'] not in ids:
                raise PermissionDenied
            data=form.cleaned_data
            with transaction.atomic():
                row,_=NoticePreference.objects.select_for_update().get_or_create(recipient=data['recipient'],defaults={'enabled':sorted(DEFAULT_TOPICS)})
                if row.revision!=data['revision']:
                    self.message_user(request,'تنظیمات از زمان باز شدن صفحه تغییر کرده است. دوباره بررسی کنید.',messages.WARNING)
                elif set(row.enabled)!=set(data['topics']):
                    removed=set(row.enabled)-set(data['topics'])
                    row.enabled=sorted(set(data['topics']));row.revision+=1;row.save()
                    if removed:
                        channels=[c for c,t in [('web','web_order'),('telegram','bot_order')] if t in removed]
                        OrderDelivery.objects.filter(recipient=row.pk,state__in=('pending','stopped')).filter(
                            Q(operation__topic__in=removed)|Q(event__channel__in=channels)).update(state='muted',last_error='muted',lease=None)
                    Audit.objects.create(actor=request.user,action='notice.settings',object_ref=str(row.pk))
                    self.message_user(request,'تنظیمات پیام‌های این مدیر ذخیره شد.')
                else:self.message_user(request,'تنظیمات این مدیر تغییری نکرد.')
            return HttpResponseRedirect(reverse('admin:portal_noticepreference_changelist'))
        stored=NoticePreference.objects.in_bulk(ids);cards=[]
        stats={r['recipient']:r for r in OrderDelivery.objects.filter(recipient__in=ids).values('recipient').annotate(
            waiting=Count('pk',filter=Q(state__in=('pending','sending'))),
            stopped=Count('pk',filter=Q(state='stopped')),last_sent=Max('sent_at'))}
        email_stats={r['recipient']:r for r in ChatEmailDelivery.objects.filter(recipient__in=ids).values('recipient').annotate(
            waiting=Count('pk',filter=Q(state__in=('pending','sending'))),stopped=Count('pk',filter=Q(state='stopped')),
            accepted=Max('sent_at'))} if can_email else {}
        for i in ids:
            row=stored.get(i);enabled=row.enabled if row else DEFAULT_TOPICS
            groups=[('فروش و قیمت',('web_order','bot_order','order_status','catalog','price_review','finance')),
                    ('پشتیبانی',('web_chat','support','incoming_ticket','incoming_receipt')),
                    ('مدیریت و سلامت',('management','staff_session','site_error','lottery_warning'))]
            selected=mail_topics(row) if row and can_email else set()
            cards.append({'id':i,'revision':row.revision if row else 0,'address':row.chat_email if row and can_email else '',
                'groups':[(title,[(key,TOPICS[key],key in enabled,key in selected) for key in keys]) for title,keys in groups],
                'telegram':stats.get(i,{}),'mail':email_stats.get(i,{})})
        return render(request,'admin/portal/notice_preferences.html',{**self.admin_site.each_context(request),
            'opts':self.opts,'title':'اعلان‌های تلگرام و ایمیل','cards':cards,'editable':edit,'can_email':can_email})


@admin.register(SiteIssue)
class IssueAdmin(admin.ModelAdmin):
    change_list_template='admin/portal/issues_list.html'
    list_display=['kind','route','status_code','method','occurrences','last_seen','resolved']
    list_display_links=['kind','route']
    list_filter=['resolved','status_code','method','last_seen'];search_fields=['kind','route','trace','release']
    readonly_fields=['kind','status_code','method','route','hint','trace','release','occurrences','first_seen','last_seen','resolved_at']
    fields=[*readonly_fields,'resolved'];actions=['resolve_selected','reopen_selected'];list_per_page=40
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

    @transaction.atomic
    def mark(self,request,queryset,resolved):
        if not self.has_change_permission(request):raise PermissionDenied
        ids=list(queryset.select_for_update().exclude(resolved=resolved).order_by('pk').values_list('pk',flat=True))
        if ids:
            fields={'resolved':resolved}
            if resolved:fields['resolved_at']=timezone.now()
            SiteIssue.objects.filter(pk__in=ids).update(**fields)
            Audit.objects.create(actor=request.user,action='issue.resolve' if resolved else 'issue.reopen',
                                 object_ref=str(ids[0]) if len(ids)==1 else '',details={'count':len(ids)})
        return len(ids)

    def save_model(self,request,obj,form,change):
        if not change or not self.has_change_permission(request,obj):raise PermissionDenied
        if 'resolved' in form.changed_data:self.mark(request,self.get_queryset(request).filter(pk=obj.pk),obj.resolved)

    @admin.action(description='علامت بزن: رفع‌شده',permissions=['change'])
    def resolve_selected(self,request,queryset):
        self.message_user(request,f'{self.mark(request,queryset,True)} خطا رفع‌شده علامت خورد.')

    @admin.action(description='بازگشایی برای بررسی',permissions=['change'])
    def reopen_selected(self,request,queryset):
        self.message_user(request,f'{self.mark(request,queryset,False)} خطا بازگشایی شد.')
