from django.core.management.base import BaseCommand, CommandError
from portal.exchange_rates import refresh_rates


class Command(BaseCommand):
    help = 'Refresh configured FX quotes (no trades).'

    def add_arguments(self, parser):
        parser.add_argument('--bootstrap',action='store_true',
            help='Opt in existing USD, USDT, BTC and ETH with verified first quotes, keeping existing policies.')

    def handle(self,*args,**options):
        results=refresh_rates(bootstrap=options['bootstrap'])
        for code,error in results.items():
            self.stdout.write(f'{code}: {error or "OK"}')
        if any(results.values()):
            raise CommandError('Some markets were unavailable; no manual fallback was used.')
