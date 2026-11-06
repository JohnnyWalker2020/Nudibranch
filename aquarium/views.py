import hmac
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .alerts import compute_alert_state
from .calculators import (
    DOSE_CHEMICALS, DOSE_PARAMETERS, MAX_DAILY_RAISE, SALT_MIX_RECIPES,
    calculate_salt_mix, dose_estimate, estimate_daily_change,
)
from .conversions import PARAMETER_UNIT_SUGGESTIONS, convert_value
from .dashboard_widgets import get_dashboard_layout, reset_dashboard_layout, save_dashboard_layout
from .forms import (
    AnimalForm, AnimalGroupForm, DosingReservoirForm, EquipmentForm, MaintenanceRoutineForm,
    ParameterLogEditForm, ParameterSettingsForm, ParameterTypeForm, QuickParameterLogForm,
    SumpChamberForm, SumpForm, TankForm, WaterChangeLogForm, WebcamFeedForm,
)
from .models import (
    Animal, AnimalGroup, DosingReservoir, Equipment, MaintenanceRoutine, ParameterLog,
    ParameterType, SpeciesCatalog, Sump, SumpChamber, Tank, WaterChangeLog, WebcamFeed,
    reef2reef_search,
)


# ==========================================
# Small shared helpers
# ==========================================

def _safe_next(request, default):
    """Redirect target from ?next= / POST next, only if it points back at this site."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return default


def _flash_form_errors(request, form, prefix="Couldn't save"):
    """Surface form validation problems as toast messages instead of silently redirecting."""
    problems = []
    for field, errs in form.errors.items():
        label = form.fields[field].label or field.replace('_', ' ').title() if field in form.fields else ''
        for err in errs:
            problems.append(f"{label}: {err}" if label else str(err))
    messages.error(request, f"{prefix}: " + "; ".join(problems) if problems else prefix)


def _to_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _to_decimal(raw):
    """Parses '8.4' or '8,4' into a Decimal, or returns None."""
    if raw is None:
        return None
    text = str(raw).strip().replace(',', '.')
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _edit_object(request, model, form_class, pk, *, title, subtitle='', back_url, delete_url=None):
    """Generic edit page used by most models."""
    obj = get_object_or_404(model, pk=pk)
    next_url = _safe_next(request, back_url)
    if request.method == 'POST':
        form = form_class(request.POST, request.FILES or None, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Saved.")
            return redirect(next_url)
    else:
        form = form_class(instance=obj)
    return render(request, 'aquarium/generic_form.html', {
        'form': form,
        'title': title,
        'subtitle': subtitle,
        'back_url': next_url,
        'delete_url': delete_url,
        'multipart': any(getattr(f.field.widget, 'input_type', '') == 'file' for f in form),
    })


def _delete_object(request, model, pk, *, label, back_url, warning=''):
    """Generic confirm-then-delete page."""
    obj = get_object_or_404(model, pk=pk)
    next_url = _safe_next(request, back_url)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, f"Deleted {label}.")
        return redirect(next_url)
    return render(request, 'aquarium/generic_confirm_delete.html', {
        'object_label': label,
        'warning': warning,
        'back_url': next_url,
    })


# ==========================================
# Dashboard (customizable)
# ==========================================

def dashboard_view(request):
    """Main dashboard. Which widgets show, and in what order, is stored in the database."""
    parameter_types = ParameterType.objects.all()
    layout = get_dashboard_layout()
    enabled_keys = {w['key'] for w in layout if w['enabled']}

    context = {
        'parameter_types': parameter_types,
        'form': QuickParameterLogForm(),
        'layout': layout,
        'visible_widgets': [w for w in layout if w['enabled']],
        'all_widgets': layout,
    }
    context.update(compute_alert_state(request))

    # Only run the queries a visible widget actually needs.
    if 'recent_logs' in enabled_keys:
        context['recent_logs'] = ParameterLog.objects.select_related('parameter_type')[:8]
    if 'livestock' in enabled_keys:
        active = Animal.objects.exclude(status__in=['rehomed', 'deceased'])
        context['total_animals'] = active.aggregate(total=Sum('count'))['total'] or 0
        context['groups'] = AnimalGroup.objects.all()
        context['featured_animals'] = active[:6]
    if 'webcam' in enabled_keys:
        context['active_cameras'] = WebcamFeed.objects.filter(is_active=True)[:2]
    if 'reservoirs' in enabled_keys:
        context['reservoirs'] = DosingReservoir.objects.select_related('tank')
    if 'tank_summary' in enabled_keys:
        tanks = Tank.objects.prefetch_related('sumps', 'equipment')
        context['tank_summaries'] = [{'tank': t, 'flow': t.flow_summary()} for t in tanks]

    return render(request, 'aquarium/dashboard.html', context)


@require_POST
def dashboard_customize_view(request):
    """Save which dashboard widgets are shown and their order (or reset to defaults)."""
    if request.POST.get('reset'):
        reset_dashboard_layout()
        messages.success(request, "Dashboard reset to the default layout.")
    else:
        order = [k for k in request.POST.get('order', '').split(',') if k]
        save_dashboard_layout(order, request.POST.getlist('enabled'))
        messages.success(request, "Dashboard layout saved.")
    return redirect('dashboard')


@require_POST
def quick_measure_create(request):
    """
    Dashboard 'quick measurements' table: each row is one text value plus a dropdown
    for what is being measured. Several rows can be saved at once.
    """
    values = request.POST.getlist('value')
    param_ids = request.POST.getlist('parameter')
    types = {str(pt.id): pt for pt in ParameterType.objects.all()}
    now = timezone.now()

    saved, problems = [], []
    for raw_value, param_id in zip(values, param_ids):
        if not str(raw_value).strip():
            continue  # untouched row
        pt = types.get(str(param_id))
        value = _to_decimal(raw_value)
        if pt is None:
            problems.append("pick what you measured")
        elif value is None:
            problems.append(f"'{raw_value}' isn't a number ({pt.name})")
        elif abs(value) >= Decimal('999999'):
            problems.append(f"'{raw_value}' is too large ({pt.name})")
        else:
            ParameterLog.objects.create(parameter_type=pt, value=value, measured_at=now)
            saved.append(f"{pt.name} {pt.format_value(value)} {pt.unit}")

    if saved:
        messages.success(request, "Logged " + ", ".join(saved))
    if problems:
        messages.error(request, "Skipped: " + "; ".join(problems))
    if not saved and not problems:
        messages.info(request, "Nothing to save - enter a value first.")

    if getattr(request, 'htmx', False):
        response = HttpResponse(status=204)
        response['HX-Refresh'] = 'true'
        return response
    return redirect('dashboard')


# ==========================================
# Parameters
# ==========================================

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
    optionally convert all previous historical values (and the ideal range) to the new unit.
    """
    ptype = get_object_or_404(ParameterType, id=param_id)
    # Snapshot from the database: the ModelForm mutates `ptype` while validating.
    old = ParameterType.objects.get(pk=ptype.pk)
    suggestions = PARAMETER_UNIT_SUGGESTIONS.get(ptype.code, [])
    logs_count = old.logs.count()

    if request.method == 'POST':
        form = ParameterSettingsForm(request.POST, instance=ptype)
        if form.is_valid():
            old_unit = old.unit
            new_unit = form.cleaned_data['unit'].strip()
            convert_history = form.cleaned_data.get('convert_history', False)

            with transaction.atomic():
                if convert_history and old_unit.lower() != new_unit.lower():
                    code = old.code
                    for log in old.logs.all():
                        new_val = convert_value(float(log.value), old_unit, new_unit, code)
                        log.value = Decimal(f"{new_val:.4f}")
                        log.save(update_fields=['value'])
                    # Convert the ideal range too, unless the user typed a new one.
                    if 'min_ideal' not in form.changed_data:
                        ptype.min_ideal = Decimal(f"{convert_value(float(old.min_ideal), old_unit, new_unit, code):.3f}")
                    if 'max_ideal' not in form.changed_data:
                        ptype.max_ideal = Decimal(f"{convert_value(float(old.max_ideal), old_unit, new_unit, code):.3f}")
                    if ptype.min_ideal > ptype.max_ideal:  # e.g. an inverted conversion
                        ptype.min_ideal, ptype.max_ideal = ptype.max_ideal, ptype.min_ideal
                form.save()

            messages.success(request, f"{ptype.name} settings saved.")
            return redirect(f"/parameters/?param={ptype.code}")
    else:
        form = ParameterSettingsForm(instance=ptype)

    return render(request, 'aquarium/parameter_settings.html', {
        'parameter': old,
        'form': form,
        'suggestions': suggestions,
        'logs_count': logs_count,
    })


def parameter_type_create_view(request):
    if request.method == 'POST':
        form = ParameterTypeForm(request.POST)
        if form.is_valid():
            pt = form.save()
            messages.success(request, f"Added parameter {pt.name}.")
            return redirect(f"/parameters/?param={pt.code}")
    else:
        form = ParameterTypeForm(initial={'unit': 'ppm', 'decimal_places': 2})
    return render(request, 'aquarium/generic_form.html', {
        'form': form, 'title': 'Add Custom Parameter',
        'subtitle': 'Track anything else you test: nitrite, ammonia, potassium, iodine...',
        'back_url': '/parameters/',
    })


def parameter_type_delete_view(request, param_id):
    pt = get_object_or_404(ParameterType, id=param_id)
    return _delete_object(
        request, ParameterType, param_id, label=pt.name, back_url='/parameters/',
        warning=f"This also deletes all {pt.logs.count()} logged measurements for {pt.name}.")


def log_edit_view(request, log_id):
    return _edit_object(request, ParameterLog, ParameterLogEditForm, log_id,
                        title='Edit Measurement', back_url='/parameters/')


def api_chart_data(request):
    """JSON API endpoint powering dynamic Chart.js rendering."""
    param_code = request.GET.get('code')
    days = _to_int(request.GET.get('days'), 30, 1, 3650)

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

    local = timezone.localtime
    labels = [local(log.measured_at).strftime('%m/%d %H:%M') for log in logs]
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
    days = _to_int(request.GET.get('days'), 30, 1, 3650)
    start_date = timezone.now() - timedelta(days=days)
    local = timezone.localtime

    datasets = []
    for ptype in ParameterType.objects.all():
        logs = list(ParameterLog.objects.filter(
            parameter_type=ptype, measured_at__gte=start_date).order_by('measured_at'))
        if not logs:
            continue
        datasets.append({
            'code': ptype.code,
            'name': ptype.name,
            'unit': ptype.unit,
            'color': ptype.color,
            'min_ideal': float(ptype.min_ideal),
            'max_ideal': float(ptype.max_ideal),
            'labels': [local(log.measured_at).strftime('%m/%d %H:%M') for log in logs],
            'values': [
                round(float(log.value), ptype.decimal_places) if ptype.decimal_places > 0
                else round(float(log.value))
                for log in logs
            ],
        })

    return JsonResponse({'datasets': datasets, 'days': days})


def quick_log_create(request):
    """Handles quick-add parameter submissions via HTMX (modal) or standard form POST."""
    if request.method == 'POST':
        form = QuickParameterLogForm(request.POST)
        if form.is_valid():
            log = form.save()
            if getattr(request, 'htmx', False):
                response = render(request, 'aquarium/partials/parameter_log_row.html', {'log': log})
                response['HX-Trigger'] = 'logAdded'
                return response
            messages.success(request, f"Logged {log.parameter_type.name} {log.formatted_value} {log.parameter_type.unit}")
            return redirect(_safe_next(request, 'dashboard'))
        if getattr(request, 'htmx', False):
            problems = "; ".join(f"{k}: {' '.join(v)}" for k, v in form.errors.items())
            return HttpResponse(problems or "Invalid entry", status=400)
        _flash_form_errors(request, form)
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

        if not hmac.compare_digest(incoming_key.encode(), api_key.encode()):
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
        if not isinstance(r, dict):
            errors.append(f"Reading #{index + 1}: must be a JSON object.")
            continue
        param_identifier = str(r.get('parameter') or '').strip()
        val_raw = r.get('value')
        notes = str(r.get('notes') or '')[:255]
        timestamp_raw = r.get('measured_at')

        if not param_identifier:
            errors.append(f"Reading #{index + 1}: Missing 'parameter' field.")
            continue

        if val_raw is None or val_raw == '':
            errors.append(f"Reading #{index + 1} ({param_identifier}): Missing 'value' field.")
            continue

        val_decimal = _to_decimal(val_raw)
        if val_decimal is None or not val_decimal.is_finite() or abs(val_decimal) >= Decimal('999999'):
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
            try:
                parsed_dt = parse_datetime(str(timestamp_raw))
            except ValueError:
                parsed_dt = None
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
    group_id = _to_int(request.GET.get('group'), None)
    status_filter = request.GET.get('status')
    tank_id = _to_int(request.GET.get('tank'), None)

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
        'selected_group': group_id,
        'selected_status': status_filter,
        'selected_tank': tank_id,
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
        _flash_form_errors(request, form)
    return redirect('livestock')


def group_edit_view(request, group_id):
    return _edit_object(request, AnimalGroup, AnimalGroupForm, group_id,
                        title='Edit Group', back_url='/livestock/')


def group_delete_view(request, group_id):
    g = get_object_or_404(AnimalGroup, id=group_id)
    return _delete_object(
        request, AnimalGroup, group_id, label=f"group '{g.name}'", back_url='/livestock/',
        warning="Animals in this group are kept; they just lose this tag.")


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
        primary = Tank.objects.filter(is_primary=True).first()
        if primary:
            initial.setdefault('tank', primary.pk)
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
        count = _to_int(request.POST.get('count'), 1, 1, 500)

        # Resolve assigned tank (or default to primary)
        tank_id = _to_int(request.POST.get('tank'), None)
        target_tank = Tank.objects.filter(id=tank_id).first() if tank_id else None
        if not target_tank:
            target_tank = Tank.objects.filter(is_primary=True).first() or Tank.objects.first()

        # Find or create corresponding AnimalGroup
        group_name = species.suggested_group or 'Fish'
        group_obj, _ = AnimalGroup.objects.get_or_create(
            name=group_name,
            defaults={'icon': species.icon, 'color': '#0ea5e9'}
        )

        care_notes = f"Care: {species.care_level}. Diet: {species.diet}. {species.notes}".strip()

        animal = Animal.objects.create(
            name=species.name,
            species=species.species,
            tank=target_tank,
            count=count,
            status='healthy',
            notes=care_notes,
            acquired_date=timezone.localdate()
        )
        animal.groups.add(group_obj)
        messages.success(request, f"Added {count}x {species.name} to {target_tank.name if target_tank else 'your roster'}.")
        return redirect('livestock')

    return redirect('species_catalog')


def api_species_catalog(request):
    """JSON API returning common species for search / form autocomplete."""
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
        for s in SpeciesCatalog.objects.all()
    ]
    return JsonResponse({'species': data})


# ==========================================
# Webcams
# ==========================================

def webcams_view(request):
    """Live aquarium webcam feeds."""
    feeds = WebcamFeed.objects.filter(is_active=True)
    return render(request, 'aquarium/webcams.html', {'feeds': feeds})


def webcam_create_view(request):
    if request.method == 'POST':
        form = WebcamFeedForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Camera added.")
            return redirect('webcams')
    else:
        form = WebcamFeedForm()
    return render(request, 'aquarium/generic_form.html', {
        'form': form, 'title': 'Add Webcam Feed',
        'subtitle': 'MJPEG/snapshot URL, a go2rtc stream, or an embeddable player',
        'back_url': '/webcams/',
    })


def webcam_edit_view(request, cam_id):
    return _edit_object(request, WebcamFeed, WebcamFeedForm, cam_id, title='Edit Webcam Feed',
                        back_url='/webcams/', delete_url=f'/webcams/{cam_id}/delete/')


def webcam_delete_view(request, cam_id):
    cam = get_object_or_404(WebcamFeed, id=cam_id)
    return _delete_object(request, WebcamFeed, cam_id, label=cam.name, back_url='/webcams/')


# ==========================================
# Dosing & ATO Reservoirs
# ==========================================

def _dose_context():
    """Latest readings, targets and consumption per dosable parameter, in dKH / ppm."""
    canonical_units = {'alkalinity': 'dKH', 'calcium': 'ppm', 'magnesium': 'ppm'}
    context = {}
    since = timezone.now() - timedelta(days=14)

    for code, info in DOSE_PARAMETERS.items():
        ptype = ParameterType.objects.filter(code=code).first()
        canon = canonical_units[code]
        entry = {
            'code': code, 'name': info['name'], 'unit': canon,
            'decimals': info['decimals'], 'available': ptype is not None,
            'max_daily': MAX_DAILY_RAISE[code],
            'current': None, 'measured_at': None, 'target': None,
            'ideal_min': None, 'ideal_max': None, 'daily_change': None, 'display_unit': canon,
        }
        if ptype:
            def conv(v):
                return float(convert_value(float(v), ptype.unit, canon, code))
            entry['display_unit'] = ptype.unit
            entry['ideal_min'] = round(conv(ptype.min_ideal), 3)
            entry['ideal_max'] = round(conv(ptype.max_ideal), 3)
            entry['target'] = round((entry['ideal_min'] + entry['ideal_max']) / 2, 3)
            latest = ptype.latest_log()
            if latest:
                entry['current'] = round(conv(latest.value), 3)
                entry['measured_at'] = timezone.localtime(latest.measured_at).strftime('%b %d, %H:%M')
            points = [(log.measured_at, conv(log.value))
                      for log in ptype.logs.filter(measured_at__gte=since)]
            change = estimate_daily_change(points)
            if change is not None:
                entry['daily_change'] = round(change, 3)
        context[code] = entry
    return context


def dosing_view(request):
    """Dosing additive reservoirs and ATO fresh water levels, forecasts and dose estimator."""
    tanks = Tank.objects.prefetch_related('sumps')
    reservoirs = DosingReservoir.objects.select_related('tank').all()

    dose_data = {
        'parameters': _dose_context(),
        'chemicals': [
            {'key': k, 'name': c['name'], 'parameter': c['parameter']}
            for k, c in DOSE_CHEMICALS.items()
        ],
        'tanks': [
            {'id': t.id, 'name': t.name, 'display': float(t.volume_gallons),
             'sump': t.sump_gallons, 'system': t.total_system_gallons}
            for t in tanks
        ],
    }

    return render(request, 'aquarium/dosing.html', {
        'tanks': tanks,
        'dosing_containers': reservoirs.filter(reservoir_type='dosing_additive'),
        'ato_containers': reservoirs.filter(reservoir_type='ato_freshwater'),
        'form': DosingReservoirForm(initial={'tank': Tank.objects.filter(is_primary=True).first()}),
        'dose_data': dose_data,
    })


def dose_calc_api(request):
    """GET /api/calculators/dosing/ - estimate additive amounts (see calculators.dose_estimate)."""
    try:
        def num(name, default=None):
            raw = request.GET.get(name)
            if raw in (None, ''):
                return default
            return float(raw)

        parameter = request.GET.get('parameter', '')
        chemical = request.GET.get('chemical') or None
        result = dose_estimate(
            parameter=parameter,
            chemical_key=chemical,
            current=num('current'),
            target=num('target'),
            system_gallons=num('gallons'),
            solution_g_per_l=num('solution_g_l'),
            max_daily_raise=num('max_daily'),
            daily_loss=num('daily_loss', 0.0),
            label_raise=num('label_raise'),
            label_ml=num('label_ml'),
            label_gallons=num('label_gallons'),
        )
        return JsonResponse(result)
    except (TypeError, ValueError) as e:
        return JsonResponse({'error': str(e) or 'Please fill in the current and target values and a tank volume.'}, status=400)


def refill_reservoir_view(request, res_id):
    """Refills a dosing container or ATO reservoir to full or to a custom level."""
    reservoir = get_object_or_404(DosingReservoir, id=res_id)
    if request.method == 'POST':
        new_level = _to_decimal(request.POST.get('custom_level'))
        if new_level is not None:
            reservoir.current_level = max(Decimal('0'), min(new_level, reservoir.capacity))
        else:
            reservoir.current_level = reservoir.capacity

        reservoir.last_refilled_date = timezone.localdate()
        reservoir.save()
    return redirect('dosing')


def dosing_create_view(request):
    """Create a new dosing container or ATO reservoir."""
    if request.method == 'POST':
        form = DosingReservoirForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Reservoir added.")
        else:
            _flash_form_errors(request, form)
    return redirect('dosing')


def dosing_edit_view(request, res_id):
    return _edit_object(request, DosingReservoir, DosingReservoirForm, res_id,
                        title='Edit Reservoir / Container Size',
                        subtitle='Change the container size, current level, unit or daily rate',
                        back_url='/dosing/', delete_url=f'/dosing/{res_id}/delete/')


def dosing_delete_view(request, res_id):
    res = get_object_or_404(DosingReservoir, id=res_id)
    return _delete_object(request, DosingReservoir, res_id, label=res.name, back_url='/dosing/')


# ==========================================
# Tanks, sumps and chambers
# ==========================================

def _tank_equipment_flow(tank):
    """Equipment on this tank that contributes to flow, with estimated gph."""
    rows = []
    for eq in tank.equipment.all():
        if eq.category in Equipment.FLOW_CATEGORIES:
            rows.append(eq)
    return rows


def tanks_view(request):
    tanks = Tank.objects.prefetch_related('sumps', 'equipment', 'animals')
    return render(request, 'aquarium/tanks.html', {
        'tank_cards': [{'tank': t, 'flow': t.flow_summary()} for t in tanks],
    })


def tank_detail_view(request, tank_id):
    tank = get_object_or_404(Tank.objects.prefetch_related('sumps__chambers', 'equipment'), id=tank_id)
    return render(request, 'aquarium/tank_detail.html', {
        'tank': tank,
        'flow': tank.flow_summary(),
        'flow_equipment': _tank_equipment_flow(tank),
        'chamber_types': [{'value': k, 'label': v} for k, v in SumpChamber.CHAMBER_TYPES],
    })


def tank_create_view(request):
    if request.method == 'POST':
        form = TankForm(request.POST)
        if form.is_valid():
            tank = form.save()
            if tank.is_primary:
                Tank.objects.exclude(pk=tank.pk).update(is_primary=False)
            messages.success(request, f"Added {tank.name}.")
            return redirect('tank_detail', tank_id=tank.id)
    else:
        form = TankForm(initial={'is_primary': not Tank.objects.exists()})
    return render(request, 'aquarium/vessel_form.html', {
        'form': form, 'title': 'Add Tank', 'kind': 'tank', 'back_url': '/tanks/',
    })


def tank_edit_view(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id)
    if request.method == 'POST':
        form = TankForm(request.POST, instance=tank)
        if form.is_valid():
            tank = form.save()
            if tank.is_primary:
                Tank.objects.exclude(pk=tank.pk).update(is_primary=False)
            messages.success(request, "Tank saved.")
            return redirect('tank_detail', tank_id=tank.id)
    else:
        form = TankForm(instance=tank)
    return render(request, 'aquarium/vessel_form.html', {
        'form': form, 'title': f'Edit {tank.name}', 'kind': 'tank',
        'back_url': f'/tanks/{tank.id}/', 'delete_url': f'/tanks/{tank.id}/delete/',
    })


def tank_delete_view(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id)
    warning = (f"This also deletes its {tank.sumps.count()} sump(s), {tank.reservoirs.count()} dosing/ATO reservoir(s), "
               f"{tank.routines.count()} routine(s) and {tank.water_changes.count()} water change log(s). "
               f"{tank.animals.count()} animal(s) and {tank.equipment.count()} equipment item(s) are kept but unassigned.")
    return _delete_object(request, Tank, tank_id, label=tank.name, back_url='/tanks/', warning=warning)


def sump_create_view(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id)
    if request.method == 'POST':
        form = SumpForm(request.POST)
        if form.is_valid():
            sump = form.save(commit=False)
            sump.tank = tank
            sump.save()
            messages.success(request, f"Added {sump.name}. Split it into chambers below.")
            return redirect('tank_detail', tank_id=tank.id)
    else:
        form = SumpForm()
    return render(request, 'aquarium/vessel_form.html', {
        'form': form, 'title': f'Add Sump to {tank.name}', 'kind': 'sump',
        'back_url': f'/tanks/{tank.id}/',
    })


def sump_edit_view(request, sump_id):
    sump = get_object_or_404(Sump, id=sump_id)
    if request.method == 'POST':
        form = SumpForm(request.POST, instance=sump)
        if form.is_valid():
            form.save()
            messages.success(request, "Sump saved.")
            return redirect('tank_detail', tank_id=sump.tank_id)
    else:
        form = SumpForm(instance=sump)
    return render(request, 'aquarium/vessel_form.html', {
        'form': form, 'title': f'Edit {sump.name}', 'kind': 'sump',
        'back_url': f'/tanks/{sump.tank_id}/', 'delete_url': f'/sumps/{sump.id}/delete/',
    })


def sump_delete_view(request, sump_id):
    sump = get_object_or_404(Sump, id=sump_id)
    return _delete_object(request, Sump, sump_id, label=sump.name, back_url=f'/tanks/{sump.tank_id}/',
                          warning="Its chambers are deleted too.")


@require_POST
def sump_split_view(request, sump_id):
    """Replace a sump's chambers with N chambers, each with a type, name and share of the volume."""
    sump = get_object_or_404(Sump, id=sump_id)
    types = request.POST.getlist('chamber_type')
    names = request.POST.getlist('chamber_name')
    shares_raw = request.POST.getlist('chamber_share')
    count = len(types)

    if not 1 <= count <= 12:
        messages.error(request, "Choose between 1 and 12 chambers.")
        return redirect('tank_detail', tank_id=sump.tank_id)

    valid_types = {value for value, _ in SumpChamber.CHAMBER_TYPES}
    parsed = []
    for i in range(count):
        raw = shares_raw[i] if i < len(shares_raw) else ''
        value = _to_decimal(raw)
        parsed.append(value if value is not None and 0 <= value <= 100 else None)

    if all(p is None for p in parsed):
        base = (Decimal(100) / count).quantize(Decimal('0.1'))
        shares = [base] * count
        shares[-1] = Decimal(100) - base * (count - 1)
    else:
        shares = [p if p is not None else Decimal(0) for p in parsed]

    with transaction.atomic():
        sump.chambers.all().delete()
        for i in range(count):
            chamber_type = types[i] if types[i] in valid_types else 'other'
            SumpChamber.objects.create(
                sump=sump,
                position=i + 1,
                name=(names[i] if i < len(names) else '').strip()[:80],
                chamber_type=chamber_type,
                share_percent=shares[i],
            )

    total = sum(shares)
    if abs(total - 100) > Decimal('0.5'):
        messages.warning(request, f"Chambers saved, but their shares add up to {total}% rather than 100%.")
    else:
        messages.success(request, f"{sump.name} split into {count} chamber{'s' if count != 1 else ''}.")
    return redirect('tank_detail', tank_id=sump.tank_id)


def chamber_edit_view(request, chamber_id):
    chamber = get_object_or_404(SumpChamber.objects.select_related('sump'), id=chamber_id)
    back = f'/tanks/{chamber.sump.tank_id}/'
    return _edit_object(request, SumpChamber, SumpChamberForm, chamber_id,
                        title=f'Edit Chamber ({chamber.sump.name})', back_url=back,
                        delete_url=f'/chambers/{chamber_id}/delete/')


def chamber_delete_view(request, chamber_id):
    chamber = get_object_or_404(SumpChamber.objects.select_related('sump'), id=chamber_id)
    return _delete_object(request, SumpChamber, chamber_id, label=chamber.display_name,
                          back_url=f'/tanks/{chamber.sump.tank_id}/')


# ==========================================
# Equipment
# ==========================================

def equipment_view(request):
    """Equipment hardware roster assigned to tanks with maintenance tracking and flow."""
    tanks = Tank.objects.all()
    selected_tank_id = _to_int(request.GET.get('tank'), None)
    selected_category = request.GET.get('category')

    equipment_list = Equipment.objects.select_related('tank').all()
    if selected_tank_id:
        equipment_list = equipment_list.filter(tank_id=selected_tank_id)
    if selected_category:
        equipment_list = equipment_list.filter(category=selected_category)

    total_watts = equipment_list.aggregate(total=Sum('wattage'))['total'] or 0

    return render(request, 'aquarium/equipment.html', {
        'tanks': tanks,
        'equipment_list': equipment_list,
        'selected_tank_id': selected_tank_id,
        'selected_category': selected_category,
        'equipment_form': EquipmentForm(initial={'tank': Tank.objects.filter(is_primary=True).first()}),
        'total_watts': total_watts,
        'categories': Equipment.CATEGORY_CHOICES,
    })


@require_POST
def service_equipment_view(request, eq_id):
    """Marks an equipment piece serviced/cleaned today."""
    eq = get_object_or_404(Equipment, id=eq_id)
    eq.last_serviced_date = timezone.localdate()
    eq.status = 'operational'
    eq.save()
    return redirect(_safe_next(request, 'equipment'))


@require_POST
def equipment_power_view(request, eq_id):
    """Quick power-setting change from the equipment card (re-estimates flow)."""
    eq = get_object_or_404(Equipment, id=eq_id)
    eq.power_setting_percent = _to_int(request.POST.get('power'), eq.power_setting_percent, 1, 100)
    eq.save(update_fields=['power_setting_percent'])
    return redirect(_safe_next(request, 'equipment'))


def equipment_create_view(request):
    if request.method == 'POST':
        form = EquipmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Equipment added.")
        else:
            _flash_form_errors(request, form)
    return redirect('equipment')


def equipment_edit_view(request, eq_id):
    return _edit_object(request, Equipment, EquipmentForm, eq_id, title='Edit Equipment',
                        back_url='/equipment/', delete_url=f'/equipment/{eq_id}/delete/')


def equipment_delete_view(request, eq_id):
    eq = get_object_or_404(Equipment, id=eq_id)
    return _delete_object(request, Equipment, eq_id, label=eq.name, back_url='/equipment/')


# ==========================================
# Maintenance Routines & Water Change Checklists
# ==========================================

def routines_view(request):
    """Recurring tank checklists, water change preparation calculator, and change logs."""
    routines = MaintenanceRoutine.objects.select_related('tank')
    water_changes = WaterChangeLog.objects.select_related('tank')[:10]
    sample_mix = calculate_salt_mix(volume=10.0, volume_unit='gal', brand_key='tropic_marin_pro',
                                    target_salinity=1.026, salinity_unit='sg')

    return render(request, 'aquarium/routines.html', {
        'routines': routines,
        'water_changes': water_changes,
        'tanks': Tank.objects.all(),
        'wc_form': WaterChangeLogForm(initial={'tank': Tank.objects.filter(is_primary=True).first()}),
        'routine_form': MaintenanceRoutineForm(),
        'sample_mix': sample_mix,
        'salt_brands': SALT_MIX_RECIPES,
    })


@require_POST
def complete_routine_view(request, routine_id):
    """Marks a checklist routine completed now."""
    routine = get_object_or_404(MaintenanceRoutine, id=routine_id)
    routine.last_completed = timezone.now()
    routine.save()
    return redirect(_safe_next(request, 'routines'))


def routine_create_view(request):
    """Creates a new custom maintenance routine / checklist directly in GUI."""
    if request.method == 'POST':
        form = MaintenanceRoutineForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Routine added.")
        else:
            _flash_form_errors(request, form)
    return redirect('routines')


def routine_edit_view(request, routine_id):
    return _edit_object(request, MaintenanceRoutine, MaintenanceRoutineForm, routine_id,
                        title='Edit Routine', back_url='/routines/')


@require_POST
def routine_delete_view(request, routine_id):
    """Deletes a custom routine."""
    routine = get_object_or_404(MaintenanceRoutine, id=routine_id)
    routine.delete()
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
            messages.success(request, "Water change logged.")
        else:
            _flash_form_errors(request, form)
    return redirect('routines')


def water_change_edit_view(request, wc_id):
    return _edit_object(request, WaterChangeLog, WaterChangeLogForm, wc_id,
                        title='Edit Water Change', back_url='/routines/',
                        delete_url=f'/routines/water-change/{wc_id}/delete/')


def water_change_delete_view(request, wc_id):
    wc = get_object_or_404(WaterChangeLog, id=wc_id)
    return _delete_object(request, WaterChangeLog, wc_id, label=str(wc), back_url='/routines/')


# ==========================================
# Alerts & Notifications Center
# ==========================================

def notifications_view(request):
    """Alerts & Notifications Center with health scoring and community resources."""
    state = compute_alert_state(request)

    # Attach Reef2Reef search links (site-restricted web search; Reef2Reef's own search URL is unreliable).
    for item in state['out_of_range_params']:
        direction = 'too low' if item['log'].status == 'low' else 'too high'
        item['r2r_url'] = reef2reef_search(f"{item['param'].name} {direction}", "reef tank")
    for eq in state['due_equipment']:
        eq.r2r_url = reef2reef_search(eq.name, "cleaning maintenance")

    r2r_forums = [
        {'name': 'Reef Chemistry', 'icon': '🧪',
         'desc': 'Alkalinity, calcium, magnesium, nitrate and phosphate discussions',
         'url': reef2reef_search('reef chemistry alkalinity calcium magnesium')},
        {'name': 'Fish Disease & Treatment', 'icon': '🩺',
         'desc': 'Ich, velvet, flukes, bacterial infections: diagnosis and treatment threads',
         'url': reef2reef_search('fish disease treatment diagnosis')},
        {'name': 'Coral Care', 'icon': '🪸',
         'desc': 'SPS, LPS and soft coral care, polyp extension, lighting and placement',
         'url': reef2reef_search('coral care placement lighting flow')},
        {'name': 'Equipment & Hardware', 'icon': '⚙️',
         'desc': 'Wavemakers, skimmers, return pumps and lighting reviews and troubleshooting',
         'url': reef2reef_search('equipment pump skimmer wavemaker troubleshooting')},
        {'name': 'Reef2Reef Main Community', 'icon': '🌊',
         'desc': 'Saltwater community, tank build threads, and discussions',
         'url': 'https://www.reef2reef.com/'},
    ]

    context = dict(state)
    context['r2r_forums'] = r2r_forums
    return render(request, 'aquarium/notifications.html', context)


# ==========================================
# PWA service worker (must be served from "/" so it can control the whole site)
# ==========================================

def service_worker_view(request):
    path = settings.BASE_DIR / 'static' / 'sw.js'
    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        return HttpResponse("// service worker missing", content_type='application/javascript', status=404)
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response
