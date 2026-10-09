import pytest
from httpx import AsyncClient
from PIL import Image, ImageDraw
import json
import subprocess
from pathlib import Path

from app.config import settings

@pytest.mark.asyncio
async def test_full_workflow_e2e(async_client: AsyncClient):
    import shutil
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract not available for E2E test.")
        
    # Check Ollama
    try:
        from app.ollama_client import OllamaClient
        client = OllamaClient()
        await client.check_health()
    except Exception:
        pytest.skip("Ollama not available for E2E test.")
        
    # 1. Create a synthetic image
    ingestion_dir = Path(settings.evidentia_data_dir) / "test_e2e_source"
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    img_path = ingestion_dir / "e2e_notice.png"
    
    img = Image.new("RGB", (1200, 800), color="white")
    d = ImageDraw.Draw(img)
    d.text((10,10), "COMMUNITY NOTICE", fill=(0,0,0))
    d.text((10,50), "Application deadline: 18 October 2026", fill=(0,0,0))
    d.text((10,100), "Required document: ID proof", fill=(0,0,0))
    img.save(img_path)
    
    # 2. Ingest
    with open(img_path, "rb") as f:
        files = {"file": ("e2e_notice.png", f, "image/png")}
        response = await async_client.post("/api/ingest", files=files)
        
    assert response.status_code == 200
    ingestion_data = response.json()
    ingestion_id = ingestion_data["ingestion_id"]
    
    # 3. Inspect (this runs OCR + Analyze + Match + Checks + Resources + Receipt)
    response = await async_client.post(f"/api/inspect/{ingestion_id}?fetch_resources=true")
    assert response.status_code == 200
    receipt_data = response.json()
    
    assert receipt_data["metadata"]["ingestion_id"] == ingestion_id
    assert receipt_data["global_status"] == "COMPLETED"
    
    # 4. Verify standalone
    receipt_path = Path(settings.evidentia_data_dir) / ingestion_id / "receipt.json"
    assert receipt_path.exists()
    
    result = subprocess.run([
        "python", "verify.py", str(receipt_path), "--source", str(img_path)
    ], capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "[PASS]" in result.stdout
