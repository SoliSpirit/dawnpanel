from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from io import BytesIO
from PIL import Image

from hashlib import sha256
from .product_art import BRANDS, GALLERY_KEYS, artwork_key, gallery_path, gallery_jpeg
from .service_art import SERVICE_TITLES
from .store_catalog import TAXONOMY
from .templatetags.storefront import CATEGORY_COVERS


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class CategoryCoverTests(SimpleTestCase):
    def test_gallery_artwork_resolves_and_has_two_valid_renditions(self):
        identities=set()
        for _, label, _, _ in BRANDS:
            with self.subTest(brand=label):
                identities.add(artwork_key(None,'other',label))
        for platform, items in SERVICE_TITLES.items():
            for pk,name in items.items():
                identities.add(artwork_key(pk,platform,name))
        self.assertEqual(identities, GALLERY_KEYS)
        fingerprints=set()
        for key in identities:
            with self.subTest(illustration=key):
                for small,size in [(True,(480,320)),(False,(960,640))]:
                    asset = finders.find(gallery_path(key,small=small))
                    self.assertIsNotNone(asset)
                    with Image.open(asset) as image:
                        self.assertEqual((image.format,image.size),('WEBP',size))
                        if small:
                            fingerprints.add(sha256(image.tobytes()).digest())
        self.assertEqual(len(fingerprints),len(identities))

    def test_distinct_reactions_and_bot_skus_do_not_get_an_unrelated_cover(self):
        self.assertNotEqual(artwork_key(30,'rubika','ری اکشن چشم 😍'),artwork_key(31,'rubika','ری اکشن چشم 😍'))
        self.assertIsNone(artwork_key(30,'rubika','Another service'))
        key=artwork_key(32,'ai',SERVICE_TITLES['ai'][32],'ChatGPT')
        self.assertNotEqual(key,artwork_key(None,'ai','ChatGPT'))
        with Image.open(BytesIO(gallery_jpeg(key))) as image:
            self.assertEqual((image.format,image.size),('JPEG',(960,640)))
            image.verify()

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
        self.assertIn('href="/ai/"', html)
        self.assertIn('aria-current="page"', html)
        self.assertIn('data-theme-light', html)
        self.assertIn('alt=""', html)
        self.assertIn('هوش مصنوعی', html)
