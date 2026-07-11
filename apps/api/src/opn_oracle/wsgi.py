"""Gunicorn entrypoint: opn_oracle.wsgi:app."""

from opn_oracle.app import create_app

app = create_app()
