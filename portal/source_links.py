"""Public product pages supplied as evidence. Never use these URLs for fetching."""
import re
from urllib.parse import parse_qsl, unquote, urlsplit


def product_page(source, value, external_id=''):
    hosts = {'premstore':'premstore.ir', 'denapanel':'denapanel.ir'}
    host = hosts.get(source)
    if not host or not isinstance(value, str) or not value or len(value) > 2000:
        return ''
    if value.startswith('/') and not value.startswith('//'):
        value = f'https://{host}{value}'
    if len(value) > 2000 or re.search(r'[\x00-\x20\x7f\\]', value):
        return ''
    try:
        parts = urlsplit(value)
        if parts.scheme != 'https' or parts.netloc.lower() not in {host, 'www.' + host}:
            return ''
        path = unquote(parts.path)
        if re.search(r'[\x00-\x1f\x7f\\]', path) or '..' in path.split('/') or parts.fragment:
            return ''
        if source == 'premstore':
            if not re.fullmatch(r'/product/[^/]+/?', path):
                return ''
            # Variation permalinks carry the selected plan, never a cart action.
            if any(not key.startswith('attribute_') for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
                return ''
        elif not re.fullmatch(r'/service/'+re.escape(str(external_id))+r'(?:/[^/]*)?/?', path) or parts.query:
            return ''
    except ValueError:
        return ''
    return value
