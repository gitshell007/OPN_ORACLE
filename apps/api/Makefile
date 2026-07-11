.PHONY: install lock lint format typecheck test test-coverage test-integration migrate migration run openapi gunicorn

install:
	uv sync --frozen

lock:
	uv lock

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy src

test:
	uv run pytest -m "not integration" --no-cov

test-coverage:
	uv run pytest

test-integration:
	uv run pytest -m integration --no-cov

migrate:
	uv run flask --app opn_oracle.wsgi:app db upgrade

migration:
	uv run flask --app opn_oracle.wsgi:app db migrate

run:
	uv run flask --app opn_oracle.wsgi:app run --debug --port 8000

openapi:
	APP_ENV=test uv run flask --app opn_oracle.wsgi:app export-openapi ../../docs/api/openapi.json

gunicorn:
	uv run gunicorn -c gunicorn.conf.py opn_oracle.wsgi:app
