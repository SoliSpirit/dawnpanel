from django.test import TestCase,Client,override_settings
from django.contrib.auth.models import User,Permission
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
import uuid
from .models import ChatConversation,ChatMessage,SupportPresence,Audit

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
        self.assertContains(self.agent.get('/staff/chat/'),'میز گفتگوی آنلاین')
