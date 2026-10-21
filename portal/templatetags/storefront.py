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
