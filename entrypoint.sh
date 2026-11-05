#!/bin/sh
set -e

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Auto-seed standard saltwater parameters if database is fresh
python manage.py seed_reef_data || true

echo "Starting server..."
exec "$@"
