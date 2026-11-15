"""Supplier observations are proposals, never blind overwrites of merchant prices."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Audit, Product, SourceProduct, SourceSyncSettings
from .services import BusinessError
from .supplier_clients import fetch_catalogue


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


def sync_source(source, *, due_only=False, actor=None):
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
        config.last_attempt = now
        config.save(update_fields=['running_until','last_attempt'])
    try:
        rows = fetch_catalogue(source)
        indexed = {str(row['external_id']): row for row in rows}
        pending = applied = 0
        with transaction.atomic():
            links = SourceProduct.objects.select_for_update().filter(source=source,sync_enabled=True).order_by('pk')
            for link in links:
                row = indexed.get(link.external_id)
                product = Product.objects.filter(pk=link.product_id).first()
                link.proposed_price = None
                link.observed_at = now
                link.available = bool(row and row['available'])
                if not row or not row['available']:
                    link.review_status = 'unavailable'
                elif not product:
                    link.review_status = 'conflict'
                else:
                    link.last_price = row['price']
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
                link.save()
        # No network I/O inside row locks or financial transactions.
        if config.enabled and not config.require_approval:
            for pk in SourceProduct.objects.filter(source=source,review_status='pending',observed_at=now).values_list('pk',flat=True):
                applied += bool(apply_proposal(pk,actor,automatic=True,expected_observed_at=now))
        SourceSyncSettings.objects.filter(source=source,running_until=lease).update(
            running_until=None,last_success=timezone.now(),last_error='')
        Audit.objects.create(actor=actor,action='source.price.fetch',object_ref=source,
                             details={'received':len(rows),'pending':pending,'applied':applied})
        return {'received':len(rows),'pending':pending,'applied':applied}
    except Exception:
        SourceSyncSettings.objects.filter(source=source,running_until=lease).update(
            running_until=None,last_error='دریافت یا ثبت قیمت‌ها ناموفق بود؛ دوباره بررسی کنید.')
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
