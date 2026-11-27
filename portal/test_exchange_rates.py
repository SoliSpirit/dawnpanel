from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from .exchange_rates import Market, Rates, RateError, fetch_source, market_for, resolve, source_link, spread, supported


def book(at,bid='2800000',ask='2800000'):
    return {'lastUpdate':int(at.timestamp()*1000),'asks':[[ask,'12.34']],'bids':[[bid,'2.3']]}


def stars_html(price='4,560,000 تومان'):
    return ('<h5>🌟 استارز تلگرام 🌟</h5><tr data-service-id="1161" data-service-name="🌟 استارز تلگرام 🌟"'
            ' data-category="179" data-status="1"><td data-title="شناسه">1161</td>'
            '<td data-title="نام"><a href="/service/1161/🌟-استارز-تلگرام-🌟">🌟 استارز تلگرام 🌟</a></td>'
            f'<td data-title="قیمت هر 1000 عدد">{price}</td><td data-title="حداقل/حداکثر">1,000,000/50</td></tr>')


def dena_page(html,page=1,total=1):
    return {'success':True,'data':{'html':html,'pagination':{'current_page':page,'total_pages':total}}}


class QuoteTests(SimpleTestCase):
    def test_stars_public_catalogue_uses_direct_service_and_exact_pack_units(self):
        star=stars_html('۴٬۵۶۰٬۱۲۵ تومان')
        other=''.join(stars_html('100 تومان').replace('1161',key) for key in ('1156','1239','1240'))
        at=timezone.now()
        with patch('portal.supplier_clients.read_json',side_effect=[dena_page(other,1,2),dena_page(star,2,2)]) as read, \
                patch('portal.exchange_rates.timezone.now',return_value=at):
            data=fetch_source('denapanel')
        self.assertEqual(len(data['services']),1)
        self.assertEqual(data['services'][0]['item_url'],source_link('denapanel','STAR'))
        for page,call in enumerate(read.call_args_list,1):
            self.assertEqual(call.kwargs['data'],{'action':'kando_get_categories','page':page})
            self.assertIsNotNone(call.kwargs['deadline'])
        market=market_for('denapanel','STAR',data,at+timedelta(minutes=2))
        self.assertEqual(market,Market(Decimal('4560.125'),Decimal('4560.125'),at))
        self.assertEqual(spread(market.bid,market.ask,'percent',0,10),Rates(4104,4561))
        with self.assertRaises(RateError):market_for('denapanel','STAR',data,at+timedelta(minutes=11))
        with self.assertRaises(RateError):market_for('denapanel','USDT',data,at)
        self.assertTrue(supported('STAR','telegram','denapanel'))
        for code,kind in [('STAR','crypto'),('XTR','telegram'),('USD','fiat')]:
            self.assertFalse(supported(code,kind,'denapanel'))

    def test_stars_rejects_lookalikes_conflicting_rows_and_unverified_prices(self):
        html=stars_html()
        bad_pages=[
            [dena_page(html.replace('1161','1240'))],
            [dena_page(html,1,2),dena_page(html,2,2)],
            [dena_page(html.replace('استارز تلگرام','ری اکشن استارز'))],
            [dena_page(html.replace('href="/service/1161','href="/service/1156'))],
            [dena_page(html.replace('data-status="1"','data-status="0"'))],
            [dena_page(html.replace('قیمت هر 1000 عدد','قیمت هر 100 عدد'))],
            [dena_page(html.replace('تومان','ریال'))],
            [dena_page(html.replace('4,560,000','45,60,000'))],
            [dena_page(html.replace('</tr>','<td data-title="قیمت هر 1000 عدد">777 تومان</td></tr>'))],
        ]
        for pages in bad_pages:
            with self.subTest(pages=pages),patch('portal.supplier_clients.read_json',side_effect=pages),self.assertRaises(RateError):
                market_for('denapanel','STAR',fetch_source('denapanel'),timezone.now())

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
                               sell_extra=0,buy_less=0,candidate_key='nobitex:USDT',candidate_at=timezone.now(),published_at=timezone.now())
        with self.assertRaises(RateError):resolve('USDT','crypto',85000,policy)
        policy.quote_key='nobitex:USDT';policy.candidate_at-=timedelta(hours=1)
        with self.assertRaises(RateError):resolve('USDT','crypto',85000,policy)
        policy.candidate_at=timezone.now();policy.published_at-=timedelta(days=2)
        with self.assertRaises(RateError):resolve('USDT','crypto',85000,policy)
        with self.assertRaises(RateError):spread(100,100,'fixed',0,100)
        with self.assertRaises(RateError):spread(100,100,'percent',0,100)
        self.assertEqual(resolve('USD','fiat',85,None),Rates(85,85))
