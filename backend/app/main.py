from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

app = FastAPI(
    title="Evidentia", description="Make AI show its evidence.", version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.evidentia_cors_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
)

from app.ingestion import router as ingestion_router  # noqa: E402
from app.ocr import router as ocr_router  # noqa: E402
from app.analyze import router as analyze_router  # noqa: E402
from app.inspect import router as inspect_router  # noqa: E402
from app.health import router as health_router  # noqa: E402


@app.get("/")
def read_root():
    return {"name": "evidentia-backend", "version": "0.1.0"}


app.include_router(health_router)
app.include_router(ingestion_router, prefix="/api")
app.include_router(ocr_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(inspect_router)
