#!/bin/sh
set -e

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Preparing icons..."
python manage.py build_icon_thumbnails || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Auto-seed standard saltwater parameters if database is fresh
python manage.py seed_reef_data || true

# Background jobs (alerts, webhooks, timers, time-lapse, backups) run beside the web server.
# Restarted automatically if they ever stop. One-off commands like "docker compose run" skip this.
if [ "$1" = "gunicorn" ]; then
    echo "Starting background worker..."
    ( while true; do python manage.py run_worker || true; sleep 10; done ) &
fi

echo "Starting server..."
exec "$@"
