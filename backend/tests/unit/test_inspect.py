import pytest
from httpx import AsyncClient
from unittest.mock import patch
from pathlib import Path
from PIL import Image, ImageDraw
import json

from app.config import settings
import app.inspect

@pytest.mark.asyncio
async def test_inspect_not_found(async_client: AsyncClient):
    response = await async_client.post("/api/inspect/fake-id")
    assert response.status_code == 404

@pytest.mark.asyncio
@patch('app.inspect.perform_ocr')
@patch('app.inspect.OllamaClient.check_health')
@patch('app.inspect.OllamaClient.analyze_document_page')
async def test_inspect_success(mock_analyze, mock_health, mock_ocr, async_client: AsyncClient):
    mock_health.return_value = True
    mock_ocr.return_value = []
    
    mock_analyze.return_value = {
        "document_type": "Notice",
        "dates_and_deadlines": [
            {
                "fact_description": "18 October 2026",
                "candidate_quotation": "18 October 2026"
            }
        ]
    }
    
    ingestion_id = "test-inspect-123"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True, exist_ok=True)
    
    with open(ingestion_dir / "metadata.json", "w") as f:
        json.dump({
            "sha256": "testhash",
            "original_filename": "test.pdf",
            "content_type": "application/pdf"
        }, f)
        
    img = Image.new("RGB", (100, 100), color="white")
    img.save(ingestion_dir / "page_0.png")
    
    response = await async_client.post(f"/api/inspect/{ingestion_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["schema_version"] == "1.0.0"
    assert data["metadata"]["source_sha256"] == "testhash"
    assert data["global_status"] == "COMPLETED"
    
    # Receipt file should exist
    assert (ingestion_dir / "receipt.json").exists()
