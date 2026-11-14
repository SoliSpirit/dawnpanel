import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from portal.models import Category, Product, SourceProduct
from portal.source_catalog import catalogue_rows


class Command(BaseCommand):
    help = 'Validate a supplier snapshot and optionally create unpublished product drafts.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=Path)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            with options['file'].open(encoding='utf-8') as source:
                rows = catalogue_rows(json.load(source))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CommandError('Invalid supplier snapshot: ' + str(error)) from error
        if not rows:
            raise CommandError('The supplier snapshot is empty.')
        self.stdout.write(f'Validated {len(rows)} supplier items.')
        if not options['apply']:
            self.stdout.write('Preview only; nothing was changed.')
            return
        created = skipped = 0
        for row in rows:
            if SourceProduct.objects.filter(source=row['source'], external_id=row['external_id']).exists():
                skipped += 1
                continue
            category, _ = Category.objects.get_or_create(name=row['category'])
            product = Product.objects.create(
                category=category, name=row['name'][:500], price=row['price'],
                price_per=row['price_per'], min_order=row['min_order'],
                max_order=row['max_order'], need_link=True,
                platform='telegram' if row['source'] == 'denapanel' else 'other',
                is_active=False, show_on_website=False, show_on_telegram=False,
            )
            SourceProduct.objects.create(
                source=row['source'], external_id=row['external_id'],
                product_id=product.pk, source_url=row['url'], last_price=row['price'],
            )
            created += 1
        self.stdout.write(f'Created {created} unpublished drafts; skipped {skipped} previously imported items.')
