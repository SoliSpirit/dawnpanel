from django import template
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.templatetags.static import static
register=template.Library()
@register.filter
def number(value):
    try:return format(int(value),',')
    except (ValueError,TypeError):return value


@register.filter
def fa_number(value):
    return str(number(value)).translate(str.maketrans('0123456789,', '۰۱۲۳۴۵۶۷۸۹٬'))
@register.simple_tag
def platform_icon(name):
    if name=='other':return icon('grid')
    name=name if name in {'telegram','eitaa','bale','rubika','chatgpt','gemini','claude','instagram'} else 'gemini'
    extension='.png' if name=='rubika' else '.svg'
    return format_html('<img class="platform-logo" src="{}" alt="" width="32" height="32" loading="lazy" decoding="async">',static('platforms/'+name+extension))
PATHS={
 'menu':'<path d="M3 6h18M3 12h18M3 18h18"/>',
 'bag':'<path d="M5 7h14l1 13H4L5 7Z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
 'box':'<path d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm-9 5 9 5 9-5m-9 5v10m-4.5-17.5L16.5 10"/>',
 'tag':'<path d="M3 3h8l10 10-8 8L3 11V3Z"/><circle cx="7.5" cy="7.5" r="1"/>',
 'layers':'<path d="m12 3 10 5-10 5L2 8l10-5Zm-9 10 9 4.5 9-4.5M3 17l9 4.5 9-4.5"/>',
 'calendar':'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18m-13 4h3m2 3h3"/>',
 'plot':'<path d="M3 4v16h18M6 15l4-5 4 2 6-7"/>',
 'plus':'<path d="M12 5v14M5 12h14"/>',
 'inbox':'<path d="m3 14 3-9h12l3 9v5H3v-5Zm0 0h5l2 3h4l2-3h5"/>',
 'left':'<path d="M20 12H4m6 6-6-6 6-6"/>',
 'chevron':'<path d="m14 6-6 6 6 6"/>',
 'store':'<path d="M3 10 5 4h14l2 6M4 12v8h16v-8M3 10a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0M9 20v-6h5v6"/>',
 'search':'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
 'user':'<circle cx="12" cy="7" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/>',
 'wallet':'<path d="M20 8V5a2 2 0 0 0-2-2H5a3 3 0 0 0 0 6h15v12H5a3 3 0 0 1-3-3V6m18 7h-5v4h5"/>',
 'grid':'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
 'spark':'<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z"/>',
 'chat':'<path d="M21 11a8 8 0 0 1-8 8H7l-5 3V11a9 9 0 0 1 19 0Z"/><path d="M7 10h8m-8 4h5"/>',
 'clock':'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
 'shield':'<path d="m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5l8-3Z"/><path d="m8 11 3 3 5-6"/>',
 'book':'<path d="M12 5v16M3 3h5a4 4 0 0 1 4 3 4 4 0 0 1 4-3h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3V3Z"/>',
 'arrow':'<path d="M5 12h14m-6-6 6 6-6 6"/>',
 'headset':'<path d="M3 13v-1a9 9 0 0 1 18 0v5a4 4 0 0 1-4 4h-4M3 11h4v7H3v-7Zm14 0h4v7h-4v-7Z"/>'}
@register.simple_tag
def icon(name):
    path=PATHS.get(name,PATHS['spark'])
    return mark_safe('<svg class="ui-icon" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+path+'</svg>')
