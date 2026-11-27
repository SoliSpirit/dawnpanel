"""Read public catalogues from fixed hosts; never follow supplier-provided URLs."""
import json
import time
from html.parser import HTMLParser

import requests

from .source_catalog import catalogue_rows
from .source_links import product_page


class SupplierError(ValueError):
    pass


def read_json(url, *, data=None, deadline=None):
    if not url.startswith(('https://premstore.ir/wp-json/wc/store/v1/products',
                           'https://denapanel.ir/wp-admin/admin-ajax.php')):
        raise SupplierError('نشانی منبع مجاز نیست.')
    try:
        method = 'POST' if data else 'GET'
        timeout = (8,25)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SupplierError('مهلت دریافت از منبع تمام شد.')
            timeout = (min(4,remaining/2),min(8,remaining/2))
        with requests.request(method, url, data=data, timeout=timeout,
                              allow_redirects=False, stream=True,
                              headers={'User-Agent': 'DawnPanel-Catalog/1.0','Cache-Control':'no-cache'}) as response:
            if response.status_code != 200:
                raise SupplierError('منبع پاسخ معتبر نداد.')
            chunks = []
            size = 0
            for chunk in response.iter_content(65536):
                if deadline is not None and time.monotonic() >= deadline:
                    raise SupplierError('مهلت دریافت از منبع تمام شد.')
                size += len(chunk)
                if size > 10_000_000:
                    raise SupplierError('حجم پاسخ منبع بیش از حد مجاز است.')
                chunks.append(chunk)
            return json.loads(b''.join(chunks).decode('utf-8-sig'))
    except (requests.RequestException, UnicodeError, ValueError) as error:
        if isinstance(error, SupplierError):
            raise
        raise SupplierError('دریافت اطلاعات منبع ناموفق بود.') from None


class DenaTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.category = ''
        self.heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h5':
            self.heading = True
            self.category = ''
        if tag == 'tr' and 'data-service-id' in attrs:
            self.row = {
                'id': attrs['data-service-id'], 'name': attrs.get('data-service-name', ''),
                'category_id': attrs.get('data-category', ''), 'category_name': self.category.strip(),
                'status': attrs.get('data-status', ''), 'cells': {},
            }
        elif self.row is not None and tag == 'td':
            self.cell = attrs.get('data-title', '')
            self.row['cells'][self.cell] = ''
        elif self.row is not None and tag == 'a':
            url = product_page('denapanel', attrs.get('href'), self.row['id'])
            if url:
                self.row['url'] = url
        if self.row is not None and 'data-desc' in attrs:
            self.row['description'] = attrs['data-desc']

    def handle_data(self, data):
        if self.heading:
            self.category += data
        if self.row is not None and self.cell is not None:
            self.row['cells'][self.cell] += data

    def handle_endtag(self, tag):
        if tag == 'h5':
            self.heading = False
        if tag == 'td':
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.row['cells'] = {k: ' '.join(v.split()) for k, v in self.row['cells'].items()}
            self.rows.append(self.row)
            self.row = None


def fetch_catalogue(source, *, deadline=None):
    snapshot = {'premstore': {'products': [], 'variations': []}, 'denapanel': {'services': []}}
    if source == 'premstore':
        for kind, key in [('', 'products'), ('variation', 'variations')]:
            for page in range(1, 11):
                rows = read_json(
                    'https://premstore.ir/wp-json/wc/store/v1/products'
                    f'?per_page=100&page={page}' + ('&type=variation' if kind else ''), deadline=deadline)
                if not isinstance(rows, list):
                    raise SupplierError('ساختار فهرست پریم‌استور تغییر کرده است.')
                snapshot['premstore'][key].extend(rows)
                if len(rows) < 100:
                    break
            else:
                raise SupplierError('فهرست پریم‌استور بیش از حد مجاز صفحه دارد.')
    elif source == 'denapanel':
        parser = DenaTable()
        page = 1
        while page <= 10:
            response = read_json('https://denapanel.ir/wp-admin/admin-ajax.php',
                                 data={'action': 'kando_get_categories', 'page': page}, deadline=deadline)
            if not isinstance(response, dict) or not response.get('success'):
                raise SupplierError('ساختار فهرست دناپنل تغییر کرده است.')
            try:
                data = response['data']
                pagination = data['pagination']
                current, total = int(pagination['current_page']), int(pagination['total_pages'])
                body = data['html']
            except (KeyError,TypeError,ValueError):
                raise SupplierError('ساختار فهرست دناپنل تغییر کرده است.') from None
            if not isinstance(body,str) or current != page or not page <= total <= 10:
                raise SupplierError('صفحه‌بندی دناپنل معتبر نیست.')
            parser.feed(body)
            if page == total:
                break
            page += 1
        snapshot['denapanel']['services'] = parser.rows
    else:
        raise SupplierError('منبع ناشناخته است.')
    try:
        rows = catalogue_rows(snapshot)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SupplierError('قیمت‌ها یا مشخصات منبع قابل تأیید نیستند.') from None
    if not rows:
        raise SupplierError('فهرست خالی است؛ قیمت‌های قبلی حفظ شدند.')
    return rows
