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
 'gauge':'<path d="M4 18a9 9 0 1 1 16 0H4ZM6 13h1m2-5 1 1m6-1-4 5"/><circle cx="12" cy="14" r="1.2"/>',
 'receipt':'<path d="M5 3l2 1.5L9.5 3 12 4.5 14.5 3 17 4.5 19 3v18l-2-1.5-2.5 1.5-2.5-1.5-2.5 1.5L7 19.5 5 21V3Z"/><path d="M8.5 8h7m-7 4h7m-7 4h4"/>',
 'folders':'<path d="M3 16V6a2 2 0 0 1 2-2h4l2 2h7"/><path d="M6 10a1 1 0 0 1 1-1h5l2 2h6a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1Z"/>',
 'transfer':'<path d="M3 7h16m-4-4 4 4-4 4M21 17H5m4-4-4 4 4 4"/>',
 'coins':'<ellipse cx="9" cy="6" rx="6" ry="3"/><path d="M3 6v5c0 1.7 2.7 3 6 3m6-8v3"/><ellipse cx="15" cy="12" rx="6" ry="3"/><path d="M9 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/>',
 'gift':'<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M5 12v8h14v-8M12 8v12M12 8c-4 0-6-1-6-3a2 2 0 0 1 4-1l2 4Zm0 0c4 0 6-1 6-3a2 2 0 0 0-4-1l-2 4Z"/>',
 'id-card':'<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><circle cx="8.5" cy="10" r="2"/><path d="M5 16a3.5 3.5 0 0 1 7 0m2-6h4m-4 4h3"/>',
 'award':'<circle cx="12" cy="8.5" r="5.5"/><path d="m8.5 13-2 8 5.5-3 5.5 3-2-8"/>',
 'users':'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20v-1a6.5 6.5 0 0 1 13 0v1m0-15a3.5 3.5 0 0 1 0 6.5M18 14a5 5 0 0 1 3.5 4.8V20"/>',
 'pen':'<path d="m4 20 4.5-1 12-12a1.7 1.7 0 0 0 0-2.4l-1.2-1.2a1.7 1.7 0 0 0-2.4 0l-12 12L4 20ZM15 6l3.5 3.5"/>',
 'ticket':'<path d="M3 6h18v4a2 2 0 0 0 0 4v4H3v-4a2 2 0 0 0 0-4V6Z"/><path d="M15 7v2m0 2v2m0 2v2"/>',
 'tags':'<path d="M3 4h7l9 9-7 7-9-9V4Zm11-1 8 8-1 3"/><circle cx="7" cy="8" r="1"/>',
 'sliders':'<path d="M3 7h3m5 0h10M3 17h10m5 0h3"/><circle cx="8.5" cy="7" r="2.5"/><circle cx="15.5" cy="17" r="2.5"/>',
 'megaphone':'<path d="M4 9h5l11-5v15L9 14H4V9Zm5 5 1.5 6H7l-1.5-6M9 9v5"/>',
 'target':'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
 'activity':'<path d="M2 12h5l3-8 4 16 3-8h5"/>',
 'history':'<path d="M3 10a9 9 0 1 1 1.5 7M3 4v6h6m3-3v5l3 2"/>',
 'toolbox':'<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18m-14-1v3m10-3v3"/>',
 'image':'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 6"/>',
 'truck':'<path d="M2 5h12v12H9m-5 0H2V5Zm12 4h4l4 5v3h-2m-6 0h2"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="18" cy="17.5" r="2.5"/>',
 'check-circle':'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
 'x-circle':'<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6m0-6-6 6"/>',
 'alert':'<path d="m10.4 4.5-8 14A1.6 1.6 0 0 0 4 21h16a1.6 1.6 0 0 0 1.6-2.5l-8-14a1.8 1.8 0 0 0-3.2 0Z"/><path d="M12 9v4m0 3.5v.5"/>',
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
    return mark_safe('<svg class="ui-icon" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+path+'</svg>')


@register.simple_tag
def order_status_icon(status):
    return icon({'pending':'clock', 'confirmed':'activity', 'approved':'activity', 'processing':'activity',
                 'completed':'check-circle', 'cancelled':'x-circle', 'rejected':'x-circle'}.get(status,'receipt'))
