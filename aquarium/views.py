import json
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Q
from .models import (
    ParameterType, ParameterLog, Animal, AnimalGroup, WebcamFeed, SpeciesCatalog,
    Tank, Equipment, DosingReservoir, MaintenanceRoutine, WaterChangeLog
)
from .forms import (
    QuickParameterLogForm, AnimalForm, ParameterSettingsForm,
    TankForm, EquipmentForm, DosingReservoirForm, WaterChangeLogForm, MaintenanceRoutineForm,
    AnimalGroupForm
)
from .conversions import PARAMETER_UNIT_SUGGESTIONS, convert_value, suggest_decimals
from .calculators import calculate_salt_mix, SALT_MIX_RECIPES


def dashboard_view(request):
    """Main dashboard: latest parameters, quick-add, livestock overview, mini webcam, and alert notifications."""
    parameter_types = ParameterType.objects.all()
    recent_logs = ParameterLog.objects.select_related('parameter_type')[:8]
    total_animals = Animal.objects.filter(status='healthy').aggregate(total=Sum('count'))['total'] or 0
    groups = AnimalGroup.objects.all()
    featured_animals = Animal.objects.all()[:6]
    active_cameras = WebcamFeed.objects.filter(is_active=True)[:2]
    form = QuickParameterLogForm()

    # Calculate active system notifications & reminders
    low_reservoirs = [r for r in DosingReservoir.objects.all() if r.is_low]
    due_routines = [r for r in MaintenanceRoutine.objects.all() if r.is_due]
    due_equipment = [e for e in Equipment.objects.all() if e.is_service_due]

    # Out of ideal range parameters
    out_of_range_params = []
    for pt in parameter_types:
        latest = pt.latest_log()
        if latest and latest.status in ['low', 'high']:
            out_of_range_params.append({'param': pt, 'log': latest})

    return render(request, 'aquarium/dashboard.html', {
        'parameter_types': parameter_types,
        'recent_logs': recent_logs,
        'total_animals': total_animals,
        'groups': groups,
        'featured_animals': featured_animals,
        'active_cameras': active_cameras,
        'form': form,
        'low_reservoirs': low_reservoirs,
        'due_routines': due_routines,
        'due_equipment': due_equipment,
        'out_of_range_params': out_of_range_params,
    })


def parameters_view(request):
    """Full parameter management, historical logs, and interactive charts."""
    param_code = request.GET.get('param')
    types = ParameterType.objects.all()

    logs_query = ParameterLog.objects.select_related('parameter_type')
    selected_param = None
    if param_code:
        logs_query = logs_query.filter(parameter_type__code=param_code)
        selected_param = ParameterType.objects.filter(code=param_code).first()
    elif types.exists():
        selected_param = types.first()

    recent_logs = logs_query[:50]
    form = QuickParameterLogForm()

    return render(request, 'aquarium/parameters.html', {
        'parameter_types': types,
        'selected_code': param_code,
        'selected_param': selected_param,
        'recent_logs': recent_logs,
        'form': form,
    })


def parameter_settings_view(request, param_id):
    """
    Manage unit, decimal precision, ideal target ranges, and
    optionally convert all previous historical values to the new unit.
    """
    ptype = get_object_or_404(ParameterType, id=param_id)
    suggestions = PARAMETER_UNIT_SUGGESTIONS.get(ptype.code, [])
    logs_count = ptype.logs.count()

    if request.method == 'POST':
        form = ParameterSettingsForm(request.POST, instance=ptype)
        if form.is_valid():
            old_unit = ptype.unit
            new_unit = form.cleaned_data['unit'].strip()
            convert_history = form.cleaned_data.get('convert_history', False)

            with transaction.atomic():
                # If unit changed and user requested conversion of historical entries
                if convert_history and old_unit.lower() != new_unit.lower():
                    for log in ptype.logs.all():
                        new_val = convert_value(float(log.value), old_unit, new_unit)
                        log.value = Decimal(f"{new_val:.4f}")
                        log.save(update_fields=['value'])

                form.save()

            return redirect(f"/parameters/?param={ptype.code}")
    else:
        form = ParameterSettingsForm(instance=ptype)

    return render(request, 'aquarium/parameter_settings.html', {
        'parameter': ptype,
        'form': form,
        'suggestions': suggestions,
        'logs_count': logs_count,
    })


def api_chart_data(request):
    """JSON API endpoint powering dynamic Chart.js rendering."""
    param_code = request.GET.get('code')
    days = int(request.GET.get('days', 30))

    if not param_code:
        ptype = ParameterType.objects.first()
    else:
        ptype = ParameterType.objects.filter(code=param_code).first()

    if not ptype:
        return JsonResponse({'error': 'No parameter found'}, status=404)

    start_date = timezone.now() - timedelta(days=days)
    logs = ParameterLog.objects.filter(
        parameter_type=ptype,
        measured_at__gte=start_date
    ).order_by('measured_at')

    labels = [log.measured_at.strftime('%m/%d %H:%M') for log in logs]
    values = [round(float(log.value), ptype.decimal_places) if ptype.decimal_places > 0 else round(float(log.value)) for log in logs]

    return JsonResponse({
        'parameter': {
            'name': ptype.name,
            'unit': ptype.unit,
            'decimal_places': ptype.decimal_places,
            'min_ideal': float(ptype.min_ideal),
            'max_ideal': float(ptype.max_ideal),
            'formatted_min': ptype.formatted_min_ideal,
            'formatted_max': ptype.formatted_max_ideal,
            'color': ptype.color,
        },
        'labels': labels,
        'values': values,
    })


def api_all_chart_data(request):
    """JSON API endpoint returning all parameter datasets for multi-line Chart.js rendering."""
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)
    parameter_types = ParameterType.objects.all()

    datasets = []
    all_labels = set()

    for ptype in parameter_types:
        logs = ParameterLog.objects.filter(
            parameter_type=ptype,
            measured_at__gte=start_date
        ).order_by('measured_at')

        if not logs.exists():
            continue

        labels = [log.measured_at.strftime('%m/%d %H:%M') for log in logs]
        values = [
            round(float(log.value), ptype.decimal_places) if ptype.decimal_places > 0
            else round(float(log.value))
            for log in logs
        ]
        all_labels.update(labels)

        datasets.append({
            'code': ptype.code,
            'name': ptype.name,
            'unit': ptype.unit,
            'color': ptype.color,
            'min_ideal': float(ptype.min_ideal),
            'max_ideal': float(ptype.max_ideal),
            'labels': labels,
            'values': values,
        })

    return JsonResponse({'datasets': datasets, 'days': days})


def alerts_view(request):
    """Priority-sorted alerts list with colour-coded urgency tiers (red/orange/yellow/green)."""
    from datetime import date as date_cls
    today = date_cls.today()
    alerts = []

    # --- Water Chemistry: out-of-range parameters ---
    for pt in ParameterType.objects.all():
        latest = pt.latest_log()
        if latest and latest.status in ['low', 'high']:
            alerts.append({
                'priority': 1,  # Red — immediate action
                'color': 'red',
                'icon': '🧪',
                'title': f'{pt.name} out of range',
                'detail': f'Measured {latest.formatted_value} {pt.unit} '
                          f'(ideal {pt.formatted_min_ideal}–{pt.formatted_max_ideal} {pt.unit})',
                'action_label': 'View Parameters',
                'action_url': f'/parameters/?param={pt.code}',
                'category': 'Chemistry',
            })

    # --- Sick / Quarantined Livestock ---
    for animal in Animal.objects.filter(status__in=['quarantine', 'monitoring']).select_related('tank'):
        alerts.append({
            'priority': 1,
            'color': 'red',
            'icon': '🐠',
            'title': f'{animal.name} needs attention',
            'detail': f'Status: {animal.get_status_display()}' + (f' — Tank: {animal.tank}' if animal.tank else ''),
            'action_label': 'View Livestock',
            'action_url': '/livestock/',
            'category': 'Livestock',
        })

    # --- Equipment overdue for service ---
    for eq in Equipment.objects.select_related('tank').all():
        if eq.is_service_due:
            alerts.append({
                'priority': 2,  # Orange — overdue
                'color': 'orange',
                'icon': '⚙️',
                'title': f'{eq.name} service overdue',
                'detail': (f'Last serviced: {eq.last_serviced.strftime("%b %d, %Y")} '
                           f'(every {eq.service_interval_days}d)')
                          if eq.last_serviced else 'Never serviced',
                'action_label': 'View Equipment',
                'action_url': '/equipment/',
                'category': 'Equipment',
            })

    # --- Reservoirs critically low (<15%) or <3 days ---
    for res in DosingReservoir.objects.select_related('tank').all():
        if not res.is_low:
            continue
        pct = res.percent_remaining
        days_left = res.days_remaining
        if pct < 15 or (days_left is not None and days_left < 3):
            priority, color = 2, 'orange'
        else:
            priority, color = 3, 'yellow'
        alerts.append({
            'priority': priority,
            'color': color,
            'icon': '🧴',
            'title': f'{res.name} reservoir low',
            'detail': f'{pct}% remaining' + (f' (~{days_left} days)' if days_left is not None else ''),
            'action_label': 'View Dosing',
            'action_url': '/dosing/',
            'category': 'Dosing',
        })

    # --- Maintenance routines due ---
    for rt in MaintenanceRoutine.objects.select_related('tank').all():
        if not rt.is_due:
            continue
        alerts.append({
            'priority': 3,  # Yellow — due soon / overdue routine
            'color': 'yellow',
            'icon': '📋',
            'title': f'Routine due: {rt.title}',
            'detail': f'Repeats every {rt.frequency_days} day(s)' + (f' — {rt.tank}' if rt.tank else ''),
            'action_label': 'View Routines',
            'action_url': '/routines/',
            'category': 'Routine',
        })

    # Sort: priority ascending (1=red first), then category
    alerts.sort(key=lambda a: (a['priority'], a['category']))

    # Count by colour tier
    counts = {
        'red': sum(1 for a in alerts if a['color'] == 'red'),
        'orange': sum(1 for a in alerts if a['color'] == 'orange'),
        'yellow': sum(1 for a in alerts if a['color'] == 'yellow'),
    }
    all_clear = len(alerts) == 0

    return render(request, 'aquarium/alerts.html', {
        'alerts': alerts,
        'counts': counts,
        'all_clear': all_clear,
        'total': len(alerts),
    })


def quick_log_create(request):
    """Handles quick-add parameter submissions via HTMX or standard form POST."""
    if request.method == 'POST':
        form = QuickParameterLogForm(request.POST)
        if form.is_valid():
            log = form.save()
            if getattr(request, 'htmx', False):
                response = render(request, 'aquarium/partials/parameter_log_row.html', {'log': log})
                response['HX-Trigger'] = 'logAdded'
                return response
            return redirect('dashboard')
        else:
            if getattr(request, 'htmx', False):
                return HttpResponse(f"<div class='text-rose-400 text-sm'>Validation error: {form.errors}</div>", status=400)
    return redirect('dashboard')


def delete_log(request, log_id):
    """Delete a log entry (supports HTMX delete)."""
    if request.method in ['POST', 'DELETE']:
        log = get_object_or_404(ParameterLog, id=log_id)
        log.delete()
        if getattr(request, 'htmx', False):
            response = HttpResponse("")
            response['HX-Trigger'] = 'logDeleted'
            return response
        return redirect('parameters')
    return HttpResponse(status=405)


# ==========================================
# REST API: Parameter Ingestion & Types
# ==========================================

def api_parameter_types(request):
    """GET /api/parameters/types/ - Returns metadata of all tracked parameters."""
    types = ParameterType.objects.all()
    data = [
        {
            'id': pt.id,
            'name': pt.name,
            'code': pt.code,
            'unit': pt.unit,
            'decimal_places': pt.decimal_places,
            'min_ideal': float(pt.min_ideal),
            'max_ideal': float(pt.max_ideal),
            'formatted_min': pt.formatted_min_ideal,
            'formatted_max': pt.formatted_max_ideal,
            'color': pt.color,
        }
        for pt in types
    ]
    return JsonResponse({'parameters': data})


@csrf_exempt
def api_parameter_log(request):
    """
    POST /api/parameters/log/ - Endpoint to log parameter readings via API calls.
    Accepts single reading or batch list of readings.
    Supports JSON or standard form encoded payloads.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    # Optional API key check if configured
    api_key = getattr(settings, 'API_SECRET_KEY', '')
    if api_key:
        incoming_key = request.headers.get('X-API-Key') or ''
        auth_header = request.headers.get('Authorization') or ''
        if auth_header.startswith('Bearer '):
            incoming_key = auth_header.split('Bearer ', 1)[1].strip()

        if incoming_key != api_key:
            return JsonResponse({'error': 'Unauthorized: Invalid or missing API key'}, status=401)

    # Parse request body
    try:
        if request.content_type == 'application/json':
            payload = json.loads(request.body.decode('utf-8'))
        else:
            payload = {
                'parameter': request.POST.get('parameter'),
                'value': request.POST.get('value'),
                'notes': request.POST.get('notes', ''),
                'measured_at': request.POST.get('measured_at')
            }
    except Exception as e:
        return JsonResponse({'error': f'Invalid JSON payload: {str(e)}'}, status=400)

    # Normalize into a list of readings
    if isinstance(payload, list):
        readings = payload
    elif isinstance(payload, dict):
        if 'readings' in payload and isinstance(payload['readings'], list):
            readings = payload['readings']
        else:
            readings = [payload]
    else:
        return JsonResponse({'error': 'Payload must be a JSON object or array of objects.'}, status=400)

    if not readings:
        return JsonResponse({'error': 'No readings provided in payload.'}, status=400)

    # Map existing parameter types for fast matching
    all_types = list(ParameterType.objects.all())
    code_map = {pt.code.lower(): pt for pt in all_types}
    name_map = {pt.name.lower(): pt for pt in all_types}
    id_map = {pt.id: pt for pt in all_types}

    created_logs = []
    errors = []

    for index, r in enumerate(readings):
        param_identifier = str(r.get('parameter') or '').strip()
        val_raw = r.get('value')
        notes = r.get('notes', '')
        timestamp_raw = r.get('measured_at')

        if not param_identifier:
            errors.append(f"Reading #{index + 1}: Missing 'parameter' field.")
            continue

        if val_raw is None or val_raw == '':
            errors.append(f"Reading #{index + 1} ({param_identifier}): Missing 'value' field.")
            continue

        try:
            val_decimal = Decimal(str(val_raw))
        except (InvalidOperation, ValueError):
            errors.append(f"Reading #{index + 1} ({param_identifier}): Invalid numeric value '{val_raw}'.")
            continue

        # Match parameter type by code, name, or integer ID
        ptype = None
        if param_identifier.isdigit():
            ptype = id_map.get(int(param_identifier))
        if not ptype:
            ptype = code_map.get(param_identifier.lower())
        if not ptype:
            ptype = name_map.get(param_identifier.lower())

        if not ptype:
            valid_codes = list(code_map.keys())
            errors.append(f"Reading #{index + 1}: Unknown parameter '{param_identifier}'. Valid codes: {valid_codes}")
            continue

        # Parse timestamp or default to now
        measured_at = timezone.now()
        if timestamp_raw:
            parsed_dt = parse_datetime(str(timestamp_raw))
            if parsed_dt:
                if timezone.is_naive(parsed_dt):
                    parsed_dt = timezone.make_aware(parsed_dt, timezone.get_current_timezone())
                measured_at = parsed_dt

        # Create log record
        log = ParameterLog.objects.create(
            parameter_type=ptype,
            value=val_decimal,
            notes=notes,
            measured_at=measured_at
        )

        created_logs.append({
            'id': log.id,
            'parameter': ptype.name,
            'code': ptype.code,
            'value': float(log.value),
            'formatted_value': log.formatted_value,
            'unit': ptype.unit,
            'decimal_places': ptype.decimal_places,
            'status': log.status,
            'measured_at': log.measured_at.isoformat(),
            'notes': log.notes,
        })

    if errors and not created_logs:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    response_data = {
        'success': True,
        'count': len(created_logs),
        'logs': created_logs,
    }
    if errors:
        response_data['warnings'] = errors

    return JsonResponse(response_data, status=201)


# ==========================================
# In-App Livestock GUI (View, Add, Edit, Delete)
# ==========================================

def livestock_view(request):
    """Livestock listing with group filtering, tank filtering, and built-in Add Modals."""
    group_id = request.GET.get('group')
    status_filter = request.GET.get('status')
    tank_id = request.GET.get('tank')

    animals = Animal.objects.select_related('tank').prefetch_related('groups').all()
    if group_id:
        animals = animals.filter(groups__id=group_id)
    if status_filter:
        animals = animals.filter(status=status_filter)
    if tank_id:
        animals = animals.filter(tank_id=tank_id)

    groups = AnimalGroup.objects.all()
    tanks = Tank.objects.all()
    form = AnimalForm()
    group_form = AnimalGroupForm()

    return render(request, 'aquarium/livestock.html', {
        'animals': animals,
        'groups': groups,
        'tanks': tanks,
        'selected_group': int(group_id) if group_id else None,
        'selected_status': status_filter,
        'selected_tank': int(tank_id) if tank_id else None,
        'form': form,
        'group_form': group_form,
    })


def group_create_view(request):
    """Quick-add a custom animal group in GUI."""
    if request.method == 'POST':
        form = AnimalGroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            return redirect(f"/livestock/?group={group.id}")
    return redirect('livestock')


def animal_create_view(request):
    """Create a new animal directly from the GUI (supports modal POST or dedicated page)."""
    if request.method == 'POST':
        form = AnimalForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('livestock')
    else:
        initial = {}
        species_id = request.GET.get('species_id')
        if species_id:
            sp = SpeciesCatalog.objects.filter(id=species_id).first()
            if sp:
                initial = {
                    'name': sp.name,
                    'species': sp.species,
                    'notes': f"Care: {sp.care_level}. Diet: {sp.diet}. {sp.notes}".strip(),
                    'new_group_name': sp.suggested_group,
                }
        form = AnimalForm(initial=initial)

    return render(request, 'aquarium/animal_form.html', {
        'form': form,
        'title': 'Add Unlisted Specimen',
        'is_edit': False
    })


def animal_edit_view(request, animal_id):
    """Edit an existing animal directly in the GUI."""
    animal = get_object_or_404(Animal, id=animal_id)
    if request.method == 'POST':
        form = AnimalForm(request.POST, request.FILES, instance=animal)
        if form.is_valid():
            form.save()
            return redirect('livestock')
    else:
        form = AnimalForm(instance=animal)

    return render(request, 'aquarium/animal_form.html', {
        'form': form,
        'animal': animal,
        'title': f'Edit {animal.name}',
        'is_edit': True
    })


def animal_upload_photo_view(request, animal_id):
    """Fast 1-click photo upload or replacement directly from the livestock card."""
    animal = get_object_or_404(Animal, id=animal_id)
    if request.method == 'POST' and request.FILES.get('photo'):
        animal.photo = request.FILES['photo']
        animal.save(update_fields=['photo'])
    return redirect('livestock')


def animal_delete_view(request, animal_id):
    """Delete an animal from the tank with confirmation."""
    animal = get_object_or_404(Animal, id=animal_id)
    if request.method == 'POST':
        animal.delete()
        return redirect('livestock')
    return render(request, 'aquarium/animal_confirm_delete.html', {'animal': animal})


# ==========================================
# Species Catalog: Common Animals Lookup & Quick Add
# ==========================================

def species_catalog_view(request):
    """Browse common saltwater species catalog with category filters and search."""
    category = request.GET.get('category')
    search_query = request.GET.get('q', '').strip()

    species_list = SpeciesCatalog.objects.all()
    if category and category != 'all':
        species_list = species_list.filter(category=category)
    if search_query:
        species_list = species_list.filter(
            Q(name__icontains=search_query) |
            Q(species__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(diet__icontains=search_query)
        )

    tanks = Tank.objects.all()
    return render(request, 'aquarium/species_catalog.html', {
        'species_list': species_list,
        'tanks': tanks,
        'selected_category': category or 'all',
        'search_query': search_query,
    })


def species_add_to_tank(request, species_id):
    """1-click or quantity-prompt add from common species catalog into active tank roster."""
    species = get_object_or_404(SpeciesCatalog, id=species_id)

    if request.method == 'POST':
        count = int(request.POST.get('count', 1))
        if count < 1:
            count = 1

        # Resolve assigned tank (or default to primary)
        tank_id = request.POST.get('tank')
        target_tank = None
        if tank_id:
            target_tank = Tank.objects.filter(id=tank_id).first()
        if not target_tank:
            target_tank = Tank.objects.filter(is_primary=True).first()

        # Find or create corresponding AnimalGroup
        group_name = species.suggested_group or 'Fish'
        group_obj, _ = AnimalGroup.objects.get_or_create(
            name=group_name,
            defaults={'icon': species.icon, 'color': '#0ea5e9'}
        )

        # Build helpful starter notes
        care_notes = f"Care: {species.care_level}. Diet: {species.diet}. {species.notes}".strip()

        # Create animal
        animal = Animal.objects.create(
            name=species.name,
            species=species.species,
            tank=target_tank,
            count=count,
            status='healthy',
            notes=care_notes,
            acquired_date=timezone.now().date()
        )
        animal.groups.add(group_obj)

        return redirect('livestock')

    # If GET, redirect back to catalog
    return redirect('species_catalog')


def api_species_catalog(request):
    """JSON API returning common species for search / form autocomplete."""
    species = SpeciesCatalog.objects.all()
    data = [
        {
            'id': s.id,
            'name': s.name,
            'species': s.species,
            'category': s.category,
            'suggested_group': s.suggested_group,
            'care_level': s.care_level,
            'reef_safe': s.reef_safe,
            'diet': s.diet,
            'notes': s.notes,
            'icon': s.icon,
        }
        for s in species
    ]
    return JsonResponse({'species': data})


def webcams_view(request):
    """Live aquarium webcam feeds."""
    feeds = WebcamFeed.objects.filter(is_active=True)
    return render(request, 'aquarium/webcams.html', {
        'feeds': feeds,
    })


# ==========================================
# Dosing & ATO Reservoirs
# ==========================================

def dosing_view(request):
    """Dosing additive reservoirs and ATO fresh water levels and days-remaining forecasts."""
    tanks = Tank.objects.all()
    reservoirs = DosingReservoir.objects.select_related('tank').all()
    dosing_containers = reservoirs.filter(reservoir_type='dosing_additive')
    ato_containers = reservoirs.filter(reservoir_type='ato_freshwater')

    form = DosingReservoirForm()

    return render(request, 'aquarium/dosing.html', {
        'tanks': tanks,
        'dosing_containers': dosing_containers,
        'ato_containers': ato_containers,
        'form': form,
    })


def refill_reservoir_view(request, res_id):
    """Refills a dosing container or ATO reservoir to full or to a custom level."""
    reservoir = get_object_or_404(DosingReservoir, id=res_id)
    if request.method == 'POST':
        new_level = request.POST.get('custom_level')
        if new_level:
            try:
                reservoir.current_level = Decimal(new_level)
            except (ValueError, InvalidOperation):
                reservoir.current_level = reservoir.capacity
        else:
            reservoir.current_level = reservoir.capacity

        reservoir.last_refilled_date = timezone.now().date()
        reservoir.save()
        return redirect('dosing')

    return redirect('dosing')


def dosing_create_view(request):
    """Create a new dosing container or ATO reservoir."""
    if request.method == 'POST':
        form = DosingReservoirForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dosing')
    return redirect('dosing')


# ==========================================
# Equipment & Tanks Management
# ==========================================

def equipment_view(request):
    """Equipment hardware roster assigned to tanks with maintenance tracking."""
    tanks = Tank.objects.prefetch_related('equipment').all()
    selected_tank_id = request.GET.get('tank')
    selected_category = request.GET.get('category')

    equipment_list = Equipment.objects.select_related('tank').all()
    if selected_tank_id:
        equipment_list = equipment_list.filter(tank_id=selected_tank_id)
    if selected_category:
        equipment_list = equipment_list.filter(category=selected_category)

    equipment_form = EquipmentForm()
    tank_form = TankForm()

    # Total system power draw
    total_watts = equipment_list.aggregate(total=Sum('wattage'))['total'] or 0

    return render(request, 'aquarium/equipment.html', {
        'tanks': tanks,
        'equipment_list': equipment_list,
        'selected_tank_id': int(selected_tank_id) if selected_tank_id else None,
        'selected_category': selected_category,
        'equipment_form': equipment_form,
        'tank_form': tank_form,
        'total_watts': total_watts,
        'categories': Equipment.CATEGORY_CHOICES,
    })


def service_equipment_view(request, eq_id):
    """Marks an equipment piece serviced/cleaned today."""
    eq = get_object_or_404(Equipment, id=eq_id)
    if request.method == 'POST':
        eq.last_serviced_date = timezone.now().date()
        eq.status = 'operational'
        eq.save()
        return redirect('equipment')
    return redirect('equipment')


def equipment_create_view(request):
    if request.method == 'POST':
        form = EquipmentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('equipment')
    return redirect('equipment')


def tank_create_view(request):
    if request.method == 'POST':
        form = TankForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('equipment')
    return redirect('equipment')


# ==========================================
# Maintenance Routines & Water Change Checklists
# ==========================================

def routines_view(request):
    """Recurring tank checklists, water change preparation calculator, and change logs."""
    routines = MaintenanceRoutine.objects.all()
    water_changes = WaterChangeLog.objects.select_related('tank')[:10]
    tanks = Tank.objects.all()
    wc_form = WaterChangeLogForm()
    routine_form = MaintenanceRoutineForm()

    # Pre-calculated 10 gal Tropic Marin recipe for quick display
    sample_mix = calculate_salt_mix(volume=10.0, volume_unit='gal', brand_key='tropic_marin_pro', target_salinity=1.026, salinity_unit='sg')

    return render(request, 'aquarium/routines.html', {
        'routines': routines,
        'water_changes': water_changes,
        'tanks': tanks,
        'wc_form': wc_form,
        'routine_form': routine_form,
        'sample_mix': sample_mix,
        'salt_brands': SALT_MIX_RECIPES,
    })


def complete_routine_view(request, routine_id):
    """Marks a checklist routine completed today."""
    routine = get_object_or_404(MaintenanceRoutine, id=routine_id)
    if request.method == 'POST':
        routine.last_completed = timezone.now()
        routine.save()
        return redirect('routines')
    return redirect('routines')


def routine_create_view(request):
    """Creates a new custom maintenance routine / checklist directly in GUI."""
    if request.method == 'POST':
        form = MaintenanceRoutineForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('routines')
    return redirect('routines')


def routine_delete_view(request, routine_id):
    """Deletes a custom routine."""
    routine = get_object_or_404(MaintenanceRoutine, id=routine_id)
    if request.method == 'POST':
        routine.delete()
        return redirect('routines')
    return redirect('routines')


def water_change_calc_api(request):
    """API endpoint returning exact salt weight (g, oz, lbs) and cups needed for specified volume."""
    try:
        volume = float(request.GET.get('volume', request.GET.get('gallons', 10.0)))
        volume_unit = request.GET.get('volume_unit', 'gal').lower()
        brand = request.GET.get('brand', 'tropic_marin_pro')
        salinity = float(request.GET.get('salinity', 1.026))
        salinity_unit = request.GET.get('salinity_unit', 'sg').lower()

        result = calculate_salt_mix(
            volume=volume,
            volume_unit=volume_unit,
            brand_key=brand,
            target_salinity=salinity,
            salinity_unit=salinity_unit
        )
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def water_change_log_create(request):
    if request.method == 'POST':
        form = WaterChangeLogForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('routines')
    return redirect('routines')


# ==========================================
# Alerts & Notifications Center
# ==========================================

def notifications_view(request):
    """Dedicated Alerts & Notifications Center with health scoring and community resources."""
    parameter_types = ParameterType.objects.all()

    # Out of range params
    out_of_range_params = []
    for pt in parameter_types:
        latest = pt.latest_log()
        if latest and latest.status in ['low', 'high']:
            out_of_range_params.append({'param': pt, 'log': latest})

    # Reservoirs
    low_reservoirs = [r for r in DosingReservoir.objects.select_related('tank').all() if r.is_low]

    # Routines
    due_routines = [r for r in MaintenanceRoutine.objects.select_related('tank').all() if r.is_due]

    # Equipment
    due_equipment = [e for e in Equipment.objects.select_related('tank').all() if e.is_service_due]

    # Sick / Quarantined Animals
    sick_animals = Animal.objects.filter(status__in=['quarantine', 'monitoring']).select_related('tank')

    # Tank Stability / Health Score calculation (100 base)
    score_penalty = (
        len(out_of_range_params) * 12 +
        len(low_reservoirs) * 8 +
        len(due_routines) * 6 +
        len(due_equipment) * 6 +
        sick_animals.count() * 15
    )
    health_score = max(25, 100 - score_penalty)

    total_alerts = (
        len(out_of_range_params) +
        len(low_reservoirs) +
        len(due_routines) +
        len(due_equipment) +
        sick_animals.count()
    )

    # Curated Reef2Reef Forums Directory
    r2r_forums = [
        {
            'name': 'Reef Chemistry Forum',
            'desc': 'Alkalinity, Calcium, Magnesium, Nitrate, Phosphate advice by Randy Holmes-Farley',
            'icon': '🧪',
            'url': 'https://www.reef2reef.com/forums/reef-chemistry-forum.73/'
        },
        {
            'name': 'Fish Disease & Treatment',
            'desc': 'Ich, Velvet, Flukes, Bacterial infections diagnosis & medication guides by Humblefish & team',
            'icon': '🩺',
            'url': 'https://www.reef2reef.com/forums/fish-disease-treatment-and-diagnosis.77/'
        },
        {
            'name': 'General Coral Discussion',
            'desc': 'SPS, LPS, and Soft Coral care, polyp extension, PAR requirements & placement',
            'icon': '🪸',
            'url': 'https://www.reef2reef.com/forums/general-coral-discussion.75/'
        },
        {
            'name': 'Equipment & Hardware',
            'desc': 'Wavemakers, skimmers, return pumps, and lighting reviews & troubleshooting',
            'icon': '⚙️',
            'url': 'https://www.reef2reef.com/forums/equipment-lighting-hardware.212/'
        },
        {
            'name': 'Reef2Reef Main Community',
            'desc': 'World-class saltwater community, tank build threads, and discussions',
            'icon': '🌊',
            'url': 'https://www.reef2reef.com/'
        },
    ]

    return render(request, 'aquarium/notifications.html', {
        'out_of_range_params': out_of_range_params,
        'low_reservoirs': low_reservoirs,
        'due_routines': due_routines,
        'due_equipment': due_equipment,
        'sick_animals': sick_animals,
        'total_alerts': total_alerts,
        'health_score': health_score,
        'r2r_forums': r2r_forums,
    })

