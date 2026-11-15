from django.core.management.base import BaseCommand
from django.db import transaction
from portal.models import Audit, SourceProduct
from portal.supplier_clients import fetch_catalogue


class Command(BaseCommand):
    help = 'Refresh product family text only. Never changes prices or availability.'

    def handle(self, *args, **options):
        rows = {row['external_id']: row for row in fetch_catalogue('premstore')}
        updated = []
        with transaction.atomic():
            for link in SourceProduct.objects.select_for_update().filter(source='premstore'):
                row = rows.get(link.external_id)
                if row and row['url'] == link.source_url:
                    link.family_name = row['family_name']
                    link.family_summary = row['family_summary']
                    updated.append(link)
            SourceProduct.objects.bulk_update(updated, ['family_name','family_summary'])
            Audit.objects.create(action='source.catalog.metadata', details={'updated':len(updated)})
        self.stdout.write(f'Updated {len(updated)} family descriptions; prices untouched.')
