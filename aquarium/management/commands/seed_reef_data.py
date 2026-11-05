from django.core.management.base import BaseCommand
from aquarium.models import ParameterType, AnimalGroup


class Command(BaseCommand):
    help = "Seeds common reef aquarium parameters and animal groups"

    def handle(self, *args, **options):
        self.stdout.write("Seeding default reef parameters...")

        default_parameters = [
            {"name": "Salinity", "code": "salinity", "unit": "SG", "min_ideal": 1.025, "max_ideal": 1.026, "color": "#0284c7", "display_order": 1},
            {"name": "Alkalinity", "code": "alkalinity", "unit": "dKH", "min_ideal": 8.0, "max_ideal": 9.0, "color": "#06b6d4", "display_order": 2},
            {"name": "Calcium", "code": "calcium", "unit": "ppm", "min_ideal": 420.0, "max_ideal": 450.0, "color": "#3b82f6", "display_order": 3},
            {"name": "Magnesium", "code": "magnesium", "unit": "ppm", "min_ideal": 1300.0, "max_ideal": 1400.0, "color": "#8b5cf6", "display_order": 4},
            {"name": "Nitrate", "code": "nitrate", "unit": "ppm", "min_ideal": 2.0, "max_ideal": 15.0, "color": "#f97316", "display_order": 5},
            {"name": "Phosphate", "code": "phosphate", "unit": "ppm", "min_ideal": 0.03, "max_ideal": 0.10, "color": "#eab308", "display_order": 6},
            {"name": "Temperature", "code": "temperature", "unit": "°F", "min_ideal": 77.0, "max_ideal": 79.0, "color": "#ef4444", "display_order": 7},
            {"name": "pH", "code": "ph", "unit": "pH", "min_ideal": 8.0, "max_ideal": 8.4, "color": "#10b981", "display_order": 8},
        ]

        for p in default_parameters:
            obj, created = ParameterType.objects.get_or_create(
                code=p["code"],
                defaults=p
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  + Created parameter: {obj.name}"))
            else:
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

        self.stdout.write(self.style.SUCCESS("Seeding complete!"))
