import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from aquarium.models import (
    ParameterType, AnimalGroup, SpeciesCatalog,
    Tank, Equipment, DosingReservoir, MaintenanceRoutine
)


# Editable in a spreadsheet: save as "CSV UTF-8" so the emoji icons survive.
SPECIES_CSV = Path(__file__).resolve().parents[2] / "species_catalog.csv"
SPECIES_FIELDS = ("name", "species", "category", "suggested_group", "care_level", "reef_safe", "diet", "notes", "icon")
SPECIES_EXTRAS = ("min_tank_gallons", "max_size_inches", "temperament")


class Command(BaseCommand):
    help = "Seeds common reef aquarium parameters, animal groups, and species catalog"

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-species", action="store_true",
            help="Also overwrite existing catalog entries with the values in species_catalog.csv",
        )

    def _seed_species(self, update_existing=False):
        """Add species from the CSV. A bad row is skipped so it can't stop the rest of the seed."""
        valid_categories = {key for key, _ in SpeciesCatalog.CATEGORY_CHOICES}
        added = updated = skipped = 0
        try:
            with open(SPECIES_CSV, encoding="utf-8-sig", newline="") as fh:
                for line, row in enumerate(csv.DictReader(fh), start=2):
                    values = {field: (row.get(field) or "").strip() for field in SPECIES_FIELDS}
                    if not values["name"] or values["category"] not in valid_categories:
                        self.stderr.write(f"  ! Skipped {SPECIES_CSV.name} line {line}: missing name or bad category")
                        skipped += 1
                        continue
                    extras = {field: (row.get(field) or "").strip() or None for field in SPECIES_EXTRAS}
                    extras["temperament"] = extras["temperament"] or ""
                    name = values.pop("name")
                    obj, created = SpeciesCatalog.objects.get_or_create(name=name, defaults={**values, **extras})
                    if created:
                        added += 1
                    elif update_existing:
                        SpeciesCatalog.objects.filter(pk=obj.pk).update(**values, **extras)
                        updated += 1
                    else:
                        # Older entries predate these columns: fill the gaps, never overwrite.
                        gaps = {field: value for field, value in extras.items()
                                if value not in (None, "") and getattr(obj, field) in (None, "")}
                        if gaps:
                            SpeciesCatalog.objects.filter(pk=obj.pk).update(**gaps)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            self.stderr.write(f"  ! Could not read {SPECIES_CSV.name}: {exc}")
            return
        total = SpeciesCatalog.objects.count()
        self.stdout.write(f"  Species catalog: {added} added, {updated} updated, {skipped} skipped, {total} total")

    def handle(self, *args, **options):
        self.stdout.write("Seeding default reef parameters...")

        default_parameters = [
            {"name": "Salinity", "code": "salinity", "unit": "SG", "decimal_places": 3, "low_limit": 1.023, "min_ideal": 1.025, "max_ideal": 1.026, "high_limit": 1.028, "color": "#0284c7", "display_order": 1},
            {"name": "Alkalinity", "code": "alkalinity", "unit": "dKH", "decimal_places": 1, "low_limit": 7.0, "min_ideal": 8.0, "max_ideal": 9.0, "high_limit": 11.0, "color": "#06b6d4", "display_order": 2},
            {"name": "Calcium", "code": "calcium", "unit": "ppm", "decimal_places": 0, "low_limit": 380.0, "min_ideal": 420.0, "max_ideal": 450.0, "high_limit": 480.0, "color": "#3b82f6", "display_order": 3},
            {"name": "Magnesium", "code": "magnesium", "unit": "ppm", "decimal_places": 0, "low_limit": 1250.0, "min_ideal": 1300.0, "max_ideal": 1400.0, "high_limit": 1450.0, "color": "#8b5cf6", "display_order": 4},
            {"name": "Nitrate", "code": "nitrate", "unit": "ppm", "decimal_places": 1, "low_limit": 0.5, "min_ideal": 2.0, "max_ideal": 15.0, "high_limit": 25.0, "color": "#f97316", "display_order": 5},
            {"name": "Phosphate", "code": "phosphate", "unit": "ppm", "decimal_places": 2, "low_limit": 0.01, "min_ideal": 0.03, "max_ideal": 0.10, "high_limit": 0.2, "color": "#eab308", "display_order": 6},
            {"name": "Temperature", "code": "temperature", "unit": "°F", "decimal_places": 1, "low_limit": 75.0, "min_ideal": 77.0, "max_ideal": 79.0, "high_limit": 81.0, "color": "#ef4444", "display_order": 7},
            {"name": "pH", "code": "ph", "unit": "pH", "decimal_places": 2, "low_limit": 7.8, "min_ideal": 8.0, "max_ideal": 8.4, "high_limit": 8.5, "color": "#10b981", "display_order": 8},
        ]

        for p in default_parameters:
            obj, created = ParameterType.objects.get_or_create(
                code=p["code"],
                defaults=p
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  + Created parameter: {obj.name}"))
            else:
                # Update decimal_places if needed
                if obj.decimal_places != p["decimal_places"]:
                    obj.decimal_places = p["decimal_places"]
                    obj.save(update_fields=['decimal_places'])
                self.stdout.write(f"  - Parameter already exists: {obj.name}")

        self.stdout.write("Seeding default animal groups...")
        default_groups = [
            {"name": "Cleanup Crew", "icon": "🐌", "color": "#10b981", "description": "Snails, hermits, and sand-sifters"},
            {"name": "School", "icon": "🐟", "color": "#38bdf8", "description": "Fish that swim together as a group"},
            {"name": "Clownfish Pair", "icon": "🐠", "color": "#fb923c", "description": "Mated or bonded clownfish pair"},
            {"name": "Corals", "icon": "🪸", "color": "#ec4899", "description": "SPS, LPS, and soft corals"},
            {"name": "Invertebrates", "icon": "🦐", "color": "#a855f7", "description": "Shrimp, crabs, starfish, and urchins"},
        ]

        for g in default_groups:
            obj, created = AnimalGroup.objects.get_or_create(
                name=g["name"],
                defaults=g
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  + Created group: {obj.name}"))
            else:
                self.stdout.write(f"  - Group already exists: {obj.name}")

        self.stdout.write("Seeding popular species catalog...")
        self._seed_species(update_existing=options["update_species"])

        # Sample data is only for a brand new install. Otherwise renaming or deleting the sample tank or
        # gear would bring it back on every restart, creating phantom systems.
        if Tank.objects.exists():
            self.stdout.write("Seeding complete (existing systems left as they are).")
            return

        self.stdout.write("Seeding default display tank...")
        default_tank, created = Tank.objects.get_or_create(
            name="Main Display Tank",
            defaults={"volume_gallons": 60.0, "is_primary": True, "notes": "60g Mixed Reef + 20g Sump"}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  + Created primary tank: {default_tank.name}"))

        self.stdout.write("Seeding default equipment...")
        sample_equipment = [
            {"name": "EcoTech Radion XR30 Pro", "category": "lighting", "brand": "EcoTech Marine", "wattage": 190, "maintenance_interval_days": 180, "status": "operational", "tank": default_tank},
            {"name": "Vectra M2 Return Pump", "category": "return_pump", "brand": "EcoTech Marine", "wattage": 80, "maintenance_interval_days": 90, "status": "operational", "tank": default_tank},
            {"name": "Reef Octopus Classic 150INT", "category": "skimmer", "brand": "Reef Octopus", "wattage": 18, "maintenance_interval_days": 60, "status": "operational", "tank": default_tank},
            {"name": "VorTech MP40wQD", "category": "wavemaker", "brand": "EcoTech Marine", "wattage": 38, "maintenance_interval_days": 90, "status": "operational", "tank": default_tank},
            {"name": "Helio Titanium Heater 300W", "category": "heater", "brand": "Innovative Marine", "wattage": 300, "maintenance_interval_days": 180, "status": "operational", "tank": default_tank},
            {"name": "Smart ATO Micro", "category": "ato", "brand": "AutoAqua", "wattage": 10, "maintenance_interval_days": 90, "status": "operational", "tank": default_tank},
        ]
        for eq in sample_equipment:
            _, eq_created = Equipment.objects.get_or_create(
                name=eq["name"],
                tank=default_tank,
                defaults=eq
            )
            if eq_created:
                self.stdout.write(self.style.SUCCESS(f"  + Added equipment: {eq['name']}"))

        self.stdout.write("Seeding default dosing & ATO reservoirs...")
        sample_reservoirs = [
            {"name": "Alkalinity (Soda Ash)", "reservoir_type": "dosing_additive", "capacity": 2000.0, "current_level": 1450.0, "unit": "ml", "daily_consumption": 25.0, "color": "#06b6d4", "tank": default_tank},
            {"name": "Calcium Chloride", "reservoir_type": "dosing_additive", "capacity": 2000.0, "current_level": 1500.0, "unit": "ml", "daily_consumption": 25.0, "color": "#3b82f6", "tank": default_tank},
            {"name": "All-For-Reef (CarboCalcium)", "reservoir_type": "dosing_additive", "capacity": 1000.0, "current_level": 820.0, "unit": "ml", "daily_consumption": 12.0, "color": "#a855f7", "tank": default_tank},
            {"name": "RO/DI Auto Top-Off (ATO)", "reservoir_type": "ato_freshwater", "capacity": 10.0, "current_level": 6.5, "unit": "gal", "daily_consumption": 0.8, "color": "#0ea5e9", "tank": default_tank},
        ]
        for res in sample_reservoirs:
            _, res_created = DosingReservoir.objects.get_or_create(
                name=res["name"],
                tank=default_tank,
                defaults=res
            )
            if res_created:
                self.stdout.write(self.style.SUCCESS(f"  + Added reservoir: {res['name']}"))

        self.stdout.write("Seeding default maintenance routines...")
        sample_routines = [
            {
                "title": "Weekly Water Change & Sump Siphon",
                "category": "water_change",
                "repeat_every": 1, "repeat_unit": "week",
                "tank": default_tank,
                "checklist_items": [
                    "Heat and aerate new saltwater (check salinity with refractometer)",
                    "Turn off return pump and skimmer (feed mode)",
                    "Scrape glass / acrylic and blow detritus off rocks with turkey baster",
                    "Siphon 10 gallons from sandbed and sump bottom",
                    "Pump new heated saltwater into display tank or sump",
                    "Turn return pump back on and verify water level in return chamber",
                    "Empty and clean skimmer collection cup",
                    "Top off ATO freshwater reservoir with RO/DI water",
                ],
                "notes": "Perform every weekend for nutrient export and trace element replenishment."
            },
            {
                "title": "Weekly Parameter Testing Routine",
                "category": "testing",
                "repeat_every": 1, "repeat_unit": "week",
                "tank": default_tank,
                "checklist_items": [
                    "Clean test vials with RO/DI water",
                    "Test Alkalinity (dKH) - Hanna Checker or Salifert",
                    "Test Calcium (ppm)",
                    "Test Magnesium (ppm)",
                    "Test Nitrate (NO3) - High Sensitivity",
                    "Test Phosphate (PO4) - Ultra Low Range",
                    "Log values into Nudibranch app",
                    "Adjust dosing pump schedule if alk or ca drifted",
                ],
                "notes": "Test at approximately the same time of day (photoperiod mid-point) for consistent alk readings."
            },
            {
                "title": "Monthly Pump & Equipment Vinegar Bath",
                "category": "equipment",
                "repeat_every": 1, "repeat_unit": "month",
                "tank": default_tank,
                "checklist_items": [
                    "Remove wavemaker powerheads from display",
                    "Soak wet-side impellers in 50/50 citric acid / warm water bath for 1 hour",
                    "Brush off calcium carbonate deposits and coralline algae",
                    "Inspect impeller shaft and ceramic bushings for wear",
                    "Rinse thoroughly in RO/DI water and reinstall",
                    "Check heater controller temperature probe calibration",
                ],
                "notes": "Prevents calcification freeze-ups and preserves silent motor performance."
            }
        ]
        for rt in sample_routines:
            _, rt_created = MaintenanceRoutine.objects.get_or_create(
                title=rt["title"],
                tank=default_tank,
                defaults=rt
            )
            if rt_created:
                self.stdout.write(self.style.SUCCESS(f"  + Added routine: {rt['title']}"))

        self.stdout.write(self.style.SUCCESS("Seeding complete!"))
