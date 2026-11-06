"""Backup and restore of the SQLite database and uploaded media as a single zip file."""
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from .models import AppSettings

DB_MEMBER = 'nudibranch.sqlite3'
NAME_RE = re.compile(r'^nudibranch-(manual|auto|pre-restore)-\d{8}-\d{6}\.zip$')


class BackupError(Exception):
    """A backup file couldn't be used. The message is safe to show the user."""


def backup_dir():
    path = Path(settings.DATA_DIR) / 'backups'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dump_database(target):
    """Consistent copy of the live database (safe while the app is running)."""
    connection.ensure_connection()
    dest = sqlite3.connect(str(target))
    try:
        connection.connection.backup(dest)
    finally:
        dest.close()


def create_backup(kind='manual', include_timelapse=True):
    """Writes a new backup zip and returns its path."""
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    final = backup_dir() / f"nudibranch-{kind}-{stamp}.zip"
    media_root = Path(settings.MEDIA_ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / DB_MEMBER
        _dump_database(db_copy)
        partial = final.with_suffix('.partial')
        try:
            with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(db_copy, DB_MEMBER)
                archive.writestr('manifest.json', json.dumps({
                    'app': 'nudibranch', 'created_at': timezone.now().isoformat(), 'kind': kind,
                }))
                if media_root.is_dir():
                    for path in sorted(media_root.rglob('*')):
                        if not path.is_file():
                            continue
                        rel = path.relative_to(media_root).as_posix()
                        if not include_timelapse and rel.startswith('timelapse/'):
                            continue
                        # Photos are already compressed, so store them as they are.
                        archive.write(path, f"media/{rel}", compress_type=zipfile.ZIP_STORED)
            partial.replace(final)
        finally:
            partial.unlink(missing_ok=True)
    return final


def list_backups():
    items = []
    for path in backup_dir().glob('nudibranch-*.zip'):
        match = NAME_RE.match(path.name)
        if not match:
            continue
        stat = path.stat()
        items.append({
            'name': path.name,
            'kind': match.group(1),
            'size_mb': round(stat.st_size / (1024 * 1024), 1),
            'created': datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
        })
    items.sort(key=lambda b: b['created'], reverse=True)
    return items


def resolve_backup(name):
    """Path for a backup chosen by name. Only exact backup file names in the backup folder are accepted."""
    if not NAME_RE.match(name or ''):
        raise BackupError("That isn't a valid backup name.")
    path = backup_dir() / name
    if not path.is_file():
        raise BackupError("That backup no longer exists.")
    return path


def prune_auto_backups(keep):
    autos = [b for b in list_backups() if b['kind'] == 'auto']
    for old in autos[max(0, keep):]:
        (backup_dir() / old['name']).unlink(missing_ok=True)


def run_auto_backup(now=None):
    """Makes a scheduled backup if one is due. Returns the new path, or None."""
    now = now or timezone.now()
    settings_obj = AppSettings.load()
    if not settings_obj.auto_backup_days:
        return None
    last = settings_obj.last_auto_backup
    if last and (now - last).days < settings_obj.auto_backup_days:
        return None
    path = create_backup('auto')
    AppSettings.objects.filter(pk=settings_obj.pk).update(last_auto_backup=now)
    prune_auto_backups(settings_obj.auto_backup_keep)
    return path


def _safe_media_target(member, media_root):
    """Where a zip member should extract to, or None if its path tries to escape the media folder."""
    rel = member[len('media/'):]
    if not rel or rel.endswith('/'):
        return None
    target = (media_root / rel).resolve()
    return target if target.is_relative_to(media_root) else None


def validate_backup(path, workdir):
    """Checks the zip really is a good Nudibranch backup and extracts its database to workdir."""
    try:
        with zipfile.ZipFile(path) as archive:
            if DB_MEMBER not in archive.namelist():
                raise BackupError("This zip doesn't contain a Nudibranch database.")
            extracted = Path(workdir) / DB_MEMBER
            with archive.open(DB_MEMBER) as src, open(extracted, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as exc:
        raise BackupError("That file isn't a valid zip.") from exc

    db = sqlite3.connect(str(extracted))
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise BackupError("The database in this backup is damaged.")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise BackupError("The database in this backup can't be read.") from exc
    finally:
        db.close()
    if 'aquarium_tank' not in tables:
        raise BackupError("This doesn't look like a Nudibranch database.")
    return extracted


def restore_backup(path):
    """
    Replaces the live data with a backup. A safety backup is taken first, and media files in the
    backup are added to or overwrite existing ones (nothing else is removed from the media folder).
    Returns the name of the safety backup.
    """
    media_root = Path(settings.MEDIA_ROOT).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        extracted = validate_backup(path, tmp)
        safety = create_backup('pre-restore')

        connection.ensure_connection()
        src = sqlite3.connect(str(extracted))
        try:
            src.backup(connection.connection)
        finally:
            src.close()

        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not member.startswith('media/'):
                    continue
                target = _safe_media_target(member, media_root)
                if target is None:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target, 'wb') as out:
                    shutil.copyfileobj(source, out)

    # A backup from an older version may need newer tables.
    call_command('migrate', interactive=False, verbosity=0)
    # Alerts that were active in the backup aren't news, so don't re-send them.
    AppSettings.objects.update_or_create(pk=1, defaults={'events_baselined': False})
    return safety.name
