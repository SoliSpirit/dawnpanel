import json
from tempfile import NamedTemporaryFile

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from .source_catalog import catalogue_rows


class SupplierCatalogueTests(SimpleTestCase):
    def sample(self):
        return {
            'premstore': {
                'products': [{
                    'id': 10, 'name': 'Example', 'permalink': 'https://premstore.ir/product/example/',
                    'categories': [{'name': 'Example category'}],
                    'attributes': [{'terms': [{'slug': 'pro', 'name': 'Pro'}]}],
                    'variations': [{'id': 11, 'attributes': [{'value': 'pro'}]}],
                }],
                'variations': [{
                    'id': 11, 'prices': {'price': '500', 'currency_code': 'IRT'},
                    'is_in_stock': True,
                }],
            },
            'denapanel': {'services': [{
                'id': '21', 'name': 'Service', 'category_id': '3', 'status': '1',
                'cells': {'قیمت هر 1000 عدد': '1,000 تومان', 'حداقل/حداکثر': '5,000/100'},
            }]},
        }

    def test_variation_and_thousand_unit_price_are_separate(self):
        rows = catalogue_rows(self.sample())
        self.assertEqual([(row['price'], row['price_per']) for row in rows], [(500, 1), (1000, 1000)])
        self.assertEqual(rows[0]['name'], 'Example - Pro')
        self.assertEqual((rows[1]['min_order'], rows[1]['max_order']), (100, 5000))

    def test_invalid_currency_fails_closed(self):
        snapshot = self.sample()
        snapshot['premstore']['variations'][0]['prices']['currency_code'] = 'IRR'
        with self.assertRaises(ValueError):
            catalogue_rows(snapshot)

    def test_variation_stock_and_evidence_are_independent_of_price_and_parent(self):
        snap=self.sample()
        variant=snap['premstore']['variations'][0]
        url='https://premstore.ir/product/example/?attribute_pa_plan=pro'
        variant.update(is_in_stock=False,is_purchasable=True,permalink=url)
        row=catalogue_rows(snap)[0]
        self.assertEqual((row['price'],row['available'],row['item_url'],row['url']),
                         (500,False,url,'https://premstore.ir/product/example/'))
        for ambiguous in (None,'false',0):
            variant['is_in_stock']=ambiguous
            with self.assertRaises(ValueError):catalogue_rows(snap)

    def test_dena_records_the_matching_public_detail_not_an_order_or_another_service(self):
        from .supplier_clients import DenaTable
        from .source_links import product_page
        table=DenaTable()
        table.feed('<tr data-service-id="21" data-status="1"><td><a href="/service/2/other/">a</a>'
                   '<a href="/service/21/plan/">b</a><a href="/dashboard/orders/new/?service-id=21">c</a></td></tr>')
        self.assertEqual(table.rows[0]['url'],'https://denapanel.ir/service/21/plan/')
        for url in ('https://example.net/product/a/', 'https://premstore.ir/product/a/?add-to-cart=1','#','javascript:void(0)'):
            self.assertEqual(product_page('premstore',url),'')

    def test_duplicate_identifier_fails_closed(self):
        snapshot = self.sample()
        snapshot['denapanel']['services'].append(snapshot['denapanel']['services'][0])
        with self.assertRaises(ValueError):
            catalogue_rows(snapshot)


class SupplierImportTests(TransactionTestCase):
    def setUp(self):
        from .models import Category, Product
        Product.objects.all().delete()
        Category.objects.all().delete()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from .models import Category, Product
        with connection.schema_editor() as editor:
            editor.create_model(Category)
            editor.create_model(Product)

    @classmethod
    def tearDownClass(cls):
        from .models import Category, Product
        with connection.schema_editor() as editor:
            editor.delete_model(Product)
            editor.delete_model(Category)
        super().tearDownClass()

    def test_import_is_idempotent_and_unpublished(self):
        from .models import Category, Product, SourceProduct
        existing_category = Category.objects.create(name='existing')
        existing = Product.objects.create(category=existing_category, name='Existing', price=123, platform='ai')
        with NamedTemporaryFile(mode='w+', encoding='utf-8') as source:
            json.dump(SupplierCatalogueTests().sample(), source)
            source.flush()
            call_command('import_source_catalog', source.name)
            self.assertEqual(Product.objects.count(), 1)
            call_command('import_source_catalog', source.name, apply=True)
            call_command('import_source_catalog', source.name, apply=True)
        self.assertEqual(Product.objects.count(), 3)
        self.assertEqual(SourceProduct.objects.count(), 2)
        self.assertFalse(Product.objects.exclude(pk=existing.pk).filter(is_active=True).exists())
        existing.refresh_from_db()
        self.assertEqual(existing.price, 123)

    def test_explicit_publish_uses_source_link_and_keeps_telegram_hidden(self):
        from .models import Product, SourceProduct
        from .services import public_products
        Product.objects.all().delete()
        with NamedTemporaryFile(mode='w+',encoding='utf-8') as source:
            json.dump(SupplierCatalogueTests().sample(),source)
            source.flush()
            call_command('import_source_catalog',source.name,apply=True,publish=True)
        self.assertEqual(public_products().count(),1)
        self.assertFalse(Product.objects.filter(platform='telegram',show_on_website=True).exists())
        self.assertFalse(Product.objects.filter(show_on_telegram=True).exists())
        self.assertEqual(SourceProduct.objects.count(),2)
