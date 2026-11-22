"""Reviewed web-only equivalents; never infer identity from a price or a brand."""
from django.db.models import Q

from .models import SourceProduct
from .service_art import SERVICE_TITLES


# Original native SKU -> stable supplier variation. The native titles are the
# seeded tier/duration/delivery triples also used to select the bot artwork.
PREMSTORE_EQUIVALENTS = {
    32:'277', 33:'510', 34:'508', 35:'278', 36:'279', 37:'280', 38:'509',
    39:'549', 40:'550', 41:'271', 42:'551', 43:'552', 44:'272',
    45:'553', 46:'273', 47:'276', 48:'554', 49:'555',
}


def unavailable_mirrors():
    """A known mirror is not a way around its monitored source's stock hold."""
    held = SourceProduct.objects.filter(source='premstore', external_id__in=PREMSTORE_EQUIVALENTS.values(),
                                        sync_enabled=True, available=False).values_list('external_id', flat=True)
    held = set(held)
    result = Q(pk__in=[])
    for pk, external_id in PREMSTORE_EQUIVALENTS.items():
        if external_id in held:
            result |= Q(pk=pk, platform='ai', name=SERVICE_TITLES['ai'][pk], min_order=1, price_per=1,
                        max_order=1) & ~Q(pk__in=SourceProduct.objects.values('product_id'))
    return result


def web_aliases(products, links):
    """Return alias PK -> preferred eligible Product, using only the given rows."""
    by_id = {p.pk:p for p in products}
    imported = {link.external_id:by_id[pk] for pk,link in links.items()
                if pk in by_id and link.source == 'premstore'}
    aliases = {}
    for pk, external_id in PREMSTORE_EQUIVALENTS.items():
        native, preferred = by_id.get(pk), imported.get(external_id)
        if (native and preferred and pk not in links and native.platform == preferred.platform == 'ai'
                and native.name == SERVICE_TITLES['ai'][pk]
                and all(p.price_per == p.min_order == p.max_order == 1 for p in (native, preferred))):
            aliases[pk] = preferred
    # Both titles contain the same heart-eyes emoji and have the same legacy
    # terms. Other heart or face reactions are separate services.
    preferred, other = by_id.get(30), by_id.get(31)
    if (preferred and other and 30 not in links and 31 not in links and
            all(p.platform == 'rubika' and p.name == SERVICE_TITLES['rubika'][30] and
                (p.description or '').startswith(f'شناسه خدمت در سایت قبلی: #{source_id}؛')
                for p,source_id in ((preferred,6),(other,8))) and
            all(getattr(preferred, k) == getattr(other, k) for k in
                ('category_id','min_order','max_order','price_per','need_link','target_type'))):
        aliases[other.pk] = preferred
    return aliases
