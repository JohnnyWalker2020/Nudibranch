# 🪸 Nudibranch: Reef Manager

A self-hosted, mobile-friendly app for saltwater aquarium keepers. Track water chemistry, livestock, equipment and maintenance for one tank or several, plan your next tank, and get alerts on your phone.

Built with **Python**, **Django 5**, **SQLite**, **Tailwind CSS**, **HTMX** and **Chart.js**, and installable on your phone as a **Progressive Web App**.

> **Keep it private.** Everything requires a sign-in, but this app isn't hardened for the public internet. Use [Tailscale](#-reaching-it-from-your-phone) to reach it from anywhere: it keeps the app private to your own devices. Just don't turn on Tailscale **Funnel**, which would put it on the public internet, and don't forward port 8000 on your router.

![The dashboard](docs/screenshots/dashboard.png)

---

## 📸 Screenshots

| Water quality | Compare planned tanks |
|---|---|
| ![Parameter chart with target ranges](docs/screenshots/parameters.png) | ![A project comparing three planned tanks side by side](docs/screenshots/planner-project.png) |

| Species catalog | Wishlist |
|---|---|
| ![Species catalog with care details](docs/screenshots/species-catalog.png) | ![Wishlist with tank fit checks](docs/screenshots/wishlist.png) |

| Alerts, resolved history and mute | A timer on a routine's step |
|---|---|
| ![Alerts page with a mute timer, filters and resolved alerts](docs/screenshots/alerts.png) | ![A routine checklist with a 5 minute timer on one step](docs/screenshots/routine-timers.png) |

| Lighting and PAR estimate |
|---|
| ![Light power slider with estimated PAR near the top, middle and bottom of the tank](docs/screenshots/lighting.png) |

| Colours and characters | Fill timers | On your phone |
|---|---|---|
| ![Colour schemes and character icons](docs/screenshots/system-look.png) | ![Fill timer and RO calculator](docs/screenshots/fill-timers.png) | ![Dashboard on a phone, using Match my icon](docs/screenshots/mobile-dashboard.png) |

*Screenshots use sample data.*

---

## 🚀 Getting started

You need [Docker](https://www.docker.com/products/docker-desktop/) with Docker Compose. Nudibranch comes as a ready-built image for normal PCs and 64-bit Raspberry Pi OS, so you don't need the source code. New to Docker? Use the [step by step](#-new-to-docker-step-by-step) guide below.

1. Make a folder and save [`docker-compose.yml`](https://raw.githubusercontent.com/JohnnyWalker2020/Nudibranch/main/docker-compose.yml) and [`.env.example`](https://raw.githubusercontent.com/JohnnyWalker2020/Nudibranch/main/.env.example) into it.
2. Copy `.env.example` to `.env` and fill in `DJANGO_SECRET_KEY` and `API_SECRET_KEY` with long random values.
3. Run `docker compose up -d` in that folder.
4. Open **[http://localhost:8000](http://localhost:8000)** and create your account.

Your data lives in the `data` folder. Keep a private copy of `.env` (in a password manager, say), because it isn't in the app's backups.

### 🐣 New to Docker? Step by step

Docker runs Nudibranch in a sealed box (a *container*) with everything it needs inside, so there's nothing else to install.

**1. Install Docker**

- **Windows 10 or 11:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/). Keep **WSL 2** ticked if it asks, and restart when it's done.
- **Mac:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/), choosing **Apple silicon** (M1 or newer) or **Intel** (Apple menu > About This Mac tells you which).
- **Linux:** install [Docker Engine](https://docs.docker.com/engine/install/), which includes Compose.

Open Docker Desktop and wait until it says it's running. It needs to be running whenever you use Nudibranch, so you may want to tick **Start Docker Desktop when you sign in** in its settings (⚙️ > **General**).

**2. Open a terminal**

On Windows, open the Start menu and type **Terminal**. On a Mac, press Cmd + Space and type **Terminal**. Type or paste each command below and press Enter. Check Docker is ready; both should print a version number:

```bash
docker --version
```

```bash
docker compose version
```

If you get "command not found" or "cannot connect to the Docker daemon", make sure Docker Desktop is running, then open a new terminal.

**3. Get Nudibranch**

Make a folder and go into it:

```bash
mkdir Nudibranch
```

```bash
cd Nudibranch
```

Then download the two files. On Windows (PowerShell):

```powershell
curl.exe -fsSL -o docker-compose.yml https://raw.githubusercontent.com/JohnnyWalker2020/Nudibranch/main/docker-compose.yml
```

```powershell
curl.exe -fsSL -o .env.example https://raw.githubusercontent.com/JohnnyWalker2020/Nudibranch/main/.env.example
```

On Mac or Linux:

```bash
curl -fsSL -o docker-compose.yml https://raw.githubusercontent.com/JohnnyWalker2020/Nudibranch/main/docker-compose.yml
```

```bash
curl -fsSL -o .env.example https://raw.githubusercontent.com/JohnnyWalker2020/Nudibranch/main/.env.example
```

Every command from here on runs in this folder. In a new terminal, run `cd Nudibranch` first.

**4. Make your settings file**

Copy the example to `.env`. On Windows (PowerShell):

```powershell
Copy-Item .env.example .env
```

On Mac or Linux:

```bash
cp .env.example .env
```

The app needs two long random keys. Run this twice to make them:

```bash
docker run --rm python:3.12-alpine python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Open `.env` (`notepad .env` on Windows, `open -e .env` on a Mac) and:

- paste the first key after `DJANGO_SECRET_KEY=` and the second after `API_SECRET_KEY=`, with no spaces or quotes
- remove the `#` before `TIME_ZONE` and set yours, such as `TIME_ZONE=America/New_York` ([list of time zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones), "TZ identifier" column)

Save and close it. (On a Mac, the Finder hides files starting with a dot; Cmd + Shift + . shows them.)

**5. Start it**

```bash
docker compose up -d
```

The first start takes a few minutes while the app downloads. After that it starts in seconds, keeps running after you close the terminal, and starts again by itself whenever Docker is running.

**6. Open it**

Go to **[http://localhost:8000](http://localhost:8000)** and create your account. For your phone, see [Reaching it from your phone](#-reaching-it-from-your-phone).

**Everyday commands**

| To... | Run |
|---|---|
| See if it's running | `docker compose ps` |
| See what it's doing (Ctrl + C stops watching) | `docker compose logs -f web` |
| Stop it | `docker compose down` |
| Start it again | `docker compose up -d` |
| Update it | `docker compose pull`, then `docker compose up -d` |

**Updating:** take a backup first (**Tools > Backups**). Database changes apply on startup. To stay on one version, or go back after a bad update, set `NUDIBRANCH_VERSION` in `.env` (such as `1.0.0`) and run `docker compose up -d`; restore your backup if the update changed the database. Releases are listed on GitHub.

Your tanks, tests and photos are in the `data` folder. Stopping, updating and restarting don't touch it, but never delete it.

**If something goes wrong**

- **"Copy .env.example to .env and set DJANGO_SECRET_KEY":** `.env` is missing or the key is empty. Go back to step 4.
- **"'compose' is not a docker command":** your Docker is older and doesn't have Compose built in. Install the [Compose plugin](https://docs.docker.com/compose/install/linux/), or type `docker-compose` (with a hyphen) instead of `docker compose` in every command.
- **"port is already allocated":** another program is using port 8000. Close it or restart your computer.
- **"manifest unknown" or "pull access denied":** `NUDIBRANCH_VERSION` names a version that doesn't exist. Fix it, or leave it blank for the newest.
- **The page won't load:** give it a minute, then check `docker compose ps`. `docker compose logs web` shows any error.
- **A form is rejected (CSRF):** the address in your browser isn't in `CSRF_TRUSTED_ORIGINS` in `.env`. Add it and run `docker compose up -d`.

### Accounts

Every page, photo and backup needs a sign-in. You stay signed in for 30 days on each device, and **Sign out** is on the **Tools** page.

Forgot your password? Reset it from your Nudibranch folder, replacing `YOUR-USERNAME`:

```bash
docker compose exec web python manage.py changepassword YOUR-USERNAME
```

### Settings

Set these in your `.env` file.

| Setting | What it does |
|---|---|
| `DJANGO_SECRET_KEY` | Required. The app won't start without it. |
| `API_SECRET_KEY` | The key devices must send to log readings. Without one, the logging API stays closed. |
| `CSRF_TRUSTED_ORIGINS` | The addresses you open the app from. Without yours, forms are rejected. |
| `BIND_ADDRESS` | `127.0.0.1` (the default) allows only this computer. `0.0.0.0` allows your whole local network. |
| `TIME_ZONE` | Used for schedules and log times, such as `Europe/London`. The default is `America/Regina`, so set yours. |
| `NUDIBRANCH_VERSION` | Stay on one release, such as `1.0.0`. Blank means the newest. |

### 📱 Reaching it from your phone

Out of the box, Nudibranch only answers on the computer it runs on. There are two ways to open it up, and you can use both:

- **At home, on the same Wi-Fi:** a quick settings change.
- **Anywhere:** [Tailscale](#away-from-home-tailscale). It's also the only way to install Nudibranch on your phone as an app, because that needs HTTPS.

#### At home: your local network

1. Find the computer's address: on Windows run `ipconfig` and look for **IPv4 Address** (such as `192.168.1.50`); on a Mac, see System Settings > Wi-Fi > **Details** > **IP address**.
2. In `.env`, change `BIND_ADDRESS` to `0.0.0.0` and add the address to the end of `CSRF_TRUSTED_ORIGINS`:

   ```
   CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://192.168.1.50:8000
   ```

3. Run `docker compose up -d`.
4. On your phone, on the same Wi-Fi, open `http://192.168.1.50:8000` (your own address).

- **Won't load?** Windows may ask whether to allow Docker through the firewall; allow it on **private** networks. Check your phone isn't on mobile data or a guest network.
- **Address changed?** Routers sometimes hand out new addresses. Most can reserve one for a computer (a *DHCP reservation*).
- **Who can reach it:** anything on your network can now reach the sign-in page. Everything still needs your password, but if you'd rather not, use Tailscale only and keep `BIND_ADDRESS=127.0.0.1`.

#### Away from home: Tailscale

Use [Tailscale](https://tailscale.com) rather than opening a port on your router. It's free for personal use, and its Serve feature gives you a private HTTPS address only your own devices can reach. Install it on both devices, turn on **HTTPS** in the Tailscale admin console, and leave **Funnel** off. Then, on the computer running Nudibranch:

```bash
tailscale serve --bg 8000
```

Add the `https://` address it shows to `CSRF_TRUSTED_ORIGINS` in `.env` and run `docker compose up -d`.

- **Install it as an app:** open that address on your phone and use the browser's install or add to home screen option.
- **Keep Tailscale on:** with the default `BIND_ADDRESS`, your phone needs Tailscale even at home (unless you've also set up the home network way). If Tailscale is off, the app shows **Can't reach Nudibranch** with a **Try again** button.
- **App icon:** it's your main tank's icon. On an iPhone, an icon already on the home screen keeps its old picture until you remove it and add it again.
- **Webcams:** cameras on your local network won't load away from home unless Tailscale can reach them too.

---

## ✨ Features

### Dashboard and getting around
- **On a phone,** the bar at the bottom has Home, Water, Livestock, Tanks and Tools. Calculators, timers, webcams, phone alerts and backups are under Tools.
- **Water quality rating:** a 0–100 score and grade on the dashboard and Water page, from your latest test of each parameter in the last 30 days against that tank's targets (core parameters count double). It lists what's pulling it down and what hasn't been tested lately. A confidence level (High, Medium or Low) sits under the grade: tests up to 7 days old count fully, then count less until 30 days, and it names the oldest tests to redo. Old tests lower the confidence, not the score. It summarises your own tests; it isn't a lab result.
- **The dashboard** shows your alerts, timers, a card for each water test, charts, reservoir levels and more. **Quick Add Test** and **Water Change** at the top log either in a couple of taps.
- **Trend arrows:** each water test card shows the change since the test before. Green means it moved toward the ideal range, amber away from it, and grey that it held steady or moved within the range.
- **Customize** picks which sections show and their order, and under **Water test cards**, which parameters get a card.

### Multiple tanks
Pick a tank from the **Tank** menu at the top of any page (beside the logo on a phone). The dashboard, water tests, charts, livestock, equipment, dosing, routines, webcams, alerts and calculators then show just that tank. Your choice is remembered per device, and the menu flags other tanks that have alerts.

- **Sizes shown:** wherever a tank is named, its size is the total water: display, sumps and plumbing. The tank's own page still breaks it down.
- **Order:** the ↑ and ↓ buttons on the **Tanks** page set the order of the tanks there and in the Tank menu.
- **Shared across tanks:** the wishlist, plans, species catalog, parameter names and units, webhooks, backups and the quarantine list.
- **All tanks views:** Equipment and Power can show every tank at once.
- **Tank look:** use **Icon & colours** on a tank's page to give each tank its own colour scheme and icon, from 26 nudibranch characters or your own image. **Match my icon** builds the colour scheme from the icon itself. **Style** switches the tank between **Standard** and **8-bit**: stepped corners (square in browsers that cannot cut them), chunky borders with hard shadows, flat colours and blocky lettering for headings and numbers. Charts keep their smooth lines. Normal text stays easy to read.
- **Retiring a tank:** the **Retire** button on a tank's page keeps all its data but stops its alerts, schedules, time-lapse and new tests. You can bring it back at any time.
- **Icon settings:** under **⚙️ Settings** (the gear at the top of every page), **Enable random icons** gives tanks with no chosen icon a different character on every page. There are a couple of other icon options there too.

### Water quality
- Log tests by hand or through the [API](#-parameter-logging-rest-api), with charts and optimal and alert ranges. The **Water** page shows your last 10 readings, and **Load more** walks back through the rest.
- **Quick Add Test** logs a test for the selected tank, or pick another tank in its menu.
- **Test reminders:** on a parameter's settings page, set **Remind me to test every N days**. When a test is overdue, **Time to test** shows on the Alerts page and the dashboard, and can notify your phone. (A probe check in hours, under **Phone Alerts**, works the same way.)
- **ICP elements:** an ICP test is a lab test of a mailed-in water sample that reports 30 or more elements at once. Turn on **Enable ICP elements** under **⚙️ Settings** to add 29 of them, such as boron, iodine, strontium, copper and tin. Until then they don't appear anywhere, unless you add a few on their own: **+ Add a test** on the Water page lists them under **From an ICP test** to tick, with units and target ranges built in. **Take off my list** on an element's settings page hides it again and keeps its tests. Once on, they're listed after your regular tests, chart from the **ICP** menu beside the parameter buttons rather than on the All chart, and get a dashboard card only if you tick it under **Customize > Water test cards** or on the element's settings page. Their ranges are rough, mostly natural seawater levels, and labs set their own, so adjust them to match your lab's report.
- **Export CSV** on the Water page downloads every test for the selected tank as a spreadsheet file. Add `?tank=all` to the address for every tank. Water changes and doses have their own Export CSV links.
- Each tank can have its own target ranges, or use the shared defaults.
- Change units and decimals, with automatic conversion of past readings.
- Want to see the charts and alerts in action first? Add 90 days of made-up tests with `docker compose exec web python manage.py seed_demo_readings`, and take them out again by adding `--remove`. Your own readings are left alone. Limit it to one tank with `--tank NAME`.

### Livestock and species catalog
- Track animals with photos, categories, health status and notes. Photos are saved as JPEGs up to 1600 pixels on the longest side to keep them small, and the originals aren't kept. To shrink photos from before this, run `docker compose exec web python manage.py compress_photos`.
- Browse **240+ built-in species** with care level, diet, reef safety, minimum tank size, adult size and temperament. Add one with a single tap.
- **Categories** work like tags, and an animal can be in several. Corals from the catalog go into **SPS Corals**, **LPS Corals** or **Soft Corals** (using the usual hobby labels) and also stay in **Corals**. Anemones get their own **Anemones** category.
- **Edit categories** (top of the Livestock page) manages them all on one page: rename, change the icon, colour and description, reorder with ↑ and ↓, **Merge into** another category (its animals move over and it goes away), or delete one (its animals are kept). The colour shows as a stripe on the category filters and badges.
- **Names:** give an animal a name of its own on its form, or tap **🎲 Silly name** there or **Give it a silly name** on its card. The name is kept once saved.
- **Banned to the sump:** tick it on the animal's form to put a ⛓️ tag on its card.
- **Deceased:** an animal marked deceased leaves the list. A small link at the bottom of the page shows them, so you can fix a mistake.
- See **compatibility warnings** when an animal may be too big for the tank, may fight, isn't reef safe, or would push the fish load too high.
- **Quarantine tracker:** day counter and medication and observation log. When the planned days are up, you get a notification and the quarantine ends, marking the animal healthy.
- **Growth timeline:** dated photos of each animal with a before and after slider.

The catalog lives in `aquarium/species_catalog.csv`, which you can edit in a spreadsheet (save as CSV UTF-8). Starting the app adds new rows and fills empty fields, but never overwrites your edits. To apply edited values to existing species, run `docker compose exec web python manage.py seed_reef_data --update-species`. Care details are hobby rules of thumb, not checked against a reference, so please verify them before buying.

### Planning
- **Tank Planner:** design a new tank or plan stocking for an existing tank, with checks for stocking, flow, heating and power. **Start tracking this tank** then creates the real tank, sump, equipment and livestock. Equipment you add shows the fields for its type: a light gets hours on a day and a **Running at** slider, which feed the power cost and a rough PAR estimate under **Checks**.
- **Projects:** group several planned tanks to compare them side by side and see combined cost, water and power. Copy a plan to try a variation. Nothing becomes real until you track that one plan.
- **Wishlist:** save animals and gear with a priority, price, link and notes. Each animal is checked against your tank, and you can move items into a plan or mark them bought.

### Equipment, dosing and maintenance
- **Tank profile:** dimensions, sumps and plumbing, plus substrate type and amount, its linked product, and live rock, in lb or kg. Split a sump into chambers under **Edit sump**. **Start from a common tank** on the Add and Edit tank forms fills in the size of a standard glass tank (20 gallon long, 40 gallon breeder and so on) or a Waterbox or Red Sea Reefer display. The sizes are approximate, so check them against your tank.
- **Tank page:** Flow & Water Turnover lists **Return pumps** and **Wavemakers & powerheads** in their own groups. Each section (sumps and chambers, Flow & Water Turnover, Lighting, Filters, and the display) has its own add menu. Add new equipment, or pick something not in a tank yet, or move something from elsewhere. ✕ takes an item off the tank and keeps it in your equipment list, and 🗑 deletes it after a confirmation. **Lighting** shows each light with the automated routines that switch it on and off. **Filters** lists socks, roller mats, sponges, canisters and media reactors with a **✓ Changed** button.
- **Equipment:** **Start from a known model** fills in specs for popular pumps, wavemakers, lights and heaters. Lights, skimmers, pumps and similar gear can have a **Daily schedule**, shown on their cards. Service intervals, placement in the display or sump, and pump flow and turnover estimates. 🗑 deletes an item wherever it's listed (Equipment, tank page, Routines, Power, PAR estimate), always after a confirmation.
- **Flow sketch:** place each return pump and wavemaker outlet on two little pictures when you edit it: from above (tap where it is, slide to set which way it points) and from the front (tap how high it sits, slide to tilt it up or down) and where each sump's overflow is (type and position). The Flow section then draws the display from above, shaped like your tank, with numbered outlets, arrows for their aim, and the overflow.
- **Import and export:** **⬇ Export** on a tank's page downloads its setup as a YAML tank file: the tank, sumps and chambers, plumbing, equipment and where it sits, living animals and their categories, target ranges, routines, and dosing and ATO containers. Water tests, logs and photos stay out (use backups or the CSV downloads for those), and so do prices unless you pick **with prices**. **⬆ Import a tank** on the Tanks page shows what a file will add before anything is saved, and always makes a new tank. Categories you already have are reused.
- **Head height:** set a sump's head height (Edit sump, in ft or m), and a return pump's **Max head** from its box. A return pump sitting in that sump then gets its flow from a straight-line pump curve at its power setting, which feeds the turnover. Without a max head, the head loss % still applies. It's an estimate: real pump curves bow a little, and pipe and elbows add to the lift.
- **Dosing and top-off:** reservoir levels and run-out forecasts. A container with a daily use (the doser's daily amount, or the ATO's daily top-off) counts down by itself from the last time you set its level, so its level is an estimate, marked with ~. **Refill to full** or **Edit** restarts it from what's really there, so correct it now and then, especially an ATO, since evaporation changes with temperature and humidity. With a daily use of 0 it only changes when you log a dose or edit it. Doses you log come off on top of the daily use, so only log extra doses, not the doser's own.
- **Dose log:** record what you add with **Log a dose** on the Dosing page, or **Log this dose** under the Dose Estimator's answer, which fills it in. Pick the container it came from, and a liquid dose (ml, tsp or fl oz) comes off its level. Deleting the dose puts it back.
- **Calculators:** the Salt Mixing Calculator, Salinity Fixer, Dose Estimator and PAR estimate are together on the **Tools** page. They use the selected tank's volume, or a custom one. Tap a unit (gal, L, SG, ppt, g, oz and so on) to switch it, and each answer appears once, in the unit you pick. The salt calculator can start from water that already has salt in it, and the Dose Estimator starts from your latest test. It works out dry chemicals or a product's label for alkalinity, calcium and magnesium, and uses the product's label for nitrate, phosphate, potassium, iodine and strontium. Results are estimates, so confirm them independently before using them.
- **Salinity Fixer:** on **Tools**, enter the water you have, its salinity, the salinity you want and how much new water you'll add. It works out how salty the new water needs to be (as a top up, or a water change that takes water out first) and the salt for that batch, starting from your latest reading and target range. If the change is more than your daily limit it lays out a gentler plan over several days, and it says so if even plain RO/DI can't get there. Switch to **Dilute with RO/DI** to bring salinity down instead: enter the water you have, its salinity and the salinity you want, and it works out how much 0 ppt RO/DI to add (or swap in), with the same gentler plan. It's a mixing estimate, so check the batch with a calibrated refractometer or salinity meter.
- **Water changes:** log one from the dashboard's **Water Change** button or the Routines page. Enter the amount in gallons, liters or a % of the tank's total water, the salinity in SG or ppt, and pick the salt from the calculator's list.
- **Routines:** manual checklists and automated schedules with flexible repeats, plus water change history.
- **Step timers:** give a checklist step a timer by ending it with the time in brackets, such as `Wait for the colour to develop [5 min]`. A button on the step starts the countdown, and it beeps when it's done. To also trigger one of your connections when it finishes, name it: `[5 min @Feeder]`.
- **Lighting and PAR:** set each light's power with a slider, and the PAR estimate on **Tools** gives a rough figure near the top, in the middle and at the bottom of the tank. It averages across the tank from wattage and dimensions, and can easily be off by half, so confirm with a PAR meter before placing sensitive corals.
- **Power cost:** estimated electricity use and cost from equipment wattage. Set your price under **⚙️ Settings**.

### Alerts
- The **Alerts** page lists active problems, including overdue test reminders and probes that have stopped reporting, plus a **Resolved** section and metrics such as average time to resolve. Filter by severity and status.
- **Mute notifications** for a set time, or until you turn them back on. Phone alerts and alert webhooks pause, while alerts still show on the site, and feeder schedules and timers keep working. Anything still wrong when the mute ends is sent then.
- Resolved alerts are kept for 7 days. Change that, up to 30, under **⚙️ Settings**. The history starts when you install this version.

### Timers
- **On the dashboard:** a countdown card where you tap a preset (1, 2, 3, 5, 10 or 30 minutes, or an hour) or nudge it with − and +, then press **Start**. Next to it, **Add a timer** saves ones you use often, like "Feeding, 3 min", each as its own card with a Start button. Change or delete one with its **Edit** link.
- **Fill timers:** enter your RO/DI specs to estimate fill time and waste water, then start a timer.
- Every timer runs on the server, so it keeps going if you close or reload the page, beeps when it ends, and can alert your phone.

> A timer only reminds you. **It can't shut off water**, so use a float valve or a timed shut-off on anything that could overflow.

### Phone alerts and webhooks
Under **Tools > Phone Alerts & Webhooks**, send events to your phone through [ntfy](https://ntfy.sh), or to Home Assistant or your own devices. See [Webhooks](#-webhooks).

### Backups
Under **Tools > Backups**, make a zip of your database and photos, download it, or restore one. Your current data is saved first when you restore. Automatic backups run weekly by default.

Backups are stored in `data/backups` on the same drive as your data, so copy one somewhere else now and then. They don't include your `.env` file.

### Webcams
Add MJPEG, snapshot or embedded camera feeds (under **Tools** on a phone), and assign each to a tank or show it on all of them. **Time-lapse** captures frames on a schedule and plays them back in the browser. RTSP cameras need a converter such as [go2rtc](https://github.com/AlexxIT/go2rtc), and an example is commented out in `docker-compose.yml`. A camera mounted sideways or upside down can be turned with **↻ Rotate** under its picture (a quarter turn each tap) or on its edit page; the live view, the dashboard and the time-lapse all follow. Only the picture in the app turns: the camera itself is left alone.

> ⚠️ **Handle with care.** Some nudibranchs steal stinging cells from the prey they eat and use them for defence. This one is no different: touch it three times and it stings. Mostly your wallet.

<details>
<summary>🤫 Spoiler: where it stings</summary>

<br>

Touch the nudibranch (the app icon) three times quickly, and it stings you with **The Damage**, a fire-themed spending ledger. It's off until you **Light the match** inside it. After that:

- Livestock and equipment get a "what you paid" field, which lands in the ledger automatically and stays in sync with it. A purchase logged in the ledger can also be tied to a piece of equipment, which sets that field.
- Choose your currency in the ledger or under **⚙️ Settings**. It only changes the symbol, and amounts aren't converted.
- **All tanks** leaves out retired tanks unless you tick **Include retired tanks**.
- Planner and Wishlist prices are always visible, and only reach the ledger when an item moves into an active tank.
- Filter by tank and dates.
- **Put out the fire** to hide your spending again. Your values aren't erased.
- **The Graveyard** sits at the bottom, fire or no fire: a tombstone for each animal marked deceased, with its name, last words and a tiny copy of its photo. **🎲 Recarve** picks new last words, and **Edit** changes them or brings it back.

</details>

---

## 🔗 Webhooks

A connection receives events as they happen, from a background worker that starts with the app.

| Event | When it fires |
|---|---|
| `parameter.critical` | A reading reaches a critical limit |
| `parameter.out_of_range` | A reading leaves the optimal range |
| `parameter.stale` | A test reminder is overdue, or a probe stops reporting (set per parameter) |
| `reservoir.low` | A reservoir is running low |
| `routine.due` | A manual routine comes due |
| `routine.scheduled` | An automated schedule event's time arrives, such as a feeder |
| `routine.step_finished` | A timer on a routine's step finishes |
| `equipment.service_due` | Equipment needs service |
| `animal.attention` | An animal is flagged sick or in quarantine |
| `quarantine.complete` | A quarantine's planned days are up, and it ends automatically |
| `timer.finished` | A fill timer ends |

Example JSON payload:

```json
{
  "id": "unique-id-use-this-to-ignore-repeats",
  "type": "routine.scheduled",
  "severity": "info",
  "title": "Feeder: Feed",
  "message": "Scheduled for 08:00.",
  "occurred_at": "2026-11-05T14:00:00+00:00",
  "data": {"routine": "Feeder", "routine_id": 3, "action": "Feed", "scheduled_for": "2026-11-05T08:00:00-06:00"}
}
```

Requests include `X-Nudibranch-Event` and `X-Nudibranch-Delivery` headers, plus `X-Nudibranch-Signature: sha256=...` (HMAC-SHA256 of the body) when you set a secret. Parameter events also include `tank` and `tank_id` in `data`, and timer events include `timer_id` and `reservoir_id`.

**How sending works:**
- Most events notify once, when the condition first happens, and each send is tried up to 5 times.
- Retired tanks don't send events, except a fill timer that's already running.
- `routine.scheduled` is sent once and never retried, and a missed one is dropped after 5 minutes, so a retry can't double-feed.
- The first time the worker runs, it records existing problems without sending them.

**Using webhooks with hardware:**
- **Target one step:** name the connection in that step, as in `[5 min @Feeder]`. Only that step triggers it, unless the connection is also set to receive that routine's events.
- **Target one device:** edit the connection and tick only that routine or reservoir. With no event types ticked, it receives only events about those targets, so a feeder webhook can't fire on a parameter alert.
- **Keep the feeder's own schedule as the main one.** If this PC or Docker is off, nothing is sent.
- **Limit it on the device too:** ignore repeated event IDs, and give anything that doses or feeds its own daily limit.
- **Home Assistant:** use `http://YOUR-HA-IP:8123/api/webhook/YOUR-ID`. Names like `homeassistant.local` may not work from inside Docker.

---

## 🧪 Parameter Units & Decimal Precision

**Logging in another unit:** wherever you log a test, pick what you measured, then tap the unit in the value box to switch it (for example dKH, meq/L or ppm for alkalinity). The reading is converted to the parameter's own unit when it's saved. The same tap-to-switch button is used for every unit in the app.

You can change measurement units and customize decimal places for any parameter:
- Click the **gear icon** ⚙️ on any dashboard parameter card, or select a parameter on the **Water** page and open its settings.
- **Customizable Decimals**: Choose from `0` to `4` decimal places:
  - `0` decimals for whole-number metrics (e.g. `Calcium 420 ppm`, `Magnesium 1350 ppm`).
  - `1` decimal for tenths (e.g. `Alkalinity 8.4 dKH`, `Temperature 78.2 °F`).
  - `2` decimals for hundredths (e.g. `Phosphate 0.03 ppm`, `pH 8.25`).
  - `3` decimals for thousandths (e.g. `Salinity 1.026 SG`).
- **Automatic Historical Conversion**:
  - Checking **"Convert previous entries automatically"** recalculates all existing logs and target ranges, across every tank, using standard reef conversion formulas:
    - **Temperature**: `°F` ↔ `°C`
    - **Salinity**: `SG` (Specific Gravity) ↔ `ppt` (Parts per Thousand) ↔ `mS/cm` (Conductivity)
    - **Alkalinity**: `dKH` ↔ `meq/L` ↔ `ppm CaCO3`
    - **Phosphate**: `ppm PO4` ↔ `ppb Phosphorus P` (for Hanna HI736 Checkers)
    - **Nitrate**: `ppm` ↔ `ppb`
    - **Water level**: `in` ↔ `cm` ↔ `mm`
- **Target ranges** apply to the selected tank, and can differ per tank. Units and decimals are shared by all of them.
- **Water level** is there for depth and level sensors (ultrasonic, float or pressure), logged like any test and stored in millimeters (readings in inches or cm are converted). It starts with a wide range that flags nothing and has no dashboard card. A level can be read at any place in the system: the display, a sump, any of its chambers, or an ATO or dosing reservoir. Each place shows its newest level and the last day as a small line on the Tank system page, where you can also log one by hand, and each has its own **alert below / above** levels on its edit page (a return chamber dropping means a stuck ATO; one rising means a blocked drain). The display's own range is set on the Water page like any test. Levels read at a place stay off the Water page's charts and dashboard, so a sump at 150 mm and a display at 400 mm never share a line. Until the first level is logged, pages don't look any up.
- **Sumps inside the tank**: an all-in-one tank's back chambers are a sump set to **Inside the main tank**. Their water is already part of the tank's volume, so they move water from the display's share instead of adding to the total used for dosing; circulation turnover uses the display's share. They skip the overflow and head height questions.
- **Charts** average readings into one point a minute, so a sensor sending every few seconds still draws a clean line. Add `?every=<seconds>` to the chart APIs for another spacing (`0` for every reading).

---

## 📡 Parameter Logging REST API

You can log parameter readings programmatically via HTTP POST requests from automated test kits, Raspberry Pi/ESP32 probes, Python scripts, or Home Assistant.

**Every request needs your API key.** Devices use the `API_SECRET_KEY` from your `.env` file in place of signing in. In the examples below, replace `YOUR-API-KEY` with it.

**Reaching the app from a device:** a script on the same computer can use `http://localhost:8000`, and a device running Tailscale can use your `https://` Tailscale address. A device that can't run Tailscale, such as an ESP32, needs `BIND_ADDRESS=0.0.0.0` in `.env`, which opens port 8000 to your whole local network.

### 1. View Your Tanks
```http
GET /api/tanks/
X-API-Key: YOUR-API-KEY
```
Lists your current tanks, so a device knows which `id` or `name` to send as `"tank"`. Readings sent without one go to `primary_tank_id`. Archived tanks aren't listed because they don't take new readings.

**Example Response:**
```json
{
  "count": 2,
  "primary_tank_id": 1,
  "tanks": [
    {"id": 1, "name": "Main Display Tank", "is_primary": true, "stage": "cycled", "has_sump": true, "sump_count": 1,
     "total_gallons": 52.9, "total_liters": 200.2, "living_animals": 14, "url": "http://localhost:8000/api/tanks/1/"},
    {"id": 2, "name": "Frag Tank", "is_primary": false, "stage": "uncycled", "has_sump": false, "sump_count": 0,
     "total_gallons": 20.0, "total_liters": 75.7, "living_animals": 3, "url": "http://localhost:8000/api/tanks/2/"}
  ]
}
```

**One tank's whole system:** `GET /api/tanks/<ID or name>/` returns what the Tank system page shows:
- `water`: display, sumps, plumbing and the total used for dosing.
- `display`: its size, substrate, live rock and the equipment in it.
- `sumps`: each sump's size, overflow and head height, and its `chambers` in the order the water flows through them, with each chamber's share, volume and equipment.
- `plumbing`, `flow` (turnover, with `low`/`ok`/`high`) and `lighting`.

Notes and prices are left out. The API docs page (Settings › Advanced) shows every field, with your own first tank as the example.

---

### 2. View Available Parameter Types
```http
GET /api/parameters/types/
X-API-Key: YOUR-API-KEY
```
Add `?tank=<ID or name>` to get that tank's target ranges. ICP elements are listed only while they're switched on in Settings, but a device can log them either way.

**Example Response:**
```json
{
  "parameters": [
    {"id": 1, "name": "Salinity", "code": "salinity", "unit": "SG", "min_ideal": 1.025, "max_ideal": 1.026},
    {"id": 2, "name": "Alkalinity", "code": "alkalinity", "unit": "dKH", "min_ideal": 8.0, "max_ideal": 9.0},
    {"id": 3, "name": "Calcium", "code": "calcium", "unit": "ppm", "min_ideal": 420.0, "max_ideal": 450.0},
    {"id": 4, "name": "Magnesium", "code": "magnesium", "unit": "ppm", "min_ideal": 1300.0, "max_ideal": 1400.0},
    {"id": 5, "name": "Nitrate", "code": "nitrate", "unit": "ppm", "min_ideal": 2.0, "max_ideal": 15.0},
    {"id": 6, "name": "Phosphate", "code": "phosphate", "unit": "ppm", "min_ideal": 0.03, "max_ideal": 0.10},
    {"id": 7, "name": "Temperature", "code": "temperature", "unit": "°F", "min_ideal": 77.0, "max_ideal": 79.0},
    {"id": 8, "name": "pH", "code": "ph", "unit": "pH", "min_ideal": 8.0, "max_ideal": 8.4}
  ]
}
```

---

### 3. Log a Single Parameter
```http
POST /api/parameters/log/
Content-Type: application/json
X-API-Key: YOUR-API-KEY
```
**Payload:**
```json
{
  "parameter": "alkalinity",
  "value": 8.4,
  "notes": "Hanna checker test",
  "measured_at": "2026-11-04T22:30:00Z"
}
```
*(Note: `parameter` matches case-insensitively by code, name, or ID. `measured_at`, `unit` and `notes` are optional; the time defaults to now. A `measured_at` that can't be read is refused rather than logged at the wrong time.)*

Add `"unit"` when a reading isn't in the test's own unit, such as a probe reporting `°C` or a refractometer in `SG`. It's converted the same way as an import; a unit the app can't convert is refused for that reading. **Tools › Phone Alerts & Webhooks** shows your address, tank names and test codes under *Log tests from a device or script*.

To log to a specific tank, add `"tank"` (ID or name), on each reading or once for a whole batch. Without it, readings go to your primary tank. Retired tanks don't accept new readings.

**cURL Example:**
```bash
curl -X POST http://localhost:8000/api/parameters/log/ \
  -H "X-API-Key: YOUR-API-KEY" \
  -H "Content-Type: application/json" \
  -d '{"parameter": "alkalinity", "value": 8.4, "notes": "Automated log"}'
```

**Response (`201 Created`):**
```json
{
  "success": true,
  "count": 1,
  "logs": [
    {
      "id": 14,
      "parameter": "Alkalinity",
      "code": "alkalinity",
      "tank": "Main Display Tank",
      "value": 8.4,
      "unit": "dKH",
      "status": "optimal",
      "measured_at": "2026-11-04T22:30:00+00:00",
      "notes": "Automated log"
    }
  ]
}
```

**A water level sensor** logs the same way. It's stored in mm; send `in` or `cm` as the unit and it's converted (19.0 cm is stored as 190 mm). Say where it was read with `chamber`, `sump` or `reservoir`: an ID from `GET /api/tanks/<ID>/`, or a name only one place has (`"Sump/Return Pump"` for a chamber). The tank follows from the place. With none, it's the display's level:
```json
{"parameter": "water_level", "value": 19.0, "unit": "cm", "tank": "Main Display Tank", "notes": "Display level sensor"}
{"parameter": "water_level", "value": 152, "chamber": 3, "notes": "Return chamber sensor"}
{"parameter": "water_level", "value": 9.5, "unit": "in", "reservoir": "ATO RO/DI"}
```
`GET /api/tanks/<ID>/` shows each place's newest `level` and its `level_targets`. `GET /api/levels/chart/?chamber=3&days=1` gives one place's levels for a chart (`?sump=`, `?reservoir=`, or `?tank=` alone for the display), one averaged point a minute.

---

### 4. Log Multiple Parameters (Batch)
You can log multiple readings in a single API call:
```json
{
  "readings": [
    {"parameter": "temperature", "value": 78.4},
    {"parameter": "ph", "value": 8.22},
    {"parameter": "salinity", "value": 1.0255}
  ]
}
```

**cURL Example:**
```bash
curl -X POST http://localhost:8000/api/parameters/log/ \
  -H "X-API-Key: YOUR-API-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "readings": [
      {"parameter": "temperature", "value": 78.4},
      {"parameter": "ph", "value": 8.22}
    ]
  }'
```

---

### 5. Python Integration Example
```python
import requests

SERVER_URL = "http://localhost:8000"  # or your https:// Tailscale address
API_KEY = "YOUR-API-KEY"  # from your .env file

data = {
    "readings": [
        {"parameter": "temperature", "value": 78.1, "notes": "DS18B20 probe"},
        {"parameter": "ph", "value": 8.18, "notes": "Atlas probe"}
    ]
}

response = requests.post(f"{SERVER_URL}/api/parameters/log/", json=data, headers={"X-API-Key": API_KEY})
print(response.status_code, response.json())
```

---

### 6. Sending the API Key
Either of these headers works:
```bash
curl -H "X-API-Key: YOUR-API-KEY" ...
# or
curl -H "Authorization: Bearer YOUR-API-KEY" ...
```
*(If `API_SECRET_KEY` is empty, the logging endpoint accepts readings from anyone who can reach it, so keep it set).*

---

## 🧑‍💻 Development

To work on the code, clone the repository and copy `docker-compose.dev.yml` to `docker-compose.override.yml`. Docker Compose merges that file in automatically (and Git ignores it), so it builds the app from your folder instead of pulling the published image, and mounts the code into the container so template and Python edits show after a restart:

```bash
docker compose up -d --build
```

Run the tests against a temporary data folder, so your real data isn't touched:

```bash
docker compose run --rm --no-deps -e DATA_DIR=/tmp/testdata --entrypoint python web manage.py test aquarium
```

- `aquarium/`: the Django app. Views for the newer tools are in `views_tools.py`, sign-in is in `middleware.py`, alert history is in `alert_history.py`, CSV downloads are in `exports.py`, the main-tank app icon is in `app_icon.py`, and background jobs are in `management/commands/run_worker.py`. `request_cache.py` lets a page read the app settings once instead of many times.
- `aquarium/species_catalog.csv`: the built-in species list.
- `static/icons/nudibranch/`: character icons, two PNG files per character. To add a character, copy the naming of an existing pair and restart. Small copies are generated at startup in `thumbs/`.
- `.env.example`: the settings to copy into your private `.env`.
- `static/css/tailwind.css` and `static/vendor/`: the styling and libraries (htmx, Chart.js, and Swagger UI for the API docs page, under the Apache 2.0 licence), served from the app so it works without internet. The app doesn't need Node. If you change the classes used in a template, rebuild the CSS (below).
- `static/fonts/`: the Press Start 2P pixel font used by the 8-bit style, by The Press Start 2P Project Authors under the SIL Open Font License (its licence is beside it).
- [CHANGES.md](CHANGES.md): what changed in each round.
- `.github/workflows/docker-image.yml`: runs the tests and builds the image on GitHub (see below).

Rebuild the CSS after changing templates, or add `&& npm run vendor` to update the libraries as well:

```bash
docker run --rm -v "$PWD:/app" -v /app/node_modules -w /app node:22-alpine sh -c "npm ci && npm run css"
```

### Publishing a release

The image is built and published by GitHub Actions, not by hand. Pushing a version tag does it:

```bash
git tag v1.0.0
```

```bash
git push origin v1.0.0
```

The workflow runs the tests, then builds for normal PCs and Raspberry Pi and publishes `ghcr.io/johnnywalker2020/nudibranch` as `1.0.0`, `1.0` and `latest`. Its progress is on the repository's **Actions** tab. **Run workflow** there publishes the current main branch as `edge`, for trying something before a release. Pull requests are built and tested but not published.

The first time, the published image is private. Make it public once under your GitHub profile > **Packages** > **nudibranch** > **Package settings** > **Change visibility**, or nobody else can download it.

---

## 📜 Licence

Nudibranch is free software under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). You can use, change and share it. If you share a changed version, or run one as a website for other people, you must make your changed source code available under the same licence.

The character icons were generated with ChatGPT. The Press Start 2P font has its own licence, the SIL Open Font License, which is beside it in `static/fonts/`.

---

## ☕ Support

Nudibranch is free. If it helps your reef, you can [buy me a coffee through PayPal](https://paypal.me/DoNudibranchlikcoffe). Thank you!
