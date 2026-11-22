"""Shared, local product artwork for the storefront and Telegram."""
from colorsys import hls_to_rgb
from functools import lru_cache
from hashlib import blake2s
from io import BytesIO
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


STATIC_ROOT = Path(__file__).resolve().parent.parent / 'static'
ART = 'artwork/product-covers'
# Stable brand names, not supplier IDs or the currently cheapest plan.
BRANDS = (
    ('gemini','Google Gemini','ai','جمنای|جمینای|gemini'),
    ('suno','Suno','music','suno|سونو'),
    ('kling','Kling AI','video','kling|کیلینگ'),
    ('higgsfield','Higgsfield','video','higgsfield|هیگزفیلد'),
    ('grok','Grok & Cursor','development','grok|cursor|گراک|کرسر'),
    ('elevenlabs','ElevenLabs','music','elevenlabs|الون لبز|الونلبز'),
    ('grammarly','Grammarly','business','grammarly|گرامرلی'),
    ('perplexity','Perplexity','ai','perplexity|پرپلکسیتی'),
    ('claude','Claude Pro','ai','claude|کلاد|کلود'),
    ('chatgpt','ChatGPT','ai','chatgpt|chat gpt|چت جی پی تی|چت جیپیتی'),
    ('granola','Granola','business','granola|گرانولا'),
    ('gamma','Gamma','business','gamma|گاما'),
    ('quillbot','QuillBot','business','quillbot|کوئیل بات'),
    ('microsoft365','Microsoft 365','software','microsoft 365|مایکروسافت ۳۶۵'),
    ('ilovepdf','iLovePDF','business','ilovepdf|آی لاو ام پی دی اف|آی لاوم پی دی اف'),
    ('notion','Notion','business','notion|نوشن'),
    ('kiro','Kiro','development','kiro|کایرو'),
    ('gumloop','Gumloop','development','gumloop|گام لوپ'),
    ('zencoder','Zencoder','development','zencoder|زن کدر'),
    ('lovable','Lovable','development','lovable|لاوبل'),
    ('brainfm','Brain.fm','music','brain fm|برین اف ام'),
    ('spotify','Spotify','music','spotify|اسپاتیفای'),
    ('soundcloud','SoundCloud','music','soundcloud|ساندکلاود'),
    ('deezer','Deezer','music','deezer|دیزر'),
    ('picsart','Picsart','design','picsart|پیکس آرت'),
    ('canva','Canva','design','canva|کنوا|کانوا'),
    ('figma','Figma','design','figma|فیگما'),
    ('capcut','CapCut Pro','design','capcut|کپ کات'),
    ('duolingo','Duolingo','education','duolingo|دولینگو'),
    ('linkedin','LinkedIn Premium','education','linkedin|لینکدین'),
    ('windows','Windows 11 Pro','software','windows|ویندوز'),
    ('youtube','YouTube Premium','video','youtube|یوتیوب'),
    ('telegram-premium','Telegram Premium','social','telegram premium|تلگرام پریمیوم|تلگرام پرمیوم'),
)
ILLUSTRATIONS = {
    'gemini': 'artwork/products-v1/gemini-dark-480.webp',
    'claude': 'artwork/claude-480.webp',
    'chatgpt': 'artwork/products-v1/chatgpt-dark-480.webp',
}
BACKDROPS = {
    'ai': 'artwork/ai-480.webp',
    'rubika': 'artwork/products-v1/rubika-dark-480.webp',
    'eitaa': 'artwork/products-v1/eitaa-dark-480.webp',
    'bale': 'artwork/products-v1/bale-dark-480.webp',
    'telegram': 'artwork/social-480.webp',
    'other': 'artwork/hero-480.webp',
}
for _, _, section, _ in BRANDS:
    if section != 'ai':
        BACKDROPS[section] = f'artwork/categories/{section}.webp'


def _words(text):
    text = unicodedata.normalize('NFKC', text).casefold().translate(str.maketrans('يك','یک'))
    return ' '.join(re.findall(r'[^\W_]+', text))


_ALIASES = [(key, tuple(_words(w) for w in names.split('|'))) for key, _, _, names in BRANDS]


def brand_cover(title):
    text = f' {_words(title)} '
    return next((f'{ART}/{key}.jpg' for key, aliases in _ALIASES
                 if any(f' {alias} ' in text for alias in aliases)), '')


def _gradient(seed, size):
    w, h = size
    hue = int.from_bytes(blake2s(seed.encode(), digest_size=2).digest(), 'big') / 65536
    pixels = []
    for y in range(45):
        for x in range(68):
            shine = max(0, 1 - ((x - 49)**2 + (y - 13)**2)**.5 / 47)
            pixels.append(tuple(round(c*255) for c in hls_to_rgb(hue, .08 + .18*shine, .52 + .25*shine)))
    layer = Image.new('RGB', (68, 45))
    layer.putdata(pixels)
    return layer.resize((w, h), Image.Resampling.BICUBIC)


def write_jpeg(image):
    output = BytesIO()
    photo = ImageOps.exif_transpose(image).convert('RGB')
    photo.thumbnail((720, 720), Image.Resampling.LANCZOS)
    # Telegram rejects extremely narrow image ratios.
    if max(photo.size) > 10 * min(photo.size):
        photo = ImageOps.pad(photo, (720, 480), color='#101827')
    photo.save(output, 'JPEG', quality=84, optimize=True)
    return output.getvalue()


def compose_cover(key, label, section, photo=None, *, service=False):
    """Draw bounded artwork without using external fonts, URLs or disk cache."""
    w, h = 540, 360
    image = _gradient(key, (w, h))
    with Image.open(photo or STATIC_ROOT / BACKDROPS.get(section, BACKDROPS['other'])) as source:
        art = ImageOps.fit(source.convert('RGB'), (424, 248), method=Image.Resampling.LANCZOS)
        if not photo and not service:
            art = ImageEnhance.Brightness(art).enhance(.58)
    mask = Image.new('L', art.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 423, 247), radius=25, fill=255)
    image.paste(art, (58, 28), mask)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((58, 28, 481, 275), radius=25, outline='#c7eeee', width=2)
    if not photo and not service:
        color = image.getpixel((490, 60))
        draw.rounded_rectangle((188, 70, 352, 234), radius=42, fill=color, outline='#a8e2de', width=3)
        ink = '#ebffff'
        if key == 'elevenlabs':
            for x in (242, 278):
                draw.rounded_rectangle((x, 111, x+20, 193), radius=3, fill=ink)
        elif key == 'windows':
            for x in (226, 273):
                for y in (108, 155):
                    draw.rounded_rectangle((x, y, x+40, y+40), radius=3, fill=ink)
        elif key == 'perplexity':
            for points in [[(234, 103), (306, 177), (234, 177), (306, 103), (306, 201)],
                           [(234, 103), (234, 201)], [(270, 103), (270, 201)]]:
                draw.line(points, fill=ink, width=5)
        else:
            mark = ''.join(word[0] for word in label.split() if word[0].isalpha())[:2] or label[:1]
            if len(mark) == 1:
                mark = label[:2]
            draw.text((270, 153), mark, anchor='mm', font=ImageFont.load_default(60), fill=ink)
    draw.text((60, 309), label, anchor='lm', font=ImageFont.load_default(26), fill='#f8ffff')
    tag = 'SERVICE' if service else 'D A W N'
    draw.text((480, 311), tag, anchor='rm', font=ImageFont.load_default(13), fill='#ade7e5')
    return write_jpeg(image)


@lru_cache(maxsize=64)
def service_cover(product_id, platform, name):
    # Per-product palette and reference; no customer or checkout data is used.
    platform_name = {'ai':'AI Tools', 'telegram':'Telegram', 'rubika':'Rubika',
                     'eitaa':'Eitaa', 'bale':'Bale'}.get(platform, 'DawnPanel')
    return compose_cover(name, f'{platform_name}  /  {product_id}', platform, service=True)
