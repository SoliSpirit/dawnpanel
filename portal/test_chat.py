from django.test import TestCase,Client,override_settings
from django.contrib.auth.models import User,Permission
from django.utils import timezone
from datetime import timedelta
from unittest.mock import Mock,patch
from django.core import mail
from django.db import transaction
import smtplib
import uuid
from .models import ChatConversation,ChatMessage,SupportPresence,Audit,ChatEmailDelivery,NoticePreference,OperationNotice,OrderDelivery
from .chat_notices import dispatch_email
from .order_notices import dispatch

@override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ChatSecurityTests(TestCase):
    def setUp(self):
        self.visitor=Client();self.other=Client()
        self.staff=User.objects.create_user(username='support',is_staff=True)
        self.staff.user_permissions.add(Permission.objects.get(codename='change_chatconversation',content_type__app_label='portal'))
        self.agent=Client();self.agent.force_login(self.staff)
    def send(self,client,body='سلام، درباره محصول سوال دارم.',nonce=None,**extra):
        return client.post('/support/chat/',{'body':body,'nonce':str(nonce or uuid.uuid4()),**extra})
    def test_guest_sessions_are_isolated_and_staff_api_is_private(self):
        sent=self.send(self.visitor);self.assertEqual(sent.status_code,200)
        conversation=sent.json()['conversation']
        self.assertEqual(len(self.visitor.get('/support/chat/').json()['messages']),1)
        self.assertEqual(self.other.get('/support/chat/?conversation='+conversation).json()['messages'],[])
        self.assertEqual(self.other.get('/staff/chat/api/'+conversation+'/').status_code,403)
        self.assertEqual(self.other.get('/staff/chat/api/').status_code,403)
        self.assertIn('no-store',self.visitor.get('/support/chat/')['Cache-Control'])
    def test_csrf_required_for_guest_and_staff_posts(self):
        client=Client(enforce_csrf_checks=True)
        initial=client.get('/support/chat/')
        data={'body':'پیام آزمایشی','nonce':str(uuid.uuid4())}
        self.assertEqual(client.post('/support/chat/',data).status_code,403)
        self.assertEqual(client.post('/support/chat/',data,HTTP_X_CSRFTOKEN=initial.json()['csrf']).status_code,200)
        client.force_login(self.staff)
        self.assertEqual(client.post('/staff/chat/api/').status_code,403)
    def test_customer_cannot_forge_staff_author_or_duplicate_message(self):
        nonce=uuid.uuid4()
        first=self.send(self.visitor,nonce=nonce,from_staff='true',author=self.staff.pk)
        second=self.send(self.visitor,nonce=nonce)
        self.assertEqual(first.json()['id'],second.json()['id'])
        message=ChatMessage.objects.get();self.assertFalse(message.from_staff);self.assertIsNone(message.author_id)
    def test_staff_reply_close_and_visitor_reopen(self):
        thread=self.send(self.visitor).json()['conversation'];url='/staff/chat/api/'+thread+'/'
        nonce=str(uuid.uuid4())
        for _ in range(2):self.assertEqual(self.agent.post(url,{'body':'سلام، در خدمت شما هستیم.','nonce':nonce}).status_code,200)
        messages=self.visitor.get('/support/chat/').json()['messages']
        self.assertEqual(len(messages),2);self.assertTrue(messages[-1]['from_staff'])
        self.assertEqual(Audit.objects.filter(action='chat.reply').count(),1)
        self.assertEqual(self.agent.post(url,{'action':'read','through':messages[-1]['id']}).status_code,200)
        self.assertEqual(self.agent.post(url,{'action':'close'}).json()['status'],'closed')
        self.assertEqual(self.send(self.visitor,'یک سوال دیگر هم دارم.').json()['status'],'waiting')
        self.assertEqual(ChatConversation.objects.count(),1)
    def test_presence_requires_active_authorized_staff_and_expires(self):
        self.assertFalse(self.visitor.get('/support/chat/').json()['online'])
        self.assertEqual(self.agent.post('/staff/chat/api/').status_code,200)
        self.assertTrue(self.visitor.get('/support/chat/').json()['online'])
        SupportPresence.objects.update(seen_at=timezone.now()-timedelta(seconds=90))
        self.assertFalse(self.visitor.get('/support/chat/').json()['online'])
        ordinary=User.objects.create_user(username='ordinary',is_staff=True);client=Client();client.force_login(ordinary)
        self.assertEqual(client.post('/staff/chat/api/').status_code,403)
    def test_invalid_and_rate_limited_messages_do_not_create_threads(self):
        for body in ['', 'x'*2001]:self.assertEqual(self.send(self.visitor,body).status_code,400)
        with patch('portal.chat.rate_limit',return_value=False):self.assertEqual(self.send(self.visitor).status_code,429)
        self.assertFalse(ChatConversation.objects.exists())
    def test_authenticated_accounts_do_not_share_messages(self):
        first=User.objects.create_user(username='first');second=User.objects.create_user(username='second')
        a=Client();a.force_login(first);b=Client();b.force_login(second)
        self.send(a,'پیام خصوصی کاربر اول')
        self.assertEqual(b.get('/support/chat/').json()['messages'],[])
    def test_polling_cursor_and_support_desk_render(self):
        first=self.send(self.visitor).json()['id'];self.send(self.visitor,'پیام دوم')
        self.assertEqual(len(self.visitor.get('/support/chat/?after='+str(first)).json()['messages']),1)
        self.assertEqual(self.visitor.get('/support/chat/?after=bad').status_code,400)
        self.assertRedirects(self.agent.get('/staff/chat/'),'/admin/support/chat/')
        self.assertContains(self.agent.get('/admin/support/chat/'),'data-list-url="/admin/support/chat/api/"')

    def test_shared_unread_only_acknowledges_displayed_messages_and_late_arrivals_survive_reply(self):
        first=self.send(self.visitor).json();url=f"/admin/support/chat/api/{first['conversation']}/"
        count=lambda:self.agent.get('/admin/support/counts/').json()
        seen=self.agent.get(url).json()['messages'][-1]['id']
        second=self.send(self.visitor).json()['id'];other=self.send(self.other).json()['id']
        self.assertEqual(count(),{'chat':3,'latest':other})
        self.assertEqual(self.agent.post(url,{'action':'read','through':other}).status_code,400)
        for _ in range(2):self.assertEqual(self.agent.post(url,{'action':'read','through':seen}).status_code,200)
        self.agent.post(url,{'body':'پاسخ','nonce':uuid.uuid4()})
        self.assertEqual(count()['chat'],2)
        self.assertEqual(self.agent.post(url,{'action':'close'}).status_code,409)
        self.agent.post(url,{'action':'read','through':second});self.agent.post(url,{'action':'read','through':seen})
        self.assertEqual(self.agent.post(url,{'action':'close'}).status_code,200)
        self.assertEqual(count()['chat'],1)
        self.send(self.visitor);self.assertEqual(count()['chat'],2)
        self.assertEqual(self.visitor.get('/admin/support/counts/').status_code,404)
        self.assertNotIn('requests',count())

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[71,81],'token':'test'}},EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_chat_outboxes_commit_once_and_failed_smtp_does_not_delay_telegram(self):
        NoticePreference.objects.create(pk=71,enabled=['web_chat'])
        NoticePreference.objects.create(pk=81,enabled=[],chat_email='alerts@example.org',chat_email_enabled=True)
        with self.assertRaises(RuntimeError),transaction.atomic():
            self.send(self.visitor)
            raise RuntimeError('roll back chat')
        for model in (ChatMessage,OperationNotice,OrderDelivery,ChatEmailDelivery):
            self.assertFalse(model.objects.exists())
        nonce=uuid.uuid4();body='private buyer question';reply='private staff answer'
        with patch('portal.order_notices.requests.post') as api,patch('portal.chat_notices.send_chat_email') as smtp:
            sent=self.send(self.visitor,body,nonce).json();self.send(self.visitor,body,nonce)
            self.agent.post(f"/admin/support/chat/api/{sent['conversation']}/",{'body':reply,'nonce':uuid.uuid4()})
            api.assert_not_called();smtp.assert_not_called()
        self.assertEqual(OrderDelivery.objects.get(operation__topic='web_chat').recipient,71)
        self.assertEqual(ChatEmailDelivery.objects.get().recipient,81)
        with patch('portal.chat_notices.send_chat_email',side_effect=smtplib.SMTPServerDisconnected):
            self.assertEqual(dispatch_email()['retry'],1)
        with patch('portal.order_notices.requests.post') as api:
            api.return_value=Mock(status_code=200);api.return_value.json.return_value={'ok':True,'result':{'chat':{'id':71},'message_id':5}}
            self.assertEqual(dispatch()['sent'],1);self.assertEqual(dispatch()['sent'],0)
            payload=api.call_args.kwargs['json'];link=payload['reply_markup']['inline_keyboard'][0][0]['url']
            self.assertIn('/admin/support/chat/?thread='+sent['conversation'],link)
            self.assertNotIn(body,str(payload));self.assertNotIn(reply,str(payload))
        ChatEmailDelivery.objects.update(due_at=timezone.now())
        self.assertEqual(dispatch_email()['accepted'],1);self.assertEqual(dispatch_email()['accepted'],0)
        self.assertEqual(len(mail.outbox),1);self.assertEqual(mail.outbox[0].to,['alerts@example.org'])
        self.assertIn(link,mail.outbox[0].body);self.assertNotIn(body,mail.outbox[0].body);self.assertNotIn(reply,mail.outbox[0].body)

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[71],'token':'test'}})
    def test_email_destination_requires_separate_permission_and_never_backfills_a_mute(self):
        url='/admin/portal/noticepreference/'
        self.staff.user_permissions.add(Permission.objects.get(codename='change_noticepreference'))
        cfg={'email_settings':'1','recipient':71,'revision':0,'chat_email':'desk@example.org','chat_email_enabled':'on'}
        self.assertNotContains(self.agent.get(url),'name="chat_email"')
        self.assertEqual(self.agent.post(url,cfg).status_code,404)
        self.staff.user_permissions.add(Permission.objects.get(codename='manage_chat_email'))
        self.agent.post(url,{**cfg,'chat_email':'not-an-email'})
        self.assertFalse(NoticePreference.objects.exists())
        self.assertEqual(self.agent.post(url,{**cfg,'recipient':111}).status_code,404)
        self.agent.post(url,cfg);self.send(self.visitor)
        self.agent.post(url,{**cfg,'revision':1,'chat_email':'new@example.org'})
        self.agent.post(url,{**cfg,'revision':1})  # stale
        with patch('portal.chat_notices.send_chat_email') as smtp:
            dispatch_email();smtp.assert_not_called()
        self.assertEqual(ChatEmailDelivery.objects.get().state,'muted')
        self.assertEqual(NoticePreference.objects.get().chat_email,'new@example.org')
        self.agent.post(url,{'recipient':71,'revision':2,'topics':[]})
        second=self.send(self.visitor).json()
        self.agent.post(url,{'recipient':71,'revision':3,'topics':['web_chat']})
        self.assertEqual(OrderDelivery.objects.filter(operation__topic='web_chat',state='muted').count(),1)
        self.assertEqual(OrderDelivery.objects.filter(operation__topic='web_chat').count(),1)
        self.assertTrue(ChatEmailDelivery.objects.filter(message_id=second['id'],state='pending').exists())
        with override_settings(BOT_CONFIG={'telegram':{'admin_ids':[]}}),patch('portal.chat_notices.send_chat_email') as smtp:
            self.assertEqual(dispatch_email()['muted'],1);smtp.assert_not_called()

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[71,81]}},EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_explicit_mail_test_only_reaches_current_opted_in_destinations(self):
        from io import StringIO
        from django.core.management import call_command,CommandError
        NoticePreference.objects.create(pk=81,chat_email='disabled@example.org')
        NoticePreference.objects.create(pk=99,chat_email_enabled=True,chat_email='removed@example.org')
        with self.assertRaises(CommandError):call_command('deliver_chat_emails','--test')
        NoticePreference.objects.create(pk=71,chat_email_enabled=True,chat_email='alerts@example.org')
        call_command('deliver_chat_emails','--test',stdout=StringIO())
        self.assertEqual([m.to for m in mail.outbox],[['alerts@example.org']])
        self.assertFalse(ChatMessage.objects.exists())
