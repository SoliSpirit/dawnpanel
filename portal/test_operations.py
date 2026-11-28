from unittest.mock import Mock,patch
import requests

from django.contrib.auth.models import Permission,User
from django.db import transaction
from django.http import HttpResponse
from django.test import Client,TestCase,override_settings
from django.urls import path,reverse

from .models import Audit,Campaign,NoticePreference,OperationNotice,OrderDelivery,SiteIssue
from .notice_topics import subscribers
from .order_notices import dispatch,prepare


def broken_test_view(request,reference):
    raise ValueError('qa-exception-detail-not-for-report')


urlpatterns=[path('test-issue/<str:reference>/',broken_test_view,name='issue_test_view'),
             path('unavailable/',lambda r:HttpResponse(status=503),name='issue_test_http')]
handler404=lambda request,exception:HttpResponse(status=404)
handler500=lambda request:HttpResponse(status=500)


@override_settings(BOT_CONFIG={'telegram':{'admin_ids':[71,81],'token':'test'}},STORAGES={
    'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class OperationsTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('qa-owner',is_staff=True,is_superuser=True)
        self.client.force_login(self.user)
        self.pref=reverse('admin:portal_noticepreference_changelist')
        self.issues=reverse('admin:portal_siteissue_changelist')

    def test_per_admin_preferences_revalidate_pending_events_and_do_not_leak_private_fields(self):
        self.assertEqual(subscribers('catalog'),[71,81]);self.assertEqual(subscribers('site_error'),[])
        self.client.post(self.pref,{'recipient':71,'revision':0,'topics':['web_order','catalog']})
        self.client.post(self.pref,{'recipient':81,'revision':0,'topics':['bot_order','finance']})
        self.assertEqual(subscribers('web_order'),[71]);self.assertEqual(subscribers('bot_order'),[81])
        self.assertEqual(subscribers('incoming_receipt'),[])
        self.assertEqual(self.client.post(self.pref,{'recipient':'999','revision':0,'topics':['catalog']}).status_code,404)
        self.assertEqual(self.client.post(self.pref,{'recipient':'71','revision':1,'topics':['unknown']}).status_code,404)
        obj=Campaign.objects.create(name='secret-notice-name',code='sample')
        self.client.post(reverse('admin:portal_campaign_change',args=[obj.pk]),{'name':'private-changed-name','code':'sample','active':'on','_save':'1'})
        obj.refresh_from_db();self.assertEqual(obj.name,'private-changed-name')
        self.assertEqual(OperationNotice.objects.filter(topic='management',summary='ویرایش لینک تبلیغاتی',reference=str(obj.pk)).count(),1)
        with self.assertRaises(ValueError),transaction.atomic():
            Audit.objects.create(actor=self.user,action='ticket.reply',object_ref='7')
            raise ValueError('rollback')
        self.assertFalse(OperationNotice.objects.filter(topic='support').exists())
        Audit.objects.create(action='source.price.fetch',object_ref='denapanel')
        before=OperationNotice.objects.count()
        buyer=User.objects.create_user('qa-customer');Audit.objects.create(actor=buyer,action='account.login')
        self.assertEqual(OperationNotice.objects.count(),before)
        Audit.objects.create(action='receipt.approve',object_ref='9',details={'telegram_admin_id':71,'note':'qa-private-note'})
        Audit.objects.create(action='bot.product.edit',object_ref='3',details={'telegram_admin_id':81})
        prepare(60)
        bought=OrderDelivery.objects.get(operation__topic='catalog')
        self.assertEqual(bought.recipient,71)
        # A mute that happens after fanout still suppresses the pending request,
        # and re-enabling later must not backfill it.
        self.client.post(self.pref,{'recipient':71,'revision':1})
        self.client.post(self.pref,{'recipient':71,'revision':1,'topics':['finance']})  # stale browser
        self.assertEqual(NoticePreference.objects.get(pk=71).enabled,[])
        with patch('portal.order_notices.requests.post') as send:
            send.return_value=Mock(status_code=200)
            send.return_value.json.return_value={'ok':True,'result':{'message_id':19,'chat':{'id':81}}}
            dispatch(60);self.assertEqual(send.call_count,1)
            payload=send.call_args.kwargs['json'];self.assertEqual(payload['chat_id'],81)
            self.assertIn('تأیید رسید',payload['text']);self.assertIn('#71',payload['text'])
            self.assertNotIn('qa-private-note',str(payload));self.assertNotIn('private-changed-name',str(payload))
            bought.refresh_from_db();self.assertEqual(bought.state,'muted')
            self.client.post(self.pref,{'recipient':71,'revision':2,'topics':['catalog']})
            dispatch();self.assertEqual(send.call_count,1)

    def test_access_is_separate_for_view_edit_issues_and_recipient_preferences(self):
        anon=Client()
        for u in [self.pref,self.issues]:
            self.assertEqual(anon.get(u).status_code,404)
        guard=Client(enforce_csrf_checks=True);guard.force_login(self.user)
        self.assertEqual(guard.post(self.pref,{'recipient':71,'revision':0}).status_code,403)
        reader=User.objects.create_user('operations-reader',is_staff=True)
        reader.user_permissions.add(*Permission.objects.filter(content_type__app_label='portal',codename__in=['view_noticepreference','view_siteissue']))
        self.client.force_login(reader)
        self.assertContains(self.client.get(self.pref),'disabled')
        self.assertEqual(self.client.post(self.pref,{'recipient':71,'revision':0}).status_code,404)
        self.assertEqual(self.client.get(self.issues).status_code,200)
        self.assertFalse(NoticePreference.objects.exists())

    def test_html_mail_and_matrix_subscriptions_are_independent_and_snapshot_new_events(self):
        from django.core import mail
        from .models import ChatEmailDelivery
        from .notice_topics import TOPICS,mail_topics
        from .chat_notices import dispatch_email
        new={'matrix':'1','recipient':71,'revision':0,'topics':['web_order'],'email_topics':list(TOPICS),'chat_email':'qa@example.org'}
        self.client.post(self.pref,new);pref=NoticePreference.objects.get(pk=71)
        self.assertEqual(mail_topics(pref),set(TOPICS));self.assertEqual(pref.enabled,['web_order'])
        self.client.post(self.pref,{**new,'revision':0,'email_topics':[]});self.assertEqual(mail_topics(NoticePreference.objects.get(pk=71)),set(TOPICS))
        for topic in ('catalog','site_error','incoming_ticket','incoming_receipt','lottery_warning'):
            OperationNotice.objects.create(topic=topic,origin='system',summary='تست <qa>',reference='1')
        self.assertEqual(ChatEmailDelivery.objects.filter(recipient=71).exclude(topic='management').count(),5)
        self.assertEqual(dispatch_email()['accepted'],6)
        for msg in mail.outbox:
            self.assertEqual(msg.to,['qa@example.org']);self.assertEqual(msg.alternatives[0].mimetype,'text/html')
            self.assertIn('dir="rtl"',msg.alternatives[0].content);self.assertNotIn('<qa>',msg.alternatives[0].content)
        self.assertEqual(dispatch_email()['accepted'],0)

    def test_actual_5xx_are_grouped_redacted_and_reopened(self):
        with override_settings(ROOT_URLCONF=__name__):
            c=Client(raise_request_exception=False)
            for ref in ('qa-private-path-one','qa-private-path-two'):
                res=c.post(f'/test-issue/{ref}/?token=qa-private-query',{'password':'qa-private-password'})
                self.assertEqual(res.status_code,500)
            self.assertEqual(c.get('/unavailable/').status_code,503)
            self.assertEqual(c.get('/does-not-exist/').status_code,404)
        self.assertEqual(SiteIssue.objects.count(),2)
        issue=SiteIssue.objects.get(kind='ValueError');self.assertEqual(issue.occurrences,2)
        self.assertEqual((issue.route,issue.status_code,issue.method),('issue_test_view',500,'POST'))
        self.assertIn('broken_test_view',issue.trace)
        detail=reverse('admin:portal_siteissue_change',args=[issue.pk])
        page=self.client.get(detail)
        for private in ['qa-private','qa-exception-detail-not-for-report']:
            self.assertNotContains(page,private)
        self.assertEqual(OperationNotice.objects.filter(topic='site_error',reference=str(issue.pk)).count(),1)
        self.client.post(detail,{'_save':'1','resolved':'on'})
        issue.refresh_from_db();self.assertTrue(issue.resolved);self.assertIsNotNone(issue.resolved_at)
        with override_settings(ROOT_URLCONF=__name__):
            c.post('/test-issue/another-private-value/')
        issue.refresh_from_db()
        self.assertFalse(issue.resolved);self.assertEqual(issue.occurrences,3)
        self.assertEqual(OperationNotice.objects.filter(topic='site_error',reference=str(issue.pk)).count(),2)

    def test_handled_sms_outage_visible_without_phone_or_sms_code(self):
        with patch('portal.services.requests.post',side_effect=requests.ConnectionError('qa-private-provider-url')):
            self.client.logout()
            self.client.post('/login/',{'phone':'09123456700'})
        issue=SiteIssue.objects.get(kind='SMSDeliveryError')
        self.assertIsNone(issue.status_code)
        self.assertFalse(any('09123456700' in str(v) or 'qa-private' in str(v) for v in vars(issue).values()))
