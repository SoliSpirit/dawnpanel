# Supplier catalogue draft importer

`import_source_catalog` validates an explicitly supplied private JSON snapshot.
It does not fetch prices, schedule updates, publish products, or place supplier
orders. Checkout and payment handling are unchanged.

```sh
python manage.py migrate --noinput
python manage.py import_source_catalog /private/path/snapshot.json
# Back up the production database before applying:
python manage.py import_source_catalog /private/path/snapshot.json --apply
```

Without `--apply`, no products are written. Applying creates inactive products
hidden from both website and Telegram. Existing source associations are skipped;
existing merchant products and prices are not updated. Source identifiers are
unique per supplier. Missing variation data or ambiguous price units abort the
import rather than guessing a price.

Snapshots remain outside Git. The currently captured catalogue has 296 Dena
services and 74 Premstore simple products/variants, not 370 published products.
Supplier availability is not a guarantee that the merchant can fulfil an order.
Review product type, delivery requirements, terms, names, and prices before
publication. Dena category names currently use source category identifiers;
Premstore imports use the `other` platform. These drafts are not yet ready for
website publication under the current storefront platform restrictions.

Concurrent import commands should not be run together. The unique source mapping
and atomic command prevent duplicate associations and partial committed imports;
a conflicting concurrent run may fail and should be retried after inspection.

Automatic refresh, approval controls, storefront category expansion, and
dashboard redesign are separate, unimplemented work.
