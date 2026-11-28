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

## Admin activity and preferences

`/admin/portal/noticepreference/` lists only the private IDs configured under
`telegram.admin_ids`. Each recipient has independent selections for web and bot
purchases, catalogue/pricing, order status, finance, staff support, management,
staff login/logout, new or reopened site errors, incoming bot tickets, receipt
photos and lottery warnings. The last three retain their original actionable
messages. Direct command replies and customer receipts are separate from alerts.
By default, purchase and administrative changes are on; error and session alerts
are opt-in. Saving one recipient does not change another's choices. Muting a
category cancels outstanding unsent deliveries in that category, and the sender
checks the current policy before each API call. An already in-flight API call
can't be recalled.

Committed panel writes, audited operations (e.g. ticket replies and settlements),
and bot admin operations feed the shared sender. Reads and automated catalogue
polls do not create staff activity notices. Summaries use an operation label,
source, admin ID and, where relevant, an object ID; no submitted field values,
ticket contents or verification documents are included in these summaries. An
explicit CLI `--test --test-topic catalog` honours the same subscription.
The owner can delegate `view_noticepreference`/`change_noticepreference`; these
permissions cannot add a Telegram recipient not in the server allowlist.

## Live website chat

Customer messages also enqueue `web_chat` Telegram deliveries and independent
email deliveries in the chat transaction. Each channel snapshots its subscribed
recipients and rechecks before sending. A new message nonce is unique within
the thread. Old conversations initialize the unread counter, not the outboxes.
Each delivery contains a link under `/admin/support/chat/`; opening it requires
the usual staff session and support permission. The chat text stays on the site.

The manager with `change_noticepreference` and `manage_chat_email` sets
each destination at `/admin/portal/noticepreference/`. To install the SMTP
worker after migration, create a root-owned `0600` `/etc/dawnpanel/chat-mail.env`
containing `DAWN_SMTP_HOST`, `DAWN_SMTP_PORT` (587), `DAWN_SMTP_USER`,
`DAWN_SMTP_FROM` and `DAWN_SMTP_PASSWORD`. Use a dedicated SMTP-only
application credential for the sender. The worker uses verified STARTTLS;
the web and bot services do not need that credential.

```sh
install -m 644 /opt/dawnpanel/current/deploy/dawnpanel-chat-email.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dawnpanel-chat-email.timer
systemctl start dawnpanel-chat-email.service
```

The email timer retries temporary failures with backoff. Changing or muting
a destination suppresses queued emails. An in-flight network transmission
cannot be recalled; a lost acknowledgement may cause a repeat. The timestamp
in the settings screen indicates SMTP acceptance, not Gmail inbox placement.
With the worker environment, `manage.py deliver_chat_emails --test` sends a
labelled message to the enabled destinations without creating a customer chat.
For this domain's outbound authentication, see [Cloudflare records](CHAT_MAIL_DNS.md).

All listed Telegram admin notification types can also be selected independently for
email. «ایمیل مثل تلگرام» copies the current selection; save it to opt in.
Messages are multipart (plain text and RTL HTML). Incoming bot receipts/tickets
commit with their outboxes. Telegram keeps its actionable private message; email
contains an administrative summary, not a customer's attachment or message body.
Transient Telegram failures remain queued across restarts.

Supplier checks never publish a price. `/admin/prices/reviews/` shows the newest
ready report. Earlier ready reports are listed at `/admin/prices/reviews/archive/`
with the same detail links and 30-day retention. Reports show old/new source
prices, units, merchant markup and pre-tax sales.
One row can be approved at a custom markup in the panel; bulk approval retains the
existing pricing method. A row also accepts an exact pre-tax selling amount in
toman per displayed pack. This does not change the supplier's observed price or
stack a markup on the entered amount. Choosing markup pricing explicitly removes
the fixed sale. Historical rows link to a version-checked current-price editor.
Telegram opens on a short digest; the pending index and the full catalog open
separately. Tap a number to compare one item's supplier and selling prices and
act on it. The digest's example and each live proposal have explicit approve,
reject and supplier recheck buttons. A decision is bound to the displayed row;
reject keeps the selling price and suppresses the same rejected quote on later checks.
A recheck fetches only that supplier, observes only the chosen mapping and queues
a new one-product report with its own message-bound controls. Bulk approval
still has an explicit confirmation. Superseded observations,
changed products and proposals older than 24 hours cannot overwrite newer prices.
«صفحهٔ منبع» opens the supplier's current public product or service page beside the
observed price, in the current-price editor and on the Telegram detail card. The
digest links its first example and the emailed CSV includes a per-row URL.
Premstore variation links keep their plan parameters when supplied.

## Website errors

`/admin/portal/siteissue/` groups application HTTP 5xx errors and service
failures handled by the SMS login/payment pages. It keeps first/last time,
count, exception class, named route, sanitized code frames and release when
available, instead of raw exception strings or request data. HTTP 4xx and
ordinary customer validation/cancellation are not incidents. Proxy-only errors
and outages of the issue database remain in the server logs.

`view_siteissue` allows investigation; `change_siteissue` also allows resolving
or reopening. Another occurrence after resolution reopens the issue; a continuing
open issue increments its count rather than sending the same Telegram alert each
time. Marking resolved records triage, not an automatic fix.
