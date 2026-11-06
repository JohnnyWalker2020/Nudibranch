# Nudibranch: change summary

## Round 6 (2026-11-05)

Apply with `docker compose up -d --build`; migrations 0012 to 0019 run on start and assign your existing water tests to your primary tank.

- **One selected system**: a selector at the top of every page picks the system, remembered per browser. The dashboard, parameters,
  charts, livestock, equipment, dosing, routines, webcams, alerts, power and calculators then show just that system.
  Universal: wishlist, plans, species catalog, parameter names and units, webhooks, backups, quarantine list.
- **Per-system target ranges**: a parameter's settings page edits the selected system's ranges. Systems without their own use the
  default, and can go back to it at any time. Readings, alerts, charts and the Dose Estimator all use the right system's targets.
- **Water tests belong to a system**. The API takes an optional `tank` (ID or name); without it, readings go to the primary tank.
  Background alerts check every system, and the selector marks other systems that have alerts.
- **Equipment** and **Power** have an "All systems" view. Webcams can belong to one system, or show on all.
- **Calculators** use the selected system automatically, with whole system, display, sump or custom volume.
- **Planner projects**: group several planned systems into a project to compare them side by side and see combined water, cost, power and
  budget. Copy a plan to try a variation. Nothing becomes real until you track that one plan.
- **Retiring a system** (button on its tank page): keeps all its data, switches its icon to the old version, and stops its alerts, schedules,
  time-lapse and new tests. It moves to a Retired group in the selector and can be brought back any time. An uploaded icon never changes.
- **System look**: each system has a colour scheme and a character or uploaded icon. Characters are `NN-name-young.png` and `NN-name-old.png`
  pairs in `static/icons/nudibranch`, and small copies are made at startup. The "Match my icon" scheme builds its colours from the icon. Settings has "Disable icon aging" and "Enable old version icons".
- **The Damage**: there's a hidden, fire-themed spending ledger. It's off until you "light the match" inside it, which turns on "what you
  paid" on livestock and equipment. Those land in the ledger and stay in sync with it. Planner and Wishlist prices are always visible, and
  only reach the ledger when an item moves into an active tank. Putting the fire out hides spending but erases nothing, and the page says so. The ledger can be filtered by system and dates, and has a spending chart.
- **Fixed**: restarting the app recreated "Main Display Tank" and its sample gear if they'd been renamed or deleted. Sample data is
  now only added to a brand new install.
- **Fixed**: the top navigation overlapped the logo on narrower screens. It now scrolls instead.
- **Docs**: rewrote the README to cover all current features, webhooks and development.

## Round 5 (2026-11-05)

Apply with `docker compose down && docker compose up -d --build`; migration 0009 runs on start.
Run the tests with `docker compose run --rm --no-deps -e DATA_DIR=/tmp/testdata --entrypoint python web manage.py test aquarium`.

- **Species library**: 241 species, now in `aquarium/species_catalog.csv` so it can be edited in a spreadsheet (save as CSV UTF-8).
  New columns for minimum tank, adult size and temperament. Starting the app adds new rows and fills empty fields, but never
  overwrites your edits. To push edited CSV values over existing entries: `python manage.py seed_reef_data --update-species`.
  Care details are hobby rules of thumb written from general knowledge, not checked against a reference.
- **Background worker** (`python manage.py run_worker`): started by `entrypoint.sh` beside gunicorn. Runs alerts, webhooks, timers,
  time-lapse and automatic backups. Its status is shown on the Tools and Phone Alerts pages.
- **Webhooks and phone alerts** (Tools > Phone Alerts & Webhooks): JSON webhooks (optionally HMAC signed) and ntfy phone alerts for
  chosen events. Conditions notify once when they first happen. Failed sends retry up to 5 times, except automated schedule events,
  which are sent once and never late, so a retry can't double-feed.
- **System Planner** (Planner tab): plan a new system or stocking for an existing tank, with stocking, flow, heating, power and budget
  checks. "Start tracking this system" creates the real tank, sump, equipment and livestock. It can be repeated without duplicates.
- **Compatibility warnings**: in the planner, and when adding from the species catalog.
- **Fill timers and RO calculator** (Tools > Fill Timers): enter RO specs to estimate fill time and waste water, then start a timer that
  beeps on the page and can alert your phone. It only reminds you and cannot shut off water.
- **Backups** (Tools > Backups): one-click zip of the database and photos, automatic weekly backups, and restore (which saves your
  current data first). Stored in `data/backups`.
- **Quarantine tracker**: day counter, medication and observation log, and an alert when the period ends.
- **Growth timeline**: dated photos per animal with a before and after slider.
- **Webcam time-lapse**: scheduled frames from a snapshot URL or MJPEG stream, played back in the browser.
- **Power cost**: estimated kWh and cost from equipment wattage. Set your electricity price in Tools > Settings.
- `docker-compose.yml`: passes an optional `API_SECRET_KEY` from a `.env` file.
- **Calculator volumes**: the Dose Estimator, Salt Mixing Calculator and Fill Timer calculator all share a tank system picker (whole
  system, display only, sump only or a custom volume, in gallons or liters). Typing a volume switches to custom. In the Dose Estimator,
  changing the tank no longer resets your other entries, and changing the parameter keeps your volume.
- **Webhook targeting**: a connection can be limited to specific routines or to fill timers for specific reservoirs, and a timer can
  choose its connections when it starts. A targeted connection with no event types ticked receives only events about its targets.
  If its last target is deleted, the connection pauses rather than widening to everything. Migration 0011 runs on start.
- **Wishlist** (Planner > Wishlist): save animals and gear with a priority, price and link. Each animal is checked against your tank.
  Move an item into a plan, or mark it bought to add it to tracking. Species catalog cards have a one-tap Wishlist button.
  Migration 0010 runs on start.

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
