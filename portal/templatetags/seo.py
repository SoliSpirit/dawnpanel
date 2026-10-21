import json
from django import template
from django.utils.safestring import mark_safe
from django.templatetags.static import static
from .storefront import product_image,storefront_description
register=template.Library()
@register.simple_tag(takes_context=True)
def structured_data(context):
    request=context['request'];base='https://dawnpanel.ir'
    data={'@context':'https://schema.org','@type':'WebSite','name':'دان پنل','url':base,'inLanguage':'fa-IR','potentialAction':{'@type':'SearchAction','target':base+'/services/?q={search_term_string}','query-input':'required name=search_term_string'}}
    post=context.get('post');product=context.get('product')
    if post:
        data={'@context':'https://schema.org','@type':'BlogPosting','headline':post.title,'description':post.summary,'datePublished':post.created_at.isoformat(),'dateModified':post.updated_at.isoformat(),'url':base+post.get_absolute_url(),'inLanguage':'fa-IR','author':{'@type':'Organization','name':'تحریریه دان پنل','url':base+'/about/'},'publisher':{'@type':'Organization','name':'دان پنل','url':base}}
    elif product:
        data={'@context':'https://schema.org','@type':'Service','name':product.name,'description':product.seo_description or storefront_description(product),'url':base+product.get_absolute_url(),'serviceType':product.get_platform_display(),'provider':{'@type':'Organization','name':'دان پنل','url':base}}
    if product:
        data['image']='https://dawnpanel.ir'+product_image(product)
        if product.platform=='ai':
            data['@type']='Product'
            data['sku']=str(product.pk)
            data.pop('serviceType',None)
            data.pop('provider',None)
            from portal.services import price_for,BusinessError
            try:
                price=price_for(product,product.min_order)[0]
                data['offers']={'@type':'Offer','price':price*10,'priceCurrency':'IRR','url':base+product.get_absolute_url(),'availability':'https://schema.org/InStock','seller':{'@type':'Organization','name':'دان پنل'},'description':'قیمت برای '+str(product.min_order)+' اشتراک طبق شرایط محصول'}
            except BusinessError:
                pass
    if data['@type']!='Product': data['inLanguage']='fa-IR'
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return mark_safe('<script type="application/ld+json">'+payload+'</script>')

@register.simple_tag(takes_context=True)
def page_seo(context):
    request=context['request'];product=context.get('product')
    title=context.get('title') or 'دان پنل | اشتراک هوش مصنوعی و خدمات دیجیتال'
    description=context.get('description') or 'فروشگاه اشتراک هوش مصنوعی و خدمات پیام‌رسان با حساب یکپارچه و پشتیبانی تیکتی در دان پنل.'
    image=product_image(product) if product else static('artwork/hero.webp')
    private=request.path.startswith(('/account/','/login/','/manage/','/staff/','/payment/'))
    filtered=bool(request.GET.get('q') or request.GET.get('platform') or request.GET.get('page'))
    return {'title':title,'description':description,'image':'https://dawnpanel.ir'+image,'canonical':'https://dawnpanel.ir'+request.path,'robots':'noindex,follow' if private or filtered else 'index,follow,max-image-preview:large'}
