"""Build static JPEGs for recognised catalogue families; no network required."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal.product_art import ART, BRANDS, ILLUSTRATIONS, STATIC_ROOT, compose_cover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--illustrations', type=Path, help='Optional directory of dawn-product-*.png artwork')
    args = parser.parse_args()
    destination = STATIC_ROOT / ART
    destination.mkdir(parents=True, exist_ok=True)
    for key, label, section, _ in BRANDS:
        path = destination / f'{key}.jpg'
        photo = ILLUSTRATIONS.get(key)
        if key in {'suno', 'kling', 'higgsfield', 'grok'}:
            if args.illustrations is None and path.exists():
                continue
            if args.illustrations is not None:
                photo = args.illustrations / f'dawn-product-{key}.png'
        path.write_bytes(compose_cover(key, label, section, STATIC_ROOT / photo if photo else None))


if __name__ == '__main__':
    main()
