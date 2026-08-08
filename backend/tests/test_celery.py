from app.celery_app import celery_app


def test_ingest_task_is_registered() -> None:
    celery_app.loader.import_default_modules()

    assert "documents.ingest" in celery_app.tasks
