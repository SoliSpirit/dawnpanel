"""Supplier observations are proposals, never blind overwrites of merchant prices."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Audit, Product, SourceProduct, SourceSyncSettings
from .services import BusinessError
from .supplier_clients import fetch_catalogue
from .source_links import product_page


def price_signature(product):
    return {name: str(getattr(product, name)) for name in (
        'price', 'price_amount', 'price_currency', 'price_per', 'product_profit_percent')}


@transaction.atomic
def apply_proposal(pk, actor=None, *, automatic=False, expected_observed_at=None):
    link = SourceProduct.objects.select_for_update().get(pk=pk)
    if expected_observed_at is not None and link.observed_at != expected_observed_at:
        raise BusinessError('قیمت پیشنهادی تغییر کرده؛ دوباره بررسی کنید.')
    if link.review_status != 'pending' or not link.proposed_price or not link.available:
        raise BusinessError('قیمت تأییدنشدهٔ معتبری برای اعمال وجود ندارد.')
    if not link.observed_at or link.observed_at < timezone.now() - timedelta(hours=24):
        raise BusinessError('قیمت پیشنهادی قدیمی است؛ دوباره دریافت کنید.')
    product = Product.objects.select_for_update().get(pk=link.product_id)
    signature = price_signature(product)
    if (signature != {key:link.price_baseline.get(key) for key in signature}
            or product.price_currency != 'TOMAN' or product.price_amount is not None
            or str(product.price_per) != link.price_baseline.get('source_price_per')):
        link.review_status = 'conflict'
        link.save(update_fields=['review_status'])
        return False
    if automatic:
        config = SourceSyncSettings.objects.select_for_update().get(source=link.source)
        if not config.enabled or config.require_approval or not link.sync_enabled:
            return False
        delta = abs(Decimal(link.proposed_price) - product.price) * 100 / max(product.price, 1)
        if delta > config.max_change_percent:
            return False
    before = product.price
    product.price = link.proposed_price
    product.save(update_fields=['price'])
    link.review_status = 'applied'
    link.proposed_price = None
    link.save(update_fields=['review_status','proposed_price'])
    Audit.objects.create(actor=actor, action='source.price.apply', object_ref=str(product.pk),
                         details={'source':link.source,'old':before,'new':product.price,'automatic':automatic})
    return True


def sync_source(source, *, due_only=False, actor=None, link_ids=None, deadline=None):
    """A targeted recheck observes exactly these mappings, including paused ones.

    It never moves the full-catalog schedule or applies a merchant price.
    """
    targeted = link_ids is not None
    if targeted:
        link_ids = sorted(set(link_ids))
        if not link_ids or due_only:
            raise BusinessError('ردیفی برای بررسی دستی انتخاب نشده است.')
    SourceSyncSettings.objects.get_or_create(source=source)
    now = timezone.now()
    # A persisted lease serializes CLI, scheduler and admin fetches across workers.
    with transaction.atomic():
        config = SourceSyncSettings.objects.select_for_update().get(source=source)
        if config.running_until and config.running_until > now:
            raise BusinessError('دریافت این منبع هم‌اکنون در حال اجراست.')
        if due_only and (not config.enabled or (
                config.last_attempt and now < config.last_attempt + timedelta(minutes=config.interval_minutes))):
            return {'skipped':True}
        lease = now + timedelta(minutes=30)
        config.running_until = lease
        if not targeted:
            config.last_attempt = now
        config.save(update_fields=['running_until'] if targeted else ['running_until','last_attempt'])
    try:
        rows = fetch_catalogue(source, deadline=deadline)
        indexed = {str(row['external_id']): row for row in rows}
        pending = applied = 0
        present = missing = sold_out = 0
        observed = timezone.now()
        with transaction.atomic():
            scope = SourceProduct.objects.filter(source=source)
            scope = scope.filter(pk__in=link_ids) if targeted else scope.filter(sync_enabled=True)
            links = list(scope.select_for_update().order_by('pk'))
            if not SourceSyncSettings.objects.select_for_update().filter(source=source,running_until=lease).exists():
                raise BusinessError('مهلت بررسی پایان یافته است؛ دوباره تلاش کنید.')
            products = Product.objects.in_bulk([link.product_id for link in links])
            for link in links:
                row = indexed.get(link.external_id)
                product = products.get(link.product_id)
                link.proposed_price = None
                link.observed_at = link.updated_at = observed
                link.available = bool(row and row['available'])
                if row:
                    # Even an out-of-stock plan can have a freshly quoted price.
                    link.last_price = row['price']
                    link.item_url = product_page(source,row.get('item_url') or row.get('url'),link.external_id)
                    present += int(link.available)
                if not row:
                    link.review_status = 'missing'
                    missing += 1
                elif not row['available']:
                    link.review_status = 'unavailable'
                    sold_out += 1
                elif not product:
                    link.review_status = 'conflict'
                else:
                    baseline = price_signature(product)
                    baseline['source_price_per'] = str(row['price_per'])
                    # Preserve a rejected observation until source price changes.
                    rejected = link.review_status == 'rejected' and link.price_baseline.get('rejected_price') == row['price']
                    link.price_baseline = baseline
                    if rejected:
                        link.price_baseline['rejected_price'] = row['price']
                        link.review_status = 'rejected'
                    elif (product.price_currency != 'TOMAN' or product.price_amount is not None
                          or product.price_per != row['price_per']):
                        link.review_status = 'conflict'
                    elif product.price == row['price']:
                        link.review_status = 'unchanged'
                    else:
                        link.proposed_price = row['price']
                        link.review_status = 'pending'
                        pending += 1
            SourceProduct.objects.bulk_update(links, ['proposed_price','observed_at','updated_at','available',
                'last_price','item_url','review_status','price_baseline'],batch_size=100)
        # No network I/O inside row locks or financial transactions.
        if not targeted and config.enabled and not config.require_approval:
            for p in links:
                if p.review_status == 'pending':
                    applied += bool(apply_proposal(p.pk,actor,automatic=True,expected_observed_at=observed))
        result={'received':len(rows),'checked':len(links),'available':present,'unavailable':sold_out,
                'missing':missing,'pending':pending,'applied':applied}
        with transaction.atomic():
            SourceSyncSettings.objects.filter(source=source,running_until=lease).update(running_until=None,
                **({} if targeted else {'last_success':timezone.now(),'last_error':''}))
            Audit.objects.create(actor=actor,action='source.price.recheck' if targeted else 'source.price.fetch',
                object_ref=source,details={**result,**({'links':link_ids} if targeted else {})})
        return result
    except Exception:
        SourceSyncSettings.objects.filter(source=source,running_until=lease).update(running_until=None,
            **({} if targeted else {'last_error':'دریافت یا ثبت قیمت‌ها ناموفق بود؛ دوباره بررسی کنید.'}))
        raise


@transaction.atomic
def reject_proposal(pk, actor=None, *, expected_observed_at=None):
    link = SourceProduct.objects.select_for_update().get(pk=pk)
    if expected_observed_at is not None and link.observed_at != expected_observed_at:
        raise BusinessError('پیشنهاد تغییر کرده است؛ دوباره بررسی کنید.')
    if link.review_status != 'pending':
        raise BusinessError('پیشنهاد در انتظار تأیید نیست.')
    link.price_baseline['rejected_price'] = link.proposed_price
    link.review_status = 'rejected'
    link.proposed_price = None
    link.save(update_fields=['price_baseline','review_status','proposed_price'])
    Audit.objects.create(actor=actor,action='source.price.reject',object_ref=str(link.product_id))
