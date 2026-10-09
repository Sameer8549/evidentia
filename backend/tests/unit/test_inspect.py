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
    
    from app.analyze import PageAnalysisSchema
    mock_analyze.return_value = PageAnalysisSchema(
        document_type="Notice",
        dates_and_deadlines=[
            {
                "fact_description": "18 October 2026",
                "candidate_quotation": "18 October 2026",
                "is_missing_or_unknown": False
            }
        ]
    )
    
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

@pytest.mark.asyncio
async def test_verify_receipt_valid(async_client: AsyncClient, tmp_path: Path):
    receipt_path = tmp_path / "receipt.json"
    source_path = tmp_path / "source.bin"
    
    # Just mock verify.py success by patching subprocess.run inside inspect.py
    with patch("app.inspect.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "[PASS] Evidence receipt is valid."
        
        with open(receipt_path, "wb") as f: f.write(b"{}")
        with open(source_path, "wb") as f: f.write(b"data")
        
        with open(receipt_path, "rb") as rf, open(source_path, "rb") as sf:
            files = {
                "receipt_file": ("receipt.json", rf, "application/json"),
                "source_file": ("source.bin", sf, "application/octet-stream")
            }
            response = await async_client.post("/api/verify", files=files)
            
        assert response.status_code == 200
        assert response.json()["verified"] is True

@pytest.mark.asyncio
async def test_verify_receipt_oversized(async_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_upload_mb", 1) # 1 MB limit
    # We can use a custom UploadFile or just create a payload that is > 1MB
    class DummyUpload:
        async def read(self, size=-1):
            if not hasattr(self, 'read_bytes'): self.read_bytes = 0
            if self.read_bytes >= 2 * 1024 * 1024: return b""
            chunk = b"0" * 8192
            self.read_bytes += len(chunk)
            return chunk
            
    with patch("app.inspect.UploadFile.read", side_effect=DummyUpload().read):
        # We simulate the size limit being exceeded during read
        # Using the actual endpoint
        pass
        
    # Since streaming limits are best tested with actual large requests:
    large_data = b"0" * (1024 * 1024 + 1024) # 1MB + 1KB
    files = {
        "receipt_file": ("receipt.json", large_data, "application/json"),
        "source_file": ("source.bin", b"small", "application/octet-stream")
    }
    response = await async_client.post("/api/verify", files=files)
    assert response.status_code == 413
    
    files = {
        "receipt_file": ("receipt.json", b"small", "application/json"),
        "source_file": ("source.bin", large_data, "application/octet-stream")
    }
    response = await async_client.post("/api/verify", files=files)
    assert response.status_code == 413
