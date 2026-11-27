# Supplier catalogue and price controls

## Product photos and Telegram visibility

The website uses full-width, wordless product illustrations. Local 480w and
960w WebPs in `static/artwork/product-gallery/` are selected via `srcset`;
the original large PNGs are not required on the server. Operator uploads take
precedence. Brand families have their own artwork, as do the individual
messaging services and native bot SKUs in `portal/service_art.py`. The bot uses
the same selection and sends a JPEG from a bounded in-memory cache. The
legacy `/product-cover/<id>.jpg` URLs still check website eligibility.
`scripts/build_product_covers.py --illustrations DIR [--key KEY]` exports
wordless `<key>.png` originals. Missing originals fail the build rather than
silently substituting the category image.

Telegram service rows are no longer eligible for public website listing, detail
or checkout. Existing rows, orders and bot visibility remain unchanged; Telegram
Premium sold as a standalone subscription is distinct and remains in the store.
Website imports skip publication of Telegram service rows; other eligible items
can still be published. Art in the bot is applied to products already enabled
there and does not change their availability.

## Storefront organization

Subscription plans with the same Premstore parent URL share one display card.
Cards and the detail page's plan picker are native keyboard-operable disclosures.
Opening a card reveals its order/plan links; choosing a plan opens its page.
The selected plan's URL is also the purchase form's action.
Known original merchant ChatGPT/Gemini/Claude plans share their brand's card only
when exactly one imported parent matches. Within those cards, the 18 native
ChatGPT/Gemini plans transcribed in `PLAN_REFERENCE.md` have reviewed Premstore
variation equivalents (`portal/catalog_aliases.py`). On the website we prefer
the supplier-linked SKU over its original copy, independently of price. Rubika's
two original heart-eyes services (#6/#8) likewise share one web listing.
No generic merging on similar names, prices, emoji, or duration occurs.

Old published mirror URLs temporarily redirect to the preferred plan; old reviews
remain bound to their original SKU and price. If only the native SKU is published,
it can appear on its own. A monitored out-of-stock equivalent cannot reappear on
the web through its mirror. Existing product rows, bot flags, artwork, supplier
mappings and historical order IDs are retained. Search and category filters
recognize eligible mirror names; the sitemap only lists the visible choices.

The curated presentation taxonomy lives in `portal/store_catalog.py`. Subscription
categories are separate from Telegram/Rubika/Eitaa/Bale services. Existing
category IDs and historical orders are not rewritten. The legacy `platform`,
numeric `category`, search and pagination links still work; `section` adds the
curated category filter. Counts refer to visible product families, not plans.
Minimum card prices use actual checkout totals for minimum order quantities.

The storefront also supports `collection=subscriptions` and
`collection=messaging`. Available subcategories are scoped to the chosen
collection/platform, not to the current search or subcategory selection.
Product pages estimate variable-quantity totals using integer rounding; the
server always recalculates at review and again before debiting the wallet.
A guest can return to the same plan and quantity after login for up to 20
minutes; delivery information is not retained in a guest draft.

## Tax and wallet totals

In product management, open **قیمت و تعداد → درصد مالیات**. Rates are per SKU:
0–100 percent, up to two decimal places. The product editor for a web mirror links
to the effective storefront SKU. An unset rate is zero. Migration 0013 adds managed
side tables without changing legacy tables or inferring tax on historical orders.

Web and Telegram use `portal/pricing.py`: convert currency and apply merchant
profit, ceil to whole toman for the pack, then ceil `pack × quantity / price_per`
for the order subtotal. Tax is computed **once per order**: ceil `subtotal ×
rate / 100`. The server stores the reviewed breakdown and rechecks it before
payment, including when the total is unchanged. The purchase transaction records
the subtotal, rate and tax with the wallet debit. A cancellation refunds the
stored inclusive total. Supplier price approval only changes the untaxed base.

After migration 0012, backfill the existing parent titles/descriptions:

```sh
python manage.py refresh_catalog_metadata
```

This command fetches the public Premstore catalogue but updates **only**
`SourceProduct.family_name` and `family_summary` for matching source IDs/URLs.
It does not import new products, apply prices, alter availability, change price
proposals or touch schedules. Re-running it refreshes these editorial fields;
do not run it after manual family-text edits unless replacement is intended.

Public catalogues come from fixed HTTPS endpoints on `denapanel.ir` and
`premstore.ir`. Responses have time/size/page limits, redirects are rejected,
and a malformed catalogue is rejected rather than treated as zero prices.
No supplier account, API secret, copied logo, or supplier checkout is used.

## Import

```sh
python manage.py migrate --noinput
python manage.py import_source_catalog --source premstore
python manage.py import_source_catalog --source denapanel
# After backup and checking fulfilment/terms:
python manage.py import_source_catalog --source premstore --apply --publish
python manage.py import_source_catalog --source denapanel --apply --publish
```

Without `--apply`, nothing is written. Without `--publish`, imports create
inactive drafts hidden from website and Telegram. Publication affects only new,
available products and only the website. Existing source associations are skipped,
not overwritten or republished. Stable source IDs prevent duplicate associations.
The importer still accepts a private snapshot path instead of `--source`.
Do not run multiple import commands concurrently.

Premstore variants become separate products using their own prices, plan labels
and descriptions, not the parent "from" price. Dena uses its explicitly labelled
price per 1,000 and maximum/minimum fields. Prices are integer toman. Unknown
currencies, fractional currency units, missing variants and inconsistent units
are rejected. Photos fall back to the existing DawnPanel illustrations.

Existing unlinked Telegram-only products remain private. Imported `other` and
Telegram products may be published through their source association. Customers
use the existing DawnPanel checkout/wallet/gateway. **Orders are not automatically
sent to suppliers.** Source availability does not guarantee merchant fulfilment.
Descriptions and delivery requirements must be reviewed by the merchant.

## Admin workflow

The admin dashboard links to **تنظیمات دریافت قیمت** and **بررسی قیمت محصولات**.
Both source settings are created by migration, with scheduling OFF and approval
ON. Product managers can review proposals; senior managers can configure schedules.
Actions additionally require product-change permission and normal admin CSRF.

1. Select a source in settings and use "دریافت قیمت‌ها اکنون".
2. Review pending proposals, select up to 50, then confirm apply or reject on
   the confirmation screen. Prices older than 24h cannot be applied.
3. Turn scheduling on and set the interval (minimum 15 minutes).
4. Leaving approval on means scheduled checks only propose prices.
5. Turning approval off permits automatic application within the configured
   percentage-change bound (default 25%). Larger changes stay pending.
6. Disable synchronization on an individual source-product row to manage its
   price/availability manually. Manual product editing remains in Product admin.

The source price replaces only `Product.price`; existing profit percentage stays
unchanged. It is therefore a supplier-base price, not necessarily the final sales
price. Currency-priced products, changed quantity units, or product edits after
the proposal was fetched produce conflicts and are not overwritten.
Fetch/apply/reject events are audited.

In **بررسی قیمت محصولات**, the link under the last observed price opens the
supplier's product page: the selected variation at Premstore or the matching
service detail at Dena. The optional `item_url` is separate from the parent
`source_url` used to group plans in the storefront. Neither is fetched by the
monitor. An explicitly out-of-stock plan may still quote a price. A missing ID
in a valid catalogue is labelled separately; a failed response retains the
previous observation.

Use **بررسی مجدد** for one row, select checkboxes and choose the recheck action,
or use **بررسی مجدد همهٔ نتایج** for all pages of the current search/filter.
Each source is fetched once per operation. A manual recheck can observe a paused
item; it does not enable its schedule, apply a new sale price or postpone a
full scheduled run. Remaining stock/approval rules still apply.

In either price monitoring or Products, click **سود فروش** on a row, or select
products and use **تنظیم درصد سود انتخاب‌ها**. Enter a percentage or `0` for no
markup. This sets the merchant's existing per-SKU percentage on the selected
products only, including native products without a supplier. Price proposals
with a pre-edit merchant baseline still require a fresh check.

Missing/unavailable supplier items retain the merchant's stored price but are
excluded from public purchasing while synchronization is enabled. A network error
retains last successful observations; no automatic deactivation is inferred
from an error. Rejected prices stay rejected until the source price changes.
Changing approval mode does not apply pending prices until another check occurs
or an operator explicitly approves them.

## Scheduler installation

After deploying code/migrations, as root:

```sh
install -m 644 /opt/dawnpanel/current/deploy/dawnpanel-prices.service /etc/systemd/system/dawnpanel-prices.service
install -m 644 /opt/dawnpanel/current/deploy/dawnpanel-prices.timer /etc/systemd/system/dawnpanel-prices.timer
systemctl daemon-reload
systemctl enable --now dawnpanel-prices.timer
```

The timer wakes every five minutes, but each source's persisted interval and
enabled flag determine whether it is fetched. No update thread runs in web
workers. A database lease prevents overlapping scheduled/manual fetches.

```sh
python manage.py sync_source_prices --due
python manage.py sync_source_prices --source premstore
systemctl status dawnpanel-prices.timer
journalctl -u dawnpanel-prices.service --no-pager -n 30
```

The supplier websites may change their API/HTML, block requests or cache prices;
failures require operator attention. This is a public-price importer, not a
guaranteed commercial supplier API or inventory fulfilment integration.
