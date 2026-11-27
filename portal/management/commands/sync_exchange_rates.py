from django.core.management.base import BaseCommand, CommandError
from portal.exchange_rates import refresh_rates
from portal.models import Currency


class Command(BaseCommand):
    help = 'Refresh configured FX quotes (no trades).'

    def add_arguments(self, parser):
        parser.add_argument('--bootstrap',action='store_true',
            help='Opt in existing USD, USDT, BTC, ETH and Telegram STAR with verified first quotes, keeping existing policies.')
        parser.add_argument('--code',help='Refresh only this currency code (e.g. STAR).')

    def handle(self,*args,**options):
        ids=None
        if options['code']:
            ids=list(Currency.objects.filter(code=options['code'].strip().upper()).values_list('pk',flat=True))
            if not ids:
                raise CommandError('Unknown currency code.')
        results=refresh_rates(ids,bootstrap=options['bootstrap'])
        for code,error in results.items():
            self.stdout.write(f'{code}: {error or "OK"}')
        if any(results.values()):
            raise CommandError('Some markets were unavailable; no manual fallback was used.')
