import uuid
from datetime import timedelta
from unittest.mock import patch,Mock
from decimal import Decimal
from django.test import TransactionTestCase,override_settings,Client
from django.db import connection
from django.contrib.auth.models import User,Permission
from django.utils import timezone
from django.template.loader import get_template
from .models import *
from .services import *

@override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class SecurityAndCommerceTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.legacy=[LegacyUser,Category,Product,Order,Ledger,Currency,GiftCode]
        with connection.schema_editor() as editor:
            for model in cls.legacy: editor.create_model(model)
        with connection.cursor() as c:
            c.execute('CREATE TABLE gift_code_uses (id INTEGER PRIMARY KEY '+('AUTO_INCREMENT' if connection.vendor=='mysql' else 'AUTOINCREMENT')+',gift_code_id INTEGER,user_id BIGINT,amount BIGINT,UNIQUE(gift_code_id,user_id))')
    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as c: c.execute('DROP TABLE gift_code_uses')
        with connection.schema_editor() as editor:
            for model in reversed(cls.legacy): editor.delete_model(model)
        super().tearDownClass()
    def setUp(self):
        with connection.cursor() as c: c.execute('DELETE FROM gift_code_uses')
        GiftCode.objects.all().delete();Currency.objects.all().delete()
        # Django flush does not include unmanaged tables.
        for model in [Order,Ledger,Product,Category,LegacyUser]: model.objects.all().delete()
        self.user=User.objects.create_user(username='09120000001')
        self.other=User.objects.create_user(username='09120000002')
        self.wallet=LegacyUser.objects.create(user_id=101,phone_number='09120000001',is_verified=True,balance=10000,referral_code='test')
        self.otherwallet=LegacyUser.objects.create(user_id=102,phone_number='09120000002',is_verified=True,balance=10000,referral_code='test2')
        self.account=Account.objects.create(user=self.user,phone='09120000001',legacy_id=101)
        Account.objects.create(user=self.other,phone='09120000002',legacy_id=102)
        self.category=Category.objects.create(name='روبیکا')
        self.product=Product.objects.create(category=self.category,name='خدمت آزمایشی',price=1000,price_per=100,min_order=10,max_order=1000,platform='rubika',show_on_website=True,show_on_telegram=True,need_link=True)
        self.client.force_login(self.user)
    def buy(self,key=None): return place_order(self.account,self.product.pk,100,'https://rubika.ir/test',key or uuid.uuid4(),1000)
    def test_price_rounds_up_and_honors_profit(self):
        self.product.product_profit_percent=Decimal('7.5')
        self.assertEqual(price_for(self.product,11)[0],119)
    def test_invalid_quantity(self):
        for q in [-1,0,1,1001]:
            with self.assertRaises(BusinessError): price_for(self.product,q)
    def test_purchase_and_ledger_are_atomic(self):
        with patch.object(Order.objects,'create',side_effect=RuntimeError('db failure')):
            with self.assertRaises(RuntimeError): self.buy()
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000);self.assertFalse(Ledger.objects.exists())
    def test_checkout_is_idempotent(self):
        key=uuid.uuid4();a=self.buy(key);b=self.buy(key)
        self.assertEqual(a.pk,b.pk);self.assertEqual(Order.objects.count(),1)
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,9000)
    def test_insufficient_funds_no_order(self):
        self.wallet.balance=1;self.wallet.save()
        with self.assertRaises(BusinessError): self.buy()
        self.assertFalse(Order.objects.exists());self.assertFalse(Ledger.objects.exists())
    def test_changed_quote_not_charged(self):
        self.product.price=1100;self.product.save()
        with self.assertRaises(BusinessError): self.buy()
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000)
    def test_hidden_website_product_cannot_be_ordered(self):
        self.product.show_on_website=False;self.product.save()
        with self.assertRaises(BusinessError): self.buy()
        self.assertEqual(self.client.get(self.product.get_absolute_url()).status_code,404)
    def test_telegram_only_product_cannot_leak_to_website(self):
        self.product.platform='telegram';self.product.save()
        self.assertFalse(public_products().exists())
        with self.assertRaises(BusinessError): self.buy()
    def test_ai_product_is_visible_filterable_and_purchasable(self):
        self.product.platform='ai';self.product.name='ChatGPT اشتراک';self.product.save()
        self.assertTrue(public_products().filter(pk=self.product.pk).exists())
        self.assertContains(self.client.get('/ai/'),'ChatGPT اشتراک')
        self.assertNotContains(self.client.get('/services/?platform=bale'),'ChatGPT اشتراک')
        self.assertContains(self.client.get('/sitemap.xml'),'/ai/')
        self.assertEqual(self.buy().total_price,1000)

    def test_ai_brand_search_matches_persian_name(self):
        self.product.platform='ai';self.product.name='اشتراک جمینای';self.product.save()
        self.assertContains(self.client.get('/ai/?q=Gemini'),'اشتراک جمینای')

    def test_image_upload_is_reencoded_and_used_in_product_seo(self):
        import io,tempfile,json,re
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from portal.product_media import normalize_product_image,save_product_picture
        from portal.templatetags.storefront import product_image
        image=io.BytesIO();Image.new('RGB',(2000,1000),'red').save(image,format='PNG')
        upload=SimpleUploadedFile('untrusted-name.png',image.getvalue(),content_type='text/plain')
        with tempfile.TemporaryDirectory() as directory,override_settings(MEDIA_ROOT=directory):
            normalized=normalize_product_image(upload)
            self.assertTrue(normalized.name.endswith('.webp'))
            with Image.open(normalized) as result:
                self.assertEqual(result.format,'WEBP');self.assertEqual(result.size,(1600,800))
            normalized.seek(0)
            form=Mock(cleaned_data={'picture':normalized,'picture_alt':'عکس واقعی محصول'})
            save_product_picture(self.product,form)
            self.product=Product.objects.get(pk=self.product.pk)
            url=product_image(self.product)
            self.assertTrue(url.startswith('/media/products/'))
            response=self.client.get(self.product.get_absolute_url())
            self.assertContains(response,'https://dawnpanel.ir'+url)
            self.assertContains(response,'عکس واقعی محصول')

    def test_product_day_and_night_uploads_are_independent(self):
        import io,tempfile
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from portal.product_media import ProductImageForm,save_product_picture
        from portal.templatetags.storefront import product_image
        def upload(color):
            image=io.BytesIO();Image.new('RGB',(64,64),color).save(image,format='PNG')
            return SimpleUploadedFile('photo.png',image.getvalue(),content_type='image/png')
        with tempfile.TemporaryDirectory() as directory,override_settings(MEDIA_ROOT=directory):
            form=ProductImageForm(files={'picture':upload('white'),'night_picture':upload('black')})
            # Exercise the same normalization hooks used by admin on both uploads.
            form.cleaned_data={'picture':form.files['picture'],'night_picture':form.files['night_picture']}
            day=form.clean_picture();night=form.clean_night_picture()
            save_product_picture(self.product,Mock(cleaned_data={'picture':day,'night_picture':night,'picture_alt':'محصول'}))
            day_url=product_image(self.product,'light');night_url=product_image(self.product,'dark')
            self.assertTrue(day_url.startswith('/media/products/'))
            self.assertTrue(night_url.startswith('/media/products/'))
            self.assertNotEqual(day_url,night_url)
            response=self.client.get(self.product.get_absolute_url())
            self.assertContains(response,day_url);self.assertContains(response,night_url)
            save_product_picture(self.product,Mock(cleaned_data={'remove_night_picture':True}))
            self.assertEqual(product_image(self.product,'light'),day_url)
            self.assertIn('/artwork/social.webp',product_image(self.product,'dark'))
            save_product_picture(self.product,Mock(cleaned_data={'remove_picture':True}))
            self.assertFalse(ProductVisual.objects.filter(product_id=self.product.pk).exists())

    def test_night_upload_rejects_invalid_content(self):
        from django import forms
        from django.core.files.uploadedfile import SimpleUploadedFile
        from portal.product_media import ProductImageForm
        form=ProductImageForm()
        form.cleaned_data={'night_picture':SimpleUploadedFile('image.png',b'<svg onload="alert(1)"/>',content_type='image/png')}
        with self.assertRaises(forms.ValidationError):form.clean_night_picture()

    def test_product_admin_accepts_picture_upload(self):
        import io,tempfile
        from PIL import Image
        from django.forms.models import model_to_dict
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save()
        data={key:value if value is not None else '' for key,value in model_to_dict(self.product).items()}
        image=io.BytesIO();Image.new('RGB',(64,64),'blue').save(image,format='PNG')
        data.update({'picture':SimpleUploadedFile('picture.png',image.getvalue(),content_type='image/png'),'picture_alt':'تصویر انتخاب‌شده مدیر','_save':'ذخیره'})
        night=io.BytesIO();Image.new('RGB',(64,64),'black').save(night,format='PNG')
        data['night_picture']=SimpleUploadedFile('night.png',night.getvalue(),content_type='image/png')
        with tempfile.TemporaryDirectory() as directory,override_settings(MEDIA_ROOT=directory):
            response=self.client.post('/manage/portal/product/'+str(self.product.pk)+'/change/',data)
            self.assertEqual(response.status_code,302)
            visual=ProductVisual.objects.get(product_id=self.product.pk)
            self.assertEqual(visual.alt_text,'تصویر انتخاب‌شده مدیر')
            self.assertTrue(visual.image.storage.exists(visual.image.name))
            self.assertTrue(visual.night_image.storage.exists(visual.night_image.name))
            self.assertNotEqual(visual.image.name,visual.night_image.name)

    def test_image_upload_rejects_svg_and_oversized_payload(self):
        from django import forms
        from django.core.files.uploadedfile import SimpleUploadedFile
        from portal.product_media import normalize_product_image,MAX_BYTES
        for upload in [SimpleUploadedFile('fake.png',b'<svg onload="alert(1)"></svg>'),SimpleUploadedFile('large.jpg',b'x'*(MAX_BYTES+1))]:
            with self.assertRaises(forms.ValidationError):normalize_product_image(upload)

    def test_seo_ai_offer_uses_rials_and_search_is_noindex(self):
        import json,re
        self.product.platform='ai';self.product.save()
        response=self.client.get(self.product.get_absolute_url())
        data=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',response.content.decode()).group(1))
        self.assertEqual(data['@type'],'Product')
        self.assertEqual(data['offers']['priceCurrency'],'IRR')
        self.assertEqual(data['offers']['price'],1000)
        self.assertContains(self.client.get('/ai/?q=ChatGPT'),'noindex,follow')
        self.assertContains(self.client.get('/ai/'),'index,follow,max-image-preview:large')

    def test_banned_user_cannot_order(self):
        self.wallet.is_banned=True;self.wallet.save()
        with self.assertRaises(BusinessError): self.buy()
    def test_bot_visibility_independent(self):
        self.product.show_on_telegram=False;self.product.save()
        self.assertTrue(public_products().exists())
        with self.assertRaises(BusinessError): place_bot_order(101,self.product.pk,100,'test',1000)
    def test_refund_is_once_only(self):
        order=self.buy();change_order(self.user,order.pk,'cancelled','تست')
        with self.assertRaises(BusinessError): change_order(self.user,order.pk,'cancelled','again')
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000);self.assertEqual(Ledger.objects.filter(type='refund').count(),1)
    def test_completed_order_cannot_refund(self):
        order=self.buy();change_order(self.user,order.pk,'completed','done')
        with self.assertRaises(BusinessError): change_order(self.user,order.pk,'cancelled','again')
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.total_purchases,1000)
    def test_foreign_order_is_not_visible(self):
        o=self.buy();self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/account/orders/{o.pk}/').status_code,404)
    def test_foreign_ticket_is_not_visible(self):
        t=Ticket.objects.create(user=self.other,subject='private')
        self.assertEqual(self.client.get(f'/account/tickets/{t.pk}/').status_code,404)
        self.assertEqual(self.client.post(f'/account/tickets/{t.pk}/',{'body':'attack'}).status_code,404)
    def test_staff_permission_required(self):
        o=self.buy();self.assertEqual(self.client.post(f'/staff/order/{o.pk}/',{'status':'cancelled'}).status_code,403)
    def test_support_cannot_change_products(self):
        self.user.is_staff=True;self.user.save()
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='change_ticket'))
        self.assertEqual(self.client.get('/manage/portal/product/').status_code,403)
    def test_csrf_is_enforced(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.user)
        self.assertEqual(c.post('/account/checkout/',{'key':str(uuid.uuid4())}).status_code,403)
    def test_xss_escaped_in_ticket(self):
        t=Ticket.objects.create(user=self.user,subject='xss')
        TicketMessage.objects.create(ticket=t,author=self.user,body='<script>alert(1)</script>')
        r=self.client.get(f'/account/tickets/{t.pk}/');self.assertNotContains(r,'<script>alert(1)</script>');self.assertContains(r,'&lt;script&gt;')
    def test_otp_replay_and_cross_session_blocked(self):
        o=OTP.objects.create(phone='09120000001',code_hash=digest('123456'),session_hash=digest('s'),expires_at=timezone.now()+timedelta(minutes=5))
        self.assertIsNone(verify_otp(o.pk,'123456','other'))
        self.assertEqual(verify_otp(o.pk,'123456','s'),'09120000001')
        self.assertIsNone(verify_otp(o.pk,'123456','s'))
    def test_otp_lockout(self):
        o=OTP.objects.create(phone='09120000001',code_hash=digest('123456'),session_hash=digest('s'),expires_at=timezone.now()+timedelta(minutes=5))
        for _ in range(5): self.assertIsNone(verify_otp(o.pk,'000000','s'))
        self.assertIsNone(verify_otp(o.pk,'123456','s'))
    def test_expired_otp(self):
        o=OTP.objects.create(phone='09120000001',code_hash=digest('123456'),session_hash=digest('s'),expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIsNone(verify_otp(o.pk,'123456','s'))
    def test_rate_limit(self):
        self.assertTrue(rate_limit('test',2,60));self.assertTrue(rate_limit('test',2,60));self.assertFalse(rate_limit('test',2,60))
    def test_phone_normalization(self):
        self.assertEqual(normalize_phone('+98 935-617-1858'),'09356171858')
        self.assertEqual(normalize_phone('۰۹۳۵۶۱۷۱۸۵۸'),'09356171858')
        with self.assertRaises(BusinessError): normalize_phone('bad')
    def test_security_headers(self):
        r=self.client.get('/account/')
        self.assertIn("frame-ancestors 'none'",r['Content-Security-Policy']);self.assertIn('no-store',r['Cache-Control'])
    def test_public_pages_render(self):
        for url in ['/','/services/','/blog/','/login/','/privacy/','/terms/','/about/','/robots.txt','/sitemap.xml',self.product.get_absolute_url()]:
            self.assertEqual(self.client.get(url).status_code,302 if url=='/login/' else 200,url)
    def test_account_pages_render(self):
        for url in ['/account/','/account/orders/','/account/charge/','/account/tickets/']:
            self.assertEqual(self.client.get(url).status_code,200,url)

    def test_gift_once_and_capacity(self):
        GiftCode.objects.create(code='GIFT',amount=500,max_uses=1)
        self.assertEqual(redeem_gift(self.account,'gift'),500)
        with self.assertRaises(BusinessError): redeem_gift(self.account,'GIFT')
        with self.assertRaises(BusinessError): redeem_gift(self.other.account,'GIFT')
        self.wallet.refresh_from_db();self.otherwallet.refresh_from_db()
        self.assertEqual(self.wallet.balance,10500);self.assertEqual(self.otherwallet.balance,10000)
        self.assertEqual(Ledger.objects.filter(type='gift').count(),1)
    def test_gift_unknown_eligibility_fails_closed(self):
        GiftCode.objects.create(code='UNKNOWN',amount=500,target_type='unsupported')
        with self.assertRaises(BusinessError): redeem_gift(self.account,'UNKNOWN')
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000)
    def test_gift_requires_eligible_account(self):
        GiftCode.objects.create(code='BUYERS',amount=500,target_type='buyers')
        with self.assertRaises(BusinessError): redeem_gift(self.account,'BUYERS')
    def test_currency_rate_missing_fails_closed(self):
        self.product.price_currency='MISSING';self.product.price_amount=Decimal('1')
        with self.assertRaises(BusinessError): price_for(self.product,100)
    def test_forged_admin_ip_header_ignored(self):
        with patch('portal.views.request_otp',side_effect=BusinessError('mock')) as otp:
            self.client.logout();self.client.post('/login/',{'phone':'09120000001'},REMOTE_ADDR='203.0.113.1',HTTP_X_REAL_IP='8.8.8.8')
            self.assertEqual(otp.call_args.args[-1],'203.0.113.1')
    def test_trusted_proxy_ip_used(self):
        with patch('portal.views.request_otp',side_effect=BusinessError('mock')) as otp:
            self.client.logout();self.client.post('/login/',{'phone':'09120000001'},REMOTE_ADDR='127.0.0.1',HTTP_X_REAL_IP='203.0.113.2')
            self.assertEqual(otp.call_args.args[-1],'203.0.113.2')
    def test_banned_existing_login_blocked(self):
        self.wallet.is_banned=True;self.wallet.save()
        with self.assertRaises(BusinessError): login_account('09120000001')


from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections

@skipUnless(connection.vendor=='mysql','Real row-lock tests require MariaDB')
@override_settings(BOT_CONFIG={'zarinpal':{'merchant':'test-only','sandbox':True},'business':{'commission_percent':10}})
class MariaDBConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.legacy=[LegacyUser,Category,Product,Order,Ledger]
        with connection.schema_editor() as e:
            for m in cls.legacy:e.create_model(m)
        with connection.cursor() as c:
            c.execute("CREATE TABLE zarinpal_transactions (id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id BIGINT,amount BIGINT,status VARCHAR(50),authority VARCHAR(50),ref_id VARCHAR(50),payment_tracking_code VARCHAR(10),verified_at DATETIME NULL) ENGINE=InnoDB")
            c.execute("CREATE TABLE zarinpal_verification_queue (user_id BIGINT,authority VARCHAR(50),status VARCHAR(50)) ENGINE=InnoDB")
            c.execute("CREATE TABLE referrals (referrer_id BIGINT,referred_user_id BIGINT,total_commission BIGINT DEFAULT 0) ENGINE=InnoDB")
            c.execute("CREATE TABLE bot_settings (setting_key VARCHAR(100),setting_value VARCHAR(100)) ENGINE=InnoDB")
            c.execute("CREATE TABLE phone_verification_codes (user_id BIGINT PRIMARY KEY,phone_number VARCHAR(20),verification_code VARCHAR(64),last_code VARCHAR(10),expires_at DATETIME,verification_attempts INT DEFAULT 0) ENGINE=InnoDB")
    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as c:
            for t in ['zarinpal_transactions','zarinpal_verification_queue','referrals','bot_settings','phone_verification_codes']:c.execute('DROP TABLE '+t)
        with connection.schema_editor() as e:
            for m in reversed(cls.legacy): e.delete_model(m)
        super().tearDownClass()
    def setUp(self):
        for m in [Order,Ledger,Product,Category,LegacyUser]:m.objects.all().delete()
        with connection.cursor() as c:
            for t in ['zarinpal_transactions','zarinpal_verification_queue','referrals','bot_settings','phone_verification_codes']:c.execute('DELETE FROM '+t)
        self.user=User.objects.create_user(username='race-user')
        self.wallet=LegacyUser.objects.create(user_id=201,phone_number='09120000003',is_verified=True,balance=1500,referral_code='race')
        self.account=Account.objects.create(user=self.user,phone='09120000003',legacy_id=201)
        cat=Category.objects.create(name='روبیکا')
        self.product=Product.objects.create(category=cat,name='race',price=1000,price_per=1,min_order=1,platform='rubika',show_on_website=True,show_on_telegram=True,need_link=False)
    def race(self,call):
        barrier=Barrier(2)
        def job(index):
            close_old_connections();barrier.wait()
            try:return call(index)
            except BusinessError:return 'denied'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(job,range(2)))
    def test_two_purchases_cannot_overdraw(self):
        results=self.race(lambda i:place_order(self.account,self.product.pk,1,'',uuid.uuid4(),1000))
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,500)
        self.assertEqual(Order.objects.count(),1);self.assertEqual(results.count('denied'),1)
    def test_same_checkout_key_charged_once_concurrently(self):
        key=uuid.uuid4();results=self.race(lambda i:place_order(self.account,self.product.pk,1,'',key,1000).pk)
        self.assertEqual(results[0],results[1]);self.assertEqual(Order.objects.count(),1)
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,500)
    def test_concurrent_refund_credits_once(self):
        order=place_order(self.account,self.product.pk,1,'',uuid.uuid4(),1000)
        results=self.race(lambda i:change_order(None,order.pk,'cancelled','test'))
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,1500)
        self.assertEqual(Ledger.objects.filter(type='refund').count(),1)
    def test_payment_callback_and_worker_credit_once(self):
        authority='A'+'1'*35
        with connection.cursor() as c:c.execute("INSERT INTO zarinpal_transactions (user_id,amount,status,authority,payment_tracking_code) VALUES (201,1000,'pending',%s,'test')",[authority])
        response=Mock();response.json.return_value={'data':{'code':100,'ref_id':987654321}}
        with patch('portal.services.requests.post',return_value=response) as provider:
            results=self.race(lambda i:verify_payment(authority))
        self.assertEqual(provider.call_count,1)
        self.assertEqual(results[0],results[1]);self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,2500)
        self.assertEqual(Ledger.objects.filter(type='deposit').count(),1)
    def test_payment_db_failure_does_not_credit_partially(self):
        authority='A'+'2'*35
        with connection.cursor() as c:c.execute("INSERT INTO zarinpal_transactions (user_id,amount,status,authority,payment_tracking_code) VALUES (201,1000,'pending',%s,'test')",[authority])
        response=Mock();response.json.return_value={'data':{'code':100,'ref_id':123}}
        with patch('portal.services.requests.post',return_value=response),patch('portal.services.PaymentAttempt.objects.filter',side_effect=RuntimeError('db failed')):
            with self.assertRaises(RuntimeError): verify_payment(authority)
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,1500);self.assertFalse(Ledger.objects.exists())
        # Provider code 101 is accepted on retry only while the local record remains uncredited.
        response.json.return_value={'data':{'code':101,'ref_id':123}}
        with patch('portal.services.requests.post',return_value=response): verify_payment(authority)
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,2500)

    def otp_for_bot(self):
        with connection.cursor() as c:c.execute("INSERT INTO phone_verification_codes (user_id,phone_number,verification_code,expires_at) VALUES (201,'09120000003',%s,DATE_ADD(NOW(),INTERVAL 5 MINUTE))",[digest('123456')])
    def test_website_first_account_links_without_losing_money(self):
        src=LegacyUser.objects.create(user_id=-202,phone_number='09120000003',is_verified=True,balance=10000,referral_code='website-link')
        self.account.legacy_id=src.pk;self.account.save()
        order=place_order(self.account,self.product.pk,1,'',uuid.uuid4(),1000)
        self.otp_for_bot();self.assertTrue(verify_bot_phone(201,'123456'))
        self.account.refresh_from_db();self.wallet.refresh_from_db();order.refresh_from_db()
        self.assertEqual(self.account.legacy_id,201);self.assertEqual(order.user_id,201)
        self.assertEqual(self.wallet.balance,10500);self.assertFalse(LegacyUser.objects.filter(pk=-202).exists())
        self.assertEqual(ReferralAlias.objects.get(code='website-link').legacy_id,201)
        self.assertIsNone(Ledger.objects.exclude(user_id=201).first())
        self.assertFalse(verify_bot_phone(201,'123456'))
    def test_bot_phone_cannot_take_another_telegram_account(self):
        self.account.legacy_id=999;self.account.save();self.otp_for_bot()
        with self.assertRaises(BusinessError):verify_bot_phone(201,'123456')
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,1500)
    def test_bot_phone_requires_matching_code(self):
        self.otp_for_bot();self.assertFalse(verify_bot_phone(201,'999999'))
        self.assertTrue(verify_bot_phone(201,'123456'))
