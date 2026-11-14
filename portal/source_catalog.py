"""Validate the locally captured supplier catalogue before any database writes."""
import html
import re
from urllib.parse import unquote


def catalogue_rows(snapshot):
    result = []
    products = snapshot['premstore']['products']
    variants = {row['id']: row for row in snapshot['premstore']['variations']}
    for product in products:
        children = product.get('variations', [])
        entries = [(variants[item['id']], item) for item in children] if children else [(product, None)]
        for entry, variation in entries:
            prices = entry['prices']
            if prices.get('currency_code') != 'IRT' or not str(prices.get('price', '')).isdigit():
                raise ValueError('Unsupported or missing Premstore price')
            price = int(prices['price'])
            if price <= 0:
                raise ValueError('Invalid Premstore price')
            label = ''
            if variation:
                labels = []
                for attr in variation.get('attributes', []):
                    value = attr.get('value', '')
                    for group in product.get('attributes', []):
                        for term in group.get('terms', []):
                            if term['slug'] == value:
                                value = term['name']
                    labels.append(unquote(value))
                label = ' - '.join(labels)
            categories = product.get('categories', [])
            result.append({
                'source': 'premstore', 'external_id': str(entry['id']),
                'category': categories[0]['name'] if categories else 'اشتراک‌ها',
                'name': html.unescape(product['name']) + (' - ' + label if label else ''),
                'price': price, 'price_per': 1, 'min_order': 1, 'max_order': 1,
                'url': product['permalink'], 'available': bool(entry.get('is_in_stock')),
            })
    for entry in snapshot['denapanel']['services']:
        cells = entry['cells']
        price_match = re.fullmatch(r'([\d,]+)\s*تومان', cells.get('قیمت هر 1000 عدد', ''))
        limits_match = re.fullmatch(r'([\d,]+)/([\d,]+)', cells.get('حداقل/حداکثر', ''))
        if not price_match or not limits_match:
            raise ValueError('Invalid Dena service price or limits: ' + entry['id'])
        maximum, minimum = (int(value.replace(',', '')) for value in limits_match.groups())
        price = int(price_match[1].replace(',', ''))
        if not price or not 0 < minimum <= maximum:
            raise ValueError('Invalid Dena service values: ' + entry['id'])
        result.append({
            'source': 'denapanel', 'external_id': entry['id'],
            'category': 'خدمات تلگرام ' + entry['category_id'],
            'name': entry['name'], 'price': price, 'price_per': 1000,
            'min_order': minimum, 'max_order': maximum, 'url': entry.get('url', ''),
            'available': entry.get('status') == '1',
        })
    keys = [(row['source'], row['external_id']) for row in result]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate supplier identifiers')
    return result
