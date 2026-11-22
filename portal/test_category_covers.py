from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from io import BytesIO
from PIL import Image

from .product_art import BRANDS, brand_cover, service_cover
from .store_catalog import TAXONOMY
from .templatetags.storefront import CATEGORY_COVERS


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class CategoryCoverTests(SimpleTestCase):
    def test_brand_photos_and_generated_service_photo_are_valid(self):
        for _, label, _, _ in BRANDS:
            with self.subTest(brand=label):
                asset = finders.find(brand_cover(label))
                self.assertIsNotNone(asset)
                with Image.open(asset) as image:
                    self.assertEqual((image.format, image.size), ('JPEG', (540, 360)))
        with Image.open(BytesIO(service_cover(1, 'telegram', 'Telegram service'))) as image:
            image.verify()
        self.assertNotEqual(service_cover(1, 'telegram', 'A'), service_cover(2, 'telegram', 'B'))

    def test_faq_has_four_sections_and_no_foreign_checkout_links(self):
        response = self.client.get(reverse('faq'))
        self.assertContains(response, '<details>', count=16)
        self.assertNotContains(response, 'premstore.ir')

    def test_all_storefront_sections_have_local_cover_assets(self):
        self.assertEqual(set(CATEGORY_COVERS), {key for key, *_ in TAXONOMY})
        for key, paths in CATEGORY_COVERS.items():
            with self.subTest(section=key):
                self.assertTrue(paths[0])
                for path in filter(None, paths):
                    self.assertIsNotNone(finders.find(path))

    def test_cover_is_decorative_and_keeps_the_selected_category_link(self):
        html = render_to_string('partials/category_tiles.html', {
            'categories': [{'key': 'ai', 'name': 'هوش مصنوعی', 'count': 10}],
            'section': 'ai',
        })
        self.assertIn('href="/services/?section=ai"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('data-theme-light', html)
        self.assertIn('alt=""', html)
        self.assertIn('هوش مصنوعی', html)
