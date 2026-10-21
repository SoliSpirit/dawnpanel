from django import template
from portal.services import price_for, BusinessError
register = template.Library()

@register.simple_tag
def card_price(product):
    # Reuse checkout pricing, including currency rates, profit and rounding.
    try:
        return format(price_for(product, product.min_order)[1], ',')
    except BusinessError:
        return None


@register.simple_tag
def product_image(product):
    from django.templatetags.static import static
    visual=product.visual
    if visual and visual.image:
        return visual.image.url
    if product.platform=='ai':
        name=product.name.casefold()
        kind='gemini' if ('gemini' in name or 'جمینای' in name) else 'claude' if ('claude' in name or 'کلاد' in name or 'کلود' in name) else 'chatgpt' if ('gpt' in name or 'جی پی تی' in name) else 'ai'
        return static('artwork/'+kind+'.webp')
    return static('artwork/social.webp')

@register.filter
def storefront_description(product):
    import re
    text=product.description or ''
    if text.startswith('شناسه خدمت در سایت قبلی:'):
        text=text.split('؛',1)[-1].strip()
        text=re.sub(r'^#\d+\s*\|\s*','',text).replace('|',' · ')
    return text or 'قیمت، شرایط و جزئیات این محصول را پیش از سفارش بررسی کنید.'
