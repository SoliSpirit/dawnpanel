# Supplier catalogue and price controls

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
