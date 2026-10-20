import json
from django import template
from django.utils.safestring import mark_safe
register=template.Library()
@register.simple_tag(takes_context=True)
def structured_data(context):
    request=context['request'];base='https://dawnpanel.ir'
    data={'@context':'https://schema.org','@type':'WebSite','name':'دان پنل','url':base,'inLanguage':'fa-IR','potentialAction':{'@type':'SearchAction','target':base+'/services/?q={search_term_string}','query-input':'required name=search_term_string'}}
    post=context.get('post');product=context.get('product')
    if post:
        data={'@context':'https://schema.org','@type':'BlogPosting','headline':post.title,'description':post.summary,'datePublished':post.created_at.isoformat(),'dateModified':post.updated_at.isoformat(),'url':base+post.get_absolute_url(),'inLanguage':'fa-IR','author':{'@type':'Organization','name':'تحریریه دان پنل','url':base+'/about/'},'publisher':{'@type':'Organization','name':'دان پنل','url':base}}
    elif product:
        data={'@context':'https://schema.org','@type':'Service','name':product.name,'description':product.description or product.name,'url':base+product.get_absolute_url(),'serviceType':product.get_platform_display(),'provider':{'@type':'Organization','name':'دان پنل','url':base}}
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return mark_safe('<script type="application/ld+json">'+payload+'</script>')
