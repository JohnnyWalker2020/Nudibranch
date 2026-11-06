# Nudibranch: change summary

Drop these files over your project (same relative paths), then:

```bash
python manage.py makemigrations --check   # should report no changes
python manage.py migrate                  # applies 0006
python manage.py seed_reef_data           # optional, existing
python manage.py seed_system_example      # optional: sample sump/chambers/pump flows
```

Not tested by running Django (no network in the authoring sandbox); everything was compiled and
cross-checked statically (all `{% url %}` names resolve, template tags balance, views ↔ templates agree).

## New features
- **Tank dimensions + capacity**: width/depth/height (in or cm), usable-water %, live estimate while typing, or tick "enter capacity manually".
- **Sumps & chambers**: tank → many sumps → split into N chambers (inflow, skimmer, refugium, return, …) with % shares; diagram on the tank page.
- **Flow & turnover**: pumps/wavemakers have rated max gph, a **power setting %** and head-loss %; the tank page and tanks list show return turnover (target 4–10x/hr of system) and circulation (20–50x/hr of display).
- **Reservoir resize**: Dosing page → "Resize / Edit" on any container (size, level, unit, daily use, colour).
- **Dose estimator** (Dosing page): current/target prefilled from logs and ideal range, volume from tank + sump; dry-chemical (stoichiometry) or commercial-label mode; daily-raise safety limit splits corrections over days; maintenance dose from daily consumption (regressed from your logs).
- **Customisable dashboard**: "Customize" button; show/hide and reorder widgets; reset to default.
- **Quick-measure widget** on the dashboard: one value box + parameter dropdown.
- **Edit/delete in the GUI** for tanks, sumps, chambers, equipment, reservoirs, parameters, logs, groups, routines, water changes, webcams, animals.

## Bug fixes
- Notifications page: Reef2Reef links used unreliable URLs (now site-restricted search), "mark serviced"/"done" and refill buttons now work and return you to the page; reservoir/routine actions added.
- Modals were toggled with `hidden` only, so they never centred; new `openModal`/`closeModal` helpers (Escape closes).
- Service worker was registered at `/static/sw.js` (scope limited to `/static/`); now `/sw.js`. `cache.addAll` aborted the whole install if one icon was missing; caching is now tolerant and offline fallback works.
- `animal_form.html` nested `{% block extra_js %}` inside `content` (script never ran on some Django versions).
- Mobile nav highlighted the wrong tab (substring match on URL name).
- Quick-log modal shared the `form` context name with the livestock page; now `modal_form` via context processor.
- Admin: registers Sump, SumpChamber, DashboardWidget; new fields shown.
