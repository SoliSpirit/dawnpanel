from django.core.management.base import BaseCommand, CommandError
from portal.price_sync import sync_source


class Command(BaseCommand):
    help = 'Fetch supplier price proposals. --due respects each source schedule.'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['denapanel','premstore'])
        parser.add_argument('--due', action='store_true')

    def handle(self, *args, **options):
        failed = False
        for source in ([options['source']] if options['source'] else ['denapanel','premstore']):
            try:
                self.stdout.write(f'{source}: {sync_source(source,due_only=options["due"])}')
            except Exception:
                failed = True
                self.stderr.write(f'{source}: sync failed; inspect source settings and server logs.')
        if failed:
            raise CommandError('One or more supplier checks failed; current product prices were not blindly overwritten.')
