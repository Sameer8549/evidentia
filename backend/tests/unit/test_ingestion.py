import os
import shutil
import pytest
import fitz
from httpx import AsyncClient
from pathlib import Path
from app.main import settings

@pytest.fixture(autouse=True)
def setup_teardown_data_dir():
    data_dir = Path(settings.evidentia_data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir)

def create_synthetic_pdf(path: str, pages: int = 1):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=100, height=100)
        page.insert_text((10, 10), "Test Document")
    doc.save(path)
    doc.close()

def create_synthetic_png(path: str):
    # Minimal 1x1 PNG transparent
    png_magic = b"\x89PNG\r\n\x1a\n"
    content = b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    with open(path, "wb") as f:
        f.write(png_magic + content)

@pytest.mark.asyncio
async def test_ingest_valid_pdf(async_client: AsyncClient, tmp_path: Path):
    pdf_path = tmp_path / "valid.pdf"
    create_synthetic_pdf(str(pdf_path), pages=2)
    
    with open(pdf_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("valid.pdf", f, "application/pdf")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "valid.pdf"
    assert data["detected_type"] == "application/pdf"
    assert data["page_count"] == 2
    assert len(data["page_dimensions"]) == 2
    assert data["page_dimensions"][0]["width"] == 100
    
    # test SHA256 correctness
    import hashlib
    with open(pdf_path, "rb") as f:
        expected_hash = hashlib.sha256(f.read()).hexdigest()
    assert data["hash"] == expected_hash
    
    # temporary-file cleanup on success check (temp file moved or ingestion dir cleaned up?
    # Actually, ingestion_dir is kept on success. Let's check it's there.
    ingestion_dir = Path(settings.evidentia_data_dir) / data["ingestion_id"]
    assert ingestion_dir.exists()

@pytest.mark.asyncio
async def test_ingest_valid_image(async_client: AsyncClient, tmp_path: Path):
    png_path = tmp_path / "test.png"
    create_synthetic_png(str(png_path))
    
    with open(png_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("test.png", f, "image/png")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["detected_type"] == "image/png"

@pytest.mark.asyncio
async def test_ingest_malformed_file(async_client: AsyncClient, tmp_path: Path):
    # It has correct extension but bad content (starts with PDF magic but is broken)
    bad_pdf = tmp_path / "bad.pdf"
    with open(bad_pdf, "wb") as f:
        f.write(b"%PDF-1.4\n%Bad content...")
        
    with open(bad_pdf, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("bad.pdf", f, "application/pdf")})
        
    assert response.status_code == 422
    assert "Malformed PDF" in response.json()["detail"]

@pytest.mark.asyncio
async def test_ingest_empty_upload(async_client: AsyncClient, tmp_path: Path):
    empty_file = tmp_path / "empty.pdf"
    empty_file.touch()
    
    with open(empty_file, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("empty.pdf", f, "application/pdf")})
        
    assert response.status_code == 415 # Empty won't match any magic bytes

@pytest.mark.asyncio
async def test_ingest_oversized_upload(async_client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_upload_mb", 1) # Set limit to 1MB
    large_pdf = tmp_path / "large.pdf"
    
    with open(large_pdf, "wb") as f:
        f.write(b"%PDF-1.4\n")
        f.write(b"A" * (2 * 1024 * 1024)) # 2MB content
        
    with open(large_pdf, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("large.pdf", f, "application/pdf")})
        
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()
    
    # ensure dir is cleaned up on failure
    # we don't have ingestion_id here easily since it fails, but data_dir should be empty
    data_dir = Path(settings.evidentia_data_dir)
    assert not any(data_dir.iterdir()) # directory should be empty due to cleanup

@pytest.mark.asyncio
async def test_ingest_excess_pdf_pages(async_client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_pages", 3)
    pdf_path = tmp_path / "excess.pdf"
    create_synthetic_pdf(str(pdf_path), pages=4)
    
    with open(pdf_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("excess.pdf", f, "application/pdf")})
        
    assert response.status_code == 413
    assert "pages limit" in response.json()["detail"]
