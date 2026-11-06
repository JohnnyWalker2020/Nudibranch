from django.core.management.base import BaseCommand
from PIL import Image

from aquarium.icons import icon_dir, thumbnail_dir

THUMBNAIL_SIZE = 256


class Command(BaseCommand):
    help = "Makes small copies of the character icons for pages to show. The originals aren't changed."

    def handle(self, *args, **options):
        source_dir, target_dir = icon_dir(), thumbnail_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        sources = sorted(source_dir.glob('*.png'))
        made = 0
        for source in sources:
            target = target_dir / f'{source.stem}.webp'
            if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
                continue
            with Image.open(source) as image:
                image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
                image.save(target, 'WEBP', quality=85, method=4)
            made += 1
        # Remove copies of icons that no longer exist.
        names = {source.stem for source in sources}
        for orphan in target_dir.glob('*.webp'):
            if orphan.stem not in names:
                orphan.unlink()
        self.stdout.write(f"Icon thumbnails: {made} made, {len(sources)} total.")
