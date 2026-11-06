"""Shrinks uploaded photos: phone cameras produce far bigger files than these pages need."""
import io
import logging
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)
MAX_SIDE = 1600  # pixels on the longest side, plenty for a full-screen photo
QUALITY = 82


def compressed_jpeg(source, name):
    """A smaller JPEG copy of an image, or None if it can't be read (the original is then kept as it was)."""
    try:
        source.seek(0)
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)  # phones store sideways pixels plus a note to rotate them
            if image.mode in ('RGBA', 'LA', 'PA') or 'transparency' in image.info:
                rgba = image.convert('RGBA')
                image = Image.new('RGB', rgba.size, 'white')
                image.paste(rgba, mask=rgba.getchannel('A'))
            image = image.convert('RGB')
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            buffer = io.BytesIO()
            image.save(buffer, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        logger.warning("Couldn't compress the photo %s, so it was kept as uploaded.", name)
        return None
    finally:
        source.seek(0)
    return ContentFile(buffer.getvalue(), name=f"{Path(name).stem}.jpg")
