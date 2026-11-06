from django.core.management.base import BaseCommand

from aquarium.models import Tank, Sump, SumpChamber, Equipment


class Command(BaseCommand):
    help = ("Adds example tank dimensions, a sump with refugium chambers and pump flow ratings "
            "to the sample tank created by seed_reef_data. Safe to re-run; never overwrites your edits.")

    def handle(self, *args, **options):
        tank = Tank.objects.filter(is_primary=True).first() or Tank.objects.first()
        if not tank:
            self.stdout.write(self.style.WARNING("No tank found. Run `seed_reef_data` first."))
            return

        # Dimensions only when none have been entered, and never touch a manually entered capacity.
        if not tank.has_dimensions and not tank.capacity_is_manual:
            tank.width, tank.depth, tank.height = 36, 24, 20
            tank.dimension_unit = 'in'
            tank.save()
            self.stdout.write(self.style.SUCCESS(f"  + Added example dimensions to {tank.name}"))

        sump, created = Sump.objects.get_or_create(
            tank=tank, name="Main Sump",
            defaults={'volume_gallons': 20, 'notes': "Example sump: split into chambers"},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  + Created sump: {sump.name}"))

        if not sump.chambers.exists():
            chambers = [
                ("Filter sock", 'inflow', 15),
                ("Skimmer", 'skimmer', 25),
                ("Refugium", 'refugium', 35),
                ("Bubble trap", 'bubble_trap', 5),
                ("Return", 'return', 20),
            ]
            for i, (name, kind, share) in enumerate(chambers, start=1):
                SumpChamber.objects.create(sump=sump, position=i, name=name, chamber_type=kind, share_percent=share)
            self.stdout.write(self.style.SUCCESS("  + Added 5 example chambers"))

        # Rated flows (gph) for the sample pumps, only where nothing is set yet.
        rated = {"Vectra M2 Return Pump": (2100, 30), "VorTech MP40wQD": (4000, 0)}
        for name, (max_gph, derate) in rated.items():
            eq = Equipment.objects.filter(tank=tank, name=name).first()
            if eq and not eq.max_flow_gph:
                eq.max_flow_gph = max_gph
                eq.flow_derate_percent = derate
                eq.save()
                self.stdout.write(self.style.SUCCESS(f"  + Set rated flow for {name}"))

        self.stdout.write(self.style.SUCCESS("Example system data ready."))
