"""Supplier observations are proposals, never blind overwrites of merchant prices."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Audit, Product, ProductSaleOverride, SourceProduct, SourceSyncSettings, PriceReviewBatch, PriceReviewItem, OperationNotice,OrderDelivery
from .pricing import MAX_TOTAL
from .notice_topics import subscribers
from .services import BusinessError
from .supplier_clients import fetch_catalogue
from .source_links import product_page


def price_signature(product):
    return {name: str(getattr(product, name)) for name in (
        'price', 'price_amount', 'price_currency', 'price_per', 'product_profit_percent')} | {'fixed_sale':product.fixed_sale}


def matches_baseline(product,link,signature):
    return (product.price_currency=='TOMAN' and product.price_amount is None and
            product.price_per==(link.pack_override or link.feed_units) and
            str(product.price_per)==link.price_baseline.get('source_price_per') and
            all(link.price_baseline.get(k)==v for k,v in signature.items()))


@transaction.atomic
def apply_proposal(pk, actor=None, *, automatic=False, expected_observed_at=None, markup=None, fixed_sale=None, review=False, telegram_admin_id=None):
    if automatic:return False
    link = SourceProduct.objects.select_for_update().get(pk=pk)
    if expected_observed_at is not None and link.observed_at != expected_observed_at:
        raise BusinessError('قیمت پیشنهادی تغییر کرده؛ دوباره بررسی کنید.')
    if not link.available or not (link.review_status=='pending' and link.proposed_price or
            review and (markup is not None or fixed_sale is not None) and link.review_status=='unchanged' and link.last_price):
        raise BusinessError('قیمت تأییدنشدهٔ معتبری برای اعمال وجود ندارد.')
    if not link.observed_at or link.observed_at < timezone.now() - timedelta(hours=24):
        raise BusinessError('قیمت پیشنهادی قدیمی است؛ دوباره دریافت کنید.')
    product = Product.objects.select_for_update().get(pk=link.product_id)
    signature = price_signature(product)
    if not matches_baseline(product,link,signature):
        link.review_status = 'conflict'
        link.save(update_fields=['review_status'])
        return False
    before,old_markup = product.price,product.product_profit_percent
    product.price = link.proposed_price or link.last_price
    if fixed_sale is not None:
        if not review or markup is not None or type(fixed_sale) is not int or not 0<fixed_sale<=MAX_TOTAL:
            raise BusinessError('مبلغ فروش معتبر نیست.')
        ProductSaleOverride.objects.update_or_create(product_id=product.pk,defaults={'amount':fixed_sale,'units':product.price_per})
    if markup is not None:
        if not isinstance(markup,Decimal) or not markup.is_finite() or not 0<=markup<1000000 or markup.as_tuple().exponent < -4:
            raise BusinessError('درصد سود معتبر نیست.')
        product.product_profit_percent=markup
        ProductSaleOverride.objects.filter(product_id=product.pk).delete()
    product.save(update_fields=['price','product_profit_percent'])
    link.review_status = 'applied'
    link.proposed_price = None
    link.save(update_fields=['review_status','proposed_price'])
    Audit.objects.create(actor=actor, action='source.price.apply', object_ref=str(product.pk),
                         details={'source':link.source,'old':before,'new':product.price,'old_markup':str(old_markup),
                                  'markup':str(product.product_profit_percent),'fixed_before':signature['fixed_sale'],
                                  'fixed_after':fixed_sale if fixed_sale is not None else (None if markup is not None else signature['fixed_sale']),
                                  'batch_item':review,'telegram_admin_id':telegram_admin_id})
    return True


@transaction.atomic
def finish_batch(batch):
    batch=PriceReviewBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.ready:return
    n=batch.items.count()
    if not n:
        batch.delete()
        return
    batch.ready=True;batch.save(update_fields=['ready'])
    pending=batch.items.filter(status='pending').count()
    op=OperationNotice.objects.create(topic='price_review',origin='system',summary=f'گزارش بررسی {n} محصول؛ {pending} پیشنهاد قیمت منتظر تأیید.',
                                   reference=str(batch.pk),prepared=True)
    OrderDelivery.objects.bulk_create([OrderDelivery(operation=op,recipient=key,due_at=timezone.now()) for key in subscribers('price_review')])


def sync_source(source, *, due_only=False, actor=None, link_ids=None, deadline=None, batch=None,
                recheck_item=None, telegram_admin_id=None):
    """A targeted recheck observes exactly these mappings, including paused ones.

    It never moves the full-catalog schedule or applies a merchant price.
    """
    targeted = link_ids is not None
    if targeted:
        link_ids = sorted(set(link_ids))
        if not link_ids or due_only:
            raise BusinessError('ردیفی برای بررسی دستی انتخاب نشده است.')
    # A Telegram recheck refers to the observation on the button, never whichever
    # product/price happens to be pending when a delayed callback arrives.
    if recheck_item is not None or telegram_admin_id is not None:
        if (recheck_item is None or telegram_admin_id not in subscribers('price_review') or
                source!=recheck_item.source or link_ids!=[recheck_item.link_id] or batch is not None or actor is not None):
            raise BusinessError('درخواست بررسی مجدد معتبر نیست.')
    def same_observation():
        return SourceProduct.objects.filter(pk=recheck_item.link_id,source=source,product_id=recheck_item.product_id,
                                            observed_at=recheck_item.observed_at).exists()
    SourceSyncSettings.objects.get_or_create(source=source)
    now = timezone.now()
    # A persisted lease serializes CLI, scheduler and admin fetches across workers.
    with transaction.atomic():
        config = SourceSyncSettings.objects.select_for_update().get(source=source)
        if recheck_item is not None and not same_observation():
            raise BusinessError('برای این محصول بررسی تازه‌تری ثبت شده است.')
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
        pending = 0
        present = missing = sold_out = 0
        observed = timezone.now()
        with transaction.atomic():
            scope = SourceProduct.objects.filter(source=source)
            scope = scope.filter(pk__in=link_ids) if targeted else scope.filter(sync_enabled=True)
            links = list(scope.select_for_update().order_by('pk'))
            if not SourceSyncSettings.objects.select_for_update().filter(source=source,running_until=lease).exists():
                raise BusinessError('مهلت بررسی پایان یافته است؛ دوباره تلاش کنید.')
            if recheck_item is not None and (telegram_admin_id not in subscribers('price_review') or not same_observation()):
                raise BusinessError('وضعیت محصول یا دسترسی بررسی تغییر کرده است.')
            products = Product.objects.select_related('sale_override').in_bulk([link.product_id for link in links])
            report=batch or PriceReviewBatch.objects.create(kind='recheck' if recheck_item is not None else ('scheduled' if due_only else 'manual'))
            items=[]
            for link in links:
                row = indexed.get(link.external_id)
                product = products.get(link.product_id)
                previous=link.last_price or None
                previous_units=link.observed_units if previous is not None else None
                feed_units=row['price_per'] if row else None
                units=(link.pack_override or feed_units) if row else None
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
                    # Preserve a rejected observation until source price changes.
                    rejected = (link.review_status == 'rejected' and previous_units==units and
                                link.price_baseline.get('rejected_price') == row['price'])
                    link.price_baseline = baseline
                    if rejected:
                        link.price_baseline['rejected_price'] = row['price']
                        link.review_status = 'rejected'
                    elif (product.price_currency != 'TOMAN' or product.price_amount is not None
                          or product.price_per != units):
                        link.review_status = 'conflict'
                    elif product.price == row['price']:
                        link.review_status = 'unchanged'
                    else:
                        link.proposed_price = row['price']
                        link.review_status = 'pending'
                        pending += 1
                if row:
                    link.price_baseline.update(feed_price_per=str(feed_units),source_price_per=str(units))
                status=link.review_status
                items.append(PriceReviewItem(batch=report,link=link,product_id=link.product_id,source=source,
                    label=product.name if product else f'محصول #{link.product_id}',observed_at=observed,
                    units=units,feed_units=feed_units,previous_units=previous_units,sale_units=product.price_per if product else None,
                    previous=previous,observed=row['price'] if row else None,
                    base=product.price if product and product.price_currency=='TOMAN' and product.price_amount is None else None,
                    markup=product.product_profit_percent if product else None,fixed_before=product.fixed_sale if product else None,status=status,
                    rank=0 if status=='pending' else (2 if status=='unchanged' else 1)))
            SourceProduct.objects.bulk_update(links, ['proposed_price','observed_at','updated_at','available',
                'last_price','item_url','review_status','price_baseline'],batch_size=100)
            PriceReviewItem.objects.bulk_create(items,batch_size=150)
            result={'received':len(rows),'checked':len(links),'available':present,'unavailable':sold_out,
                    'missing':missing,'pending':pending,'applied':0,'review_batch':report.pk}
            SourceSyncSettings.objects.filter(source=source,running_until=lease).update(running_until=None,
                **({} if targeted else {'last_success':timezone.now(),'last_error':''}))
            Audit.objects.create(actor=actor,action='source.price.recheck' if targeted else 'source.price.fetch',
                 object_ref=source,details={**result,**({'links':link_ids} if targeted else {}),
                    **({'review_item':recheck_item.pk,'telegram_admin_id':telegram_admin_id} if recheck_item is not None else {})})
            if batch is None:finish_batch(report)
        return result
    except Exception:
        SourceSyncSettings.objects.filter(source=source,running_until=lease).update(running_until=None,
            **({} if targeted else {'last_error':'دریافت یا ثبت قیمت‌ها ناموفق بود؛ دوباره بررسی کنید.'}))
        raise


@transaction.atomic
def reject_proposal(pk, actor=None, *, expected_observed_at=None,telegram_admin_id=None):
    link = SourceProduct.objects.select_for_update().get(pk=pk)
    if expected_observed_at is not None and link.observed_at != expected_observed_at:
        raise BusinessError('پیشنهاد تغییر کرده است؛ دوباره بررسی کنید.')
    if link.review_status != 'pending' or not link.proposed_price:
        raise BusinessError('پیشنهاد در انتظار تأیید نیست.')
    rejected=link.proposed_price
    link.price_baseline['rejected_price'] = rejected
    link.review_status = 'rejected'
    link.proposed_price = None
    link.save(update_fields=['price_baseline','review_status','proposed_price'])
    Audit.objects.create(actor=actor,action='source.price.reject',object_ref=str(link.product_id),
                         details={'source':link.source,'rejected_price':rejected,'telegram_admin_id':telegram_admin_id})
