"""One quotation in integer toman for the website, Telegram, and wallet."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, localcontext

from .models import Currency
from .exchange_rates import currency_rates, RateError

MAX_QUANTITY = 100_000_000
MAX_TOTAL = 100_000_000_000


class BusinessError(ValueError):
    pass


def ceil_div(amount, divisor):
    return (amount + divisor - 1) // divisor


@dataclass(frozen=True)
class Quote:
    subtotal: int
    tax_bps: int  # 100 basis points = 1 percent

    @property
    def tax_percent(self):
        return Decimal(self.tax_bps) / 100

    @property
    def tax_amount(self):
        return ceil_div(self.subtotal * self.tax_bps, 10_000)

    @property
    def total(self):
        return self.subtotal + self.tax_amount

    @property
    def breakdown(self):
        return {'subtotal': self.subtotal, 'tax_bps': self.tax_bps}

    def check_review(self, total, breakdown):
        # An in-flight review from before this release never disclosed a tax.
        matches = breakdown == self.breakdown if breakdown is not None else self.tax_bps == 0
        if total != self.total or not matches:
            raise BusinessError('قیمت یا مالیات تغییر کرده است؛ سفارش را دوباره بررسی کنید.')


@dataclass(frozen=True)
class Pricing:
    pack: int  # after currency conversion and merchant profit, BEFORE tax
    price_per: int
    min_order: int
    max_order: int | None
    tax_bps: int

    def amounts(self, quantity):
        return Quote(ceil_div(self.pack * quantity, self.price_per), self.tax_bps)

    def quote(self, quantity):
        if (not isinstance(quantity, int) or quantity < max(1, self.min_order)
                or quantity > min(self.max_order or MAX_QUANTITY, MAX_QUANTITY)):
            raise BusinessError('تعداد خارج از محدوده مجاز است.')
        quote = self.amounts(quantity)
        if not 0 < quote.total <= MAX_TOTAL:
            raise BusinessError('مبلغ سفارش نامعتبر است.')
        return quote

    def affordable(self, balance):
        # Exact inverse of the two order-level ceilings (not balance/unit_price).
        before_tax = min(balance, MAX_TOTAL) * 10_000 // (10_000 + self.tax_bps)
        quantity = min(before_tax * self.price_per // self.pack,
                       self.max_order or MAX_QUANTITY, MAX_QUANTITY)
        return quantity if quantity >= self.min_order else 0


def pricing_for(product):
    if product.price_per <= 0:
        raise BusinessError('قیمت محصول نیاز به بررسی دارد.')
    with localcontext() as ctx:
        ctx.prec = 80
        amount = product.price_amount if product.price_amount is not None else Decimal(product.price)
        if product.price_currency != 'TOMAN':
            currency = Currency.objects.select_related('fx').filter(code=product.price_currency, is_active=True).first()
            if not currency:
                raise BusinessError('نرخ ارز در دسترس نیست.')
            try:
                amount *= currency_rates(currency).sell
            except RateError as error:
                raise BusinessError(str(error)) from None
        pack = int((amount * (100 + max(Decimal(0), product.product_profit_percent)) / 100
                    ).to_integral_value(rounding=ROUND_CEILING))
    bps = int(product.tax_percent * 100)
    if pack <= 0 or not 0 <= bps <= 10_000:
        raise BusinessError('قیمت یا مالیات محصول نیاز به بررسی دارد.')
    return Pricing(pack, product.price_per, product.min_order, product.max_order, bps)
