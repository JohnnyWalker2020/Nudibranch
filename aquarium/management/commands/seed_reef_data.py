from django.core.management.base import BaseCommand
from aquarium.models import (
    ParameterType, AnimalGroup, SpeciesCatalog,
    Tank, Equipment, DosingReservoir, MaintenanceRoutine
)


class Command(BaseCommand):
    help = "Seeds common reef aquarium parameters, animal groups, and species catalog"

    def handle(self, *args, **options):
        self.stdout.write("Seeding default reef parameters...")

        default_parameters = [
            {"name": "Salinity", "code": "salinity", "unit": "SG", "decimal_places": 3, "min_ideal": 1.025, "max_ideal": 1.026, "color": "#0284c7", "display_order": 1},
            {"name": "Alkalinity", "code": "alkalinity", "unit": "dKH", "decimal_places": 1, "min_ideal": 8.0, "max_ideal": 9.0, "color": "#06b6d4", "display_order": 2},
            {"name": "Calcium", "code": "calcium", "unit": "ppm", "decimal_places": 0, "min_ideal": 420.0, "max_ideal": 450.0, "color": "#3b82f6", "display_order": 3},
            {"name": "Magnesium", "code": "magnesium", "unit": "ppm", "decimal_places": 0, "min_ideal": 1300.0, "max_ideal": 1400.0, "color": "#8b5cf6", "display_order": 4},
            {"name": "Nitrate", "code": "nitrate", "unit": "ppm", "decimal_places": 1, "min_ideal": 2.0, "max_ideal": 15.0, "color": "#f97316", "display_order": 5},
            {"name": "Phosphate", "code": "phosphate", "unit": "ppm", "decimal_places": 2, "min_ideal": 0.03, "max_ideal": 0.10, "color": "#eab308", "display_order": 6},
            {"name": "Temperature", "code": "temperature", "unit": "°F", "decimal_places": 1, "min_ideal": 77.0, "max_ideal": 79.0, "color": "#ef4444", "display_order": 7},
            {"name": "pH", "code": "ph", "unit": "pH", "decimal_places": 2, "min_ideal": 8.0, "max_ideal": 8.4, "color": "#10b981", "display_order": 8},
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
        default_species = [
            # Fish
            {
                "name": "Ocellaris Clownfish", "species": "Amphiprion ocellaris", "category": "fish",
                "suggested_group": "Clownfish Pair", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Omnivore (pellets, flakes, mysis)", "notes": "Hardy and iconic. Pairs easily with another clown; can host anemones.", "icon": "🐠"
            },
            {
                "name": "Percula Clownfish", "species": "Amphiprion percula", "category": "fish",
                "suggested_group": "Clownfish Pair", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Omnivore", "notes": "True Percula clownfish with prominent black outlines. Peaceful reef inhabitant.", "icon": "🐠"
            },
            {
                "name": "Blue Green Chromis", "species": "Chromis viridis", "category": "fish",
                "suggested_group": "School", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Planktivore / Omnivore", "notes": "Active schooling damselfish. Shimmers bright metallic aqua. Keep in odd-numbered groups.", "icon": "🐟"
            },
            {
                "name": "Yellow Tang", "species": "Zebrasoma flavescens", "category": "fish",
                "suggested_group": "Fish", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Herbivore (nori seaweed, algae pellets)", "notes": "Classic reef centerpiece. Voracious grazer on filamentous algae.", "icon": "🐠"
            },
            {
                "name": "Blue / Hippo Tang", "species": "Paracanthurus hepatus", "category": "fish",
                "suggested_group": "Fish", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Omnivore / Herbivore", "notes": "Active swimmer, needs ample horizontal swimming space. Prone to ich if stressed.", "icon": "🐠"
            },
            {
                "name": "Royal Gramma", "species": "Gramma loreto", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Carnivore (mysis, brine, pods)", "notes": "Stunning violet-and-yellow coloration. Caves and rock crevices are essential.", "icon": "🐠"
            },
            {
                "name": "Firefish Goby", "species": "Nemateleotris magnifica", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Planktivore / Carnivore", "notes": "Peaceful dartfish with high dorsal fin. Known jumper—requires a tight tank lid.", "icon": "🐟"
            },
            {
                "name": "Yellow Watchman Goby", "species": "Cryptocentrus cinctus", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Carnivore", "notes": "Bottom dweller with charismatic grumpy face. Forms a famous symbiotic bond with pistol shrimp.", "icon": "🐠"
            },
            {
                "name": "Diamond Watchman Goby", "species": "Valenciennea puellaris", "category": "fish",
                "suggested_group": "Fish", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Carnivore / Sand Sifter", "notes": "Master sand-sifter. Continuously filters sand bed through gills, keeping sand spotless.", "icon": "🐟"
            },
            {
                "name": "Lawnmower Blenny", "species": "Salarias fasciatus", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Herbivore", "notes": "Excellent natural grazer for nuisance hair algae and microalgae films.", "icon": "🐟"
            },
            {
                "name": "Tailspot Blenny", "species": "Ecsenius stigmatura", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Herbivore / Omnivore", "notes": "Small, comical nano fish. Perches on rocks and pecks at microalgae.", "icon": "🐟"
            },
            {
                "name": "Six Line Wrasse", "species": "Pseudocheilinus hexataenia", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Carnivore / Pest Eater", "notes": "Active hunter that eats nuisance flatworms, bristleworms, and pyramid snails.", "icon": "🐠"
            },
            {
                "name": "Banggai Cardinalfish", "species": "Pterapogon kauderni", "category": "fish",
                "suggested_group": "Fish", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Carnivore", "notes": "Gentle, slow-moving fish with striking black and silver stripes. Mouthbrooder.", "icon": "🐠"
            },
            # Cleanup Crew
            {
                "name": "Trochus Snail", "species": "Trochus sp.", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Herbivore (film & hair algae)", "notes": "Top-tier algae snail. Can upright itself if flipped upside down.", "icon": "🐌"
            },
            {
                "name": "Nassarius Snail", "species": "Nassarius vibex", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Carnivore / Detritivore", "notes": "Burrows under the sand bed, emerges like a zombie when fish are fed to clean leftover food.", "icon": "🐌"
            },
            {
                "name": "Astraea Snail", "species": "Astraea tecta", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Herbivore (diatoms, green film)", "notes": "Classic glass and live-rock grazer with pyramid shell. Cannot flip itself if overturned.", "icon": "🐌"
            },
            {
                "name": "Cerith Snail", "species": "Cerithium sp.", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Detritivore / Herbivore", "notes": "Cleans glass, rock crevices, and burrows into sand bed eating detritus and diatoms.", "icon": "🐌"
            },
            {
                "name": "Mexican Turbo Snail", "species": "Turbo fluctuosa", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Voracious Herbivore", "notes": "Bulldozer snail that demolishes thick green hair algae.", "icon": "🐌"
            },
            {
                "name": "Blue Leg Hermit Crab", "species": "Clibanarius tricolor", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Omnivore / Scavenger", "notes": "Miniature scavenger. Scours rock holes for detritus and nuisance algae. Provide empty shells.", "icon": "🦀"
            },
            {
                "name": "Scarlet Reef Hermit Crab", "species": "Paguristes cadenati", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Herbivore / Scavenger", "notes": "The most peaceful hermit crab. Bright red legs with yellow eye stalks.", "icon": "🦀"
            },
            {
                "name": "Emerald Crab", "species": "Mithraculus sculptus", "category": "cleanup_crew",
                "suggested_group": "Cleanup Crew", "care_level": "Beginner", "reef_safe": "With Caution",
                "diet": "Herbivore (bubble algae)", "notes": "Famous for controlling nuisance Valonia (bubble algae).", "icon": "🦀"
            },
            # Invertebrates & Shrimp
            {
                "name": "Skunk Cleaner Shrimp", "species": "Lysmata amboinensis", "category": "invert",
                "suggested_group": "Invertebrates", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Omnivore / Cleaner", "notes": "Bold and friendly. Sets up cleaning stations where fish queue to have parasites removed.", "icon": "🦐"
            },
            {
                "name": "Blood Red Fire Shrimp", "species": "Lysmata debelius", "category": "invert",
                "suggested_group": "Invertebrates", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Omnivore", "notes": "Deep crimson red with striking white antennae and legs. Shy scavenger.", "icon": "🦐"
            },
            {
                "name": "Tiger Pistol Shrimp", "species": "Alpheus bellulus", "category": "invert",
                "suggested_group": "Invertebrates", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Carnivore", "notes": "Excavates elaborate underground burrows shared with watchman gobies.", "icon": "🦐"
            },
            {
                "name": "Bubble Tip Anemone (BTA)", "species": "Entacmaea quadricolor", "category": "invert",
                "suggested_group": "Invertebrates", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Photosynthetic / Meaty foods", "notes": "Natural host for clownfish. Requires stable mature water parameters and good lighting.", "icon": "🪸"
            },
            {
                "name": "Tuxedo Urchin", "species": "Mespilia globulus", "category": "invert",
                "suggested_group": "Invertebrates", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Herbivore", "notes": "Voracious algae grazer that covers itself with small debris and shells for camouflage.", "icon": "🦔"
            },
            # Corals
            {
                "name": "Green Star Polyps (GSP)", "species": "Pachyclavularia violacea", "category": "coral",
                "suggested_group": "Corals", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Extremely hardy neon green mat. Keep on an isolated rock island to prevent spreading over rockwork.", "icon": "🪸"
            },
            {
                "name": "Zoanthids & Palys", "species": "Zoanthus sp.", "category": "coral",
                "suggested_group": "Corals", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Vibrant button polyps in endless color morphs. Note: Handle with care due to palytoxin.", "icon": "🪸"
            },
            {
                "name": "Duncan Coral", "species": "Duncanopsammia axifuga", "category": "coral",
                "suggested_group": "Corals", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Photosynthetic / Target feeder", "notes": "Hardy LPS coral with large green fleshy polyps. Spawns new heads rapidly.", "icon": "🪸"
            },
            {
                "name": "Hammer Coral", "species": "Euphyllia ancora", "category": "coral",
                "suggested_group": "Corals", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Waving tentacles with hammer-shaped tips. Moderate light and gentle oscillating flow.", "icon": "🪸"
            },
            {
                "name": "Torch Coral", "species": "Euphyllia glabrescens", "category": "coral",
                "suggested_group": "Corals", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Prized long waving tentacles with glowing tips. Keep space between it and other non-Euphyllia.", "icon": "🪸"
            },
            {
                "name": "Frogspawn Coral", "species": "Euphyllia divisa", "category": "coral",
                "suggested_group": "Corals", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Multilobed tentacles resembling frog eggs. Hardy and stunning under blue actinics.", "icon": "🪸"
            },
            {
                "name": "Candy Cane Coral", "species": "Caulastraea furcata", "category": "coral",
                "suggested_group": "Corals", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Hardy trumpet-shaped LPS coral. Extends feeder tentacles at night.", "icon": "🪸"
            },
            {
                "name": "Montipora Cap", "species": "Montipora capricornis", "category": "coral",
                "suggested_group": "Corals", "care_level": "Moderate", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "The best beginner SPS coral. Forms stunning swirling plates under good lighting.", "icon": "🪸"
            },
            {
                "name": "Toadstool Leather Coral", "species": "Sarcophyton sp.", "category": "coral",
                "suggested_group": "Corals", "care_level": "Beginner", "reef_safe": "Yes",
                "diet": "Photosynthetic", "notes": "Hardy mushroom-shaped soft coral with long flowing polyp tentacles.", "icon": "🪸"
            },
        ]

        for s in default_species:
            obj, created = SpeciesCatalog.objects.get_or_create(
                name=s["name"],
                defaults=s
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  + Added species to catalog: {obj.name}"))
            else:
                self.stdout.write(f"  - Species already in catalog: {obj.name}")

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
                "frequency_days": 7,
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
                "frequency_days": 7,
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
                "frequency_days": 30,
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
