from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from .models import ParameterType, ParameterLog, Animal, AnimalGroup, WebcamFeed
from .forms import QuickParameterLogForm, AnimalForm


def dashboard_view(request):
    """Main dashboard: latest parameters, quick-add, livestock overview, and mini webcam preview."""
    parameter_types = ParameterType.objects.all()
    recent_logs = ParameterLog.objects.select_related('parameter_type')[:8]
    total_animals = Animal.objects.filter(status='healthy').aggregate(total=Sum('count'))['total'] or 0
    groups = AnimalGroup.objects.all()
    active_cameras = WebcamFeed.objects.filter(is_active=True)[:2]
    form = QuickParameterLogForm()

    return render(request, 'aquarium/dashboard.html', {
        'parameter_types': parameter_types,
        'recent_logs': recent_logs,
        'total_animals': total_animals,
        'groups': groups,
        'active_cameras': active_cameras,
        'form': form,
    })


def parameters_view(request):
    """Full parameter management, historical logs, and interactive charts."""
    param_code = request.GET.get('param')
    types = ParameterType.objects.all()

    logs_query = ParameterLog.objects.select_related('parameter_type')
    if param_code:
        logs_query = logs_query.filter(parameter_type__code=param_code)

    recent_logs = logs_query[:50]
    form = QuickParameterLogForm()

    return render(request, 'aquarium/parameters.html', {
        'parameter_types': types,
        'selected_code': param_code,
        'recent_logs': recent_logs,
        'form': form,
    })


def api_chart_data(request):
    """JSON API endpoint powering dynamic Chart.js rendering."""
    param_code = request.GET.get('code')
    days = int(request.GET.get('days', 30))

    if not param_code:
        # Default to first parameter type
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
    values = [float(log.value) for log in logs]

    return JsonResponse({
        'parameter': {
            'name': ptype.name,
            'unit': ptype.unit,
            'min_ideal': float(ptype.min_ideal),
            'max_ideal': float(ptype.max_ideal),
            'color': ptype.color,
        },
        'labels': labels,
        'values': values,
    })


def quick_log_create(request):
    """Handles quick-add parameter submissions via HTMX or standard form POST."""
    if request.method == 'POST':
        form = QuickParameterLogForm(request.POST)
        if form.is_valid():
            log = form.save()
            if getattr(request, 'htmx', False):
                # Return partial row and trigger client-side chart reload
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


def livestock_view(request):
    """Livestock listing with group filtering."""
    group_id = request.GET.get('group')
    status_filter = request.GET.get('status')

    animals = Animal.objects.prefetch_related('groups').all()
    if group_id:
        animals = animals.filter(groups__id=group_id)
    if status_filter:
        animals = animals.filter(status=status_filter)

    groups = AnimalGroup.objects.all()

    return render(request, 'aquarium/livestock.html', {
        'animals': animals,
        'groups': groups,
        'selected_group': int(group_id) if group_id else None,
        'selected_status': status_filter,
    })


def webcams_view(request):
    """Live aquarium webcam feeds."""
    feeds = WebcamFeed.objects.filter(is_active=True)
    return render(request, 'aquarium/webcams.html', {
        'feeds': feeds,
    })
