import os
import shutil
import pytest
import fitz
import hashlib
from PIL import Image
from io import BytesIO
from httpx import AsyncClient
from pathlib import Path
from app.config import settings

@pytest.fixture(autouse=True)
def setup_teardown_data_dir():
    data_dir = Path(settings.evidentia_data_dir)
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    os.makedirs(data_dir, exist_ok=True)
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)

def create_synthetic_pdf(path: str, pages: int = 1, width: int = 100, height: int = 100):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=width, height=height)
        page.insert_text((10, 10), "Test Document")
    doc.save(path)
    doc.close()

def create_synthetic_image(path: str, format: str = "PNG", width: int = 10, height: int = 10):
    img = Image.new("RGB", (width, height), color="red")
    img.save(path, format=format)

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
    
    with open(pdf_path, "rb") as f:
        expected_hash = hashlib.sha256(f.read()).hexdigest()
    assert data["hash"] == expected_hash

@pytest.mark.asyncio
async def test_ingest_valid_jpeg(async_client: AsyncClient, tmp_path: Path):
    jpeg_path = tmp_path / "test.jpeg"
    create_synthetic_image(str(jpeg_path), format="JPEG")
    
    with open(jpeg_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("test.jpeg", f, "image/jpeg")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["detected_type"] == "image/jpeg"
    assert data["page_dimensions"][0]["width"] == 10

@pytest.mark.asyncio
async def test_ingest_valid_webp(async_client: AsyncClient, tmp_path: Path):
    webp_path = tmp_path / "test.webp"
    create_synthetic_image(str(webp_path), format="WEBP")
    
    with open(webp_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("test.webp", f, "image/webp")})
        
    assert response.status_code == 200
    data = response.json()
    assert data["detected_type"] == "image/webp"

@pytest.mark.asyncio
async def test_ingest_corrupt_pdf(async_client: AsyncClient, tmp_path: Path):
    bad_pdf = tmp_path / "bad.pdf"
    with open(bad_pdf, "wb") as f:
        f.write(b"%PDF-1.4\n%Bad content...")
        
    with open(bad_pdf, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("bad.pdf", f, "application/pdf")})
        
    assert response.status_code == 422
    assert "Malformed PDF" in response.json()["detail"]

@pytest.mark.asyncio
async def test_ingest_corrupt_image(async_client: AsyncClient, tmp_path: Path):
    bad_png = tmp_path / "bad.png"
    with open(bad_png, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nBad content...")
        
    with open(bad_png, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("bad.png", f, "image/png")})
        
    assert response.status_code == 422
    assert "image" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_ingest_empty_upload(async_client: AsyncClient, tmp_path: Path):
    empty_file = tmp_path / "empty.pdf"
    empty_file.touch()
    
    with open(empty_file, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("empty.pdf", f, "application/pdf")})
        
    assert response.status_code == 400
    assert "Empty" in response.json()["detail"]

@pytest.mark.asyncio
async def test_ingest_oversized_upload(async_client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_upload_mb", 1)
    large_pdf = tmp_path / "large.pdf"
    
    with open(large_pdf, "wb") as f:
        f.write(b"%PDF-1.4\n")
        f.write(b"A" * (2 * 1024 * 1024))
        
    with open(large_pdf, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("large.pdf", f, "application/pdf")})
        
    assert response.status_code == 413
    data_dir = Path(settings.evidentia_data_dir)
    assert not any(data_dir.iterdir()) # Cleanup verification

@pytest.mark.asyncio
async def test_ingest_excess_pdf_pages(async_client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_pages", 1)
    pdf_path = tmp_path / "excess.pdf"
    create_synthetic_pdf(str(pdf_path), pages=2)
    
    with open(pdf_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("excess.pdf", f, "application/pdf")})
        
    assert response.status_code == 413

@pytest.mark.asyncio
async def test_ingest_oversized_image_dims(async_client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_image_dim", 50)
    png_path = tmp_path / "large_dim.png"
    create_synthetic_image(str(png_path), width=100, height=10)
    
    with open(png_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("large_dim.png", f, "image/png")})
        
    assert response.status_code == 413
    assert "dimensions exceed" in response.json()["detail"]

@pytest.mark.asyncio
async def test_ingest_invalid_pdf_dims(async_client: AsyncClient, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "evidentia_max_image_dim", 50)
    pdf_path = tmp_path / "large_pdf.pdf"
    create_synthetic_pdf(str(pdf_path), width=100, height=10)
    
    with open(pdf_path, "rb") as f:
        response = await async_client.post("/api/ingest", files={"file": ("large_pdf.pdf", f, "application/pdf")})
        
    assert response.status_code == 413
    assert "dimensions exceed" in response.json()["detail"]

@pytest.mark.asyncio
async def test_ingest_path_traversal(async_client: AsyncClient, tmp_path: Path):
    pdf_path = tmp_path / "valid.pdf"
    create_synthetic_pdf(str(pdf_path), pages=1)
    
    with open(pdf_path, "rb") as f:
        # FastAPI handles basename internally if client tries to send ../ but we also test the sanitization
        response = await async_client.post("/api/ingest", files={"file": ("../../../etc/passwd.pdf", f, "application/pdf")})
        
    assert response.status_code == 200
    assert response.json()["filename"] == "passwd.pdf"
