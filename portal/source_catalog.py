"""Validate the locally captured supplier catalogue before any database writes."""
import html
import re
from html.parser import HTMLParser
from urllib.parse import unquote


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {'p','h2','h3','li','div'}:
            self.parts.append('\n')

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')


def plain_text(value):
    parser = PlainText()
    parser.feed(html.unescape(value or ''))
    return ''.join(parser.parts).strip()


def catalogue_rows(snapshot):
    result = []
    products = snapshot['premstore']['products']
    variation_rows = snapshot['premstore']['variations']
    variants = {row['id']: row for row in variation_rows}
    if len(variants) != len(variation_rows):
        raise ValueError('Duplicate variant identifiers')
    for product in products:
        if product.get('type') not in {None, 'simple', 'variable'}:
            raise ValueError('Unsupported supplier product type')
        children = product.get('variations', [])
        if product.get('type') == 'variable' and not children:
            raise ValueError('Variable product has no identifiable plans')
        entries = [(variants[item['id']], item) for item in children] if children else [(product, None)]
        for entry, variation in entries:
            prices = entry['prices']
            if (prices.get('currency_code') != 'IRT' or prices.get('currency_minor_unit',0) != 0
                    or not str(prices.get('price', '')).isascii()
                    or not str(prices.get('price', '')).isdigit()):
                raise ValueError('Unsupported or missing Premstore price')
            price = int(prices['price'])
            if not 0 < price <= 100_000_000_000:
                raise ValueError('Invalid Premstore price')
            label = ''
            if variation:
                if entry.get('parent',product['id']) != product['id']:
                    raise ValueError('Variant belongs to a different product')
                labels = []
                for attr in variation.get('attributes', []):
                    value = attr.get('value', '')
                    for group in product.get('attributes', []):
                        for term in group.get('terms', []):
                            if term['slug'] == value:
                                value = term['name']
                    labels.append(unquote(value))
                label = ' - '.join(labels)
                if not label:
                    raise ValueError('Variant has no plan label')
            categories = product.get('categories', [])
            category = categories[0]['name'] if categories else 'اشتراک‌ها'
            result.append({
                'source': 'premstore', 'external_id': str(entry['id']),
                'category': html.unescape(category),
                'name': html.unescape(product['name']) + (' - ' + label if label else ''),
                'price': price, 'price_per': 1, 'min_order': 1, 'max_order': 1,
                'url': product['permalink'], 'available': bool(entry.get('is_in_stock')),
                'description': plain_text(entry.get('description') or product.get('short_description')),
                'platform': 'ai' if category == 'هوش مصنوعی' else 'other',
                'plan_name': label[:80],
                'family_name': html.unescape(product['name']),
                'family_summary': plain_text(product.get('short_description')),
            })
    for entry in snapshot['denapanel']['services']:
        cells = entry['cells']
        price_match = re.fullmatch(r'([\d,]+)\s*تومان', cells.get('قیمت هر 1000 عدد', ''))
        limits_match = re.fullmatch(r'([\d,]+)/([\d,]+)', cells.get('حداقل/حداکثر', ''))
        if not price_match or not limits_match:
            raise ValueError('Invalid Dena service price or limits: ' + entry['id'])
        maximum, minimum = (int(value.replace(',', '')) for value in limits_match.groups())
        price = int(price_match[1].replace(',', ''))
        if not 0 < price <= 100_000_000_000 or not 0 < minimum <= maximum <= 100_000_000:
            raise ValueError('Invalid Dena service values: ' + entry['id'])
        result.append({
            'source': 'denapanel', 'external_id': entry['id'],
            'category': entry.get('category_name') or 'خدمات تلگرام ' + entry['category_id'],
            'name': entry['name'], 'price': price, 'price_per': 1000,
            'min_order': minimum, 'max_order': maximum, 'url': entry.get('url', ''),
            'available': entry.get('status') == '1',
            'description': plain_text(entry.get('description')),
            'platform': 'telegram', 'plan_name': '',
        })
    keys = [(row['source'], row['external_id']) for row in result]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate supplier identifiers')
    return result
