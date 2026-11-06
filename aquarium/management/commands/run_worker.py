import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from aquarium import backups, events, timelapse
from aquarium.models import AppSettings

logger = logging.getLogger(__name__)
TICK_SECONDS = 20


def run_step(step):
    """One failing job must not stop the others, or the worker itself."""
    try:
        step()
    except Exception:
        logger.exception("Worker step %s failed", getattr(step, '__name__', step))


def tick():
    now = timezone.now()
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(worker_last_seen=now)
    for step in (events.sync_conditions, events.fire_scheduled, events.finish_timers, events.deliver_due,
                 timelapse.capture_due, backups.run_auto_backup, timelapse.prune_frames, events.prune):
        run_step(step)


class Command(BaseCommand):
    help = "Background jobs: alerts and webhooks, fill timers, webcam time-lapse, automatic backups"

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help="Run one pass and exit")

    def handle(self, *args, **options):
        if options['once']:
            tick()
            return
        self.stdout.write("Background worker started.")
        while True:
            close_old_connections()
            try:
                tick()
            except Exception:
                logger.exception("Worker pass failed")
            close_old_connections()
            time.sleep(TICK_SECONDS)
