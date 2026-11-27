# Currency pricing

`/admin/portal/currency/` uses the existing currency permissions. The code opens
the policy for that currency. An admin action refreshes the selected automatic
feeds; each provider is contacted once per run. The public `/rates/` board lists
only active currencies. Inactive currencies can still have an up-to-date policy.

* **Nobitex**: [public spot order books](https://apiv2.nobitex.ir/v3/orderbook/all).
  Match the exact `CODEIRT` book; these API prices are in **rial**. Divide by ten
  once to get toman. The merchant buys at the best bid minus the buying
  adjustment, and sells at the best ask plus the selling adjustment.
* **Cash FX**: [Nerkhara public API](https://nerkhara.com/api/), including the
  [Tehran cash dollar reference](https://nerkhara.com/dollar/). Use the specified
  per-unit fiat codes only. Its `IRT` prices are already **toman**. This is an
  indicative cash-market reference, not an executable exchange bid or offer.
  Both adjustments start from that reference; USD never aliases USDT.
* **Manual**: the existing `currencies.rate` supplies the reference. With no
  policy both rates equal the manual rate. An unsupported asset can remain
  manual. Storefront toman prices are not converted.

For example, at 280,000 toman on both sides, fixed adjustments of +5,000 for
selling and −10,000 for buying give 285,000 and 270,000. Percentage mode uses
`ask × (1 + sell%/100)` and `bid × (1 − buy%/100)`. Round the per-unit selling
rate up and buying rate down to whole toman. Web and bot orders apply the selling
rate, then existing SKU profit and order tax. Crypto deposits are coordinated by
support using the buy rate; a Stars invoice snapshots the applicable buy rate.

The scheduler stores the provider timestamp (not the poll time) and last error.
No external requests run during checkout. Missing, stale, future-dated, crossed
or anomalously wide books cannot replace a verified quote. A network failure
leaves a previous verified quote usable only up to its original deadline:
10 minutes for Nobitex, 30 minutes for Nerkhara (published about every 10 minutes).
New transactions requiring an expired rate stop until there is a valid price.
Previously completed orders, receipts and refunds retain their original amounts.

## Installation

After migrating and deploying, install `deploy/dawnpanel-fx.{service,timer}` as
root-owned unit files. The independently scheduled oneshot runs as the application
user and reads only public HTTPS feeds without credentials.

```sh
install -m 644 /opt/dawnpanel/current/deploy/dawnpanel-fx.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dawnpanel-fx.timer
systemctl start dawnpanel-fx.service
```

Configure policies in admin. Alternatively run `python manage.py sync_exchange_rates
--bootstrap` once as the app user with its environment: this seeds only existing
USD/USDT (+5,000/−10,000 toman) and BTC/ETH (+1.8%/−3.6%) with valid first
observations and no existing policy. It neither enables a currency nor modifies
the stored manual base. Later polls use `sync_exchange_rates` without
`--bootstrap`; explicit operator settings always win.
