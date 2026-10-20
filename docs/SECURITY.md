# Security implementation and limits

Web: HTTPS-only production cookies, CSRF, session rotation, one-time session-bound OTP hashes, five verification attempts, phone/IP SMS throttles, parameterized queries, autoescaped content, CSP, no public source/config routes, permission-scoped staff access, private account responses without caching.

Money: row-locked wallets and payment records; order, debit and ledger commit together; idempotent website checkout key; quote revalidation; one-time refund and terminal order-state checks; the bot and website share payment verification rather than separate writers.

Operations: unprivileged systemd services with filesystem restrictions, dedicated database user, secret files outside the repository, fixed SSH deploy entry point, host-key verification, application health check, dependency lock and vulnerability audit.

Remaining limits: SMS login inherits SIM takeover and SMS provider risks. No claim of a complete penetration test is made. Old third-party bot features outside the covered order/payment/publication paths need ongoing review. Live SMS delivery and real bank settlement require controlled operational verification; automated tests mock external providers.

HSTS is enabled for the website host but deliberately not preloaded or imposed on every subdomain, because independent subdomains may have different TLS requirements. The corresponding two Django warnings are documented and silenced.

Backups contain sensitive personal data and must stay private. Restore tests should use an isolated database. Keep the old server backup until the migration is accepted.
