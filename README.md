# 🪸 Nudibranch: Reef Aquarium Tracker

A self-hosted, mobile-friendly app for saltwater aquarium keepers. Track water chemistry, livestock, equipment and maintenance for one tank or several, plan your next system, and get alerts on your phone.

Built with **Python**, **Django 5**, **SQLite**, **Tailwind CSS**, **HTMX** and **Chart.js**, and installable on your phone as a **Progressive Web App**.

> **Keep it on your home network.** The app has no login, so anyone who can reach it can see and change everything, including downloading backups. Don't expose port 8000 to the internet.

---

## 🚀 Getting started

You need [Docker](https://www.docker.com/products/docker-desktop/) with Docker Compose. From the project folder, run:

```bash
docker compose up -d --build
```

Then open **[http://localhost:8000](http://localhost:8000)**, or `http://YOUR-PC-IP:8000` from your phone.

Run the same command to apply updates. Database changes are applied on startup, and your data stays in the `data` folder.

### Settings

Set these in `docker-compose.yml`, or put `API_SECRET_KEY` in a `.env` file beside it.

| Setting | What it does |
|---|---|
| `TIME_ZONE` | Your time zone, used for schedules and log times. This repo's default is `America/Regina`, so change it to yours. |
| `DJANGO_SECRET_KEY` | Change this to your own long random value. |
| `CSRF_TRUSTED_ORIGINS` | Add the address you use from other devices, such as `http://192.168.1.50:8000`. Otherwise forms will be rejected from those devices. |
| `API_SECRET_KEY` | Optional key required by the parameter logging API. Without it, anyone on your network can post readings. |

---

## ✨ Features

### Multiple systems
Pick a system from the **System** menu at the top of any page. The dashboard, parameters, charts, livestock, equipment, dosing, routines, webcams, alerts and calculators then show just that system. Your choice is remembered per device, and the menu flags other systems that have alerts.

- **Shared across systems:** the wishlist, plans, species catalog, parameter names and units, webhooks, backups and the quarantine list.
- **All systems views:** Equipment and Power can show every system at once.
- **System look:** tap 🎨 to give each system its own colour scheme and icon, from 26 nudibranch characters or your own image. **Match my icon** builds the colour scheme from the icon itself.
- **Retiring a system:** the **Retire** button on a tank's page keeps all its data but stops its alerts, schedules, time-lapse and new tests, and its character ages into the old version. You can bring it back at any time. Your own uploaded icon never changes.

### Water parameters
- Log tests by hand or through the [API](#-parameter-logging-rest-api), with charts and optimal and alert ranges.
- Each system can have its own target ranges, or use the shared defaults.
- Change units and decimals, with automatic conversion of past readings.

### Livestock and species catalog
- Track animals with photos, groups, health status and notes.
- Browse **240+ built-in species** with care level, diet, reef safety, minimum tank size, adult size and temperament. Add one with a single tap.
- See **compatibility warnings** when an animal may be too big for the tank, may fight, isn't reef safe, or would push the fish load too high.
- **Quarantine tracker:** day counter, medication and observation log, and an alert when the period ends.
- **Growth timeline:** dated photos of each animal with a before and after slider.

The catalog lives in `aquarium/species_catalog.csv`, which you can edit in a spreadsheet (save as CSV UTF-8). Starting the app adds new rows and fills empty fields, but never overwrites your edits. To apply edited values to existing species, run `python manage.py seed_reef_data --update-species`. Care details are hobby rules of thumb, not checked against a reference, so please verify them before buying.

### Planning
- **System Planner:** design a new system or plan stocking for an existing tank, with checks for stocking, flow, heating and power. **Start tracking this system** then creates the real tank, sump, equipment and livestock.
- **Projects:** group several planned systems to compare them side by side and see combined cost, water and power. Copy a plan to try a variation. Nothing becomes real until you track that one plan.
- **Wishlist:** save animals and gear with a priority, price, link and notes. Each animal is checked against your tank, and you can move items into a plan or mark them bought.

### Equipment, dosing and maintenance
- **Equipment:** service intervals, placement in the display or sump, and pump flow and turnover estimates.
- **Dosing and top-off:** reservoir levels and run-out forecasts.
- **Calculators:** the Dose Estimator, Salt Mixing Calculator and Fill Timer calculator use the selected system's volume, or a custom one.
- **Routines:** manual checklists and automated schedules with flexible repeats, plus water change history.
- **Power cost:** estimated electricity use and cost from equipment wattage. Set your price under **Tools > Settings**.

### Fill timers
Enter your RO/DI specs to estimate fill time and waste water, then start a timer that beeps on the page and can alert your phone.

> A timer only reminds you. **It can't shut off water**, so use a float valve or a timed shut-off on anything that could overflow.

### Phone alerts and webhooks
Under **Tools > Phone Alerts & Webhooks**, send events to your phone through [ntfy](https://ntfy.sh), or to Home Assistant or your own devices. See [Webhooks](#-webhooks).

### Backups
Under **Tools > Backups**, make a zip of your database and photos, download it, or restore one. Your current data is saved first when you restore. Automatic backups run weekly by default.

Backups are stored in `data/backups` on the same drive as your data, so copy one somewhere else now and then.

### Webcams
Add MJPEG, snapshot or embedded camera feeds, and assign each to a system or show it on all of them. **Time-lapse** captures frames on a schedule and plays them back in the browser. RTSP cameras need a converter such as [go2rtc](https://github.com/AlexxIT/go2rtc), and an example is commented out in `docker-compose.yml`.

> ⚠️ **Handle with care.** Some nudibranchs steal stinging cells from the prey they eat and use them for defence. This one is no different: touch it three times and it stings. Mostly your wallet.

<details>
<summary>🤫 Spoiler: where it stings</summary>

<br>

Touch the nudibranch (the app icon) three times quickly, and it stings you with **The Damage**, a fire-themed spending ledger. It's off until you **Light the match** inside it. After that:

- Livestock and equipment get a "what you paid" field, which lands in the ledger automatically and stays in sync with it.
- Planner and Wishlist prices are always visible, and only reach the ledger when an item moves into an active tank.
- Filter by system and dates, and watch a chart of your running total, with money under a line of flames.
- **Put out the fire** to hide your spending again. Your $ values aren't erased.

</details>

---

## 🔗 Webhooks

A connection receives events as they happen, from a background worker that starts with the app.

| Event | When it fires |
|---|---|
| `parameter.critical` | A reading reaches a critical limit |
| `parameter.out_of_range` | A reading leaves the optimal range |
| `parameter.stale` | A probe stops reporting (set the hours per parameter) |
| `reservoir.low` | A reservoir is running low |
| `routine.due` | A manual routine comes due |
| `routine.scheduled` | An automated schedule event's time arrives, such as a feeder |
| `equipment.service_due` | Equipment needs service |
| `animal.attention` | An animal is flagged sick or in quarantine |
| `quarantine.complete` | A quarantine period ends |
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
- Most events notify once, when the condition first happens, and failed sends retry up to 5 times.
- `routine.scheduled` is sent once and never retried, and a missed one is dropped after 5 minutes, so a retry can't double-feed.
- The first time the worker runs, it records existing problems without sending them.

**Using webhooks with hardware:**
- **Target one device:** edit the connection and tick only that routine or reservoir. With no event types ticked, it receives only events about those targets, so a feeder webhook can't fire on a parameter alert.
- **Keep the feeder's own schedule as the main one.** If this PC or Docker is off, nothing is sent.
- **Limit it on the device too:** ignore repeated event IDs, and give anything that doses or feeds its own daily limit.
- **Home Assistant:** use `http://YOUR-HA-IP:8123/api/webhook/YOUR-ID`. Names like `homeassistant.local` may not work from inside Docker.

---

## 🧪 Parameter Units & Decimal Precision

You can change measurement units and customize decimal places for any parameter:
- Click the **gear icon** ⚙️ on any parameter card (or **"Unit Settings"** on the Parameters page).
- **Customizable Decimals**: Choose from `0` to `4` decimal places:
  - `0` decimals for whole-number metrics (e.g. `Calcium 420 ppm`, `Magnesium 1350 ppm`).
  - `1` decimal for tenths (e.g. `Alkalinity 8.4 dKH`, `Temperature 78.2 °F`).
  - `2` decimals for hundredths (e.g. `Phosphate 0.03 ppm`, `pH 8.25`).
  - `3` decimals for thousandths (e.g. `Salinity 1.026 SG`).
- **Automatic Historical Conversion**:
  - Checking **"Convert previous entries automatically"** recalculates all existing logs and ideal ranges using standard reef conversion formulas:
    - **Temperature**: `°F` $\leftrightarrow$ `°C`
    - **Salinity**: `SG` (Specific Gravity) $\leftrightarrow$ `ppt` (Parts per Thousand) $\leftrightarrow$ `mS/cm` (Conductivity)
    - **Alkalinity**: `dKH` $\leftrightarrow$ `meq/L` $\leftrightarrow$ `ppm CaCO3`
    - **Phosphate**: `ppm PO4` $\leftrightarrow$ `ppb Phosphorus P` (for Hanna HI736 Checkers)
    - **Nutrients**: `ppm` $\leftrightarrow$ `ppb`

---

## 📡 Parameter Logging REST API

You can log parameter readings programmatically via HTTP POST requests from automated test kits, Raspberry Pi/ESP32 probes, Python scripts, or Home Assistant.

### 1. View Available Parameter Types
```http
GET /api/parameters/types/
```
Add `?tank=<ID or name>` to get that system's target ranges.

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

Readings can name a system with `"tank"` (ID or name), on each reading or once for a whole batch. Without it, they go to your primary tank.

### 2. Log a Single Parameter
```http
POST /api/parameters/log/
Content-Type: application/json
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
*(Note: `parameter` matches case-insensitively by code, name, or ID. `measured_at` and `notes` are optional; defaults to current time).*

**cURL Example:**
```bash
curl -X POST http://localhost:8000/api/parameters/log/ \
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
      "value": 8.4,
      "unit": "dKH",
      "status": "optimal",
      "measured_at": "2026-11-04T22:30:00+00:00",
      "notes": "Automated log"
    }
  ]
}
```

---

### 3. Log Multiple Parameters (Batch)
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
  -H "Content-Type: application/json" \
  -d '{
    "readings": [
      {"parameter": "temperature", "value": 78.4},
      {"parameter": "ph", "value": 8.22}
    ]
  }'
```

---

### 4. Python Integration Example
```python
import requests

SERVER_URL = "http://192.168.1.150:8000"  # or http://localhost:8000

data = {
    "readings": [
        {"parameter": "temp", "value": 78.1, "notes": "DS18B20 probe"},
        {"parameter": "ph", "value": 8.18, "notes": "Atlas probe"}
    ]
}

response = requests.post(f"{SERVER_URL}/api/parameters/log/", json=data)
print(response.status_code, response.json())
```

---

### Optional API Security Key
To protect the API from unauthorized callers, create a `.env` file beside `docker-compose.yml`, then restart the app:
```bash
API_SECRET_KEY=my-super-secret-reef-token
```
Then pass the key in your requests:
```bash
curl -H "X-API-Key: my-super-secret-reef-token" ...
# or
curl -H "Authorization: Bearer my-super-secret-reef-token" ...
```
*(Without `API_SECRET_KEY`, the API accepts readings from anyone who can reach it).*

---

## 🧑‍💻 Development

Run the tests against a temporary data folder, so your real data isn't touched:

```bash
docker compose run --rm --no-deps -e DATA_DIR=/tmp/testdata --entrypoint python web manage.py test aquarium
```

- `aquarium/`: the Django app. Views for the newer tools are in `views_tools.py`, and background jobs are in `management/commands/run_worker.py`.
- `aquarium/species_catalog.csv`: the built-in species list.
- `static/icons/nudibranch/`: character icons, as `NN-name-young.png` and `NN-name-old.png` pairs. Add a pair and restart to add a character. Small copies are generated at startup in `thumbs/`.
- [CHANGES.md](CHANGES.md): what changed in each round.
