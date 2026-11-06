# 🪸 Nudibranch — Reef Aquarium Tracker

A mobile-first, containerized web application designed for saltwater aquarium hobbyists to track water chemistry, monitor livestock, and view live tank webcams.

Built with **Python**, **Django 5**, **SQLite (WAL Mode)**, **Tailwind CSS**, **HTMX**, and **Chart.js**, packaged as an installable **Progressive Web App (PWA)**.

---

## 🚀 Running with Docker Compose

To apply code updates and run the application:
```powershell
docker-compose up -d --build
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser or phone.

---

## 🧰 Tools

Find these under the **Planner** and **Tools** tabs. On a phone, open **System** and scroll the tabs at the top.

- **System Planner**: plan a new system or stocking for an existing tank, check it, then start tracking it.
- **Fill Timers & RO Calculator**: estimate fill time from your RO specs and get a reminder. Timers can't shut off water.
- **Phone Alerts & Webhooks**: send events to your phone (via ntfy), Home Assistant or your own devices.
- **Backups**: save and restore your database and photos. Copy backups off this PC now and then.
- **Quarantine Tracker**, **Power Cost**, plus a **Timeline** on each animal and a **Time-lapse** on each camera.

The app has no login, so anyone who can reach it can see and change everything, including downloading backups. Keep it on your home network and don't expose port 8000 to the internet.

### Webhook payload
```json
{
  "id": "unique-id-use-this-to-ignore-repeats",
  "type": "routine.scheduled",
  "severity": "info",
  "title": "Feeder: Feed",
  "message": "Scheduled for 08:00.",
  "occurred_at": "2026-11-05T14:00:00+00:00",
  "data": {"routine": "Feeder", "action": "Feed", "scheduled_for": "2026-11-05T08:00:00-06:00"}
}
```
Headers: `X-Nudibranch-Event`, `X-Nudibranch-Delivery`, and `X-Nudibranch-Signature: sha256=...` when a secret is set.

Keep any feeder's own schedule as the main one. If this PC or Docker is off, nothing is sent.

To point a webhook at one device, edit the connection and tick only that routine or reservoir. With no event types ticked, it then receives only events about those targets. Routine events include `routine_id` in `data`, and timer events include `timer_id` and `reservoir_id`.

---

## 🐠 In-App Creature & Coral Tracking (GUI)

You no longer need to use the Django Admin to manage your tank inhabitants:
- Navigate to the **Livestock** tab in the app.
- Click **"Browse Common Species"** to explore the built-in saltwater species catalog.
- Click **"Add Custom"** to add an unlisted specimen with your own photo and details.
- Features:
  - **240+ Built-in Reef Species**: Pre-populated with popular fish, cleanup crew, invertebrates, corals, and anemones. Edit the list in `aquarium/species_catalog.csv`.
  - **1-Click Quick Add**: Pick a species and quantity (e.g. `5x` Trochus Snails or `1x` Royal Gramma) to add it immediately with recommended groups, diet notes, and care level.
  - **Form Autofill**: When manually adding or editing, select any common species from the dropdown to automatically prefill scientific names, care level, diet, and group tags.
  - **Photo Upload**: Supports photos taken directly from your phone camera or desktop file picker.
  - **In-App Editing & Deletion**: Update notes, change health status (Healthy, Quarantine, Sick), or remove creatures with confirmation.

---

## 📖 Common Species Catalog

The app includes a searchable, curated library of popular saltwater aquarium inhabitants. Examples:
- **🐠 Fish**: Ocellaris & Percula Clowns, Blue-Green Chromis (School), Yellow Tang, Blue Hippo Tang, Royal Gramma, Firefish Goby, Yellow Watchman Goby, Diamond Sand-Sifter, Lawnmower Blenny, Tailspot Blenny, Six-Line Wrasse, Banggai Cardinal, etc.
- **🐌 Cleanup Crew**: Trochus Snail, Nassarius Snail, Astraea Snail, Cerith Snail, Mexican Turbo, Blue Leg Hermit, Scarlet Reef Hermit, Emerald Crab, Peppermint Shrimp.
- **🦐 Invertebrates & Shrimp**: Skunk Cleaner Shrimp, Blood Red Fire Shrimp, Tiger Pistol Shrimp, Bubble Tip Anemone (BTA), Tuxedo Urchin.
- **🪸 Corals**: Green Star Polyps (GSP), Zoanthids & Palys, Duncan, Hammer, Torch, Frogspawn, Candy Cane, Montipora Cap, Toadstool Leather.

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
If you want to protect the API from unauthorized external callers, set the `API_SECRET_KEY` environment variable in your `docker-compose.yml`:
```yaml
    environment:
      - API_SECRET_KEY=my-super-secret-reef-token
```
Then pass the key in your requests:
```bash
curl -H "X-API-Key: my-super-secret-reef-token" ...
# or
curl -H "Authorization: Bearer my-super-secret-reef-token" ...
```
*(If `API_SECRET_KEY` is omitted, the API allows local network requests without a key).*
