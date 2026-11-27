# Currency pricing

`/admin/portal/currency/` uses the existing currency permissions. **به‌روزرسانی
قیمت ارزها** fetches proposals, then opens `/admin/portal/currency/review/`.
Each provider is contacted once per run. Choose one or more rows, edit the
reference and/or the per-side margins, review the buy/sell prices, then publish.
The periodic poller never publishes. A changed reference or a concurrent edit
invalidates the selected batch; there is no partial publication. The public
`/rates/` board lists only active currencies.

* **Nobitex**: [public spot order books](https://apiv2.nobitex.ir/v3/orderbook/all).
  Match the exact `CODEIRT` book; these API prices are in **rial**. Divide by ten
  once to get toman. The merchant buys at the best bid minus the buying
  adjustment, and sells at the best ask plus the selling adjustment.
* **Cash FX**: [Nerkhara public API](https://nerkhara.com/api/), including the
  [Tehran cash dollar reference](https://nerkhara.com/dollar/). Use the specified
  per-unit fiat codes only. Its `IRT` prices are already **toman**. This is an
  indicative cash-market reference, not an executable exchange bid or offer.
  Both adjustments start from that reference; USD never aliases USDT.
* **Telegram Stars (STAR)**: DenaPanel’s public catalogue, direct
  [Telegram Stars service 1161](https://denapanel.ir/service/1161/🌟-استارز-تلگرام-🌟).
  The `قیمت هر 1000 عدد` column quotes **toman per 1,000 stars**. Divide once
  by 1,000 using decimal arithmetic. Use that supplier reference for both sides
  before the operator’s adjustments. The review shows the pack and unit price.
  Reactions, giveaways, unavailable services and ambiguous evidence cannot
  supply a quote. No supplier account or order is involved.
* **Manual**: the existing `currencies.rate` supplies the reference. With no
  policy both rates equal the manual rate. An unsupported asset can remain
  manual. Storefront toman prices are not converted.

For example, at 280,000 toman on both sides, fixed adjustments of +5,000 for
selling and −10,000 for buying give 285,000 and 270,000. Percentage mode uses
`ask × (1 + sell%/100)` and `bid × (1 − buy%/100)`. Round the per-unit selling
rate up and buying rate down to whole toman. Web and bot orders apply the selling
rate, then existing SKU profit and order tax. Crypto deposits are coordinated by
support in a private ticket using the approved buy rate. STAR requires a
positive discount from the approved buying basis to charge a
wallet. The 10% suggestion is not applied until approved. Enable the currency
and the Stars payment method to accept deposits. The invoice snapshots the
discounted rate, discloses the credit, and rechecks the price at Telegram
pre-checkout. Settlement of an already paid invoice uses the invoice snapshot.

The scheduler stores the provider timestamp for exchange feeds and the last
error. DenaPanel has no quote timestamp: record the time its catalogue was
actually read. A failed read never refreshes the previous observation.
No external requests run during checkout. Missing, stale, future-dated, crossed
or anomalously wide books cannot replace a verified quote. A network failure
leaves a previous observation usable only up to its original deadline: 10
minutes for DenaPanel or Nobitex, 30 minutes for Nerkhara. An automatic-source currency
also needs a published quote less than 24 hours old. Polls do not extend its
lifetime. Migration 0016 carries forward the already effective references
with their original timestamps, not a newly asserted operator approval.
Previously completed orders, receipts and refunds retain their original amounts.

## Ticket-only crypto top-ups

The wallet page and Telegram crypto button link to `/account/charge/crypto/`.
The shared legacy `crypto` payment-method switch controls availability. The
authenticated user selects an active crypto and quantity. The private ticket
records the indicative buy rate but does not change the balance. Support
confirms the network, destination and final rate in the ticket. After checking
the transfer, a staff member with **both** `portal.change_ticket` and
`portal.settle_crypto_topup` records its actual received quantity and unique
network transaction hash. Wallet, ledger, ticket closure and audit are saved
in one transaction. Ordinary support membership cannot credit funds.

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
USD/USDT (+5,000/−10,000 toman), BTC/ETH (+1.8%/−3.6%) and Telegram STAR
(no pre-approved margin) with valid first observations and no existing policy.
Use `python manage.py sync_exchange_rates --bootstrap --code STAR` for Stars
alone. On the review page adjust the buy deduction and sell markup, tick
activation if desired and confirm the row. Bootstrap neither enables a currency nor modifies
the stored manual base. Later polls use `sync_exchange_rates` without
`--bootstrap`; explicit operator settings always win.
