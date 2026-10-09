from fastapi import APIRouter
from app.ollama_client import OllamaClient
import shutil

router = APIRouter()

@router.get("/health/live")
def get_live():
    return {"status": "ok"}
    
@router.get("/health/ready")
async def get_ready():
    import subprocess
    from app.config import settings
    # check tesseract
    tesseract_available = False
    try:
        result = subprocess.run([settings.evidentia_tesseract_cmd, "--list-langs"], capture_output=True, text=True)
        if result.returncode == 0 and "eng" in result.stdout:
            tesseract_available = True
    except Exception:
        pass
    
    # check ollama
    client = OllamaClient()
    try:
        await client.check_health()
        ollama_available = True
        ollama_error = None
    except Exception as e:
        ollama_available = False
        ollama_error = str(e)
        
    status = "ok" if (tesseract_available and ollama_available) else "degraded"
    
    return {
        "status": status,
        "tesseract": tesseract_available,
        "ollama": ollama_available,
        "ollama_error": ollama_error
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
            "receipt_generation"
        ]
    }
