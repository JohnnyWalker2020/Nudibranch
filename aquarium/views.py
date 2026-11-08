import hmac
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import retire
from .active import default_tank, get_active_tank
from .alert_history import alert_summary
from .alerts import compute_alert_state
from .compatibility import warnings_for_addition
from .calculators import (
    DOSE_CHEMICALS, DOSE_PARAMETERS, MAX_DAILY_RAISE, SALT_MIX_RECIPES,
    calculate_salt_mix, dose_estimate, estimate_daily_change,
)
from .conversions import PARAMETER_UNIT_SUGGESTIONS, convert_value
from .dashboard_widgets import COUNTDOWN_PRESETS, get_dashboard_layout, reset_dashboard_layout, save_dashboard_layout
from .forms import (
    AnimalForm, AnimalGroupForm, AnimalPhotoUploadForm, DosingReservoirForm, EquipmentForm, MaintenanceRoutineForm,
    ParameterLogEditForm, ParameterSettingsForm, ParameterTypeForm, QuickParameterLogForm,
    DoseLogForm, QuickTimerForm, SumpChamberForm, SumpForm, TankForm, WaterChangeLogForm, WebcamFeedForm, PlumbingRunForm,
)
from .models import (
    Animal, AnimalGroup, AppSettings, DoseLog, DosingReservoir, Equipment, FillTimer, MaintenanceRoutine, ParameterLog,
    ParameterType, QuickTimer, SpeciesCatalog, Sump, SumpChamber, Tank, WaterChangeLog, WebcamFeed,
    ParameterTarget, PlumbingRun, RANGE_FIELDS, in_system, latest_logs_by_parameter, not_retired, reef2reef_search, trend,
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
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None  # 'NaN' and 'Infinity' parse, but aren't readings


def safe_json(value):
    """JSON to put inside a <script> tag. User text containing </script> can't break out of it."""
    return json.dumps(value).replace('<', '\\u003C').replace('>', '\\u003E').replace('&', '\\u0026')


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

def _groups_with_counts(tank):
    if tank is None:
        in_this_system = Q(animals__tank__isnull=True)
    else:
        in_this_system = Q(animals__tank=tank) | Q(animals__tank__isnull=True)
    return list(AnimalGroup.objects.annotate(scoped_count=Count('animals', filter=in_this_system)))


def _logs_for_list(tank):
    """Logs ready to show their status, without a query per row to look up that system's targets."""
    logs = in_system(ParameterLog.objects.select_related('parameter_type').prefetch_related('parameter_type__targets'), tank)
    if not AppSettings.load().icp_enabled:  # ICP readings stay out of sight while ICP is switched off
        logs = logs.filter(parameter_type__is_trace=False)
    return logs


def dashboard_view(request):
    """Main dashboard. Which widgets show, and in what order, is stored in the database."""
    tank = get_active_tank(request)
    latest = latest_logs_by_parameter(tank)
    previous = latest_logs_by_parameter(tank, back=1)
    parameter_types = [pt.for_system(tank) for pt in ParameterType.objects.in_use().prefetch_related('targets')]
    for pt in parameter_types:
        pt.current_log = latest.get(pt.pk)
        pt.trend = trend(pt, pt.current_log, previous.get(pt.pk))
        if pt.current_log:
            pt.current_log.parameter_type = pt
    layout = get_dashboard_layout()
    enabled_keys = {w['key'] for w in layout if w['enabled']}

    context = {
        'parameter_types': parameter_types,
        'card_types': [pt for pt in parameter_types if pt.show_on_dashboard],
        'chip_types': [pt for pt in parameter_types if not pt.is_trace],
        'trace_types': [pt for pt in parameter_types if pt.is_trace],
        'form': QuickParameterLogForm(),
        'layout': layout,
        'visible_widgets': [w for w in layout if w['enabled']],
        'all_widgets': layout,
        **water_change_context(tank),
    }
    context.update(compute_alert_state(request))
    if 'countdown' in enabled_keys:
        context['countdown_presets'] = COUNTDOWN_PRESETS
        # A plain timer already running (not a fill or a routine step) shows on the countdown card.
        running = list(FillTimer.objects.filter(status='running', reservoir__isnull=True, routine__isnull=True).order_by('-started_at'))
        context['countdown_timer'] = next((run for run in running if not run.quick_timer_id), None)
        latest_run = {}
        for run in running:
            if run.quick_timer_id:
                latest_run.setdefault(run.quick_timer_id, run)
        saved = list(QuickTimer.objects.all())
        for timer in saved:
            timer.running = latest_run.get(timer.pk)
        context['quick_timers'] = saved
        context['quick_timer_form'] = QuickTimerForm(auto_id='qt_%s')

    # Only run the queries a visible widget actually needs.
    if 'recent_logs' in enabled_keys:
        context['recent_logs'] = _logs_for_list(tank)[:8]
    if 'livestock' in enabled_keys:
        active = in_system(Animal.objects.exclude(status__in=['rehomed', 'deceased']), tank)
        context['total_animals'] = active.aggregate(total=Sum('count'))['total'] or 0
        context['groups'] = _groups_with_counts(tank)
        context['featured_animals'] = active[:6]
    if 'webcam' in enabled_keys:
        context['active_cameras'] = in_system(WebcamFeed.objects.filter(is_active=True), tank)[:2]
    if 'reservoirs' in enabled_keys:
        context['reservoirs'] = in_system(DosingReservoir.objects.select_related('tank'), tank)
    if 'tank_summary' in enabled_keys:
        tanks = Tank.objects.prefetch_related('sumps', 'equipment', 'plumbing_runs').filter(pk=tank.pk) if tank else []
        context['tank_summaries'] = [{'tank': t, 'flow': t.flow_summary()} for t in tanks]

    return render(request, 'aquarium/dashboard.html', context)


@require_POST
def dashboard_customize_view(request):
    """Save which dashboard widgets are shown and their order (or reset to defaults)."""
    if request.POST.get('reset'):
        reset_dashboard_layout()
        ParameterType.objects.filter(is_trace=False).update(show_on_dashboard=True)
        ParameterType.objects.filter(is_trace=True).update(show_on_dashboard=False)
        messages.success(request, "Dashboard reset to the default layout.")
    else:
        order = [k for k in request.POST.get('order', '').split(',') if k]
        save_dashboard_layout(order, request.POST.getlist('enabled'))
        if request.POST.get('cards_shown'):  # the water test card choices were on the form
            shown = {_to_int(raw, None) for raw in request.POST.getlist('card')}
            listed = ParameterType.objects.in_use()
            listed.filter(pk__in=shown).update(show_on_dashboard=True)
            listed.exclude(pk__in=shown).update(show_on_dashboard=False)
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
    types = {str(pt.id): pt for pt in ParameterType.objects.in_use()}
    now = timezone.now()
    tank = get_active_tank(request)
    if tank is not None and tank.is_archived:
        messages.warning(request, f"{tank.name} is retired. Bring it back to log new tests.")
        return redirect('dashboard')

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
            ParameterLog.objects.create(parameter_type=pt, tank=tank, value=value, measured_at=now)
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

LOG_FIRST_PAGE = 10  # readings shown before Load more
LOG_PAGE_SIZE = 25  # readings each Load more adds


def parameters_view(request):
    """Full parameter management, historical logs, and interactive charts."""
    param_code = request.GET.get('param')
    types = ParameterType.objects.in_use()
    tank = get_active_tank(request)

    logs_query = _logs_for_list(tank)
    selected_param = None
    if param_code:
        logs_query = logs_query.filter(parameter_type__code=param_code)
        selected_param = ParameterType.objects.in_use().filter(code=param_code).first()
        if selected_param:
            selected_param = selected_param.for_system(tank)
    # No ?param= means the "All Parameters" view: every parameter on one chart.

    recent_logs = list(logs_query[:LOG_FIRST_PAGE + 1])
    has_more = len(recent_logs) > LOG_FIRST_PAGE
    form = QuickParameterLogForm()

    return render(request, 'aquarium/parameters.html', {
        'parameter_types': types,
        'chip_types': [pt for pt in types if not pt.is_trace],
        'trace_types': [pt for pt in types if pt.is_trace],
        'selected_code': param_code,
        'selected_param': selected_param,
        'recent_logs': recent_logs[:LOG_FIRST_PAGE],
        'next_offset': LOG_FIRST_PAGE if has_more else None,
        'form': form,
    })


def parameter_logs_more(request):
    """The next page of the log history, for the Load more button."""
    code = request.GET.get('param') or ''
    offset = _to_int(request.GET.get('offset'), LOG_FIRST_PAGE, 0)
    logs_query = _logs_for_list(get_active_tank(request))
    if code:
        logs_query = logs_query.filter(parameter_type__code=code)
    logs = list(logs_query[offset:offset + LOG_PAGE_SIZE + 1])
    return render(request, 'aquarium/partials/parameter_log_page.html', {
        'recent_logs': logs[:LOG_PAGE_SIZE],
        'next_offset': offset + LOG_PAGE_SIZE if len(logs) > LOG_PAGE_SIZE else None,
        'selected_code': code,
    })


def parameter_settings_view(request, param_id):
    """
    Manage unit, decimal precision, ideal target ranges, and
    optionally convert all previous historical values (and the ideal range) to the new unit.
    """
    ptype = get_object_or_404(ParameterType, id=param_id)
    # Snapshot from the database: the ModelForm mutates `ptype` while validating.
    old = ParameterType.objects.get(pk=ptype.pk)
    tank = get_active_tank(request)
    effective = old.for_system(tank)
    several_systems = Tank.objects.count() > 1
    suggestions = PARAMETER_UNIT_SUGGESTIONS.get(ptype.code, [])
    logs_count = old.logs.count()
    range_initial = {field: getattr(effective, field) for field in RANGE_FIELDS}

    if request.method == 'POST':
        form = ParameterSettingsForm(request.POST, instance=ptype, initial=range_initial)
        if form.is_valid():
            old_unit = old.unit
            new_unit = form.cleaned_data['unit'].strip()
            converting = form.cleaned_data.get('convert_history', False) and old_unit.lower() != new_unit.lower()
            code = old.code
            shared = _ranges_of(old)
            typed = {field: form.cleaned_data.get(field) for field in RANGE_FIELDS}

            with transaction.atomic():
                if converting:
                    logs = list(old.logs.all())
                    for log in logs:
                        new_val = convert_value(float(log.value), old_unit, new_unit, code)
                        log.value = Decimal(f"{new_val:.4f}")
                    ParameterLog.objects.bulk_update(logs, ['value'], batch_size=500)
                    shared = _converted_ranges(shared, old_unit, new_unit, code)
                    for target in old.targets.all():
                        for field, value in _converted_ranges(_ranges_of(target), old_unit, new_unit, code).items():
                            setattr(target, field, value)
                        target.save()
                    # Convert these ranges too, unless the user typed new ones.
                    converted = _converted_ranges(range_initial, old_unit, new_unit, code)
                    typed = {f: typed[f] if f in form.changed_data else converted[f] for f in RANGE_FIELDS}
                    typed = _uninverted(typed)

                # Units and decimals are shared by every system. Ranges belong to the selected one.
                if not several_systems or form.cleaned_data.get('apply_default'):
                    shared = typed
                for field, value in shared.items():
                    setattr(ptype, field, value)
                ptype.unit = new_unit
                ptype.decimal_places = form.cleaned_data['decimal_places']
                ptype.show_on_dashboard = form.cleaned_data.get('show_on_dashboard', ptype.show_on_dashboard)
                # A reminder in days. An hours setting for a probe (from Phone Alerts) is kept unless replaced.
                days = form.cleaned_data.get('test_every_days')
                if days:
                    ptype.stale_after_hours = days * 24
                elif old.test_every_days:
                    ptype.stale_after_hours = None
                ptype.save()

                if tank is not None:
                    if typed == shared:
                        ptype.targets.filter(tank=tank).delete()
                    else:
                        ParameterTarget.objects.update_or_create(tank=tank, parameter_type=ptype, defaults=typed)

            messages.success(request, f"{ptype.name} settings saved.")
            return redirect(f"/parameters/?param={ptype.code}")
    else:
        form = ParameterSettingsForm(instance=ptype, initial={**range_initial, 'test_every_days': ptype.test_every_days,
                                                              'show_on_dashboard': ptype.show_on_dashboard})

    return render(request, 'aquarium/parameter_settings.html', {
        'parameter': old,
        'form': form,
        'suggestions': suggestions,
        'logs_count': logs_count,
        'several_systems': several_systems,
        'has_system_targets': getattr(effective, 'has_system_targets', False),
        'default_min': old.formatted_min_ideal,
        'default_max': old.formatted_max_ideal,
    })


def _ranges_of(obj):
    return {field: getattr(obj, field) for field in RANGE_FIELDS}


def _uninverted(ranges):
    """Some unit conversions run backwards, which flips the order of the range."""
    if ranges['min_ideal'] is not None and ranges['max_ideal'] is not None and ranges['min_ideal'] > ranges['max_ideal']:
        ranges = dict(ranges, min_ideal=ranges['max_ideal'], max_ideal=ranges['min_ideal'],
                      low_limit=ranges['high_limit'], high_limit=ranges['low_limit'])
    return ranges


def _converted_ranges(ranges, old_unit, new_unit, code):
    converted = {
        field: None if value is None else Decimal(f"{convert_value(float(value), old_unit, new_unit, code):.3f}")
        for field, value in ranges.items()
    }
    return _uninverted(converted)


@require_POST
def parameter_targets_reset_view(request, param_id):
    """Makes the selected system go back to the shared default ranges for this parameter."""
    ptype = get_object_or_404(ParameterType, id=param_id)
    tank = get_active_tank(request)
    if tank is not None:
        ptype.targets.filter(tank=tank).delete()
        messages.success(request, f"{tank.name} now uses the default {ptype.name} targets.")
    return redirect('parameter_settings', param_id=ptype.pk)


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
        'subtitle': 'Track anything else you test: nitrite, ammonia, ORP...',
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


def _chart_tank(request):
    """Charts use ?tank=<id> when given, otherwise the system selected in this browser."""
    tank = Tank.objects.filter(pk=_to_int(request.GET.get('tank'), None)).first()
    return tank or get_active_tank(request)


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

    tank = _chart_tank(request)
    ptype = ptype.for_system(tank)
    start_date = timezone.now() - timedelta(days=days)
    logs = in_system(ParameterLog.objects.filter(
        parameter_type=ptype,
        measured_at__gte=start_date
    ), tank).order_by('measured_at')

    local = timezone.localtime
    labels = [local(log.measured_at).strftime('%m/%d %H:%M') for log in logs]
    timestamps = [int(log.measured_at.timestamp() * 1000) for log in logs]
    values = [round(float(log.value), ptype.decimal_places) if ptype.decimal_places > 0 else round(float(log.value)) for log in logs]

    return JsonResponse({
        'parameter': {
            'name': ptype.name,
            'unit': ptype.unit,
            'decimal_places': ptype.decimal_places,
            'min_ideal': float(ptype.min_ideal),
            'max_ideal': float(ptype.max_ideal),
            'low_limit': float(ptype.low_limit) if ptype.low_limit is not None else None,
            'high_limit': float(ptype.high_limit) if ptype.high_limit is not None else None,
            'formatted_min': ptype.formatted_min_ideal,
            'formatted_max': ptype.formatted_max_ideal,
            'color': ptype.color,
        },
        'labels': labels,
        'timestamps': timestamps,
        'values': values,
    })


def api_all_chart_data(request):
    """JSON API endpoint returning all parameter datasets for multi-line Chart.js rendering."""
    days = _to_int(request.GET.get('days'), 30, 1, 3650)
    start_date = timezone.now() - timedelta(days=days)
    local = timezone.localtime
    tank = _chart_tank(request)

    datasets = []
    for base in ParameterType.objects.filter(is_trace=False).prefetch_related('targets'):
        ptype = base.for_system(tank)
        logs = list(in_system(ParameterLog.objects.filter(
            parameter_type=ptype, measured_at__gte=start_date), tank).order_by('measured_at'))
        if not logs:
            continue
        datasets.append({
            'code': ptype.code,
            'name': ptype.name,
            'unit': ptype.unit,
            'color': ptype.color,
            'min_ideal': float(ptype.min_ideal),
            'max_ideal': float(ptype.max_ideal),
            'low_limit': float(ptype.low_limit) if ptype.low_limit is not None else None,
            'high_limit': float(ptype.high_limit) if ptype.high_limit is not None else None,
            'labels': [local(log.measured_at).strftime('%m/%d %H:%M') for log in logs],
            'timestamps': [int(log.measured_at.timestamp() * 1000) for log in logs],
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
        # The popup can pick another tank; anything else (like the quick measurement card) uses the selected one.
        chosen = _to_int(request.POST.get('tank'), None)
        active_tank = (Tank.objects.filter(pk=chosen).first() if chosen else None) or get_active_tank(request)
        if active_tank is not None and active_tank.is_archived:
            if getattr(request, 'htmx', False):
                return HttpResponse(f"{active_tank.name} is retired.", status=400)
            messages.warning(request, f"{active_tank.name} is retired. Bring it back to log new tests.")
            return redirect(_safe_next(request, 'dashboard'))
        form = QuickParameterLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.tank = active_tank
            log.save()
            if getattr(request, 'htmx', False):
                response = render(request, 'aquarium/partials/parameter_log_row.html', {'log': log})
                response['HX-Trigger'] = 'logAdded'
                return response
            where = f" on {log.tank.name}" if log.tank and log.tank != get_active_tank(request) else ''
            messages.success(request, f"Logged {log.parameter_type.name} {log.formatted_value} {log.parameter_type.unit}{where}")
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
    """GET /api/parameters/types/ - Parameter details. Add ?tank=<id or name> for that system's targets."""
    tank = None
    if request.GET.get('tank'):
        tank = _api_tank(request.GET['tank'])
        if tank is None:
            return JsonResponse({'error': f"Unknown tank '{request.GET['tank']}'."}, status=404)
    types = [pt.for_system(tank) for pt in ParameterType.objects.in_use().prefetch_related('targets')]
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


def _api_tank(identifier):
    """Finds a tank by ID or by name (ignoring case)."""
    text = str(identifier).strip()
    current = Tank.objects.filter(is_archived=False)  # retired systems don't accept new readings
    if text.isdecimal():
        tank = current.filter(pk=int(text)).first()
        if tank:
            return tank
    return current.filter(name__iexact=text).first()


@csrf_exempt
def api_parameter_log(request):
    """
    POST /api/parameters/log/ - Endpoint to log parameter readings via API calls.
    Accepts single reading or batch list of readings.
    Supports JSON or standard form encoded payloads.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    # Without a key set there's nothing to check callers against, so nobody gets in. Tests turn this off.
    api_key = getattr(settings, 'API_SECRET_KEY', '')
    if not api_key and getattr(settings, 'LOGIN_REQUIRED', True):
        return JsonResponse({'error': 'Set API_SECRET_KEY in your .env file to log readings through the API.'}, status=401)
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
                'measured_at': request.POST.get('measured_at'),
                'tank': request.POST.get('tank'),
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
    # A device has no selected system, so readings go to its named tank or else the primary tank.
    default_system = _api_tank(payload.get('tank')) if isinstance(payload, dict) and payload.get('tank') else default_tank()
    if isinstance(payload, dict) and payload.get('tank') and default_system is None:
        return JsonResponse({'success': False, 'errors': [f"Unknown tank '{payload.get('tank')}'."]}, status=400)
    if default_system is not None and default_system.is_archived:
        return JsonResponse({'success': False, 'errors': ['Every tank is retired. Bring one back to log readings.']}, status=400)

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
        if param_identifier.isdecimal():
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

        tank = default_system
        if r.get('tank') and r.get('tank') != (payload.get('tank') if isinstance(payload, dict) else None):
            tank = _api_tank(r.get('tank'))
            if tank is None:
                errors.append(f"Reading #{index + 1}: Unknown tank '{r.get('tank')}'.")
                continue

        # Create log record
        log = ParameterLog.objects.create(
            parameter_type=ptype,
            tank=tank,
            value=val_decimal,
            notes=notes,
            measured_at=measured_at
        )

        created_logs.append({
            'id': log.id,
            'parameter': ptype.name,
            'code': ptype.code,
            'tank': tank.name if tank else None,
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
    tank = get_active_tank(request)

    animals = in_system(Animal.objects.select_related('tank').prefetch_related('groups'), tank)
    if group_id:
        animals = animals.filter(groups__id=group_id)
    if status_filter:
        animals = animals.filter(status=status_filter)

    groups = _groups_with_counts(tank)
    form = AnimalForm()
    group_form = AnimalGroupForm()

    return render(request, 'aquarium/livestock.html', {
        'animals': animals,
        'groups': groups,
        'selected_group': group_id,
        'selected_status': status_filter,
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
        species_id = _to_int(request.GET.get('species_id'), None)
        if species_id:
            sp = SpeciesCatalog.objects.filter(id=species_id).first()
            if sp:
                initial = {
                    'name': sp.name,
                    'species': sp.species,
                    'notes': f"Care: {sp.care_level}. Diet: {sp.diet}. {sp.notes}".strip(),
                    'new_group_name': sp.suggested_group,
                }
        active_tank = get_active_tank(request)
        if active_tank:
            initial.setdefault('tank', active_tank.pk)
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
    if request.method == 'POST':
        form = AnimalPhotoUploadForm(request.POST, request.FILES, instance=animal)
        if form.is_valid():
            form.save()
        else:
            _flash_form_errors(request, form)
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

    tanks = Tank.objects.filter(is_archived=False)
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
            target_tank = get_active_tank(request)

        # Find or create corresponding AnimalGroup
        group_name = species.suggested_group or 'Fish'
        group_obj, _ = AnimalGroup.objects.get_or_create(
            name=group_name,
            defaults={'icon': species.icon, 'color': '#0ea5e9'}
        )

        care_notes = f"Care: {species.care_level}. Diet: {species.diet}. {species.notes}".strip()
        new_warnings = warnings_for_addition(species, target_tank, count)
        paid = _to_decimal(request.POST.get('paid')) if AppSettings.load().costs_enabled else None
        if paid is not None and (not paid.is_finite() or paid < 0 or paid >= Decimal('100000000')):
            paid = None

        animal = Animal.objects.create(
            paid=paid,
            name=species.name,
            species=species.species,
            tank=target_tank,
            count=count,
            status='healthy',
            notes=care_notes,
            acquired_date=timezone.localdate()
        )
        animal.groups.add(group_obj)
        if species.category == 'coral' and group_name not in ('Corals', 'Anemones'):
            corals, _ = AnimalGroup.objects.get_or_create(name='Corals', defaults={'icon': '🪸', 'color': '#ec4899'})
            animal.groups.add(corals)
        messages.success(request, f"Added {count}x {species.name} to {target_tank.name if target_tank else 'your roster'}.")
        for warning in new_warnings:
            if warning['level'] != 'info':
                messages.warning(request, f"{warning['title']}. {warning['detail']}")
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
    feeds = in_system(WebcamFeed.objects.filter(is_active=True), get_active_tank(request))
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

def _dose_context(tank):
    """Latest readings, targets and consumption per dosable parameter, in dKH / ppm."""
    context = {}
    since = timezone.now() - timedelta(days=14)

    by_code = {pt.code: pt for pt in ParameterType.objects.in_use().filter(code__in=DOSE_PARAMETERS).prefetch_related('targets')}
    # Two queries for every parameter's newest reading, and one for the last 14 days of all of them.
    newest = latest_logs_by_parameter(tank)
    recent = {}
    for log in in_system(ParameterLog.objects.filter(parameter_type__in=by_code.values(), measured_at__gte=since), tank):
        recent.setdefault(log.parameter_type_id, []).append(log)
    for code, info in DOSE_PARAMETERS.items():
        ptype = by_code.get(code)
        if ptype:
            ptype = ptype.for_system(tank)
        canon = info['unit']
        entry = {
            'code': code, 'name': info['name'], 'unit': canon,
            'decimals': info['decimals'], 'available': ptype is not None,
            'max_daily': MAX_DAILY_RAISE[code],
            'label_only': info.get('label_only', False), 'note': info.get('note', ''),
            'current': None, 'measured_at': None, 'target': None if ptype else info.get('typical'),
            'ideal_min': None, 'ideal_max': None, 'daily_change': None, 'display_unit': canon,
        }
        if ptype:
            def conv(v):
                return float(convert_value(float(v), ptype.unit, canon, code))
            entry['display_unit'] = ptype.unit
            entry['ideal_min'] = round(conv(ptype.min_ideal), 3)
            entry['ideal_max'] = round(conv(ptype.max_ideal), 3)
            entry['target'] = round((entry['ideal_min'] + entry['ideal_max']) / 2, 3)
            latest = newest.get(ptype.pk)
            if latest:
                entry['current'] = round(conv(latest.value), 3)
                entry['measured_at'] = timezone.localtime(latest.measured_at).strftime('%b %d, %H:%M')
            points = [(log.measured_at, conv(log.value)) for log in recent.get(ptype.pk, [])]
            change = estimate_daily_change(points)
            if change is not None:
                entry['daily_change'] = round(change, 3)
        context[code] = entry
    return context


def tank_volume_choices(tank):
    """Volumes the calculators can use for the selected system."""
    if tank is None:
        return None
    return {'id': tank.id, 'name': tank.name, 'display': float(tank.volume_gallons or 0),
            'sump': round(tank.sump_gallons, 1), 'system': tank.total_system_gallons}


def dosing_view(request):
    """Dosing additive reservoirs and ATO fresh water levels, forecasts and dose estimator."""
    tank = get_active_tank(request)
    reservoirs = in_system(DosingReservoir.objects.select_related('tank'), tank)

    return render(request, 'aquarium/dosing.html', {
        'dosing_containers': reservoirs.filter(reservoir_type='dosing_additive'),
        'ato_containers': reservoirs.filter(reservoir_type='ato_freshwater'),
        'form': DosingReservoirForm(initial={'tank': tank}),
        'doses': in_system(DoseLog.objects.select_related('tank', 'reservoir'), tank)[:15],
        **dose_log_context(tank),
    })


def dose_log_context(tank):
    """The Log a dose popup, starting on the selected tank."""
    return {'dose_form': DoseLogForm(initial={'tank': tank}, auto_id='dose_%s')}


@require_POST
def dose_log_create(request):
    form = DoseLogForm(request.POST)
    if form.is_valid():
        dose = form.save()
        taken = f" {dose.taken.normalize():f} {dose.reservoir.unit} came off {dose.reservoir.name}." if dose.taken else ''
        messages.success(request, f"Logged {dose.amount_label} {dose.product or dose.parameter_label}.{taken}")
    else:
        _flash_form_errors(request, form)
    return redirect(_safe_next(request, 'dosing'))


def dose_log_edit(request, dose_id):
    return _edit_object(request, DoseLog, DoseLogForm, dose_id, title='Edit Dose', back_url='/dosing/',
                        delete_url=f'/dosing/doses/{dose_id}/delete/')


def dose_log_delete(request, dose_id):
    dose = get_object_or_404(DoseLog, pk=dose_id)
    warning = f"{dose.taken.normalize():f} {dose.reservoir.unit} goes back into {dose.reservoir.name}." if dose.taken and dose.reservoir else ''
    return _delete_object(request, DoseLog, dose_id, label=str(dose), back_url='/dosing/', warning=warning)


def calculator_context(tank):
    """What the salt calculator and Dose Estimator need. They live on the Tools page."""
    return {
        **dose_log_context(tank),
        'dose_data': {
            'parameters': _dose_context(tank),
            'chemicals': [
                {'key': k, 'name': c['name'], 'parameter': c['parameter']}
                for k, c in DOSE_CHEMICALS.items()
            ],
        },
        'sample_mix': calculate_salt_mix(volume=10.0, volume_unit='gal', brand_key='tropic_marin_pro',
                                         target_salinity=1.026, salinity_unit='sg'),
        'salt_brands': SALT_MIX_RECIPES,
        'volume_tank': tank_volume_choices(tank),
    }


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
    except (TypeError, ValueError, OverflowError) as e:
        message = str(e) if isinstance(e, ValueError) else ''
        return JsonResponse({'error': message or 'Please fill in the current and target values and a tank volume.'}, status=400)


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
    tanks = Tank.objects.prefetch_related('sumps', 'equipment', 'animals', 'plumbing_runs')
    return render(request, 'aquarium/tanks.html', {
        'tank_cards': [{'tank': t, 'flow': t.flow_summary()} for t in tanks if not t.is_archived],
        'retired_tanks': [t for t in tanks if t.is_archived],
    })


@require_POST
def tank_move_view(request, tank_id):
    """Moves a tank one place up or down the list. Retired tanks keep their places at the end."""
    tanks = list(Tank.objects.filter(is_archived=False))
    index = next((i for i, t in enumerate(tanks) if t.pk == tank_id), None)
    if index is None:
        raise Http404
    other = index - 1 if request.POST.get('direction') == 'up' else index + 1
    if 0 <= other < len(tanks):
        tanks[index], tanks[other] = tanks[other], tanks[index]
    for position, tank in enumerate(tanks + list(Tank.objects.filter(is_archived=True))):
        if tank.position != position:
            Tank.objects.filter(pk=tank.pk).update(position=position)
    return redirect(reverse('tanks') + f'#tank-{tank_id}')


def tank_detail_view(request, tank_id):
    tank = get_object_or_404(Tank.objects.prefetch_related('sumps__chambers', 'equipment', 'plumbing_runs'), id=tank_id)

    # Group this tank's equipment by where it sits.
    all_equipment = list(tank.equipment.all())
    by_sump, by_chamber, display_equipment = {}, {}, []
    for eq in all_equipment:
        if eq.chamber_id:
            by_chamber.setdefault(eq.chamber_id, []).append(eq)
        elif eq.sump_id:
            by_sump.setdefault(eq.sump_id, []).append(eq)
        else:
            display_equipment.append(eq)
    sumps = []
    for sump in tank.sumps.all():
        chambers = [{'chamber': c, 'equipment': by_chamber.get(c.id, [])} for c in sump.chambers.all()]
        sumps.append({'sump': sump, 'equipment': by_sump.get(sump.id, []), 'chambers': chambers})

    return render(request, 'aquarium/tank_detail.html', {
        'tank': tank,
        'flow': tank.flow_summary(),
        'flow_equipment': _tank_equipment_flow(tank),
        'display_equipment': display_equipment,
        'sump_rows': sumps,
    })


def _settle_primary(tank):
    """Only one system can be primary, and a retired one can't be."""
    if tank.is_archived:
        Tank.objects.filter(pk=tank.pk).update(is_primary=False)
    elif tank.is_primary:
        Tank.objects.exclude(pk=tank.pk).update(is_primary=False)


def tank_create_view(request):
    if request.method == 'POST':
        form = TankForm(request.POST)
        if form.is_valid():
            tank = form.save()
            _settle_primary(tank)
            messages.success(request, f"Added {tank.name}.")
            return redirect('tank_detail', tank_id=tank.id)
    else:
        form = TankForm(initial={'is_primary': not Tank.objects.filter(is_archived=False).exists()})
    return render(request, 'aquarium/vessel_form.html', {
        'form': form, 'title': 'Add Tank', 'kind': 'tank', 'back_url': '/tanks/',
    })


def tank_edit_view(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id)
    if request.method == 'POST':
        form = TankForm(request.POST, instance=tank)
        if form.is_valid():
            tank = form.save()
            _settle_primary(tank)
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
               f"{tank.routines.count()} routine(s), {tank.water_changes.count()} water change log(s) and "
               f"{tank.parameter_logs.count()} water test(s). "
               f"{tank.animals.count()} animal(s) and {tank.equipment.count()} equipment item(s) are kept but unassigned.")
    response = _delete_object(request, Tank, tank_id, label=tank.name, back_url='/tanks/', warning=warning)
    if request.method == 'POST':
        retire.promote_new_primary()
    return response


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
        'form': form, 'title': f'Edit {sump.name}', 'kind': 'sump', 'sump': sump,
        'chamber_types': [{'value': k, 'label': v} for k, v in SumpChamber.CHAMBER_TYPES],
        'back_url': f'/tanks/{sump.tank_id}/', 'delete_url': f'/sumps/{sump.id}/delete/',
    })


def sump_delete_view(request, sump_id):
    sump = get_object_or_404(Sump, id=sump_id)
    return _delete_object(request, Sump, sump_id, label=sump.name, back_url=f'/tanks/{sump.tank_id}/',
                          warning="Its chambers are deleted too.")


def _plumbing_form_page(request, form, tank, title, delete_url=None):
    return render(request, 'aquarium/plumbing_form.html', {
        'form': form, 'tank': tank, 'title': title,
        'back_url': f'/tanks/{tank.id}/', 'delete_url': delete_url,
    })


def plumbing_create_view(request, tank_id):
    tank = get_object_or_404(Tank, id=tank_id)
    if request.method == 'POST':
        form = PlumbingRunForm(request.POST)
        if form.is_valid():
            run = form.save(commit=False)
            run.tank = tank
            run.save()
            messages.success(request, f"Added {run.display_name}: {run.gallons} gal.")
            return redirect('tank_detail', tank_id=tank.id)
    else:
        form = PlumbingRunForm()
    return _plumbing_form_page(request, form, tank, f'Add Plumbing Run · {tank.name}')


def plumbing_edit_view(request, run_id):
    run = get_object_or_404(PlumbingRun.objects.select_related('tank'), id=run_id)
    if request.method == 'POST':
        form = PlumbingRunForm(request.POST, instance=run)
        if form.is_valid():
            form.save()
            messages.success(request, "Plumbing run saved.")
            return redirect('tank_detail', tank_id=run.tank_id)
    else:
        form = PlumbingRunForm(instance=run)
    return _plumbing_form_page(request, form, run.tank, f'Edit {run.display_name}',
                               delete_url=f'/plumbing/{run.id}/delete/')


def plumbing_delete_view(request, run_id):
    run = get_object_or_404(PlumbingRun, id=run_id)
    return _delete_object(request, PlumbingRun, run_id, label=run.display_name, back_url=f'/tanks/{run.tank_id}/')


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
        return redirect(reverse('sump_edit', args=[sump.id]) + '#chambers')

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
        # Update existing chambers in order rather than recreating them, so equipment
        # placed in a chamber stays there. Extra chambers are deleted; equipment in
        # them falls back to the sump as a whole.
        existing = list(sump.chambers.order_by('position', 'id'))
        for i in range(count):
            chamber = existing[i] if i < len(existing) else SumpChamber(sump=sump)
            chamber.position = i + 1
            chamber.name = (names[i] if i < len(names) else '').strip()[:80]
            chamber.chamber_type = types[i] if types[i] in valid_types else 'other'
            chamber.share_percent = shares[i]
            chamber.save()
        for chamber in existing[count:]:
            chamber.delete()

    total = sum(shares)
    if abs(total - 100) > Decimal('0.5'):
        messages.warning(request, f"Chambers saved, but their shares add up to {total}% rather than 100%.")
    else:
        messages.success(request, f"{sump.name} split into {count} chamber{'s' if count != 1 else ''}.")
    return redirect(reverse('sump_edit', args=[sump.id]) + '#chambers')


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
    tanks = Tank.objects.filter(is_archived=False)
    active_tank = get_active_tank(request)
    # Defaults to the selected system. ?tank=all shows every system, ?tank=<id> just one.
    tank_param = request.GET.get('tank') or (str(active_tank.pk) if active_tank else 'all')
    selected_tank_id = None if tank_param == 'all' else _to_int(tank_param, None)
    selected_category = request.GET.get('category')

    equipment_list = (Equipment.objects.select_related('tank', 'sump', 'chamber__sump')
                      .prefetch_related('routines'))
    if selected_tank_id:
        equipment_list = equipment_list.filter(tank_id=selected_tank_id)
    else:
        equipment_list = not_retired(equipment_list)
    if selected_category:
        equipment_list = equipment_list.filter(category=selected_category)

    total_watts = equipment_list.aggregate(total=Sum('wattage'))['total'] or 0

    return render(request, 'aquarium/equipment.html', {
        'tanks': tanks,
        'equipment_list': equipment_list,
        'selected_tank_id': selected_tank_id,
        'tank_param': tank_param,
        'selected_category': selected_category,
        'equipment_form': EquipmentForm(initial={'location': _default_location(active_tank)}),
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


def _default_location(tank):
    return f"tank:{tank.id}" if tank else ''


def equipment_create_view(request):
    """POST from the equipment-page modal, or a full page (GET ?location=sump:3) from a tank page."""
    next_url = _safe_next(request, '/equipment/')
    if request.method == 'POST':
        form = EquipmentForm(request.POST)
        if form.is_valid():
            eq = form.save()
            messages.success(request, f"Added {eq.name}" + (f" to {eq.location_label}." if eq.location_label else "."))
            return redirect(next_url)
        if request.POST.get('full_page'):
            return render(request, 'aquarium/generic_form.html', {
                'form': form, 'title': 'Add Equipment', 'back_url': next_url, 'full_page': True})
        _flash_form_errors(request, form)
        return redirect('equipment')
    form = EquipmentForm(initial={'location': request.GET.get('location') or _default_location(get_active_tank(request))})
    return render(request, 'aquarium/generic_form.html', {
        'form': form, 'title': 'Add Equipment',
        'subtitle': 'Placed where you chose; change the location below if needed',
        'back_url': next_url, 'full_page': True,
    })


def equipment_edit_view(request, eq_id):
    return _edit_object(request, Equipment, EquipmentForm, eq_id, title='Edit Equipment',
                        back_url='/equipment/', delete_url=f'/equipment/{eq_id}/delete/')


def equipment_delete_view(request, eq_id):
    eq = get_object_or_404(Equipment, id=eq_id)
    return _delete_object(request, Equipment, eq_id, label=eq.name, back_url='/equipment/')


# ==========================================
# Maintenance Routines & Water Change Checklists
# ==========================================

def _last_salt_brand():
    """The salt used last time, if it's one the calculator knows, so the next log starts there."""
    last = WaterChangeLog.objects.exclude(salt_brand='').order_by('-performed_at').values_list('salt_brand', flat=True).first()
    return last if last in {r['name'] for r in SALT_MIX_RECIPES.values()} else ''


# The popup's fields share the app's usual field look, and the height of its amount and salinity boxes. min-w-0 and the fixed height keep a
# phone's date picker from spilling out of its box.
WC_POPUP_FIELD = ('block w-full min-w-0 h-11 px-3 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm '
                  'appearance-none focus:outline-none focus:ring-2 focus:ring-cyan-500')


def water_change_context(tank):
    """The Log Water Change popup: its form, starting on the selected tank, and each tank's total water for %."""
    form = WaterChangeLogForm(initial={'tank': tank, 'salt_brand': _last_salt_brand()}, auto_id='wc_%s')
    for name in ('tank', 'salt_brand', 'notes', 'performed_at'):
        # Menus keep their own arrow; the date box drops the phone's default styling so it fits.
        form.fields[name].widget.attrs['class'] = WC_POPUP_FIELD.replace(' appearance-none', '') if name in ('tank', 'salt_brand') else WC_POPUP_FIELD
    return {
        'wc_form': form,
        'wc_tank_volumes': {str(t.pk): t.total_system_gallons
                            for t in Tank.objects.filter(is_archived=False).prefetch_related('sumps', 'plumbing_runs')},
    }


def routines_view(request):
    """Recurring tank checklists, water change preparation calculator, and change logs."""
    tank = get_active_tank(request)
    routines = list(in_system(MaintenanceRoutine.objects.select_related('tank').prefetch_related('equipment__tank'), tank))
    far = timezone.localdate() + timedelta(days=10000)
    manual_routines = sorted(
        (r for r in routines if not r.is_automated),
        key=lambda r: (not r.is_active, r.next_due_date or far))
    running_timers = {t.name: t for t in FillTimer.objects.filter(status='running')}
    for routine in manual_routines:
        routine.steps = routine.checklist_steps
        for step in routine.steps:
            step['timer'] = running_timers.get(step['timer_name'])
    automated_routines = sorted(
        (r for r in routines if r.is_automated),
        key=lambda r: (not r.is_active, r.upcoming['at'] if r.upcoming else timezone.now() + timedelta(days=30)))
    water_changes = in_system(WaterChangeLog.objects.select_related('tank'), tank)[:10]
    return render(request, 'aquarium/routines.html', {
        'manual_routines': manual_routines,
        'automated_routines': automated_routines,
        'water_changes': water_changes,
        **water_change_context(tank),
        'routine_form': MaintenanceRoutineForm(initial={'tank': tank}),
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
    routine = get_object_or_404(MaintenanceRoutine, id=routine_id)
    if request.method == 'POST':
        form = MaintenanceRoutineForm(request.POST, instance=routine)
        if form.is_valid():
            form.save()
            messages.success(request, "Routine saved.")
            return redirect('routines')
    else:
        form = MaintenanceRoutineForm(instance=routine)
    return render(request, 'aquarium/routine_form.html', {'form': form, 'routine': routine})


@require_POST
def routine_toggle_view(request, routine_id):
    """Pause or resume a routine."""
    routine = get_object_or_404(MaintenanceRoutine, id=routine_id)
    routine.is_active = not routine.is_active
    routine.save(update_fields=['is_active'])
    messages.success(request, f"{routine.title} {'resumed' if routine.is_active else 'paused'}.")
    return redirect(_safe_next(request, 'routines'))


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
        start_salinity = float(request.GET.get('start_salinity') or 0)

        result = calculate_salt_mix(
            volume=volume,
            volume_unit=volume_unit,
            brand_key=brand,
            target_salinity=salinity,
            salinity_unit=salinity_unit,
            start_salinity=start_salinity
        )
        return JsonResponse(result)
    except (TypeError, ValueError) as e:
        return JsonResponse({'error': str(e)}, status=400)


def water_change_log_create(request):
    if request.method == 'POST':
        form = WaterChangeLogForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Water change logged: {form.instance.gallons} gal on {form.instance.tank.name}.")
        else:
            _flash_form_errors(request, form)
    return redirect(_safe_next(request, 'routines'))


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

MUTE_MINUTES = {'30m': 30, '1h': 60, '4h': 240, '8h': 480, '24h': 1440, '3d': 4320, '7d': 10080}
MAX_MUTE_HOURS = 24 * 30


@require_POST
def notifications_mute_view(request):
    """Pauses phone alerts and alert webhooks for a while, until further notice, or ends a mute."""
    choice = request.POST.get('duration', '')
    typed_hours = (request.POST.get('custom_hours') or '').strip()
    custom_hours = _to_decimal(typed_hours)
    until, forever = None, False
    if choice == 'off':
        message = "Notifications are back on."
    elif choice == 'forever':
        forever = True
        message = "Notifications muted until you turn them back on."
    else:
        if typed_hours:
            minutes = int(custom_hours * 60) if custom_hours is not None and 0 < custom_hours <= MAX_MUTE_HOURS else None
        else:
            minutes = MUTE_MINUTES.get(choice)
        if not minutes:
            messages.error(request, f"Choose how long to mute for, up to {MAX_MUTE_HOURS} hours.")
            return redirect(_safe_next(request, 'notifications'))
        until = timezone.now() + timedelta(minutes=minutes)
        message = f"Notifications muted until {timezone.localtime(until):%b %-d, %-I:%M %p}."
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(alerts_muted_until=until, alerts_muted_forever=forever)
    messages.success(request, message)
    return redirect(_safe_next(request, 'notifications'))


ALERT_SEVERITIES = ('critical', 'warning', 'info')
ALERT_STATUSES = ('active', 'resolved')


def _alerts_matching(state, severity):
    """The active alert lists for one severity. These match the severities the notifications use."""
    if not severity:
        return {}
    parameters = [i for i in state['out_of_range_params'] if ('critical' if i['critical'] else 'warning') == severity]
    return {
        'out_of_range_params': parameters,
        'stale_params': state['stale_params'] if severity == 'warning' else [],
        'low_reservoirs': state['low_reservoirs'] if severity == 'warning' else [],
        'sick_animals': state['sick_animals'] if severity == 'warning' else [],
        'due_routines': state['due_routines'] if severity == 'info' else [],
        'due_equipment': state['due_equipment'] if severity == 'info' else [],
    }


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

    severity = request.GET.get('severity', '')
    status = request.GET.get('status', '')
    if severity not in ALERT_SEVERITIES:
        severity = ''
    if status not in ALERT_STATUSES:
        status = ''

    # The filters only change this page's lists. `state` is shared with the alert badge, so it's left whole.
    context = dict(state)
    context.update(_alerts_matching(state, severity))
    context['shown_alerts'] = sum(len(context[name]) for name in ('out_of_range_params', 'stale_params', 'low_reservoirs', 'due_routines', 'due_equipment', 'sick_animals'))
    context['r2r_forums'] = r2r_forums
    context['history'] = alert_summary(get_active_tank(request), severity)
    context['show_active'] = status != 'resolved'
    context['show_resolved'] = status != 'active'
    context['severity_filters'] = [
        {'label': label, 'active': severity == value, 'query': urlencode({k: v for k, v in (('severity', value), ('status', status)) if v})}
        for value, label in (('', 'All'), ('critical', 'Critical'), ('warning', 'Warning'), ('info', 'Reminder'))
    ]
    context['status_filters'] = [
        {'label': label, 'active': status == value, 'query': urlencode({k: v for k, v in (('severity', severity), ('status', value)) if v})}
        for value, label in (('', 'All'), ('active', 'Active'), ('resolved', 'Resolved'))
    ]
    return render(request, 'aquarium/notifications.html', context)


# ==========================================
# PWA service worker (must be served from "/" so it can control the whole site)
# ==========================================

def app_icon_view(request, size):
    """The browser tab and home-screen icon: the main tank's icon, or the standard nudibranch."""
    from . import app_icon
    path = app_icon.png(size)
    if path is None:
        return redirect('/static/icons/icon.svg')
    response = FileResponse(open(path, 'rb'), content_type='image/png')
    response['Cache-Control'] = 'public, max-age=86400'  # the links carry a version, so a new icon is a new address
    return response


def manifest_view(request):
    """The install details for the home-screen app, with the main tank's icon."""
    from . import app_icon
    tag = app_icon.version()
    if tag == 'default':
        app_icons = [{'src': '/static/icons/icon.svg', 'sizes': '192x192 512x512', 'type': 'image/svg+xml', 'purpose': 'any'}]
    else:
        app_icons = [{'src': f'/app-icon/{size}.png?v={tag}', 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any'}
                     for size in (192, 512)]
    response = JsonResponse({
        'name': 'Nudibranch Reef Manager',
        'short_name': 'Nudibranch',
        'description': 'Saltwater aquarium parameter tracker, livestock manager, and webcam viewer',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#0f172a',
        'theme_color': '#0f172a',
        'orientation': 'portrait-primary',
        'icons': app_icons,
    }, content_type='application/manifest+json')
    response['Cache-Control'] = 'no-cache'
    return response


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
