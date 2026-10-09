import subprocess

from fastapi import APIRouter

from app.config import settings
from app.ollama_client import OllamaClient

router = APIRouter()


@router.get("/health/live")
def get_live():
    """Liveness: the API process is running."""
    return {"status": "ok"}


@router.get("/health/ready")
async def get_ready():
    """Readiness: report the actual availability of configured local dependencies."""
    tesseract_available = False
    tesseract_error = None
    try:
        result = subprocess.run(
            [settings.evidentia_tesseract_cmd, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and any(
            line.strip() == "eng" for line in result.stdout.splitlines()
        ):
            tesseract_available = True
        else:
            tesseract_error = (
                result.stderr.strip()
                or "Tesseract did not report the required English language data."
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        tesseract_error = str(exc)

    client = OllamaClient()
    try:
        await client.check_health()
        ollama_available = True
        ollama_error = None
    except Exception as exc:
        ollama_available = False
        ollama_error = str(exc)

    ready = tesseract_available and ollama_available
    return {
        "status": "ok" if ready else "degraded",
        "tesseract": tesseract_available,
        "tesseract_error": tesseract_error,
        "ollama": ollama_available,
        "ollama_error": ollama_error,
    }


@router.get("/api/capabilities")
def get_capabilities():
    return {
        "features": [
            "ingestion",
            "ocr",
            "multimodal_analysis",
            "evidence_matching",
            "deterministic_checks",
            "receipt_generation",
            "offline_receipt_verification",
            "inspection_job_status",
        ]
    }
