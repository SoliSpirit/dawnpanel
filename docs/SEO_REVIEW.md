# DawnPanel technical SEO and accessibility review — 2026-10-21

Scope: server-rendered home, catalog/AI, product, article and legal pages; private account/admin exclusions. This review does not claim Search Console ownership, confirmed Google indexing, rankings or a guaranteed Lighthouse score.

## Changes

- `/admin/` is the sole management route. Unauthenticated, inactive, non-staff and staff without admin permissions receive404; model-level permission denials also become404. The previous `/manage/` route is removed. Authorized requests retain CSRF and model permissions. Private account, chat and admin responses are no-store and noindex.
- Paginated unfiltered catalog/blog pages have self-canonical `?page=N` and distinct titles; search/filter pages remain noindex with their base canonical. Canonical HTTPS www traffic redirects to the apex while preserving path/query. Sitemap includes only published products/articles and real image URLs.
- Product offers use the actual minimum-order price from checkout, in IRR, without invented ratings or discounts. Article schema now includes its displayed image and mainEntityOfPage. Product/article breadcrumbs and homepage Organization/logo added. JSON-LD text remains escaped against HTML/script injection.
- Article covers are stable per article; cards, article body, metadata and sitemap use the same cover family with day/night companions. Product, article and AI cards have480px responsive sources. Brand-category SVGs are original representative icons, not supplied official brand artwork.
- Desktop decorative React Bits/GSAP/Lenis bundle loads after interaction and idle time, and is omitted on coarse-pointer/reduced-motion devices. Existing visible text is never hidden by delayed entrances. All functional content and links remain server-rendered.
- Fingerprinted static files receive one-year immutable caching; unversioned files retain a shorter cache. Existing scoped HTTPS/HSTS settings remain; no blind preload/subdomain or Trusted Types enforcement was introduced.
- Light-theme small-text contrast improved; announcement bar darkened; link underlines, distinct accessible link labels, larger touch targets and keyboard focus retained. Local Lighthouse before responsive-image changes reported accessibility100, SEO100, best practices100; production results must be recorded separately.

## Reference guidance

- [Google canonical URLs](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
- [Google product structured data](https://developers.google.com/search/docs/appearance/structured-data/product-snippet)

## Optional profile data

Names and email use the account owner's Django user; Jalali date input converts to a real Gregorian date for storage, and province/city are optional. Iranian national-code checksum validates format only, not identity. The value is encrypted with Fernet using a separately generated private server key; it is not repopulated in HTML, exposed in admin lists, or written into audit values. Owners can replace/delete it. Private backups include a0600 key file; never publish it or discard it while encrypted records remain. Key rotation requires a planned decrypt/re-encrypt migration, not simply replacing the key.
