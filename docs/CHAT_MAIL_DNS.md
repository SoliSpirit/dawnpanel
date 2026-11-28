# احراز هویت ایمیل چت برای Gmail

در Cloudflare، دامنهٔ `dawnpanel.ir` را باز کنید و در **DNS → Records** دو رکورد از نوع **TXT** با TTL خودکار ثبت کنید. این مقادیر برای سرور ارسال فعلی دان‌پنل هستند.

**نام `@`** — مقدار SPF:

```text
v=spf1 ip4:46.38.138.244 ~all
```

اگر دامنه از قبل رکوردی با `v=spf1` دارد، فقط `ip4:46.38.138.244` را پیش از `all` در همان رکورد اضافه کنید. سایر رکوردهای TXT، از جمله تأییدیهٔ گوگل، باید بمانند.

**نام `dkim._domainkey`** — مقدار DKIM را به‌صورت یک خط کپی کنید:

```text
v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAt4XfMQ4Z/8WQr9ELzvB5c0TblyXg3C5Tp9k6Wm7YIGgmx5WKb43wtnCS4r6YdpkbU9AAiLOyKombfi7Wj1jtJm22HBD4iOKKXonzGPtzdAsy6xTm1Jnsvdt0k3oYmZqR8iZMsPBJwkryJ6XBDr9VZfZeUMFtgbEJVjndFNNbJpWH7VsGtSBDDNhmdC+29QudnNvlVfTHL+RrDHRLcO99a8KzhmUk41ny0jEp+bSM5Y7XRvGvQVOIf7M2+rOzErXm2NiCGRuB050HvcBuFIIh88CQ1nVZYEIBnF1PvjV3lViFMhmQcjNaALEUSqDs+c3l3GH9HxeIj2NTD+WhSXsyBQIDAQAB
```

این **کلید عمومی** امضای فعلی Mailcow است. اگر کلید را در Mailcow عوض کردید، مقدار جدید را از تنظیمات DKIM همان دامنه بردارید.

سپس در [اعلان‌های تلگرام و ایمیل](https://dawnpanel.ir/admin/portal/noticepreference/) مقصد را فعال کنید. در Gmail، روی پیام دریافتی **Show original / نمایش نسخه اصلی** را بزنید؛ وضعیت SPF و DKIM را آنجا می‌بینید.
