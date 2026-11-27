# Purchase alerts

Both successful wallet order paths write an `OrderEvent` in the order/debit
transaction. A rollback writes nothing; an idempotent web checkout replay returns
the existing order. Only future purchases generate events. Deposits, payment
previews and the existing public report after an admin confirms a bot order are
separate operations.

Install the independent sender as root after migration:

```sh
install -m 644 /opt/dawnpanel/current/deploy/dawnpanel-order-notices.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dawnpanel-order-notices.timer
systemctl start dawnpanel-order-notices.service
```

The sender normally checks for work ten seconds after the last run. It uses the
same bot token and **positive private `telegram.admin_ids`** as the existing bot.
Each recipient must start the bot. It does not need the bot polling process or a
web request to be running. New events wait when no recipients are configured.
Each recipient is rechecked against the allowlist before sending. The initial
alert contains product, channel, amount, quantity, tracking and a protected
management link, without phone, email or delivery target. Telegram orders retain
the bot's order-action buttons.

Unique order/recipient records, short database claims and expiring leases
prevent ordinary duplicate handling without holding locks across the network.
Transient failures are retried with backoff; 429 honours Telegram's wait.
As with any non-idempotent remote send, a lost acknowledgement after Telegram
accepted a message can result in a repeat of the same tracking code.
`last_error` contains only a reason code. Blocked/invalid recipients stop until
corrected. With the normal service environment as the app user:

* `manage.py deliver_order_notices --test` sends a labelled test to authorized
  recipients, without creating a purchase or altering a wallet.
* `manage.py deliver_order_notices --retry-stopped` retries stopped deliveries
  to current admins. Use after the recipient has started/unblocked the bot.

The admin dashboard also shows the newest committed orders to staff with order
view access. Opt in to system notifications using **فعال‌کردن اعلان مرورگر**.
The dashboard must remain open for browser alerts; Telegram delivery runs
independently of it.
