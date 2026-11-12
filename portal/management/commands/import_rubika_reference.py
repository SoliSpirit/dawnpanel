import csv
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from portal.models import Category, Product


class Command(BaseCommand):
    help = 'Preview or import Rubika reference rows as inactive website drafts.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=Path)
        parser.add_argument('--apply', action='store_true')

    @transaction.atomic
    def handle(self, *args, **opts):
        group = None
        rows = {}
        for row in csv.reader(opts['file'].read_text(encoding='utf-8-sig').splitlines(), delimiter='\t'):
            if len(row) == 1:
                group = row[0].strip()
                continue
            if not group or 'بله' in group or not any(word in group for word in ('روب','روبینو')):
                continue
            if len(row) < 5 or not row[0].strip().isascii() or not row[0].strip().isdigit():
                continue
            price = re.fullmatch(r'([0-9,]+)\s+تومان', row[3].strip())
            limits = re.fullmatch(r'([0-9,]+)/([0-9,]+)', row[4].strip())
            if not price or not limits:
                self.stderr.write(f'Skipped malformed reference row {row[0]}')
                continue
            maximum, minimum = (int(x.replace(',', '')) for x in limits.groups())
            amount = int(price[1].replace(',', ''))
            if not 0 < minimum <= maximum or not amount or not row[1].strip():
                raise CommandError(f'Invalid reference row {row[0]}')
            rows.setdefault(row[0].strip(), (group, row[1].strip(), amount, minimum, maximum))
        if not rows:
            raise CommandError('No valid Rubika rows found')
        self.stdout.write(f'Validated {len(rows)} Rubika reference rows')
        if not opts['apply']:
            return
        created = 0
        for group, name, amount, minimum, maximum in rows.values():
            if Product.objects.filter(platform='rubika',name=name).exists():
                continue
            category = Category.objects.filter(name=group).order_by('pk').first() or Category.objects.create(name=group)
            Product.objects.create(category=category,name=name,price=amount,price_per=1000,
                                   min_order=minimum,max_order=maximum,platform='rubika',
                                   is_active=False,show_on_website=True,show_on_telegram=False)
            created += 1
        self.stdout.write(f'Created {created} inactive drafts; existing products unchanged')
