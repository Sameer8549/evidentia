import json
import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List

from app.config import settings


class JobState(BaseModel):
    job_id: str
    ingestion_id: str
    stage: str = "queued"
    status: str = "running"
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat() + "Z"
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat() + "Z"
    )
    progress: int = 0
    total_pages: int = 0
    pages_processed: int = 0
    errors: List[str] = []
    receipt_available: bool = False


def get_job_path(ingestion_id: str) -> Path:
    return Path(settings.evidentia_data_dir) / ingestion_id / "job.json"


def init_job(ingestion_id: str) -> JobState:
    job = JobState(job_id=f"job-{ingestion_id}", ingestion_id=ingestion_id)
    save_job(job)
    return job


def load_job(ingestion_id: str) -> Optional[JobState]:
    job_path = get_job_path(ingestion_id)
    if not job_path.exists():
        return None
    try:
        with open(job_path, "r", encoding="utf-8") as f:
            return JobState(**json.load(f))
    except Exception:
        return None


def save_job(job: JobState):
    job.updated_at = datetime.datetime.now(datetime.UTC).isoformat() + "Z"
    job_path = get_job_path(job.ingestion_id)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job.model_dump(), f, indent=2)


def update_job_stage(
    ingestion_id: str,
    stage: str,
    status: str = "running",
    error: str = None,
    receipt_available: bool = False,
):
    job = load_job(ingestion_id)
    if not job:
        job = init_job(ingestion_id)
    job.stage = stage
    job.status = status
    job.receipt_available = receipt_available or job.receipt_available
    if error:
        job.errors.append(error)
    save_job(job)


def update_job_progress(ingestion_id: str, pages_processed: int, total_pages: int):
    job = load_job(ingestion_id)
    if job:
        job.pages_processed = pages_processed
        job.total_pages = total_pages
        if total_pages > 0:
            job.progress = int((pages_processed / total_pages) * 100)
        save_job(job)
