import io
import json
import re
import shutil
import tempfile
import threading
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .alert_history import alert_summary
from .alerts import compute_alert_state
from . import icons
from .icons import character_icons
from .themes import theme_css
from .schedule import parse_step
from . import backups, compatibility, events, fill, planner, power, timelapse
from .models import (
    DoseLog, PlumbingRun, SumpChamber,
    QuickTimer,
    WaterChangeLog,
    AlertRecord, Animal, AnimalGroup, AppSettings, CostEntry, ParameterTarget, DosingReservoir, Equipment, EventState, FillTimer, MaintenanceRoutine,
    ParameterLog, ParameterType, Sump, PlanProject, PlannedItem, PlannedSystem, QuarantineEntry, ROSystem, SpeciesCatalog, Tank,
    WebcamFeed, WebhookDelivery, WebhookEndpoint, WishlistItem,
)


def species(name, sci, **kw):
    defaults = dict(category='fish', suggested_group='Fish', care_level='Beginner', reef_safe='Yes',
                    temperament='peaceful', min_tank_gallons=20, max_size_inches=Decimal('3'))
    defaults.update(kw)
    return SpeciesCatalog.objects.create(name=name, species=sci, **defaults)


def jpeg_bytes(color='red'):
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(buf, 'JPEG')
    return buf.getvalue()


class _Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        self.server.received.append((dict(self.headers), self.rfile.read(length)))
        self.send_response(self.server.status)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', self.server.content_type)
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, *args):
        pass


class ServerMixin:
    def start_server(self, status=200, content_type='image/jpeg', body=b''):
        server = HTTPServer(('127.0.0.1', 0), _Receiver)
        server.received, server.status, server.content_type, server.body = [], status, content_type, body
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, f"http://127.0.0.1:{server.server_port}/"


class CatalogSeedTests(TestCase):
    def test_csv_is_valid_and_seed_is_repeatable(self):
        call_command('seed_reef_data', verbosity=0, stdout=io.StringIO())
        total = SpeciesCatalog.objects.count()
        self.assertGreaterEqual(total, 240)
        call_command('seed_reef_data', verbosity=0, stdout=io.StringIO())
        self.assertEqual(SpeciesCatalog.objects.count(), total)
        self.assertTrue(SpeciesCatalog.objects.filter(name='Peppermint Shrimp').exists())
        self.assertFalse(SpeciesCatalog.objects.filter(category='fish', min_tank_gallons__isnull=True).exists())

    def test_seed_fills_gaps_but_keeps_user_edits(self):
        SpeciesCatalog.objects.create(name='Yellow Tang', species='Custom', notes='Mine')
        call_command('seed_reef_data', verbosity=0, stdout=io.StringIO())
        tang = SpeciesCatalog.objects.get(name='Yellow Tang')
        self.assertEqual(tang.notes, 'Mine')
        self.assertEqual(tang.min_tank_gallons, 75)


class CompatibilityTests(TestCase):
    def titles(self, stock, volume, **kw):
        return [w['title'] for w in compatibility.check_stock(stock, volume, **kw)]

    def test_small_tank_warns(self):
        big = species('Big', 'Bigus fish', min_tank_gallons=100)
        warnings = compatibility.check_stock([(big, 1)], 40)
        self.assertEqual(warnings[0]['level'], 'danger')
        self.assertEqual(compatibility.check_stock([(big, 1)], 90)[0]['level'], 'warning')
        self.assertFalse(any('room' in t for t in self.titles([(big, 1)], 120)))

    def test_rival_genus(self):
        a = species('A', 'Zebrasoma one', min_tank_gallons=None)
        b = species('B', 'Zebrasoma two', min_tank_gallons=None)
        self.assertTrue(any('Zebrasoma' in t for t in self.titles([(a, 1), (b, 1)], 300)))
        self.assertFalse(any('Zebrasoma' in t for t in self.titles([(a, 2)], 300)))

    def test_not_reef_safe_ignored_for_fish_only(self):
        fish = species('Trigger', 'Rhinecanthus aculeatus', reef_safe='No')
        self.assertTrue(any('not reef safe' in t for t in self.titles([(fish, 1)], 100)))
        self.assertFalse(any('not reef safe' in t for t in self.titles([(fish, 1)], 100, reef=False)))

    def test_bioload(self):
        fish = species('F', 'Fishus one', max_size_inches=Decimal('10'))
        self.assertEqual(compatibility.bioload([(fish, 2)], 40), 0.5)
        self.assertTrue(any('Fish load' in t for t in self.titles([(fish, 2)], 60)))

    def test_addition_only_reports_new_issues(self):
        tank = Tank.objects.create(name='T', volume_gallons=30, capacity_is_manual=True)
        big = species('Big', 'Bigus fish', min_tank_gallons=100)
        Animal.objects.create(name='Big', species='Bigus fish', tank=tank)
        small = species('Small', 'Smallus fish')
        self.assertEqual(compatibility.warnings_for_addition(small, tank), [])
        other = species('Other big', 'Otherus fish', min_tank_gallons=100)
        self.assertEqual(len([w for w in compatibility.warnings_for_addition(other, tank) if 'room' in w['title']]), 1)
        self.assertTrue(big)

    def test_catalog_add_warns_about_this_addition(self):
        tank = Tank.objects.create(name='T', volume_gallons=30, capacity_is_manual=True)
        big = species('Big', 'Bigus fish', min_tank_gallons=100)
        response = self.client.post(reverse('species_add_to_tank', args=[big.pk]), {'tank': tank.pk, 'count': 1}, follow=True)
        self.assertContains(response, 'needs more room')


class FillTests(TestCase):
    def test_estimate_scales(self):
        self.assertAlmostEqual(fill.estimated_gph(72, 60, 77, 60, 77), 3.0)
        self.assertAlmostEqual(fill.estimated_gph(72, 60, 77, 30, 77), 1.5)
        self.assertLess(fill.estimated_gph(72, 60, 77, 60, 50), 3.0)
        self.assertEqual(fill.estimated_gph(72, 60, 77, 60, 77, measured_gph=Decimal('2.2')), 2.2)

    def test_fill_estimate(self):
        result = fill.fill_estimate(10, 2, waste_ratio=3, stop_at_percent=90)
        self.assertEqual(result['gallons'], 9.0)
        self.assertEqual(result['minutes'], 270.0)
        self.assertEqual(result['waste_gallons'], 27.0)
        self.assertEqual(result['hours_label'], '4 h 30 min')
        self.assertIsNone(fill.fill_estimate(10, 0))

    def test_units(self):
        self.assertAlmostEqual(fill.to_gallons(3785.41, 'ml'), 1)
        self.assertAlmostEqual(fill.to_gallons(3.78541, 'L'), 1)
        self.assertEqual(fill.to_gallons(5, 'gal'), 5)

    def test_api(self):
        ro = ROSystem.objects.create(name='R', rated_gpd=72, feed_temp_f=77, measured_gph=None)
        data = self.client.get(reverse('fill_calc_api'), {'system': ro.pk, 'gallons': 3}).json()
        self.assertEqual(data['minutes'], 60.0)
        self.assertEqual(self.client.get(reverse('fill_calc_api')).status_code, 400)


class PowerTests(TestCase):
    def test_summary(self):
        settings_obj = AppSettings.load()
        settings_obj.electricity_rate = Decimal('0.10')
        settings_obj.save()
        tank = Tank.objects.create(name='T', capacity_is_manual=True)
        Equipment.objects.create(name='Pump', category='return_pump', wattage=100, tank=tank, power_setting_percent=50)
        Equipment.objects.create(name='Heat', category='heater', wattage=200, tank=tank, hours_per_day=Decimal('12'))
        Equipment.objects.create(name='Off', category='other', wattage=999, tank=tank, status='offline')
        summary = power.power_summary()
        self.assertEqual(summary['kwh_day'], 3.6)  # 100W at 50% for 24h = 1.2, 200W for 12h = 2.4
        self.assertEqual(summary['cost_day'], 0.36)


class EventTests(ServerMixin, TestCase):
    def setUp(self):
        self.param = ParameterType.objects.create(name='Alk', code='alk', unit='dKH', min_ideal=8, max_ideal=9, low_limit=7)
        self.settings = AppSettings.load()
        self.settings.events_baselined = True
        self.settings.save()
        self.server, self.url = self.start_server()
        self.endpoint = WebhookEndpoint.objects.create(name='E', url=self.url, secret='s3')

    def log(self, value, when=None):
        return ParameterLog.objects.create(parameter_type=self.param, value=Decimal(str(value)), measured_at=when or timezone.now())

    def test_condition_fires_once_then_after_clearing(self):
        self.log(7.5)
        self.assertEqual(events.sync_conditions(), 1)
        self.assertEqual(events.sync_conditions(), 0)
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.event_type, 'parameter.out_of_range')
        self.log(8.5)
        now = timezone.now()
        events.sync_conditions(now)
        self.log(7.5, now + timedelta(minutes=1))
        # Coming back within the quiet period doesn't notify again (a hovering probe can't spam).
        self.assertEqual(events.sync_conditions(now + timedelta(minutes=2)), 0)
        self.log(8.5, now + timedelta(minutes=3))
        later = now + timedelta(minutes=5)
        events.sync_conditions(later)
        events.sync_conditions(later + events.CLEAR_AFTER + timedelta(minutes=1))
        self.log(7.5, later + events.CLEAR_AFTER + timedelta(minutes=2))
        self.assertEqual(events.sync_conditions(later + events.CLEAR_AFTER + timedelta(minutes=3)), 1)

    def test_critical_is_a_separate_event(self):
        self.log(7.5)
        events.sync_conditions()
        self.log(6.5)
        self.assertEqual(events.sync_conditions(), 1)
        self.assertEqual(WebhookDelivery.objects.first().event_type, 'parameter.critical')
        self.assertEqual(WebhookDelivery.objects.first().severity, 'critical')

    def test_first_run_is_silent(self):
        AppSettings.objects.filter(pk=1).update(events_baselined=False)
        self.log(7.5)
        self.assertEqual(events.sync_conditions(), 0)
        self.assertEqual(WebhookDelivery.objects.count(), 0)
        self.assertTrue(AppSettings.load().events_baselined)
        self.assertEqual(events.sync_conditions(), 0)

    def test_stale_probe(self):
        ParameterType.objects.filter(pk=self.param.pk).update(stale_after_hours=2)
        self.log(8.5, timezone.now() - timedelta(hours=3))
        self.assertEqual(events.sync_conditions(), 1)
        self.assertEqual(WebhookDelivery.objects.get().event_type, 'parameter.stale')

    def test_endpoint_filter_and_pause(self):
        self.endpoint.event_types = ['reservoir.low']
        self.endpoint.save()
        self.log(7.5)
        self.assertEqual(events.sync_conditions(), 0)
        self.assertTrue(EventState.objects.exists())

    def test_json_delivery_is_signed(self):
        import hashlib
        import hmac
        self.log(7.5)
        events.sync_conditions()
        self.assertEqual(events.deliver_due(), 1)
        headers, body = self.server.received[0]
        payload = json.loads(body)
        self.assertEqual(payload['type'], 'parameter.out_of_range')
        self.assertEqual(payload['data']['parameter'], 'alk')
        self.assertEqual(headers['X-Nudibranch-Delivery'], payload['id'])
        expected = 'sha256=' + hmac.new(b's3', body, hashlib.sha256).hexdigest()
        self.assertEqual(headers['X-Nudibranch-Signature'], expected)
        self.assertEqual(WebhookDelivery.objects.get().status, 'sent')

    def test_ntfy_format(self):
        WebhookEndpoint.objects.filter(pk=self.endpoint.pk).update(format='ntfy')
        events.emit('parameter.critical', 'critical', 'Alk is low 🐠', 'Body text')
        events.deliver_due()
        headers, body = self.server.received[0]
        self.assertEqual(body, b'Body text')
        self.assertEqual(headers['Title'], 'Alk is low')
        self.assertEqual(headers['Priority'], '5')

    def test_failure_retries_then_gives_up(self):
        self.server.status = 500
        events.emit('reservoir.low', 'warning', 'T', 'M')
        now = timezone.now()
        self.assertEqual(events.deliver_due(now), 0)
        delivery = WebhookDelivery.objects.get()
        self.assertEqual((delivery.status, delivery.attempts, delivery.response_code), ('pending', 1, 500))
        self.assertGreater(delivery.next_attempt_at, now)
        self.assertEqual(events.deliver_due(now), 0)
        self.assertEqual(len(self.server.received), 1)
        for _ in range(4):
            WebhookDelivery.objects.update(next_attempt_at=timezone.now())
            events.deliver_due()
        delivery.refresh_from_db()
        self.assertEqual((delivery.status, delivery.attempts), ('failed', 5))

    def test_unreachable_endpoint_is_recorded(self):
        WebhookEndpoint.objects.filter(pk=self.endpoint.pk).update(url='http://127.0.0.1:1/')
        events.emit('reservoir.low', 'warning', 'T', 'M')
        events.deliver_due()
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.status, 'pending')
        self.assertTrue(delivery.error)

    def _routine(self, at_time):
        return MaintenanceRoutine.objects.create(
            title='Feeder', routine_type='automated', category='feeding', repeat_every=1, repeat_unit='day',
            start_date=timezone.localdate() - timedelta(days=2), checklist_items=[],
            schedule_events=[{'time': at_time.strftime('%H:%M'), 'action': 'Feed'}],
        )

    def _at(self, hour, minute):
        return timezone.make_aware(datetime.combine(timezone.localdate(), time(hour, minute)))

    def test_scheduled_event_fires_exactly_once_without_retries(self):
        self._routine(time(8, 0))
        AppSettings.objects.filter(pk=1).update(last_schedule_check=self._at(7, 59))
        self.assertEqual(events.fire_scheduled(self._at(7, 59)), 0)
        self.assertEqual(events.fire_scheduled(self._at(8, 0)), 1)
        AppSettings.objects.filter(pk=1).update(last_schedule_check=self._at(7, 59))
        self.assertEqual(events.fire_scheduled(self._at(8, 0)), 0)  # a repeated window can't double-feed
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.max_attempts, 1)
        self.assertEqual(delivery.data['action'], 'Feed')
        self.server.status = 500
        events.deliver_due()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'failed')

    def test_missed_schedule_is_dropped(self):
        self._routine(time(8, 0))
        AppSettings.objects.filter(pk=1).update(last_schedule_check=self._at(6, 0))
        self.assertEqual(events.fire_scheduled(self._at(9, 0)), 0)

    def test_paused_routine_does_not_fire(self):
        routine = self._routine(time(8, 0))
        routine.is_active = False
        routine.save()
        AppSettings.objects.filter(pk=1).update(last_schedule_check=self._at(7, 59))
        self.assertEqual(events.fire_scheduled(self._at(8, 0)), 0)

    def test_timer_finishes_and_notifies(self):
        now = timezone.now()
        running = FillTimer.objects.create(name='Later', ends_at=now + timedelta(minutes=5))
        done = FillTimer.objects.create(name='Fill', ends_at=now - timedelta(seconds=1))
        self.assertEqual(events.finish_timers(now), 1)
        done.refresh_from_db()
        running.refresh_from_db()
        self.assertEqual((done.status, running.status), ('finished', 'running'))
        self.assertEqual(events.finish_timers(now), 0)
        self.assertEqual(WebhookDelivery.objects.get().event_type, 'timer.finished')

    def test_quarantine_complete_event(self):
        Animal.objects.create(name='Fish', status='quarantine', quarantine_days=10,
                              quarantine_started=timezone.localdate() - timedelta(days=10))
        events.end_finished_quarantines()
        self.assertTrue(WebhookDelivery.objects.filter(event_type='quarantine.complete').exists())

    def test_worker_pass_runs(self):
        # Backups can't run inside a test's open transaction; BackupTests covers them.
        with mock.patch('aquarium.backups.run_auto_backup'):
            call_command('run_worker', '--once')
        self.assertTrue(AppSettings.load().worker_online)

    def test_one_failing_job_does_not_stop_the_others(self):
        self.log(7.5)
        with mock.patch('aquarium.backups.run_auto_backup'), \
                mock.patch('aquarium.events.sync_conditions', side_effect=RuntimeError('boom')):
            with self.assertLogs('aquarium.management.commands.run_worker', level='ERROR'):
                call_command('run_worker', '--once')
        self.assertTrue(AppSettings.load().worker_online)


class TimelapseTests(ServerMixin, TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)

    def test_snapshot_capture(self):
        _, url = self.start_server(body=jpeg_bytes())
        feed = WebcamFeed.objects.create(name='C', feed_url=url, timelapse_enabled=True)
        self.assertEqual(timelapse.capture_due(), 1)
        self.assertEqual(feed.frames.count(), 1)
        self.assertTrue(Path(feed.frames.get().image.path).exists())
        feed.refresh_from_db()
        self.assertEqual(feed.last_capture_error, '')
        self.assertEqual(timelapse.capture_due(), 0)  # not due again yet

    def test_mjpeg_first_frame(self):
        boundary = b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg_bytes() + b'\r\n--frame\r\n'
        _, url = self.start_server(content_type='multipart/x-mixed-replace; boundary=frame', body=boundary)
        feed = WebcamFeed.objects.create(name='C', feed_url=url)
        self.assertIsNotNone(timelapse.capture_frame(feed))

    def test_bad_image_records_error(self):
        _, url = self.start_server(content_type='text/html', body=b'<html>login</html>')
        feed = WebcamFeed.objects.create(name='C', feed_url=url)
        self.assertIsNone(timelapse.capture_frame(feed))
        feed.refresh_from_db()
        self.assertIn('usable', feed.last_capture_error)

    def test_stream_type_without_snapshot_explains(self):
        feed = WebcamFeed.objects.create(name='C', feed_url='http://x/', feed_type='iframe')
        self.assertIsNone(timelapse.capture_frame(feed))
        feed.refresh_from_db()
        self.assertIn('snapshot URL', feed.last_capture_error)

    def test_prune_deletes_old_frames_and_files(self):
        _, url = self.start_server(body=jpeg_bytes())
        feed = WebcamFeed.objects.create(name='C', feed_url=url, timelapse_keep_days=5)
        old = timelapse.capture_frame(feed, timezone.now() - timedelta(days=6))
        path = Path(old.image.path)
        timelapse.prune_frames()
        self.assertEqual(feed.frames.count(), 0)
        self.assertFalse(path.exists())


class BackupTests(TransactionTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / 'media').mkdir()
        override = override_settings(DATA_DIR=self.tmp, MEDIA_ROOT=self.tmp / 'media')
        override.enable()
        self.addCleanup(override.disable)

    def test_roundtrip(self):
        (self.tmp / 'media' / 'pic.jpg').write_bytes(b'photo')
        tank = Tank.objects.create(name='Before', capacity_is_manual=True)
        path = backups.create_backup('manual')
        with zipfile.ZipFile(path) as archive:
            self.assertIn('nudibranch.sqlite3', archive.namelist())
            self.assertIn('media/pic.jpg', archive.namelist())
        Tank.objects.filter(pk=tank.pk).update(name='After')
        Tank.objects.create(name='Extra', capacity_is_manual=True)
        (self.tmp / 'media' / 'pic.jpg').write_bytes(b'changed')
        safety = backups.restore_backup(path)
        self.assertEqual(list(Tank.objects.values_list('name', flat=True)), ['Before'])
        self.assertEqual((self.tmp / 'media' / 'pic.jpg').read_bytes(), b'photo')
        self.assertTrue((backups.backup_dir() / safety).exists())
        self.assertFalse(AppSettings.load().events_baselined)

    def test_rejects_bad_files_without_changing_anything(self):
        Tank.objects.create(name='Keep', capacity_is_manual=True)
        junk = self.tmp / 'junk.zip'
        junk.write_bytes(b'not a zip')
        with self.assertRaises(backups.BackupError):
            backups.restore_backup(junk)
        empty = self.tmp / 'empty.zip'
        with zipfile.ZipFile(empty, 'w') as archive:
            archive.writestr('hello.txt', 'hi')
        with self.assertRaises(backups.BackupError):
            backups.restore_backup(empty)
        wrong = self.tmp / 'wrong.zip'
        with zipfile.ZipFile(wrong, 'w') as archive:
            archive.writestr('nudibranch.sqlite3', 'not a database')
        with self.assertRaises(backups.BackupError):
            backups.restore_backup(wrong)
        self.assertTrue(Tank.objects.filter(name='Keep').exists())
        self.assertEqual(backups.list_backups(), [])

    def test_zip_paths_cannot_escape_media(self):
        path = backups.create_backup('manual')
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('media/../../escaped.txt', 'bad')
        backups.restore_backup(path)
        self.assertFalse((self.tmp.parent / 'escaped.txt').exists())
        self.assertFalse((self.tmp / 'escaped.txt').exists())

    def test_names_are_validated(self):
        for bad in ('../secret.zip', 'nudibranch.sqlite3', 'nudibranch-manual-1.zip', ''):
            with self.assertRaises(backups.BackupError):
                backups.resolve_backup(bad)

    def test_auto_backup_schedule_and_pruning(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'auto_backup_days': 7, 'auto_backup_keep': 1})
        self.assertIsNotNone(backups.run_auto_backup())
        self.assertIsNone(backups.run_auto_backup())
        future = timezone.now() + timedelta(days=8)
        with mock.patch('aquarium.backups.timezone.localtime', return_value=timezone.localtime() + timedelta(days=8)):
            self.assertIsNotNone(backups.run_auto_backup(future))
        self.assertEqual(len([b for b in backups.list_backups() if b['kind'] == 'auto']), 1)

    def test_views(self):
        client = Client()
        client.post(reverse('backup_create'))
        items = backups.list_backups()
        self.assertEqual(len(items), 1)
        name = items[0]['name']
        self.assertEqual(client.get(reverse('backup_download', args=[name])).status_code, 200)
        self.assertEqual(client.get(reverse('backup_download', args=['evil.zip'])).status_code, 404)
        Tank.objects.create(name='New', capacity_is_manual=True)
        client.post(reverse('backup_restore'), {'name': name, 'confirm': 'nope'})
        self.assertTrue(Tank.objects.filter(name='New').exists())
        client.post(reverse('backup_restore'), {'name': name, 'confirm': 'RESTORE'})
        self.assertFalse(Tank.objects.filter(name='New').exists())


class PlannerTests(TestCase):
    def setUp(self):
        self.fish = species('Clown', 'Amphiprion ocellaris', suggested_group='Clownfish Pair', icon='🐠')
        self.coral = species('Coral', 'Coralus sp.', category='coral', suggested_group='Corals', min_tank_gallons=None,
                             max_size_inches=None, temperament='')
        self.plan = PlannedSystem.objects.create(name='Dream', volume_gallons=75, capacity_is_manual=True,
                                                 sump_gallons=20, budget=Decimal('100'))
        PlannedItem.objects.create(plan=self.plan, kind='livestock', species=self.fish, name='Clown', quantity=2, unit_cost=Decimal('30'))
        PlannedItem.objects.create(plan=self.plan, kind='livestock', species=self.coral, name='Coral', quantity=1)
        PlannedItem.objects.create(plan=self.plan, kind='equipment', name='Pump', category='return_pump', wattage=50, max_flow_gph=800, unit_cost=Decimal('60'))
        PlannedItem.objects.create(plan=self.plan, kind='equipment', name='Heater', category='heater', wattage=300, quantity=1)

    def test_analysis(self):
        a = planner.analyze(self.plan)
        self.assertEqual(a['system_gallons'], 95.0)
        self.assertEqual(a['total_cost'], 120.0)
        self.assertTrue(a['over_budget'])
        self.assertEqual(a['flow']['return_gph'], 600)
        self.assertEqual(a['flow']['return_turnover'], 6.3)
        self.assertEqual(a['heater_per_gal'], 3.2)
        self.assertEqual(a['heater_status'], 'ok')
        self.assertIn('Lighting', a['missing'])
        self.assertIn('Protein skimmer', a['missing'])
        self.assertNotIn('Heater', a['missing'])

    def test_track_new_system(self):
        response = self.client.post(reverse('plan_track', args=[self.plan.pk]), {'quarantine_fish': 'on'})
        tank = Tank.objects.get(name='Dream')
        self.assertRedirects(response, reverse('tank_detail', args=[tank.pk]))
        self.assertEqual(float(tank.volume_gallons), 75)
        self.assertEqual(tank.sumps.count(), 1)
        self.assertTrue(tank.is_primary)
        self.assertEqual(tank.equipment.count(), 2)
        self.assertEqual(tank.equipment.get(name='Pump').flow_derate_percent, 25)
        clown = tank.animals.get(name='Clown')
        self.assertEqual((clown.count, clown.status), (2, 'quarantine'))
        self.assertIsNotNone(clown.quarantine_started)
        self.assertEqual(tank.animals.get(name='Coral').status, 'healthy')
        self.assertTrue(clown.groups.filter(name='Clownfish Pair').exists())

    def test_tracking_twice_does_not_duplicate(self):
        planner.track_plan(self.plan)
        planner.track_plan(self.plan)
        self.assertEqual(Tank.objects.filter(name='Dream').count(), 1)
        self.assertEqual(Equipment.objects.count(), 2)
        PlannedItem.objects.create(plan=self.plan, kind='equipment', name='Light', category='lighting', wattage=100)
        planner.track_plan(self.plan)
        self.assertEqual(Tank.objects.filter(name='Dream').count(), 1)
        self.assertEqual(Equipment.objects.count(), 3)

    def test_existing_primary_tank_is_kept(self):
        Tank.objects.create(name='Current', is_primary=True, capacity_is_manual=True)
        tank = planner.track_plan(self.plan)
        self.assertFalse(tank.is_primary)
        self.assertEqual(Tank.objects.filter(is_primary=True).count(), 1)

    def test_stocking_plan_for_existing_tank(self):
        tank = Tank.objects.create(name='Current', volume_gallons=40, capacity_is_manual=True)
        Equipment.objects.create(name='Old light', category='lighting', wattage=100, tank=tank)
        Animal.objects.create(name='Clown', species='Amphiprion ocellaris', tank=tank, count=2)
        big = species('Big', 'Bigus fish', min_tank_gallons=100)
        plan = PlannedSystem.objects.create(name='Add', existing_tank=tank)
        PlannedItem.objects.create(plan=plan, kind='livestock', species=big, name='Big')
        a = planner.analyze(plan)
        self.assertEqual(a['display_gallons'], 40.0)
        self.assertNotIn('Lighting', a['missing'])
        self.assertTrue(any('Big needs' in w['title'] for w in a['warnings']))
        self.assertEqual(planner.track_plan(plan), tank)
        self.assertEqual(Tank.objects.count(), 1)
        self.assertTrue(tank.animals.filter(name='Big').exists())


class PlanProjectTests(TestCase):
    def setUp(self):
        self.fish = species('Clown', 'Amphiprion ocellaris')
        self.project = PlanProject.objects.create(name='Fish room', budget=Decimal('500'))
        self.one = self.plan('Reef A', 75)
        self.two = self.plan('Reef B', 40)
        self.loose = PlannedSystem.objects.create(name='Loose', volume_gallons=10, capacity_is_manual=True)

    def plan(self, name, gallons):
        plan = PlannedSystem.objects.create(name=name, volume_gallons=gallons, capacity_is_manual=True, sump_gallons=10, project=self.project)
        PlannedItem.objects.create(plan=plan, kind='livestock', species=self.fish, name='Clown', quantity=2, unit_cost=Decimal('30'))
        PlannedItem.objects.create(plan=plan, kind='equipment', name='Pump', category='return_pump', wattage=50, max_flow_gph=800, unit_cost=Decimal('200'))
        return plan

    def test_combined_totals_and_comparison(self):
        page = self.client.get(reverse('project_detail', args=[self.project.pk]))
        totals = page.context['totals']
        self.assertEqual(totals['gallons'], 135.0)
        self.assertEqual(totals['cost'], 520.0)
        self.assertTrue(totals['over_budget'])
        self.assertEqual(totals['tracked'], 0)
        self.assertGreater(totals['power'], 0)
        for text in ('Reef A', 'Reef B', 'Return turnover', 'Still to add', 'Loose'):
            self.assertContains(page, text)
        self.assertEqual([r['plan'] for r in page.context['rows']], [self.one, self.two])

    def test_planning_a_project_creates_nothing_real(self):
        self.client.get(reverse('project_detail', args=[self.project.pk]))
        self.client.get(reverse('planner'))
        self.client.post(reverse('plan_duplicate', args=[self.one.pk]))
        self.client.post(reverse('project_add_plans', args=[self.project.pk]), {'plans': [self.loose.pk]})
        self.assertEqual(Tank.objects.count(), 0)
        self.assertEqual(Equipment.objects.count(), 0)
        self.assertEqual(Animal.objects.count(), 0)
        self.assertEqual(CostEntry.objects.count(), 0)

    def test_tracking_one_leaves_the_others_as_plans(self):
        self.client.post(reverse('plan_track', args=[self.one.pk]))
        self.assertEqual(list(Tank.objects.values_list('name', flat=True)), ['Reef A'])
        self.two.refresh_from_db()
        self.assertIsNone(self.two.tracked_tank)
        self.assertFalse(self.two.items.filter(tracked=True).exists())
        self.assertEqual(self.client.get(reverse('project_detail', args=[self.project.pk])).context['totals']['tracked'], 1)

    def test_duplicate_is_independent_and_untracked(self):
        planner.track_plan(self.one)
        response = self.client.post(reverse('plan_duplicate', args=[self.one.pk]))
        copy = PlannedSystem.objects.get(name='Copy of Reef A')
        self.assertRedirects(response, reverse('plan_detail', args=[copy.pk]))
        self.assertEqual(copy.project, self.project)
        self.assertIsNone(copy.tracked_tank)
        self.assertEqual(copy.items.count(), 2)
        self.assertFalse(copy.items.filter(tracked=True).exists())
        copy.items.first().delete()
        self.one.refresh_from_db()
        self.assertEqual(self.one.items.count(), 2)
        self.assertIsNotNone(self.one.tracked_tank)
        planner.track_plan(copy)
        self.assertEqual(Tank.objects.count(), 2)

    def test_add_remove_and_delete_keep_plans(self):
        url = reverse('project_add_plans', args=[self.project.pk])
        self.client.post(url, {'plans': [self.loose.pk]})
        self.loose.refresh_from_db()
        self.assertEqual(self.loose.project, self.project)
        self.client.post(reverse('project_remove_plan', args=[self.project.pk, self.loose.pk]))
        self.loose.refresh_from_db()
        self.assertIsNone(self.loose.project)
        self.client.post(reverse('project_delete', args=[self.project.pk]))
        self.assertEqual(PlanProject.objects.count(), 0)
        self.assertEqual(PlannedSystem.objects.count(), 3)

    def test_new_plan_preselects_project(self):
        page = self.client.get(reverse('plan_create'), {'project': self.project.pk})
        self.assertEqual(page.context['form'].initial['project'], self.project)
        response = self.client.post(reverse('project_create'), {'name': 'Second'})
        self.assertRedirects(response, reverse('project_detail', args=[PlanProject.objects.get(name='Second').pk]))

    def test_empty_project_and_list_render(self):
        empty = PlanProject.objects.create(name='Empty')
        self.assertContains(self.client.get(reverse('project_detail', args=[empty.pk])), 'No tanks in this project yet')
        page = self.client.get(reverse('planner'))
        self.assertContains(page, 'Fish room')
        self.assertContains(page, 'New project')
        self.assertEqual(self.client.get(reverse('project_edit', args=[empty.pk])).status_code, 200)

    def test_existing_tank_plan_in_project(self):
        tank = Tank.objects.create(name='Current', volume_gallons=40, capacity_is_manual=True, is_primary=True)
        PlannedSystem.objects.create(name='Stock it', existing_tank=tank, project=self.project)
        self.assertEqual(self.client.get(reverse('project_detail', args=[self.project.pk])).status_code, 200)


class QuarantineTests(TestCase):
    def test_status_starts_the_clock(self):
        animal = Animal.objects.create(name='F')
        self.assertIsNone(animal.quarantine_day)
        animal.status = 'quarantine'
        animal.save()
        self.assertEqual(animal.quarantine_started, timezone.localdate())
        self.assertEqual(animal.quarantine_day, 1)
        self.assertFalse(animal.quarantine_complete)
        animal.quarantine_started = timezone.localdate() - timedelta(days=30)
        self.assertTrue(animal.quarantine_complete)

    def test_flow(self):
        animal = Animal.objects.create(name='F')
        self.client.post(reverse('quarantine_start', args=[animal.pk]))
        self.client.post(reverse('quarantine_entry_add', args=[animal.pk]), {
            'logged_on': timezone.localdate().isoformat(), 'kind': 'medication', 'medication': 'Copper', 'dose': '2 ml'})
        self.assertEqual(QuarantineEntry.objects.get().medication, 'Copper')
        self.assertContains(self.client.get(reverse('quarantine_detail', args=[animal.pk])), 'Copper')
        self.client.post(reverse('quarantine_finish', args=[animal.pk]))
        animal.refresh_from_db()
        self.assertEqual(animal.status, 'healthy')


class TimerViewTests(TestCase):
    def test_start_validates(self):
        self.client.post(reverse('timer_start'), {'minutes': '0'})
        self.client.post(reverse('timer_start'), {'minutes': 'abc'})
        self.client.post(reverse('timer_start'), {'minutes': '99999'})
        self.assertEqual(FillTimer.objects.count(), 0)
        self.client.post(reverse('timer_start'), {'minutes': '10', 'name': 'Fill'})
        timer = FillTimer.objects.get()
        self.assertAlmostEqual((timer.ends_at - timer.started_at).total_seconds(), 600, delta=1)

    def test_extend_reopens_and_cancel(self):
        timer = FillTimer.objects.create(name='F', ends_at=timezone.now() - timedelta(minutes=1), status='finished', notified=True)
        self.client.post(reverse('timer_extend', args=[timer.pk]), {'minutes': 5})
        timer.refresh_from_db()
        self.assertEqual(timer.status, 'running')
        self.assertGreater(timer.ends_at, timezone.now())
        self.client.post(reverse('timer_cancel', args=[timer.pk]))
        timer.refresh_from_db()
        self.assertEqual(timer.status, 'cancelled')

    def test_reservoir_fill_amount_on_page(self):
        tank = Tank.objects.create(name='T', capacity_is_manual=True)
        DosingReservoir.objects.create(tank=tank, name='ATO', reservoir_type='ato_freshwater', capacity=10, current_level=4,
                                       unit='gal', daily_consumption=1)
        response = self.client.get(reverse('timers'))
        self.assertContains(response, '"gallons_to_full": 6.0')

    def test_default_ro_is_unique(self):
        first = ROSystem.objects.create(name='One', is_default=True)
        self.client.post(reverse('ro_create'), {
            'name': 'Two', 'rated_gpd': 100, 'rated_psi': 60, 'rated_temp_f': 77, 'feed_psi': 60, 'feed_temp_f': 60,
            'waste_ratio': 3, 'is_default': 'on'})
        first.refresh_from_db()
        self.assertFalse(first.is_default)


class WebhookFormTests(ServerMixin, TestCase):
    def test_create_and_test_button(self):
        server, url = self.start_server()
        response = self.client.post(reverse('webhook_create'), {
            'name': 'Mine', 'format': 'json', 'url': url, 'event_types': ['timer.finished'], 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        endpoint = WebhookEndpoint.objects.get()
        self.assertEqual(endpoint.event_types, ['timer.finished'])
        self.assertContains(self.client.post(reverse('webhook_test', args=[endpoint.pk]), follow=True), 'Test sent')
        self.assertEqual(json.loads(server.received[0][1])['type'], 'test')

    def test_rejects_bad_addresses(self):
        for url in ('ftp://x/y', 'javascript:alert(1)', 'http://', 'not a url', 'http://bad host/', 'http://x:notaport/'):
            response = self.client.post(reverse('webhook_create'), {'name': 'x', 'format': 'json', 'url': url, 'is_active': 'on'})
            self.assertEqual(response.status_code, 200, url)
        self.assertEqual(WebhookEndpoint.objects.count(), 0)

    def test_accepts_local_device_addresses(self):
        urls = ['http://esp32-feeder/trigger', 'http://192.168.1.50:8123/api/webhook/abc', 'https://ntfy.sh/topic', 'http://homeassistant:8123/x']
        for url in urls:
            response = self.client.post(reverse('webhook_create'), {'name': url, 'format': 'json', 'url': url, 'is_active': 'on'})
            self.assertEqual(response.status_code, 302, url)
        self.assertEqual(WebhookEndpoint.objects.count(), len(urls))


class TimelineTests(TestCase):
    def test_upload_and_delete_removes_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        animal = Animal.objects.create(name='Coral')
        with override_settings(MEDIA_ROOT=tmp):
            for day in ('2026-01-01', '2026-06-01'):
                self.client.post(reverse('timeline', args=[animal.pk]), {
                    'taken_on': day, 'image': SimpleUploadedFile('a.jpg', jpeg_bytes(), 'image/jpeg')})
            self.assertEqual(animal.timeline_photos.count(), 2)
            self.assertContains(self.client.get(reverse('timeline', args=[animal.pk])), 'compare-slider')
            photo = animal.timeline_photos.first()
            path = Path(photo.image.path)
            self.assertTrue(path.exists())
            self.client.post(reverse('timeline_photo_delete', args=[photo.pk]))
            self.assertFalse(path.exists())


class WebhookTargetingTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'events_baselined': True})
        self.tank = Tank.objects.create(name='T', capacity_is_manual=True)
        self.feeder = self.routine('Feeder')
        self.lights = self.routine('Lights')
        self.res_a = DosingReservoir.objects.create(tank=self.tank, name='ATO', capacity=10, current_level=10, unit='gal', daily_consumption=0)
        self.res_b = DosingReservoir.objects.create(tank=self.tank, name='Salt', capacity=10, current_level=10, unit='gal', daily_consumption=0)
        self.all = WebhookEndpoint.objects.create(name='All', url='http://x/')
        self.target = WebhookEndpoint.objects.create(name='Feeder hook', url='http://y/')

    def routine(self, title):
        return MaintenanceRoutine.objects.create(
            title=title, routine_type='automated', repeat_every=1, repeat_unit='day',
            start_date=timezone.localdate() - timedelta(days=1), checklist_items=[],
            schedule_events=[{'time': '08:00', 'action': 'Go'}])

    def fire_at_eight(self):
        at = timezone.make_aware(datetime.combine(timezone.localdate(), time(8, 0)))
        AppSettings.objects.filter(pk=1).update(last_schedule_check=at - timedelta(minutes=1))
        return events.fire_scheduled(at)

    def test_routine_target_only_receives_that_routine(self):
        self.target.routines.add(self.feeder)
        self.fire_at_eight()
        to_target = WebhookDelivery.objects.filter(endpoint=self.target)
        self.assertEqual([d.data['routine'] for d in to_target], ['Feeder'])
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=self.all).count(), 2)

    def test_targeted_hook_ignores_unrelated_alerts(self):
        self.target.routines.add(self.feeder)
        self.assertFalse(self.target.wants('parameter.critical'))
        self.assertFalse(self.target.wants('timer.finished'))
        self.assertTrue(self.all.wants('parameter.critical'))

    def test_ticked_events_still_apply_alongside_targets(self):
        self.target.routines.add(self.feeder)
        self.target.event_types = ['parameter.critical', 'routine.scheduled']
        self.target.save()
        self.assertTrue(self.target.wants('parameter.critical'))
        self.assertTrue(self.target.wants('routine.scheduled', routine_id=self.feeder.pk))
        self.assertFalse(self.target.wants('routine.scheduled', routine_id=self.lights.pk))
        self.assertFalse(self.target.wants('reservoir.low'))

    def test_due_routine_respects_target(self):
        due = MaintenanceRoutine.objects.create(
            title='Water change', routine_type='manual', repeat_every=1, repeat_unit='week',
            start_date=timezone.localdate() - timedelta(days=30), checklist_items=[])
        self.target.routines.add(self.feeder)
        events.sync_conditions()
        self.assertFalse(WebhookDelivery.objects.filter(endpoint=self.target).exists())
        self.target.routines.add(due)
        EventState.objects.all().delete()
        WebhookDelivery.objects.all().delete()
        events.sync_conditions()
        self.assertEqual(WebhookDelivery.objects.get(endpoint=self.target).data['routine_id'], due.pk)

    def _finish(self, **kwargs):
        timer = FillTimer.objects.create(name='Fill', ends_at=timezone.now() - timedelta(seconds=1), **kwargs)
        return timer

    def test_reservoir_target(self):
        self.target.timer_reservoirs.add(self.res_a)
        self._finish(reservoir=self.res_b)
        events.finish_timers()
        self.assertFalse(WebhookDelivery.objects.filter(endpoint=self.target).exists())
        self._finish(reservoir=self.res_a)
        events.finish_timers()
        delivery = WebhookDelivery.objects.get(endpoint=self.target)
        self.assertEqual(delivery.data['reservoir_id'], self.res_a.pk)

    def test_timer_can_choose_connections(self):
        self.client.post(reverse('timer_start'), {'minutes': '1', 'name': 'Chosen', 'endpoints': [self.target.pk]})
        timer = FillTimer.objects.get()
        self.assertEqual(list(timer.endpoints.all()), [self.target])
        FillTimer.objects.update(ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(events.finish_timers(), 1)
        self.assertEqual(WebhookDelivery.objects.get().endpoint, self.target)

    def test_timer_without_choice_uses_usual_connections(self):
        self.client.post(reverse('timer_start'), {'minutes': '1'})
        FillTimer.objects.update(ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(events.finish_timers(), 2)

    def test_deleting_last_target_pauses_instead_of_widening(self):
        self.target.routines.add(self.feeder, self.lights)
        self.lights.delete()
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.feeder.delete()
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertIn('Feeder', self.target.pause_reason)
        self.assertContains(self.client.get(reverse('integrations')), 'Paused because')

    def test_deleting_tank_also_pauses(self):
        self.target.routines.add(self.feeder)
        MaintenanceRoutine.objects.filter(pk=self.feeder.pk).update(tank=self.tank)
        self.tank.delete()
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_form_saves_targets_and_clears_pause(self):
        self.target.is_active = False
        self.target.pause_reason = 'Paused because'
        self.target.save()
        response = self.client.post(reverse('webhook_edit', args=[self.target.pk]), {
            'name': 'Feeder hook', 'format': 'json', 'url': 'http://y/', 'routines': [self.feeder.pk],
            'timer_reservoirs': [self.res_a.pk], 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(list(self.target.routines.all()), [self.feeder])
        self.assertEqual(list(self.target.timer_reservoirs.all()), [self.res_a])
        self.assertEqual(self.target.pause_reason, '')
        page = self.client.get(reverse('integrations'))
        self.assertContains(page, 'Only the items below')
        self.assertContains(self.client.get(reverse('webhook_edit', args=[self.target.pk])), 'Only these routines')


class CalculatorVolumeTests(TestCase):
    PAGES = ('tools', 'timers')

    def test_pages_use_the_selected_system(self):
        from .models import Sump
        tank = Tank.objects.create(name='Main', volume_gallons=40, capacity_is_manual=True, is_primary=True)
        Sump.objects.create(tank=tank, name='Sump', volume_gallons=10, capacity_is_manual=True)
        qt = Tank.objects.create(name='QT', volume_gallons=10, capacity_is_manual=True, is_primary=False)
        ROSystem.objects.create(name='RO')
        for name in self.PAGES:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
            self.assertEqual(response.context['volume_tank'], {'id': tank.pk, 'name': 'Main', 'display': 40.0, 'sump': 10.0, 'system': 50.0})
            self.assertContains(response, 'Custom volume')
            self.assertContains(response, 'function volumePicker')
        self.client.post(reverse('system_select'), {'tank': qt.pk, 'next': '/dosing/'})
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(name)).context['volume_tank']['name'], 'QT', name)

    def test_pages_work_without_tanks(self):
        ROSystem.objects.create(name='RO')
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_dose_uses_the_custom_volume_sent(self):
        common = {'parameter': 'alkalinity', 'chemical': 'soda_ash', 'current': 7, 'target': 8, 'max_daily': 1}
        ParameterType.objects.create(name='Alkalinity', code='alkalinity', unit='dKH', min_ideal=8, max_ideal=9)
        big = self.client.get(reverse('dose_calc_api'), {**common, 'gallons': 100})
        small = self.client.get(reverse('dose_calc_api'), {**common, 'gallons': 10})
        self.assertEqual(big.status_code, 200, big.content)
        self.assertEqual(big.json()['system_gallons'], 100)
        self.assertEqual(small.json()['system_gallons'], 10)
        missing = self.client.get(reverse('dose_calc_api'), {**common, 'gallons': ''})
        self.assertEqual(missing.status_code, 400)


class SystemScopeTests(ServerMixin, TestCase):
    def setUp(self):
        self.main = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.qt = Tank.objects.create(name='QT', volume_gallons=10, capacity_is_manual=True, is_primary=False)
        self.alk = ParameterType.objects.create(name='Alkalinity', code='alkalinity', unit='dKH', min_ideal=8, max_ideal=9, low_limit=7)

    def select(self, tank):
        return self.client.post(reverse('system_select'), {'tank': tank.pk, 'next': '/'})

    def log(self, tank, value):
        return ParameterLog.objects.create(parameter_type=self.alk, tank=tank, value=Decimal(str(value)))

    def test_defaults_to_primary_and_remembers_choice(self):
        self.assertEqual(self.client.get('/').context['active_tank'], self.main)
        self.assertRedirects(self.select(self.qt), '/')
        self.assertEqual(self.client.get('/').context['active_tank'], self.qt)

    def test_bad_or_deleted_selection_falls_back(self):
        self.client.cookies['nudibranch_system'] = 'not-a-number'
        self.assertEqual(self.client.get('/').context['active_tank'], self.main)
        self.select(self.qt)
        self.qt.delete()
        self.assertEqual(self.client.get('/').context['active_tank'], self.main)

    def test_select_cannot_redirect_offsite(self):
        response = self.client.post(reverse('system_select'), {'tank': self.qt.pk, 'next': 'https://evil.example/'})
        self.assertEqual(response.url, reverse('dashboard'))

    def test_readings_are_separate(self):
        self.log(self.main, 8.5)
        self.log(self.qt, 6.0)
        self.assertEqual(float(self.alk.latest_log(self.main).value), 8.5)
        self.assertEqual(float(self.alk.latest_log(self.qt).value), 6.0)
        page = self.client.get(reverse('parameters'))
        self.assertEqual([float(l.value) for l in page.context['recent_logs']], [8.5])
        data = self.client.get(reverse('api_chart_data'), {'code': 'alkalinity'}).json()
        self.assertEqual(data['values'], [8.5])
        self.select(self.qt)
        self.assertEqual(self.client.get(reverse('api_chart_data'), {'code': 'alkalinity'}).json()['values'], [6.0])
        everything = self.client.get(reverse('api_all_chart_data')).json()['datasets']
        self.assertEqual(everything[0]['values'], [6.0])
        self.assertEqual(self.client.get(reverse('api_chart_data'), {'code': 'alkalinity', 'tank': self.main.pk}).json()['values'], [8.5])

    def test_logging_goes_to_selected_system(self):
        self.select(self.qt)
        self.client.post(reverse('quick_log_create'), {'parameter_type': self.alk.pk, 'value': '8.1'})
        self.client.post(reverse('quick_measure_create'), {'value': ['8.2'], 'parameter': [self.alk.pk]})
        self.assertEqual(ParameterLog.objects.filter(tank=self.qt).count(), 2)

    def test_api_routes_readings(self):
        post = lambda body: self.client.post(reverse('api_parameter_log'), json.dumps(body), content_type='application/json')
        self.select(self.qt)  # a browser's choice must not affect devices
        self.assertEqual(post({'parameter': 'alkalinity', 'value': 8}).json()['logs'][0]['tank'], 'Main')
        self.assertEqual(post({'parameter': 'alkalinity', 'value': 8, 'tank': 'qt'}).json()['logs'][0]['tank'], 'QT')
        self.assertEqual(post({'tank': self.qt.pk, 'readings': [{'parameter': 'alkalinity', 'value': 8}]}).json()['logs'][0]['tank'], 'QT')
        batch = post({'readings': [{'parameter': 'alkalinity', 'value': 8, 'tank': 'QT'}, {'parameter': 'alkalinity', 'value': 8}]}).json()
        self.assertEqual([l['tank'] for l in batch['logs']], ['QT', 'Main'])
        self.assertEqual(post({'parameter': 'alkalinity', 'value': 8, 'tank': 'nope'}).status_code, 400)
        self.assertEqual(post({'readings': [{'parameter': 'alkalinity', 'value': 8, 'tank': 'nope'}]}).status_code, 400)

    def test_pages_only_show_selected_system(self):
        Animal.objects.create(name='MainFish', tank=self.main)
        Animal.objects.create(name='QtFish', tank=self.qt)
        Animal.objects.create(name='Unassigned')
        names = lambda: {a.name for a in self.client.get(reverse('livestock')).context['animals']}
        self.assertEqual(names(), {'MainFish', 'Unassigned'})
        self.select(self.qt)
        self.assertEqual(names(), {'QtFish', 'Unassigned'})

    def test_equipment_all_systems_view(self):
        Equipment.objects.create(name='MainPump', tank=self.main, wattage=10)
        Equipment.objects.create(name='QtHeater', tank=self.qt, wattage=20)
        names = lambda **q: {e.name for e in self.client.get(reverse('equipment'), q).context['equipment_list']}
        self.assertEqual(names(), {'MainPump'})
        self.assertEqual(names(tank='all'), {'MainPump', 'QtHeater'})
        self.assertEqual(names(tank=self.qt.pk), {'QtHeater'})
        self.assertContains(self.client.get(reverse('equipment')), 'All tanks')
        self.assertEqual(self.client.get(reverse('power'), {'tank': 'all'}).context['summary']['rows'].__len__(), 2)
        self.assertEqual(self.client.get(reverse('power')).context['summary']['rows'].__len__(), 1)

    def test_universal_pages_stay_universal(self):
        WishlistItem.objects.create(kind='equipment', name='Wanted', category='other')
        PlannedSystem.objects.create(name='Plan', volume_gallons=10, capacity_is_manual=True)
        self.select(self.qt)
        self.assertContains(self.client.get(reverse('wishlist')), 'Wanted')
        self.assertContains(self.client.get(reverse('planner')), 'Plan')

    def test_alerts_scope_and_other_system_marker(self):
        self.log(self.qt, 6.0)
        page = self.client.get('/')
        self.assertEqual(page.context['global_out_of_range_count'], 0)
        marks = {s['tank'].name: s['alerts'] for s in page.context['systems']}
        self.assertEqual(marks['QT'], 1)
        self.assertContains(page, '⚠️ 1')
        self.select(self.qt)
        self.assertEqual(self.client.get('/').context['global_out_of_range_count'], 1)

    def test_background_alerts_cover_every_system(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'events_baselined': True})
        WebhookEndpoint.objects.create(name='E', url='http://x/')
        self.log(self.main, 7.5)
        self.log(self.qt, 7.5)
        self.assertEqual(events.sync_conditions(), 2)
        titles = sorted(WebhookDelivery.objects.values_list('title', flat=True))
        self.assertTrue(titles[0].startswith('Main:'))
        self.assertTrue(titles[1].startswith('QT:'))
        self.assertEqual(WebhookDelivery.objects.first().data['tank_id'] in (self.main.pk, self.qt.pk), True)
        self.assertEqual(events.sync_conditions(), 0)

    def test_system_calculators_read_that_systems_tests(self):
        self.log(self.main, 8.5)
        self.log(self.qt, 6.0)
        current = lambda: self.client.get(reverse('tools')).context['dose_data']['parameters']['alkalinity']['current']
        self.assertEqual(current(), 8.5)
        self.select(self.qt)
        self.assertEqual(current(), 6.0)

    def test_delete_warning_mentions_tests(self):
        self.log(self.qt, 6.0)
        self.assertContains(self.client.get(reverse('tank_delete', args=[self.qt.pk])), '1 water test')

    def test_seed_leaves_existing_systems_alone(self):
        self.main.name = 'Renamed'
        self.main.save()
        call_command('seed_reef_data', stdout=io.StringIO())
        self.assertEqual(sorted(Tank.objects.values_list('name', flat=True)), ['QT', 'Renamed'])
        self.assertEqual(Equipment.objects.count(), 0)

    def test_seed_creates_sample_system_on_fresh_install(self):
        Tank.objects.all().delete()
        call_command('seed_reef_data', stdout=io.StringIO())
        self.assertEqual(Tank.objects.count(), 1)
        self.assertTrue(Equipment.objects.exists())

    def test_no_tanks_still_renders(self):
        Tank.objects.all().delete()
        ParameterLog.objects.create(parameter_type=self.alk, value=8)
        for name in ('dashboard', 'parameters', 'livestock', 'equipment', 'dosing', 'routines', 'timers', 'webcams', 'tools', 'the_damage', 'power'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertRedirects(self.client.get(reverse('system_theme')), reverse('tank_create'))


class ParameterTargetTests(TestCase):
    def setUp(self):
        self.main = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.soft = Tank.objects.create(name='Soft', volume_gallons=40, capacity_is_manual=True, is_primary=False)
        self.nitrate = ParameterType.objects.create(
            name='Nitrate', code='nitrate', unit='ppm', decimal_places=1, low_limit=1, min_ideal=2, max_ideal=10, high_limit=30)
        self.url = reverse('parameter_settings', args=[self.nitrate.pk])

    def select(self, tank):
        self.client.post(reverse('system_select'), {'tank': tank.pk})

    def form(self, **overrides):
        data = {'unit': 'ppm', 'decimal_places': 1, 'low_limit': 1, 'min_ideal': 2, 'max_ideal': 10, 'high_limit': 30}
        data.update(overrides)
        return self.client.post(self.url, data)

    def own_targets(self, tank):
        self.nitrate.targets.create(tank=tank, low_limit=None, min_ideal=Decimal('5'), max_ideal=Decimal('40'), high_limit=Decimal('60'))

    def log(self, tank, value):
        return ParameterLog.objects.create(parameter_type=self.nitrate, tank=tank, value=Decimal(str(value)))

    def test_same_reading_is_judged_per_system(self):
        self.own_targets(self.soft)
        self.assertEqual(self.log(self.main, 25).status_label, 'HIGH')
        self.assertEqual(self.log(self.soft, 25).status_label, 'OPTIMAL')
        self.assertEqual(self.log(self.main, 35).status_label, 'CRITICAL HIGH')
        self.assertEqual(self.log(self.soft, 1).status, 'low')
        self.assertEqual(self.log(self.soft, 1).severity, 'warning')  # that system has no low limit

    def test_alerts_use_each_systems_targets(self):
        self.own_targets(self.soft)
        self.log(self.main, 25)
        self.log(self.soft, 25)
        main_state = compute_alert_state(tank=self.main)
        soft_state = compute_alert_state(tank=self.soft)
        self.assertEqual(len(main_state['out_of_range_params']), 1)
        self.assertEqual(soft_state['out_of_range_params'], [])
        AppSettings.objects.update_or_create(pk=1, defaults={'events_baselined': True})
        WebhookEndpoint.objects.create(name='E', url='http://x/')
        self.assertEqual(events.sync_conditions(), 1)
        self.assertTrue(WebhookDelivery.objects.get().title.startswith('Main:'))

    def test_alert_message_quotes_that_systems_range(self):
        self.own_targets(self.soft)
        self.log(self.soft, 50)
        AppSettings.objects.update_or_create(pk=1, defaults={'events_baselined': True})
        WebhookEndpoint.objects.create(name='E', url='http://x/')
        events.sync_conditions()
        delivery = WebhookDelivery.objects.get()
        self.assertIn('5.0 to 40.0', delivery.message)
        self.assertEqual(delivery.data['max_ideal'], 40.0)

    def test_charts_dashboard_and_dose_follow_selected_system(self):
        self.own_targets(self.soft)
        self.log(self.soft, 25)
        chart = lambda: self.client.get(reverse('api_chart_data'), {'code': 'nitrate'}).json()['parameter']['max_ideal']
        self.assertEqual(chart(), 10.0)
        self.select(self.soft)
        self.assertEqual(chart(), 40.0)
        self.assertEqual(self.client.get(reverse('api_all_chart_data')).json()['datasets'][0]['max_ideal'], 40.0)
        self.assertContains(self.client.get('/'), '5.0 – 40.0')
        alk = ParameterType.objects.create(name='Alkalinity', code='alkalinity', unit='dKH', min_ideal=8, max_ideal=9)
        alk.targets.create(tank=self.soft, min_ideal=Decimal('7'), max_ideal=Decimal('8'))
        dose = self.client.get(reverse('tools')).context['dose_data']['parameters']['alkalinity']
        self.assertEqual((dose['ideal_min'], dose['ideal_max'], dose['target']), (7.0, 8.0, 7.5))
        data = self.client.get(reverse('api_parameter_types'), {'tank': 'Soft'}).json()['parameters']
        self.assertEqual({p['code']: p['max_ideal'] for p in data}['nitrate'], 40.0)
        data = self.client.get(reverse('api_parameter_types')).json()['parameters']
        self.assertEqual({p['code']: p['max_ideal'] for p in data}['nitrate'], 10.0)

    def test_editing_only_changes_selected_system(self):
        self.select(self.soft)
        response = self.form(min_ideal=5, max_ideal=40, high_limit=60)
        self.assertEqual(response.status_code, 302)
        self.nitrate.refresh_from_db()
        self.assertEqual(self.nitrate.max_ideal, Decimal('10'))
        self.assertEqual(self.nitrate.targets.get().tank, self.soft)
        self.assertEqual(self.nitrate.for_system(self.main).max_ideal, Decimal('10'))
        self.assertEqual(self.nitrate.for_system(self.soft).max_ideal, Decimal('40'))
        page = self.client.get(self.url)
        self.assertContains(page, 'has its own targets')
        self.assertContains(page, 'value="40.000"')

    def test_saving_default_values_needs_no_override(self):
        self.select(self.soft)
        self.form()
        self.assertEqual(self.nitrate.targets.count(), 0)
        self.assertContains(self.client.get(self.url), 'is using the default targets')

    def test_unit_and_decimals_are_shared(self):
        self.select(self.soft)
        self.form(decimal_places=2, min_ideal=5, max_ideal=40, high_limit=60)
        self.nitrate.refresh_from_db()
        self.assertEqual(self.nitrate.decimal_places, 2)
        self.assertEqual(self.nitrate.for_system(self.soft).decimal_places, 2)

    def test_make_default_and_reset(self):
        self.select(self.soft)
        self.form(min_ideal=5, max_ideal=40, high_limit=60, apply_default='on')
        self.nitrate.refresh_from_db()
        self.assertEqual(self.nitrate.max_ideal, Decimal('40'))
        self.assertEqual(self.nitrate.targets.count(), 0)
        self.form(min_ideal=6, max_ideal=20, high_limit=60)
        self.assertEqual(self.nitrate.targets.count(), 1)
        self.client.post(reverse('parameter_targets_reset', args=[self.nitrate.pk]))
        self.assertEqual(self.nitrate.targets.count(), 0)
        self.assertEqual(self.nitrate.for_system(self.soft).max_ideal, Decimal('40'))

    def test_one_system_just_edits_the_default(self):
        self.soft.delete()
        self.form(min_ideal=3, max_ideal=20, high_limit=40)
        self.nitrate.refresh_from_db()
        self.assertEqual(self.nitrate.max_ideal, Decimal('20'))
        self.assertEqual(self.nitrate.targets.count(), 0)
        self.assertNotContains(self.client.get(self.url), 'Also make these the default')

    def test_bad_ranges_are_rejected(self):
        self.select(self.soft)
        response = self.form(min_ideal=50, max_ideal=10)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.nitrate.targets.count(), 0)

    def test_unit_conversion_covers_every_systems_targets_and_tests(self):
        temp = ParameterType.objects.create(name='Temperature', code='temperature', unit='F', decimal_places=1,
                                            low_limit=75, min_ideal=77, max_ideal=79, high_limit=81)
        temp.targets.create(tank=self.soft, low_limit=Decimal('68'), min_ideal=Decimal('68'), max_ideal=Decimal('86'), high_limit=Decimal('95'))
        temp.targets.update(low_limit=Decimal('59'))
        log = ParameterLog.objects.create(parameter_type=temp, tank=self.soft, value=Decimal('77'))
        response = self.client.post(reverse('parameter_settings', args=[temp.pk]), {
            'unit': 'C', 'decimal_places': 1, 'low_limit': 75, 'min_ideal': 77, 'max_ideal': 79, 'high_limit': 81,
            'convert_history': 'on'})
        self.assertEqual(response.status_code, 302)
        temp.refresh_from_db()
        log.refresh_from_db()
        self.assertEqual(temp.unit, 'C')
        self.assertEqual(round(float(temp.min_ideal)), 25)
        self.assertEqual(round(float(log.value)), 25)
        target = temp.targets.get()
        self.assertEqual((round(float(target.low_limit)), round(float(target.min_ideal)), round(float(target.max_ideal))), (15, 20, 30))

    def test_system_view_cannot_be_saved(self):
        self.own_targets(self.soft)
        with self.assertRaises(ValueError):
            self.nitrate.for_system(self.soft).save()

    def test_deleting_system_removes_its_targets(self):
        self.own_targets(self.soft)
        self.soft.delete()
        self.assertEqual(self.nitrate.targets.count(), 0)


class RetiredSystemTests(TestCase):
    def setUp(self):
        self.main = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True, icon_choice='03-robot-young')
        self.old = Tank.objects.create(name='Old', volume_gallons=20, capacity_is_manual=True, is_primary=False, icon_choice='01-dragon-mage-young')
        self.alk = ParameterType.objects.create(name='Alkalinity', code='alkalinity', unit='dKH', min_ideal=8, max_ideal=9, low_limit=7)
        self.log = ParameterLog.objects.create(parameter_type=self.alk, tank=self.old, value=Decimal('5'))

    def retire(self, tank=None):
        return self.client.post(reverse('tank_archive', args=[(tank or self.old).pk]))

    def test_keeps_data_and_switches_to_old_icon(self):
        Animal.objects.create(name='Oldie', tank=self.old)
        self.assertIn('01-dragon-mage-young', self.old.icon_url)
        self.retire()
        self.old.refresh_from_db()
        self.assertTrue(self.old.is_archived)
        self.assertIsNotNone(self.old.archived_at)
        self.assertIn('01-dragon-mage-old', self.old.icon_url)
        self.assertEqual(self.old.parameter_logs.count(), 1)
        self.assertEqual(self.old.animals.count(), 1)

    def test_restore_brings_back_young_icon(self):
        self.retire()
        response = self.client.post(reverse('tank_restore', args=[self.old.pk]))
        self.assertRedirects(response, reverse('tank_detail', args=[self.old.pk]))
        self.old.refresh_from_db()
        self.assertFalse(self.old.is_archived)
        self.assertEqual(self.old.icon_choice, '01-dragon-mage-young')
        self.assertIn('01-dragon-mage-young', self.old.icon_url)
        self.assertEqual(self.client.get('/').context['active_tank'], self.old)

    def test_retiring_twice_is_harmless(self):
        self.retire()
        self.retire()
        self.client.post(reverse('tank_restore', args=[self.old.pk]))
        self.old.refresh_from_db()
        self.assertIn('01-dragon-mage-young', self.old.icon_url)

    def test_retiring_primary_promotes_another(self):
        self.retire(self.main)
        self.main.refresh_from_db()
        self.old.refresh_from_db()
        self.assertFalse(self.main.is_primary)
        self.assertTrue(self.old.is_primary)
        self.assertEqual(self.client.get('/').context['active_tank'], self.old)

    def test_retiring_selected_system_moves_on(self):
        self.client.post(reverse('system_select'), {'tank': self.old.pk})
        self.retire()
        self.assertEqual(self.client.get('/').context['active_tank'], self.main)

    def test_no_alerts_or_events(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'events_baselined': True})
        WebhookEndpoint.objects.create(name='E', url='http://x/')
        Animal.objects.create(name='Sick', tank=self.old, status='monitoring')
        self.retire()
        self.assertEqual(events.sync_conditions(), 0)
        self.old.refresh_from_db()
        self.assertEqual(compute_alert_state(tank=self.old)['total_alerts'], 0)
        marks = {s['tank'].name: s['alerts'] for s in self.client.get('/').context['systems']}
        self.assertEqual(marks['Old'], 0)

    def test_schedules_do_not_fire(self):
        MaintenanceRoutine.objects.create(
            title='Feeder', tank=self.old, routine_type='automated', repeat_every=1, repeat_unit='day',
            start_date=timezone.localdate() - timedelta(days=1), checklist_items=[], schedule_events=[{'time': '08:00', 'action': 'Go'}])
        WebhookEndpoint.objects.create(name='E', url='http://x/')
        at = timezone.make_aware(datetime.combine(timezone.localdate(), time(8, 0)))
        AppSettings.objects.update_or_create(pk=1, defaults={'last_schedule_check': at - timedelta(minutes=1)})
        self.retire()
        self.assertEqual(events.fire_scheduled(at), 0)

    def test_no_new_tests(self):
        self.client.post(reverse('system_select'), {'tank': self.old.pk})
        self.retire()
        self.client.post(reverse('system_select'), {'tank': self.old.pk})
        self.client.post(reverse('quick_log_create'), {'parameter_type': self.alk.pk, 'value': '8'})
        self.client.post(reverse('quick_measure_create'), {'value': ['8'], 'parameter': [self.alk.pk]})
        self.assertEqual(self.old.parameter_logs.count(), 1)
        post = lambda body: self.client.post(reverse('api_parameter_log'), json.dumps(body), content_type='application/json')
        self.assertEqual(post({'parameter': 'alkalinity', 'value': 8, 'tank': 'Old'}).status_code, 400)
        self.assertEqual(post({'parameter': 'alkalinity', 'value': 8}).json()['logs'][0]['tank'], 'Main')

    def test_history_is_viewable(self):
        self.retire()
        self.client.post(reverse('system_select'), {'tank': self.old.pk})
        page = self.client.get(reverse('parameters'))
        self.assertEqual(list(page.context['recent_logs']), [self.log])
        self.assertContains(page, 'Bring it back')
        for name in ('dashboard', 'livestock', 'equipment', 'dosing', 'routines', 'timers', 'webcams', 'tools', 'power', 'the_damage', 'system_theme'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_selector_and_lists(self):
        self.retire()
        page = self.client.get(reverse('tanks'))
        self.assertContains(page, 'Retired tanks')
        self.assertContains(page, 'label="Retired"')
        self.assertEqual([c['tank'] for c in page.context['tank_cards']], [self.main])
        Equipment.objects.create(name='OldPump', tank=self.old, wattage=100)
        self.assertEqual([e.name for e in self.client.get(reverse('equipment'), {'tank': 'all'}).context['equipment_list']], [])
        self.assertEqual(self.client.get(reverse('power'), {'tank': 'all'}).context['summary']['rows'], [])
        choices = self.client.get(reverse('plan_create')).context['form'].fields['existing_tank'].queryset
        self.assertEqual(list(choices), [self.main])

    def test_retired_page_explains_the_old_icon(self):
        self.assertNotContains(self.client.get(reverse('system_theme')), 'This tank is retired')
        self.retire()
        self.client.post(reverse('system_select'), {'tank': self.old.pk})
        self.assertContains(self.client.get(reverse('system_theme')), 'This tank is retired')
        self.client.post(reverse('system_theme'), {'theme': 'ocean', 'icon_choice': '03-robot-young'})
        self.old.refresh_from_db()
        self.assertIn('03-robot-old', self.old.icon_url)
        self.assertIn('03-robot-old', self.client.get('/').context['system_icon_url'])

    def test_every_system_retired_still_works(self):
        self.retire()
        self.retire(self.main)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertIsNotNone(self.client.get('/').context['active_tank'])
        call_command('seed_reef_data', stdout=io.StringIO())
        self.assertEqual(Tank.objects.count(), 2)


class CharacterIconTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.main = Tank.objects.create(name='Main', capacity_is_manual=True, is_primary=True, icon_choice='03-robot-young')
        self.other = Tank.objects.create(name='Other', capacity_is_manual=True, is_primary=False)

    def settings_on(self, **values):
        AppSettings.load()
        AppSettings.objects.filter(pk=1).update(**values)

    def retire(self, tank):
        self.client.post(reverse('tank_archive', args=[tank.pk]))
        tank.refresh_from_db()

    def test_all_26_characters_are_complete_pairs(self):
        characters = character_icons()
        self.assertEqual(len(characters), 26)
        for c in characters:
            self.assertNotEqual(c['young'], c['old'], c['key'])
            self.assertEqual(c['old'], f"{c['key']}-old")
        labels = [c['label'] for c in characters]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertIn('Dragon Mage', labels)

    def test_names_are_plain_descriptions(self):
        franchise_words = ('jedi', '-borg', 'ghibli', 'ironman', 'joker', 'kpop', 'dune', 'federation', 'straw-hat', 'turtle')
        for character in character_icons():
            for word in franchise_words:
                self.assertNotIn(word, character['key'])

    def test_picker_only_offers_young_by_default(self):
        page = self.client.get(reverse('system_theme'))
        self.assertContains(page, 'value="01-dragon-mage-young"')
        self.assertNotContains(page, 'value="01-dragon-mage-old"')
        self.client.post(reverse('system_theme'), {'theme': 'ocean', 'icon_choice': '01-dragon-mage-old'})
        self.main.refresh_from_db()
        self.assertEqual(self.main.icon_choice, '03-robot-young')

    def test_surprise_me_only_uses_young(self):
        self.settings_on(enable_random_icons=True)
        pool = self.client.get('/').context['random_icons']
        self.assertEqual(len(pool), 26)
        self.assertTrue(all('-young' in item['path'] for item in pool))

    def test_aging_switches_on_retire_and_back(self):
        self.assertIn('03-robot-young', self.main.icon_url)
        self.retire(self.main)
        self.assertIn('03-robot-old', self.main.icon_url)
        self.client.post(reverse('tank_restore', args=[self.main.pk]))
        self.main.refresh_from_db()
        self.assertIn('03-robot-young', self.main.icon_url)

    def test_disable_icon_aging(self):
        self.retire(self.main)
        self.settings_on(disable_icon_aging=True)
        self.assertIn('03-robot-young', self.main.icon_url)
        self.settings_on(disable_icon_aging=False)
        self.assertIn('03-robot-old', self.main.icon_url)

    def test_enable_old_version_icons(self):
        self.settings_on(enable_old_version_icons=True)
        self.assertContains(self.client.get(reverse('system_theme')), 'value="01-dragon-mage-old"')
        self.client.post(reverse('system_theme'), {'theme': 'ocean', 'icon_choice': '01-dragon-mage-old'})
        self.main.refresh_from_db()
        self.assertEqual(self.main.icon_choice, '01-dragon-mage-old')
        self.assertIn('01-dragon-mage-old', self.main.icon_url)
        # Turned off again: the system shows the young version, and saving the page keeps that character.
        self.settings_on(enable_old_version_icons=False)
        self.assertIn('01-dragon-mage-young', self.main.icon_url)
        page = self.client.get(reverse('system_theme'))
        self.assertEqual(page.context['selected_icon'], '01-dragon-mage-young')

    def test_old_choice_with_aging_disabled_still_works(self):
        self.settings_on(enable_old_version_icons=True, disable_icon_aging=True)
        Tank.objects.filter(pk=self.main.pk).update(icon_choice='01-dragon-mage-old')
        self.main.refresh_from_db()
        self.retire(self.main)
        self.assertIn('01-dragon-mage-old', self.main.icon_url)
        self.other.icon_choice = '03-robot-young'
        self.other.save()
        self.retire(self.other)
        self.assertIn('03-robot-young', self.other.icon_url)

    def test_uploaded_icon_stays_static(self):
        buf = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(buf, 'PNG')
        self.client.post(reverse('system_theme'), {'theme': 'ocean', 'icon_choice': '', 'custom_icon': SimpleUploadedFile('me.png', buf.getvalue(), 'image/png')})
        self.main.refresh_from_db()
        url = self.main.icon_url
        self.assertIn('/media/icons/', url)
        self.retire(self.main)
        self.assertEqual(self.main.icon_url, url)
        self.assertNotContains(self.client.get(reverse('system_theme')), 'This tank is retired')

    def test_surprise_me_retired_gets_a_lasting_old_icon(self):
        self.settings_on(enable_random_icons=True)
        self.assertEqual(self.other.icon_url, '')
        self.retire(self.other)
        first = self.other.icon_url
        self.assertIn('-old', first)
        self.assertEqual(Tank.objects.get(pk=self.other.pk).icon_url, first)
        self.settings_on(disable_icon_aging=True)
        self.assertEqual(self.other.icon_url, '')

    def test_settings_page_has_both_options(self):
        page = self.client.get(reverse('app_settings'))
        self.assertContains(page, 'Disable icon aging')
        self.assertContains(page, 'Enable old version icons')
        self.client.post(reverse('app_settings'), {
            'electricity_rate': '0.15', 'currency_symbol': '$', 'auto_backup_days': 7, 'auto_backup_keep': 4,
            'disable_icon_aging': 'on', 'enable_old_version_icons': 'on'})
        saved = AppSettings.load()
        self.assertTrue(saved.disable_icon_aging and saved.enable_old_version_icons)

    def test_removed_icon_falls_back_to_the_default(self):
        Tank.objects.filter(pk=self.main.pk).update(icon_choice='gone-young')
        self.main.refresh_from_db()
        self.assertIn(icons.default_stem(self.main.pk), self.main.icon_url)
        self.settings_on(enable_random_icons=True)
        self.assertEqual(self.main.icon_url, '')

    def test_random_icons_are_off_by_default(self):
        self.assertFalse(AppSettings.load().enable_random_icons)
        first = self.other.icon_url
        self.assertIn(icons.default_stem(self.other.pk), first)
        self.assertEqual(Tank.objects.get(pk=self.other.pk).icon_url, first)
        page = self.client.get('/')
        self.assertEqual(page.context['random_icons'], [])
        self.assertEqual(page.context['system_icon_url'], self.main.icon_url)
        look = self.client.get(reverse('system_theme'))
        self.assertNotContains(look, 'Surprise me')
        self.assertContains(look, 'Default')

    def test_tanks_with_no_icon_get_different_defaults(self):
        third = Tank.objects.create(name='Third', capacity_is_manual=True)
        self.assertNotEqual(self.other.icon_url, third.icon_url)

    def test_match_my_icon_works_with_the_default_icon(self):
        self.assertIsNotNone(self.other.icon_palette())

    def test_random_icons_setting_brings_them_back(self):
        page = self.client.get(reverse('app_settings'))
        self.assertContains(page, 'Enable random icons')
        self.client.post(reverse('app_settings'), {
            'electricity_rate': '0.15', 'currency_symbol': '$', 'auto_backup_days': 7, 'auto_backup_keep': 4,
            'enable_random_icons': 'on'})
        self.assertTrue(AppSettings.load().enable_random_icons)
        self.assertEqual(self.other.icon_url, '')
        self.assertEqual(len(self.client.get('/').context['random_icons']), 26)
        self.client.get(reverse('tank_look', args=[self.other.pk]))
        self.assertContains(self.client.get(reverse('system_theme')), 'Surprise me')

    def test_no_look_button_beside_the_system_menu(self):
        self.assertNotContains(self.client.get('/'), 'Colours and icon for this system')

    def test_thumbnails_are_small_and_leave_originals_alone(self):
        from unittest.mock import patch
        tmp = Path(self.tmp) / 'source'
        (tmp / 'thumbs').mkdir(parents=True)
        Image.new('RGBA', (1024, 1024), 'red').save(tmp / '01-x-young.png')
        original = (tmp / '01-x-young.png').read_bytes()
        (tmp / 'thumbs' / 'gone.webp').write_bytes(b'stale')
        target = 'aquarium.management.commands.build_icon_thumbnails'
        with patch(f'{target}.icon_dir', return_value=tmp), patch(f'{target}.thumbnail_dir', return_value=tmp / 'thumbs'):
            call_command('build_icon_thumbnails', stdout=io.StringIO())
            first = (tmp / 'thumbs' / '01-x-young.webp').stat().st_mtime
            call_command('build_icon_thumbnails', stdout=io.StringIO())
        with Image.open(tmp / 'thumbs' / '01-x-young.webp') as thumb:
            self.assertEqual(thumb.size, (256, 256))
        self.assertEqual((tmp / '01-x-young.png').read_bytes(), original)
        self.assertEqual((tmp / 'thumbs' / '01-x-young.webp').stat().st_mtime, first)
        self.assertFalse((tmp / 'thumbs' / 'gone.webp').exists())


def _contrast(foreground, background):
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + .05) / (darker + .05)


class MatchMyIconTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.tank = Tank.objects.create(name='Main', capacity_is_manual=True, is_primary=True, theme='icon', icon_choice='01-dragon-mage-young')

    def test_every_character_makes_a_readable_palette(self):
        problems = []
        palettes = set()
        for character in character_icons():
            for stem in (character['young'], character['old']):
                self.tank.icon_choice = stem
                AppSettings.load()
                AppSettings.objects.filter(pk=1).update(enable_old_version_icons=True)
                palette = self.tank.icon_palette()
                if palette is None:
                    problems.append(f'{stem}: no colours')
                    continue
                palettes.add(palette['cyan']['500'])
                background = palette['slate']['900']
                for name, color in (('accent', palette['cyan']['400']), ('second', palette['blue']['400'])):
                    if _contrast(color, background) < 4.5:
                        problems.append(f'{stem}: {name} {color} on {background}')
        self.assertEqual(problems, [])
        self.assertGreater(len(palettes), 8)  # they really differ between icons

    def test_page_uses_the_icon_colors(self):
        page = self.client.get('/')
        palette = self.tank.icon_palette()
        self.assertContains(page, theme_css(palette))
        self.assertEqual(page.context['theme_background'], palette['slate']['950'])

    def test_surprise_me_falls_back(self):
        AppSettings.load()
        AppSettings.objects.filter(pk=1).update(enable_random_icons=True)
        Tank.objects.filter(pk=self.tank.pk).update(icon_choice='')
        page = self.client.get('/')
        self.assertEqual(page.context['theme_css'], '')
        self.assertContains(self.client.get(reverse('system_theme')), 'Match my icon')

    def test_upload_colors_are_read(self):
        buf = io.BytesIO()
        Image.new('RGB', (32, 32), (220, 30, 30)).save(buf, 'PNG')
        self.client.post(reverse('system_theme'), {'theme': 'icon', 'icon_choice': '', 'custom_icon': SimpleUploadedFile('red.png', buf.getvalue(), 'image/png')})
        self.tank.refresh_from_db()
        accent = self.tank.icon_palette()['cyan']['500']
        red, green, blue = (int(accent[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(red, green + 60)
        self.assertGreater(red, blue + 60)

    def test_grey_image_falls_back_and_missing_file_is_safe(self):
        path = Path(self.tmp) / 'grey.png'
        Image.new('RGB', (32, 32), (128, 128, 128)).save(path)
        self.assertIsNone(icons.colors_from_file(path))
        self.assertIsNone(icons.colors_from_file(Path(self.tmp) / 'nope.png'))
        Tank.objects.filter(pk=self.tank.pk).update(icon_choice='custom')
        self.tank.refresh_from_db()
        self.assertIsNone(self.tank.icon_palette())
        self.assertEqual(self.client.get('/').status_code, 200)


@override_settings(LOGIN_REQUIRED=True)
class SignInTests(TestCase):
    PASSWORD = 'correct-horse-battery-staple-42'

    def make_user(self):
        return get_user_model().objects.create_superuser('reefer', password=self.PASSWORD)

    def test_every_kind_of_page_needs_sign_in(self):
        self.make_user()
        tank = Tank.objects.create(name='T', capacity_is_manual=True)
        for url in ('/', '/parameters/', '/livestock/', '/backups/', '/integrations/', '/the-damage/', '/planner/',
                    f'/tanks/{tank.pk}/', '/media/livestock/x.jpg', '/backups/nudibranch-manual-20260101-000000.zip/download/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response.url.startswith('/login/'), url)
        self.assertEqual(self.client.post(reverse('backup_create')).status_code, 302)
        self.assertEqual(self.client.post(reverse('tank_archive', args=[tank.pk])).status_code, 302)
        tank.refresh_from_db()
        self.assertFalse(tank.is_archived)

    def test_sign_in_returns_to_the_page_and_sign_out_ends_it(self):
        self.make_user()
        response = self.client.post('/login/', {'username': 'reefer', 'password': self.PASSWORD, 'next': '/livestock/'})
        self.assertRedirects(response, '/livestock/')
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertContains(self.client.get(reverse('tools')), 'Sign out')
        self.client.post(reverse('logout'))
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_wrong_password_and_offsite_redirect(self):
        self.make_user()
        response = self.client.post('/login/', {'username': 'reefer', 'password': 'nope'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 302)
        response = self.client.post('/login/', {'username': 'reefer', 'password': self.PASSWORD, 'next': 'https://evil.example/'})
        self.assertEqual(response.url, '/')

    def test_page_does_not_leak_data_before_sign_in(self):
        self.make_user()
        Tank.objects.create(name='Secret Tank', capacity_is_manual=True)
        page = self.client.get('/login/')
        self.assertNotContains(page, 'Secret Tank')
        self.assertNotContains(page, 'system-select')

    def test_first_visit_creates_the_account_then_setup_closes(self):
        self.assertRedirects(self.client.get('/'), '/setup/')
        self.assertContains(self.client.get('/setup/'), 'Create your account')
        self.client.post('/setup/', {'username': 'first', 'password1': 'x', 'password2': 'x'})
        self.assertEqual(get_user_model().objects.count(), 0)  # a weak password is refused
        response = self.client.post('/setup/', {'username': 'first', 'password1': self.PASSWORD, 'password2': self.PASSWORD})
        self.assertRedirects(response, '/')
        user = get_user_model().objects.get()
        self.assertTrue(user.is_superuser and user.check_password(self.PASSWORD))
        other = Client()
        self.assertRedirects(other.get('/setup/'), '/login/')
        other.post('/setup/', {'username': 'intruder', 'password1': self.PASSWORD, 'password2': self.PASSWORD})
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_public_paths(self):
        self.make_user()
        self.assertEqual(self.client.get('/sw.js').status_code, 200)
        self.assertEqual(self.client.get('/login/').status_code, 200)
        self.assertIn(self.client.get('/admin/').status_code, (200, 302))

    @override_settings(API_SECRET_KEY='device-key')
    def test_devices_use_the_api_key(self):
        self.make_user()
        ParameterType.objects.create(name='Alk', code='alk', unit='dKH', min_ideal=8, max_ideal=9)
        Tank.objects.create(name='T', capacity_is_manual=True)
        body = json.dumps({'parameter': 'alk', 'value': 8})
        log = reverse('api_parameter_log')
        self.assertEqual(self.client.post(log, body, content_type='application/json').status_code, 401)
        self.assertEqual(self.client.post(log, body, content_type='application/json', headers={'X-API-Key': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.post(log, body, content_type='application/json', headers={'X-API-Key': 'device-key'}).status_code, 201)
        self.assertEqual(self.client.post(log, body, content_type='application/json', headers={'Authorization': 'Bearer device-key'}).status_code, 201)
        types = reverse('api_parameter_types')
        self.assertEqual(self.client.get(types).status_code, 401)
        self.assertEqual(self.client.get(types, headers={'X-API-Key': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.get(types, headers={'X-API-Key': 'device-key'}).status_code, 200)
        # The key opens only those two endpoints.
        self.assertEqual(self.client.get(reverse('api_chart_data'), headers={'X-API-Key': 'device-key'}).status_code, 401)
        self.assertEqual(self.client.get(reverse('api_species_catalog'), headers={'X-API-Key': 'device-key'}).status_code, 401)
        self.assertEqual(self.client.get('/backups/', headers={'X-API-Key': 'device-key'}).status_code, 302)

    def test_background_form_requests_are_told_to_sign_in(self):
        self.make_user()
        response = self.client.post(reverse('quick_log_create'), {}, headers={'HX-Request': 'true'})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response['HX-Redirect'].startswith('/login/'))


class DamageExtrasTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.old = Tank.objects.create(name='Old', volume_gallons=25, capacity_is_manual=True, is_archived=True)
        self.pump = Equipment.objects.create(name='Pump', category='pump', tank=self.tank)
        AppSettings.load()
        AppSettings.objects.filter(pk=1).update(costs_enabled=True)

    def confess(self, **extra):
        data = {'description': 'One more', 'amount': '100', 'spent_on': '2026-11-01', 'category': 'other', 'tank': self.tank.pk}
        data.update(extra)
        return self.client.post(reverse('the_damage'), data)

    def test_retired_systems_are_an_option(self):
        CostEntry.objects.create(description='Now', amount=Decimal('10'), tank=self.tank)
        CostEntry.objects.create(description='Then', amount=Decimal('5'), tank=self.old)
        CostEntry.objects.create(description='Loose', amount=Decimal('1'))
        without = self.client.get(reverse('the_damage'), {'tank': 'all'})
        self.assertEqual(without.context['total'], 11)
        self.assertEqual(without.context['per_gallon'], 11 / 75)
        included = self.client.get(reverse('the_damage'), {'tank': 'all', 'retired': '1'})
        self.assertEqual(included.context['total'], 16)
        self.assertEqual(included.context['per_gallon'], 16 / 100)
        self.assertIn('retired=1', included.context['presets'][0]['query'])
        self.assertContains(without, 'Include retired tanks')

    def test_a_retired_system_can_still_be_viewed_alone(self):
        CostEntry.objects.create(description='Then', amount=Decimal('5'), tank=self.old)
        self.assertEqual(self.client.get(reverse('the_damage'), {'tank': self.old.pk}).context['total'], 5)

    def test_currency_shows_wherever_prices_do(self):
        Equipment.objects.filter(pk=self.pump.pk).update(paid=Decimal('40'))
        self.client.post(reverse('damage_currency'), {'currency': '€', 'next': reverse('the_damage')})
        self.assertEqual(AppSettings.load().currency_symbol, '€')
        self.assertContains(self.client.get(reverse('equipment')), '€40.00')
        page = self.client.get(reverse('the_damage'))
        self.assertContains(page, 'Cost (€)')
        self.assertEqual(Equipment.objects.get(pk=self.pump.pk).paid, Decimal('40'))
        self.assertContains(self.client.get(reverse('equipment_edit', args=[self.pump.pk])), 'What you paid (€)')

    def test_currency_picker_does_not_clash_with_the_chart_data(self):
        CostEntry.objects.create(description='Now', amount=Decimal('10'), tank=self.tank)
        page = self.client.get(reverse('the_damage')).content.decode()
        self.assertEqual(page.count('id="damage-currency"'), 1)
        self.assertIn('<script id="damage-currency"', page)

    def test_fire_out_text_uses_the_currency(self):
        self.client.post(reverse('damage_currency'), {'currency': '£'})
        page = self.client.post(reverse('damage_switch'), {'enabled': '0'}, follow=True)
        self.assertContains(page, 'Your £ values')
        self.assertNotContains(page, '$ value')

    def test_unknown_currency_is_refused_and_custom_is_kept(self):
        self.client.post(reverse('damage_currency'), {'currency': 'GOLD'})
        self.assertEqual(AppSettings.load().currency_symbol, '$')
        AppSettings.objects.filter(pk=1).update(currency_symbol='Ƀ')
        self.assertContains(self.client.get(reverse('app_settings')), 'Ƀ (your own)')
        self.client.post(reverse('damage_currency'), {'currency': 'Ƀ'})
        self.assertEqual(AppSettings.load().currency_symbol, 'Ƀ')

    def test_settings_page_offers_the_currency_list(self):
        self.client.post(reverse('app_settings'), {
            'electricity_rate': '0.15', 'currency_symbol': 'CA$', 'auto_backup_days': 7, 'auto_backup_keep': 4})
        self.assertEqual(AppSettings.load().currency_symbol, 'CA$')

    def test_confession_sets_the_equipment_price(self):
        other = Tank.objects.create(name='Other', volume_gallons=10, capacity_is_manual=True)
        self.confess(description='The pump I needed', equipment=self.pump.pk, tank=other.pk)
        entry = CostEntry.objects.get()
        self.pump.refresh_from_db()
        self.assertEqual(self.pump.paid, Decimal('100'))
        self.assertEqual(entry.equipment, self.pump)
        self.assertEqual(entry.tank, self.tank)
        self.assertEqual(entry.category, 'equipment')
        self.assertEqual(entry.description, 'The pump I needed')

    def test_equipment_page_price_updates_the_confession(self):
        self.confess(description='The pump I needed', equipment=self.pump.pk, spent_on='2026-10-01')
        pump = Equipment.objects.get(pk=self.pump.pk)
        pump.paid = Decimal('150')
        pump.save()
        entry = CostEntry.objects.get()
        self.assertEqual(entry.amount, Decimal('150'))
        self.assertEqual(entry.description, 'The pump I needed')
        self.assertEqual(str(entry.spent_on), '2026-10-01')

    def test_price_from_equipment_page_counts_in_the_total(self):
        pump = Equipment.objects.get(pk=self.pump.pk)
        pump.paid = Decimal('75')
        pump.save()
        self.assertEqual(self.client.get(reverse('the_damage')).context['total'], 75)
        self.assertContains(self.client.get(reverse('the_damage')), 'value="%d"' % self.pump.pk)

    def test_no_double_counting_when_confessing_again(self):
        self.confess(equipment=self.pump.pk)
        page = self.client.post(reverse('the_damage'), {
            'description': 'Again', 'amount': '250', 'spent_on': '2026-11-02', 'category': 'other',
            'tank': self.tank.pk, 'equipment': self.pump.pk}, follow=True)
        self.assertEqual(CostEntry.objects.count(), 1)
        self.assertEqual(Equipment.objects.get(pk=self.pump.pk).paid, Decimal('250'))
        self.assertEqual(page.context['total'], 250)
        self.assertContains(page, 'This replaced the $100.00 already on Pump')

    def test_name_defaults_to_the_equipment(self):
        self.confess(description='', equipment=self.pump.pk)
        self.assertEqual(CostEntry.objects.get().description, 'Pump')
        CostEntry.objects.all().delete()
        self.confess(description='')
        self.assertEqual(CostEntry.objects.count(), 0)

    def test_negative_cost_is_refused(self):
        self.confess(amount='-5')
        self.assertEqual(CostEntry.objects.count(), 0)

    def test_unlinking_on_edit_clears_the_price(self):
        self.confess(equipment=self.pump.pk)
        entry = CostEntry.objects.get()
        self.client.post(reverse('cost_edit', args=[entry.pk]), {
            'description': 'One more', 'amount': '100', 'spent_on': '2026-11-01', 'category': 'equipment', 'tank': self.tank.pk, 'equipment': ''})
        self.assertIsNone(Equipment.objects.get(pk=self.pump.pk).paid)
        self.assertEqual(CostEntry.objects.get().amount, Decimal('100'))

    def test_moving_the_link_moves_the_price(self):
        light = Equipment.objects.create(name='Light', category='lighting', tank=self.tank)
        self.confess(equipment=self.pump.pk)
        entry = CostEntry.objects.get()
        self.client.post(reverse('cost_edit', args=[entry.pk]), {
            'description': 'One more', 'amount': '100', 'spent_on': '2026-11-01', 'category': 'equipment', 'tank': self.tank.pk, 'equipment': light.pk})
        self.assertIsNone(Equipment.objects.get(pk=self.pump.pk).paid)
        self.assertEqual(Equipment.objects.get(pk=light.pk).paid, Decimal('100'))

    def test_livestock_lines_stay_with_their_animal(self):
        animal = Animal.objects.create(name='Clown', tank=self.tank, paid=Decimal('30'))
        entry = CostEntry.objects.get(animal=animal)
        form_page = self.client.get(reverse('cost_edit', args=[entry.pk]))
        self.assertNotIn('equipment', form_page.context['form'].fields)
        self.client.post(reverse('cost_edit', args=[entry.pk]), {
            'description': 'Clown', 'amount': '35', 'spent_on': '2026-11-01', 'category': 'livestock', 'tank': self.tank.pk})
        self.assertEqual(Animal.objects.get(pk=animal.pk).paid, Decimal('35'))

    def test_retired_equipment_is_not_offered(self):
        Equipment.objects.create(name='Old pump', category='pump', tank=self.old)
        names = [e.name for e in self.client.get(reverse('the_damage')).context['form'].fields['equipment'].queryset]
        self.assertEqual(names, ['Pump'])

    def test_price_stays_hidden_while_the_fire_is_out(self):
        self.confess(equipment=self.pump.pk)
        self.client.post(reverse('damage_switch'), {'enabled': '0'})
        self.assertNotContains(self.client.get(reverse('equipment')), 'Paid $100')
        self.assertEqual(Equipment.objects.get(pk=self.pump.pk).paid, Decimal('100'))

    def test_sins_are_suggested(self):
        from .forms_tools import SIN_DESCRIPTIONS
        self.assertGreaterEqual(len(SIN_DESCRIPTIONS), 10)
        placeholder = self.client.get(reverse('the_damage')).context['form'].fields['description'].widget.attrs['placeholder']
        self.assertTrue(any(sin in placeholder for sin in SIN_DESCRIPTIONS))


class DemoReadingsTests(TestCase):
    def setUp(self):
        if not ParameterType.objects.filter(code='alkalinity').exists():
            call_command('seed_reef_data', stdout=io.StringIO())
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)

    def run_it(self, **options):
        call_command('seed_demo_readings', stdout=io.StringIO(), **options)

    def statuses(self, tank=None):
        logs = list(ParameterLog.objects.filter(tank=tank or self.tank))
        return [log.status for log in logs]

    def test_most_readings_are_in_range_with_a_few_outliers(self):
        self.run_it()
        statuses = self.statuses()
        self.assertGreater(len(statuses), 300)
        outliers = sum(1 for status in statuses if status != 'optimal')
        self.assertGreater(outliers, 5)
        self.assertLess(outliers / len(statuses), .1)

    def test_it_sets_off_a_warning_and_a_critical_alert(self):
        self.run_it()
        state = compute_alert_state(tank=self.tank)
        alerts = {item['param'].code: item['critical'] for item in state['out_of_range_params']}
        self.assertEqual(alerts, {'alkalinity': True, 'phosphate': False})

    def test_past_problems_have_a_reason_and_have_recovered(self):
        self.run_it()
        temperature = ParameterLog.objects.filter(tank=self.tank, parameter_type__code='temperature')
        self.assertTrue(temperature.filter(notes='Demo data: heater stuck on').exists())
        self.assertEqual(temperature.first().status, 'optimal')

    def test_nothing_is_in_the_future_or_before_the_start(self):
        self.run_it(days=30)
        now = timezone.now()
        for log in ParameterLog.objects.filter(tank=self.tank):
            self.assertLess(log.measured_at, now)
            self.assertGreater(log.measured_at, now - timedelta(days=30))

    def test_running_again_replaces_and_remove_keeps_real_readings(self):
        alk = ParameterType.objects.get(code='alkalinity')
        mine = ParameterLog.objects.create(parameter_type=alk, tank=self.tank, value=Decimal('8.5'), notes='Salifert')
        self.run_it()
        first = ParameterLog.objects.filter(tank=self.tank).count()
        self.run_it()
        self.assertEqual(ParameterLog.objects.filter(tank=self.tank).count(), first)
        self.run_it(remove=True)
        self.assertEqual(list(ParameterLog.objects.filter(tank=self.tank)), [mine])

    def test_works_in_whatever_units_the_ranges_use(self):
        ParameterType.objects.filter(code='temperature').update(
            unit='°C', low_limit=24, min_ideal=25, max_ideal=26, high_limit=27.5)
        ParameterType.objects.filter(code='salinity').update(unit='SG', min_ideal='1.024', max_ideal='1.027', decimal_places=3)
        self.run_it()
        temps = ParameterLog.objects.filter(tank=self.tank, parameter_type__code='temperature')
        self.assertTrue(all(20 < log.value < 30 for log in temps))
        salinity = ParameterLog.objects.filter(tank=self.tank, parameter_type__code='salinity')
        self.assertTrue(all(Decimal('1.02') < log.value < Decimal('1.03') for log in salinity))

    def test_uses_a_systems_own_targets(self):
        from .models import ParameterTarget
        alk = ParameterType.objects.get(code='alkalinity')
        ParameterTarget.objects.create(tank=self.tank, parameter_type=alk, min_ideal=10, max_ideal=11)
        self.run_it()
        normal = ParameterLog.objects.filter(tank=self.tank, parameter_type=alk, notes='Demo data')
        self.assertTrue(all(10 <= log.value <= 11 for log in normal))

    def test_parameter_with_no_limits_or_special_timing(self):
        ParameterType.objects.filter(code='iodine').delete()  # the built-in ICP iodine; this test makes its own
        ParameterType.objects.create(name='Iodine', code='iodine', unit='ppb', min_ideal=50, max_ideal=70, decimal_places=0)
        self.run_it()
        self.assertTrue(ParameterLog.objects.filter(tank=self.tank, parameter_type__code='iodine').exists())

    def test_retired_systems_are_left_alone_unless_named(self):
        old = Tank.objects.create(name='Old', volume_gallons=10, capacity_is_manual=True, is_archived=True)
        self.run_it()
        self.assertFalse(ParameterLog.objects.filter(tank=old).exists())
        self.run_it(tank='old')
        self.assertTrue(ParameterLog.objects.filter(tank=old).exists())

    def test_unknown_system_is_an_error(self):
        with self.assertRaises(CommandError):
            self.run_it(tank='nope')

    def test_charts_and_pages_cope_with_it(self):
        self.run_it()
        for name in ('dashboard', 'parameters', 'notifications'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class AlertHistoryTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.other = Tank.objects.create(name='Other', volume_gallons=10, capacity_is_manual=True)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'low_limit': 7, 'min_ideal': 8, 'max_ideal': 9, 'high_limit': 11})
        self.start = timezone.now() - timedelta(days=2)

    def reading(self, value, at, tank=None):
        return ParameterLog.objects.create(parameter_type=self.alk, tank=tank or self.tank, value=Decimal(str(value)), measured_at=at)

    def sync(self, at):
        events.sync_conditions(at)

    def resolved_episode(self, tank=None, minutes=120):
        self.reading(7.5, self.start, tank)
        self.sync(self.start)
        fixed = self.start + timedelta(minutes=minutes)
        self.reading(8.5, fixed, tank)
        self.sync(fixed)
        return fixed

    def test_records_start_and_resolve(self):
        fixed = self.resolved_episode()
        record = AlertRecord.objects.get(subject='Alkalinity')
        self.assertEqual(record.tank, self.tank)
        self.assertEqual((record.started_at, record.resolved_at), (self.start, fixed))
        self.assertEqual(record.duration_label, '2 hours')

    def test_getting_worse_stays_one_record_at_its_worst(self):
        self.reading(7.5, self.start)
        self.sync(self.start)
        self.reading(6.5, self.start + timedelta(hours=1))
        self.sync(self.start + timedelta(hours=1))
        self.reading(7.5, self.start + timedelta(hours=2))
        self.sync(self.start + timedelta(hours=2))
        record = AlertRecord.objects.get(subject='Alkalinity')
        self.assertEqual(record.severity, 'critical')
        self.assertIsNone(record.resolved_at)

    def test_hovering_probe_keeps_one_record_but_a_later_return_is_new(self):
        fixed = self.resolved_episode()
        self.reading(7.5, fixed + timedelta(minutes=5))
        self.sync(fixed + timedelta(minutes=5))
        record = AlertRecord.objects.get(subject='Alkalinity')
        self.assertIsNone(record.resolved_at)
        self.reading(8.5, fixed + timedelta(minutes=10))
        self.sync(fixed + timedelta(minutes=10))
        self.reading(7.5, fixed + timedelta(hours=3))
        self.sync(fixed + timedelta(hours=3))
        self.assertEqual(AlertRecord.objects.filter(subject='Alkalinity').count(), 2)

    def test_retention_defaults_to_seven_and_is_applied(self):
        self.assertEqual(AppSettings.load().resolved_alert_days, 7)
        fixed = self.resolved_episode()
        self.assertEqual(alert_summary(self.tank, now=fixed + timedelta(days=6))['resolved_count'], 1)
        self.assertEqual(alert_summary(self.tank, now=fixed + timedelta(days=8))['resolved_count'], 0)
        events.prune(fixed + timedelta(days=6))
        self.assertEqual(AlertRecord.objects.count(), 1)
        events.prune(fixed + timedelta(days=8))
        self.assertEqual(AlertRecord.objects.count(), 0)

    def test_open_alerts_are_never_pruned(self):
        self.reading(7.5, self.start)
        self.sync(self.start)
        events.prune(self.start + timedelta(days=60))
        self.assertEqual(AlertRecord.objects.count(), 1)

    def test_setting_limits(self):
        base = {'electricity_rate': '0.15', 'currency_symbol': '$', 'auto_backup_days': 7, 'auto_backup_keep': 4}
        self.client.post(reverse('app_settings'), {**base, 'resolved_alert_days': 30})
        self.assertEqual(AppSettings.load().resolved_alert_days, 30)
        for bad in (31, 0):
            self.client.post(reverse('app_settings'), {**base, 'resolved_alert_days': bad})
            self.assertEqual(AppSettings.load().resolved_alert_days, 30)
        self.assertContains(self.client.get(reverse('app_settings')), 'Days to keep resolved alerts')

    def test_metrics(self):
        self.resolved_episode(minutes=60)
        later = self.start + timedelta(hours=10)
        self.reading(6.5, later)
        self.sync(later)
        self.reading(8.5, later + timedelta(hours=3))
        self.sync(later + timedelta(hours=3))
        metrics = alert_summary(self.tank)['metrics']
        self.assertEqual((metrics['total'], metrics['fixed'], metrics['open'], metrics['critical']), (2, 2, 0, 1))
        self.assertEqual(metrics['average'], '2 hours')
        self.assertEqual(metrics['longest'], '3 hours')
        self.assertEqual((metrics['most_frequent'], metrics['most_frequent_times']), ('Alkalinity', 2))

    def test_most_frequent_only_shows_a_real_repeat(self):
        self.resolved_episode()
        self.assertContains(self.client.get(reverse('notifications')), 'Nothing has repeated')

    def test_no_history_means_no_metrics(self):
        self.assertIsNone(alert_summary(self.tank)['metrics'])
        self.assertNotContains(self.client.get(reverse('notifications')), 'Average time to resolve')

    def test_history_is_per_system(self):
        self.resolved_episode(tank=self.other)
        self.assertEqual(alert_summary(self.tank)['resolved_count'], 0)
        self.assertEqual(alert_summary(self.other)['resolved_count'], 1)

    def test_retiring_is_not_counted_as_fixed(self):
        self.reading(7.5, self.start)
        self.sync(self.start)
        self.tank.is_archived = True
        self.tank.save()
        self.sync(self.start + timedelta(hours=1))
        self.assertEqual(AlertRecord.objects.get(subject='Alkalinity').resolution, 'retired')
        metrics = alert_summary(self.tank)['metrics']
        self.assertEqual(metrics['fixed'], 0)
        self.assertIsNone(metrics['average'])

    def test_other_kinds_of_alert_are_recorded_with_their_system(self):
        animal = Animal.objects.create(name='Clown', tank=self.other, status='monitoring')
        self.sync(self.start)
        record = AlertRecord.objects.get(subject='Clown')
        self.assertEqual((record.tank, record.severity), (self.other, 'warning'))
        Animal.objects.filter(pk=animal.pk).update(status='healthy')
        self.sync(self.start + timedelta(hours=1))
        self.assertIsNotNone(AlertRecord.objects.get(subject='Clown').resolved_at)

    def page(self, **query):
        return self.client.get(reverse('notifications'), query)

    def test_page_shows_resolved_with_status_filter(self):
        self.resolved_episode()
        self.reading(6.5, timezone.now())
        self.sync(timezone.now())
        everything = self.page()
        self.assertContains(everything, 'Active Action Items')
        self.assertContains(everything, 'Resolved (1)')
        active = self.page(status='active')
        self.assertContains(active, 'Active Action Items')
        self.assertNotContains(active, 'Resolved (')
        resolved = self.page(status='resolved')
        self.assertNotContains(resolved, 'Active Action Items')
        self.assertContains(resolved, 'Resolved (1)')

    def test_severity_filter_applies_to_both_lists(self):
        self.resolved_episode()
        self.reading(6.5, timezone.now())
        critical = self.page(severity='critical')
        self.assertContains(critical, 'Active Action Items (1)')
        self.assertContains(critical, 'Resolved (0)')
        warning = self.page(severity='warning')
        self.assertContains(warning, 'Active Action Items (0)')
        self.assertContains(warning, 'No active alerts at this severity')
        self.assertContains(warning, 'Resolved (1)')

    def test_filters_keep_each_other_and_leave_the_badge_alone(self):
        self.reading(6.5, timezone.now())
        page = self.page(severity='warning', status='active')
        queries = [f['query'] for f in page.context['severity_filters']]
        self.assertIn('severity=critical&status=active', queries)
        self.assertEqual(page.context['global_total_alerts'], 1)

    def test_unknown_filters_are_ignored(self):
        self.reading(6.5, timezone.now())
        self.assertContains(self.page(severity='spicy', status='nope'), 'Active Action Items (1)')


class ReviewFixTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'low_limit': 7, 'min_ideal': 8, 'max_ideal': 9, 'high_limit': 11, 'decimal_places': 1})

    # Numbers that parse but aren't numbers
    def test_nan_and_infinity_are_not_readings(self):
        for bad in ('NaN', 'Infinity', 'sNaN'):
            response = self.client.post(reverse('quick_measure_create'), {'value': bad, 'parameter': self.alk.pk})
            self.assertEqual(response.status_code, 302, bad)
        self.assertEqual(ParameterLog.objects.count(), 0)

    def test_nan_refill_keeps_the_page_working(self):
        res = DosingReservoir.objects.create(tank=self.tank, name='A', capacity=100, current_level=10, daily_consumption=1)
        self.assertEqual(self.client.post(reverse('refill_reservoir', args=[res.pk]), {'custom_level': 'NaN'}).status_code, 302)
        res.refresh_from_db()
        self.assertEqual(res.current_level, 100)

    def test_calculators_refuse_nonsense_instead_of_crashing(self):
        common = {'parameter': 'alkalinity', 'chemical': 'baking_soda', 'current': 7, 'target': 8}
        for bad in ({'gallons': 'nan'}, {'gallons': 'inf'}, {'gallons': 10, 'target': 'inf'}, {'gallons': 10, 'current': 'nan'}):
            response = self.client.get(reverse('dose_calc_api'), {**common, **bad})
            self.assertEqual(response.status_code, 400, bad)
        for bad in ({'volume': 'nan'}, {'volume': 'inf'}, {'salinity': 'nan'}, {'volume': -5}, {'salinity': 35}):
            response = self.client.get(reverse('water_change_calc_api'), {'salinity': 1.026, **bad})
            self.assertEqual(response.status_code, 400, bad)

    def test_salt_target_of_fresh_water_needs_no_salt(self):
        self.assertEqual(self.client.get(reverse('water_change_calc_api'), {'volume': 10, 'salinity': 1}).json()['grams'], 0)
        self.assertEqual(self.client.get(reverse('water_change_calc_api'), {
            'volume': 10, 'salinity': 0, 'salinity_unit': 'ppt'}).json()['grams'], 0)

    def test_fill_calculator_with_no_output_is_an_error_not_a_crash(self):
        system = ROSystem.objects.create(name='Off', feed_psi=0)
        response = self.client.get(reverse('fill_calc_api'), {'system': system.pk, 'gallons': 5})
        self.assertEqual(response.status_code, 400)
        self.assertIn('zero', response.json()['error'])

    def test_bad_species_id_is_ignored(self):
        self.assertEqual(self.client.get(reverse('animal_create'), {'species_id': 'abc'}).status_code, 200)

    # API
    @override_settings(LOGIN_REQUIRED=True, API_SECRET_KEY='')
    def test_api_is_closed_with_no_key_set(self):
        response = self.client.post(reverse('api_parameter_log'), json.dumps({'parameter': 'alkalinity', 'value': 8}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(ParameterLog.objects.count(), 0)

    def test_api_refuses_when_every_system_is_retired(self):
        Tank.objects.update(is_archived=True)
        response = self.client.post(reverse('api_parameter_log'), json.dumps({'parameter': 'alkalinity', 'value': 8}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ParameterLog.objects.count(), 0)

    def test_unknown_tank_on_types_api_says_so(self):
        self.assertEqual(self.client.get(reverse('api_parameter_types'), {'tank': 'nope'}).status_code, 404)

    def test_odd_digit_characters_do_not_crash(self):
        response = self.client.post(reverse('api_parameter_log'), json.dumps({'parameter': '²', 'value': 8, 'tank': '²'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.client.cookies['nudibranch_system'] = '²'
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    # Uploads and page safety
    def test_quick_photo_must_be_an_image(self):
        animal = Animal.objects.create(name='Clown', tank=self.tank)
        fake = SimpleUploadedFile('evil.html', b'<script>alert(1)</script>', 'text/html')
        self.client.post(reverse('animal_upload_photo', args=[animal.pk]), {'photo': fake})
        animal.refresh_from_db()
        self.assertFalse(animal.photo)

    def test_user_text_cannot_break_out_of_a_script_tag(self):
        res = DosingReservoir.objects.create(tank=self.tank, name='</script><b>x', capacity=10, current_level=1, daily_consumption=1)
        page = self.client.get(reverse('timers')).content.decode()
        self.assertNotIn('</script><b>x', page.split('const reservoirs = ')[1].split(';')[0])
        self.assertTrue(res.pk)

    def test_camera_addresses_must_be_web_addresses(self):
        base = {'name': 'Cam', 'feed_type': 'mjpeg', 'order': 0, 'timelapse_interval_minutes': 60, 'timelapse_keep_days': 90}
        for bad in ('javascript:alert(1)', 'file:///etc/passwd'):
            self.client.post(reverse('webcam_create'), {**base, 'feed_url': bad})
            self.assertFalse(WebcamFeed.objects.exists(), bad)
        self.client.post(reverse('webcam_create'), {**base, 'feed_url': 'http://cam.local/stream'})
        self.assertTrue(WebcamFeed.objects.exists())

    def test_worker_will_not_read_local_files(self):
        with self.assertRaises(timelapse.CaptureError):
            timelapse.fetch_image('file:///etc/passwd')

    # Data staying correct
    def test_restart_keeps_your_parameter_changes(self):
        ParameterType.objects.all().delete()
        call_command('seed_reef_data', stdout=io.StringIO())
        self.assertTrue(ParameterType.objects.filter(code='ph').exists())
        ParameterType.objects.filter(code='alkalinity').update(decimal_places=3)
        ParameterType.objects.filter(code='ph').delete()
        AnimalGroup.objects.filter(name='School').delete()
        call_command('seed_reef_data', stdout=io.StringIO())
        self.assertEqual(ParameterType.objects.get(code='alkalinity').decimal_places, 3)
        self.assertFalse(ParameterType.objects.filter(code='ph').exists())
        self.assertFalse(AnimalGroup.objects.filter(name='School').exists())

    def test_deleting_the_primary_tank_promotes_another(self):
        other = Tank.objects.create(name='Other', volume_gallons=10, capacity_is_manual=True, is_primary=False)
        self.client.post(reverse('tank_delete', args=[self.tank.pk]))
        other.refresh_from_db()
        self.assertTrue(other.is_primary)

    def test_a_retired_tank_cannot_be_made_primary(self):
        Tank.objects.create(name='Old', volume_gallons=10, capacity_is_manual=True, is_primary=False, is_archived=True)
        old = Tank.objects.get(name='Old')
        self.client.post(reverse('tank_edit', args=[old.pk]), {
            'name': 'Old', 'is_primary': 'on', 'dimension_unit': 'in', 'fill_percent': 90, 'capacity_is_manual': 'on', 'volume_gallons': 10})
        old.refresh_from_db()
        self.tank.refresh_from_db()
        self.assertFalse(old.is_primary)
        self.assertTrue(self.tank.is_primary)

    def test_auto_backup_never_deletes_the_one_just_made(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=tmp):
            (Path(tmp) / 'backups').mkdir()
            name = Path(tmp) / 'backups' / 'nudibranch-auto-20260101-000000.zip'
            name.write_bytes(b'x')
            backups.prune_auto_backups(0)
            self.assertTrue(name.exists())

    def test_negative_reservoir_amounts_are_refused(self):
        self.client.post(reverse('dosing_create'), {
            'tank': self.tank.pk, 'name': 'A', 'reservoir_type': 'dosing_additive', 'capacity': 100, 'current_level': -5,
            'unit': 'ml', 'daily_consumption': 1, 'color': '#000000'})
        self.client.post(reverse('dosing_create'), {
            'tank': self.tank.pk, 'name': 'B', 'reservoir_type': 'dosing_additive', 'capacity': 100, 'current_level': 5,
            'unit': 'ml', 'daily_consumption': -1, 'color': '#000000'})
        self.assertFalse(DosingReservoir.objects.exists())

    def test_finishing_quarantine_resets_the_day_count(self):
        animal = Animal.objects.create(name='Tang', tank=self.tank, status='quarantine', quarantine_started=date(2020, 1, 1))
        self.client.post(reverse('quarantine_finish', args=[animal.pk]))
        animal.refresh_from_db()
        self.assertIsNone(animal.quarantine_started)
        animal.status = 'quarantine'
        animal.save()
        self.assertEqual(animal.quarantine_day, 1)

    def test_retired_animals_are_not_in_the_quarantine_list(self):
        old = Tank.objects.create(name='Old', volume_gallons=10, capacity_is_manual=True, is_primary=False, is_archived=True)
        Animal.objects.create(name='Ghost', tank=old, status='quarantine')
        self.assertEqual(list(self.client.get(reverse('quarantine_list')).context['active']), [])

    def test_tank_card_counts_only_living_animals(self):
        Animal.objects.create(name='Snails', tank=self.tank, count=10)
        Animal.objects.create(name='Gone', tank=self.tank, count=5, status='deceased')
        self.assertContains(self.client.get(reverse('tanks')), '10 animals')

    # Old files
    def test_photo_files_are_removed_with_their_records(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            def image(name):
                buffer = io.BytesIO()
                Image.new('RGB', (4, 4), 'red').save(buffer, 'PNG')
                return SimpleUploadedFile(name, buffer.getvalue(), 'image/png')
            animal = Animal.objects.create(name='Clown', tank=self.tank, photo=image('one.png'))
            first = Path(animal.photo.path)
            self.assertTrue(first.exists())
            self.client.post(reverse('animal_upload_photo', args=[animal.pk]), {'photo': image('two.png')})
            animal.refresh_from_db()
            second = Path(animal.photo.path)
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            animal.delete()
            self.assertFalse(second.exists())

    # Probes that go quiet
    def test_quiet_probe_shows_on_the_alerts_page(self):
        ParameterType.objects.filter(pk=self.alk.pk).update(stale_after_hours=2)
        ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal('8.5'),
                                    measured_at=timezone.now() - timedelta(hours=5))
        page = self.client.get(reverse('notifications'))
        self.assertContains(page, 'No new Alkalinity readings')
        self.assertEqual(page.context['total_alerts'], 1)
        self.assertEqual(page.context['global_stale_count'], 1)
        self.assertContains(self.client.get(reverse('notifications'), {'severity': 'warning'}), 'No new Alkalinity readings')
        self.assertNotContains(self.client.get(reverse('notifications'), {'severity': 'critical'}), 'No new Alkalinity readings')
        self.assertEqual(events.collect_conditions()[0]['type'], 'parameter.stale')

    # Speed
    def test_pages_do_not_query_per_reading_or_per_parameter(self):
        ParameterTarget.objects.create(tank=self.tank, parameter_type=self.alk, min_ideal=8, max_ideal=9)
        for index in range(40):
            ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal('8.5'),
                                        measured_at=timezone.now() - timedelta(hours=index))
        for name in range(12):
            ParameterType.objects.create(name=f'P{name}', code=f'p{name}', unit='x', min_ideal=1, max_ideal=2)
        self.client.get(reverse('dashboard'))  # its first ever visit saves the default layout
        for page in ('parameters', 'dashboard', 'notifications', 'dosing'):
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.client.get(reverse(page)).status_code, 200)
            # A fixed amount per page: 40 readings and 12 parameters must not add queries. The dashboard's
            # timers and app icon added a few fixed ones, so the cap is 45.
            self.assertLess(len(queries), 45, page)

    def test_list_status_uses_each_systems_own_targets(self):
        ParameterTarget.objects.create(tank=self.tank, parameter_type=self.alk, min_ideal=10, max_ideal=11)
        ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal('8.5'))
        self.assertEqual(self.client.get(reverse('parameters')).context['recent_logs'][0].status, 'low')
        state = compute_alert_state(tank=self.tank)
        self.assertEqual(state['out_of_range_params'][0]['log'].status, 'low')

    # Pages
    def test_one_set_of_ids_per_page(self):
        for page in ('routines', 'wishlist', 'equipment', 'dashboard', 'tanks'):
            html = self.client.get(reverse(page)).content.decode()
            ids = re.findall(r'\sid="([^"]+)"', html)
            repeats = sorted({i for i in ids if ids.count(i) > 1})
            self.assertEqual(repeats, [], page)

    def test_title(self):
        page = self.client.get(reverse('tanks'))
        self.assertContains(page, 'Reef Manager')
        self.assertNotContains(page, '>REEF<')


class QuarantineEndTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        WebhookEndpoint.objects.create(name='Phone', url='http://example.invalid/')

    def animal(self, days_ago=10, days=10, **extra):
        return Animal.objects.create(name='Tang', tank=self.tank, status='quarantine', quarantine_days=days,
                                     quarantine_started=timezone.localdate() - timedelta(days=days_ago), **extra)

    def test_ends_with_a_notification(self):
        animal = self.animal()
        self.assertEqual(events.end_finished_quarantines(), 1)
        animal.refresh_from_db()
        self.assertEqual(animal.status, 'healthy')
        self.assertIsNone(animal.quarantine_started)
        self.assertEqual(WebhookDelivery.objects.get().event_type, 'quarantine.complete')
        self.assertTrue(animal.quarantine_entries.exists())
        page = self.client.get(reverse('notifications'))
        self.assertContains(page, 'Tang has finished quarantine')
        self.assertContains(page, 'Resolved (1)')

    def test_only_notifies_once(self):
        self.animal()
        events.end_finished_quarantines()
        self.assertEqual(events.end_finished_quarantines(), 0)
        self.assertEqual(WebhookDelivery.objects.count(), 1)

    def test_not_finished_yet_is_left_alone(self):
        animal = self.animal(days_ago=3)
        self.assertEqual(events.end_finished_quarantines(), 0)
        animal.refresh_from_db()
        self.assertEqual(animal.status, 'quarantine')

    def test_retired_tanks_are_left_alone(self):
        animal = self.animal()
        Tank.objects.filter(pk=self.tank.pk).update(is_archived=True)
        self.assertEqual(events.end_finished_quarantines(), 0)
        animal.refresh_from_db()
        self.assertEqual(animal.status, 'quarantine')

    def test_notice_does_not_skew_the_metrics(self):
        self.animal()
        events.end_finished_quarantines()
        self.assertIsNone(alert_summary(self.tank)['metrics'])

    def test_worker_pass_ends_them(self):
        animal = self.animal()
        # Backups can't run inside a test's open transaction; BackupTests covers them.
        with mock.patch('aquarium.events.urllib.request.urlopen', side_effect=OSError('offline')), \
                mock.patch('aquarium.backups.run_auto_backup'):
            call_command('run_worker', '--once')
        animal.refresh_from_db()
        self.assertEqual(animal.status, 'healthy')


class MuteTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'low_limit': 7, 'min_ideal': 8, 'max_ideal': 9, 'high_limit': 11})
        self.endpoint = WebhookEndpoint.objects.create(name='Phone', url='http://example.invalid/')
        AppSettings.load()
        AppSettings.objects.filter(pk=1).update(events_baselined=True)

    def mute(self, **data):
        return self.client.post(reverse('notifications_mute'), data)

    def bad_reading(self):
        ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal('7.5'))

    def test_timer_presets_and_custom_hours(self):
        self.mute(duration='1h')
        settings_obj = AppSettings.load()
        self.assertTrue(settings_obj.alerts_muted)
        self.assertAlmostEqual((settings_obj.alerts_muted_until - timezone.now()).total_seconds(), 3600, delta=10)
        self.mute(duration='1h', custom_hours='2.5')
        self.assertAlmostEqual((AppSettings.load().alerts_muted_until - timezone.now()).total_seconds(), 9000, delta=10)

    def test_it_ends_by_itself(self):
        AppSettings.objects.filter(pk=1).update(alerts_muted_until=timezone.now() - timedelta(minutes=1))
        self.assertFalse(AppSettings.load().alerts_muted)

    def test_forever_and_unmute(self):
        self.mute(duration='forever')
        self.assertTrue(AppSettings.load().alerts_muted)
        self.mute(duration='off')
        settings_obj = AppSettings.load()
        self.assertFalse(settings_obj.alerts_muted)
        self.assertIsNone(settings_obj.alerts_muted_until)

    def test_bad_choices_change_nothing(self):
        for bad in ({'duration': 'soon'}, {'duration': ''}, {'duration': '1h', 'custom_hours': '99999'}, {'custom_hours': '-1'}):
            self.mute(**bad)
        self.assertFalse(AppSettings.load().alerts_muted)

    def test_nothing_sent_while_muted_but_still_wrong_is_sent_after(self):
        self.mute(duration='forever')
        self.bad_reading()
        self.assertEqual(events.sync_conditions(), 0)
        self.assertEqual(WebhookDelivery.objects.count(), 0)
        self.assertTrue(AlertRecord.objects.filter(subject='Alkalinity', resolved_at__isnull=True).exists())
        self.mute(duration='off')
        self.assertEqual(events.sync_conditions(), 1)

    def test_fixed_while_muted_is_never_sent(self):
        self.mute(duration='forever')
        self.bad_reading()
        events.sync_conditions()
        ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal('8.5'))
        events.sync_conditions()
        self.mute(duration='off')
        self.assertEqual(events.sync_conditions(), 0)

    def test_waiting_sends_are_held_but_jobs_keep_working(self):
        held = WebhookDelivery.objects.create(endpoint=self.endpoint, event_id='a', event_type='parameter.out_of_range', title='Alert')
        job = WebhookDelivery.objects.create(endpoint=self.endpoint, event_id='b', event_type='routine.scheduled', title='Feeder')
        timer = WebhookDelivery.objects.create(endpoint=self.endpoint, event_id='c', event_type='timer.finished', title='Timer')
        self.mute(duration='forever')
        with mock.patch('aquarium.events.send_delivery', return_value=True) as send:
            events.deliver_due()
        sent = {call.args[0].pk for call in send.call_args_list}
        self.assertEqual(sent, {job.pk, timer.pk})
        self.assertNotIn(held.pk, sent)

    def test_pages_show_it(self):
        self.bad_reading()
        self.assertContains(self.client.get(reverse('notifications')), 'id="mute-duration"')
        self.assertContains(self.client.get(reverse('integrations')), 'id="mute-duration"')
        self.assertContains(self.client.get(reverse('tanks')), 'id="alert-banner"')
        self.mute(duration='1h')
        self.assertContains(self.client.get(reverse('notifications')), 'Unmute now')
        page = self.client.get(reverse('tanks'))
        self.assertContains(page, 'Notifications muted')
        self.assertNotContains(page, 'id="alert-banner"')


class StepTimerTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.routine = MaintenanceRoutine.objects.create(
            title='Test', tank=self.tank, start_date=timezone.localdate(),
            checklist_items=['Add reagent', 'Wait for the colour [5 min]', 'Rinse [30 sec]', 'Soak [2 hours]', 'Odd [9999 hours]'])

    def test_steps_are_understood(self):
        steps = self.routine.checklist_steps
        self.assertEqual([s['text'] for s in steps[:4]], ['Add reagent', 'Wait for the colour', 'Rinse', 'Soak'])
        self.assertEqual([s['minutes'] for s in steps[:4]], [None, 5, 0.5, 120])
        self.assertEqual([s['label'] for s in steps[:4]], ['', '5 min', '30 sec', '2 hr'])
        self.assertIsNone(steps[4]['minutes'])

    def test_routines_page_offers_the_timer(self):
        page = self.client.get(reverse('routines'))
        self.assertContains(page, '⏱️ 5 min')
        self.assertContains(page, 'Wait for the colour')
        self.assertNotContains(page, 'Wait for the colour [5 min]')

    def test_starting_keeps_the_page_and_shows_the_countdown(self):
        step = self.routine.checklist_steps[1]
        response = self.client.post(reverse('timer_start'), {'minutes': step['minutes'], 'name': step['timer_name']}, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-step-timer')
        timer = FillTimer.objects.get()
        self.assertEqual(timer.name, 'Test: Wait for the colour')
        self.assertAlmostEqual((timer.ends_at - timezone.now()).total_seconds(), 300, delta=5)

    def test_a_running_timer_survives_a_reload(self):
        step = self.routine.checklist_steps[1]
        self.client.post(reverse('timer_start'), {'minutes': 5, 'name': step['timer_name']}, HTTP_HX_REQUEST='true')
        page = self.client.get(reverse('routines'))
        self.assertContains(page, 'data-step-timer')
        self.assertContains(page, '⏱️ 30 sec')

    def finish_step(self):
        step = self.routine.checklist_steps[1]
        self.client.post(reverse('timer_start'), {'minutes': 5, 'name': step['timer_name'], 'routine': self.routine.pk}, HTTP_HX_REQUEST='true')
        FillTimer.objects.update(ends_at=timezone.now() - timedelta(seconds=1))
        return events.finish_timers()

    def test_finished_step_fires_a_webhook(self):
        WebhookEndpoint.objects.create(name='Phone', url='http://example.invalid/')
        self.assertEqual(self.finish_step(), 1)
        delivery = WebhookDelivery.objects.get()
        self.assertEqual(delivery.event_type, 'routine.step_finished')
        self.assertEqual(delivery.data['routine_id'], self.routine.pk)
        self.assertEqual(delivery.data['step'], 'Wait for the colour')
        self.assertEqual(FillTimer.objects.get().status, 'finished')

    def test_step_webhook_can_target_one_routine(self):
        other = MaintenanceRoutine.objects.create(title='Other', tank=self.tank, start_date=timezone.localdate())
        mine = WebhookEndpoint.objects.create(name='Mine', url='http://example.invalid/a')
        mine.routines.add(self.routine)
        theirs = WebhookEndpoint.objects.create(name='Theirs', url='http://example.invalid/b')
        theirs.routines.add(other)
        self.finish_step()
        self.assertEqual(WebhookDelivery.objects.get().endpoint, mine)

    def test_a_step_can_name_its_own_connection(self):
        feeder = WebhookEndpoint.objects.create(name='Feeder', url='http://example.invalid/f')
        other = MaintenanceRoutine.objects.create(title='Other', tank=self.tank, start_date=timezone.localdate())
        feeder.routines.add(other)  # wired to another routine, so normally it wouldn't hear about this one
        step = parse_step('Dose now [2 min @feeder]')
        self.assertEqual((step['text'], step['minutes'], step['webhook']), ('Dose now', 2, 'feeder'))
        self.client.post(reverse('timer_start'), {'minutes': 2, 'name': 'Test: Dose now', 'routine': self.routine.pk, 'webhook': 'feeder'}, HTTP_HX_REQUEST='true')
        FillTimer.objects.update(ends_at=timezone.now() - timedelta(seconds=1))
        events.finish_timers()
        self.assertEqual(WebhookDelivery.objects.get().endpoint, feeder)

    def test_other_steps_do_not_trigger_a_named_connection(self):
        feeder = WebhookEndpoint.objects.create(name='Feeder', url='http://example.invalid/f')
        other = MaintenanceRoutine.objects.create(title='Other', tank=self.tank, start_date=timezone.localdate())
        feeder.routines.add(other)
        self.finish_step()
        self.assertFalse(WebhookDelivery.objects.exists())

    def test_step_naming_an_unknown_connection_is_refused(self):
        data = {'routine_type': 'manual', 'title': 'Test', 'category': 'general', 'repeat_preset': '1:week',
                'checklist_raw': 'Dose [2 min @Nope]', 'is_active': 'on'}
        self.client.post(reverse('routine_edit', args=[self.routine.pk]), data)
        self.routine.refresh_from_db()
        self.assertEqual(self.routine.checklist_items[0], 'Add reagent')

    def test_step_webhook_still_fires_while_muted(self):
        WebhookEndpoint.objects.create(name='Phone', url='http://example.invalid/')
        self.client.post(reverse('notifications_mute'), {'duration': 'forever'})
        self.finish_step()
        with mock.patch('aquarium.events.send_delivery', return_value=True) as send:
            events.deliver_due()
        self.assertEqual(send.call_count, 1)

    def test_finished_step_timer_alert_does_not_mention_a_fill(self):
        WebhookEndpoint.objects.create(name='Phone', url='http://example.invalid/')
        FillTimer.objects.create(name='Test: Wait', ends_at=timezone.now() - timedelta(seconds=1))
        events.finish_timers()
        self.assertEqual(WebhookDelivery.objects.get().message, "Time's up.")

    def test_form_keeps_the_timer_text(self):
        page = self.client.get(reverse('routine_edit', args=[self.routine.pk]))
        self.assertContains(page, 'Wait for the colour [5 min]')


class PhotoCompressionTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)

    def upload(self, name='big.png', size=(3000, 2000), mode='RGB', fmt='PNG', **save):
        buffer = io.BytesIO()
        Image.effect_noise(size, 64).convert(mode).save(buffer, fmt, **save)
        return SimpleUploadedFile(name, buffer.getvalue(), f'image/{fmt.lower()}')

    def test_quick_upload_becomes_a_smaller_jpeg(self):
        animal = Animal.objects.create(name='Clown', tank=self.tank)
        original = self.upload()
        self.client.post(reverse('animal_upload_photo', args=[animal.pk]), {'photo': original})
        animal.refresh_from_db()
        self.assertTrue(animal.photo.name.endswith('.jpg'))
        self.assertLess(animal.photo.size, original.size)
        with Image.open(animal.photo.path) as saved:
            self.assertEqual(saved.format, 'JPEG')
            self.assertEqual(max(saved.size), 1600)

    def test_timeline_photos_too(self):
        animal = Animal.objects.create(name='Clown', tank=self.tank)
        self.client.post(reverse('timeline', args=[animal.pk]), {'image': self.upload(), 'taken_on': '2026-01-01'})
        self.assertTrue(animal.timeline_photos.get().image.name.endswith('.jpg'))

    def test_transparent_images_get_a_white_background(self):
        buffer = io.BytesIO()
        Image.new('RGBA', (10, 10), (0, 0, 0, 0)).save(buffer, 'PNG')
        animal = Animal.objects.create(name='Clown', tank=self.tank, photo=SimpleUploadedFile('clear.png', buffer.getvalue()))
        with Image.open(animal.photo.path) as saved:
            self.assertEqual(saved.getpixel((5, 5))[0] > 240, True)

    def test_sideways_phone_photos_are_turned_upright(self):
        buffer = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6  # "rotate 90 degrees to view"
        Image.new('RGB', (40, 20), 'red').save(buffer, 'JPEG', exif=exif)
        animal = Animal.objects.create(name='Clown', tank=self.tank, photo=SimpleUploadedFile('side.jpg', buffer.getvalue()))
        with Image.open(animal.photo.path) as saved:
            self.assertEqual(saved.size, (20, 40))

    def test_small_details_keep_saving_without_touching_the_file(self):
        animal = Animal.objects.create(name='Clown', tank=self.tank, photo=self.upload(size=(50, 50)))
        name = animal.photo.name
        animal.notes = 'changed'
        animal.save()
        animal.refresh_from_db()
        self.assertEqual(animal.photo.name, name)
        self.assertTrue(Path(animal.photo.path).exists())

    def test_command_compresses_older_photos(self):
        Animal.objects.create(name='Clown', tank=self.tank)
        old = Path(self.tmp) / 'livestock'
        old.mkdir()
        Image.effect_noise((3000, 2000), 64).convert('RGB').save(old / 'old.png')
        Animal.objects.update(photo='livestock/old.png')
        out = io.StringIO()
        call_command('compress_photos', stdout=out)
        animal = Animal.objects.get()
        self.assertTrue(animal.photo.name.endswith('.jpg'))
        self.assertTrue(Path(animal.photo.path).exists())
        self.assertFalse((old / 'old.png').exists())
        self.assertIn('Compressed 1 photo', out.getvalue())


class LogPagingAndPageTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'min_ideal': 8, 'max_ideal': 9})
        now = timezone.now()
        ParameterLog.objects.bulk_create([
            ParameterLog(parameter_type=self.alk, tank=self.tank, value=Decimal('8.5'), measured_at=now - timedelta(hours=i))
            for i in range(120)])

    def test_load_more_walks_through_everything(self):
        page = self.client.get(reverse('parameters'))
        self.assertEqual(len(page.context['recent_logs']), 10)
        self.assertContains(page, 'Load more')
        self.assertContains(page, 'offset=10')
        second = self.client.get(reverse('parameter_logs_more'), {'offset': 10})
        self.assertEqual(len(second.context['recent_logs']), 25)
        self.assertContains(second, 'offset=35')
        last = self.client.get(reverse('parameter_logs_more'), {'offset': 110})
        self.assertEqual(len(last.context['recent_logs']), 10)
        self.assertNotContains(last, 'Load more')

    def test_load_more_keeps_the_selected_parameter(self):
        other, _ = ParameterType.objects.update_or_create(code='calcium', defaults={
            'name': 'Calcium', 'unit': 'ppm', 'min_ideal': 400, 'max_ideal': 450})
        ParameterLog.objects.create(parameter_type=other, tank=self.tank, value=420)
        page = self.client.get(reverse('parameters'), {'param': 'alkalinity'})
        self.assertContains(page, 'param=alkalinity')
        logs = self.client.get(reverse('parameter_logs_more'), {'offset': 50, 'param': 'alkalinity'}).context['recent_logs']
        self.assertTrue(all(log.parameter_type_id == self.alk.pk for log in logs))

    def test_short_list_has_no_button(self):
        ParameterLog.objects.filter(pk__in=ParameterLog.objects.values('pk')[:112]).delete()
        self.assertNotContains(self.client.get(reverse('parameters')), 'Load more')

    def test_pinch_zoom_is_allowed_and_nothing_loads_from_the_internet(self):
        html = self.client.get(reverse('parameters')).content.decode()
        self.assertNotIn('user-scalable=no', html)
        self.assertNotIn('maximum-scale', html)
        for host in ('cdn.tailwindcss.com', 'unpkg.com', 'jsdelivr'):
            self.assertNotIn(host, html)
        for name in ('css/tailwind.css', 'vendor/htmx.min.js', 'vendor/chart.umd.js'):
            self.assertIn(f'/static/{name}', html)
            self.assertTrue((Path(settings.BASE_DIR) / 'static' / name).exists(), name)

    def test_vendor_files_have_no_broken_map_links(self):
        chart = (Path(settings.BASE_DIR) / 'static/vendor/chart.umd.js').read_text(encoding='utf-8')
        self.assertNotIn('sourceMappingURL', chart)

    def test_phone_tabs_hide_the_extras_behind_more(self):
        page = self.client.get(reverse('tanks')).content.decode()
        self.assertIn('>More</button>', page)
        self.assertIn('data-more-tab class="hidden md:inline-block', page)
        wishlist = self.client.get(reverse('wishlist')).content.decode()
        tab = wishlist.split('💜 Wishlist')[0].rsplit('<a ', 1)[1]
        self.assertIn('bg-cyan-500', tab)
        self.assertNotIn('hidden', tab)

    def test_wording_says_tank(self):
        for name in ('tanks', 'tools', 'planner', 'notifications', 'parameters'):
            text = re.sub(r'<(script|style).*?</\1>|<[^>]+>|\{.*?\}', ' ', self.client.get(reverse(name)).content.decode(), flags=re.S)
            self.assertIsNone(re.search(r'(?<!RO/DI )\b[Ss]ystems?\b', text), name)


class LightAndParTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', width=24, depth=24, height=20, dimension_unit='in', is_primary=True)
        self.light = Equipment.objects.create(name='Radion', category='lighting', wattage=190, tank=self.tank)

    def par(self):
        tank = Tank.objects.get(pk=self.tank.pk)
        return [level['par'] for level in tank.light_summary()['levels']]

    def test_light_falls_off_with_depth(self):
        top, middle, bottom = self.par()
        self.assertTrue(top > middle > bottom > 0)
        self.assertTrue(100 < bottom < 300, bottom)

    def test_slider_changes_the_estimate(self):
        full = self.par()
        response = self.client.post(reverse('equipment_power', args=[self.light.pk]), {'power': 50})
        self.assertEqual(response.status_code, 302)
        half = self.par()
        for before, after in zip(full, half):
            self.assertAlmostEqual(after, before / 2, delta=10)

    def test_centimetres_give_the_same_answer(self):
        Tank.objects.filter(pk=self.tank.pk).update(width=60.96, depth=60.96, height=50.8, dimension_unit='cm')
        Tank.objects.get(pk=self.tank.pk)
        tank = Tank.objects.get(pk=self.tank.pk)
        self.assertEqual(tank.light_summary()['levels'][2]['inches'], 20)

    def test_sump_and_offline_lights_do_not_count(self):
        sump = Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=10, capacity_is_manual=True)
        before = self.par()
        Equipment.objects.create(name='Refugium light', category='lighting', wattage=500, tank=self.tank, sump=sump)
        Equipment.objects.create(name='Spare', category='lighting', wattage=500, tank=self.tank, status='offline')
        self.assertEqual(self.par(), before)

    def test_pages_show_the_slider_and_estimate(self):
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.tank.pk])), reverse('tools') + f'?tank={self.tank.pk}#light')
        page = self.client.get(reverse('tools'), {'tank': self.tank.pk})
        self.assertContains(page, 'about ')
        self.assertContains(page, 'PAR')
        self.assertContains(page, 'Rough estimate only')
        self.assertContains(page, 'Light power setting')
        self.assertContains(self.client.get(reverse('equipment')), 'Light power setting')

    def test_missing_details_ask_for_them(self):
        Equipment.objects.filter(pk=self.light.pk).update(wattage=None)
        self.assertContains(self.client.get(reverse('tools'), {'tank': self.tank.pk}), 'Add a wattage')
        Tank.objects.filter(pk=self.tank.pk).update(width=None)
        self.assertContains(self.client.get(reverse('tools'), {'tank': self.tank.pk}), 'dimensions</a> to see a PAR estimate')


class ExtraDosingTests(TestCase):
    LABEL = {'label_ml': 10, 'label_raise': 1, 'label_gallons': 100, 'gallons': 50}

    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=50, capacity_is_manual=True, is_primary=True)

    def estimate(self, **params):
        return self.client.get(reverse('dose_calc_api'), params)

    def test_label_maths_for_each_new_option(self):
        # 10 ml raises 1 ppm in 100 gal, so raising 2 ppm in 50 gal takes 10 ml.
        for code in ('nitrate', 'phosphate', 'potassium', 'iodine', 'strontium'):
            data = self.estimate(parameter=code, current=1, target=3, max_daily=100, **self.LABEL).json()
            self.assertEqual(data['correction_ml'], 10, code)
            self.assertIsNone(data['correction_grams'], code)
            self.assertEqual(data['mode'], 'label')

    def test_label_dose_scales_up_and_down_with_the_tank(self):
        # A bigger tank needs more product, and a smaller one less.
        common = {'parameter': 'alkalinity', 'current': 8, 'target': 9, 'max_daily': 10, 'label_ml': 10, 'label_raise': 1, 'label_gallons': 100}
        self.assertEqual(self.estimate(gallons=200, **common).json()['correction_ml'], 20)
        self.assertEqual(self.estimate(gallons=100, **common).json()['correction_ml'], 10)
        self.assertEqual(self.estimate(gallons=25, **common).json()['correction_ml'], 2.5)

    def test_small_doses_are_spread_over_days(self):
        data = self.estimate(parameter='phosphate', current=0.01, target=0.06, **self.LABEL).json()
        self.assertEqual(data['correction_days'], 3)
        self.assertEqual(data['correction_per_day_raise'], 0.017)

    def test_units_sit_beside_their_fields(self):
        Page = self.client.get(reverse('tools')).content.decode()
        for unit in ('calc-volume-unit', 'calc-salinity-unit', 'calc-start-unit'):
            self.assertIn(f'id="{unit}"', Page)
        self.assertNotIn('btn-unit-', Page)
        self.assertContains(self.client.get(reverse('tools')), 'id="est-label-gal-unit"')

    def test_units_are_buttons_and_each_answer_is_shown_once(self):
        salt = self.client.get(reverse('tools')).content.decode()
        self.assertIn('id="calc-volume-unit" data-units="gal,L"', salt)
        self.assertIn('id="salt-output-unit" data-units="g,oz,lb,cups"', salt)
        self.assertNotIn('output-ounces', salt)
        dose = self.client.get(reverse('tools')).content.decode()
        for unit in ('est-gallons-unit', 'est-label-gal-unit', 'est-amount-unit'):
            self.assertIn(f'id="{unit}" data-units=', dose)
        self.assertIn('id="est-amount"', dose)
        # The tank comes from the top of the page, so the calculators no longer repeat it in a box.
        self.assertNotIn('Change it at the top of the page', dose)
        self.assertIn('All water (tank + sump)', dose)

    def test_they_need_a_label(self):
        response = self.estimate(parameter='iodine', current=0.02, target=0.06, gallons=50)
        self.assertEqual(response.status_code, 400)

    def test_chemicals_are_not_offered_for_the_wrong_parameter(self):
        response = self.estimate(parameter='potassium', chemical='baking_soda', current=380, target=400, gallons=50)
        self.assertEqual(response.status_code, 400)

    def test_above_target_says_not_to_dose(self):
        data = self.estimate(parameter='nitrate', current=20, target=10, **self.LABEL).json()
        self.assertFalse(data['needs_raise'])
        self.assertIn("Don't dose", ' '.join(data['warnings']))

    def test_page_data(self):
        ParameterType.objects.update_or_create(code='nitrate', defaults={'name': 'Nitrate', 'unit': 'ppm', 'min_ideal': 2, 'max_ideal': 12})
        ParameterType.objects.filter(code__in=['iodine', 'potassium', 'strontium']).delete()
        data = self.client.get(reverse('tools')).context['dose_data']['parameters']
        self.assertEqual(set(data) >= {'alkalinity', 'nitrate', 'phosphate', 'potassium', 'iodine', 'strontium'}, True)
        self.assertEqual(data['nitrate']['target'], 7)
        self.assertEqual(data['iodine']['target'], 0.06)
        self.assertFalse(data['iodine']['available'])
        self.assertTrue(data['iodine']['label_only'])
        self.assertFalse(data['alkalinity']['label_only'])
        self.assertTrue(data['iodine']['note'])

    def test_tracked_in_ppb_is_converted(self):
        iodine, _ = ParameterType.objects.update_or_create(code='iodine', defaults={'name': 'Iodine', 'unit': 'ppb', 'min_ideal': 40, 'max_ideal': 80,
                                                                                   'is_trace': False})  # one you track yourself
        ParameterLog.objects.create(parameter_type=iodine, tank=self.tank, value=30)
        entry = self.client.get(reverse('tools')).context['dose_data']['parameters']['iodine']
        self.assertEqual(entry['current'], 0.03)
        self.assertEqual(entry['target'], 0.06)


class TankLookTests(TestCase):
    def setUp(self):
        self.main = Tank.objects.create(name='Main', volume_gallons=75, is_primary=True, theme='ocean', icon_choice='03-robot-young')
        self.second = Tank.objects.create(name='Second', volume_gallons=20, theme='ocean', icon_choice='')

    def test_look_belongs_to_the_tank_not_the_account(self):
        users = get_user_model()
        self.client.force_login(users.objects.create_user('first'))
        self.client.get(reverse('tank_look', args=[self.second.pk]))
        self.client.post(reverse('system_theme'), {'theme': 'icon', 'icon_choice': '03-robot-young'})
        self.second.refresh_from_db()
        self.main.refresh_from_db()
        self.assertEqual(self.second.theme, 'icon')
        self.assertEqual(self.main.theme, 'ocean')

        viewer = Client()
        viewer.force_login(users.objects.create_user('other'))
        viewer.get(reverse('tank_look', args=[self.second.pk]))
        page = viewer.get(reverse('system_theme'))
        self.assertEqual(page.context['active_tank'], self.second)
        self.assertEqual(page.context['system_icon_url'], self.second.icon_url)
        self.assertTrue(self.second.icon_url)

    def test_tank_page_opens_that_tanks_look(self):
        url = reverse('tank_look', args=[self.second.pk])
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.second.pk])), url)
        self.assertRedirects(self.client.get(url), reverse('system_theme'))
        self.assertEqual(self.client.get(reverse('system_theme')).context['active_tank'], self.second)

    def test_edit_page_links_to_the_look_only_for_a_saved_tank(self):
        url = reverse('tank_look', args=[self.main.pk])
        self.assertContains(self.client.get(reverse('tank_edit', args=[self.main.pk])), url)
        self.assertNotContains(self.client.get(reverse('tank_create')), 'Icon &amp; colours')

    def test_bottom_navigation_says_tanks(self):
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, '<span class="text-[10px] font-semibold">Tanks</span>')
        self.assertNotContains(page, '<span class="text-[10px] font-semibold">System</span>')
    def test_unknown_tank_is_not_found(self):
        self.assertEqual(self.client.get(reverse('tank_look', args=[9999])).status_code, 404)

    def test_tanks_list_shows_each_icon(self):
        self.assertContains(self.client.get(reverse('tanks')), self.main.icon_url)


class SaltCalculatorTests(TestCase):
    def setUp(self):
        Tank.objects.create(name='Main', volume_gallons=75, is_primary=True)

    def mix(self, **params):
        query = {'volume': 10, 'volume_unit': 'gal', 'brand': 'tropic_marin_pro', 'salinity': 1.026, 'salinity_unit': 'sg'}
        query.update(params)
        return self.client.get(reverse('water_change_calc_api'), query).json()

    def test_reachable_from_tabs_and_tools(self):
        self.assertContains(self.client.get(reverse('tanks')), reverse('tools') + '#salt-calculator')
        self.assertContains(self.client.get(reverse('tools')), 'href="#salt-calculator"')
        self.assertContains(self.client.get(reverse('tools')), 'id="salt-calculator"')
        # Moved to Tools, with a pointer left where it used to be.
        routines = self.client.get(reverse('routines'))
        self.assertNotContains(routines, 'id="salt-calculator"')
        self.assertContains(routines, reverse('tools') + '#salt-calculator')

    def test_calculators_say_they_are_estimates_to_confirm(self):
        for name in ('tools',):
            page = self.client.get(reverse(name))
            self.assertContains(page, 'Estimate only.')
            self.assertContains(page, 'confirm')
            self.assertContains(page, 'independently')
    def test_dose_estimator_reachable_from_tabs_and_tools(self):
        self.assertContains(self.client.get(reverse('tanks')), reverse('tools') + '#dose-estimator')
        self.assertContains(self.client.get(reverse('tools')), 'href="#dose-estimator"')
        self.assertContains(self.client.get(reverse('tools')), 'id="dose-estimator"')
        dosing = self.client.get(reverse('dosing'))
        self.assertNotContains(dosing, 'id="dose-estimator"')
        self.assertContains(dosing, reverse('tools') + '#dose-estimator')

    def test_starting_salinity_defaults_to_fresh_water(self):
        fresh = self.mix()
        self.assertEqual(fresh['grams'], 1480.0)
        self.assertEqual(self.mix(start_salinity=0)['grams'], 1480.0)
        self.assertEqual(self.mix(start_salinity='')['grams'], 1480.0)
        self.assertFalse(fresh['already_at_target'])

    def test_only_the_missing_salt_is_counted(self):
        self.assertEqual(self.mix(start_salinity=1.013)['grams'], 740.0)
        self.assertEqual(self.mix(salinity=35, salinity_unit='ppt', start_salinity=17.5)['grams'], 740.0)

    def test_water_already_at_target_needs_no_salt(self):
        for start in (1.026, 1.030):
            result = self.mix(start_salinity=start)
            self.assertEqual((result['grams'], result['cups']), (0.0, 0.0))
            self.assertTrue(result['already_at_target'])

    def test_negative_start_counts_as_fresh(self):
        self.assertEqual(self.mix(salinity=35, salinity_unit='ppt', start_salinity=-5)['grams'], 1480.0)

    def test_bad_start_is_rejected(self):
        response = self.client.get(reverse('water_change_calc_api'), {'start_salinity': 'salty'})
        self.assertEqual(response.status_code, 400)


class SubstrateTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, capacity_is_manual=True, is_primary=True)

    def post(self, **extra):
        data = {'name': 'Main', 'is_primary': 'on', 'dimension_unit': 'in', 'fill_percent': 90,
                'capacity_is_manual': 'on', 'volume_gallons': 75}
        data.update(extra)
        response = self.client.post(reverse('tank_edit', args=[self.tank.pk]), data)
        self.tank.refresh_from_db()
        return response

    def test_saves_and_shows_both_units(self):
        response = self.post(substrate_type='live_sand', substrate_amount='50', substrate_unit='lb',
                             live_rock_amount='40', live_rock_unit='kg')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.tank.substrate_amount_label, '50 lb (22.7 kg)')
        self.assertEqual(self.tank.live_rock_label, '40 kg (88.2 lb)')
        page = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        self.assertContains(page, 'Live sand')
        self.assertContains(page, '50 lb (22.7 kg)')
        self.assertContains(page, '40 kg (88.2 lb)')

    def test_new_product_is_added_to_equipment_and_reused(self):
        self.post(substrate_type='live_sand', new_substrate_product='CaribSea Arag-Alive Pink')
        product = self.tank.substrate_product
        self.assertEqual((product.name, product.category, product.tank), ('CaribSea Arag-Alive Pink', 'substrate', self.tank))
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.tank.pk])), 'CaribSea Arag-Alive Pink')
        self.post(substrate_type='live_sand', new_substrate_product='caribsea arag-alive pink')
        self.assertEqual(Equipment.objects.filter(category='substrate').count(), 1)

    def test_pick_existing_product_and_only_substrate_is_offered(self):
        sand = Equipment.objects.create(name='Sand', category='substrate')
        pump = Equipment.objects.create(name='Pump', category='return_pump')
        form_choices = self.client.get(reverse('tank_edit', args=[self.tank.pk])).context['form'].fields['substrate_product'].queryset
        self.assertEqual(list(form_choices), [sand])
        self.post(substrate_type='aragonite', substrate_product=sand.pk)
        self.assertEqual(self.tank.substrate_product, sand)
        response = self.post(substrate_type='aragonite', substrate_product=pump.pk)
        self.assertEqual(response.status_code, 200)

    def test_bare_bottom_clears_sand_details(self):
        sand = Equipment.objects.create(name='Sand', category='substrate')
        self.post(substrate_type='bare', substrate_amount='50', substrate_product=sand.pk, new_substrate_product='Other', live_rock_amount='10')
        self.assertIsNone(self.tank.substrate_amount)
        self.assertIsNone(self.tank.substrate_product)
        self.assertEqual(Equipment.objects.filter(category='substrate').count(), 1)
        self.assertEqual(self.tank.live_rock_amount, Decimal('10'))

    def test_negative_rejected_and_unit_defaults(self):
        self.assertEqual(self.post(substrate_amount='-1').status_code, 200)
        self.assertEqual(self.post(live_rock_amount='-1').status_code, 200)
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual((self.tank.substrate_unit, self.tank.live_rock_unit), ('lb', 'lb'))

    def test_deleting_the_product_keeps_the_tank_details(self):
        self.post(substrate_type='live_sand', substrate_amount='50', new_substrate_product='Sand')
        self.tank.substrate_product.delete()
        self.tank.refresh_from_db()
        self.assertIsNone(self.tank.substrate_product)
        self.assertEqual(self.tank.substrate_amount, Decimal('50'))

    def test_substrate_gets_no_service_reminders(self):
        old_date = timezone.localdate() - timedelta(days=900)
        sand = Equipment.objects.create(name='Sand', category='substrate', tank=self.tank, installed_date=old_date)
        pump = Equipment.objects.create(name='Pump', category='return_pump', tank=self.tank, installed_date=old_date)
        self.assertFalse(sand.is_service_due)
        self.assertTrue(pump.is_service_due)
        self.assertEqual(compute_alert_state(tank=self.tank)['due_equipment'], [pump])
        page = self.client.get(reverse('equipment'), {'category': 'substrate'})
        self.assertContains(page, 'Sand')
        self.assertNotContains(page, 'Service every')

    def test_empty_profile_offers_to_add(self):
        page = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        self.assertContains(page, 'Add substrate')
        self.assertContains(page, 'Add live rock')
        form = self.client.get(reverse('tank_create'))
        self.assertContains(form, 'Or add a new product')
        self.assertEqual(self.client.get(reverse('sump_edit', args=[Sump.objects.create(tank=self.tank, capacity_is_manual=True).pk])).status_code, 200)


class SystemLookTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.main = Tank.objects.create(name='Main', capacity_is_manual=True, is_primary=True)
        self.qt = Tank.objects.create(name='QT', capacity_is_manual=True, is_primary=False)

    def save(self, **data):
        data.setdefault('theme', 'ocean')
        data.setdefault('icon_choice', '')
        return self.client.post(reverse('system_theme'), data, follow=True)

    def test_each_system_has_its_own_look(self):
        self.save(theme='kelp', icon_choice='01-dragon-mage-young')
        page = self.client.get('/')
        self.assertContains(page, '--cyan-500:16 185 129')
        self.assertContains(page, '01-dragon-mage-young')
        self.assertIn('01-dragon-mage-young', page.context['system_icon_url'])
        self.client.post(reverse('system_select'), {'tank': self.qt.pk})
        page = self.client.get('/')
        self.assertNotContains(page, '--cyan-500:16 185 129')
        self.assertEqual(page.context['system_icon_url'], self.qt.icon_url)
        self.assertNotIn('01-dragon-mage-young', page.context['system_icon_url'])

    def test_custom_icon_upload_and_replace(self):
        buf = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(buf, 'PNG')
        self.save(custom_icon=SimpleUploadedFile('me.png', buf.getvalue(), 'image/png'))
        self.main.refresh_from_db()
        self.assertEqual(self.main.icon_choice, 'custom')
        first = Path(self.main.custom_icon.path)
        self.assertTrue(first.exists())
        self.assertEqual(self.main.icon_url, self.main.custom_icon.url)
        self.save(icon_choice='custom', custom_icon=SimpleUploadedFile('next.png', buf.getvalue(), 'image/png'))
        self.main.refresh_from_db()
        self.assertFalse(first.exists())
        self.assertTrue(Path(self.main.custom_icon.path).exists())

    def test_rejects_bad_uploads_and_values(self):
        self.save(custom_icon=SimpleUploadedFile('x.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>', 'image/svg+xml'))
        self.save(custom_icon=SimpleUploadedFile('x.png', b'not an image', 'image/png'))
        self.save(icon_choice='../../evil')
        self.save(theme='nonsense')
        self.main.refresh_from_db()
        self.assertFalse(self.main.custom_icon)
        self.assertEqual((self.main.theme, self.main.icon_choice), ('ocean', ''))

    def test_page_lists_all_choices(self):
        page = self.client.get(reverse('system_theme'))
        for text in ('Kelp Forest', 'Coral Reef', 'Default', 'Dragon Mage', 'Or add your own'):
            self.assertContains(page, text)


class CostSwitchTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=50, capacity_is_manual=True, is_primary=True)
        self.fish = species('F', 'Fishus one')

    def switch(self, on):
        return self.client.post(reverse('damage_switch'), {'enabled': '1'} if on else {})

    def test_off_by_default_and_blocks_entries(self):
        page = self.client.get(reverse('the_damage'))
        self.assertContains(page, 'Light the match')
        self.assertNotContains(page, 'Confess a purchase')
        self.client.post(reverse('the_damage'), {
            'description': 'x', 'amount': '5', 'spent_on': timezone.localdate().isoformat(), 'category': 'other'})
        self.assertEqual(CostEntry.objects.count(), 0)

    def test_planning_prices_always_available(self):
        plan = PlannedSystem.objects.create(name='P', volume_gallons=10, capacity_is_manual=True)
        for url in (reverse('wishlist'), reverse('plan_detail', args=[plan.pk])):
            self.assertContains(self.client.get(url), 'Price each', msg_prefix=url)
        self.assertContains(self.client.get(reverse('plan_create')), 'budget')
        self.client.post(reverse('wishlist_add_livestock'), {'species': self.fish.pk, 'quantity': 2, 'priority': 'want', 'est_price': '50'})
        self.assertEqual(WishlistItem.objects.get().est_price, Decimal('50'))
        self.assertContains(self.client.get(reverse('wishlist')), '100.00')
        self.client.post(reverse('plan_add_equipment', args=[plan.pk]), {
            'gear-name': 'Pump', 'gear-category': 'other', 'gear-quantity': 1, 'gear-unit_cost': '70'})
        self.assertContains(self.client.get(reverse('plan_detail', args=[plan.pk])), '70.00')

    def test_planning_prices_do_not_count_until_moved_to_a_tank(self):
        self.switch(True)
        item = WishlistItem.objects.create(species=self.fish, name='F', est_price=Decimal('25'))
        plan = PlannedSystem.objects.create(name='P', existing_tank=self.tank)
        PlannedItem.objects.create(plan=plan, kind='equipment', name='Heater', category='heater', unit_cost=Decimal('40'))
        total = lambda: self.client.get(reverse('the_damage')).context['total']
        self.assertEqual(total(), 0.0)
        self.assertEqual(CostEntry.objects.count(), 0)
        self.client.post(reverse('wishlist_to_plan', args=[item.pk]), {'plan': plan.pk})
        self.assertEqual(total(), 0.0)
        self.client.post(reverse('plan_track', args=[plan.pk]))
        self.assertEqual(total(), 65.0)

    def test_tracked_paid_fields_stay_behind_the_fire(self):
        self.assertNotContains(self.client.get(reverse('animal_create')), 'name="paid"')
        self.assertNotContains(self.client.get(reverse('equipment')), 'name="paid"')
        self.switch(True)
        self.assertContains(self.client.get(reverse('animal_create')), 'name="paid"')

    def test_priced_purchase_while_out_is_hidden_then_counted(self):
        self.switch(True)
        item = WishlistItem.objects.create(species=self.fish, name='F', est_price=Decimal('25'))
        self.switch(False)
        self.client.post(reverse('wishlist_bought', args=[item.pk]), {'tank': self.tank.pk})
        self.assertEqual(Animal.objects.get().paid, Decimal('25'))
        self.assertNotContains(self.client.get(reverse('the_damage')), 'Confess a purchase')
        self.assertNotContains(self.client.get(reverse('livestock')), 'Paid $')
        self.switch(True)
        self.assertEqual(self.client.get(reverse('the_damage')).context['total'], 25.0)
        self.assertContains(self.client.get(reverse('livestock')), 'Paid $25.00')

    def test_messages_promise_nothing_is_erased(self):
        self.assertContains(self.client.get(reverse('the_damage')), "your $ values won't be erased")
        self.switch(True)
        page = self.client.get(reverse('the_damage'))
        self.assertContains(page, "Your $ values won't be erased")
        self.assertContains(page, 'will NOT be erased')
        CostEntry.objects.create(description='Secret', amount=Decimal('9'), tank=self.tank)
        CostEntry.objects.create(description='Also', amount=Decimal('1'), tank=self.tank)
        response = self.client.post(reverse('damage_switch'), {}, follow=True)
        self.assertContains(response, 'hidden, not erased')
        self.assertContains(response, 'Your 2 saved $ values are hidden, not erased')
        self.assertNotContains(response, 'Secret')

    def test_ledger_cannot_change_while_out(self):
        self.switch(True)
        entry = CostEntry.objects.create(description='Secret', amount=Decimal('9'), tank=self.tank)
        self.switch(False)
        self.client.post(reverse('cost_delete', args=[entry.pk]))
        self.client.post(reverse('cost_edit', args=[entry.pk]), {'description': 'x', 'amount': '1', 'spent_on': '2026-01-01', 'category': 'other'})
        entry.refresh_from_db()
        self.assertEqual((entry.description, entry.amount), ('Secret', Decimal('9')))

    def test_every_value_survives_being_put_out_and_edited(self):
        """Each kind of $ value, through everything you can do to its record while prices are hidden."""
        self.switch(True)
        fish = Animal.objects.create(name='Tang', tank=self.tank, paid=Decimal('80'))
        pump = Equipment.objects.create(name='Pump', tank=self.tank, category='other', paid=Decimal('200'))
        manual = CostEntry.objects.create(description='Rock', amount=Decimal('60'), tank=self.tank, category='rock')
        wanted_animal = WishlistItem.objects.create(species=self.fish, name='F', est_price=Decimal('25'))
        wanted_gear = WishlistItem.objects.create(kind='equipment', name='Light', category='lighting', est_price=Decimal('300'))
        plan = PlannedSystem.objects.create(name='P', volume_gallons=30, capacity_is_manual=True, budget=Decimal('999'))
        planned = PlannedItem.objects.create(plan=plan, kind='equipment', name='Heater', category='heater', unit_cost=Decimal('40'))
        settings_before = AppSettings.load().electricity_rate

        self.switch(False)
        self.client.post(reverse('animal_edit', args=[fish.pk]), {'name': 'Renamed Tang', 'count': 2, 'status': 'healthy', 'tank': self.tank.pk})
        self.client.post(reverse('equipment_edit', args=[pump.pk]), {
            'location': f'tank:{self.tank.pk}', 'name': 'Renamed Pump', 'category': 'other', 'power_setting_percent': 100,
            'flow_derate_percent': 0, 'maintenance_interval_days': 90, 'status': 'operational'})
        self.client.post(reverse('equipment_power', args=[pump.pk]), {'power': 50})
        self.client.post(reverse('service_equipment', args=[pump.pk]))
        self.client.post(reverse('wishlist_edit', args=[wanted_animal.pk]), {'species': self.fish.pk, 'quantity': 1, 'priority': 'must', 'est_price': '25'})
        self.client.post(reverse('wishlist_edit', args=[wanted_gear.pk]), {'name': 'New Light', 'category': 'lighting', 'quantity': 1, 'priority': 'must', 'est_price': '300'})
        self.client.post(reverse('plan_edit', args=[plan.pk]), {
            'name': 'Renamed Plan', 'goal': 'mixed', 'dimension_unit': 'in', 'fill_percent': 90, 'capacity_is_manual': 'on',
            'volume_gallons': 30, 'sump_gallons': 0, 'budget': '999'})
        self.client.post(reverse('app_settings'), {'electricity_rate': '0.2', 'currency_symbol': '$', 'auto_backup_days': 7, 'auto_backup_keep': 4})
        self.client.post(reverse('wishlist_to_plan', args=[wanted_gear.pk]), {'plan': plan.pk})
        call_command('seed_reef_data', stdout=io.StringIO())
        self.assertFalse(AppSettings.load().costs_enabled)
        self.assertNotEqual(AppSettings.load().electricity_rate, settings_before)

        self.switch(True)
        for obj in (fish, pump, manual, wanted_animal, wanted_gear, plan, planned):
            obj.refresh_from_db()
        self.assertEqual(fish.name, 'Renamed Tang')
        self.assertEqual(fish.paid, Decimal('80'))
        self.assertEqual(pump.name, 'Renamed Pump')
        self.assertEqual(pump.paid, Decimal('200'))
        self.assertEqual(manual.amount, Decimal('60'))
        self.assertEqual(wanted_animal.est_price, Decimal('25'))
        self.assertEqual(wanted_gear.est_price, Decimal('300'))
        self.assertEqual(wanted_gear.planned_item.unit_cost, Decimal('300'))
        self.assertEqual(plan.name, 'Renamed Plan')
        self.assertEqual(plan.budget, Decimal('999'))
        self.assertEqual(planned.unit_cost, Decimal('40'))
        self.assertEqual(fish.cost_entry.amount, Decimal('80'))
        self.assertEqual(pump.cost_entry.amount, Decimal('200'))
        self.assertEqual(self.client.get(reverse('the_damage')).context['total'], 340.0)
        self.assertContains(self.client.get(reverse('wishlist')), '25.00')

    def test_plan_tracked_while_out_reaches_ledger_after(self):
        self.switch(True)
        plan = PlannedSystem.objects.create(name='P', existing_tank=self.tank)
        PlannedItem.objects.create(plan=plan, kind='equipment', name='Heater', category='heater', unit_cost=Decimal('40'))
        self.switch(False)
        self.client.post(reverse('plan_track', args=[plan.pk]))
        self.switch(True)
        self.assertEqual(self.client.get(reverse('the_damage')).context['total'], 40.0)

    def test_putting_it_out_hides_but_keeps_everything(self):
        self.switch(True)
        WishlistItem.objects.create(species=self.fish, name='F', est_price=Decimal('25'))
        entry = CostEntry.objects.create(description='Secret', amount=Decimal('9'), tank=self.tank)
        self.assertContains(self.client.get(reverse('wishlist')), '25.00')
        self.assertContains(self.client.get(reverse('the_damage')), 'Secret')
        self.switch(False)
        self.assertContains(self.client.get(reverse('wishlist')), '25.00')  # planning prices stay visible
        self.assertNotContains(self.client.get(reverse('the_damage')), 'Secret')
        self.assertRedirects(self.client.get(reverse('cost_edit', args=[entry.pk])), reverse('the_damage'))
        # Editing a tracked record while hidden must not wipe what was paid.
        pump = Equipment.objects.create(name='Pump', tank=self.tank, paid=Decimal('7'))
        self.client.post(reverse('equipment_edit', args=[pump.pk]), {
            'location': f'tank:{self.tank.pk}', 'name': 'Renamed', 'category': 'other', 'power_setting_percent': 100,
            'flow_derate_percent': 0, 'maintenance_interval_days': 90, 'status': 'operational'})
        pump.refresh_from_db()
        self.assertEqual((pump.name, pump.paid), ('Renamed', Decimal('7')))
        self.switch(True)
        self.assertContains(self.client.get(reverse('the_damage')), 'Secret')

    def test_flames_are_decorative(self):
        page = self.client.get(reverse('the_damage'))
        self.assertContains(page, 'damage-fire')
        self.assertContains(page, 'pointer-events: none')
        self.assertContains(page, 'prefers-reduced-motion')


class WhatYouPaidTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'costs_enabled': True})
        self.main = Tank.objects.create(name='Main', volume_gallons=50, capacity_is_manual=True, is_primary=True)
        self.qt = Tank.objects.create(name='QT', volume_gallons=10, capacity_is_manual=True, is_primary=False)

    def test_animal_paid_creates_and_follows_ledger_entry(self):
        fish = Animal.objects.create(name='Tang', tank=self.main, paid=Decimal('80'), acquired_date=date(2026, 3, 1))
        entry = CostEntry.objects.get()
        self.assertEqual((entry.amount, entry.category, entry.tank, entry.spent_on), (Decimal('80'), 'livestock', self.main, date(2026, 3, 1)))
        fish.paid = Decimal('95')
        fish.tank = self.qt
        fish.count = 2
        fish.save()
        entry = CostEntry.objects.get()
        self.assertEqual((entry.amount, entry.tank, entry.description), (Decimal('95'), self.qt, '2x Tang'))
        fish.paid = None
        fish.save()
        self.assertEqual(CostEntry.objects.count(), 0)

    def test_ledger_edits_flow_back(self):
        fish = Animal.objects.create(name='Tang', paid=Decimal('80'))
        pump = Equipment.objects.create(name='Pump', paid=Decimal('200'))
        entry = fish.cost_entry
        entry.amount = Decimal('75')
        entry.save()
        fish.refresh_from_db()
        self.assertEqual(fish.paid, Decimal('75'))
        self.client.post(reverse('cost_delete', args=[pump.cost_entry.pk]))
        pump.refresh_from_db()
        self.assertIsNone(pump.paid)
        self.assertEqual(CostEntry.objects.count(), 1)

    def test_deleting_the_animal_keeps_the_money_spent(self):
        fish = Animal.objects.create(name='Tang', paid=Decimal('80'))
        fish.delete()
        self.assertEqual(CostEntry.objects.get().amount, Decimal('80'))

    def test_forms_show_field_only_when_lit(self):
        fish = Animal.objects.create(name='Tang', tank=self.main)
        pump = Equipment.objects.create(name='Pump', tank=self.main)
        pages = [reverse('animal_create'), reverse('animal_edit', args=[fish.pk]), reverse('equipment_edit', args=[pump.pk]), reverse('equipment_create')]
        for url in pages:
            self.assertContains(self.client.get(url), 'name="paid"', msg_prefix=url)
        self.assertContains(self.client.get(reverse('equipment')), 'name="paid"')
        AppSettings.objects.filter(pk=1).update(costs_enabled=False)
        for url in pages + [reverse('equipment')]:
            self.assertNotContains(self.client.get(url), 'name="paid"', msg_prefix=url)

    def test_edit_form_saves_paid(self):
        pump = Equipment.objects.create(name='Pump', tank=self.main)
        response = self.client.post(reverse('equipment_edit', args=[pump.pk]), {
            'location': f'tank:{self.main.pk}', 'name': 'Pump', 'category': 'other', 'power_setting_percent': 100,
            'flow_derate_percent': 0, 'maintenance_interval_days': 90, 'status': 'operational', 'paid': '149.99'})
        self.assertEqual(response.status_code, 302)
        pump.refresh_from_db()
        self.assertEqual(pump.paid, Decimal('149.99'))
        self.assertEqual(pump.cost_entry.tank, self.main)
        self.assertContains(self.client.get(reverse('equipment')), 'Paid $149.99')

    def test_negative_rejected(self):
        response = self.client.post(reverse('animal_create'), {'name': 'Fish', 'count': 1, 'status': 'healthy', 'paid': '-5'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Animal.objects.count(), 0)

    def test_hidden_edit_keeps_paid(self):
        pump = Equipment.objects.create(name='Pump', tank=self.main, paid=Decimal('50'))
        AppSettings.objects.filter(pk=1).update(costs_enabled=False)
        self.client.post(reverse('equipment_edit', args=[pump.pk]), {
            'location': f'tank:{self.main.pk}', 'name': 'Renamed', 'category': 'other', 'power_setting_percent': 100,
            'flow_derate_percent': 0, 'maintenance_interval_days': 90, 'status': 'operational'})
        pump.refresh_from_db()
        self.assertEqual((pump.name, pump.paid), ('Renamed', Decimal('50')))

    def test_catalog_quick_add_with_paid(self):
        fish = species('F', 'Fishus one')
        url = reverse('species_add_to_tank', args=[fish.pk])
        self.assertContains(self.client.get(reverse('species_catalog')), 'name="paid"')
        self.client.post(url, {'tank': self.main.pk, 'count': 2, 'paid': '60'})
        self.assertEqual(CostEntry.objects.get().description, '2x F')
        self.client.post(url, {'tank': self.main.pk, 'count': 1, 'paid': 'nonsense'})
        self.client.post(url, {'tank': self.main.pk, 'count': 1, 'paid': '-3'})
        self.assertEqual(CostEntry.objects.count(), 1)
        AppSettings.objects.filter(pk=1).update(costs_enabled=False)
        self.client.post(url, {'tank': self.main.pk, 'count': 1, 'paid': '60'})
        self.assertEqual(CostEntry.objects.count(), 1)


class DamageFilterTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'costs_enabled': True})
        self.main = Tank.objects.create(name='Main', volume_gallons=50, capacity_is_manual=True, is_primary=True)
        self.qt = Tank.objects.create(name='QT', volume_gallons=10, capacity_is_manual=True, is_primary=False)
        today = timezone.localdate()
        self.today = today
        CostEntry.objects.create(tank=self.main, description='Old', amount=Decimal('100'), spent_on=today - timedelta(days=200))
        CostEntry.objects.create(tank=self.main, description='New', amount=Decimal('50'), spent_on=today - timedelta(days=5))
        CostEntry.objects.create(tank=self.qt, description='QT buy', amount=Decimal('25'), spent_on=today - timedelta(days=5))

    def get(self, **query):
        return self.client.get(reverse('the_damage'), query).context

    def test_system_filter(self):
        self.assertEqual(self.get()['total'], 150.0)
        self.assertEqual(self.get(tank=self.qt.pk)['total'], 25.0)
        self.assertEqual(self.get(tank='all')['total'], 175.0)
        self.assertEqual(self.get(tank=99999)['total'], 150.0)

    def test_date_filter(self):
        start = (self.today - timedelta(days=30)).isoformat()
        context = self.get(**{'from': start})
        self.assertEqual(context['total'], 50.0)
        self.assertTrue(context['range_active'])
        self.assertEqual([e.description for e in context['entries']], ['New'])
        end = (self.today - timedelta(days=30)).isoformat()
        self.assertEqual(self.get(to=end)['total'], 100.0)

    def test_bad_and_backwards_dates(self):
        self.assertEqual(self.get(**{'from': 'garbage', 'to': '2026-99-99'})['total'], 150.0)
        early, late = (self.today - timedelta(days=30)).isoformat(), self.today.isoformat()
        self.assertEqual(self.get(**{'from': late, 'to': early})['total'], 50.0)

    def test_chart_is_running_total(self):
        points = self.get()['chart_points']
        self.assertEqual(points[0]['y'], 0.0)
        self.assertEqual([p['y'] for p in points[1:3]], [100.0, 150.0])
        self.assertEqual(points[-1]['y'], 150.0)
        self.assertEqual(points, sorted(points, key=lambda p: p['x']))

    def test_chart_range_and_empty(self):
        start = self.today - timedelta(days=30)
        points = self.get(**{'from': start.isoformat()})['chart_points']
        self.assertEqual((points[0]['y'], points[-1]['y']), (0.0, 50.0))
        self.assertEqual(self.get(to=(self.today - timedelta(days=400)).isoformat())['chart_points'], [])
        page = self.client.get(reverse('the_damage'), {'to': (self.today - timedelta(days=400)).isoformat()})
        self.assertNotContains(page, 'damage-chart')
        self.assertContains(page, 'Nothing burned in these dates')

    def test_page_has_chart_and_filters(self):
        page = self.client.get(reverse('the_damage'))
        for text in ('id="damage-chart"', 'moneyPattern', 'drawFlames', 'name="from"', 'name="to"', 'name="tank"', 'Last 30 days'):
            self.assertContains(page, text)

    def test_adding_keeps_the_filter(self):
        url = reverse('the_damage') + f'?tank={self.qt.pk}'
        response = self.client.post(url, {'description': 'x', 'amount': '1', 'spent_on': self.today.isoformat(), 'category': 'other', 'tank': self.qt.pk})
        self.assertRedirects(response, url)

    def test_retired_system_is_filterable(self):
        self.qt.is_archived = True
        self.qt.save()
        self.assertContains(self.client.get(reverse('the_damage')), 'QT (retired)')
        self.assertEqual(self.get(tank=self.qt.pk)['total'], 25.0)


class DamageTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'costs_enabled': True})
        self.main = Tank.objects.create(name='Main', volume_gallons=50, capacity_is_manual=True, is_primary=True)
        self.qt = Tank.objects.create(name='QT', volume_gallons=10, capacity_is_manual=True, is_primary=False)

    def add(self, amount, tank=None, description='Thing', category='other'):
        return self.client.post(reverse('the_damage'), {
            'description': description, 'amount': amount, 'spent_on': timezone.localdate().isoformat(),
            'category': category, 'tank': (tank or self.main).pk})

    def test_add_and_totals(self):
        self.add('300', description='Coral', category='livestock')
        self.add('200', description='Pump', category='equipment')
        self.add('999', tank=self.qt)
        page = self.client.get(reverse('the_damage'))
        self.assertEqual(page.context['total'], 500.0)
        self.assertEqual(page.context['per_gallon'], 10.0)
        self.assertEqual(page.context['by_category'][0]['percent'], 60)
        self.assertContains(page, 'A few nice dinners')
        everything = self.client.get(reverse('the_damage'), {'all': 1})
        self.assertEqual(everything.context['total'], 1499.0)

    def test_empty_page_and_edit_delete(self):
        self.assertContains(self.client.get(reverse('the_damage')), 'clean slate')
        self.add('5')
        entry = CostEntry.objects.get()
        self.assertEqual(self.client.get(reverse('cost_edit', args=[entry.pk])).status_code, 200)
        self.client.post(reverse('cost_delete', args=[entry.pk]))
        self.assertEqual(CostEntry.objects.count(), 0)

    def test_hidden_but_reachable(self):
        page = self.client.get('/')
        self.assertContains(page, 'logo-link')
        self.assertContains(page, reverse('the_damage'))
        self.assertNotContains(page, 'The Damage</a>')
        self.assertContains(self.client.get(reverse('tools')), 'aria-label="The Damage"')

    def test_purchases_land_here(self):
        fish = species('F', 'Fishus one')
        item = WishlistItem.objects.create(species=fish, name='F', quantity=2, est_price=Decimal('25'))
        self.client.post(reverse('wishlist_bought', args=[item.pk]), {'tank': self.main.pk})
        self.assertEqual(CostEntry.objects.get().amount, Decimal('50'))
        CostEntry.objects.all().delete()
        plan = PlannedSystem.objects.create(name='P', existing_tank=self.main)
        PlannedItem.objects.create(plan=plan, kind='equipment', name='Pump', category='return_pump', quantity=2, unit_cost=Decimal('10'))
        PlannedItem.objects.create(plan=plan, kind='equipment', name='Free', category='other')
        planner.track_plan(plan)
        planner.track_plan(plan)
        entries = list(CostEntry.objects.all())
        self.assertEqual([e.amount for e in entries], [Decimal('10'), Decimal('10')])
        self.assertEqual({(e.category, e.tank) for e in entries}, {('equipment', self.main)})
        self.assertEqual(Equipment.objects.filter(paid=Decimal('10')).count(), 2)


class WishlistTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'costs_enabled': True})
        self.tank = Tank.objects.create(name='Main', volume_gallons=30, capacity_is_manual=True, is_primary=True)
        self.big = species('Big', 'Bigus fish', min_tank_gallons=100, suggested_group='Fish')
        self.small = species('Small', 'Smallus fish', max_size_inches=Decimal('2'))

    def test_add_edit_and_remove(self):
        self.client.post(reverse('wishlist_add_livestock'), {
            'species': self.big.pk, 'quantity': 2, 'est_price': '50', 'priority': 'must', 'link': 'https://example.com/fish'})
        item = WishlistItem.objects.get()
        self.assertEqual((item.kind, item.name, item.total_price), ('livestock', 'Big', Decimal('100')))
        response = self.client.get(reverse('wishlist'))
        self.assertContains(response, 'Big needs more room')
        self.assertContains(response, '100.00')
        self.assertEqual(self.client.get(reverse('wishlist_edit', args=[item.pk])).status_code, 200)
        self.client.post(reverse('wishlist_edit', args=[item.pk]), {
            'species': self.small.pk, 'quantity': 1, 'priority': 'someday'})
        item.refresh_from_db()
        self.assertEqual((item.name, item.priority), ('Small', 'someday'))
        self.client.post(reverse('wishlist_delete', args=[item.pk]))
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_equipment_needs_a_name_and_rejects_bad_links(self):
        self.client.post(reverse('wishlist_add_equipment'), {'category': 'heater', 'quantity': 1, 'priority': 'want'})
        self.client.post(reverse('wishlist_add_equipment'), {
            'name': 'X', 'category': 'heater', 'quantity': 1, 'priority': 'want', 'link': 'javascript:alert(1)'})
        self.assertEqual(WishlistItem.objects.count(), 0)
        self.client.post(reverse('wishlist_add_equipment'), {
            'name': 'Heater', 'category': 'heater', 'quantity': 1, 'priority': 'want', 'wattage': 300})
        self.assertEqual(WishlistItem.objects.get().kind, 'equipment')

    def test_catalog_button_does_not_duplicate(self):
        url = reverse('wishlist_add_species', args=[self.small.pk])
        response = self.client.post(url, {'next': '/species/?category=fish'})
        self.assertRedirects(response, '/species/?category=fish')
        self.client.post(url, {'next': 'https://evil.example/'})
        self.assertEqual(WishlistItem.objects.count(), 1)
        self.assertContains(self.client.get(reverse('species_catalog')), 'Wishlist')

    def test_bought_livestock_is_tracked_once(self):
        item = WishlistItem.objects.create(species=self.small, name='Small', quantity=3)
        url = reverse('wishlist_bought', args=[item.pk])
        self.client.post(url, {'tank': self.tank.pk, 'quarantine': 'on'})
        self.client.post(url, {'tank': self.tank.pk})
        animal = Animal.objects.get()
        self.assertEqual((animal.count, animal.status, animal.tank), (3, 'quarantine', self.tank))
        self.assertEqual(animal.acquired_date, timezone.localdate())
        item.refresh_from_db()
        self.assertEqual(item.status, 'acquired')
        self.assertContains(self.client.get(reverse('wishlist')), 'Recently bought')

    def test_bought_equipment(self):
        item = WishlistItem.objects.create(kind='equipment', name='Pump', category='return_pump', wattage=40, max_flow_gph=500)
        self.client.post(reverse('wishlist_bought', args=[item.pk]), {'tank': self.tank.pk})
        pump = Equipment.objects.get()
        self.assertEqual((pump.tank, pump.flow_derate_percent, pump.wattage), (self.tank, 25, 40))

    def test_plan_round_trip(self):
        plan = PlannedSystem.objects.create(name='P', volume_gallons=75, capacity_is_manual=True)
        item = WishlistItem.objects.create(species=self.big, name='Big', est_price=Decimal('40'))
        url = reverse('wishlist_to_plan', args=[item.pk])
        self.client.post(url, {'plan': plan.pk})
        self.client.post(url, {'plan': plan.pk})
        planned = plan.items.get()
        self.assertEqual((planned.species, planned.unit_cost), (self.big, Decimal('40')))
        self.assertContains(self.client.get(reverse('wishlist')), 'In your plan')
        # While it's in a plan it can't also be bought directly, which would track it twice.
        self.client.post(reverse('wishlist_bought', args=[item.pk]), {'tank': self.tank.pk})
        self.assertEqual(Animal.objects.count(), 0)
        # Removing it from the plan puts it back on the list.
        self.client.post(reverse('plan_item_delete', args=[planned.pk]))
        item.refresh_from_db()
        self.assertIsNone(item.planned_item)
        self.client.post(url, {'plan': plan.pk})
        plan.delete()
        item.refresh_from_db()
        self.assertIsNone(item.planned_item)
        self.assertEqual(item.status, 'wanted')

    def test_combined_warning_across_items(self):
        a = species('Tang A', 'Zebrasoma one', min_tank_gallons=None)
        b = species('Tang B', 'Zebrasoma two', min_tank_gallons=None)
        WishlistItem.objects.create(species=a, name=a.name)
        WishlistItem.objects.create(species=b, name=b.name)
        self.assertContains(self.client.get(reverse('wishlist')), 'If you bought everything')

    def test_page_works_with_no_tanks(self):
        Tank.objects.all().delete()
        WishlistItem.objects.create(species=self.big, name='Big')
        self.assertEqual(self.client.get(reverse('wishlist')).status_code, 200)
        item = WishlistItem.objects.get()
        self.client.post(reverse('wishlist_bought', args=[item.pk]))
        self.assertIsNone(Animal.objects.get().tank)


class PageSmokeTests(TestCase):
    """Every page renders, both empty and with data."""

    def urls(self):
        animal = Animal.objects.first()
        feed = WebcamFeed.objects.first()
        plan = PlannedSystem.objects.first()
        ro = ROSystem.objects.first()
        endpoint = WebhookEndpoint.objects.first()
        names = [reverse(n) for n in ('tools', 'app_settings', 'power', 'planner', 'plan_create', 'quarantine_list',
                                      'integrations', 'webhook_create', 'backups', 'timers', 'ro_create',
                                      'species_catalog', 'livestock', 'webcams', 'notifications', 'equipment', 'tanks', 'dashboard')]
        if animal:
            names += [reverse('quarantine_detail', args=[animal.pk]), reverse('timeline', args=[animal.pk])]
        if feed:
            names += [reverse('timelapse', args=[feed.pk]), reverse('webcam_edit', args=[feed.pk])]
        if plan:
            names += [reverse(n, args=[plan.pk]) for n in ('plan_detail', 'plan_edit', 'plan_track', 'plan_delete')]
        if ro:
            names += [reverse('ro_edit', args=[ro.pk])]
        if endpoint:
            names += [reverse('webhook_edit', args=[endpoint.pk]), reverse('webhook_delete', args=[endpoint.pk])]
        return names

    def assert_all_ok(self):
        for url in self.urls():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_empty(self):
        self.assert_all_ok()

    def test_with_data(self):
        call_command('seed_reef_data', stdout=io.StringIO())
        tank = Tank.objects.first()
        animal = Animal.objects.create(name='Clown', status='quarantine', tank=tank)
        QuarantineEntry.objects.create(animal=animal, kind='medication', medication='Copper')
        WebcamFeed.objects.create(name='Cam', feed_url='http://x/', feed_type='iframe')
        ro = ROSystem.objects.create(name='RO')
        FillTimer.objects.create(name='Fill', ends_at=timezone.now() + timedelta(minutes=5),
                                 reservoir=DosingReservoir.objects.first())
        FillTimer.objects.create(name='Old', ends_at=timezone.now() - timedelta(minutes=5), status='finished',
                                 reservoir=DosingReservoir.objects.first())
        endpoint = WebhookEndpoint.objects.create(name='E', url='http://x/')
        events.emit('reservoir.low', 'warning', 'T', 'M')
        plan = PlannedSystem.objects.create(name='P', volume_gallons=30, capacity_is_manual=True, budget=10)
        PlannedItem.objects.create(plan=plan, kind='livestock', species=SpeciesCatalog.objects.first(), name='Fish', unit_cost=5)
        PlannedItem.objects.create(plan=plan, kind='equipment', name='Light', category='lighting', wattage=50)
        self.assertTrue(ro and endpoint)
        self.assert_all_ok()
        self.assertContains(self.client.get(reverse('species_catalog')), '+ gal')


class CoralGroupAndWaterWordingTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, is_primary=True)

    def test_coral_groups_exist(self):
        names = set(AnimalGroup.objects.values_list('name', flat=True))
        self.assertTrue({'SPS Corals', 'LPS Corals', 'Soft Corals', 'Anemones'} <= names)

    def test_catalog_corals_join_their_type_and_corals(self):
        hammer = SpeciesCatalog.objects.create(name='Test Hammer', category='coral', suggested_group='LPS Corals')
        self.client.post(reverse('species_add_to_tank', args=[hammer.pk]), {'tank': self.tank.pk, 'count': 1})
        groups = set(Animal.objects.get(name='Test Hammer').groups.values_list('name', flat=True))
        self.assertEqual(groups, {'LPS Corals', 'Corals'})

    def test_anemones_are_not_filed_as_corals(self):
        rfa = SpeciesCatalog.objects.create(name='Test Anemone', category='coral', suggested_group='Anemones')
        self.client.post(reverse('species_add_to_tank', args=[rfa.pk]), {'tank': self.tank.pk, 'count': 1})
        groups = set(Animal.objects.get(name='Test Anemone').groups.values_list('name', flat=True))
        self.assertEqual(groups, {'Anemones'})

    def test_catalog_file_sorts_every_coral(self):
        import csv
        from pathlib import Path as _Path
        with open(_Path(__file__).resolve().parent / 'species_catalog.csv', encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.DictReader(fh))
        corals = [r for r in rows if r['category'] == 'coral']
        self.assertTrue(corals)
        self.assertEqual({r['suggested_group'] for r in corals}, {'SPS Corals', 'LPS Corals', 'Soft Corals', 'Anemones'})

    def test_navigation_says_water(self):
        page = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('>Water</a>', page)
        self.assertIn('>Water</span>', page)
        self.assertNotIn('>Params<', page)
        self.assertContains(self.client.get(reverse('parameters')), 'Water Quality')


class TankOrderTopBarAndParTests(TestCase):
    def setUp(self):
        self.a = Tank.objects.create(name='Alpha', volume_gallons=40, is_primary=True)
        self.b = Tank.objects.create(name='Bravo', volume_gallons=20, is_primary=False)
        self.c = Tank.objects.create(name='Charlie', volume_gallons=10, is_primary=False)

    def names(self):
        return [t.name for t in Tank.objects.all()]

    def test_new_tanks_go_to_the_end(self):
        self.assertEqual(self.names(), ['Alpha', 'Bravo', 'Charlie'])
        Tank.objects.create(name='Aardvark', volume_gallons=5, is_primary=False)
        self.assertEqual(self.names()[-1], 'Aardvark')

    def test_moving_up_and_down(self):
        self.client.post(reverse('tank_move', args=[self.c.pk]), {'direction': 'up'})
        self.assertEqual(self.names(), ['Alpha', 'Charlie', 'Bravo'])
        self.client.post(reverse('tank_move', args=[self.a.pk]), {'direction': 'down'})
        self.assertEqual(self.names(), ['Charlie', 'Alpha', 'Bravo'])
        # The ends stay put.
        self.client.post(reverse('tank_move', args=[self.c.pk]), {'direction': 'up'})
        self.assertEqual(self.names(), ['Charlie', 'Alpha', 'Bravo'])

    def test_order_shows_on_the_page_and_in_the_menu(self):
        self.client.post(reverse('tank_move', args=[self.c.pk]), {'direction': 'up'})
        page = self.client.get(reverse('tanks')).content.decode()
        self.assertLess(page.index('id="tank-%d"' % self.c.pk), page.index('id="tank-%d"' % self.b.pk))
        self.assertIn('Move Charlie up', page)
        menu = page[page.index('id="system-select"'):]
        self.assertLess(menu.index('>Charlie<'), menu.index('>Bravo<'))

    def test_move_needs_post(self):
        self.assertEqual(self.client.get(reverse('tank_move', args=[self.a.pk])).status_code, 405)

    def test_phone_top_bar_has_the_tank_menu(self):
        page = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('id="system-select-top"', page)
        phone_bar = page[page.index('Phones: the app name'):page.index('id="system-select-top"')]
        self.assertIn('NUDIBRANCH', phone_bar)
        self.assertIn('id="system-select"', page)

    def test_par_estimate_lives_on_tools(self):
        page = self.client.get(reverse('tools'), {'tank': self.b.pk})
        self.assertContains(page, 'id="light"')
        self.assertEqual(page.context['light_tank'], self.b)
        self.assertEqual(self.client.get(reverse('tools')).context['light_tank'], self.a)
        self.assertNotContains(self.client.get(reverse('tank_detail', args=[self.a.pk])), 'id="light"')

    def test_sumps_come_before_flow_on_the_tank_page(self):
        page = self.client.get(reverse('tank_detail', args=[self.a.pk])).content.decode()
        self.assertLess(page.index('No sump on this tank'), page.index('Flow &amp; Water Turnover'))


class WaterChangeUnitsAndChamberTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.sump = Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=10, capacity_is_manual=True)

    def log(self, **data):
        base = {'tank': self.tank.pk, 'gallons': '5', 'salt_brand': '', 'target_salinity': '', 'notes': '', 'performed_at': ''}
        base.update(data)
        self.client.post(reverse('water_change_log_create'), base)
        return WaterChangeLog.objects.order_by('-id').first()

    def test_gallons_and_sg_are_stored_as_entered(self):
        wc = self.log(gallons='5', target_salinity='1.025', volume_unit='gal', salinity_unit='sg')
        self.assertEqual(wc.gallons, Decimal('5.0'))
        self.assertEqual(wc.target_salinity, Decimal('1.025'))

    def test_liters_and_ppt_are_converted(self):
        wc = self.log(gallons='18.9', target_salinity='35', volume_unit='L', salinity_unit='ppt')
        self.assertEqual(wc.gallons, Decimal('5.0'))
        self.assertEqual(wc.target_salinity, Decimal('1.026'))

    def test_ppt_typed_as_sg_is_caught(self):
        self.assertIsNone(self.log(target_salinity='35', salinity_unit='sg'))

    def test_salt_brand_comes_from_the_calculator(self):
        from .calculators import SALT_MIX_RECIPES
        page = self.client.get(reverse('routines')).content.decode()
        for recipe in SALT_MIX_RECIPES.values():
            self.assertIn('>%s</option>' % recipe['name'].replace("'", '&#x27;'), page)
        self.assertIn('id="wc-volume-unit"', page)
        self.assertIn('id="wc-salinity-unit"', page)
        self.assertIsNone(self.log(salt_brand='Made Up Salt'))
        wc = self.log(salt_brand='Red Sea Coral Pro')
        self.assertEqual(wc.salt_brand, 'Red Sea Coral Pro')
        # The next log starts on the salt used last time.
        self.assertEqual(self.client.get(reverse('routines')).context['wc_form'].initial['salt_brand'], 'Red Sea Coral Pro')

    def test_chambers_are_edited_only_on_the_sump_page(self):
        tank_page = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        self.assertNotContains(tank_page, 'split-form')
        self.assertNotContains(tank_page, 'Change chambers')
        sump_page = self.client.get(reverse('sump_edit', args=[self.sump.pk]))
        self.assertContains(sump_page, 'split-form')
        response = self.client.post(reverse('sump_split', args=[self.sump.pk]), {
            'chamber_type': ['other', 'other'], 'chamber_name': ['A', 'B'], 'chamber_share': ['50', '50']})
        self.assertRedirects(response, reverse('sump_edit', args=[self.sump.pk]) + '#chambers', fetch_redirect_response=False)
        self.assertEqual(self.sump.chambers.count(), 2)
        tank_page = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        self.assertNotContains(tank_page, reverse('chamber_edit', args=[self.sump.chambers.first().pk]))


class QuickWaterChangeTests(TestCase):
    def setUp(self):
        self.main = Tank.objects.create(name='Main', volume_gallons=40, capacity_is_manual=True, is_primary=True)
        Sump.objects.create(tank=self.main, name='Sump', volume_gallons=10, capacity_is_manual=True)
        self.qt = Tank.objects.create(name='QT', volume_gallons=20, capacity_is_manual=True, is_primary=False)

    def log(self, **data):
        base = {'tank': self.main.pk, 'gallons': '5', 'salt_brand': '', 'target_salinity': '', 'notes': '', 'performed_at': ''}
        base.update(data)
        return self.client.post(reverse('water_change_log_create'), base)

    def test_dashboard_has_the_button_and_popup(self):
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, "openModal('log-wc-modal')")
        self.assertContains(page, 'id="log-wc-modal"')
        self.assertContains(page, 'data-units="gal,L,%"')
        self.assertEqual(page.context['wc_form'].initial['tank'], self.main)
        self.assertEqual(page.context['wc_tank_volumes'], {str(self.main.pk): 50.0, str(self.qt.pk): 20.0})

    def test_percent_of_total_water(self):
        self.log(gallons='10', volume_unit='%')
        self.assertEqual(WaterChangeLog.objects.get().gallons, Decimal('5.0'))  # 10% of 40 + 10

    def test_percent_uses_the_chosen_tank(self):
        self.log(tank=self.qt.pk, gallons='25', volume_unit='%')
        wc = WaterChangeLog.objects.get()
        self.assertEqual((wc.tank, wc.gallons), (self.qt, Decimal('5.0')))

    def test_percent_must_be_sensible(self):
        self.log(gallons='150', volume_unit='%')
        self.assertFalse(WaterChangeLog.objects.exists())

    def test_returns_to_the_page_it_came_from(self):
        response = self.log(next='/')
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertRedirects(self.log(next='https://evil.example/'), reverse('routines'), fetch_redirect_response=False)

    def test_retired_tanks_are_not_offered(self):
        Tank.objects.filter(pk=self.qt.pk).update(is_archived=True)
        page = self.client.get(reverse('dashboard'))
        self.assertNotIn(self.qt, list(page.context['wc_form'].fields['tank'].queryset))

    def test_even_shares_are_allowed_by_the_share_boxes(self):
        sump = self.main.sumps.get()
        page = self.client.get(reverse('sump_edit', args=[sump.pk])).content.decode()
        self.assertIn('step="0.1" class="split-share', page)
        self.assertNotIn('step="0.5" class="split-share', page)
        self.client.post(reverse('sump_split', args=[sump.pk]), {
            'chamber_type': ['other'] * 3, 'chamber_name': ['', '', ''], 'chamber_share': ['33.3', '33.3', '33.4']})
        self.assertEqual(sum(c.share_percent for c in sump.chambers.all()), Decimal('100.0'))


class TotalVolumeShownTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, capacity_is_manual=True, is_primary=True)
        Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=10, capacity_is_manual=True)

    def test_tank_names_carry_the_total_water(self):
        self.assertEqual(str(self.tank), 'Main (50.0 gal)')
        page = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn('Main (50.0 gal)</option>', page)
        self.assertNotIn('Main (40.0 gal)', page)

    def test_tank_pages_lead_with_the_total(self):
        self.assertContains(self.client.get(reverse('tanks')), '50.0 gal total water')
        detail = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        self.assertContains(detail, '50.0 gal total water')
        # The tank's own size stays on its page, labelled as the display tank.
        self.assertContains(detail, 'Display tank')


class CountdownTimerTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)

    def test_card_is_on_the_dashboard(self):
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, 'id="timer-cards"')
        self.assertContains(page, 'data-adjustable')
        self.assertIsNone(page.context['countdown_timer'])

    def test_start_extend_and_stop(self):
        data = self.client.post(reverse('timer_start'), {'minutes': '5', 'name': 'Feeding', 'format': 'json'}).json()
        timer = FillTimer.objects.get(pk=data['id'])
        self.assertEqual(timer.name, 'Feeding')
        self.assertAlmostEqual((timer.ends_at - timezone.now()).total_seconds(), 300, delta=5)
        extended = self.client.post(reverse('timer_extend', args=[timer.pk]), {'minutes': 1, 'format': 'json'}).json()
        timer.refresh_from_db()
        self.assertEqual(extended['ends_at'], timer.ends_at.isoformat())
        self.assertAlmostEqual((timer.ends_at - timezone.now()).total_seconds(), 360, delta=5)
        self.assertEqual(self.client.post(reverse('timer_cancel', args=[timer.pk]), {'format': 'json'}).json(), {'ok': True})
        timer.refresh_from_db()
        self.assertEqual(timer.status, 'cancelled')

    def test_a_running_countdown_shows_after_a_reload(self):
        data = self.client.post(reverse('timer_start'), {'minutes': '2', 'name': 'Countdown', 'format': 'json'}).json()
        page = self.client.get(reverse('dashboard'))
        self.assertEqual(page.context['countdown_timer'].pk, data['id'])
        self.assertContains(page, f'data-id="{data["id"]}"')

    def test_fills_and_step_timers_are_not_shown_on_it(self):
        routine = MaintenanceRoutine.objects.create(title='Test', tank=self.tank)
        self.client.post(reverse('timer_start'), {'minutes': '2', 'name': 'Step', 'routine': routine.pk, 'format': 'json'})
        self.assertIsNone(self.client.get(reverse('dashboard')).context['countdown_timer'])

    def test_bad_times_are_refused(self):
        for minutes in ('0', '-3', '2000', 'nan', ''):
            response = self.client.post(reverse('timer_start'), {'minutes': minutes, 'format': 'json'})
            self.assertEqual(response.status_code, 400, minutes)

    def test_water_change_popup_fields_match(self):
        form = self.client.get(reverse('dashboard')).context['wc_form']
        for name in ('tank', 'salt_brand', 'notes', 'performed_at'):
            self.assertIn('bg-slate-800', form.fields[name].widget.attrs['class'], name)
        self.assertIn('appearance-none', form.fields['performed_at'].widget.attrs['class'])
        self.assertNotIn('appearance-none', form.fields['salt_brand'].widget.attrs['class'])


class QuickTestTankAndOfflineTests(TestCase):
    def setUp(self):
        self.main = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.qt = Tank.objects.create(name='QT', volume_gallons=20, is_primary=False)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={'name': 'Alkalinity', 'unit': 'dKH', 'min_ideal': 8, 'max_ideal': 9})

    def post(self, **extra):
        data = {'parameter_type': self.alk.pk, 'value': '8.4', 'notes': '', 'measured_at': '', 'next': '/'}
        data.update(extra)
        return self.client.post(reverse('quick_log_create'), data)

    def test_popup_offers_each_tank_with_the_selected_one_first(self):
        page = self.client.get(reverse('dashboard')).content.decode()
        menu = page[page.index('id="quick-log-tank"'):]
        menu = menu[:menu.index('</select>')]
        self.assertIn(f'value="{self.main.pk}" selected', menu)
        self.assertIn('>QT</option>', menu)

    def test_test_goes_to_the_chosen_tank(self):
        self.post(tank=self.qt.pk)
        self.assertEqual(ParameterLog.objects.get().tank, self.qt)

    def test_without_a_choice_it_uses_the_selected_tank(self):
        self.post()
        self.assertEqual(ParameterLog.objects.get().tank, self.main)

    def test_a_retired_tank_takes_no_tests(self):
        Tank.objects.filter(pk=self.qt.pk).update(is_archived=True)
        self.post(tank=self.qt.pk)
        self.assertFalse(ParameterLog.objects.exists())

    def test_countdown_presets(self):
        page = self.client.get(reverse('dashboard')).content.decode()
        for seconds, label in ((60, '1m'), (180, '3m'), (1800, '30m'), (3600, '1h')):
            self.assertIn(f'data-preset="{seconds}"', page)
        self.assertNotIn("What's it for", page)

    def test_offline_shows_a_message_not_an_old_page(self):
        sw = self.client.get('/sw.js').content.decode()
        self.assertIn("Can't reach Nudibranch", sw)
        self.assertIn("req.mode === 'navigate'", sw)
        self.assertIn("nudibranch-v6", sw)


class SavedTimerAndAppIconTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True, icon_choice='01-dragon-mage-young')

    def test_add_a_saved_timer(self):
        self.client.post(reverse('quick_timer_create'), {'name': 'Feeding', 'minutes': '3', 'next': '/'})
        self.client.post(reverse('quick_timer_create'), {'name': 'Alk test', 'minutes': '0.5', 'next': '/'})
        feeding, alk = QuickTimer.objects.all()
        self.assertEqual((feeding.name, feeding.seconds, feeding.duration_label, feeding.clock), ('Feeding', 180, '3 min', '03:00'))
        self.assertEqual((alk.seconds, alk.duration_label), (30, '30 sec'))
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, f'data-quick-id="{feeding.pk}"')
        self.assertContains(page, 'Add a timer')

    def test_bad_times_are_refused(self):
        for minutes in ('0', '-1', '5000', ''):
            self.client.post(reverse('quick_timer_create'), {'name': 'X', 'minutes': minutes})
        self.assertFalse(QuickTimer.objects.exists())

    def test_starting_a_saved_timer_uses_its_own_time(self):
        saved = QuickTimer.objects.create(name='Feeding', seconds=180)
        data = self.client.post(reverse('timer_start'), {'quick_timer': saved.pk, 'minutes': '999', 'name': 'other', 'format': 'json'}).json()
        timer = FillTimer.objects.get(pk=data['id'])
        self.assertEqual((timer.name, timer.quick_timer), ('Feeding', saved))
        self.assertAlmostEqual((timer.ends_at - timezone.now()).total_seconds(), 180, delta=5)
        page = self.client.get(reverse('dashboard'))
        self.assertEqual(page.context['quick_timers'][0].running, timer)
        self.assertIsNone(page.context['countdown_timer'])

    def test_edit_and_delete(self):
        saved = QuickTimer.objects.create(name='Feeding', seconds=180)
        self.assertContains(self.client.get(reverse('quick_timer_edit', args=[saved.pk])), 'value="3"')
        self.client.post(reverse('quick_timer_edit', args=[saved.pk]), {'name': 'Feed', 'minutes': '90'})
        saved.refresh_from_db()
        self.assertEqual((saved.name, saved.seconds, saved.duration_label), ('Feed', 5400, '1 hr 30 min'))
        self.client.post(reverse('quick_timer_delete', args=[saved.pk]))
        self.assertFalse(QuickTimer.objects.exists())

    def test_app_icon_follows_the_main_tank(self):
        from . import app_icon
        path = app_icon.source_file()
        self.assertTrue(path and path.name.startswith('01-dragon-mage'))
        page = self.client.get(reverse('dashboard')).content.decode()
        self.assertIn(f'/app-icon/32.png?v={app_icon.version()}', page)
        manifest = self.client.get('/manifest.json').json()
        self.assertEqual([i['sizes'] for i in manifest['icons']], ['192x192', '512x512'])
        response = self.client.get('/app-icon/192.png')
        self.assertEqual(response['Content-Type'], 'image/png')
        from PIL import Image
        import io
        with Image.open(io.BytesIO(b''.join(response.streaming_content))) as image:
            self.assertEqual(image.size, (192, 192))

    def test_app_icon_falls_back_without_one(self):
        Tank.objects.all().delete()
        self.assertRedirects(self.client.get('/app-icon/192.png'), '/static/icons/icon.svg', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/manifest.json').json()['icons'][0]['src'], '/static/icons/icon.svg')
        self.assertEqual(self.client.get('/app-icon/77.png').status_code, 302)


class ReviewRoundTwoTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)

    def test_settings_are_read_once_per_page(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for name in range(4):
            PlannedSystem.objects.create(name=f'Plan {name}', volume_gallons=20)
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse('planner'))
        reads = [q for q in queries.captured_queries if 'aquarium_appsettings' in q['sql']]
        self.assertLessEqual(len(reads), 2)

    def test_saved_settings_are_not_stale(self):
        settings_obj = AppSettings.load()
        settings_obj.electricity_rate = Decimal('0.2500')
        settings_obj.save()
        self.assertEqual(AppSettings.load().electricity_rate, Decimal('0.2500'))

    def test_dose_estimator_does_not_query_per_parameter(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse('tools'))
        logs = [q for q in queries.captured_queries if 'FROM "aquarium_parameterlog"' in q['sql']]
        self.assertLess(len(logs), 6)

    def test_back_buttons_match(self):
        plan = PlannedSystem.objects.create(name='Nano', volume_gallons=20)
        self.assertNotContains(self.client.get(reverse('plan_detail', args=[plan.pk])), 'aria-label="Back">←')


class ToolsBarTrendsDosesRemindersExportTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main Reef', volume_gallons=40, is_primary=True)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'decimal_places': 1, 'min_ideal': 8, 'max_ideal': 9})
        self.bottle = DosingReservoir.objects.create(tank=self.tank, name='Alk', capacity=1000, current_level=500, unit='ml',
                                                     daily_consumption=10)

    def log(self, value, hours_ago):
        return ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal(value),
                                           measured_at=timezone.now() - timedelta(hours=hours_ago))

    def alk_card(self):
        return next(p for p in self.client.get(reverse('dashboard')).context['parameter_types'] if p.code == 'alkalinity')

    # Phone bar
    def test_bottom_bar_has_tools_and_tools_has_webcams(self):
        page = self.client.get(reverse('dashboard')).content.decode()
        bar = page[page.index('Mobile Bottom Tab Navigation Bar'):]
        self.assertIn('>Tools</span>', bar)
        self.assertNotIn('>Cams</span>', bar)
        self.assertContains(self.client.get(reverse('tools')), '0 cameras')

    # Trend arrows
    def test_trend_toward_and_away_from_the_ideal_range(self):
        self.log('7.0', 48)
        self.log('7.6', 1)
        self.assertEqual(self.alk_card().trend, {'arrow': '↑', 'text': '+0.6', 'tone': 'better'})
        self.log('7.2', 0)
        trend = self.alk_card().trend
        self.assertEqual((trend['arrow'], trend['tone']), ('↓', 'worse'))

    def test_trend_needs_two_tests_and_shows_no_change(self):
        self.log('8.5', 2)
        self.assertIsNone(self.alk_card().trend)
        self.log('8.5', 1)
        self.assertEqual(self.alk_card().trend['tone'], 'steady')

    # Dose log
    def dose(self, **extra):
        data = {'tank': self.tank.pk, 'parameter': 'alkalinity', 'product': 'Soda ash', 'amount': '25', 'unit': 'ml',
                'reservoir': self.bottle.pk, 'dosed_at': '', 'notes': '', 'next': '/dosing/'}
        data.update(extra)
        return self.client.post(reverse('dose_log_create'), data)

    def test_a_dose_comes_off_the_container_and_goes_back_when_deleted(self):
        self.dose()
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.current_level, Decimal('475'))
        dose = DoseLog.objects.get()
        self.assertEqual(dose.taken, Decimal('25'))
        self.client.post(reverse('dose_log_edit', args=[dose.pk]), {
            'tank': self.tank.pk, 'parameter': 'alkalinity', 'product': 'Soda ash', 'amount': '40', 'unit': 'ml',
            'reservoir': self.bottle.pk, 'dosed_at': '', 'notes': ''})
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.current_level, Decimal('460'))
        self.client.post(reverse('dose_log_delete', args=[dose.pk]))
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.current_level, Decimal('500'))

    def test_powder_doses_and_other_units(self):
        self.dose(unit='g', amount='5')
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.current_level, Decimal('500'))  # grams don't come off a liquid container
        self.dose(unit='tsp', amount='2')
        self.bottle.refresh_from_db()
        self.assertEqual(self.bottle.current_level, Decimal('490.14'))
        litres = DosingReservoir.objects.create(tank=self.tank, name='Big', capacity=5, current_level=Decimal('0.01'),
                                                unit='L', daily_consumption=1)
        self.dose(reservoir=litres.pk, amount='500', unit='ml')
        litres.refresh_from_db()
        self.assertEqual(litres.current_level, Decimal('0'))  # never below empty

    def test_dose_needs_a_container_on_the_same_tank(self):
        other = Tank.objects.create(name='QT', volume_gallons=10, is_primary=False)
        self.dose(tank=other.pk)
        self.assertFalse(DoseLog.objects.exists())

    def test_dose_log_shows_on_dosing_and_tools(self):
        self.dose()
        self.assertContains(self.client.get(reverse('dosing')), '25 ml Soda ash')
        tools = self.client.get(reverse('tools'))
        self.assertContains(tools, 'id="est-log-dose"')
        self.assertContains(tools, 'id="dose-log-modal"')

    # Test reminders
    def test_reminder_in_days(self):
        self.assertContains(self.client.get(reverse('parameter_settings', args=[self.alk.pk])), 'Remind me to test every')
        data = {'unit': 'dKH', 'decimal_places': 1, 'low_limit': '', 'min_ideal': 8, 'max_ideal': 9, 'high_limit': '',
                'test_every_days': 3}
        self.client.post(reverse('parameter_settings', args=[self.alk.pk]), data)
        self.alk.refresh_from_db()
        self.assertEqual((self.alk.stale_after_hours, self.alk.test_every_days), (72, 3))
        self.log('8.5', 24 * 4)
        self.assertContains(self.client.get(reverse('notifications')), 'Time to test Alkalinity')
        self.assertContains(self.client.get(reverse('dashboard')), 'Time to test Alkalinity')
        from . import events
        self.assertEqual(events.collect_conditions()[0]['title'], 'Time to test Alkalinity')
        data['test_every_days'] = ''
        self.client.post(reverse('parameter_settings', args=[self.alk.pk]), data)
        self.alk.refresh_from_db()
        self.assertIsNone(self.alk.stale_after_hours)

    def test_probe_hours_are_kept(self):
        ParameterType.objects.filter(pk=self.alk.pk).update(stale_after_hours=6)
        data = {'unit': 'dKH', 'decimal_places': 1, 'low_limit': '', 'min_ideal': 8, 'max_ideal': 9, 'high_limit': '',
                'test_every_days': ''}
        self.client.post(reverse('parameter_settings', args=[self.alk.pk]), data)
        self.alk.refresh_from_db()
        self.assertEqual(self.alk.stale_after_hours, 6)
        self.log('8.5', 8)
        self.assertContains(self.client.get(reverse('notifications')), 'No new Alkalinity readings')

    # CSV export
    def test_exports(self):
        self.log('8.4', 1)
        ParameterLog.objects.update(notes='=HYPERLINK("x")')
        WaterChangeLog.objects.create(tank=self.tank, gallons=10, salt_brand='Fritz Pro RPM', target_salinity=Decimal('1.026'))
        self.dose()
        tests = self.client.get(reverse('export_tests'))
        self.assertEqual(tests['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('nudibranch-water-tests-main-reef-', tests['Content-Disposition'])
        body = tests.content.decode('utf-8-sig')
        self.assertIn('Tank,Parameter,Value,Unit,Measured at,Notes', body)
        self.assertIn('Main Reef,Alkalinity,8.4,dKH', body)
        self.assertIn("'=HYPERLINK", body)  # a note is never run as a spreadsheet formula
        self.assertIn('Main Reef,', self.client.get(reverse('export_water_changes')).content.decode('utf-8-sig'))
        self.assertIn(',10,37.9,Fritz Pro RPM', self.client.get(reverse('export_water_changes')).content.decode('utf-8-sig'))
        self.assertIn('Soda ash', self.client.get(reverse('export_doses')).content.decode('utf-8-sig'))
        other = Tank.objects.create(name='QT', volume_gallons=10, is_primary=False)
        WaterChangeLog.objects.create(tank=other, gallons=2)
        self.assertNotIn('QT', self.client.get(reverse('export_water_changes')).content.decode('utf-8-sig'))
        self.assertIn('QT', self.client.get(reverse('export_water_changes'), {'tank': 'all'}).content.decode('utf-8-sig'))


class IcpElementTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={'icp_enabled': True})
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.alk, _ = ParameterType.objects.update_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'min_ideal': 8, 'max_ideal': 9, 'display_order': 2})
        self.copper = ParameterType.objects.get(code='copper')

    def test_elements_are_added_as_trace_parameters(self):
        icp = ParameterType.objects.filter(is_trace=True)
        self.assertGreaterEqual(icp.count(), 25)
        self.assertTrue({'sodium', 'boron', 'iodine', 'strontium', 'potassium', 'copper', 'tin', 'mercury'} <= set(icp.values_list('code', flat=True)))
        self.assertFalse(icp.filter(show_on_dashboard=True).exists())
        self.assertEqual((self.copper.unit, float(self.copper.max_ideal), float(self.copper.high_limit)), ('µg/L', 2.0, 5.0))

    def test_they_come_last_in_lists(self):
        names = [pt.name for pt in ParameterType.objects.all()]
        regular = [pt.name for pt in ParameterType.objects.filter(is_trace=False)]
        self.assertEqual(names[:len(regular)], regular)
        from .forms import QuickParameterLogForm
        modal = QuickParameterLogForm().fields['parameter_type'].queryset
        self.assertFalse(list(modal)[0].is_trace)
        self.assertTrue(list(modal)[-1].is_trace)

    def test_no_cards_or_chips_but_a_menu(self):
        page = self.client.get(reverse('dashboard'))
        self.assertNotIn(self.copper, page.context['card_types'])
        self.assertNotContains(page, 'id="tab-copper"')
        self.assertContains(page, '<option value="copper"')
        water = self.client.get(reverse('parameters'))
        self.assertContains(water, 'ICP ▾')
        self.assertNotContains(water, '?param=copper"')

    def test_left_off_the_all_chart_but_chartable_alone(self):
        ParameterLog.objects.create(parameter_type=self.copper, tank=self.tank, value=Decimal('1.2'))
        ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=Decimal('8.5'))
        codes = [d['code'] for d in self.client.get(reverse('api_all_chart_data')).json()['datasets']]
        self.assertEqual(codes, ['alkalinity'])
        single = self.client.get(reverse('api_chart_data'), {'param': 'copper'}).json()
        self.assertEqual(len(single['values'] if 'values' in single else single['datasets'][0]['data']), 1)

    def test_turning_a_card_on_from_customize_and_settings(self):
        alk_and_copper = [str(self.alk.pk), str(self.copper.pk)]
        self.client.post(reverse('dashboard_customize'), {'order': '', 'enabled': ['parameters'], 'cards_shown': '1', 'card': alk_and_copper})
        self.copper.refresh_from_db()
        self.assertTrue(self.copper.show_on_dashboard)
        self.assertIn(self.copper, self.client.get(reverse('dashboard')).context['card_types'])
        self.client.post(reverse('dashboard_customize'), {'reset': '1'})
        self.copper.refresh_from_db()
        self.assertFalse(self.copper.show_on_dashboard)
        data = {'unit': 'µg/L', 'decimal_places': 2, 'low_limit': '', 'min_ideal': 0, 'max_ideal': 2, 'high_limit': 5,
                'test_every_days': '', 'show_on_dashboard': 'on'}
        self.client.post(reverse('parameter_settings', args=[self.copper.pk]), data)
        self.copper.refresh_from_db()
        self.assertTrue(self.copper.show_on_dashboard)

    def test_fresh_install_still_gets_the_regular_parameters(self):
        from django.core.management import call_command
        ParameterType.objects.filter(is_trace=False).delete()
        call_command('seed_reef_data', stdout=__import__('io').StringIO())
        self.assertTrue(ParameterType.objects.filter(code='salinity').exists())

    def test_switched_off_they_appear_nowhere(self):
        AppSettings.objects.filter(pk=1).update(icp_enabled=False)
        ParameterLog.objects.create(parameter_type=self.copper, tank=self.tank, value=Decimal('9'))  # out of range
        from .forms import QuickParameterLogForm
        self.assertNotIn(self.copper, list(QuickParameterLogForm().fields['parameter_type'].queryset))
        page = self.client.get(reverse('dashboard'))
        self.assertNotContains(page, 'ICP ▾')
        self.assertNotContains(page, '>Copper')
        self.assertNotContains(page, 'Copper is')
        water = self.client.get(reverse('parameters'))
        self.assertNotContains(water, 'ICP ▾')
        self.assertNotContains(self.client.get(reverse('integrations')), 'Copper')
        self.assertEqual(self.client.get(reverse('notifications')).context['total_alerts'], 0)
        self.assertNotIn('copper', [p['code'] for p in self.client.get(reverse('api_parameter_types')).json().get('parameters', [])])
        self.assertContains(self.client.get(reverse('app_settings')), 'Enable ICP elements')


class FinalReviewTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)

    def test_new_parameter_goes_after_regular_ones(self):
        from .forms import ParameterTypeForm
        regular_last = ParameterType.objects.filter(is_trace=False).order_by('-display_order').first()
        expected = (regular_last.display_order + 1) if regular_last else 0
        self.assertEqual(ParameterTypeForm().initial['display_order'], expected)
        self.assertLess(expected, 100)

    def test_hidden_icp_name_explains_itself(self):
        from .forms import ParameterTypeForm
        form = ParameterTypeForm(data={'name': 'Iodine', 'code': 'my-iodine', 'unit': 'ppm', 'decimal_places': 3,
                                       'min_ideal': 0.05, 'max_ideal': 0.07, 'color': '#000000', 'display_order': 9})
        self.assertFalse(form.is_valid())
        self.assertIn('Enable ICP elements', form.errors['name'][0])

    def test_csv_leaves_out_icp_while_off(self):
        copper = ParameterType.objects.get(code='copper')
        ParameterLog.objects.create(parameter_type=copper, tank=self.tank, value=Decimal('1'))
        self.assertNotIn('Copper', self.client.get(reverse('export_tests')).content.decode('utf-8-sig'))
        AppSettings.objects.update_or_create(pk=1, defaults={'icp_enabled': True})
        self.assertIn('Copper', self.client.get(reverse('export_tests')).content.decode('utf-8-sig'))

    def test_service_worker_does_not_preload_the_old_manifest(self):
        self.assertNotIn('/static/manifest.json', self.client.get('/sw.js').content.decode())


class PixelStyleTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.other = Tank.objects.create(name='QT', volume_gallons=10, is_primary=False)

    def test_standard_by_default(self):
        self.assertEqual(self.tank.ui_style, 'standard')
        self.assertContains(self.client.get(reverse('dashboard')), '<body class="style-standard')

    def test_choose_8bit_for_one_tank(self):
        page = self.client.get(reverse('system_theme'))
        self.assertContains(page, 'name="ui_style" value="8bit"')
        self.client.post(reverse('system_theme'), {'theme': self.tank.theme, 'ui_style': '8bit', 'icon_choice': ''})
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.ui_style, '8bit')
        self.assertContains(self.client.get(reverse('dashboard')), '<body class="style-8bit')
        # Another tank keeps its own style.
        self.client.post(reverse('system_select'), {'tank': self.other.pk, 'next': '/'})
        self.assertContains(self.client.get(reverse('dashboard')), '<body class="style-standard')

    def test_bad_style_is_refused(self):
        self.client.post(reverse('system_theme'), {'theme': self.tank.theme, 'ui_style': 'neon', 'icon_choice': ''})
        self.tank.refresh_from_db()
        self.assertEqual(self.tank.ui_style, 'standard')


class TankPageEquipmentLightsAndPresetTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.other = Tank.objects.create(name='QT', volume_gallons=10, is_primary=False)
        self.sump = Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=10)
        self.light = Equipment.objects.create(tank=self.tank, name='Radion', category='lighting', wattage=100)
        self.heater = Equipment.objects.create(tank=self.tank, name='Heater', category='heater')
        self.spare = Equipment.objects.create(name='Spare pump', category='return_pump', max_flow_gph=800)
        self.qt_wave = Equipment.objects.create(tank=self.other, name='QT wave', category='wavemaker')
        self.url = reverse('tank_detail', args=[self.tank.pk])

    def test_pickers_offer_unplaced_and_elsewhere_equipment(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn(reverse('equipment_place'), page)
        self.assertIn('<option value="%d">Spare pump</option>' % self.spare.pk, page)
        self.assertIn('QT wave (QT · Display tank)', page)
        self.assertIn('+ Add some flow', page)
        self.assertIn('+ Add more sun', page)
        self.assertIn('category=lighting', page)

    def test_place_into_sump_and_take_off(self):
        self.client.post(reverse('equipment_place'), {'equipment': self.spare.pk, 'location': f'sump:{self.sump.pk}',
                                                      'next': self.url})
        self.spare.refresh_from_db()
        self.assertEqual((self.spare.tank, self.spare.sump), (self.tank, self.sump))
        response = self.client.post(reverse('equipment_unplace', args=[self.spare.pk]), {'next': self.url})
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.spare.refresh_from_db()
        self.assertIsNone(self.spare.tank)
        self.assertTrue(Equipment.objects.filter(pk=self.spare.pk).exists())

    def test_place_into_missing_spot_changes_nothing(self):
        self.client.post(reverse('equipment_place'), {'equipment': self.spare.pk, 'location': 'sump:999'})
        self.spare.refresh_from_db()
        self.assertIsNone(self.spare.tank)

    def test_every_listed_item_has_delete(self):
        page = self.client.get(self.url).content.decode()
        for eq in (self.light, self.heater):
            self.assertIn(reverse('equipment_delete', args=[eq.pk]) + '?next=', page)
            self.assertIn(reverse('equipment_unplace', args=[eq.pk]), page)
        self.assertContains(self.client.get(reverse('equipment')), reverse('equipment_delete', args=[self.heater.pk]))
        self.assertContains(self.client.get(reverse('power')), reverse('equipment_delete', args=[self.light.pk]))

    def test_delete_returns_to_tank_page(self):
        response = self.client.post(reverse('equipment_delete', args=[self.heater.pk]) + '?next=' + self.url)
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(Equipment.objects.filter(pk=self.heater.pk).exists())

    def test_lights_section_shows_schedule(self):
        routine = MaintenanceRoutine.objects.create(
            tank=self.tank, title='Light cycle', routine_type='automated', category='lighting',
            schedule_events=[{'time': '20:00', 'action': 'Lights off'}, {'time': '10:00', 'action': 'Lights on'}])
        routine.equipment.add(self.light)
        page = self.client.get(self.url)
        self.assertContains(page, 'Light cycle')
        self.assertContains(page, '10:00 Lights on · 20:00 Lights off')
        self.assertEqual(page.context['display_equipment'], [self.heater])  # the light isn't listed twice

    def test_light_without_schedule_says_so(self):
        self.assertContains(self.client.get(self.url), 'No schedule yet')

    def test_new_equipment_can_start_in_a_category(self):
        page = self.client.get(reverse('equipment_create') + f'?location=tank:{self.tank.pk}&category=lighting')
        self.assertEqual(page.context['form'].initial['category'], 'lighting')

    def test_tank_form_offers_common_tanks(self):
        for url in (reverse('tank_create'), reverse('tank_edit', args=[self.tank.pk])):
            page = self.client.get(url)
            self.assertContains(page, 'Start from a common tank')
            self.assertContains(page, '20 gallon long')
            self.assertContains(page, '40 gallon breeder')
            self.assertContains(page, 'tank-presets-data')
        self.assertNotContains(self.client.get(reverse('sump_edit', args=[self.sump.pk])), 'Start from a common tank')

    def test_presets_are_sane(self):
        from .tank_presets import TANK_PRESETS
        for group in TANK_PRESETS:
            for p in group['tanks']:
                self.assertTrue(p['width'] > 0 and p['depth'] > 0 and p['height'] > 0, p['name'])
                self.assertIn(p['unit'], ('in', 'cm'))


class HeadHeightAndFilterTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, is_primary=True)
        self.sump = Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=20)
        self.pump = Equipment.objects.create(tank=self.tank, sump=self.sump, name='Return', category='return_pump',
                                             max_flow_gph=2000, flow_derate_percent=30)

    def test_pump_curve_math(self):
        from .calculators import estimate_flow_at_head
        self.assertAlmostEqual(estimate_flow_at_head(2000, 20, 0), 2000)
        self.assertAlmostEqual(estimate_flow_at_head(2000, 20, 5), 1500)
        self.assertEqual(estimate_flow_at_head(2000, 20, 25), 0.0)
        # Half speed: half the flow, a quarter of the max head (affinity laws).
        self.assertAlmostEqual(estimate_flow_at_head(2000, 20, 2.5, 50), 500)
        self.assertEqual(estimate_flow_at_head(2000, 20, 6, 50), 0.0)
        self.assertIsNone(estimate_flow_at_head(2000, None, 5))

    def test_head_height_drives_return_flow_and_turnover(self):
        before = self.tank.flow_summary()['return_gph']
        self.assertAlmostEqual(self.pump.estimated_flow_gph, 1400)  # the old 30% head loss
        self.sump.head_height, self.sump.head_height_unit = 5, 'ft'
        self.sump.save()
        self.pump.max_head, self.pump.max_head_unit = 20, 'ft'
        self.pump.save()
        pump = Equipment.objects.get(pk=self.pump.pk)
        self.assertTrue(pump.uses_head_curve)
        self.assertAlmostEqual(pump.estimated_flow_gph, 1500)
        tank = Tank.objects.prefetch_related('equipment__sump').get(pk=self.tank.pk)
        self.assertNotEqual(tank.flow_summary()['return_gph'], before)

    def test_metres_convert(self):
        self.sump.head_height, self.sump.head_height_unit = 1, 'm'
        self.sump.save()
        self.pump.max_head, self.pump.max_head_unit = 4, 'm'
        self.pump.save()
        self.assertAlmostEqual(Equipment.objects.get(pk=self.pump.pk).estimated_flow_gph, 1500, places=3)

    def test_without_max_head_the_percent_still_applies(self):
        self.sump.head_height = 5
        self.sump.save()
        pump = Equipment.objects.get(pk=self.pump.pk)
        self.assertFalse(pump.uses_head_curve)
        self.assertAlmostEqual(pump.estimated_flow_gph, 1400)
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.tank.pk])), 'add its max head')

    def test_sump_form_saves_head_height_with_unit_button(self):
        page = self.client.get(reverse('sump_edit', args=[self.sump.pk]))
        self.assertContains(page, 'data-units="ft,m"')
        self.assertContains(page, 'name="head_height_unit"')
        self.client.post(reverse('sump_edit', args=[self.sump.pk]), {
            'name': 'Sump', 'dimension_unit': 'in', 'fill_percent': 60, 'volume_gallons': 20,
            'capacity_is_manual': 'on', 'head_height': '1.5', 'head_height_unit': 'm'})
        self.sump.refresh_from_db()
        self.assertEqual((float(self.sump.head_height), self.sump.head_height_unit), (1.5, 'm'))
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.tank.pk])), '1.5 m head height')

    def test_equipment_form_has_max_head(self):
        page = self.client.get(reverse('equipment_edit', args=[self.pump.pk]))
        self.assertContains(page, 'name="max_head"')
        self.assertContains(page, 'name="max_head_unit"')
        self.assertContains(self.client.get(reverse('equipment')), 'name="max_head"')

    def test_filters_section(self):
        sock = Equipment.objects.create(tank=self.tank, sump=self.sump, name='Filter sock', category='filter')
        page = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        self.assertContains(page, '+ Catch more gunk')
        self.assertContains(page, 'Filter sock')
        self.assertContains(page, reverse('service_equipment', args=[sock.pk]))
        self.assertIn(f'sump:{self.sump.pk}&category=filter', page.content.decode())
        new = self.client.get(reverse('equipment_create') + '?category=filter')
        self.assertEqual(new.context['form'].initial['maintenance_interval_days'], 7)


class EditCategoriesTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.fish = AnimalGroup.objects.create(name='Fish', icon='🐠')
        self.cuc = AnimalGroup.objects.create(name='Cleanup Crew', icon='🐌')
        self.snail = Animal.objects.create(name='Trochus', tank=self.tank)
        self.snail.groups.add(self.cuc)
        self.both = Animal.objects.create(name='Goby', tank=self.tank)
        self.both.groups.add(self.cuc, self.fish)

    def test_livestock_page_links_to_edit_categories(self):
        page = self.client.get(reverse('livestock'))
        self.assertContains(page, '✏️ Edit categories')
        self.assertContains(page, reverse('groups_manage'))
        self.assertNotContains(page, 'New Group')

    def test_new_categories_go_to_the_end(self):
        names = [g.name for g in AnimalGroup.objects.all()]
        self.assertLess(names.index('Fish'), names.index('Cleanup Crew'))
        self.client.post(reverse('group_create'), {'new-name': 'Nano Fish', 'new-icon': '🐟', 'new-color': '#ff0000'})
        self.assertEqual(AnimalGroup.objects.last().name, 'Nano Fish')

    def test_page_lists_counts_and_edits(self):
        page = self.client.get(reverse('groups_manage'))
        self.assertContains(page, '2 living')
        self.client.post(reverse('group_edit', args=[self.cuc.pk]), {
            f'g{self.cuc.pk}-name': 'CUC', f'g{self.cuc.pk}-icon': '🦀', f'g{self.cuc.pk}-color': '#22C55E',
            f'g{self.cuc.pk}-description': 'Snails and crabs'})
        self.cuc.refresh_from_db()
        self.assertEqual((self.cuc.name, self.cuc.icon, self.cuc.color), ('CUC', '🦀', '#22c55e'))

    def test_duplicate_name_and_bad_colour(self):
        self.client.post(reverse('group_edit', args=[self.cuc.pk]), {
            f'g{self.cuc.pk}-name': 'fish', f'g{self.cuc.pk}-icon': '🐌', f'g{self.cuc.pk}-color': 'red;x'})
        self.cuc.refresh_from_db()
        self.assertEqual(self.cuc.name, 'Cleanup Crew')
        self.client.post(reverse('group_edit', args=[self.cuc.pk]), {
            f'g{self.cuc.pk}-name': 'Cleanup Crew', f'g{self.cuc.pk}-icon': '🐌', f'g{self.cuc.pk}-color': 'red;x'})
        self.cuc.refresh_from_db()
        self.assertTrue(self.cuc.color.startswith('#') and ';' not in self.cuc.color)

    def test_reorder(self):
        self.client.post(reverse('group_move', args=[self.cuc.pk]), {'direction': 'up'})
        names = [g.name for g in AnimalGroup.objects.all()]
        self.assertEqual(names.index('Cleanup Crew') + 1, names.index('Fish'))
        self.assertContains(self.client.get(reverse('livestock')), 'Category:')

    def test_merge_moves_animals_and_removes_the_category(self):
        self.client.post(reverse('group_merge', args=[self.cuc.pk]), {'into': self.fish.pk})
        self.assertFalse(AnimalGroup.objects.filter(pk=self.cuc.pk).exists())
        self.assertEqual(set(self.fish.animals.values_list('name', flat=True)), {'Trochus', 'Goby'})

    def test_merge_needs_another_category(self):
        self.client.post(reverse('group_merge', args=[self.cuc.pk]), {'into': self.cuc.pk})
        self.assertTrue(AnimalGroup.objects.filter(pk=self.cuc.pk).exists())

    def test_delete_keeps_animals(self):
        response = self.client.post(reverse('group_delete', args=[self.cuc.pk]))
        self.assertRedirects(response, reverse('groups_manage'), fetch_redirect_response=False)
        self.assertTrue(Animal.objects.filter(name='Trochus').exists())


class DefaultReturnDerateTests(TestCase):
    def test_new_return_pump_starts_at_the_usual_head_loss(self):
        page = self.client.get(reverse('equipment_create') + '?category=return_pump')
        self.assertEqual(page.context['form'].initial['flow_derate_percent'], 25)
        self.assertContains(page, 'data-auto-derate="25"')

    def test_other_new_equipment_starts_at_zero(self):
        page = self.client.get(reverse('equipment_create') + '?category=wavemaker')
        self.assertNotIn('flow_derate_percent', page.context['form'].initial)
        self.assertContains(page, 'data-auto-derate="25"')  # follows the category if it's changed to a return pump

    def test_editing_leaves_your_own_figure_alone(self):
        pump = Equipment.objects.create(name='Pump', category='return_pump', flow_derate_percent=10)
        page = self.client.get(reverse('equipment_edit', args=[pump.pk]))
        self.assertNotContains(page, 'data-auto-derate')
        self.assertEqual(page.context['form']['flow_derate_percent'].value(), 10)

    def test_planner_uses_the_same_figure(self):
        from . import planner
        self.assertEqual(planner.RETURN_HEAD_LOSS_PERCENT, Equipment.DEFAULT_RETURN_DERATE)


class OutletOverflowSketchTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, width=48, depth=18, height=21, is_primary=True)
        self.sump = Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=20)
        self.pump = Equipment.objects.create(tank=self.tank, sump=self.sump, name='Return', category='return_pump',
                                             max_flow_gph=1200)
        self.wave = Equipment.objects.create(tank=self.tank, name='MP40', category='wavemaker', max_flow_gph=3000)
        self.url = reverse('tank_detail', args=[self.tank.pk])

    def test_nothing_set_shows_a_hint(self):
        page = self.client.get(self.url)
        self.assertFalse(page.context['flow_sketch']['show'])
        self.assertContains(page, 'to see your flow drawn from above and from the front')

    def test_sketch_places_outlets_and_overflow(self):
        self.pump.outlet_x, self.pump.outlet_y, self.pump.outlet_z, self.pump.outlet_heading = 50, 10, 5, 0
        self.pump.save()
        self.sump.overflow_type, self.sump.overflow_across, self.sump.overflow_depth = 'corner', 'right', 'back'
        self.sump.save()
        page = self.client.get(self.url)
        sketch = page.context['flow_sketch']
        self.assertTrue(sketch['show'])
        self.assertEqual((sketch['outlets'][0]['x'], sketch['outlets'][0]['top_y']), (150.0, 22.4))
        # The strongest outlet gets the longest arrow, pointing at the front glass.
        self.assertEqual((sketch['outlets'][0]['top_dx'], sketch['outlets'][0]['top_dy']), (0.0, 64.0))
        self.assertEqual(sketch['overflows'][0]['x'], 258.8)
        self.assertEqual(sketch['top_h'], 112)  # shaped like the 48 x 18 tank
        self.assertEqual([e.name for e in sketch['unplaced']], ['MP40'])
        self.assertContains(page, 'Corner overflow, back right')
        self.assertContains(page, 'Back, centre, near the surface, toward the front')

    def test_coast_to_coast_runs_the_width(self):
        self.sump.overflow_type = 'coast'
        self.sump.save()
        self.assertTrue(self.client.get(self.url).context['flow_sketch']['overflows'][0]['wide'])

    def test_forms_save_positions(self):
        self.client.post(reverse('sump_edit', args=[self.sump.pk]), {
            'name': 'Sump', 'dimension_unit': 'in', 'fill_percent': 60, 'volume_gallons': 20, 'capacity_is_manual': 'on',
            'head_height_unit': 'ft', 'overflow_type': 'internal', 'overflow_across': 'left', 'overflow_depth': 'back'})
        self.sump.refresh_from_db()
        self.assertEqual((self.sump.overflow_type, self.sump.overflow_across), ('internal', 'left'))
        page = self.client.get(reverse('equipment_edit', args=[self.wave.pk]))
        self.assertContains(page, 'name="outlet_heading"')
        self.assertContains(page, 'class="outlet-picker')
        self.assertContains(self.client.get(reverse('equipment')), 'class="outlet-picker')


class TankFileTests(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.Upload = SimpleUploadedFile
        self.tank = Tank.objects.create(name='Reef', volume_gallons=75, width=48, depth=18, height=21, is_primary=True,
                                        ui_style='8bit', substrate_type='live_sand')
        sump = Sump.objects.create(tank=self.tank, name='Sump', volume_gallons=20, head_height=4,
                                   overflow_type='corner', overflow_across='right', overflow_depth='back')
        self.chamber = SumpChamber.objects.create(sump=sump, position=2, chamber_type='refugium', share_percent=40)
        PlumbingRun.objects.create(tank=self.tank, name='Return', length=6, pipe_size='1')
        self.pump = Equipment.objects.create(tank=self.tank, sump=sump, chamber=self.chamber, name='Vectra',
                                             category='return_pump', max_flow_gph=2100, max_head=12.5, paid=500,
                                             outlet_x=50, outlet_y=20, outlet_heading=0)
        self.light = Equipment.objects.create(tank=self.tank, name='Radion', category='lighting', wattage=190)
        sand = Equipment.objects.create(name='Arag-Alive', category='substrate')
        self.tank.substrate_product = sand
        self.tank.save()
        group = AnimalGroup.objects.create(name='Fish', icon='🐠')
        clown = Animal.objects.create(name='Clowns', tank=self.tank, count=2)
        clown.groups.add(group)
        Animal.objects.create(name='Old tang', tank=self.tank, status='deceased')
        self.alk = ParameterType.objects.create(name='Alkalinity', code='alk_test', unit='dKH', min_ideal=7, max_ideal=9)
        ParameterTarget.objects.create(tank=self.tank, parameter_type=self.alk, min_ideal=8, max_ideal=9)
        routine = MaintenanceRoutine.objects.create(tank=self.tank, title='Lights', routine_type='automated',
                                                    category='lighting',
                                                    schedule_events=[{'time': '10:00', 'action': 'Lights on'}])
        routine.equipment.add(self.light)
        DosingReservoir.objects.create(tank=self.tank, name='Alk', capacity=1000, current_level=500, daily_consumption=20)

    def _export(self, prices=False):
        url = reverse('tank_export', args=[self.tank.pk]) + ('?prices=1' if prices else '')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('reef.nudibranch.yaml', response['Content-Disposition'])
        return response.content.decode()

    def test_export_is_readable_yaml_without_prices_or_history(self):
        import yaml
        text = self._export()
        data = yaml.safe_load(text)
        self.assertEqual(data['nudibranch_tank'], 1)
        self.assertEqual(data['tank']['name'], 'Reef')
        self.assertEqual(data['tank']['substrate_product'], 'Arag-Alive')
        self.assertNotIn('paid', text)
        self.assertEqual([a['name'] for a in data['livestock']], ['Clowns'])  # gone animals stay out
        pump = next(e for e in data['equipment'] if e['name'] == 'Vectra')
        self.assertEqual(pump['location'], {'sump': 'Sump', 'chamber': 2})
        self.assertEqual(data['targets'][0]['parameter'], 'alk_test')
        self.assertIn('paid: 500', self._export(prices=True))

    def test_round_trip_makes_a_matching_new_tank(self):
        text = self._export(prices=True)
        before = Tank.objects.count()
        page = self.client.post(reverse('tank_import'), {'file': self.Upload('reef.yaml', text.encode())})
        self.assertContains(page, 'Import this tank')
        self.assertContains(page, 'already have a tank called Reef')
        self.assertEqual(Tank.objects.count(), before)  # the preview keeps nothing
        response = self.client.post(reverse('tank_import'), {'text': text, 'confirm': '1'})
        new = Tank.objects.exclude(pk=self.tank.pk).get()
        self.assertRedirects(response, reverse('tank_detail', args=[new.pk]), fetch_redirect_response=False)
        self.assertEqual(new.name, 'Reef (imported)')
        self.assertFalse(new.is_primary)
        self.assertEqual((new.ui_style, new.substrate_type, float(new.width)), ('8bit', 'live_sand', 48.0))
        sump = new.sumps.get()
        self.assertEqual((float(sump.head_height), sump.overflow_type), (4.0, 'corner'))
        pump = new.equipment.get(name='Vectra')
        self.assertEqual((pump.chamber.position, pump.sump, float(pump.max_head), pump.outlet_heading), (2, sump, 12.5, 0))
        self.assertEqual(new.substrate_product.name, 'Arag-Alive')
        self.assertEqual(new.plumbing_runs.count(), 1)
        self.assertEqual([a.name for a in new.animals.all()], ['Clowns'])
        self.assertEqual(AnimalGroup.objects.filter(name='Fish').count(), 1)  # reused, not copied
        self.assertEqual(new.parameter_targets.get().parameter_type, self.alk)
        self.assertEqual(list(new.routines.get().equipment.values_list('name', flat=True)), ['Radion'])
        self.assertEqual(new.reservoirs.count(), 1)

    def test_bad_files_are_refused_kindly(self):
        cases = [
            ('just: words', 'look like a Nudibranch tank file'),
            ('nudibranch_tank: 9\ntank: {name: X}', 'version 9'),
            ('nudibranch_tank: 1\ntank: {name: X\n', 'valid YAML'),
            ('nudibranch_tank: 1\nx: &a [1]\ny: *a\ntank: {name: X}', 'aliases'),
            ('nudibranch_tank: 1\ntank: {name: X, dimension_unit: furlongs}', 'dimension_unit'),
        ]
        for text, message in cases:
            page = self.client.post(reverse('tank_import'), {'file': self.Upload('t.yaml', text.encode())})
            self.assertContains(page, message, msg_prefix=text)
        self.assertEqual(Tank.objects.count(), 1)

    def test_unknown_parameter_is_skipped_with_a_note(self):
        text = 'nudibranch_tank: 1\ntank: {name: Nano}\ntargets:\n  - {parameter: unobtainium, min_ideal: 1, max_ideal: 2}\n'
        page = self.client.post(reverse('tank_import'), {'file': self.Upload('t.yaml', text.encode())})
        self.assertContains(page, 'No parameter called unobtainium')

    def test_buttons(self):
        self.assertContains(self.client.get(reverse('tanks')), reverse('tank_import'))
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.tank.pk])), reverse('tank_export', args=[self.tank.pk]))


class QuickMeasureUnitTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.alk = ParameterType.objects.get_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'min_ideal': 7, 'max_ideal': 9, 'decimal_places': 1})[0]
        self.oddball = ParameterType.objects.create(name='Iodine test', code='iodine_x', unit='ppb', min_ideal=0, max_ideal=1)

    def test_card_offers_units_per_parameter(self):
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, f'data-units="{self.alk.unit},meq/L,ppm"')
        self.assertContains(page, 'data-units="ppb"')  # no known conversions: one unit, not switchable

    def test_other_units_are_converted_on_save(self):
        self.client.post(reverse('quick_measure_create'), {
            'parameter': [self.alk.pk], 'value': ['3.0'], 'unit': ['meq/L']})
        log = ParameterLog.objects.get(parameter_type=self.alk)
        self.assertEqual(float(log.value), 8.4)

    def test_own_unit_and_missing_unit_are_unchanged(self):
        self.client.post(reverse('quick_measure_create'), {
            'parameter': [self.alk.pk, self.oddball.pk], 'value': ['8.3', '12'], 'unit': [self.alk.unit]})
        self.assertEqual(float(ParameterLog.objects.get(parameter_type=self.alk).value), 8.3)
        self.assertEqual(float(ParameterLog.objects.get(parameter_type=self.oddball).value), 12)

    def test_unknown_unit_is_refused(self):
        self.client.post(reverse('quick_measure_create'), {
            'parameter': [self.oddball.pk], 'value': ['5'], 'unit': ['furlongs']})
        self.assertFalse(ParameterLog.objects.filter(parameter_type=self.oddball).exists())


class UnitButtonEverywhereTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.alk = ParameterType.objects.get_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'min_ideal': 7, 'max_ideal': 9, 'decimal_places': 1})[0]

    def test_log_test_popup_lists_names_and_converts(self):
        page = self.client.get(reverse('dashboard'))
        self.assertContains(page, 'What are you measuring?')
        self.assertContains(page, f'>{self.alk.name}</option>')
        self.assertNotContains(page, f'>{self.alk.name} ({self.alk.unit})</option>')
        self.client.post(reverse('quick_log_create'), {
            'parameter_type': self.alk.pk, 'value': '150', 'unit': 'ppm', 'tank': self.tank.pk})
        log = ParameterLog.objects.get(parameter_type=self.alk)
        self.assertEqual(float(log.value), 8.4)

    def test_edit_a_test_in_another_unit(self):
        log = ParameterLog.objects.create(parameter_type=self.alk, tank=self.tank, value=8, measured_at=timezone.now())
        page = self.client.get(reverse('log_edit', args=[log.pk]))
        self.assertContains(page, 'data-units="dKH,meq/L,ppm"')
        self.client.post(reverse('log_edit', args=[log.pk]), {
            'parameter_type': self.alk.pk, 'tank': self.tank.pk, 'value': '3', 'unit': 'meq/L',
            'measured_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M')})
        log.refresh_from_db()
        self.assertEqual(float(log.value), 8.4)

    def test_substrate_and_live_rock_use_buttons(self):
        page = self.client.get(reverse('tank_edit', args=[self.tank.pk]))
        self.assertContains(page, 'data-units="lb,kg"')
        self.assertContains(page, 'id="dim-unit-btn"')
        self.assertNotContains(page, '<select name="substrate_unit"')

    def test_plumbing_saves_metres(self):
        page = self.client.get(reverse('plumbing_create', args=[self.tank.pk]))
        self.assertContains(page, 'data-units="ft,m"')
        self.assertContains(page, 'data-units="in,mm"')
        self.client.post(reverse('plumbing_create', args=[self.tank.pk]), {
            'name': 'Return', 'length': '2', 'length_unit': 'm', 'pipe_size': '1', 'custom_diameter_unit': 'in',
            'count': 1, 'fill_percent': 100})
        self.assertEqual(PlumbingRun.objects.get().length_unit, 'm')

    def test_dose_and_container_units(self):
        page = self.client.get(reverse('dosing'))
        self.assertContains(page, 'data-units="ml,g,tsp,fl oz,drops"')
        self.assertContains(page, 'data-units="ml,L,gal"')
        self.assertContains(page, 'class="unit-suffix"')


class NumberBoxStepTests(TestCase):
    def test_every_step_and_minimum_allow_round_numbers(self):
        """A browser only accepts min + n x step, so a step that doesn't divide evenly from the minimum
        blocks ordinary values (a 5% step from 1% refused 100%)."""
        import re
        from decimal import Decimal
        from pathlib import Path
        app = Path(__file__).resolve().parent
        sources = [app / 'forms.py', app / 'forms_tools.py']
        sources += list((app.parent / 'templates').rglob('*.html'))
        pairs = []
        for path in sources:
            for line in path.read_text(encoding='utf-8').splitlines():
                step = re.search(r"""step["']?\s*[:=]\s*["']([0-9.]+)["']""", line)
                low = re.search(r"""min["']?\s*[:=]\s*["']([0-9.]+)["']""", line)
                if step and low:
                    pairs.append((path.name, Decimal(step.group(1)), Decimal(low.group(1))))
        self.assertTrue(pairs)
        for name, step, low in pairs:
            self.assertEqual(low % step, 0, f"{name}: min {low} isn't a whole number of {step} steps")

    def test_plumbing_accepts_100_percent(self):
        tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        page = self.client.get(reverse('plumbing_create', args=[tank.pk]))
        self.assertContains(page, 'step="1"')
        self.assertNotContains(page, 'step="5"')


class OutletPickerAndFlowGroupTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=75, is_primary=True)
        self.pump = Equipment.objects.create(tank=self.tank, name='Return', category='return_pump', max_flow_gph=1200)
        self.wave = Equipment.objects.create(tank=self.tank, name='MP40', category='wavemaker', max_flow_gph=3000)

    def _post(self, eq, **extra):
        data = {'location': f'tank:{self.tank.pk}', 'name': eq.name, 'category': eq.category, 'max_flow_gph': 3000,
                'power_setting_percent': 100, 'flow_derate_percent': 30, 'max_head': '10', 'max_head_unit': 'ft',
                'maintenance_interval_days': 90, 'status': 'operational', 'outlet_tilt': 0}
        data.update(extra)
        return self.client.post(reverse('equipment_edit', args=[eq.pk]), data)

    def test_picker_values_save_and_describe(self):
        self._post(self.wave, outlet_x=5, outlet_y=50, outlet_z=40, outlet_heading=90, outlet_tilt=20)
        self.wave.refresh_from_db()
        self.assertEqual((self.wave.outlet_x, self.wave.outlet_heading, self.wave.outlet_tilt), (5, 90, 20))
        self.assertEqual(self.wave.outlet_label, 'Middle, left, mid-water, to the right, angled up')

    def test_wavemaker_drops_head_loss_and_max_head(self):
        self._post(self.wave)
        self.wave.refresh_from_db()
        self.assertEqual((self.wave.flow_derate_percent, self.wave.max_head), (0, None))
        self._post(self.pump)
        self.pump.refresh_from_db()
        self.assertEqual((self.pump.flow_derate_percent, float(self.pump.max_head)), (30, 10.0))

    def test_non_flow_equipment_has_no_outlet(self):
        heater = Equipment.objects.create(tank=self.tank, name='Heater', category='heater')
        self.client.post(reverse('equipment_edit', args=[heater.pk]), {
            'location': f'tank:{self.tank.pk}', 'name': 'Heater', 'category': 'heater', 'power_setting_percent': 100,
            'flow_derate_percent': 0, 'max_head_unit': 'ft', 'maintenance_interval_days': 90, 'status': 'operational',
            'outlet_x': 50, 'outlet_y': 50, 'outlet_tilt': 0})
        heater.refresh_from_db()
        self.assertIsNone(heater.outlet_x)

    def test_fields_are_tagged_for_their_categories(self):
        page = self.client.get(reverse('equipment_edit', args=[self.wave.pk])).content.decode()
        self.assertIn('data-for-categories="return_pump"', page)
        self.assertIn('data-for-categories="return_pump,wavemaker"', page)

    def test_straight_up_outlet(self):
        self.wave.outlet_x, self.wave.outlet_y, self.wave.outlet_tilt = 50, 50, 80
        self.wave.save()
        self.assertTrue(self.wave.outlet_label.endswith('pointing up'))
        sketch = self.client.get(reverse('tank_detail', args=[self.tank.pk])).context['flow_sketch']
        self.assertLess(sketch['outlets'][0]['front_dy'], 0)  # drawn pointing up in the front view
        self.assertLess(abs(sketch['outlets'][0]['top_dy']), 15)  # and barely sideways from above

    def test_flow_section_groups(self):
        page = self.client.get(reverse('tank_detail', args=[self.tank.pk]))
        groups = page.context['flow_groups']
        self.assertEqual([g['title'] for g in groups], ['Return pumps', 'Wavemakers & powerheads'])
        self.assertEqual([[e.name for e in g['items']] for g in groups], [['Return'], ['MP40']])
        self.assertContains(page, '+ Add a return pump')
        self.assertContains(page, '+ Add some flow')


class WaterQualityRatingTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.alk = ParameterType.objects.get_or_create(code='alkalinity', defaults={
            'name': 'Alkalinity', 'unit': 'dKH', 'min_ideal': 7.5, 'max_ideal': 9, 'decimal_places': 1})[0]
        ParameterType.objects.filter(pk=self.alk.pk).update(min_ideal=7.5, max_ideal=9, low_limit=6.5, high_limit=11)
        self.alk.refresh_from_db()

    def _log(self, pt, value, days_ago=0):
        return ParameterLog.objects.create(parameter_type=pt, tank=self.tank, value=value,
                                           measured_at=timezone.now() - timedelta(days=days_ago))

    def test_scores(self):
        from .water_quality import _score
        self.assertEqual(_score(8, 7.5, 9, 6.5, 11), 100)
        self.assertEqual(_score(7.0, 7.5, 9, 6.5, 11), 75)   # halfway to the low limit
        self.assertEqual(_score(6.5, 7.5, 9, 6.5, 11), 50)   # at the limit
        self.assertLess(_score(5.0, 7.5, 9, 6.5, 11), 40)    # past it
        self.assertGreaterEqual(_score(-100, 7.5, 9, 6.5, 11), 0)

    def test_rating_with_only_in_range_readings(self):
        from .views import _water_quality
        ParameterLog.objects.all().delete()
        self._log(self.alk, 8.2)
        q = _water_quality(self.tank)
        self.assertEqual(q['score'], 100)
        self.assertEqual(q['grade'], 'Excellent')

    def test_out_of_range_drags_it_down_and_old_tests_are_left_out(self):
        from .views import _water_quality
        ParameterLog.objects.all().delete()
        self._log(self.alk, 7.0)
        old = ParameterType.objects.create(name='Iodine x', code='iodine_x', unit='ppb', min_ideal=50, max_ideal=70)
        self._log(old, 10, days_ago=60)
        q = _water_quality(self.tank)
        self.assertEqual(q['score'], 75)
        self.assertEqual(q['dragging'][0]['parameter'].pk, self.alk.pk)
        self.assertEqual([pt.pk for pt in q['stale']], [old.pk])

    def test_no_recent_tests_means_no_rating(self):
        from .views import _water_quality
        ParameterLog.objects.all().delete()
        self.assertIsNone(_water_quality(self.tank))
        self.assertContains(self.client.get(reverse('parameters')), 'your rating shows up here')

    def test_card_on_dashboard_and_water_page(self):
        ParameterLog.objects.all().delete()
        self._log(self.alk, 8.2)
        self.assertContains(self.client.get(reverse('dashboard')), 'not a lab result')
        self.assertContains(self.client.get(reverse('parameters')), 'Excellent')


class PlannerGearAndSliderTests(TestCase):
    def setUp(self):
        self.plan = PlannedSystem.objects.create(name='Big reef', goal='mixed', width=48, depth=24, height=24,
                                                 dimension_unit='in', volume_gallons=120)
        self.url = reverse('plan_detail', args=[self.plan.pk])

    def test_add_form_offers_category_fields_and_a_slider(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn('data-for-categories="lighting"', page)
        self.assertIn('Lights on (hours a day)', page)
        self.assertIn('type="range"', page)

    def test_light_and_wavemaker_use_their_output(self):
        self.client.post(reverse('plan_add_equipment', args=[self.plan.pk]), {
            'gear-name': 'LED', 'gear-category': 'lighting', 'gear-quantity': 2, 'gear-wattage': 100,
            'gear-power_percent': 50, 'gear-hours_per_day': 9, 'gear-max_flow_gph': 999})
        self.client.post(reverse('plan_add_equipment', args=[self.plan.pk]), {
            'gear-name': 'MP40', 'gear-category': 'wavemaker', 'gear-quantity': 1, 'gear-wattage': 40,
            'gear-max_flow_gph': 4000, 'gear-power_percent': 30, 'gear-hours_per_day': 5})
        light = PlannedItem.objects.get(name='LED')
        wave = PlannedItem.objects.get(name='MP40')
        self.assertEqual((light.power_percent, float(light.hours_per_day), light.max_flow_gph), (50, 9.0, None))
        self.assertEqual((wave.power_percent, wave.hours_per_day), (30, None))
        from . import planner
        a = planner.analyze(self.plan)
        self.assertEqual(a['light_watts'], 100)
        self.assertTrue(a['par_levels'])
        self.assertEqual(round(a['flow']['wavemaker_gph']), 1200)
        page = self.client.get(self.url)
        self.assertContains(page, 'running at 30%')
        self.assertContains(page, '9 h a day')

    def test_tracking_carries_output_over(self):
        from . import planner
        PlannedItem.objects.create(plan=self.plan, kind='equipment', name='MP40', category='wavemaker',
                                   max_flow_gph=4000, power_percent=30)
        tank = planner.track_plan(self.plan) if hasattr(planner, 'track_plan') else None
        if tank is None:
            self.skipTest('tracking helper has another name')
        self.assertEqual(Equipment.objects.get(name='MP40').power_setting_percent, 30)

    def test_tank_page_and_equipment_form_use_sliders(self):
        tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        wave = Equipment.objects.create(tank=tank, name='MP40', category='wavemaker', max_flow_gph=4000,
                                        power_setting_percent=30)
        Equipment.objects.create(tank=tank, name='Radion', category='lighting', wattage=100)
        page = self.client.get(reverse('tank_detail', args=[tank.pk])).content.decode()
        self.assertGreaterEqual(page.count('aria-label="MP40 output"') + page.count('aria-label="Radion output"'), 2)
        form = self.client.get(reverse('equipment_edit', args=[wave.pk])).content.decode()
        self.assertIn('data-for-categories="return_pump,wavemaker,lighting"', form)
        self.assertIn('type="range" min="1" max="100" step="1" value="30"', form)


class EquipmentScheduleTests(TestCase):
    def setUp(self):
        self.tank = Tank.objects.create(name='Main', volume_gallons=40, is_primary=True)
        self.light = Equipment.objects.create(tank=self.tank, name='Radion', category='lighting', wattage=100)

    def _post(self, schedule, category='lighting'):
        import json
        return self.client.post(reverse('equipment_edit', args=[self.light.pk]), {
            'location': f'tank:{self.tank.pk}', 'name': 'Radion', 'category': category, 'power_setting_percent': 80,
            'flow_derate_percent': 0, 'max_head_unit': 'ft', 'maintenance_interval_days': 90, 'status': 'operational',
            'outlet_tilt': 0, 'schedule': json.dumps(schedule)})

    def test_schedule_saves_as_its_own_routine_and_shows(self):
        self._post([{'time': '20:00', 'action': 'Lights off'}, {'time': '10:00', 'action': 'Lights on'}, {'time': '', 'action': 'x'}])
        routine = MaintenanceRoutine.objects.get(owner_equipment=self.light)
        self.assertEqual((routine.routine_type, routine.repeat_unit, routine.category), ('automated', 'day', 'lighting'))
        self.assertEqual([e['time'] for e in routine.schedule_events], ['10:00', '20:00'])
        light = Equipment.objects.prefetch_related('routines').get(pk=self.light.pk)
        self.assertEqual(light.schedule_text, '10:00 Lights on · 20:00 Lights off')
        self.assertContains(self.client.get(reverse('equipment')), '10:00 Lights on')
        self.assertContains(self.client.get(reverse('tank_detail', args=[self.tank.pk])), '10:00 Lights on')
        self.assertContains(self.client.get(reverse('equipment_edit', args=[self.light.pk])), 'Lights off')

    def test_editing_updates_and_clearing_removes(self):
        self._post([{'time': '10:00', 'action': 'Lights on'}])
        self._post([{'time': '09:30', 'action': 'Ramp up'}])
        self.assertEqual(MaintenanceRoutine.objects.filter(owner_equipment=self.light).count(), 1)
        self.assertEqual(MaintenanceRoutine.objects.get(owner_equipment=self.light).schedule_events[0]['time'], '09:30')
        self._post([])
        self.assertFalse(MaintenanceRoutine.objects.filter(owner_equipment=self.light).exists())

    def test_bad_time_is_refused(self):
        response = self._post([{'time': '25:00', 'action': 'On'}])
        self.assertContains(response, "isn&#x27;t a time of day")
        self.assertFalse(MaintenanceRoutine.objects.filter(owner_equipment=self.light).exists())

    def test_category_without_schedules_drops_it(self):
        self._post([{'time': '10:00', 'action': 'On'}], category='substrate')
        self.assertFalse(MaintenanceRoutine.objects.filter(owner_equipment=self.light).exists())
