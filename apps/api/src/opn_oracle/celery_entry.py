"""Importable worker/beat entrypoint: ``celery -A opn_oracle.celery_entry:celery``."""

from opn_oracle.celery_app import create_celery_app

celery = create_celery_app()
