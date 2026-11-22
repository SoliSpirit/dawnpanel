"""Encode finished wordless illustrations into the two published WebP sizes."""
import argparse
from pathlib import Path
import sys

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal.product_art import CARD_SIZE, FULL_SIZE, GALLERY_KEYS, STATIC_ROOT, gallery_path


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--illustrations', type=Path, required=True,
                        help='Directory of full-bleed <gallery-key>.png originals')
    parser.add_argument('--key', action='append', choices=sorted(GALLERY_KEYS),
                        help='Rebuild only this illustration (repeatable)')
    args = parser.parse_args()
    keys = sorted(args.key or GALLERY_KEYS)
    pending = [key for key in keys if not (args.illustrations / f'{key}.png').is_file()]
    if pending:
        parser.error('Missing originals: ' + ', '.join(pending))
    for key in keys:
        with Image.open(args.illustrations / f'{key}.png') as original:
            full = ImageOps.fit(ImageOps.exif_transpose(original).convert('RGB'), FULL_SIZE,
                                method=Image.Resampling.LANCZOS)
            for small, size, quality in [(False, FULL_SIZE, 83), (True, CARD_SIZE, 80)]:
                path = STATIC_ROOT / gallery_path(key, small=small)
                path.parent.mkdir(parents=True, exist_ok=True)
                full.resize(size, Image.Resampling.LANCZOS).save(path, 'WEBP', quality=quality, method=5)
    print(f'Encoded {len(keys)} illustrations in two sizes.')


if __name__ == '__main__':
    main()
