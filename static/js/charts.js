// Nudibranch parameter charts, shared by the dashboard trends widget and the Parameters page.
//
// Two chart modes:
//   * single parameter  -> real values, with the ideal range shaded
//   * all parameters    -> every parameter on one chart, scaled to its own ideal range
//                          (0% = bottom of range, 100% = top), because SG (1.025),
//                          calcium (420) and phosphate (0.03) can't share a raw axis.
(function () {
  const GRID = '#1e293b';
  const TICK = '#64748b';
  const TOOLTIP = { backgroundColor: '#0f172a', borderColor: '#334155', borderWidth: 1, titleColor: '#fff', bodyColor: '#cbd5e1' };
  const BAND = 'rgba(16, 185, 129, 0.08)';
  const BAND_EDGE = 'rgba(16, 185, 129, 0.35)';
  const WARN = 'rgba(245, 158, 11, 0.06)';
  const CRIT = 'rgba(244, 63, 94, 0.08)';
  // Points far out of range are pinned to the chart edge so one bad reading
  // doesn't squash every other line flat. The tooltip still shows the real value.
  const PCT_MIN = -100, PCT_MAX = 200;

  function fmtTime(ms) {
    const d = new Date(ms);
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  function fmtDay(ms) {
    const d = new Date(ms);
    return (d.getMonth() + 1) + '/' + d.getDate();
  }

  // Shades horizontal zones. Each zone: {low, high, fill, edge}; null low/high = chart edge.
  function zonesPlugin(zones) {
    return {
      id: 'rangeZones',
      beforeDatasetsDraw(chart) {
        const y = chart.scales.y, area = chart.chartArea;
        if (!y) return;
        const ctx = chart.ctx;
        ctx.save();
        zones.forEach(z => {
          const top = z.high == null ? area.top : Math.max(area.top, y.getPixelForValue(z.high));
          const bottom = z.low == null ? area.bottom : Math.min(area.bottom, y.getPixelForValue(z.low));
          if (bottom <= top) return;
          ctx.fillStyle = z.fill;
          ctx.fillRect(area.left, top, area.right - area.left, bottom - top);
          if (z.edge) {
            ctx.strokeStyle = z.edge;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            if (z.high != null) { ctx.moveTo(area.left, top); ctx.lineTo(area.right, top); }
            if (z.low != null) { ctx.moveTo(area.left, bottom); ctx.lineTo(area.right, bottom); }
            ctx.stroke();
          }
        });
        ctx.restore();
      },
    };
  }

  function bandPlugin(low, high) {
    return zonesPlugin([{ low, high, fill: BAND, edge: BAND_EDGE }]);
  }

  // Optimal band, amber between the alert limits and the optimal range, red past the limits.
  function rangeZones(min, max, lowLimit, highLimit) {
    const zones = [{ low: min, high: max, fill: BAND, edge: BAND_EDGE }];
    if (lowLimit != null) {
      zones.push({ low: lowLimit, high: min, fill: WARN });
      zones.push({ low: null, high: lowLimit, fill: CRIT, edge: 'rgba(244, 63, 94, 0.4)' });
    }
    if (highLimit != null) {
      zones.push({ low: max, high: highLimit, fill: WARN });
      zones.push({ low: highLimit, high: null, fill: CRIT, edge: 'rgba(244, 63, 94, 0.4)' });
    }
    return zonesPlugin(zones);
  }

  function timeAxis(spanDays) {
    return {
      type: 'linear',
      grid: { color: GRID },
      ticks: { color: TICK, maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 10 },
               callback: v => (spanDays > 2 ? fmtDay(v) : fmtTime(v)) },
    };
  }

  function rangeStatus(v, min, max, lowLimit, highLimit) {
    if (v < min) return (lowLimit != null && v <= lowLimit) ? 'CRITICAL low' : 'low';
    if (v > max) return (highLimit != null && v >= highLimit) ? 'CRITICAL high' : 'high';
    return 'optimal';
  }

  /** One parameter, real values. `data` is the /api/parameters/chart-data/ response. */
  function renderSingle(canvas, data, previous, opts) {
    if (previous) previous.destroy();
    const p = data.parameter;
    const color = p.color || '#06b6d4';
    const pts = (data.timestamps || []).map((t, i) => ({ x: t, y: data.values[i] }));
    const days = (opts && opts.days) || 30;
    return new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [{
        label: p.name + ' (' + p.unit + ')', data: pts, borderColor: color, backgroundColor: color + '20',
        fill: false, tension: 0.3, pointBackgroundColor: color, pointRadius: 4, pointHoverRadius: 6,
      }]},
      options: {
        responsive: true, maintainAspectRatio: false, parsing: false,
        plugins: {
          legend: { display: false },
          tooltip: { ...TOOLTIP, callbacks: {
            title: items => items.length ? fmtTime(items[0].parsed.x) : '',
            label: item => p.name + ': ' + item.parsed.y + ' ' + p.unit + ' (' + rangeStatus(item.parsed.y, p.min_ideal, p.max_ideal, p.low_limit, p.high_limit) + ')',
          }},
        },
        scales: {
          x: timeAxis(days),
          y: { grid: { color: GRID }, ticks: { color: TICK, font: { size: 10 } },
               suggestedMin: p.low_limit != null ? p.low_limit : p.min_ideal,
               suggestedMax: p.high_limit != null ? p.high_limit : p.max_ideal },
        },
      },
      plugins: [rangeZones(p.min_ideal, p.max_ideal, p.low_limit, p.high_limit)],
    });
  }

  /** Every parameter on one chart. `data` is the /api/parameters/chart-data/all/ response. */
  function renderAll(canvas, data, previous, opts) {
    if (previous) previous.destroy();
    const days = (opts && opts.days) || data.days || 30;
    const datasets = data.datasets.map(ds => {
      const span = (ds.max_ideal - ds.min_ideal) || Math.abs(ds.min_ideal) * 0.1 || 1;
      const pts = ds.timestamps.map((t, i) => {
        const raw = ds.values[i];
        const pct = (raw - ds.min_ideal) / span * 100;
        return { x: t, y: Math.max(PCT_MIN, Math.min(PCT_MAX, pct)), raw: raw };
      });
      return {
        label: ds.name, data: pts, unit: ds.unit, min: ds.min_ideal, max: ds.max_ideal,
        lowLimit: ds.low_limit, highLimit: ds.high_limit,
        borderColor: ds.color, backgroundColor: ds.color, tension: 0.3, fill: false,
        pointRadius: 3, pointHoverRadius: 6, borderWidth: 2,
      };
    });
    return new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, parsing: false,
        interaction: { mode: 'nearest', intersect: false },
        plugins: {
          legend: { position: 'bottom', labels: { color: '#94a3b8', boxWidth: 10, boxHeight: 10, font: { size: 11, weight: 'bold' } } },
          tooltip: { ...TOOLTIP, callbacks: {
            title: items => items.length ? fmtTime(items[0].parsed.x) : '',
            label: item => {
              const ds = item.dataset, raw = ds.data[item.dataIndex].raw;
              return ds.label + ': ' + raw + ' ' + ds.unit + ' (' + rangeStatus(raw, ds.min, ds.max, ds.lowLimit, ds.highLimit) + ')';
            },
          }},
        },
        scales: {
          x: timeAxis(days),
          y: { grid: { color: GRID }, suggestedMin: -25, suggestedMax: 125,
               title: { display: true, text: 'Position in ideal range', color: TICK, font: { size: 10 } },
               ticks: { color: TICK, font: { size: 10 }, stepSize: 25,
                        callback: v => v === 0 ? 'Min' : v === 100 ? 'Max' : v + '%' } },
        },
      },
      plugins: [bandPlugin(0, 100)],
    });
  }

  /**
   * Loads and draws a chart. code === 'all' (or empty) draws every parameter.
   * Returns { chart, empty } so callers can update headings.
   */
  async function loadParameterChart(canvas, code, days, previous) {
    const all = !code || code === 'all';
    const url = all
      ? '/api/parameters/chart-data/all/?days=' + days
      : '/api/parameters/chart-data/?code=' + encodeURIComponent(code) + '&days=' + days;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Chart data request failed: ' + res.status);
    const data = await res.json();
    if (all) {
      return { chart: renderAll(canvas, data, previous, { days }), data, all,
               empty: !data.datasets.length };
    }
    return { chart: renderSingle(canvas, data, previous, { days }), data, all,
             empty: !data.values.length };
  }

  window.NudiCharts = { loadParameterChart, renderAll, renderSingle };
})();
