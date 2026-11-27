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

    def test_review_charge_receipt_and_full_refund_include_order_level_tax(self):
        Currency.objects.create(code='USD',name='Dollar',rate=1000)
        self.product.price_currency='USD';self.product.price_amount=Decimal('1.1')
        self.product.product_profit_percent=Decimal('7.5');self.product.save()
        ProductTax.objects.create(product_id=self.product.pk,percent='9.5')
        url=self.product.get_absolute_url()
        response=self.client.get(url)
        # ceil(1.1*1000*1.075) = 1183/pack; quantity 11/100 -> 131; tax = ceil(12.445).
        self.assertEqual(response.context['pricing'].pack,1183)
        self.assertContains(response,'data-tax-bps="950"')
        self.assertEqual(response.context['family'].minimum,131)  # minimum quantity 10
        review=self.client.post(url,{'quantity':11,'target':'test','quoted_total':'1','tax_percent':'0'})
        self.assertContains(review,'مبلغ پیش از مالیات')
        self.assertEqual(review.context['total'],144)
        pending=self.client.session['checkout']
        self.assertEqual(pending['quoted_breakdown'],{'subtotal':131,'tax_bps':950})
        self.client.post('/account/checkout/',{'key':pending['key']})
        order=Order.objects.get()
        self.assertEqual((order.total_price,order.amounts.tax_amount,order.amounts.tax_percent),(144,13,Decimal('9.50')))
        self.assertEqual(order.pk,place_order(self.account,**pending).pk)
        self.assertEqual(list(Ledger.objects.values_list('amount',flat=True)),[-144])
        ProductTax.objects.filter(product_id=self.product.pk).update(percent=50)
        self.assertContains(self.client.get(f'/account/orders/{order.pk}/'),'13 تومان')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/account/orders/{order.pk}/').status_code,404)
        change_order(None,order.pk,'cancelled','test')
        with self.assertRaises(BusinessError): change_order(None,order.pk,'cancelled','again')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance,10000)
        self.assertEqual(Ledger.objects.get(type='refund').amount,144)

    def test_bot_and_web_reject_changed_breakdown_even_if_final_total_matches(self):
        # An old zero-tax review for 1000 must not authorize a 25% tax on 800.
        self.product.price=800;self.product.save()
        ProductTax.objects.create(product_id=self.product.pk,percent=25)
        for old_review in (None,{'subtotal':1000,'tax_bps':0}):
            with self.assertRaises(BusinessError):
                place_order(self.account,self.product.pk,100,'test',uuid.uuid4(),1000,old_review)
            with self.assertRaises(BusinessError):
                place_bot_order(self.wallet.pk,self.product.pk,100,'test',1000,old_review)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Ledger.objects.exists())
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000)

    def test_bot_order_uses_identical_invoice_and_snapshot_is_atomic(self):
        ProductTax.objects.create(product_id=self.product.pk,percent='1.25')
        pricing=pricing_for(Product.objects.get(pk=self.product.pk))
        quote=pricing.quote(100)
        self.assertEqual((quote.subtotal,quote.tax_amount,quote.total),(1000,13,1013))
        args=(self.wallet.pk,self.product.pk,100,'target',1013,quote.breakdown)
        with patch.object(OrderAmounts.objects,'create',side_effect=RuntimeError('invoice write failed')):
            with self.assertRaises(RuntimeError): place_bot_order(*args)
        self.assertFalse(Order.objects.exists());self.assertFalse(Ledger.objects.exists())
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000)
        pk,_=place_bot_order(*args)
        self.assertEqual(Order.objects.get(pk=pk).amounts.tax_amount,13)
        self.assertEqual(Ledger.objects.get(type='withdraw').amount,-1013)
        change_order(None,pk,'cancelled','test')
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000)

    def test_old_order_without_snapshot_displays_its_original_total(self):
        old=Order.objects.create(user=self.wallet,tracking_code='HISTORY',product_id=self.product.pk,
            product_name='Old order',quantity=1,unit_price=5200,total_price=5200)
        ProductTax.objects.create(product_id=self.product.pk,percent=20)
        receipt=self.client.get(f'/account/orders/{old.pk}/')
        self.assertContains(receipt,'5,200 تومان')
        self.assertNotContains(receipt,'مبلغ پیش از مالیات')
        self.assertFalse(OrderAmounts.objects.exists())

    def test_product_admin_set_reset_and_validate_only_this_products_tax(self):
        from django.forms.models import model_to_dict
        url=f'/admin/portal/product/{self.product.pk}/change/'
        data={key:value if value is not None else '' for key,value in model_to_dict(self.product).items()}
        self.user.is_staff=True;self.user.save(update_fields=['is_staff'])
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='view_product'))
        self.assertEqual(self.client.post(url,{**data,'tax_percent':20}).status_code,404)
        self.assertFalse(ProductTax.objects.exists())
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='change_product'))
        self.assertContains(self.client.get(url),'name="tax_percent"')
        self.assertEqual(self.client.post(url,{**data,'tax_percent':'۹٫۵'}).status_code,302)
        self.assertEqual(Product.objects.get(pk=self.product.pk).tax_percent,Decimal('9.50'))
        for invalid in ('-1','100.01','9.555','NaN'):
            result=self.client.post(url,{**data,'tax_percent':invalid})
            self.assertEqual(result.status_code,200)
            self.assertIn('tax_percent',result.context['adminform'].form.errors)
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(Product.objects.get(pk=self.product.pk).tax_percent,Decimal('9.50'))
        self.assertEqual(self.client.post(url,{**data,'tax_percent':'0'}).status_code,302)
        self.assertEqual(price_for(Product.objects.get(pk=self.product.pk),100)[0],1000)
        self.assertEqual(Audit.objects.filter(action='product.tax',actor=self.user).count(),2)

    def _grant_list_permissions(self,*names):
        self.user.is_staff=True
        self.user.save(update_fields=['is_staff'])
        self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label='portal',codename__in=names))

    def _list_state(self,obj,field,on,*,url=None):
        return self.client.post(url or f'/admin/portal/{obj._meta.model_name}/',
                                {'_dp_state':f'{obj.pk}:{field}:{int(on)}'},HTTP_ACCEPT='application/json')

    def test_admin_states_round_trip_on_both_channels_with_a_legacy_neighbor(self):
        from django.contrib.admin.models import LogEntry
        self._grant_list_permissions('change_category','change_product')
        legacy=Product.objects.create(category=self.category,name='خدمات قدیمی تلگرام',price=700,
                                      platform='telegram',show_on_website=True,show_on_telegram=True)
        order=self.buy()
        ProductTax.objects.create(product=self.product,percent='9.5')
        artwork=ProductVisual.objects.create(product_id=self.product.pk,image='day.webp',night_image='night.webp',plan_name='Plus')
        price_history=Order.objects.values().get(pk=order.pk)
        product_url='/admin/portal/product/'
        listing=self.client.get(product_url)
        self.assertContains(listing,'فقط ربات')
        self.assertNotContains(listing,f'value="{legacy.pk}:show_on_website:')
        self.assertNotContains(listing,'form-TOTAL_FORMS')
        for obj,field in [(self.category,'is_active'),(self.product,'is_active'),
                          (self.product,'show_on_website'),(self.product,'show_on_telegram')]:
            for on in (False,True):
                with self.subTest(model=obj._meta.model_name,field=field,on=on):
                    result=self._list_state(obj,field,on)
                    self.assertEqual(result.status_code,200,result.content)
                    self.assertIs(result.json()['checked'],on)
                    self.assertIs(getattr(type(obj).objects.get(pk=obj.pk),field),on)
                    fresh=self.client.get(f'/admin/portal/{obj._meta.model_name}/')
                    self.assertContains(fresh,f'value="{obj.pk}:{field}:{int(not on)}"')
                    self.assertEqual(public_products().filter(pk=self.product.pk).exists(),on or field=='show_on_telegram')
                    self.assertEqual(bot_products().filter(pk=self.product.pk).exists(),on or field=='show_on_website')
                    # Re-sending the same desired state is a no-op on disk and in both logs.
                    audit_count=Audit.objects.count()
                    log_count=LogEntry.objects.count()
                    self.assertIs(self._list_state(obj,field,on).json()['checked'],on)
                    self.assertEqual((Audit.objects.count(),LogEntry.objects.count()),(audit_count,log_count))
        self.assertEqual(Audit.objects.filter(actor=self.user,action='product.update').count(),6)
        self.assertEqual(Order.objects.values().get(pk=order.pk),price_history)
        self.assertEqual(ProductTax.objects.get(product=self.product).percent,Decimal('9.50'))
        artwork.refresh_from_db()
        self.assertEqual((artwork.image.name,artwork.night_image.name,artwork.plan_name),('day.webp','night.webp','Plus'))
        legacy.refresh_from_db()
        self.assertTrue(legacy.show_on_website and legacy.show_on_telegram and legacy.is_active)
        self.assertFalse(public_products().filter(pk=legacy.pk).exists())

    def test_legacy_web_flag_is_inert_and_other_activation_still_validates(self):
        self._grant_list_permissions('change_product')
        p=self.product
        Product.objects.filter(pk=p.pk).update(platform='telegram')
        self.assertIs(self.client.get(f'/admin/portal/product/{p.pk}/change/').context['adminform'].form['show_on_website'].value(),False)
        self.assertEqual(self._list_state(p,'show_on_website',True).status_code,422)
        for field in ('show_on_telegram','is_active'):
            for on in (False,True):
                result=self._list_state(p,field,on)
                self.assertEqual(result.status_code,200,result.content)
                self.assertEqual(bot_products().filter(pk=p.pk).exists(),on)
                self.assertFalse(public_products().filter(pk=p.pk).exists())
                p.refresh_from_db()
                self.assertTrue(p.show_on_website)
        Product.objects.filter(pk=p.pk).update(price=0)
        self.assertEqual(self._list_state(p,'is_active',False).status_code,200)
        before=Audit.objects.count()
        rejected=self._list_state(p,'is_active',True)
        self.assertEqual(rejected.status_code,422)
        self.assertIn('قیمت پایه تومان',rejected.json()['message'])
        self.assertIs(rejected.json()['checked'],False)
        self.assertFalse(Product.objects.get(pk=p.pk).is_active)
        self.assertEqual(Audit.objects.count(),before)

    def test_web_filter_respects_channel_policy_and_native_post_rebuilds_results(self):
        self._grant_list_permissions('change_product')
        blocked=Product.objects.create(name='Bot service',category=self.category,price=900,platform='telegram',show_on_website=True)
        linked=Product.objects.create(name='Linked SKU',category=self.category,price=900,platform='other',show_on_website=True)
        SourceProduct.objects.create(product_id=linked.pk,source='premstore',external_id='test',last_price=900,available=True)
        base='/admin/portal/product/?show_on_website__exact='
        rows=lambda suffix: set(self.client.get(base+suffix).context['cl'].result_list.values_list('pk',flat=True))
        self.assertEqual(rows('1&_facets=1'),{self.product.pk,linked.pk})
        self.assertEqual(rows('blocked'),{blocked.pk})
        path=base+'1'
        response=self.client.post(path,{'_dp_state':f'{linked.pk}:show_on_website:0'},follow=True)
        self.assertEqual(response.redirect_chain,[(path,302)])
        self.assertNotContains(response,f'value="{linked.pk}:show_on_website:')
        self.assertContains(response,'ذخیره شد')
        self.assertEqual(rows('0'),{linked.pk})

    def test_state_permissions_csrf_and_row_scoping(self):
        from django.contrib import admin
        product_admin=admin.site._registry[Product]
        p=self.product
        url='/admin/portal/product/'
        self._grant_list_permissions('view_product')
        self.assertNotContains(self.client.get(url),'name="_dp_state"')
        self.assertEqual(self._list_state(p,'is_active',False).status_code,404)
        self._grant_list_permissions('change_product')
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get(url)
        self.assertEqual(client.post(url,{'_dp_state':f'{p.pk}:is_active:0'}).status_code,403)
        self.assertEqual(self._list_state(p,'is_active',False,url=url+'?_popup=1').status_code,404)
        self.assertEqual(self._list_state(p,'price',False).status_code,400)
        with patch.object(product_admin,'get_queryset',return_value=Product.objects.exclude(pk=p.pk)):
            self.assertEqual(self._list_state(p,'is_active',False).status_code,404)
        with patch.object(product_admin,'has_change_permission',side_effect=lambda _,obj=None: obj is None):
            self.assertNotContains(self.client.get(url),'name="_dp_state"')
            self.assertEqual(self._list_state(p,'is_active',False).status_code,404)
        with patch.object(product_admin,'get_readonly_fields',return_value=('is_active',)):
            self.assertNotContains(self.client.get(url),f'value="{p.pk}:is_active:')
            self.assertEqual(self._list_state(p,'is_active',False).status_code,404)
        self.assertFalse(Audit.objects.exists())
        self.assertTrue(Product.objects.get(pk=p.pk).is_active)

    def test_state_and_both_audit_logs_commit_together(self):
        from django.contrib import admin
        self._grant_list_permissions('change_category')
        with patch.object(admin.site._registry[Category],'log_change',side_effect=RuntimeError('log unavailable')):
            with self.assertRaises(RuntimeError):
                self._list_state(self.category,'is_active',False)
        self.assertTrue(Category.objects.get(pk=self.category.pk).is_active)
        self.assertFalse(Audit.objects.exists())

    def test_redeployment_preserves_explicit_bot_only_products_in_rubika_categories(self):
        if connection.vendor!='mysql':
            self.skipTest('Legacy schema preparation runs only on MariaDB')
        from io import StringIO
        from django.core.management import call_command
        Product.objects.filter(pk=self.product.pk).update(platform='telegram',show_on_website=False)
        with connection.cursor() as cursor:
            cursor.execute('CREATE TEMPORARY TABLE phone_verification_codes (verification_code VARCHAR(64) NULL,last_code VARCHAR(8) NULL,expires_at DATETIME NULL)')
            try:
                call_command('prepare_portal',stdout=StringIO())
            finally:
                cursor.execute('DROP TEMPORARY TABLE phone_verification_codes')
        self.product.refresh_from_db()
        self.assertEqual((self.product.platform,self.product.show_on_website,self.product.show_on_telegram),('telegram',False,True))

    def test_other_operational_flags_preserve_related_values(self):
        self._grant_list_permissions('change_campaign','change_post','change_currency','change_giftcode')
        campaign=Campaign.objects.create(name='Ad',code='ad',clicks=40,registrations=2)
        post=Post.objects.create(title='Story',slug='story',summary='Short',body='Long',author=self.user)
        currency=Currency.objects.create(code='USD',name='Dollar',rate=90000)
        gift=GiftCode.objects.create(code='TEST',amount=5000,used_count=2,created_by=self.user.pk)
        for obj,field in [(campaign,'active'),(post,'published'),(currency,'is_active'),(gift,'is_active')]:
            for on in (not getattr(obj,field),getattr(obj,field)):
                result=self._list_state(obj,field,on)
                self.assertEqual(result.status_code,200,result.content)
                self.assertIs(getattr(type(obj).objects.get(pk=obj.pk),field),on)
        campaign.refresh_from_db();currency.refresh_from_db();gift.refresh_from_db()
        self.assertEqual((campaign.clicks,campaign.registrations,currency.rate,gift.used_count,gift.amount),(40,2,90000,2,5000))

    def test_affordability_and_max_charge_use_tax_on_the_whole_quantity(self):
        from .pricing import Pricing
        p=Pricing(pack=11,price_per=10,min_order=2,max_order=100,tax_bps=950)
        for balance in range(25):
            self.assertEqual(p.affordable(balance),max((n for n in range(2,101) if p.quote(n).total<=balance),default=0))
        p=Pricing(pack=100000000000,price_per=1,min_order=1,max_order=1,tax_bps=1)
        with self.assertRaises(BusinessError): p.quote(1)
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

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[42,'42',-100],'token':'test-value'}})
    def test_purchase_alerts_are_committed_once_and_failures_do_not_repeat_or_reverse_orders(self):
        from django.db import transaction
        from .order_notices import dispatch,claim,prepare
        with patch('portal.order_notices.requests.post') as api:
            with self.assertRaises(RuntimeError),transaction.atomic():
                self.buy(uuid.uuid4())
                raise RuntimeError('rollback')
            self.assertFalse(OrderEvent.objects.exists())
            key=uuid.uuid4();web=self.buy(key);self.assertEqual(self.buy(key).pk,web.pk)
            bot,tracking=place_bot_order(self.wallet.pk,self.product.pk,100,'private delivery data',1000)
            api.assert_not_called()
            self.assertEqual(list(OrderEvent.objects.order_by('pk').values_list('order_id','channel')),[(web.pk,'web'),(bot,'telegram')])
            prepare(10)
            first=claim()
            self.assertEqual(first.event_id,web.pk)
            api.return_value=Mock(status_code=429);api.return_value.json.return_value={'parameters':{'retry_after':90}}
            self.assertEqual(dispatch(),{'sent':0,'retry':1,'stopped':0})
            self.assertIsNone(claim())
            # Worker restart: reclaim an expired lease, honour successful deliveries.
            OrderDelivery.objects.all().update(due_at=timezone.now()-timedelta(seconds=2))
            api.return_value=Mock(status_code=200);api.return_value.json.return_value={'ok':True,'result':{'chat':{'id':42},'message_id':7}}
            self.assertEqual(dispatch(),{'sent':2,'retry':0,'stopped':0})
            self.assertEqual(dispatch(),{'sent':0,'retry':0,'stopped':0})
            self.assertEqual(api.call_count,3)
            alerts=[c.kwargs['json'] for c in api.call_args_list[-2:]]
            self.assertTrue(all(a['chat_id']==42 and a['disable_notification'] is False for a in alerts))
            web_msg=next(a for a in alerts if web.tracking_code in a['text'])
            bot_msg=next(a for a in alerts if tracking in a['text'])
            self.assertIn('سایت',web_msg['text']);self.assertIn('ربات',bot_msg['text'])
            self.assertIn('1,000 تومان',bot_msg['text']);self.assertNotIn('private delivery data',str(alerts))
            self.assertIn(f'confirmorder_{bot}',str(bot_msg['reply_markup']));self.assertNotIn('callback_data',str(web_msg))
        self.assertEqual(Ledger.objects.filter(type='withdraw').count(),2)
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,8000)
        path='/admin/order-alerts/'
        self.assertEqual(self.client.get(path).status_code,404)
        self._grant_list_permissions('view_currency')
        self.assertEqual(self.client.get(path).status_code,404)
        self._grant_list_permissions('view_order')
        page=self.client.get(path)
        self.assertIn('no-store',page['Cache-Control']);self.assertEqual([e['tracking'] for e in page.json()['orders']],[tracking,web.tracking_code])

    def test_order_alert_never_sends_to_a_removed_or_unconfigured_recipient(self):
        from .order_notices import prepare,dispatch,recipients
        web=self.buy(uuid.uuid4())
        with override_settings(BOT_CONFIG={'telegram':{'admin_ids':'777'}}):
            self.assertEqual(recipients(),[]);prepare(5)
        self.assertFalse(OrderEvent.objects.get(pk=web.pk).prepared)
        with override_settings(BOT_CONFIG={'telegram':{'admin_ids':[777]}}):prepare(5)
        with override_settings(BOT_CONFIG={'telegram':{'admin_ids':[888]}}),patch('portal.order_notices.requests.post') as api:
            self.assertEqual(dispatch()['stopped'],1);api.assert_not_called()
        self.assertEqual(OrderDelivery.objects.get().last_error,'recipient_removed')

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[111,222],'token':'test'}})
    def test_order_and_staff_alert_categories_are_independent(self):
        from .order_notices import dispatch
        NoticePreference.objects.create(recipient=111,enabled=['web_order','order_status'])
        NoticePreference.objects.create(recipient=222,enabled=['bot_order','catalog'])
        web=self.buy(uuid.uuid4())
        bpk,_=place_bot_order(self.wallet.pk,self.product.pk,100,'detail',1000)
        change_order(None,bpk,'confirmed','private note',telegram_admin_id=111)
        self._grant_list_permissions('change_product')
        path='/admin/portal/product/'
        self.client.post(path,{'_dp_state':f'{self.product.pk}:show_on_website:0'})
        # Both the Django admin log and merchant audit were written, but only one activity alert.
        self.assertEqual(OperationNotice.objects.filter(topic='catalog',reference=str(self.product.pk)).count(),1)
        with patch('portal.order_notices.requests.post') as send:
            def ok(*a,**kw):
                r=Mock(status_code=200);r.json.return_value={'ok':True,'result':{'chat':{'id':kw['json']['chat_id']},'message_id':1}};return r
            send.side_effect=ok
            self.assertEqual(dispatch()['sent'],4)
            self.assertEqual(dispatch()['sent'],0)
            pairs={(r['chat_id'],r['text'].splitlines()[0]) for c in send.call_args_list for r in [c.kwargs['json']]}
            self.assertTrue(any(r==111 and 'سفارش جدید از سایت' in txt for r,txt in pairs))
            self.assertTrue(any(r==222 and 'سفارش جدید از ربات' in txt for r,txt in pairs))
        self.assertEqual(OrderDelivery.objects.get(event_id=web.pk).recipient,111)
        self.assertEqual(OrderDelivery.objects.get(event_id=bpk).recipient,222)
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
            from django.templatetags.static import static
            from .product_art import gallery_path
            self.assertEqual(product_image(self.product,'dark'),static(gallery_path(None)))
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
            response=self.client.post('/admin/portal/product/'+str(self.product.pk)+'/change/',data)
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
        self.assertEqual(self.client.get('/admin/portal/product/').status_code,404)

    def test_admin_routes_hide_from_unauthorized_users(self):
        for client in [Client(),self.client]:
            for path in ['/admin','/admin/','/admin/login/','/admin/portal/product/','/admin/jsi18n/','/manage/']:
                self.assertEqual(client.get(path).status_code,404,path)
            self.assertEqual(client.post('/admin/login/',{}).status_code,404)
        self.user.is_staff=True;self.user.save()
        self.assertEqual(self.client.get('/admin/').status_code,404)
        self.user.is_superuser=True;self.user.save()
        self.assertTemplateUsed(self.client.get('/admin/'),'admin/dashboard.html')
        self.assertContains(self.client.get('/admin/portal/product/'),'admin-panel.css')
        response=self.client.get('/admin/')
        self.assertIn('noindex',response['X-Robots-Tag'])
        self.assertIn('no-store',response['Cache-Control'])

    def test_store_dashboard_data_respects_staff_permissions(self):
        self.buy()
        self.user.is_staff=True;self.user.save()
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='view_product'))
        response=self.client.get('/admin/')
        self.assertNotIn('recent_orders',response.context)
        self.assertNotIn('completed_revenue',response.context)
        self.assertNotIn('recent_tickets',response.context)
        self.assertNotIn('sales_chart',response.context)
        self.assertNotContains(response,'sales-chart-data')
        self.assertNotContains(response,'href="/admin/portal/product/add/"')
        self.user.is_superuser=True;self.user.save()
        response=self.client.get('/admin/')
        self.assertEqual(response.context['pending_orders_count'],1)
        self.assertEqual(response.context['completed_revenue'],0)
        self.assertEqual(len(response.context['recent_orders']),1)

    def test_dashboard_chart_fills_dates_and_counts_completed_sales_only(self):
        import json
        import re
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save()
        order=self.buy()
        now=timezone.now()
        Order.objects.filter(pk=order.pk).update(status='completed',completed_at=now)
        self.buy()
        response=self.client.get('/admin/?period=week')
        chart=response.context['sales_chart']
        self.assertEqual(len(chart),7)
        self.assertEqual(sum(row['amount'] for row in chart),order.total_price)
        self.assertEqual(chart[-1]['label'],timezone.localdate().isoformat())
        self.assertEqual(chart[-1]['amount'],order.total_price)
        self.assertEqual(response.context['today_sales'],order.total_price)
        rendered=response.content.decode()
        self.assertEqual(json.loads(re.search(r'<script id="sales-chart-data" type="application/json">(.*?)</script>',rendered).group(1)),chart)
        self.assertNotIn('<details open>',rendered)
        response=self.client.get('/admin/?period=custom&start=invalid&end=2030-01-01')
        self.assertTrue(response.context['report_error'])
        self.assertEqual(len(response.context['sales_chart']),7)
        response=self.client.get('/admin/?period=year')
        self.assertTrue(response.context['monthly_buckets'])
        self.assertIn(len(response.context['sales_chart']),[12,13])
        self.assertEqual(sum(row['amount'] for row in response.context['sales_chart']),order.total_price)

    def test_overview_groups_completed_sales_at_tehran_nowruz_midnight(self):
        from datetime import date, datetime, timezone as tz
        from .admin_overview import sales_report
        for minute in (29,30):
            order=self.buy()
            Order.objects.filter(pk=order.pk).update(status='completed',
                completed_at=datetime(2025,3,20,20,minute,tzinfo=tz.utc))
        report=sales_report({'period':'custom','start':'2025-02-01','end':'2025-05-05'}, date(2025,5,5))
        self.assertTrue(report['monthly_buckets'])
        self.assertEqual([(r['display'],r['amount']) for r in report['sales_chart'] if r['amount']],
                         [('اسفند ۱۴۰۳',1000),('فروردین ۱۴۰۴',1000)])
        self.assertEqual(report['range_order_count'],2)

    def test_dashboard_support_queue_does_not_include_answered_or_financial_work(self):
        self.user.is_staff=True;self.user.save()
        self.user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='view_ticket'))
        for status in ('open','answered','closed'):
            Ticket.objects.create(user=self.other,subject='نمونه '+status,status=status)
        self.buy()
        page=self.client.get('/admin/')
        items=page.context['desk_tasks']
        self.assertEqual([(t['href'],t['count']) for t in items],[('/admin/portal/ticket/?status__exact=open',1)])
        self.assertEqual(len(page.context['recent_tickets']),2)
        self.assertNotContains(page,'sales-chart-data')
        self.assertNotContains(page,'/admin/portal/order/')
        self.assertNotContains(page,'/admin/portal/sourceproduct/')
        self.assertEqual(self.client.get(items[0]['href']).context['cl'].result_count,1)

    def test_admin_can_add_website_product_with_independent_bot_visibility(self):
        self.user.is_staff=True;self.user.is_superuser=True;self.user.save()
        response=self.client.get('/admin/portal/product/add/')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['adminform'].form.initial['show_on_website'])
        data={'name':'اشتراک نمونه','category':self.category.pk,'platform':'ai','price':'500000','price_per':'1','min_order':'1','is_active':'on','show_on_website':'on','price_currency':'TOMAN','product_profit_percent':'0','target_type':'email','need_link':'on','_save':'ذخیره'}
        response=self.client.post('/admin/portal/product/add/',data)
        self.assertEqual(response.status_code,302)
        product=Product.objects.get(name='اشتراک نمونه')
        self.assertTrue(product.show_on_website)
        self.assertFalse(product.show_on_telegram)
        self.assertEqual(product.price,500000)
        self.assertEqual(product.target_type,'email')
        self.assertTrue(Audit.objects.filter(action='product.create',object_ref=str(product.pk)).exists())

    def test_profile_update_is_private_encrypted_and_scoped(self):
        import json
        from portal.profile import profile_cipher
        other_before=self.other.first_name
        response=self.client.post('/account/profile/',{'first_name':'نام نمونه','last_name':'آزمایشی','email':'example@example.com','national_code':'۰۱۲۳۴۵۶۷۸۹','birth_date':'۱۳۸۰/۰۱/۱۵','province':'تهران','city':'تهران','user_id':self.other.pk,'is_staff':'1','phone':'09000000000'})
        self.assertRedirects(response,'/account/profile/')
        self.user.refresh_from_db();self.other.refresh_from_db();self.account.refresh_from_db()
        self.assertEqual(self.user.get_full_name(),'نام نمونه آزمایشی')
        self.assertFalse(self.user.is_staff)
        self.assertEqual(self.other.first_name,other_before)
        self.assertEqual(self.account.phone,self.user.username)
        ciphertext=self.account.national_code_encrypted
        self.assertNotIn('0123456789',ciphertext)
        self.assertEqual(profile_cipher().decrypt(ciphertext.encode()),b'0123456789')
        self.assertEqual(self.account.birth_date.isoformat(),'2001-04-04')
        page=self.client.get('/account/profile/')
        self.assertNotContains(page,'0123456789');self.assertNotContains(page,ciphertext)
        self.assertIn('no-store',page['Cache-Control'])
        self.assertIn('noindex',page['X-Robots-Tag'])
        self.assertNotIn('0123456789',json.dumps(Audit.objects.get(action='profile.update').details))
        self.client.post('/account/profile/',{'first_name':'نام نمونه','last_name':'آزمایشی'})
        self.account.refresh_from_db();self.assertEqual(self.account.national_code_encrypted,ciphertext)
        self.client.post('/account/profile/',{'clear_national_code':'on'})
        self.account.refresh_from_db();self.assertEqual(self.account.national_code_encrypted,'')

    def test_profile_rejects_invalid_identity_without_partial_save(self):
        for values in [{'national_code':'1111111111'},{'national_code':'0123456788'},{'birth_date':'۱۴۰۰/۱۲/۳۰'},{'birth_date':'۱۵۰۰/۰۱/۰۱'},{'email':'bad-email'}]:
            response=self.client.post('/account/profile/',{'first_name':'نباید ذخیره شود',**values})
            self.assertEqual(response.status_code,200)
            self.user.refresh_from_db();self.assertNotEqual(self.user.first_name,'نباید ذخیره شود')
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post('/account/profile/',{'first_name':'CSRF'}).status_code,403)
        self.assertEqual(Client().get('/account/profile/').status_code,302)

    def test_paginated_seo_and_breadcrumbs_are_consistent(self):
        for i in range(20):Post.objects.create(title='مقاله '+str(i),slug='seo-page-'+str(i),summary='راهنمای نمونه',body='متن',published=True,author=self.user)
        response=self.client.get('/blog/?page=2')
        self.assertContains(response,'https://dawnpanel.ir/blog/?page=2')
        self.assertContains(response,'صفحه 2')
        self.assertContains(response,'index,follow,max-image-preview:large')
        response=self.client.get(self.product.get_absolute_url())
        self.assertContains(response,'BreadcrumbList')
        self.assertContains(self.client.get('/robots.txt'),'Disallow: /admin')

    def test_indexable_categories_agree_with_links_sitemap_and_private_filters(self):
        from xml.etree import ElementTree
        from django.urls import reverse
        path=reverse('catalog_section',args=['rubika'])
        self.assertRedirects(self.client.get('/services/?section=rubika'),path,status_code=301)
        page=self.client.get(path)
        self.assertContains(page,'index,follow,max-image-preview:large')
        self.assertContains(page,'<link rel="canonical" href="https://dawnpanel.ir'+path+'">')
        self.assertContains(page,'CollectionPage');self.assertContains(page,'خدمات کانال روبیکا')
        self.assertContains(self.client.get(path,{'q':'جستجو'}),'noindex,follow')
        self.assertEqual(self.client.get(path,{'page':'9999'}).status_code,404)
        self.assertEqual(self.client.get('/services/category/telegram/').status_code,404)
        self.assertContains(self.client.get('/services/category/eitaa/'),'noindex,follow')
        urls=[n.text for n in ElementTree.fromstring(self.client.get('/sitemap.xml').content).findall('{*}url/{*}loc')]
        self.assertIn('https://dawnpanel.ir'+path,urls);self.assertIn('https://dawnpanel.ir/rates/',urls)
        self.assertNotIn('https://dawnpanel.ir/services/category/eitaa/',urls)
        self.assertEqual(len(urls),len(set(urls)))
        with override_settings(GOOGLE_SITE_VERIFICATION='operator-verification'):
            self.assertContains(self.client.get('/'),'<meta name="google-site-verification" content="operator-verification">')
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

    def test_login_session_persists_for_180_days_without_sliding(self):
        from django.contrib.sessions.models import Session
        client=Client()
        session=client.session
        session['otp_id']=str(uuid.uuid4());session['otp_phone']=self.account.phone;session.save()
        started=timezone.now()
        with patch('portal.views.verify_otp',return_value=self.account.phone):
            response=client.post('/login/verify/',{'code':'123456'})
        self.assertEqual(response.status_code,302)
        session=client.session
        self.assertEqual(int(session['_auth_user_id']),self.user.pk)
        deadline=session.get_expiry_date()
        self.assertAlmostEqual((deadline-started).total_seconds(),180*86400,delta=5)
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertTrue(response.cookies['sessionid']['expires'])
        self.assertTrue(response.cookies['sessionid']['httponly'])
        with patch('django.utils.timezone.now',return_value=started+timedelta(days=179)):
            self.assertEqual(client.get('/account/').status_code,200)
            session=client.session;session['checkout']={'example':'session modification'};session.save()
            self.assertEqual(Session.objects.get(session_key=session.session_key).expire_date,deadline)
        with patch('django.utils.timezone.now',return_value=deadline+timedelta(seconds=1)):
            self.assertEqual(client.get('/account/').status_code,302)

    def test_guest_order_returns_to_exact_product_after_localized_otp(self):
        client=Client()
        url=self.product.get_absolute_url()
        self.assertRedirects(client.post(url,{'quantity':20,'target':'sample-delivery'}),'/login/',fetch_redirect_response=False)
        draft=client.session['order_draft']
        self.assertEqual(draft['product_id'],self.product.pk)
        self.assertNotIn('target',draft)
        self.assertContains(client.get('/login/'),'به پلن انتخابی برمی‌گردی')
        session=client.session
        otp=OTP.objects.create(phone=self.account.phone,code_hash=digest('123456'),
                               session_hash=digest(session.session_key),expires_at=timezone.now()+timedelta(minutes=5))
        session['otp_id']=str(otp.pk);session.save()
        self.assertRedirects(client.post('/login/verify/',{'code':'۱۲۳٤۵۶'}),url,fetch_redirect_response=False)
        restored=client.get(url)
        self.assertEqual(restored.context['form']['quantity'].value(),20)
        self.assertNotContains(restored,'sample-delivery')
        self.assertIn('no-store',restored['Cache-Control'])
        review=client.post(url,{'quantity':20,'target':'sample-delivery'})
        self.assertTemplateUsed(review,'review.html')
        self.assertEqual(review.context['total'],price_for(self.product,20)[0])
        self.assertContains(review,'noindex,nofollow')
        self.assertIn('no-store',review['Cache-Control'])
        self.assertNotIn('order_draft',client.session)
        self.assertFalse(Order.objects.filter(product_id=self.product.pk).exists())

    def test_login_resumes_local_account_destination(self):
        client=Client()
        self.assertRedirects(client.get('/account/charge/'),'/login/?next=/account/charge/',fetch_redirect_response=False)
        client.get('/login/',{'next':'/account/charge/'})
        session=client.session
        session['otp_id']=str(uuid.uuid4());session.save()
        with patch('portal.views.verify_otp',return_value=self.account.phone):
            response=client.post('/login/verify/',{'code':'123456'})
        self.assertRedirects(response,'/account/charge/',fetch_redirect_response=False)

    def test_stale_guest_draft_is_not_restored(self):
        session=self.client.session
        session['order_draft']={'product_id':self.product.pk,'quantity':20,
                                'at':(timezone.now()-timedelta(minutes=21)).timestamp()}
        session.save()
        response=self.client.get(self.product.get_absolute_url())
        self.assertFalse(response.context['restored'])
        self.assertNotIn('order_draft',self.client.session)
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

    def _fx_selection(self,*currencies):
        page=self.client.get('/admin/portal/currency/review/')
        self.assertEqual(page.status_code,200)
        selected={r.pk for r in currencies}
        data={'_publish':1,'selected':list(selected)}
        for card in page.context['cards']:
            if card['row'].pk not in selected:continue
            form=card['form']
            for key in form.fields:
                val=form.initial[key]
                if val is not False:data[form.add_prefix(key)]='on' if val is True else val
        return data

    def test_exchange_feed_updates_quote_not_product_or_wallet_and_requotes_both_channels(self):
        from .exchange_rates import refresh_rates
        from .test_exchange_rates import book
        now=timezone.now()
        currency=Currency.objects.create(code='USDT',name='تتر',rate=85000,type='crypto')
        old=Currency.objects.create(code='STAR',name='Stars',rate=1200,type='telegram',is_active=False)
        self.product.price_currency='USDT';self.product.price_amount=Decimal('0.01')
        self.product.price_per=1;self.product.product_profit_percent=10;self.product.save()
        ProductTax.objects.create(product=self.product,percent=10)
        with patch('portal.exchange_rates.fetch_source',return_value={'USDTIRT':book(now)}):
            self.assertEqual(refresh_rates([currency.pk],bootstrap=True),{'USDT':''})
        self._grant_list_permissions('change_currency')
        path='/admin/portal/currency/review/'
        with self.assertRaises(BusinessError):pricing_for(self.product)
        self.assertRedirects(self.client.post(path,self._fx_selection(currency)),'/admin/portal/currency/',fetch_redirect_response=False)
        self.assertFalse(CurrencyPricing.objects.filter(currency=old).exists())
        self.assertEqual(Currency.objects.get(pk=currency.pk).rate,85000)
        self.assertEqual(Product.objects.get(pk=self.product.pk).price,1000)
        # .01 USDT × 285000 sale rate × 1.10 product markup = 3135; tax on the order.
        quote=pricing_for(self.product).quote(10)
        self.assertEqual((quote.subtotal,quote.tax_amount,quote.total),(31350,3135,34485))
        board=self.client.get('/rates/')
        self.assertContains(board,'۲۷۰٬۰۰۰');self.assertContains(board,'۲۸۵٬۰۰۰');self.assertNotContains(board,'Stars')
        self.assertIn('no-store',board['Cache-Control'])
        self.wallet.balance=100000;self.wallet.save()
        target='test'
        with patch('portal.exchange_rates.fetch_source',return_value={'USDTIRT':book(now+timedelta(seconds=1),'2900000','2900000')}):
            self.assertEqual(refresh_rates(),{'USDT':''})
        self.assertEqual(pricing_for(self.product).quote(10),quote)
        self.assertRedirects(self.client.post(path,self._fx_selection(currency)),'/admin/portal/currency/',fetch_redirect_response=False)
        for attempt in (lambda:place_order(self.account,self.product.pk,10,target,uuid.uuid4(),quote.total,quote.breakdown),
                        lambda:place_bot_order(self.wallet.pk,self.product.pk,10,target,quote.total,quote.breakdown)):
            with self.assertRaises(BusinessError):attempt()
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,100000);self.assertFalse(Ledger.objects.exists())
        fresh=pricing_for(self.product).quote(10)
        self.assertEqual(fresh.total,35695)
        order=place_order(self.account,self.product.pk,10,target,uuid.uuid4(),fresh.total,fresh.breakdown)
        self.assertEqual(order.total_price,35695)
        change_order(None,order.pk,'cancelled','test')
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,100000)

    def test_market_failure_retains_real_timestamp_and_never_revives_an_old_price(self):
        from .exchange_rates import refresh_rates,currency_rates,RateError
        from .test_exchange_rates import book
        currency=Currency.objects.create(code='USDT',name='تتر',rate=85000)
        at=timezone.now()-timedelta(minutes=1)
        with patch('portal.exchange_rates.fetch_source',return_value={'USDTIRT':book(at)}):
            refresh_rates(bootstrap=True)
        self._grant_list_permissions('change_currency')
        self.client.post('/admin/portal/currency/review/',self._fx_selection(currency))
        before=CurrencyPricing.objects.get(currency=currency)
        for data in ({},{'USDTIRT':book(at-timedelta(seconds=10),'2000000','2000000')},
                     {'USDTIRT':book(at,'2000000','2000000')}):
            with patch('portal.exchange_rates.fetch_source',return_value=data):
                self.assertTrue(refresh_rates()['USDT'])
            policy=CurrencyPricing.objects.get(currency=currency)
            self.assertEqual((policy.market_bid,policy.observed_at),(before.market_bid,before.observed_at))
            self.assertEqual((policy.candidate_bid,policy.candidate_at),(before.candidate_bid,before.candidate_at))
            self.assertTrue(policy.last_error)
        with self.assertRaises(RateError):
            currency_rates(Currency.objects.get(pk=currency.pk),now=at+timedelta(minutes=12))
        CurrencyPricing.objects.filter(currency=currency).update(source='manual',sell_extra=100,buy_less=200)
        with patch('portal.exchange_rates.fetch_source') as fetcher:
            self.assertEqual(refresh_rates(bootstrap=True),{})
            fetcher.assert_not_called()
        self.assertEqual(currency_rates(Currency.objects.get(pk=currency.pk)).sell,85100)

    def test_review_stars_discount_and_concurrent_currency_selection(self):
        from .exchange_rates import currency_rates,refresh_rates,Rates
        from .test_exchange_rates import book
        cur=Currency.objects.create(name='Stars',code='STAR',type='telegram',rate=3000,is_active=False)
        CurrencyPricing.objects.create(currency=cur,source='manual')
        coin=Currency.objects.create(name='Tether',code='USDT',rate=280000)
        url='/admin/portal/currency/review/'
        self._grant_list_permissions('view_currency')
        with patch('portal.exchange_rates.fetch_source') as fetch:
            self.assertEqual(self.client.post(url,{'_fetch':1}).status_code,404)
            fetch.assert_not_called()
        self._grant_list_permissions('change_currency')
        guarded=Client(enforce_csrf_checks=True);guarded.force_login(self.user)
        self.assertEqual(guarded.post(url,{'_fetch':1}).status_code,403)
        now=timezone.now()
        with patch('portal.exchange_rates.fetch_source',return_value={'USDTIRT':book(now)}):refresh_rates(bootstrap=True)
        selected=self._fx_selection(cur,coin)
        selected[f'r{cur.pk}-active']='on';selected[f'r{cur.pk}-less']='۱۲٫۵'
        selected[f'r{coin.pk}-basis_buy']='279000';selected[f'r{coin.pk}-basis_sell']='281000'
        with patch('portal.exchange_rates.fetch_source',return_value={'USDTIRT':book(now+timedelta(seconds=1),'2800000','2800100')}):
            self.assertRedirects(self.client.post(url,{'_fetch':1}),url,fetch_redirect_response=False)
        self.client.post(url,selected)
        cur.refresh_from_db();self.assertFalse(cur.is_active)
        self.assertFalse(Audit.objects.filter(action='currency.publish').exists())
        fresh=self._fx_selection(cur,coin)
        for field in ('active','less'):fresh[f'r{cur.pk}-{field}']=selected[f'r{cur.pk}-{field}']
        for field in ('basis_buy','basis_sell'):fresh[f'r{coin.pk}-{field}']=selected[f'r{coin.pk}-{field}']
        self.assertRedirects(self.client.post(url,fresh),'/admin/portal/currency/',fetch_redirect_response=False)
        self.assertEqual(currency_rates(Currency.objects.get(pk=cur.pk)),Rates(2625,3000))
        self.assertEqual(currency_rates(Currency.objects.get(pk=coin.pk)),Rates(269000,286000))
        self.client.post(url,fresh)
        self.assertEqual(Audit.objects.filter(action='currency.publish').count(),2)

    def test_denapanel_stars_from_bootstrap_through_review_and_expiry(self):
        from .exchange_rates import Rates, RateError, currency_rates, refresh_rates, source_link
        from .test_exchange_rates import dena_page,stars_html
        cur=Currency.objects.create(code='STAR',type='telegram',name='استارز',rate=3000,is_active=False)
        self._grant_list_permissions('change_currency')
        url=f'/admin/portal/currency/review/?rows={cur.pk}'
        with patch('portal.supplier_clients.read_json',return_value=dena_page(stars_html().replace('1161','1239'))):
            self.assertTrue(refresh_rates([cur.pk],bootstrap=True)['STAR'])
        self.assertFalse(CurrencyPricing.objects.filter(currency=cur).exists())
        with patch('portal.supplier_clients.read_json',return_value=dena_page(stars_html())):
            self.assertEqual(refresh_rates([cur.pk],bootstrap=True),{'STAR':''})
        p=CurrencyPricing.objects.get(currency=cur)
        self.assertEqual((p.source,p.candidate_bid,p.candidate_ask,p.buy_less,p.market_bid,p.published_at),
                         ('denapanel',4560,4560,0,None,None))
        self.assertNotContains(self.client.get('/rates/'),'STAR')
        page=self.client.get(url)
        for text in ('۴٬۵۶۰٬۰۰۰','۱٬۰۰۰','۴٬۵۶۰ تومان','۴٬۱۰۴',source_link('denapanel','STAR')):
            self.assertContains(page,text)
        # Reject approval of a quote that changed after the operator opened the page.
        outdated=self._fx_selection(cur)
        with patch('portal.supplier_clients.read_json',return_value=dena_page(stars_html('4,560,500 تومان'))):
            self.client.post(url,{'_fetch':1})
        self.client.post(url,outdated)
        p.refresh_from_db();cur.refresh_from_db()
        self.assertEqual((p.published_at,cur.is_active,cur.rate),(None,False,3000))
        digits=f'r{cur.pk}-'
        reviewed=self._fx_selection(cur)
        reviewed.update({digits+'active':'on',digits+'less':'0'})
        self.assertContains(self.client.post(url,reviewed),'کسریِ خرید مثبت وارد کنید')
        cur.refresh_from_db();self.assertFalse(cur.is_active)
        reviewed.update({digits+'basis_buy':'۴۶۰۰',digits+'basis_sell':'۴۶۰۰',digits+'less':'۱۲٫۵',digits+'extra':'۲'})
        self.assertRedirects(self.client.post(url,reviewed),'/admin/portal/currency/',fetch_redirect_response=False)
        p.refresh_from_db();cur.refresh_from_db()
        self.assertEqual((cur.is_active,cur.rate,p.market_bid,p.market_ask),(True,3000,4600,4600))
        self.assertEqual(currency_rates(cur),Rates(4025,4692))
        approval=p.published_at
        self.assertContains(self.client.get('/rates/'),'۴٬۰۲۵')
        with patch('portal.supplier_clients.read_json',return_value=dena_page(stars_html('5,000,000 تومان'))):
            self.client.post(url,{'_fetch':1})
        p.refresh_from_db();observed=p.candidate_at
        with patch('portal.supplier_clients.read_json',return_value=dena_page(stars_html().replace('data-status="1"','data-status="0"'))):
            self.client.post(url,{'_fetch':1})
        p.refresh_from_db();cur.refresh_from_db()
        self.assertEqual((p.published_at,p.candidate_at,p.candidate_bid,p.market_bid),(approval,observed,5000,4600))
        self.assertContains(self.client.get(url),'در دسترس نیست')
        self.assertEqual(currency_rates(cur),Rates(4025,4692))
        with self.assertRaises(RateError):currency_rates(cur,now=observed+timedelta(minutes=11))
        CurrencyPricing.objects.filter(pk=cur.pk).update(published_at=observed-timedelta(hours=25))
        with self.assertRaises(RateError):currency_rates(Currency.objects.get(pk=cur.pk),now=observed)
        self.assertEqual(Audit.objects.filter(action='currency.publish',object_ref='STAR').count(),1)
        self.assertFalse(Ledger.objects.exists())

    def test_crypto_request_is_a_ticket_and_requires_separate_verified_settlement(self):
        with patch('portal.crypto_topups.method_open',return_value=True):
            Currency.objects.create(name='تتر',code='USDT',type='crypto',rate=280000)
            url='/account/charge/crypto/'
            get_data=lambda client: {'code':'USDT','units':'۲٫۵','quote':client.get(url).context['form'].initial['quote']}
            data=get_data(self.client)
            result=self.client.post(url,{**data,'credited':9999999,'paid_ref':'bogus'})
            ticket=Ticket.objects.get()
            self.assertRedirects(result,f'/account/tickets/{ticket.pk}/')
            self.assertEqual(self.client.post(url,data).status_code,302)
            self.assertEqual(CryptoTopup.objects.count(),1);self.assertFalse(Ledger.objects.exists())
            self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,10000)
            other=Client();other.force_login(self.other)
            self.assertEqual(other.get(f'/account/tickets/{ticket.pk}/').status_code,404)
            self.assertEqual(other.post(url,data).status_code,403)
            settle=f'/staff/ticket/{ticket.pk}/settle-crypto/'
            transfer={'units':'2','reference':'0x'+'A1'*32,'verified':'on','expected':280000}
            self.assertEqual(self.client.post(settle,transfer).status_code,403)
            self._grant_list_permissions('change_ticket')
            self.assertEqual(self.client.post(settle,transfer).status_code,403)
            self._grant_list_permissions('settle_crypto_topup')
            self.client.post(settle,{**transfer,'expected':1})
            self.assertFalse(Ledger.objects.exists())
            self.client.post(settle,transfer);self.client.post(settle,transfer)
            self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,570000)
            self.assertEqual(Ledger.objects.get().amount,560000)
            second=self.client.post(url,get_data(self.client));self.assertEqual(second.status_code,302)
            ticket2=Ticket.objects.exclude(pk=ticket.pk).get()
            self.client.post(f'/staff/ticket/{ticket2.pk}/settle-crypto/',{**transfer,'reference':'a1'*32})
            self.assertEqual(Ledger.objects.count(),1)
            self.assertEqual(Audit.objects.filter(action='wallet.crypto.credit').count(),1)
        with patch('portal.crypto_topups.method_open',return_value=False):
            self.assertNotContains(self.client.get(url),'name="quote"')

    def test_concurrent_crypto_settlement_credits_one_deposit(self):
        if connection.vendor!='mysql':self.skipTest('Requires row locks')
        from .crypto_topups import settle
        self._grant_list_permissions('change_ticket','settle_crypto_topup')
        Currency.objects.create(name='تتر',code='USDT',rate=280000)
        ticket=Ticket.objects.create(user=self.user,subject='شارژ')
        CryptoTopup.objects.create(ticket=ticket,account=self.account,request_key=uuid.uuid4(),
                                   code='USDT',units=2,requested_rate=280000)
        gate=Barrier(2,timeout=10)
        def confirm(index):
            close_old_connections()
            try:
                operator=User.objects.get(pk=self.user.pk)
                gate.wait()
                return settle(operator,ticket.pk,{'expected':280000,'reference':'a2'*32,'units':Decimal(2)})
            except BusinessError:return 0
            finally:close_old_connections()
        with patch('portal.crypto_topups.method_open',return_value=True),ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(confirm,range(2))),[0,560000])
        self.wallet.refresh_from_db();self.assertEqual(self.wallet.balance,570000)
        self.assertEqual(Ledger.objects.count(),1)

    def test_currency_admin_sets_persian_margins_and_preserves_other_rows(self):
        from .exchange_rates import currency_rates,Rates
        cur=Currency.objects.create(name='دلار',code='USD',type='fiat',rate=280000)
        other=Currency.objects.create(name='تتر',code='USDT',rate=270000)
        self._grant_list_permissions('view_currency')
        url=f'/admin/portal/currency/{cur.pk}/change/'
        data={'name':cur.name,'code':'USD','type':'fiat','symbol':'$','icon':'','rate':280000,'is_active':'on',
              'fx_source':'manual','spread_mode':'fixed','sell_extra':'۵٬۰۰۰','buy_less':'۱۰٬۰۰۰'}
        self.assertEqual(self.client.post(url,data).status_code,404)
        self._grant_list_permissions('change_currency')
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(currency_rates(Currency.objects.get(pk=cur.pk)),Rates(270000,285000))
        self.assertContains(self.client.get('/admin/portal/currency/'),'۲۷۰٬۰۰۰')
        self.assertEqual(currency_rates(other),Rates(270000,270000))
        for change in ({'buy_less':'300000'},{'spread_mode':'percent','buy_less':'100'},
                       {'fx_source':'nobitex'},{'sell_extra':'-1'}):
            result=self.client.post(url,{**data,**change})
            self.assertTrue(result.context['adminform'].form.errors)
        self.assertEqual(currency_rates(Currency.objects.get(pk=cur.pk)),Rates(270000,285000))
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
            c.execute("CREATE TABLE receipts (id BIGINT PRIMARY KEY,user_id BIGINT,amount BIGINT,status VARCHAR(30),payment_tracking_code VARCHAR(10),admin_id BIGINT,charge_amount BIGINT,reject_reason TEXT,processed_at DATETIME NULL) ENGINE=InnoDB")
    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as c:
            for t in ['receipts','zarinpal_transactions','zarinpal_verification_queue','referrals','bot_settings','phone_verification_codes']:c.execute('DROP TABLE '+t)
        with connection.schema_editor() as e:
            for m in reversed(cls.legacy): e.delete_model(m)
        super().tearDownClass()
    def setUp(self):
        for m in [Order,Ledger,Product,Category,LegacyUser]:m.objects.all().delete()
        with connection.cursor() as c:
            for t in ['receipts','zarinpal_transactions','zarinpal_verification_queue','referrals','bot_settings','phone_verification_codes']:c.execute('DELETE FROM '+t)
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

    def receipt(self):
        with connection.cursor() as c:
            c.execute("INSERT INTO receipts(id,user_id,amount,status,payment_tracking_code) VALUES(1,201,1000,'pending','receipt')")

    def test_receipt_concurrent_approval_credits_once(self):
        self.receipt()
        results=self.race(lambda i:decide_bot_receipt(1,901,amount=1000))
        self.assertEqual(results.count('denied'),1)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance,2500)
        self.assertEqual(Ledger.objects.filter(type='deposit').count(),1)

    def test_receipt_failure_rolls_back_wallet_and_status(self):
        self.receipt()
        with patch('portal.services.Ledger.objects.create',side_effect=RuntimeError('test-only')):
            with self.assertRaises(RuntimeError):decide_bot_receipt(1,901)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance,1500)
        with connection.cursor() as c:
            c.execute('SELECT status FROM receipts WHERE id=1')
            self.assertEqual(c.fetchone()[0],'pending')

    def test_approved_receipt_cannot_be_rejected_or_credited_again(self):
        self.receipt()
        decide_bot_receipt(1,901)
        with self.assertRaises(BusinessError):decide_bot_receipt(1,901)
        with self.assertRaises(BusinessError):decide_bot_receipt(1,901,reject_reason='test-only')
