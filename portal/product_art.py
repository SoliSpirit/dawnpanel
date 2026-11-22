"""Select the same wordless illustration in the store, previews and Telegram."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageOps
from .service_art import SERVICE_TITLES


STATIC_ROOT = Path(__file__).resolve().parent.parent / 'static'
ART = 'artwork/product-gallery'
FULL_SIZE = (960, 640)
CARD_SIZE = (480, 320)
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
GALLERY_KEYS = frozenset(
    [brand[0] for brand in BRANDS] +
    [f'{platform}-{pk}' for platform, rows in SERVICE_TITLES.items() for pk in rows]
)


def _normalize(text):
    return unicodedata.normalize('NFKC', text).casefold().translate(
        str.maketrans('يك۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','یک01234567890123456789')
    ).replace('\u200c',' ').replace('\ufe0f','')


def _words(text):
    return ' '.join(re.findall(r'[^\W_]+', _normalize(text)))


_ALIASES = [(key, tuple(_words(w) for w in names.split('|'))) for key, _, _, names in BRANDS]
_SERVICE_INDEX = {}
for _platform, _rows in SERVICE_TITLES.items():
    for _pk, _name in _rows.items():
        _SERVICE_INDEX.setdefault((_platform, ' '.join(_normalize(_name).split())), []).append(_pk)


def artwork_key(product_id, platform, name, family_name=''):
    """Match a real product; don't mistake an unrelated item with a recycled ID."""
    matches = _SERVICE_INDEX.get((platform, ' '.join(_normalize(name).split())))
    if matches:
        return f'{platform}-{product_id if product_id in matches else matches[0]}'
    for title in (family_name, name):
        if title:
            text = f' {_words(title)} '
            for key, aliases in _ALIASES:
                if any(f' {alias} ' in text for alias in aliases):
                    return key
    return None


def gallery_path(key, *, small=False):
    suffix = '-480.webp' if small else '.webp'
    if key in GALLERY_KEYS:
        return f'{ART}/{key}{suffix}'
    # New, as-yet unillustrated products still have a local, text-free cover.
    return 'artwork/hero' + suffix


def write_jpeg(image):
    output = BytesIO()
    photo = ImageOps.exif_transpose(image).convert('RGB')
    photo.thumbnail((960, 960), Image.Resampling.LANCZOS)
    # Telegram rejects extremely narrow image ratios.
    if max(photo.size) > 10 * min(photo.size):
        photo = ImageOps.pad(photo, (720, 480), color='#101827')
    photo.save(output, 'JPEG', quality=84, optimize=True)
    return output.getvalue()


@lru_cache(maxsize=24)
def gallery_jpeg(key):
    """Telegram takes JPEG photos. Convert once per illustration, in memory."""
    with Image.open(STATIC_ROOT / gallery_path(key)) as image:
        return write_jpeg(image)
