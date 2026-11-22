from django import template
from django.templatetags.static import static
from portal.product_art import artwork_key, gallery_path
from portal.pricing import pricing_for, BusinessError
register = template.Library()

CATEGORY_COVERS = {
    'ai': ('artwork/ai-480.webp', 'artwork/ai-light-480.webp'),
    'rubika': ('artwork/products-v1/rubika-dark-480.webp', 'artwork/products-v1/rubika-light-480.webp'),
    'eitaa': ('artwork/products-v1/eitaa-dark-480.webp', 'artwork/products-v1/eitaa-light-480.webp'),
    'bale': ('artwork/products-v1/bale-dark-480.webp', 'artwork/products-v1/bale-light-480.webp'),
    'telegram': ('artwork/categories/telegram.svg', ''),
    'subscriptions': ('artwork/hero-480.webp', 'artwork/hero-light-480.webp'),
    **{key: (f'artwork/categories/{key}.webp', '') for key in
       ('business', 'development', 'music', 'design', 'education', 'software', 'video', 'social')},
}


@register.simple_tag
def category_cover(key):
    image, light = CATEGORY_COVERS.get(key, CATEGORY_COVERS['subscriptions'])
    return {'image': static(image), 'light': static(light) if light else ''}


@register.simple_tag
def family_icon(family):
    """Use local brand marks; never hotlink logos or mislabel unknown brands."""
    from django.templatetags.static import static
    name=family.name.casefold()
    for key,aliases in [
        ('chatgpt',('gpt','جی پی تی','جی‌پی‌تی')),
        ('gemini',('gemini','جمینای')),('claude',('claude','کلاد','کلود')),
        ('telegram',('telegram','تلگرام')),('eitaa',('ایتا',)),
        ('bale',('بله',)),('spotify',('spotify','اسپاتیفای')),
        ('netflix',('netflix','نتفلیکس')),('notion',('notion','نوشن')),
        ('duolingo',('duolingo','دولینگو')),
        ('github',('github','گیت‌هاب')),('perplexity',('perplexity','پرپلکسیتی')),
        ('deezer',('deezer','دیزر')),('elevenlabs',('elevenlabs','الون‌لبز')),
        ('youtube',('youtube','یوتیوب')),
    ]:
        if any(alias in name for alias in aliases):
            return static('platforms/'+key+'.svg')
    return ''


def cover_visual(product):
    for candidate in (product, *getattr(product, 'web_aliases', ())):
        visual = candidate.visual
        if visual and (visual.image or visual.night_image):
            return visual


def plan_key(product, family_name=''):
    if product.platform == 'ai' and getattr(product, 'web_aliases', None):
        product = product.web_aliases[0]  # use the plan-specific native illustration
    return artwork_key(product.pk, product.platform, product.name, family_name)


@register.simple_tag
def family_cover(family, product=None):
    selected = bool(product)
    product = product or family.first
    visual = cover_visual(product)
    if visual:
        dark = (visual.night_image or visual.image).url
        light = (visual.image or visual.night_image).url
        return {'image': dark, 'light': light}
    key = (plan_key(product, family.name) if selected or not family.imported
           else artwork_key(product.pk, product.platform, family.name))
    return {'image': static(gallery_path(key)), 'small': static(gallery_path(key, small=True))}

@register.simple_tag
def card_price(product):
    # Reuse checkout pricing, including currency rates, profit and rounding.
    try:
        pricing=pricing_for(product)
        pricing.quote(product.min_order)
        return format(pricing.amounts(pricing.price_per).total, ',')
    except BusinessError:
        return None


@register.simple_tag
def product_image(product,theme='light',width=None):
    from django.templatetags.static import static
    visual=cover_visual(product)
    uploaded=(visual.night_image if theme=='dark' else visual.image) if visual else None
    if uploaded:
        return uploaded.url
    key = plan_key(product)
    return static(gallery_path(key, small=width==480))

@register.simple_tag
def post_image(post,theme='light',width=None):
    from django.templatetags.static import static
    kind=['social','ai','hero'][post.pk%3]
    return static('artwork/'+kind+('-light' if theme=='light' else '')+('-480' if width==480 else '')+'.webp')

@register.filter
def storefront_description(product):
    import re
    text=product.description or ''
    if text.startswith('شناسه خدمت در سایت قبلی:'):
        text=text.split('؛',1)[-1].strip()
        text=re.sub(r'^#\d+\s*\|\s*','',text).replace('|',' · ')
    return text or 'قیمت، شرایط و جزئیات این محصول را پیش از سفارش بررسی کنید.'
