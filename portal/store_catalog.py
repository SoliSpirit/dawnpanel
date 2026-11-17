"""Presentation-only taxonomy. Plans retain their original checkout identities."""
from collections import OrderedDict
from dataclasses import dataclass
import re
import unicodedata

from .models import ProductVisual, SourceProduct
from .services import BusinessError, price_for, public_products


TAXONOMY = [
    ('ai', 'هوش مصنوعی', '✦', 'نوشتن، ساختن و ایده‌پردازی'),
    ('business', 'بهره‌وری و کسب‌وکار', '▤', 'ابزارهای کار و مدیریت'),
    ('development', 'برنامه‌نویسی و توسعه', '⌘', 'همراه توسعه‌دهنده‌ها'),
    ('music', 'موسیقی و صدا', '♫', 'شنیدن، تمرکز و کشف'),
    ('design', 'طراحی و تدوین', '◈', 'از ایده تا تصویر'),
    ('education', 'آموزش و مهارت', '↗', 'هر روز یک قدم جلوتر'),
    ('software', 'نرم‌افزار و سیستم‌عامل', '⊞', 'ابزارهای کاربردی دیجیتال'),
    ('video', 'فیلم و ویدیو', '▷', 'دنیای تماشا و سرگرمی'),
    ('social', 'اشتراک شبکه‌های اجتماعی', '◎', 'امکانات بیشتر، تجربه بهتر'),
    ('telegram', 'خدمات تلگرام', '➤', 'ممبر، بازدید و خدمات کانال'),
    ('rubika', 'خدمات روبیکا', '◉', 'خدمات کانال و محتوا'),
    ('eitaa', 'خدمات ایتا', '◌', 'خدمات کانال و محتوا'),
    ('bale', 'خدمات بله', '◍', 'خدمات کانال و محتوا'),
    ('subscriptions', 'سایر اشتراک‌ها', '＋', 'انتخاب‌های بیشتر'),
]
CATEGORY_MAP = {
    'هوش مصنوعی':'ai', 'بهره‌وری و کسب‌وکار':'business',
    'برنامه‌نویسی و توسعه':'development', 'موزیک':'music',
    'طراحی و تدوین':'design', 'آموزش و مهارت':'education',
    'سیستم‌عامل و نرم‌افزار':'software', 'فیلم و ویدیو':'video',
    'شبکه‌های اجتماعی':'social',
}
MESSAGING = {'telegram','rubika','eitaa','bale'}
SEARCH_CHARS = str.maketrans('يك۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', 'یک01234567890123456789')
BRANDS = (
    ('chatgpt', ('chatgpt', 'chat gpt', 'چت جی پی تی', 'چت جیپیتی')),
    ('gemini', ('gemini', 'جمینای')),
    ('claude', ('claude', 'کلاد', 'کلود')),
)


def search_text(value):
    text = unicodedata.normalize('NFKC', value).casefold().translate(SEARCH_CHARS)
    text = ''.join(char for char in text if not unicodedata.combining(char) and char != 'ـ')
    return ' '.join(re.findall(r'[^\W_]+', text))


def section_for(product, link=None):
    if link and link.source == 'premstore':
        return CATEGORY_MAP.get(product.category.name, 'ai' if product.platform == 'ai' else 'subscriptions')
    return product.platform if product.platform in {'ai','telegram','rubika','eitaa','bale'} else 'subscriptions'


def payable(product):
    try:
        return price_for(product, product.min_order)[0]
    except BusinessError:
        return None


@dataclass
class Family:
    name: str
    summary: str
    section: str
    plans: list
    imported: bool

    @property
    def first(self):
        return self.plans[0]

    @property
    def url(self):
        return self.first.get_absolute_url()

    @property
    def minimum(self):
        prices = [p.catalog_price for p in self.plans if p.catalog_price is not None]
        return min(prices) if prices else None

    @property
    def label(self):
        return next(row[1] for row in TAXONOMY if row[0] == self.section)

    @property
    def subscription(self):
        return self.imported or self.section not in MESSAGING


def known_ai_brand(name):
    text = ' '+search_text(name)+' '
    matches = [brand for brand,aliases in BRANDS if any(' '+alias+' ' in text for alias in aliases)]
    return matches[0] if len(matches) == 1 else None


def families():
    products = list(public_products().select_related('category').order_by('id'))
    visuals = {v.product_id:v for v in ProductVisual.objects.filter(product_id__in=[p.pk for p in products])}
    links = {s.product_id:s for s in SourceProduct.objects.filter(product_id__in=[p.pk for p in products])}
    groups = OrderedDict()
    for p in products:
        p._visual_cache = visuals.get(p.pk)
        p.catalog_price = payable(p)
        link = links.get(p.pk)
        imported = bool(link and link.source == 'premstore')
        # No guessing from names: only the supplier's shared parent URL groups plans.
        key = ('premstore',link.source_url) if imported and link.source_url else ('product',p.pk)
        if key not in groups:
            label = p.visual.plan_name if p.visual else ''
            name = link.family_name if imported else ''
            if not name:
                suffix = ' - ' + label
                name = p.name[:-len(suffix)] if label and p.name.endswith(suffix) else p.name
            groups[key] = Family(name, link.family_summary if imported else '',
                                 section_for(p,link), [], imported)
        groups[key].plans.append(p)
    # Original merchant plans remain purchasable. Only recognized AI brands with
    # exactly one imported parent share a display card; no source link is created.
    imported_brands = {}
    for family in groups.values():
        brand = known_ai_brand(family.name)
        if family.imported and brand:
            imported_brands.setdefault(brand, []).append(family)
    for key,family in list(groups.items()):
        if family.imported or family.section != 'ai' or family.first.pk in links:
            continue
        matches = imported_brands.get(known_ai_brand(family.name), [])
        if len(matches) == 1:
            matches[0].plans.extend(family.plans)
            del groups[key]
    for family in groups.values():
        family.plans.sort(key=lambda p:(p.catalog_price is None,p.catalog_price or 0,p.pk))
    order = {row[0]:index for index,row in enumerate(TAXONOMY)}
    return sorted(groups.values(), key=lambda f:(order[f.section],not f.imported,f.first.pk))


def category_tiles(items):
    return [dict(key=key,name=name,symbol=symbol,description=description,
                 count=sum(f.section == key for f in items))
            for key,name,symbol,description in TAXONOMY
            if any(f.section == key for f in items)]


def filter_families(items, *, section='', platform='', category='', query='', collection=''):
    result = []
    query = search_text(query)
    terms = next((aliases for _,aliases in BRANDS if query in aliases), ())
    for family in items:
        if section and family.section != section:
            continue
        if collection and (family.section in MESSAGING) != (collection == 'messaging'):
            continue
        matches = [p for p in family.plans if (not platform or p.platform == platform)
                   and (not category or str(p.category_id) == category)]
        if not matches:
            continue
        if query:
            text = search_text(' '.join([family.name,family.summary]+
                [p.name+' '+(p.description or '') for p in matches]))
            if terms and not any(term in text for term in terms):
                continue
            if not terms and not all(word in text for word in query.split()):
                continue
        result.append(family)
    return result
