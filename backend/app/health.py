from fastapi import APIRouter
from app.ollama_client import OllamaClient
import shutil

router = APIRouter()

@router.get("/health/live")
def get_live():
    return {"status": "ok"}
    
@router.get("/health/ready")
async def get_ready():
    # check tesseract
    tesseract_available = shutil.which("tesseract") is not None
    
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
