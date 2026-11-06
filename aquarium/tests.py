import io
import json
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, time, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import backups, compatibility, events, fill, planner, power, timelapse
from .models import (
    Animal, AnimalPhoto, AppSettings, DosingReservoir, Equipment, EventState, FillTimer, MaintenanceRoutine,
    ParameterLog, ParameterType, PlannedItem, PlannedSystem, QuarantineEntry, ROSystem, SpeciesCatalog, Tank,
    TimelapseFrame, WebcamFeed, WebhookDelivery, WebhookEndpoint, WishlistItem,
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
        events.sync_conditions()
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


class WishlistTests(TestCase):
    def setUp(self):
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
