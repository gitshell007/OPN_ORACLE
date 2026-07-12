"""Single Flask-aware Celery application factory."""

from __future__ import annotations

from typing import Any

from celery import Celery, Task
from flask import Flask
from kombu import Queue

QUEUES = ("default", "signals", "ai", "documents", "notifications", "maintenance")
TASK_ROUTES = {
    "oracle.signal.*": {"queue": "signals"},
    "oracle.memory.*": {"queue": "ai"},
    "oracle.dossier_summary.*": {"queue": "ai"},
    "oracle.ai.*": {"queue": "ai"},
    "oracle.report.*": {"queue": "ai"},
    "oracle.export.*": {"queue": "documents"},
    "oracle.document.*": {"queue": "documents"},
    "notifications.*": {"queue": "notifications"},
    "maintenance.*": {"queue": "maintenance"},
}


def celery_init_app(app: Flask) -> Celery:
    existing = app.extensions.get("celery")
    if isinstance(existing, Celery):
        return existing

    class FlaskTask(Task):  # type: ignore[misc]
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery = Celery(app.import_name, task_cls=FlaskTask)
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_always_eager=app.config["CELERY_TASK_ALWAYS_EAGER"],
        task_eager_propagates=app.config["CELERY_TASK_EAGER_PROPAGATES"],
        task_acks_late=app.config["CELERY_ACKS_LATE"],
        worker_prefetch_multiplier=app.config["CELERY_WORKER_PREFETCH_MULTIPLIER"],
        task_soft_time_limit=app.config["CELERY_TASK_SOFT_TIME_LIMIT"],
        task_time_limit=app.config["CELERY_TASK_TIME_LIMIT"],
        result_expires=app.config["CELERY_RESULT_EXPIRES"],
        task_default_queue=app.config["CELERY_DEFAULT_QUEUE"],
        task_queues=tuple(Queue(name) for name in QUEUES),
        task_routes=TASK_ROUTES,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            "dispatch-due-jobs": {
                "task": "maintenance.dispatch_due_jobs",
                "schedule": 60.0,
                "options": {"queue": "maintenance"},
            },
            "dispatch-queued-jobs": {
                "task": "maintenance.dispatch_queued_jobs",
                "schedule": 30.0,
                "options": {"queue": "maintenance"},
            },
            "cleanup-tokens": {
                "task": "maintenance.cleanup_tokens",
                "schedule": 3600.0,
                "options": {"queue": "maintenance"},
            },
            "expire-sessions": {
                "task": "maintenance.expire_sessions",
                "schedule": 900.0,
                "options": {"queue": "maintenance"},
            },
            "recover-stale-jobs": {
                "task": "maintenance.recover_stale_jobs",
                "schedule": 300.0,
                "options": {"queue": "maintenance"},
            },
            "documents-retention": {
                "task": "maintenance.documents_retention",
                "schedule": 3600.0,
                "options": {"queue": "maintenance"},
            },
            "reconcile-signal-outbox": {
                "task": "maintenance.signal_reconcile_outbox",
                "schedule": 30.0,
                "options": {"queue": "maintenance"},
            },
            "reconcile-signal-inbox": {
                "task": "maintenance.signal_reconcile_inbox",
                "schedule": 30.0,
                "options": {"queue": "maintenance"},
            },
            "schedule-alert-evaluations": {
                "task": "maintenance.schedule_alert_evaluations",
                "schedule": 300.0,
                "options": {"queue": "maintenance"},
            },
        },
    )
    celery.set_default()
    celery.autodiscover_tasks(
        ["opn_oracle.jobs", "opn_oracle.integrations", "opn_oracle.documents"], force=True
    )
    app.extensions["celery"] = celery
    return celery


def create_celery_app() -> Celery:
    from opn_oracle.app import create_app

    return celery_init_app(create_app())
