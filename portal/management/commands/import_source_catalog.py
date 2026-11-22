import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from portal.models import Audit, Category, Product, ProductVisual, SourceProduct
from portal.source_catalog import catalogue_rows


class Command(BaseCommand):
    help = 'Validate a supplier snapshot and optionally create unpublished product drafts.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=Path, nargs='?')
        parser.add_argument('--source', choices=['denapanel','premstore'])
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--publish', action='store_true',
                            help='Explicitly publish newly imported available items on website only.')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            if bool(options['source']) == bool(options['file']):
                raise ValueError('Supply either a snapshot file or --source.')
            if options['source']:
                from portal.supplier_clients import fetch_catalogue
                rows = fetch_catalogue(options['source'])
            else:
                with options['file'].open(encoding='utf-8') as source:
                    rows = catalogue_rows(json.load(source))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CommandError('Invalid supplier snapshot: ' + str(error)) from error
        if not rows:
            raise CommandError('The supplier snapshot is empty.')
        self.stdout.write(f'Validated {len(rows)} supplier items.')
        if options['publish'] and not options['apply']:
            raise CommandError('--publish requires --apply.')
        if not options['apply']:
            self.stdout.write('Preview only; nothing was changed.')
            return
        created = skipped = 0
        for row in rows:
            if SourceProduct.objects.filter(source=row['source'], external_id=row['external_id']).exists():
                skipped += 1
                continue
            category=Category.objects.filter(name=row['category']).order_by('pk').first()
            if category is None:
                category=Category.objects.create(name=row['category'])
            product = Product.objects.create(
                category=category, name=row['name'][:500], price=row['price'],
                price_per=row['price_per'], min_order=row['min_order'],
                max_order=row['max_order'], need_link=True,
                platform=row['platform'],
                description=row['description'],
                target_type='channel_group' if row['source'] == 'denapanel' else 'custom',
                target_prompt='اطلاعات لازم برای تحویل را مطابق توضیحات محصول وارد کنید؛ رمز و کد ورود ارسال نکنید.',
                is_active=False, show_on_website=False, show_on_telegram=False,
            )
            SourceProduct.objects.create(
                source=row['source'], external_id=row['external_id'],
                product_id=product.pk, source_url=row['url'], last_price=row['price'],
                available=row['available'],
                family_name=row.get('family_name',''),family_summary=row.get('family_summary',''),
            )
            if row.get('plan_name'):
                ProductVisual.objects.create(product_id=product.pk,image='',plan_name=row['plan_name'])
            if options['publish'] and row['available'] and row['platform'] != 'telegram':
                product.is_active=True
                product.show_on_website=True
                product.full_clean()
                product.save(update_fields=['is_active','show_on_website'])
            created += 1
        mode='website products (unavailable items kept hidden)' if options['publish'] else 'unpublished drafts'
        Audit.objects.create(action='source.catalog.import',object_ref=options['source'] or 'snapshot',
            details={'created':created,'skipped':skipped,'publish':options['publish']})
        self.stdout.write(f'Created {created} {mode}; skipped {skipped} previously imported items.')
