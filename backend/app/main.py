from fastapi import FastAPI
from app.config import settings

app = FastAPI(
    title="Evidentia",
    description="Make AI show its evidence.",
    version="0.1.0"
)

from app.ingestion import router as ingestion_router
from app.ocr import router as ocr_router
from app.analyze import router as analyze_router
from app.inspect import router as inspect_router
from app.health import router as health_router

@app.get("/")
def read_root():
    return {"name": "evidentia-backend", "version": "0.1.0"}

app.include_router(health_router)
app.include_router(ingestion_router, prefix="/api")
app.include_router(ocr_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(inspect_router)
