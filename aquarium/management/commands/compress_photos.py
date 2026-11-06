from pathlib import Path

from django.core.management.base import BaseCommand

from aquarium.images import compressed_jpeg
from aquarium.models import Animal, AnimalPhoto


class Command(BaseCommand):
    help = ("Compresses photos uploaded before photos were compressed automatically. New photos don't need this. "
            "A photo is only replaced if the new file is smaller.")

    def handle(self, *args, **options):
        saved = changed = 0
        for model, field in ((Animal, 'photo'), (AnimalPhoto, 'image')):
            for record in model.objects.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}):
                image = getattr(record, field)
                old_path = Path(image.path)
                if not old_path.exists():
                    continue
                before = old_path.stat().st_size
                with open(old_path, 'rb') as source:
                    smaller = compressed_jpeg(source, old_path.name)
                if smaller is None or smaller.size >= before:
                    continue
                old_name = image.name
                image.save(smaller.name, smaller, save=False)
                model.objects.filter(pk=record.pk).update(**{field: image.name})
                image.storage.delete(old_name)
                saved += before - smaller.size
                changed += 1
        self.stdout.write(f"Compressed {changed} photo{'' if changed == 1 else 's'}, saving {saved / (1024 * 1024):.1f} MB.")
