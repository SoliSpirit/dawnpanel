from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from .store_catalog import TAXONOMY
from .templatetags.storefront import CATEGORY_COVERS


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class CategoryCoverTests(SimpleTestCase):
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
