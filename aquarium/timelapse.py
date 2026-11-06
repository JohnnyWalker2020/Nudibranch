"""Grabs still frames from webcams for time-lapse playback."""
import io
import urllib.request
from datetime import timedelta

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from .models import TimelapseFrame, WebcamFeed, not_retired

MAX_BYTES = 15 * 1024 * 1024
TIMEOUT = 15
JPEG_START = b'\xff\xd8'
JPEG_END = b'\xff\xd9'


class CaptureError(Exception):
    pass


def snapshot_source(feed):
    """URL to grab from, or '' if this feed type can't provide a still image."""
    if feed.snapshot_url:
        return feed.snapshot_url
    return feed.feed_url if feed.feed_type == 'mjpeg' else ''


def first_jpeg(stream, chunk_size=65536):
    """Reads an MJPEG stream just far enough to return its first complete JPEG frame."""
    buffer = b''
    while len(buffer) < MAX_BYTES:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        buffer += chunk
        start = buffer.find(JPEG_START)
        if start == -1:
            continue
        end = buffer.find(JPEG_END, start)
        if end != -1:
            return buffer[start:end + 2]
    raise CaptureError("No complete image arrived from the stream.")


def fetch_image(url):
    if not url.lower().startswith(('http://', 'https://')):
        raise CaptureError("The camera's address must start with http:// or https://.")
    request = urllib.request.Request(url, headers={'User-Agent': 'Nudibranch-Reef-Manager'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            content_type = response.headers.get('Content-Type', '').lower()
            if 'multipart' in content_type:
                data = first_jpeg(response)
            else:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise CaptureError("The image is too large.")
    except CaptureError:
        raise
    except (OSError, ValueError) as exc:
        raise CaptureError(str(getattr(exc, 'reason', exc))[:200] or "Couldn't reach the camera.") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            extension = (image.format or 'JPEG').lower().replace('jpeg', 'jpg')
    except Exception as exc:
        raise CaptureError("The camera didn't return a usable image.") from exc
    return data, extension


def capture_frame(feed, now=None):
    """Captures one frame and records success or failure on the feed. Returns the frame or None."""
    now = now or timezone.now()
    source = snapshot_source(feed)
    frame = None
    error = ''
    if not source:
        error = "Add a snapshot URL: this feed type has no still image to grab."
    else:
        try:
            data, extension = fetch_image(source)
            frame = TimelapseFrame(feed=feed, captured_at=now)
            frame.image.save(f"{feed.pk}/{timezone.localtime(now):%Y%m%d-%H%M%S}.{extension}", ContentFile(data), save=True)
        except CaptureError as exc:
            error = str(exc)
    WebcamFeed.objects.filter(pk=feed.pk).update(last_capture_at=now, last_capture_error=error[:255])
    return frame


def capture_due(now=None):
    now = now or timezone.now()
    count = 0
    for feed in not_retired(WebcamFeed.objects.filter(is_active=True, timelapse_enabled=True)):
        interval = timedelta(minutes=max(1, feed.timelapse_interval_minutes))
        if feed.last_capture_at is None or now - feed.last_capture_at >= interval:
            count += 1 if capture_frame(feed, now) else 0
    return count


def prune_frames(now=None):
    now = now or timezone.now()
    for feed in WebcamFeed.objects.all():
        if feed.timelapse_keep_days:
            cutoff = now - timedelta(days=feed.timelapse_keep_days)
            for frame in feed.frames.filter(captured_at__lt=cutoff):
                frame.delete()
