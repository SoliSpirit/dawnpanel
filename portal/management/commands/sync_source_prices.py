from django.core.management.base import BaseCommand, CommandError
from datetime import timedelta
from django.utils import timezone
from portal.models import PriceReviewBatch,OrderDelivery,ChatEmailDelivery
from portal.price_sync import sync_source,finish_batch


class Command(BaseCommand):
    help = 'Fetch supplier price proposals. --due respects each source schedule.'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['denapanel','premstore'])
        parser.add_argument('--due', action='store_true')

    def handle(self, *args, **options):
        failed = False
        batch=PriceReviewBatch.objects.create(kind='scheduled' if options['due'] else 'manual')
        for source in ([options['source']] if options['source'] else ['denapanel','premstore']):
            try:
                self.stdout.write(f'{source}: {sync_source(source,due_only=options["due"],batch=batch)}')
            except Exception:
                failed = True
                self.stderr.write(f'{source}: sync failed; inspect source settings and server logs.')
        finish_batch(batch)
        old=list(PriceReviewBatch.objects.filter(created_at__lt=timezone.now()-timedelta(days=30)).order_by('pk').values_list('pk',flat=True)[:10])
        if old:
            refs=[str(i) for i in old];keep=set()
            for table in (OrderDelivery,ChatEmailDelivery):
                keep.update(table.objects.filter(operation__topic='price_review',operation__reference__in=refs,
                    state__in=('pending','sending')).values_list('operation__reference',flat=True))
            PriceReviewBatch.objects.filter(pk__in=[i for i in old if str(i) not in keep]).delete()
        if failed:
            raise CommandError('One or more supplier checks failed; current product prices were not blindly overwritten.')
