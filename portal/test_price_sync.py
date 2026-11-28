from datetime import timedelta
from unittest.mock import patch
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth.models import User, Permission
from django.db import connection, close_old_connections
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .models import Category, Product, SourceProduct, SourceSyncSettings
from .price_sync import apply_proposal, reject_proposal, sync_source
from .services import BusinessError, public_products
from .supplier_clients import DenaTable, SupplierError


@override_settings(STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
                            'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PriceSyncTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(Category)
            editor.create_model(Product)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(Product)
            editor.delete_model(Category)
        super().tearDownClass()

    def setUp(self):
        Product.objects.all().delete()
        Category.objects.all().delete()
        self.category=Category.objects.create(name='Test')
        self.product=Product.objects.create(pk=1001,name='Test plan',category=self.category,price=1000,price_per=1,
                                            min_order=1,platform='ai',show_on_website=True)
        self.link=SourceProduct.objects.create(source='premstore',external_id='11',
                                               product_id=self.product.pk,last_price=1000,available=True)
        self.config,_=SourceSyncSettings.objects.get_or_create(source='premstore')
        self.rows=[{'external_id':'11','price':1100,'price_per':1,'available':True}]

    def fetch(self):
        with patch('portal.price_sync.fetch_catalogue',return_value=self.rows):
            return sync_source('premstore')

    def test_default_fetch_does_not_apply_until_approved(self):
        self.fetch()
        self.product.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.product.price,1000)
        self.assertEqual(self.link.proposed_price,1100)
        self.assertTrue(apply_proposal(self.link.pk))
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1100)
        with self.assertRaises(BusinessError):apply_proposal(self.link.pk)

    def test_manual_edit_between_fetch_and_approval_is_preserved(self):
        self.fetch()
        Product.objects.filter(pk=self.product.pk).update(price=1234)
        self.assertFalse(apply_proposal(self.link.pk))
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1234)

    def test_legacy_automatic_setting_cannot_write_a_price(self):
        self.config.enabled=True
        self.config.require_approval=False
        self.config.save()
        self.assertEqual(self.fetch()['applied'],0)
        self.assertFalse(apply_proposal(self.link.pk,automatic=True))
        self.rows[0]['price']=2000
        self.fetch()
        self.product.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.product.price,1000)
        self.assertEqual(self.link.review_status,'pending')

    def test_scheduler_respects_enabled_interval_and_lease(self):
        with patch('portal.price_sync.fetch_catalogue') as fetcher:
            self.assertTrue(sync_source('premstore',due_only=True)['skipped'])
            fetcher.assert_not_called()
        self.config.enabled=True
        self.config.last_attempt=timezone.now()
        self.config.save()
        with patch('portal.price_sync.fetch_catalogue') as fetcher:
            self.assertTrue(sync_source('premstore',due_only=True)['skipped'])
            fetcher.assert_not_called()
        self.config.running_until=timezone.now()+timedelta(minutes=10)
        self.config.save()
        with self.assertRaises(BusinessError):self.fetch()

    def test_failure_preserves_price_and_releases_lease(self):
        with patch('portal.price_sync.fetch_catalogue',side_effect=SupplierError('test')):
            with self.assertRaises(SupplierError):sync_source('premstore')
        self.product.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(self.product.price,1000)
        self.assertIsNone(self.config.running_until)
        self.assertTrue(self.config.last_error)

    def test_unavailable_or_missing_item_never_applies(self):
        self.rows[0]['available']=False
        self.fetch()
        with self.assertRaises(BusinessError):apply_proposal(self.link.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1000)
        self.assertFalse(public_products().filter(pk=self.product.pk).exists())

    def test_stale_or_changed_proposal_rejected(self):
        self.fetch()
        self.link.refresh_from_db()
        old=self.link.observed_at-timedelta(seconds=1)
        with self.assertRaises(BusinessError):apply_proposal(self.link.pk,expected_observed_at=old)
        SourceProduct.objects.filter(pk=self.link.pk).update(observed_at=timezone.now()-timedelta(days=2))
        with self.assertRaises(BusinessError):apply_proposal(self.link.pk)

    def test_currency_and_unit_mismatch_never_apply(self):
        Product.objects.filter(pk=self.product.pk).update(price_per=1000)
        self.fetch()
        self.link.refresh_from_db()
        self.assertEqual(self.link.review_status,'conflict')
        with self.assertRaises(BusinessError):apply_proposal(self.link.pk)

    def test_rejection_persists_until_source_changes(self):
        self.fetch()
        reject_proposal(self.link.pk)
        self.fetch()
        self.link.refresh_from_db()
        self.assertEqual(self.link.review_status,'rejected')
        self.rows[0]['price']=1200
        self.fetch()
        self.link.refresh_from_db()
        self.assertEqual(self.link.review_status,'pending')

    def test_disable_individual_product(self):
        self.link.sync_enabled=False
        self.link.save()
        self.fetch()
        self.link.refresh_from_db()
        self.assertIsNone(self.link.proposed_price)

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[71]}})
    def test_frozen_report_markup_paging_and_safe_telegram_bulk_across_pages(self):
        from django.core.exceptions import PermissionDenied
        from .models import PriceReviewBatch,OrderDelivery,OperationNotice
        from .review_queue import email_sheet
        from .telegram_reviews import telegram_action,telegram_digest
        self._tools_staff('change_product','change_sourceproduct')
        for i in range(14):
            p=Product.objects.create(name=f'پلن {i}',category=self.category,price=1000)
            SourceProduct.objects.create(product_id=p.pk,source='premstore',external_id=str(i+30),last_price=900)
            self.rows.append({'external_id':str(i+30),'price':1300,'price_per':1,'available':True})
        result=self.fetch();batch=PriceReviewBatch.objects.get(pk=result['review_batch']);url=f'/admin/prices/reviews/{batch.pk}/'
        item=batch.items.get(link=self.link);self.assertEqual((item.previous,item.observed,item.base),(1000,1100,1000))
        filename,content,mime=email_sheet(batch.pk)
        self.assertEqual(mime,'text/csv');self.assertEqual(len(content.splitlines()),16);self.assertIn('1000,1100',content)
        self.assertEqual(len(self.client.get(url).context['items']),12);self.assertEqual(len(self.client.get(url,{'page':2}).context['items']),3)
        self.client.post(url,{'decision':'one','item':item.pk,'markup':'۲۵'})
        self.product.refresh_from_db();self.assertEqual((self.product.price,self.product.product_profit_percent),(1100,25))
        changed=batch.items.exclude(pk=item.pk).first();Product.objects.filter(pk=changed.product_id).update(price=1800)
        op=OperationNotice.objects.get(topic='price_review');self.assertEqual(OrderDelivery.objects.filter(operation=op,recipient=71).update(state='sent',message_id=12),1)
        cb=lambda a:f'pr:{batch.pk}:1:{a}:0'
        for args in [(81,81,'private',12),(71,-1000,'supergroup',12),(71,71,'private',13)]:
            with self.assertRaises(PermissionDenied):telegram_action(*args,cb('all'))
        args=(71,71,'private',12)
        self.assertIn('تمام صفحه‌ها',telegram_action(*args,cb('ask'))['text']);self.assertEqual(batch.items.filter(decision='applied').count(),1)
        digest=telegram_digest(batch.pk)
        self.assertEqual(digest['parse_mode'],'HTML');self.assertIn('اولین پیشنهاد',digest['text'])
        index=telegram_action(*args,cb('pending'))
        self.assertIn('از ۳',index['text'])
        entry=index['reply_markup']['inline_keyboard'][0][0]
        card=telegram_action(*args,entry['callback_data'])
        self.assertIn('قیمت منبع',card['text']);self.assertIn('تومان',card['text'])
        self.assertIn('صفحهٔ ۲',telegram_action(*args,f'pr:{batch.pk}:2:page:0')['text'])
        self.assertEqual(batch.items.filter(decision='applied').count(),1)
        telegram_action(*args,cb('all'));telegram_action(*args,cb('all'))
        self.assertEqual(batch.items.filter(decision='applied').count(),14)
        self.assertEqual(batch.items.get(pk=changed.pk).decision,'stale')
        self.assertEqual(Product.objects.get(pk=changed.product_id).price,1800)

    def test_exact_pack_amount_preserves_supplier_basis_and_survives_another_review(self):
        from .models import PriceReviewItem,ProductSaleOverride,ProductTax
        from .pricing import pricing_for
        self._tools_staff('change_product','change_sourceproduct')
        self.rows[0].update(price=4_880_000,price_per=1000)
        Product.objects.filter(pk=self.product.pk).update(price=4_560_000,price_per=1000,product_profit_percent=20)
        ProductTax.objects.create(product=self.product,percent=10)
        def review():
            result=self.fetch();i=PriceReviewItem.objects.get(batch_id=result['review_batch']);return i,f'/admin/prices/reviews/{i.batch_id}/'
        i,url=review();self.assertContains(self.client.get(url),'name="sale_price"')
        form={'decision':'fixed','item':i.pk}
        for invalid in ['۱۲,۳','99.5','۰','-30','۱۰۰٬۰۰۰٬۰۰۰٬۰۰۱']:
            self.client.post(url,{**form,'sale_price':invalid})
            self.assertFalse(ProductSaleOverride.objects.exists())
        self.client.post(url,{**form,'sale_price':'۵٬۰۰۰٬۰۰۱'})
        self.product.refresh_from_db();i.refresh_from_db();self.link.refresh_from_db()
        self.assertEqual((self.product.price,self.product.product_profit_percent,self.link.last_price),(4_880_000,20,4_880_000))
        self.assertEqual((self.product.fixed_sale,i.final_sale,pricing_for(self.product).pack),(5_000_001,5_000_001,5_000_001))
        self.assertEqual(pricing_for(self.product).quote(1000).total,5_500_002)
        self.rows[0]['price']=4_900_000;j,url=review();self.assertEqual(j.fixed_before,5_000_001)
        self.client.post(url,{'decision':'all'})
        self.product.refresh_from_db();self.assertEqual((self.product.price,pricing_for(self.product).pack),(4_900_000,5_000_001))
        k,url=review()
        self.client.post(url,{'decision':'one','item':k.pk,'markup':'۲۰'})
        self.product.refresh_from_db();self.assertIsNone(self.product.fixed_sale);self.assertEqual(pricing_for(self.product).pack,5_880_000)

    def test_closed_review_links_to_editable_live_price_and_checks_current_revision(self):
        from .models import PriceReviewItem
        self._tools_staff('change_product','change_sourceproduct')
        result=self.fetch();row=PriceReviewItem.objects.get(batch_id=result['review_batch'])
        self.fetch()  # later report replaces this observation
        url=f'/admin/prices/reviews/{row.batch_id}/'
        current=url+f'items/{row.pk}/price/'
        self.assertContains(self.client.get(url),current)
        self.client.post(url,{'decision':'fixed','item':row.pk,'sale_price':'35000'})
        self.product.refresh_from_db();self.assertIsNone(self.product.fixed_sale)
        stamp=self.client.get(current).context['stamp']
        Product.objects.filter(pk=self.product.pk).update(price=900)
        refused=self.client.post(current,{'sale_price':'35000','stamp':stamp})
        self.assertContains(refused,'مهلت فرم')
        self.product.refresh_from_db();self.assertIsNone(self.product.fixed_sale)
        self.client.post(current,{'sale_price':'۳۵٬۰۰۰','stamp':refused.context['stamp']})
        self.product.refresh_from_db();row.refresh_from_db()
        self.assertEqual((self.product.fixed_sale,self.product.price,row.previous,row.final_sale),(35000,900,1000,None))
        self.assertEqual(self.client.post(current,{'sale_price':'35001','stamp':refused.context['stamp']}).status_code,200)
        self.product.refresh_from_db();self.assertEqual(self.product.fixed_sale,35000)

    @override_settings(BOT_CONFIG={'telegram':{'admin_ids':[71]}})
    def test_telegram_detail_escapes_product_and_confirms_only_the_selected_row(self):
        from .models import OrderDelivery,PriceReviewItem
        from .telegram_reviews import telegram_digest,telegram_action
        self.product.name='<پکیج & آزمایشی>';self.product.save()
        pk=self.fetch()['review_batch'];item=PriceReviewItem.objects.get(batch_id=pk);msg=telegram_digest(pk)
        self.assertIn('&lt;پکیج &amp; آزمایشی&gt;',msg['text']);self.assertNotIn('صفحهٔ ۱',msg['text'])
        OrderDelivery.objects.filter(operation__reference=str(pk),operation__topic='price_review').update(message_id=33,state='sent')
        click=lambda data:telegram_action(71,71,'private',33,data)
        first=click(msg['reply_markup']['inline_keyboard'][0][0]['callback_data'])
        card=click(first['reply_markup']['inline_keyboard'][0][0]['callback_data'])
        self.assertIn('فروش پیش از مالیات',card['text'])
        self.assertFalse(item.decision)
        approved=card['reply_markup']['inline_keyboard'][0][0]['callback_data']
        self.assertLessEqual(len(approved.encode()),64)
        self.assertIn('تأیید شد',click(approved)['text'])
        self.assertIn('قبلاً بررسی',click(approved)['text'])
        self.product.refresh_from_db();self.assertEqual(self.product.price,1100)

    def _tools_staff(self,*perms):
        editor=User.objects.create_user(username='price-tools',is_staff=True)
        editor.user_permissions.add(*Permission.objects.filter(content_type__app_label='portal',codename__in=perms))
        self.client.force_login(editor)
        return editor

    def test_targeted_check_records_evidence_but_never_applies_a_price_or_resets_schedule(self):
        self.config.enabled=True;self.config.require_approval=False
        self.config.last_success=self.config.last_attempt=timezone.now()-timedelta(minutes=15)
        self.config.save()
        self.link.source_url='https://premstore.ir/product/example/'
        self.link.sync_enabled=False;self.link.save()
        missing=SourceProduct.objects.create(source='premstore',external_id='12',product_id=2002,last_price=800,available=True)
        untouched=SourceProduct.objects.create(source='premstore',external_id='13',product_id=2003,last_price=200,available=True)
        url=self.link.source_url+'?attribute_pa_plan=pro'
        self.rows[0].update(available=False,item_url=url)
        with patch('portal.price_sync.fetch_catalogue',return_value=self.rows) as fetcher:
            result=sync_source('premstore',link_ids=[self.link.pk,missing.pk])
        fetcher.assert_called_once()
        self.assertEqual((result['checked'],result['unavailable'],result['missing']),(2,1,1))
        self.link.refresh_from_db();missing.refresh_from_db();untouched.refresh_from_db()
        self.assertEqual((self.link.review_status,self.link.last_price,self.link.evidence_url,self.link.proposed_price),
                         ('unavailable',1100,url,None))
        self.assertEqual(self.link.source_url,'https://premstore.ir/product/example/')
        self.assertEqual((missing.review_status,missing.available,missing.last_price),('missing',False,800))
        self.assertIsNone(untouched.observed_at)
        self.assertFalse(self.link.sync_enabled)
        self.rows[0]['available']=True
        SourceProduct.objects.filter(pk=self.link.pk).update(sync_enabled=True)
        with patch('portal.price_sync.fetch_catalogue',return_value=self.rows):
            result=sync_source('premstore',link_ids=[self.link.pk])
        self.assertEqual((result['pending'],result['applied']),(1,0))
        self.product.refresh_from_db();self.assertEqual(self.product.price,1000)
        config=SourceSyncSettings.objects.get(pk=self.config.pk)
        self.assertEqual((config.running_until,config.last_attempt,config.last_success),
                         (None,self.config.last_attempt,self.config.last_success))
        self.link.refresh_from_db()
        with patch('portal.price_sync.fetch_catalogue',side_effect=SupplierError('ارتباط ناموفق')):
            with self.assertRaises(SupplierError):sync_source('premstore',link_ids=[self.link.pk])
        self.assertEqual(SourceProduct.objects.get(pk=self.link.pk).observed_at,self.link.observed_at)

    def test_recheck_one_group_and_filtered_all_fetch_each_source_once(self):
        self._tools_staff('change_sourceproduct','change_product')
        dena=Product.objects.create(name='Second plan',category=self.category,price=1200)
        other=SourceProduct.objects.create(source='denapanel',external_id='11',product_id=dena.pk,last_price=1200)
        third=SourceProduct.objects.create(source='premstore',external_id='12',product_id=3000,last_price=900,available=True)
        def get_rows(source,**_):
            return self.rows if source=='premstore' else [{'external_id':'11','price':1300,'price_per':1,'available':True}]
        url='/admin/portal/sourceproduct/'
        with patch('portal.price_sync.fetch_catalogue',side_effect=get_rows) as fetcher:
            self.assertEqual(self.client.post(url,{'_dp_recheck':other.pk}).status_code,302)
            self.assertEqual(fetcher.call_count,1)
            self.assertIsNone(SourceProduct.objects.get(pk=self.link.pk).observed_at)
            fetcher.reset_mock()
            self.client.post(url,{'action':'recheck_selected','_selected_action':[other.pk,self.link.pk]})
            self.assertEqual({c.args[0] for c in fetcher.call_args_list},{'denapanel','premstore'})
            self.assertEqual(fetcher.call_count,2)
            fetcher.reset_mock()
            self.client.post(url+'?q=Test%20plan',{'_dp_recheck':'results'})
            self.assertEqual(fetcher.call_count,1)
            self.assertEqual(fetcher.call_args.args[0],'premstore')
        self.assertIsNone(SourceProduct.objects.get(pk=third.pk).observed_at)

    def test_profit_edits_are_scoped_validated_and_used_once_in_quotes(self):
        from decimal import Decimal
        from .pricing import pricing_for
        from .models import Audit,ProductTax
        self._tools_staff('change_product','change_sourceproduct')
        ProductTax.objects.create(product=self.product,percent=10)
        other=Product.objects.create(name='No source',category=self.category,price=1000)
        keep=Product.objects.create(name='Keep',category=self.category,price=1000,product_profit_percent=3)
        base='/admin/portal/product/'
        self.fetch()
        opened=self.client.post(base,{'action':'set_profit','_selected_action':[self.product.pk,other.pk]})
        self.assertEqual(opened.context['count'],2)
        token={'_dp_profit_selection':opened.context['selection']}
        for invalid in ('','-1','NaN','0.00001','1000000'):
            res=self.client.post(base,{**token,'percent':invalid})
            self.assertIn('percent',res.context['form'].errors)
        self.assertEqual(self.client.post(base,{**token,'percent':'۱۲٫۵'}).status_code,302)
        self.product.refresh_from_db();other.refresh_from_db();keep.refresh_from_db()
        self.assertEqual((self.product.price,self.product.product_profit_percent,other.product_profit_percent,keep.product_profit_percent),
                         (1000,Decimal('12.5'),Decimal('12.5'),3))
        self.assertEqual(pricing_for(self.product).quote(1).total,1238)
        self.assertEqual(Audit.objects.filter(action='product.profit').count(),2)
        self.assertFalse(apply_proposal(self.link.pk))  # fetched with the previous markup
        self.client.post(base,{**token,'percent':99})
        self.product.refresh_from_db();self.assertEqual(self.product.product_profit_percent,Decimal('12.5'))
        url='/admin/portal/sourceproduct/'
        opened=self.client.post(url,{'_dp_profit':self.link.pk})
        self.assertEqual(opened.context['count'],1)
        self.client.post(url,{'_dp_profit_selection':opened.context['selection'],'percent':'۰'})
        self.product.refresh_from_db();other.refresh_from_db();self.link.refresh_from_db()
        self.assertEqual((self.product.product_profit_percent,other.product_profit_percent,self.link.last_price),(0,Decimal('12.5'),1100))

    def test_one_source_action_needs_both_permissions_and_csrf(self):
        from django.test import Client
        url='/admin/portal/sourceproduct/'
        user=self._tools_staff('change_sourceproduct')
        with patch('portal.price_sync.fetch_catalogue') as fetch:
            self.assertEqual(self.client.post(url,{'_dp_recheck':self.link.pk}).status_code,404)
            self.assertEqual(self.client.post(url,{'_dp_profit':self.link.pk}).status_code,404)
            user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='change_product'))
            secure=Client(enforce_csrf_checks=True);secure.force_login(user)
            self.assertEqual(secure.post(url,{'_dp_recheck':'results'}).status_code,403)
            self.assertEqual(secure.post(url,{'_dp_profit':self.link.pk}).status_code,403)
            self.assertEqual(secure.post(url,{'_dp_approve':1}).status_code,403)
            fetch.assert_not_called()

    def add_family_plan(self):
        from .models import ProductVisual
        self.link.source_url='https://premstore.ir/product/example/'
        self.link.family_name='Example family'
        self.link.family_summary='Family introduction'
        self.link.save()
        ProductVisual.objects.create(product_id=self.product.pk,plan_name='Monthly')
        plan=Product.objects.create(name='Example - Annual',category=self.category,price=2400,
            min_order=1,max_order=1,platform='ai',show_on_website=True)
        ProductVisual.objects.create(product_id=plan.pk,plan_name='Annual')
        SourceProduct.objects.create(source='premstore',external_id='12',product_id=plan.pk,
            source_url=self.link.source_url,family_name='Example family',last_price=2400,available=True)
        return plan

    def test_catalog_groups_parent_but_retains_plan_identity(self):
        from .store_catalog import families
        plan=self.add_family_plan()
        groups=families()
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0].name,'Example family')
        self.assertEqual(groups[0].minimum,1000)
        self.assertEqual({p.pk for p in groups[0].plans},{self.product.pk,plan.pk})
        response=self.client.get('/services/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-family-card',count=1)
        response=self.client.get(plan.get_absolute_url())
        self.assertContains(response,'aria-current="true"')
        self.assertContains(response,self.product.get_absolute_url())
        self.assertContains(response,'action="'+plan.get_absolute_url()+'"')
        self.assertEqual(response.context['product'].pk,plan.pk)

    def test_family_search_matches_plan_not_just_parent(self):
        self.add_family_plan()
        response=self.client.get('/services/',{'q':'Annual'})
        self.assertEqual(response.context['page'].paginator.count,1)
        self.assertEqual(len(response.context['page'][0].plans),2)

    def test_catalog_normalizes_persian_letters_joiners_and_digits(self):
        self.product.name='تلگرام پریمیوم ۱۲ ماهه'
        self.product.save()
        result=self.client.get('/services/',{'q':'  پريميوم\u200c١٢ تلگرام  '})
        self.assertEqual(result.context['page'].paginator.count,1)

    def test_subcategory_options_keep_siblings_when_search_is_empty(self):
        extra=Category.objects.create(name='Sibling')
        Product.objects.create(name='Sibling item',category=extra,platform='ai',price=500,show_on_website=True)
        result=self.client.get('/services/',{'section':'ai','category':self.category.pk,'q':'no matching product'})
        self.assertEqual(result.context['page'].paginator.count,0)
        self.assertEqual({cat.pk for cat in result.context['catalog_categories']},{extra.pk,self.category.pk})

    def test_messaging_collection_does_not_include_subscriptions(self):
        messages=Category.objects.create(name='Channels')
        for index in range(13):
            Product.objects.create(name='Channel service '+str(index),category=messages,
                                   platform='rubika',price=500,show_on_website=True)
        response=self.client.get('/services/',{'collection':'messaging','sort':'price'})
        self.assertEqual(response.context['page'].paginator.count,13)
        self.assertContains(response,'collection=messaging&amp;sort=price&amp;page=2')
        self.assertNotContains(response,self.product.name)
        self.assertEqual(self.client.get('/services/?collection=subscriptions').context['page'].paginator.count,1)

    def test_card_minimum_uses_actual_quantity_total_not_pack(self):
        from .store_catalog import families
        Product.objects.filter(pk=self.product.pk).update(price_per=1000,min_order=100)
        self.assertEqual(families()[0].minimum,100)

    def test_subscription_social_is_not_telegram_services(self):
        from .store_catalog import families
        self.category.name='شبکه‌های اجتماعی'
        self.category.save()
        Product.objects.filter(pk=self.product.pk).update(platform='other')
        self.assertEqual(families()[0].section,'social')
        self.assertRedirects(self.client.get('/services/?section=telegram'),'/services/?collection=messaging')
        self.assertEqual(self.client.get('/services/category/social/').context['page'].paginator.count,1)

    def test_unavailable_plan_not_in_group(self):
        plan=self.add_family_plan()
        SourceProduct.objects.filter(product_id=plan.pk).update(available=False)
        response=self.client.get('/services/')
        self.assertEqual(len(response.context['page'][0].plans),1)
        self.assertEqual(self.client.get(plan.get_absolute_url()).status_code,404)

    def test_legacy_brand_plans_share_card_without_supplier_mapping(self):
        from .store_catalog import families
        self.link.family_name='ChatGPT'
        self.link.source_url='https://premstore.ir/product/chatgpt/'
        self.link.save()
        legacy=Product.objects.create(name='ChatGPT original merchant plan',category=self.category,
            price=900,platform='ai',show_on_website=True)
        groups=families()
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0].plans),2)
        self.assertFalse(SourceProduct.objects.filter(product_id=legacy.pk).exists())
        self.assertEqual(self.client.get(legacy.get_absolute_url()).status_code,200)

    def reviewed_pair(self):
        from .service_art import SERVICE_TITLES
        self.link.external_id='277';self.link.family_name='ChatGPT';self.link.source_url='https://premstore.ir/product/chatgpt/';self.link.save()
        self.product.name='ChatGPT - Go';self.product.max_order=1;self.product.save()
        return Product.objects.create(pk=32,name=SERVICE_TITLES['ai'][32],category=Category.objects.create(name='Native'),
            platform='ai',price=850,min_order=1,max_order=1,show_on_website=True,show_on_telegram=True)

    def test_reviewed_mirror_keeps_old_links_filters_drafts_and_selects_preferred_sku(self):
        from .models import ProductTax
        from .store_catalog import families
        legacy=self.reviewed_pair()
        ProductTax.objects.create(product_id=self.product.pk,percent=10)
        f,=families();self.assertEqual([p.pk for p in f.plans],[self.product.pk])
        self.assertEqual(f.minimum,1100)
        self.assertRedirects(self.client.get(legacy.get_absolute_url()),self.product.get_absolute_url(),status_code=302)
        self.assertEqual(self.client.get('/services/',{'q':'کد فعال‌سازی','category':legacy.category_id}).context['page'].paginator.count,1)
        self.assertNotContains(self.client.get('/sitemap.xml'),legacy.get_absolute_url())
        self.assertTrue(Product.objects.get(pk=legacy.pk).show_on_telegram)
        user=User.objects.create_user(username='alias-buyer')
        self.client.force_login(user)
        session=self.client.session
        session['order_draft']={'product_id':legacy.pk,'quantity':1,'at':timezone.now().timestamp()};session.save()
        self.assertTrue(self.client.get(legacy.get_absolute_url(),follow=True).context['restored'])
        self.client.post(legacy.get_absolute_url(),{'quantity':1,'target':'test'})
        pending=self.client.session['checkout']
        self.assertEqual((pending['product_id'],pending['quoted_total']),(self.product.pk,1100))
        self.assertFalse(SourceProduct.objects.filter(product_id=legacy.pk).exists())

    def test_no_alias_can_bypass_supplier_stock_and_standalone_fallback_must_be_published(self):
        from .store_catalog import families
        legacy=self.reviewed_pair()
        self.link.available=False;self.link.save()
        self.assertFalse(public_products().filter(pk__in=[legacy.pk,self.product.pk]).exists())
        self.assertEqual(self.client.get(legacy.get_absolute_url()).status_code,404)
        self.link.available=True;self.link.save()
        self.product.show_on_website=False;self.product.save()
        self.assertEqual(families()[0].first.pk,legacy.pk)
        self.assertEqual(self.client.get(legacy.get_absolute_url()).status_code,200)

    def test_different_delivery_and_recycled_ids_do_not_hide_real_variants(self):
        from .store_catalog import families
        legacy=self.reviewed_pair()
        legacy.name='ChatGPT - آماده سفارشی';legacy.save()
        self.assertEqual({p.pk for p in families()[0].plans},{legacy.pk,self.product.pk})

    def test_rubika_duplicate_is_one_card_and_other_reactions_remain_distinct(self):
        from .store_catalog import families
        from .service_art import SERVICE_TITLES
        def service(pk,source_id,name):
            return Product.objects.create(pk=pk,category=self.category,name=name,platform='rubika',price=20000,
                min_order=100,max_order=1000,price_per=1000,show_on_website=True,
                description=f'شناسه خدمت در سایت قبلی: #{source_id}؛')
        a=service(30,6,SERVICE_TITLES['rubika'][30])
        b=service(31,8,a.name)
        other=service(777,9,'ری اکشن چشم 😁')
        groups=[f for f in families() if f.section=='rubika']
        self.assertEqual({f.first.pk for f in groups},{a.pk,other.pk})
        self.assertRedirects(self.client.get(b.get_absolute_url()),a.get_absolute_url(),status_code=302)
        a.is_active=False;a.save()
        self.assertEqual(self.client.get(b.get_absolute_url()).status_code,200)

    def test_supplier_approval_changes_base_only_after_merchant_sets_tax(self):
        from .models import ProductTax
        from .services import price_for
        self.fetch()
        ProductTax.objects.create(product_id=self.product.pk,percent='9.50')
        self.assertTrue(apply_proposal(self.link.pk))
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1100)
        self.assertEqual(price_for(self.product,1),(1205,1100))

    def test_post_selected_plan_keeps_existing_checkout_contract(self):
        plan=self.add_family_plan()
        user=User.objects.create_user(username='family-buyer')
        self.client.force_login(user)
        response=self.client.post(plan.get_absolute_url(),{'quantity':1,'target':'buyer@example.test'})
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'review.html')
        self.assertEqual(self.client.session['checkout']['product_id'],plan.pk)
        self.assertEqual(self.client.session['checkout']['quoted_total'],2400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1000)

    def test_metadata_refresh_never_changes_prices_or_observations(self):
        from django.core.management import call_command
        self.add_family_plan()
        self.fetch()
        self.link.refresh_from_db()
        old=(self.link.last_price,self.link.proposed_price,self.link.observed_at,self.link.review_status,self.link.available)
        with patch('portal.management.commands.refresh_catalog_metadata.fetch_catalogue',return_value=[{
            'external_id':'11','url':self.link.source_url,'family_name':'New title',
            'family_summary':'New summary','price':999999,'available':False}]):
            call_command('refresh_catalog_metadata')
        self.link.refresh_from_db()
        self.assertEqual(self.link.family_name,'New title')
        self.assertEqual((self.link.last_price,self.link.proposed_price,self.link.observed_at,self.link.review_status,self.link.available),old)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1000)

    def test_telegram_service_is_hidden_on_web_without_disabling_bot(self):
        self.product.platform='telegram'
        self.product.show_on_telegram=True
        self.product.save()
        self.assertFalse(public_products().filter(pk=self.product.pk).exists())
        self.assertEqual(self.client.get(self.product.get_absolute_url()).status_code,404)
        self.assertEqual(self.client.get(f'/product-cover/{self.product.pk}.jpg').status_code,404)
        self.assertRedirects(self.client.get('/services/?section=telegram'),'/services/?collection=messaging')
        self.assertTrue(Product.objects.get(pk=self.product.pk).show_on_telegram)

    def test_unbranded_public_product_has_local_cover(self):
        response=self.client.get(f'/product-cover/{self.product.pk}.jpg')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'image/jpeg')
        self.assertTrue(response.content.startswith(b'\xff\xd8'))

    def test_admin_permissions_and_confirmation(self):
        from .models import PriceReviewItem
        self.fetch()
        user=User.objects.create_user(username='source-test-admin',is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename='change_sourceproduct',content_type__app_label='portal'))
        self.client.force_login(user)
        url='/admin/portal/sourceproduct/'
        data={'action':'approve_prices','_selected_action':[str(self.link.pk)]}
        self.client.post(url,data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1000)
        user.user_permissions.add(Permission.objects.get(codename='change_product',content_type__app_label='portal'))
        response=self.client.post(url,data)
        self.assertTemplateUsed(response,'admin/portal/sourceproduct/review.html')
        self.link.refresh_from_db()
        data.update(confirm='yes',**{'observed_'+str(self.link.pk):self.link.observed_at.isoformat()})
        response=self.client.post(url,data)
        self.assertEqual(response.status_code,302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price,1100)
        self.assertEqual(PriceReviewItem.objects.get(link=self.link).decision,'applied')

    def test_pending_list_button_commits_only_its_review_once_and_keeps_the_fixed_sale(self):
        from .models import Audit,PriceReviewItem,ProductSaleOverride
        self._tools_staff('change_product','change_sourceproduct')
        ProductSaleOverride.objects.create(product=self.product,units=1,amount=1651)
        other=Product.objects.create(name='Other plan',category=self.category,price=2400)
        other_link=SourceProduct.objects.create(source='premstore',external_id='12',product_id=other.pk,last_price=2400)
        self.rows.append(dict(self.rows[0],external_id='12',price=3000))
        result=self.fetch();rows=PriceReviewItem.objects.filter(batch_id=result['review_batch'])
        row=rows.get(link=self.link);url='/admin/portal/sourceproduct/?review_status__exact=pending'
        page=self.client.get(url);self.assertContains(page,'name="_dp_approve"',count=2)
        self.assertContains(page,'۱٬۶۵۱ تومان')
        # Checked boxes and the bulk dropdown must not change a single-button submission.
        data={'_dp_approve':str(row.pk),'action':'approve_prices','_selected_action':str(other_link.pk)}
        for _ in range(2):self.assertRedirects(self.client.post(url,data),url,fetch_redirect_response=False)
        self.product.refresh_from_db();self.link.refresh_from_db();other.refresh_from_db();row.refresh_from_db()
        self.assertEqual((self.link.review_status,self.product.price,self.product.fixed_sale,row.decision,row.final_sale),
                         ('applied',1100,1651,'applied',1651))
        self.assertEqual((other.price,rows.get(link=other_link).decision),(2400,''))
        self.assertContains(self.client.get(url),'name="_dp_approve"',count=1)
        self.assertEqual(Audit.objects.filter(action='source.price.apply').count(),1)

    def test_pending_list_cannot_apply_a_newer_observation_or_a_changed_product_from_an_old_button(self):
        from .models import Audit,PriceReviewItem
        user=self._tools_staff('view_product','view_sourceproduct')
        one=self.fetch()['review_batch']
        row=PriceReviewItem.objects.get(batch_id=one);url='/admin/portal/sourceproduct/?review_status__exact=pending'
        self.assertNotContains(self.client.get(url),'name="_dp_approve"')
        self.assertEqual(self.client.post(url,{'_dp_approve':row.pk}).status_code,404)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='portal',codename__in=['change_product','change_sourceproduct']))
        self.rows[0]['price']=1250
        two=self.fetch()['review_batch'];fresh=PriceReviewItem.objects.get(batch_id=two)
        self.client.post(url,{'_dp_approve':row.pk})
        self.link.refresh_from_db();self.product.refresh_from_db()
        self.assertEqual((self.product.price,self.link.review_status,self.link.proposed_price),(1000,'pending',1250))
        # A manual price edit after the page loaded must also win.
        Product.objects.filter(pk=self.product.pk).update(price=1234)
        self.client.post(url,{'_dp_approve':fresh.pk})
        self.product.refresh_from_db();fresh.refresh_from_db()
        self.assertEqual((self.product.price,fresh.decision),(1234,'stale'))
        self.assertFalse(Audit.objects.filter(action='source.price.apply').exists())

    def test_inline_monitoring_respects_permissions_and_price_approval(self):
        self.fetch()
        user=User.objects.create_user(username='price-monitor',is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='portal',
            codename__in=['change_sourceproduct','change_sourcesyncsettings']))
        self.client.force_login(user)
        def submit(obj,field,on):
            return self.client.post(f'/admin/portal/{obj._meta.model_name}/',
                                    {'_dp_state':f'{obj.pk}:{field}:{int(on)}'},HTTP_ACCEPT='application/json')
        for obj,field,on in [(self.link,'sync_enabled',False),(self.config,'enabled',True)]:
            self.assertEqual(submit(obj,field,on).status_code,404)
        user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='change_product'))
        for obj,field in [(self.link,'sync_enabled'),(self.config,'enabled')]:
            for on in (not getattr(obj,field),getattr(obj,field)):
                result=submit(obj,field,on)
                self.assertEqual(result.status_code,200,result.content)
                self.assertIs(getattr(type(obj).objects.get(pk=obj.pk),field),on)
        for obj,field in [(self.link,'available'),(self.config,'require_approval')]:
            self.assertEqual(submit(obj,field,False).status_code,400)
        self.config.refresh_from_db();self.link.refresh_from_db();self.product.refresh_from_db()
        self.assertTrue(self.config.require_approval and self.link.available)
        self.assertEqual((self.config.interval_minutes,self.link.proposed_price,self.link.review_status,self.product.price),
                         (60,1100,'pending',1000))

    @skipUnless(connection.vendor=='mysql','Requires real row locking')
    def test_parallel_state_requests_record_a_single_transition(self):
        from django.test import Client
        from .models import Audit
        user=User.objects.create_user(username='stock-editor',is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label='portal',codename='change_product'))
        self.client.force_login(user)
        cookie=self.client.cookies['sessionid'].value
        gate=Barrier(2,timeout=10)
        def send(_):
            close_old_connections()
            try:
                client=Client();client.cookies['sessionid']=cookie
                gate.wait()
                return client.post('/admin/portal/product/',{'_dp_state':f'{self.product.pk}:is_active:0'},
                                   HTTP_ACCEPT='application/json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(send,range(2))),[200,200])
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        self.assertEqual(Audit.objects.get(action='product.update').details,{'fields':['is_active'],'old':True,'new':False})

    @skipUnless(connection.vendor=='mysql','Requires real row locking')
    def test_concurrent_proposal_approval_applies_once(self):
        from .models import Audit
        self.fetch()
        gate=Barrier(2)
        pk=self.link.pk
        def approve(_):
            close_old_connections()
            gate.wait()
            try:
                return apply_proposal(pk)
            except BusinessError:
                return False
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(approve,range(2)))
        self.assertEqual(sum(results),1)
        self.assertEqual(Audit.objects.filter(action='source.price.apply').count(),1)


class SupplierParserTests(SimpleTestCase):
    def test_dena_table_preserves_category_units_and_limits(self):
        table=DenaTable()
        table.feed('<h5>گروه تست</h5><table><tr data-service-id="1" data-service-name="سرویس" data-category="2" data-status="1">'
                   '<td data-title="قیمت هر 1000 عدد">1,000&nbsp;تومان</td>'
                   '<td data-title="حداقل/حداکثر">5,000/100</td>'
                   '<td><span data-desc="شرح&lt;br&gt;تست"></span></td></tr></table>')
        self.assertEqual(table.rows[0]['category_name'],'گروه تست')
        self.assertEqual(table.rows[0]['cells']['حداقل/حداکثر'],'5,000/100')

    def test_client_rejects_arbitrary_hosts(self):
        from .supplier_clients import read_json
        with patch('portal.supplier_clients.requests.request') as request:
            with self.assertRaises(SupplierError):read_json('http://127.0.0.1/private')
            request.assert_not_called()
