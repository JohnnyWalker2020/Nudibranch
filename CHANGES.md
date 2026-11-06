# Nudibranch: change summary

## Round 4 (2026-11-05)

Apply the same way (`docker compose down && docker compose up -d --build`); migration 0008 runs on start.

- **Plumbing runs**: a tank can have any number of runs (return line, drains, manifold...). Each run has a
  length (ft or m), a Sch 40 PVC size **or a custom inside diameter** (in or mm), how many identical pipes,
  and how full it runs (drains are often 50-80%). Managed on the tank page; live volume estimate on the form.
  The single plumbing length/diameter from round 3 is moved into a run called "Plumbing" automatically.
- **Repeat schedules for every routine**: Every day / 2 days / week / 2 weeks / month / 3 months / 6 months /
  year, or Custom (every N days, weeks, months or years). Plus a start date, weekdays for weekly schedules,
  and an optional due time for manual routines. Cards show "next due", "in 3d", DUE or OVERDUE.
  Completing early/late counts for the nearest scheduled date (doing a Saturday job on Friday covers Saturday).
  Existing routines are converted (7 days -> every week, 30 -> every month, 90 -> every 3 months...) and
  anchored on their last completion, so their next due date doesn't change.
- **Parameter low / optimal / high ranges**: optional low and high *alert limits* around the optimal range.
  Outside optimal = LOW/HIGH (amber); at or past a limit = CRITICAL LOW/HIGH (red, listed first in alerts,
  bigger health-score hit). Set them in each parameter's settings (live zone preview); converted along with the
  unit. Charts shade amber/red zones. Default parameters get starter limits (only if still on their default units).

## Round 3 (2026-11-05)

Apply with a rebuild (`docker compose down && docker compose up -d --build`); migration 0007 runs on start.
Check afterwards: `docker compose exec web python manage.py makemigrations --check --dry-run` should say "No changes detected".

- **Charts default to "All parameters"** on the dashboard trends widget and the Parameters page. The old
  "All Parameters" button just showed the first parameter. Each line is scaled to its own ideal range
  (shaded band = in range) so SG, calcium and phosphate fit on one chart; hover shows the real value.
  Single-parameter charts now shade the ideal range too, and use a real time axis. Shared code: `static/js/charts.js`.
- **Automated routines**: a routine is now either a *manual checklist* (every N days, shows as due) or an
  *automated schedule* (times of day + weekdays, e.g. feeder, lights, skimmer). Automated ones never nag;
  they show the next event, a 24h timeline, and can be paused/resumed. New categories: feeding, lighting,
  skimmer, pumps & flow, dosing, top-off.
- **Equipment linked to routines** (many-to-many). Shown on routine cards and on equipment cards.
- **Equipment placement**: equipment has a *Location*: display tank, a whole sump, or a specific sump chamber.
  The tank page lists display-tank gear, shows gear inside each chamber tile, and has "+ Equipment" links
  that pre-fill the location. New equipment category: Auto Feeder.
- **Plumbing volume**: tanks have optional *feet of plumbing* and *pipe diameter* (Sch 40 PVC 1/2" to 2").
  The water in the pipes is added to total system volume (dosing and turnover use it).
- **Salt calculator**: AquaForest Reef Salt corrected to its label (390 g per 10 L for 33 ppt). It was ~369 g.
- **Sump re-split keeps chambers** (updates them in place) so equipment placed in a chamber isn't lost.
- `docker-compose.yml`: `TIME_ZONE=America/Regina` (was UTC), needed for schedule times and log timestamps.

## Round 2

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
