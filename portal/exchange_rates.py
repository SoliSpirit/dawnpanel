"""Indicative per-unit quotes in toman, always from the merchant's perspective."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import json
import re
from time import monotonic
from urllib.parse import unquote, urlsplit

import requests
from django.db import transaction
from django.utils import timezone

from .models import Currency, CurrencyPricing
from .source_catalog import DENA_PRICE_PER
from .source_links import product_page
from .supplier_clients import DENA_CATALOGUE_URL, SupplierError, fetch_catalogue


DENA_STARS_ID = '1161'
DENA_STARS_PATH = f'/service/{DENA_STARS_ID}/🌟-استارز-تلگرام-🌟'
SOURCES = {
    'nobitex': ('نوبیتکس', 'https://apiv2.nobitex.ir/v3/orderbook/all', timedelta(minutes=10)),
    'nerkhara': ('نرخ‌آرا', 'https://nerkhara.com/api/v1/latest.json', timedelta(minutes=30)),
    'denapanel': ('دناپنل', DENA_CATALOGUE_URL, timedelta(minutes=10)),
}
# Only fiat feeds explicitly denominated per *one* currency unit.
FIAT = {'USD','EUR','GBP','AED','CAD','AUD','CHF','TRY'}
MAX_RATE = Decimal(10**16)
QUANTUM = Decimal('0.00000001')
UTC = dt_timezone.utc
APPROVAL_LIFETIME = timedelta(hours=24)


class RateError(ValueError):
    pass


@dataclass(frozen=True)
class Market:
    bid: Decimal  # best price at which the merchant could sell the asset
    ask: Decimal  # price to replace an asset the merchant sells
    at: datetime


@dataclass(frozen=True)
class Rates:
    buy: int     # merchant buys from the customer
    sell: int    # merchant sells to the customer


def valid_age(source, at, now):
    return (isinstance(at,datetime) and timezone.is_aware(at)
            and -timedelta(seconds=30) <= now-at <= SOURCES[source][2])


def supported(code, kind, source):
    if source == 'manual':
        return True
    if source == 'nerkhara':
        return kind == 'fiat' and code in FIAT
    if source == 'denapanel':
        return code == 'STAR' and kind == 'telegram'
    return (source == 'nobitex' and kind == 'crypto' and code not in FIAT | {'STAR','XTR','IRT','IRR','TOMAN'}
            and bool(re.fullmatch(r'[A-Z0-9]{2,15}',code)))


def spread(bid, ask, mode, sell_extra, buy_less):
    """Round outward only after applying the chosen adjustment."""
    sell_extra, buy_less = Decimal(sell_extra), Decimal(buy_less)
    if min(bid,ask)<=0 or ask<bid or max(ask,bid)>MAX_RATE or min(sell_extra,buy_less)<0:
        raise RateError('نرخ مرجع یا حاشیهٔ خرید و فروش معتبر نیست.')
    if mode == 'percent' and buy_less < 100:
        sell = ask*(100+sell_extra)/100
        buy = bid*(100-buy_less)/100
    elif mode == 'fixed':
        sell, buy = ask+sell_extra, bid-buy_less
    else:
        raise RateError('درصد کسر خرید باید کمتر از ۱۰۰ باشد.')
    buy = int(buy.to_integral_value(rounding=ROUND_FLOOR))
    sell = int(sell.to_integral_value(rounding=ROUND_CEILING))
    if not 1 <= buy <= sell <= MAX_RATE:
        raise RateError('با این حاشیه، نرخ خرید یا فروش خارج از محدوده است.')
    return Rates(buy,sell)


def resolve(code, kind, manual_rate, policy, *, now=None):
    source = policy.source if policy else 'manual'
    now = now or timezone.now()
    if source == 'manual':
        bid = ask = Decimal(manual_rate)
    else:
        key=f'{source}:{code}'
        if (not supported(code,kind,source) or policy.quote_key != key
                or policy.candidate_key!=key or not valid_age(source,policy.candidate_at,now)
                or not policy.published_at or not -timedelta(seconds=30)<=now-policy.published_at<=APPROVAL_LIFETIME
                or policy.market_bid is None or policy.market_ask is None):
            raise RateError('نرخ مصوب یا مرجع تازهٔ این ارز در دسترس نیست.')
        bid, ask = policy.market_bid, policy.market_ask
    rates=spread(bid,ask,policy.spread_mode,policy.sell_extra,policy.buy_less) if policy else spread(bid,ask,'fixed',0,0)
    if code=='STAR' and (not policy or policy.buy_less<=0 or rates.buy>=bid or rates.buy>=rates.sell):
        raise RateError('برای شارژ با استارز، کسریِ خرید مثبت را تأیید کن.')
    return rates


def currency_rates(currency, *, now=None):
    if not currency.is_active:
        raise RateError('این ارز غیرفعال است.')
    return resolve(currency.code,currency.type,currency.rate,getattr(currency,'fx',None),now=now)


def source_link(source, code):
    if source=='nobitex':
        return f'https://apiv2.nobitex.ir/v3/orderbook/{code}IRT'
    if source=='nerkhara':
        return 'https://nerkhara.com/dollar/' if code=='USD' else 'https://nerkhara.com/'
    if source=='denapanel' and code=='STAR':
        return 'https://denapanel.ir'+DENA_STARS_PATH
    return ''


def fetch_source(source):
    """Public, fixed HTTPS feeds. No credentials, redirects or network I/O at checkout."""
    end = monotonic()+15
    if source=='denapanel':
        try:
            rows=fetch_catalogue(source,dena_service_id=DENA_STARS_ID,deadline=end)
        except SupplierError as exc:
            raise RateError(str(exc)) from None
        # No supplier tick timestamp is provided: date this direct catalogue read,
        # never re-date it during review or reuse a monitoring/database timestamp.
        return {'services':rows,'observed_at':timezone.now()}
    try:
        with requests.get(SOURCES[source][1],headers={'Accept':'application/json','Cache-Control':'no-cache',
                'User-Agent':'DawnPanel-Rates/1.0'},timeout=(4,7),stream=True,allow_redirects=False) as res:
            if res.status_code != 200:
                raise RateError('مرجع نرخ پاسخ معتبر نداد.')
            body = bytearray()
            for chunk in res.iter_content(65536):
                if monotonic()>end or len(body)+len(chunk)>4_000_000:
                    raise RateError('پاسخ مرجع طولانی یا بیش از حد بزرگ است.')
                body.extend(chunk)
        data = json.loads(body, parse_float=Decimal)
    except (requests.RequestException,UnicodeError,json.JSONDecodeError):
        raise RateError('ارتباط با مرجع نرخ برقرار نشد.') from None
    if not isinstance(data,dict):
        raise RateError('ساختار پاسخ مرجع نرخ معتبر نیست.')
    if source=='nobitex' and data.get('status')=='ok':
        return data
    if source=='nerkhara' and data.get('api')=='nerkhara/v1' and isinstance(data.get('items'),list):
        rows=[i for i in data['items'] if isinstance(i,dict) and i.get('family')=='currency']
        index={i['id']:i for i in rows if isinstance(i.get('id'),str)}
        if index and len(index)==len(rows):
            return index
    raise RateError('ساختار پاسخ مرجع نرخ معتبر نیست.')


def number(value):
    text=str(value)
    if len(text)>40 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',text):
        raise ValueError
    result=Decimal(text)
    if not 0<result<=MAX_RATE*10:
        raise ValueError
    return result


def market_for(source, code, data, now):
    try:
        if source=='nobitex':
            book=data[code+'IRT']
            stamp=book['lastUpdate']
            if type(stamp) is not int or not 10**12<=stamp<10**13:
                raise ValueError
            at=datetime.fromtimestamp(stamp//1000,UTC)+timedelta(milliseconds=stamp%1000)
            # Despite the IRT suffix the public API quotes these markets in RIAL.
            def levels(side):
                values=[]
                for price,quantity in book[side]:
                    number(quantity)
                    values.append(number(price)/10)
                return values
            bid=max(levels('bids')).quantize(QUANTUM,rounding=ROUND_FLOOR)
            ask=min(levels('asks')).quantize(QUANTUM,rounding=ROUND_CEILING)
        elif source=='nerkhara':
            row=data[code.lower()]
            if (code not in FIAT or row['id']!=code.lower() or row['family']!='currency' or row['unit']!='IRT'
                    or row['stale'] is not False or not row.get('sources') or 'T' not in row['updated_utc']):
                raise ValueError
            at=datetime.fromisoformat(row['updated_utc'])
            if timezone.is_naive(at):
                at=at.replace(tzinfo=UTC)  # documented updated_utc
            mid=number(row['price'])  # already TOMAN, one reference, not a two-sided book
            bid=mid.quantize(QUANTUM,rounding=ROUND_FLOOR)
            ask=mid.quantize(QUANTUM,rounding=ROUND_CEILING)
        elif source=='denapanel':
            row,=data['services']  # scoped reader must deliver exactly one match
            if (code!='STAR' or row['source']!='denapanel' or row['external_id']!=DENA_STARS_ID
                    or row['platform']!='telegram' or re.findall(r'\w+',row['name'])!=['استارز','تلگرام']
                    or row['price_per']!=DENA_PRICE_PER or type(row['price']) is not int):
                raise ValueError
            evidence=product_page(source,row['item_url'],DENA_STARS_ID)
            if not evidence or unquote(urlsplit(evidence).path).rstrip('/')!=DENA_STARS_PATH:
                raise ValueError
            if row['available'] is not True:
                raise RateError('سرویس استارز تلگرام در دناپنل در دسترس نیست.')
            at=data['observed_at']
            bid=ask=Decimal(row['price'])/DENA_PRICE_PER  # supplier TOMAN per 1,000 → per star
        else:
            raise ValueError
        if not 0<bid<=ask<=MAX_RATE or ask>bid*Decimal('1.15'):
            raise ValueError
    except RateError:
        raise
    except (KeyError,ValueError,IndexError,TypeError,InvalidOperation,OverflowError):
        raise RateError('بازار یا نرخ خرید و فروش قابل تأیید نیست.') from None
    if not valid_age(source,at,now):
        raise RateError('زمان نرخ مرجع قدیمی یا نامعتبر است.')
    return Market(bid,ask,at)


def refresh_rates(ids=None, *, bootstrap=False):
    """Fetch each feed only once. Stage observations; only an operator publishes.

    Bootstrap is explicit, idempotent, and creates a policy only if the market
    returned a valid first quote. It never enables a disabled currency.
    """
    rows=Currency.objects.select_related('fx').order_by('pk')
    if ids is not None:
        rows=rows.filter(pk__in=ids)
    groups={}
    for row in rows:
        policy=getattr(row,'fx',None)
        if policy:
            source=policy.source
        elif bootstrap and row.code in ('USD','USDT','BTC','ETH') and row.type in ('fiat','crypto'):
            source='nerkhara' if row.code=='USD' else 'nobitex'
        elif bootstrap and supported(row.code,row.type,'denapanel'):
            source='denapanel'
        else:
            continue
        if source in SOURCES:
            groups.setdefault(source,[]).append((row,policy is None))
    results={}
    for source,group in groups.items():
        started=timezone.now()
        try:
            data=fetch_source(source)
            failure=''
        except RateError as exc:
            data={};failure=str(exc)
        for row,new in group:
            error=failure
            market=None
            if not error:
                try:
                    if not supported(row.code,row.type,source):
                        raise RateError('مرجع با نوع ارز سازگار نیست.')
                    market=market_for(source,row.code,data,timezone.now())
                except RateError as exc:
                    error=str(exc)
            with transaction.atomic():
                # Same order as the admin policy save. An older, overlapping
                # request cannot resurrect a deleted policy or an obsolete book.
                locked=Currency.objects.select_for_update().filter(pk=row.pk,code=row.code,type=row.type).first()
                if locked is None:continue
                policy=CurrencyPricing.objects.select_for_update().filter(currency_id=row.pk).first()
                if new:
                    if policy:continue
                    if not market:
                        results[row.code]=error
                        continue
                    policy=CurrencyPricing(currency=locked,source=source,spread_mode='percent')
                    if row.code in ('USDT','USD'):
                        policy.spread_mode,policy.sell_extra,policy.buy_less='fixed',5000,10000
                    elif source=='nobitex':
                        policy.sell_extra,policy.buy_less=Decimal('1.8'),Decimal('3.6')
                    # Stars margins stay at zero until the operator chooses them.
                if not policy or policy.source!=source or (policy.checked_at and policy.checked_at>started):
                    continue
                key=f'{source}:{row.code}'
                if market and policy.candidate_key==key and policy.candidate_at:
                    if market.at<policy.candidate_at or (market.at==policy.candidate_at and
                            (market.bid,market.ask)!=(policy.candidate_bid,policy.candidate_ask)):
                        error='نرخ دریافتی از آخرین مشاهده قدیمی‌تر یا متعارض است.'
                        market=None
                if market:
                    policy.candidate_key=key
                    policy.candidate_bid,policy.candidate_ask,policy.candidate_at=market.bid,market.ask,market.at
                policy.checked_at=started
                policy.last_error=error
                policy.save()
                results[row.code]=error
    return results
