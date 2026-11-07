# Nudibranch: change summary

## Round 13 (2026-11-07)

Apply with `docker compose up -d --build`; migrations 0027 and 0028 run on start.

- **Shorter log history**: the Water page shows the last 10 readings, and Load more adds 25 at a time.
- **PAR estimate on Tools**: lighting and PAR moved from the tank page to Tools, with a link left on each tank. Opening it from a tank or a light shows that tank.
- **Tank menu in the phone top bar**: on phones, the tank picker sits beside the logo instead of on its own row.
- **Reorder tanks**: up and down buttons on the Tanks page. The order is also used in the Tank menu. Existing tanks keep the order they had: primary first, then by name.
- **Sumps near the top**: a tank's sumps now come right after its volume and dimensions.
- **Chambers edited under Edit sump**: splitting a sump into chambers, and changing them, is on the Edit sump page only. The tank page just shows them.
- **Log Water Change units**: tap gal/L and SG/ppt beside the amount and salinity. It's still stored as gallons and SG, using the calculator's 35 ppt = 1.026 SG.
- **Water change from the dashboard**: a Water Change button beside Quick Add Test. The amount can be gal, L or % of the tank's total water, and the tank defaults to the selected one but can be changed in the popup.
- **Countdown timer on the dashboard**: a compact card. Tap a preset (1, 2, 3, 5, 10, 30 min or 1 hr) or nudge it with − and +, then press Start. It runs on the server, so it survives a reload and sends a phone alert when it ends. +1 min and Stop while it runs.
- **Saved timers**: **Add a timer** on the dashboard saves one with its name and time, like "Feeding, 3 min", as its own card with a Start button. The timer cards are the same size as the water test cards. Migration 0028 runs on start.
- **App icon follows the main tank**: the browser tab and the installed app use the primary tank's icon.
- **Quick Add Test picks the tank**: the popup has a tank menu, starting on the selected tank.
- **No more out-of-date pages**: when a phone can't reach the server, it now says so with a Try again button, instead of quietly showing a saved copy of a page that could be days old.
- **Water change popup fields match**: the tank, salt brand, notes and date fields now look like the amount and salinity boxes, and the date fits on phones.
- **Total water everywhere**: tank menus, the Tanks list and the top of each tank's page show the total water (display, sumps and plumbing). The display tank's own size stays in the tank page's breakdown.
- **Even shares fixed**: the chamber share boxes accept one decimal place, so Even shares (33.3%) no longer trips the browser's check.
- **Salt brand from the list**: the salt brand is picked from the salt calculator's brands, starting on the one you used last.

## Round 12 (2026-11-07)

Apply with `docker compose up -d --build`; migration 0026 runs on start.

- **Calculators on Tools**: the salt calculator and Dose Estimator now sit together on the Tools page. Routines and Dosing link to them.
- **"Water" instead of "Parameters"**: the navigation says Water, and the page is Water Quality.
- **Coral groups**: new SPS Corals, LPS Corals, Soft Corals and Anemones groups. The species catalog sorts its corals into them using the usual hobby labels, and a coral added from the catalog also stays in "Corals", so that filter still shows every coral. Animals already added from the catalog are added to their new group.
- **Tap the unit to switch it**: in the salt calculator, Dose Estimator and fill timer, the unit sits inside each field (gal, L, SG, ppt) and is itself the button.
- **One answer per calculator**: the salt calculator shows one amount, switchable between g, oz, lb and cups. The Dose Estimator shows one dose, switchable between g, oz, ml, tsp and fl oz depending on what it can work out, with the total, days and daily top-up in a sentence below. Each remembers the unit you last picked.
- **No repeated tank box**: the calculators no longer show the tank name in a box of its own. Which volume to use is a small menu on the volume field's label.
- **More compact pages**: Tools shows two tiles a row on phones; livestock without a photo get a slim "Add photo" strip; equipment service info is one line; dosing containers, the tank profile, PAR by depth, water test rows and the mute controls take less room; the Reef2Reef links on the alerts page fold away until opened.

## Round 11 (2026-11-06)

Apply with `docker compose up -d --build`. There's no database change.

- **Units beside each field**: the salt calculator's units now sit next to the volume, target and starting salinity, and each salinity can use its own unit. The Dose Estimator's label amount can be in gallons or liters.
- **More dosing options**: the Dose Estimator adds nitrate, phosphate, potassium, iodine and strontium, using the amounts on the product's own label.
- **Label dose fixed**: the Dose Estimator's product label mode scaled the wrong way with tank size, giving too much on a tank smaller than the label's volume and too little on a bigger one. Please re-check any dose worked out with it before this fix.

## Round 10 (2026-11-06)

Apply with `docker compose up -d --build`; migration 0025 runs on start.

- **Quarantine ends by itself**: when the planned days are up, you get a notification, the animal is marked healthy and the quarantine ends.
- **Mute notifications**: for a set time or until you turn them back on. Feeder schedules and timers keep working, and anything still wrong is sent when the mute ends.
- **Step timers**: a routine's checklist step can have a timer, like `[5 min]`, started from the step. A new `routine.step_finished` event fires when it ends, and a step can name the connection it triggers, like `[5 min @Feeder]`.
- **Light power and PAR**: lights get a power slider, and the tank page gives a rough PAR estimate at three depths.
- **Log history**: Load more walks back through every reading, rather than stopping at 50.
- **Works without internet**: Tailwind, htmx and Chart.js are now served from the app.
- **Phones**: pinch zoom is allowed, and the page tabs show the main ones plus More.
- **Photos**: animal photos are saved as JPEGs up to 1600 pixels. `compress_photos` shrinks older ones.
- **Wording**: "system" is now "tank" throughout, apart from RO/DI systems.

## Round 9 (2026-11-06)

A full review of the code. Apply with `docker compose up -d --build`. There's no database change, but the image is rebuilt with Django 5.2.

- **Settings kept on restart**: changed decimal places were being put back on every start, and deleted parameters and groups came back. They no longer do.
- **API closed without a key**: with no `API_SECRET_KEY` set, anyone who could reach the logging API could post readings. It now refuses them.
- **Crashes fixed**: `NaN` or `Infinity` typed as a reading or refill level, an RO/DI system with zero output in the fill calculator, a bad species link, and odd characters in API names.
- **Uploads and page safety**: the quick photo button now checks it's really an image, text like `</script>` in a name can't break a page, and camera addresses must be web addresses.
- **Calculators**: a target of fresh water no longer gives a full dose of salt, an impossible target shows a dash rather than the last answer, and impossible numbers get an error.
- **Tanks**: deleting the primary tank promotes another, a retired tank can't be primary, and tank cards count only living animals.
- **Quarantine**: finishing resets the day count for next time, and retired systems are left out of the list.
- **Alerts**: probes that stop reporting now show on the Alerts page and badge, where they'd been sent only as notifications. Alert code failures are logged, not hidden.
- **Speed**: typical pages run about 35 database queries instead of about 100. The worker clears old records every 30 minutes rather than every 20 seconds, and the quick log pop-up loads its data only when opened.
- **Storage**: replaced or deleted photos and icons are removed from disk, phones no longer keep copies of every photo and backup, and an automatic backup can't delete itself.
- **Forms**: negative reservoir levels and water changes are refused, and forms sharing a page no longer share field ids.
- **Top bar**: the REEF badge is gone, which also stops pages scrolling sideways on phones. The app is now called Nudibranch Reef Manager.
- **Upkeep**: moved to Django 5.2 LTS, removed unused packages and code, and `TIME_ZONE` can now be set in `.env`.

## Round 8 (2026-11-06)

Apply with `docker compose up -d --build`; migrations 0022 to 0024 run on start.

- **Substrate and live rock**: a tank can record its substrate type and amount, link a substrate product from your equipment, and record its
  live rock. Weights can be in lb or kg, and the tank page shows both. There's a new Substrate equipment type with no service reminders.
- **Calculators easier to find**: tabs and Tools cards open the salt calculator and Dose Estimator directly, and the page tabs now wrap on phones instead of running off-screen.
  The salt calculator also takes a starting salinity, default 0, and only counts the salt still needed.
- **Icon and colours from each tank**: the tank page and its edit page open that tank's look, and the Tanks list shows each tank's icon.
- **Bottom navigation**: the System button is now Tanks, with a tank icon in place of the gear.
- **The Damage**: an option to count retired systems, which are now left out of All systems unless you tick it. A currency choice sets the symbol
  everywhere prices appear, without converting amounts. A confession can be tied to a piece of equipment, which sets what you paid on it, and more sins to suggest.
- **Demo readings**: `python manage.py seed_demo_readings` adds 90 days of made-up water tests for trying out the charts and alerts, and `--remove` takes them out.
- **Alert history**: the Alerts page now has a Resolved section and metrics, with filters for severity and status. Choose how many days to keep them under Tools > Settings: 7 by default, up to 30.
- **Estimate disclaimers**: the salt calculator and Dose Estimator now say their results are estimates to confirm independently.
- **Random icons are off by default**: a system with no chosen icon keeps a lasting one. Turn **Enable random icons** on under Tools > Settings to bring them back.
- **Removed the palette button** beside the system menu. Use **Icon & colours** on a tank's page, or **System Look** under Tools.

## Round 7 (2026-11-06)

Security update. Copy `.env.example` to `.env` and fill it in before running `docker compose up -d --build`.

- **Sign-in required**: every page, photo and backup now needs an account, and the first visit creates one if none exist.
  Devices logging readings use `API_SECRET_KEY` instead. Reset a password with `docker compose exec web python manage.py changepassword NAME`.
- **Secrets moved to `.env`**, which Git and Docker image builds ignore. The app refuses to start in production without `DJANGO_SECRET_KEY`.
- **Port 8000 only listens on this computer by default**, for use with Tailscale Serve. Set `BIND_ADDRESS=0.0.0.0` in `.env` to allow your local network.

## Round 6 (2026-11-05)

Apply with `docker compose up -d --build`; migrations 0012 to 0021 run on start and assign your existing water tests to your primary tank.

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
  only reach the ledger when an item moves into an active tank. Putting the fire out hides spending but erases nothing, and the page says so. The ledger can be filtered by system and dates.
- **Fixed**: restarting the app recreated "Main Display Tank" and its sample gear if they'd been renamed or deleted. Sample data is
  now only added to a brand new install.
- **Fixed**: the top navigation overlapped the logo on narrower screens. It now scrolls instead.
- **Docs**: rewrote the README to cover all current features, webhooks and development, with screenshots in `docs/screenshots`.

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
