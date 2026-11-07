"""The app's own icon (browser tab, home-screen app) follows the main tank's icon.

PNG copies at the sizes browsers ask for are made on first use and kept in the data folder.
"""
import hashlib
import os
from pathlib import Path

from django.conf import settings
from PIL import Image

from . import icons

SIZES = (32, 180, 192, 512)


def main_tank(tanks=None):
    """The primary tank, or the first one in use. Pass tanks already loaded to save a query."""
    if tanks is None:
        from .models import Tank
        tanks = list(Tank.objects.filter(is_archived=False))
    live = [t for t in tanks if not t.is_archived]
    return next((t for t in live if t.is_primary), live[0] if live else None)


def source_file(tank=None, *, find=True):
    """The full-size picture of the main tank's icon, or None to use the standard nudibranch."""
    if tank is None and find:
        tank = main_tank()
    if tank is None:
        return None
    if tank.icon_choice == 'custom':
        try:
            path = Path(tank.custom_icon.path) if tank.custom_icon else None
        except (ValueError, NotImplementedError):
            path = None
    else:
        stem = tank._icon_stem()
        # The original, not the small page thumbnail, so the 512 px app icon stays sharp.
        path = icons.icon_dir() / f'{stem}.png' if stem else None
        if path and not path.is_file():
            path = icons.file_for_stem(stem)
    return path if path and path.is_file() else None


_FIND = object()


def version(path=_FIND):
    """Changes whenever the icon does, so browsers fetch the new one. Pass the picture if you have it (or None)."""
    path = source_file() if path is _FIND else path
    if not path:
        return 'default'
    return hashlib.sha1(f'{path}:{path.stat().st_mtime_ns}'.encode()).hexdigest()[:10]


def png(size):
    """A square PNG of the main tank's icon at this size, or None when there isn't one."""
    path = source_file()
    if path is None or size not in SIZES:
        return None
    folder = Path(settings.DATA_DIR) / 'app-icons'
    tag = version(path)
    target = folder / f'{tag}-{size}.png'
    if not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as image:
            image = image.convert('RGBA')
            width, height = image.size
            side = min(width, height)
            left, top = (width - side) // 2, (height - side) // 2
            image = image.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
            temporary = target.with_suffix(f'.{os.getpid()}.tmp')  # two server processes can't clash
            image.save(temporary, 'PNG', optimize=True)
            temporary.replace(target)
        for old in folder.glob('*.png'):  # icons from before a change
            if not old.name.startswith(tag):
                old.unlink(missing_ok=True)
    return target
