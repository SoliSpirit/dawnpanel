# DawnPanel

سایت و ربات تلگرام با پایگاه داده مشترک؛ فروشگاه وب شامل خدمات روبیکا، ایتا و بله و اشتراک‌های هوش مصنوعی است.

- ورود با کد پیامکی sms.ir، محدودیت درخواست و تلاش، کد هش‌شده و مصرف یک‌باره.
- کیف پول، سفارش و پرداخت زرین‌پال مشترک؛ تراکنش اتمیک و کنترل برداشت و بازگشت وجه تکراری.
- انتشار مستقل محصول در سایت و تلگرام، قابل تغییر در هر دو پنل مدیریت.
- تیکت چندپیامی، ارجاع به پشتیبان، نقش‌های جداگانه و گزارش تغییرات مدیریتی.
- مدیریت ارز و کد هدیه، دعوت دوستان، رتبه کاربر، وبلاگ و نقشه سایت.

## مسیرها

`/login/` ورود · `/account/` حساب کاربر · `/staff/` میز کار کارکنان · `/manage/` مدیریت محتوا و نقش‌ها.

ورود مدیریت هم از مسیر پیامکی انجام می‌شود. شماره مالک فقط در تنظیمات خصوصی سرور تعریف می‌شود. برای کارکنان، پس از اولین ورود آن‌ها در مدیریت کاربران، گزینه staff و گروه مناسب را فعال کنید؛ به کارکنان عادی superuser ندهید.

## تنظیمات

`DAWN_CONFIG` مسیر config خصوصی سرور، `DJANGO_SECRET_KEY` کلید مستقل سایت، `DAWN_OWNER_PHONE` شماره مالک، `DAWN_PRODUCTION=1` و `ALLOWED_HOSTS` لازم هستند. نمونه بدون کلید در `telegram/config.example.json` است.

دیتابیس فعلی ربات باید پیش از مهاجرت وب بازیابی شده باشد. سپس:

```text
pip install -r requirements.lock
python manage.py migrate --noinput
python manage.py prepare_portal
python manage.py seed_content
python manage.py collectstatic --noinput
python manage.py check --deploy
```

فایل config، بکاپ، اطلاعات کاربران و کلیدهای TLS در مخزن قرار نمی‌گیرند. کاربر سرویس به دیتابیس اختصاصی DawnPanel دسترسی دارد؛ دسترسی root دیتابیس به برنامه داده نمی‌شود.

## انتشار

گردش کار GitHub Actions تست‌ها و بررسی آسیب‌پذیری وابستگی‌ها را اجرا می‌کند. انتشار main تنها با `DEPLOY_ENABLED=true` فعال می‌شود و از secrets با نام‌های `DEPLOY_HOST`، `DEPLOY_PORT`، `DEPLOY_SSH_KEY` و `DEPLOY_KNOWN_HOSTS` استفاده می‌کند. کلید میزبان باید از اتصال معتبر گرفته شود؛ بررسی کلید میزبان خاموش نمی‌شود.

سرویس‌ها در `deploy/` هستند. release.py یک مسیر انتشار محدود با SHA مشخص، استخراج امن آرشیو، اجرای برنامه با کاربر dawnpanel، بررسی سلامت و برگشت symlink به نسخه قبلی در صورت شکست فراهم می‌کند. این برگشت، بازگردانی دیتابیس یا نسخه وابستگی‌ها نیست؛ برای تغییرات ناسازگار schema ابتدا بکاپ و برنامه مهاجرت لازم است.

## آزمون

```text
python manage.py test portal --noinput
python manage.py check
pip-audit -r requirements.lock
```

تست‌های محلی با داده ساختگی اجرا می‌شوند و پیامک یا پرداخت واقعی ایجاد نمی‌کنند. اطمینان کامل از نبود تمام اشکالات یا امنیت مطلق ممکن نیست؛ تغییرات بعدی نیز به آزمون نیاز دارند.

## دامنه

DNS دامنه و apibot باید به سرور مقصد اشاره کنند و پروکسی Cloudflare خاموش باشد. تمدید HTTPS، بکاپ زمان‌بندی‌شده و پایش سلامت باید روی سرور فعال بمانند.


### Storefront animation assets

The Django storefront uses React Bits SpotlightCard as decorative React islands, GSAP with ScrollTrigger for section entrances, and Lenis for desktop wheel scrolling. Product content and prices remain server rendered. Touch scrolling stays native, reduced-motion preferences disable animation, and account/payment pages do not load this bundle.

Run `npm ci` then `npm run build` after changing `frontend/`. Commit generated `static/storefront.js`, `static/storefront.css` and `static/storefront.js.LEGAL.txt`; CI rebuilds and checks for drift. The server only needs Python. React Bits source provenance and license are in `frontend/react-bits/`; third-party license notices are in `frontend/THIRD_PARTY_NOTICES.md`.

### Product images and AI subscriptions

AI products use platform `ai`, with independent website/Telegram publication flags. Only publish actual plans with their real price, term, account type and delivery instructions. The homepage introductions are category links and do not fabricate purchasable inventory.

Product admin supports a product photo, alt text and removing the active photo. Uploads accept decoded JPEG/PNG/WebP, max 5 MB and 16 megapixels. The server strips metadata, re-encodes to WebP, caps dimensions at 1600, and gives random filenames. `ProductVisual` stores media separately from the unmanaged legacy product table. Production media lives at `/var/lib/dawnpanel/media`, outside release folders; Nginx serves `/media/products/` and the daily backup includes media alongside database dumps. Use the updated `deploy/nginx.conf` (6 MB request limit) and `deploy/backup.py` root helper when provisioning.

Product pages include a social image, alt text, canonical URL and structured data; AI offers use actual minimum-order totals converted from toman to IRR. Search/filter URLs are noindex/follow; `/ai/` is indexable and included in the image-aware sitemap. Generated artwork prompts and paths are documented in `docs/DESIGN_ASSETS.md`.
