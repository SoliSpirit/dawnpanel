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
        self.product=Product.objects.create(name='Test plan',category=self.category,price=1000,price_per=1,
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

    def test_automatic_is_opt_in_and_limited(self):
        self.config.enabled=True
        self.config.require_approval=False
        self.config.save()
        self.assertEqual(self.fetch()['applied'],1)
        self.rows[0]['price']=2000
        self.fetch()
        self.product.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.product.price,1100)
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
        self.assertEqual(self.client.get('/services/?section=social').context['page'].paginator.count,1)

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
