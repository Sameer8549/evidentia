import os
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from PIL import Image

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

def create_mock_tesseract_data(has_text=True):
    if not has_text:
        return {
            'level': [1, 2, 3, 4, 5],
            'page_num': [1, 1, 1, 1, 1],
            'block_num': [0, 1, 1, 1, 1],
            'par_num': [0, 0, 1, 1, 1],
            'line_num': [0, 0, 0, 1, 1],
            'word_num': [0, 0, 0, 0, 1],
            'left': [0, 0, 0, 0, 0],
            'top': [0, 0, 0, 0, 0],
            'width': [100, 100, 100, 100, 0],
            'height': [100, 100, 100, 100, 0],
            'conf': ['-1', '-1', '-1', '-1', '-1'],
            'text': ['', '', '', '', '  ']
        }
    
    return {
        'level': [5, 5, 5, 5],
        'page_num': [1, 1, 1, 1],
        'block_num': [1, 1, 1, 2],
        'par_num': [1, 1, 1, 1],
        'line_num': [1, 1, 2, 1],
        'word_num': [1, 2, 1, 1],
        'left': [10, 50, 10, 10],
        'top': [10, 10, 30, 80],
        'width': [30, 40, 30, 50],
        'height': [10, 10, 10, 10],
        'conf': ['95.5', '90.0', '85.5', '99.9'],
        'text': ['Hello', 'World', 'NextLine', 'NewBlock']
    }

@pytest.mark.asyncio
@patch('pytesseract.image_to_data')
@patch('pytesseract.get_tesseract_version')
async def test_ocr_mocked_pdf(mock_version, mock_image_to_data, async_client: AsyncClient, tmp_path: Path):
    mock_version.return_value = "5.0.0"
    mock_image_to_data.return_value = create_mock_tesseract_data()
    
    ingestion_id = "test-pdf-123"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    # Create fake page images
    img = Image.new("RGB", (100, 100), color="white")
    img.save(ingestion_dir / "page_0.png")
    img.save(ingestion_dir / "page_1.png")
    
    response = await async_client.post(f"/api/ocr/{ingestion_id}")
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    assert len(data["pages"]) == 2
    
    page = data["pages"][0]
    assert page["page_index"] == 0
    assert page["width"] == 100
    
    # Test reconstruction logic
    expected_text = "Hello World\nNextLine\n\nNewBlock"
    assert page["text"] == expected_text
    
    words = page["words"]
    assert len(words) == 4
    
    assert words[0]["text"] == "Hello"
    assert words[0]["char_start"] == 0
    assert words[0]["char_end"] == 5
    
    assert words[1]["text"] == "World"
    assert words[1]["char_start"] == 6
    assert words[1]["char_end"] == 11
    
    assert words[2]["text"] == "NextLine"
    assert words[2]["char_start"] == 12
    assert words[2]["char_end"] == 20
    
    assert words[3]["text"] == "NewBlock"
    assert words[3]["char_start"] == 22
    assert words[3]["char_end"] == 30
    
    # Verify exact substring match!
    for word in words:
        assert page["text"][word["char_start"]:word["char_end"]] == word["text"]

@pytest.mark.asyncio
@patch('pytesseract.image_to_data')
@patch('pytesseract.get_tesseract_version')
async def test_ocr_mocked_image(mock_version, mock_image_to_data, async_client: AsyncClient, tmp_path: Path):
    mock_version.return_value = "5.0.0"
    mock_image_to_data.return_value = create_mock_tesseract_data()
    
    ingestion_id = "test-img-456"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    # Create original image, no page_ files
    img = Image.new("RGB", (200, 200), color="white")
    img.save(ingestion_dir / "original", format="PNG")
    
    response = await async_client.post(f"/api/ocr/{ingestion_id}")
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["pages"]) == 1
    page = data["pages"][0]
    assert page["width"] == 200
    assert len(page["words"]) == 4

@pytest.mark.asyncio
@patch('pytesseract.image_to_data')
@patch('pytesseract.get_tesseract_version')
async def test_ocr_blank_page(mock_version, mock_image_to_data, async_client: AsyncClient, tmp_path: Path):
    mock_version.return_value = "5.0.0"
    mock_image_to_data.return_value = create_mock_tesseract_data(has_text=False)
    
    ingestion_id = "test-blank-789"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    img = Image.new("RGB", (100, 100), color="white")
    img.save(ingestion_dir / "page_0.png")
    
    response = await async_client.post(f"/api/ocr/{ingestion_id}")
    assert response.status_code == 200
    data = response.json()
    
    page = data["pages"][0]
    assert page["text"] == ""
    assert len(page["words"]) == 0
    assert "No text detected on page." in page["warnings"]

@pytest.mark.asyncio
@patch('pytesseract.get_tesseract_version')
async def test_ocr_missing_tesseract(mock_version, async_client: AsyncClient, tmp_path: Path):
    mock_version.side_effect = Exception("Not found")
    
    ingestion_id = "test-missing-tess"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    response = await async_client.post(f"/api/ocr/{ingestion_id}")
    assert response.status_code == 503
    assert "not available" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_ocr_unknown_ingestion_id(async_client: AsyncClient):
    response = await async_client.post("/api/ocr/fake-id-123")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_ocr_path_traversal(async_client: AsyncClient):
    response = await async_client.post("/api/ocr/..%2f..%2fetc%2fpasswd")
    assert response.status_code in [404, 400] # Depends on how router and relative_to parses it, but shouldn't be 500 or 200

import pytesseract
@pytest.mark.asyncio
async def test_ocr_integration(async_client: AsyncClient, tmp_path: Path):
    # This test will only fully execute if tesseract is actually installed
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        pytest.skip("Tesseract is not available in environment. Skipping integration test.")
        
    ingestion_id = "test-real-123"
    ingestion_dir = Path(settings.evidentia_data_dir) / ingestion_id
    ingestion_dir.mkdir(parents=True)
    
    # Needs a real image with text to reliably detect something
    # But since tesseract isn't available, it'll just skip.
    img = Image.new("RGB", (500, 100), color="white")
    # Draw some text if possible, but keeping it simple
    img.save(ingestion_dir / "page_0.png")
    
    response = await async_client.post(f"/api/ocr/{ingestion_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["pages"]) == 1
