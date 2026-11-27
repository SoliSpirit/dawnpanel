from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from .exchange_rates import Market, Rates, RateError, market_for, resolve, spread, supported


def book(at,bid='2800000',ask='2800000'):
    return {'lastUpdate':int(at.timestamp()*1000),'asks':[[ask,'12.34']],'bids':[[bid,'2.3']]}


class QuoteTests(SimpleTestCase):
    def test_nobitex_rial_book_uses_opposite_market_sides_and_outward_rounding(self):
        now=timezone.now()
        row=book(now,'2799999.1','2800030.8')
        row['bids'].insert(0,['2785000','1'])
        row['asks'].insert(0,['2850000','1'])
        market=market_for('nobitex','USDT',{'USDTIRT':row},now)
        self.assertEqual((market.bid,market.ask),(Decimal('279999.91'),Decimal('280003.08')))
        self.assertEqual(spread(market.bid,market.ask,'fixed',5000,10000),Rates(269999,285004))
        self.assertEqual(spread(280000,280000,'fixed',5000,10000),Rates(270000,285000))
        self.assertEqual(spread(Decimal('100.5'),Decimal('101.5'),'percent',2,3),Rates(97,104))

    def test_stale_crossed_missing_and_nonfinite_markets_do_not_quote(self):
        now=timezone.now()
        data={'USDTIRT':book(now)}
        for row in (book(now-timedelta(minutes=11)),book(now+timedelta(minutes=2)),book(now,'2810000','2800000'),
                    book(now,'NaN'),book(now,'0'),{**book(now),'asks':[]}):
            with self.assertRaises(RateError):market_for('nobitex','USDT',{'USDTIRT':row},now)
        with self.assertRaises(RateError):market_for('nobitex','USD',data,now)
        self.assertFalse(supported('USD','crypto','nobitex'))
        self.assertFalse(supported('STAR','telegram','nobitex'))

    def test_cash_usd_is_a_toman_reference_with_its_own_timestamp(self):
        now=timezone.now()
        row={'id':'usd','family':'currency','unit':'IRT','sources':2,'price':280000,
             'stale':False,'updated_utc':now.isoformat()}
        self.assertEqual(market_for('nerkhara','USD',{'usd':row},now),Market(Decimal('280000'),Decimal('280000'),now))
        for changed in ({'unit':'IRR'},{'stale':True},{'id':'usdt'},{'sources':0},
                        {'updated_utc':(now-timedelta(hours=1)).isoformat()}):
            with self.assertRaises(RateError):market_for('nerkhara','USD',{'usd':{**row,**changed}},now)

    def test_no_manual_fallback_for_unpriced_or_renamed_auto_market(self):
        policy=SimpleNamespace(source='nobitex',observed_at=timezone.now(),quote_key='nobitex:ETH',
                               market_bid=Decimal('280000'),market_ask=Decimal('280000'),spread_mode='fixed',
                               sell_extra=0,buy_less=0)
        with self.assertRaises(RateError):resolve('USDT','crypto',85000,policy)
        policy.quote_key='nobitex:USDT';policy.observed_at-=timedelta(hours=1)
        with self.assertRaises(RateError):resolve('USDT','crypto',85000,policy)
        with self.assertRaises(RateError):spread(100,100,'fixed',0,100)
        with self.assertRaises(RateError):spread(100,100,'percent',0,100)
        self.assertEqual(resolve('USD','fiat',85,None),Rates(85,85))
