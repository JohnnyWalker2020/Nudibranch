"""Views for the tools section: planner, power, quarantine, timeline, time-lapse, webhooks, backups, timers."""
import json
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import backups, events, fill, planner, power, timelapse, wishlist
from .forms_tools import (
    AnimalPhotoForm, AppSettingsForm, PlannedEquipmentForm, PlannedLivestockForm, PlannedSystemForm,
    QuarantineEntryForm, QuarantinePlanForm, ROSystemForm, WebhookEndpointForm, WishlistEquipmentForm,
    WishlistLivestockForm,
)
from .models import (
    Animal, AnimalPhoto, AppSettings, DosingReservoir, FillTimer, ParameterType, PlannedItem, PlannedSystem,
    QuarantineEntry, ROSystem, SpeciesCatalog, Tank, TimelapseFrame, WebcamFeed, WebhookDelivery, WebhookEndpoint,
    WishlistItem,
)
from .views import _delete_object, _edit_object, _flash_form_errors, _safe_next, _to_decimal, _to_int

MAX_TIMER_SECONDS = 24 * 60 * 60


def _form_page(request, form, title, back_url, subtitle='', multipart=False):
    return render(request, 'aquarium/generic_form.html', {
        'form': form, 'title': title, 'subtitle': subtitle, 'back_url': back_url, 'multipart': multipart,
    })


# ==========================================
# Tools hub & settings
# ==========================================

def tools_view(request):
    settings_obj = AppSettings.load()
    return render(request, 'aquarium/tools.html', {
        'settings_obj': settings_obj,
        'plan_count': PlannedSystem.objects.count(),
        'running_timers': FillTimer.objects.filter(status='running').count(),
        'endpoint_count': WebhookEndpoint.objects.filter(is_active=True).count(),
        'quarantine_count': Animal.objects.filter(status='quarantine').count(),
        'power': power.power_summary(),
        'latest_backup': next(iter(backups.list_backups()), None),
    })


def app_settings_view(request):
    obj = AppSettings.load()
    return _edit_object(request, AppSettings, AppSettingsForm, obj.pk, title='App Settings',
                        subtitle='Electricity price and automatic backups', back_url=reverse('tools'))


# ==========================================
# Power
# ==========================================

def power_view(request):
    tank = Tank.objects.filter(pk=_to_int(request.GET.get('tank'), None)).first()
    return render(request, 'aquarium/power.html', {
        'summary': power.power_summary(tank), 'tanks': Tank.objects.all(), 'selected_tank': tank,
    })


# ==========================================
# Quarantine
# ==========================================

def quarantine_list_view(request):
    active = Animal.objects.filter(status='quarantine').select_related('tank').order_by('quarantine_started', 'name')
    others = Animal.objects.exclude(status__in=['quarantine', 'rehomed', 'deceased']).order_by('name')
    return render(request, 'aquarium/quarantine_list.html', {'active': active, 'others': others})


def quarantine_detail_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    return render(request, 'aquarium/quarantine_detail.html', {
        'animal': animal,
        'entries': animal.quarantine_entries.all(),
        'entry_form': QuarantineEntryForm(initial={'logged_on': timezone.localdate()}),
        'plan_form': QuarantinePlanForm(initial={
            'started': animal.quarantine_started or timezone.localdate(), 'days': animal.quarantine_days,
        }),
    })


@require_POST
def quarantine_start_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    animal.status = 'quarantine'
    animal.quarantine_started = timezone.localdate()
    animal.save()
    messages.success(request, f"{animal.name} is now in quarantine.")
    return redirect('quarantine_detail', animal_id=animal.pk)


@require_POST
def quarantine_plan_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    form = QuarantinePlanForm(request.POST)
    if form.is_valid():
        animal.quarantine_started = form.cleaned_data['started']
        animal.quarantine_days = form.cleaned_data['days']
        animal.save()
        messages.success(request, "Quarantine plan updated.")
    else:
        _flash_form_errors(request, form)
    return redirect('quarantine_detail', animal_id=animal.pk)


@require_POST
def quarantine_finish_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    animal.status = 'healthy'
    animal.save()
    messages.success(request, f"{animal.name} is out of quarantine and marked healthy.")
    return redirect('quarantine_list')


@require_POST
def quarantine_entry_add_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    form = QuarantineEntryForm(request.POST)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.animal = animal
        entry.save()
        messages.success(request, "Logged.")
    else:
        _flash_form_errors(request, form)
    return redirect('quarantine_detail', animal_id=animal.pk)


@require_POST
def quarantine_entry_delete_view(request, entry_id):
    entry = get_object_or_404(QuarantineEntry, pk=entry_id)
    animal_id = entry.animal_id
    entry.delete()
    messages.success(request, "Entry deleted.")
    return redirect('quarantine_detail', animal_id=animal_id)


# ==========================================
# Growth timeline
# ==========================================

def timeline_view(request, animal_id):
    animal = get_object_or_404(Animal, pk=animal_id)
    if request.method == 'POST':
        form = AnimalPhotoForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.animal = animal
            photo.save()
            messages.success(request, "Photo added to the timeline.")
            return redirect('timeline', animal_id=animal.pk)
        _flash_form_errors(request, form)
    else:
        form = AnimalPhotoForm(initial={'taken_on': timezone.localdate()})
    photos = list(animal.timeline_photos.all())
    return render(request, 'aquarium/timeline.html', {
        'animal': animal,
        'photos': photos,
        'form': form,
        'first': photos[0] if photos else None,
        'last': photos[-1] if photos else None,
        'photos_json': json.dumps([
            {'url': p.image.url, 'date': p.taken_on.strftime('%b %d, %Y'), 'note': p.note} for p in photos
        ]),
    })


@require_POST
def timeline_photo_delete_view(request, photo_id):
    photo = get_object_or_404(AnimalPhoto, pk=photo_id)
    animal_id = photo.animal_id
    photo.delete()
    messages.success(request, "Photo removed.")
    return redirect('timeline', animal_id=animal_id)


# ==========================================
# Webcam time-lapse
# ==========================================

def timelapse_view(request, cam_id):
    feed = get_object_or_404(WebcamFeed, pk=cam_id)
    days = _to_int(request.GET.get('days'), 7, 0, 3650)
    frames = feed.frames.all()
    if days:
        frames = frames.filter(captured_at__gte=timezone.now() - timedelta(days=days))
    frames = list(frames)
    return render(request, 'aquarium/timelapse.html', {
        'feed': feed,
        'days': days,
        'frame_count': len(frames),
        'total_frames': feed.frames.count(),
        'can_capture': bool(timelapse.snapshot_source(feed)),
        'frames_json': json.dumps([
            {'url': f.image.url, 'at': timezone.localtime(f.captured_at).strftime('%b %d %H:%M')} for f in frames
        ]),
    })


@require_POST
def timelapse_capture_view(request, cam_id):
    feed = get_object_or_404(WebcamFeed, pk=cam_id)
    frame = timelapse.capture_frame(feed)
    if frame:
        messages.success(request, "Frame captured.")
    else:
        feed.refresh_from_db()
        messages.error(request, f"Couldn't capture a frame: {feed.last_capture_error}")
    return redirect('timelapse', cam_id=feed.pk)


@require_POST
def timelapse_clear_view(request, cam_id):
    feed = get_object_or_404(WebcamFeed, pk=cam_id)
    for frame in feed.frames.all():
        frame.delete()
    messages.success(request, "All frames for this camera were deleted.")
    return redirect('timelapse', cam_id=feed.pk)


# ==========================================
# Webhooks & phone alerts
# ==========================================

def integrations_view(request):
    if request.method == 'POST':
        changed = 0
        for param in ParameterType.objects.all():
            raw = request.POST.get(f'stale_{param.pk}', '').strip()
            value = _to_int(raw, None, 1, 8760) if raw else None
            if param.stale_after_hours != value:
                param.stale_after_hours = value
                param.save(update_fields=['stale_after_hours'])
                changed += 1
        messages.success(request, "Probe alerts saved." if changed else "No changes.")
        return redirect('integrations')
    settings_obj = AppSettings.load()
    return render(request, 'aquarium/integrations.html', {
        'endpoints': WebhookEndpoint.objects.annotate(delivery_count=Count('deliveries'))
                     .prefetch_related('routines', 'timer_reservoirs'),
        'deliveries': WebhookDelivery.objects.select_related('endpoint')[:30],
        'parameters': ParameterType.objects.all(),
        'settings_obj': settings_obj,
        'api_key_set': bool(getattr(settings, 'API_SECRET_KEY', '')),
        'event_types': events.EVENT_TYPES,
    })


def webhook_create_view(request):
    if request.method == 'POST':
        form = WebhookEndpointForm(request.POST)
        if form.is_valid():
            endpoint = form.save()
            messages.success(request, f"Added {endpoint.name}. Send a test to check it works.")
            return redirect('integrations')
    else:
        form = WebhookEndpointForm()
    return _form_page(request, form, 'Add Webhook or Phone Alert', reverse('integrations'),
                      'Events are sent as they happen, in the background')


def webhook_edit_view(request, endpoint_id):
    return _edit_object(request, WebhookEndpoint, WebhookEndpointForm, endpoint_id, title='Edit Webhook',
                        back_url=reverse('integrations'), delete_url=reverse('webhook_delete', args=[endpoint_id]))


def webhook_delete_view(request, endpoint_id):
    endpoint = get_object_or_404(WebhookEndpoint, pk=endpoint_id)
    return _delete_object(request, WebhookEndpoint, endpoint_id, label=endpoint.name, back_url=reverse('integrations'))


@require_POST
def webhook_test_view(request, endpoint_id):
    endpoint = get_object_or_404(WebhookEndpoint, pk=endpoint_id)
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint, event_id=str(uuid.uuid4()), event_type='test', severity='info',
        title='Nudibranch test', message='If you can read this, this connection works.',
        data={'test': True}, max_attempts=1,
    )
    if events.send_delivery(delivery):
        messages.success(request, f"Test sent to {endpoint.name} (HTTP {delivery.response_code}).")
    else:
        messages.error(request, f"Test to {endpoint.name} failed: {delivery.error or delivery.response_code}")
    return redirect('integrations')


# ==========================================
# Backups
# ==========================================

def backups_view(request):
    return render(request, 'aquarium/backups.html', {
        'backups': backups.list_backups(),
        'settings_obj': AppSettings.load(),
    })


@require_POST
def backup_create_view(request):
    path = backups.create_backup('manual', include_timelapse=bool(request.POST.get('include_timelapse')))
    messages.success(request, f"Backup created: {path.name}")
    return redirect('backups')


def backup_download_view(request, name):
    try:
        path = backups.resolve_backup(name)
    except backups.BackupError as exc:
        raise Http404(str(exc))
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)


@require_POST
def backup_delete_view(request, name):
    try:
        backups.resolve_backup(name).unlink()
        messages.success(request, "Backup deleted.")
    except backups.BackupError as exc:
        messages.error(request, str(exc))
    return redirect('backups')


@require_POST
def backup_restore_view(request):
    if request.POST.get('confirm', '').strip().upper() != 'RESTORE':
        messages.error(request, 'Type RESTORE to confirm. Nothing was changed.')
        return redirect('backups')
    upload = request.FILES.get('file')
    try:
        if upload:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'upload.zip'
                with open(target, 'wb') as out:
                    for chunk in upload.chunks():
                        out.write(chunk)
                safety = backups.restore_backup(target)
        else:
            safety = backups.restore_backup(backups.resolve_backup(request.POST.get('name', '')))
    except backups.BackupError as exc:
        messages.error(request, f"Nothing was restored: {exc}")
        return redirect('backups')
    messages.success(request, f"Restored. Your previous data was saved as {safety}.")
    return redirect('backups')


# ==========================================
# Fill timers & RO calculator
# ==========================================

def _ro_context(system):
    return {
        'system': system,
        'gph': round(fill.estimated_gph(
            system.rated_gpd, system.rated_psi, system.rated_temp_f, system.feed_psi, system.feed_temp_f,
            system.measured_gph), 2),
    }


def _system_gph(system):
    return fill.estimated_gph(system.rated_gpd, system.rated_psi, system.rated_temp_f,
                              system.feed_psi, system.feed_temp_f, system.measured_gph)


def timers_view(request):
    systems = list(ROSystem.objects.all())
    ro_rows = [_ro_context(s) for s in systems]
    reservoirs = []
    for res in DosingReservoir.objects.select_related('tank'):
        reservoirs.append({
            'id': res.pk, 'name': res.name,
            'gallons_to_full': round(max(0.0, fill.to_gallons(float(res.capacity) - float(res.current_level), res.unit)), 3),
            'capacity_gallons': round(fill.to_gallons(res.capacity, res.unit), 3),
            'is_ato': res.reservoir_type == 'ato_freshwater',
        })
    reservoirs.sort(key=lambda r: (not r['is_ato'], r['name']))
    settings_obj = AppSettings.load()
    return render(request, 'aquarium/timers.html', {
        'running': FillTimer.objects.filter(status='running').select_related('reservoir'),
        'recent': FillTimer.objects.exclude(status='running').select_related('reservoir').order_by('-ends_at')[:5],
        'ro_rows': ro_rows,
        'reservoirs': reservoirs,
        'systems_json': json.dumps([
            {'id': r['system'].pk, 'name': r['system'].name, 'gph': r['gph'], 'waste': float(r['system'].waste_ratio)}
            for r in ro_rows]),
        'reservoirs_json': json.dumps(reservoirs),
        'worker_online': settings_obj.worker_online,
        'timer_endpoints': sum(1 for e in WebhookEndpoint.objects.filter(is_active=True)
                               if e.wants('timer.finished', check_targets=False)),
        'all_endpoints': WebhookEndpoint.objects.filter(is_active=True),
    })


@require_POST
def timer_start_view(request):
    minutes = _to_decimal(request.POST.get('minutes'))
    seconds = int(float(minutes) * 60) if minutes is not None else 0
    if not 0 < seconds <= MAX_TIMER_SECONDS:
        messages.error(request, "Enter a time between a few seconds and 24 hours.")
        return redirect('timers')
    reservoir = DosingReservoir.objects.filter(pk=_to_int(request.POST.get('reservoir'), None)).first()
    name = (request.POST.get('name') or '').strip()[:100] or (f"Fill {reservoir.name}" if reservoir else 'Timer')
    now = timezone.now()
    timer = FillTimer.objects.create(name=name, reservoir=reservoir, started_at=now, ends_at=now + timedelta(seconds=seconds))
    chosen = [pk for pk in (_to_int(raw, None) for raw in request.POST.getlist('endpoints')) if pk]
    timer.endpoints.set(WebhookEndpoint.objects.filter(pk__in=chosen))
    messages.success(request, f"Timer started: {name}.")
    return redirect('timers')


@require_POST
def timer_cancel_view(request, timer_id):
    FillTimer.objects.filter(pk=timer_id, status='running').update(status='cancelled')
    return redirect('timers')


@require_POST
def timer_extend_view(request, timer_id):
    timer = get_object_or_404(FillTimer, pk=timer_id)
    minutes = _to_int(request.POST.get('minutes'), 5, 1, 240)
    now = timezone.now()
    timer.ends_at = max(timer.ends_at, now) + timedelta(minutes=minutes)
    timer.status = 'running'
    timer.notified = False
    timer.save()
    return redirect('timers')


@require_POST
def timer_dismiss_view(request, timer_id):
    FillTimer.objects.filter(pk=timer_id).exclude(status='running').delete()
    return redirect('timers')


def ro_create_view(request):
    if request.method == 'POST':
        form = ROSystemForm(request.POST)
        if form.is_valid():
            system = form.save()
            _ensure_single_default(system)
            messages.success(request, f"Added {system.name}.")
            return redirect('timers')
    else:
        form = ROSystemForm(initial={'is_default': not ROSystem.objects.exists()})
    return _form_page(request, form, 'Add RO/DI System', reverse('timers'),
                      "Use your membrane's spec sheet. Time a real fill for the most accurate result.")


def _ensure_single_default(system):
    if system.is_default:
        ROSystem.objects.exclude(pk=system.pk).update(is_default=False)


def ro_edit_view(request, ro_id):
    response = _edit_object(request, ROSystem, ROSystemForm, ro_id, title='Edit RO/DI System',
                            back_url=reverse('timers'), delete_url=reverse('ro_delete', args=[ro_id]))
    if request.method == 'POST':
        system = ROSystem.objects.filter(pk=ro_id).first()
        if system:
            _ensure_single_default(system)
    return response


def ro_delete_view(request, ro_id):
    system = get_object_or_404(ROSystem, pk=ro_id)
    return _delete_object(request, ROSystem, ro_id, label=system.name, back_url=reverse('timers'))


def fill_calc_api(request):
    """Fill time for a volume on a chosen RO system (used by the calculator on the timers page)."""
    system = ROSystem.objects.filter(pk=_to_int(request.GET.get('system'), None)).first()
    gallons = _to_decimal(request.GET.get('gallons'))
    stop_at = _to_decimal(request.GET.get('stop_at'))
    if system is None or gallons is None:
        return JsonResponse({'error': 'Choose a system and an amount.'}, status=400)
    return JsonResponse(fill.fill_estimate(
        gallons, _system_gph(system), system.waste_ratio, stop_at if stop_at is not None else 100,
    ))


# ==========================================
# System planner
# ==========================================

def planner_list_view(request):
    plans = list(PlannedSystem.objects.select_related('existing_tank', 'tracked_tank').prefetch_related('items'))
    rows = [{'plan': plan, 'analysis': planner.analyze(plan)} for plan in plans]
    return render(request, 'aquarium/planner_list.html', {'rows': rows})


def plan_create_view(request):
    if request.method == 'POST':
        form = PlannedSystemForm(request.POST)
        if form.is_valid():
            plan = form.save()
            return redirect('plan_detail', plan_id=plan.pk)
    else:
        initial = {}
        tank_id = _to_int(request.GET.get('tank'), None)
        if tank_id:
            tank = Tank.objects.filter(pk=tank_id).first()
            if tank:
                initial = {'existing_tank': tank, 'name': f"Stocking plan for {tank.name}"}
        form = PlannedSystemForm(initial=initial)
    return _form_page(request, form, 'New System Plan', reverse('planner'),
                      'Sketch a system, or plan additions to a tank you already have')


def plan_detail_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem.objects.select_related('existing_tank', 'tracked_tank'), pk=plan_id)
    return render(request, 'aquarium/planner_detail.html', {
        'plan': plan,
        'a': planner.analyze(plan),
        'livestock_form': PlannedLivestockForm(prefix='animal'),
        'equipment_form': PlannedEquipmentForm(prefix='gear'),
    })


def plan_edit_view(request, plan_id):
    return _edit_object(request, PlannedSystem, PlannedSystemForm, plan_id, title='Edit Plan',
                        back_url=reverse('plan_detail', args=[plan_id]), delete_url=reverse('plan_delete', args=[plan_id]))


def plan_delete_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem, pk=plan_id)
    return _delete_object(request, PlannedSystem, plan_id, label=plan.name, back_url=reverse('planner'),
                          warning='Only the plan is deleted. Anything already being tracked stays.')


@require_POST
def plan_add_livestock_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem, pk=plan_id)
    form = PlannedLivestockForm(request.POST, prefix='animal')
    if form.is_valid():
        item = form.save(commit=False)
        item.plan = plan
        item.kind = 'livestock'
        item.name = item.species.name
        item.save()
        plan.save(update_fields=['updated_at'])
    else:
        _flash_form_errors(request, form)
    return redirect('plan_detail', plan_id=plan.pk)


@require_POST
def plan_add_equipment_view(request, plan_id):
    plan = get_object_or_404(PlannedSystem, pk=plan_id)
    form = PlannedEquipmentForm(request.POST, prefix='gear')
    if form.is_valid():
        item = form.save(commit=False)
        item.plan = plan
        item.kind = 'equipment'
        item.save()
        plan.save(update_fields=['updated_at'])
    else:
        _flash_form_errors(request, form)
    return redirect('plan_detail', plan_id=plan.pk)


@require_POST
def plan_item_delete_view(request, item_id):
    item = get_object_or_404(PlannedItem, pk=item_id)
    plan_id = item.plan_id
    item.delete()
    return redirect('plan_detail', plan_id=plan_id)


def plan_track_view(request, plan_id):
    """Review what will be created, then turn the plan into real tracked records."""
    plan = get_object_or_404(PlannedSystem.objects.select_related('existing_tank', 'tracked_tank'), pk=plan_id)
    target = plan.existing_tank or plan.tracked_tank
    pending = plan.items.filter(tracked=False)
    if request.method == 'POST':
        if not pending.exists() and target is not None:
            messages.info(request, "Everything in this plan is already being tracked.")
            return redirect('tank_detail', tank_id=target.pk)
        tank = planner.track_plan(plan, quarantine_fish=bool(request.POST.get('quarantine_fish')))
        messages.success(request, f"Now tracking {tank.name}.")
        return redirect('tank_detail', tank_id=tank.pk)
    return render(request, 'aquarium/planner_track.html', {
        'plan': plan, 'target': target, 'a': planner.analyze(plan),
        'pending_livestock': pending.filter(kind='livestock'),
        'pending_gear': pending.filter(kind='equipment'),
        'back_url': _safe_next(request, reverse('plan_detail', args=[plan.pk])),
    })


# ==========================================
# Wishlist
# ==========================================

def wishlist_view(request):
    items = wishlist.wanted_items()
    combined = wishlist.fit_summary(items)
    return render(request, 'aquarium/wishlist.html', {
        'items': items,
        'combined': combined,
        'total': sum(float(i.total_price) for i in items),
        'unpriced': sum(1 for i in items if i.est_price is None),
        'currency': AppSettings.load().currency_symbol,
        'bought': WishlistItem.objects.filter(status='acquired').select_related('tank').order_by('-acquired_at')[:10],
        'tanks': Tank.objects.all(),
        'plans': PlannedSystem.objects.all(),
        'livestock_form': WishlistLivestockForm(),
        'equipment_form': WishlistEquipmentForm(),
    })


def _wishlist_add(request, form_class):
    form = form_class(request.POST)
    if form.is_valid():
        item = form.save()
        messages.success(request, f"Added {item.name} to your wishlist.")
    else:
        _flash_form_errors(request, form)
    return redirect('wishlist')


@require_POST
def wishlist_add_livestock_view(request):
    return _wishlist_add(request, WishlistLivestockForm)


@require_POST
def wishlist_add_equipment_view(request):
    return _wishlist_add(request, WishlistEquipmentForm)


@require_POST
def wishlist_add_species_view(request, species_id):
    """The one-tap button on species catalog cards."""
    species = get_object_or_404(SpeciesCatalog, pk=species_id)
    if WishlistItem.objects.filter(species=species, status='wanted').exists():
        messages.info(request, f"{species.name} is already on your wishlist.")
    else:
        WishlistItem.objects.create(kind='livestock', species=species, name=species.name)
        messages.success(request, f"Added {species.name} to your wishlist.")
    return redirect(_safe_next(request, reverse('wishlist')))


def wishlist_edit_view(request, item_id):
    item = get_object_or_404(WishlistItem, pk=item_id)
    form_class = WishlistEquipmentForm if item.kind == 'equipment' else WishlistLivestockForm
    return _edit_object(request, WishlistItem, form_class, item_id, title=f"Edit {item.name}", back_url=reverse('wishlist'))


@require_POST
def wishlist_delete_view(request, item_id):
    WishlistItem.objects.filter(pk=item_id).delete()
    return redirect('wishlist')


@require_POST
def wishlist_to_plan_view(request, item_id):
    item = get_object_or_404(WishlistItem, pk=item_id)
    plan = get_object_or_404(PlannedSystem, pk=_to_int(request.POST.get('plan'), 0))
    if wishlist.add_to_plan(item, plan):
        messages.success(request, f"Added {item.name} to {plan.name}.")
    else:
        messages.info(request, f"{item.name} is already in a plan or bought.")
    return redirect('wishlist')


@require_POST
def wishlist_bought_view(request, item_id):
    item = get_object_or_404(WishlistItem, pk=item_id)
    tank = Tank.objects.filter(pk=_to_int(request.POST.get('tank'), 0)).first() or wishlist.primary_tank()
    if wishlist.mark_bought(item, tank, quarantine=bool(request.POST.get('quarantine'))):
        messages.success(request, f"Nice! {item.name} is now tracked{f' in {tank.name}' if tank else ''}.")
    else:
        messages.info(request, f"{item.name} was already added.")
    return redirect('wishlist')
