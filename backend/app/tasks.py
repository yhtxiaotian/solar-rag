from app.celery_app import celery_app
from app.services.ingest import process_document


@celery_app.task(name="documents.ingest", autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3)
def ingest_document(document_id: str) -> None:
    process_document(document_id)

